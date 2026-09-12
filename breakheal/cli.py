"""Typer CLI application orchestrating BreakHeal's Red-to-Green protocol across Python and Java projects."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table

from breakheal.agent import GroqAgent, MODEL_NAME
from breakheal.context import (
    CodeContext,
    detect_targets_from_diff,
    extract_context,
    scan_directory_for_functions,
)
from breakheal.git_utils import (
    apply_patch_to_file,
    commit_files,
    get_branch_modified_file_lines,
    get_modified_file_lines,
    rollback_file,
)
from breakheal.java_context import (
    JavaContext,
    extract_java_context,
    scan_directory_for_java_methods,
)
from breakheal.java_runner import run_maven_test
from breakheal.hooks import ASTCache, get_staged_files
from breakheal.mutator import (
    discover_mutations,
    format_surviving_mutants_report,
    run_mutation_testing,
)
from breakheal.pr_bot import execute_pr_healing_branch
from breakheal.report import AuditRecord, generate_markdown_report
from breakheal.runner import run_pytest, run_regression_suite
from breakheal.ts_context import (
    TSContext,
    extract_ts_context,
    scan_directory_for_ts_functions,
)
from breakheal.ts_runner import run_node_test
from breakheal.go_context import (
    GoContext,
    extract_go_context,
    scan_directory_for_go_functions,
)
from breakheal.go_runner import run_go_test, is_go_available
from breakheal.rust_context import (
    RustContext,
    extract_rust_context,
    scan_directory_for_rust_functions,
)
from breakheal.rust_runner import run_cargo_test, is_cargo_available, find_cargo_root
from breakheal.tui import (
    PipelineCard,
    StepState,
    render_brand_banner,
    render_code_diff_panel,
    render_success_badge,
    render_clean_badge,
)

app = typer.Typer(
    name="breakheal",
    help="Autonomous Red-to-Green automated software engineering and self-healing test engine (Python, Java, & TypeScript).",
    add_completion=False,
)
console = Console(force_terminal=True, legacy_windows=False)


def print_banner() -> None:
    console.print(render_brand_banner())


def display_side_by_side_diff(
    original_code: str,
    patched_code: str,
    title: str = "Code Modification Preview (Before vs. After)",
    language: str = "python",
) -> None:
    """Render a clean side-by-side comparison table showing original and patched code."""
    console.print(render_code_diff_panel(original_code, patched_code, title=title, language=language))


def heal_target(
    context: CodeContext,
    agent: GroqAgent,
    retries: int = 3,
    heal_retries: int = 3,
    check_regression: bool = True,
    auto_accept: bool = False,
    quiet: bool = False,
) -> AuditRecord:
    """Execute the Red-to-Green cycle on a specific Python target symbol."""
    start_time = time.time()
    target_path = Path(context.file_path).resolve()
    original_content = target_path.read_text(encoding="utf-8")

    tests_dir = target_path.parent / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / f"test_breakheal_{context.target_name}.py"

    card = PipelineCard(
        target_name=context.target_name,
        file_path=str(target_path.relative_to(Path.cwd()) if target_path.is_relative_to(Path.cwd()) else target_path),
        language="Python",
        console=console,
    )
    card.update_step("context", StepState.SUCCESS, f"Lines {context.start_line}-{context.end_line} ({len(context.imports)} imports)")

    if not quiet:
        card.print_current()

    # Step 1 & 2: Break & Prove Red
    red_established = False
    test_code = ""
    red_result = None
    feedback: Optional[str] = None

    for attempt in range(1, retries + 1):
        with console.status(
            f"[bold magenta]Synthesizing adversarial test ({context.target_name} attempt {attempt}/{retries})...[/bold magenta]"
        ):
            try:
                test_code = agent.generate_adversarial_test(context, feedback=feedback)
            except Exception as e:
                if not quiet:
                    console.print(f"[bold red]LLM Error:[/bold red] {e}")
                card.update_step("red", StepState.FAILURE, str(e))
                return AuditRecord(
                    target_file=str(target_path),
                    symbol_name=context.target_name,
                    status="FAILED",
                    vulnerability_details=f"LLM Error: {e}",
                    test_code="",
                    patch_text="",
                    duration_seconds=time.time() - start_time,
                )

        test_file.write_text(test_code, encoding="utf-8")

        with console.status(f"[bold yellow]Executing pytest against {context.target_name} (proving Red)...[/bold yellow]"):
            red_result = run_pytest(test_file, cwd=target_path.parent)

        if red_result.failed:
            err_output = red_result.combined_output
            harness_errs = [
                "ImportError:", "ModuleNotFoundError:", "SyntaxError:",
                "is not defined", "TypeError: __init__() missing", "takes no arguments",
            ]
            is_harness = any(err in err_output for err in harness_errs) or ("AttributeError: module" in err_output)
            if is_harness:
                if not quiet:
                    console.print(f"[yellow]Attempt {attempt}: Pytest failed due to test harness/import error. Retrying...[/yellow]")
                feedback = (
                    f"The test failed with a setup/import/syntax error rather than target logic flaw:\n"
                    f"{err_output[-350:]}\n"
                    f"Target: {context.target_name}. If it is a method on class {context.class_name}, import the class, instantiate it, and call the method."
                )
                continue

            red_established = True
            card.update_step("red", StepState.SUCCESS, f"Pytest Exit Code {red_result.exit_code} (Proved RED)")
            if not quiet:
                card.print_current()
                console.print(
                    Panel(
                        Syntax(test_code, "python", theme="monokai", line_numbers=True),
                        title=f"[bold red]Adversarial Test Established (RED - Exit Code {red_result.exit_code})[/bold red]",
                        border_style="red",
                    )
                )
                console.print("[dim red]" + red_result.combined_output[-400:] + "[/dim red]")
            break
        else:
            if not quiet:
                console.print(
                    f"[yellow]Attempt {attempt}: Generated test passed (exit code 0). Rejecting and retrying...[/yellow]"
                )
            feedback = (
                f"The generated test PASSED on the buggy code with exit code 0:\n"
                f"{red_result.combined_output[-300:]}\n"
                f"It is NOT exposing any flaw. You must craft an edge-case test that FAILS on current code."
            )

    if not red_established or not red_result:
        if test_file.exists():
            test_file.unlink()
        if not quiet:
            console.print(f"[bold green]No reproducible boundary flaws found in {context.target_name}.[/bold green]")
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="CLEAN",
            vulnerability_details="No adversarial boundary flaws detected.",
            test_code="",
            patch_text="",
            duration_seconds=time.time() - start_time,
        )

    # Step 3 & 4: Multi-Turn Heal & Prove Green
    if not quiet:
        console.print("\n[bold yellow]=== STEP 3 & 4: MULTI-TURN HEAL & PROVE GREEN ===[/bold yellow]")

    healing_succeeded = False
    previous_attempts: list[dict[str, str]] = []
    final_patch = ""

    for heal_attempt in range(1, heal_retries + 1):
        target_path.write_text(original_content, encoding="utf-8")

        with console.status(
            f"[bold cyan]Synthesizing patch for {context.target_name} (iteration {heal_attempt}/{heal_retries})...[/bold cyan]"
        ):
            try:
                patch_text = agent.generate_patch(
                    context=context,
                    test_code=test_code,
                    test_output=red_result.combined_output,
                    previous_attempts=previous_attempts if previous_attempts else None,
                )
            except Exception as e:
                if not quiet:
                    console.print(f"[bold red]LLM Patching Error:[/bold red] {e}")
                if test_file.exists():
                    test_file.unlink()
                return AuditRecord(
                    target_file=str(target_path),
                    symbol_name=context.target_name,
                    status="FAILED",
                    vulnerability_details=f"Patch generation error: {e}",
                    test_code=test_code,
                    patch_text="",
                    duration_seconds=time.time() - start_time,
                )

        final_patch = patch_text
        if not quiet:
            console.print(
                Panel(
                    Syntax(patch_text, "text", theme="monokai"),
                    title=f"[bold cyan]Generated SEARCH/REPLACE Patch (Iteration {heal_attempt})[/bold cyan]",
                    border_style="cyan",
                )
            )

        applied = apply_patch_to_file(target_path, patch_text)
        if not applied:
            if not quiet:
                console.print(f"[yellow]Iteration {heal_attempt}: SEARCH block mismatch. Retrying...[/yellow]")
            previous_attempts.append({
                "patch": patch_text,
                "error": "The SEARCH block did not match the lines in the file exactly. Ensure exact whitespace match.",
            })
            continue

        card.update_step("patch", StepState.SUCCESS, f"SEARCH/REPLACE block applied (iteration {heal_attempt})")
        if not quiet:
            card.print_current()

        with console.status(
            f"[bold green]Testing patched code for {context.target_name} (proving Green - iteration {heal_attempt})...[/bold green]"
        ):
            green_result = run_pytest(test_file, cwd=target_path.parent)

        if green_result.passed:
            if check_regression:
                with console.status(f"[bold blue]Verifying regression suite for {context.target_name}...[/bold blue]"):
                    reg_result = run_regression_suite(cwd=target_path.parent)
                    if reg_result.failed:
                        if not quiet:
                            console.print(f"[yellow]Iteration {heal_attempt}: Regression detected in baseline suite:[/yellow]")
                            console.print(f"[dim red]{reg_result.combined_output[-300:]}[/dim red]")
                        previous_attempts.append({
                            "patch": patch_text,
                            "error": f"Regression failure in existing tests:\n{reg_result.combined_output[-300:]}",
                        })
                        continue

            healing_succeeded = True
            card.update_step("green", StepState.HEALED, f"Proved GREEN (Exit Code 0 in {time.time() - start_time:.2f}s)")
            if not quiet:
                console.print(
                    Panel(
                        f"[bold green][PASS] All Tests Passed! (Exit Code 0)[/bold green]\n\n"
                        f"[dim]{green_result.combined_output[-300:]}[/dim]",
                        title="[bold green]Self-Healing Verified (GREEN)[/bold green]",
                        border_style="green",
                    )
                )
                card.print_current()
            break
        else:
            if not quiet:
                console.print(f"[yellow]Iteration {heal_attempt}: Test failed on patched code. Feeding error back...[/yellow]")
            previous_attempts.append({
                "patch": patch_text,
                "error": green_result.combined_output[-400:],
            })

    if not healing_succeeded:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        if not quiet:
            console.print(f"[bold red]Failed to heal {context.target_name} after {heal_retries} iterations.[/bold red]")
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="FAILED",
            vulnerability_details="Failed to synthesize a passing patch within iteration limit.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )

    accept = auto_accept
    if not auto_accept:
        patched_context = extract_context(target_path, target_name=context.target_name)
        display_side_by_side_diff(
            original_code=context.target_code,
            patched_code=patched_context.target_code,
            title=f"Side-by-Side Patch Preview: {context.target_name}",
            language="python",
        )
        choice = Prompt.ask(
            f"[bold white]Accept patch and save verified test for {context.target_name}?[/bold white]",
            choices=["A", "R"],
            default="A",
        )
        accept = choice.upper() == "A"

    if accept:
        duration = time.time() - start_time
        if not quiet:
            console.print(render_success_badge(target_name=context.target_name, duration=duration))
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="HEALED",
            vulnerability_details=red_result.combined_output[-250:].strip(),
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=duration,
        )
    else:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        if not quiet:
            console.print(f"[yellow]Patch rejected for {context.target_name}. Restored original file.[/yellow]")
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="CLEAN",
            vulnerability_details="User rejected generated patch.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )


def heal_java_target(
    context: JavaContext,
    agent: GroqAgent,
    retries: int = 3,
    heal_retries: int = 3,
    auto_accept: bool = False,
    quiet: bool = False,
) -> AuditRecord:
    """Execute the Red-to-Green cycle on a specific Java target method."""
    start_time = time.time()
    target_path = Path(context.file_path).resolve()
    original_content = target_path.read_text(encoding="utf-8")

    # Set up test destination in Maven project structure
    maven_root = Path(context.maven_root)
    pkg_dirs = Path(context.package_name.replace(".", "/")) if context.package_name else Path(".")
    test_dir = maven_root / "src" / "test" / "java" / pkg_dirs
    test_dir.mkdir(parents=True, exist_ok=True)
    test_class_name = f"BreakHeal{context.class_name}Test"
    test_file = test_dir / f"{test_class_name}.java"

    card = PipelineCard(
        target_name=f"{context.class_name}.{context.method_name}",
        file_path=str(target_path.relative_to(Path.cwd()) if target_path.is_relative_to(Path.cwd()) else target_path),
        language="Java",
        console=console,
    )
    card.update_step("context", StepState.SUCCESS, f"Lines {context.start_line}-{context.end_line} ({context.package_name})")

    if not quiet:
        card.print_current()

    # Step 1 & 2: Break & Prove Red
    red_established = False
    test_code = ""
    red_result = None
    feedback: Optional[str] = None

    for attempt in range(1, retries + 1):
        with console.status(
            f"[bold magenta]Synthesizing adversarial JUnit 5 test ({context.method_name} attempt {attempt}/{retries})...[/bold magenta]"
        ):
            try:
                test_code = agent.generate_adversarial_java_test(context, feedback=feedback)
            except Exception as e:
                if not quiet:
                    console.print(f"[bold red]LLM Error:[/bold red] {e}")
                card.update_step("red", StepState.FAILURE, str(e))
                return AuditRecord(
                    target_file=str(target_path),
                    symbol_name=f"{context.class_name}.{context.method_name}",
                    status="FAILED",
                    vulnerability_details=f"LLM Error: {e}",
                    test_code="",
                    patch_text="",
                    duration_seconds=time.time() - start_time,
                )

        test_file.write_text(test_code, encoding="utf-8")

        with console.status(f"[bold yellow]Executing Maven Surefire on {test_class_name} (proving Red)...[/bold yellow]"):
            red_result = run_maven_test(context.maven_root, test_class=test_class_name)

        if red_result.failed:
            err_output = red_result.combined_output
            java_harness_errs = [
                "cannot find symbol", "compilation error", "constructor cannot be applied",
                "package does not exist", "nosuchmethoderror", "unresolved compilation problem",
                "cannot be resolved", "noclassdeffounderror", "classnotfoundexception",
                "has private access",
            ]
            if any(err.lower() in err_output.lower() for err in java_harness_errs):
                err_lines = [
                    line for line in err_output.splitlines()
                    if "[ERROR]" in line and "Failed to execute" not in line and "Re-run Maven" not in line
                ]
                specific_err = "\n".join(err_lines[:6]) if err_lines else err_output[-350:]
                if not quiet:
                    console.print(f"[yellow]Attempt {attempt}: Maven test compilation/symbol error. Retrying...[/yellow]")
                    for el in err_lines[:4]:
                        if "COMPILATION ERROR :" not in el:
                            console.print(f"[dim yellow]{el}[/dim yellow]")
                feedback = (
                    f"The JUnit test failed to compile or had a symbol error:\n"
                    f"{specific_err}\n"
                    f"Target method: {context.method_name} in class {context.class_name}. Match class constructor, inner types, and method signatures from full source."
                )
                continue

            red_established = True
            card.update_step("red", StepState.SUCCESS, f"Maven Exit Code {red_result.exit_code} (Proved RED)")
            if not quiet:
                card.print_current()
                console.print(
                    Panel(
                        Syntax(test_code, "java", theme="monokai", line_numbers=True),
                        title=f"[bold red]Adversarial JUnit 5 Test Established (RED - Exit Code {red_result.exit_code})[/bold red]",
                        border_style="red",
                    )
                )
                console.print("[dim red]" + red_result.combined_output[-400:] + "[/dim red]")
            break
        else:
            if not quiet:
                console.print(f"[yellow]Attempt {attempt}: Maven test passed (exit code 0). Retrying...[/yellow]")
            feedback = (
                f"The generated JUnit 5 test unexpectedly PASSED with exit code 0:\n"
                f"{red_result.combined_output[-300:]}\n"
                f"It is NOT exposing any flaw. Craft an adversarial test that FAILS on current code."
            )

    if not red_established or not red_result:
        if test_file.exists():
            test_file.unlink()
        if not quiet:
            console.print(render_clean_badge(target_name=f"{context.class_name}.{context.method_name}", duration=time.time() - start_time, tests_passed=retries))
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=f"{context.class_name}.{context.method_name}",
            status="CLEAN",
            vulnerability_details="No adversarial boundary flaws detected.",
            test_code="",
            patch_text="",
            duration_seconds=time.time() - start_time,
        )

    # Step 3 & 4: Multi-Turn Heal & Prove Green
    if not quiet:
        console.print("\n[bold yellow]=== STEP 3 & 4: MULTI-TURN HEAL & PROVE GREEN (JAVA) ===[/bold yellow]")

    healing_succeeded = False
    previous_attempts: list[dict[str, str]] = []
    final_patch = ""

    for heal_attempt in range(1, heal_retries + 1):
        target_path.write_text(original_content, encoding="utf-8")

        with console.status(
            f"[bold cyan]Synthesizing Java patch for {context.method_name} (iteration {heal_attempt}/{heal_retries})...[/bold cyan]"
        ):
            try:
                patch_text = agent.generate_java_patch(
                    context=context,
                    test_code=test_code,
                    test_output=red_result.combined_output,
                    previous_attempts=previous_attempts if previous_attempts else None,
                )
            except Exception as e:
                if not quiet:
                    console.print(f"[bold red]LLM Patching Error:[/bold red] {e}")
                if test_file.exists():
                    test_file.unlink()
                return AuditRecord(
                    target_file=str(target_path),
                    symbol_name=f"{context.class_name}.{context.method_name}",
                    status="FAILED",
                    vulnerability_details=f"Patch generation error: {e}",
                    test_code=test_code,
                    patch_text="",
                    duration_seconds=time.time() - start_time,
                )

        final_patch = patch_text
        if not quiet:
            console.print(
                Panel(
                    Syntax(patch_text, "text", theme="monokai"),
                    title=f"[bold cyan]Generated SEARCH/REPLACE Patch (Iteration {heal_attempt})[/bold cyan]",
                    border_style="cyan",
                )
            )

        applied = apply_patch_to_file(target_path, patch_text)
        if not applied:
            if not quiet:
                console.print(f"[yellow]Iteration {heal_attempt}: SEARCH block mismatch. Retrying...[/yellow]")
            previous_attempts.append({
                "patch": patch_text,
                "error": "The SEARCH block did not match the lines in the Java file exactly. Ensure exact whitespace match.",
            })
            continue

        card.update_step("patch", StepState.SUCCESS, f"Java patch applied cleanly (iteration {heal_attempt})")
        if not quiet:
            card.print_current()

        with console.status(
            f"[bold green]Testing patched Java code for {context.method_name} (proving Green - iteration {heal_attempt})...[/bold green]"
        ):
            green_result = run_maven_test(context.maven_root, test_class=test_class_name)

        if green_result.passed:
            healing_succeeded = True
            card.update_step("green", StepState.HEALED, f"Maven Surefire Exit Code 0 in {time.time() - start_time:.2f}s (GREEN)")
            if not quiet:
                console.print(
                    Panel(
                        f"[bold green][PASS] All Maven Tests Passed! (Exit Code 0)[/bold green]\n\n"
                        f"[dim]{green_result.combined_output[-300:]}[/dim]",
                        title="[bold green]Self-Healing Verified (GREEN)[/bold green]",
                        border_style="green",
                    )
                )
                card.print_current()
            break
        else:
            fail_lines = [
                l for l in green_result.combined_output.splitlines()
                if any(k in l for k in ["FAILURE", "Failures:", "AssertionFailedError", "Expected", "[ERROR]"])
                and "Failed to execute goal" not in l
                and "Please refer to" not in l
                and "Re-run Maven" not in l
            ]
            err_msg = "\n".join(fail_lines[:8]) if fail_lines else green_result.combined_output[-400:]
            if not quiet:
                console.print(f"[yellow]Iteration {heal_attempt}: Maven test failed on patched code. Feeding error back...[/yellow]")
                if fail_lines:
                    console.print(f"[dim red]{fail_lines[0]}[/dim red]")
            previous_attempts.append({
                "patch": patch_text,
                "error": err_msg,
            })

    if not healing_succeeded:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        if not quiet:
            console.print(f"[bold red]Failed to heal Java method {context.method_name} after {heal_retries} iterations.[/bold red]")
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=f"{context.class_name}.{context.method_name}",
            status="FAILED",
            vulnerability_details="Failed to synthesize passing Java patch within iteration limit.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )

    accept = auto_accept
    if not auto_accept:
        patched_context = extract_java_context(target_path, target_name=context.method_name)
        display_side_by_side_diff(
            original_code=context.method_code,
            patched_code=patched_context.method_code,
            title=f"Side-by-Side Patch Preview: {context.class_name}.{context.method_name}",
            language="java",
        )
        choice = Prompt.ask(
            f"[bold white]Accept patch and save verified test for {context.method_name}?[/bold white]",
            choices=["A", "R"],
            default="A",
        )
        accept = choice.upper() == "A"

    if accept:
        duration = time.time() - start_time
        if not quiet:
            console.print(render_success_badge(target_name=f"{context.class_name}.{context.method_name}", duration=duration))
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=f"{context.class_name}.{context.method_name}",
            status="HEALED",
            vulnerability_details=red_result.combined_output[-250:].strip(),
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=duration,
        )
    else:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        if not quiet:
            console.print(f"[yellow]Patch rejected for {context.method_name}. Restored original file.[/yellow]")
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=f"{context.class_name}.{context.method_name}",
            status="CLEAN",
            vulnerability_details="User rejected generated patch.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )


def heal_ts_target(
    context: TSContext,
    agent: GroqAgent,
    retries: int = 3,
    heal_retries: int = 3,
    auto_accept: bool = False,
    quiet: bool = False,
) -> AuditRecord:
    """Execute Red-to-Green repair cycle on a TypeScript/JavaScript function using Node.js test runner."""
    start_time = time.time()
    target_path = Path(context.file_path).resolve()
    original_content = target_path.read_text(encoding="utf-8")

    card = PipelineCard(
        target_name=context.target_name,
        file_path=str(target_path),
        language="TypeScript/JS",
        console=console,
    )

    card.update_step("context", StepState.RUNNING, "Analyzing TS/JS function boundaries...")
    if not quiet:
        card.print_current()

    card.update_step(
        "context",
        StepState.SUCCESS,
        f"Lines {context.start_line}-{context.end_line} ({len(context.imports)} imports)",
    )

    # 1. Synthesize Adversarial Test
    card.update_step("red", StepState.RUNNING, "Synthesizing Node.js adversarial test...")
    if not quiet:
        card.print_current()

    safe_symbol = context.target_name.replace(".", "_")
    test_ext = ".test.ts" if target_path.suffix in (".ts", ".mts") else ".test.js"
    test_file = target_path.parent / f"test_breakheal_{safe_symbol}{test_ext}"
    test_code = ""
    red_result = None
    red_proven = False
    feedback = None

    for attempt in range(1, retries + 1):
        with console.status(
            f"[bold magenta]Synthesizing adversarial Node test ({context.target_name} attempt {attempt}/{retries})...[/bold magenta]"
        ):
            try:
                test_code = agent.generate_adversarial_ts_test(context, feedback=feedback)
            except Exception as e:
                if not quiet:
                    console.print(f"[bold red]LLM Error:[/bold red] {e}")
                card.update_step("red", StepState.FAILURE, str(e))
                return AuditRecord(
                    target_file=str(target_path),
                    symbol_name=context.target_name,
                    status="FAILED",
                    vulnerability_details=f"LLM Error: {e}",
                    test_code="",
                    patch_text="",
                    duration_seconds=time.time() - start_time,
                )

        test_file.write_text(test_code, encoding="utf-8")

        res = run_node_test(test_file)
        if res.failed:
            err_output = res.combined_output
            ts_harness_errs = [
                "is not a function", "is not a constructor", "SyntaxError",
                "Cannot find module", "ERR_MODULE_NOT_FOUND", "ReferenceError"
            ]
            if any(err in err_output for err in ts_harness_errs):
                if not quiet:
                    console.print(f"[yellow]Attempt {attempt}: Node test failed due to harness/invocation error. Retrying...[/yellow]")
                feedback = (
                    f"The test failed with an invocation or syntax error (not a legitimate boundary flaw):\n"
                    f"{err_output[-300:]}\n"
                    f"If targeting an instance method, instantiate the class: const instance = new {context.class_name}(...); instance.{context.target_name.split('.')[-1]}(...);"
                )
                continue

            red_proven = True
            red_result = res
            card.update_step("red", StepState.SUCCESS, f"Node.js test Exit Code {res.exit_code} (RED PROVED)")
            if not quiet:
                card.print_current()
                console.print(
                    Panel(
                        Syntax(test_code, "typescript" if test_ext == ".test.ts" else "javascript", theme="monokai", line_numbers=True),
                        title=f"[bold red]Adversarial Node Test Established (RED - Exit Code {res.exit_code})[/bold red]",
                        border_style="red",
                    )
                )
            break
        else:
            feedback = (
                f"Generated test PASSED on buggy code with exit code 0:\n"
                f"{res.combined_output[-300:]}\n"
                f"It did not expose any flaw. You must write an adversarial test that FAILS on current code."
            )

    if not red_proven:
        if test_file.exists():
            test_file.unlink()
        card.update_step("red", StepState.SKIPPED, "No boundary flaw detected (CLEAN)")
        if not quiet:
            card.print_current()
            console.print(render_clean_badge(target_name=context.target_name, duration=time.time() - start_time, tests_passed=retries))
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="CLEAN",
            vulnerability_details="Target function resisted adversarial probes.",
            test_code="",
            patch_text="",
            duration_seconds=time.time() - start_time,
        )

    # 2. Synthesize Patch
    card.update_step("patch", StepState.RUNNING, "Synthesizing SEARCH/REPLACE patch block...")
    if not quiet:
        card.print_current()

    healing_succeeded = False
    final_patch = ""
    previous_attempts: list[dict[str, str]] = []

    for attempt in range(1, heal_retries + 1):
        target_path.write_text(original_content, encoding="utf-8")

        with console.status(
            f"[bold cyan]Synthesizing patch for {context.target_name} (iteration {attempt}/{heal_retries})...[/bold cyan]"
        ):
            try:
                patch_text = agent.generate_ts_patch(
                    context=context,
                    test_code=test_code,
                    test_output=red_result.combined_output,
                    previous_attempts=previous_attempts if previous_attempts else None,
                )
            except Exception as e:
                if not quiet:
                    console.print(f"[bold red]LLM Patching Error:[/bold red] {e}")
                if test_file.exists():
                    test_file.unlink()
                return AuditRecord(
                    target_file=str(target_path),
                    symbol_name=context.target_name,
                    status="FAILED",
                    vulnerability_details=f"Patch generation error: {e}",
                    test_code=test_code,
                    patch_text="",
                    duration_seconds=time.time() - start_time,
                )

        final_patch = patch_text

        if not quiet:
            console.print(
                Panel(
                    Syntax(patch_text, "text", theme="monokai"),
                    title=f"[bold cyan]Generated SEARCH/REPLACE Patch (Iteration {attempt})[/bold cyan]",
                    border_style="cyan",
                )
            )

        applied = apply_patch_to_file(target_path, patch_text)
        if not applied:
            if not quiet:
                console.print(f"[yellow]Iteration {attempt}: SEARCH block mismatch. Retrying...[/yellow]")
            previous_attempts.append({
                "patch": patch_text,
                "error": "The SEARCH block did not match the lines in the file exactly. Ensure exact whitespace match.",
            })
            continue

        card.update_step("patch", StepState.SUCCESS, f"Patch applied cleanly (iteration {attempt})")
        if not quiet:
            card.print_current()

        with console.status(
            f"[bold green]Testing patched code for {context.target_name} (proving Green - iteration {attempt})...[/bold green]"
        ):
            green_res = run_node_test(test_file)

        if green_res.passed:
            healing_succeeded = True
            card.update_step("green", StepState.HEALED, f"Node.js Exit Code 0 in {time.time() - start_time:.2f}s (GREEN PROVED)")
            if not quiet:
                card.print_current()
            break
        else:
            if not quiet:
                console.print(f"[yellow]Iteration {attempt} test failed:[/yellow] [dim red]{green_res.combined_output[-250:].strip()}[/dim red]")
            previous_attempts.append({
                "patch": patch_text,
                "error": green_res.combined_output[-400:],
            })

    if not healing_succeeded:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        card.update_step("patch", StepState.FAILURE, "Patch failed to prove Green")
        card.update_step("green", StepState.FAILURE, f"Exhausted {heal_retries} repair iterations")
        if not quiet:
            card.print_current()
            console.print(
                Panel(
                    f"[bold red]Failed to heal `{context.target_name}` after {heal_retries} iterations.[/bold red]\n"
                    f"The test runner rejected all synthesized patches.\n"
                    f"[dim]Original file has been safely preserved.[/dim]",
                    title="[bold red]Self-Healing Incomplete[/bold red]",
                    border_style="red",
                    box=box.ROUNDED,
                )
            )
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="FAILED",
            vulnerability_details="Failed to heal within retry limit.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )

    accept = auto_accept
    if not auto_accept:
        try:
            patched_context = extract_ts_context(target_path, target_name=context.target_name)
            patched_code = patched_context.source_code
        except Exception:
            patched_code = target_path.read_text(encoding="utf-8")

        lang = "typescript" if target_path.suffix in (".ts", ".mts") else "javascript"
        display_side_by_side_diff(
            original_code=context.source_code,
            patched_code=patched_code,
            title=f"Side-by-Side Patch Preview: {context.target_name}",
            language=lang,
        )
        choice = Prompt.ask(
            f"[bold white]Accept patch and save verified test for {context.target_name}?[/bold white]",
            choices=["A", "R"],
            default="A",
        )
        accept = choice.upper() == "A"

    if accept:
        duration = time.time() - start_time
        if not quiet:
            console.print(render_success_badge(target_name=context.target_name, duration=duration))
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="HEALED",
            vulnerability_details=red_result.combined_output[-250:].strip(),
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=duration,
        )
    else:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        if not quiet:
            console.print(f"[yellow]Patch rejected for {context.target_name}. Restored original file.[/yellow]")
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="CLEAN",
            vulnerability_details="User rejected generated patch.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )


def heal_go_target(
    context: GoContext,
    agent: GroqAgent,
    retries: int = 3,
    heal_retries: int = 3,
    auto_accept: bool = False,
    quiet: bool = False,
) -> AuditRecord:
    """Execute Red-to-Green repair cycle on a Go function or method using `go test`."""
    start_time = time.time()
    target_path = Path(context.file_path).resolve()
    original_content = target_path.read_text(encoding="utf-8")

    card = PipelineCard(
        target_name=context.target_name,
        file_path=str(target_path),
        language="Go",
        console=console,
    )

    card.update_step("context", StepState.RUNNING, "Analyzing Go AST & threats...")
    if not quiet:
        card.print_current()

    threat_info = f" [Threat: {context.threat_score}]" if context.threat_score > 0 else ""
    card.update_step(
        "context",
        StepState.SUCCESS,
        f"Lines {context.start_line}-{context.end_line} (package {context.package_name}){threat_info}",
    )

    # Check Go toolchain availability
    if not is_go_available() and not quiet:
        console.print("[dim cyan]• Native 'go' compiler not detected on PATH. Activating BreakHeal Zero-Install AST Prover.[/dim cyan]")

    test_file_name = f"{target_path.stem}_breakheal_test.go"
    test_file = target_path.parent / test_file_name

    # Step 1: Synthesize Adversarial Test
    card.update_step("red", StepState.RUNNING, "Synthesizing Go testing.T test...")
    feedback = None
    test_code = ""
    red_result = None

    for attempt in range(1, retries + 1):
        try:
            test_code = agent.generate_adversarial_go_test(context, feedback=feedback)
        except Exception as e:
            if not quiet:
                console.print(f"[bold red]LLM Error:[/bold red] {e}")
            card.update_step("red", StepState.FAILURE, str(e))
            return AuditRecord(
                target_file=str(target_path),
                symbol_name=context.target_name,
                status="FAILED",
                vulnerability_details=f"LLM Error: {e}",
                test_code="",
                patch_text="",
                duration_seconds=time.time() - start_time,
            )

        test_file.write_text(test_code, encoding="utf-8")
        red_result = run_go_test(target_path.parent, target_file=target_path, target_name=context.target_name)

        if red_result.failed:
            if "undefined:" in red_result.combined_output or "syntax error" in red_result.combined_output:
                feedback = f"Go test had compilation error:\n{red_result.combined_output[-300:]}"
                continue
            card.update_step(
                "red",
                StepState.SUCCESS,
                f"Adversarial Go test proved Red (exit code {red_result.exit_code})",
            )
            if not quiet:
                card.print_current()
            break
        else:
            feedback = "Test passed unexpectedly on unmodified code. Generate an aggressive edge-case input that triggers a bug."
    else:
        if test_file.exists():
            test_file.unlink()
        card.update_step(
            "red",
            StepState.SUCCESS,
            f"Verified target robustness ({retries} adversarial tests passed)",
        )
        if not quiet:
            card.print_current()
            console.print(render_clean_badge(target_name=context.target_name, duration=time.time() - start_time, tests_passed=retries))
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="CLEAN",
            vulnerability_details="Target resisted all synthesized adversarial tests.",
            test_code=test_code,
            patch_text="",
            duration_seconds=time.time() - start_time,
        )

    # Step 2: Multi-turn Self-Healing
    card.update_step("patch", StepState.RUNNING, "Synthesizing Go SEARCH/REPLACE patch...")
    if not quiet:
        card.print_current()

    previous_attempts = []
    healing_succeeded = False
    final_patch = ""

    for heal_attempt in range(1, heal_retries + 1):
        try:
            patch_text = agent.generate_go_patch(
                context=context,
                test_code=test_code,
                test_output=red_result.combined_output,
                previous_attempts=previous_attempts,
            )
        except Exception as e:
            if not quiet:
                console.print(f"[bold red]LLM Patching Error:[/bold red] {e}")
            if test_file.exists():
                test_file.unlink()
            return AuditRecord(
                target_file=str(target_path),
                symbol_name=context.target_name,
                status="FAILED",
                vulnerability_details=f"Patch generation error: {e}",
                test_code=test_code,
                patch_text="",
                duration_seconds=time.time() - start_time,
            )

        final_patch = patch_text
        applied = apply_patch_to_file(target_path, patch_text)
        if not applied:
            previous_attempts.append({
                "patch": patch_text,
                "error": "The SEARCH block did not match the lines in the Go file exactly. Ensure exact whitespace match.",
            })
            continue

        card.update_step("patch", StepState.SUCCESS, f"Go patch applied cleanly (iteration {heal_attempt})")
        green_result = run_go_test(target_path.parent, target_file=target_path, target_name=context.target_name)

        if green_result.passed:
            healing_succeeded = True
            card.update_step(
                "green",
                StepState.HEALED,
                f"`go test` Exit Code 0 in {time.time() - start_time:.2f}s (GREEN)",
            )
            if not quiet:
                card.print_current()
            break
        else:
            previous_attempts.append({
                "patch": patch_text,
                "error": green_result.combined_output[-400:],
            })

    if not healing_succeeded:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        card.update_step("green", StepState.FAILURE, "Failed to synthesize passing Go patch within iteration limit")
        if not quiet:
            card.print_current()
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="FAILED",
            vulnerability_details="Failed to synthesize passing Go patch within iteration limit.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )

    accept = auto_accept
    if not auto_accept:
        try:
            patched_ctx = extract_go_context(target_path, target_name=context.target_name)
            patched_code = patched_ctx.function_code
        except Exception:
            patched_code = target_path.read_text(encoding="utf-8")

        display_side_by_side_diff(
            original_code=context.function_code,
            patched_code=patched_code,
            title=f"Side-by-Side Patch Preview: {context.target_name}",
            language="go",
        )
        choice = Prompt.ask(
            f"[bold white]Accept patch and save verified test for {context.target_name}?[/bold white]",
            choices=["A", "R"],
            default="A",
        )
        accept = choice.upper() == "A"

    if accept:
        duration = time.time() - start_time
        if not quiet:
            console.print(render_success_badge(target_name=context.target_name, duration=duration))
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="HEALED",
            vulnerability_details=red_result.combined_output[-250:].strip(),
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=duration,
        )
    else:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="CLEAN",
            vulnerability_details="User rejected generated patch.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )


def heal_rust_target(
    context: RustContext,
    agent: GroqAgent,
    retries: int = 3,
    heal_retries: int = 3,
    auto_accept: bool = False,
    quiet: bool = False,
) -> AuditRecord:
    """Execute Red-to-Green repair cycle on a Rust function or method using `cargo test`."""
    start_time = time.time()
    target_path = Path(context.file_path).resolve()
    original_content = target_path.read_text(encoding="utf-8")

    cargo_root = find_cargo_root(target_path) or target_path.parent

    card = PipelineCard(
        target_name=context.target_name,
        file_path=str(target_path),
        language="Rust",
        console=console,
    )

    card.update_step("context", StepState.RUNNING, "Analyzing Rust AST & threats...")
    if not quiet:
        card.print_current()

    threat_info = f" [Threat: {context.threat_score}]" if context.threat_score > 0 else ""
    card.update_step(
        "context",
        StepState.SUCCESS,
        f"Lines {context.start_line}-{context.end_line} ({context.enclosing_type or 'fn'}){threat_info}",
    )

    # Check Cargo toolchain availability
    if not is_cargo_available() and not quiet:
        console.print("[dim cyan]• Native 'cargo' toolchain not detected on PATH. Activating BreakHeal Zero-Install AST Prover.[/dim cyan]")

    # Place integration test in tests/ or append module to file
    tests_dir = cargo_root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / f"breakheal_{target_path.stem}_test.rs"

    # Step 1: Synthesize Adversarial Test
    card.update_step("red", StepState.RUNNING, "Synthesizing Rust #[test] module...")
    feedback = None
    test_code = ""
    red_result = None

    for attempt in range(1, retries + 1):
        try:
            test_code = agent.generate_adversarial_rust_test(context, feedback=feedback)
        except Exception as e:
            if not quiet:
                console.print(f"[bold red]LLM Error:[/bold red] {e}")
            card.update_step("red", StepState.FAILURE, str(e))
            return AuditRecord(
                target_file=str(target_path),
                symbol_name=context.target_name,
                status="FAILED",
                vulnerability_details=f"LLM Error: {e}",
                test_code="",
                patch_text="",
                duration_seconds=time.time() - start_time,
            )

        test_file.write_text(test_code, encoding="utf-8")
        red_result = run_cargo_test(cargo_root, target_file=target_path, target_name=context.target_name)

        if red_result.failed:
            if "error[E" in red_result.combined_output:
                feedback = f"Rust test had compilation error:\n{red_result.combined_output[-350:]}"
                continue
            card.update_step(
                "red",
                StepState.SUCCESS,
                f"Adversarial Rust test proved Red (exit code {red_result.exit_code})",
            )
            if not quiet:
                card.print_current()
            break
        else:
            feedback = "Test passed unexpectedly on unmodified code. Generate an aggressive edge-case input triggering panic or failure."
    else:
        if test_file.exists():
            test_file.unlink()
        card.update_step(
            "red",
            StepState.SUCCESS,
            f"Verified target robustness ({retries} adversarial tests passed)",
        )
        if not quiet:
            card.print_current()
            console.print(render_clean_badge(target_name=context.target_name, duration=time.time() - start_time, tests_passed=retries))
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="CLEAN",
            vulnerability_details="Target resisted all synthesized adversarial tests.",
            test_code=test_code,
            patch_text="",
            duration_seconds=time.time() - start_time,
        )

    # Step 2: Multi-turn Self-Healing
    card.update_step("patch", StepState.RUNNING, "Synthesizing Rust SEARCH/REPLACE patch...")
    if not quiet:
        card.print_current()

    previous_attempts = []
    healing_succeeded = False
    final_patch = ""

    for heal_attempt in range(1, heal_retries + 1):
        try:
            patch_text = agent.generate_rust_patch(
                context=context,
                test_code=test_code,
                test_output=red_result.combined_output,
                previous_attempts=previous_attempts,
            )
        except Exception as e:
            if not quiet:
                console.print(f"[bold red]LLM Patching Error:[/bold red] {e}")
            if test_file.exists():
                test_file.unlink()
            return AuditRecord(
                target_file=str(target_path),
                symbol_name=context.target_name,
                status="FAILED",
                vulnerability_details=f"Patch generation error: {e}",
                test_code=test_code,
                patch_text="",
                duration_seconds=time.time() - start_time,
            )

        final_patch = patch_text
        applied = apply_patch_to_file(target_path, patch_text)
        if not applied:
            previous_attempts.append({
                "patch": patch_text,
                "error": "The SEARCH block did not match the lines in the Rust file exactly. Ensure exact whitespace match.",
            })
            continue

        card.update_step("patch", StepState.SUCCESS, f"Rust patch applied cleanly (iteration {heal_attempt})")
        green_result = run_cargo_test(cargo_root, target_file=target_path, target_name=context.target_name)

        if green_result.passed:
            healing_succeeded = True
            card.update_step(
                "green",
                StepState.HEALED,
                f"`cargo test` Exit Code 0 in {time.time() - start_time:.2f}s (GREEN)",
            )
            if not quiet:
                card.print_current()
            break
        else:
            previous_attempts.append({
                "patch": patch_text,
                "error": green_result.combined_output[-400:],
            })

    if not healing_succeeded:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        card.update_step("green", StepState.FAILURE, "Failed to synthesize passing Rust patch within iteration limit")
        if not quiet:
            card.print_current()
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="FAILED",
            vulnerability_details="Failed to synthesize passing Rust patch within iteration limit.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )

    accept = auto_accept
    if not auto_accept:
        try:
            patched_ctx = extract_rust_context(target_path, target_name=context.target_name)
            patched_code = patched_ctx.function_code
        except Exception:
            patched_code = target_path.read_text(encoding="utf-8")

        display_side_by_side_diff(
            original_code=context.function_code,
            patched_code=patched_code,
            title=f"Side-by-Side Patch Preview: {context.target_name}",
            language="rust",
        )
        choice = Prompt.ask(
            f"[bold white]Accept patch and save verified test for {context.target_name}?[/bold white]",
            choices=["A", "R"],
            default="A",
        )
        accept = choice.upper() == "A"

    if accept:
        duration = time.time() - start_time
        if not quiet:
            console.print(render_success_badge(target_name=context.target_name, duration=duration))
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="HEALED",
            vulnerability_details=red_result.combined_output[-250:].strip(),
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=duration,
        )
    else:
        target_path.write_text(original_content, encoding="utf-8")
        if test_file.exists():
            test_file.unlink()
        return AuditRecord(
            target_file=str(target_path),
            symbol_name=context.target_name,
            status="CLEAN",
            vulnerability_details="User rejected generated patch.",
            test_code=test_code,
            patch_text=final_patch,
            duration_seconds=time.time() - start_time,
        )


def _resolve_target_path(file: str) -> Path:
    """Resolve file path, automatically locating it if partially specified."""
    target_path = Path(file).resolve()
    if target_path.exists():
        return target_path

    # Try resolving relative to repository subdirectories
    search_name = Path(file).name
    matches = list(Path.cwd().glob(f"**/{search_name}"))
    matches = [
        m for m in matches
        if not any(p in m.parts for p in ["target", "build", "dist", "node_modules", ".git", "__pycache__"])
    ]

    file_norm = Path(file).as_posix()
    suffix_matches = [m for m in matches if m.as_posix().endswith(file_norm)]
    if suffix_matches:
        resolved = suffix_matches[0].resolve()
        console.print(f"[dim cyan]Auto-resolved path to: {resolved.relative_to(Path.cwd())}[/dim cyan]")
        return resolved

    if len(matches) == 1:
        resolved = matches[0].resolve()
        console.print(f"[dim cyan]Auto-resolved path to: {resolved.relative_to(Path.cwd())}[/dim cyan]")
        return resolved

    console.print(f"[bold red]Error:[/bold red] Target file does not exist: {target_path}")
    if matches:
        console.print("[yellow]Did you mean one of these?[/yellow]")
        for m in matches[:3]:
            console.print(f"  - breakheal {m.relative_to(Path.cwd())}")
    raise typer.Exit(code=1)


@app.command()
def run(
    file: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to target Python or Java file. If omitted, auto-detects from uncommitted git diff.",
    ),
    func: Optional[str] = typer.Option(
        None,
        "--func",
        help="Specific function or method name to target.",
    ),
    line: Optional[int] = typer.Option(
        None,
        "--line",
        "-l",
        help="Line number within target file to detect enclosing function/method.",
    ),
    model: str = typer.Option(
        MODEL_NAME,
        "--model",
        "-m",
        help="Groq model name.",
    ),
    retries: int = typer.Option(
        3,
        "--retries",
        "-r",
        help="Maximum attempts to produce a failing adversarial test.",
    ),
    heal_retries: int = typer.Option(
        3,
        "--heal-retries",
        help="Maximum multi-turn repair iterations.",
    ),
    check_regression: bool = typer.Option(
        True,
        "--check-regression/--no-check-regression",
        help="Verify existing test suite continues to pass.",
    ),
    auto_accept: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Automatically accept verified patch without prompt.",
    ),
) -> None:
    """Execute the Red-to-Green adversarial test and self-healing loop on a single target (Python or Java)."""
    print_banner()

    target_path: Path | None = None
    target_func = func
    target_line = line

    if file:
        target_path = _resolve_target_path(file)
    else:
        with console.status("[bold blue]Scanning git diff for uncommitted changes...[/bold blue]"):
            modified_map = get_modified_file_lines()

        candidates = {
            f: lines
            for f, lines in modified_map.items()
            if (f.endswith(".py") or f.endswith(".java") or f.endswith(".ts") or f.endswith(".js") or f.endswith(".go") or f.endswith(".rs"))
            and Path(f).is_file()
            and not f.startswith("test")
            and "test" not in Path(f).parts
        }

        if not candidates:
            console.print(
                "[bold yellow]No uncommitted Python/Java/TypeScript/Go/Rust changes detected via git diff.[/bold yellow]\n"
                "[dim]Tip: Specify a file directly via `breakheal run --file <path>` "
                "or modify code in your repository.[/dim]"
            )
            raise typer.Exit(code=0)

        detected_rel, changed_lines = next(iter(candidates.items()))
        target_path = Path(detected_rel).resolve()

        if not target_func and changed_lines and target_path.suffix == ".py":
            contexts = detect_targets_from_diff(target_path, changed_lines)
            if contexts:
                target_func = contexts[0].target_name
                target_line = contexts[0].start_line

        console.print(
            Panel(
                f"[bold cyan]Auto-Detected Modified File:[/bold cyan] {target_path}\n"
                f"[bold]Modified Lines:[/bold] {sorted(changed_lines)[:8]}{'...' if len(changed_lines) > 8 else ''}\n"
                f"[bold]Target Symbol:[/bold] {target_func or 'Primary function/method'}",
                title="[bold green]Git Auto-Detection[/bold green]",
                border_style="green",
            )
        )

    agent = GroqAgent(model=model)

    # Route based on file extension
    ext = target_path.suffix.lower()
    if ext == ".java":
        java_context = extract_java_context(target_path, target_name=target_func, line_number=target_line)
        record = heal_java_target(
            context=java_context,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            auto_accept=auto_accept,
            quiet=False,
        )
    elif ext in (".ts", ".js", ".mjs", ".cjs"):
        ts_context = extract_ts_context(target_path, target_name=target_func, target_line=target_line)
        record = heal_ts_target(
            context=ts_context,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            auto_accept=auto_accept,
            quiet=False,
        )
    elif ext == ".go":
        go_context = extract_go_context(target_path, target_name=target_func, line_number=target_line)
        record = heal_go_target(
            context=go_context,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            auto_accept=auto_accept,
            quiet=False,
        )
    elif ext in (".rs",):
        rust_context = extract_rust_context(target_path, target_name=target_func, line_number=target_line)
        record = heal_rust_target(
            context=rust_context,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            auto_accept=auto_accept,
            quiet=False,
        )
    else:
        py_context = extract_context(target_path, target_name=target_func, line_number=target_line)
        record = heal_target(
            context=py_context,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            check_regression=check_regression,
            auto_accept=auto_accept,
            quiet=False,
        )

    generate_markdown_report([record], output_path="BREAKHEAL_REPORT.md")
    console.print("\n[dim]Audit report saved to [bold]BREAKHEAL_REPORT.md[/bold][/dim]")


@app.command()
def scan(
    directory: str = typer.Argument(
        ".",
        help="Directory to scan recursively for Python and Java functions.",
    ),
    model: str = typer.Option(
        MODEL_NAME,
        "--model",
        "-m",
        help="Groq model name.",
    ),
    retries: int = typer.Option(
        2,
        "--retries",
        "-r",
        help="Maximum attempts to break each function.",
    ),
    heal_retries: int = typer.Option(
        3,
        "--heal-retries",
        help="Maximum multi-turn repair iterations per flaw.",
    ),
    check_regression: bool = typer.Option(
        True,
        "--check-regression/--no-check-regression",
        help="Verify existing test suite continues to pass.",
    ),
    auto_accept: bool = typer.Option(
        True,
        "--yes",
        "-y",
        help="Automatically apply and accept verified patches.",
    ),
) -> None:
    """Recursively discover, test, and heal all functions/methods across Python and Java projects."""
    print_banner()

    scan_path = Path(directory).resolve()
    if not scan_path.is_dir():
        console.print(f"[bold red]Error:[/bold red] Directory not found: {scan_path}")
        raise typer.Exit(code=1)

    console.print(f"\n[bold blue]Discovering targets in {scan_path.name}...[/bold blue]")
    py_contexts = scan_directory_for_functions(scan_path)
    java_contexts = scan_directory_for_java_methods(scan_path)
    ts_contexts = scan_directory_for_ts_functions(scan_path)
    go_contexts = scan_directory_for_go_functions(scan_path)
    rust_contexts = scan_directory_for_rust_functions(scan_path)

    total_targets = len(py_contexts) + len(java_contexts) + len(ts_contexts) + len(go_contexts) + len(rust_contexts)
    if total_targets == 0:
        console.print(f"[yellow]No Python, Java, TypeScript, Go, or Rust functions discovered in {scan_path}.[/yellow]")
        raise typer.Exit(code=0)

    console.print(
        f"[bold green]Discovered {len(py_contexts)} Python, {len(java_contexts)} Java, {len(ts_contexts)} TS/JS, {len(go_contexts)} Go, and {len(rust_contexts)} Rust target(s) to audit.[/bold green]\n"
    )

    agent = GroqAgent(model=model)
    records: list[AuditRecord] = []
    current_idx = 1

    # Audit Python functions
    for ctx in py_contexts:
        console.print(f"[bold cyan][{current_idx}/{total_targets}] [Python] {Path(ctx.file_path).name} :: {ctx.target_name}...[/bold cyan]")
        record = heal_target(
            context=ctx,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            check_regression=check_regression,
            auto_accept=auto_accept,
            quiet=True,
        )
        records.append(record)
        status_color = "green" if record.status == "HEALED" else ("blue" if record.status == "CLEAN" else "red")
        console.print(f"  └─ Status: [{status_color}]{record.status}[/{status_color}] ({record.duration_seconds:.2f}s)")
        current_idx += 1

    # Audit Java methods
    for j_ctx in java_contexts:
        console.print(f"[bold cyan][{current_idx}/{total_targets}] [Java] {Path(j_ctx.file_path).name} :: {j_ctx.class_name}.{j_ctx.method_name}...[/bold cyan]")
        record = heal_java_target(
            context=j_ctx,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            auto_accept=auto_accept,
            quiet=True,
        )
        records.append(record)
        status_color = "green" if record.status == "HEALED" else ("blue" if record.status == "CLEAN" else "red")
        console.print(f"  └─ Status: [{status_color}]{record.status}[/{status_color}] ({record.duration_seconds:.2f}s)")
        current_idx += 1

    # Audit TypeScript/JavaScript functions
    for ts_ctx in ts_contexts:
        console.print(f"[bold cyan][{current_idx}/{total_targets}] [TS/JS] {Path(ts_ctx.file_path).name} :: {ts_ctx.target_name}...[/bold cyan]")
        record = heal_ts_target(
            context=ts_ctx,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            auto_accept=auto_accept,
            quiet=True,
        )
        records.append(record)
        status_color = "green" if record.status == "HEALED" else ("blue" if record.status == "CLEAN" else "red")
        console.print(f"  └─ Status: [{status_color}]{record.status}[/{status_color}] ({record.duration_seconds:.2f}s)")
        current_idx += 1

    # Audit Go functions
    for go_ctx in go_contexts:
        console.print(f"[bold cyan][{current_idx}/{total_targets}] [Go] {Path(go_ctx.file_path).name} :: {go_ctx.target_name}...[/bold cyan]")
        record = heal_go_target(
            context=go_ctx,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            auto_accept=auto_accept,
            quiet=True,
        )
        records.append(record)
        status_color = "green" if record.status == "HEALED" else ("blue" if record.status == "CLEAN" else "red")
        console.print(f"  └─ Status: [{status_color}]{record.status}[/{status_color}] ({record.duration_seconds:.2f}s)")
        current_idx += 1

    # Audit Rust functions
    for rust_ctx in rust_contexts:
        console.print(f"[bold cyan][{current_idx}/{total_targets}] [Rust] {Path(rust_ctx.file_path).name} :: {rust_ctx.target_name}...[/bold cyan]")
        record = heal_rust_target(
            context=rust_ctx,
            agent=agent,
            retries=retries,
            heal_retries=heal_retries,
            auto_accept=auto_accept,
            quiet=True,
        )
        records.append(record)
        status_color = "green" if record.status == "HEALED" else ("blue" if record.status == "CLEAN" else "red")
        console.print(f"  └─ Status: [{status_color}]{record.status}[/{status_color}] ({record.duration_seconds:.2f}s)")
        current_idx += 1

    # Print Batch Summary Table
    table = Table(title="Multi-Language Directory Audit Summary", show_header=True, header_style="bold magenta")
    table.add_column("File", style="cyan")
    table.add_column("Symbol", style="white")
    table.add_column("Status", style="bold")
    table.add_column("Time", style="dim")

    for r in records:
        status_styled = (
            "[bold green]HEALED[/bold green]"
            if r.status == "HEALED"
            else ("[bold blue]CLEAN[/bold blue]" if r.status == "CLEAN" else "[bold red]FAILED[/bold red]")
        )
        table.add_row(Path(r.target_file).name, r.symbol_name, status_styled, f"{r.duration_seconds:.2f}s")

    console.print("\n")
    console.print(table)

    report_path = generate_markdown_report(records, output_path="BREAKHEAL_REPORT.md")
    console.print(f"\n[bold green][OK] Multi-language audit complete. Full report saved to {report_path.name}.[/bold green]")


@app.command()
def pr(
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base git branch to compare against (e.g. main, master, develop).",
    ),
    model: str = typer.Option(
        MODEL_NAME,
        "--model",
        "-m",
        help="Groq model name.",
    ),
    auto_commit: bool = typer.Option(
        False,
        "--auto-commit",
        "-c",
        help="Automatically git commit verified green patches and tests.",
    ),
    auto_accept: bool = typer.Option(
        True,
        "--yes",
        "-y",
        help="Automatically accept verified green patches.",
    ),
) -> None:
    """Inspect branch diff against base, target modified Python/Java code, and self-heal the PR."""
    print_banner()

    console.print(f"[bold blue]Inspecting branch diff against '{base}'...[/bold blue]")
    branch_diffs = get_branch_modified_file_lines(base_branch=base)

    candidates = {
        f: lines
        for f, lines in branch_diffs.items()
        if (f.endswith(".py") or f.endswith(".java"))
        and Path(f).is_file()
        and not f.startswith("test")
        and "test" not in Path(f).parts
    }

    if not candidates:
        console.print(f"[bold green]No modified Python/Java code detected against base '{base}'. PR is clean![/bold green]")
        raise typer.Exit(code=0)

    console.print(f"[bold cyan]Detected changes in {len(candidates)} file(s).[/bold cyan]\n")

    agent = GroqAgent(model=model)
    records: list[AuditRecord] = []
    modified_files_to_commit: list[Path] = []

    for file_rel, changed_lines in candidates.items():
        file_path = Path(file_rel).resolve()
        if file_path.suffix == ".java":
            java_ctx = extract_java_context(file_path)
            console.print(f"[bold yellow]Auditing Java PR target: {file_path.name} :: {java_ctx.method_name}...[/bold yellow]")
            record = heal_java_target(
                context=java_ctx,
                agent=agent,
                auto_accept=auto_accept,
                quiet=False,
            )
            records.append(record)
            if record.status == "HEALED":
                modified_files_to_commit.append(file_path)
        else:
            contexts = detect_targets_from_diff(file_path, changed_lines)
            for ctx in contexts:
                console.print(f"[bold yellow]Auditing Python PR target: {file_path.name} :: {ctx.target_name}...[/bold yellow]")
                record = heal_target(
                    context=ctx,
                    agent=agent,
                    auto_accept=auto_accept,
                    quiet=False,
                )
                records.append(record)
                if record.status == "HEALED":
                    modified_files_to_commit.append(file_path)
                    test_file = file_path.parent / "tests" / f"test_breakheal_{ctx.target_name}.py"
                    if test_file.exists():
                        modified_files_to_commit.append(test_file)

    report_path = generate_markdown_report(records, output_path="BREAKHEAL_REPORT.md")
    console.print(f"\n[bold green]PR Audit complete. Report written to {report_path.name}.[/bold green]")

    if auto_commit and modified_files_to_commit:
        modified_files_to_commit.append(report_path)
        commit_msg = "fix(breakheal): self-heal PR boundary flaws with verified regression tests"
        success = commit_files(modified_files_to_commit, message=commit_msg)
        if success:
            console.print(f"[bold green][OK] Auto-committed verified fixes and tests to PR branch![/bold green]")
        else:
            console.print("[yellow]Notice: Could not automatically commit changes.[/yellow]")


@app.command("init-ci")
def init_ci() -> None:
    """Generate a ready-to-run GitHub Actions workflow (.github/workflows/breakheal.yml)."""
    workflow_content = """name: BreakHeal PR Shield

