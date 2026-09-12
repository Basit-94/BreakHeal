"""Unit tests for BreakHeal GitHub PR comment generator."""

from breakheal.pr_bot import format_github_pr_markdown_comment, generate_github_suggestion_block
from breakheal.report import AuditRecord


def test_format_github_pr_comment():
    records = [
        AuditRecord(
            target_file="pricing.py",
            symbol_name="calculate_discount",
            status="HEALED",
            vulnerability_details="ZeroDivisionError when quantity is 0",
            test_code="def test_zero(): calculate_discount(100, 0)",
            patch_text="<<<<<<< SEARCH\nreturn price / qty\n=======\nif qty <= 0: return 0.0\nreturn price / qty\n>>>>>>>",
        ),
        AuditRecord(
            target_file="auth.py",
            symbol_name="verify_token",
            status="CLEAN",
            vulnerability_details="Robust token validation",
            test_code="",
            patch_text="",
        ),
    ]

    comment = format_github_pr_markdown_comment(records, pr_number=42, branch_name="breakheal/heal-discount")
    assert "BreakHeal Autonomous Code Sentinel" in comment
    assert "calculate_discount" in comment
    assert "verify_token" in comment
    assert "HEALED" in comment
    assert "CLEAN" in comment
    assert "View Proven Failing Test (Red Reproducer)" in comment
    assert "breakheal/heal-discount" in comment


def test_generate_github_suggestion_block():
    block = generate_github_suggestion_block(
        file_path="src/calc.py",
        original_lines="return a / b",
        patched_lines="if b == 0: return 0\nreturn a / b",
        target_symbol="calc",
    )
    assert "```suggestion" in block
    assert "if b == 0: return 0" in block
