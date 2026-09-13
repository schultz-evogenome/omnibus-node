import requests

from omnibus_node import fetch as fetch_mod

JATS = """<?xml version="1.0"?><article><body><sec><title>Intro</title><p>Text survives image failures.</p>
<fig id="f1"><label>Figure 1</label><caption><p>A legend that is long enough to count.</p></caption><graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="img1"/></fig>
</sec></body></article>"""


class _Resp:
    def __init__(self, status, content=b"", text="", data=None):
        self.status_code = status
        self.content = content
        self.text = text or content.decode("latin-1", "ignore")
        self._data = data

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


def test_text_is_written_even_when_images_time_out(node, monkeypatch):
    calls = {"search": 0}

    def fake_get(self, url, **kw):
        if "/search" in url:
            calls["search"] += 1
            return _Resp(200, data={"resultList": {"result": [{"pmcid": "PMC77", "source": "MED"}]}})
        if url.endswith("/fullTextXML"):
            return _Resp(200, JATS.encode(), JATS)
        if "/bin/" in url:
            raise requests.ReadTimeout("slow")
        return _Resp(404)

    monkeypatch.setattr(fetch_mod.requests.Session, "get", fake_get)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)
    node.upsert_entry("Doi2023", "article", {"title": "T", "doi": "10.1000/x", "contributor": "0000-0002-1825-0097", "added": "2026-01-01"})
    r = fetch_mod.run_fetch_text(node)
    assert r["written"] == ["Doi2023"] and r["pmcids_looked_up"] == 1
    assert "Text survives" in (node.sources / "Doi2023" / "text.md").read_text()
    assert any("not available" in w for w in r["warnings"])
    e = node.entry("Doi2023")
    assert e.get("pmcid") == "PMC77" and e.get("pmcidchecked")
    # A second run neither looks up again nor rewrites.
    r2 = fetch_mod.run_fetch_text(node)
    assert r2["written"] == [] and calls["search"] == 1


def test_preprint_ppr_id_is_used(node, monkeypatch):
    def fake_get(self, url, **kw):
        if "/search" in url:
            return _Resp(200, data={"resultList": {"result": [{"id": "PPR99", "source": "PPR", "hasFullTextXML": "Y"}]}})
        if url.endswith("PPR99/fullTextXML"):
            return _Resp(200, JATS.encode(), JATS)
        return _Resp(404)

    monkeypatch.setattr(fetch_mod.requests.Session, "get", fake_get)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)
    node.upsert_entry("Pre2025", "article", {"title": "P", "doi": "10.1101/x", "status": "preprint"})
    r = fetch_mod.run_fetch_text(node, images=False)
    assert r["written"] == ["Pre2025"]
    assert node.entry("Pre2025").get("pmcid") == "PPR99"
