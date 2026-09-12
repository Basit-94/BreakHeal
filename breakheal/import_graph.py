"""Cross-module import graph and type contract resolver for multi-language repositories.

Extracts referenced dependencies, function signatures, interfaces, and classes from
neighboring files to prevent contract mismatch or hallucinated external calls.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class ImportedSignature:
    symbol_name: str
    signature: str
    source_file: str
    kind: str = "function"  # "function", "class", "interface", "method"


@dataclass
class ModuleContract:
    module_name: str
    source_path: str
    signatures: List[ImportedSignature] = field(default_factory=list)

    def to_context_block(self) -> str:
        """Format the contract as an informative markdown block for LLM prompts."""
        if not self.signatures:
            return ""
        lines = [f"Module: `{self.module_name}` (from `{Path(self.source_path).name}`):"]
        for s in self.signatures:
            lines.append(f"  • [{s.kind.upper()}] {s.signature}")
        return "\n".join(lines)


class ImportGraphResolver:
    """Resolves local project imports for Python, TypeScript, and Java files."""

    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = repo_root or Path.cwd()

    def resolve_contracts_for_file(self, target_file: Path | str) -> List[ModuleContract]:
        """Discover and resolve all local project dependencies imported by target_file."""
        path = Path(target_file).resolve()
        if not path.exists():
            return []

        suffix = path.suffix.lower()
        if suffix == ".py":
            return self._resolve_python_imports(path)
        elif suffix in (".ts", ".js", ".tsx", ".jsx"):
            return self._resolve_ts_imports(path)
        elif suffix == ".java":
            return self._resolve_java_imports(path)
        return []

    def _resolve_python_imports(self, path: Path) -> List[ModuleContract]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return []

        contracts: List[ModuleContract] = []
        file_dir = path.parent

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Find candidate local files
                rel_parts = node.module.split(".")
                candidate_paths = [
                    file_dir / f"{rel_parts[-1]}.py",
                    self.repo_root / ("/".join(rel_parts) + ".py"),
                    self.repo_root / ("/".join(rel_parts) + "/__init__.py"),
                ]
                for cand in candidate_paths:
                    if cand.exists() and cand.is_file() and cand != path:
                        mod_contract = self._extract_python_signatures(node.module, cand, node.names)
                        if mod_contract:
                            contracts.append(mod_contract)
                        break
        return contracts

    def _extract_python_signatures(
        self,
        module_name: str,
        source_path: Path,
        imported_names: Sequence[ast.alias],
    ) -> Optional[ModuleContract]:
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return None

        wanted = {alias.name for alias in imported_names}
        sigs: List[ImportedSignature] = []

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and (not wanted or node.name in wanted or "*" in wanted):
                # Build function signature
                args_list = []
                for a in node.args.args:
                    arg_str = a.arg
                    if a.annotation:
                        try:
                            arg_str += f": {ast.unparse(a.annotation)}"
                        except Exception:
                            pass
                    args_list.append(arg_str)
                ret = ""
                if node.returns:
                    try:
                        ret = f" -> {ast.unparse(node.returns)}"
                    except Exception:
                        pass
                sig_str = f"def {node.name}({', '.join(args_list)}){ret}"
                sigs.append(ImportedSignature(symbol_name=node.name, signature=sig_str, source_file=str(source_path), kind="function"))

            elif isinstance(node, ast.ClassDef) and (not wanted or node.name in wanted or "*" in wanted):
                methods = [m.name for m in node.body if isinstance(m, ast.FunctionDef)]
                methods_str = ", ".join(methods[:5])
                sig_str = f"class {node.name} (methods: {methods_str})"
                sigs.append(ImportedSignature(symbol_name=node.name, signature=sig_str, source_file=str(source_path), kind="class"))

        return ModuleContract(module_name=module_name, source_path=str(source_path), signatures=sigs)

    def _resolve_ts_imports(self, path: Path) -> List[ModuleContract]:
        content = path.read_text(encoding="utf-8", errors="ignore")
        file_dir = path.parent
        contracts: List[ModuleContract] = []

        # Regex for ES import: import { a, b } from './sub' or import Foo from './sub'
        import_pattern = re.compile(r"""import\s+(?:\{([^}]+)\}|(\w+))\s+from\s+['"]([^'"]+)['"]""")
        for match in import_pattern.finditer(content):
            named_group, default_group, rel_path = match.groups()
            if not rel_path.startswith("."):
                continue  # External npm package, ignore for local resolution

            candidate_paths = [
                file_dir / f"{rel_path}.ts",
                file_dir / f"{rel_path}.js",
                file_dir / f"{rel_path}.tsx",
                file_dir / f"{rel_path}.jsx",
                file_dir / rel_path / "index.ts",
                file_dir / rel_path / "index.js",
            ]
            for cand in candidate_paths:
                cand = cand.resolve()
                if cand.exists() and cand.is_file() and cand != path:
                    sigs = self._extract_ts_signatures(cand)
                    if sigs:
                        contracts.append(ModuleContract(module_name=rel_path, source_path=str(cand), signatures=sigs))
                    break
        return contracts

    def _extract_ts_signatures(self, path: Path) -> List[ImportedSignature]:
        content = path.read_text(encoding="utf-8", errors="ignore")
        sigs: List[ImportedSignature] = []

        # Exported functions: export function foo(...)
        func_pat = re.compile(r"""export\s+(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)(?:\s*:\s*([^;{]+))?""")
        for m in func_pat.finditer(content):
            name, params, ret = m.groups()
            ret_str = f": {ret.strip()}" if ret else ""
            clean_params = " ".join(params.split())
            sig = f"export function {name}({clean_params}){ret_str}"
            sigs.append(ImportedSignature(symbol_name=name, signature=sig, source_file=str(path), kind="function"))

        # Exported classes/interfaces: export (class|interface) Bar
        class_pat = re.compile(r"""export\s+(class|interface)\s+(\w+)""")
        for m in class_pat.finditer(content):
            kind, name = m.groups()
            sig = f"export {kind} {name}"
            sigs.append(ImportedSignature(symbol_name=name, signature=sig, source_file=str(path), kind=kind))

        return sigs

    def _resolve_java_imports(self, path: Path) -> List[ModuleContract]:
        # Scan sibling .java files in the same directory (same package)
        file_dir = path.parent
        contracts: List[ModuleContract] = []
        sigs: List[ImportedSignature] = []

        for sibling in file_dir.glob("*.java"):
            if sibling == path:
                continue
            content = sibling.read_text(encoding="utf-8", errors="ignore")
            # Discover public methods
            method_pat = re.compile(r"""public\s+(?:static\s+)?([\w<>[\]]+)\s+(\w+)\s*\(([^)]*)\)""")
            for m in method_pat.finditer(content):
                ret_type, name, params = m.groups()
                clean_params = " ".join(params.split())
                sig = f"public {ret_type} {name}({clean_params})"
                sigs.append(ImportedSignature(symbol_name=name, signature=sig, source_file=str(sibling), kind="method"))

        if sigs:
            contracts.append(ModuleContract(module_name=file_dir.name, source_path=str(file_dir), signatures=sigs[:8]))
        return contracts


def build_import_contract_prompt_section(target_file: Path | str, repo_root: Optional[Path] = None) -> str:
    """Helper to generate a markdown context block for LLM prompts containing imported contracts."""
    resolver = ImportGraphResolver(repo_root=repo_root)
    contracts = resolver.resolve_contracts_for_file(target_file)
    if not contracts:
        return ""

    blocks = [c.to_context_block() for c in contracts if c.to_context_block()]
    if not blocks:
        return ""

    return "\n### [RESOLVED IMPORTED CONTRACTS & SIGNATURES]\n" + "\n\n".join(blocks) + "\n"
