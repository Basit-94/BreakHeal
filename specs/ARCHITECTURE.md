# BreakHeal Architecture Specification

## 1. System Overview
BreakHeal is an automated red-to-green test generation and code repair loop.

```
[Target File / Git Diff]
        │
        ▼
[context.py: AST Extraction & Imports]
        │
        ▼
[agent.py: Adversarial Test Generator (Groq LLaMA 3.3 70B)]
        │
        ▼
[runner.py: Pytest Execution (Step 2: Prove Red)]
        │
        ├── (Pass: Exit 0) ──► Test Rejected (Retry / Fail)
        │
        ▼ (Fail: Exit != 0)
[agent.py: Patch Synthesizer (SEARCH/REPLACE format)]
        │
        ▼
[Apply Patch directly to disk]
        │
        ▼
[runner.py: Pytest Execution (Step 4: Prove Green)]
        │
        ├── (Fail: Exit != 0) ──► Re-prompt or Rollback
        │
        ▼ (Pass: Exit 0)
[cli.py: Prompt User to Accept / Reject / Git Commit]
```

## 2. Module Boundaries
- `breakheal.cli`: CLI definition with Typer and terminal styling with Rich.
- `breakheal.git_utils`: Shell git commands (diff extraction, status checks, revert/rollback).
- `breakheal.context`: AST parsing to extract targeted functions, signatures, docstrings, and module-level imports.
- `breakheal.agent`: LLM orchestration with Groq API (test crafting, patch synthesis).
- `breakheal.runner`: Pytest subprocess manager with timeout and structured exit code reporting.
