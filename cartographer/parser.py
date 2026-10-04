"""JavaScript AST extraction with tree-sitter.

For every file we extract:
  * functions / methods / named arrows / tool handlers with exact line spans
  * every call site, in *evaluation order*, with a branch "guard" so that calls in
    mutually exclusive if/else or switch arms are never reported as "A before B"
  * tool invocations (`registry.invoke('toolName')`) and tool registrations
  * import / require bindings (for cross-file call resolution)
  * identifier references, string literals and symbol definitions
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Parser, Node

from . import config

JS_LANGUAGE = Language(tsjs.language())

FUNCTION_TYPES = {
    "function_declaration", "generator_function_declaration", "function_expression",
    "function", "arrow_function", "method_definition", "generator_function",
}
LOOP_TYPES = {"for_statement", "for_in_statement", "while_statement", "do_statement"}
BRANCH_TYPES = {"if_statement", "ternary_expression", "switch_statement"}


@dataclass
class CallSite:
    name: str                 # last identifier of the callee, e.g. "invoke"
    callee: str               # full callee text, e.g. "this.tools.invoke"
    line: int
    tool: str | None = None   # tool name if this is a tool invocation
    literal: str | None = None  # first string argument, if any
    guard: list = field(default_factory=list)  # [[branch_id, arm], ...]
    in_loop: bool = False
    is_new: bool = False
    targets: list = field(default_factory=list)  # resolved function ids (filled by indexer)


@dataclass
class FunctionInfo:
    id: str
    name: str            # qualified, e.g. "SettingsAgent.launch"
    short_name: str      # "launch"
    kind: str            # function | method | arrow | tool_handler | module
    file: str
    start_line: int
    end_line: int
    class_name: str | None = None
    params: str = ""
    doc: str = ""
    tool: str | None = None   # tool name if this function is a registered tool handler
    calls: list = field(default_factory=list)


@dataclass
class FileInfo:
    path: str
    sha1: str
    loc: int
    imports: dict = field(default_factory=dict)      # local name -> [module spec, imported name | "*"]
    functions: list = field(default_factory=list)    # function ids
    classes: dict = field(default_factory=dict)      # class name -> superclass name | None
    symbols: list = field(default_factory=list)      # [name, kind, line, end_line, container]
    refs: list = field(default_factory=list)         # [name, line, func_id]
    strings: list = field(default_factory=list)      # [value, line, func_id]
    findings: list = field(default_factory=list)     # optimisation findings (see optimizer.py)


def _text(node: Node | None) -> str:
    return node.text.decode("utf8", "replace") if node is not None else ""


def _line(node: Node) -> int:
    return node.start_point[0] + 1


def _end_line(node: Node) -> int:
    return node.end_point[0] + 1


def _string_value(node: Node) -> str | None:
    if node.type == "string":
        return _text(node)[1:-1]
    if node.type == "template_string" and not any(c.type == "template_substitution" for c in node.children):
        return _text(node)[1:-1]
    return None


def _callee_name(fn: Node) -> str:
    if fn.type == "member_expression":
        return _text(fn.child_by_field_name("property"))
    if fn.type == "identifier":
        return _text(fn)
    return ""


def _first_arg(call: Node) -> Node | None:
    args = call.child_by_field_name("arguments")
    if args is None:
        return None
    named = [c for c in args.named_children if c.type != "comment"]
    return named[0] if named else None


def _leading_comment(node: Node, src_lines: list[str]) -> str:
    """Return the JSDoc / line comments immediately above a node."""
    row = node.start_point[0] - 1
    out: list[str] = []
    while row >= 0:
        line = src_lines[row].strip()
        if line.startswith(("*", "/**", "/*", "//", "*/")):
            out.append(line.lstrip("/*").rstrip("*/").strip())
            row -= 1
            continue
        break
    return " ".join(reversed([l for l in out if l]))[:400]


class _Extractor:
    def __init__(self, rel_path: str, source: bytes):
        self.path = rel_path
        self.source = source
        self.lines = source.decode("utf8", "replace").splitlines()
        self.functions: dict[str, FunctionInfo] = {}
        self.file = FileInfo(
            path=rel_path,
            sha1=hashlib.sha1(source).hexdigest(),
            loc=len(self.lines),
        )
        module_id = f"{rel_path}::<module>"
        self.functions[module_id] = FunctionInfo(
            id=module_id, name="<module>", short_name="<module>", kind="module",
            file=rel_path, start_line=1, end_line=max(1, len(self.lines)),
        )
        self.module_id = module_id

    # ------------------------------------------------------------------ naming
    def _function_name(self, node: Node, class_name: str | None) -> tuple[str | None, str, str | None]:
        """Return (name, kind, tool) for a function-like node, or (None, ...) if anonymous."""
        t = node.type
        if t in ("function_declaration", "generator_function_declaration"):
            return _text(node.child_by_field_name("name")), "function", None
        if t == "method_definition":
            name = _text(node.child_by_field_name("name"))
            return (f"{class_name}.{name}" if class_name else name), "method", None
        # expressions: look at the parent to find a name
        parent = node.parent
        if parent is None:
            return None, "arrow", None
        own = node.child_by_field_name("name")
        if parent.type == "variable_declarator":
            return _text(parent.child_by_field_name("name")), "arrow", None
        if parent.type == "pair":
            key = _text(parent.child_by_field_name("key")).strip("'\"")
            return key, "arrow", None
        if parent.type in ("field_definition", "public_field_definition"):
            prop = parent.child_by_field_name("property") or parent.child_by_field_name("name")
            name = _text(prop)
            return (f"{class_name}.{name}" if class_name else name), "method", None
        if parent.type == "assignment_expression":
            left = _text(parent.child_by_field_name("left"))
            name = left.split(".")[-1]
            if left.startswith(("module.exports", "exports.")) or "prototype" in left:
                return name, "function", None
            return left.replace("this.", ""), "arrow", None
        if parent.type == "arguments":
            call = parent.parent
            if call is not None and call.type == "call_expression":
                cname = _callee_name(call.child_by_field_name("function"))
                first = _first_arg(call)
                lit = _string_value(first) if first is not None else None
                if cname in config.TOOL_REGISTER_NAMES and lit:
                    return f"tool:{lit}", "tool_handler", lit
        if own is not None:
            return _text(own), "function", None
        return None, "arrow", None

    # ---------------------------------------------------------------- traversal
    def run(self, tree) -> tuple[FileInfo, dict[str, FunctionInfo]]:
        self._visit(tree.root_node, self.module_id, None, [], False)
        self.file.functions = list(self.functions.keys())
        return self.file, self.functions

    def _visit(self, node: Node, func_id: str, class_name: str | None, guard: list, in_loop: bool):
        t = node.type

        # ---- classes
        if t in ("class_declaration", "class"):
            name_node = node.child_by_field_name("name")
            cname = _text(name_node) if name_node is not None else class_name
            sup = None
            for c in node.children:
                if c.type == "class_heritage":
                    sup = _text(c).replace("extends", "").strip()
            if cname:
                self.file.classes[cname] = sup
                self.file.symbols.append([cname, "class", _line(node), _end_line(node), None])
            for c in node.children:
                self._visit(c, func_id, cname, guard, in_loop)
            return

        # ---- functions
        if t in FUNCTION_TYPES:
            name, kind, tool = self._function_name(node, class_name)
            if name:
                fid = f"{self.path}::{name}@{_line(node)}"
                params = _text(node.child_by_field_name("parameters") or node.child_by_field_name("parameter"))
                doc_anchor = node if t in ("function_declaration", "method_definition") else (node.parent.parent if node.parent is not None and node.parent.type == "variable_declarator" and node.parent.parent is not None else node)
                self.functions[fid] = FunctionInfo(
                    id=fid, name=name, short_name=name.split(".")[-1] if not name.startswith("tool:") else name,
                    kind=kind, file=self.path, start_line=_line(node), end_line=_end_line(node),
                    class_name=class_name, params=params[:200], doc=_leading_comment(doc_anchor, self.lines),
                    tool=tool,
                )
                self.file.symbols.append([name, kind, _line(node), _end_line(node), class_name])
                for c in node.children:
                    self._visit(c, fid, class_name, [], False)
                return
            # anonymous callback: inline into the enclosing function
            for c in node.children:
                self._visit(c, func_id, class_name, guard, in_loop)
            return

        # ---- branches (guards make calls in different arms mutually exclusive)
        if t == "if_statement":
            bid = node.start_byte
            cond = node.child_by_field_name("condition")
            if cond is not None:
                self._visit(cond, func_id, class_name, guard, in_loop)
            cons = node.child_by_field_name("consequence")
            if cons is not None:
                self._visit(cons, func_id, class_name, guard + [[bid, 0]], in_loop)
            alt = node.child_by_field_name("alternative")
            if alt is not None:
                self._visit(alt, func_id, class_name, guard + [[bid, 1]], in_loop)
            return
        if t == "ternary_expression":
            bid = node.start_byte
            self._visit(node.child_by_field_name("condition"), func_id, class_name, guard, in_loop)
            self._visit(node.child_by_field_name("consequence"), func_id, class_name, guard + [[bid, 0]], in_loop)
            self._visit(node.child_by_field_name("alternative"), func_id, class_name, guard + [[bid, 1]], in_loop)
            return
        if t == "switch_statement":
            bid = node.start_byte
            body = node.child_by_field_name("body")
            val = node.child_by_field_name("value")
            if val is not None:
                self._visit(val, func_id, class_name, guard, in_loop)
            if body is not None:
                arm = 0
                for c in body.named_children:
                    self._visit(c, func_id, class_name, guard + [[bid, arm]], in_loop)
                    arm += 1
            return

        if t in LOOP_TYPES:
            for c in node.children:
                self._visit(c, func_id, class_name, guard, True)
            return

        # ---- imports
        if t == "import_statement":
            self._record_import(node)
        if t == "variable_declarator":
            self._record_declarator(node, func_id)

        # ---- object literal keys at module level are symbols (constants tables)
        if t == "pair" and func_id == self.module_id:
            key = node.child_by_field_name("key")
            if key is not None:
                self.file.symbols.append([_text(key).strip("'\""), "property", _line(node), _end_line(node), None])

        # ---- leaves: references & strings
        if t in ("identifier", "property_identifier", "shorthand_property_identifier", "type_identifier"):
            name = _text(node)
            if len(name) > 2:
                self.file.refs.append([name, _line(node), func_id])
        elif t == "member_expression" and node.parent is not None and node.parent.type != "member_expression":
            full = _text(node)
            if len(full) < 80 and "(" not in full and "\n" not in full:
                self.file.refs.append([full.replace("this.", ""), _line(node), func_id])
        elif t in ("string", "template_string"):
            val = _text(node)[1:-1]
            if 2 < len(val) < 300:
                self.file.strings.append([val, _line(node), func_id])

        # ---- calls: post-order so that argument calls come before the outer call
        for c in node.children:
            self._visit(c, func_id, class_name, guard, in_loop)

        if t in ("call_expression", "new_expression"):
            fn = node.child_by_field_name("function") if t == "call_expression" else node.child_by_field_name("constructor")
            if fn is None:
                return
            name = _callee_name(fn) if fn.type in ("member_expression", "identifier") else ""
            if not name:
                return
            first = _first_arg(node)
            lit = _string_value(first) if first is not None else None
            tool = lit if (name in config.TOOL_INVOKE_NAMES and lit and t == "call_expression") else None
            callee = _text(fn)
            if "\n" in callee or len(callee) > 120:
                callee = name
            if name == "require" and lit:
                return
            self.functions[func_id].calls.append(CallSite(
                name=name, callee=callee, line=_line(node), tool=tool, literal=lit,
                guard=[list(g) for g in guard], in_loop=in_loop, is_new=(t == "new_expression"),
            ))

    def _record_import(self, node: Node):
        src = node.child_by_field_name("source")
        spec = _string_value(src) if src is not None else None
        if not spec:
            return
        for clause in node.named_children:
            if clause.type != "import_clause":
                continue
            for c in clause.named_children:
                if c.type == "identifier":
                    self.file.imports[_text(c)] = [spec, "default"]
                elif c.type == "namespace_import":
                    ids = [x for x in c.named_children if x.type == "identifier"]
                    if ids:
                        self.file.imports[_text(ids[0])] = [spec, "*"]
                elif c.type == "named_imports":
                    for spec_node in c.named_children:
                        if spec_node.type != "import_specifier":
                            continue
                        orig = _text(spec_node.child_by_field_name("name"))
                        alias = spec_node.child_by_field_name("alias")
                        self.file.imports[_text(alias) if alias is not None else orig] = [spec, orig]

    def _record_declarator(self, node: Node, func_id: str):
        name_node = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if name_node is None:
            return
        # require() bindings
        if value is not None and value.type == "call_expression":
            fn = value.child_by_field_name("function")
            if fn is not None and _text(fn) == "require":
                first = _first_arg(value)
                spec = _string_value(first) if first is not None else None
                if spec:
                    if name_node.type == "identifier":
                        self.file.imports[_text(name_node)] = [spec, "*"]
                    elif name_node.type == "object_pattern":
                        for p in name_node.named_children:
                            if p.type == "shorthand_property_identifier_pattern":
                                self.file.imports[_text(p)] = [spec, _text(p)]
                            elif p.type == "pair_pattern":
                                k = _text(p.child_by_field_name("key"))
                                v = _text(p.child_by_field_name("value"))
                                self.file.imports[v] = [spec, k]
                    return
        if func_id == self.module_id and name_node.type == "identifier":
            if value is None or value.type not in ("arrow_function", "function_expression", "function"):
                self.file.symbols.append([_text(name_node), "variable", _line(node), _end_line(node), None])


_parser = Parser(JS_LANGUAGE)


def parse_file(rel_path: str, source: bytes):
    """Parse one JS file. Returns (FileInfo, {func_id: FunctionInfo}, tree)."""
    tree = _parser.parse(source)
    ex = _Extractor(rel_path, source)
    file_info, functions = ex.run(tree)
    return file_info, functions, tree


def to_dict(obj) -> dict:
    return asdict(obj)
