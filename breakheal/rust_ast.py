"""Tree-sitter AST parser, API Contract Oracle, and Threat Surface Scorer for Rust."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

try:
    from tree_sitter import Language, Parser, Node
    import tree_sitter_rust

    _RUST_LANG = Language(tree_sitter_rust.language())
    _HAS_TREE_SITTER = True
except ImportError:
    _HAS_TREE_SITTER = False


@dataclass
class RustParam:
    name: str
    type_name: str


@dataclass
class RustFunctionInfo:
    name: str
    return_type: str
    parameters: list[RustParam]
    is_pub: bool
    is_async: bool
    is_method: bool  # True if takes &self, &mut self, or self
    start_line: int
    end_line: int
    source_code: str
    enclosing_type: Optional[str] = None
    threat_score: int = 0
    threat_reasons: list[str] = field(default_factory=list)


@dataclass
class RustFieldInfo:
    name: str
    type_name: str
    is_pub: bool


@dataclass
class RustStructInfo:
    name: str
    is_pub: bool
    fields: list[RustFieldInfo] = field(default_factory=list)
    methods: list[RustFunctionInfo] = field(default_factory=list)


@dataclass
class RustParsedFile:
    modules: list[str]
    uses: list[str]
    structs: list[RustStructInfo]
    all_functions: list[RustFunctionInfo]
    source_code: str


def _get_node_text(node: Optional[Node], source_bytes: bytes) -> str:
    if not node:
        return ""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _score_rust_threat(node: Node, source_bytes: bytes) -> tuple[int, list[str]]:
    """Score threat surface for Rust functions and methods."""
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

    # 1. unwrap() / expect() (Panic on None / Err)
    if ".unwrap()" in code or ".expect(" in code:
        score += 35
        reasons.append("Calls unwrap() or expect() (panic on None or Err)")

    # 2. Arithmetic division or modulo (Panic on integer zero division)
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
            reasons.append("Arithmetic division or modulo (integer division-by-zero panic risk)")

    # 3. Indexing into Vec or slice (Panic on out-of-bounds)
    if has_node_type(node, "index_expression") or re.search(r"\[\s*[^\]\s]+\s*\]", code):
        score += 25
        reasons.append("Slice/Vec index expression (panic: index out of bounds risk)")

    # 4. Explicit panic macros
    if "panic!" in code or "todo!" in code or "unimplemented!" in code or "unreachable!" in code:
        score += 30
        reasons.append("Explicit panic! / todo! / unimplemented! macro")

    # 5. Type casts (as u32, as usize)
    if re.search(r"\bas\s+(?:u8|u16|u32|u64|u128|usize|i8|i16|i32|i64|i128|isize|f32|f64)\b", code):
        score += 15
        reasons.append("Primitive type casting (truncation / overflow risk)")

    return score, reasons


def parse_rust_ast(source: str) -> RustParsedFile:
    """Parse Rust source code into AST metadata using Tree-sitter."""
    if not _HAS_TREE_SITTER:
        raise RuntimeError("tree-sitter or tree-sitter-rust is not installed")

    source_bytes = source.encode("utf-8")
    parser = Parser(_RUST_LANG)
    tree = parser.parse(source_bytes)

    modules: list[str] = []
    uses: list[str] = []
    structs: dict[str, RustStructInfo] = {}
    all_functions: list[RustFunctionInfo] = []

    def parse_params(params_node: Optional[Node]) -> tuple[list[RustParam], bool]:
        params: list[RustParam] = []
        is_method = False
        if not params_node:
            return params, is_method

        for child in params_node.children:
            if child.type == "self_parameter":
                is_method = True
                params.append(RustParam(name="self", type_name=_get_node_text(child, source_bytes)))
            elif child.type == "parameter":
                pat = child.child_by_field_name("pattern")
                typ = child.child_by_field_name("type")
                p_name = _get_node_text(pat, source_bytes) if pat else ""
                t_str = _get_node_text(typ, source_bytes) if typ else "()"
                params.append(RustParam(name=p_name, type_name=t_str))
        return params, is_method

    for node in tree.root_node.children:
        if node.type == "use_declaration":
            uses.append(_get_node_text(node, source_bytes).strip())

        elif node.type == "struct_item":
            vis_n = node.child_by_field_name("visibility") or [c for c in node.children if c.type == "visibility_modifier"]
            is_pub = bool(vis_n)
            name_n = node.child_by_field_name("name")
            s_name = _get_node_text(name_n, source_bytes) if name_n else "AnonymousStruct"
            fields: list[RustFieldInfo] = []

            field_list = node.child_by_field_name("body") or [c for c in node.children if c.type == "field_declaration_list"]
            if field_list:
                fl = field_list[0] if isinstance(field_list, list) else field_list
                for f in fl.children:
                    if f.type == "field_declaration":
                        f_vis = [c for c in f.children if c.type == "visibility_modifier"]
                        f_name_n = f.child_by_field_name("name")
                        f_type_n = f.child_by_field_name("type")
                        f_name = _get_node_text(f_name_n, source_bytes) if f_name_n else ""
                        f_type = _get_node_text(f_type_n, source_bytes) if f_type_n else "()"
                        fields.append(RustFieldInfo(name=f_name, type_name=f_type, is_pub=bool(f_vis)))

            structs[s_name] = RustStructInfo(name=s_name, is_pub=is_pub, fields=fields)

        elif node.type == "impl_item":
            type_n = node.child_by_field_name("type")
            t_name = _get_node_text(type_n, source_bytes) if type_n else ""
            body_list = node.child_by_field_name("body") or [c for c in node.children if c.type == "declaration_list"]
            if body_list:
                bl = body_list[0] if isinstance(body_list, list) else body_list
                for m in bl.children:
                    if m.type == "function_item":
                        vis_m = [c for c in m.children if c.type == "visibility_modifier"]
                        name_m = m.child_by_field_name("name")
                        fn_name = _get_node_text(name_m, source_bytes) if name_m else "fn"
                        params_n = m.child_by_field_name("parameters")
                        params, is_method = parse_params(params_n)
                        ret_n = m.child_by_field_name("return_type")
                        ret_str = _get_node_text(ret_n, source_bytes).replace("->", "").strip() if ret_n else "()"
                        score, reasons = _score_rust_threat(m, source_bytes)

                        f_info = RustFunctionInfo(
                            name=fn_name,
                            return_type=ret_str,
                            parameters=params,
                            is_pub=bool(vis_m),
                            is_async=any(c.type == "async" for c in m.children),
                            is_method=is_method,
                            start_line=m.start_point[0] + 1,
                            end_line=m.end_point[0] + 1,
                            source_code=_get_node_text(m, source_bytes),
                            enclosing_type=t_name,
                            threat_score=score,
                            threat_reasons=reasons,
                        )
                        all_functions.append(f_info)
                        if t_name in structs:
                            structs[t_name].methods.append(f_info)

        elif node.type == "function_item":
            vis_m = [c for c in node.children if c.type == "visibility_modifier"]
            name_m = node.child_by_field_name("name")
            fn_name = _get_node_text(name_m, source_bytes) if name_m else "fn"
            params_n = node.child_by_field_name("parameters")
            params, is_method = parse_params(params_n)
            ret_n = node.child_by_field_name("return_type")
            ret_str = _get_node_text(ret_n, source_bytes).replace("->", "").strip() if ret_n else "()"
            score, reasons = _score_rust_threat(node, source_bytes)

            f_info = RustFunctionInfo(
                name=fn_name,
                return_type=ret_str,
                parameters=params,
                is_pub=bool(vis_m),
                is_async=any(c.type == "async" for c in node.children),
                is_method=is_method,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                source_code=_get_node_text(node, source_bytes),
                threat_score=score,
                threat_reasons=reasons,
            )
            all_functions.append(f_info)

    return RustParsedFile(
        modules=modules,
        uses=uses,
        structs=list(structs.values()),
        all_functions=all_functions,
        source_code=source,
    )


def generate_rust_api_contract(parsed: RustParsedFile, target_name: Optional[str] = None) -> str:
    """Generate a strict, anti-hallucination API contract markdown block for Rust code."""
    lines = ["### STRICT RUST API CONTRACT (DO NOT HALLUCINATE OR ACCESS PRIVATE MEMBERS):"]

    # Structs & fields
    for s in parsed.structs:
        pub_tag = "pub struct" if s.is_pub else "struct (private)"
        lines.append(f"- Struct: `{s.name}` ({pub_tag})")
        pub_fields = [f.name for f in s.fields if f.is_pub]
        priv_fields = [f.name for f in s.fields if not f.is_pub]
        if pub_fields:
            lines.append(f"  * Public Fields: {', '.join(pub_fields)}")
        if priv_fields:
            lines.append(
                f"  * FORBIDDEN Private Fields (Cannot construct via struct literal! Must call ::new): {', '.join(priv_fields)}"
            )

        # Methods
        pub_methods = [m for m in s.methods if m.is_pub]
        if pub_methods:
            lines.append("  * Public Callable Methods:")
            for m in pub_methods:
                p_str = ", ".join(f"{p.name}: {p.type_name}" for p in m.parameters)
                lines.append(f"    - `pub fn {m.name}({p_str}) -> {m.return_type}`")

    # Standalone Public Functions
    standalone_pub = [f for f in parsed.all_functions if f.enclosing_type is None and f.is_pub]
    if standalone_pub:
        lines.append("- Public Callable Functions:")
        for f in standalone_pub:
            p_str = ", ".join(f"{p.name}: {p.type_name}" for f in [f] for p in f.parameters)
            lines.append(f"  * `pub fn {f.name}({p_str}) -> {f.return_type}`")

    return "\n".join(lines)
