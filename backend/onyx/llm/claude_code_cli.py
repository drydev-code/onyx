"""Claude Code CLI LLM provider.

Shells out to the `claude` CLI binary to generate completions.
This is NOT a LiteLLM-based provider; it uses subprocess directly.
"""

import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.llm.cli_tool_bridge import CATEGORY_FETCH
from onyx.llm.cli_tool_bridge import CATEGORY_FILE_READER
from onyx.llm.cli_tool_bridge import CATEGORY_INTERNAL_SEARCH
from onyx.llm.cli_tool_bridge import CATEGORY_INTERNET_SEARCH
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.llm.model_response import Choice
from onyx.llm.model_response import Delta
from onyx.llm.model_response import FunctionCall
from onyx.llm.model_response import Message
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice
from onyx.llm.model_response import Usage
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.well_known_providers.constants import CLAUDE_CODE_AUTH_MODE_KEY
from onyx.llm.well_known_providers.constants import CLAUDE_CODE_CLI_PATH_KEY
from onyx.llm.well_known_providers.constants import CLAUDE_CODE_CLI_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import (
    CLAUDE_CODE_DISABLE_BUILTIN_TOOLS_KEY,
)
from onyx.llm.well_known_providers.constants import CLAUDE_CODE_OAUTH_TOKEN_KEY
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DEFAULT_CLI_PATH = "claude"
_DEFAULT_TIMEOUT = 300

# Comma-separated list of Claude built-in tools to disable via
# --disallowedTools when the disable-builtin-tools toggle is on (the
# default). WebSearch and WebFetch are replaced by the Onyx MCP
# server's own search/fetch tools (auto-injected by
# mcp_config_builder.py), so disabling them avoids duplicate/divergent
# results. The agentic tools (Read, Bash, Grep, Glob, Write, Edit, Task,
# TodoWrite) stay enabled because Claude needs them to be useful and no
# Onyx equivalent exists.
_DISABLED_BUILTIN_TOOLS = "WebSearch,WebFetch"

# Icon map for rendering built-in Claude tools inside the Thinking panel
# as reasoning markdown. Bridged tools (Onyx MCP and Claude's own
# WebSearch/WebFetch/Read) skip this path entirely and render as chip UI
# via cli_tool_bridge.py.
_TOOL_ICON_MAP: dict[str, str] = {
    "WebSearch": "🔍",
    "WebFetch": "🌐",
    "Read": "📖",
    "Write": "📝",
    "Edit": "✏️",
    "Bash": "💻",
    "Grep": "🔎",
    "Glob": "📁",
    "Task": "🤖",
    "TodoWrite": "✅",
}

# Bridged (self-executed) tool name → cli_tool_bridge category. Keys are
# the tool names Claude Code CLI surfaces in its stream-json events:
# Claude's own built-ins use the bare PascalCase name, while MCP tools
# arrive with the mcp__<server>__<tool> prefix. When
# _disable_builtin_tools is on (default), WebSearch/WebFetch are blocked
# via --disallowedTools and the Onyx MCP entries below pick up the work.
# Admins who opt out of the disable flag can still benefit from the chip
# UI for WebSearch/WebFetch/Read because those entries route the
# built-ins through the bridge too.
_CLAUDE_CODE_TOOL_BRIDGE: dict[str, str] = {
    # Claude built-ins
    "WebSearch": CATEGORY_INTERNET_SEARCH,
    "WebFetch": CATEGORY_FETCH,
    "Read": CATEGORY_FILE_READER,
    # Onyx MCP server tools (auto-injected at mcp_config_builder.py:78-82).
    # The mcp__<server>__<tool> prefix follows the Anthropic MCP naming
    # convention; verify the exact key if additional Onyx MCP tools are
    # exposed.
    "mcp__onyx__search_indexed_documents": CATEGORY_INTERNAL_SEARCH,
}


