import yaml

from omnibus_node.assets import run_assets
from omnibus_node.ingest.common import write_asset_yaml

from conftest import make_png


def test_assets_take_captions_from_fetched_records_by_number(node, tmp_path):
    """`fetch --text` leaves caption-only records (Europe PMC legends);
    a figures.yaml entry with the same number takes the caption and
    replaces that record instead of duplicating it."""
    node.upsert_entry("Paper2023", "article", {"title": "P", "year": "2023"})
    adir = node.assets / "Paper2023"
    adir.mkdir(parents=True)
    write_asset_yaml(
        adir,
        "Paper2023",
        {"contributor": "x", "added": "2026-01-01", "tool": "t"},
        [
            {"id": "fig1", "caption": "Main legend from JATS.", "caption_confidence": "high", "label": "Fig. 1", "number": "1", "files": [], "missing": ["img1"]},
            {"id": "fig5", "caption": "Extended legend from JATS.", "caption_confidence": "high", "number": "ED1", "files": [], "missing": ["img5"]},
        ],
    )
    folder = tmp_path / "figs"
    make_png(folder / "fig1.png")
    make_png(folder / "ed1.png")
    spec = {
        "key": "Paper2023",
        "figures": [
            {"id": "fig1", "original": "fig1.png", "caption_from_text": 1},
            {"id": "ed1", "original": "ed1.png", "caption_from_text": "ED1"},
        ],
    }
    (folder / "figures.yaml").write_text(yaml.safe_dump(spec))
    result = run_assets(node, folder / "figures.yaml", "x")
    assert not result["warnings"]
    doc = yaml.safe_load((adir / "asset.yaml").read_text())
    ids = [f["id"] for f in doc["figures"]]
    assert ids == ["fig1", "ed1"]  # fig5 was folded into ed1
    figs = {f["id"]: f for f in doc["figures"]}
    assert figs["fig1"]["caption"] == "Main legend from JATS." and figs["fig1"]["label"] == "Fig. 1"
    assert figs["ed1"]["caption"] == "Extended legend from JATS." and figs["ed1"]["number"] == "ED1"
    assert figs["ed1"]["files"][0]["path"] == "ed1.png"
