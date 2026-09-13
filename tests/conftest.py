"""Fixtures built on the fly, so no binary files live in the repo and no real
manuscript is needed: a one-page PDF with known text, a 1x1 PNG, a small
LaTeX project, and a DocX with one image and a caption."""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import pytest

from omnibus_node.node import Node

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def make_png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_1X1)
    return path


def make_pdf(path: Path, text: str = "Hello fixture") -> Path:
    """A valid one-page PDF whose text layer contains ``text``."""
    content = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


LATEX_MAIN = r"""% !TeX program = pdflatex
\documentclass{article}
\usepackage{graphicx}
\usepackage{subcaption}
\graphicspath{{figs/}}
\title{A fixture manuscript about \emph{Euplokamis}}
\begin{document}
\maketitle
\begin{abstract}
We test the ingester. % a comment
\end{abstract}
\input{sections/intro}
\section{Results}
Text before the figure.
\begin{figure}[t]
  \centering
  \includegraphics[width=\linewidth]{fig1}
  \caption{\textbf{The first figure.} Panels are lettered.}
  \label{fig:first}
\end{figure}
\begin{figure*}
  \begin{subfigure}{0.5\linewidth}
    \includegraphics{fig2.png}
    \caption{Left panel}
  \end{subfigure}
  \begin{subfigure}{0.5\linewidth}
    \includegraphics{missing_figure}
    \caption{Right panel}
  \end{subfigure}
  \caption{The second figure, with two panels~\cite{Someone2020}.}
  \label{fig:second}
\end{figure*}
\bibliography{refs}
\end{document}
"""

LATEX_INTRO = r"""\section{Introduction}
This is the introduction with 50\% effort and a citation \citep{Someone2020}.
"""


def make_latex_project(root: Path) -> Path:
    (root / "sections").mkdir(parents=True, exist_ok=True)
    (root / "figs").mkdir(exist_ok=True)
    main = root / "main.tex"
    main.write_text(LATEX_MAIN, encoding="utf-8")
    (root / "sections" / "intro.tex").write_text(LATEX_INTRO, encoding="utf-8")
    make_pdf(root / "figs" / "fig1.pdf", "figure one")
    make_png(root / "figs" / "fig2.png")
    (root / "refs.bib").write_text("@article{Someone2020, title={X}, year={2020}}\n", encoding="utf-8")
    return main


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>
"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>
"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>
</Relationships>
"""

_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>A fixture DocX manuscript</dc:title>
</cp:coreProperties>
"""


def _p(text: str, style: str | None = None) -> str:
    ppr = f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>" if style else ""
    return f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


_DRAWING = (
    "<w:p><w:r><w:drawing>"
    "<wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\"><wp:extent cx=\"914400\" cy=\"914400\"/>"
    "<wp:docPr id=\"1\" name=\"Picture 1\"/>"
    "<a:graphic xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\">"
    "<a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
    "<pic:pic xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
    "<pic:nvPicPr><pic:cNvPr id=\"1\" name=\"image1.png\"/><pic:cNvPicPr/></pic:nvPicPr>"
    "<pic:blipFill><a:blip r:embed=\"rId1\"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
    "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"914400\" cy=\"914400\"/></a:xfrm>"
    "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></pic:spPr>"
    "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
)


def make_docx(path: Path) -> Path:
    body = "".join(
        [
            _p("A fixture DocX manuscript", "Title"),
            _p("Introduction", "Heading1"),
            _p("This paragraph introduces the work."),
            _DRAWING,
            _p("Figure 1. A test caption of the one and only figure."),
            _p("Results", "Heading1"),
            _p("Nothing much happened."),
        ]
    )
    document = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" "
        "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\">"
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/media/image1.png", PNG_1X1)
        z.writestr("docProps/core.xml", _CORE)
    return path


@pytest.fixture
def node(tmp_path: Path) -> Node:
    return Node.init(tmp_path / "node", "test-node", "0000-0002-1825-0097", "Test Person")


@pytest.fixture
def latex_main(tmp_path: Path) -> Path:
    return make_latex_project(tmp_path / "paper")


@pytest.fixture
def docx_file(tmp_path: Path) -> Path:
    return make_docx(tmp_path / "paper.docx")


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "Author2024.pdf", "Hello fixture text")
