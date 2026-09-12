"""Tests for Tree-sitter Rust AST, threat scoring, and API contract generator."""

import pytest
from breakheal.rust_ast import (
    parse_rust_ast,
    generate_rust_api_contract,
    _HAS_TREE_SITTER,
)
from breakheal.rust_context import extract_rust_context


@pytest.mark.skipif(not _HAS_TREE_SITTER, reason="Tree-sitter Rust is not installed")
def test_parse_rust_ast_threats_and_contracts(tmp_path):
    rust_code = """
pub struct OrderEngine {
    secret_seed: u64,
    pub active: bool,
}

impl OrderEngine {
    pub fn new(seed: u64) -> Self {
        OrderEngine { secret_seed: seed, active: true }
    }

    pub fn calculate_spread(&self, high: f64, low: f64, count: u32) -> f64 {
        let diff = high - low;
        diff / (count as f64)
    }

    pub fn dangerous_lookup(&self, val: Option<i32>) -> i32 {
        val.unwrap()
    }
}
"""
    rust_file = tmp_path / "order_engine.rs"
    rust_file.write_text(rust_code, encoding="utf-8")

    parsed = parse_rust_ast(rust_code)
    assert len(parsed.structs) == 1
    assert parsed.structs[0].name == "OrderEngine"

    # calculate_spread has division: threat score >= 35
    spread_fn = next(f for f in parsed.all_functions if f.name == "calculate_spread")
    assert spread_fn.threat_score >= 35

    # dangerous_lookup has unwrap(): threat score >= 35
    unwrap_fn = next(f for f in parsed.all_functions if f.name == "dangerous_lookup")
    assert unwrap_fn.threat_score >= 35

    # API contract verification: secret_seed is private, active is pub
    contract = generate_rust_api_contract(parsed)
    assert "OrderEngine" in contract
    assert "active" in contract
    assert "FORBIDDEN Private Fields" in contract
    assert "secret_seed" in contract

    # extract_rust_context auto-threat ranking: should pick one of the high-threat functions
    ctx = extract_rust_context(rust_file)
    assert ctx.threat_score >= 35
    assert "STRICT RUST API CONTRACT" in ctx.api_contract
