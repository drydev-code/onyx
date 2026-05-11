"""Tests for the Claude Code CLI LLM provider.

Covers:
- invoke() command construction (permission flag, disallowed tools, stdin)
- invoke() JSON response parsing (text + thinking + usage)
- stream() command construction (verbose, stream-json, partial messages)
- stream() stream_event dispatch: thinking, text, tool_use (bridged + built-in)
- stream() input_json_delta accumulation
- stream() assistant-snapshot dedup + tool routing
- Bridge routing: WebSearch (bridged) yields delta.tool_calls; Bash (built-in)
  yields reasoning markdown
- Disable-builtin-tools toggle on/off
"""

import json
import subprocess
from io import StringIO
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.llm.claude_code_cli import _CLAUDE_CODE_TOOL_BRIDGE
from onyx.llm.claude_code_cli import _DISABLED_BUILTIN_TOOLS
from onyx.llm.claude_code_cli import _format_builtin_tool_markdown
from onyx.llm.claude_code_cli import _messages_to_prompt
from onyx.llm.claude_code_cli import ClaudeCodeCLI
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import AssistantMessage
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cli(
    model: str = "claude-sonnet-4-20250514",
    custom_config: dict[str, str] | None = None,
    timeout: int | None = None,
) -> ClaudeCodeCLI:
    return ClaudeCodeCLI(
        model_name=model,
        api_key="test-key",
        custom_config=custom_config,
        timeout=timeout,
    )


def _make_proc(stdout_text: str) -> MagicMock:
    """Build a mock subprocess.Popen return value."""
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = StringIO(stdout_text)
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = ""
    proc.wait.return_value = None
    proc.returncode = 0
    return proc


def _stream_event(inner: dict) -> str:
    return json.dumps({"type": "stream_event", "event": inner})


def _run_stream(
    cli: ClaudeCodeCLI, events: list[str]
) -> list[ModelResponseStream]:
    """Drive cli.stream() against a canned sequence of JSONL events."""
    stdout = "\n".join(events) + ("\n" if events else "")
    proc = _make_proc(stdout)
    with patch(
        "onyx.llm.claude_code_cli.subprocess.Popen", return_value=proc
    ):
        with patch(
            "onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config",
            return_value=None,
        ):
            return list(cli.stream([UserMessage(content="hello")]))


