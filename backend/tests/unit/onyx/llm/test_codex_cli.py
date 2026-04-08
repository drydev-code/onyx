"""Tests for the OpenAI Codex CLI LLM provider.

Covers:
- Command construction (--json, disable-web-search toggle, instructions)
- Event dispatch for thread.started, turn.started, turn.completed
- item.started command_execution -> reasoning markdown
- item.completed command_execution -> reasoning markdown with exit code
- item.completed agent_message -> delta.content
- item.completed error (known deprecation) -> silently skipped
- item.completed error (other) -> reasoning markdown with warning
- Output truncation for long command results
- Final chunk usage from turn.completed
- Disable-builtin-tools toggle on/off
"""

import json
from io import StringIO
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.llm.codex_cli import _build_codex_usage
from onyx.llm.codex_cli import _CODEX_DISABLE_WEB_TOOL_FLAGS
from onyx.llm.codex_cli import _CODEX_OUTPUT_MAX_CHARS
from onyx.llm.codex_cli import _format_codex_command_result
from onyx.llm.codex_cli import _format_codex_command_start
from onyx.llm.codex_cli import CodexCLI
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import UserMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cli(custom_config: dict[str, str] | None = None) -> CodexCLI:
    return CodexCLI(
        model_name="gpt-5-codex-mini",
        custom_config=custom_config,
        timeout=60,
    )


def _make_proc(stdout_text: str) -> MagicMock:
    proc = MagicMock()
    proc.stdout = StringIO(stdout_text)
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = ""
    proc.wait.return_value = None
    proc.returncode = 0
    return proc


def _run_stream(
    cli: CodexCLI, events: list[dict]
) -> list[ModelResponseStream]:
    """Drive cli.stream() against a canned sequence of JSONL events."""
    stdout = "\n".join(json.dumps(e) for e in events) + (
        "\n" if events else ""
    )
    proc = _make_proc(stdout)
    with patch("onyx.llm.codex_cli.subprocess.Popen", return_value=proc):
        with patch("onyx.llm.codex_cli.CodexCLI._setup_auth", return_value=None):
            return list(cli.stream([UserMessage(content="hi")]))


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


def test_stream_command_uses_json_flag() -> None:
    proc = _make_proc("")
    with patch(
        "onyx.llm.codex_cli.subprocess.Popen", return_value=proc
    ) as mock_popen:
        with patch("onyx.llm.codex_cli.CodexCLI._setup_auth", return_value=None):
            list(_make_cli().stream([UserMessage(content="hi")]))

    cmd = mock_popen.call_args[0][0]
    assert "--json" in cmd
    assert "exec" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "--skip-git-repo-check" in cmd
    assert "--ephemeral" in cmd


def test_stream_command_disables_web_search_by_default() -> None:
    proc = _make_proc("")
    with patch(
        "onyx.llm.codex_cli.subprocess.Popen", return_value=proc
    ) as mock_popen:
        with patch("onyx.llm.codex_cli.CodexCLI._setup_auth", return_value=None):
            list(_make_cli().stream([UserMessage(content="hi")]))

    cmd = mock_popen.call_args[0][0]
    # _CODEX_DISABLE_WEB_TOOL_FLAGS = ["-c", 'web_search="disabled"']
    assert _CODEX_DISABLE_WEB_TOOL_FLAGS[0] in cmd
    assert _CODEX_DISABLE_WEB_TOOL_FLAGS[1] in cmd


def test_stream_command_toggle_off_keeps_web_search() -> None:
    proc = _make_proc("")
    cli = _make_cli(
        custom_config={"openai_codex_disable_builtin_tools": "false"}
    )
    with patch(
        "onyx.llm.codex_cli.subprocess.Popen", return_value=proc
    ) as mock_popen:
        with patch("onyx.llm.codex_cli.CodexCLI._setup_auth", return_value=None):
            list(cli.stream([UserMessage(content="hi")]))

    cmd = mock_popen.call_args[0][0]
    assert 'web_search="disabled"' not in cmd


def test_stream_command_includes_instructions() -> None:
    proc = _make_proc("")
    with patch(
        "onyx.llm.codex_cli.subprocess.Popen", return_value=proc
    ) as mock_popen:
        with patch("onyx.llm.codex_cli.CodexCLI._setup_auth", return_value=None):
            list(_make_cli().stream([UserMessage(content="hi")]))

    cmd = mock_popen.call_args[0][0]
    # There should be a -c instructions="..." somewhere
    c_indices = [i for i, v in enumerate(cmd) if v == "-c"]
    instructions_found = any(
        cmd[i + 1].startswith("instructions=") for i in c_indices
    )
    assert instructions_found


# ---------------------------------------------------------------------------
# Event dispatch
# ---------------------------------------------------------------------------


def test_stream_thread_and_turn_started_produce_no_output() -> None:
    cli = _make_cli()
    chunks = _run_stream(
        cli,
        [
            {"type": "thread.started", "thread_id": "tid1"},
            {"type": "turn.started"},
        ],
    )

    # Only the final stop chunk
    assert len(chunks) == 1
    assert chunks[-1].choice.finish_reason == "stop"


def test_stream_command_started_yields_reasoning_header() -> None:
    cli = _make_cli()
    chunks = _run_stream(
        cli,
        [
            {"type": "thread.started", "thread_id": "t"},
            {"type": "turn.started"},
            {
                "type": "item.started",
                "item": {
                    "id": "item_1",
                    "type": "command_execution",
                    "command": "ls /tmp",
                    "status": "in_progress",
                },
            },
        ],
    )

    reasoning_chunks = [
        c.choice.delta.reasoning_content
        for c in chunks
        if c.choice.delta.reasoning_content
    ]
    joined = "".join(reasoning_chunks)
    assert "💻" in joined
    assert "`Bash`" in joined
    assert "ls /tmp" in joined
    assert "*running...*" in joined


