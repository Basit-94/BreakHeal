"""Terminal User Interface, futuristic styling, and interactive visual pipeline cards for BreakHeal."""

from __future__ import annotations

import time
from typing import Optional
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax


class StepState:
    WAITING = "waiting"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    HEALED = "healed"
    SKIPPED = "skipped"


def render_brand_banner() -> Panel:
    """Render a futuristic brand header for BreakHeal."""
    title_art = (
        "[bold cyan] ██████╗ ██████╗ ███████╗ █████╗ ██╗  ██╗██╗  ██╗███████╗ █████╗ ██╗     [/bold cyan]\n"
        "[bold cyan] ██╔══██╗██╔══██╗██╔════╝██╔══██╗██║ ██╔╝██║  ██║██╔════╝██╔══██╗██║     [/bold cyan]\n"
        "[bold bright_cyan] ██████╔╝██████╔╝█████╗  ███████║█████╔╝ ███████║█████╗  ███████║██║     [/bold bright_cyan]\n"
        "[bold bright_cyan] ██╔══██╗██╔══██╗██╔══╝  ██╔══██║██╔═██╗ ██╔══██║██╔══╝  ██╔══██║██║     [/bold bright_cyan]\n"
        "[bold white] ██████╔╝██║  ██║███████╗██║  ██║██║  ██╗██║  ██║███████╗██║  ██║███████╗ [/bold white]\n"
        "[bold dim] ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝ [/bold dim]"
    )

    tagline = (
        "[bold bright_yellow]⚡ DETERMINISTIC RED-TO-GREEN SOFTWARE REPAIR ENGINE[/bold bright_yellow]\n"
        "[dim white]Adversarial PR Edge-Case Breaker  •  Compiler-Backed Test Prover  •  Python & Java 17/22[/dim white]"
    )

    content = Table.grid(padding=(0, 0))
    content.add_column(justify="center", ratio=1)
    content.add_row(Text.from_markup(title_art))
    content.add_row(Text(""))
    content.add_row(Text.from_markup(tagline))

    return Panel(
        content,
        border_style="bright_cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )


class PipelineCard:
    """Renders a sleek, multi-phase execution card for Red-to-Green repair."""

    def __init__(
        self,
        target_name: str,
        file_path: str,
        language: str = "Python",
        console: Optional[Console] = None,
    ):
        self.target_name = target_name
        self.file_path = file_path
        self.language = language.upper()
        self.console = console or Console(force_terminal=True, legacy_windows=False)
        self.start_time = time.time()

        self.steps = [
            {
                "id": "context",
                "title": "Context Extraction & Threat Analysis",
                "state": StepState.RUNNING,
                "detail": "Parsing AST symbols, method scope & dependencies",
            },
            {
                "id": "red",
                "title": "Adversarial Test Synthesis (RED)",
                "state": StepState.WAITING,
                "detail": "Crafting isolated test probe to expose boundary failure",
            },
            {
                "id": "patch",
                "title": "Deterministic Patch Synthesis",
                "state": StepState.WAITING,
                "detail": "Generating exact SEARCH/REPLACE code patch",
            },
            {
                "id": "green",
                "title": "Green Proof & Regression Shield",
                "state": StepState.WAITING,
                "detail": "Executing native compiler/runner to verify fix & full suite",
            },
        ]

    def update_step(self, step_id: str, state: str, detail: str = "") -> None:
        for s in self.steps:
            if s["id"] == step_id:
                s["state"] = state
                if detail:
                    s["detail"] = detail
                break

    def render(self) -> Panel:
        elapsed = time.time() - self.start_time

        # Telemetry Metadata Bar
        meta_table = Table.grid(padding=(0, 2))
        meta_table.add_column(justify="left", ratio=1)
        meta_table.add_column(justify="right")

        left_meta = Text()
        left_meta.append(" 🎯 Target: ", style="bold dim")
        left_meta.append(f"{self.target_name} ", style="bold bright_white")
        left_meta.append(f"({self.file_path}) ", style="dim cyan")
        left_meta.append(f"[{self.language}]", style="bold magenta")

        right_meta = Text()
        right_meta.append(f"⏱️  {elapsed:.1f}s", style="bold yellow")

        meta_table.add_row(left_meta, right_meta)

        # Status Pill Styles
        status_pills = {
            StepState.WAITING: ("[dim white on grey23]  QUEUED  [/dim white on grey23]", "dim white"),
            StepState.RUNNING: ("[bold black on bright_yellow] ◐ RUNNING [/bold black on bright_yellow]", "bold bright_yellow"),
            StepState.SUCCESS: ("[bold white on dark_green] ✓ PROVED  [/bold white on dark_green]", "bold green"),
            StepState.FAILURE: ("[bold white on red] ✕ FAILED  [/bold white on red]", "bold red"),
            StepState.HEALED:  ("[bold black on bright_green] ★ HEALED  [/bold black on bright_green]", "bold bright_green"),
            StepState.SKIPPED: ("[dim white on grey27] - SKIPPED [/dim white on grey27]", "dim white"),
        }

        # Step Cards
        step_grid = Table.grid(padding=(0, 1))
        step_grid.add_column(justify="left", ratio=1)
        step_grid.add_row(meta_table)
        step_grid.add_row(Text("─" * 74, style="dim cyan"))

        for idx, s in enumerate(self.steps, 1):
            pill_markup, title_style = status_pills.get(
                s["state"], ("[white] UNKNOWN [/white]", "white")
            )

            row_table = Table.grid(padding=(0, 1))
            row_table.add_column(justify="left", ratio=1)
            row_table.add_column(justify="right")

            step_title = Text()
            step_title.append(f" [{idx:02d}] ", style="bold cyan")
            step_title.append(f"{s['title']} ", style=title_style)

            row_table.add_row(step_title, Text.from_markup(pill_markup))
            step_grid.add_row(row_table)

            if s["detail"]:
                detail_text = Text()
                detail_text.append(f"      └─ {s['detail']}", style="dim cyan")
                step_grid.add_row(detail_text)

            if idx < len(self.steps):
                step_grid.add_row(Text(""))

        border_style = "bright_cyan"
        if any(s["state"] == StepState.FAILURE for s in self.steps):
            border_style = "red"
        elif all(s["state"] in (StepState.SUCCESS, StepState.HEALED) for s in self.steps):
            border_style = "bright_green"

        return Panel(
            step_grid,
            title="[bold bright_cyan]❖ BREAKHEAL AUTONOMOUS PIPELINE ❖[/bold bright_cyan]",
            border_style=border_style,
            box=box.ROUNDED,
            padding=(1, 2),
        )

    def print_current(self) -> None:
        self.console.print(self.render())


def render_code_diff_panel(
    original: str,
    patched: str,
    title: str = "Self-Healing Patch Diff",
    language: str = "python",
) -> Panel:
    """Render side-by-side comparison with high-end terminal styling."""
    table = Table(
        show_header=True,
        header_style="bold bright_white",
        box=box.ROUNDED,
        border_style="bright_blue",
        expand=True,
    )
    table.add_column("🔴 Original Code (Vulnerable)", style="red", ratio=1)
    table.add_column("🟢 Patched Code (Deterministic Fix)", style="bright_green", ratio=1)

    orig_syntax = Syntax(original.strip(), language, theme="monokai", line_numbers=True)
    patch_syntax = Syntax(patched.strip(), language, theme="monokai", line_numbers=True)
    table.add_row(orig_syntax, patch_syntax)

    return Panel(
        table,
        title=f"[bold bright_cyan]⚡ {title} ⚡[/bold bright_cyan]",
        border_style="bright_cyan",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_success_badge(target_name: str, duration: float) -> Panel:
    """Render a celebratory completion badge with metrics."""
    text = (
        f"[bold bright_green]✓ 100% GREEN PROVEN BY COMPILER & TEST RUNNER[/bold bright_green]\n"
        f"[dim white]Symbol: [bold cyan]{target_name}[/bold cyan]  •  Repair Cycle: [bold yellow]{duration:.2f}s[/bold yellow]  •  Regressions: [bold green]0[/bold green][/dim white]\n\n"
        f"[dim]Audit evidence saved to [bold bright_white]BREAKHEAL_REPORT.md[/bold bright_white][/dim]"
    )
    return Panel(
        Text.from_markup(text, justify="center"),
        title="[bold bright_green]★ REPAIR COMPLETE ★[/bold bright_green]",
        border_style="bright_green",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def render_clean_badge(target_name: str, duration: float, tests_passed: int = 3) -> Panel:
    """Render an audit badge indicating the target resisted all adversarial attacks."""
    text = (
        f"[bold bright_cyan]🛡️ 100% ROBUST & CLEAN — NO VULNERABILITIES DETECTED[/bold bright_cyan]\n"
        f"[dim white]Symbol: [bold cyan]{target_name}[/bold cyan]  •  Adversarial Tests Passed: [bold green]{tests_passed}[/bold green]  •  Scan Duration: [bold yellow]{duration:.2f}s[/bold yellow][/dim white]\n\n"
        f"[dim]Audit evidence saved to [bold bright_white]BREAKHEAL_REPORT.md[/bold bright_white][/dim]"
    )
    return Panel(
        Text.from_markup(text, justify="center"),
        title="[bold bright_cyan]★ AUDIT VERIFIED CLEAN ★[/bold bright_cyan]",
        border_style="bright_cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )

