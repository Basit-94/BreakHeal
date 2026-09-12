"""Deterministic AST Mutation Fuzzing Engine for BreakHeal.

Automatically injects boundary condition mutations (swapping comparison operators,
boundary constants, removing guards) and executes test suites to discover unkilled mutants.
Surviving mutants represent untested boundary vulnerabilities that are fed into the LLM
to generate proven adversarial tests.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from breakheal.runner import run_pytest, TestResult


@dataclass
class Mutation:
    """Represents a single deterministic AST mutation."""
    id: str
    line_number: int
    original_code: str
    mutated_code: str
    mutation_type: str
    description: str


@dataclass
class MutationResult:
    """Result of running tests against a mutated codebase."""
    mutation: Mutation
    survived: bool  # True if tests still passed (mutant NOT caught)
    test_output: str


class ComparisonTransformer(ast.NodeTransformer):
    """Mutate comparison operators (< -> <=, > -> >=, == -> !=, etc.)."""

    OP_MAP = {
        ast.Lt: (ast.LtE, "<", "<="),
        ast.LtE: (ast.Lt, "<=", "<"),
        ast.Gt: (ast.GtE, ">", ">="),
        ast.GtE: (ast.Gt, ">=", ">"),
        ast.Eq: (ast.NotEq, "==", "!="),
        ast.NotEq: (ast.Eq, "!=", "=="),
    }

    def __init__(self, target_line: Optional[int] = None):
        super().__init__()
        self.target_line = target_line
        self.mutations: List[Mutation] = []
        self._counter = 0

    def visit_Compare(self, node: ast.Compare) -> Any:
        self.generic_visit(node)
        new_ops = []
        for op in node.ops:
            op_type = type(op)
            if op_type in self.OP_MAP:
                new_type, orig_sym, new_sym = self.OP_MAP[op_type]
                lineno = getattr(node, "lineno", 0)

                mut_id = f"cmp_{lineno}_{self._counter}"
                self._counter += 1

                self.mutations.append(
                    Mutation(
                        id=mut_id,
                        line_number=lineno,
                        original_code=orig_sym,
                        mutated_code=new_sym,
                        mutation_type="boundary_comparison",
                        description=f"Swapped boundary operator '{orig_sym}' to '{new_sym}' at line {lineno}",
                    )
                )

                if self.target_line == lineno:
                    new_ops.append(new_type())
                else:
                    new_ops.append(op)
            else:
                new_ops.append(op)

        if self.target_line is not None:
            node.ops = new_ops
        return node


class GuardRemovalTransformer(ast.NodeTransformer):
    """Mutates defensive guard statements (e.g. if cond: raise ...) to pass."""

    def __init__(self, target_line: Optional[int] = None):
        super().__init__()
        self.target_line = target_line
        self.mutations: List[Mutation] = []
        self._counter = 0

    def visit_If(self, node: ast.If) -> Any:
        self.generic_visit(node)
        lineno = getattr(node, "lineno", 0)

        # Check if the if-body contains a Raise
        has_raise = any(isinstance(stmt, ast.Raise) for stmt in node.body)
        if has_raise:
            mut_id = f"guard_{lineno}_{self._counter}"
            self._counter += 1

            self.mutations.append(
                Mutation(
                    id=mut_id,
                    line_number=lineno,
                    original_code="if guard: raise ...",
                    mutated_code="pass  # Guard removed",
                    mutation_type="guard_removal",
                    description=f"Removed defensive exception guard at line {lineno}",
                )
            )

            if self.target_line == lineno:
                # Replace the entire if-body with a Pass
                node.body = [ast.Pass(lineno=lineno, col_offset=node.col_offset)]

        return node


def discover_mutations(source_code: str) -> List[Mutation]:
    """Scan source code AST and return all potential boundary mutations."""
    tree = ast.parse(source_code)
    mutations: List[Mutation] = []

    cmp_visitor = ComparisonTransformer()
    cmp_visitor.visit(tree)
    mutations.extend(cmp_visitor.mutations)

    guard_visitor = GuardRemovalTransformer()
    guard_visitor.visit(tree)
    mutations.extend(guard_visitor.mutations)

    return mutations


def apply_mutation(source_code: str, mutation: Mutation) -> str:
    """Apply a specific mutation to source code and return modified code."""
    tree = ast.parse(source_code)

    if mutation.mutation_type == "boundary_comparison":
        transformer = ComparisonTransformer(target_line=mutation.line_number)
        modified_tree = transformer.visit(tree)
        ast.fix_missing_locations(modified_tree)
        return ast.unparse(modified_tree)

    elif mutation.mutation_type == "guard_removal":
        transformer = GuardRemovalTransformer(target_line=mutation.line_number)
        modified_tree = transformer.visit(tree)
        ast.fix_missing_locations(modified_tree)
        return ast.unparse(modified_tree)

    return source_code


def run_mutation_testing(
    target_file: Path,
    test_path: Optional[Path] = None,
    max_mutants: int = 10,
) -> List[MutationResult]:
    """
    Run mutation analysis on a Python source file:
    1. Discovers boundary mutations.
    2. Applies each mutation temporarily in-place.
    3. Runs pytest. If tests PASS, mutant SURVIVED (untested boundary flaw!).
    4. Restores original code.
    """
    original_source = target_file.read_text(encoding="utf-8")
    mutations = discover_mutations(original_source)[:max_mutants]

    results: List[MutationResult] = []

    try:
        for mutation in mutations:
            mutated_source = apply_mutation(original_source, mutation)
            if mutated_source == original_source:
                continue

            target_file.write_text(mutated_source, encoding="utf-8")

            t_path = test_path or target_file.parent
            res: TestResult = run_pytest(
                target_path=t_path,
                cwd=target_file.parent,
            )

            # A mutant SURVIVED if the test suite STILL PASSED despite the code being mutated!
            survived = res.passed

            results.append(
                MutationResult(
                    mutation=mutation,
                    survived=survived,
                    test_output=res.stdout + "\n" + res.stderr,
                )
            )

    finally:
        # Guarantee original file restoration
        target_file.write_text(original_source, encoding="utf-8")

    return results


def format_surviving_mutants_report(results: List[MutationResult]) -> str:
    """Format surviving mutants into actionable threat intelligence for the LLM."""
    survivors = [r for r in results if r.survived]
    if not survivors:
        return "No surviving mutants detected. Boundary conditions appear well-tested."

    lines = [
        f"Detected {len(survivors)} SURVIVING MUTANT(S) (Untested Boundary Flaws):",
        "The following boundary mutations were injected, yet all existing unit tests STILL PASSED:",
    ]
    for s in survivors:
        lines.append(f"- Line {s.mutation.line_number} [{s.mutation.mutation_type}]: {s.mutation.description}")
        lines.append(f"  Mutated code caused no test failures (Vulnerability Confirmed).")

    return "\n".join(lines)
