from breakheal.tui import PipelineCard, StepState, render_code_diff_panel
from rich.console import Console


def test_pipeline_card_initialization_and_steps():
    console = Console(record=True, width=80)
    card = PipelineCard(
        target_name="calculate_discounted_unit_price",
        file_path="demo_repo/pricing.py",
        language="Python",
        console=console,
    )

    assert len(card.steps) == 4
    assert card.steps[0]["id"] == "context"
    assert card.steps[1]["id"] == "red"

    # Transition steps
    card.update_step("context", StepState.SUCCESS, "Extracted lines 6-27")
    assert card.steps[0]["state"] == StepState.SUCCESS

    card.update_step("red", StepState.RUNNING, "Synthesizing test...")
    assert card.steps[1]["state"] == StepState.RUNNING

    card.update_step("red", StepState.SUCCESS, "Proved RED")
    card.update_step("patch", StepState.SUCCESS, "Patch applied")
    card.update_step("green", StepState.HEALED, "Proved GREEN")

    rendered = card.render()
    assert rendered is not None

    card.print_current()
    output = console.export_text()
    assert "calculate_discounted_unit_price" in output
    assert "PROVED" in output or "HEALED" in output


def test_render_code_diff_panel():
    orig = "def foo():\n    return 1\n"
    patch = "def foo():\n    return 2\n"
    panel = render_code_diff_panel(orig, patch, title="Test Diff", language="python")
    assert panel is not None
    assert panel.renderable is not None
    assert len(panel.renderable.columns) == 2
