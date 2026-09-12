"""Tests for Tree-sitter Java AST, threat scoring, and API contract generator."""

import pytest
from breakheal.java_ast import (
    parse_java_ast,
    generate_java_api_contract,
    _HAS_TREE_SITTER,
)
from breakheal.java_context import extract_java_context


@pytest.mark.skipif(not _HAS_TREE_SITTER, reason="Tree-sitter Java is not installed")
def test_parse_java_ast_records_and_threats(tmp_path):
    java_code = """
package com.example.test;

import java.util.List;

public class MathEngine {
    private List<String> history;
    public final int maxIterations;

    public MathEngine(int maxIterations) {
        this.maxIterations = maxIterations;
    }

    public double calculateRatio(int a, int b) {
        return (double) a / b;
    }

    public int getSafeValue(int[] items, int idx) {
        return items[idx];
    }

    public String toString() {
        return "MathEngine";
    }
}
"""
    java_file = tmp_path / "MathEngine.java"
    java_file.write_text(java_code, encoding="utf-8")

    parsed = parse_java_ast(java_code)
    assert parsed.package_name == "com.example.test"
    assert len(parsed.classes) == 1
    assert parsed.classes[0].name == "MathEngine"
    assert len(parsed.classes[0].constructors) == 1

    # Ratio has division: threat score should be >= 35
    ratio_method = next(m for m in parsed.all_methods if m.name == "calculateRatio")
    assert ratio_method.threat_score >= 35
    assert any("division" in r for r in ratio_method.threat_reasons)

    # getSafeValue has array indexing: threat score >= 20
    array_method = next(m for m in parsed.all_methods if m.name == "getSafeValue")
    assert array_method.threat_score >= 20

    # API contract verification
    contract = generate_java_api_contract(parsed, "MathEngine")
    assert "new MathEngine(int maxIterations)" in contract
    assert "calculateRatio(int a, int b) -> double" in contract
    assert "FORBIDDEN Private Fields (DO NOT ACCESS DIRECTLY): history" in contract

    # extract_java_context auto-threat ranking: should pick calculateRatio
    ctx = extract_java_context(java_file)
    assert ctx.method_name == "calculateRatio"
    assert ctx.threat_score >= 35
    assert "STRICT API CONTRACT" in ctx.api_contract