def _format_builtin_tool_markdown(tool_name: str, args_json: str) -> str:
    """Structured markdown block for a non-bridged (built-in) tool use.

    Bridged tools use the chip UI path via ``cli_tool_bridge.py``; this
    helper is only used for Claude's internal agentic tools (Bash, Grep,
    Glob, Write, Edit, Task, TodoWrite, ...) that we surface in the
    Thinking panel via ``reasoning_content`` markdown.
    """
    icon = _TOOL_ICON_MAP.get(tool_name, "🔧")
    pretty = (args_json or "{}").strip() or "{}"
    try:
        parsed = json.loads(args_json) if args_json else {}
        pretty = json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, TypeError):
        pass
    return (
        f"\n\n---\n\n"
        f"### {icon} `{tool_name}`\n\n"
        f"```json\n{pretty}\n```\n"
    )


def _messages_to_prompt(prompt: LanguageModelInput) -> str:
    """Convert message list to a single text prompt for the CLI.

    Handles both LangChain message types (which dump ``type: human|system|ai``)
    and plain dicts following the OpenAI ``role: user|system|assistant``
    convention.  Without the LangChain ``type`` mapping, system prompts were
    silently being labelled as user content.
    """
    # Maps LangChain message ``type`` values to OpenAI-style ``role``s.
    LC_TYPE_TO_ROLE = {
        "human": "user",
        "system": "system",
        "ai": "assistant",
        "tool": "tool",
        "function": "function",
    }

    def _normalize(msg: object) -> tuple[str, str]:
        if hasattr(msg, "model_dump"):
            dumped = msg.model_dump(exclude_none=True)  # type: ignore[union-attr]
        elif isinstance(msg, dict):
            dumped = msg
        else:
            return ("user", str(msg))

        # Prefer ``role`` (OpenAI / dict style); fall back to LangChain ``type``.
        raw_role = dumped.get("role")
        if not raw_role:
            raw_role = LC_TYPE_TO_ROLE.get(dumped.get("type", ""), "user")
        content = dumped.get("content", "")
        if isinstance(content, list):
            # Handle content blocks (e.g., [{"type": "text", "text": "..."}])
            content = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return (raw_role, content if isinstance(content, str) else str(content))

    if isinstance(prompt, list):
        parts = []
        for msg in prompt:
            role, content = _normalize(msg)
            if not content:
                continue
            if role == "system":
                parts.append(f"[System]: {content}")
            elif role == "assistant":
                parts.append(f"[Assistant]: {content}")
            else:
                parts.append(content)
        return "\n\n".join(parts)

    _, content = _normalize(prompt)
    return content


