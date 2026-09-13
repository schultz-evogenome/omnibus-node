"""Word manuscripts. pandoc gives the best text and extracts the embedded
media; without it, the document XML is read directly (headings, paragraphs,
images in order of appearance). Captions are the paragraph after an image
that reads as a legend, else the one before."""

from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .. import tools
from .common import Figure, Ingested, caption_match, captions_from_text, pair_captions, paragraphs

# pandoc writes ![alt](path) for a plain image and raw <img src="path"> HTML
# when the image carries a width, which DocX images always do.
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|<img\b[^>]*?\bsrc=\"([^\"]+)\"[^>]*>")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
DC = "{http://purl.org/dc/elements/1.1/}"


def ingest_docx(path: Path) -> Ingested:
    path = Path(path)
    if tools.find("pandoc"):
        return _with_pandoc(path)
    ing = _stdlib(path)
    ing.warnings.append("pandoc is not installed; text came from the document XML directly")
    return ing


def _assign_captions(blocks: list[str], image_positions: list[int], figures: list[Figure]) -> None:
    """``blocks`` are Markdown paragraphs; ``image_positions[i]`` is the block
    index holding figure i. Look after, then before, for a legend."""
    for fig, pos in zip(figures, image_positions):
        for cand in (pos + 1, pos - 1):
            if 0 <= cand < len(blocks):
                m = caption_match(blocks[cand])
                if m:
                    fig.number, fig.caption = m
                    fig.caption_confidence = "high" if cand == pos + 1 else "medium"
                    break


def _with_pandoc(path: Path) -> Ingested:
    tmp = tempfile.TemporaryDirectory(prefix="omnibus-docx-")
    media = Path(tmp.name) / "media"
    warnings: list[str] = []
    exe = tools.find("pandoc")
    r = tools.run([exe, str(path), "-t", "gfm", "--wrap=none", f"--extract-media={media}"], timeout=300)
    md = r.stdout
    blocks = paragraphs(md)
    figures: list[Figure] = []
    positions: list[int] = []
    n = 0
    for i, block in enumerate(blocks):
        for m in _MD_IMAGE_RE.finditer(block):
            n += 1
            ref = m.group(2) or m.group(3) or ""
            src = Path(ref)
            if not src.is_absolute():
                src = Path(tmp.name) / src
            fig = Figure(id=f"fig{n}", caption="", caption_confidence="low")
            if src.exists():
                fig.files.append(src)
            else:
                fig.missing.append(ref)
            figures.append(fig)
            positions.append(i)
    _assign_captions(blocks, positions, figures)
    pair_captions(figures, captions_from_text(md))
    # Replace image links with figure markers so text.md does not point at a temp dir.
    counter = iter(range(1, n + 1))
    md = _MD_IMAGE_RE.sub(lambda m: f"[figure: fig{next(counter)}]", md)
    title = _title_from_core(path) or _first_heading(md)
    return Ingested(format="docx", source=path, text=md, title=title, figures=figures, warnings=warnings, tmp=tmp)


def _first_heading(md: str) -> str | None:
    for line in md.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None


def _title_from_core(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as z:
            if "docProps/core.xml" not in z.namelist():
                return None
            root = ET.fromstring(z.read("docProps/core.xml"))
            el = root.find(DC + "title")
            return el.text.strip() if el is not None and el.text and el.text.strip() else None
    except (zipfile.BadZipFile, ET.ParseError):
        return None


def _stdlib(path: Path) -> Ingested:
    tmp = tempfile.TemporaryDirectory(prefix="omnibus-docx-")
    figures: list[Figure] = []
    blocks: list[str] = []
    positions: list[int] = []
    with zipfile.ZipFile(path) as z:
        rels: dict[str, str] = {}
        if "word/_rels/document.xml.rels" in z.namelist():
            rroot = ET.fromstring(z.read("word/_rels/document.xml.rels"))
            for rel in rroot:
                rels[rel.get("Id", "")] = rel.get("Target", "")
        doc = ET.fromstring(z.read("word/document.xml"))
        n = 0
        for p in doc.iter(W + "p"):
            style_el = p.find(f"{W}pPr/{W}pStyle")
            style = style_el.get(W + "val", "") if style_el is not None else ""
            text = "".join(t.text or "" for t in p.iter(W + "t")).strip()
            blips = [b.get(R + "embed") for b in p.iter(A + "blip")]
            if blips:
                for rid in blips:
                    n += 1
                    target = rels.get(rid or "", "")
                    fig = Figure(id=f"fig{n}", caption="", caption_confidence="low")
                    member = "word/" + target if not target.startswith("word/") else target
                    if member in z.namelist():
                        out = Path(tmp.name) / Path(member).name
                        out.write_bytes(z.read(member))
                        fig.files.append(out)
                    else:
                        fig.missing.append(target or rid or "?")
                    figures.append(fig)
                    positions.append(len(blocks))
                    blocks.append(f"[figure: fig{n}]")
                continue
            if not text:
                continue
            if style.lower().startswith("heading"):
                level = re.sub(r"\D", "", style) or "1"
                blocks.append("#" * min(int(level), 6) + " " + text)
            elif style.lower() == "title":
                blocks.append("# " + text)
            else:
                blocks.append(text)
    _assign_captions(blocks, positions, figures)
    md = "\n\n".join(blocks) + "\n"
    pair_captions(figures, captions_from_text(md))
    title = _title_from_core(path) or _first_heading(md)
    return Ingested(format="docx", source=path, text=md, title=title, figures=figures, tmp=tmp)
