"""License clearance, with corpus's vocabulary (dev_docs/LICENSING.md).

``publication_clearance`` is one of ``public_domain``, ``licensed_open``,
``restricted``, ``undetermined``, ``no_record``. Only ``restricted`` is a
recorded prohibition; ``no_record`` is the common case and is not evidence
of one. Output profiles decide what a figure tool does with the state:
``report`` (in-chat display) is permissive, ``manuscript`` and
``presentation`` refuse anything but ``public_domain`` and ``licensed_open``.
"""

from __future__ import annotations

import datetime as _dt

OPEN_LICENSES = {
    "public-domain",
    "cc0-1.0",
    "cc0",
    "cc-by-1.0",
    "cc-by-2.0",
    "cc-by-2.5",
    "cc-by-3.0",
    "cc-by-4.0",
    "cc-by",
    "cc-by-sa-3.0",
    "cc-by-sa-4.0",
    "cc-by-sa",
}
RESTRICTED_LICENSES = {
    "all-rights-reserved",
    "publisher-permission",
    "unknown",
    "cc-by-nc",
    "cc-by-nc-4.0",
    "cc-by-nc-3.0",
    "cc-by-nc-nd",
    "cc-by-nc-nd-4.0",
    "cc-by-nc-nd-3.0",
    "cc-by-nc-sa",
    "cc-by-nc-sa-4.0",
    "cc-by-nd",
    "cc-by-nd-4.0",
}
STRICT_PROFILES = ("manuscript", "presentation")
PROFILES = ("report",) + STRICT_PROFILES
PD_CUTOFF_YEARS = 95


def normalise(license_value: str | None) -> str | None:
    if not license_value:
        return None
    v = license_value.strip().lower().replace(" ", "-").replace("_", "-")
    return v


def clearance(license_value: str | None, year: str | int | None = None) -> str:
    lic = normalise(license_value)
    if lic:
        if lic == "public-domain":
            return "public_domain"
        if lic in OPEN_LICENSES:
            return "licensed_open"
        if lic in RESTRICTED_LICENSES:
            return "restricted"
        return "undetermined"
    try:
        y = int(str(year)[:4]) if year else None
    except ValueError:
        y = None
    if y and _dt.date.today().year - y > PD_CUTOFF_YEARS:
        return "public_domain"
    return "no_record"


def cleared_for(profile: str, state: str) -> bool:
    if profile not in STRICT_PROFILES:
        return True
    return state in ("public_domain", "licensed_open")


def attribution(fields: dict) -> str:
    """A citation-shaped attribution string for captions."""
    author = fields.get("author") or ""
    first = author.split(" and ")[0].strip()
    if "," in first:
        first = first.split(",")[0].strip()
    et_al = " et al." if " and " in author else ""
    year = fields.get("year") or "n.d."
    title = fields.get("title") or ""
    venue = fields.get("journal") or fields.get("publisher") or ""
    lic = fields.get("license") or "license not recorded"
    doi = fields.get("doi")
    parts = [f"{first}{et_al} ({year})", title, venue, lic]
    if doi:
        parts.append(f"https://doi.org/{doi}")
    return ". ".join(p for p in parts if p)
