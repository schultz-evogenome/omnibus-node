import yaml

from omnibus_node.assets import run_assets
from omnibus_node.check import run_check
from omnibus_node.export import plan, run_export
from omnibus_node.ingest.common import captions_from_text, figure_number

from conftest import make_png


def test_figure_numbers_keep_extended_data_apart():
    assert figure_number("Extended Data Fig. 3") == "ED3"
    assert figure_number("Fig. S2") == "S2"
    assert figure_number("Supplementary Figure 4") == "S4"
    assert figure_number("Figure 1") == "1"
    assert figure_number("Plate 7") == "7"
    legends = captions_from_text(
        "Fig. 1 | Main legend, long enough here.\n\nExtended Data Fig. 1 | Extended legend, long enough.\n\nSupplementary Fig. 2. Supp legend text here."
    )
    assert legends["1"].startswith("Main")
    assert legends["ED1"].startswith("Extended")
    assert legends["S2"].startswith("Supp")


def test_offline_originals_are_recorded_not_copied(node, tmp_path):
    folder = tmp_path / "figs"
    folder.mkdir()
    (folder / "FIG1_v19.ai").write_bytes(b"%PDF-1.4 pretend illustrator file")
    make_png(folder / "FIG1_v19.jpg")
    spec = {"key": "Big2023", "figures": [{"id": "fig1", "original": "FIG1_v19.jpg", "offline": ["FIG1_v19.ai", "nope.ai"], "caption": "Big one."}]}
    (folder / "figures.yaml").write_text(yaml.safe_dump(spec))
    node.upsert_entry("Big2023", "article", {"title": "Big", "year": "2023", "contributor": "x", "added": "2026-01-01", "license": "CC-BY-4.0", "share": "all"})
    result = run_assets(node, folder / "figures.yaml", "0000-0002-1825-0097")
    assert any("nope.ai" in w for w in result["warnings"])
    doc = yaml.safe_load((node.assets / "Big2023" / "asset.yaml").read_text())
    files = doc["figures"][0]["files"]
    offline = [f for f in files if f.get("stored") is False]
    assert len(offline) == 1
    assert offline[0]["from"] == "FIG1_v19.ai" and offline[0]["bytes"] > 0 and "path" not in offline[0]
    assert not (node.assets / "Big2023" / "fig1.ai").exists()
    assert run_check(node)["ok"]

    works, _, _ = plan(node, "all")
    assert any(f.get("stored") is False for f in works[0].figures[0]["files"])
    works_plots, _, _ = plan(node, "plots")
    assert all(f.get("stored") is not False for f in works_plots[0].figures[0]["files"])

    out = tmp_path / "out"
    run_export(node, out=out, cap="all")
    assert (out / "works" / "Big2023" / "assets" / "fig1.jpg").exists()
    assert not list((out / "works" / "Big2023" / "assets").glob("*.ai"))
