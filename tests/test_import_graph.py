"""Unit tests for BreakHeal cross-module import graph resolver."""

from pathlib import Path
from breakheal.import_graph import (
    ImportGraphResolver,
    build_import_contract_prompt_section,
)


def test_python_import_graph_resolution(tmp_path: Path):
    # Create module A: math_utils.py
    mod_a = tmp_path / "math_utils.py"
    mod_a.write_text(
        "def compute_discount(price: float, rate: float = 0.1) -> float:\n    return price * rate\n",
        encoding="utf-8",
    )

    # Create module B: checkout.py
    mod_b = tmp_path / "checkout.py"
    mod_b.write_text(
        "from math_utils import compute_discount\n\ndef run_checkout(total):\n    return compute_discount(total)\n",
        encoding="utf-8",
    )

    resolver = ImportGraphResolver(repo_root=tmp_path)
    contracts = resolver.resolve_contracts_for_file(mod_b)

    assert len(contracts) >= 1
    c = contracts[0]
    assert c.module_name == "math_utils"
    assert any("compute_discount" in s.symbol_name for s in c.signatures)

    prompt_section = build_import_contract_prompt_section(mod_b, repo_root=tmp_path)
    assert "[RESOLVED IMPORTED CONTRACTS & SIGNATURES]" in prompt_section
    assert "compute_discount" in prompt_section


def test_ts_import_graph_resolution(tmp_path: Path):
    # Create service.ts
    svc = tmp_path / "service.ts"
    svc.write_text(
        "export function getTaxRate(country: string): number {\n    return 0.2;\n}\n",
        encoding="utf-8",
    )

    # Create consumer.ts
    consumer = tmp_path / "consumer.ts"
    consumer.write_text(
        "import { getTaxRate } from './service';\nexport function calculateTax(amt: number) { return amt * getTaxRate('US'); }\n",
        encoding="utf-8",
    )

    resolver = ImportGraphResolver(repo_root=tmp_path)
    contracts = resolver.resolve_contracts_for_file(consumer)

    assert len(contracts) >= 1
    assert any("getTaxRate" in s.symbol_name for s in contracts[0].signatures)
