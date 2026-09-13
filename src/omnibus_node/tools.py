"""External programs the node can use, and what each one is for.

None of them is required to install the package. ``omnibus-node check``
reports which are present; each ingester says what it can and cannot do
without them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# name -> (candidate executables, what it is used for)
TOOLS: dict[str, tuple[list[str], str]] = {
    "pandoc": (["pandoc"], "LaTeX and DocX to Markdown text; DocX media extraction"),
    "pdftotext": (["pdftotext"], "text from PDFs (poppler)"),
    "pdfimages": (["pdfimages"], "raster figures from PDFs (poppler)"),
    "pdftoppm": (["pdftoppm"], "PNG previews of PDF, Illustrator and EPS-in-PDF figures (poppler)"),
    "pdfinfo": (["pdfinfo"], "page counts and titles of PDFs (poppler)"),
    "soffice": (
        [
            "soffice",
            "libreoffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ],
        "DocX to PDF (LibreOffice), so corpus can ingest a DocX manuscript",
    ),
    "latexmk": (["latexmk"], "LaTeX to PDF, so corpus can ingest a LaTeX manuscript"),
    "tesseract": (["tesseract"], "OCR (only corpus needs it; reported for completeness)"),
}


def find(name: str) -> str | None:
    """Path to the executable for ``name``, or None."""
    for cand in TOOLS[name][0]:
        if os.path.sep in cand:
            if Path(cand).is_file() and os.access(cand, os.X_OK):
                return cand
            continue
        found = shutil.which(cand)
        if found:
            return found
    return None


def available() -> dict[str, str | None]:
    return {name: find(name) for name in TOOLS}


def run(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 900,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a tool, capturing text output. Raises on failure when ``check``."""
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
        input=input_text,
    )


class MissingTool(RuntimeError):
    def __init__(self, name: str) -> None:
        purpose = TOOLS[name][1]
        super().__init__(f"{name} is not installed; it is needed for: {purpose}")
