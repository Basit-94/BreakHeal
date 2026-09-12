"""Tests for Tree-sitter Go AST, threat scoring, and API contract generator."""

import pytest
from breakheal.go_ast import (
    parse_go_ast,
    generate_go_api_contract,
    _HAS_TREE_SITTER,
)
from breakheal.go_context import extract_go_context


@pytest.mark.skipif(not _HAS_TREE_SITTER, reason="Tree-sitter Go is not installed")
def test_parse_go_ast_threats_and_contracts(tmp_path):
    go_code = """
package payments

type Account struct {
    balance int
    Owner   string
}

func NewAccount(owner string, balance int) *Account {
    return &Account{Owner: owner, balance: balance}
}

func (a *Account) CalculateFeeRatio(fee int, divisor int) int {
    return fee / divisor
}

func GetFirstItem(items []string) string {
    return items[0]
}
"""
    go_file = tmp_path / "account.go"
    go_file.write_text(go_code, encoding="utf-8")

    parsed = parse_go_ast(go_code)
    assert parsed.package_name == "payments"
    assert len(parsed.structs) == 1
    assert parsed.structs[0].name == "Account"

    # Verify threat scoring: CalculateFeeRatio has division (>= 35)
    fee_method = next(f for f in parsed.all_functions if f.name == "CalculateFeeRatio")
    assert fee_method.threat_score >= 35

    # Verify threat scoring: GetFirstItem has slice indexing (>= 25)
    slice_fn = next(f for f in parsed.all_functions if f.name == "GetFirstItem")
    assert slice_fn.threat_score >= 25

    # Verify API contract: Owner is exported, balance is unexported (forbidden)
    contract = generate_go_api_contract(parsed)
    assert "Owner" in contract
    assert "balance" in contract
    assert "FORBIDDEN Unexported Fields" in contract
    assert "NewAccount" in contract

    # extract_go_context auto-threat ranking: should pick CalculateFeeRatio
    ctx = extract_go_context(go_file)
    assert ctx.target_name == "Account.CalculateFeeRatio"
    assert ctx.threat_score >= 35
    assert "STRICT GO API CONTRACT" in ctx.api_contract
