"""FastAPI server: streams the agent trace over Server-Sent Events and serves the web UI."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config
from .agent import Agent
from .indexer import CodeIndex
from .llm import LLM
from .tools import Toolbox

WEB = config.ROOT / "web"
DEFAULT_REPO = os.getenv("CARTO_REPO", str(config.ROOT / "sample_repo" / "nova-assistant"))

EXAMPLES = [
    {"type": "structural", "q": "Which files call tool checkPermission before tool openDeeplink?"},
    {"type": "usage", "q": "Where is the Bluetooth-settings deeplink used?"},
    {"type": "structural", "q": "Which agents open a deeplink without checking permission first?"},
    {"type": "semantic", "q": "How does the assistant decide which agent handles an intent?"},
    {"type": "callers", "q": "Who calls getUserLocation?"},
    {"type": "optimize", "q": "What is slow in smart home device discovery?"},
    {"type": "semantic", "q": "Where do we retry failed network requests with backoff?"},
]

app = FastAPI(title="CodeCartographer", version=__version__)


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.index: CodeIndex | None = None
        self.agent: Agent | None = None
        self.tools: Toolbox | None = None
        self.llm = LLM()

    def open(self, repo: str, rebuild: bool = False, progress=None):
        ix = CodeIndex(repo)
        if rebuild or not ix.exists():
            ix.build(progress=progress)
        else:
            ix.load()
        with self.lock:
            self.index, self.agent, self.tools = ix, Agent(ix, self.llm), Toolbox(ix)
        return ix

    def require(self):
        if self.index is None:
            raise HTTPException(409, "No repository indexed yet")
        return self.index


S = State()


@app.on_event("startup")
def _startup():
    repo = Path(DEFAULT_REPO)
    if repo.exists():
        S.open(str(repo))


def sse(gen):
    def stream():
        try:
            for ev in gen:
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        except Exception as exc:  # surface errors to the UI instead of a dead stream
            yield f"data: {json.dumps({'type': 'error', 'text': f'{exc.__class__.__name__}: {exc}'})}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ----------------------------------------------------------------------- API
@app.get("/api/status")
def status():
    ix = S.index
    return {
        "version": __version__,
        "repo": ix.meta.get("repo_name") if ix else None,
        "repo_path": str(ix.repo) if ix else None,
        "meta": ix.meta if ix else None,
        "llm": S.llm.describe(),
        "llm_available": S.llm.available,
        "examples": EXAMPLES,
    }


@app.get("/api/ask")
def ask(q: str = Query(..., min_length=2), llm: bool = True):
    S.require()
    return sse(S.agent.run(q, use_llm=llm))


@app.get("/api/index")
def index(path: str, rebuild: bool = True):
    p = Path(path).expanduser()
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f"Not a directory: {path}")

    def gen():
        import queue
        q: queue.Queue = queue.Queue()
        result = {}

        def work():
            try:
                ix = S.open(str(p), rebuild=rebuild, progress=lambda e: q.put({"type": "progress", **e}))
                result["meta"] = ix.meta
            except Exception as exc:
                result["error"] = str(exc)
            q.put(None)

        threading.Thread(target=work, daemon=True).start()
        while True:
            item = q.get()
            if item is None:
                break
            yield item
        if "error" in result:
            yield {"type": "error", "text": result["error"]}
        else:
            yield {"type": "indexed", "meta": result["meta"]}
    return sse(gen())


@app.get("/api/search")
def search(q: str, mode: str = "hybrid", k: int = 10):
    S.require()
    text, data = S.tools.call("search_code", {"query": q, "k": k, "mode": mode})
    return data


@app.get("/api/tool/{name}")
def tool(name: str, args: str = "{}"):
    S.require()
    text, data = S.tools.call(name, json.loads(args))
    return {"text": text, "data": data}


@app.get("/api/graph")
def graph(fid: str, hops: int = 1):
    S.require()
    return S.tools.graph.neighborhood([fid], hops=hops, limit=50)


@app.get("/api/file")
def file(path: str, start: int = 1, end: int = 0):
    ix = S.require()
    if path not in ix.files:
        raise HTTPException(404, "file not indexed")
    lines = ix.file_lines(path)
    return ix.snippet(path, start, end or len(lines))


@app.get("/api/findings")
def findings():
    ix = S.require()
    return {"findings": ix.findings}


@app.get("/api/map")
def repo_map():
    ix = S.require()
    tree = {}
    for rel, f in sorted(ix.files.items()):
        syms = [{"name": s[0], "kind": s[1], "line": s[2]} for s in f["symbols"] if s[1] in ("class", "function", "method", "tool_handler")]
        tree[rel] = {"loc": f["loc"], "symbols": syms, "findings": len(f["findings"])}
    return {"files": tree, "tools": sorted(ix.tool_handlers.keys())}


@app.get("/api/eval")
def eval_results():
    p = config.ROOT / "eval" / "results.json"
    if not p.exists():
        return JSONResponse({"error": "run `python -m eval.run_eval` first"}, status_code=404)
    return json.loads(p.read_text())


# ------------------------------------------------------------------------ UI
@app.get("/")
def home():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")
