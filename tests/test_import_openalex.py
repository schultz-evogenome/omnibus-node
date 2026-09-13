from omnibus_node.import_openalex import abstract_from_inverted, entry_from_work, license_value, name_to_bib, run_import

WORK_OPEN = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1000/open",
    "title": "An open paper.",
    "publication_year": 2023,
    "type": "article",
    "authorships": [
        {"author_position": "first", "author": {"display_name": "Namrata Ahuja"}},
        {"author_position": "last", "author": {"display_name": "Darrin T. Schultz"}},
    ],
    "primary_location": {"source": {"display_name": "PLoS ONE"}},
    "best_oa_location": {"pdf_url": "https://journals.plos.org/x.pdf", "license": "cc-by", "landing_page_url": "https://doi.org/10.1000/open"},
    "locations": [{"pdf_url": "https://journals.plos.org/x.pdf"}, {"pdf_url": "https://europepmc.org/y.pdf"}],
    "open_access": {"is_oa": True, "oa_status": "gold"},
    "biblio": {"volume": "21", "issue": "7", "first_page": "e1", "last_page": "e1"},
    "ids": {"openalex": "https://openalex.org/W1", "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12345"},
    "abstract_inverted_index": {"We": [0], "tested": [1], "it.": [2]},
}
WORK_CLOSED = {
    "id": "https://openalex.org/W2",
    "doi": "https://doi.org/10.1000/closed",
    "title": "A closed chapter",
    "publication_year": 2014,
    "type": "book-chapter",
    "authorships": [{"author_position": "first", "author": {"display_name": "Darrin T. Schultz"}}],
    "primary_location": {"source": {"display_name": "Advances in Something"}},
    "best_oa_location": None,
    "locations": [],
    "open_access": {"is_oa": False, "oa_status": "closed"},
    "biblio": {},
    "ids": {"openalex": "https://openalex.org/W2"},
}
WORK_PREPRINT = {
    "id": "https://openalex.org/W3",
    "doi": "https://doi.org/10.1101/2025.pre",
    "title": "A preprint",
    "publication_year": 2025,
    "type": "preprint",
    "authorships": [{"author_position": "first", "author": {"display_name": "Namrata Ahuja"}}],
    "primary_location": {"source": {"display_name": "bioRxiv"}},
    "best_oa_location": {"pdf_url": "https://www.biorxiv.org/p.pdf", "license": "cc-by-nc-nd"},
    "locations": [],
    "open_access": {"is_oa": True, "oa_status": "green"},
    "biblio": {},
    "ids": {"openalex": "https://openalex.org/W3"},
}


def test_helpers():
    assert name_to_bib("Darrin T. Schultz") == "Schultz, Darrin T."
    assert name_to_bib("Schultz, D.") == "Schultz, D."
    assert abstract_from_inverted({"b": [1], "a": [0]}) == "a b"
    assert license_value("cc-by", 2023) == "CC-BY-4.0"
    assert license_value("cc-by", 2010) == "CC-BY"
    assert license_value("cc-by-nc-nd", 2025) == "CC-BY-NC-ND-4.0"
    assert license_value("public-domain", 2000) == "public-domain"
    assert license_value(None, 2020) is None


def test_entry_from_work():
    key, etype, f = entry_from_work(WORK_OPEN, "0000-0003-1190-1122", set())
    assert key == "Ahuja2023" and etype == "article"
    assert f["author"] == "Ahuja, Namrata and Schultz, Darrin T."
    assert f["title"] == "An open paper" and f["journal"] == "PLoS ONE"
    assert f["volume"] == "21" and f["number"] == "7" and f["pages"] == "e1"
    assert f["doi"] == "10.1000/open" and f["license"] == "CC-BY-4.0"
    assert f["oapdf"] == "https://journals.plos.org/x.pdf" and f["oapdfalt"] == "https://europepmc.org/y.pdf"
    assert f["pmcid"] == "PMC12345" and f["openalex"] == "W1" and f["status"] == "published"
    assert f["abstract"] == "We tested it." and "serve" not in f
    key2, etype2, f2 = entry_from_work(WORK_CLOSED, "0000-0003-1190-1122", {"Schultz2014"})
    assert key2 == "Schultz2014a" and etype2 == "incollection"
    assert f2["serve"] == "false" and "license" not in f2
    _, _, f3 = entry_from_work(WORK_PREPRINT, "x", set())
    assert f3["status"] == "preprint" and f3["license"] == "CC-BY-NC-ND-4.0"


def test_run_import_is_idempotent_and_keeps_curation(node):
    r = run_import(node, "0000-0003-1190-1122", works=[WORK_OPEN, WORK_CLOSED, WORK_PREPRINT])
    assert r["added"] == ["Ahuja2023", "Schultz2014", "Ahuja2025"]
    assert r["closed_not_served"] == ["Schultz2014"]
    e = node.entry("Ahuja2023")
    e.set("title", "Curated title")
    e.set("license", "CC-BY-4.0")
    node.save_bib(node.load_bib()[:0] + [x if x.key != "Ahuja2023" else e for x in node.load_bib()])
    r2 = run_import(node, "0000-0003-1190-1122", works=[WORK_OPEN])
    assert r2["added"] == [] and r2["updated"] == ["Ahuja2023"]
    assert node.entry("Ahuja2023").get("title") == "Curated title"
    assert r2["total_entries"] == 3
