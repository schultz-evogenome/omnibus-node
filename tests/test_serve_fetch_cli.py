import asyncio
import json

import yaml

from omnibus_node import fetch as fetch_mod
from omnibus_node.cli import main
from omnibus_node.ingest.common import Ingested, write_text
from omnibus_node.provenance import stamp
from omnibus_node.serve import build_server

from conftest import PNG_1X1, make_pdf, make_png


def _work_with_figure(node, key, license_value=None):
    fields = {"title": f"Title {key}", "year": "2023", "author": "Schultz, D. T. and Other, A.", "contributor": "0000-0002-1825-0097", "added": "2026-01-01"}
    if license_value:
        fields["license"] = license_value
    node.upsert_entry(key, "article", fields)
    src = node.root / f"{key}.md"
    src.write_text("Body text about ctenophores.\n")
    write_text(node, key, Ingested(format="markdown", source=src, text="Body text about ctenophores.\n"), stamp("0000-0002-1825-0097"), "published")
    adir = node.assets / key
    make_png(adir / "fig1.png")
    (adir / "asset.yaml").write_text(
        yaml.safe_dump({"key": key, "figures": [{"id": "fig1", "caption": "A caption.", "files": [{"path": "fig1.png", "role": "plot", "tier": "plots", "sha256": "0" * 64}]}]})
    )


def _call(server, name, args):
    return asyncio.run(server.call_tool(name, args))


def _payload(result):
    """The payload of a call_tool result: structured content when the SDK
    provides it, else the JSON text of the first text block."""
    sc = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if sc:
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    content = getattr(result, "content", result)
    texts = [c.text for c in content if getattr(c, "type", None) == "text"]
    if texts:
        try:
            return json.loads(texts[0])
        except ValueError:
            return texts[0]
    return content


def test_server_tools(node):
    _work_with_figure(node, "Open2023", "CC-BY-4.0")
    _work_with_figure(node, "NoLicense2022")
    server = build_server(node)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"node_info", "list_works", "get_work", "get_text", "search_text", "list_figures", "get_figure", "get_figure_file", "list_notes", "get_note", "record_dead_end", "refresh"} <= names

    info = _payload(_call(server, "node_info", {}))
    assert info["works"] == 2 and info["texts"] == 2 and info["figures"] == 2

    works = _payload(_call(server, "list_works", {}))
    assert {w["key"] for w in works} == {"Open2023", "NoLicense2022"}

    text = _payload(_call(server, "get_text", {"key": "Open2023"}))
    assert "ctenophores" in text["text"] and "Schultz et al. (2023)" in text["attribution"]

    hits = _payload(_call(server, "search_text", {"query": "ctenophores"}))
    assert hits and hits[0]["key"] in ("Open2023", "NoLicense2022")

    ok = _call(server, "get_figure", {"key": "Open2023", "figure_id": "fig1", "profile": "manuscript"})
    content = ok[0] if isinstance(ok, tuple) else getattr(ok, "content", ok)
    assert any(getattr(c, "type", None) == "image" for c in content)

    refused = _call(server, "get_figure", {"key": "NoLicense2022", "figure_id": "fig1", "profile": "manuscript"})
    content = refused[0] if isinstance(refused, tuple) else getattr(refused, "content", refused)
    texts = " ".join(getattr(c, "text", "") for c in content)
    assert "no_record" in texts and "withheld" in texts

    allowed = _call(server, "get_figure", {"key": "NoLicense2022", "figure_id": "fig1", "profile": "report"})
    content = allowed[0] if isinstance(allowed, tuple) else getattr(allowed, "content", allowed)
    assert any(getattr(c, "type", None) == "image" for c in content)

    rec = _payload(_call(server, "record_dead_end", {"project": "Open2023", "tried": "thing", "happened": "failed"}))
    assert rec["recorded"] == "notes/dead-ends.md" and rec["contributor"] == "0000-0002-1825-0097"

    missing = _payload(_call(server, "get_work", {"key": "Nope"}))
    assert missing["code"] == "not_found"


class _FakeResponse:
    def __init__(self, status, content=b"", text=""):
        self.status_code = status
        self.content = content
        self.text = text or content.decode("latin-1", "ignore")


