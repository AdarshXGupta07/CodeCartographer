"""The agent's toolbox. Every tool returns (compact_text_for_llm, structured_data).

Tools never return whole files: the agent works over a repo far larger than any
context window by pulling only ranked chunks, symbol hits and exact line spans.
"""

from __future__ import annotations

import re
from collections import Counter

from .graph import GraphQueries
from .retrieval import Retriever

TOOL_SPECS = [
    {"name": "search_code", "args": {"query": "natural language or identifiers", "k": "int, default 8"},
     "desc": "Hybrid semantic+lexical search over function-level chunks. Returns ranked file:line spans."},
    {"name": "find_symbol", "args": {"name": "identifier, constant, tool name or phrase"},
     "desc": "Fuzzy lookup of definitions: functions, classes, constants, object keys, tool names, string literals."},
    {"name": "find_references", "args": {"name": "exact identifier, e.g. BLUETOOTH_SETTINGS"},
     "desc": "Every place an identifier (or member like DEEPLINKS.X, or a string literal equal to it) is used."},
    {"name": "callers", "args": {"name": "function or tool name"},
     "desc": "All call sites of a function or tool invocation (tool calls like registry.invoke('x') included)."},
    {"name": "callees", "args": {"name": "function name"},
     "desc": "Ordered calls made by a function, with resolved targets."},
    {"name": "call_order", "args": {"first": "tool/function", "then": "tool/function", "negate": "bool"},
     "desc": "Structural query: functions/files that call `first` before `then` on some execution path "
             "(inter-procedural, branch-aware). negate=true finds calls of `then` with NO prior `first`."},
    {"name": "read_code", "args": {"file": "path", "start": "line", "end": "line"},
     "desc": "Read an exact line span (max 80 lines)."},
    {"name": "repo_map", "args": {"path": "optional directory prefix"},
     "desc": "Directory overview: files, their main symbols and tools. Use to orient in an unfamiliar area."},
    {"name": "optimizations", "args": {"file": "optional path", "function": "optional function name"},
     "desc": "Static performance findings (await in loop, sync I/O, N+1, regex in loop, ...)."},
]


