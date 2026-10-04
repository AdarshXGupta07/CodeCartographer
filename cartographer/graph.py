"""Structural queries over the call graph.

The key query is *call order*: "which files call tool XYZ before tool ABC?".
For every function we build its execution-ordered event sequence, expanding calls into
resolved callees (including tool invocation -> registered tool handler) up to a depth
limit. Each event carries a branch guard; two events in different arms of the same
if/else, ternary or switch are mutually exclusive and never count as "before".
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from . import config
from .textutil import code_tokens, split_identifier


@dataclass
class Event:
    call: dict
    func_id: str                 # function whose body contains this call
    guard: list                  # concatenated guards along the expansion path
    chain: list = field(default_factory=list)  # [(func_id, line), ...] expansion path from the root


def _exclusive(g1: list, g2: list) -> bool:
    arms = {}
    for bid, arm in g1:
        arms[bid] = arm
    for bid, arm in g2:
        if bid in arms and arms[bid] != arm:
            return True
    return False


class GraphQueries:
    def __init__(self, index):
        self.ix = index
        self._seq_cache: dict[str, list[Event]] = {}

    # ------------------------------------------------------------ term matching
    def known_names(self) -> list[str]:
        names = set(self.ix.tool_handlers.keys())
        for f in self.ix.functions.values():
            if f["kind"] != "module" and not f["name"].startswith("tool:"):
                names.add(f["short_name"])
        return sorted(names)

    def resolve_term(self, term: str) -> dict:
        """Map a user phrase ("permission check", "openDeeplink") onto a tool / function name."""
        term = term.strip().strip("`'\"")
        tools = list(self.ix.tool_handlers.keys())
        names = self.known_names()
        low = {n.lower(): n for n in names}
        if term.lower() in low:
            n = low[term.lower()]
            return {"term": term, "name": n, "is_tool": n in self.ix.tool_handlers, "confidence": 1.0}
        # also accept names that only appear at call sites (unresolved / external)
        called = {c["name"].lower(): c["name"] for f in self.ix.functions.values() for c in f["calls"]}
        called.update({c["tool"].lower(): c["tool"] for f in self.ix.functions.values() for c in f["calls"] if c.get("tool")})
        if term.lower() in called:
            n = called[term.lower()]
            return {"term": term, "name": n, "is_tool": n in self.ix.tool_handlers, "confidence": 0.95}
        qt = set(code_tokens(term)) | {t.rstrip("s") for t in code_tokens(term)}
        best, best_score = None, 0.0
        for n in tools + names:
            nt = set(split_identifier(n)) | {n.lower()}
            overlap = len(qt & nt) / max(len(nt), 1)
            fuzzy = difflib.SequenceMatcher(None, term.lower().replace(" ", ""), n.lower()).ratio()
            score = 0.7 * overlap + 0.3 * fuzzy + (0.05 if n in self.ix.tool_handlers else 0)
            if score > best_score:
                best, best_score = n, score
        if best is None:
            return {"term": term, "name": term, "is_tool": False, "confidence": 0.0}
        return {"term": term, "name": best, "is_tool": best in self.ix.tool_handlers, "confidence": round(best_score, 2)}

    @staticmethod
    def _matches(call: dict, name: str) -> bool:
        n = name.lower()
        if call.get("tool") and call["tool"].lower() == n:
            return True
        return call["name"].lower() == n or call["callee"].lower().endswith("." + n)

    # ----------------------------------------------------------- event sequence
    def sequence(self, fid: str, depth: int | None = None) -> list[Event]:
        depth = config.CALL_EXPANSION_DEPTH if depth is None else depth
        key = f"{fid}|{depth}"
        if key in self._seq_cache:
            return self._seq_cache[key]
        out: list[Event] = []

        def walk(cur: str, d: int, prefix: list, chain: list, visited: frozenset):
            f = self.ix.functions.get(cur)
            if f is None:
                return
            for call in f["calls"]:
                g = prefix + call["guard"]
                link = chain + [(cur, call["line"])]
                out.append(Event(call=call, func_id=cur, guard=g, chain=link))
                if d > 0 and len(call["targets"]) == 1:
                    t = call["targets"][0]
                    if t not in visited and self.ix.functions.get(t, {}).get("kind") != "module":
                        walk(t, d - 1, g, link, visited | {t})

        walk(fid, depth, [], [], frozenset([fid]))
        self._seq_cache[key] = out
        return out

    def call_order(self, first: str, then: str, negate: bool = False, depth: int | None = None) -> dict:
        """Find functions where `first` is called before `then` on some path.

        negate=True instead finds functions that call `then` with NO preceding `first`
        (e.g. "deeplinks opened without a permission check").
        """
        a = self.resolve_term(first)
        b = self.resolve_term(then)
        hits = []
        for fid, f in self.ix.functions.items():
            if f["kind"] == "module" and not f["calls"]:
                continue
            seq = self.sequence(fid, depth)
            if not seq:
                continue
            if negate:
                for j, ev_b in enumerate(seq):
                    if not self._matches(ev_b.call, b["name"]):
                        continue
                    prior = [ev for ev in seq[:j] if self._matches(ev.call, a["name"]) and not _exclusive(ev.guard, ev_b.guard)]
                    if not prior and len(ev_b.chain) == 1:
                        hits.append(self._hit(fid, None, ev_b))
                        break
                continue
            found = None
            for i, ev_a in enumerate(seq):
                if not self._matches(ev_a.call, a["name"]):
                    continue
                for ev_b in seq[i + 1:]:
                    if self._matches(ev_b.call, b["name"]) and not _exclusive(ev_a.guard, ev_b.guard):
                        # skip if both events come from the same expanded child call: the child
                        # function is reported on its own, so the parent would be a duplicate
                        if len(ev_a.chain) > 1 and len(ev_b.chain) > 1 and ev_a.chain[0] == ev_b.chain[0]:
                            continue
                        found = (ev_a, ev_b)
                        break
                if found:
                    break
            if found:
                hits.append(self._hit(fid, *found))
        hits.sort(key=lambda h: (h["file"], h["line"]))
        files = sorted({h["file"] for h in hits})
        return {"first": a, "then": b, "negate": negate, "matches": hits, "files": files}

    def _hit(self, fid: str, ev_a: Event | None, ev_b: Event) -> dict:
        f = self.ix.functions[fid]
        def ev_json(ev: Event | None):
            if ev is None:
                return None
            hops = [{"function": self.ix.functions[c[0]]["name"], "file": self.ix.functions[c[0]]["file"], "line": c[1]} for c in ev.chain]
            return {"callee": ev.call["callee"], "tool": ev.call.get("tool"), "line": ev.call["line"],
                    "file": self.ix.functions[ev.func_id]["file"], "via": hops}
        return {
            "function": f["name"], "func_id": fid, "file": f["file"], "line": f["start_line"],
            "end_line": f["end_line"], "first_call": ev_json(ev_a), "then_call": ev_json(ev_b),
            "direct": (ev_a is None or len(ev_a.chain) == 1) and len(ev_b.chain) == 1,
        }

    # ------------------------------------------------------------ callers/callees
    def find_functions(self, name: str) -> list[str]:
        n = name.strip().strip("`'\"()").lower()
        if n.startswith("tool:"):
            n = n[5:]
        if n in self.ix.tool_handlers or n in {k.lower() for k in self.ix.tool_handlers}:
            return [fid for k, v in self.ix.tool_handlers.items() if k.lower() == n for fid in v]
        return list(self.ix.by_name.get(n, [])) or list(self.ix.by_short.get(n, []))

    def callers(self, name: str) -> dict:
        res = self.resolve_term(name)
        target = res["name"]
        sites = []
        for fid, f in self.ix.functions.items():
            for call in f["calls"]:
                if self._matches(call, target):
                    sites.append({"function": f["name"], "func_id": fid, "file": f["file"], "line": call["line"],
                                  "callee": call["callee"], "tool": call.get("tool")})
        return {"target": res, "call_sites": sites, "files": sorted({s["file"] for s in sites})}

    def callees(self, name: str) -> dict:
        fids = self.find_functions(name)
        out = []
        for fid in fids:
            f = self.ix.functions[fid]
            out.append({
                "function": f["name"], "file": f["file"], "line": f["start_line"],
                "calls": [{"callee": c["callee"], "tool": c.get("tool"), "line": c["line"],
                           "resolved": [self.ix.functions[t]["name"] + " @ " + self.ix.functions[t]["file"] for t in c["targets"]]}
                          for c in f["calls"]],
            })
        return {"functions": out}

    def neighborhood(self, fids: list[str], hops: int = 1, limit: int = 60) -> dict:
        """Nodes + edges around a set of functions, for the UI graph view."""
        nodes, edges = {}, []
        frontier = set(fids)
        for fid in fids:
            if fid in self.ix.functions:
                nodes[fid] = True
        for _ in range(hops):
            nxt = set()
            for fid in frontier:
                f = self.ix.functions.get(fid)
                if not f:
                    continue
                for c in f["calls"]:
                    for t in c["targets"]:
                        edges.append({"source": fid, "target": t, "label": c.get("tool") or c["name"], "line": c["line"]})
                        nxt.add(t)
                for caller, line in self.ix.callers.get(fid, []):
                    edges.append({"source": caller, "target": fid, "label": "", "line": line})
                    nxt.add(caller)
            for n in nxt:
                nodes[n] = True
            frontier = nxt
            if len(nodes) > limit:
                break
        keep = set(list(nodes)[:limit])
        out_nodes = []
        for fid in keep:
            f = self.ix.functions.get(fid)
            if f:
                out_nodes.append({"id": fid, "label": f["name"], "file": f["file"], "line": f["start_line"],
                                  "kind": f["kind"], "focus": fid in fids})
        seen = set()
        out_edges = []
        for e in edges:
            k = (e["source"], e["target"])
            if e["source"] in keep and e["target"] in keep and k not in seen:
                seen.add(k)
                out_edges.append(e)
        return {"nodes": out_nodes, "edges": out_edges}
