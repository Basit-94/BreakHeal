from breakheal.report import AuditRecord
from breakheal.pr_bot import generate_github_suggestion_block, execute_pr_healing_branch


def test_generate_github_suggestion_block():
    suggestion = generate_github_suggestion_block(
        file_path="src/pricing.py",
        original_lines="return x / y",
        patched_lines="if y <= 0:\n    raise ValueError()\nreturn x / y",
        target_symbol="calculate_price",
    )
    assert "```suggestion" in suggestion
    assert "if y <= 0:" in suggestion
    assert "calculate_price" in suggestion


def test_execute_pr_healing_branch_dry_run():
    record = AuditRecord(
        target_file="src/pricing.py",
        symbol_name="calculate_price",
        status="HEALED",
        vulnerability_details="ZeroDivision",
        test_code="def test_zero(): pass",
        patch_text="patch",
        duration_seconds=1.2,
    )
    result = execute_pr_healing_branch([record], commit=False)
    assert result.success is True
    assert "breakheal/heal" in result.branch_name
    assert "src/pricing.py" in result.committed_files
    assert len(result.github_suggestions) == 1


def test_execute_pr_healing_branch_no_healed_records():
    record = AuditRecord(
        target_file="src/clean.py",
        symbol_name="clean_func",
        status="CLEAN",
        vulnerability_details="Clean",
        test_code="",
        patch_text="",
        duration_seconds=0.5,
    )
    result = execute_pr_healing_branch([record], commit=False)
    assert result.success is False
    assert result.branch_name is None
