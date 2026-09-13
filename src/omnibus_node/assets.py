"""``omnibus-node assets``: a figure folder into figure assets.

A manuscript's figure folder holds many versions of each figure, the data
behind it, and the scripts that drew it. A small ``figures.yaml`` says which
file is the final one and what belongs with it:

    key: Schultz2023a
    base: .                       # paths below are relative to this (default: the yaml's folder)
    figures:
      - id: fig1
        caption: "..."            # or caption_from_text: 1  (the "Fig. 1" legend in sources/<key>/text.md)
        original: FIG1/FIG1_v12.ai   # one file, or a list of panel files
        data: [tables/table1.tsv, "dots/*.tsv"]
        scripts: [scripts/plot_fig1.py]
        notes: why v12 is the final version

The final file and a PNG preview go to tier ``plots``; the vector original,
data and scripts to tier ``assets``. Every file is checksummed and its
origin recorded relative to ``base``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .ingest.common import POPPLER_RENDERS, RASTER, captions_from_text, make_preview, read_asset_yaml, read_text, write_asset_yaml
from .node import Node
from .provenance import sha256_file, stamp


class FigureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    original: str | list[str] | None = None  # none for a data-only entry (a table, supplementary data)
    caption: str | None = None
    caption_from_text: str | int | None = None
    data: list[str] = Field(default_factory=list)
    scripts: list[str] = Field(default_factory=list)
    # Files too large for the repository (a 170 MB Illustrator original):
    # recorded with size and checksum, never copied. The org keeps large
    # data out of git and carries checksums instead.
    offline: list[str] = Field(default_factory=list)
    notes: str | None = None


class FiguresSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    base: str | None = None
    figures: list[FigureSpec]


def load_spec(path: Path) -> tuple[FiguresSpec, Path]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    spec = FiguresSpec.model_validate(data)
    base = (path.parent / spec.base).resolve() if spec.base else path.parent.resolve()
    return spec, base


def _expand(patterns: list[str], base: Path) -> tuple[list[Path], list[str]]:
    found: list[Path] = []
    missing: list[str] = []
    for pat in patterns:
        matches = sorted(base.glob(pat)) if any(ch in pat for ch in "*?[") else [base / pat]
        matches = [m for m in matches if m.is_file()]
        if matches:
            found.extend(matches)
        else:
            missing.append(pat)
    return found, missing


def _copy(src: Path, dest: Path, role: str, tier: str, base: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    try:
        origin = str(src.resolve().relative_to(base))
    except ValueError:
        origin = src.name
    return {"path": str(dest), "role": role, "tier": tier, "sha256": sha256_file(dest), "from": origin}


def run_assets(node: Node, spec_path: str | Path, contributor: str) -> dict:
    spec_path = Path(spec_path).resolve()
    spec, base = load_spec(spec_path)
    st = stamp(contributor)
    adir = node.assets / spec.key
    adir.mkdir(parents=True, exist_ok=True)
    legends: dict[str, str] = {}
    txt = read_text(node, spec.key)
    if txt:
        legends = captions_from_text(txt[1])
    # Caption-only records left by `fetch --text` (Europe PMC legends, no
    # files), keyed by figure number. A spec figure with the same number
    # takes the caption and replaces that record.
    prior = {str(r.get("number")): r for r in read_asset_yaml(adir).get("figures", []) if r.get("number")}
    consumed: set[str] = set()
    warnings: list[str] = []
    records: list[dict] = []
    for fig in spec.figures:
        rec: dict = {"id": fig.id, "caption": fig.caption or "", "caption_confidence": "high" if fig.caption else "low"}
        if fig.caption_from_text is not None:
            num = str(fig.caption_from_text)
            rec["number"] = num
            if num in prior and prior[num].get("caption"):
                rec["caption"] = prior[num]["caption"]
                rec["caption_confidence"] = prior[num].get("caption_confidence", "high")
                if prior[num].get("label"):
                    rec["label"] = prior[num]["label"]
                if prior[num]["id"] != fig.id and not any(f.get("path") for f in prior[num].get("files", [])):
                    consumed.add(prior[num]["id"])
            elif num in legends:
                rec["caption"] = legends[num]
                rec["caption_confidence"] = "medium"
            else:
                warnings.append(f"{fig.id}: no legend for figure {num} in sources/{spec.key}/text.md or assets/{spec.key}/asset.yaml")
        if fig.notes:
            rec["notes"] = fig.notes
        files: list[dict] = []
        originals = [] if fig.original is None else ([fig.original] if isinstance(fig.original, str) else list(fig.original))
        missing: list[str] = []
        for n, name in enumerate(originals):
            src = base / name
            if not src.is_file():
                missing.append(name)
                continue
            ext = src.suffix.lower()
            stem = fig.id if len(originals) == 1 else f"{fig.id}-{chr(97 + n)}"
            dest = adir / f"{stem}{ext}"
            if ext in RASTER or ext == ".svg":
                files.append(_copy(src, dest, "plot", "plots", base))
            else:
                files.append(_copy(src, dest, "original", "assets", base))
                if ext in POPPLER_RENDERS:
                    prev = make_preview(dest, adir / f"{stem}.png", warnings)
                    if prev:
                        files.append({"path": str(prev), "role": "preview", "tier": "plots", "sha256": sha256_file(prev)})
                else:
                    warnings.append(f"{dest.name}: no preview for {ext} files")
        for role, patterns in (("data", fig.data), ("script", fig.scripts)):
            found, miss = _expand(patterns, base)
            missing.extend(miss)
            for src in found:
                dest = adir / fig.id / (role + "s") / src.name
                files.append(_copy(src, dest, role, "assets", base))
        for f in files:
            f["path"] = str(Path(f["path"]).relative_to(adir))
        found, miss = _expand(fig.offline, base)
        missing.extend(miss)
        for src in found:
            try:
                origin = str(src.resolve().relative_to(base))
            except ValueError:
                origin = src.name
            files.append(
                {"from": origin, "role": "original", "tier": "assets", "stored": False, "bytes": src.stat().st_size, "sha256": sha256_file(src)}
            )
        rec["files"] = files
        if missing:
            rec["missing"] = missing
            warnings.append(f"{fig.id}: not found: {', '.join(missing)}")
        records.append(rec)
    doc = write_asset_yaml(adir, spec.key, st, records, drop_ids=consumed)
    if node.entry(spec.key) is None:
        node.upsert_entry(spec.key, "misc", {"contributor": st["contributor"], "added": st["added"]})
        warnings.append(f"{spec.key} had no bib entry; a minimal one was created, add its metadata")
    return {
        "key": spec.key,
        "figures": len(records),
        "files": sum(len(r["files"]) for r in records),
        "assets": str((adir / "asset.yaml").relative_to(node.root)),
        "warnings": warnings,
        "doc": doc,
    }
