"""Tests for the Claude Code CLI LLM provider."""

import json
import subprocess
from io import StringIO
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.llm.claude_code_cli import _messages_to_prompt
from onyx.llm.claude_code_cli import ClaudeCodeCLI
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import AssistantMessage
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage


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


# ---------------------------------------------------------------------------
# invoke() command construction
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
def test_invoke_command_construction(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello")])

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "claude"
    assert "--print" in cmd
    assert "--output-format" in cmd
    idx = cmd.index("--output-format")
    assert cmd[idx + 1] == "text"
    assert "--model" in cmd
    assert "claude-sonnet-4-20250514" in cmd
    assert "-p" in cmd


# ---------------------------------------------------------------------------
# invoke() with max_tokens
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
def test_invoke_with_max_tokens(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello")], max_tokens=1024)

    cmd = mock_run.call_args[0][0]
    assert "--max-tokens" in cmd
    idx = cmd.index("--max-tokens")
    assert cmd[idx + 1] == "1024"


# ---------------------------------------------------------------------------
# invoke() successful response
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
def test_invoke_successful_response(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=0, stdout="This is the response text.", stderr=""
    )
    cli = _make_cli()

    result = cli.invoke([UserMessage(content="hello")])

    assert isinstance(result, ModelResponse)
    assert result.id.startswith("cli-")
    assert result.choice.finish_reason == "stop"
    assert result.choice.message.content == "This is the response text."
    assert result.choice.message.role == "assistant"
    assert result.usage is not None
    assert result.usage.total_tokens == 0


# ---------------------------------------------------------------------------
# invoke() non-zero exit
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
def test_invoke_nonzero_exit_raises_runtime_error(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="Something went wrong"
    )
    cli = _make_cli()

    with pytest.raises(RuntimeError, match="Claude Code CLI error"):
        cli.invoke([UserMessage(content="hello")])


# ---------------------------------------------------------------------------
# invoke() timeout
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
def test_invoke_timeout_raises_timeout_error(mock_run: MagicMock) -> None:
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)
    cli = _make_cli()

    with pytest.raises(TimeoutError, match="timed out"):
        cli.invoke([UserMessage(content="hello")])


# ---------------------------------------------------------------------------
# invoke() missing binary
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
def test_invoke_missing_binary_raises_runtime_error(mock_run: MagicMock) -> None:
    mock_run.side_effect = FileNotFoundError()
    cli = _make_cli()

    with pytest.raises(RuntimeError, match="not found"):
        cli.invoke([UserMessage(content="hello")])


# ---------------------------------------------------------------------------
# stream() command construction
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.Popen")
def test_stream_command_construction(mock_popen: MagicMock) -> None:
    proc = MagicMock()
    proc.stdout = StringIO("")
    proc.stderr = MagicMock()
    proc.wait.return_value = None
    proc.returncode = 0
    mock_popen.return_value = proc
    cli = _make_cli()

    # Consume the generator to trigger Popen call
    list(cli.stream([UserMessage(content="hello")]))

    cmd = mock_popen.call_args[0][0]
    assert "--print" in cmd
    assert "--output-format" in cmd
    idx = cmd.index("--output-format")
    assert cmd[idx + 1] == "stream-json"
    assert "--model" in cmd
    assert "-p" in cmd


# ---------------------------------------------------------------------------
# stream() text output parsing
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.Popen")
def test_stream_plain_text_output(mock_popen: MagicMock) -> None:
    proc = MagicMock()
    proc.stdout = StringIO("Hello\nWorld\n")
    proc.stderr = MagicMock()
    proc.wait.return_value = None
    proc.returncode = 0
    mock_popen.return_value = proc
    cli = _make_cli()

    chunks = list(cli.stream([UserMessage(content="hello")]))

    assert len(chunks) >= 3  # "Hello", "World", final stop chunk
    for chunk in chunks:
        assert isinstance(chunk, ModelResponseStream)
    # First two are text content
    assert chunks[0].choice.delta.content == "Hello"
    assert chunks[1].choice.delta.content == "World"


# ---------------------------------------------------------------------------
# stream() JSON output parsing
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.Popen")
def test_stream_json_output_parsing(mock_popen: MagicMock) -> None:
    events = [
        json.dumps({"type": "text", "text": "chunk1"}),
        json.dumps({"type": "content_block_delta", "delta": {"text": "chunk2"}}),
        json.dumps({"type": "assistant", "message": "chunk3"}),
    ]
    proc = MagicMock()
    proc.stdout = StringIO("\n".join(events) + "\n")
    proc.stderr = MagicMock()
    proc.wait.return_value = None
    proc.returncode = 0
    mock_popen.return_value = proc
    cli = _make_cli()

    chunks = list(cli.stream([UserMessage(content="hello")]))

    # 3 content chunks + 1 final stop chunk
    assert len(chunks) == 4
    assert chunks[0].choice.delta.content == "chunk1"
    assert chunks[1].choice.delta.content == "chunk2"
    assert chunks[2].choice.delta.content == "chunk3"


# ---------------------------------------------------------------------------
# stream() final chunk
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.Popen")
def test_stream_final_chunk_has_stop_finish_reason(mock_popen: MagicMock) -> None:
    proc = MagicMock()
    proc.stdout = StringIO("some text\n")
    proc.stderr = MagicMock()
    proc.wait.return_value = None
    proc.returncode = 0
    mock_popen.return_value = proc
    cli = _make_cli()

    chunks = list(cli.stream([UserMessage(content="hello")]))

    last = chunks[-1]
    assert last.choice.finish_reason == "stop"
    assert last.choice.delta.content is None
    assert last.usage is not None


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
    # User messages should not have a role prefix
    assert "[User]" not in result


def test_messages_to_prompt_single_message() -> None:
    msg = UserMessage(content="single message")

    result = _messages_to_prompt(msg)

    assert result == "single message"


def test_messages_to_prompt_content_blocks() -> None:
    """Content blocks like [{"type": "text", "text": "..."}] are flattened."""
    msg = UserMessage(content=[{"type": "text", "text": "block content"}])  # type: ignore[arg-type]

    result = _messages_to_prompt([msg])

    assert "block content" in result


# ---------------------------------------------------------------------------
# Custom CLI path
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
def test_custom_cli_path(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    cli = _make_cli(custom_config={"cli_path": "/usr/local/bin/claude-custom"})

    cli.invoke([UserMessage(content="hello")])

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "/usr/local/bin/claude-custom"


# ---------------------------------------------------------------------------
# Unsupported features warning
# ---------------------------------------------------------------------------


@patch("onyx.llm.claude_code_cli.subprocess.run")
@patch("onyx.llm.claude_code_cli.logger")
def test_tools_warning_logged(mock_logger: MagicMock, mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    cli = _make_cli()

    cli.invoke([UserMessage(content="hello")], tools=[{"type": "function"}])

    mock_logger.warning.assert_called_once()
    warning_msg = mock_logger.warning.call_args[0][0]
    assert "does not support tool calling" in warning_msg
