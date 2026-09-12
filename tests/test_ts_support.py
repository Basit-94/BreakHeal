from pathlib import Path
from breakheal.ts_context import (
    extract_ts_context,
    scan_directory_for_ts_functions,
    extract_ts_imports,
)
from breakheal.ts_runner import run_node_test


def test_extract_ts_imports():
    sample = (
        "import test from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "const path = require('path');\n"
    )
    imports = extract_ts_imports(sample)
    assert len(imports) == 3


def test_extract_ts_context():
    file_path = Path("demo_ts/pricing.js")
    ctx = extract_ts_context(file_path, target_name="calculateDiscountedUnitPrice")
    assert ctx.target_name == "calculateDiscountedUnitPrice"
    assert "discountFactor" in ctx.source_code
    assert ctx.start_line >= 1
    assert ctx.is_exported is True


def test_scan_directory_for_ts():
    dir_path = Path("demo_ts")
    functions = scan_directory_for_ts_functions(dir_path)
    names = [f.target_name for f in functions]
    assert "calculateDiscountedUnitPrice" in names


def test_run_node_test_runner():
    test_file = Path("demo_ts/test_pricing.test.js")
    result = run_node_test(test_file)
    assert result.passed is True
    assert result.exit_code == 0
    assert "calculateDiscountedUnitPrice" in result.stdout


def test_extract_ts_class_method():
    file_path = Path("demo_ts/bill.ts")
    ctx = extract_ts_context(file_path, target_name="OrderPricingEngine.processOrder")
    assert ctx.target_name == "OrderPricingEngine.processOrder"
    assert ctx.class_name == "OrderPricingEngine"
    assert "processOrder" in ctx.source_code
    assert ctx.start_line == 35
    assert ctx.end_line == 94


def test_ts_side_by_side_diff():
    from breakheal.cli import display_side_by_side_diff
    original = "function calc(x: number): number { return x * 10; }"
    patched = "function calc(x: number): number { if (x < 0) return 0; return x * 10; }"
    display_side_by_side_diff(original, patched, title="Test TS Diff", language="typescript")

