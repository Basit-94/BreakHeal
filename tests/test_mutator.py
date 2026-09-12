from pathlib import Path
from breakheal.mutator import (
    discover_mutations,
    apply_mutation,
    run_mutation_testing,
    format_surviving_mutants_report,
    MutationResult,
    Mutation,
)

SAMPLE_CODE = """
def check_discount(discount_percent: float, quantity: int) -> float:
    if discount_percent < 0.0 or discount_percent > 100.0:
        raise ValueError("Invalid discount")
    return (100.0 - discount_percent) / quantity
"""


def test_discover_mutations():
    muts = discover_mutations(SAMPLE_CODE)
    assert len(muts) >= 2
    types = [m.mutation_type for m in muts]
    assert "boundary_comparison" in types
    assert "guard_removal" in types


def test_apply_mutation():
    muts = discover_mutations(SAMPLE_CODE)
    cmp_mut = next(m for m in muts if m.mutation_type == "boundary_comparison")
    mutated = apply_mutation(SAMPLE_CODE, cmp_mut)
    assert mutated != SAMPLE_CODE
    # Either <= or >= should now be present
    assert "<=" in mutated or ">=" in mutated


def test_format_surviving_mutants_report():
    dummy_mut = Mutation(
        id="test_1",
        line_number=3,
        original_code="<",
        mutated_code="<=",
        mutation_type="boundary_comparison",
        description="Swapped < to <=",
    )
    results = [
        MutationResult(mutation=dummy_mut, survived=True, test_output=""),
        MutationResult(mutation=dummy_mut, survived=False, test_output=""),
    ]
    report = format_surviving_mutants_report(results)
    assert "1 SURVIVING MUTANT(S)" in report
    assert "Line 3" in report
