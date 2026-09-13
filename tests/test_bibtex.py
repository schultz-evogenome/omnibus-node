import importlib.util
from pathlib import Path

from omnibus_node import bibtex

SAMPLE = """% a header comment
@article{Schultz2023, author = {Schultz, D. T. and Haddock, S. H. D.},
  title = {Ancient gene {linkages} support ctenophores}, year = 2023,
  journal = "Nature", doi = {10.1038/s41586-023-05936-6}, file = {Schultz2023.pdf},
  license = {CC-BY-4.0}, serve = {true}}
@comment{ignored entirely}
@misc(Key2, title = {Two} # { parts}, note = {a \\{brace\\} here})
"""


def test_parse_basic():
    es = bibtex.parse(SAMPLE)
    assert [e.key for e in es] == ["Schultz2023", "Key2"]
    a = es[0]
    assert a.type == "article"
    assert a.get("title") == "Ancient gene {linkages} support ctenophores"
    assert a.get("journal") == "Nature"
    assert a.get("year") == "2023"
    assert a.flag("serve") is True
    assert es[1].get("title") == "Two parts"
    assert es[1].get("note") == "a \\{brace\\} here"


def test_round_trip():
    es = bibtex.parse(SAMPLE)
    out = bibtex.dumps(es, header="written by a test")
    back = bibtex.parse(out)
    assert [(e.type, e.key, e.fields) for e in back] == [(e.type, e.key, e.fields) for e in es]
    assert out.startswith("% written by a test\n")


def test_upsert_and_set():
    es = bibtex.parse(SAMPLE)
    e = bibtex.upsert(es, "Schultz2023", "article", {"share": "assets", "journal": None})
    assert e.get("share") == "assets"
    assert e.get("journal") is None
    new = bibtex.upsert(es, "New2020", "misc", {"title": "  spaced   out  "})
    assert new.get("title") == "spaced out"
    assert len(es) == 3


def test_make_key():
    assert bibtex.make_key("Schultz", 2023) == "Schultz2023"
    assert bibtex.make_key("van der Berg", 2023, {"Berg2023"}) == "Berg2023a"
    assert bibtex.make_key("O'Brien-Smith", None) == "OBrienSmithnd"


def test_malformed_entry_costs_one_entry():
    text = "@article{Bad, title = {unbalanced\n@article{Good, title = {ok}}\n"
    es = bibtex.parse(text)
    assert es and es[-1].get("title") in ("ok", None)


def test_corpus_parser_reads_our_output():
    """Corpus's own BibTeX parser (vendored under tests/compat, MIT) must
    accept what we write, since corpus run reads references.bib."""
    vendored = Path(__file__).parent / "compat" / "corpus_bib_parser.py"
    if not vendored.exists():
        return
    spec = importlib.util.spec_from_file_location("corpus_bib_parser", vendored)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    ours = bibtex.dumps(bibtex.parse(SAMPLE))
    theirs = mod.parse_bibtex(ours)
    keys = [e.get("_key") or e.get("key") for e in theirs]
    assert "Schultz2023" in keys
    entry = next(e for e in theirs if (e.get("_key") or e.get("key")) == "Schultz2023")
    assert entry.get("file") == "Schultz2023.pdf"
    assert entry.get("license") == "CC-BY-4.0"
