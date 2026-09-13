from omnibus_node import fetch as fetch_mod
from omnibus_node.check import run_check
from omnibus_node.export import plan
from omnibus_node.ingest.common import Ingested, license_from_statement, read_text, text_withheld_reason, write_text
from omnibus_node.provenance import stamp


def test_license_from_statement():
    assert license_from_statement("http://creativecommons.org/licenses/by/4.0/", None) == "CC-BY-4.0"
    assert license_from_statement(None, "This is an open-access article distributed under the terms of the Creative Commons Attribution-NonCommercial license") == "CC-BY-NC"
    assert license_from_statement(None, "distributed under the terms of the Creative Commons Attribution License (CC BY 4.0)") == "CC-BY-4.0"
    assert license_from_statement("https://creativecommons.org/publicdomain/zero/1.0/", None) == "CC0-1.0"
    assert license_from_statement(None, "All rights reserved.") is None


def _text(node, key, fmt, body="Body."):
    src = node.root / f"{key}.src"
    src.write_text(body)
    write_text(node, key, Ingested(format=fmt, source=src, text=body, title=key), stamp("x"), "published")


def test_text_front_matter_carries_rights(node):
    node.upsert_entry("Open2023", "article", {"title": "O", "year": "2023", "author": "Schultz, D. T.", "license": "CC-BY-4.0", "copyright": "© 2023 The Authors"})
    _text(node, "Open2023", "jats")
    front, _ = read_text(node, "Open2023")
    assert front["license"] == "CC-BY-4.0" and front["copyright"] == "© 2023 The Authors"
    assert front["publication_clearance"] == "licensed_open"
    assert "Schultz (2023)" in front["attribution"]
    assert front["conversion"].startswith("converted to Markdown from jats")


def test_publisher_pdf_text_of_closed_work_is_withheld(node):
    node.upsert_entry("Closed2018", "article", {"title": "C", "year": "2018", "share": "all"})
    node.upsert_entry("OpenPdf2020", "article", {"title": "P", "year": "2020", "license": "CC-BY-4.0", "share": "all"})
    node.upsert_entry("Author2019", "article", {"title": "A", "year": "2019", "textsource": "author", "share": "all"})
    for key in ("Closed2018", "OpenPdf2020", "Author2019"):
        _text(node, key, "pdf")
    front, _ = read_text(node, "Closed2018")
    assert text_withheld_reason(node, node.entry("Closed2018"), front)
    assert text_withheld_reason(node, node.entry("OpenPdf2020"), read_text(node, "OpenPdf2020")[0]) is None
    assert text_withheld_reason(node, node.entry("Author2019"), read_text(node, "Author2019")[0]) is None
    works, _, _ = plan(node, "all")
    by = {w.key: w for w in works}
    assert by["Closed2018"].text is None and by["Closed2018"].text_withheld
    assert by["OpenPdf2020"].text is not None and by["Author2019"].text is not None
    r = run_check(node)
    assert not r["ok"] and any("Closed2018" in e and "must not be published" in e for e in r["errors"])


JATS = """<?xml version="1.0"?><article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>
<permissions><copyright-statement>© 2024 Liu et al</copyright-statement>
<license xlink:href="http://creativecommons.org/licenses/by/4.0/"><license-p>This is an open access article distributed under the terms of the Creative Commons Attribution License.</license-p></license>
</permissions></article-meta></front><body><p>Text here.</p></body></article>"""


def test_jats_permissions_recorded_in_bib_and_text(node, monkeypatch):
    perm = fetch_mod.jats_permissions(JATS)
    assert perm["license"] == "CC-BY-4.0" and perm["copyright"] == "© 2024 Liu et al" and "open access" in perm["licensestatement"]

    class _Resp:
        def __init__(self, status, text=""):
            self.status_code, self.text, self.content = status, text, text.encode()

    def fake_get(self, url, **kw):
        return _Resp(200, JATS) if url.endswith("/fullTextXML") else _Resp(404)

    monkeypatch.setattr(fetch_mod.requests.Session, "get", fake_get)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)
    node.upsert_entry("Liu2024", "article", {"title": "L", "year": "2024", "pmcid": "PMC1", "license": "CC-BY-NC-4.0", "licensesource": "openalex"})
    r = fetch_mod.run_fetch_text(node, images=False)
    assert r["written"] == ["Liu2024"]
    e = node.entry("Liu2024")
    assert e.get("license") == "CC-BY-4.0" and e.get("licensesource") == "jats" and e.get("copyright") == "© 2024 Liu et al"
    front, _ = read_text(node, "Liu2024")
    assert front["license"] == "CC-BY-4.0" and front["license_source"] == "jats"
