"""Choreographed Zero-Risk Interactive Demo Mode for BreakHeal."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax

from breakheal.tui import (
    PipelineCard,
    StepState,
    render_brand_banner,
    render_code_diff_panel,
    render_success_badge,
)


def run_stage_demo(
    console: Optional[Console] = None,
    language_filter: str = "all",
    speed: str = "normal",
    live: bool = False,
) -> None:
    """Execute the choreographed interactive demo showcasing Python and Java self-repair."""
    c = console or Console(force_terminal=True, legacy_windows=False)

    delay = 1.2 if speed == "normal" else (0.4 if speed == "fast" else 0.0)

    # 1. Futuristic Brand Header & Architectural Overview
    c.print(render_brand_banner())
    time.sleep(delay * 0.8)

    c.print(
        Panel(
            "[bold bright_yellow]The Problem with Traditional AI Reviewers (CodeRabbit, Copilot):[/bold bright_yellow]\n"
            "• Linters & bots write speculative text comments that engineers ignore.\n"
            "• Generative LLMs hallucinate syntax or non-compiling unified diffs.\n\n"
            "[bold bright_green]The BreakHeal Deterministic Solution:[/bold bright_green]\n"
            "1. Synthesizes an adversarial test and [bold red]PROVES IT FAILS[/bold red] (Exit Code != 0).\n"
            "2. Synthesizes a deterministic patch and [bold green]PROVES IT PASSES[/bold green] (Exit Code == 0).\n"
            "3. Zero Hallucinations: If a patch fails compilation or breaks regressions, it is rejected!",
            title="[bold bright_cyan]❖ ARCHITECTURE & VERIFICATION SHOWCASE ❖[/bold bright_cyan]",
            border_style="bright_cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
    time.sleep(delay)

    run_py = language_filter in ("all", "python", "py")
    run_java = language_filter in ("all", "java")

    # =========================================================================
    # ACT 1: PYTHON ADVERSARIAL REPAIR
    # =========================================================================
    if run_py:
        c.print("\n[bold yellow]══════════════════════════════════════════════════════════════════════════[/bold yellow]")
        c.print("[bold yellow]ACT 1: Python Microservice Vulnerability — Division by Zero Flaw[/bold yellow]")
        c.print("[bold yellow]══════════════════════════════════════════════════════════════════════════[/bold yellow]\n")
        time.sleep(delay * 0.7)

        card = PipelineCard(
            target_name="calculate_discounted_unit_price",
            file_path="demo_repo/pricing.py",
            language="Python",
            console=c,
        )
        card.update_step("context", StepState.RUNNING, "Extracting AST function signatures & parameters...")
        card.print_current()
        time.sleep(delay)

        # Context complete
        card.update_step("context", StepState.SUCCESS, "Found 'calculate_discounted_unit_price(price, discount_percent, quantity=1)' [Lines 6-27]")
        card.update_step("red", StepState.RUNNING, "Synthesizing adversarial pytest targeting boundary condition (quantity=0)...")
        c.print("\n")
        card.print_current()
        time.sleep(delay)

        # Red Test established
        py_test_snippet = (
            "import pytest\n"
            "from demo_repo.pricing import calculate_discounted_unit_price\n\n"
            "def test_calculate_discounted_unit_price_zero_quantity():\n"
            "    # Adversarial probe: quantity=0 triggers unhandled division by zero\n"
            "    with pytest.raises(ValueError, match='quantity must be greater than 0'):\n"
            "        calculate_discounted_unit_price(100.0, 10.0, quantity=0)\n"
        )
        c.print(
            Panel(
                Syntax(py_test_snippet, "python", theme="monokai", line_numbers=True),
                title="[bold red]💥 Adversarial Test Synthesized (Targeting Zero-Quantity Boundary)[/bold red]",
                border_style="red",
            )
        )
        time.sleep(delay * 0.8)

        # Proving Red
        card.update_step("red", StepState.SUCCESS, "Pytest Exit Code 1 — ZeroDivisionError: float division by zero (RED PROVED)")
        card.update_step("patch", StepState.RUNNING, "Synthesizing SEARCH/REPLACE patch block...")
        c.print("\n")
        card.print_current()
        time.sleep(delay)

        # Patch synthesized
        py_patch_block = (
            "<<<<<<< SEARCH\n"
            "    if discount_percent < 0.0 or discount_percent > 100.0:\n"
            "        raise ValueError(\"discount_percent must be between 0.0 and 100.0\")\n"
            "=======\n"
            "    if discount_percent < 0.0 or discount_percent > 100.0:\n"
            "        raise ValueError(\"discount_percent must be between 0.0 and 100.0\")\n\n"
            "    if quantity <= 0:\n"
            "        raise ValueError(\"quantity must be greater than 0\")\n"
            ">>>>>>>"
        )
        c.print(
            Panel(
                Syntax(py_patch_block, "text", theme="monokai"),
                title="[bold cyan]🩹 Minimal SEARCH/REPLACE Patch Synthesized[/bold cyan]",
                border_style="cyan",
            )
        )
        time.sleep(delay * 0.8)

        # Green verified
        card.update_step("patch", StepState.SUCCESS, "Patch applied cleanly with 0 whitespace drift")
        card.update_step("green", StepState.RUNNING, "Executing subprocess pytest & regression guard suite...")
        c.print("\n")
        card.print_current()
        time.sleep(delay)

        card.update_step("green", StepState.HEALED, "Pytest Exit Code 0 — 1 passed in 0.05s | Full Suite: 15/15 passed (GREEN PROVED)")
        c.print("\n")
        card.print_current()
        time.sleep(delay * 0.5)

        # Side-by-side diff
        original_py = (
            "def calculate_discounted_unit_price(price, discount_percent, quantity=1):\n"
            "    if discount_percent < 0.0 or discount_percent > 100.0:\n"
            "        raise ValueError('discount_percent must be between 0.0 and 100.0')\n"
            "\n"
            "    discount_factor = 1.0 - (discount_percent / 100.0)\n"
            "    return (price * discount_factor) / quantity  # BUG: ZeroDivisionError"
        )
        patched_py = (
            "def calculate_discounted_unit_price(price, discount_percent, quantity=1):\n"
            "    if discount_percent < 0.0 or discount_percent > 100.0:\n"
            "        raise ValueError('discount_percent must be between 0.0 and 100.0')\n"
            "    if quantity <= 0:\n"
            "        raise ValueError('quantity must be greater than 0')\n"
            "\n"
            "    discount_factor = 1.0 - (discount_percent / 100.0)\n"
            "    return (price * discount_factor) / quantity  # HEALED!"
        )
        diff_table = render_code_diff_panel(original_py, patched_py, title="Python Patch Diff: pricing.py", language="python")
        c.print(diff_table)
        c.print(render_success_badge("calculate_discounted_unit_price", 0.05))
        time.sleep(delay)

    # =========================================================================
    # ACT 2: JAVA ENTERPRISE REPAIR (JUNIT 5 + MAVEN SUREFIRE)
    # =========================================================================
    if run_java:
        c.print("\n[bold yellow]══════════════════════════════════════════════════════════════════════════[/bold yellow]")
        c.print("[bold yellow]ACT 2: Enterprise Java Microservice — JUnit 5 & Maven Surefire Proof[/bold yellow]")
        c.print("[bold yellow]══════════════════════════════════════════════════════════════════════════[/bold yellow]\n")
        time.sleep(delay * 0.7)

        j_card = PipelineCard(
            target_name="DiscountCalculator.calculateDiscountedUnitPrice",
            file_path="demo_java/.../DiscountCalculator.java",
            language="Java",
            console=c,
        )
        j_card.update_step("context", StepState.RUNNING, "Discovering Maven pom.xml & bracket-matching Java AST...")
        j_card.print_current()
        time.sleep(delay)

        # Context complete
        j_card.update_step("context", StepState.SUCCESS, "Found Maven Root (com.breakheal.demo:demo-java:1.0.0)")
        j_card.update_step("red", StepState.RUNNING, "Synthesizing JUnit 5 Jupiter adversarial test class...")
        c.print("\n")
        j_card.print_current()
        time.sleep(delay)

        # Java Red Test snippet
        java_test_snippet = (
            "package com.breakheal.demo;\n\n"
            "import org.junit.jupiter.api.Test;\n"
            "import static org.junit.jupiter.api.Assertions.assertThrows;\n\n"
            "class BreakHealDiscountCalculatorTest {\n"
            "    @Test\n"
            "    void testCalculateDiscountedUnitPriceZeroQuantity() {\n"
            "        // Adversarial probe: Zero quantity must throw IllegalArgumentException\n"
            "        assertThrows(IllegalArgumentException.class, () -> {\n"
            "            DiscountCalculator.calculateDiscountedUnitPrice(100.0, 10.0, 0);\n"
            "        });\n"
            "    }\n"
            "}\n"
        )
        c.print(
            Panel(
                Syntax(java_test_snippet, "java", theme="monokai", line_numbers=True),
                title="[bold red]💥 Adversarial JUnit 5 Test Synthesized[/bold red]",
                border_style="red",
            )
        )
        time.sleep(delay * 0.8)

        # Proving Red via Maven
        j_card.update_step("red", StepState.SUCCESS, "Maven Surefire Exit Code 1 — AssertionFailedError: Expected IllegalArgumentException (RED PROVED)")
        j_card.update_step("patch", StepState.RUNNING, "Synthesizing Java SEARCH/REPLACE patch block...")
        c.print("\n")
        j_card.print_current()
        time.sleep(delay)

        # Java Patch synthesized
        java_patch_block = (
            "<<<<<<< SEARCH\n"
            "        if (discountPercent < 0.0 || discountPercent > 100.0) {\n"
            "            throw new IllegalArgumentException(\"discountPercent must be between 0.0 and 100.0\");\n"
            "        }\n"
            "=======\n"
            "        if (discountPercent < 0.0 || discountPercent > 100.0) {\n"
            "            throw new IllegalArgumentException(\"discountPercent must be between 0.0 and 100.0\");\n"
            "        }\n\n"
            "        if (quantity <= 0) {\n"
            "            throw new IllegalArgumentException(\"quantity must be greater than 0\");\n"
            "        }\n"
            ">>>>>>>"
        )
        c.print(
            Panel(
                Syntax(java_patch_block, "text", theme="monokai"),
                title="[bold cyan]🩹 Java SEARCH/REPLACE Patch Synthesized[/bold cyan]",
                border_style="cyan",
            )
        )
        time.sleep(delay * 0.8)

        # Green verified via Maven
        j_card.update_step("patch", StepState.SUCCESS, "Java source patched cleanly")
        j_card.update_step("green", StepState.RUNNING, "Invoking 'mvn test -Dtest=BreakHealDiscountCalculatorTest'...")
        c.print("\n")
        j_card.print_current()
        time.sleep(delay)

        j_card.update_step("green", StepState.HEALED, "Maven Surefire BUILD SUCCESS — Tests run: 3, Failures: 0, Errors: 0 in 2.73s (GREEN PROVED)")
        c.print("\n")
        j_card.print_current()
        time.sleep(delay * 0.5)

        # Side-by-side Java diff
        original_java = (
            "public static double calculateDiscountedUnitPrice(double price, double discountPercent, int quantity) {\n"
            "    if (discountPercent < 0.0 || discountPercent > 100.0) {\n"
            "        throw new IllegalArgumentException(\"discountPercent must be between 0.0 and 100.0\");\n"
            "    }\n"
            "    double discountFactor = 1.0 - (discountPercent / 100.0);\n"
            "    return (price * discountFactor) / quantity;  // BUG: Returns Infinity on quantity=0\n"
            "}"
        )
        patched_java = (
            "public static double calculateDiscountedUnitPrice(double price, double discountPercent, int quantity) {\n"
            "    if (discountPercent < 0.0 || discountPercent > 100.0) {\n"
            "        throw new IllegalArgumentException(\"discountPercent must be between 0.0 and 100.0\");\n"
            "    }\n"
            "    if (quantity <= 0) {\n"
            "        throw new IllegalArgumentException(\"quantity must be greater than 0\");\n"
            "    }\n"
            "    double discountFactor = 1.0 - (discountPercent / 100.0);\n"
            "    return (price * discountFactor) / quantity;  // HEALED!\n"
            "}"
        )
        j_diff_table = render_code_diff_panel(original_java, patched_java, title="Java Patch Diff: DiscountCalculator.java", language="java")
        c.print(j_diff_table)
        c.print(render_success_badge("DiscountCalculator.calculateDiscountedUnitPrice", 2.73))
        time.sleep(delay)

    # =========================================================================
    # SUMMARY & ARCHITECTURAL TAKEAWAY
    # =========================================================================
    summary_table = Table(
        title="[bold cyan]BreakHeal Autonomous Execution Summary[/bold cyan]",
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED,
        border_style="bright_cyan",
    )
    summary_table.add_column("Language", style="cyan")
    summary_table.add_column("Target Symbol", style="white")
    summary_table.add_column("Flaw Detected", style="yellow")
    summary_table.add_column("Adversarial Test", style="bold red")
    summary_table.add_column("Repair Proof", style="bold green")
    summary_table.add_column("Status", style="bold")

    if run_py:
        summary_table.add_row(
            "Python 3.11+",
            "calculate_discounted_unit_price",
            "ZeroDivisionError on quantity <= 0",
            "pytest (Exit 1)",
            "pytest (Exit 0)",
            "[bold green]HEALED[/bold green]",
        )
    if run_java:
        summary_table.add_row(
            "Java 17/22",
            "DiscountCalculator.calculateDiscountedUnitPrice",
            "Missing IllegalArgumentException on quantity <= 0",
            "JUnit 5 (Exit 1)",
            "Maven Surefire (Exit 0)",
            "[bold green]HEALED[/bold green]",
        )

    c.print("\n")
    c.print(summary_table)

    c.print(
        Panel(
            "[bold green]Why BreakHeal Wins:[/bold green]\n"
            "✓ [bold]100% Deterministic:[/bold] We never accept code that wasn't proven green by native compilers.\n"
            "✓ [bold]Multi-Language Native:[/bold] True polyglot support across Python AST + Java Maven/JUnit 5.\n"
            "✓ [bold]Zero-Token Hallucination Protection:[/bold] SEARCH/REPLACE blocks only; no broken git diff headers.\n"
            "✓ [bold]Enterprise CI/CD Ready:[/bold] Drop-in GitHub Action workflow via `breakheal init-ci`.\n",
            title="[bold bright_green]❖ SUMMARY & KEY TAKEAWAYS ❖[/bold bright_green]",
            border_style="bright_green",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
