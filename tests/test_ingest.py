import pytest
import yaml

from omnibus_node import tools
from omnibus_node.ingest import default_key, detect_format, read_source, run_ingest
from omnibus_node.ingest.common import captions_from_text
from omnibus_node.ingest.latex import detex_regex, flatten, strip_comments

from conftest import make_png


def test_detect_format_and_default_key(tmp_path):
    assert detect_format(tmp_path / "x.tex") == "latex"
    assert detect_format(tmp_path / "x.DOCX") == "docx"
    with pytest.raises(ValueError):
        detect_format(tmp_path / "x.rtf")
    assert default_key(tmp_path / "schultz_2023-final.docx") == "Schultz2023final"


def test_captions_from_text():
    text = "Intro.\n\n**Figure 2.** Second legend that is long enough.\n\nFig. S1 | Supplementary legend text here.\n\nFigure 2. Repeated, ignored."
    legends = captions_from_text(text)
    assert legends["2"].startswith("Second legend")
    assert legends["S1"].startswith("Supplementary legend")


def test_latex_helpers(latex_main):
    flat = flatten(latex_main)
    assert "This is the introduction" in flat
    assert "a comment" not in strip_comments(flat)
    assert "50\\%" in strip_comments(flat)
    assert detex_regex(r"\textbf{Bold} and \emph{it}~\cite{x}.") == "Bold and it ."


def test_latex_ingest_structure(latex_main):
    ing = read_source(latex_main)
    assert ing.format == "latex"
    assert "Euplokamis" in (ing.title or "")
    assert ing.extras["abstract"].startswith("We test")
    assert ing.extras["bibfile"] == "refs"
    assert len(ing.figures) == 2
    f1, f2 = ing.figures
    assert f1.label == "fig:first"
    assert "first figure" in f1.caption
    assert [p.name for p in f1.files] == ["fig1.pdf"]
    assert f2.label == "fig:second"
    assert [p.name for p in f2.files] == ["fig2.png"]
    assert f2.missing == ["missing_figure"]
    assert f2.panels == ["Left panel", "Right panel"]
    assert "Introduction" in ing.text and "Results" in ing.text


def test_latex_run_ingest(node, latex_main):
    result = run_ingest(node, latex_main, "0000-0002-1825-0097", key="Fixture2024", render=False, keep_source=True)
    assert result["key"] == "Fixture2024"
    assert result["figures"] == 2 and result["figures_missing_files"] == 1
    text = (node.sources / "Fixture2024" / "text.md").read_text()
    assert text.startswith("---\nkey: Fixture2024\n")
    assert "contributor: 0000-0002-1825-0097" in text
    assert "status: draft" in text
    assert (node.sources / "Fixture2024" / "src" / "main.tex").exists()
    assert (node.sources / "Fixture2024" / "src" / "sections" / "intro.tex").exists()
    asset = yaml.safe_load((node.assets / "Fixture2024" / "asset.yaml").read_text())
    figs = {f["id"]: f for f in asset["figures"]}
    roles = {(f["role"], f["tier"]) for f in figs["fig1"]["files"]}
    assert ("original", "assets") in roles
    if tools.find("pdftoppm"):
        assert ("preview", "plots") in roles
        assert (node.assets / "Fixture2024" / "fig1.png").exists()
    assert figs["fig1"]["files"][0]["from"] == "figs/fig1.pdf"
    assert figs["fig2"]["files"][0]["tier"] == "plots"
    assert figs["fig2"]["missing"] == ["missing_figure"]
    e = node.entry("Fixture2024")
    assert e.get("status") == "draft" and e.get("added") and e.get("sourcefile")
    assert e.get("file") is None  # not rendered
    assert any("not found" in w for w in result["warnings"])


def test_latex_ingest_does_not_overwrite_curated_metadata(node, latex_main):
    node.upsert_entry("Fixture2024", "article", {"title": "Curated title", "year": "2024"})
    run_ingest(node, latex_main, "0000-0002-1825-0097", key="Fixture2024", render=False)
    assert node.entry("Fixture2024").get("title") == "Curated title"


@pytest.mark.parametrize("use_pandoc", [True, False])
def test_docx_ingest(node, docx_file, monkeypatch, use_pandoc):
    if use_pandoc and not tools.find("pandoc"):
        pytest.skip("pandoc not installed")
    if not use_pandoc:
        real = tools.find
        monkeypatch.setattr(tools, "find", lambda name: None if name == "pandoc" else real(name))
    ing = read_source(docx_file)
    try:
        assert ing.format == "docx"
        assert ing.title == "A fixture DocX manuscript"
        assert len(ing.figures) == 1
        fig = ing.figures[0]
        assert fig.number == "1"
        assert fig.caption.startswith("A test caption")
        assert fig.files and fig.files[0].suffix == ".png"
        assert "[figure: fig1]" in ing.text
        assert "Introduction" in ing.text and "Results" in ing.text
    finally:
        ing.cleanup()
    result = run_ingest(node, docx_file, "0000-0002-1825-0097", key="Docx2024", render=False)
    assert result["figures"] == 1
    assert (node.assets / "Docx2024" / "fig1.png").exists()


def test_markdown_ingest(node, tmp_path):
    make_png(tmp_path / "img" / "plot.png")
    md = tmp_path / "notes.md"
    md.write_text(
        "---\ntitle: A markdown note\n---\n# Heading\n\nSome text.\n\n![](img/plot.png)\n\nFigure 1. The plot legend, long enough.\n\n![missing](img/none.png)\n",
        encoding="utf-8",
    )
    ing = read_source(md)
    assert ing.title == "A markdown note"
    assert len(ing.figures) == 2
    assert ing.figures[0].caption.startswith("The plot legend")
    assert ing.figures[1].missing == ["img/none.png"]
    result = run_ingest(node, md, "0000-0002-1825-0097", key="Note2024")
    assert result["figures_missing_files"] == 1
    assert (node.assets / "Note2024" / "fig1.png").exists()


def test_text_ingest(node, tmp_path):
    txt = tmp_path / "plain.txt"
    txt.write_text("A short title line\n\nBody paragraph.\n", encoding="utf-8")
    ing = read_source(txt)
    assert ing.title == "A short title line" and ing.format == "text"


def test_pdf_ingest(node, pdf_file):
    if not tools.find("pdftotext"):
        pytest.skip("poppler not installed")
    result = run_ingest(node, pdf_file, "0000-0002-1825-0097")
    assert result["key"] == "Author2024"
    assert result["status"] == "published"
    assert (node.library / "Author2024.pdf").exists()
    text = (node.sources / "Author2024" / "text.md").read_text()
    assert "Hello fixture text" in text
    e = node.entry("Author2024")
    assert e.get("file") == "Author2024.pdf" and len(e.get("sha256")) == 64
