"""Tree-sitter AST parser, API Contract Oracle, and Threat Surface Scorer for TypeScript/JavaScript."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from tree_sitter import Language, Parser, Node
    import tree_sitter_typescript

    _TS_LANG = Language(tree_sitter_typescript.language_typescript())
    _TSX_LANG = Language(tree_sitter_typescript.language_tsx())
    _HAS_TREE_SITTER = True
except ImportError:
    _HAS_TREE_SITTER = False


@dataclass
class TSParam:
    name: str
    type_name: str


@dataclass
class TSFunctionInfo:
    name: str
    return_type: str
    parameters: list[TSParam]
    is_exported: bool
    is_async: bool
    is_arrow: bool
    is_static: bool
    start_line: int
    end_line: int
    source_code: str
    enclosing_class: Optional[str] = None
    visibility: str = "public"
    threat_score: int = 0
    threat_reasons: list[str] = field(default_factory=list)


@dataclass
class TSConstructorInfo:
    parameters: list[TSParam]
    visibility: str
    source_code: str


@dataclass
class TSFieldInfo:
    name: str
    type_name: str
    visibility: str
    is_static: bool
    is_readonly: bool


@dataclass
class TSClassInfo:
    name: str
    is_exported: bool
    constructors: list[TSConstructorInfo] = field(default_factory=list)
    fields: list[TSFieldInfo] = field(default_factory=list)
    methods: list[TSFunctionInfo] = field(default_factory=list)


@dataclass
class TSTypeInfo:
    name: str
    kind: str  # "interface", "type", "enum"
    source_code: str


@dataclass
class TSParsedFile:
    imports: list[str]
    types: list[TSTypeInfo]
    classes: list[TSClassInfo]
    all_functions: list[TSFunctionInfo]
    source_code: str


def _get_node_text(node: Optional[Node], source_bytes: bytes) -> str:
    if not node:
        return ""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _score_ts_threat(node: Node, source_bytes: bytes) -> tuple[int, list[str]]:
    """Score threat surface for TypeScript / JavaScript functions."""
    score = 0
    reasons: list[str] = []
    code = _get_node_text(node, source_bytes)

    # 1. Division or modulo (Zero-division, NaN, Infinity)
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
            reasons.append("Arithmetic division or modulo (zero-division / NaN / Infinity risk)")

    # 2. Array index access (Out of bounds -> undefined)
    def has_subscript(n: Node) -> bool:
        if n.type == "subscript_expression":
            return True
        for ch in n.children:
            if has_subscript(ch):
                return True
        return False

    if has_subscript(node) or re.search(r"\[\s*[^\]\s]+\s*\]", code):
        score += 20
        reasons.append("Array indexing (out-of-bounds undefined access risk)")

    # 3. JSON.parse / Serialization (Throws uncaught SyntaxError)
    if "JSON.parse" in code:
        score += 25
        reasons.append("JSON.parse operation (SyntaxError risk on unexpected payload)")

    # 4. Numeric parsing (parseInt / parseFloat -> NaN propagation)
    if "parseInt" in code or "parseFloat" in code or "Number(" in code:
        score += 15
        reasons.append("Numeric string conversion (NaN propagation risk)")

    # 5. Regex execution / matching
    if "match" in code or "exec" in code or "test" in code or "replace" in code:
        score += 15
        reasons.append("Regex or string mutation operations")

    # 6. Throwing exceptions / error boundaries
    if "throw " in code:
        score += 20
        reasons.append("Explicit error throw boundary")

    # 7. Null/undefined checks or defensive guards
    if "null" in code or "undefined" in code or "===" in code or "!==" in code:
        score += 10
        reasons.append("Defensive boundary / null check")

    return score, reasons


def parse_ts_ast(source: str, is_tsx: bool = False) -> TSParsedFile:
    """Parse TypeScript / JavaScript code into high-fidelity AST metadata using Tree-sitter."""
    if not _HAS_TREE_SITTER:
        raise RuntimeError("tree-sitter or tree-sitter-typescript is not installed")

    source_bytes = source.encode("utf-8")
    parser = Parser(_TSX_LANG if is_tsx else _TS_LANG)
    tree = parser.parse(source_bytes)

    imports: list[str] = []
    types: list[TSTypeInfo] = []
    classes: list[TSClassInfo] = []
    all_functions: list[TSFunctionInfo] = []

    def parse_parameters(params_node: Optional[Node]) -> list[TSParam]:
        params: list[TSParam] = []
        if not params_node:
            return params
        for child in params_node.children:
            if child.type in {"required_parameter", "optional_parameter"}:
                pat_n = child.child_by_field_name("pattern") or child.child_by_field_name("name")
                type_n = child.child_by_field_name("type")
                val_n = child.child_by_field_name("value")
                
                if pat_n:
                    p_name = _get_node_text(pat_n, source_bytes).strip()
                else:
                    # fallback to first identifier
                    ids = [c for c in child.children if c.type == "identifier"]
                    p_name = _get_node_text(ids[0], source_bytes).strip() if ids else _get_node_text(child, source_bytes).split(":")[0].strip()

                if type_n:
                    p_type = _get_node_text(type_n, source_bytes).strip()
                    if p_type.startswith(":"):
                        p_type = p_type[1:].strip()
                else:
                    p_type = "any"

                if val_n:
                    default_val = _get_node_text(val_n, source_bytes).strip()
                    p_name = f"{p_name} = {default_val}"

                params.append(TSParam(name=p_name, type_name=p_type))
            elif child.type == "identifier":
                params.append(TSParam(name=_get_node_text(child, source_bytes), type_name="any"))
        return params

    def parse_class_node(class_node: Node, is_exported: bool) -> TSClassInfo:
        name_n = class_node.child_by_field_name("name")
        c_name = _get_node_text(name_n, source_bytes) if name_n else "AnonymousClass"
        body = class_node.child_by_field_name("body")

        constructors: list[TSConstructorInfo] = []
        fields: list[TSFieldInfo] = []
        methods: list[TSFunctionInfo] = []

        if body:
            for member in body.children:
                if member.type == "method_definition":
                    name_child = member.child_by_field_name("name")
                    m_name = _get_node_text(name_child, source_bytes) if name_child else ""
                    m_text = _get_node_text(member, source_bytes)

                    is_stat = False
                    is_async = False
                    vis = "public"
                    for ch in member.children:
                        if ch.type == "accessibility_modifier":
                            vis = _get_node_text(ch, source_bytes)
                        elif ch.type == "static":
                            is_stat = True
                        elif ch.type == "async":
                            is_async = True

                    params_n = member.child_by_field_name("parameters")
                    params = parse_parameters(params_n)

                    if m_name == "constructor":
                        constructors.append(
                            TSConstructorInfo(parameters=params, visibility=vis, source_code=m_text)
                        )
                    else:
                        ret_n = member.child_by_field_name("return_type")
                        ret_type = _get_node_text(ret_n, source_bytes) if ret_n else "any"
                        if ret_type.startswith(":"):
                            ret_type = ret_type[1:].strip()

                        score, reasons = _score_ts_threat(member, source_bytes)
                        f_info = TSFunctionInfo(
                            name=m_name,
                            return_type=ret_type,
                            parameters=params,
                            is_exported=is_exported,
                            is_async=is_async,
                            is_arrow=False,
                            is_static=is_stat,
                            start_line=member.start_point[0] + 1,
                            end_line=member.end_point[0] + 1,
                            source_code=m_text,
                            enclosing_class=c_name,
                            visibility=vis,
                            threat_score=score,
                            threat_reasons=reasons,
                        )
                        methods.append(f_info)
                        all_functions.append(f_info)

                elif member.type in {"public_field_definition", "field_definition", "property_definition"}:
                    name_child = member.child_by_field_name("name") or member.child_by_field_name("property")
                    f_name = _get_node_text(name_child, source_bytes) if name_child else ""
                    vis = "public"
                    is_stat = False
                    is_ro = False
                    for ch in member.children:
                        if ch.type == "accessibility_modifier":
                            vis = _get_node_text(ch, source_bytes)
                        elif ch.type == "static":
                            is_stat = True
                        elif ch.type == "readonly":
                            is_ro = True
                    type_n = member.child_by_field_name("type")
                    type_str = _get_node_text(type_n, source_bytes) if type_n else "any"
                    if type_str.startswith(":"):
                        type_str = type_str[1:].strip()
                    fields.append(
                        TSFieldInfo(name=f_name, type_name=type_str, visibility=vis, is_static=is_stat, is_readonly=is_ro)
                    )

        return TSClassInfo(
            name=c_name,
            is_exported=is_exported,
            constructors=constructors,
            fields=fields,
            methods=methods,
        )

    for node in tree.root_node.children:
        is_exported = False
        target_node = node

        if node.type == "export_statement":
            is_exported = True
            # The exported item is inside children
            for ch in node.children:
                if ch.type in {
                    "class_declaration",
                    "function_declaration",
                    "lexical_declaration",
                    "interface_declaration",
                    "type_alias_declaration",
                    "enum_declaration",
                }:
                    target_node = ch
                    break

        if target_node.type == "import_statement":
            imports.append(_get_node_text(node, source_bytes).strip())

        elif target_node.type == "class_declaration":
            classes.append(parse_class_node(target_node, is_exported))

        elif target_node.type == "function_declaration":
            name_n = target_node.child_by_field_name("name")
            f_name = _get_node_text(name_n, source_bytes) if name_n else "anonymous"
            is_async = any(c.type == "async" for c in target_node.children)
            params = parse_parameters(target_node.child_by_field_name("parameters"))
            ret_n = target_node.child_by_field_name("return_type")
            ret_type = _get_node_text(ret_n, source_bytes) if ret_n else "any"
            if ret_type.startswith(":"):
                ret_type = ret_type[1:].strip()

            score, reasons = _score_ts_threat(target_node, source_bytes)
            f_info = TSFunctionInfo(
                name=f_name,
                return_type=ret_type,
                parameters=params,
                is_exported=is_exported,
                is_async=is_async,
                is_arrow=False,
                is_static=False,
                start_line=target_node.start_point[0] + 1,
                end_line=target_node.end_point[0] + 1,
                source_code=_get_node_text(node if is_exported else target_node, source_bytes),
                threat_score=score,
                threat_reasons=reasons,
            )
            all_functions.append(f_info)

        elif target_node.type == "lexical_declaration":
            # const foo = (x) => ...
            for decl in target_node.children:
                if decl.type == "variable_declarator":
                    name_n = decl.child_by_field_name("name")
                    value_n = decl.child_by_field_name("value")
                    if value_n and value_n.type == "arrow_function":
                        f_name = _get_node_text(name_n, source_bytes) if name_n else "anonymous"
                        is_async = any(c.type == "async" for c in value_n.children)
                        params = parse_parameters(value_n.child_by_field_name("parameters"))
                        ret_n = value_n.child_by_field_name("return_type")
                        ret_type = _get_node_text(ret_n, source_bytes) if ret_n else "any"
                        if ret_type.startswith(":"):
                            ret_type = ret_type[1:].strip()

                        score, reasons = _score_ts_threat(value_n, source_bytes)
                        f_info = TSFunctionInfo(
                            name=f_name,
                            return_type=ret_type,
                            parameters=params,
                            is_exported=is_exported,
                            is_async=is_async,
                            is_arrow=True,
                            is_static=False,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            source_code=_get_node_text(node, source_bytes),
                            threat_score=score,
                            threat_reasons=reasons,
                        )
                        all_functions.append(f_info)

        elif target_node.type == "interface_declaration":
            name_n = target_node.child_by_field_name("name")
            t_name = _get_node_text(name_n, source_bytes) if name_n else "Interface"
            types.append(
                TSTypeInfo(
                    name=t_name,
                    kind="interface",
                    source_code=_get_node_text(node if is_exported else target_node, source_bytes),
                )
            )

        elif target_node.type == "type_alias_declaration":
            name_n = target_node.child_by_field_name("name")
            t_name = _get_node_text(name_n, source_bytes) if name_n else "Type"
            types.append(
                TSTypeInfo(
                    name=t_name,
                    kind="type",
                    source_code=_get_node_text(node if is_exported else target_node, source_bytes),
                )
            )

        elif target_node.type == "enum_declaration":
            name_n = target_node.child_by_field_name("name")
            t_name = _get_node_text(name_n, source_bytes) if name_n else "Enum"
            types.append(
                TSTypeInfo(
                    name=t_name,
                    kind="enum",
                    source_code=_get_node_text(node if is_exported else target_node, source_bytes),
                )
            )

    return TSParsedFile(
        imports=imports,
        types=types,
        classes=classes,
        all_functions=all_functions,
        source_code=source,
    )


def generate_ts_api_contract(parsed: TSParsedFile, target_name: Optional[str] = None) -> str:
    """Generate a strict, anti-hallucination API contract markdown block for TypeScript / JavaScript."""
    lines = ["### STRICT API CONTRACT (DO NOT HALLUCINATE TYPES OR PRIVATE MEMBERS):"]

    # 1. Types and Interfaces
    if parsed.types:
        lines.append("- Defined Types / Interfaces / Enums:")
        for t in parsed.types:
            lines.append(f"  * `{t.name}` ({t.kind})")

    # 2. Classes
    for c in parsed.classes:
        lines.append(f"- Class: `{c.name}` (exported: {c.is_exported})")
        if c.constructors:
            for cons in c.constructors:
                p_str = ", ".join(f"{p.name}: {p.type_name}" for p in cons.parameters)
                lines.append(f"  * Constructor: `new {c.name}({p_str})` [visibility: {cons.visibility}]")
        else:
            lines.append(f"  * Default Constructor: `new {c.name}()` (no arguments)")

        # Public methods
        public_methods = [m for m in c.methods if m.visibility == "public"]
        if public_methods:
            lines.append("  * Public Callable Methods:")
            for m in public_methods:
                p_str = ", ".join(f"{p.name}: {p.type_name}" for p in m.parameters)
                static_tag = " [static]" if m.is_static else ""
                async_tag = " [async]" if m.is_async else ""
                lines.append(f"    - `{m.name}({p_str}): {m.return_type}`{static_tag}{async_tag}")

        # Forbidden private members
        priv_fields = [f.name for f in c.fields if f.visibility == "private" or f.name.startswith("#")]
        if priv_fields:
            lines.append(f"  * FORBIDDEN Private Fields (DO NOT ACCESS DIRECTLY): {', '.join(priv_fields)}")

        priv_methods = [m.name for m in c.methods if m.visibility == "private" or m.name.startswith("#")]
        if priv_methods:
            lines.append(f"  * FORBIDDEN Private Methods (DO NOT CALL DIRECTLY): {', '.join(priv_methods)}")

    # 3. Standalone Exported Functions
    standalone_exports = [f for f in parsed.all_functions if f.enclosing_class is None and f.is_exported]
    if standalone_exports:
        lines.append("- Standalone Exported Functions:")
        for f in standalone_exports:
            p_str = ", ".join(f"{p.name}: {p.type_name}" for p in f.parameters)
            async_tag = " [async]" if f.is_async else ""
            lines.append(f"  * `{f.name}({p_str}): {f.return_type}`{async_tag}")

    return "\n".join(lines)
