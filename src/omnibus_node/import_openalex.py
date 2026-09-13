"""``omnibus-node import-openalex``: a bib entry for every work OpenAlex
lists under an ORCID.

OpenAlex (api.openalex.org) knows each work's authors, venue, DOI, the
license of its best open-access location, where a PDF can be fetched, and
its PubMed Central id. That is enough to seed ``references.bib`` so that
``fetch`` and ``fetch --text`` can do the rest. Curated fields in an existing
entry are never overwritten.

Licenses come as OpenAlex reports them (``cc-by``, ``cc-by-nc-nd``,
``public-domain``). Creative Commons licenses are recorded with version 4.0
when the work appeared in 2014 or later (CC 4.0 was released in late 2013),
otherwise unversioned; ``licensesource = {openalex}`` says where the value
came from. A work with no open-access location is entered with
``serve = {false}`` and a reason, so it counts but is not served until the
authors supply their text.
"""

from __future__ import annotations

import re

import requests

from . import __version__, bibtex
from .node import Node
from .provenance import today

API = "https://api.openalex.org/works"
UA = f"omnibus-node/{__version__} (+https://github.com/schultz-evogenome/omnibus-node)"

TYPE_MAP = {
    "article": "article",
    "review": "article",
    "preprint": "article",
    "letter": "article",
    "erratum": "article",
    "editorial": "article",
    "book-chapter": "incollection",
    "book": "book",
    "conference-abstract": "inproceedings",
    "paratext": "misc",
    "dataset": "misc",
    "software": "software",
}


