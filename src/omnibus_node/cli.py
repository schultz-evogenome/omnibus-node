"""The ``omnibus-node`` command."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, sharing, tools
from .node import Node


def _contributor(node: Node, given: str | None) -> str:
    """--contributor, else $OMNIBUS_CONTRIBUTOR, else the only person in
    sharing.yaml."""
    if given:
        return given
    env = os.environ.get("OMNIBUS_CONTRIBUTOR")
    if env:
        return env
    people = list(node.load_sharing().people) if node.sharing_path.exists() else []
    if len(people) == 1:
        return people[0]
    raise SystemExit("who is adding this? pass --contributor <ORCID or GitHub login> or set OMNIBUS_CONTRIBUTOR")


def _report(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    for k, v in result.items():
        if k == "warnings" or k == "doc":
            continue
        print(f"  {k}: {v}")
    for w in result.get("warnings", []):
        print(f"  warning: {w}")


def cmd_init(a: argparse.Namespace) -> int:
    node = Node.init(a.root, a.name, a.contributor, a.contributor_name, a.default_share)
    print(f"initialised node '{a.name}' at {node.root}")
    print("  next: omnibus-node ingest <file> | omnibus-node assets figures.yaml | omnibus-node check")
    return 0


def cmd_ingest(a: argparse.Namespace) -> int:
    from .ingest import run_ingest

    node = Node(a.root)
    result = run_ingest(
        node,
        a.path,
        _contributor(node, a.contributor),
        key=a.key,
        share=a.share,
        status=a.status,
        title=a.title,
        render=not a.no_render,
        keep_source=a.keep_source,
        extract_images=a.extract_images,
    )
    _report(result, a.json)
    return 0


def cmd_assets(a: argparse.Namespace) -> int:
    from .assets import run_assets

    node = Node(a.root)
    result = run_assets(node, a.figures_yaml, _contributor(node, a.contributor))
    _report(result, a.json)
    return 0


def cmd_import_openalex(a: argparse.Namespace) -> int:
    from .import_openalex import run_import

    result = run_import(Node(a.root), a.orcid, mailto=a.mailto)
    _report(result, a.json)
    return 0


def cmd_fetch(a: argparse.Namespace) -> int:
    from .fetch import run_fetch, run_fetch_text

    node = Node(a.root)
    if a.text:
        result = run_fetch_text(node, contributor=a.contributor, keys=a.key or None, force=a.force, images=not a.no_images)
    else:
        result = run_fetch(node, keys=a.key or None, force=a.force)
    _report(result, a.json)
    return 0 if not result.get("failed") else 1


def cmd_check(a: argparse.Namespace) -> int:
    from .check import run_check

    result = run_check(Node(a.root))
    if a.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        for line in result["lines"]:
            print(line)
    return 0 if result["ok"] else 1


def cmd_share(a: argparse.Namespace) -> int:
    node = Node(a.root)
    s = node.load_sharing()
    if a.share_cmd == "show":
        entries = node.load_bib()
        if a.key:
            entries = [e for e in entries if e.key == a.key]
        print(f"default: {s.defaults.share}")
        for who, p in s.people.items():
            print(f"person {who}: {p.share or '(default)'}{' — ' + p.name if p.name else ''}")
        for e in entries:
            print(f"{e.key}: {node.tier_for(e, s)}  (contributor {e.get('contributor') or '?'})")
        return 0
    if a.share_cmd == "set":
        if a.tier not in sharing.TIERS:
            raise SystemExit(f"tier must be one of {', '.join(sharing.TIERS)}")
        if a.person:
            s.people.setdefault(a.person, sharing.Person())
            s.people[a.person].share = a.tier  # type: ignore[assignment]
            if a.name:
                s.people[a.person].name = a.name
        elif a.item:
            s.items.setdefault(a.item, sharing.Item())
            s.items[a.item].share = a.tier  # type: ignore[assignment]
            if a.reason:
                s.items[a.item].reason = a.reason
        else:
            s.defaults.share = a.tier  # type: ignore[assignment]
        node.save_sharing(s)
        print(f"saved {node.sharing_path.name}")
        return 0
    return 2


def cmd_export(a: argparse.Namespace) -> int:
    from .export import run_export

    result = run_export(Node(a.root), out=a.out, cap=a.tier)
    _report(result, a.json)
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    from .serve import serve

    serve(Node(a.root), transport=a.transport, host=a.host, port=a.port, default_profile=a.profile)
    return 0


def cmd_dead_end(a: argparse.Namespace) -> int:
    from .notes import record_dead_end

    node = Node(a.root)
    path = record_dead_end(node, _contributor(node, a.contributor), a.project, a.tried, a.happened, a.decided)
    print(f"appended to {path.relative_to(node.root)}")
    return 0


def cmd_tools(a: argparse.Namespace) -> int:
    for name, path in tools.available().items():
        print(f"  {'ok     ' if path else 'missing'} {name:<10} {tools.TOOLS[name][1]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omnibus-node",
        description="Turn manuscript sources and figure folders into a corpus-ready library with sharing tiers.",
    )
    p.add_argument("--version", action="version", version=f"omnibus-node {__version__}")
    p.add_argument("--root", default=".", help="node directory (default: current directory)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create the node layout in --root")
    s.add_argument("--name", required=True, help="node name, e.g. schultz-evogenome")
    s.add_argument("--contributor", required=True, help="your ORCID or GitHub login")
    s.add_argument("--contributor-name", help="your name, for sharing.yaml")
    s.add_argument("--default-share", default="plots", choices=sharing.TIERS)
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("ingest", help="a LaTeX, DocX, Markdown, text or PDF file into the node")
    s.add_argument("path")
    s.add_argument("--key", help="bib key and library filename stem, e.g. Schultz2023a")
    s.add_argument("--contributor")
    s.add_argument("--share", choices=sharing.TIERS, help="tier override for this work")
    s.add_argument("--status", choices=("published", "preprint", "draft"))
    s.add_argument("--title")
    s.add_argument("--no-render", action="store_true", help="do not render LaTeX/DocX to a PDF for corpus")
    s.add_argument("--keep-source", action="store_true", help="copy the source files under sources/<key>/src/")
    s.add_argument(
        "--extract-images",
        action="store_true",
        help="PDF only: also pull embedded raster images out as figures (exact copies of published figures; off by default)",
    )
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("assets", help="a figure folder into figure assets, driven by a figures.yaml")
    s.add_argument("figures_yaml")
    s.add_argument("--contributor")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_assets)

    s = sub.add_parser("import-openalex", help="bib entries for every work OpenAlex lists under an ORCID")
    s.add_argument("--orcid", required=True)
    s.add_argument("--mailto", help="your email, for OpenAlex's polite pool (faster, optional)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_import_openalex)

    s = sub.add_parser("fetch", help="download PDFs named by oapdf= into library/, or full text from Europe PMC")
    s.add_argument("--key", action="append", help="only these keys (repeatable)")
    s.add_argument("--force", action="store_true", help="re-download files that exist")
    s.add_argument("--text", action="store_true", help="fetch full-text XML for works with pmcid= and write sources/<key>/text.md")
    s.add_argument("--no-images", action="store_true", help="with --text: do not fetch figure images")
    s.add_argument("--contributor", help="with --text: who is adding the text (default: the entry's contributor)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("check", help="is the node consistent and corpus-ready?")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("share", help="show or set sharing tiers")
    ss = s.add_subparsers(dest="share_cmd", required=True)
    s1 = ss.add_parser("show")
    s1.add_argument("key", nargs="?")
    s2 = ss.add_parser("set")
    s2.add_argument("--tier", required=True)
    g = s2.add_mutually_exclusive_group()
    g.add_argument("--person", help="ORCID or GitHub login")
    g.add_argument("--item", help="bib key")
    s2.add_argument("--name", help="with --person: their name")
    s2.add_argument("--reason", help="with --item: why")
    s.set_defaults(func=cmd_share)

    s = sub.add_parser("export", help="write the served view (what leaves the node) to a directory")
    s.add_argument("--out", default=None, help="default: export/")
    s.add_argument("--tier", default="all", choices=sharing.TIERS, help="cap every work at this tier")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("serve", help="serve the node over MCP")
    s.add_argument("--transport", default="stdio", choices=("stdio", "streamable-http", "sse"))
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--profile", default="report", choices=("report", "manuscript", "presentation"))
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("dead-end", help="log something that was tried and failed")
    s.add_argument("--contributor")
    s.add_argument("--project", required=True, help="project name or bib key")
    s.add_argument("--tried", required=True)
    s.add_argument("--happened", required=True)
    s.add_argument("--decided", default="")
    s.set_defaults(func=cmd_dead_end)

    s = sub.add_parser("tools", help="which external programs are available")
    s.set_defaults(func=cmd_tools)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, tools.MissingTool) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["main", "build_parser", "Path"]
