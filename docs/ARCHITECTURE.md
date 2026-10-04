# Architecture

## Design goals (from the Theme 01 brief)

| Requirement | Design decision |
|---|---|
| Plain-English question → snippets with file + line | Function-level chunks with exact spans. Every answer is a list of verified `file:start-end` locations |
| Structural queries ("calls tool XYZ before tool ABC") | AST call graph with execution-ordered, branch-guarded call sites; tool invocation → handler edges |
| Usage queries ("where is the Bluetooth-settings deeplink used") | Symbol + reference + string-literal indexes with alias-table hops |
| Agentic over a repo larger than the context window | The agent sees only tool outputs (ranked spans, symbol hits, exact line ranges) and never whole files |
| CPU only, minimal GPU | tree-sitter (C), BM25 (pure Python), jina-v2-base-code via ONNX Runtime CPU |
| Report precision@k, recall, latency, indexing cost | `eval/run_eval.py` with a labelled gold set, baselines and a scale benchmark |
| Bonus: optimisation suggestions | 8 AST detectors run at index time and attached to surfaced code paths |

## Index (per repository, incremental)

```
.cartographer/<repo>-<hash>/
  index.json       files{sha1, imports, symbols, refs, strings, findings}, functions{calls[], …}, chunks[]
  embeddings.npy   float32 [n_chunks, 768]
  meta.json        stats: files, LOC, functions, call sites, edges, tools, timings, size
```

* **Parsing**: one tree-sitter pass per file extracts named functions (declarations, methods, named arrows,
  `module.exports.x = function`, and tool handlers registered via `register('name', fn)`). Anonymous callbacks
  are inlined into their enclosing function, so `arr.forEach(x => tools.invoke('a'))` still counts as calling `a`.
* **Call sites** are recorded in evaluation order (post-order). Each one stores its callee text, last identifier,
  tool name (if the first argument of `invoke/callTool/runTool/…` is a string literal), whether it sits in a loop,
  and its **guard**, the list of `[branch_node_id, arm]` pairs it lives under.
* **Resolution**: `this.m()` → method of the class or its parents. `f()` → local function or an imported binding.
  `ns.f()` → `f` in the imported module. `invoke('tool')` → the registered handler. Otherwise a globally unique name.
* **Incremental**: files with an unchanged SHA-1 reuse their parsed facts. Chunks with an unchanged content hash
  reuse their vectors. Embedding batches are length-sorted to minimise padding (2.2× faster on CPU).

## Query engine

* `graph.call_order(A, B, negate)`: for each function, build an expanded event sequence (depth ≤ 3, cycle-safe,
  guards concatenated along the expansion path). There is a match if an `A` event precedes a `B` event and no shared
  branch node puts them in different arms. Duplicate parents whose match is entirely inside one child call are suppressed.
  `negate` returns `B` calls with no preceding, non-exclusive `A`.
* `resolve_term`: maps phrases to names ("permission check" → `checkPermission`) using exact → called-name →
  token-overlap + fuzzy scoring, with a tool bonus. Confidence is reported in the trace.
* `retrieval.search`: weighted RRF over BM25, dense, the optional rewrite channels and the symbol channel,
  followed by a mild name-overlap re-score.

## Agent

```
classify ─┬─ structural → call_order → locations (+ via-chains)
          ├─ callers    → callers → group by function
          ├─ usage      → find_symbol → find_references → alias-table hop(s)
          ├─ optimize   → search_code (scope) → optimizations
          └─ semantic   → rewrite → search_code (multi-query) → read_code → callees (expand)
                                   │
           optional LLM refine ◄───┘  (JSON tool-calling loop, max 8 steps, starts from planner evidence)
                                   │
                              verifier  →  final event (answer, locations, graph, optimisations, metrics)
```

Every step is streamed as an event (`plan`, `rewrite`, `step`, `observation`, `verify`, `final`). The web UI
renders them live over Server-Sent Events, and the CLI prints them as a trace.

## Why a deterministic planner and an LLM

* The deterministic planner makes the system **work offline, on CPU, for free**, and keeps the evaluation reproducible.
* The LLM adds what heuristics can't: paraphrase-robust query rewriting, follow-up tool calls when the evidence is
  thin, and a natural-language explanation. Its locations go through the same verifier, so it cannot introduce
  hallucinated paths.

## Interfaces

* Web UI: `python -m cartographer serve`
* REST/SSE: `/api/ask`, `/api/search`, `/api/tool/{name}`, `/api/graph`, `/api/file`, `/api/index`, `/api/eval`
* CLI: `python -m cartographer index | ask | search | serve | mcp`
* MCP stdio server: `ask_codebase`, `call_order`, `search_code`, `find_references`, `read_code`
