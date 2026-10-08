from __future__ import annotations

import json
import unittest
from pathlib import Path

from lgt.summarizer import (
    SUMMARY_SCHEMA,
    CLISummarizer,
    SummaryOutputError,
    SummarizerError,
    parse_claude_output,
    parse_codex_output,
)


def make_summarizer(invoke, *, attempts: int = 2) -> CLISummarizer:
    return CLISummarizer(
        claude_command=["claude"],
        codex_command=["codex"],
        cwd="C:/workspace",
        timeout_seconds=2.5,
        attempts=attempts,
        claude_model="haiku",
        codex_model="codex-test",
        invoke=invoke,
    )


def codex_events(summary: str, *, finish: bool = True) -> str:
    events = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started", "turn_id": "turn-1"},
        {
            "type": "item.completed",
            "item": {"id": "item-1", "type": "agent_message", "text": json.dumps({"summary": summary})},
        },
    ]
    if finish:
        events.append({"type": "turn.completed", "turn_id": "turn-1"})
    return "\n".join(json.dumps(event) for event in events)


class CLISummarizerTests(unittest.IsolatedAsyncioTestCase):
    async def test_claude_print_json_wrapper_and_required_flags(self) -> None:
        invocations: list[tuple[list[str], str, str, float]] = []

        async def invoke(argv: list[str], cwd: str, prompt: str, timeout: float) -> str:
            invocations.append((argv, cwd, prompt, timeout))
            return json.dumps({
                "type": "result",
                "subtype": "success",
                "result": json.dumps({"summary": "  Compact checkpoint  "}),
            })

        result = await make_summarizer(invoke).summarize("Open task: finish the parser", 80)
        self.assertEqual(result, "Compact checkpoint")
        self.assertEqual(len(invocations), 1)
        argv, cwd, prompt, timeout = invocations[0]
        self.assertEqual(cwd, "C:/workspace")
        self.assertEqual(timeout, 2.5)
        self.assertEqual(argv[:4], ["claude", "-p", "--model", "haiku"])
        self.assertIn("--output-format", argv)
        self.assertIn("--json-schema", argv)
        schema = json.loads(argv[argv.index("--json-schema") + 1])
        self.assertEqual(schema, SUMMARY_SCHEMA)
        tools_index = argv.index("--tools")
        self.assertEqual(argv[tools_index + 1], "")
        self.assertIn("--no-session-persistence", argv)
        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertIn("80 characters", prompt)
        self.assertIn("Open task: finish the parser", prompt)

    async def test_codex_fallback_uses_ephemeral_schema_and_requires_completed_message(self) -> None:
        invocations: list[tuple[list[str], str, str, float]] = []
        claude_calls = 0
        schema_paths: list[Path] = []

        async def invoke(argv: list[str], cwd: str, prompt: str, timeout: float) -> str:
            nonlocal claude_calls
            invocations.append((argv, cwd, prompt, timeout))
            if argv[0] == "claude":
                claude_calls += 1
                raise TimeoutError("injected timeout")

            schema_path = Path(argv[argv.index("--output-schema") + 1])
            schema_paths.append(schema_path)
            self.assertTrue(schema_path.is_file())
            self.assertEqual(json.loads(schema_path.read_text(encoding="utf-8")), SUMMARY_SCHEMA)
            return codex_events("Recovered checkpoint")

        result = await make_summarizer(invoke, attempts=2).summarize("Context", 80)
        self.assertEqual(result, "Recovered checkpoint")
        self.assertEqual(claude_calls, 2)
        self.assertEqual(len(invocations), 3)
        codex_argv = invocations[-1][0]
        self.assertEqual(codex_argv[:3], ["codex", "exec", "--ephemeral"])
        self.assertIn("--json", codex_argv)
        self.assertIn("--skip-git-repo-check", codex_argv)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", codex_argv)
        self.assertIn("--output-schema", codex_argv)
        self.assertEqual(codex_argv[codex_argv.index("-m") + 1], "codex-test")
        self.assertEqual(codex_argv[-1], "-")
        self.assertEqual(len(schema_paths), 1)
        self.assertFalse(schema_paths[0].exists())

    async def test_retry_counts_and_bad_codex_turn_fail_without_inventing_a_summary(self) -> None:
        invocations: list[list[str]] = []

        async def invoke(argv: list[str], _cwd: str, _prompt: str, _timeout: float) -> str:
            invocations.append(argv)
            if argv[0] == "claude":
                return json.dumps({"structured_output": {"summary": ""}})
            return codex_events("Never accepted", finish=False)

        with self.assertRaises(SummarizerError):
            await make_summarizer(invoke, attempts=2).summarize("Context", 80)
        self.assertEqual([argv[0] for argv in invocations], ["claude", "claude", "codex", "codex"])

    async def test_empty_or_overlong_summaries_are_rejected_and_prompt_limits_are_validated(self) -> None:
        with self.assertRaises(SummaryOutputError):
            parse_claude_output(json.dumps({"summary": "  "}), 10)
        with self.assertRaises(SummaryOutputError):
            parse_claude_output(json.dumps({"summary": "longer than limit"}), 4)
        with self.assertRaises(SummaryOutputError):
            parse_claude_output(json.dumps({"summary": "ok", "extra": True}), 10)
        with self.assertRaises(SummaryOutputError):
            parse_codex_output(codex_events("too long"), 3)

        calls = 0

        async def invoke(_argv: list[str], _cwd: str, _prompt: str, _timeout: float) -> str:
            nonlocal calls
            calls += 1
            return "{}"

        summarizer = make_summarizer(invoke)
        with self.assertRaises(ValueError):
            await summarizer.summarize("Context", 0)
        with self.assertRaises(ValueError):
            await summarizer.summarize("   ", 20)
        self.assertEqual(calls, 0)

    def test_codex_rejects_unknown_error_and_incomplete_output(self) -> None:
        with self.assertRaises(SummaryOutputError):
            parse_codex_output(json.dumps({"type": "future.event"}), 80)
        with self.assertRaises(SummaryOutputError):
            parse_codex_output(json.dumps({"type": "turn.failed", "error": "failed"}), 80)
        with self.assertRaises(SummaryOutputError):
            parse_codex_output(codex_events("valid JSON", finish=False), 80)


if __name__ == "__main__":
    unittest.main()
