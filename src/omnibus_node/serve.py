"""``omnibus-node serve``: the node over the Model Context Protocol.

Read tools cover what corpus does not hold (texts, figure previews and
assets, notes) at each work's sharing tier; ``record_dead_end`` is the write
path. Figure tools take corpus's ``profile`` argument and apply the same
licensing gate (rights.py). Tool and field names follow corpus where the
two overlap so a client can treat a node and a corpuscle alike.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import ImageContent

from . import __version__
from .export import plan
from .ingest.common import paragraphs, read_text
from .node import Node
from .notes import list_notes as _list_notes, read_note, record_dead_end as _record
from .rights import PROFILES, attribution, cleared_for
from .search import Index


class Served:
    """The plan, materialised in memory and rebuilt on demand."""

    def __init__(self, node: Node) -> None:
        self.node = node
        self.refresh()

    def refresh(self) -> None:
        works, excluded, shared_notes = plan(self.node, "all")
        self.works = {w.key: w for w in works}
        self.excluded = excluded
        self.shared_notes = shared_notes
        self.index = Index()
        self.texts: dict[str, str] = {}
        for w in works:
            if w.text:
                got = read_text(self.node, w.key)
                if got:
                    self.texts[w.key] = got[1]
                    self.index.add(w.key, paragraphs(got[1]))


def build_server(node: Node, default_profile: str = "report") -> MCPServer:
    served = Served(node)
    name = node.root.name
    instructions_path = node.root / "instructions.md"
    instructions = instructions_path.read_text(encoding="utf-8") if instructions_path.exists() else None
    server = MCPServer(name, instructions=instructions, version=__version__)

    def _work(key: str):
        w = served.works.get(key)
        if w is None:
            return None, {"error": f"{key} is not served by this node", "code": "not_found"}
        return w, None

    @server.tool()
    def node_info() -> dict:
        """Node name, tool version, counts of works, texts, figures and notes, and what is excluded."""
        figures = sum(len(w.figures) for w in served.works.values())
        return {
            "node": name,
            "server": f"omnibus-node {__version__}",
            "works": len(served.works),
            "texts": len(served.texts),
            "figures": figures,
            "notes": len(_list_notes(node)) if served.shared_notes else 0,
            "excluded": len(served.excluded),
            "tiers": sorted({w.tier for w in served.works.values()}),
            "profiles": list(PROFILES),
            "default_profile": default_profile,
        }

    @server.tool()
    def list_works(year_from: int | None = None, year_to: int | None = None) -> list[dict]:
        """Every served work: key, title, year, doi, tier, whether text and figures are available."""
        out = []
        for w in served.works.values():
            y = w.entry.get("year")
            try:
                yi = int(str(y)[:4]) if y else None
            except ValueError:
                yi = None
            if year_from and (yi is None or yi < year_from):
                continue
            if year_to and (yi is None or yi > year_to):
                continue
            out.append(
                {
                    "key": w.key,
                    "title": w.entry.get("title"),
                    "year": y,
                    "doi": w.entry.get("doi"),
                    "status": w.entry.get("status") or "published",
                    "tier": w.tier,
                    "has_text": w.key in served.texts,
                    "figures": len(w.figures),
                }
            )
        return out

    @server.tool()
    def get_work(key: str) -> dict:
        """Full metadata for one work, its figure captions, and the attribution string to use."""
        w, err = _work(key)
        if err:
            return err
        md = w.metadata
        md["attribution"] = attribution(w.entry.fields)
        md["figures"] = [{"id": f["id"], "caption": f.get("caption"), "number": f.get("number")} for f in w.figures]
        md["has_text"] = key in served.texts
        return md

    @server.tool()
    def get_text(key: str, offset: int = 0, max_chars: int = 20000) -> dict:
        """The text of a work (Markdown), paged by character offset."""
        w, err = _work(key)
        if err:
            return err
        text = served.texts.get(key)
        if text is None:
            return {"error": f"{key} has no served text at tier {w.tier}", "code": "not_available"}
        chunk = text[offset : offset + max_chars]
        return {"key": key, "offset": offset, "length": len(text), "text": chunk, "attribution": attribution(w.entry.fields)}

    @server.tool()
    def search_text(query: str, k: int = 10) -> list[dict]:
        """BM25 search over paragraphs of every served text. Returns key, paragraph index, score, snippet."""
        return [{"key": h.key, "paragraph": h.paragraph, "score": h.score, "snippet": h.snippet} for h in served.index.search(query, k)]

    @server.tool()
    def list_figures(key: str) -> dict:
        """Figures of a work with captions and the files servable at its tier (previews at plots; originals, data and scripts at assets)."""
        w, err = _work(key)
        if err:
            return err
        return {"key": key, "tier": w.tier, "figures": w.figures}

    @server.tool(structured_output=False)
    def get_figure(key: str, figure_id: str, profile: str = default_profile):
        """The preview image of a figure. profile= report (in-chat display) is permissive; manuscript and presentation refuse figures whose license is not recorded as open."""
        w, err = _work(key)
        if err:
            return err
        if profile not in PROFILES:
            return {"error": f"profile must be one of {', '.join(PROFILES)}", "code": "invalid_argument"}
        fig = next((f for f in w.figures if f["id"] == figure_id), None)
        if fig is None:
            return {"error": f"{key} has no figure {figure_id}", "code": "not_found"}
        state = w.metadata["publication_clearance"]
        if not cleared_for(profile, state):
            return {
                "error": f"figure withheld under profile '{profile}' — publication_clearance='{state}'. "
                "For in-chat display request profile='report'.",
                "code": "not_cleared",
                "publication_clearance": state,
            }
        preview = next((f for f in fig["files"] if f.get("role") in ("preview", "plot")), None)
        if preview is None:
            return {"error": f"no image is servable for {figure_id} at tier {w.tier}", "code": "not_available"}
        path = node.assets / key / preview["path"]
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return ImageContent(type="image", data=base64.b64encode(path.read_bytes()).decode("ascii"), mimeType=mime)

    @server.tool()
    def get_figure_file(key: str, figure_id: str, path: str) -> dict:
        """A data or script file behind a figure (tier assets), as text when it is text, else base64."""
        w, err = _work(key)
        if err:
            return err
        fig = next((f for f in w.figures if f["id"] == figure_id), None)
        if fig is None:
            return {"error": f"{key} has no figure {figure_id}", "code": "not_found"}
        rec = next((f for f in fig["files"] if f["path"] == path), None)
        if rec is None:
            return {"error": f"{path} is not servable for {figure_id} at tier {w.tier}", "code": "not_available"}
        full = (node.assets / key / path).resolve()
        if node.assets.resolve() not in full.parents:
            return {"error": "invalid path", "code": "invalid_argument"}
        data = full.read_bytes()
        try:
            return {"path": path, "role": rec.get("role"), "sha256": rec.get("sha256"), "text": data.decode("utf-8")}
        except UnicodeDecodeError:
            return {"path": path, "role": rec.get("role"), "sha256": rec.get("sha256"), "base64": base64.b64encode(data).decode("ascii")}

    @server.tool()
    def list_notes() -> list[str]:
        """Names of the shared notes, when the node shares them."""
        if not served.shared_notes:
            return []
        return [p.name for p in _list_notes(node)]

    @server.tool()
    def get_note(name: str) -> dict:
        """One shared note by name (see list_notes)."""
        if not served.shared_notes:
            return {"error": "this node does not share notes", "code": "not_available"}
        text = read_note(node, name)
        if text is None:
            return {"error": f"no note named {name}", "code": "not_found"}
        return {"name": name, "text": text}

    @server.tool()
    def record_dead_end(project: str, tried: str, happened: str, decided: str = "", contributor: str = "") -> dict:
        """Log something that was tried and failed: dated, attributed, appended to notes/dead-ends.md."""
        who = contributor or _default_contributor(node)
        if not who:
            return {"error": "contributor is required (ORCID or GitHub login)", "code": "invalid_argument"}
        path = _record(node, who, project, tried, happened, decided)
        return {"recorded": str(path.relative_to(node.root)), "contributor": who}

    @server.tool()
    def refresh() -> dict:
        """Re-read the node from disk after files changed."""
        served.refresh()
        return node_info()

    return server


def _default_contributor(node: Node) -> str | None:
    people = list(node.load_sharing().people)
    return people[0] if len(people) == 1 else None


def serve(node: Node, transport: str = "stdio", host: str = "127.0.0.1", port: int = 8765, default_profile: str = "report") -> None:
    server = build_server(node, default_profile)
    if transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport=transport, host=host, port=port)


__all__ = ["build_server", "serve", "Path"]
