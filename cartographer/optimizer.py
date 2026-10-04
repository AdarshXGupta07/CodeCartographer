"""Static, AST-based optimisation detectors for JavaScript.

Each finding points at an exact line and carries a concrete suggestion. These run at
index time (cheap) so the agent can attach them to any code path it surfaces.
"""

from __future__ import annotations

from tree_sitter import Node

LOOPS = {"for_statement", "for_in_statement", "while_statement", "do_statement"}
FUNCS = {"function_declaration", "function_expression", "function", "arrow_function",
         "method_definition", "generator_function", "generator_function_declaration"}
SYNC_FS = {"readFileSync", "writeFileSync", "appendFileSync", "existsSync", "readdirSync",
           "statSync", "mkdirSync", "execSync", "spawnSync"}
ITER_SEARCH = {"find", "filter", "includes", "indexOf", "some", "findIndex"}
INVARIANT_METHODS = {"toLowerCase", "toUpperCase", "trim", "normalize"}

RULES = {
    "await-in-loop": ("Sequential await inside a loop", "high",
                      "Each iteration waits for the previous one. Collect the promises and use "
                      "`await Promise.all(items.map(...))` (or a bounded pool) to run them concurrently."),
    "sync-io": ("Blocking synchronous I/O", "high",
                "Synchronous fs/child_process calls block the event loop (and every voice turn). "
                "Use the `fs.promises` API or batch/debounce the writes."),
    "regex-in-loop": ("RegExp compiled inside a loop", "medium",
                      "The pattern is rebuilt every iteration. Precompile the RegExp objects once at module load."),
    "json-deep-clone": ("JSON round-trip deep clone", "medium",
                        "`JSON.parse(JSON.stringify(x))` is slow and lossy. Use `structuredClone(x)` or avoid the copy."),
    "search-in-loop": ("Linear search inside a loop (O(n^2))", "medium",
                       "Build a Map/Set index once outside the loop and look items up in O(1)."),
    "sort-for-max": ("Full sort to pick one element", "low",
                     "`arr.sort(...)[0]` is O(n log n) and mutates the input. Use a single `reduce` pass to find the max/min."),
    "invariant-in-loop": ("Loop-invariant computation", "low",
                          "This value does not change between iterations. Hoist it above the loop."),
    "tight-polling": ("Tight polling interval", "medium",
                      "Polling with setInterval wakes the CPU constantly (battery drain on device). "
                      "Prefer push events/callbacks from the native layer or back off the interval."),
}


def _text(n: Node) -> str:
    return n.text.decode("utf8", "replace")


def _callee(call: Node) -> tuple[str, Node | None]:
    fn = call.child_by_field_name("function")
    if fn is None:
        return "", None
    if fn.type == "member_expression":
        return _text(fn.child_by_field_name("property")), fn.child_by_field_name("object")
    if fn.type == "identifier":
        return _text(fn), None
    return "", None


def _loop_declared_names(loop: Node) -> set[str]:
    names = set()
    for field in ("left", "initializer"):
        n = loop.child_by_field_name(field)
        if n is not None:
            stack = [n]
            while stack:
                x = stack.pop()
                if x.type in ("identifier", "shorthand_property_identifier_pattern"):
                    names.add(_text(x))
                stack.extend(x.children)
    return names


def _exits_early(loop: Node) -> bool:
    """Loops that return/break are retry or search loops: sequential by design."""
    body = loop.child_by_field_name("body")
    stack = [body] if body is not None else []
    while stack:
        n = stack.pop()
        if n.type in ("return_statement", "break_statement"):
            return True
        if n.type in FUNCS:
            continue
        stack.extend(n.children)
    return False


def analyze(root: Node) -> list[dict]:
    findings: list[dict] = []
    seen: set[tuple[str, int]] = set()

    def add(rule: str, node: Node, detail: str = ""):
        line = node.start_point[0] + 1
        if (rule, line) in seen:
            return
        seen.add((rule, line))
        title, severity, suggestion = RULES[rule]
        findings.append({
            "rule": rule, "title": title, "severity": severity, "line": line,
            "code": _text(node).split("\n")[0][:160], "suggestion": suggestion, "detail": detail,
        })

    def visit(node: Node, loops: list[Node], in_function: bool):
        t = node.type
        if t in FUNCS:
            # a nested function body is a new execution context: loops do not carry over
            for c in node.children:
                visit(c, [], True)
            return
        if t in LOOPS:
            # the loop header (iterable / condition) runs once per loop, the body per iteration
            body = node.child_by_field_name("body")
            for c in node.children:
                visit(c, loops + [node] if c == body else loops, in_function)
            return

        if t == "await_expression" and loops and not _exits_early(loops[-1]):
            add("await-in-loop", node)

        if t == "new_expression" and loops:
            ctor = node.child_by_field_name("constructor")
            if ctor is not None and _text(ctor) == "RegExp":
                add("regex-in-loop", node)

        if t == "call_expression":
            name, obj = _callee(node)
            if name in SYNC_FS and in_function:
                add("sync-io", node, name)
            if name == "parse" and obj is not None and _text(obj) == "JSON":
                args = node.child_by_field_name("arguments")
                if args is not None and "JSON.stringify" in _text(args):
                    add("json-deep-clone", node)
            if name in ITER_SEARCH and loops and obj is not None and obj.type in ("identifier", "member_expression"):
                # `x.includes(...)` on a string literal-ish name is fine; flag collections only
                if not _text(obj).endswith(("text", "line", "name", "str", "lower", "normalized")):
                    add("search-in-loop", node, _text(obj))
            if name in INVARIANT_METHODS and loops and obj is not None and obj.type == "identifier":
                declared = set()
                for lp in loops:
                    declared |= _loop_declared_names(lp)
                if _text(obj) not in declared:
                    add("invariant-in-loop", node, _text(obj))
            if name == "setInterval":
                args = node.child_by_field_name("arguments")
                if args is not None:
                    nums = [a for a in args.named_children if a.type == "number"]
                    if nums:
                        try:
                            if float(_text(nums[0])) < 1000:
                                add("tight-polling", node)
                        except ValueError:
                            pass

        if t == "subscript_expression":
            obj = node.child_by_field_name("object")
            idx = node.child_by_field_name("index")
            if obj is not None and idx is not None and _text(idx) in ("0", "-1") and obj.type == "call_expression":
                name, _ = _callee(obj)
                if name == "sort":
                    add("sort-for-max", node)

        for c in node.children:
            visit(c, loops, in_function)

    visit(root, [], False)
    return findings
