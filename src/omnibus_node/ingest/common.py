"""Shared pieces of every ingester: the result shape, figure materialisation,
caption detection, and writing ``sources/<key>/text.md``."""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import tools
from ..node import Node
from ..provenance import sha256_file

RASTER = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
POPPLER_RENDERS = {".pdf", ".ai"}  # Illustrator files are PDF-compatible
OTHER_IMAGE = {".svg", ".eps", ".tif", ".tiff"}
IMAGE_EXTS = RASTER | POPPLER_RENDERS | OTHER_IMAGE

# "Figure 3." / "Fig. S2 |" / "**Extended Data Fig. 1.**" at the start of a paragraph.
CAPTION_RE = re.compile(
    r"^\s*(?:\*\*|__)?\s*"
    r"((?:Supplementary|Supplemental|Extended\s+Data)\s+)?"
    r"(?:Fig(?:ure)?|FIG(?:URE)?)\.?\s*"
    r"(S?\d+)\s*[.:|]?\s*(?:\*\*|__)?\s*(.*)",
    re.S,
)


def figure_number(label: str) -> str | None:
    """A figure key from a label: ``Fig. 3`` -> ``3``, ``Fig. S2`` -> ``S2``,
    ``Extended Data Fig. 1`` -> ``ED1``, ``Supplementary Figure 4`` -> ``S4``."""
    m = re.search(r"(Supplementary|Supplemental|Extended\s+Data)?\s*(?:Fig(?:ure)?|FIG(?:URE)?)\.?\s*(S?\d+)", label or "", re.I)
    if not m:
        m2 = re.search(r"(S?\d+)", label or "")
        return m2.group(1) if m2 else None
    prefix, num = (m.group(1) or "").lower(), m.group(2).upper()
    if prefix.startswith("extended"):
        return "ED" + num.lstrip("S")
    if prefix.startswith("supplement") and not num.startswith("S"):
        return "S" + num
    return num


@dataclass
class Figure:
    id: str
    caption: str = ""
    label: str | None = None
    number: str | None = None
    files: list[Path] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    panels: list[str] = field(default_factory=list)
    caption_confidence: str = "high"


@dataclass
class Ingested:
    format: str
    source: Path
    text: str
    title: str | None = None
    figures: list[Figure] = field(default_factory=list)
    extras: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    tmp: tempfile.TemporaryDirectory | None = None

    def cleanup(self) -> None:
        if self.tmp is not None:
            self.tmp.cleanup()
            self.tmp = None


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def caption_match(paragraph: str) -> tuple[str, str] | None:
    """(figure number, caption text) when a paragraph reads as a legend."""
    m = CAPTION_RE.match(paragraph)
    if not m:
        return None
    prefix, number, body = (m.group(1) or "").lower(), m.group(2).upper(), m.group(3).strip()
    if len(body) < 8:
        return None
    if prefix.startswith("extended"):
        number = "ED" + number.lstrip("S")
    elif prefix.startswith("supplement") and not number.startswith("S"):
        number = "S" + number
    return number, " ".join(body.split())


def captions_from_text(text: str) -> dict[str, str]:
    """Figure number -> legend, from the first paragraph that reads as one."""
    found: dict[str, str] = {}
    for p in paragraphs(text):
        m = caption_match(p)
        if m and m[0] not in found:
            found[m[0]] = m[1]
    return found


def pair_captions(figures: list[Figure], legends: dict[str, str]) -> None:
    """Give figures without captions the legend with the same number, else
    the n-th legend in order, marking the guess as low confidence."""
    ordered = list(legends.values())
    for i, fig in enumerate(figures):
        if fig.caption:
            continue
        if fig.number and fig.number in legends:
            fig.caption = legends[fig.number]
            fig.caption_confidence = "medium"
        elif i < len(ordered):
            fig.caption = ordered[i]
            fig.caption_confidence = "low"


def relative_origin(path: Path, root: Path | None) -> str:
    """How a file is recorded in asset.yaml: relative to the manuscript when
    it is inside it, otherwise just the filename. Never an absolute path."""
    if root is not None:
        try:
            return str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            pass
    return path.name


