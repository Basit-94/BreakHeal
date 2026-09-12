"""Tree-sitter AST parser, API Contract Oracle, and Threat Surface Scorer for Go."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

try:
    from tree_sitter import Language, Parser, Node
    import tree_sitter_go

    _GO_LANG = Language(tree_sitter_go.language())
    _HAS_TREE_SITTER = True
except ImportError:
    _HAS_TREE_SITTER = False


@dataclass
class GoParam:
    name: str
    type_name: str


@dataclass
class GoFunctionInfo:
    name: str
    return_type: str
    parameters: list[GoParam]
    is_exported: bool
    start_line: int
    end_line: int
    source_code: str
    receiver_type: Optional[str] = None
    receiver_name: Optional[str] = None
    threat_score: int = 0
    threat_reasons: list[str] = field(default_factory=list)


@dataclass
class GoFieldInfo:
    name: str
    type_name: str
    is_exported: bool


@dataclass
class GoStructInfo:
    name: str
    is_exported: bool
    fields: list[GoFieldInfo] = field(default_factory=list)
    methods: list[GoFunctionInfo] = field(default_factory=list)


@dataclass
class GoParsedFile:
    package_name: str
    imports: list[str]
    structs: list[GoStructInfo]
    all_functions: list[GoFunctionInfo]
    source_code: str


def _get_node_text(node: Optional[Node], source_bytes: bytes) -> str:
    if not node:
        return ""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _score_go_threat(node: Node, source_bytes: bytes) -> tuple[int, list[str]]:
    """Score threat surface for Go functions and methods."""
    score = 0
    reasons: list[str] = []
    code = _get_node_text(node, source_bytes)

    def has_node_type(n: Node, target_type: str) -> bool:
        if n.type == target_type:
            return True
        for ch in n.children:
            if has_node_type(ch, target_type):
                return True
        return False

    # 1. Division or modulo (Zero-division panic)
    if "/" in code or "%" in code:
        def has_div_op(n: Node) -> bool:
            if n.type == "binary_expression":
                for ch in n.children:
                    if ch.type in {"/", "%"}:
                        return True
            for ch in n.children:
                if has_div_op(ch):
                    return True
            return False

        if has_div_op(node) or re.search(r"[a-zA-Z0-9_)]\s*[/]\s*[a-zA-Z0-9_(]", code):
            score += 35
            reasons.append("Arithmetic division or modulo (runtime division-by-zero panic risk)")

    # 2. Slice or array index access (runtime error: index out of range)
    if has_node_type(node, "index_expression") or re.search(r"\[\s*[^\]\s]+\s*\]", code):
        score += 25
        reasons.append("Slice/Array index access (panic: index out of range risk)")

    # 3. Explicit panics
    if "panic(" in code:
        score += 30
        reasons.append("Explicit panic() invocation")

    # 4. Pointer dereferences (nil pointer dereference risk)
    if has_node_type(node, "pointer_type") or "*" in code:
        score += 15
        reasons.append("Pointer operations (nil pointer dereference risk)")

    # 5. Type assertions (interface conversion panic risk)
    if ".(" in code:
        score += 20
        reasons.append("Type assertion (panic: interface conversion risk)")

    return score, reasons


def parse_go_ast(source: str) -> GoParsedFile:
    """Parse Go source code into AST metadata using Tree-sitter."""
    if not _HAS_TREE_SITTER:
        raise RuntimeError("tree-sitter or tree-sitter-go is not installed")

    source_bytes = source.encode("utf-8")
    parser = Parser(_GO_LANG)
    tree = parser.parse(source_bytes)

    package_name = "main"
    imports: list[str] = []
    structs: dict[str, GoStructInfo] = {}
    all_functions: list[GoFunctionInfo] = []

    def parse_params(params_node: Optional[Node]) -> list[GoParam]:
        params: list[GoParam] = []
        if not params_node:
            return params
        for child in params_node.children:
            if child.type == "parameter_declaration":
                names = [c for c in child.children if c.type == "identifier"]
                type_n = child.child_by_field_name("type") or (child.children[-1] if child.children else None)
                t_str = _get_node_text(type_n, source_bytes) if type_n else "interface{}"
                if names:
                    for n in names:
                        params.append(GoParam(name=_get_node_text(n, source_bytes), type_name=t_str))
                else:
                    params.append(GoParam(name="", type_name=t_str))
        return params

    for node in tree.root_node.children:
        if node.type == "package_clause":
            pkg_id = node.child_by_field_name("name") or [c for c in node.children if c.type == "package_identifier"]
            if pkg_id:
                package_name = _get_node_text(pkg_id[0] if isinstance(pkg_id, list) else pkg_id, source_bytes)

        elif node.type == "import_declaration":
            imports.append(_get_node_text(node, source_bytes).strip())

        elif node.type == "type_declaration":
            for child in node.children:
                if child.type == "type_spec":
                    name_n = child.child_by_field_name("name")
                    s_name = _get_node_text(name_n, source_bytes) if name_n else "Anonymous"
                    type_body = child.child_by_field_name("type") or (child.children[1] if len(child.children) > 1 else None)
                    fields: list[GoFieldInfo] = []
                    if type_body and type_body.type == "struct_type":
                        field_lists = [c for c in type_body.children if c.type == "field_declaration_list"]
                        if field_lists:
                            for f in field_lists[0].children:
                                if f.type == "field_declaration":
                                    ids = [c for c in f.children if c.type == "field_identifier"]
                                    f_name = _get_node_text(ids[0], source_bytes) if ids else ""
                                    type_nodes = [c for c in f.children if c.type not in {"field_identifier", "tag"}]
                                    f_type = _get_node_text(type_nodes[0], source_bytes) if type_nodes else "interface{}"
                                    is_exp = f_name[:1].isupper() if f_name else False
                                    if f_name:
                                        fields.append(GoFieldInfo(name=f_name, type_name=f_type, is_exported=is_exp))
                    is_struct_exp = s_name[:1].isupper()
                    structs[s_name] = GoStructInfo(name=s_name, is_exported=is_struct_exp, fields=fields)

        elif node.type == "function_declaration":
            name_n = node.child_by_field_name("name")
            f_name = _get_node_text(name_n, source_bytes) if name_n else "func"
            params = parse_params(node.child_by_field_name("parameters"))
            res_n = node.child_by_field_name("result")
            ret_str = _get_node_text(res_n, source_bytes) if res_n else ""
            score, reasons = _score_go_threat(node, source_bytes)
            is_exp = f_name[:1].isupper()

            f_info = GoFunctionInfo(
                name=f_name,
                return_type=ret_str,
                parameters=params,
                is_exported=is_exp,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                source_code=_get_node_text(node, source_bytes),
                threat_score=score,
                threat_reasons=reasons,
            )
            all_functions.append(f_info)

        elif node.type == "method_declaration":
            name_n = node.child_by_field_name("name")
            m_name = _get_node_text(name_n, source_bytes) if name_n else "method"
            recv_n = node.child_by_field_name("receiver")
            recv_params = parse_params(recv_n)
            recv_type = recv_params[0].type_name if recv_params else None
            recv_name = recv_params[0].name if recv_params else None
            clean_recv_type = recv_type.replace("*", "").strip() if recv_type else None

            params = parse_params(node.child_by_field_name("parameters"))
            res_n = node.child_by_field_name("result")
            ret_str = _get_node_text(res_n, source_bytes) if res_n else ""
            score, reasons = _score_go_threat(node, source_bytes)
            is_exp = m_name[:1].isupper()

            f_info = GoFunctionInfo(
                name=m_name,
                return_type=ret_str,
                parameters=params,
                is_exported=is_exp,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                source_code=_get_node_text(node, source_bytes),
                receiver_type=recv_type,
                receiver_name=recv_name,
                threat_score=score,
                threat_reasons=reasons,
            )
            all_functions.append(f_info)
            if clean_recv_type and clean_recv_type in structs:
                structs[clean_recv_type].methods.append(f_info)

    return GoParsedFile(
        package_name=package_name,
        imports=imports,
        structs=list(structs.values()),
        all_functions=all_functions,
        source_code=source,
    )


def generate_go_api_contract(parsed: GoParsedFile, target_name: Optional[str] = None) -> str:
    """Generate a strict, anti-hallucination API contract markdown block for Go code."""
    lines = [
        "### STRICT GO API CONTRACT (DO NOT HALLUCINATE OR ACCESS UNEXPORTED MEMBERS):",
        f"- Package: `{parsed.package_name}`",
    ]

    # Structs & fields
    for s in parsed.structs:
        exp_tag = "exported" if s.is_exported else "unexported"
        lines.append(f"- Struct: `{s.name}` ({exp_tag})")
        exp_fields = [f.name for f in s.fields if f.is_exported]
        unexp_fields = [f.name for f in s.fields if not f.is_exported]
        if exp_fields:
            lines.append(f"  * Exported Fields: {', '.join(exp_fields)}")
        if unexp_fields:
            lines.append(
                f"  * FORBIDDEN Unexported Fields (DO NOT ACCESS DIRECTLY OUTSIDE PACKAGE): {', '.join(unexp_fields)}"
            )

        # Methods
        exp_methods = [m for m in s.methods if m.is_exported]
        if exp_methods:
            lines.append("  * Callable Exported Methods:")
            for m in exp_methods:
                p_str = ", ".join(f"{p.name} {p.type_name}" for p in m.parameters)
                ret_s = f" {m.return_type}" if m.return_type else ""
                lines.append(f"    - `func ({m.receiver_name} {m.receiver_type}) {m.name}({p_str}){ret_s}`")

    # Standalone Exported Functions & Constructors
    standalone_exp = [f for f in parsed.all_functions if f.receiver_type is None and f.is_exported]
    if standalone_exp:
        lines.append("- Callable Exported Functions / Constructors:")
        for f in standalone_exp:
            p_str = ", ".join(f"{p.name} {p.type_name}" for p in f.parameters)
            ret_s = f" {f.return_type}" if f.return_type else ""
            lines.append(f"  * `func {f.name}({p_str}){ret_s}`")

    return "\n".join(lines)
