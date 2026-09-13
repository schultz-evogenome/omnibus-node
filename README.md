# omnibus-node

The software a lab runs to be a node in [Omnibus](https://github.com/schultz-evogenome/omnibus).

It turns manuscript sources (LaTeX, DocX, plain text, Markdown, PDF) and
figure folders into a library that [corpus](https://github.com/caseywdunn/corpus)
can build a corpuscle from, keeps the layers corpus does not hold (figure
assets, notes, dead ends), records who added each thing and when, and serves
what each contributor chose to share over the Model Context Protocol (MCP).

corpus does the heavy work on PDFs: OCR, layout, figure extraction,
bibliography reconciliation, embeddings. This package does what happens before
and beside that: getting a manuscript out of the format it was written in,
keeping the files behind each plot, and deciding what leaves the lab.

## Install

```sh
pip install git+https://github.com/schultz-evogenome/omnibus-node
```

Python 3.10 or later. Optional programs, each detected at run time and
reported by `omnibus-node tools`:

| Program | Used for |
| --- | --- |
| pandoc | LaTeX and DocX to Markdown; DocX media extraction; JATS full text |
| poppler (`pdftotext`, `pdfimages`, `pdftoppm`, `pdfinfo`) | text and raster figures from PDFs; PNG previews of PDF and Illustrator figures |
| LibreOffice (`soffice`) | DocX to PDF, so corpus can ingest a DocX manuscript |
| latexmk | LaTeX to PDF, so corpus can ingest a LaTeX manuscript |

On a Mac: `brew install pandoc poppler` and LibreOffice from libreoffice.org.
On the cluster the same tools come from conda-forge, as in corpus's
`environment.yaml`.

## A node on disk

```text
my-node/
  config.yaml       corpus project config: input_pdfs, bib, output_dir
  instructions.md   text injected into every chat session against the corpus
  references.bib    one entry per work
  sharing.yaml      tiers per person and per item
  library/          PDFs. Never committed, never served.
  sources/<key>/    text.md, and the source files when kept
  assets/<key>/     figure previews, originals, data, scripts, asset.yaml
  notes/            notes and the dead-ends log
  export/           the served view, written by `omnibus-node export`
```

`references.bib` is read by corpus (`file`, `license`, `serve`) and by this
package. The fields it adds:

| Field | Meaning |
| --- | --- |
| `contributor` | ORCID or GitHub login of whoever added the work |
| `added` | date added, YYYY-MM-DD |
| `share` | tier override for this work |
| `status` | `published`, `preprint` or `draft`; a draft's text is served only at tier `all` |
| `oapdf`, `oapdfalt` | where the PDF can be fetched from |
| `sha256` | checksum of the PDF in `library/` |
| `pmcid`, `openalex` | identifiers used by `fetch --text` and for provenance |

## Commands

```sh
omnibus-node init --name schultz-evogenome --contributor 0000-0003-1190-1122 --contributor-name "Darrin Schultz"

omnibus-node ingest paper/main.tex --key Schultz2026a          # LaTeX: text, every figure, PDF via latexmk
omnibus-node ingest draft.docx --key Student2026 --status draft  # DocX: text, embedded images, PDF via LibreOffice
omnibus-node ingest Schultz2023.pdf                             # PDF: text, raster figures, copied into library/
omnibus-node assets figures/figures.yaml                        # a figure folder: final files, data, scripts

omnibus-node fetch                 # PDFs named by oapdf= into library/
omnibus-node fetch --text          # full text and figures from Europe PMC for works with pmcid=

omnibus-node share show
omnibus-node share set --person 0000-0003-1190-1122 --tier all
omnibus-node share set --item Secret2026 --tier none --reason "under review"

omnibus-node check                 # consistency and corpus-readiness
omnibus-node export --tier plots   # what an outsider at tier plots would see
omnibus-node dead-end --project hydra --tried "aligner X" --happened "N50 halved"
omnibus-node serve                 # MCP over stdio
```

Every ingest writes `sources/<key>/text.md` with front matter naming the
source file, its checksum, the contributor, the date and the tool version;
copies each figure into `assets/<key>/` with a PNG preview and its caption;
and creates or updates the bib entry. Curated metadata in an existing entry
is never overwritten by a weaker guess from the file.

### Figure folders

A manuscript's figure folder holds many versions of each figure, the tables
behind it, and the scripts that drew it. A `figures.yaml` names the final one
and what belongs with it:

```yaml
key: Schultz2023a
figures:
  - id: fig1
    original: FIG1/FIG1_v12.ai
    caption_from_text: 1          # the "Fig. 1" legend in sources/Schultz2023a/text.md
    data: ["tables/*.tsv"]
    scripts: [scripts/plot_fig1.py]
  - id: fig2
    original: [FIG2/panel_a.pdf, FIG2/panel_b.pdf]
    caption: "Two panels."
```

The final file and its PNG preview are tier `plots`; vector originals, data
and scripts are tier `assets`. Every file is checksummed and its origin
recorded relative to the folder, never as an absolute path.

## Sharing tiers

Tiers are cumulative. `plots` is what a contributor shares by joining;
`none` is opting out. A tier is set once per person in `sharing.yaml` and
overridden per work with `share =` in the bib or `items:` in `sharing.yaml`;
the most specific setting wins.

| Tier | Served |
| --- | --- |
| `none` | nothing |
| `plots` | bibliographic metadata, figure previews with captions, and the text of published works |
| `assets` | + the files behind each figure: data, scripts, vector originals |
| `notes` | + notes, decisions, dead ends |
| `all` | + manuscript sources and the text of unpublished drafts |

Two rules sit outside the tiers. PDFs in `library/` are never served or
exported: the node publishes the authors' text, not the publisher's file.
And corpus's `serve = {false}` removes a work entirely.

The tier is enforced by `export` and `serve`. If the node's own repository
is public, everything in it is public regardless of tier; keep the working
node private and publish `export/`.

## Licenses and figures

Each work's `license` is recorded as given (SPDX identifiers or corpus's
small vocabulary) and reported with corpus's clearance states:
`public_domain`, `licensed_open`, `restricted`, `undetermined`, `no_record`.
The figure tools take a `profile`: `report` displays any figure the tier
allows; `manuscript` and `presentation` refuse anything not recorded as
open. Every figure and text response carries an attribution string.

## Serving

`omnibus-node serve` exposes: `node_info`, `list_works`, `get_work`,
`get_text`, `search_text` (BM25 over paragraphs), `list_figures`,
`get_figure`, `get_figure_file`, `list_notes`, `get_note`, `record_dead_end`
and `refresh`. For Claude Code, a project `.mcp.json`:

```json
{
  "mcpServers": {
    "lab-node": {
      "command": "omnibus-node",
      "args": ["--root", "/path/to/my-node", "serve"]
    }
  }
}
```

For a network endpoint: `omnibus-node serve --transport streamable-http --host 0.0.0.0 --port 8765`,
behind whatever authentication the lab already uses (Tailscale, a reverse proxy).

## Building the corpuscle

The node directory is a corpus project root. When there are enough PDFs in
`library/` to justify it, on a machine with corpus installed:

```sh
cd my-node
corpus check
corpus run
corpus serve
```

corpus reads `config.yaml` and `references.bib`; `instructions.md` travels
with the bundle. The two servers cover different layers and can run side by
side.

## Limits

Figures pulled from a PDF are the raster images the file contains; vector
figures are not recoverable this way, and captions are paired by order, so
their confidence is marked `low`. corpus extracts figures properly at build
time. LaTeX macros that pandoc cannot expand come through as their arguments.

## Development

```sh
pip install -e ".[dev]"
ruff check src tests
pytest
```

Tests build their own fixtures (a PDF, a PNG, a LaTeX project, a DocX) and
parse the BibTeX this package writes with corpus's own parser, vendored under
`tests/compat/`.

## Citation and license

MIT. See `CITATION.cff`. If you use this with corpus, cite corpus:
Church, S. H., Mańko, M. K., Zapata, F., & Dunn, C. W. (2026).
Extracting AI agent-accessible data from biodiversity literature with corpus.
https://doi.org/10.5281/zenodo.19964909
