"""Executive report generator producing markdown audits for BreakHeal runs."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class AuditRecord:
    target_file: str
    symbol_name: str
    status: str  # "HEALED", "CLEAN", "FAILED"
    vulnerability_details: str
    test_code: str
    patch_text: str
    duration_seconds: float = 0.0


def generate_mermaid_sequence_diagram(symbol_name: str) -> str:
    """Generate a Mermaid sequence diagram visualizing the adversarial Red-to-Green cycle."""
    safe_name = symbol_name.split(".")[-1]
    return f"""```mermaid
sequenceDiagram
    autonumber
    actor Suite as Test Suite / Client
    participant Target as {safe_name}()
    participant Shield as BreakHeal Shield
    
    Note over Suite,Target: 1. Adversarial Test Phase (RED)
    Suite->>Target: Call with boundary edge-case
    Target-->>Suite: 💥 Unhandled Exception (Exit != 0)
    
    Note over Suite,Target: 2. BreakHeal Self-Repair (GREEN)
    Shield->>Target: Injected SEARCH/REPLACE Guard
    Suite->>Target: Call with same edge-case
    Target->>Shield: Validate Boundary Constraints
    Shield-->>Suite: ✅ Handled Gracefully / Safe Return (Exit == 0)
```"""


def generate_markdown_report(
    records: Sequence[AuditRecord],
    output_path: str | Path = "BREAKHEAL_REPORT.md",
    title: str = "BreakHeal Automated Software Engineering Audit",
) -> Path:
    """Generate a clean, professional markdown report summarizing discovered flaws and applied patches."""
    total = len(records)
    healed = sum(1 for r in records if r.status == "HEALED")
    clean = sum(1 for r in records if r.status == "CLEAN")
    failed = sum(1 for r in records if r.status == "FAILED")

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# {title}",
        "",
        f"> **Generated:** {now} | **Deterministic Red-to-Green Engine**",
        "",
        "## Executive Summary",
        "",
        "| Metric | Count | Status |",
        "| :--- | :--- | :--- |",
        f"| **Total Functions Inspected** | {total} | Scanned |",
        f"| **Vulnerabilities Broken & Healed** | {healed} | Green Verified |",
        f"| **Clean / Robust Targets** | {clean} | Passed |",
        f"| **Unresolved Flaws** | {failed} | Manual Review Required |",
        "",
        "---",
        "",
        "## Target Verification Results",
        "",
        "| File | Symbol | Status | Vulnerability Detected | Time |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in records:
        status_badge = "✅ HEALED" if r.status == "HEALED" else ("🛡️ CLEAN" if r.status == "CLEAN" else "❌ FAILED")
        file_name = Path(r.target_file).name
        vuln_short = r.vulnerability_details.replace("\n", " ")[:60]
        lines.append(
            f"| `{file_name}` | `{r.symbol_name}` | {status_badge} | {vuln_short} | {r.duration_seconds:.2f}s |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Detailed Proof & Patch Evidence",
        "",
    ])

    for idx, r in enumerate(records, start=1):
        if r.status != "HEALED":
            continue

        file_name = Path(r.target_file).name
        lang = "java" if file_name.endswith(".java") else "python"
        diagram = generate_mermaid_sequence_diagram(r.symbol_name)
        lines.extend([
            f"### {idx}. `{file_name}` :: `{r.symbol_name}`",
            "",
            f"- **Target Path:** `{r.target_file}`",
            f"- **Flaw Diagnosis:** {r.vulnerability_details}",
            "",
            "#### 🔄 Red-to-Green Verification Flow",
            "",
            diagram,
            "",
            "<details>",
            "<summary><b>View Adversarial Test (Proved Red)</b></summary>",
            "",
            f"```{lang}",
            r.test_code.strip(),
            "```",
            "",
            "</details>",
            "",
            "<details open>",
            "<summary><b>View Verified SEARCH/REPLACE Patch (Proved Green)</b></summary>",
            "",
            "```text",
            r.patch_text.strip(),
            "```",
            "",
            "</details>",
            "",
            "---",
            "",
        ])

    target_file = Path(output_path).resolve()
    target_file.write_text("\n".join(lines), encoding="utf-8")
    return target_file