# ---------------------------------------------------------------------------
# invoke() command construction
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
def test_invoke_command_uses_dangerously_skip_permissions(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello")])

    cmd = mock_run.call_args[0][0]
    assert "--dangerously-skip-permissions" in cmd


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value="/tmp/mcp.json")
def test_invoke_command_disables_builtin_tools_when_mcp_available(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello")])

    cmd = mock_run.call_args[0][0]
    assert "--disallowedTools" in cmd
    idx = cmd.index("--disallowedTools")
    assert cmd[idx + 1] == _DISABLED_BUILTIN_TOOLS


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
def test_invoke_command_keeps_builtin_tools_when_no_mcp(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    """When MCP is unavailable, built-in WebSearch/WebFetch must stay enabled
    so the model still has web-search capability."""
    mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello")])

    cmd = mock_run.call_args[0][0]
    assert "--disallowedTools" not in cmd


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value="/tmp/mcp.json")
def test_invoke_command_disable_builtin_tools_toggle_off(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
    cli = _make_cli(
        custom_config={"claude_code_disable_builtin_tools": "false"}
    )

    cli.invoke([UserMessage(content="hello")])

    cmd = mock_run.call_args[0][0]
    assert "--disallowedTools" not in cmd


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
def test_invoke_command_reads_prompt_from_stdin(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello world")])

    cmd = mock_run.call_args[0][0]
    assert "-p" in cmd
    idx = cmd.index("-p")
    assert cmd[idx + 1] == "-"
    # And the prompt was passed via input=
    kwargs = mock_run.call_args[1]
    assert kwargs.get("input") == "hello world"


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
def test_invoke_command_uses_json_output_format(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello")])

    cmd = mock_run.call_args[0][0]
    idx = cmd.index("--output-format")
    assert cmd[idx + 1] == "json"


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
def test_invoke_does_not_pass_max_tokens(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    """--max-tokens is not a valid Claude CLI flag and must never be passed."""
    mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello")], max_tokens=1024)

    cmd = mock_run.call_args[0][0]
    assert "--max-tokens" not in cmd


# ---------------------------------------------------------------------------
# invoke() JSON response parsing
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
def test_invoke_parses_json_text_and_thinking(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    raw = json.dumps(
        {
            "content": [
                {"type": "thinking", "thinking": "let me think"},
                {"type": "text", "text": "the answer is 42"},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 9},
        }
    )
    mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")
    cli = _make_cli()

    result = cli.invoke([UserMessage(content="hi")])

    assert isinstance(result, ModelResponse)
    assert result.choice.message.content == "the answer is 42"
    assert result.choice.message.reasoning_content == "let me think"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 5
    assert result.usage.completion_tokens == 9
    assert result.usage.total_tokens == 14


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
def test_invoke_fallback_when_output_not_json(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.return_value = MagicMock(
        returncode=0, stdout="not valid json", stderr=""
    )
    cli = _make_cli()

    result = cli.invoke([UserMessage(content="hi")])

    assert result.choice.message.content == "not valid json"
    assert result.choice.message.reasoning_content is None


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
def test_invoke_nonzero_exit_raises_runtime_error(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="something went wrong"
    )
    cli = _make_cli()

    with pytest.raises(RuntimeError, match="Claude Code CLI error"):
        cli.invoke([UserMessage(content="hi")])


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
def test_invoke_timeout_raises_timeout_error(
    _mock_mcp: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)
    cli = _make_cli()

    with pytest.raises(TimeoutError, match="timed out"):
        cli.invoke([UserMessage(content="hi")])


# ---------------------------------------------------------------------------
# stream() command construction
# ---------------------------------------------------------------------------


def test_stream_command_has_phase2_flags() -> None:
    proc = _make_proc("")
    with patch(
        "onyx.llm.claude_code_cli.subprocess.Popen", return_value=proc
    ) as mock_popen:
        with patch(
            "onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config",
            return_value="/tmp/mcp.json",
        ):
            list(_make_cli().stream([UserMessage(content="hi")]))

    cmd = mock_popen.call_args[0][0]
    assert "--dangerously-skip-permissions" in cmd
    assert "--verbose" in cmd
    assert "--include-partial-messages" in cmd
    assert "--disallowedTools" in cmd
    idx = cmd.index("--output-format")
    assert cmd[idx + 1] == "stream-json"
    # Prompt is piped via stdin
    idx = cmd.index("-p")
    assert cmd[idx + 1] == "-"


def test_stream_command_toggle_off_drops_disallowed_tools() -> None:
    proc = _make_proc("")
    cli = _make_cli(
        custom_config={"claude_code_disable_builtin_tools": "false"}
    )
    with patch(
        "onyx.llm.claude_code_cli.subprocess.Popen", return_value=proc
    ) as mock_popen:
        with patch(
            "onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config",
            return_value=None,
        ):
            list(cli.stream([UserMessage(content="hi")]))

    cmd = mock_popen.call_args[0][0]
    assert "--disallowedTools" not in cmd


# ---------------------------------------------------------------------------
# stream() thinking and text deltas
# ---------------------------------------------------------------------------


def test_stream_emits_thinking_as_reasoning_content() -> None:
    cli = _make_cli()
    events = [
        _stream_event({"type": "message_start", "message": {"id": "m1"}}),
        _stream_event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            }
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "hmm "},
            }
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "ok."},
            }
        ),
        _stream_event({"type": "content_block_stop", "index": 0}),
    ]
    chunks = _run_stream(cli, events)

    reasoning = [
        c.choice.delta.reasoning_content
        for c in chunks
        if c.choice.delta.reasoning_content
    ]
    assert "".join(reasoning) == "hmm ok."


def test_stream_emits_text_as_content() -> None:
    cli = _make_cli()
    events = [
        _stream_event({"type": "message_start", "message": {"id": "m1"}}),
        _stream_event(
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            }
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "Hello "},
            }
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "world"},
            }
        ),
        _stream_event({"type": "content_block_stop", "index": 1}),
    ]
    chunks = _run_stream(cli, events)

    text = [c.choice.delta.content for c in chunks if c.choice.delta.content]
    assert "".join(text) == "Hello world"


# ---------------------------------------------------------------------------
# stream() tool_use — bridged vs built-in
# ---------------------------------------------------------------------------


