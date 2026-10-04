"""Minimal Model Context Protocol (MCP) server over stdio - no extra dependencies.

Lets Claude Code, Cursor, VS Code Copilot or any MCP client use CodeCartographer as a tool:

  claude mcp add codecartographer -- python -m cartographer mcp /path/to/repo

Messages are newline-delimited JSON-RPC 2.0, per the MCP stdio transport.
"""

from __future__ import annotations

import json
import sys

from . import __version__

PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "ask_codebase",
        "description": "Ask a natural-language question about the indexed JavaScript codebase. Returns a grounded answer "
                       "with verified file:line locations. Handles semantic ('where do we retry requests'), usage "
                       "('where is the bluetooth settings deeplink used'), caller and structural "
                       "('which files call tool A before tool B') questions.",
        "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
    },
    {
        "name": "call_order",
        "description": "Structural query: functions/files that call `first` before `then` (branch-aware, inter-procedural). "
                       "Set negate=true to find calls of `then` with no prior `first`.",
        "inputSchema": {"type": "object", "properties": {
            "first": {"type": "string"}, "then": {"type": "string"}, "negate": {"type": "boolean"}},
            "required": ["first", "then"]},
    },
    {
        "name": "search_code",
        "description": "Hybrid (BM25 + code embeddings + symbols) search returning ranked file:line spans.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]},
    },
    {
        "name": "find_references",
        "description": "All usages of an identifier / constant / member (e.g. BLUETOOTH_SETTINGS).",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
    {
        "name": "read_code",
        "description": "Read an exact line span from a file in the repository.",
        "inputSchema": {"type": "object", "properties": {
            "file": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}}, "required": ["file", "start"]},
    },
]


def serve(repo: str):
    from .agent import Agent
    from .indexer import CodeIndex
    from .llm import LLM

    ix = CodeIndex(repo)
    ix.load() if ix.exists() else ix.build()
    agent = Agent(ix, LLM(provider="none"))  # the MCP client is the LLM; keep the server deterministic

    def respond(mid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": mid}
        if error:
            msg["error"] = error
        else:
            msg["result"] = result
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        mid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
        if mid is None:  # notification (e.g. notifications/initialized)
            continue
        try:
            if method == "initialize":
                respond(mid, {"protocolVersion": params.get("protocolVersion", PROTOCOL),
                              "capabilities": {"tools": {}},
                              "serverInfo": {"name": "codecartographer", "version": __version__}})
            elif method == "tools/list":
                respond(mid, {"tools": TOOLS})
            elif method == "tools/call":
                name, args = params.get("name"), params.get("arguments") or {}
                if name == "ask_codebase":
                    fin = agent.ask(args["question"], use_llm=False)
                    text = fin["answer"] + "\n\n" + "\n".join(
                        f"- {l['file']}:{l['start']}-{l['end']} `{l['symbol']}` - {l['why']}" for l in fin["locations"])
                    if fin["optimizations"]:
                        text += "\n\nOptimisation suggestions:\n" + "\n".join(
                            f"- [{o['severity']}] {o['file']}:{o['line']} {o['title']}: {o['suggestion']}" for o in fin["optimizations"])
                else:
                    text, _ = agent.tb.call(name, args)
                respond(mid, {"content": [{"type": "text", "text": text}]})
            elif method == "ping":
                respond(mid, {})
            else:
                respond(mid, error={"code": -32601, "message": f"Method not found: {method}"})
        except Exception as exc:
            respond(mid, {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True})
