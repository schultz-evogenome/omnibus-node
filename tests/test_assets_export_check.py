import json

import yaml

from omnibus_node.assets import run_assets
from omnibus_node.check import run_check
from omnibus_node.export import plan, run_export
from omnibus_node.ingest.common import write_text, Ingested
from omnibus_node.notes import record_dead_end
from omnibus_node.provenance import stamp
from omnibus_node.search import Index

from conftest import make_pdf, make_png


def _figure_folder(tmp_path):
    folder = tmp_path / "CtenoFigures"
    make_pdf(folder / "FIG1" / "FIG1_v12.pdf", "figure one")
    make_png(folder / "FIG2" / "FIG2_final.png")
    (folder / "tables").mkdir(parents=True)
    (folder / "tables" / "table1.tsv").write_text("a\tb\n1\t2\n")
    (folder / "tables" / "table2.tsv").write_text("c\td\n3\t4\n")
    (folder / "plot.py").write_text("print('plot')\n")
    spec = {
        "key": "Paper2023",
        "figures": [
            {"id": "fig1", "original": "FIG1/FIG1_v12.pdf", "caption_from_text": 1, "data": ["tables/*.tsv"], "scripts": ["plot.py"]},
            {"id": "fig2", "original": "FIG2/FIG2_final.png", "caption": "Given caption.", "data": ["tables/nope.tsv"]},
        ],
    }
    (folder / "figures.yaml").write_text(yaml.safe_dump(spec))
    return folder / "figures.yaml"


def _text(node, key, body, status="published"):
    src = node.root / f"{key}.src.md"
    src.write_text(body)
    ing = Ingested(format="markdown", source=src, text=body, title=f"Title of {key}")
    write_text(node, key, ing, stamp("0000-0002-1825-0097"), status)


def test_assets_from_figure_folder(node, tmp_path):
    node.upsert_entry("Paper2023", "article", {"title": "Paper", "year": "2023", "license": "CC-BY-4.0", "contributor": "0000-0002-1825-0097", "added": "2026-01-01"})
    _text(node, "Paper2023", "Intro.\n\nFigure 1. Legend pulled from the text, long enough.\n")
    result = run_assets(node, _figure_folder(tmp_path), "0000-0002-1825-0097")
    assert result["figures"] == 2
    doc = yaml.safe_load((node.assets / "Paper2023" / "asset.yaml").read_text())
    figs = {f["id"]: f for f in doc["figures"]}
    assert figs["fig1"]["caption"].startswith("Legend pulled")
    roles = {(f["role"], f["tier"]) for f in figs["fig1"]["files"]}
    assert ("original", "assets") in roles and ("data", "assets") in roles and ("script", "assets") in roles
    data_paths = sorted(f["path"] for f in figs["fig1"]["files"] if f["role"] == "data")
    assert data_paths == ["fig1/datas/table1.tsv", "fig1/datas/table2.tsv"]
    assert figs["fig2"]["files"][0]["tier"] == "plots"
    assert figs["fig2"]["missing"] == ["tables/nope.tsv"]
    assert all(len(f["sha256"]) == 64 for fig in doc["figures"] for f in fig["files"])
    assert figs["fig1"]["files"][0]["from"] == "FIG1/FIG1_v12.pdf"


def test_plan_and_export_respect_tiers(node, tmp_path):
    node.upsert_entry("Open2023", "article", {"title": "Open", "year": "2023", "license": "CC-BY-4.0", "contributor": "0000-0002-1825-0097", "added": "2026-01-01"})
    node.upsert_entry("Draft2026", "article", {"title": "Draft", "status": "draft", "contributor": "0000-0002-1825-0097", "added": "2026-01-01"})
    node.upsert_entry("Hidden2020", "article", {"title": "Hidden", "serve": "false", "servereason": "collaborator asked"})
    _text(node, "Open2023", "Open text.\n\nFigure 1. The open legend, long enough to count.\n")
    _text(node, "Draft2026", "Secret draft text.\n", status="draft")
    run_assets(node, _figure_folder(tmp_path), "0000-0002-1825-0097")  # key Paper2023 -> minimal entry created
    make_pdf(node.library / "Open2023.pdf")
    record_dead_end(node, "0000-0002-1825-0097", "Open2023", "an aligner", "it crashed", "use another")

    s = node.load_sharing()
    s.people["0000-0002-1825-0097"].share = "assets"
    s.items["Draft2026"] = __import__("omnibus_node.sharing", fromlist=["Item"]).Item(share="all")
    node.save_sharing(s)

    works, excluded, shared_notes = plan(node, "all")
    by_key = {w.key: w for w in works}
    assert {x["key"] for x in excluded} == {"Hidden2020"}
    assert by_key["Open2023"].tier == "assets" and by_key["Open2023"].text is not None
    assert by_key["Draft2026"].tier == "all" and by_key["Draft2026"].text is not None
    assert shared_notes is False  # default tier is plots

    # Cap at plots: draft text disappears, asset-tier files are withheld, previews stay.
    result = run_export(node, out=tmp_path / "out", cap="plots")
    out = tmp_path / "out"
    manifest = json.loads((out / "manifest.json").read_text())
    recs = {r["key"]: r for r in manifest["works"]}
    assert recs["Open2023"]["text"] is True
    assert recs["Draft2026"]["text"] is False
    assert recs["Paper2023"]["files_withheld_by_tier"] >= 3
    served = yaml.safe_load((out / "works" / "Paper2023" / "assets" / "asset.yaml").read_text())
    served_roles = {f["role"] for fig in served["figures"] for f in fig["files"]}
    assert served_roles <= {"preview", "plot"}
    assert not list(out.rglob("*.pdf")) or all("assets" in str(p) for p in out.rglob("*.pdf"))
    assert not (out / "library").exists()
    bib = (out / "references.bib").read_text()
    assert "Hidden2020" not in bib and "oapdf" not in bib
    meta = json.loads((out / "works" / "Open2023" / "metadata.json").read_text())
    assert meta["publication_clearance"] == "licensed_open"
    assert result["excluded"] == 1


def test_check_reports(node):
    node.upsert_entry("Missing2020", "article", {"title": "M", "file": "Missing2020.pdf"})
    node.upsert_entry("Fetchable2021", "article", {"title": "F", "file": "Fetchable2021.pdf", "oapdf": "https://example.org/x.pdf", "share": "bogus"})
    r = run_check(node)
    assert not r["ok"]
    assert any("Missing2020" in e and "no oapdf" in e for e in r["errors"])
    assert any("bogus" in e for e in r["errors"])
    assert any("Fetchable2021" in w and "fetch" in w for w in r["warnings"])


def test_check_ok_on_clean_node(node):
    make_pdf(node.library / "Good2022.pdf")
    node.upsert_entry("Good2022", "article", {"title": "G", "year": "2022", "file": "Good2022.pdf", "license": "CC-BY-4.0", "contributor": "x", "added": "2026-01-01"})
    r = run_check(node)
    assert r["ok"]
    assert any("1 corpus-ready" in line for line in r["info"])


def test_dead_end_and_search(node):
    path = record_dead_end(node, "conchoecia", "hydra", "assembly with tool X", "N50 halved", "stay with tool Y")
    text = path.read_text()
    assert "· conchoecia · hydra" in text and "- Decided: stay with tool Y" in text
    idx = Index()
    idx.add("A", ["Ctenophores are the sister group to all other animals.", "Sponges are filter feeders."])
    idx.add("B", ["Hydra regenerates its head."])
    hits = idx.search("sister group ctenophores")
    assert hits and hits[0].key == "A" and hits[0].paragraph == 0
    assert idx.search("") == []
