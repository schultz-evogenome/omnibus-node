"""A small BM25 index over paragraphs of the served texts. Enough for a lab
node with hundreds of works; corpus's embeddings take over at scale."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Hit:
    key: str
    paragraph: int
    score: float
    snippet: str


class Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs: list[tuple[str, int, str]] = []
        self.tf: list[Counter] = []
        self.df: Counter = Counter()
        self.lengths: list[int] = []

    def add(self, key: str, paragraphs: list[str]) -> None:
        for i, p in enumerate(paragraphs):
            toks = tokenize(p)
            if not toks:
                continue
            self.docs.append((key, i, p))
            c = Counter(toks)
            self.tf.append(c)
            self.lengths.append(len(toks))
            for term in c:
                self.df[term] += 1

    def search(self, query: str, k: int = 10) -> list[Hit]:
        q = tokenize(query)
        n = len(self.docs)
        if not q or n == 0:
            return []
        avg = sum(self.lengths) / n
        scores: list[tuple[float, int]] = []
        for i, c in enumerate(self.tf):
            s = 0.0
            for term in q:
                f = c.get(term)
                if not f:
                    continue
                idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                denom = f + self.k1 * (1 - self.b + self.b * self.lengths[i] / avg)
                s += idf * f * (self.k1 + 1) / denom
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        out: list[Hit] = []
        for s, i in scores[:k]:
            key, para, text = self.docs[i]
            out.append(Hit(key, para, round(s, 3), text[:400]))
        return out