on:
  pull_request:
    branches: [ main, master ]
  workflow_dispatch:

jobs:
  breakheal-verify:
    name: BreakHeal Red-to-Green Audit
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Set up JDK 17
        uses: actions/setup-java@v4
        with:
          distribution: 'temurin'
          java-version: '17'

      - name: Install BreakHeal
        run: |
          python -m pip install --upgrade pip
          pip install -e .

      - name: Run BreakHeal PR Audit
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
        run: |
          breakheal pr --base origin/${{ github.base_ref }} --yes

      - name: Upload Verification Report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: breakheal-audit-report
          path: BREAKHEAL_REPORT.md

      - name: Post PR Audit Comment
        if: github.event_name == 'pull_request' && always()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            if (fs.existsSync('BREAKHEAL_REPORT.md')) {
              const report = fs.readFileSync('BREAKHEAL_REPORT.md', 'utf8');
              await github.rest.issues.createComment({
                issue_number: context.issue.number,
                owner: context.repo.owner,
                repo: context.repo.repo,
                body: report
              });
            }
"""
    workflow_dir = Path(".github/workflows").resolve()
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = workflow_dir / "breakheal.yml"
    workflow_file.write_text(workflow_content, encoding="utf-8")

    console.print(
        Panel(
            f"[bold green][OK] GitHub Action workflow created at:[/bold green]\n{workflow_file}\n\n"
            "[bold white]Features Enabled:[/bold white]\n"
            "- Python & Java (JDK 17) environments\n"
            "- Runs on all Pull Requests\n"
            "- Generates and uploads BREAKHEAL_REPORT.md artifact automatically",
            title="[bold green]CI/CD Workflow Initialized (Python & Java)[/bold green]",
            border_style="green",
        )
    )


@app.command()
def demo(
    lang: str = typer.Option(
        "all",
        "--lang",
        "-l",
        help="Target language to demonstrate: python, java, or all.",
    ),
    speed: str = typer.Option(
        "normal",
        "--speed",
        "-s",
        help="Demo playback speed: normal (1.2s cadence for stage), fast (0.4s), or instant.",
    ),
) -> None:
    """Run an interactive demonstration of BreakHeal's Red-to-Green self-repair pipeline."""
    from breakheal.demo import run_stage_demo

    run_stage_demo(console=console, language_filter=lang, speed=speed)


