"""Evaluation harness: precision@k, recall@k, MRR, latency and indexing cost.

Compares four systems on the hand-labelled gold set:
  bm25    - lexical baseline (code-aware tokens)
  dense   - code-embedding baseline (jina-embeddings-v2-base-code, CPU)
  hybrid  - BM25 + dense + symbols fused with RRF (single query)
  agent   - full CodeCartographer agent (planner + graph + refinement + verifier)

Usage:
  python -m eval.run_eval                 # deterministic agent (no API key needed)
  python -m eval.run_eval --llm           # also evaluate the LLM-driven agent
  python -m eval.run_eval --scale 20      # + indexing/latency benchmark on a 20x replicated repo
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cartographer.agent import Agent  # noqa: E402
from cartographer.indexer import CodeIndex  # noqa: E402
from cartographer.llm import LLM  # noqa: E402
from cartographer.retrieval import Retriever  # noqa: E402

KS = (1, 3, 5, 10)


def gold_spans(ix, targets: list[str]) -> list[tuple[str, int, int, str]]:
    spans = []
    for t in targets:
        if "::" in t:
            rel, name = t.split("::", 1)
            fns = [f for f in ix.functions.values() if f["file"] == rel and f["name"] == name]
            if not fns:
                raise ValueError(f"gold target not found in index: {t}")
            f = fns[0]
            spans.append((rel, f["start_line"], f["end_line"], t))
        else:
            rel, line = t.split(":L")
            spans.append((rel, int(line), int(line), t))
    return spans


def match(loc: dict, spans) -> str | None:
    """Return the gold id this location satisfies (None if irrelevant)."""
    for rel, s, e, gid in spans:
        if loc["file"] != rel:
            continue
        ls, le = loc["start"], loc["end"]
        if ls > e or le < s:
            continue
        if s == e:  # line target
            if le - ls <= 60:
                return gid
            continue
        glen = e - s + 1
        if (le - ls + 1) <= max(3 * glen, glen + 20):
            return gid
    return None


def score(ranked: list[dict], spans) -> dict:
    gold_ids = [g[3] for g in spans]
    rel_flags, hit_ids = [], []
    seen = set()
    for loc in ranked:
        gid = match(loc, spans)
        rel_flags.append(gid is not None)
        hit_ids.append(gid if gid and gid not in seen else None)
        if gid:
            seen.add(gid)
    out = {}
    for k in KS:
        topk = rel_flags[:k]
        out[f"P@{k}"] = sum(topk) / k
        out[f"R@{k}"] = len({h for h in hit_ids[:k] if h}) / len(gold_ids)
    out["MRR"] = next((1 / (i + 1) for i, f in enumerate(rel_flags) if f), 0.0)
    # set metrics over everything returned (what a developer actually reads)
    n_ret = len(ranked)
    out["set_P"] = (sum(rel_flags) / n_ret) if n_ret else 0.0
    out["set_R"] = len(seen) / len(gold_ids)
    return out


def run(args):
    gold = json.loads((ROOT / "eval" / "gold.json").read_text())
    repo = ROOT / gold["repo"]
    ix = CodeIndex(repo)
    t0 = time.perf_counter()
    meta = ix.build(force=True)
    print(f"indexed {meta['stats']['files']} files / {meta['stats']['chunks']} chunks in {time.perf_counter() - t0:.1f}s")
    retr = Retriever(ix)
    systems = {
        "bm25": lambda q: retr.search(q, 10, mode="bm25"),
        "dense": lambda q: retr.search(q, 10, mode="dense"),
        "hybrid": lambda q: retr.search(q, 10, mode="hybrid"),
    }
    det_agent = Agent(ix, llm=LLM(provider="none"))
    systems["agent"] = lambda q: [l for l in det_agent.ask(q, use_llm=False)["locations"] if not l.get("related")]
    if args.llm:
        llm = LLM()
        if not llm.available:
            print("!! --llm requested but no provider configured (set GEMINI_API_KEY / GROQ_API_KEY / OPENAI_API_KEY)")
        else:
            llm_agent = Agent(ix, llm=llm)
            systems[f"agent+llm"] = lambda q: [l for l in llm_agent.ask(q, use_llm=True)["locations"] if not l.get("related")]

    # warm up (model load, caches) so latency reflects steady state
    for fn in systems.values():
        fn("warm up query")

    per_query = []
    for q in gold["queries"]:
        row = {"id": q["id"], "type": q["type"], "query": q["query"], "n_gold": len(q["relevant"]), "systems": {}}
        spans = gold_spans(ix, q["relevant"])
        for name, fn in systems.items():
            t = time.perf_counter()
            ranked = fn(q["query"])
            ms = (time.perf_counter() - t) * 1000
            if spans:
                m = score(ranked, spans)
            else:  # negative query: correct answer is "nothing"
                m = {"negative_correct": float(len(ranked) == 0)}
            m["latency_ms"] = ms
            m["returned"] = len(ranked)
            row["systems"][name] = m
        per_query.append(row)
        print(f"{q['id']:<8}" + "  ".join(
            f"{n}:{row['systems'][n].get('R@5', row['systems'][n].get('negative_correct', 0)):.2f}" for n in systems))

    # aggregate
    def agg(rows, name):
        pos = [r["systems"][name] for r in rows if r["n_gold"]]
        neg = [r["systems"][name] for r in rows if not r["n_gold"]]
        lat = sorted(r["systems"][name]["latency_ms"] for r in rows)
        out = {k: round(statistics.mean(m[k] for m in pos), 3) for k in
               [f"P@{k}" for k in KS] + [f"R@{k}" for k in KS] + ["MRR", "set_P", "set_R"]} if pos else {}
        if neg:
            out["negative_correct"] = round(statistics.mean(m["negative_correct"] for m in neg), 3)
        out["latency_p50_ms"] = round(lat[len(lat) // 2], 1)
        out["latency_p95_ms"] = round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1)
        out["n"] = len(rows)
        return out

    types = sorted({r["type"] for r in per_query})
    summary = {name: {"all": agg(per_query, name), **{t: agg([r for r in per_query if r["type"] == t], name) for t in types}}
               for name in systems}

    # optimisation detector precision / recall against the expected findings
    expected = {(f["file"], f["line"], f["rule"]) for f in gold["expected_findings"]}
    found = {(f["file"], f["line"], f["rule"]) for f in ix.findings}
    tp = len(expected & found)
    detector = {"expected": len(expected), "found": len(found), "true_positive": tp,
                "precision": round(tp / len(found), 3) if found else 0, "recall": round(tp / len(expected), 3),
                "false_positives": sorted(found - expected), "missed": sorted(expected - found)}

    results = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repo": gold["repo"],
        "embedder": meta["embedder"],
        "index": meta["stats"],
        "summary": summary,
        "detector": detector,
        "per_query": per_query,
    }
    if args.scale:
        results["scale"] = scale_benchmark(repo, args.scale, [q["query"] for q in gold["queries"]])

    out = ROOT / "eval" / "results.json"
    out.write_text(json.dumps(results, indent=2))
    (ROOT / "eval" / "RESULTS.md").write_text(render_md(results))
    print(f"\nwrote {out} and eval/RESULTS.md")
    print(render_md(results))


def scale_benchmark(repo: Path, copies: int, queries: list[str]) -> dict:
    """Replicate the repo N times (renamed dirs) to measure indexing cost and latency at scale."""
    tmp = Path(tempfile.mkdtemp(prefix="carto-scale-"))
    try:
        for i in range(copies):
            shutil.copytree(repo / "src", tmp / f"pkg{i:03d}" / "src")
        ix = CodeIndex(tmp)
        t = time.perf_counter()
        meta = ix.build(force=True)
        cold = time.perf_counter() - t
        # incremental: touch one file and rebuild
        f = next((tmp / "pkg000" / "src" / "agents").glob("*.js"))
        f.write_text(f.read_text() + "\n// touched\n")
        t = time.perf_counter()
        meta2 = ix.build()
        warm = time.perf_counter() - t
        agent = Agent(ix, llm=LLM(provider="none"))
        agent.ask("warm up")
        lats = []
        for q in queries:
            t = time.perf_counter()
            agent.ask(q, use_llm=False)
            lats.append((time.perf_counter() - t) * 1000)
        lats.sort()
        return {
            "copies": copies, "files": meta["stats"]["files"], "loc": meta["stats"]["loc"],
            "chunks": meta["stats"]["chunks"], "approx_repo_tokens": meta["stats"]["approx_repo_tokens"],
            "cold_index_s": round(cold, 2), "parse_s": meta["stats"]["parse_s"], "embed_s": meta["stats"]["embed_s"],
            "incremental_reindex_s": round(warm, 2), "incremental_files_parsed": meta2["stats"]["files_parsed"],
            "incremental_chunks_embedded": meta2["stats"]["chunks_embedded"],
            "index_mb": round(meta["stats"].get("index_bytes", 0) / 1e6, 2),
            "agent_latency_p50_ms": round(lats[len(lats) // 2], 1),
            "agent_latency_p95_ms": round(lats[int(len(lats) * 0.95)], 1),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        idx = CodeIndex(tmp).dir
        shutil.rmtree(idx, ignore_errors=True)


def render_md(r: dict) -> str:
    s = r["index"]
    lines = [
        "# CodeCartographer - Evaluation Results", "",
        f"Generated {r['generated_at']} on `{r['repo']}` with embedder `{r['embedder']}` (CPU only).", "",
        "## Indexing cost", "",
        "| files | LOC | functions | call sites | resolved edges | tools | chunks | parse | embed | total | index size |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        f"| {s['files']} | {s['loc']} | {s['functions']} | {s['call_sites']} | {s['resolved_edges']} | {s['tools']} | {s['chunks']} "
        f"| {s['parse_s']}s | {s['embed_s']}s | {s['total_s']}s | {s.get('index_bytes', 0) / 1e6:.2f} MB |", "",
        "## Retrieval quality (all 41 positive queries)", "",
        "| system | P@1 | P@5 | R@5 | R@10 | MRR | set precision | set recall | p50 latency | p95 latency |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, m in r["summary"].items():
        a = m["all"]
        lines.append(f"| **{name}** | {a['P@1']:.2f} | {a['P@5']:.2f} | {a['R@5']:.2f} | {a['R@10']:.2f} | {a['MRR']:.2f} "
                     f"| {a['set_P']:.2f} | {a['set_R']:.2f} | {a['latency_p50_ms']} ms | {a['latency_p95_ms']} ms |")
    lines += ["", "## Recall@5 by query type", "", "| system | " + " | ".join(t for t in r["summary"]["agent"] if t != "all") + " |",
              "|---|" + "---|" * (len(r["summary"]["agent"]) - 1)]
    for name, m in r["summary"].items():
        lines.append(f"| {name} | " + " | ".join(f"{m[t].get('R@5', 0):.2f}" for t in m if t != "all") + " |")
    neg = {n: m["all"].get("negative_correct") for n, m in r["summary"].items()}
    lines += ["", f"Negative query (correct answer is *no file*): " + ", ".join(f"{n}={'correct' if v == 1 else 'wrong'}" for n, v in neg.items()), ""]
    d = r["detector"]
    lines += ["## Optimisation detectors (bonus)", "",
              f"Precision **{d['precision']:.2f}**, recall **{d['recall']:.2f}** on {d['expected']} expected findings "
              f"({d['found']} reported).", ""]
    if "scale" in r:
        sc = r["scale"]
        lines += ["## Scale benchmark", "",
                  f"Repo replicated {sc['copies']}x: **{sc['files']} files, {sc['loc']} LOC, ~{sc['approx_repo_tokens']:,} tokens** "
                  "(far beyond any LLM context window).", "",
                  "| cold index | parse | embed | incremental re-index (1 file changed) | index size | agent p50 | agent p95 |",
                  "|---|---|---|---|---|---|---|",
                  f"| {sc['cold_index_s']}s | {sc['parse_s']}s | {sc['embed_s']}s | {sc['incremental_reindex_s']}s "
                  f"({sc['incremental_files_parsed']} file, {sc['incremental_chunks_embedded']} chunks) | {sc['index_mb']} MB "
                  f"| {sc['agent_latency_p50_ms']} ms | {sc['agent_latency_p95_ms']} ms |", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="also evaluate the LLM-driven agent")
    ap.add_argument("--scale", type=int, default=0, help="replicate the repo N times for a scale benchmark")
    run(ap.parse_args())
