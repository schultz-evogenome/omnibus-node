"""Who, when, and from what. Every entry the node writes carries these."""

from __future__ import annotations

import datetime as _dt
import hashlib
from pathlib import Path

from . import __version__


def today() -> str:
    return _dt.date.today().isoformat()


def tool() -> str:
    return f"omnibus-node {__version__}"


def stamp(contributor: str) -> dict[str, str]:
    """The fields added to every bib entry, asset record and note."""
    if not contributor:
        raise ValueError("a contributor (ORCID or GitHub login) is required")
    return {"contributor": contributor, "added": today(), "tool": tool()}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def is_orcid(value: str) -> bool:
    parts = value.split("-")
    if len(parts) != 4 or any(len(p) != 4 for p in parts):
        return False
    digits = "".join(parts)
    return digits[:-1].isdigit() and (digits[-1].isdigit() or digits[-1] == "X")
