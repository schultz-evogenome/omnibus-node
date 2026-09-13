"""``omnibus-node fetch``: bring in what the bibliography points at.

PDFs named by ``oapdf =`` (and the ``;``-separated alternates in
``oapdfalt =``) are downloaded into ``library/`` for corpus. Publishers
differ in whether they serve a PDF to a script; the report says which files
need to be saved by hand.

``--text`` fetches the full-text XML of every work with a ``pmcid =`` from
Europe PMC and writes ``sources/<key>/text.md`` from it, with the figure
captions and, when available, the figure images. That is the authors' text
of the open-access version, which is what the node publishes.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from . import __version__, tools
from .ingest.common import Figure, Ingested, figure_number, materialize, write_text
from .node import Node
from .provenance import sha256_file, stamp, today

UA = f"omnibus-node/{__version__} (+https://github.com/schultz-evogenome/omnibus-node)"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
XLINK = "{http://www.w3.org/1999/xlink}"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/pdf, application/xml, text/xml, */*"})
    return s


def fetch_pdf(session: requests.Session, url: str, retries: int = 2) -> tuple[bytes | None, str]:
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=90, allow_redirects=True)
        except requests.RequestException as exc:
            return None, f"{type(exc).__name__}"
        if r.status_code == 429 and attempt < retries:
            time.sleep(8 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        if r.content[:5] == b"%PDF-":
            return r.content, "ok"
        return None, "not a PDF (landing page)"
    return None, "HTTP 429"


def run_fetch(node: Node, keys: list[str] | None = None, force: bool = False, delay: float = 1.0) -> dict:
    entries = node.load_bib()
    node.library.mkdir(exist_ok=True)
    session = _session()
    ok: list[str] = []
    skipped: list[str] = []
    failed: list[dict] = []
    for e in entries:
        if keys and e.key not in keys:
            continue
        dest = node.library / f"{e.key}.pdf"
        if dest.exists() and not force:
            if e.get("file") != dest.name or not e.get("sha256"):
                e.set("file", dest.name)
                e.set("sha256", sha256_file(dest))
            skipped.append(e.key)
            continue
        urls = [u.strip() for u in [e.get("oapdf") or ""] + (e.get("oapdfalt") or "").split(";") if u.strip()]
        if not urls:
            skipped.append(e.key)
            continue
        reasons: list[str] = []
        for url in urls:
            content, reason = fetch_pdf(session, url)
            if content:
                dest.write_bytes(content)
                e.set("file", dest.name)
                e.set("sha256", sha256_file(dest))
                ok.append(e.key)
                break
            reasons.append(f"{url.split('/')[2]}: {reason}")
            time.sleep(delay)
        else:
            failed.append({"key": e.key, "reasons": reasons})
        time.sleep(delay)
    node.save_bib(entries)
    advice = ""
    if failed:
        advice = (
            "Some publishers do not serve PDFs to scripts. Download those while signed in and save each as "
            "library/<Key>.pdf; `omnibus-node fetch` will then record its checksum."
        )
    return {"downloaded": ok, "already_present_or_no_url": len(skipped), "failed": failed, "advice": advice}


# --- Europe PMC full text --------------------------------------------------


def lookup_pmcid(session: requests.Session, doi: str) -> str | None:
    """Europe PMC's search resolves a DOI to an id with full text: a PMC id
    for an article in PubMed Central, or a PPR id for a preprint whose full
    text Europe PMC holds. OpenAlex often lacks both."""
    try:
        r = session.get(f"{EUROPEPMC}/search", params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 5}, timeout=60)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        hits = r.json().get("resultList", {}).get("result", [])
    except ValueError:
        return None
    for hit in hits:
        if hit.get("pmcid"):
            return hit["pmcid"]
    for hit in hits:
        if hit.get("source") == "PPR" and str(hit.get("hasFullTextXML", "")).upper() == "Y":
            return hit.get("id")
    return None


def europepmc_xml(session: requests.Session, pmcid: str) -> str | None:
    pmcid = pmcid.upper()
    if not pmcid.startswith(("PMC", "PPR")):
        pmcid = "PMC" + pmcid
    r = session.get(f"{EUROPEPMC}/{pmcid}/fullTextXML", timeout=90)
    if r.status_code != 200 or not r.text.lstrip().startswith("<"):
        return None
    return r.text


def _text_of(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return " ".join("".join(el.itertext()).split())


def jats_figures(xml_text: str) -> list[Figure]:
    """Figures from JATS ``<fig>`` elements: label, caption, graphic name."""
    root = ET.fromstring(xml_text)
    figs: list[Figure] = []
    for n, fig in enumerate(root.iter("fig"), start=1):
        label = _text_of(fig.find("label"))
        caption = _text_of(fig.find("caption"))
        number = figure_number(label) or str(n)
        f = Figure(id=f"fig{n}", caption=caption, number=number, label=label or None)
        f.caption_confidence = "high" if caption else "low"
        for g in fig.iter("graphic"):
            href = g.get(XLINK + "href") or g.get("href")
            if href:
                f.missing.append(href)  # resolved to a download below
        figs.append(f)
    return figs


def jats_to_markdown(xml_text: str, warnings: list[str]) -> str:
    exe = tools.find("pandoc")
    if exe:
        try:
            r = tools.run([exe, "-f", "jats", "-t", "gfm", "--wrap=none"], input_text=xml_text, timeout=300)
            if r.stdout.strip():
                return r.stdout
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"pandoc could not convert the JATS XML ({str(exc)[:100]}); used plain text")
    else:
        warnings.append("pandoc is not installed; the JATS XML was reduced to plain text")
    root = ET.fromstring(xml_text)
    body = root.find(".//body")
    paras = [_text_of(p) for p in (body.iter("p") if body is not None else root.iter("p"))]
    return "\n\n".join(p for p in paras if p) + "\n"


def run_fetch_text(
    node: Node,
    contributor: str | None = None,
    keys: list[str] | None = None,
    force: bool = False,
    images: bool = True,
    delay: float = 1.0,
) -> dict:
    entries = node.load_bib()
    session = _session()
    written: list[str] = []
    skipped: list[str] = []
    failed: list[dict] = []
    all_warnings: list[str] = []
    looked_up = 0
    for e in entries:
        if keys and e.key not in keys:
            continue
        pmcid = e.get("pmcid")
        if not pmcid and e.get("doi") and not e.get("pmcidchecked"):
            pmcid = lookup_pmcid(session, e.get("doi"))
            e.set("pmcidchecked", today())
            if pmcid:
                e.set("pmcid", pmcid)
            looked_up += 1
            time.sleep(delay / 2)
        if not pmcid:
            skipped.append(e.key)
            continue
        text_path = node.sources / e.key / "text.md"
        if text_path.exists() and not force:
            skipped.append(e.key)
            continue
        xml_text = europepmc_xml(session, pmcid)
        if not xml_text:
            failed.append({"key": e.key, "pmcid": pmcid, "reason": "no full text at Europe PMC"})
            time.sleep(delay)
            continue
        warnings: list[str] = []
        tmp = tempfile.TemporaryDirectory(prefix="omnibus-jats-")
        xml_path = Path(tmp.name) / f"{e.key}.jats.xml"
        xml_path.write_text(xml_text, encoding="utf-8")
        figs = jats_figures(xml_text)
        if images:
            pmc = pmcid.upper() if pmcid.upper().startswith(("PMC", "PPR")) else "PMC" + pmcid
            for fig in figs:
                hrefs, fig.missing = fig.missing, []
                for href in hrefs:
                    got = False
                    for cand in (href, href + ".jpg", href + ".png"):
                        r = session.get(f"https://europepmc.org/articles/{pmc}/bin/{cand}", timeout=60)
                        if r.status_code == 200 and r.content[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb"):
                            ext = ".png" if r.content[:4] == b"\x89PNG" else ".jpg"
                            out = Path(tmp.name) / f"{fig.id}{ext}"
                            out.write_bytes(r.content)
                            fig.files.append(out)
                            got = True
                            break
                    if not got:
                        fig.missing.append(href)
                        warnings.append(f"{fig.id}: image {href} not available from Europe PMC")
        ing = Ingested(
            format="jats",
            source=xml_path,
            text=jats_to_markdown(xml_text, warnings),
            title=e.get("title"),
            figures=figs,
            extras={"source_url": f"{EUROPEPMC}/{pmcid}/fullTextXML"},
            warnings=warnings,
            tmp=tmp,
        )
        st = stamp(contributor or e.get("contributor") or "unknown")
        try:
            write_text(node, e.key, ing, st, e.get("status") or "published")
            if figs:
                materialize(node, e.key, figs, st, None, warnings)
        finally:
            ing.cleanup()
        written.append(e.key)
        all_warnings.extend(f"{e.key}: {w}" for w in warnings)
        time.sleep(delay)
    if looked_up:
        node.save_bib(entries)
    return {
        "written": written,
        "pmcids_looked_up": looked_up,
        "skipped_no_pmcid_or_existing": len(skipped),
        "failed": failed,
        "warnings": all_warnings,
    }
