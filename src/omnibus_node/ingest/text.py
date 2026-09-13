"""Plain text and Markdown. Markdown front matter supplies the title; images
referenced from Markdown become figures, captioned by their alt text or a
legend paragraph next to them."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .common import Figure, Ingested, caption_match, captions_from_text, pair_captions, paragraphs

_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def split_front_matter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---\n"):
        end = raw.find("\n---\n", 4)
        if end > 0:
            try:
                front = yaml.safe_load(raw[4:end]) or {}
            except yaml.YAMLError:
                front = {}
            if isinstance(front, dict):
                return front, raw[end + 5 :]
    return {}, raw


def ingest_text(path: Path) -> Ingested:
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    is_md = path.suffix.lower() in (".md", ".markdown")
    front, body = split_front_matter(raw) if is_md else ({}, raw)
    figures: list[Figure] = []
    warnings: list[str] = []
    if is_md:
        blocks = paragraphs(body)
        positions: list[int] = []
        n = 0
        for i, block in enumerate(blocks):
            for m in _MD_IMAGE_RE.finditer(block):
                n += 1
                alt, ref = m.group(1).strip(), m.group(2)
                fig = Figure(id=f"fig{n}", caption=alt, caption_confidence="medium" if alt else "low")
                src = path.parent / ref
                if src.is_file():
                    fig.files.append(src)
                else:
                    fig.missing.append(ref)
                figures.append(fig)
                positions.append(i)
        for fig, pos in zip(figures, positions):
            for cand in (pos + 1, pos - 1):
                if 0 <= cand < len(blocks):
                    cm = caption_match(blocks[cand])
                    if cm:
                        fig.number, fig.caption = cm
                        fig.caption_confidence = "high"
                        break
        pair_captions(figures, captions_from_text(body))
        counter = iter(range(1, n + 1))
        body = _MD_IMAGE_RE.sub(lambda m: f"[figure: fig{next(counter)}]", body)
        title = front.get("title")
        if not title:
            for line in body.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        for miss in [m for f in figures for m in f.missing]:
            warnings.append(f"image not found: {miss}")
    else:
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        title = first if 0 < len(first) <= 200 else None
    extras = {k: v for k, v in front.items() if k in ("abstract", "authors", "journal", "doi", "year")}
    return Ingested(
        format="markdown" if is_md else "text",
        source=path,
        text=body,
        title=title,
        figures=figures,
        extras=extras,
        warnings=warnings,
    )
