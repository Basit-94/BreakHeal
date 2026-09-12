"""LLM client routed to Groq endpoint for adversarial test synthesis and patch generation."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from openai import OpenAI

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from breakheal.context import CodeContext
from breakheal.java_context import JavaContext
from breakheal.ts_context import TSContext
from breakheal.go_context import GoContext
from breakheal.rust_context import RustContext

MODEL_NAME = "groq/compound-mini"
DEFAULT_MODEL = MODEL_NAME
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


def load_project_guidelines() -> str:
    """Discover and read project guidelines from CONTRIBUTING.md, STYLEGUIDE.md, or .breakhealrules."""
    for filename in [".breakhealrules", "CONTRIBUTING.md", "STYLEGUIDE.md", ".github/CONTRIBUTING.md"]:
        path = Path(filename)
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                return content[:1500].strip()
            except Exception:
                continue
    return ""


class GroqAgent:
    """Agent communicating with Groq via the OpenAI SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
    ):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.base_url = base_url
        self.model = model
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key or "missing_key",
        )

    def _create_completion(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ):
        """Invoke chat completions with automatic fallback and rate limit backoff."""
        models_to_try = [self.model]
        for fallback in ["groq/compound", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b"]:
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_err = None
        for m in models_to_try:
            curr_max_tokens = max_tokens
            for attempt in range(3):
                try:
                    resp = self.client.chat.completions.create(
                        model=m,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=curr_max_tokens,
                    )
                    # Strip any reasoning / thinking tokens if present
                    if resp.choices and resp.choices[0].message and resp.choices[0].message.content:
                        clean_content = re.sub(r"<think>[\s\S]*?</think>", "", resp.choices[0].message.content).strip()
                        resp.choices[0].message.content = clean_content
                    return resp
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    if "rate_limit" in err_str or "429" in err_str or "tokens per minute" in err_str or "tokens per day" in err_str:
                        time.sleep(2 * (attempt + 1))
                        curr_max_tokens = max(500, curr_max_tokens - 300)
                        continue
                    if "model_not_found" in err_str or "404" in err_str or "does not exist" in err_str or "decommissioned" in err_str:
                        break
                    raise e

        if last_err:
            raise last_err

    def _clean_code_fence(self, response_text: str) -> str:
        """Strip markdown code block wrappers if model wrapped output in backticks."""
        pattern = r"```(?:python)?\s*\n(.*?)\n```"
        match = re.search(pattern, response_text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # If text is enclosed in simple backticks
        if response_text.startswith("```") and response_text.endswith("```"):
            lines = response_text.splitlines()
            if len(lines) >= 2:
                return "\n".join(lines[1:-1]).strip()
        return response_text.strip()

    def generate_adversarial_test(
        self,
        context: CodeContext,
        feedback: str | None = None,
    ) -> str:
        """Generate an adversarial pytest unit test targeting boundary bugs and edge cases."""
        if not self.api_key:
            raise ValueError(
                "GROQ_API_KEY environment variable is not set. "
                "Please set GROQ_API_KEY to generate adversarial tests."
            )

        imports_block = "\n".join(context.imports) if context.imports else ""

        if context.is_method and context.class_name:
            if context.is_static:
                call_guideline = f"Call the static method directly: `{context.class_name}.{context.target_name}(...)`."
            elif context.is_classmethod:
                call_guideline = f"Call the classmethod directly: `{context.class_name}.{context.target_name}(...)`."
            else:
                call_guideline = (
                    f"CRITICAL OOP INVOCATION:\n"
                    f"`{context.target_name}` is an INSTANCE method of class `{context.class_name}`.\n"
                    f"- Import the class: `from {context.module_name} import {context.class_name}`\n"
                    f"- Instantiate the class: `instance = {context.class_name}(...)` (see constructor below)\n"
                    f"- Call: `instance.{context.target_name}(...)`\n"
                    f"- DO NOT import `{context.target_name}` directly from `{context.module_name}`!"
                )
        else:
            call_guideline = f"Import and call directly: `from {context.module_name} import {context.target_name}`."

        system_prompt = (
            "You are an adversarial test engineer in an automated Red-to-Green repair loop.\n"
            "Your objective is to craft a SINGLE, minimal, focused, runnable pytest unit test function that exposes a "
            "subtle bug, unhandled edge case, zero-division, off-by-one boundary, empty state, "
            "or type vulnerability in the target code.\n\n"
            "Rules:\n"
            "1. Output ONLY runnable Python test code. No explanations, no markdown comments outside code.\n"
            "2. Import pytest.\n"
            "3. Write exactly ONE focused test function (e.g. `def test_edge_case_...():`). Do NOT write multiple tests or general happy-path tests.\n"
            f"4. Target: {context.target_name} (in file {context.file_path})\n"
            f"5. Invocation Rule:\n{call_guideline}\n"
            "6. The test must be designed to FAIL on the current unmodified code (Red state).\n"
            "7. Do NOT mock the target function logic; execute it directly with adversarial inputs.\n"
            "8. Make sure all imports and function calls match the actual signatures from the full source.\n"
        )

        user_prompt = (
            f"File: {context.file_path}\n"
            f"Module: {context.module_name}\n"
            f"Target function / method: {context.target_name}\n"
            f"Class: {context.class_name or 'None'}\n"
            f"Is Method: {context.is_method}\n"
            f"Is Static: {context.is_static}\n\n"
            f"Target Focal Code (Lines {context.start_line}-{context.end_line}):\n```python\n{context.target_code}\n```\n\n"
        )

        if context.constructor_code:
            user_prompt += f"Class Constructor (`__init__`):\n```python\n{context.constructor_code}\n```\n\n"

        if context.full_source:
            user_prompt += f"Full File Source Code:\n```python\n{context.full_source}\n```\n\n"
        else:
            user_prompt += f"File imports:\n{imports_block}\n\n"

        try:
            from breakheal.import_graph import build_import_contract_prompt_section
            contracts = build_import_contract_prompt_section(context.file_path)
            if contracts:
                user_prompt += f"\n{contracts}\n"
        except Exception:
            pass

        if feedback:
            user_prompt += (
                f"\nPrevious attempt feedback (the previous test passed or was invalid):\n"
                f"{feedback}\n"
                "Please generate a more aggressive, targeted adversarial test that definitely fails on current code."
            )

        user_prompt += "\nWrite the complete pytest test file code below:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        raw_test = response.choices[0].message.content or ""
        return self._clean_code_fence(raw_test)

    def generate_patch(
        self,
        context: CodeContext,
        test_code: str,
        test_output: str,
        previous_attempts: list[dict[str, str]] | None = None,
    ) -> str:
        """Synthesize a targeted patch in SEARCH/REPLACE format to fix the failing test.
        
        Supports multi-turn repair by supplying previous failed attempts and tracebacks.
        """
        if not self.api_key:
            raise ValueError(
                "GROQ_API_KEY environment variable is not set. "
                "Please set GROQ_API_KEY to synthesize code patches."
            )

        system_prompt = (
            "You are an expert automated software repair agent.\n"
            "Your objective is to generate a minimal, targeted patch to fix the failing test.\n\n"
            "STRICT OUTPUT FORMAT RULES:\n"
            "1. Never output unified diffs (@@ -x,y +x,y @@).\n"
            "2. Output ONLY SEARCH/REPLACE blocks formatted exactly as:\n"
            "<<<<<<< SEARCH\n"
            "[exact matching original code]\n"
            "=======\n"
            "[replacement code]\n"
            ">>>>>>>\n"
            "3. The SEARCH block must match existing lines in the target file exactly, including whitespace.\n"
            "4. Keep the modification footprint minimal. Fix only what is necessary to pass the test.\n"
            "5. Do NOT include extraneous markdown explanations.\n"
        )

        guidelines = load_project_guidelines()
        if guidelines:
            system_prompt += f"\nProject Invariants & Coding Guidelines:\n{guidelines}\n"

        user_prompt = (
            f"File to patch: {context.file_path}\n\n"
            f"Original code section:\n```python\n{context.target_code}\n```\n\n"
            f"Full file content:\n```python\n{context.full_source}\n```\n\n"
            f"Adversarial failing test:\n```python\n{test_code}\n```\n\n"
            f"Pytest failure traceback / output:\n```text\n{test_output}\n```\n\n"
        )

        try:
            from breakheal.import_graph import build_import_contract_prompt_section
            contracts = build_import_contract_prompt_section(context.file_path)
            if contracts:
                user_prompt += f"\n{contracts}\n"
        except Exception:
            pass

        if previous_attempts:
            user_prompt += "\n--- PREVIOUS FAILED PATCH ATTEMPTS ---\n"
            for idx, attempt in enumerate(previous_attempts, start=1):
                user_prompt += (
                    f"Attempt #{idx}:\n"
                    f"Generated Patch:\n{attempt.get('patch', '')}\n"
                    f"Failure / Error:\n{attempt.get('error', '')}\n\n"
                )
            user_prompt += (
                "Please analyze the errors from previous attempts, fix the flaws, "
                "ensure the SEARCH block matches lines in the file exactly, and output a valid SEARCH/REPLACE block:\n"
            )
        else:
            user_prompt += "Generate the minimal SEARCH/REPLACE block to fix this issue:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )

        patch_output = response.choices[0].message.content or ""
        # In case the model wrapped SEARCH/REPLACE in a markdown block
        cleaned_patch = patch_output.replace("```text", "").replace("```python", "").replace("```", "").strip()
        return cleaned_patch

    def generate_adversarial_java_test(
        self,
        context: JavaContext,
        feedback: str | None = None,
    ) -> str:
        """Synthesize a complete JUnit 5 test class exposing a boundary bug in Java code."""
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        test_class_name = f"BreakHeal{context.class_name}Test"
        package_line = f"package {context.package_name};" if context.package_name else ""

        system_prompt = (
            "You are an adversarial Java test engineer in an automated Red-to-Green repair loop.\n"
            "Your objective is to craft an isolated, runnable JUnit 5 test class with ONE @Test method that exposes a "
            "subtle bug, unhandled edge case, zero-division, off-by-one boundary, empty state, "
            "or null-pointer vulnerability in the target Java method.\n\n"
            "Rules:\n"
            "1. Output ONLY runnable Java code. No markdown or explanations outside code.\n"
            "2. Use JUnit 5: import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*;\n"
            f"3. Package declaration MUST BE: {package_line}\n"
            f"4. The class name MUST BE: public class {test_class_name}\n"
            f"5. Target class: {context.class_name}, method: {context.method_name}\n"
            f"6. Invocation: {'Call static method ' + context.class_name + '.' + context.method_name + '()' if context.is_static else 'Instantiate ' + context.class_name + ' instance = new ' + context.class_name + '(...); instance.' + context.method_name + '()'}\n"
            "7. The test must be designed to FAIL on the current unmodified code (Red state) "
            "(e.g. assertThrows an expected exception when currently unhandled, or assert a correct output).\n"
            "8. Output exactly ONE @Test method.\n"
            f"9. CRITICAL INNER TYPES IMPORT: If `{context.class_name}` defines inner classes, records, or enums (e.g. `Order`, `Side`, `OrderType`), ALWAYS include `import {context.package_name + '.' if context.package_name else ''}{context.class_name}.*;` to avoid unresolved compilation errors.\n"
            "10. STRICT VISIBILITY: DO NOT access private fields or private methods directly (e.g. fields without public access). Interact ONLY through public methods and public constructor/getters.\n"
            "11. IMPORTS: Always import any standard classes needed (e.g. java.time.Duration, java.time.Instant, java.math.BigDecimal, etc.).\n"
        )

        user_prompt = (
            f"File: {context.file_path}\n"
            f"Package: {context.package_name}\n"
            f"Class: {context.class_name}\n"
            f"Target Method: {context.method_name}\n"
            f"Is Static: {context.is_static}\n\n"
            f"Target Method Code:\n```java\n{context.method_code}\n```\n\n"
        )

        if getattr(context, "api_contract", None):
            user_prompt += f"{context.api_contract}\n\n"

        if getattr(context, "threat_reasons", None):
            reasons_str = "\n".join(f"- {r}" for r in context.threat_reasons)
            user_prompt += f"Detected Vulnerability Vectors to Target in Adversarial Test:\n{reasons_str}\n\n"

        if context.constructor_code:
            user_prompt += f"Class Constructor:\n```java\n{context.constructor_code}\n```\n\n"

        if context.fields_code:
            user_prompt += f"Class Fields:\n```java\n{context.fields_code}\n```\n\n"

        user_prompt += f"Full Class Source:\n```java\n{context.full_source}\n```\n\n"

        if feedback:
            user_prompt += (
                f"\nPrevious attempt feedback (the previous test passed or was invalid):\n"
                f"{feedback}\n"
                "Please generate a more aggressive adversarial JUnit 5 test that definitely fails on current code."
            )

        user_prompt += f"\nWrite the complete Java test class `{test_class_name}` code below:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        raw_test = response.choices[0].message.content or ""
        # Clean java code fences
        cleaned = re.sub(r"^```(?:java)?\s*", "", raw_test.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
        return cleaned.strip()

    def generate_java_patch(
        self,
        context: JavaContext,
        test_code: str,
        test_output: str,
        previous_attempts: list[dict[str, str]] | None = None,
    ) -> str:
        """Synthesize a minimal SEARCH/REPLACE patch for Java code."""
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        system_prompt = (
            "You are an expert automated software repair agent for Java.\n"
            "Your objective is to generate a minimal, targeted patch to fix the failing JUnit 5 test.\n\n"
            "STRICT OUTPUT FORMAT RULES:\n"
            "1. Never output unified diffs.\n"
            "2. Output ONLY SEARCH/REPLACE blocks formatted exactly as:\n"
            "<<<<<<< SEARCH\n"
            "[exact matching original Java code]\n"
            "=======\n"
            "[replacement Java code]\n"
            ">>>>>>>\n"
            "3. The SEARCH block must match existing lines in the target file exactly, including whitespace.\n"
            "4. Keep the modification footprint minimal. Fix only what is necessary to pass the test.\n"
            "5. Do NOT include extraneous markdown explanations.\n"
        )

        guidelines = load_project_guidelines()
        if guidelines:
            system_prompt += f"\nProject Invariants & Coding Guidelines:\n{guidelines}\n"

        user_prompt = (
            f"File to patch: {context.file_path}\n"
            f"Class: {context.class_name}\n"
            f"Target Method Code:\n```java\n{context.method_code}\n```\n\n"
            f"Full File Content:\n```java\n{context.full_source}\n```\n\n"
            f"Failing JUnit 5 Test:\n```java\n{test_code}\n```\n\n"
            f"Maven / Surefire Failure Output:\n```text\n{test_output}\n```\n\n"
        )

        if getattr(context, "api_contract", None):
            user_prompt += f"{context.api_contract}\n\n"

        if previous_attempts:
            user_prompt += "\n--- PREVIOUS FAILED PATCH ATTEMPTS ---\n"
            for idx, attempt in enumerate(previous_attempts, start=1):
                user_prompt += (
                    f"Attempt #{idx}:\n"
                    f"Generated Patch:\n{attempt.get('patch', '')}\n"
                    f"Failure / Error:\n{attempt.get('error', '')}\n\n"
                )
            user_prompt += "Analyze why the previous patch failed, fix the flaws, and output a valid SEARCH/REPLACE block:\n"
        else:
            user_prompt += "Generate the minimal SEARCH/REPLACE block to fix this issue:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )

        patch_output = response.choices[0].message.content or ""
        cleaned = patch_output.replace("```text", "").replace("```java", "").replace("```", "").strip()
        return cleaned

    def generate_adversarial_ts_test(
        self,
        context: TSContext,
        feedback: str | None = None,
    ) -> str:
        """Synthesize a focused Node.js / TypeScript test exposing an edge-case boundary flaw."""
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        import_target = context.class_name if context.class_name else context.target_name.split(".")[-1]
        file_name = Path(context.file_path).name
        method_name = context.target_name.split(".")[-1]

        if context.class_name:
            if getattr(context, "is_static", False):
                call_guideline = f"Call the static method directly: `{context.class_name}.{method_name}(...)`."
            else:
                call_guideline = (
                    f"CRITICAL: `{method_name}` is an INSTANCE method on class `{context.class_name}`.\n"
                    f"You MUST instantiate the class first: `const instance = new {context.class_name}(...);`\n"
                    f"Then call: `instance.{method_name}(...);`\n"
                    f"DO NOT call `{context.class_name}.{method_name}(...)` statically!"
                )
        else:
            call_guideline = f"Call `{method_name}(...)` directly."

        system_prompt = (
            "You are an adversarial test engineer in an automated Red-to-Green repair loop for TypeScript/JavaScript.\n"
            "Your objective is to craft an isolated, runnable test using 'node:test' and 'node:assert/strict' "
            "that exposes a subtle bug, unhandled edge case, zero-division, empty array, or off-by-one boundary.\n\n"
            "Rules:\n"
            "1. Output ONLY runnable JavaScript/TypeScript test code. No explanations or text outside code.\n"
            "2. Use ES module syntax: import test from 'node:test'; import assert from 'node:assert/strict';\n"
            f"3. Import the target: import {{ {import_target} }} from './{file_name}';\n"
            f"4. Invocation: {call_guideline}\n"
            "5. The test must be designed to FAIL on the current unmodified code (Red state) "
            "(e.g. assert.throws or assert an expected correct value that current code fails to produce).\n"
            "6. Exactly ONE test() block.\n"
        )

        user_prompt = (
            f"File: {context.file_path}\n"
            f"Target: {context.target_name}\n"
            f"Class: {context.class_name or 'None'}\n"
            f"Is Static: {getattr(context, 'is_static', False)}\n"
            f"Invocation Rule: {call_guideline}\n\n"
            f"Target Focal Source Code (Lines {context.start_line}-{context.end_line}):\n```ts\n{context.source_code}\n```\n\n"
        )

        if getattr(context, "api_contract", None):
            user_prompt += f"{context.api_contract}\n\n"

        if getattr(context, "threat_reasons", None):
            reasons_str = "\n".join(f"- {r}" for r in context.threat_reasons)
            user_prompt += f"Detected Vulnerability Vectors to Target in Adversarial Test:\n{reasons_str}\n\n"

        if getattr(context, "constructor_code", None):
            user_prompt += f"Class Constructor for reference:\n```ts\n{context.constructor_code}\n```\n\n"

        if getattr(context, "types_and_interfaces", None):
            types_str = "\n\n".join(context.types_and_interfaces)
            user_prompt += f"File Types, Interfaces & Enums:\n```ts\n{types_str}\n```\n\n"

        if getattr(context, "full_source", None):
            user_prompt += f"Full File Source Code:\n```ts\n{context.full_source}\n```\n\n"

        if feedback:
            user_prompt += (
                f"\nPrevious attempt feedback (previous test passed or was invalid):\n"
                f"{feedback}\n"
                "Please generate a more aggressive test exposing an unhandled edge case that definitely fails on current code."
            )

        user_prompt += "\nWrite the complete runnable test code below:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        raw_test = response.choices[0].message.content or ""
        cleaned = re.sub(r"^```(?:javascript|typescript|js|ts)?\s*", "", raw_test.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
        return cleaned.strip()

    def generate_ts_patch(
        self,
        context: TSContext,
        test_code: str,
        test_output: str,
        previous_attempts: list[dict[str, str]] | None = None,
    ) -> str:
        """Synthesize a minimal SEARCH/REPLACE patch for TypeScript/JavaScript code."""
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        system_prompt = (
            "You are an expert automated software repair agent for TypeScript and JavaScript.\n"
            "Your objective is to generate a minimal, targeted patch to fix the failing Node.js test.\n\n"
            "STRICT OUTPUT FORMAT RULES:\n"
            "1. Never output unified diffs.\n"
            "2. Output ONLY SEARCH/REPLACE blocks formatted exactly as:\n"
            "<<<<<<< SEARCH\n"
            "[exact matching original source code]\n"
            "=======\n"
            "[replacement source code]\n"
            ">>>>>>>\n"
            "3. The SEARCH block must match existing lines in the target file exactly, including whitespace.\n"
            "4. Keep the modification footprint minimal. Fix only what is necessary to pass the test.\n"
            "5. Do NOT include extraneous markdown explanations.\n"
        )

        guidelines = load_project_guidelines()
        if guidelines:
            system_prompt += f"\nProject Invariants & Coding Guidelines:\n{guidelines}\n"

        user_prompt = (
            f"File to patch: {context.file_path}\n"
            f"Target: {context.target_name}\n"
            f"Class: {context.class_name or 'None'}\n\n"
            f"Target Method Code:\n```ts\n{context.source_code}\n```\n\n"
        )

        if getattr(context, "full_source", None):
            user_prompt += f"Full File Content:\n```ts\n{context.full_source}\n```\n\n"

        user_prompt += (
            f"Failing Test:\n```js\n{test_code}\n```\n\n"
            f"Node.js Failure Output:\n```text\n{test_output}\n```\n\n"
        )

        if getattr(context, "api_contract", None):
            user_prompt += f"{context.api_contract}\n\n"

        if previous_attempts:
            user_prompt += "\n--- PREVIOUS FAILED PATCH ATTEMPTS ---\n"
            for idx, attempt in enumerate(previous_attempts, start=1):
                user_prompt += (
                    f"Attempt #{idx}:\n"
                    f"Generated Patch:\n{attempt.get('patch', '')}\n"
                    f"Failure / Error:\n{attempt.get('error', '')}\n\n"
                )
            user_prompt += "Analyze why the previous patch failed, fix the flaws, and output a valid SEARCH/REPLACE block:\n"
        else:
            user_prompt += "Generate the minimal SEARCH/REPLACE block to fix this issue:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )

        patch_output = response.choices[0].message.content or ""
        cleaned = patch_output.replace("```text", "").replace("```javascript", "").replace("```typescript", "").replace("```js", "").replace("```ts", "").replace("```", "").strip()
        return cleaned

    def generate_adversarial_go_test(
        self,
        context: GoContext,
        feedback: str | None = None,
    ) -> str:
        """Synthesize an isolated Go test exposing a boundary bug or panic vulnerability."""
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        test_func_name = f"TestBreakHeal_{context.target_name.replace('.', '_')}"

        system_prompt = (
            "You are an adversarial Go test engineer in an automated Red-to-Green repair loop.\n"
            "Your objective is to craft an isolated, runnable Go test function using standard `testing.T` "
            "that exposes a subtle bug, unhandled edge case, zero-division, nil-pointer dereference, "
            "slice bounds panic, or logic boundary flaw in the target Go function/method.\n\n"
            "Rules:\n"
            "1. Output ONLY runnable Go code. No markdown or explanations outside code.\n"
            f"2. Package declaration MUST MATCH the target file package: package {context.package_name}\n"
            "3. Import \"testing\" and any required standard library packages.\n"
            f"4. The test function name MUST BE: func {test_func_name}(t *testing.T)\n"
            f"5. Target function/method: {context.target_name}\n"
            "6. The test must be designed to FAIL on current unmodified code (Red state) "
            "(e.g. t.Fatalf(\"...\") when result is invalid, or triggering a panic if unhandled).\n"
            "7. Output exactly ONE test function.\n"
            "8. STRICT VISIBILITY: Call only exported functions/methods or public fields within the package.\n"
        )

        user_prompt = (
            f"File: {context.file_path}\n"
            f"Package: {context.package_name}\n"
            f"Target: {context.target_name}\n"
            f"Receiver: {context.receiver_type or 'None'}\n\n"
            f"Target Code (Lines {context.start_line}-{context.end_line}):\n```go\n{context.function_code}\n```\n\n"
            f"Full File Source:\n```go\n{context.full_source}\n```\n\n"
        )

        if getattr(context, "api_contract", None):
            user_prompt += f"{context.api_contract}\n\n"

        if getattr(context, "threat_reasons", None):
            reasons_str = "\n".join(f"- {r}" for r in context.threat_reasons)
            user_prompt += f"Detected Vulnerability Vectors to Target in Adversarial Test:\n{reasons_str}\n\n"

        if feedback:
            user_prompt += (
                f"\nPrevious attempt feedback (test passed or failed compilation):\n"
                f"{feedback}\n"
                "Please generate a more aggressive Go test exposing an unhandled edge case that definitely fails on current code."
            )

        user_prompt += f"\nWrite the complete runnable Go test code below:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        raw_test = response.choices[0].message.content or ""
        cleaned = re.sub(r"^```(?:go)?\s*", "", raw_test.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
        return cleaned.strip()

    def generate_go_patch(
        self,
        context: GoContext,
        test_code: str,
        test_output: str,
        previous_attempts: list[dict[str, str]] | None = None,
    ) -> str:
        """Synthesize a minimal SEARCH/REPLACE patch for Go code."""
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        system_prompt = (
            "You are an expert automated software repair agent for Go.\n"
            "Your objective is to generate a minimal, targeted patch to fix the failing Go test.\n\n"
            "STRICT OUTPUT FORMAT RULES:\n"
            "1. Never output unified diffs.\n"
            "2. Output ONLY SEARCH/REPLACE blocks formatted exactly as:\n"
            "<<<<<<< SEARCH\n"
            "[exact matching original Go source code]\n"
            "=======\n"
            "[replacement Go source code]\n"
            ">>>>>>>\n"
            "3. The SEARCH block must match existing lines in the target file exactly, including whitespace.\n"
            "4. The SEARCH block MUST be copied VERBATIM from the Target Method Code below. DO NOT modify comments or invent lines in SEARCH.\n"
            "5. Keep the modification footprint minimal. Fix only what is necessary to pass the test.\n"
            "6. Do NOT include extraneous markdown explanations.\n"
        )

        guidelines = load_project_guidelines()
        if guidelines:
            system_prompt += f"\nProject Invariants & Coding Guidelines:\n{guidelines}\n"

        user_prompt = (
            f"File to patch: {context.file_path}\n"
            f"Package: {context.package_name}\n"
            f"Target: {context.target_name}\n\n"
            f"Target Method Code to Patch (Copy your SEARCH block verbatim from here):\n```go\n{context.function_code}\n```\n\n"
            f"Full File Content:\n```go\n{context.full_source}\n```\n\n"
            f"Failing Go Test:\n```go\n{test_code}\n```\n\n"
            f"Go Test Failure Output:\n```text\n{test_output}\n```\n\n"
        )

        if getattr(context, "api_contract", None):
            user_prompt += f"{context.api_contract}\n\n"

        if previous_attempts:
            user_prompt += "\n--- PREVIOUS FAILED PATCH ATTEMPTS ---\n"
            for idx, attempt in enumerate(previous_attempts, start=1):
                user_prompt += (
                    f"Attempt #{idx}:\n"
                    f"Generated Patch:\n{attempt.get('patch', '')}\n"
                    f"Failure / Error:\n{attempt.get('error', '')}\n\n"
                )
            user_prompt += "Analyze why the previous patch failed, fix the flaws, and output a valid SEARCH/REPLACE block:\n"
        else:
            user_prompt += "Generate the minimal SEARCH/REPLACE block to fix this issue:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )

        patch_output = response.choices[0].message.content or ""
        cleaned = patch_output.replace("```text", "").replace("```go", "").replace("```", "").strip()
        return cleaned

    def generate_adversarial_rust_test(
        self,
        context: RustContext,
        feedback: str | None = None,
    ) -> str:
        """Synthesize an isolated Rust test exposing a boundary bug or panic vulnerability."""
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        test_func_name = f"test_breakheal_{context.target_name.replace('::', '_').replace('.', '_')}"

        system_prompt = (
            "You are an adversarial Rust test engineer in an automated Red-to-Green repair loop.\n"
            "Your objective is to craft an isolated, runnable Rust `#[test]` function "
            "that exposes a subtle bug, unhandled edge case, integer overflow, unwrap() panic, "
            "slice out-of-bounds, or logic boundary flaw in the target Rust function/method.\n\n"
            "Rules:\n"
            "1. Output ONLY runnable Rust code. No markdown or explanations outside code.\n"
            "2. Wrap in a test module: #[cfg(test)] mod tests { use super::*; #[test] ... }\n"
            f"3. The test function name MUST BE: fn {test_func_name}()\n"
            f"4. Target function/method: {context.target_name}\n"
            "5. The test must be designed to FAIL on current unmodified code (Red state) "
            "(e.g. assert_eq!(...) producing incorrect value, or triggering an unexpected panic/overflow).\n"
            "6. Output exactly ONE test function.\n"
            "7. STRICT VISIBILITY: If a struct has private fields, DO NOT use struct literal `Foo { a: 1 }`. "
            "Construct via public `Foo::new(...)` or public constructor methods.\n"
        )

        user_prompt = (
            f"File: {context.file_path}\n"
            f"Target: {context.target_name}\n"
            f"Enclosing Type: {context.enclosing_type or 'None'}\n\n"
            f"Target Code (Lines {context.start_line}-{context.end_line}):\n```rust\n{context.function_code}\n```\n\n"
            f"Full File Source:\n```rust\n{context.full_source}\n```\n\n"
        )

        if getattr(context, "api_contract", None):
            user_prompt += f"{context.api_contract}\n\n"

        if getattr(context, "threat_reasons", None):
            reasons_str = "\n".join(f"- {r}" for r in context.threat_reasons)
            user_prompt += f"Detected Vulnerability Vectors to Target in Adversarial Test:\n{reasons_str}\n\n"

        if feedback:
            user_prompt += (
                f"\nPrevious attempt feedback (test passed or failed compilation):\n"
                f"{feedback}\n"
                "Please generate a more aggressive Rust test exposing an unhandled edge case that definitely fails on current code."
            )

        user_prompt += f"\nWrite the complete runnable Rust test module below:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        raw_test = response.choices[0].message.content or ""
        cleaned = re.sub(r"^```(?:rust|rs)?\s*", "", raw_test.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
        return cleaned.strip()

    def generate_rust_patch(
        self,
        context: RustContext,
        test_code: str,
        test_output: str,
        previous_attempts: list[dict[str, str]] | None = None,
    ) -> str:
        """Synthesize a minimal SEARCH/REPLACE patch for Rust code."""
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        system_prompt = (
            "You are an expert automated software repair agent for Rust.\n"
            "Your objective is to generate a minimal, targeted patch to fix the failing Rust test.\n\n"
            "STRICT OUTPUT FORMAT RULES:\n"
            "1. Never output unified diffs.\n"
            "2. Output ONLY SEARCH/REPLACE blocks formatted exactly as:\n"
            "<<<<<<< SEARCH\n"
            "[exact matching original Rust source code]\n"
            "=======\n"
            "[replacement Rust source code]\n"
            ">>>>>>>\n"
            "3. The SEARCH block must match existing lines in the target file exactly, including whitespace.\n"
            "4. Keep the modification footprint minimal. Fix only what is necessary to pass the test.\n"
            "5. Do NOT include extraneous markdown explanations.\n"
        )

        guidelines = load_project_guidelines()
        if guidelines:
            system_prompt += f"\nProject Invariants & Coding Guidelines:\n{guidelines}\n"

        user_prompt = (
            f"File to patch: {context.file_path}\n"
            f"Target: {context.target_name}\n"
            f"Enclosing Type: {context.enclosing_type or 'None'}\n\n"
            f"Target Method Code:\n```rust\n{context.function_code}\n```\n\n"
            f"Full File Content:\n```rust\n{context.full_source}\n```\n\n"
            f"Failing Rust Test:\n```rust\n{test_code}\n```\n\n"
            f"Cargo Test Failure Output:\n```text\n{test_output}\n```\n\n"
        )

        if getattr(context, "api_contract", None):
            user_prompt += f"{context.api_contract}\n\n"

        if previous_attempts:
            user_prompt += "\n--- PREVIOUS FAILED PATCH ATTEMPTS ---\n"
            for idx, attempt in enumerate(previous_attempts, start=1):
                user_prompt += (
                    f"Attempt #{idx}:\n"
                    f"Generated Patch:\n{attempt.get('patch', '')}\n"
                    f"Failure / Error:\n{attempt.get('error', '')}\n\n"
                )
            user_prompt += "Analyze why the previous patch failed, fix the flaws, and output a valid SEARCH/REPLACE block:\n"
        else:
            user_prompt += "Generate the minimal SEARCH/REPLACE block to fix this issue:"

        response = self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )

        patch_output = response.choices[0].message.content or ""
        cleaned = patch_output.replace("```text", "").replace("```rust", "").replace("```rs", "").replace("```", "").strip()
        return cleaned
