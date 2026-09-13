"""PDFs, with poppler. Text comes from ``pdftotext``; raster figures from
``pdfimages`` (vector figures cannot be pulled from a PDF this way, and
corpus does the real figure extraction when it builds its bundle).
Legends are paired to images in order, so their confidence is low."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from .. import tools
from .common import Figure, Ingested, captions_from_text, pair_captions

MIN_WIDTH = 400
MIN_HEIGHT = 300


def pdf_info(path: Path) -> dict[str, str]:
    exe = tools.find("pdfinfo")
    if not exe:
        return {}
    try:
        r = tools.run([exe, str(path)], timeout=60)
    except Exception:  # noqa: BLE001
        return {}
    info: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    return info


def pdf_text(path: Path) -> str:
    exe = tools.find("pdftotext")
    if not exe:
        raise tools.MissingTool("pdftotext")
    r = tools.run([exe, "-enc", "UTF-8", "-nopgbrk", str(path), "-"], timeout=300)
    text = r.stdout
    # Reflow: single newlines inside a paragraph become spaces; blank lines stay.
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _image_list(path: Path) -> list[dict]:
    exe = tools.find("pdfimages")
    if not exe:
        return []
    try:
        r = tools.run([exe, "-list", str(path)], timeout=120)
    except Exception:  # noqa: BLE001
        return []
    rows: list[dict] = []
    for line in r.stdout.splitlines()[2:]:
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        try:
            rows.append(
                {"page": int(parts[0]), "num": int(parts[1]), "type": parts[2], "width": int(parts[3]), "height": int(parts[4])}
            )
        except ValueError:
            continue
    return rows


def ingest_pdf(path: Path) -> Ingested:
    path = Path(path)
    warnings: list[str] = []
    text = pdf_text(path)
    info = pdf_info(path)
    title = info.get("Title") or None
    if title and (len(title) < 8 or title.lower().endswith((".doc", ".docx", ".tex", ".pdf"))):
        title = None
    tmp = tempfile.TemporaryDirectory(prefix="omnibus-pdf-")
    figures: list[Figure] = []
    rows = [r for r in _image_list(path) if r["type"] == "image" and r["width"] >= MIN_WIDTH and r["height"] >= MIN_HEIGHT]
    if rows:
        exe = tools.find("pdfimages")
        prefix = Path(tmp.name) / "img"
        try:
            tools.run([exe, "-png", "-p", str(path), str(prefix)], timeout=600)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"pdfimages failed: {str(exc)[:120]}")
            rows = []
        for n, row in enumerate(rows, start=1):
            f = Path(tmp.name) / f"img-{row['page']:03d}-{row['num']:03d}.png"
            fig = Figure(id=f"fig{n}", caption="", caption_confidence="low")
            if f.exists():
                fig.files.append(f)
            else:
                fig.missing.append(f.name)
            figures.append(fig)
    elif not tools.find("pdfimages"):
        warnings.append("pdfimages (poppler) is not installed; no figures were extracted")
    pair_captions(figures, captions_from_text(text))
    extras: dict = {}
    if info.get("Pages"):
        extras["pages"] = int(info["Pages"]) if info["Pages"].isdigit() else info["Pages"]
    if figures:
        warnings.append(
            f"{len(figures)} raster image(s) taken from the PDF; captions were paired by order. "
            "Vector figures are not extractable this way; corpus extracts figures properly at build time."
        )
    return Ingested(format="pdf", source=path, text=text, title=title, figures=figures, extras=extras, warnings=warnings, tmp=tmp)
