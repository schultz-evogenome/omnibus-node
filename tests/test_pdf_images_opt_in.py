import pytest

from omnibus_node import tools
from omnibus_node.ingest import run_ingest


def test_pdf_ingest_extracts_no_images_by_default(node, pdf_file):
    if not tools.find("pdftotext"):
        pytest.skip("poppler not installed")
    result = run_ingest(node, pdf_file, "0000-0002-1825-0097")
    assert result["figures"] == 0
    assert not list((node.assets / "Author2024").glob("*.png")) if (node.assets / "Author2024").exists() else True
    result2 = run_ingest(node, pdf_file, "0000-0002-1825-0097", extract_images=True)
    assert result2["figures"] == 0  # the fixture PDF has no embedded images; the flag is honoured without error
