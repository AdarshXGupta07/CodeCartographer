"""Builds and loads the CodeCartographer index for a JavaScript repository.

Index = AST facts (functions, ordered call sites, imports, refs, strings, symbols)
      + resolved call graph (incl. tool invocation -> tool handler edges)
      + function-level chunks with BM25 tokens and dense code embeddings
      + optimisation findings

Re-indexing is incremental: unchanged files (same SHA-1) are not re-parsed and
unchanged chunks are not re-embedded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import posixpath
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np

from . import config
from .bm25 import BM25
from .embeddings import get_embedder
from .optimizer import analyze
from .parser import parse_file
from .textutil import code_tokens

log = logging.getLogger(__name__)

# very common method names that we never resolve by global name lookup (too ambiguous)
AMBIGUOUS = {
    "get", "set", "has", "call", "apply", "bind", "push", "pop", "map", "filter", "find", "forEach",
    "reduce", "then", "catch", "on", "emit", "run", "execute", "start", "stop", "init", "toString",
    "includes", "join", "split", "replace", "slice", "keys", "values", "entries", "log", "debug",
    "info", "warn", "error", "parse", "stringify", "test", "match", "sort", "save", "clear", "list",
    "size", "delete", "add", "respond", "speak", "invoke", "register", "request", "constructor",
}


def index_dir_for(repo: Path) -> Path:
    repo = repo.resolve()
    digest = hashlib.sha1(str(repo).lower().encode()).hexdigest()[:8]
    return config.INDEX_HOME / f"{repo.name}-{digest}"


def iter_js_files(repo: Path):
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in config.IGNORED_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix in config.JS_EXTENSIONS and not fn.endswith(".min.js"):
                try:
                    if p.stat().st_size <= config.MAX_FILE_BYTES:
                        yield p
                except OSError:
                    continue


class CodeIndex:
    def __init__(self, repo: str | Path):
        self.repo = Path(repo).resolve()
        self.dir = index_dir_for(self.repo)
        self.meta: dict = {}
        self.files: dict[str, dict] = {}
        self.functions: dict[str, dict] = {}
        self.chunks: list[dict] = []
        self.emb: np.ndarray | None = None
        self._line_cache: dict[str, list[str]] = {}

    # ================================================================== build
    def build(self, progress=None, force: bool = False) -> dict:
        t0 = time.perf_counter()
        prev = None if force else self._load_raw()
        prev_files = prev["files"] if prev else {}
        prev_funcs = prev["functions"] if prev else {}

        files: dict[str, dict] = {}
        functions: dict[str, dict] = {}
        n_parsed = n_reused = 0
        paths = sorted(iter_js_files(self.repo))
        for i, p in enumerate(paths):
            rel = p.relative_to(self.repo).as_posix()
            src = p.read_bytes()
            sha = hashlib.sha1(src).hexdigest()
            if rel in prev_files and prev_files[rel]["sha1"] == sha:
                files[rel] = prev_files[rel]
                for fid in prev_files[rel]["functions"]:
                    if fid in prev_funcs:
                        f = dict(prev_funcs[fid])
                        f["calls"] = [dict(c, targets=[]) for c in f["calls"]]
                        functions[fid] = f
                n_reused += 1
            else:
                try:
                    finfo, funcs, tree = parse_file(rel, src)
                except Exception as exc:  # pragma: no cover
                    log.warning("parse failed for %s: %s", rel, exc)
                    continue
                finfo.findings = analyze(tree.root_node)
                files[rel] = asdict(finfo)
                for fid, f in funcs.items():
                    functions[fid] = asdict(f)
                n_parsed += 1
            if progress and (i % 50 == 0 or i == len(paths) - 1):
                progress({"stage": "parse", "done": i + 1, "total": len(paths)})
        t_parse = time.perf_counter() - t0

        self.files, self.functions = files, functions
        self._attach_findings()
        self._build_lookup()
        self._resolve_calls()
        t_resolve = time.perf_counter() - t0 - t_parse

        # ---- chunks + embeddings (re-use cached vectors by content hash)
        self.chunks = self._make_chunks()
        old_vecs: dict[str, np.ndarray] = {}
        if prev and prev.get("emb") is not None and prev["meta"].get("embedder") == get_embedder().name:
            for key, vec in zip(prev["emb_keys"], prev["emb"]):
                old_vecs[key] = vec
        t1 = time.perf_counter()
        embedder = get_embedder()
        # sort by length so each batch pads to a similar size (big CPU win for transformers)
        todo = sorted((c for c in self.chunks if c["hash"] not in old_vecs), key=lambda c: len(c["embed_text"]))
        new_vecs: dict[str, np.ndarray] = {}
        batch = 64
        for s in range(0, len(todo), batch):
            part = todo[s:s + batch]
            vecs = embedder.embed([c["embed_text"] for c in part])
            for c, v in zip(part, vecs):
                new_vecs[c["hash"]] = v
            if progress:
                progress({"stage": "embed", "done": min(s + batch, len(todo)), "total": len(todo)})
        all_vecs = {**old_vecs, **new_vecs}
        self.emb = np.stack([all_vecs[c["hash"]] for c in self.chunks]) if self.chunks else np.zeros((0, 8), np.float32)
        t_embed = time.perf_counter() - t1

        loc = sum(f["loc"] for f in files.values())
        chars = sum(len(c["text"]) for c in self.chunks)
        self.meta = {
            "repo": str(self.repo),
            "repo_name": self.repo.name,
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "embedder": embedder.name,
            "stats": {
                "files": len(files),
                "files_parsed": n_parsed,
                "files_reused": n_reused,
                "loc": loc,
                "functions": sum(1 for f in functions.values() if f["kind"] != "module"),
                "call_sites": sum(len(f["calls"]) for f in functions.values()),
                "resolved_edges": sum(len(c["targets"]) for f in functions.values() for c in f["calls"]),
                "tools": len(self.tool_handlers),
                "chunks": len(self.chunks),
                "chunks_embedded": len(todo),
                "findings": sum(len(f["findings"]) for f in files.values()),
                "approx_repo_tokens": int(sum(p.stat().st_size for p in paths) / 3.5),
                "parse_s": round(t_parse, 3),
                "resolve_s": round(t_resolve, 3),
                "embed_s": round(t_embed, 3),
                "total_s": round(time.perf_counter() - t0, 3),
            },
        }
        self._save()
        self.meta["stats"]["index_bytes"] = sum(f.stat().st_size for f in self.dir.glob("*"))
        (self.dir / "meta.json").write_text(json.dumps(self.meta, indent=2))
        self._build_search()
        return self.meta

    # =================================================================== load
    def load(self) -> "CodeIndex":
        raw = self._load_raw()
        if raw is None:
            raise FileNotFoundError(f"No index for {self.repo}. Run `python -m cartographer index {self.repo}` first.")
        self.meta, self.files, self.functions = raw["meta"], raw["files"], raw["functions"]
        self.chunks, self.emb = raw["chunks"], raw["emb"]
        self._build_lookup()
        self._build_search()
        return self

    def exists(self) -> bool:
        return (self.dir / "index.json").exists()

    def _load_raw(self) -> dict | None:
        p = self.dir / "index.json"
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf8"))
        meta = json.loads((self.dir / "meta.json").read_text()) if (self.dir / "meta.json").exists() else data.get("meta", {})
        emb = np.load(self.dir / "embeddings.npy") if (self.dir / "embeddings.npy").exists() else None
        return {"meta": meta, "files": data["files"], "functions": data["functions"],
                "chunks": data["chunks"], "emb": emb, "emb_keys": [c["hash"] for c in data["chunks"]]}

    def _save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "index.json").write_text(json.dumps({
            "files": self.files, "functions": self.functions, "chunks": self.chunks,
        }), encoding="utf8")
        np.save(self.dir / "embeddings.npy", self.emb)
        (self.dir / "meta.json").write_text(json.dumps(self.meta, indent=2))

    # ============================================================== internals
    def _attach_findings(self):
        """Attribute each optimisation finding to its innermost enclosing named function."""
        by_file = defaultdict(list)
        for f in self.functions.values():
            if f["kind"] != "module":
                by_file[f["file"]].append(f)
        for rel, finfo in self.files.items():
            funcs = by_file.get(rel, [])
            for fd in finfo["findings"]:
                best = None
                for f in funcs:
                    if f["start_line"] <= fd["line"] <= f["end_line"]:
                        if best is None or (f["end_line"] - f["start_line"]) < (best["end_line"] - best["start_line"]):
                            best = f
                fd["func_id"] = best["id"] if best else f"{rel}::<module>"
                fd["function"] = best["name"] if best else "<module>"
                fd["file"] = rel

    def _build_lookup(self):
        self.by_short: dict[str, list[str]] = defaultdict(list)
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.tool_handlers: dict[str, list[str]] = defaultdict(list)
        self.file_funcs: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for fid, f in self.functions.items():
            if f["kind"] == "module":
                continue
            self.by_short[f["short_name"].lower()].append(fid)
            self.by_name[f["name"].lower()].append(fid)
            self.file_funcs[f["file"]][f["short_name"]].append(fid)
            self.file_funcs[f["file"]][f["name"]].append(fid)
            if f.get("tool"):
                self.tool_handlers[f["tool"]].append(fid)
        self.class_parent: dict[str, str | None] = {}
        for rel, finfo in self.files.items():
            for cname, sup in finfo["classes"].items():
                self.class_parent[cname] = sup

    def _resolve_module(self, from_file: str, spec: str) -> str | None:
        if not spec.startswith("."):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), spec))
        for cand in (base, base + ".js", base + ".mjs", base + ".cjs", base + ".jsx", base + "/index.js"):
            if cand in self.files:
                return cand
        return None

    def _resolve_call(self, f: dict, call: dict) -> list[str]:
        if call.get("tool"):
            return list(self.tool_handlers.get(call["tool"], []))
        name, callee = call["name"], call["callee"]
        rel = f["file"]
        local = self.file_funcs[rel]
        imports = self.files[rel]["imports"]
        # this.method() -> method on the same class (or its parents)
        if callee.startswith("this.") and callee.count(".") == 1:
            cls = f.get("class_name")
            seen = set()
            while cls and cls not in seen:
                seen.add(cls)
                for frel, funcs in self.file_funcs.items():
                    if f"{cls}.{name}" in funcs:
                        return funcs[f"{cls}.{name}"][:1]
                cls = self.class_parent.get(cls)
            return []
        # bare identifier call: local function or imported binding
        if "." not in callee:
            if name in local and not call.get("is_new"):
                return local[name][:1]
            if name in imports:
                target = self._resolve_module(rel, imports[name][0])
                if target:
                    orig = imports[name][1]
                    tf = self.file_funcs[target]
                    for key in (orig, name):
                        if key in tf:
                            return tf[key][:1]
            return []
        # ns.member() where ns is an imported module namespace
        obj = callee.rsplit(".", 1)[0]
        if obj in imports:
            target = self._resolve_module(rel, imports[obj][0])
            if target and name in self.file_funcs[target]:
                return self.file_funcs[target][name][:1]
        # unique global name (skip generic names)
        if name not in AMBIGUOUS:
            cands = self.by_short.get(name.lower(), [])
            if len(cands) == 1:
                return cands
        return []

    def _resolve_calls(self):
        self.callers: dict[str, list] = defaultdict(list)
        for fid, f in self.functions.items():
            for call in f["calls"]:
                call["targets"] = self._resolve_call(f, call)
                for t in call["targets"]:
                    self.callers[t].append((fid, call["line"]))

    def _make_chunks(self) -> list[dict]:
        chunks: list[dict] = []
        by_file = defaultdict(list)
        for f in self.functions.values():
            if f["kind"] != "module":
                by_file[f["file"]].append(f)
        for rel in sorted(self.files):
            lines = self.file_lines(rel)
            funcs = sorted(by_file.get(rel, []), key=lambda f: (f["start_line"], -f["end_line"]))
            covered = set()
            for f in funcs:
                s, e = f["start_line"], f["end_line"]
                covered.update(range(s, e + 1))
                windows = [(s, e)]
                if e - s + 1 > config.CHUNK_MAX_LINES:
                    windows = []
                    w = s
                    while w <= e:
                        windows.append((w, min(e, w + config.CHUNK_WINDOW - 1)))
                        w += config.CHUNK_WINDOW - config.CHUNK_OVERLAP
                for ws, we in windows:
                    chunks.append(self._chunk(rel, lines, ws, we, f["name"], f["kind"], f["id"], f.get("doc", "")))
            # module level code not inside any function (constants, config tables, class headers)
            block: list[int] = []

            def flush():
                body = [n for n in block if lines[n - 1].strip() and not lines[n - 1].strip().startswith(("'use strict'", '"use strict"'))]
                meaningful = [n for n in body if "require(" not in lines[n - 1] and lines[n - 1].strip() not in ("}", "};", "});")]
                if len(meaningful) >= 3:
                    chunks.append(self._chunk(rel, lines, block[0], block[-1], "<module>", "module", f"{rel}::<module>", ""))

            for n in range(1, len(lines) + 1):
                if n in covered:
                    if block:
                        flush()
                        block = []
                    continue
                block.append(n)
                if len(block) >= config.CHUNK_WINDOW:
                    flush()
                    block = []
            if block:
                flush()
        for i, c in enumerate(chunks):
            c["idx"] = i
        return chunks

    def _chunk(self, rel, lines, s, e, symbol, kind, fid, doc) -> dict:
        code = "\n".join(lines[s - 1:e])
        header = f"// file: {rel}\n// symbol: {symbol}" + (f"\n// {doc}" if doc else "")
        text_for_embed = f"{header}\n{code}"[:6000]
        return {
            "file": rel, "start": s, "end": e, "symbol": symbol, "kind": kind, "func_id": fid,
            "text": code, "embed_text": text_for_embed,
            "tokens": code_tokens(f"{rel} {symbol} {doc} {code}"),
            "hash": hashlib.sha1(text_for_embed.encode()).hexdigest(),
        }

    def _build_search(self):
        self.bm25 = BM25([c["tokens"] for c in self.chunks])
        if not hasattr(self, "callers"):
            self.callers = defaultdict(list)
            for fid, f in self.functions.items():
                for call in f["calls"]:
                    for t in call["targets"]:
                        self.callers[t].append((fid, call["line"]))
        # reference / string / symbol indexes
        self.refs: dict[str, list] = defaultdict(list)
        self.refs_lower: dict[str, set] = defaultdict(set)
        for rel, finfo in self.files.items():
            for name, line, fid in finfo["refs"]:
                self.refs[name].append((rel, line, fid))
                self.refs_lower[name.lower()].add(name)
        self.symbols: list[dict] = []
        for rel, finfo in self.files.items():
            for name, kind, line, end, container in finfo["symbols"]:
                self.symbols.append({"name": name, "kind": kind, "file": rel, "line": line, "end_line": end, "container": container})
            for val, line, fid in finfo["strings"]:
                self.symbols.append({"name": val, "kind": "string", "file": rel, "line": line, "end_line": line, "container": fid})
        for tool, fids in self.tool_handlers.items():
            f = self.functions[fids[0]]
            self.symbols.append({"name": tool, "kind": "tool", "file": f["file"], "line": f["start_line"], "end_line": f["end_line"], "container": None})
        self.symbol_tokens = [set(code_tokens(s["name"])) for s in self.symbols]
        self.tool_callsites: dict[str, list] = defaultdict(list)
        for fid, f in self.functions.items():
            for call in f["calls"]:
                if call.get("tool"):
                    self.tool_callsites[call["tool"]].append((fid, call))
        self.findings = [fd for finfo in self.files.values() for fd in finfo["findings"]]

    # ================================================================ helpers
    def file_lines(self, rel: str) -> list[str]:
        if rel not in self._line_cache:
            p = self.repo / rel
            try:
                self._line_cache[rel] = p.read_text(encoding="utf8", errors="replace").splitlines()
            except OSError:
                self._line_cache[rel] = []
        return self._line_cache[rel]

    def snippet(self, rel: str, start: int, end: int, pad: int = 0) -> dict:
        lines = self.file_lines(rel)
        s = max(1, start - pad)
        e = min(len(lines), end + pad)
        return {"file": rel, "start": s, "end": e, "code": "\n".join(lines[s - 1:e])}

    def enclosing_function(self, rel: str, line: int) -> dict | None:
        best = None
        for f in self.functions.values():
            if f["file"] == rel and f["kind"] != "module" and f["start_line"] <= line <= f["end_line"]:
                if best is None or (f["end_line"] - f["start_line"]) < (best["end_line"] - best["start_line"]):
                    best = f
        return best
