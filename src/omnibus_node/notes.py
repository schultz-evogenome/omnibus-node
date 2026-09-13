"""Notes and the dead-ends log: the write path of the node."""

from __future__ import annotations

from pathlib import Path

from .node import DEAD_ENDS, Node
from .provenance import today


def record_dead_end(
    node: Node,
    contributor: str,
    project: str,
    tried: str,
    happened: str,
    decided: str = "",
) -> Path:
    """Append one dated, attributed entry to ``notes/dead-ends.md``."""
    if not (project and tried and happened):
        raise ValueError("project, tried and happened are required")
    node.notes.mkdir(parents=True, exist_ok=True)
    path = node.notes / DEAD_ENDS
    if not path.exists():
        path.write_text("# Dead ends\n\nThings that were tried and did not work.\n", encoding="utf-8")
    entry = [
        "",
        f"## {today()} · {contributor} · {project}",
        "",
        f"- Tried: {' '.join(tried.split())}",
        f"- Happened: {' '.join(happened.split())}",
    ]
    if decided:
        entry.append(f"- Decided: {' '.join(decided.split())}")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(entry) + "\n")
    return path


def list_notes(node: Node) -> list[Path]:
    if not node.notes.exists():
        return []
    return sorted(p for p in node.notes.glob("*.md") if p.name != "README.md")


def read_note(node: Node, name: str) -> str | None:
    if "/" in name or name.startswith("."):
        return None
    path = node.notes / (name if name.endswith(".md") else name + ".md")
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")