def test_stream_bridged_tool_yields_tool_calls_not_reasoning() -> None:
    """WebSearch is in the bridge -> delta.tool_calls, NO reasoning header."""
    cli = _make_cli()
    events = [
        _stream_event({"type": "message_start", "message": {"id": "m1"}}),
        _stream_event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_01",
                    "name": "WebSearch",
                    "input": {},
                },
            }
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query"',
                },
            }
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": ': "weather"}',
                },
            }
        ),
        _stream_event({"type": "content_block_stop", "index": 0}),
    ]
    chunks = _run_stream(cli, events)

    # Bridged path: NO reasoning_content header, just one tool_calls delta.
    reasoning = [
        c for c in chunks if c.choice.delta.reasoning_content
    ]
    assert reasoning == [], (
        "Bridged tool must NOT emit reasoning markdown -- it uses chip UI"
    )

    tool_call_chunks = [c for c in chunks if c.choice.delta.tool_calls]
    assert len(tool_call_chunks) == 1
    tc = tool_call_chunks[0].choice.delta.tool_calls[0]
    assert tc.function is not None
    assert tc.function.name == "WebSearch"
    assert tc.function.arguments == '{"query": "weather"}'
    assert tc.id == "toolu_01"


def test_stream_builtin_tool_yields_reasoning_markdown() -> None:
    """Bash is NOT in the bridge -> reasoning markdown, no tool_calls."""
    cli = _make_cli()
    events = [
        _stream_event({"type": "message_start", "message": {"id": "m1"}}),
        _stream_event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_bash",
                    "name": "Bash",
                    "input": {},
                },
            }
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"command": "ls"}',
                },
            }
        ),
        _stream_event({"type": "content_block_stop", "index": 0}),
    ]
    chunks = _run_stream(cli, events)

    tool_calls = [c for c in chunks if c.choice.delta.tool_calls]
    assert tool_calls == [], (
        "Non-bridged tool must NOT emit delta.tool_calls (would cause "
        "double-execution)"
    )

    reasoning_chunks = [
        c.choice.delta.reasoning_content
        for c in chunks
        if c.choice.delta.reasoning_content
    ]
    combined = "".join(reasoning_chunks)
    assert "💻" in combined  # Bash icon
    assert "`Bash`" in combined
    assert '"command": "ls"' in combined or '"command":"ls"' in combined


def test_stream_bridged_mcp_onyx_tool_yields_tool_calls() -> None:
    cli = _make_cli()
    events = [
        _stream_event({"type": "message_start", "message": {"id": "m1"}}),
        _stream_event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_mcp",
                    "name": "mcp__onyx__search_indexed_documents",
                    "input": {},
                },
            }
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query": "onboarding"}',
                },
            }
        ),
        _stream_event({"type": "content_block_stop", "index": 0}),
    ]
    chunks = _run_stream(cli, events)

    tool_call_chunks = [c for c in chunks if c.choice.delta.tool_calls]
    assert len(tool_call_chunks) == 1
    tc = tool_call_chunks[0].choice.delta.tool_calls[0]
    assert tc.function is not None
    assert tc.function.name == "mcp__onyx__search_indexed_documents"
    assert tc.function.arguments == '{"query": "onboarding"}'


# ---------------------------------------------------------------------------
# stream() final chunk usage + stop_reason
# ---------------------------------------------------------------------------


def test_stream_final_chunk_carries_usage_and_stop_reason() -> None:
    cli = _make_cli()
    events = [
        _stream_event({"type": "message_start", "message": {"id": "m1"}}),
        _stream_event(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"input_tokens": 3, "output_tokens": 7},
            }
        ),
    ]
    chunks = _run_stream(cli, events)

    assert chunks[-1].choice.finish_reason == "tool_use"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.prompt_tokens == 3
    assert chunks[-1].usage.completion_tokens == 7


def test_stream_final_chunk_defaults_to_stop() -> None:
    cli = _make_cli()
    chunks = _run_stream(cli, [])

    assert chunks[-1].choice.finish_reason == "stop"


# ---------------------------------------------------------------------------
# stream() assistant-snapshot fallback
# ---------------------------------------------------------------------------


