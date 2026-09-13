"""``omnibus-node ingest``: one source file in, three things out.

    sources/<key>/text.md   the text, with front matter saying where it came from
    assets/<key>/           every figure, its caption, a preview, asset.yaml
    references.bib          an entry (created or updated) with who and when

For LaTeX and DocX the source is also rendered to ``library/<key>.pdf`` when
the tools exist, so corpus can ingest the same work.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import bibtex
from ..node import Node
from ..provenance import sha256_file, stamp
from .common import Ingested, materialize, write_text

FORMATS = {
    ".tex": "latex",
    ".docx": "docx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".pdf": "pdf",
}

_GENERIC_STEMS = {"main", "manuscript", "paper", "draft", "document", "untitled", "final", "text"}


def detect_format(path: Path) -> str:
    fmt = FORMATS.get(path.suffix.lower())
    if not fmt:
        raise ValueError(f"unsupported file type {path.suffix!r}; expected one of {', '.join(FORMATS)}")
    return fmt


def read_source(path: Path) -> Ingested:
    fmt = detect_format(path)
    if fmt == "latex":
        from .latex import ingest_latex

        return ingest_latex(path)
    if fmt == "docx":
        from .docx import ingest_docx

        return ingest_docx(path)
    if fmt == "pdf":
        from .pdf import ingest_pdf

        return ingest_pdf(path)
    from .text import ingest_text

    return ingest_text(path)


def default_key(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "", path.stem) or "Work"
    return stem[:1].upper() + stem[1:]


def run_ingest(
    node: Node,
    path: str | Path,
    contributor: str,
    key: str | None = None,
    share: str | None = None,
    status: str | None = None,
    title: str | None = None,
    render: bool = True,
    keep_source: bool = False,
) -> dict:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    derived = key is None
    key = key or default_key(path)
    fmt = detect_format(path)
    warnings: list[str] = []
    if derived and path.stem.lower() in _GENERIC_STEMS:
        warnings.append(f"key {key!r} was derived from a generic filename; pass --key Surname2024")
    st = stamp(contributor)
    ing = read_source(path)
    try:
        if title:
            ing.title = title
        status = status or ("draft" if fmt in ("latex", "docx", "markdown", "text") else "published")
        text_path = write_text(node, key, ing, st, status)
        source_root = path.parent if fmt in ("latex", "markdown") else None
        materialize(node, key, ing.figures, st, source_root, warnings)
        warnings.extend(ing.warnings)

        fields: dict[str, str | None] = {
            "title": ing.title,
            "status": status,
            "contributor": st["contributor"],
            "added": st["added"],
        }
        if share:
            fields["share"] = share
        if ing.extras.get("abstract"):
            fields["abstract"] = ing.extras["abstract"]
        for k in ("doi", "journal", "year"):
            if ing.extras.get(k):
                fields[k] = str(ing.extras[k])

        pdf_dest = node.library / f"{key}.pdf"
        rendered = None
        if fmt == "pdf":
            if not pdf_dest.exists() or sha256_file(pdf_dest) != sha256_file(path):
                from .render import place_pdf

                place_pdf(path, pdf_dest)
            rendered = pdf_dest
        elif render and fmt in ("latex", "docx"):
            try:
                from .render import place_pdf, render_docx, render_latex

                pdf = render_latex(path, ing.extras.get("engine", "pdflatex")) if fmt == "latex" else render_docx(path)
                rendered = place_pdf(pdf, pdf_dest)
            except Exception as exc:  # noqa: BLE001 - rendering is optional
                warnings.append(f"no PDF for corpus: {str(exc).splitlines()[0][:160]}")
        if rendered:
            fields["file"] = rendered.name
            fields["sha256"] = sha256_file(rendered)
        else:
            fields["sourcefile"] = path.name

        if keep_source and fmt in ("latex", "docx", "markdown", "text"):
            kept = _keep_source(node, key, path, fmt)
            fields["sourcefile"] = kept

        existing = node.entry(key)
        if existing is not None:
            # Never overwrite curated metadata with a weaker guess.
            for k in ("title", "abstract", "doi", "journal", "year"):
                if existing.get(k):
                    fields.pop(k, None)
            fields.pop("added", None)
        etype = existing.type if existing is not None else "article"
        node.upsert_entry(key, etype, fields)
        return {
            "key": key,
            "format": fmt,
            "title": ing.title,
            "status": status,
            "text": str(text_path.relative_to(node.root)),
            "figures": len(ing.figures),
            "figures_missing_files": sum(1 for f in ing.figures if f.missing),
            "assets": str((node.assets / key / "asset.yaml").relative_to(node.root)) if ing.figures else None,
            "pdf": str(rendered.relative_to(node.root)) if rendered else None,
            "warnings": warnings,
        }
    finally:
        ing.cleanup()


def _keep_source(node: Node, key: str, path: Path, fmt: str) -> str:
    """Copy the source (and, for LaTeX, every included .tex file) under
    ``sources/<key>/src/``. Served only at tier ``all``."""
    import shutil

    dest = node.sources / key / "src"
    dest.mkdir(parents=True, exist_ok=True)
    files = [path]
    if fmt == "latex":
        from .latex import _INPUT_RE

        for name in _INPUT_RE.findall(path.read_text(encoding="utf-8", errors="replace")):
            cand = path.parent / name.strip()
            if cand.suffix == "":
                cand = cand.with_suffix(".tex")
            if cand.is_file():
                files.append(cand)
    for f in files:
        rel = f.relative_to(path.parent) if f.is_relative_to(path.parent) else Path(f.name)
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest / rel)
    return f"src/{path.name}"


__all__ = ["run_ingest", "read_source", "detect_format", "default_key", "FORMATS", "bibtex"]
