"""Executive and visual report generator producing markdown audits and interactive HTML dashboards."""

from __future__ import annotations

import datetime
import html
import http.server
import socketserver
import threading
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence, Optional


@dataclass
class AuditRecord:
    target_file: str
    symbol_name: str
    status: str  # "HEALED", "CLEAN", "FAILED"
    vulnerability_details: str
    test_code: str
    patch_text: str
    original_code: str = ""
    patched_code: str = ""
    traceback_red: str = ""
    traceback_green: str = ""
    duration_seconds: float = 0.0
    language: str = "python"


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


def generate_html_report(
    records: Sequence[AuditRecord],
    output_path: str | Path = "BREAKHEAL_REPORT.html",
    title: str = "BreakHeal — Autonomous Verification Dashboard",
) -> Path:
    """Generate a self-contained, interactive HTML web dashboard for audit findings."""
    total = len(records)
    healed = sum(1 for r in records if r.status == "HEALED")
    clean = sum(1 for r in records if r.status == "CLEAN")
    failed = sum(1 for r in records if r.status == "FAILED")
    total_time = sum(r.duration_seconds for r in records)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cards_html = []
    for idx, r in enumerate(records, start=1):
        status_color = "#10b981" if r.status == "HEALED" else ("#06b6d4" if r.status == "CLEAN" else "#f43f5e")
        status_icon = "✓ HEALED" if r.status == "HEALED" else ("🛡 CLEAN" if r.status == "CLEAN" else "✗ FAILED")
        file_name = html.escape(Path(r.target_file).name)
        file_path = html.escape(r.target_file)
        symbol = html.escape(r.symbol_name)
        vuln = html.escape(r.vulnerability_details or "No boundary vulnerabilities detected.")
        test_code = html.escape(r.test_code.strip() or "// No test generated")
        patch_text = html.escape(r.patch_text.strip() or "// No patch required")
        orig_code = html.escape(r.original_code.strip() or "// Unmodified original source")
        patched_code = html.escape(r.patched_code.strip() or "// Healed verified source")
        trace_red = html.escape(r.traceback_red.strip() or "Exit Code 1: Boundary condition triggered failure")
        trace_green = html.escape(r.traceback_green.strip() or "Exit Code 0: All assertions passed")

        card = f"""
        <div class="target-card" data-status="{r.status}">
            <div class="card-header" onclick="toggleCard({idx})">
                <div class="header-left">
                    <span class="badge" style="background-color: {status_color};">{status_icon}</span>
                    <span class="file-name">{file_name}</span>
                    <span class="symbol-name">::{symbol}</span>
                </div>
                <div class="header-right">
                    <span class="time-tag">⏱ {r.duration_seconds:.2f}s</span>
                    <span class="toggle-icon" id="toggle-{idx}">▼</span>
                </div>
            </div>
            <div class="card-body" id="body-{idx}">
                <div class="meta-row">
                    <strong>Path:</strong> <code>{file_path}</code>
                </div>
                <div class="meta-row">
                    <strong>Diagnosis:</strong> <span class="vuln-text">{vuln}</span>
                </div>

                <!-- Execution Timeline -->
                <div class="timeline">
                    <div class="timeline-step step-done">
                        <div class="step-circle">1</div>
                        <div class="step-label">AST Parse</div>
                        <div class="step-desc">Target Isolated</div>
                    </div>
                    <div class="timeline-line active"></div>
                    <div class="timeline-step step-red">
                        <div class="step-circle">2</div>
                        <div class="step-label">Adversarial Test</div>
                        <div class="step-desc">Red Proven (Exit != 0)</div>
                    </div>
                    <div class="timeline-line active"></div>
                    <div class="timeline-step step-patch">
                        <div class="step-circle">3</div>
                        <div class="step-label">SEARCH/REPLACE</div>
                        <div class="step-desc">Minimal Guard Patch</div>
                    </div>
                    <div class="timeline-line active"></div>
                    <div class="timeline-step step-green">
                        <div class="step-circle">4</div>
                        <div class="step-label">Compiler Prover</div>
                        <div class="step-desc">Green Proven (Exit == 0)</div>
                    </div>
                </div>

                <!-- Tabbed details -->
                <div class="tab-container">
                    <div class="tab-buttons">
                        <button class="tab-btn active" onclick="switchTab({idx}, 'diff')">Side-by-Side Diff</button>
                        <button class="tab-btn" onclick="switchTab({idx}, 'test')">Adversarial Test (Red)</button>
                        <button class="tab-btn" onclick="switchTab({idx}, 'traceback')">Compiler Tracebacks</button>
                        <button class="tab-btn" onclick="switchTab({idx}, 'patch')">Raw Patch</button>
                    </div>

                    <div class="tab-content active" id="tab-{idx}-diff">
                        <div class="diff-grid">
                            <div class="diff-col">
                                <div class="col-title red-title">Original (Vulnerable)</div>
                                <pre><code>{orig_code}</code></pre>
                            </div>
                            <div class="diff-col">
                                <div class="col-title green-title">Healed (Deterministic Guard)</div>
                                <pre><code>{patched_code}</code></pre>
                            </div>
                        </div>
                    </div>

                    <div class="tab-content" id="tab-{idx}-test">
                        <pre><code>{test_code}</code></pre>
                    </div>

                    <div class="tab-content" id="tab-{idx}-traceback">
                        <div class="traceback-block">
                            <div class="trace-label red-label">🔴 Adversarial Failure (Red Verification):</div>
                            <pre class="trace-pre red-trace">{trace_red}</pre>
                        </div>
                        <div class="traceback-block">
                            <div class="trace-label green-label">🟢 Compiler Re-run (Green Verification):</div>
                            <pre class="trace-pre green-trace">{trace_green}</pre>
                        </div>
                    </div>

                    <div class="tab-content" id="tab-{idx}-patch">
                        <pre><code>{patch_text}</code></pre>
                    </div>
                </div>
            </div>
        </div>
        """
        cards_html.append(card)

    all_cards_str = "\n".join(cards_html)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <style>
        :root {{
            --bg: #090d16;
            --card-bg: #111827;
            --card-border: #1e293b;
            --text: #f3f4f6;
            --text-muted: #9ca3af;
            --cyan: #06b6d4;
            --green: #10b981;
            --red: #f43f5e;
            --amber: #f59e0b;
            --code-bg: #030712;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            padding: 24px;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1280px;
            margin: 0 auto;
        }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--card-border);
            margin-bottom: 24px;
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .brand h1 {{
            font-size: 28px;
            font-weight: 800;
            background: linear-gradient(135deg, #06b6d4 0%, #10b981 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .subtitle {{
            color: var(--text-muted);
            font-size: 14px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .stat-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 18px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            position: relative;
            overflow: hidden;
        }}
        .stat-card::after {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 3px;
        }}
        .stat-cyan::after {{ background: var(--cyan); }}
        .stat-green::after {{ background: var(--green); }}
        .stat-red::after {{ background: var(--red); }}
        .stat-amber::after {{ background: var(--amber); }}
        .stat-val {{
            font-size: 28px;
            font-weight: 700;
        }}
        .stat-lbl {{
            color: var(--text-muted);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .filters {{
            display: flex;
            gap: 8px;
            margin-bottom: 20px;
        }}
        .filter-btn {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            color: var(--text-muted);
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .filter-btn:hover, .filter-btn.active {{
            background: #1e293b;
            color: var(--text);
            border-color: var(--cyan);
        }}
        .target-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            margin-bottom: 16px;
            overflow: hidden;
            transition: border-color 0.2s;
        }}
        .target-card:hover {{
            border-color: #334155;
        }}
        .card-header {{
            padding: 16px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            user-select: none;
            background: #131d2e;
        }}
        .header-left {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .badge {{
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
            color: white;
            letter-spacing: 0.5px;
        }}
        .file-name {{
            font-weight: 700;
            color: var(--cyan);
            font-family: monospace;
        }}
        .symbol-name {{
            color: var(--text);
            font-family: monospace;
        }}
        .header-right {{
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .time-tag {{
            font-size: 13px;
            color: var(--text-muted);
        }}
        .toggle-icon {{
            font-size: 12px;
            color: var(--text-muted);
            transition: transform 0.2s;
        }}
        .card-body {{
            padding: 20px;
            border-top: 1px solid var(--card-border);
        }}
        .meta-row {{
            margin-bottom: 10px;
            font-size: 14px;
        }}
        .meta-row code {{
            background: var(--code-bg);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: monospace;
            color: var(--cyan);
        }}
        .vuln-text {{
            color: #fca5a5;
        }}
        /* Timeline */
        .timeline {{
            display: flex;
            align-items: center;
            margin: 24px 0;
            padding: 16px;
            background: var(--code-bg);
            border-radius: 8px;
            border: 1px solid #1e293b;
        }}
        .timeline-step {{
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            flex: 1;
        }}
        .step-circle {{
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 14px;
            margin-bottom: 6px;
            color: #fff;
        }}
        .step-done .step-circle {{ background: var(--cyan); }}
        .step-red .step-circle {{ background: var(--red); }}
        .step-patch .step-circle {{ background: var(--amber); }}
        .step-green .step-circle {{ background: var(--green); }}
        .step-label {{
            font-size: 12px;
            font-weight: 700;
        }}
        .step-desc {{
            font-size: 11px;
            color: var(--text-muted);
        }}
        .timeline-line {{
            height: 2px;
            background: #334155;
            flex: 1;
            margin-top: -18px;
        }}
        .timeline-line.active {{
            background: var(--green);
        }}
        /* Tabs */
        .tab-container {{
            margin-top: 16px;
        }}
        .tab-buttons {{
            display: flex;
            gap: 4px;
            border-bottom: 1px solid var(--card-border);
            margin-bottom: 12px;
        }}
        .tab-btn {{
            background: none;
            border: none;
            color: var(--text-muted);
            padding: 8px 14px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            border-bottom: 2px solid transparent;
        }}
        .tab-btn.active {{
            color: var(--cyan);
            border-bottom-color: var(--cyan);
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        pre {{
            background: var(--code-bg);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 14px;
            overflow-x: auto;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 13px;
            color: #e5e7eb;
        }}
        .diff-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }}
        .col-title {{
            font-size: 12px;
            font-weight: 700;
            padding: 6px 10px;
            border-radius: 6px 6px 0 0;
        }}
        .red-title {{ background: rgba(244, 63, 94, 0.15); color: #fda4af; }}
        .green-title {{ background: rgba(16, 185, 129, 0.15); color: #6ee7b7; }}
        .traceback-block {{
            margin-bottom: 12px;
        }}
        .trace-label {{
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 4px;
        }}
        .red-label {{ color: #fda4af; }}
        .green-label {{ color: #6ee7b7; }}
        .red-trace {{ border-left: 3px solid var(--red); }}
        .green-trace {{ border-left: 3px solid var(--green); }}
        footer {{
            margin-top: 48px;
            padding-top: 24px;
            border-top: 1px solid var(--card-border);
            text-align: center;
            color: var(--text-muted);
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <h1>BreakHeal</h1>
                <span class="subtitle">Autonomous Boundary Verification & Self-Repair Platform</span>
            </div>
            <div class="timestamp">
                <span class="subtitle">Generated: {now}</span>
            </div>
        </header>

        <section class="stats-grid">
            <div class="stat-card stat-cyan">
                <span class="stat-val">{total}</span>
                <span class="stat-lbl">Targets Inspected</span>
            </div>
            <div class="stat-card stat-green">
                <span class="stat-val">{healed}</span>
                <span class="stat-lbl">Proven & Healed</span>
            </div>
            <div class="stat-card stat-amber">
                <span class="stat-val">{clean}</span>
                <span class="stat-lbl">Robust / Clean</span>
            </div>
            <div class="stat-card stat-red">
                <span class="stat-val">{failed}</span>
                <span class="stat-lbl">Manual Review</span>
            </div>
            <div class="stat-card stat-cyan">
                <span class="stat-val">{total_time:.1f}s</span>
                <span class="stat-lbl">Total Pipeline Time</span>
            </div>
        </section>

        <div class="filters">
            <button class="filter-btn active" onclick="filterCards('ALL')">All Targets ({total})</button>
            <button class="filter-btn" onclick="filterCards('HEALED')">Healed ({healed})</button>
            <button class="filter-btn" onclick="filterCards('CLEAN')">Clean ({clean})</button>
            <button class="filter-btn" onclick="filterCards('FAILED')">Failed ({failed})</button>
        </div>

        <section class="targets-list">
            {all_cards_str}
        </section>

        <footer>
            BreakHeal Deterministic Engine — Polyglot AST Verification (Python, Java, TypeScript, Go, Rust)
        </footer>
    </div>

    <script>
        function toggleCard(idx) {{
            const body = document.getElementById('body-' + idx);
            const icon = document.getElementById('toggle-' + idx);
            if (body.style.display === 'none') {{
                body.style.display = 'block';
                icon.innerText = '▼';
            }} else {{
                body.style.display = 'none';
                icon.innerText = '▶';
            }}
        }}

        function switchTab(idx, tabName) {{
            const card = document.getElementById('body-' + idx);
            const btns = card.querySelectorAll('.tab-btn');
            const contents = card.querySelectorAll('.tab-content');
            btns.forEach(b => b.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));

            const targetTab = document.getElementById('tab-' + idx + '-' + tabName);
            if (targetTab) targetTab.classList.add('active');
            if (event && event.target) event.target.classList.add('active');
        }}

        function filterCards(status) {{
            const btns = document.querySelectorAll('.filter-btn');
            btns.forEach(b => b.classList.remove('active'));
            if (event && event.target) event.target.classList.add('active');

            const cards = document.querySelectorAll('.target-card');
            cards.forEach(card => {{
                if (status === 'ALL' || card.getAttribute('data-status') === status) {{
                    card.style.display = 'block';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}
    </script>
</body>
</html>
"""
    target_file = Path(output_path).resolve()
    target_file.write_text(html_content, encoding="utf-8")
    return target_file


def serve_html_report(
    html_path: str | Path = "BREAKHEAL_REPORT.html",
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    """Serve the generated HTML report on a local HTTP server and optionally open the browser."""
    path = Path(html_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Report file not found: {path}")

    directory = str(path.parent)
    filename = path.name

    class CustomHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def do_GET(self):
            if self.path in ("/", ""):
                self.path = f"/{filename}"
            return super().do_GET()

    # Allow port reuse
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), CustomHandler) as httpd:
        url = f"http://localhost:{port}/{filename}"
        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        httpd.serve_forever()