class Toolbox:
    def __init__(self, index):
        self.ix = index
        self.retriever = Retriever(index)
        self.graph = GraphQueries(index)

    def call(self, name: str, args: dict):
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return f"Unknown tool {name}", {}
        try:
            return fn(**{k: v for k, v in (args or {}).items() if v is not None})
        except TypeError as exc:
            return f"Bad arguments for {name}: {exc}", {}

    # ---------------------------------------------------------------- tools
    def t_search_code(self, query: str, k: int = 8, mode: str = "hybrid", rewrites: list | None = None):
        res = self.retriever.search(query, int(k), mode=mode, rewrites=rewrites)
        lines = [f"{i+1}. {r['file']}:{r['start']}-{r['end']}  {r['symbol']}  (score {r['score']})" for i, r in enumerate(res)]
        return "\n".join(lines) or "no results", {"results": res}

    def t_find_symbol(self, name: str, k: int = 12):
        res = self.retriever.symbols(name, int(k))
        lines = [f"{s['kind']:<9} {s['name'][:70]}  @ {s['file']}:{s['line']}  (score {s['score']})" for s in res]
        return "\n".join(lines) or "no symbols", {"symbols": res}

    def t_find_references(self, name: str, limit: int = 60):
        name = name.strip().strip("`'\"")
        hits = []
        seen = set()
        variants = set(self.ix.refs_lower.get(name.lower(), set())) | {name}
        for v in variants:
            for rel, line, fid in self.ix.refs.get(v, []):
                if (rel, line) not in seen:
                    seen.add((rel, line))
                    hits.append({"file": rel, "line": line, "func_id": fid, "via": v})
        # member expressions ending with the name, e.g. DEEPLINKS.BLUETOOTH_SETTINGS
        for ref_name, occ in self.ix.refs.items():
            if "." in ref_name and ref_name.split(".")[-1] == name:
                for rel, line, fid in occ:
                    if (rel, line) not in seen:
                        seen.add((rel, line))
                        hits.append({"file": rel, "line": line, "func_id": fid, "via": ref_name})
        # string literals equal to the name (used as dynamic keys, e.g. SETTINGS_ALIASES values)
        for rel, finfo in self.ix.files.items():
            for val, line, fid in finfo["strings"]:
                if val == name and (rel, line) not in seen:
                    seen.add((rel, line))
                    hits.append({"file": rel, "line": line, "func_id": fid, "via": f"'{val}'"})
        hits.sort(key=lambda h: (h["file"], h["line"]))
        for h in hits:
            f = self.ix.functions.get(h["func_id"], {})
            h["function"] = f.get("name", "<module>")
            lines = self.ix.file_lines(h["file"])
            h["code"] = lines[h["line"] - 1].strip()[:160] if 0 < h["line"] <= len(lines) else ""
        hits = hits[:limit]
        out = [f"{h['file']}:{h['line']}  in {h['function']}  | {h['code']}" for h in hits]
        return "\n".join(out) or f"no references to {name}", {"references": hits}

    def t_callers(self, name: str):
        res = self.graph.callers(name)
        out = [f"resolved '{name}' -> {res['target']['name']} (tool={res['target']['is_tool']})"]
        out += [f"{s['file']}:{s['line']}  {s['function']} -> {s['callee']}" for s in res["call_sites"]]
        return "\n".join(out), res

    def t_callees(self, name: str):
        res = self.graph.callees(name)
        out = []
        for f in res["functions"][:3]:
            out.append(f"{f['function']} @ {f['file']}:{f['line']}")
            for c in f["calls"][:40]:
                tgt = f" -> {', '.join(c['resolved'])}" if c["resolved"] else ""
                out.append(f"   L{c['line']} {c['callee']}{'(' + repr(c['tool']) + ')' if c['tool'] else ''}{tgt}")
        return "\n".join(out) or f"no function named {name}", res

    def t_call_order(self, first: str, then: str, negate=False):
        negate = negate in (True, "true", "True", 1, "1")
        res = self.graph.call_order(first, then, negate=negate)
        a, b = res["first"], res["then"]
        head = (f"'{first}' -> {a['name']} (conf {a['confidence']}), '{then}' -> {b['name']} (conf {b['confidence']}). "
                f"{len(res['matches'])} function(s) in {len(res['files'])} file(s)")
        out = [head]
        for h in res["matches"]:
            if negate:
                out.append(f"{h['file']}:{h['then_call']['line']}  {h['function']} calls {b['name']} with no prior {a['name']}")
            else:
                via = "" if h["direct"] else "  (via " + " -> ".join(x["function"] for x in h["then_call"]["via"]) + ")"
                out.append(f"{h['file']}  {h['function']}: {a['name']} @L{h['first_call']['line']} before {b['name']} @L{h['then_call']['line']}{via}")
        return "\n".join(out), res

    def t_read_code(self, file: str, start: int = 1, end: int | None = None):
        start = int(start)
        end = int(end) if end is not None else start + 40
        end = min(end, start + 80)
        if file not in self.ix.files:
            cands = [f for f in self.ix.files if f.endswith(file)]
            if not cands:
                return f"file {file} not in index", {}
            file = cands[0]
        snip = self.ix.snippet(file, start, end)
        numbered = "\n".join(f"{snip['start'] + i:>5} {l}" for i, l in enumerate(snip["code"].split("\n")))
        return numbered, snip

    def t_repo_map(self, path: str = ""):
        files = sorted(f for f in self.ix.files if f.startswith(path))
        dirs = Counter(f.rsplit("/", 1)[0] if "/" in f else "." for f in files)
        out = [f"{len(files)} files under '{path or '/'}'"]
        if len(files) > 60:
            out += [f"  {d}/  ({n} files)" for d, n in sorted(dirs.items())]
            return "\n".join(out), {"dirs": dict(dirs)}
        for rel in files:
            syms = [s for s in self.ix.files[rel]["symbols"] if s[1] in ("class", "function", "method", "tool_handler")]
            names = ", ".join(s[0] for s in syms[:8])
            out.append(f"  {rel}: {names}")
        return "\n".join(out), {"files": files}

    def t_optimizations(self, file: str = "", function: str = ""):
        res = [fd for fd in self.ix.findings
               if (not file or fd["file"].endswith(file)) and (not function or function.lower() in fd["function"].lower())]
        out = [f"{fd['file']}:{fd['line']} [{fd['severity']}] {fd['title']} in {fd['function']} | {fd['code']}" for fd in res[:30]]
        return "\n".join(out) or "no findings", {"findings": res}


