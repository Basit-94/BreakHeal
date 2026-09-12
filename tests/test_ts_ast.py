"""Tests for Tree-sitter TypeScript/JavaScript AST, threat scoring, and API contract generator."""

import pytest
from pathlib import Path
from breakheal.ts_ast import (
    parse_ts_ast,
    generate_ts_api_contract,
    _HAS_TREE_SITTER,
)
from breakheal.ts_context import extract_ts_context


@pytest.mark.skipif(not _HAS_TREE_SITTER, reason="Tree-sitter TypeScript is not installed")
def test_parse_ts_ast_classes_and_threats(tmp_path):
    ts_code = """
export interface Config {
    timeoutMs: number;
}

export class OrderService {
    private secretKey: string;
    public active: boolean;

    constructor(secretKey: string) {
        this.secretKey = secretKey;
        this.active = true;
    }

    public calculateDiscountRate(total: number, count: number): number {
        return total / count;
    }

    public parsePayload(raw: string): any {
        return JSON.parse(raw);
    }
}

export const getFirstElement = (arr: string[]): string => {
    return arr[0];
};
"""
    ts_file = tmp_path / "order_service.ts"
    ts_file.write_text(ts_code, encoding="utf-8")

    parsed = parse_ts_ast(ts_code)
    assert len(parsed.types) == 1
    assert parsed.types[0].name == "Config"
    assert len(parsed.classes) == 1
    assert parsed.classes[0].name == "OrderService"

    # calculateDiscountRate has division: threat score >= 35
    div_fn = next(f for f in parsed.all_functions if f.name == "calculateDiscountRate")
    assert div_fn.threat_score >= 35

    # parsePayload has JSON.parse: threat score >= 25
    json_fn = next(f for f in parsed.all_functions if f.name == "parsePayload")
    assert json_fn.threat_score >= 25

    # getFirstElement has array indexing: threat score >= 20
    arr_fn = next(f for f in parsed.all_functions if f.name == "getFirstElement")
    assert arr_fn.threat_score >= 20

    # API contract verification
    contract = generate_ts_api_contract(parsed)
    assert "Config" in contract
    assert "OrderService" in contract
    assert "FORBIDDEN Private Fields (DO NOT ACCESS DIRECTLY): secretKey" in contract
    assert "calculateDiscountRate" in contract

    # extract_ts_context auto-threat ranking: should pick calculateDiscountRate
    ctx = extract_ts_context(ts_file)
    assert ctx.target_name == "OrderService.calculateDiscountRate"
    assert ctx.threat_score >= 35
    assert "STRICT API CONTRACT" in ctx.api_contract
