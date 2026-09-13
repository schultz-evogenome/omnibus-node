"""Minimal BibTeX reader and writer.

Reads the subset that generated bibliographies use: ``@type{key, field =
{value}, ...}`` with balanced braces, ``"quoted"`` values, bare numbers, and
``#`` concatenation joined as plain text. It is the same subset corpus's own
parser reads (``bib/parser.py`` in caseywdunn/corpus), so a file this module
writes is a file ``corpus run`` accepts. Entry order and unknown fields are
preserved, so a hand-edited file round-trips.

Field names are lowercased. Whitespace inside a value is collapsed to single
spaces, which is how every consumer reads it anyway.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SKIP_TYPES = {"comment", "preamble", "string"}


@dataclass
class Entry:
    """One BibTeX entry. ``fields`` keeps insertion order."""

    type: str
    key: str
    fields: dict[str, str] = field(default_factory=dict)

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.fields.get(name.lower(), default)

    def set(self, name: str, value: str | None) -> None:
        """Set a field, or delete it when ``value`` is None or empty."""
        name = name.lower()
        if value is None or value == "":
            self.fields.pop(name, None)
        else:
            self.fields[name] = " ".join(str(value).split())

    def flag(self, name: str, default: bool = False) -> bool:
        """Read a yes/no field the way corpus reads ``serve``."""
        raw = self.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("true", "yes", "1", "y", "on")


def _match(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Index of the delimiter closing the one at ``start``, or -1."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and open_ch == "{":
                return i
        elif c == close_ch and close_ch == ")" and depth == 0:
            return i
        i += 1
    return -1


def _parse_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    pos = 0
    n = len(body)
    while True:
        while pos < n and (body[pos].isspace() or body[pos] == ","):
            pos += 1
        if pos >= n:
            break
        eq = body.find("=", pos)
        if eq < 0:
            break
        name = body[pos:eq].strip().lower()
        pos = eq + 1
        parts: list[str] = []
        while True:
            while pos < n and body[pos].isspace():
                pos += 1
            if pos >= n:
                break
            c = body[pos]
            if c == "{":
                end = _match(body, pos, "{", "}")
                if end < 0:
                    end = n
                parts.append(body[pos + 1 : end])
                pos = end + 1
            elif c == '"':
                end = body.find('"', pos + 1)
                if end < 0:
                    end = n
                parts.append(body[pos + 1 : end])
                pos = end + 1
            else:
                m = re.match(r"[^,\s#}]+", body[pos:])
                token = m.group(0) if m else ""
                parts.append(token)
                pos += max(len(token), 1)
            while pos < n and body[pos].isspace():
                pos += 1
            if pos < n and body[pos] == "#":
                pos += 1
                continue
            break
        if name:
            fields[name] = " ".join("".join(parts).split())
    return fields


def parse(text: str) -> list[Entry]:
    """Parse BibTeX text into entries. Comment lines (``%``) are skipped."""
    entries: list[Entry] = []
    i = 0
    n = len(text)
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        line_start = text.rfind("\n", 0, at) + 1
        if text[line_start:at].lstrip().startswith("%"):
            i = at + 1
            continue
        j = at + 1
        while j < n and (text[j].isalnum() or text[j] in "_-"):
            j += 1
        etype = text[at + 1 : j].strip().lower()
        k = j
        while k < n and text[k].isspace():
            k += 1
        if k >= n or text[k] not in "{(" or not etype:
            i = j
            continue
        open_ch = text[k]
        close_ch = "}" if open_ch == "{" else ")"
        end = _match(text, k, open_ch, close_ch)
        if end < 0:
            # Unbalanced entry: drop it and carry on at the next "@", so one
            # bad entry costs one entry rather than the rest of the file.
            i = at + 1
            continue
        body = text[k + 1 : end]
        i = end + 1
        if etype in _SKIP_TYPES:
            continue
        comma = body.find(",")
        if comma < 0:
            key, fields = body.strip(), {}
        else:
            key, fields = body[:comma].strip(), _parse_fields(body[comma + 1 :])
        if key:
            entries.append(Entry(etype, key, fields))
    return entries


def dumps(entries: list[Entry], header: str | None = None) -> str:
    """Serialise entries. ``header`` is written as ``%`` comment lines."""
    out: list[str] = []
    if header:
        out.extend("% " + line if line else "%" for line in header.rstrip().splitlines())
        out.append("")
    for e in entries:
        out.append(f"@{e.type}{{{e.key},")
        for name, value in e.fields.items():
            out.append(f"  {name} = {{{value}}},")
        out.append("}")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def load(path: str | Path) -> list[Entry]:
    p = Path(path)
    if not p.exists():
        return []
    return parse(p.read_text(encoding="utf-8"))


def save(path: str | Path, entries: list[Entry], header: str | None = None) -> None:
    Path(path).write_text(dumps(entries, header), encoding="utf-8")


def find(entries: list[Entry], key: str) -> Entry | None:
    for e in entries:
        if e.key == key:
            return e
    return None


def upsert(entries: list[Entry], key: str, etype: str, fields: dict[str, str | None]) -> Entry:
    """Create or update an entry. New fields override; others are kept."""
    e = find(entries, key)
    if e is None:
        e = Entry(etype, key, {})
        entries.append(e)
    elif etype and e.type != etype:
        e.type = etype
    for name, value in fields.items():
        e.set(name, value)
    return e


_KEY_CLEAN = re.compile(r"[^A-Za-z0-9]+")


def make_key(surname: str, year: str | int | None, existing: set[str] | None = None) -> str:
    """``Surname2023``, with ``a``, ``b``, ... appended to avoid collisions.

    This is the ``<Surname><Year>`` filename convention corpus recommends
    for PDFs, so the bib key doubles as the library filename stem.
    """
    base = _KEY_CLEAN.sub("", surname.split()[-1] if surname else "Anon") or "Anon"
    base = base[:1].upper() + base[1:]
    stem = f"{base}{year or 'nd'}"
    if not existing or stem not in existing:
        return stem
    for suffix in "abcdefghijklmnopqrstuvwxyz":
        cand = stem + suffix
        if cand not in existing:
            return cand
    n = 2
    while f"{stem}{n}" in existing:
        n += 1
    return f"{stem}{n}"