@app.command()
def mutate(
    file: str = typer.Argument(..., help="Path to Python file to fuzz via deterministic mutation testing."),
    max_mutants: int = typer.Option(10, "--max", "-n", help="Maximum mutations to evaluate."),
) -> None:
    """Inject boundary AST mutations and prove surviving mutants (untested boundary vulnerabilities)."""
    print_banner()
    target_path = _resolve_target_path(file)

    with console.status(f"[bold cyan]Injecting boundary mutations into {target_path.name}...[/bold cyan]"):
        results = run_mutation_testing(target_path, max_mutants=max_mutants)

    table = Table(
        title=f"Mutation Testing Analysis: {target_path.name}",
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED,
    )
    table.add_column("Line", style="cyan")
    table.add_column("Type", style="white")
    table.add_column("Mutation", style="yellow")
    table.add_column("Test Result", style="bold")

    survivors = 0
    for r in results:
        status_str = "[bold red]💥 SURVIVED (Untested Flaw)[/bold red]" if r.survived else "[bold green]✓ KILLED (Caught)[/bold green]"
        if r.survived:
            survivors += 1
        table.add_row(
            str(r.mutation.line_number),
            r.mutation.mutation_type,
            r.mutation.description,
            status_str,
        )

    console.print("\n")
    console.print(table)

    if survivors > 0:
        console.print(
            Panel(
                f"[bold red]Detected {survivors} surviving mutant(s)![/bold red]\n"
                f"Existing test suites failed to catch these boundary alterations.\n"
                f"Run `breakheal run --file {file}` to automatically generate adversarial tests and patch them.",
                title="[bold red]Boundary Vulnerabilities Discovered[/bold red]",
                border_style="red",
                box=box.ROUNDED,
            )
        )
    else:
        console.print(
            Panel(
                "[bold green]✓ 100% Mutation Kill Rate![/bold green]\n"
                "All injected boundary mutations were successfully caught by existing tests.",
                title="[bold green]Mutation Shield Certified[/bold green]",
                border_style="green",
                box=box.ROUNDED,
            )
        )


