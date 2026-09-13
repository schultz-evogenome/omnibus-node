"""What leaves the node, and why each thing does or does not.

``plan()`` decides, per work, which layers are served at the work's tier
(capped by ``cap``); ``run_export()`` copies exactly that into a directory
with a manifest. ``serve`` uses the same plan in memory. PDFs in
``library/`` are never part of it.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import bibtex, sharing
from .node import Node
from .provenance import tool
from .rights import clearance

METADATA_FIELDS = (
    "title", "author", "year", "journal", "booktitle", "publisher", "volume", "number", "pages",
    "doi", "url", "license", "licenseurl", "status", "contributor", "added", "openalex", "pmcid", "abstract",
)


@dataclass
class WorkPlan:
    key: str
    tier: str
    entry: bibtex.Entry
    text: Path | None = None
    text_layer: str = "text"
    src_dir: Path | None = None
    note: Path | None = None
    figures: list[dict] = field(default_factory=list)  # asset records with servable files only
    excluded_files: int = 0

    @property
    def metadata(self) -> dict:
        md = {k: v for k, v in self.entry.fields.items() if k in METADATA_FIELDS}
        md["key"] = self.key
        md["type"] = self.entry.type
        md["tier"] = self.tier
        md["publication_clearance"] = clearance(self.entry.get("license"), self.entry.get("year"))
        return md


def plan(node: Node, cap: str = "all") -> tuple[list[WorkPlan], list[dict], bool]:
    """(included works, excluded works with reasons, whether shared notes are served)."""
    s = node.load_sharing()
    included: list[WorkPlan] = []
    excluded: list[dict] = []
    for e in node.load_bib():
        if not e.flag("serve", default=True):
            excluded.append({"key": e.key, "reason": e.get("servereason") or "serve=false"})
            continue
        tier = sharing.lowest(cap, node.tier_for(e, s))
        if tier == "none":
            excluded.append({"key": e.key, "reason": "tier none"})
            continue
        wp = WorkPlan(key=e.key, tier=tier, entry=e)
        status = e.get("status") or "published"
        wp.text_layer = "sources" if status == "draft" else "text"
        text = node.sources / e.key / "text.md"
        if text.exists() and sharing.allows(tier, wp.text_layer):
            wp.text = text
        src = node.sources / e.key / "src"
        if src.is_dir() and sharing.allows(tier, "sources"):
            wp.src_dir = src
        note = node.notes / f"{e.key}.md"
        if note.is_file() and sharing.allows(tier, "notes"):
            wp.note = note
        ay = node.assets / e.key / "asset.yaml"
        if ay.exists():
            doc = yaml.safe_load(ay.read_text(encoding="utf-8")) or {}
            for fig in doc.get("figures", []):
                stored = [f for f in fig.get("files", []) if f.get("path")]
                files = [f for f in stored if sharing.allows(tier, "figure_assets" if f.get("tier") == "assets" else "previews")]
                wp.excluded_files += len(stored) - len(files)
                if sharing.allows(tier, "figure_assets"):
                    # Offline originals: checksum and size are served, the file is not.
                    files += [f for f in fig.get("files", []) if not f.get("path")]
                rec = {k: v for k, v in fig.items() if k != "files"}
                rec["files"] = files
                wp.figures.append(rec)
        included.append(wp)
    shared_notes = sharing.allows(sharing.lowest(cap, s.defaults.share), "notes")
    return included, excluded, shared_notes


def run_export(node: Node, out: str | Path | None = None, cap: str = "all") -> dict:
    out_dir = Path(out).resolve() if out else node.export_dir
    if out_dir in (node.root, node.library, node.sources, node.assets, node.notes):
        raise ValueError(f"refusing to export into {out_dir}")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    works, excluded, shared_notes = plan(node, cap)
    bib_out: list[bibtex.Entry] = []
    manifest: dict = {
        "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": tool(),
        "cap": cap,
        "works": [],
        "excluded": excluded,
    }
    files_written = 0
    for wp in works:
        wdir = out_dir / "works" / wp.key
        wdir.mkdir(parents=True)
        rec = {"key": wp.key, "tier": wp.tier, "text": False, "figures": len(wp.figures), "files": 0}
        if wp.text:
            shutil.copy2(wp.text, wdir / "text.md")
            rec["text"] = True
            files_written += 1
        if wp.src_dir:
            shutil.copytree(wp.src_dir, wdir / "src")
            rec["sources"] = True
        if wp.note:
            shutil.copy2(wp.note, wdir / "note.md")
            rec["note"] = True
        if wp.figures:
            adir = wdir / "assets"
            adir.mkdir()
            for fig in wp.figures:
                for f in fig["files"]:
                    if not f.get("path"):
                        continue
                    src = node.assets / wp.key / f["path"]
                    dest = adir / f["path"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    rec["files"] += 1
                    files_written += 1
            (adir / "asset.yaml").write_text(
                yaml.safe_dump({"key": wp.key, "tier": wp.tier, "figures": wp.figures}, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        if wp.excluded_files:
            rec["files_withheld_by_tier"] = wp.excluded_files
        (wdir / "metadata.json").write_text(json.dumps(wp.metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        e = bibtex.Entry(wp.entry.type, wp.key, {k: v for k, v in wp.entry.fields.items() if k not in ("oapdf", "oapdfalt", "sha256", "file")})
        bib_out.append(e)
        manifest["works"].append(rec)
    if shared_notes and node.notes.exists():
        ndir = out_dir / "notes"
        ndir.mkdir()
        for p in node.notes.glob("*.md"):
            shutil.copy2(p, ndir / p.name)
        manifest["notes"] = True
    bibtex.save(out_dir / "references.bib", bib_out, header="Served view. PDFs and download URLs are not part of it.")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "out": str(out_dir),
        "cap": cap,
        "works": len(works),
        "excluded": len(excluded),
        "files": files_written,
        "notes": bool(manifest.get("notes")),
        "warnings": [],
    }