def make_preview(original: Path, dest_png: Path, warnings: list[str]) -> Path | None:
    """PNG preview of a vector figure via poppler. Raster and SVG files are
    their own preview and return None."""
    ext = original.suffix.lower()
    if ext not in POPPLER_RENDERS:
        return None
    exe = tools.find("pdftoppm")
    if not exe:
        warnings.append(f"{original.name}: no preview, pdftoppm (poppler) is not installed")
        return None
    prefix = dest_png.with_suffix("")
    try:
        tools.run([exe, "-png", "-r", "150", "-f", "1", "-l", "1", "-singlefile", str(original), str(prefix)])
    except Exception as exc:  # noqa: BLE001 - report, don't abort the ingest
        warnings.append(f"{original.name}: preview failed ({exc})")
        return None
    return dest_png if dest_png.exists() else None


def _file_record(path: Path, role: str, tier: str, origin: str | None = None) -> dict:
    rec = {"path": path.name, "role": role, "tier": tier, "sha256": sha256_file(path)}
    if origin:
        rec["from"] = origin
    return rec


def materialize(
    node: Node,
    key: str,
    figures: list[Figure],
    stamp: dict[str, str],
    source_root: Path | None,
    warnings: list[str],
) -> dict:
    """Copy figure files into ``assets/<key>/``, make previews, and write
    ``asset.yaml`` (merging with an existing one by figure id)."""
    adir = node.assets / key
    adir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for fig in figures:
        rec: dict = {
            "id": fig.id,
            "caption": fig.caption,
            "caption_confidence": fig.caption_confidence,
        }
        if fig.label:
            rec["label"] = fig.label
        if fig.number:
            rec["number"] = fig.number
        if fig.panels:
            rec["panels"] = fig.panels
        rec["files"] = []
        for n, src in enumerate(fig.files):
            ext = src.suffix.lower()
            base = fig.id if len(fig.files) == 1 else f"{fig.id}-{chr(97 + n)}"
            dest = adir / f"{base}{ext}"
            shutil.copy2(src, dest)
            origin = relative_origin(src, source_root)
            if ext in RASTER or ext == ".svg":
                rec["files"].append(_file_record(dest, "plot", "plots", origin))
            else:
                rec["files"].append(_file_record(dest, "original", "assets", origin))
                if ext in POPPLER_RENDERS:
                    prev = make_preview(dest, adir / f"{base}.png", warnings)
                    if prev:
                        rec["files"].append(_file_record(prev, "preview", "plots"))
                else:
                    warnings.append(f"{dest.name}: no preview for {ext} files")
        if fig.missing:
            rec["missing"] = list(fig.missing)
        records.append(rec)
    return write_asset_yaml(adir, key, stamp, records)


def read_asset_yaml(adir: Path) -> dict:
    path = adir / "asset.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_asset_yaml(adir: Path, key: str, stamp: dict[str, str], records: list[dict], drop_ids: set[str] | None = None) -> dict:
    """Merge ``records`` into ``asset.yaml`` by figure id. ``drop_ids`` names
    existing records that were folded into a new one (a caption-only record
    from a full-text fetch, now joined with the lab's figure files)."""
    path = adir / "asset.yaml"
    existing = read_asset_yaml(adir)
    by_id = {r["id"]: r for r in existing.get("figures", []) if r["id"] not in (drop_ids or set())}
    for r in records:
        by_id[r["id"]] = r
    doc = {"key": key, **stamp, "figures": list(by_id.values())}
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return doc


def write_text(node: Node, key: str, ing: Ingested, stamp: dict[str, str], status: str) -> Path:
    sdir = node.sources / key
    sdir.mkdir(parents=True, exist_ok=True)
    front: dict = {"key": key}
    if ing.title:
        front["title"] = ing.title
    front.update(
        {
            "format": ing.format,
            "source": ing.source.name,
            "source_sha256": sha256_file(ing.source),
            "status": status,
        }
    )
    front.update(stamp)
    if ing.figures:
        front["figures"] = [f.id for f in ing.figures]
    for k in ("abstract", "pages", "bibfile"):
        if ing.extras.get(k):
            front[k] = ing.extras[k]
    body = ing.text.strip() + "\n"
    text = "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n\n" + body
    dest = sdir / "text.md"
    dest.write_text(text, encoding="utf-8")
    return dest


def read_text(node: Node, key: str) -> tuple[dict, str] | None:
    """Front matter and body of ``sources/<key>/text.md``."""
    path = node.sources / key / "text.md"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("---\n"):
        end = raw.find("\n---\n", 4)
        if end > 0:
            front = yaml.safe_load(raw[4:end]) or {}
            return front, raw[end + 5 :].lstrip("\n")
    return {}, raw