def test_fetch_pdfs(node, monkeypatch):
    pdf = make_pdf(node.root / "tmp.pdf").read_bytes()

    def fake_get(self, url, **kw):
        if "plos" in url:
            return _FakeResponse(200, pdf)
        if "oup" in url:
            return _FakeResponse(403)
        return _FakeResponse(200, b"<html>landing</html>")

    monkeypatch.setattr(fetch_mod.requests.Session, "get", fake_get)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)
    node.upsert_entry("Plos2020", "article", {"title": "P", "oapdf": "https://journals.plos.org/a.pdf"})
    node.upsert_entry("Oup2021", "article", {"title": "O", "oapdf": "https://academic.oup.com/a.pdf", "oapdfalt": "https://example.org/landing"})
    node.upsert_entry("NoUrl2022", "article", {"title": "N"})
    r = fetch_mod.run_fetch(node)
    assert r["downloaded"] == ["Plos2020"]
    assert (node.library / "Plos2020.pdf").read_bytes() == pdf
    assert node.entry("Plos2020").get("file") == "Plos2020.pdf" and node.entry("Plos2020").get("sha256")
    assert r["failed"][0]["key"] == "Oup2021" and "HTTP 403" in r["failed"][0]["reasons"][0]
    assert "landing page" in r["failed"][0]["reasons"][1]
    assert r["advice"]


JATS = """<?xml version="1.0"?><article><front><article-meta><title-group><article-title>T</article-title></title-group></article-meta></front>
<body><sec><title>Introduction</title><p>Ctenophores glow in the deep sea.</p>
<fig id="f1"><label>Figure 1</label><caption><p>A legend from JATS that is long enough.</p></caption><graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="41586_Fig1_HTML"/></fig>
</sec></body></article>"""


def test_fetch_text_from_europepmc(node, monkeypatch):
    def fake_get(self, url, **kw):
        if url.endswith("/fullTextXML"):
            return _FakeResponse(200, JATS.encode(), JATS)
        if url.endswith("41586_Fig1_HTML.jpg"):
            return _FakeResponse(200, b"\xff\xd8\xff\xe0" + b"jpegdata")
        return _FakeResponse(404)

    monkeypatch.setattr(fetch_mod.requests.Session, "get", fake_get)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)
    node.upsert_entry("Pmc2023", "article", {"title": "Glow", "pmcid": "PMC123", "contributor": "0000-0002-1825-0097", "added": "2026-01-01"})
    node.upsert_entry("NoPmc2023", "article", {"title": "Other"})
    r = fetch_mod.run_fetch_text(node)
    assert r["written"] == ["Pmc2023"] and r["skipped_no_pmcid_or_existing"] == 1
    text = (node.sources / "Pmc2023" / "text.md").read_text()
    assert "Ctenophores glow" in text and "format: jats" in text
    doc = yaml.safe_load((node.assets / "Pmc2023" / "asset.yaml").read_text())
    fig = doc["figures"][0]
    assert fig["caption"].startswith("A legend from JATS") and fig["number"] == "1"
    assert fig["files"][0]["path"] == "fig1.jpg" and fig["files"][0]["tier"] == "plots"


def test_cli_end_to_end(tmp_path, capsys):
    root = tmp_path / "n"
    assert main(["--root", str(root), "init", "--name", "cli-node", "--contributor", "conchoecia", "--contributor-name", "D"]) == 0
    assert (root / "sharing.yaml").exists() and (root / "config.yaml").exists()
    capsys.readouterr()
    md = tmp_path / "Doc2024.md"
    md.write_text("# A doc\n\nText.\n")
    assert main(["--root", str(root), "ingest", str(md), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["key"] == "Doc2024" and out["text"] == "sources/Doc2024/text.md"
    assert main(["--root", str(root), "share", "set", "--person", "conchoecia", "--tier", "all"]) == 0
    assert main(["--root", str(root), "share", "show"]) == 0
    assert "Doc2024: all" in capsys.readouterr().out
    assert main(["--root", str(root), "dead-end", "--project", "Doc2024", "--tried", "x", "--happened", "y"]) == 0
    assert main(["--root", str(root), "check"]) == 0
    assert main(["--root", str(root), "export", "--tier", "plots"]) == 0
    assert (root / "export" / "manifest.json").exists()
    assert main(["--root", str(root), "tools"]) == 0
    assert main(["--root", str(root), "ingest", str(tmp_path / "missing.tex")]) == 1


def test_png_fixture_is_png():
    assert PNG_1X1[:4] == b"\x89PNG"
