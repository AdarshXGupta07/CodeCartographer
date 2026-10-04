"""Hybrid retrieval: BM25 (code tokens) + dense code embeddings + symbol match,
fused with Reciprocal Rank Fusion and re-scored with structural features."""

from __future__ import annotations

import re

import numpy as np

from .embeddings import get_embedder
from .textutil import code_tokens, query_tokens, split_identifier

RRF_K = 60
CHANNEL_WEIGHTS = {"bm25": 0.8, "dense": 1.5, "symbol": 0.6}


class Retriever:
    def __init__(self, index):
        self.ix = index

    # ---------------------------------------------------------------- channels
    def bm25(self, query: str, k: int = 50) -> list[tuple[int, float]]:
        scores = self.ix.bm25.scores(query_tokens(query))
        return sorted(scores.items(), key=lambda x: -x[1])[:k]

    def dense(self, query: str, k: int = 50) -> list[tuple[int, float]]:
        if self.ix.emb is None or len(self.ix.emb) == 0:
            return []
        qv = get_embedder().embed([query], is_query=True)[0]
        if qv.shape[0] != self.ix.emb.shape[1]:
            return []
        sims = self.ix.emb @ qv
        top = np.argsort(-sims)[:k]
        return [(int(i), float(sims[i])) for i in top]

    def symbols(self, query: str, k: int = 30) -> list[dict]:
        """Fuzzy match of the query against identifiers, constants, tool names and string literals."""
        q_raw = query_tokens(query, expand=False)
        q = set(q_raw) | {t.rstrip("s") for t in q_raw}
        if not q:
            return []
        # only code-looking words (camelCase, CONST_CASE, dotted) get the exact-identifier boost
        exact_idents = {w for w in re.findall(r"[A-Za-z_$][A-Za-z0-9_$.]{3,}", query)
                        if re.search(r"[a-z][A-Z]|_|\$|\.", w) or (w.isupper() and len(w) > 3)}
        out = []
        for sym, toks in zip(self.ix.symbols, self.ix.symbol_tokens):
            if not toks:
                continue
            inter = q & toks
            if not inter and sym["name"] not in exact_idents:
                continue
            parts = set(split_identifier(sym["name"])) or toks
            coverage = len(inter) / len(q)
            precision = len(q & parts) / len(parts)
            score = 0.65 * coverage + 0.35 * precision
            # context: query words not in the name but in the file path ("deeplink" -> deeplinks/deeplinkConstants.js)
            leftover = q - toks
            if leftover:
                ctx = self._path_tokens(sym["file"])
                score += 0.4 * len(leftover & ctx) / len(q)
            if sym["name"] in exact_idents:
                score += 1.0
            if sym["kind"] in ("tool", "class", "function", "method"):
                score += 0.05
            out.append((score, sym))
        out.sort(key=lambda x: -x[0])
        seen, res = set(), []
        for score, sym in out:
            key = (sym["name"], sym["file"], sym["line"])
            if key in seen:
                continue
            seen.add(key)
            res.append({**sym, "score": round(score, 3)})
            if len(res) >= k:
                break
        return res

    def _path_tokens(self, rel: str) -> set:
        cache = self.__dict__.setdefault("_ptok", {})
        if rel not in cache:
            toks = set()
            for part in rel.replace(".js", "").split("/"):
                toks |= set(split_identifier(part))
            cache[rel] = toks | {t.rstrip("s") for t in toks}
        return cache[rel]

    # ------------------------------------------------------------------ hybrid
    def search(self, query: str, k: int = 10, mode: str = "hybrid", rewrites: list[str] | None = None) -> list[dict]:
        if mode == "bm25":
            ranked = self.bm25(query, k)
            return [self._result(i, s, {"bm25": r + 1}) for r, (i, s) in enumerate(ranked)]
        if mode == "dense":
            ranked = self.dense(query, k)
            return [self._result(i, s, {"dense": r + 1}) for r, (i, s) in enumerate(ranked)]

        lists = {"bm25": self.bm25(query, 60), "dense": self.dense(query, 60)}
        # multi-query: code-vocabulary rewrites (from the agent) are fused as extra channels
        for j, rw in enumerate(rewrites or []):
            if rw and rw.strip().lower() != query.strip().lower():
                lists[f"rw{j+1}.bm25"] = self.bm25(rw, 60)
                lists[f"rw{j+1}.dense"] = self.dense(rw, 60)
        fused: dict[int, float] = {}
        ranks: dict[int, dict] = {}
        for name, lst in lists.items():
            # dense code embeddings are the strongest single channel on natural-language questions
            w = CHANNEL_WEIGHTS.get(name.split(".")[-1], 1.0) * (1.0 if "." not in name else 0.6)
            for r, (i, _) in enumerate(lst):
                fused[i] = fused.get(i, 0.0) + w / (RRF_K + r + 1)
                ranks.setdefault(i, {})[name] = r + 1
        # symbol channel: chunks containing a strongly matching symbol get a boost
        for r, sym in enumerate(s for s in self.symbols(query, 15) if s["score"] >= 0.6):
            for c in self._chunks_at(sym["file"], sym["line"]):
                fused[c] = fused.get(c, 0.0) + CHANNEL_WEIGHTS["symbol"] / (RRF_K + r + 1)
                ranks.setdefault(c, {})["symbol"] = r + 1
        # structural re-scoring
        qt = set(query_tokens(query, expand=False))
        for i in list(fused):
            ch = self.ix.chunks[i]
            overlap = len(qt & set(split_identifier(ch["symbol"].split(".")[-1])))
            file_overlap = len(qt & set(split_identifier(ch["file"].rsplit("/", 1)[-1].split(".")[0])))
            if overlap or file_overlap:
                fused[i] *= 1.0 + 0.05 * min(overlap, 3) + 0.02 * min(file_overlap, 2)
            if ch["kind"] == "module" and ch["end"] - ch["start"] > 40:
                fused[i] *= 0.9
        top = sorted(fused.items(), key=lambda x: -x[1])[:k]
        return [self._result(i, s, ranks.get(i, {})) for i, s in top]

    def _chunks_at(self, rel: str, line: int) -> list[int]:
        best = []
        for c in self.ix.chunks:
            if c["file"] == rel and c["start"] <= line <= c["end"]:
                best.append((c["end"] - c["start"], c["idx"]))
        best.sort()
        return [i for _, i in best[:1]]

    def _result(self, i: int, score: float, ranks: dict) -> dict:
        c = self.ix.chunks[i]
        return {
            "chunk": i, "file": c["file"], "start": c["start"], "end": c["end"], "symbol": c["symbol"],
            "kind": c["kind"], "func_id": c["func_id"], "score": round(float(score), 5), "ranks": ranks,
        }
