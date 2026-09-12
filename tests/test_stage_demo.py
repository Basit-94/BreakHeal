import re
from typer.testing import CliRunner
from breakheal.cli import app
from breakheal.demo import run_stage_demo
from rich.console import Console

runner = CliRunner()


def test_stage_demo_execution_instant():
    console = Console(record=True, width=100)
    run_stage_demo(console=console, language_filter="all", speed="instant")
    output = console.export_text()

    assert "DETERMINISTIC RED-TO-GREEN SOFTWARE REPAIR ENGINE" in output
    assert "ACT 1: Python" in output
    assert "ACT 2: Enterprise Java" in output
    assert "HEALED" in output
    assert "Why BreakHeal Wins" in output


def test_cli_demo_command():
    result = runner.invoke(app, ["demo", "--speed", "instant", "--lang", "python"])
    assert result.exit_code == 0
    clean_stdout = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", result.stdout)
    assert "ACT 1: Python" in clean_stdout
    assert "HEALED" in clean_stdout
