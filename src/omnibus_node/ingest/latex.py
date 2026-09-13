"""LaTeX manuscripts: flatten ``\\input``/``\\include``, find every figure
environment with its graphics files, caption and label, and convert the body
to Markdown (pandoc when present, a plain de-TeX otherwise)."""

from __future__ import annotations

import re
from pathlib import Path

from .. import tools
from .common import Figure, Ingested

GRAPHICS_EXTS = [".pdf", ".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".eps", ".tif", ".tiff", ".ai", ".svg"]
FIGURE_ENVS = r"figure\*?|sidewaysfigure\*?|wrapfigure|SCfigure"

_INPUT_RE = re.compile(r"\\(?:input|include|subfile)\{([^}]+)\}")
_COMMENT_RE = re.compile(r"(?<!\\)%.*")
_COMMENT_ENV_RE = re.compile(r"\\begin\{comment\}.*?\\end\{comment\}", re.S)
_GRAPHICSPATH_RE = re.compile(r"\\graphicspath\{((?:\s*\{[^}]*\}\s*)+)\}")
_INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_FIGURE_RE = re.compile(r"\\begin\{(" + FIGURE_ENVS + r")\}(?:\[[^\]]*\])?(.*?)\\end\{\1\}", re.S)
_SUBFIGURE_RE = re.compile(r"\\begin\{(subfigure|subfloat|minipage)\}.*?\\end\{\1\}", re.S)
_SECTION_RE = re.compile(r"\\(section|subsection|subsubsection|paragraph)\*?\{")


def _balanced(text: str, start: int) -> int:
    """Index just past the ``}`` matching the ``{`` at ``start``."""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def braced_command(text: str, name: str) -> str | None:
    """Argument of the first ``\\name[opt]{...}``, with nested braces."""
    m = re.search(r"\\" + name + r"\b\s*(?:\[[^\]]*\])?\s*\{", text)
    if not m:
        return None
    start = m.end() - 1
    end = _balanced(text, start)
    return text[start + 1 : end - 1]


def all_braced_commands(text: str, name: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"\\" + name + r"\b\s*(?:\[[^\]]*\])?\s*\{", text):
        start = m.end() - 1
        out.append(text[start + 1 : _balanced(text, start) - 1])
    return out


def flatten(main: Path, seen: set[Path] | None = None, depth: int = 0) -> str:
    """The main file with ``\\input``/``\\include`` files spliced in."""
    seen = seen if seen is not None else set()
    main = main.resolve()
    if main in seen or depth > 20:
        return f"% [omnibus-node: skipped recursive include {main.name}]\n"
    seen.add(main)
    text = main.read_text(encoding="utf-8", errors="replace")

    def splice(m: re.Match) -> str:
        name = m.group(1).strip()
        cand = main.parent / name
        if cand.suffix == "":
            cand = cand.with_suffix(".tex")
        if cand.exists():
            return "\n" + flatten(cand, seen, depth + 1) + "\n"
        return f"% [omnibus-node: missing include {name}]\n"

    return _INPUT_RE.sub(splice, text)


def strip_comments(text: str) -> str:
    text = _COMMENT_ENV_RE.sub("", text)
    return "\n".join(_COMMENT_RE.sub("", line) for line in text.splitlines())


def graphics_paths(text: str, base: Path) -> list[Path]:
    dirs = [base]
    m = _GRAPHICSPATH_RE.search(text)
    if m:
        for d in re.findall(r"\{([^}]*)\}", m.group(1)):
            dirs.append((base / d.strip()).resolve())
    return dirs


def resolve_graphic(name: str, dirs: list[Path]) -> Path | None:
    name = name.strip()
    for d in dirs:
        cand = d / name
        if cand.is_file():
            return cand
        if Path(name).suffix == "":
            for ext in GRAPHICS_EXTS:
                c2 = d / (name + ext)
                if c2.is_file():
                    return c2
    return None


def detex(s: str) -> str:
    """Plain text from a LaTeX fragment: pandoc when available, else regex."""
    s = s.strip()
    if not s:
        return ""
    exe = tools.find("pandoc")
    if exe:
        try:
            r = tools.run([exe, "-f", "latex", "-t", "plain", "--wrap=none"], input_text=s, timeout=60)
            out = " ".join(r.stdout.split())
            if out:
                return out
        except Exception:  # noqa: BLE001 - fall through to the regex path
            pass
    return detex_regex(s)


def detex_regex(s: str) -> str:
    s = re.sub(r"\\(?:textbf|textit|emph|textsc|texttt|underline|mathrm|text|hl)\s*\{", "{", s)
    s = re.sub(r"\\(?:cite[tp]?|citep|citet|ref|autoref|cref|eqref|label|SI|qty|si)\*?\s*(?:\[[^\]]*\])?\s*\{[^}]*\}", "", s)
    s = re.sub(r"\\[a-zA-Z@]+\*?\s*(?:\[[^\]]*\])?", " ", s)
    s = s.replace("~", " ").replace("\\,", " ").replace("\\\\", " ")
    s = re.sub(r"[{}]", "", s)
    s = s.replace("``", '"').replace("''", '"').replace("--", "-")
    return " ".join(s.split())


def extract_figures(text: str, dirs: list[Path]) -> list[Figure]:
    figures: list[Figure] = []
    for n, m in enumerate(_FIGURE_RE.finditer(text), start=1):
        body = m.group(2)
        panels: list[str] = []
        for sm in _SUBFIGURE_RE.finditer(body):
            for cap in all_braced_commands(sm.group(0), "caption") + all_braced_commands(sm.group(0), "subcaption"):
                panels.append(detex(cap))
        outer = _SUBFIGURE_RE.sub(" ", body)
        caps = all_braced_commands(outer, "caption")
        caption = detex(caps[-1]) if caps else ""
        labels = _LABEL_RE.findall(outer)
        fig = Figure(id=f"fig{n}", caption=caption, label=labels[0] if labels else None, number=str(n))
        if not caption:
            fig.caption_confidence = "low"
        for g in _INCLUDEGRAPHICS_RE.findall(body):
            path = resolve_graphic(g, dirs)
            if path is None:
                fig.missing.append(g.strip())
            else:
                fig.files.append(path)
        fig.panels = panels
        figures.append(fig)
    return figures


def to_markdown(text: str, warnings: list[str]) -> str:
    exe = tools.find("pandoc")
    if exe:
        try:
            r = tools.run([exe, "-f", "latex", "-t", "gfm", "--wrap=none"], input_text=text, timeout=300)
            if r.stdout.strip():
                return r.stdout
            warnings.append("pandoc produced no text; used the regex converter")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"pandoc failed ({str(exc).splitlines()[0][:120]}); used the regex converter")
    else:
        warnings.append("pandoc is not installed; text was converted with the regex fallback")
    return markdown_regex(text)


