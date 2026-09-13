# AGENTS.md

Orientation for AI coding agents working in this repository.

## What this is

omnibus-node is the lab-side half of Omnibus (see
github.com/schultz-evogenome/omnibus, `docs/omnibus-design.md`). It builds
on corpus (github.com/caseywdunn/corpus) and does not duplicate it. corpus
turns PDFs into a corpuscle; this package turns manuscript sources and figure
folders into the library corpus reads, keeps the layers corpus does not hold,
and serves them under sharing tiers.

## Rules

- Use corpus's vocabulary: library (PDFs plus a `.bib`), corpuscle, bundle,
  `bundle_info`, output profiles `report` / `manuscript` / `presentation`,
  clearance states in `rights.py`. Tool and field names match corpus where
  the two overlap.
- Default closed. Nothing in `library/` is ever served, exported or
  committed. A work with `serve = {false}` is not served at all.
- Every entry carries who and when: `contributor` and `added` in the bib,
  `asset.yaml`, `text.md` front matter, and every dead-end log line.
- Never record an absolute path in anything that can leave the node.
- Propose layouts and schemas before writing code. Ask before adding a
  dependency. Runtime dependencies are `pyyaml`, `pydantic`, `requests`,
  `mcp`; everything else is an external program detected in `tools.py`.
- Plain declarative prose in docs and docstrings. No marketing language.
- Do not put real manuscripts, PDFs or private data in tests. Fixtures are
  generated in `tests/conftest.py`.

## Layout

| Path | Role |
| --- | --- |
| `src/omnibus_node/cli.py` | the `omnibus-node` command |
| `bibtex.py` | minimal reader/writer, the subset corpus's `bib/parser.py` reads |
| `sharing.py` | tiers, layers, resolution, `sharing.yaml` |
| `node.py` | the on-disk layout and `init` |
| `ingest/` | one module per source format; `common.py` for figures, captions, `text.md` |
| `assets.py` | figure folders via `figures.yaml` |
| `fetch.py` | PDFs from `oapdf=`; full text and figures from Europe PMC |
| `check.py`, `export.py`, `serve.py` | consistency, the served view, the MCP server |
| `rights.py` | license clearance and profiles |
| `notes.py`, `search.py` | the dead-ends log; BM25 over paragraphs |
| `tests/compat/` | corpus's BibTeX parser, vendored for a compatibility test |

`export.plan()` is the one place that decides what is served; `serve.py`
and `run_export()` both use it. Add a layer there, not in two places.

## Running

```sh
pip install -e ".[dev]"
ruff check src tests
pytest -q
```

CI runs the same on Python 3.10 and 3.12 with pandoc and poppler installed.
