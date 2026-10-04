"""The CodeCartographer agent: plan -> search -> read -> refine -> verify.

Two planners share the same toolbox and verifier:
  * deterministic planner (always available, offline, reproducible - used for evaluation)
  * LLM planner (Gemini / Groq / OpenAI / Ollama) that starts from the deterministic
    evidence, may call more tools, and writes the final grounded answer.

`Agent.run()` is a generator of events so the UI can stream the agent's trace live.
"""

from __future__ import annotations

import json
import re
import time
from typing import Iterator

from . import config
from .llm import LLM
from .textutil import rewrite_query
from .tools import TOOL_SPECS, Toolbox, classify

SEVERITY = {"high": 0, "medium": 1, "low": 2}


class Agent:
    def __init__(self, index, llm: LLM | None = None):
        self.ix = index
        self.tb = Toolbox(index)
        self.llm = llm if llm is not None else LLM()

    # ================================================================= public
    def ask(self, question: str, use_llm: bool | None = None) -> dict:
        final = {}
        for ev in self.run(question, use_llm=use_llm):
            if ev["type"] == "final":
                final = ev
        return final

    def run(self, question: str, use_llm: bool | None = None) -> Iterator[dict]:
        t0 = time.perf_counter()
        use_llm = self.llm.available if use_llm is None else (use_llm and self.llm.available)
        self._use_llm = use_llm
        self._trace: list[dict] = []
        self._step = 0
        cls = classify(question)
        yield {"type": "plan", "query_type": cls["type"], "detail": cls,
               "planner": self.llm.describe() if use_llm else "deterministic",
               "text": self._plan_text(cls)}

        plan = getattr(self, f"_plan_{cls['type']}")
        locations, answer = yield from plan(question, cls)

        if use_llm:
            try:
                llm_locs, llm_answer = yield from self._llm_refine(question, cls, locations)
                if llm_answer:
                    answer = llm_answer
                if llm_locs:
                    locations = llm_locs
            except Exception as exc:  # network / quota problems must never break the answer
                yield {"type": "warning", "text": f"LLM step failed ({exc.__class__.__name__}: {str(exc)[:120]}); using deterministic answer."}

        verified = self._verify(locations)
        n_ok = sum(1 for l in verified if l["verified"])
        yield {"type": "verify", "checked": len(locations), "valid": n_ok,
               "text": f"Verified {n_ok}/{len(locations)} cited locations against the source"}
        verified = [l for l in verified if l["verified"]]

        fids = [l["func_id"] for l in verified if l.get("func_id")]
        opts = self._optimizations_for(verified)
        graph = self.tb.graph.neighborhood(list(dict.fromkeys(fids))[:12], hops=1, limit=40) if fids else {"nodes": [], "edges": []}
        yield {
            "type": "final",
            "question": question,
            "query_type": cls["type"],
            "answer": answer,
            "locations": verified,
            "optimizations": opts,
            "graph": graph,
            "trace": self._trace,
            "metrics": {
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "tool_calls": self._step,
                "llm": dict(self.llm.usage) if use_llm else None,
                "planner": self.llm.describe() if use_llm else "deterministic",
            },
        }

    # ================================================================ helpers
    def _tool(self, name: str, args: dict, thought: str):
        self._step += 1
        n = self._step
        t = time.perf_counter()
        text, data = self.tb.call(name, args)
        ms = round((time.perf_counter() - t) * 1000, 1)
        first = text.split("\n")
        self._trace.append({"n": n, "tool": name, "args": args, "thought": thought, "ms": ms})
        return n, text, data, [
            {"type": "step", "n": n, "tool": name, "args": args, "thought": thought},
            {"type": "observation", "n": n, "ms": ms, "summary": first[0][:200], "lines": len(first), "preview": "\n".join(first[:12])},
        ]

    def _func_loc(self, fid: str, why: str, score: float, highlight: list[int] | None = None, evidence: list[str] | None = None) -> dict:
        f = self.ix.functions.get(fid)
        if not f:
            return {}
        start, end = f["start_line"], f["end_line"]
        if f["kind"] == "module" or end - start > 45:
            hl = highlight or [start]
            start, end = max(1, min(hl) - 3), max(hl) + 3
        return {"file": f["file"], "start": start, "end": end, "symbol": f["name"], "func_id": fid,
                "why": why, "score": round(score, 4), "highlight": highlight or [], "evidence": evidence or []}

    @staticmethod
    def _plan_text(cls: dict) -> str:
        t = cls["type"]
        if t == "structural":
            if cls.get("negate"):
                return f"Structural query: find calls to '{cls['then']}' with no prior '{cls['first']}'. Resolve both names, walk ordered call sequences (branch-aware, inter-procedural)."
            return f"Structural query: '{cls['first']}' before '{cls['then']}'. Resolve both names, then walk ordered call sequences (branch-aware, inter-procedural)."
        if t == "callers":
            return f"Caller query: resolve '{cls['target']}' and list every call site (including tool invocations)."
        if t == "usage":
            return "Usage query: locate the symbol definition, then trace references and aliases (2 hops)."
        if t == "optimize":
            return "Optimisation query: locate the code path, then run static performance detectors on it."
        return "Semantic query: hybrid search (BM25 + code embeddings + symbols), read top hits, expand along the call graph."

    # ============================================================ planners
    def _plan_structural(self, q: str, cls: dict):
        n, text, data, evs = self._tool("call_order", {"first": cls["first"], "then": cls["then"], "negate": cls.get("negate", False)},
                                        "Run the inter-procedural call-order query over the call graph")
        for e in evs:
            yield e
        a, b = data["first"]["name"], data["then"]["name"]
        locs = []
        for h in data["matches"]:
            hl = [h["then_call"]["line"]] if cls.get("negate") else [h["first_call"]["line"], h["then_call"]["line"]]
            hl_local = [l for l in hl if self.ix.functions[h["func_id"]]["start_line"] <= l <= self.ix.functions[h["func_id"]]["end_line"]]
            if cls.get("negate"):
                why = f"calls {b} (L{h['then_call']['line']}) with no {a} before it"
            else:
                via = "" if h["direct"] else " via " + " -> ".join(x["function"] for x in h["then_call"]["via"])
                why = f"{a} @L{h['first_call']['line']} ({h['first_call']['file']}) before {b} @L{h['then_call']['line']} ({h['then_call']['file']}){via}"
            if not cls.get("negate") and not h["direct"]:
                # match goes through helpers: highlight the root-level call sites that lead to it
                hl_local = sorted({h["first_call"]["via"][0]["line"], h["then_call"]["via"][0]["line"]})
                evidence = []
            else:
                evidence = [a, b] if not cls.get("negate") else [b]
            locs.append(self._func_loc(h["func_id"], why, 1.0, hl_local, evidence=evidence))
        if cls.get("negate"):
            answer = (f"**{len(data['matches'])} function(s)** in {len(data['files'])} file(s) call `{b}` without calling `{a}` first "
                      f"(resolved from '{cls['then']}' / '{cls['first']}').")
        else:
            answer = (f"**{len(data['files'])} file(s)** call `{a}` before `{b}` "
                      f"(resolved from '{cls['first']}' / '{cls['then']}'): "
                      + ", ".join(f"`{f}`" for f in data["files"]) + ". "
                      "Calls in mutually exclusive branches are excluded; helper calls are followed across functions.")
        if not data["matches"]:
            answer = f"No function calls `{a}` before `{b}` on any execution path." if not cls.get("negate") else f"Every call to `{b}` is preceded by `{a}`."
        return locs, answer

    def _plan_callers(self, q: str, cls: dict):
        n, text, data, evs = self._tool("callers", {"name": cls["target"]}, "List every call site of the target")
        for e in evs:
            yield e
        locs = []
        by_func = {}
        for s in data["call_sites"]:
            by_func.setdefault(s["func_id"], []).append(s["line"])
        for fid, lines in by_func.items():
            locs.append(self._func_loc(fid, f"calls {data['target']['name']} at L{', L'.join(map(str, lines))}", 1.0, lines,
                                       evidence=[data["target"]["name"]]))
        answer = f"`{data['target']['name']}` is called from **{len(by_func)} function(s)** in {len(data['files'])} file(s)."
        return locs, answer

    def _plan_usage(self, q: str, cls: dict):
        phrase = re.sub(r"\b(where|is|are|the|used|referenced|usage|usages|of|who|uses|do|does|we|read|accessed|in|code|launched|opened)\b", " ", q, flags=re.I)
        n, text, data, evs = self._tool("find_symbol", {"name": phrase.strip()}, "Find the definition the user is talking about")
        for e in evs:
            yield e
        syms = data["symbols"]
        if not syms:
            return (yield from self._plan_semantic(q, cls))
        data_like = [x for x in syms if x["kind"] in ("property", "variable", "string", "tool")]
        if data_like and data_like[0]["score"] >= syms[0]["score"] * 0.75:
            syms = data_like
        top = syms[0]["score"]
        anchors, defs = [], []
        for s in syms:
            if s["score"] < top * 0.92 or len(anchors) >= 2:
                break
            name = s["name"]
            if s["kind"] == "string":
                if name in anchors:
                    continue  # a string equal to an anchor is a *use* of it (e.g. alias table value)
                # string literal: track the constant / key that holds it
                holder = [x for x in self.ix.symbols if x["file"] == s["file"] and x["line"] == s["line"] and x["kind"] in ("property", "variable")]
                if holder:
                    name = holder[0]["name"]
                elif not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                    continue
            if name not in anchors:
                anchors.append(name)
                defs.append(s)
        if not anchors:
            return (yield from self._plan_semantic(q, cls))

        refs = []
        for name in anchors:
            n, text, data, evs = self._tool("find_references", {"name": name}, f"Trace every reference to {name}")
            for e in evs:
                yield e
            refs.extend(r for r in data["references"] if not self._is_import_line(r))

        def_lines = {(d["file"], d["line"]) for d in defs}
        # refine: references inside module-level tables (aliases) -> follow the table one more hop
        hop2 = []
        for r in refs:
            if not r["func_id"].endswith("::<module>"):
                continue
            if (r["file"], r["line"]) in def_lines:
                continue
            holders = [x for x in self.ix.symbols if x["file"] == r["file"] and x["kind"] == "variable"
                       and x["line"] <= r["line"] <= x["end_line"]
                       and not any(df == r["file"] and x["line"] <= dl <= x["end_line"] for df, dl in def_lines)]
            for h in holders:
                if h["name"] in anchors or h["name"] in [x[0] for x in hop2]:
                    continue
                hop2.append((h["name"], r))
        for name, origin in hop2[:4]:
            n, text, data, evs = self._tool("find_references", {"name": name},
                                            f"{origin['file']}:{origin['line']} stores it in table {name}; follow that alias")
            for e in evs:
                yield e
            for ref in data["references"]:
                if self._is_import_line(ref):
                    continue
                holder_def = [x for x in self.ix.symbols if x["name"] == name and x["file"] == ref["file"] and x["line"] == ref["line"]]
                if holder_def:
                    continue  # the alias table's own declaration
                ref["alias"] = name
                refs.append(ref)

        locs, seen_funcs = [], {}
        for d in defs:
            locs.append({"file": d["file"], "start": d["line"], "end": d["end_line"] if d["end_line"] - d["line"] < 15 else d["line"],
                         "symbol": d["name"], "func_id": None, "why": f"definition of {d['name']}", "score": 1.0,
                         "highlight": [d["line"]], "evidence": [d["name"].split(".")[-1][:40]]})
        for r in refs:
            if (r["file"], r["line"]) in def_lines:
                continue
            is_module = r["func_id"].endswith("::<module>")
            if is_module and any(h[1] is r for h in hop2):
                why = f"stored in {[h[0] for h in hop2 if h[1] is r][0]} (alias table)"
            elif r.get("alias"):
                why = f"uses it through alias {r['alias']}"
            else:
                why = f"references {r['via']}"
            key = r["func_id"] if not is_module else f"{r['file']}:{r['line']}"
            if key in seen_funcs:
                seen_funcs[key]["highlight"].append(r["line"])
                continue
            if is_module:
                loc = {"file": r["file"], "start": max(1, r["line"] - 1), "end": r["line"] + 1, "symbol": "<module>",
                       "func_id": None, "why": why, "score": 0.8, "highlight": [r["line"]], "evidence": []}
            else:
                loc = self._func_loc(r["func_id"], why, 0.9, [r["line"]])
            seen_funcs[key] = loc
            locs.append(loc)
        direct = [l for l in locs[len(defs):] if "alias" not in l["why"]]
        answer = (f"`{anchors[0]}` is defined in `{defs[0]['file']}:{defs[0]['line']}` and used in **{len(locs) - len(defs)} place(s)**"
                  f" ({len(direct)} direct" + (f", {len(locs) - len(defs) - len(direct)} through alias tables {', '.join(sorted({h[0] for h in hop2}))}" if hop2 else "") + ").")
        return locs, answer

    def _plan_semantic(self, q: str, cls: dict):
        rewrites = [rewrite_query(q)]
        if self.llm.available and self._use_llm:
            try:
                rw = self.llm.chat_json(
                    "Rewrite a developer's question about a JavaScript codebase into 2 short search queries made of "
                    "likely identifiers / code words (camelCase function names, constants, API names). "
                    'Reply as JSON: {"queries": ["...", "..."]}',
                    [{"role": "user", "content": q}])
                rewrites += [x for x in rw.get("queries", [])][:2]
            except Exception:
                pass
        yield {"type": "rewrite", "text": "Query rewrites: " + " | ".join(rewrites)}
        n, text, data, evs = self._tool("search_code", {"query": q, "k": 10, "rewrites": rewrites},
                                        "Hybrid multi-query search: BM25 + code embeddings + symbol match, fused with RRF")
        for e in evs:
            yield e
        res = data["results"]
        if not res:
            return [], "No matching code found."
        # read the top hits (cheap: exact spans only)
        for r in res[:2]:
            n, text, _, evs = self._tool("read_code", {"file": r["file"], "start": r["start"], "end": min(r["end"], r["start"] + 30)},
                                         f"Read {r['symbol']} to confirm relevance")
            for e in evs:
                yield e
        locs = [self._func_loc(r["func_id"], f"hybrid rank {i+1} (" + ", ".join(f"{k}#{v}" for k, v in r["ranks"].items()) + ")", r["score"])
                if not r["func_id"].endswith("::<module>") else
                {"file": r["file"], "start": r["start"], "end": r["end"], "symbol": r["symbol"], "func_id": None,
                 "why": f"hybrid rank {i+1}", "score": r["score"], "highlight": [], "evidence": []}
                for i, r in enumerate(res[:8])]
        # expand along the call graph from the best function hit
        top_fn = next((r for r in res[:3] if not r["func_id"].endswith("::<module>")), None)
        if top_fn:
            fname = self.ix.functions[top_fn["func_id"]]["name"]
            n, text, data2, evs = self._tool("callees", {"name": fname}, f"Follow the code path out of {fname}")
            for e in evs:
                yield e
            have = {l.get("func_id") for l in locs}
            added = 0
            for c in self.ix.functions[top_fn["func_id"]]["calls"]:
                for t in c["targets"]:
                    if t not in have and added < 3 and self.ix.functions[t]["kind"] != "module":
                        loc = self._func_loc(t, f"called by {fname} at L{c['line']} (call-graph expansion)", 0.0)
                        loc["related"] = True
                        locs.append(loc)
                        have.add(t)
                        added += 1
        best = locs[0]
        answer = (f"Best match: `{best['symbol']}` in `{best['file']}:{best['start']}-{best['end']}`. "
                  f"{len([l for l in locs if not l.get('related')])} ranked results"
                  + (f" plus {len([l for l in locs if l.get('related')])} functions on its call path." if any(l.get("related") for l in locs) else "."))
        return locs, answer

    def _plan_optimize(self, q: str, cls: dict):
        stripped = re.sub(r"\b(optimi[sz]\w*|slow|performance|bottleneck|speed\s*up|inefficien\w*|latency|issues?|problems?|suggest\w*|find|any|what|are|the|in|of|is|why)\b", " ", q, flags=re.I).strip()
        files = []
        if len(stripped.split()) >= 1 and stripped:
            n, text, data, evs = self._tool("search_code", {"query": stripped, "k": 6}, "Locate the code path the user cares about")
            for e in evs:
                yield e
            top_funcs = [r["func_id"] for r in data["results"][:3]]
            files = list(dict.fromkeys(r["file"] for r in data["results"][:3]))
        findings = []
        if files:
            for f in files:
                n, text, d2, evs = self._tool("optimizations", {"file": f}, f"Run static performance detectors on {f}")
                for e in evs:
                    yield e
                findings.extend(d2["findings"])
            focused = [fd for fd in findings if fd.get("func_id") in top_funcs]
            findings = focused or findings
            files = list(dict.fromkeys(fd["file"] for fd in findings))
        if not findings:
            n, text, data, evs = self._tool("optimizations", {}, "Scan the whole index for performance findings")
            for e in evs:
                yield e
            findings = data["findings"]
        findings.sort(key=lambda f: SEVERITY.get(f["severity"], 3))
        locs = []
        for fd in findings[:10]:
            fid = fd.get("func_id")
            loc = self._func_loc(fid, f"[{fd['severity']}] {fd['title']}", 1.0, [fd["line"]]) if fid in self.ix.functions else {}
            if loc:
                locs.append(loc)
        answer = f"Found **{len(findings)} optimisation opportunities**" + (f" in {', '.join('`'+f+'`' for f in files)}" if files and findings else "") + "."
        return locs, answer

    # ============================================================== LLM refine
    def _llm_refine(self, question: str, cls: dict, locations: list[dict]):
        tool_doc = "\n".join(f"- {t['name']}({', '.join(f'{k}: {v}' for k, v in t['args'].items())}): {t['desc']}" for t in TOOL_SPECS)
        system = (
            "You are CodeCartographer, an expert code-intelligence agent for a large JavaScript voice-assistant codebase. "
            "The repository is far larger than your context, so you only see what tools return. "
            "You already have evidence gathered by a deterministic planner. You may call more tools to verify or refine it.\n\n"
            f"TOOLS:\n{tool_doc}\n\n"
            "Respond ONLY with JSON. Either a tool call:\n"
            '{"thought": "...", "tool": "<name>", "args": {...}}\n'
            "or the final answer:\n"
            '{"thought": "...", "final": {"answer": "<concise markdown answer, cite `file:line`>", '
            '"locations": [{"file": "...", "start": <int>, "end": <int>, "symbol": "...", "why": "..."}]}}\n'
            "Rules: cite only files/lines you have seen in tool output; order locations by relevance; "
            "keep the answer under 120 words; never invent code."
        )
        evidence = "\n".join(
            f"- {l['file']}:{l['start']}-{l['end']} {l.get('symbol','')} :: {l.get('why','')}" for l in locations[:15]
        )
        snippets = []
        for l in locations[:5]:
            sn = self.ix.snippet(l["file"], l["start"], min(l["end"], l["start"] + 25))
            snippets.append(f"### {l['file']}:{sn['start']}-{sn['end']}\n" + "\n".join(
                f"{sn['start'] + i}: {line}" for i, line in enumerate(sn["code"].split("\n"))))
        messages = [{"role": "user", "content":
                     f"QUESTION: {question}\nQUERY TYPE: {cls['type']} {json.dumps(cls)}\n\n"
                     f"PLANNER EVIDENCE:\n{evidence or '(none)'}\n\nTOP SNIPPETS:\n" + "\n\n".join(snippets)}]
        for _ in range(max(1, config.AGENT_MAX_STEPS - self._step)):
            yield {"type": "thinking", "text": f"LLM ({self.llm.describe()}) reasoning over evidence..."}
            out = self.llm.chat_json(system, messages)
            if "final" in out:
                fin = out["final"] or {}
                locs = []
                for l in fin.get("locations", [])[:12]:
                    try:
                        s, e = int(l["start"]), int(l.get("end", l["start"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    fn = self.ix.enclosing_function(l.get("file", ""), s) if l.get("file") in self.ix.files else None
                    locs.append({"file": l.get("file", ""), "start": s, "end": max(s, e), "symbol": l.get("symbol") or (fn["name"] if fn else ""),
                                 "func_id": fn["id"] if fn else None, "why": l.get("why", ""), "score": 1.0, "highlight": [], "evidence": []})
                yield {"type": "llm_answer", "thought": out.get("thought", "")}
                return locs, fin.get("answer")
            tool, args = out.get("tool"), out.get("args", {})
            if not tool:
                break
            n, text, data, evs = self._tool(tool, args, out.get("thought", ""))
            for e in evs:
                yield e
            messages.append({"role": "assistant", "content": json.dumps(out)})
            messages.append({"role": "user", "content": f"OBSERVATION from {tool}:\n{text[:3500]}"})
        return [], None

    def _is_import_line(self, ref: dict) -> bool:
        code = ref.get("code", "")
        return ("require(" in code or code.startswith(("import ", "export {", "module.exports", "exports."))
                or bool(re.match(r"^(const|let|var)\s*\{[^}]*\}\s*=\s*require", code)))

    # ================================================================ verify
    def _verify(self, locations: list[dict]) -> list[dict]:
        out = []
        for l in locations:
            if not l:
                continue
            ok, reason = True, "ok"
            if l["file"] not in self.ix.files:
                ok, reason = False, "file not in repository"
            else:
                lines = self.ix.file_lines(l["file"])
                if not (1 <= l["start"] <= len(lines)):
                    ok, reason = False, "line out of range"
                else:
                    l["end"] = min(max(l["end"], l["start"]), len(lines))
                    code = "\n".join(lines[l["start"] - 1:l["end"]])
                    ev = [e for e in l.get("evidence", []) if e]
                    if ev and not any(e.lower() in code.lower() for e in ev):
                        ok, reason = False, "evidence not found in cited span"
                    l["code"] = code
            l["verified"] = ok
            l["verify_reason"] = reason
            out.append(l)
        return out

    def _optimizations_for(self, locs: list[dict]) -> list[dict]:
        res, seen = [], set()
        for fd in self.ix.findings:
            for l in locs:
                if fd["file"] == l["file"] and l["start"] <= fd["line"] <= l["end"]:
                    k = (fd["file"], fd["line"], fd["rule"])
                    if k not in seen:
                        seen.add(k)
                        res.append(fd)
        res.sort(key=lambda f: SEVERITY.get(f["severity"], 3))
        return res[:12]
