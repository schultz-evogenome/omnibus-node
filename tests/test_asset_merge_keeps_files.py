import yaml

from omnibus_node.ingest.common import write_asset_yaml

from conftest import make_png


def test_caption_only_record_does_not_discard_files(node):
    adir = node.assets / "P2023"
    adir.mkdir(parents=True)
    make_png(adir / "fig1.png")
    st = {"contributor": "x", "added": "2026-01-01", "tool": "t"}
    write_asset_yaml(adir, "P2023", st, [{"id": "fig1", "caption": "", "caption_confidence": "low", "files": [{"path": "fig1.png", "role": "plot", "tier": "plots", "sha256": "0" * 64}]}])
    # A later full-text refresh brings a caption-only record for the same id.
    write_asset_yaml(adir, "P2023", st, [{"id": "fig1", "caption": "Legend from JATS.", "caption_confidence": "high", "number": "1", "files": [], "missing": ["img1"]}])
    doc = yaml.safe_load((adir / "asset.yaml").read_text())
    fig = doc["figures"][0]
    assert fig["files"][0]["path"] == "fig1.png"
    assert fig["caption"] == "Legend from JATS." and fig["number"] == "1"
    assert len(doc["figures"]) == 1