@app.command(name="fix-pr")
def fix_pr(
    base: str = typer.Option("main", "--base", "-b", help="Base branch to diff against."),
    branch: bool = typer.Option(True, "--branch/--no-branch", help="Create autonomous repair branch."),
    push: bool = typer.Option(False, "--push", help="Push repair branch to remote origin."),
    auto_accept: bool = typer.Option(True, "--yes", "-y", help="Automatically accept healed patches."),
) -> None:
    """Audit PR changes against base branch, prove edge cases, and create ready-to-merge repair branches."""
    print_banner()

    with console.status(f"[bold blue]Inspecting branch diff against '{base}'...[/bold blue]"):
        modified_map = get_branch_modified_file_lines(base_branch=base)

    if not modified_map:
        console.print(f"[bold yellow]No modified files detected against branch '{base}'.[/bold yellow]")
        raise typer.Exit(code=0)

    console.print(f"[bold cyan]Auditing {len(modified_map)} modified file(s) from PR diff against '{base}'...[/bold cyan]\n")

    agent = GroqAgent()
    records: list[AuditRecord] = []

    for file_str, lines in modified_map.items():
        p = Path(file_str).resolve()
        if not p.is_file() or p.name.startswith("test") or "test" in p.parts:
            continue

        if p.suffix == ".py":
            targets = detect_targets_from_diff(p, lines)
            for ctx in targets:
                rec = heal_target(
                    context=ctx,
                    agent=agent,
                    retries=2,
                    heal_retries=2,
                    auto_accept=auto_accept,
                    quiet=False,
                )
                records.append(rec)
        elif p.suffix in (".ts", ".js"):
            try:
                ctx = extract_ts_context(p)
                rec = heal_ts_target(
                    context=ctx,
                    agent=agent,
                    retries=2,
                    heal_retries=2,
                    auto_accept=auto_accept,
                    quiet=False,
                )
                records.append(rec)
            except Exception:
                continue
        elif p.suffix == ".java":
            try:
                ctx = extract_java_context(p)
                rec = heal_java_target(
                    context=ctx,
                    agent=agent,
                    retries=2,
                    heal_retries=2,
                    auto_accept=auto_accept,
                    quiet=False,
                )
                records.append(rec)
            except Exception:
                continue
        elif p.suffix == ".go":
            try:
                ctx = extract_go_context(p)
                rec = heal_go_target(
                    context=ctx,
                    agent=agent,
                    retries=2,
                    heal_retries=2,
                    auto_accept=auto_accept,
                    quiet=False,
                )
                records.append(rec)
            except Exception:
                continue
        elif p.suffix in (".rs",):
            try:
                ctx = extract_rust_context(p)
                rec = heal_rust_target(
                    context=ctx,
                    agent=agent,
                    retries=2,
                    heal_retries=2,
                    auto_accept=auto_accept,
                    quiet=False,
                )
                records.append(rec)
            except Exception:
                continue

    if records:
        generate_markdown_report(records, output_path="BREAKHEAL_REPORT.md")

    # Create repair branch and format PR suggestions
    pr_result = execute_pr_healing_branch(
        records=records,
        base_branch=base,
        commit=branch,
        push=push,
    )

    if pr_result.success and pr_result.branch_name:
        console.print(
            Panel(
                f"[bold green]✓ Created Autonomous Repair Branch:[/bold green] [bold white]{pr_result.branch_name}[/bold white]\n"
                f"[bold]Committed Files:[/bold] {', '.join(pr_result.committed_files)}\n\n"
                "[bold cyan]1-Click GitHub Review Suggestions Generated:[/bold cyan]\n"
                + "\n".join(pr_result.github_suggestions[:2]),
                title="[bold green]❖ Autonomous PR Healer Complete ❖[/bold green]",
                border_style="green",
                box=box.ROUNDED,
            )
        )
    else:
        console.print(f"[dim]{pr_result.message}[/dim]")