def test_stream_assistant_snapshot_dedup_skips_streamed_text() -> None:
    """If stream_event already delivered text for msg_id, snapshot skips it."""
    cli = _make_cli()
    events = [
        # Stream path delivers "Hello"
        _stream_event({"type": "message_start", "message": {"id": "m1"}}),
        _stream_event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello"},
            }
        ),
        _stream_event({"type": "content_block_stop", "index": 0}),
        # Then a top-level assistant snapshot arrives with the SAME msg id
        # and the same text. Dedup must skip it.
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "content": [{"type": "text", "text": "Hello"}],
                },
            }
        ),
    ]
    chunks = _run_stream(cli, events)

    text_chunks = [c for c in chunks if c.choice.delta.content]
    # Should have exactly one text chunk (from stream path), not two.
    assert len(text_chunks) == 1
    assert text_chunks[0].choice.delta.content == "Hello"


def test_stream_assistant_snapshot_bridged_tool_use() -> None:
    """Snapshot tool_use for a bridged tool yields delta.tool_calls once."""
    cli = _make_cli()
    events = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m_snapshot",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_snap",
                            "name": "WebFetch",
                            "input": {"url": "https://example.com"},
                        }
                    ],
                },
            }
        ),
    ]
    chunks = _run_stream(cli, events)

    tool_call_chunks = [c for c in chunks if c.choice.delta.tool_calls]
    assert len(tool_call_chunks) == 1
    tc = tool_call_chunks[0].choice.delta.tool_calls[0]
    assert tc.function is not None
    assert tc.function.name == "WebFetch"
    # Snapshot passes the full input dict -> JSON-encoded
    parsed = json.loads(tc.function.arguments or "{}")
    assert parsed == {"url": "https://example.com"}


# ---------------------------------------------------------------------------
# _format_builtin_tool_markdown helper
# ---------------------------------------------------------------------------


def test_format_builtin_tool_markdown_uses_icon() -> None:
    md = _format_builtin_tool_markdown("Bash", '{"command": "ls"}')
    assert "💻" in md
    assert "`Bash`" in md
    assert '"command": "ls"' in md


def test_format_builtin_tool_markdown_unknown_tool() -> None:
    md = _format_builtin_tool_markdown("SomethingExotic", '{}')
    assert "🔧" in md
    assert "`SomethingExotic`" in md


def test_format_builtin_tool_markdown_malformed_args() -> None:
    md = _format_builtin_tool_markdown("Bash", "{not valid")
    # Still renders, just without pretty-printing
    assert "`Bash`" in md
    assert "{not valid" in md


# ---------------------------------------------------------------------------
# Bridge map contents
# ---------------------------------------------------------------------------


def test_bridge_map_includes_expected_tools() -> None:
    assert "WebSearch" in _CLAUDE_CODE_TOOL_BRIDGE
    assert "WebFetch" in _CLAUDE_CODE_TOOL_BRIDGE
    assert "Read" in _CLAUDE_CODE_TOOL_BRIDGE
    assert "mcp__onyx__search_indexed_documents" in _CLAUDE_CODE_TOOL_BRIDGE


def test_cli_config_exposes_bridge() -> None:
    cli = _make_cli()
    assert cli.config.cli_tool_bridge == _CLAUDE_CODE_TOOL_BRIDGE


# ---------------------------------------------------------------------------
# _messages_to_prompt()
# ---------------------------------------------------------------------------


def test_messages_to_prompt_with_roles() -> None:
    messages = [
        SystemMessage(content="You are helpful."),
        UserMessage(content="What is 2+2?"),
        AssistantMessage(content="4"),
    ]

    result = _messages_to_prompt(messages)

    assert "[System]: You are helpful." in result
    assert "What is 2+2?" in result
    assert "[Assistant]: 4" in result


def test_messages_to_prompt_single_message() -> None:
    msg = UserMessage(content="single message")
    result = _messages_to_prompt(msg)
    assert result == "single message"


# ---------------------------------------------------------------------------
# Unsupported features warning
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.ClaudeCodeCLI._write_mcp_config", return_value=None)
@patch("onyx.llm.claude_code_cli.logger")
def test_tools_warning_logged(
    mock_logger: MagicMock,
    _mock_mcp: MagicMock,
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello")], tools=[{"type": "function"}])

    mock_logger.warning.assert_called()
    warning_msgs = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert any("does not support tool calling" in m for m in warning_msgs)
