"""``omnibus-node check``: is the node consistent, and is its library
something ``corpus run`` can build from?"""

from __future__ import annotations

import yaml
from pydantic import ValidationError

from . import sharing, tools
from .node import CONFIG, Node


def run_check(node: Node) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    info: list[str] = []

    entries = node.load_bib()
    keys = [e.key for e in entries]
    for k in sorted({k for k in keys if keys.count(k) > 1}):
        errors.append(f"duplicate bib key {k}")

    try:
        s = node.load_sharing()
    except ValidationError as exc:
        errors.append(f"sharing.yaml is invalid: {str(exc).splitlines()[0]}")
        s = sharing.Sharing()

    pdfs = {p.name for p in node.library.glob("*.pdf")} if node.library.exists() else set()
    ready = 0
    for e in entries:
        f = e.get("file")
        if f:
            if f in pdfs:
                if e.get("title"):
                    ready += 1
                else:
                    warnings.append(f"{e.key}: has a PDF but no title; corpus will fall back to Grobid's parse")
            elif e.get("oapdf"):
                warnings.append(f"{e.key}: file={f} is not in library/; run `omnibus-node fetch`")
            else:
                errors.append(f"{e.key}: file={f} is not in library/ and there is no oapdf= to fetch it from")
        share = e.get("share")
        if share and share not in sharing.TIERS:
            errors.append(f"{e.key}: share={share} is not a tier ({', '.join(sharing.TIERS)})")
        status = e.get("status")
        if status and status not in ("published", "preprint", "draft"):
            errors.append(f"{e.key}: status={status} must be published, preprint or draft")
        if not e.get("contributor") or not e.get("added"):
            warnings.append(f"{e.key}: missing contributor= or added= (who added it, and when)")
        if not e.get("license"):
            warnings.append(f"{e.key}: no license= recorded; figures will be reported as no_record")
        if not e.get("year"):
            warnings.append(f"{e.key}: no year")
    listed = {e.get("file") for e in entries if e.get("file")}
    for name in sorted(pdfs - listed):
        warnings.append(f"library/{name} has no bib entry with file={name}; corpus will still ingest it via Grobid")

    for d, what in ((node.sources, "sources"), (node.assets, "assets")):
        if d.exists():
            for sub in sorted(p for p in d.iterdir() if p.is_dir()):
                if sub.name not in keys:
                    warnings.append(f"{what}/{sub.name}/ has no bib entry")
    if node.assets.exists():
        for ay in sorted(node.assets.glob("*/asset.yaml")):
            try:
                doc = yaml.safe_load(ay.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                errors.append(f"{ay.relative_to(node.root)}: invalid YAML ({exc})")
                continue
            for fig in doc.get("figures", []):
                for f in fig.get("files", []):
                    if not (ay.parent / f["path"]).exists():
                        errors.append(f"{ay.parent.name}/{fig.get('id')}: listed file {f['path']} is missing")
                if fig.get("missing"):
                    warnings.append(f"{ay.parent.name}/{fig.get('id')}: {len(fig['missing'])} source file(s) were not found at ingest")

    if not (node.root / CONFIG).exists():
        warnings.append(f"no {CONFIG}; run `omnibus-node init` or `corpus init` before `corpus run`")
    for name, path in tools.available().items():
        if not path and name in ("pandoc", "pdftotext", "pdftoppm"):
            warnings.append(f"{name} is not installed ({tools.TOOLS[name][1]})")

    tiers = {}
    for e in entries:
        t = node.tier_for(e, s)
        tiers[t] = tiers.get(t, 0) + 1
    texts = sum(1 for e in entries if (node.sources / e.key / "text.md").exists())
    info.append(f"{len(entries)} works; {texts} with text; {ready} corpus-ready (PDF in library/ with metadata)")
    info.append("tiers: " + ", ".join(f"{k}={v}" for k, v in sorted(tiers.items(), key=lambda kv: sharing.rank(kv[0]))))

    lines = [f"error: {m}" for m in errors] + [f"warning: {m}" for m in warnings] + [f"  {m}" for m in info]
    lines.append("ok" if not errors else f"{len(errors)} error(s)")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "info": info, "lines": lines}