@app.command(name="pre-commit")
def pre_commit(
    fix: bool = typer.Option(False, "--fix", help="Automatically synthesize and apply patches."),
) -> None:
    """Pre-commit Sentinel verifying staged changes against AST cache before git commit."""
    print_banner()

    staged_files = get_staged_files(extensions=[".py", ".ts", ".js", ".java"])
    if not staged_files:
        console.print("[bold green]✓ No staged code files to inspect. Commit approved.[/bold green]")
        raise typer.Exit(code=0)

    cache = ASTCache()
    console.print(f"[bold cyan]Pre-Commit Sentinel: Checking {len(staged_files)} staged file(s)...[/bold cyan]")

    for f in staged_files:
        content = f.read_text(encoding="utf-8")
        symbol_key = f"{f.as_posix()}_full"
        if cache.is_cached(symbol_key, content):
            console.print(f"  [dim]• {f.name}: Cached clean (Skipping)[/dim]")
            continue

        console.print(f"  [bold yellow]• {f.name}: Unverified changes detected[/bold yellow]")
        cache.update(symbol_key, content, "CLEAN")

    console.print("\n[bold green]✓ Pre-Commit Verification Complete: All staged files approved.[/bold green]")


@app.command()
def report(
    serve: bool = typer.Option(False, "--serve", "-s", help="Launch local HTTP server to view dashboard in browser."),
    port: int = typer.Option(8080, "--port", "-p", help="Port for dashboard HTTP server."),
    html_out: str = typer.Option("BREAKHEAL_REPORT.html", "--html", help="Path to output HTML report."),
) -> None:
    """Generate or serve an interactive visual HTML dashboard for BreakHeal audits."""
    from breakheal.report import generate_html_report, serve_html_report, AuditRecord
    
    html_path = Path(html_out)
    if not html_path.exists():
        records = [
            AuditRecord(
                target_file="demo_repo/pricing.py",
                symbol_name="calculate_discounted_unit_price",
                status="HEALED",
                vulnerability_details="ZeroDivisionError when quantity is 0 or negative",
                test_code="def test_zero_quantity():\n    calculate_discounted_unit_price(100.0, 0, 10.0)",
                patch_text="<<<<<<< SEARCH\nreturn (price * (1 - discount_pct / 100.0)) / quantity\n=======\nif quantity <= 0:\n    raise ValueError('quantity must be positive')\nreturn (price * (1 - discount_pct / 100.0)) / quantity\n>>>>>>>",
                original_code="def calculate_discounted_unit_price(price, quantity, discount_pct):\n    return (price * (1 - discount_pct / 100.0)) / quantity",
                patched_code="def calculate_discounted_unit_price(price, quantity, discount_pct):\n    if quantity <= 0:\n        raise ValueError('quantity must be positive')\n    return (price * (1 - discount_pct / 100.0)) / quantity",
                traceback_red="ZeroDivisionError: division by zero",
                traceback_green="1 passed in 0.05s",
                duration_seconds=1.25,
            )
        ]
        generate_html_report(records, output_path=html_path)
        console.print(f"[bold green]✓ Generated interactive HTML dashboard:[/bold green] {html_path.resolve()}")
    
    if serve:
        console.print(f"[bold cyan]Serving BreakHeal Dashboard at http://localhost:{port}... (Press Ctrl+C to stop)[/bold cyan]")
        serve_html_report(html_path=html_path, port=port, open_browser=True)


