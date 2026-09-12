# Product Requirements Document (PRD) — BreakHeal

## 1. Problem Statement
Existing automated code review bots (e.g., CodeRabbit, PR-Agent) are conversational. They post markdown suggestions that developers frequently ignore or misapply. Conversely, automated test generators often write trivial "happy path" tests that fail to detect real boundary bugs, off-by-one errors, or unhandled null/empty states.

## 2. Product Vision
BreakHeal is a deterministic, terminal-native automated software engineering agent. Instead of leaving comments, BreakHeal:
1. Detects uncommitted changes or active branch diffs.
2. Identifies boundary vulnerabilities using targeted context extraction.
3. Automatically writes a runnable, failing edge-case test (**Red**).
4. Synthesizes a targeted code patch to fix the flaw (**Green**).
5. Exports a clean patch or auto-commits the verified fix.

## 3. Key Design Goals
- High technical depth, deterministic execution, and polyglot compiler verification.
- Clear terminal UX with rich visual progress tracking and automated self-repair.

## 4. User Journey
1. Developer modifies code in a repository (e.g., updates discount logic in `pricing.py`).
2. Developer runs `breakheal run --file pricing.py` in the terminal.
3. BreakHeal extracts the modified function, crafts a breaking unit test, and executes `pytest` (Output shows failing test in red).
4. BreakHeal feeds the failure traceback to the patcher, applies the minimal code update, and re-executes `pytest` (Output turns green).
5. BreakHeal asks the user: `[A]ccept patch and save test? / [R]eject`.
