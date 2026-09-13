"""A node on disk: a corpus library plus the layers corpus does not hold.

    <root>/
      config.yaml       corpus project config (input_pdfs, bib, output_dir)
      instructions.md   injected into every chat session against the corpus
      references.bib    one entry per work; corpus directives + node fields
      sharing.yaml      tiers per person and per item
      library/          PDFs. Never committed, never served.
      sources/<key>/    text.md (+ manuscript source files when kept)
      assets/<key>/     figures: previews, originals, data, scripts, asset.yaml
      notes/            notes and the dead-ends log
      export/           the served view, written by `omnibus-node export`

Fields the node adds to a bib entry, beside the standard ones and corpus's
``file``/``license``/``licenseurl``/``serve``/``servereason``:

    contributor  ORCID or GitHub login of whoever added it
    added        date added, YYYY-MM-DD
    share        tier override for this work (else sharing.yaml decides)
    status       published | preprint | draft (drafts' text needs tier all)
    oapdf        URL the PDF can be fetched from
    sha256       checksum of the PDF in library/
    openalex     OpenAlex work id, when imported from there
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from . import bibtex, sharing

LIBRARY = "library"
SOURCES = "sources"
ASSETS = "assets"
NOTES = "notes"
EXPORT = "export"
BIB = "references.bib"
SHARING = "sharing.yaml"
CONFIG = "config.yaml"
INSTRUCTIONS = "instructions.md"
DEAD_ENDS = "dead-ends.md"

BIB_HEADER = (
    "references.bib — one entry per work in this node.\n"
    "Read by corpus (file=, license=, serve=) and by omnibus-node\n"
    "(contributor=, added=, share=, status=, oapdf=, sha256=).\n"
    "Edit by hand freely; omnibus-node preserves fields it does not know."
)


class Node:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    # --- paths ---------------------------------------------------------
    @property
    def bib_path(self) -> Path:
        return self.root / BIB

    @property
    def sharing_path(self) -> Path:
        return self.root / SHARING

    @property
    def library(self) -> Path:
        return self.root / LIBRARY

    @property
    def sources(self) -> Path:
        return self.root / SOURCES

    @property
    def assets(self) -> Path:
        return self.root / ASSETS

    @property
    def notes(self) -> Path:
        return self.root / NOTES

    @property
    def export_dir(self) -> Path:
        return self.root / EXPORT

    def exists(self) -> bool:
        return self.bib_path.exists() or self.sharing_path.exists()

    # --- bib -------------------------------------------------------------
    def load_bib(self) -> list[bibtex.Entry]:
        return bibtex.load(self.bib_path)

    def save_bib(self, entries: list[bibtex.Entry]) -> None:
        bibtex.save(self.bib_path, entries, header=BIB_HEADER)

    def entry(self, key: str) -> bibtex.Entry | None:
        return bibtex.find(self.load_bib(), key)

    def upsert_entry(self, key: str, etype: str, fields: dict[str, str | None]) -> bibtex.Entry:
        entries = self.load_bib()
        e = bibtex.upsert(entries, key, etype, fields)
        self.save_bib(entries)
        return e

    # --- sharing ---------------------------------------------------------
    def load_sharing(self) -> sharing.Sharing:
        return sharing.load(self.sharing_path)

    def save_sharing(self, s: sharing.Sharing) -> None:
        sharing.save(self.sharing_path, s)

    def tier_for(self, entry: bibtex.Entry, s: sharing.Sharing | None = None) -> str:
        """Effective tier of a work: bib share= > sharing.yaml resolution."""
        s = s or self.load_sharing()
        explicit = entry.get("share")
        if explicit and explicit in sharing.TIERS:
            return explicit
        return s.resolve(entry.key, entry.get("contributor"))

    # --- init ------------------------------------------------------------
    @classmethod
    def init(
        cls,
        root: str | Path,
        name: str,
        contributor: str,
        contributor_name: str | None = None,
        default_share: str = "plots",
    ) -> "Node":
        node = cls(root)
        node.root.mkdir(parents=True, exist_ok=True)
        for d in (LIBRARY, SOURCES, ASSETS, NOTES):
            (node.root / d).mkdir(exist_ok=True)
        (node.library / ".gitkeep").touch()

        def put(rel: str, text: str) -> None:
            p = node.root / rel
            if not p.exists():
                p.write_text(text, encoding="utf-8")

        put(CONFIG, _template("config.yaml").replace("{{name}}", name))
        put(INSTRUCTIONS, _template("instructions.md").replace("{{name}}", name))
        put(".gitignore", _template("gitignore"))
        put(f"{NOTES}/README.md", _template("notes-README.md"))
        put(f"{NOTES}/{DEAD_ENDS}", _template("dead-ends.md"))
        if not node.bib_path.exists():
            node.save_bib([])
        if not node.sharing_path.exists():
            s = sharing.Sharing()
            s.defaults.share = default_share  # type: ignore[assignment]
            s.people[contributor] = sharing.Person(share=None, name=contributor_name)
            node.save_sharing(s)
        return node


def _template(name: str) -> str:
    return resources.files("omnibus_node").joinpath("templates", name).read_text(encoding="utf-8")