# ------------------------------------------------------------------- planner
ORDER_RE = re.compile(
    r"(?:call|calls|invoke|invokes|use|uses|run|runs|trigger|triggers|execute|executes)?\s*"
    r"(?:the\s+)?(?:tool\s+)?[`'\"]?(?P<a>[\w.\- ]+?)[`'\"]?\s+(?:tool\s+)?"
    r"(?P<rel>before|prior to|ahead of|after|followed by|and then|then)\s+"
    r"(?:calling\s+|invoking\s+|using\s+|running\s+)?(?:the\s+)?(?:tool\s+)?[`'\"]?(?P<b>[\w.\- ]+?)[`'\"]?"
    r"(?:\s+tool)?\s*\??$", re.I)
WITHOUT_RE = re.compile(
    r"(?:call|calls|invoke|invokes|open|opens|use|uses|launch|launches|run|runs)\s+(?:the\s+|a\s+|an\s+)?(?:tool\s+)?[`'\"]?(?P<b>[\w.\- ]+?)[`'\"]?\s+"
    r"without\s+(?:first\s+)?(?:calling\s+|checking\s+|invoking\s+|running\s+|doing\s+)?(?:a\s+|an\s+|the\s+)?(?:tool\s+)?[`'\"]?(?P<a>[\w.\- ]+?)[`'\"]?"
    r"(?:\s+first|\s+before)?\s*\??$", re.I)
CALLERS_RE = re.compile(
    r"(?:who|what|which\s+\w+)\s+(?:calls|invokes|uses|triggers)\s+(?:the\s+)?(?:tool\s+)?[`'\"]?(?P<x>[\w.]+)[`'\"]?|"
    r"callers?\s+of\s+(?:the\s+)?(?:tool\s+)?[`'\"]?(?P<y>[\w.]+)|"
    r"where\s+is\s+(?:the\s+)?(?:tool\s+)?[`'\"]?(?P<z>[A-Za-z_$][\w$]*[A-Z_][\w$]*|[\w$]+\(\))[`'\"]?\s+(?:called|invoked)", re.I)
USAGE_RE = re.compile(r"\b(where\s+(?:is|are|do|does)\b.*\b(used|referenced|read|accessed|launched|opened)|usages?\s+of|references?\s+to|who\s+uses)\b", re.I)
OPT_RE = re.compile(r"\b(optimi[sz]\w*|slow|performance|bottleneck|speed\s*up|inefficien\w*|latency)\b", re.I)


def classify(question: str) -> dict:
    q = question.strip().rstrip("?").strip()
    m = WITHOUT_RE.search(q)
    if m:
        return {"type": "structural", "first": _clean(m.group("a")), "then": _clean(m.group("b")), "negate": True}
    m = ORDER_RE.search(q)
    if m and re.search(r"\b(call|invoke|use|run|trigger|execute|tool)", q, re.I):
        a, b, rel = _clean(m.group("a")), _clean(m.group("b")), m.group("rel").lower()
        if rel in ("after",):
            a, b = b, a
        return {"type": "structural", "first": a, "then": b, "negate": False}
    m = CALLERS_RE.search(q)
    if m:
        x = (m.group("x") or m.group("y") or m.group("z") or "").strip("()")
        return {"type": "callers", "target": x}
    if OPT_RE.search(q):
        return {"type": "optimize"}
    if USAGE_RE.search(q):
        return {"type": "usage"}
    return {"type": "semantic"}


def _clean(s: str) -> str:
    s = re.sub(r"^(which|what|files?|functions?|agents?|that|who|do|does|any|all|code)\s+", "", s.strip(), flags=re.I)
    s = re.sub(r"^(which|what|files?|functions?|agents?|that|who|do|does|any|all)\s+", "", s.strip(), flags=re.I)
    s = re.sub(r"^(call|calls|invoke|invokes|use|uses)\s+", "", s, flags=re.I)
    s = re.sub(r"^(the|a|an|tool)\s+", "", s, flags=re.I)
    s = re.sub(r"\s+(tool|function|method)$", "", s, flags=re.I)
    return s.strip()
