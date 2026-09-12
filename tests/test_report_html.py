"""Unit tests for BreakHeal HTML report generator."""

from pathlib import Path
from breakheal.report import AuditRecord, generate_html_report, generate_markdown_report


def test_generate_html_report(tmp_path: Path):
    records = [
        AuditRecord(
            target_file="pricing.py",
            symbol_name="calculate_discount",
            status="HEALED",
            vulnerability_details="ZeroDivisionError when quantity is 0",
            test_code="def test_zero(): calculate_discount(100, 0)",
            patch_text="<<<<<<< SEARCH\nreturn price / qty\n=======\nif qty <= 0: return 0.0\nreturn price / qty\n>>>>>>>",
            original_code="def calculate_discount(price, qty):\n    return price / qty",
            patched_code="def calculate_discount(price, qty):\n    if qty <= 0:\n        return 0.0\n    return price / qty",
            traceback_red="ZeroDivisionError: division by zero",
            traceback_green="1 passed in 0.02s",
            duration_seconds=1.42,
        ),
        AuditRecord(
            target_file="auth.py",
            symbol_name="verify_token",
            status="CLEAN",
            vulnerability_details="No boundary flaws found",
            test_code="",
            patch_text="",
            duration_seconds=0.55,
        ),
    ]

    out_html = tmp_path / "test_report.html"
    res = generate_html_report(records, output_path=out_html)

    assert res.exists()
    content = res.read_text(encoding="utf-8")
    assert "BreakHeal" in content
    assert "calculate_discount" in content
    assert "verify_token" in content
    assert "ZeroDivisionError" in content
    assert "HEALED" in content
    assert "CLEAN" in content
    assert "Original (Vulnerable)" in content
    assert "Healed (Deterministic Guard)" in content
    assert "timeline" in content
