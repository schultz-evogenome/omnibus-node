"""Sharing tiers: how much of a contributor's work leaves the node.

Tiers are cumulative. ``plots`` is the default a contributor gets by joining;
``none`` is opting out. A tier is set once per person and overridden per
item; the most specific setting wins.

    none    nothing
    plots   bibliographic metadata, figure previews with captions, and the
            text of works that are already published
    assets  + the files behind each figure: data, scripts, vector originals
    notes   + notes, decisions, dead ends
    all     + manuscript sources and the text of unpublished drafts

Two things sit outside the tiers. The PDFs in ``library/`` are never served
or exported, whatever the tier: the node publishes the authors' text, not
the publisher's file. And corpus's per-entry ``serve = {false}`` removes a
work entirely, as it does in a Corpus build.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["none", "plots", "assets", "notes", "all"]
TIERS: tuple[str, ...] = ("none", "plots", "assets", "notes", "all")

# Layer -> the lowest tier that serves it.
LAYERS: dict[str, str] = {
    "metadata": "plots",
    "previews": "plots",
    "text": "plots",
    "figure_assets": "assets",
    "notes": "notes",
    "sources": "all",
}

NEVER_SERVED = ("library",)


def rank(tier: str) -> int:
    return TIERS.index(tier)


def lowest(a: str, b: str) -> str:
    return a if rank(a) <= rank(b) else b


def allows(tier: str, layer: str) -> bool:
    return rank(tier) >= rank(LAYERS[layer])


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    share: Tier = "plots"


class Person(BaseModel):
    """Keyed by ORCID when the person has one, otherwise a GitHub login."""

    model_config = ConfigDict(extra="forbid")
    share: Optional[Tier] = None
    name: Optional[str] = None
    github: Optional[str] = None


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    share: Optional[Tier] = None
    reason: Optional[str] = None


class Sharing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defaults: Defaults = Field(default_factory=Defaults)
    people: dict[str, Person] = Field(default_factory=dict)
    items: dict[str, Item] = Field(default_factory=dict)

    def resolve(self, key: str | None = None, contributor: str | None = None) -> str:
        """Effective tier for an item: item > contributor > defaults."""
        if key and key in self.items and self.items[key].share:
            return self.items[key].share
        if contributor and contributor in self.people and self.people[contributor].share:
            return self.people[contributor].share
        return self.defaults.share

    def person_name(self, contributor: str | None) -> str | None:
        if contributor and contributor in self.people:
            return self.people[contributor].name
        return None


def load(path: str | Path) -> Sharing:
    p = Path(path)
    if not p.exists():
        return Sharing()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Sharing.model_validate(data)


def save(path: str | Path, sharing: Sharing) -> None:
    data = sharing.model_dump(exclude_none=True)
    text = (
        "# Sharing tiers: none < plots < assets < notes < all. Cumulative.\n"
        "# defaults.share applies to everyone; people.<orcid-or-github>.share\n"
        "# overrides it; items.<bibkey>.share overrides that.\n"
        "# PDFs in library/ are never served, whatever the tier.\n"
    )
    text += yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    Path(path).write_text(text, encoding="utf-8")
