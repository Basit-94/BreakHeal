"""Tree-sitter AST parser, API Contract Oracle, and Threat Surface Scorer for Java."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from tree_sitter import Language, Parser, Node
    import tree_sitter_java

    _JAVA_LANG = Language(tree_sitter_java.language())
    _HAS_TREE_SITTER = True
except ImportError:
    _HAS_TREE_SITTER = False


@dataclass
class JavaParam:
    name: str
    type_name: str


@dataclass
class JavaMethodInfo:
    name: str
    return_type: str
    parameters: list[JavaParam]
    visibility: str  # "public", "protected", "private", "package-private"
    is_static: bool
    start_line: int
    end_line: int
    source_code: str
    enclosing_class: str
    threat_score: int = 0
    threat_reasons: list[str] = field(default_factory=list)


@dataclass
class JavaConstructorInfo:
    name: str
    parameters: list[JavaParam]
    visibility: str
    source_code: str


@dataclass
class JavaFieldInfo:
    name: str
    type_name: str
    visibility: str
    is_static: bool


@dataclass
class JavaClassInfo:
    name: str
    kind: str  # "class", "record", "enum", "interface"
    visibility: str
    is_static: bool
    constructors: list[JavaConstructorInfo] = field(default_factory=list)
    fields: list[JavaFieldInfo] = field(default_factory=list)
    methods: list[JavaMethodInfo] = field(default_factory=list)
    inner_classes: list[JavaClassInfo] = field(default_factory=list)


@dataclass
class JavaParsedFile:
    package_name: str
    imports: list[str]
    classes: list[JavaClassInfo]
    all_methods: list[JavaMethodInfo]
    source_code: str


def _get_node_text(node: Node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _get_visibility(modifiers_node: Optional[Node], source_bytes: bytes) -> str:
    if not modifiers_node:
        return "package-private"
    text = _get_node_text(modifiers_node, source_bytes)
    if "public" in text:
        return "public"
    if "protected" in text:
        return "protected"
    if "private" in text:
        return "private"
    return "package-private"


def _is_static(modifiers_node: Optional[Node], source_bytes: bytes) -> bool:
    if not modifiers_node:
        return False
    return "static" in _get_node_text(modifiers_node, source_bytes).split()


def _score_method_threat(node: Node, source_bytes: bytes) -> tuple[int, list[str]]:
    """Analyze method AST nodes for arithmetic boundaries, zero division, casting, and array access."""
    score = 0
    reasons = []

    code = _get_node_text(node, source_bytes)

    # 1. Division or modulo (Zero-division threat)
    if "/" in code or "%" in code:
        # Check for binary expressions with / or %
        def has_div_op(n: Node) -> bool:
            if n.type == "binary_expression":
                op = n.child_by_field_name("operator")
                if op and op.type in {"/", "%"}:
                    return True
            for child in n.children:
                if has_div_op(child):
                    return True
            return False

        if has_div_op(node) or re.search(r"[a-zA-Z0-9_)]\s*[/]\s*[a-zA-Z0-9_(]", code):
            score += 35
            reasons.append("Contains arithmetic division or modulo (zero-division risk)")

    # 2. Floating-point or BigDecimal division
    if "divide" in code or "BigDecimal" in code:
        score += 25
        reasons.append("Performs BigDecimal division / financial math (precision / RoundingMode risk)")

    def has_node_type(n: Node, target_type: str) -> bool:
        if n.type == target_type:
            return True
        for child in n.children:
            if has_node_type(child, target_type):
                return True
        return False

    # 3. Collection or array access without defensive check
    if has_node_type(node, "array_access") or re.search(r"\[\s*[^\]\s]+\s*\]", code):
        score += 20
        reasons.append("Performs array indexing (ArrayIndexOutOfBounds risk)")

    # 4. Math.pow or exponential formulas (integer overflow)
    if "Math.pow" in code or "Math.exp" in code:
        score += 25
        reasons.append("Exponential formula (integer/long overflow risk)")

    # 5. Type casting
    if re.search(r"\((?:int|long|double|float|short|byte)\)", code):
        score += 15
        reasons.append("Type casting operations (truncation / overflow risk)")

    # 6. Negative or boundary comparison checks (<, <=, >, >=, == 0)
    if re.search(r"[<>=!]=\s*0\b|\bnull\b", code):
        score += 10
        reasons.append("Checks boundaries or null states")

    return score, reasons


def parse_java_ast(source: str) -> JavaParsedFile:
    """Parse Java source code into high-fidelity AST metadata using Tree-sitter."""
    if not _HAS_TREE_SITTER:
        # Fallback will be handled via java_context regex
        raise RuntimeError("tree-sitter or tree-sitter-java is not installed")

    source_bytes = source.encode("utf-8")
    parser = Parser(_JAVA_LANG)
    tree = parser.parse(source_bytes)

    package_name = ""
    imports = []
    classes: list[JavaClassInfo] = []
    all_methods: list[JavaMethodInfo] = []

    def parse_params(params_node: Optional[Node]) -> list[JavaParam]:
        params = []
        if not params_node:
            return params
        for child in params_node.children:
            if child.type in {"formal_parameter", "spread_parameter"}:
                type_n = child.child_by_field_name("type")
                name_n = child.child_by_field_name("name")
                t_str = _get_node_text(type_n, source_bytes) if type_n else "Object"
                n_str = _get_node_text(name_n, source_bytes) if name_n else ""
                params.append(JavaParam(name=n_str, type_name=t_str))
            elif child.type == "record_component":
                type_n = child.child_by_field_name("type")
                name_n = child.child_by_field_name("name")
                t_str = _get_node_text(type_n, source_bytes) if type_n else "Object"
                n_str = _get_node_text(name_n, source_bytes) if name_n else ""
                params.append(JavaParam(name=n_str, type_name=t_str))
        return params

    def parse_class_node(class_node: Node) -> JavaClassInfo:
        c_name_node = class_node.child_by_field_name("name")
        c_name = _get_node_text(c_name_node, source_bytes) if c_name_node else "Anonymous"
        kind = class_node.type.replace("_declaration", "")

        mod_node = None
        for ch in class_node.children:
            if ch.type == "modifiers":
                mod_node = ch
                break

        visibility = _get_visibility(mod_node, source_bytes)
        is_stat = _is_static(mod_node, source_bytes)

        body_node = class_node.child_by_field_name("body")
        constructors: list[JavaConstructorInfo] = []
        fields: list[JavaFieldInfo] = []
        methods: list[JavaMethodInfo] = []
        inners: list[JavaClassInfo] = []

        # For records, the record parameters serve as canonical constructor
        if kind == "record":
            header_node = class_node.child_by_field_name("parameters")
            rec_params = parse_params(header_node)
            constructors.append(
                JavaConstructorInfo(
                    name=c_name,
                    parameters=rec_params,
                    visibility=visibility,
                    source_code=f"public {c_name}({', '.join(f'{p.type_name} {p.name}' for p in rec_params)})",
                )
            )

        if body_node:
            for child in body_node.children:
                if child.type == "constructor_declaration":
                    c_mod = None
                    for m in child.children:
                        if m.type == "modifiers":
                            c_mod = m
                            break
                    c_vis = _get_visibility(c_mod, source_bytes)
                    p_node = child.child_by_field_name("parameters")
                    params = parse_params(p_node)
                    c_code = _get_node_text(child, source_bytes)
                    constructors.append(
                        JavaConstructorInfo(name=c_name, parameters=params, visibility=c_vis, source_code=c_code)
                    )

                elif child.type == "field_declaration":
                    f_mod = None
                    for m in child.children:
                        if m.type == "modifiers":
                            f_mod = m
                            break
                    f_vis = _get_visibility(f_mod, source_bytes)
                    f_stat = _is_static(f_mod, source_bytes)
                    type_n = child.child_by_field_name("type")
                    t_str = _get_node_text(type_n, source_bytes) if type_n else "Object"
                    # A field declaration can have multiple declarators
                    for dec in child.children:
                        if dec.type == "variable_declarator":
                            var_name_n = dec.child_by_field_name("name")
                            if var_name_n:
                                fields.append(
                                    JavaFieldInfo(
                                        name=_get_node_text(var_name_n, source_bytes),
                                        type_name=t_str,
                                        visibility=f_vis,
                                        is_static=f_stat,
                                    )
                                )

                elif child.type == "method_declaration":
                    m_name_n = child.child_by_field_name("name")
                    m_name = _get_node_text(m_name_n, source_bytes) if m_name_n else "method"
                    m_mod = None
                    for m in child.children:
                        if m.type == "modifiers":
                            m_mod = m
                            break
                    m_vis = _get_visibility(m_mod, source_bytes)
                    m_stat = _is_static(m_mod, source_bytes)
                    ret_n = child.child_by_field_name("type")
                    ret_str = _get_node_text(ret_n, source_bytes) if ret_n else "void"
                    p_node = child.child_by_field_name("parameters")
                    params = parse_params(p_node)
                    start_l = child.start_point[0] + 1
                    end_l = child.end_point[0] + 1
                    m_code = _get_node_text(child, source_bytes)
                    score, reasons = _score_method_threat(child, source_bytes)

                    minfo = JavaMethodInfo(
                        name=m_name,
                        return_type=ret_str,
                        parameters=params,
                        visibility=m_vis,
                        is_static=m_stat,
                        start_line=start_l,
                        end_line=end_l,
                        source_code=m_code,
                        enclosing_class=c_name,
                        threat_score=score,
                        threat_reasons=reasons,
                    )
                    methods.append(minfo)
                    all_methods.append(minfo)

                elif child.type in {"class_declaration", "record_declaration", "enum_declaration", "interface_declaration"}:
                    inners.append(parse_class_node(child))

        return JavaClassInfo(
            name=c_name,
            kind=kind,
            visibility=visibility,
            is_static=is_stat,
            constructors=constructors,
            fields=fields,
            methods=methods,
            inner_classes=inners,
        )

    for child in tree.root_node.children:
        if child.type == "package_declaration":
            for n in child.children:
                if n.type == "scoped_identifier" or n.type == "identifier":
                    package_name = _get_node_text(n, source_bytes)
                    break
        elif child.type == "import_declaration":
            imports.append(_get_node_text(child, source_bytes).strip())
        elif child.type in {"class_declaration", "record_declaration", "enum_declaration", "interface_declaration"}:
            classes.append(parse_class_node(child))

    return JavaParsedFile(
        package_name=package_name,
        imports=imports,
        classes=classes,
        all_methods=all_methods,
        source_code=source,
    )


def generate_java_api_contract(parsed: JavaParsedFile, target_class_name: str) -> str:
    """Generate a strict, anti-hallucination API contract markdown block for LLM prompts."""
    # Find the target class or inner class
    target_class = None
    for c in parsed.classes:
        if c.name == target_class_name:
            target_class = c
            break
        for inc in c.inner_classes:
            if inc.name == target_class_name or f"{c.name}.{inc.name}" == target_class_name:
                target_class = inc
                break

    if not target_class and parsed.classes:
        target_class = parsed.classes[0]

    if not target_class:
        return ""

    lines = [
        "### STRICT API CONTRACT (DO NOT HALLUCINATE OR CALL PRIVATE MEMBERS):",
        f"- Target Class: `{target_class.name}` ({target_class.visibility} {target_class.kind})",
    ]

    # Constructors
    public_constructors = [c for c in target_class.constructors if c.visibility in {"public", "protected"}]
    if public_constructors:
        lines.append("- Valid Constructors:")
        for c in public_constructors:
            param_str = ", ".join(f"{p.type_name} {p.name}" for p in c.parameters)
            lines.append(f"  * `new {c.name}({param_str})`")
    else:
        lines.append(f"- Default Constructor: `new {target_class.name}()` (no arguments)")

    # Public Methods
    public_methods = [
        m for m in target_class.methods
        if m.visibility == "public" and m.name not in {"main", "toString", "hashCode", "equals"}
    ]
    if public_methods:
        lines.append("- Callable Public Methods:")
        for m in public_methods:
            static_tag = " [static]" if m.is_static else ""
            param_str = ", ".join(f"{p.type_name} {p.name}" for p in m.parameters)
            lines.append(f"  * `{m.name}({param_str}) -> {m.return_type}`{static_tag}")

    # Inner Types
    if target_class.inner_classes:
        lines.append("- Nested Inner Types / Enums (Must qualify or wildcard import):")
        for inc in target_class.inner_classes:
            lines.append(f"  * `{target_class.name}.{inc.name}` ({inc.kind})")
            for ic in inc.constructors:
                if ic.visibility == "public":
                    p_str = ", ".join(f"{p.type_name} {p.name}" for p in ic.parameters)
                    lines.append(f"    - `new {target_class.name}.{inc.name}({p_str})`")

    # Forbidden Private Members
    private_fields = [f.name for f in target_class.fields if f.visibility == "private"]
    if private_fields:
        lines.append(f"- FORBIDDEN Private Fields (DO NOT ACCESS DIRECTLY): {', '.join(private_fields)}")

    private_methods = [m.name for m in target_class.methods if m.visibility == "private"]
    if private_methods:
        lines.append(f"- FORBIDDEN Private Methods (DO NOT CALL DIRECTLY): {', '.join(private_methods)}")

    return "\n".join(lines)
