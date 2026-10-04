"""Small, dependency-free Okapi BM25 over code tokens."""

from __future__ import annotations

import math
from collections import Counter


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        # inverted index for speed on large repos
        self.postings: dict[str, list[int]] = {}
        for i, tf in enumerate(self.tfs):
            for t in tf:
                self.postings.setdefault(t, []).append(i)

    def scores(self, query: list[str]) -> dict[int, float]:
        out: dict[int, float] = {}
        for t in set(query):
            idf = self.idf.get(t)
            if idf is None:
                continue
            w = query.count(t)
            for i in self.postings[t]:
                f = self.tfs[i][t]
                denom = f + self.k1 * (1 - self.b + self.b * self.lens[i] / (self.avg or 1))
                out[i] = out.get(i, 0.0) + w * idf * f * (self.k1 + 1) / denom
        return out