def _make_usage() -> Usage:
    """Create a placeholder usage object (CLI doesn't report token counts)."""
    return Usage(
        completion_tokens=0,
        prompt_tokens=0,
        total_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


class ClaudeCodeCLI(LLM):
    """LLM implementation that shells out to the Claude Code CLI.

    Feature Support
    ---------------
    tools / tool_choice:
        WARNING only. The CLI does not support function calling, but callers
        may pass tools optimistically. The response will simply not contain
        tool calls. A warning is logged so operators can see when this occurs.

    structured_response_format:
        RAISES ``NotImplementedError``. Structured output is a hard contract
        -- callers that request it depend on the response conforming to a
        schema. Silently ignoring the request would produce free-form text
        that breaks downstream JSON parsing, so we fail fast instead.

    reasoning_effort:
        Silently ignored (no warning). This parameter is an advisory hint,
        not a requirement. Dropping it has no functional impact.

    user_identity:
        Silently ignored (no warning). This is metadata used for logging
        and attribution; it does not affect model behaviour.
    """

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        temperature: float | None = None,
        custom_config: dict[str, str] | None = None,
        timeout: int | None = None,
        max_input_tokens: int = 200000,
    ):
        self._model_name = model_name
        self._api_key = api_key
        self._temperature = temperature if temperature is not None else GEN_AI_TEMPERATURE
        self._custom_config = custom_config or {}
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._max_input_tokens = max_input_tokens
        self._cli_path = self._custom_config.get(CLAUDE_CODE_CLI_PATH_KEY, _DEFAULT_CLI_PATH)
        self._auth_mode = self._custom_config.get(CLAUDE_CODE_AUTH_MODE_KEY, "api_key")
        # Default ON: disable Claude's built-in WebSearch/WebFetch so the
        # Onyx MCP server's own tools (injected via --mcp-config) handle
        # web search/fetch instead. Admins can opt out by setting this
        # key to "false" in the provider's custom_config.
        self._disable_builtin_tools = (
            self._custom_config.get(
                CLAUDE_CODE_DISABLE_BUILTIN_TOOLS_KEY, "true"
            ).lower()
            != "false"
        )

    def _should_pass_api_key(self) -> bool:
        """Return True if we should pass --api-key to the CLI."""
        if self._auth_mode == "oauth":
            return False
        # Pass api_key when it is set and not the placeholder value
        return bool(self._api_key and self._api_key != "not-required")

    def _build_env(self) -> dict[str, str] | None:
        """Build environment dict for subprocess calls.

        When OAuth mode is active and an oauth_token is stored in
        custom_config, sets CLAUDE_CODE_OAUTH_TOKEN so the CLI
        authenticates via OAuth instead of an API key.

        Returns None when no environment modifications are needed
        (subprocess inherits the parent environment by default).
        """
        oauth_token = self._custom_config.get(CLAUDE_CODE_OAUTH_TOKEN_KEY)
        if self._auth_mode == "oauth" and oauth_token:
            env = os.environ.copy()
            env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
            return env
        return None

    def _build_mcp_config(self) -> dict:
        """Build MCP config from Onyx's configured MCP servers.

        Auto-loads all CONNECTED MCP servers from Onyx's database.
        All providers use Onyx's MCP servers exclusively — no manual
        config is needed or supported.

        Returns the config dict, or an empty dict if no servers are
        configured.
        """
        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.llm.mcp_config_builder import build_mcp_config_for_cli

        try:
            with get_session_with_current_tenant() as db_session:
                return build_mcp_config_for_cli(db_session)
        except Exception:
            logger.warning(
                "Could not load MCP servers from Onyx database; "
                "CLI will run without MCP tools."
            )
            return {}

    def _write_mcp_config(self) -> str | None:
        """Write Onyx MCP config JSON to a temp file.

        Loads all CONNECTED MCP servers from Onyx's database.
        Returns the path to the temp file, or None if no MCP servers
        are configured. The caller is responsible for cleanup.
        """
        merged = self._build_mcp_config()
        if not merged:
            return None

        fd, path = tempfile.mkstemp(suffix=".json", prefix="onyx_mcp_")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(merged, f)
        except Exception:
            os.unlink(path)
            raise
        return path

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider=CLAUDE_CODE_CLI_PROVIDER_NAME,
            model_name=self._model_name,
            temperature=self._temperature,
            custom_config=self._custom_config,
            max_input_tokens=self._max_input_tokens,
            cli_tool_bridge=_CLAUDE_CODE_TOOL_BRIDGE or None,
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        if tools:
            logger.warning(
                "Claude Code CLI does not support tool calling. "
                "Tools parameter will be ignored."
            )
        if structured_response_format:
            raise NotImplementedError(
                "Claude Code CLI does not support structured_response_format. "
                "Callers that request structured output depend on schema-"
                "conformant responses; use a LiteLLM-based provider instead."
            )

        text_prompt = _messages_to_prompt(prompt)
        timeout = timeout_override or self._timeout

        cmd = [
            self._cli_path,
            "--print",
            "--dangerously-skip-permissions",
            "--output-format", "json",
            "--model", self._model_name,
            "-p", "-",  # read prompt from stdin
        ]

        if self._disable_builtin_tools:
            cmd.extend(["--disallowedTools", _DISABLED_BUILTIN_TOOLS])

        if self._should_pass_api_key():
            cmd.extend(["--api-key", self._api_key])  # type: ignore[arg-type]

        # NOTE: --max-tokens is NOT a valid Claude Code CLI flag — passing it
        # causes the CLI to exit immediately with code 1 ("unknown option").
        # The CLI silently ignores token caps; callers that need a hard cap
        # should use a LiteLLM-based provider instead.

        mcp_config_path = self._write_mcp_config()
        if mcp_config_path:
            cmd.extend(["--mcp-config", mcp_config_path])

        env = self._build_env()

        try:
            result = subprocess.run(
                cmd,
                input=text_prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError(
                f"Claude Code CLI timed out after {timeout}s"
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Claude Code CLI not found at '{self._cli_path}'. "
                "Ensure the 'claude' CLI is installed and accessible."
            )
        finally:
            if mcp_config_path:
                try:
                    os.unlink(mcp_config_path)
                except OSError:
                    pass

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            raise RuntimeError(f"Claude Code CLI error: {error_msg}")

        raw_output = result.stdout.strip()

        # Parse JSON response to extract thinking and text content
        response_text = ""
        reasoning_text = ""
        usage = _make_usage()

        try:
            data = json.loads(raw_output)
            # JSON format returns content blocks array
            content_blocks = data if isinstance(data, list) else data.get("content", [])
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "thinking":
                    reasoning_text += block.get("thinking", "")
                elif block.get("type") == "text":
                    response_text += block.get("text", "")

            # Extract usage if available
            usage_data = data.get("usage") if isinstance(data, dict) else None
            if usage_data:
                usage = Usage(
                    prompt_tokens=usage_data.get("input_tokens", 0),
                    completion_tokens=usage_data.get("output_tokens", 0),
                    total_tokens=(
                        usage_data.get("input_tokens", 0)
                        + usage_data.get("output_tokens", 0)
                    ),
                    cache_creation_input_tokens=usage_data.get(
                        "cache_creation_input_tokens", 0
                    ),
                    cache_read_input_tokens=usage_data.get(
                        "cache_read_input_tokens", 0
                    ),
                )
        except (json.JSONDecodeError, TypeError):
            # Fallback: treat entire output as text
            response_text = raw_output

        return ModelResponse(
            id=f"cli-{uuid.uuid4().hex[:12]}",
            created=str(int(time.time())),
            choice=Choice(
                finish_reason="stop",
                index=0,
                message=Message(
                    content=response_text,
                    role="assistant",
                    reasoning_content=reasoning_text or None,
                ),
            ),
            usage=usage,
        )

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        if tools:
            logger.warning(
                "Claude Code CLI does not support tool calling. "
                "Tools parameter will be ignored."
            )
        if structured_response_format:
            raise NotImplementedError(
                "Claude Code CLI does not support structured_response_format. "
                "Callers that request structured output depend on schema-"
                "conformant responses; use a LiteLLM-based provider instead."
            )

        text_prompt = _messages_to_prompt(prompt)
        timeout = timeout_override or self._timeout
        response_id = f"cli-{uuid.uuid4().hex[:12]}"
        created = str(int(time.time()))

        cmd = [
            self._cli_path,
            "--print",
            "--dangerously-skip-permissions",
            "--verbose",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--model", self._model_name,
            "-p", "-",  # read prompt from stdin
        ]

        if self._disable_builtin_tools:
            cmd.extend(["--disallowedTools", _DISABLED_BUILTIN_TOOLS])

        if self._should_pass_api_key():
            cmd.extend(["--api-key", self._api_key])  # type: ignore[arg-type]

        # NOTE: --max-tokens is NOT a valid Claude Code CLI flag — passing it
        # causes the CLI to exit immediately with code 1 ("unknown option").
        # This was the root cause of background generations producing only
        # the "Response was terminated prior to completion" placeholder.
        # The CLI silently ignores token caps; callers that need a hard cap
        # should use a LiteLLM-based provider instead.

        mcp_config_path = self._write_mcp_config()
        if mcp_config_path:
            cmd.extend(["--mcp-config", mcp_config_path])

        env = self._build_env()

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            # Write prompt to stdin and close it
            assert proc.stdin is not None
            proc.stdin.write(text_prompt)
            proc.stdin.close()
        except FileNotFoundError:
            if mcp_config_path:
                try:
                    os.unlink(mcp_config_path)
                except OSError:
                    pass
            raise RuntimeError(
                f"Claude Code CLI not found at '{self._cli_path}'. "
                "Ensure the 'claude' CLI is installed and accessible."
            )

        assert proc.stdout is not None

        # Use a threading.Timer to enforce the overall streaming timeout.
        # If the subprocess hangs (e.g. no output and no exit), the timer
        # fires and kills it, which unblocks the stdout read loop below.
        timed_out = threading.Event()

        def _kill_on_timeout() -> None:
            timed_out.set()
            try:
                proc.kill()
            except OSError:
                pass  # process already dead

        timer = threading.Timer(timeout, _kill_on_timeout)
        timer.daemon = True
        timer.start()

        # Track content block types by index for proper delta routing
        block_types: dict[int, str] = {}
        # Per-index accumulators for tool_use blocks.
        # Key = content block index, value = {"id", "name", "args_buf"}.
        tool_use_state: dict[int, dict[str, str]] = {}
        # Dedup marker for tool_use blocks seen in assistant snapshots.
        snapshot_tool_ids_seen: set[str] = set()
        final_usage: Usage | None = None
        final_stop_reason: str | None = None
        event_count = 0
        # Track cumulative text lengths PER MESSAGE for partial-message
        # deduplication.  With --include-partial-messages, the CLI emits
        # growing snapshots of each assistant message — but a single CLI
        # invocation can produce MULTIPLE assistant messages when Claude
        # uses internal tools (web_search, etc.).  Each new message starts
        # its text from index 0, so a global counter would slice the
        # second message's text incorrectly and only the first message's
        # tail would ever reach the user.  Key by message id instead.
        msg_text_len: dict[str, int] = {}
        msg_thinking_len: dict[str, int] = {}
        # Track which assistant message_ids we've already streamed via
        # ``stream_event/content_block_delta`` so the ``assistant`` snapshot
        # handler skips duplicating their text content.
        streamed_msg_ids: set[str] = set()
        # Map ``stream_event`` content block index → owning message id so
        # nested deltas can be attributed to the right message.
        current_message_id: str | None = None

        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # Plain text fallback - yield as content
                    logger.debug("CLI non-JSON line: %s", line[:200])
                    if line:
                        yield ModelResponseStream(
                            id=response_id,
                            created=created,
                            choice=StreamingChoice(
                                index=0,
                                delta=Delta(content=line),
                            ),
                        )
                    continue

                event_type = event.get("type", "")
                event_count += 1
                if event_count <= 5 or event_type not in (
                    "content_block_delta", "ping", "stream_event",
                ):
                    logger.info(
                        "CLI stream event #%d: type=%s keys=%s",
                        event_count, event_type, list(event.keys()),
                    )

                # ─── stream_event: nested SSE deltas (PRIMARY stream path) ──
                # The CLI wraps Anthropic's raw streaming events inside a
                # ``stream_event`` envelope.  These arrive in real time and
                # carry the actual incremental deltas, while top-level
                # ``assistant`` events arrive periodically as full snapshots.
                # We use stream_event for live streaming and skip text
                # content in assistant events to avoid duplication.
                if event_type == "stream_event":
                    inner = event.get("event", {})
                    if not isinstance(inner, dict):
                        continue
                    inner_type = inner.get("type", "")

                    if inner_type == "message_start":
                        msg = inner.get("message", {}) or {}
                        current_message_id = msg.get("id") or current_message_id
                        if current_message_id:
                            streamed_msg_ids.add(current_message_id)
                            msg_text_len.setdefault(current_message_id, 0)
                            msg_thinking_len.setdefault(current_message_id, 0)

                    elif inner_type == "content_block_start":
                        idx = inner.get("index", 0)
                        block = inner.get("content_block", {}) or {}
                        block_type = block.get("type", "")
                        block_types[idx] = block_type
                        if block_type == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_use_state[idx] = {
                                "id": block.get("id", f"cli_{idx}"),
                                "name": tool_name,
                                "args_buf": "",
                            }
                            if tool_name not in _CLAUDE_CODE_TOOL_BRIDGE:
                                # Built-in agentic tool: surface an
                                # initial reasoning header immediately.
                                # Bridged tools wait for content_block_stop
                                # to emit delta.tool_calls (chip UI).
                                icon = _TOOL_ICON_MAP.get(tool_name, "🔧")
                                yield ModelResponseStream(
                                    id=response_id,
                                    created=created,
                                    choice=StreamingChoice(
                                        index=0,
                                        delta=Delta(
                                            reasoning_content=(
                                                f"\n\n---\n\n### {icon} "
                                                f"`{tool_name}`\n\n"
                                                f"*calling...*\n"
                                            ),
                                        ),
                                    ),
                                )

                    elif inner_type == "content_block_delta":
                        delta_data = inner.get("delta", {}) or {}
                        delta_type = delta_data.get("type", "")
                        idx = inner.get("index", 0)
                        if delta_type == "thinking_delta":
                            thinking = delta_data.get("thinking", "")
                            if thinking:
                                if current_message_id:
                                    msg_thinking_len[current_message_id] = (
                                        msg_thinking_len.get(
                                            current_message_id, 0
                                        )
                                        + len(thinking)
                                    )
                                yield ModelResponseStream(
                                    id=response_id,
                                    created=created,
                                    choice=StreamingChoice(
                                        index=0,
                                        delta=Delta(
                                            reasoning_content=thinking,
                                        ),
                                    ),
                                )
                        elif delta_type == "text_delta":
                            text = delta_data.get("text", "")
                            if text:
                                if current_message_id:
                                    msg_text_len[current_message_id] = (
                                        msg_text_len.get(
                                            current_message_id, 0
                                        )
                                        + len(text)
                                    )
                                yield ModelResponseStream(
                                    id=response_id,
                                    created=created,
                                    choice=StreamingChoice(
                                        index=0,
                                        delta=Delta(content=text),
                                    ),
                                )
                        elif delta_type == "input_json_delta":
                            # Accumulate tool_use arguments. Flushed at
                            # content_block_stop as either a bridged
                            # delta.tool_calls or a reasoning markdown
                            # block.
                            partial = delta_data.get("partial_json", "")
                            if partial and idx in tool_use_state:
                                tool_use_state[idx]["args_buf"] += partial
                        # signature_delta is ignored (thinking signature).

                    elif inner_type == "content_block_stop":
                        idx = inner.get("index", 0)
                        block_types.pop(idx, None)
                        if idx in tool_use_state:
                            tu = tool_use_state.pop(idx)
                            if tu["name"] in _CLAUDE_CODE_TOOL_BRIDGE:
                                # Bridged: yield delta.tool_calls so
                                # llm_step's bridge emits SearchToolStart
                                # etc. packets (chip UI).
                                snapshot_tool_ids_seen.add(tu["id"])
                                yield ModelResponseStream(
                                    id=response_id,
                                    created=created,
                                    choice=StreamingChoice(
                                        index=0,
                                        delta=Delta(
                                            tool_calls=[
                                                ChatCompletionDeltaToolCall(
                                                    id=tu["id"],
                                                    index=0,
                                                    type="function",
                                                    function=FunctionCall(
                                                        name=tu["name"],
                                                        arguments=(
                                                            tu["args_buf"]
                                                            or "{}"
                                                        ),
                                                    ),
                                                )
                                            ],
                                        ),
                                    ),
                                )
                            else:
                                # Built-in: emit final args as structured
                                # reasoning markdown.
                                yield ModelResponseStream(
                                    id=response_id,
                                    created=created,
                                    choice=StreamingChoice(
                                        index=0,
                                        delta=Delta(
                                            reasoning_content=(
                                                _format_builtin_tool_markdown(
                                                    tu["name"], tu["args_buf"]
                                                )
                                            ),
                                        ),
                                    ),
                                )

                    elif inner_type == "message_delta":
                        usage_data = inner.get("usage")
                        if usage_data:
                            final_usage = Usage(
                                prompt_tokens=usage_data.get("input_tokens", 0),
                                completion_tokens=usage_data.get(
                                    "output_tokens", 0
                                ),
                                total_tokens=(
                                    usage_data.get("input_tokens", 0)
                                    + usage_data.get("output_tokens", 0)
                                ),
                                cache_creation_input_tokens=usage_data.get(
                                    "cache_creation_input_tokens", 0
                                ),
                                cache_read_input_tokens=usage_data.get(
                                    "cache_read_input_tokens", 0
                                ),
                            )
                        delta_info = inner.get("delta") or {}
                        if delta_info.get("stop_reason"):
                            final_stop_reason = delta_info["stop_reason"]

                    # Skip: message_stop, ping
                    continue

                if event_type == "content_block_start":
                    idx = event.get("index", 0)
                    block = event.get("content_block", {})
                    block_type = block.get("type", "")
                    block_types[idx] = block_type

                    if block_type == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_use_state[idx] = {
                            "id": block.get("id", f"cli_{idx}"),
                            "name": tool_name,
                            "args_buf": "",
                        }
                        if tool_name not in _CLAUDE_CODE_TOOL_BRIDGE:
                            icon = _TOOL_ICON_MAP.get(tool_name, "🔧")
                            yield ModelResponseStream(
                                id=response_id,
                                created=created,
                                choice=StreamingChoice(
                                    index=0,
                                    delta=Delta(
                                        reasoning_content=(
                                            f"\n\n---\n\n### {icon} "
                                            f"`{tool_name}`\n\n"
                                            f"*calling...*\n"
                                        ),
                                    ),
                                ),
                            )

                elif event_type == "content_block_delta":
                    delta_data = event.get("delta", {})
                    delta_type = delta_data.get("type", "")
                    idx = event.get("index", 0)

                    if delta_type == "thinking_delta":
                        thinking = delta_data.get("thinking", "")
                        if thinking:
                            yield ModelResponseStream(
                                id=response_id,
                                created=created,
                                choice=StreamingChoice(
                                    index=0,
                                    delta=Delta(reasoning_content=thinking),
                                ),
                            )
                    elif delta_type == "text_delta":
                        text = delta_data.get("text", "")
                        if text:
                            yield ModelResponseStream(
                                id=response_id,
                                created=created,
                                choice=StreamingChoice(
                                    index=0,
                                    delta=Delta(content=text),
                                ),
                            )
                    elif delta_type == "input_json_delta":
                        partial = delta_data.get("partial_json", "")
                        if partial and idx in tool_use_state:
                            tool_use_state[idx]["args_buf"] += partial
                    # signature_delta is ignored (thinking signature).

                elif event_type == "content_block_stop":
                    idx = event.get("index", 0)
                    block_types.pop(idx, None)
                    if idx in tool_use_state:
                        tu = tool_use_state.pop(idx)
                        if tu["name"] in _CLAUDE_CODE_TOOL_BRIDGE:
                            snapshot_tool_ids_seen.add(tu["id"])
                            yield ModelResponseStream(
                                id=response_id,
                                created=created,
                                choice=StreamingChoice(
                                    index=0,
                                    delta=Delta(
                                        tool_calls=[
                                            ChatCompletionDeltaToolCall(
                                                id=tu["id"],
                                                index=0,
                                                type="function",
                                                function=FunctionCall(
                                                    name=tu["name"],
                                                    arguments=(
                                                        tu["args_buf"] or "{}"
                                                    ),
                                                ),
                                            )
                                        ],
                                    ),
                                ),
                            )
                        else:
                            yield ModelResponseStream(
                                id=response_id,
                                created=created,
                                choice=StreamingChoice(
                                    index=0,
                                    delta=Delta(
                                        reasoning_content=(
                                            _format_builtin_tool_markdown(
                                                tu["name"], tu["args_buf"]
                                            )
                                        ),
                                    ),
                                ),
                            )

                elif event_type == "message_delta":
                    usage_data = event.get("usage")
                    if usage_data:
                        final_usage = Usage(
                            prompt_tokens=usage_data.get("input_tokens", 0),
                            completion_tokens=usage_data.get("output_tokens", 0),
                            total_tokens=(
                                usage_data.get("input_tokens", 0)
                                + usage_data.get("output_tokens", 0)
                            ),
                            cache_creation_input_tokens=usage_data.get(
                                "cache_creation_input_tokens", 0
                            ),
                            cache_read_input_tokens=usage_data.get(
                                "cache_read_input_tokens", 0
                            ),
                        )
                    delta_info = event.get("delta") or {}
                    if delta_info.get("stop_reason"):
                        final_stop_reason = delta_info["stop_reason"]

                elif event_type == "result":
                    # Final result event with usage info
                    usage_data = event.get("usage")
                    if usage_data:
                        final_usage = Usage(
                            prompt_tokens=usage_data.get("input_tokens", 0),
                            completion_tokens=usage_data.get("output_tokens", 0),
                            total_tokens=(
                                usage_data.get("input_tokens", 0)
                                + usage_data.get("output_tokens", 0)
                            ),
                            cache_creation_input_tokens=usage_data.get(
                                "cache_creation_input_tokens", 0
                            ),
                            cache_read_input_tokens=usage_data.get(
                                "cache_read_input_tokens", 0
                            ),
                        )

                elif event_type == "assistant":
                    # Top-level ``assistant`` events arrive as periodic full
                    # snapshots of an assistant message.  When the matching
                    # ``stream_event/message_start`` was already seen, the
                    # text/thinking content has already been streamed delta-
                    # by-delta and we MUST NOT re-yield it (would double the
                    # answer).  We still scan for ``tool_use`` blocks here
                    # because tool calls only appear in the snapshot, never
                    # in the deltas.
                    #
                    # When stream_event was NOT seen for this message id
                    # (e.g. CLI built without partial-messages support), we
                    # fall back to per-message-id snapshot diffing so each
                    # turn's text is preserved correctly.
                    msg = event.get("message", {})
                    msg_id = msg.get("id", "") or ""
                    already_streamed = msg_id in streamed_msg_ids

                    for block in msg.get("content", []):
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type", "")

                        if block_type == "thinking":
                            if already_streamed:
                                # Stream path already emitted these deltas.
                                continue
                            full_thinking = block.get("thinking", "")
                            prev_len = msg_thinking_len.get(msg_id, 0)
                            new_thinking = full_thinking[prev_len:]
                            if new_thinking:
                                msg_thinking_len[msg_id] = len(full_thinking)
                                yield ModelResponseStream(
                                    id=response_id,
                                    created=created,
                                    choice=StreamingChoice(
                                        index=0,
                                        delta=Delta(reasoning_content=new_thinking),
                                    ),
                                )
                        elif block_type == "text":
                            if already_streamed:
                                # Stream path already emitted these deltas.
                                continue
                            full_text = block.get("text", "")
                            prev_len = msg_text_len.get(msg_id, 0)
                            new_text = full_text[prev_len:]
                            if new_text:
                                msg_text_len[msg_id] = len(full_text)
                                yield ModelResponseStream(
                                    id=response_id,
                                    created=created,
                                    choice=StreamingChoice(
                                        index=0,
                                        delta=Delta(content=new_text),
                                    ),
                                )
                        elif block_type == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_id = block.get("id", "") or f"cli_{tool_name}"
                            if tool_id in snapshot_tool_ids_seen:
                                # Already emitted via stream_event or
                                # top-level path.
                                continue
                            snapshot_tool_ids_seen.add(tool_id)
                            tool_input = block.get("input") or {}
                            args_json = (
                                json.dumps(tool_input) if tool_input else "{}"
                            )
                            if tool_name in _CLAUDE_CODE_TOOL_BRIDGE:
                                yield ModelResponseStream(
                                    id=response_id,
                                    created=created,
                                    choice=StreamingChoice(
                                        index=0,
                                        delta=Delta(
                                            tool_calls=[
                                                ChatCompletionDeltaToolCall(
                                                    id=tool_id,
                                                    index=0,
                                                    type="function",
                                                    function=FunctionCall(
                                                        name=tool_name,
                                                        arguments=args_json,
                                                    ),
                                                )
                                            ],
                                        ),
                                    ),
                                )
                            else:
                                yield ModelResponseStream(
                                    id=response_id,
                                    created=created,
                                    choice=StreamingChoice(
                                        index=0,
                                        delta=Delta(
                                            reasoning_content=(
                                                _format_builtin_tool_markdown(
                                                    tool_name, args_json
                                                )
                                            ),
                                        ),
                                    ),
                                )

                # Skip: ping, message_start, message_stop, system, result

            # If the timer killed the process, raise instead of yielding stop
            if timed_out.is_set():
                raise TimeoutError(
                    f"Claude Code CLI streaming timed out after {timeout}s"
                )

            # Final chunk with finish_reason
            yield ModelResponseStream(
                id=response_id,
                created=created,
                choice=StreamingChoice(
                    finish_reason=final_stop_reason or "stop",
                    index=0,
                    delta=Delta(),
                ),
                usage=final_usage or _make_usage(),
            )

        finally:
            timer.cancel()
            logger.info(
                "CLI stream ended: %d events processed, timed_out=%s",
                event_count, timed_out.is_set(),
            )
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Claude Code CLI process did not exit within 5s "
                    "after stream ended; killing it."
                )
                proc.kill()
                proc.wait(timeout=5)
            if mcp_config_path:
                try:
                    os.unlink(mcp_config_path)
                except OSError:
                    pass
            stderr = proc.stderr.read() if proc.stderr else ""
            if stderr:
                logger.info("CLI stderr: %s", stderr[:1000])
            if proc.returncode and proc.returncode != 0:
                logger.warning("Claude Code CLI exited with code %d", proc.returncode)