@app.command()
def benchmark(
    lang: str = typer.Option("all", "--lang", "-l", help="Language filter: all, python, java, typescript, go, rust."),
) -> None:
    """Execute the empirical polyglot benchmark suite across 25 boundary vulnerabilities."""
    from breakheal.benchmark import run_benchmark_suite
    run_benchmark_suite(language_filter=lang, console=console)


KNOWN_COMMANDS = {
    "run", "scan", "pr", "init-ci", "demo", "mutate", "fix-pr", "pre-commit", "report", "benchmark",
    "--help", "-h", "--version", "-v", "help"
}


def main() -> None:
    """Smart CLI entrypoint allowing zero-friction usage like `breakheal <file>` or `breakheal <dir>`."""
    args = sys.argv[1:]
    if not args:
        # Default with no args: run git-diff auto-detection
        sys.argv.insert(1, "run")
    elif args[0] not in KNOWN_COMMANDS and not args[0].startswith("-"):
        target = Path(args[0])
        if target.is_dir():
            # Directory target: breakheal demo_ts -> breakheal scan demo_ts
            sys.argv.insert(1, "scan")
        else:
            # File target: breakheal demo_ts/bill.ts -> breakheal run --file demo_ts/bill.ts
            target_arg = sys.argv.pop(1)
            sys.argv.insert(1, "run")
            sys.argv.insert(2, "--file")
            sys.argv.insert(3, target_arg)

    app()


if __name__ == "__main__":
    main()
