# CodeCartographer - Evaluation Results

Generated 2026-10-04 21:00:12 on `sample_repo/nova-assistant` with embedder `jinaai/jina-embeddings-v2-base-code` (CPU only).

## Indexing cost

| files | LOC | functions | call sites | resolved edges | tools | chunks | parse | embed | total | index size |
|---|---|---|---|---|---|---|---|---|---|---|
| 43 | 1365 | 113 | 356 | 123 | 22 | 156 | 0.039s | 18.422s | 18.477s | 1.04 MB |

## Retrieval quality (all 41 positive queries)

| system | P@1 | P@5 | R@5 | R@10 | MRR | set precision | set recall | p50 latency | p95 latency |
|---|---|---|---|---|---|---|---|---|---|
| **bm25** | 0.37 | 0.24 | 0.78 | 0.92 | 0.58 | 0.17 | 0.92 | 0.1 ms | 0.2 ms |
| **dense** | 0.68 | 0.28 | 0.87 | 0.93 | 0.79 | 0.16 | 0.93 | 16.8 ms | 19.5 ms |
| **hybrid** | 0.66 | 0.29 | 0.88 | 0.95 | 0.81 | 0.17 | 0.95 | 18.3 ms | 20.9 ms |
| **agent** | 0.78 | 0.34 | 0.98 | 1.00 | 0.88 | 0.48 | 1.00 | 33.5 ms | 38.7 ms |

## Recall@5 by query type

| system | callers | semantic | structural | usage |
|---|---|---|---|---|
| bm25 | 0.90 | 0.90 | 0.54 | 0.33 |
| dense | 0.75 | 0.98 | 0.75 | 0.60 |
| hybrid | 0.95 | 0.94 | 0.75 | 0.65 |
| agent | 1.00 | 1.00 | 1.00 | 0.85 |

Negative query (correct answer is *no file*): bm25=wrong, dense=wrong, hybrid=wrong, agent=correct

## Optimisation detectors (bonus)

Precision **1.00**, recall **1.00** on 12 expected findings (12 reported).

## Scale benchmark

Repo replicated 20x: **860 files, 27300 LOC, ~236,662 tokens** (far beyond any LLM context window).

| cold index | parse | embed | incremental re-index (1 file changed) | index size | agent p50 | agent p95 |
|---|---|---|---|---|---|---|
| 298.53s | 0.969s | 296.774s | 0.84s (1 file, 0 chunks) | 22.21 MB | 48.8 ms | 129.2 ms |
