"""Render a manuscript source to PDF so corpus can ingest it: LaTeX through
latexmk, DocX through LibreOffice. Both are optional; the caller reports when
they are missing."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .. import tools


def render_latex(main: Path, engine: str = "pdflatex") -> Path:
    exe = tools.find("latexmk")
    if not exe:
        raise tools.MissingTool("latexmk")
    outdir = Path(tempfile.mkdtemp(prefix="omnibus-latex-"))
    flag = {"xelatex": "-xelatex", "lualatex": "-lualatex"}.get(engine, "-pdf")
    tools.run(
        [exe, flag, "-interaction=nonstopmode", "-halt-on-error", f"-outdir={outdir}", main.name],
        cwd=main.parent,
        timeout=1800,
    )
    pdf = outdir / (main.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(f"latexmk finished but {pdf.name} was not produced")
    return pdf


def render_docx(path: Path) -> Path:
    exe = tools.find("soffice")
    if not exe:
        raise tools.MissingTool("soffice")
    outdir = Path(tempfile.mkdtemp(prefix="omnibus-docx-"))
    tools.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(path)], timeout=600)
    pdf = outdir / (path.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError("LibreOffice finished but produced no PDF")
    return pdf


def place_pdf(pdf: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf, dest)
    return dest