def test_stream_command_completed_yields_reasoning_result() -> None:
    cli = _make_cli()
    chunks = _run_stream(
        cli,
        [
            {"type": "thread.started", "thread_id": "t"},
            {"type": "turn.started"},
            {
                "type": "item.started",
                "item": {
                    "id": "item_1",
                    "type": "command_execution",
                    "command": "ls /tmp",
                    "status": "in_progress",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "command_execution",
                    "command": "ls /tmp",
                    "aggregated_output": "file1\nfile2\n",
                    "exit_code": 0,
                    "status": "completed",
                },
            },
        ],
    )

    reasoning_chunks = [
        c.choice.delta.reasoning_content
        for c in chunks
        if c.choice.delta.reasoning_content
    ]
    joined = "".join(reasoning_chunks)
    assert "file1" in joined
    assert "file2" in joined
    assert "Exit:" in joined
    assert "0" in joined
    assert "completed" in joined


def test_stream_agent_message_yields_content() -> None:
    cli = _make_cli()
    chunks = _run_stream(
        cli,
        [
            {"type": "thread.started", "thread_id": "t"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "agent_message",
                    "text": "Hello there!",
                },
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        ],
    )

    text_chunks = [
        c.choice.delta.content for c in chunks if c.choice.delta.content
    ]
    assert text_chunks == ["Hello there!"]


def test_stream_deprecated_openai_base_url_error_is_silent() -> None:
    cli = _make_cli()
    chunks = _run_stream(
        cli,
        [
            {"type": "thread.started", "thread_id": "t"},
            {
                "type": "item.completed",
                "item": {
                    "id": "item_0",
                    "type": "error",
                    "message": (
                        "`OPENAI_BASE_URL` is deprecated. "
                        "Set `openai_base_url` in config.toml instead."
                    ),
                },
            },
        ],
    )

    reasoning = [c for c in chunks if c.choice.delta.reasoning_content]
    text = [c for c in chunks if c.choice.delta.content]
    # Neither reasoning nor text -- error was silently skipped.
    assert reasoning == []
    assert text == []


def test_stream_other_error_yields_warning_reasoning() -> None:
    cli = _make_cli()
    chunks = _run_stream(
        cli,
        [
            {
                "type": "item.completed",
                "item": {
                    "id": "item_x",
                    "type": "error",
                    "message": "Something bad happened",
                },
            },
        ],
    )

    reasoning = [
        c.choice.delta.reasoning_content
        for c in chunks
        if c.choice.delta.reasoning_content
    ]
    assert any("⚠️" in r for r in reasoning)
    assert any("Something bad happened" in r for r in reasoning)


def test_stream_turn_completed_populates_usage() -> None:
    cli = _make_cli()
    chunks = _run_stream(
        cli,
        [
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 25,
                    "cached_input_tokens": 20,
                },
            },
        ],
    )

    assert chunks[-1].choice.finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.prompt_tokens == 100
    assert chunks[-1].usage.completion_tokens == 25
    assert chunks[-1].usage.total_tokens == 125
    assert chunks[-1].usage.cache_read_input_tokens == 20


def test_stream_unknown_item_type_yields_generic_marker() -> None:
    cli = _make_cli()
    chunks = _run_stream(
        cli,
        [
            {
                "type": "item.completed",
                "item": {
                    "id": "item_u",
                    "type": "mystery_item",
                    "foo": "bar",
                },
            },
        ],
    )

    reasoning = [
        c.choice.delta.reasoning_content
        for c in chunks
        if c.choice.delta.reasoning_content
    ]
    joined = "".join(reasoning)
    assert "mystery_item" in joined
    assert "foo" in joined


def test_stream_long_output_gets_truncated() -> None:
    cli = _make_cli()
    long_output = "x" * (_CODEX_OUTPUT_MAX_CHARS + 500)
    chunks = _run_stream(
        cli,
        [
            {
                "type": "item.started",
                "item": {
                    "id": "item_1",
                    "type": "command_execution",
                    "command": "echo x",
                    "status": "in_progress",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "command_execution",
                    "command": "echo x",
                    "aggregated_output": long_output,
                    "exit_code": 0,
                    "status": "completed",
                },
            },
        ],
    )

    reasoning = "".join(
        c.choice.delta.reasoning_content or ""
        for c in chunks
        if c.choice.delta.reasoning_content
    )
    assert "truncated" in reasoning
    assert str(len(long_output)) in reasoning


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_build_codex_usage_maps_fields() -> None:
    usage = _build_codex_usage(
        {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 3}
    )
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15
    assert usage.cache_read_input_tokens == 3


def test_build_codex_usage_handles_missing_fields() -> None:
    usage = _build_codex_usage({})
    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.total_tokens == 0
    assert usage.cache_read_input_tokens == 0


def test_format_codex_command_start_shows_command() -> None:
    md = _format_codex_command_start("ls /tmp")
    assert "💻" in md
    assert "ls /tmp" in md
    assert "running" in md


def test_format_codex_command_result_shows_exit_code() -> None:
    md = _format_codex_command_result("output text", 0, "completed")
    assert "Exit:" in md
    assert "0" in md
    assert "completed" in md
    assert "output text" in md


# ---------------------------------------------------------------------------
# Config exposes (empty) bridge
# ---------------------------------------------------------------------------


def test_codex_config_bridge_is_none_by_default() -> None:
    cli = _make_cli()
    # _CODEX_TOOL_BRIDGE is empty -> exposed as None so default LiteLLM
    # behavior applies (but there are no bridged tools to trigger anyway).
    assert cli.config.cli_tool_bridge is None
