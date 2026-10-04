"""Command line interface.

  python -m cartographer index <repo>            build / incrementally update the index
  python -m cartographer ask <repo> "<question>" run the agent and print a grounded answer
  python -m cartographer search <repo> "<query>" raw hybrid search
  python -m cartographer serve [--repo R]        web UI + API on http://localhost:8000
  python -m cartographer mcp <repo>              MCP stdio server for Claude Code / Cursor / VS Code
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from . import __version__

BOLD, DIM, GREEN, CYAN, YELLOW, RED, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[36m", "\033[33m", "\033[31m", "\033[0m"


def _progress(ev):
    sys.stderr.write(f"\r  {ev['stage']:<6} {ev['done']}/{ev['total']}   ")
    sys.stderr.flush()


def cmd_index(a):
    from .indexer import CodeIndex
    ix = CodeIndex(a.repo)
    meta = ix.build(progress=_progress, force=a.force)
    sys.stderr.write("\n")
    s = meta["stats"]
    print(f"{GREEN}Indexed{RESET} {BOLD}{meta['repo_name']}{RESET} -> {ix.dir}")
    print(f"  {s['files']} files ({s['files_parsed']} parsed, {s['files_reused']} unchanged), {s['loc']} LOC, "
          f"{s['functions']} functions, {s['call_sites']} call sites, {s['tools']} tools, {s['chunks']} chunks")
    print(f"  parse {s['parse_s']}s | embed {s['embed_s']}s ({s['chunks_embedded']} new chunks, {meta['embedder']}) | total {s['total_s']}s")
    print(f"  {s['findings']} optimisation findings")


def cmd_ask(a):
    from .agent import Agent
    from .indexer import CodeIndex
    from .llm import LLM
    ix = CodeIndex(a.repo)
    ix.load() if ix.exists() else ix.build(progress=_progress)
    agent = Agent(ix, LLM() if not a.offline else LLM(provider="none"))
    final = None
    for ev in agent.run(a.question, use_llm=not a.offline):
        t = ev["type"]
        if a.json:
            if t == "final":
                final = ev
            continue
        if t == "plan":
            print(f"{CYAN}plan{RESET}   [{ev['query_type']}] {ev['text']}  {DIM}({ev['planner']}){RESET}")
        elif t == "rewrite":
            print(f"{CYAN}rewrite{RESET} {ev['text']}")
        elif t == "step":
            print(f"{CYAN}step {ev['n']}{RESET} {ev['tool']}({json.dumps(ev['args'])[:100]})  {DIM}{ev['thought']}{RESET}")
        elif t == "observation":
            print(f"   {DIM}-> {ev['summary']} ({ev['ms']} ms){RESET}")
        elif t == "verify":
            print(f"{GREEN}verify{RESET} {ev['text']}")
        elif t == "warning":
            print(f"{YELLOW}warn{RESET}   {ev['text']}")
        elif t == "final":
            final = ev
    if a.json:
        print(json.dumps({k: final[k] for k in ("question", "query_type", "answer", "locations", "optimizations", "metrics")}, indent=2))
        return
    print(f"\n{BOLD}{final['answer']}{RESET}\n")
    for i, l in enumerate(final["locations"], 1):
        print(f"{BOLD}{i}. {l['file']}:{l['start']}-{l['end']}{RESET}  {CYAN}{l['symbol']}{RESET}  {DIM}{l['why']}{RESET}")
        if a.code:
            for n, line in enumerate(l["code"].split("\n")[:25], l["start"]):
                mark = f"{YELLOW}>{RESET}" if n in l.get("highlight", []) else " "
                print(f"   {mark}{DIM}{n:>4}{RESET} {line}")
    if final["optimizations"]:
        print(f"\n{YELLOW}Optimisation suggestions{RESET}")
        for o in final["optimizations"]:
            print(f"  [{o['severity']}] {o['file']}:{o['line']} {o['title']} - {o['suggestion']}")
    m = final["metrics"]
    print(f"\n{DIM}{m['latency_ms']} ms, {m['tool_calls']} tool calls, planner: {m['planner']}{RESET}")


def cmd_search(a):
    from .indexer import CodeIndex
    from .retrieval import Retriever
    ix = CodeIndex(a.repo).load()
    for i, r in enumerate(Retriever(ix).search(a.query, a.k, mode=a.mode), 1):
        print(f"{i:>2}. {r['file']}:{r['start']}-{r['end']}  {r['symbol']}  {DIM}{r['score']} {r['ranks']}{RESET}")


def cmd_serve(a):
    import uvicorn
    if a.repo:
        os.environ["CARTO_REPO"] = a.repo
    print(f"{GREEN}CodeCartographer{RESET} on http://localhost:{a.port}")
    uvicorn.run("cartographer.server:app", host=a.host, port=a.port, log_level="warning")


def cmd_mcp(a):
    from .mcp_server import serve
    serve(a.repo)


def main(argv=None):
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(prog="cartographer", description=f"CodeCartographer {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index"); p.add_argument("repo"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("ask"); p.add_argument("repo"); p.add_argument("question")
    p.add_argument("--offline", action="store_true", help="deterministic planner only, no LLM")
    p.add_argument("--code", action="store_true", help="print code snippets"); p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("search"); p.add_argument("repo"); p.add_argument("query"); p.add_argument("-k", type=int, default=10)
    p.add_argument("--mode", default="hybrid", choices=["hybrid", "bm25", "dense"]); p.set_defaults(fn=cmd_search)
    p = sub.add_parser("serve"); p.add_argument("--repo"); p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8000)
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("mcp"); p.add_argument("repo"); p.set_defaults(fn=cmd_mcp)
    a = ap.parse_args(argv)
    if os.name == "nt":
        os.system("")  # enable ANSI colours on Windows terminals
    t = time.perf_counter()
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
