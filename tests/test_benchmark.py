"""Unit tests for BreakHeal benchmark suite."""

from breakheal.benchmark import BENCHMARK_SUITE, run_benchmark_suite
from rich.console import Console


def test_benchmark_suite_structure():
    assert len(BENCHMARK_SUITE) == 25
    languages = {c.language for c in BENCHMARK_SUITE}
    assert languages == {"python", "java", "typescript", "go", "rust"}
    
    for case in BENCHMARK_SUITE:
        assert case.id
        assert case.symbol_name
        assert case.vulnerable_snippet
        assert case.adversarial_test
        assert case.repaired_snippet


def test_run_benchmark_suite_python():
    c = Console(record=True)
    summary = run_benchmark_suite(language_filter="python", console=c)
    assert summary["total_cases"] == 5
    assert summary["passed"] == 5
    assert summary["red_proven_rate"] == 100.0
    assert summary["green_proven_rate"] == 100.0
    assert summary["regression_rate"] == 0.0


def test_run_benchmark_suite_all():
    c = Console(record=True)
    summary = run_benchmark_suite(language_filter="all", console=c)
    assert summary["total_cases"] == 25
    assert summary["passed"] == 25