def markdown_regex(text: str) -> str:
    """A readable Markdown approximation without pandoc."""
    body = text
    m = re.search(r"\\begin\{document\}(.*?)(\\end\{document\}|$)", text, re.S)
    if m:
        body = m.group(1)
    body = _FIGURE_RE.sub("", body)
    body = re.sub(r"\\begin\{(table\*?|sidewaystable)\}.*?\\end\{\1\}", "", body, flags=re.S)
    body = re.sub(r"\\begin\{(equation\*?|align\*?)\}(.*?)\\end\{\1\}", r"\n$$\2$$\n", body, flags=re.S)
    levels = {"section": "#", "subsection": "##", "subsubsection": "###", "paragraph": "####"}

    def heading(mm: re.Match) -> str:
        start = mm.end() - 1
        end = _balanced(body, start)
        title = detex_regex(body[start + 1 : end - 1])
        heading._skip = end  # type: ignore[attr-defined]
        return f"\n{levels[mm.group(1)]} {title}\n"

    out: list[str] = []
    pos = 0
    for mm in _SECTION_RE.finditer(body):
        if mm.start() < pos:
            continue
        out.append(body[pos : mm.start()])
        out.append(heading(mm))
        pos = heading._skip  # type: ignore[attr-defined]
    out.append(body[pos:])
    body = "".join(out)
    body = re.sub(r"\\(?:maketitle|tableofcontents|newpage|clearpage|linenumbers|nolinenumbers)\b", "", body)
    body = re.sub(r"\\begin\{abstract\}", "\n## Abstract\n", body)
    body = re.sub(r"\\end\{abstract\}", "\n", body)
    body = re.sub(r"\\begin\{(itemize|enumerate|description)\}|\\end\{(itemize|enumerate|description)\}", "", body)
    body = body.replace("\\item", "\n- ")
    body = re.sub(r"\\bibliography(?:style)?\{[^}]*\}|\\printbibliography|\\addbibresource\{[^}]*\}", "", body)
    paras = [detex_regex(p) for p in re.split(r"\n\s*\n", body)]
    lines = []
    for p in paras:
        if not p:
            continue
        lines.append(p if not p.startswith("#") else "\n" + p + "\n")
    return "\n\n".join(lines).strip() + "\n"


def ingest_latex(path: Path) -> Ingested:
    path = Path(path)
    warnings: list[str] = []
    raw = flatten(path)
    text = strip_comments(raw)
    dirs = graphics_paths(text, path.parent)
    figures = extract_figures(text, dirs)
    title_tex = braced_command(text, "title")
    title = detex(title_tex) if title_tex else None
    extras: dict = {}
    abstract = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.S)
    if abstract:
        extras["abstract"] = detex(abstract.group(1))
    bib = re.search(r"\\(?:bibliography|addbibresource)\{([^}]+)\}", text)
    if bib:
        extras["bibfile"] = bib.group(1).strip()
    magic = re.search(r"%\s*!TeX\s+(?:TS-)?program\s*=\s*(\w+)", raw, re.I)
    extras["engine"] = magic.group(1).lower() if magic else "pdflatex"
    md = to_markdown(text, warnings)
    for fig in figures:
        for miss in fig.missing:
            warnings.append(f"{fig.id}: graphics file not found: {miss}")
    return Ingested(
        format="latex",
        source=path,
        text=md,
        title=title,
        figures=figures,
        extras=extras,
        warnings=warnings,
    )
