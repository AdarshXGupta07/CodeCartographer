# AI Disclosure

**Team:** SRM_SpaceX (SRM Institute of Science and Technology): Adarsh Gupta, Aryan Sandilya, Ujjwal Pratap Singh
**Project:** CodeCartographer · Samsung PRISM GenAI Hackathon 2026 · Theme 01 – Agentic Code Intelligence

We used AI in two separate ways: as a **development assistant** while building the project, and as **models inside the product** at runtime. Both are disclosed below.

---

## 1. AI used during development

| Tool | Provider | Used for |
|---|---|---|
| Claude Code (Claude Opus 5.5) | Anthropic | Coding assistant during design, implementation, testing and documentation |

**What the AI assistant helped produce**
- Most of the Python source code in `cartographer/` (parser, indexer, call-graph queries, retrieval, agent, server, CLI, MCP server), and the web UI in `web/`.
- The sample JavaScript codebase in `sample_repo/nova-assistant/`. It is a synthetic voice-assistant repo written for the demo and evaluation, because the official sample codebase was not available to us while building. It deliberately contains bugs and performance anti-patterns for the evaluation.
- The labelled evaluation queries in `eval/gold.json`, the evaluation harness in `eval/run_eval.py`, and the tests in `tests/`.
- Drafts of the README, `docs/ARCHITECTURE.md`, `docs/DEMO_SCRIPT.md` and the presentation deck.

**What the team did**
- Chose the theme and the problem framing, and set the requirements and priorities from the Theme 01 brief (structural queries, usage queries, CPU-only, metrics reporting).
- Directed the build iteratively: reviewed the outputs, requested changes, and decided what goes into the submission.
- Ran the system, the test suite and the evaluation locally, and checked the results.
- Wrote the team details, recorded the demo video, and will present and defend the design decisions to the jury.

**Integrity of reported results**
- Every metric in `eval/RESULTS.md` and the deck is produced by running `python -m eval.run_eval --scale 20`. The numbers are reproducible and were not edited by hand.
- The evaluation queries and the sample repo were written by the same process that built the system. The results are therefore an internal benchmark, not an independent one (see *Limitations* in the README). We plan to label queries on the official Samsung codebase next.

---

## 2. AI / ML models used inside the product (runtime)

| Model | Role | Required? |
|---|---|---|
| `jinaai/jina-embeddings-v2-base-code` (via fastembed / ONNX Runtime, CPU) | Code embeddings for semantic search | Yes (falls back to a non-ML hashing embedder if unavailable) |
| Gemini / Groq / OpenAI / local Ollama models | Optional query rewriting and answer refinement | **No.** The default deterministic planner runs fully offline, and every reported metric uses it |

Whichever planner produces an answer, every file:line location is checked against the actual source code before it is shown, so neither path can return a made-up location.

---

## 3. Licences

All third-party libraries and models are open source and used under their respective licences (tree-sitter: MIT; fastembed: Apache-2.0; jina-embeddings-v2-base-code: Apache-2.0; FastAPI: MIT; Cytoscape.js: MIT; highlight.js: BSD-3-Clause).