def fetch_works(orcid: str, mailto: str | None = None, session: requests.Session | None = None) -> list[dict]:
    session = session or requests.Session()
    session.headers.update({"User-Agent": UA})
    works: list[dict] = []
    cursor = "*"
    while cursor:
        params = {"filter": f"author.orcid:{orcid}", "per-page": 200, "cursor": cursor, "sort": "publication_year:desc"}
        if mailto:
            params["mailto"] = mailto
        r = session.get(API, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        works.extend(data.get("results", []))
        cursor = (data.get("meta") or {}).get("next_cursor")
    return works


def abstract_from_inverted(index: dict | None) -> str | None:
    if not index:
        return None
    positions: list[tuple[int, str]] = []
    for word, at in index.items():
        for i in at:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def name_to_bib(display: str) -> str:
    display = " ".join((display or "").split())
    if not display:
        return "Anon"
    if "," in display:
        return display
    parts = display.split(" ")
    if len(parts) == 1:
        return display
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def surname(display: str) -> str:
    return name_to_bib(display).split(",")[0].strip()


def license_value(oa_license: str | None, year: int | None) -> str | None:
    if not oa_license:
        return None
    v = oa_license.strip().lower()
    if v in ("public-domain", "pd"):
        return "public-domain"
    if v == "cc0":
        return "CC0-1.0"
    if v.startswith("cc-"):
        base = v.upper()
        if year and year >= 2014 and not re.search(r"\d", base):
            return f"{base}-4.0"
        return base
    return oa_license


def _pmcid(ids: dict) -> str | None:
    raw = (ids or {}).get("pmcid") or ""
    m = re.search(r"(PMC\d+)", raw, re.I)
    return m.group(1).upper() if m else None


def entry_from_work(work: dict, orcid: str, existing_keys: set[str]) -> tuple[str, str, dict[str, str]]:
    year = work.get("publication_year")
    authorships = work.get("authorships") or []
    first = authorships[0]["author"].get("display_name") if authorships else None
    key = bibtex.make_key(surname(first or "Anon"), year, existing_keys)
    wtype = work.get("type") or "article"
    etype = TYPE_MAP.get(wtype, "misc")
    primary = work.get("primary_location") or {}
    source = (primary.get("source") or {}).get("display_name")
    best = work.get("best_oa_location") or {}
    oa = work.get("open_access") or {}
    biblio = work.get("biblio") or {}
    doi = (work.get("doi") or "").replace("https://doi.org/", "")
    ids = work.get("ids") or {}

    fields: dict[str, str] = {}
    fields["author"] = " and ".join(name_to_bib(a["author"].get("display_name") or a.get("raw_author_name") or "") for a in authorships)
    fields["title"] = (work.get("title") or work.get("display_name") or "").rstrip(".")
    if year:
        fields["year"] = str(year)
    if source:
        fields["journal"] = source
    if biblio.get("volume"):
        fields["volume"] = biblio["volume"]
    if biblio.get("issue"):
        fields["number"] = biblio["issue"]
    if biblio.get("first_page"):
        fields["pages"] = biblio["first_page"] + (f"--{biblio['last_page']}" if biblio.get("last_page") and biblio["last_page"] != biblio["first_page"] else "")
    if doi:
        fields["doi"] = doi
        fields["url"] = f"https://doi.org/{doi}"
    elif best.get("landing_page_url"):
        fields["url"] = best["landing_page_url"]
    abstract = abstract_from_inverted(work.get("abstract_inverted_index"))
    if abstract:
        fields["abstract"] = abstract
    fields["worktype"] = wtype
    fields["status"] = "preprint" if wtype == "preprint" else "published"
    lic = license_value(best.get("license"), year)
    if lic:
        fields["license"] = lic
        fields["licensesource"] = "openalex"
    if oa.get("oa_status"):
        fields["oastatus"] = oa["oa_status"]
    pdfs: list[str] = []
    if best.get("pdf_url"):
        pdfs.append(best["pdf_url"])
    for loc in work.get("locations") or []:
        u = loc.get("pdf_url")
        if u and u not in pdfs:
            pdfs.append(u)
    if pdfs:
        fields["oapdf"] = pdfs[0]
        if len(pdfs) > 1:
            fields["oapdfalt"] = " ; ".join(pdfs[1:])
    pmc = _pmcid(ids)
    if pmc:
        fields["pmcid"] = pmc
    if ids.get("openalex"):
        fields["openalex"] = ids["openalex"].rsplit("/", 1)[-1]
    if not oa.get("is_oa"):
        fields["serve"] = "false"
        fields["servereason"] = "no open-access version; add the authors' text and set serve=true"
    fields["contributor"] = orcid
    fields["added"] = today()
    return key, etype, fields


def run_import(node: Node, orcid: str, mailto: str | None = None, works: list[dict] | None = None) -> dict:
    works = works if works is not None else fetch_works(orcid, mailto)
    entries = node.load_bib()
    by_doi = {e.get("doi", "").lower(): e for e in entries if e.get("doi")}
    by_openalex = {e.get("openalex"): e for e in entries if e.get("openalex")}
    existing_keys = {e.key for e in entries}
    added: list[str] = []
    updated: list[str] = []
    closed: list[str] = []
    for w in works:
        key, etype, fields = entry_from_work(w, orcid, existing_keys)
        doi = fields.get("doi", "").lower()
        match = by_doi.get(doi) if doi else None
        if match is None and fields.get("openalex"):
            match = by_openalex.get(fields["openalex"])
        if match is not None:
            for k, v in fields.items():
                if k in ("added", "contributor"):
                    continue
                if not match.get(k):
                    match.set(k, v)
            updated.append(match.key)
        else:
            entries.append(bibtex.Entry(etype, key, {}))
            bibtex.upsert(entries, key, etype, fields)
            existing_keys.add(key)
            added.append(key)
            if doi:
                by_doi[doi] = entries[-1]
        if fields.get("serve") == "false":
            closed.append(key if match is None else match.key)
    node.save_bib(entries)
    return {
        "works_seen": len(works),
        "added": added,
        "updated": updated,
        "closed_not_served": closed,
        "total_entries": len(entries),
        "warnings": [f"{k}: no open-access version, entered with serve=false" for k in closed],
    }
