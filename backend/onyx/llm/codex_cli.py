"""OpenAI Codex CLI LLM provider.

Routes requests through the ``codex`` CLI binary when OAuth tokens are
used, since ChatGPT session tokens only work with the Codex CLI (not
api.openai.com). When an API key is provided instead, the standard
LiteLLM path is used.

Streaming uses ``codex exec --json`` which emits JSONL events:

    {"type":"thread.started","thread_id":"..."}
    {"type":"turn.started"}
    {"type":"item.started","item":{"id":"item_1","type":"command_execution",...}}
    {"type":"item.completed","item":{"id":"item_1","type":"command_execution",...}}
    {"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"..."}}
    {"type":"turn.completed","usage":{"input_tokens":...,"output_tokens":...}}

Events are item-granular, not token-granular: agent_message arrives as
one ``item.completed`` with the full text. Shell commands stream
``item.started`` (begin) -> ``item.completed`` (end with output).

Non-bridged tool-like items (shell commands, etc.) are surfaced as
structured markdown inside ``delta.reasoning_content`` so they appear in
the Thinking panel. Codex does NOT currently support ``--mcp-config`` so
there are no bridged tools for the chip UI -- ``_CODEX_TOOL_BRIDGE`` is
left empty by default.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

from onyx.configs.model_configs import GEN_AI_TEMPERATURE
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
from onyx.llm.well_known_providers.constants import OPENAI_CODEX_ACCESS_TOKEN_KEY
from onyx.llm.well_known_providers.constants import (
    OPENAI_CODEX_DISABLE_BUILTIN_TOOLS_KEY,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DEFAULT_CLI_PATH = "codex"
_DEFAULT_TIMEOUT = 300

_DEFAULT_INSTRUCTIONS = (
    "You are a helpful AI assistant. "
    "Format your responses using proper Markdown with headings, "
    "lists, code blocks, and emphasis where appropriate."
)

# Additional ``codex exec`` args appended when the disable-builtin-tools
# toggle is on. Derived from Phase 0 probes: Codex CLI accepts
# ``-c web_search="disabled"`` to turn off its native web search
# (``features.web_search=false`` and ``--disable web_search`` are both
# deprecated in 0.117.0). Leave empty to disable the toggle entirely on
# this Codex version.
_CODEX_DISABLE_WEB_TOOL_FLAGS: list[str] = ["-c", 'web_search="disabled"']

# Map Codex item.type values to ``cli_tool_bridge`` categories. Codex
# does NOT currently read ``--mcp-config`` so there is no path to Onyx
# MCP tools -- this map is intentionally empty. If a future Codex
# version adds MCP or built-in search/fetch items, add entries here.
_CODEX_TOOL_BRIDGE: dict[str, str] = {}

# Icons for structured reasoning markdown per Codex item.type.
_CODEX_ITEM_ICON_MAP: dict[str, str] = {
    "command_execution": "💻",
    "web_search": "🔍",
    "file_read": "📖",
    "file_write": "📝",
    "apply_patch": "✏️",
}

# Codex item.type values that carry the assistant's final answer text.
# Older codex CLIs use ``agent_message`` with a ``text`` field. Newer
# versions (notably those supporting gpt-5.5*) may emit the same payload
# under different type names or with the text in alternate fields. Treat
# all of these as the final answer.
_CODEX_ANSWER_ITEM_TYPES: frozenset[str] = frozenset(
    {
        "agent_message",
        "assistant_message",
        "message",
        "output_message",
        "output_text",
        "text",
    }
)

# Candidate field names that may carry the assistant text inside an
# answer-like item. Tried in order until a non-empty string is found.
_CODEX_ANSWER_TEXT_FIELDS: tuple[str, ...] = (
    "text",
    "output_text",
    "content",
    "message",
)


# Substrings (lowercased) in codex stderr/stdout that mean the ChatGPT
# session auth is exhausted or invalid -- the user must re-authenticate
# with the codex CLI. When any of these appear we lead with a clear
# re-auth headline instead of the generic "no answer" message.
_CODEX_AUTH_FAILURE_MARKERS: tuple[str, ...] = (
    "refresh token was already used",
    "please log out and sign in again",
    "failed to refresh token",
    "401 unauthorized",
    "codex_login::auth::manager",
    "invalid_grant",
    "token has expired",
    "not authenticated",
)


def _detect_codex_auth_failure(*texts: str) -> bool:
    """Return True if any text fragment matches a known codex auth-failure signature."""
    haystack = " ".join(t for t in texts if t).lower()
    if not haystack:
        return False
    return any(marker in haystack for marker in _CODEX_AUTH_FAILURE_MARKERS)


def _build_codex_no_answer_message(
    *,
    model_name: str,
    error_messages: list[str],
    observed_events: list[tuple[str, str]],
    non_json_lines: list[str],
    stderr_text: str,
    exit_code: int | None,
    event_count: int,
) -> str:
    """Compose the fallback delta.content shown when codex emits no answer.

    The message is split in two parts so the user gets a clear top-line
    explanation and a collapsed ``<details>`` block with diagnostic data
    (CLI exit code, observed event shapes, stderr tail, non-JSON stdout)
    that's actionable for a maintainer without overwhelming the chat.
    """
    auth_failure = _detect_codex_auth_failure(
        stderr_text, *non_json_lines, *error_messages
    )

    if auth_failure:
        headline = (
            "**Codex authentication expired.** Your ChatGPT session "
            "token is no longer valid (the refresh token has already "
            "been used or has expired). "
            "**Please sign out of the OpenAI Codex provider in Onyx "
            "settings and sign in again** to issue a fresh token."
        )
    elif error_messages:
        headline = (
            "The Codex CLI did not produce a final answer for model "
            f"`{model_name}`. Reported errors:\n\n"
            + "\n".join(f"- {m}" for m in error_messages)
        )
    else:
        headline = (
            f"The Codex CLI returned no answer for model `{model_name}`. "
            "The model may not be available on this account, or the CLI "
            "version may emit an unsupported event format. "
            "Try a different model (e.g. `gpt-5.5-codex`)."
        )

    observed_unique = sorted(
        {
            (f"{e}:{i}" if i else e)
            for e, i in observed_events
            if e or i
        }
    )

    details_lines: list[str] = ["**Codex CLI diagnostics:**"]
    details_lines.append(f"- Exit code: `{exit_code}`")
    details_lines.append(f"- JSON events received: `{event_count}`")
    if observed_unique:
        details_lines.append(
            "- Observed event shapes: `"
            + ", ".join(observed_unique)
            + "`"
        )
    else:
        details_lines.append("- Observed event shapes: _(none)_")
    if non_json_lines:
        joined = "\n".join(non_json_lines[-5:])
        details_lines.append(
            f"- Non-JSON stdout tail:\n```\n{joined}\n```"
        )
    if stderr_text:
        details_lines.append(
            f"- Stderr tail:\n```\n{stderr_text[-1500:].strip()}\n```"
        )

    diagnostics = "\n".join(details_lines)
    return f"{headline}\n\n<details>\n<summary>Diagnostics</summary>\n\n{diagnostics}\n\n</details>"


def _extract_codex_answer_text(item: dict[str, Any]) -> str:
    """Pull the assistant text out of an answer-like Codex item.

    Codex versions differ in whether they put the text under ``text``,
    ``content``, ``output_text``, or a list of content parts. Walk the
    known shapes and return the first non-empty string found.
    """
    for field in _CODEX_ANSWER_TEXT_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for part in value:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    # Common shapes: {"type":"output_text","text":"..."}
                    # or {"type":"text","text":"..."}.
                    for nested in ("text", "output_text", "content"):
                        nested_value = part.get(nested)
                        if isinstance(nested_value, str) and nested_value:
                            parts.append(nested_value)
                            break
            joined = "".join(parts)
            if joined:
                return joined
    return ""

# Max chars of aggregated_output to include in a reasoning chunk. Longer
# output is truncated with a marker -- full output is still available in
# the CLI's own stderr/stdout if needed.
_CODEX_OUTPUT_MAX_CHARS = 2000


def _extract_system_and_user(prompt: LanguageModelInput) -> tuple[str, str]:
    """Split messages into system instructions and user prompt.

    Returns ``(system_text, user_text)`` where system_text contains all
    system messages and user_text contains the conversation formatted
    to preserve markdown and role structure.
    """
    if not isinstance(prompt, list):
        dumped = prompt.model_dump(exclude_none=True)
        return "", dumped.get("content", "")

    system_parts: list[str] = []
    conversation_parts: list[str] = []

    for msg in prompt:
        dumped = msg.model_dump(exclude_none=True)
        role = dumped.get("role", "user")
        content = dumped.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            conversation_parts.append(f"Assistant: {content}")
        else:
            conversation_parts.append(content)

    system_text = "\n\n".join(system_parts)
    user_text = "\n\n".join(conversation_parts)
    return system_text, user_text


def _make_usage() -> Usage:
    return Usage(
        completion_tokens=0,
        prompt_tokens=0,
        total_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


def _format_codex_command_start(command: str) -> str:
    """Initial reasoning markdown shown while a shell command is running."""
    safe_cmd = (command or "").strip() or "(empty)"
    return (
        f"\n\n---\n\n### 💻 `Bash`\n\n"
        f"```bash\n{safe_cmd}\n```\n\n*running...*\n"
    )


def _format_codex_command_result(
    aggregated_output: str | None,
    exit_code: int | None,
    status: str | None,
) -> str:
    """Follow-up reasoning markdown with the shell command result."""
    full_output = aggregated_output or ""
    truncated = full_output[:_CODEX_OUTPUT_MAX_CHARS]
    if len(full_output) > _CODEX_OUTPUT_MAX_CHARS:
        truncated += (
            f"\n... (truncated, full output {len(full_output)} chars)"
        )
    exit_line = (
        f"**Exit:** {exit_code} (`{status or 'unknown'}`)\n\n"
        if exit_code is not None
        else ""
    )
    return f"\n{exit_line}```\n{truncated.strip()}\n```\n"


def _format_codex_generic_item(item_type: str, item: dict[str, Any]) -> str:
    """Fallback reasoning markdown for unknown item.type values."""
    icon = _CODEX_ITEM_ICON_MAP.get(item_type, "🔧")
    try:
        body = json.dumps(item, indent=2)
    except (TypeError, ValueError):
        body = str(item)
    return (
        f"\n\n---\n\n### {icon} `{item_type}`\n\n"
        f"```json\n{body}\n```\n"
    )


def _build_codex_usage(usage_data: dict[str, Any]) -> Usage:
    prompt = usage_data.get("input_tokens", 0) or 0
    completion = usage_data.get("output_tokens", 0) or 0
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=usage_data.get("cached_input_tokens", 0) or 0,
    )


class CodexCLI(LLM):
    """LLM implementation that shells out to the OpenAI Codex CLI.

    Used when the provider has OAuth tokens (ChatGPT session auth)
    which only work through the Codex CLI, not the standard API.
    """

    def __init__(
        self,
        model_name: str,
        temperature: float | None = None,
        custom_config: dict[str, str] | None = None,
        timeout: int | None = None,
        max_input_tokens: int = 128000,
    ):
        self._model_name = model_name
        self._temperature = (
            temperature if temperature is not None else GEN_AI_TEMPERATURE
        )
        self._custom_config = custom_config or {}
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._max_input_tokens = max_input_tokens
        self._cli_path = _DEFAULT_CLI_PATH
        # Default ON: disable Codex's native web search so Onyx's
        # configured search tools handle web queries instead. Admins can
        # opt out by setting this key to "false" in custom_config. Note
        # that Codex has no --mcp-config support today, so disabling
        # web search here means web queries will simply fail inside
        # Codex -- callers should rely on Onyx-native tools for search
        # when this is enabled.
        self._disable_builtin_tools = (
            self._custom_config.get(
                OPENAI_CODEX_DISABLE_BUILTIN_TOOLS_KEY, "true"
            ).lower()
            != "false"
        )

    def _setup_auth(self) -> None:
        """Ensure Codex CLI has file-based authentication available.

        Writes config.toml (forces file-based credential store to bypass
        the system keyring, which doesn't work in headless Docker) and
        auth.json with the proper structure the CLI expects.
        """
        access_token = self._custom_config.get(OPENAI_CODEX_ACCESS_TOKEN_KEY)
        if not access_token:
            return

        from onyx.llm.well_known_providers.constants import (
            OPENAI_CODEX_ID_TOKEN_KEY,
            OPENAI_CODEX_REFRESH_TOKEN_KEY,
        )

        refresh_token = self._custom_config.get(
            OPENAI_CODEX_REFRESH_TOKEN_KEY, ""
        )
        id_token = self._custom_config.get(
            OPENAI_CODEX_ID_TOKEN_KEY, access_token
        )

        codex_home = os.path.expanduser("~/.codex")
        os.makedirs(codex_home, exist_ok=True)

        config_path = os.path.join(codex_home, "config.toml")
        if not os.path.exists(config_path):
            with open(config_path, "w") as f:
                f.write('cli_auth_credentials_store = "file"\n')

        auth_path = os.path.join(codex_home, "auth.json")

        account_id = ""
        try:
            import base64

            payload = access_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            auth_info = claims.get("https://api.openai.com/auth", {})
            account_id = auth_info.get("chatgpt_account_id", "")
        except Exception:
            pass

        auth_data = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "last_refresh": time.strftime(
                "%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime()
            ),
            "tokens": {
                "id_token": id_token,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "account_id": account_id,
            },
        }
        with open(auth_path, "w") as f:
            json.dump(auth_data, f)

    def _build_base_cmd(self) -> list[str]:
        """Common argv for ``codex exec`` invocations."""
        cmd = [
            self._cli_path,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--ephemeral",
            "-m", self._model_name,
        ]
        if self._disable_builtin_tools and _CODEX_DISABLE_WEB_TOOL_FLAGS:
            cmd.extend(_CODEX_DISABLE_WEB_TOOL_FLAGS)
        return cmd

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai_codex",
            model_name=self._model_name,
            temperature=self._temperature,
            custom_config=self._custom_config,
            max_input_tokens=self._max_input_tokens,
            cli_tool_bridge=_CODEX_TOOL_BRIDGE or None,
        )

    # ------------------------------------------------------------------
    # invoke() — non-streaming, uses ``-o output_file`` text capture.
    # Kept file-based because invoke() is used for short metadata tasks
    # where the item-granular --json event loop would add no value.
    # ------------------------------------------------------------------
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
        system_text, user_text = _extract_system_and_user(prompt)
        timeout = timeout_override or self._timeout

        self._setup_auth()

        import tempfile

        output_file = os.path.join(
            tempfile.gettempdir(), f"codex-{uuid.uuid4().hex[:8]}.txt"
        )

        cmd = self._build_base_cmd()
        cmd.extend(["-o", output_file])
        instructions = system_text or _DEFAULT_INSTRUCTIONS
        escaped = (
            instructions.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
        )
        cmd.extend(["-c", f'instructions="{escaped}"'])
        cmd.append(user_text)

        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Codex CLI not found at '{self._cli_path}'. "
                "Ensure the 'codex' CLI is installed."
            )

        stderr_lines: list[str] = []
        last_activity = time.time()

        def _drain_stderr() -> None:
            nonlocal last_activity
            assert proc.stderr is not None
            for line in iter(proc.stderr.readline, b""):
                decoded = line.decode("utf-8", errors="replace")
                stderr_lines.append(decoded)
                last_activity = time.time()
            proc.stderr.close()

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        while proc.poll() is None:
            elapsed_idle = time.time() - last_activity
            if elapsed_idle > timeout:
                proc.kill()
                proc.wait()
                raise TimeoutError(
                    f"Codex CLI idle for {timeout}s with no output"
                )
            time.sleep(1)

        stderr_thread.join(timeout=5)
        stdout_data = (
            proc.stdout.read().decode("utf-8", errors="replace")
            if proc.stdout
            else ""
        )

        if proc.returncode != 0:
            error_msg = "".join(stderr_lines).strip() or "Unknown error"
            fatal_lines = [
                l
                for l in error_msg.split("\n")
                if "ERROR:" in l and "Reconnecting" not in l
            ]
            raise RuntimeError(
                f"Codex CLI error: "
                f"{fatal_lines[-1] if fatal_lines else error_msg[-500:]}"
            )

        response_text = ""
        try:
            with open(output_file, "r") as f:
                response_text = f.read().strip()
        except FileNotFoundError:
            response_text = stdout_data.strip()
        finally:
            try:
                os.unlink(output_file)
            except OSError:
                pass

        return ModelResponse(
            id=f"codex-{uuid.uuid4().hex[:12]}",
            created=str(int(time.time())),
            choice=Choice(
                finish_reason="stop",
                index=0,
                message=Message(
                    content=response_text.strip(), role="assistant"
                ),
            ),
            usage=_make_usage(),
        )

    # ------------------------------------------------------------------
    # stream() — uses ``codex exec --json`` JSONL events.
    # ------------------------------------------------------------------
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
        if structured_response_format:
            raise NotImplementedError(
                "Codex CLI does not support structured_response_format."
            )

        system_text, user_text = _extract_system_and_user(prompt)
        self._setup_auth()

        response_id = f"codex-{uuid.uuid4().hex[:12]}"
        created = str(int(time.time()))

        instructions = system_text or _DEFAULT_INSTRUCTIONS
        escaped = (
            instructions.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
        )

        cmd = self._build_base_cmd()
        cmd.append("--json")
        cmd.extend(["-c", f'instructions="{escaped}"'])
        cmd.append(user_text)

        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        timeout = timeout_override or self._timeout
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Codex CLI not found at '{self._cli_path}'. "
                "Ensure the 'codex' CLI is installed."
            )

        timed_out = threading.Event()

        def _kill_on_timeout() -> None:
            timed_out.set()
            try:
                proc.kill()
            except OSError:
                pass

        timer = threading.Timer(timeout, _kill_on_timeout)
        timer.daemon = True
        timer.start()

        # Drain stderr in a background thread so we can include its
        # contents in diagnostics even when the stream completes "cleanly"
        # without yielding an answer. Without this, stderr is only read
        # after proc.wait() returns, which means the fallback content
        # would be yielded with no visibility into why codex failed.
        stderr_lines: list[str] = []

        def _drain_stderr() -> None:
            assert proc.stderr is not None
            try:
                for line in proc.stderr:
                    stderr_lines.append(line)
            except Exception:  # noqa: BLE001 - stderr can be torn down on kill
                pass

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        final_usage: Usage | None = None
        event_count = 0
        answer_emitted = False
        error_messages: list[str] = []
        # All distinct (event_type, item_type) pairs seen on stdout --
        # used in the fallback diagnostic when no answer is produced so
        # we can identify CLI versions that emit unknown event shapes.
        observed_events: list[tuple[str, str]] = []
        non_json_lines: list[str] = []

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # Some codex CLI failure modes (e.g. unsupported
                    # model, auth issues hit before --json kicks in)
                    # print plain-text errors to stdout. Keep them so
                    # they can surface in the fallback diagnostic.
                    logger.debug("Codex non-JSON line: %s", line[:200])
                    non_json_lines.append(line[:500])
                    continue

                event_count += 1
                event_type = event.get("type", "")
                item_obj = event.get("item") or {}
                item_type = (
                    item_obj.get("type", "") if isinstance(item_obj, dict) else ""
                )
                observed_events.append((event_type, item_type))

                # turn.completed carries cumulative usage.
                if event_type == "turn.completed":
                    usage_data = event.get("usage") or {}
                    if usage_data:
                        final_usage = _build_codex_usage(usage_data)
                    continue

                for chunk in self._dispatch_codex_event(
                    event, response_id, created
                ):
                    if chunk.choice.delta.content:
                        answer_emitted = True
                    yield chunk

                # Track error item messages so we can surface them as
                # content if the stream never produced an answer.
                if (
                    event_type == "item.completed"
                    and item_type == "error"
                ):
                    msg = item_obj.get("message", "")
                    if msg and "OPENAI_BASE_URL" not in msg and not (
                        "deprecated" in msg.lower() and "features" in msg.lower()
                    ):
                        error_messages.append(msg)

            if timed_out.is_set():
                raise TimeoutError(
                    f"Codex CLI streaming timed out after {timeout}s"
                )

            # If no agent_message-like item ever produced content, surface
            # something usable so the upstream LLM loop doesn't fail with
            # EmptyLLMResponseError. Prefer accumulated error messages;
            # fall back to a generic explanation that includes enough
            # diagnostic detail (event shapes, stderr tail, exit code)
            # to identify why codex stayed silent for this model.
            if not answer_emitted:
                # Wait briefly for the process + stderr drain to settle so
                # we have an exit code and final stderr to include.
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                stderr_thread.join(timeout=2)
                stderr_text = "".join(stderr_lines)
                if _detect_codex_auth_failure(
                    stderr_text, *non_json_lines, *error_messages
                ):
                    logger.warning(
                        "Codex CLI authentication failed for model %s "
                        "(refresh token expired/reused); user must "
                        "re-authenticate via the OpenAI Codex provider "
                        "settings. exit_code=%s",
                        self._model_name,
                        proc.returncode,
                    )
                fallback_text = _build_codex_no_answer_message(
                    model_name=self._model_name,
                    error_messages=error_messages,
                    observed_events=observed_events,
                    non_json_lines=non_json_lines,
                    stderr_text=stderr_text,
                    exit_code=proc.returncode,
                    event_count=event_count,
                )
                logger.warning(
                    "Codex CLI stream produced no answer for model %s; "
                    "exit_code=%s events=%d errors=%d observed=%s "
                    "stderr_tail=%r",
                    self._model_name,
                    proc.returncode,
                    event_count,
                    len(error_messages),
                    sorted({f"{e}:{i}" for e, i in observed_events}),
                    stderr_text[-500:] if stderr_text else "",
                )
                yield ModelResponseStream(
                    id=response_id,
                    created=created,
                    choice=StreamingChoice(
                        index=0,
                        delta=Delta(content=fallback_text),
                    ),
                )

            yield ModelResponseStream(
                id=response_id,
                created=created,
                choice=StreamingChoice(
                    finish_reason="stop", index=0, delta=Delta()
                ),
                usage=final_usage or _make_usage(),
            )

        finally:
            timer.cancel()
            logger.info(
                "Codex CLI stream ended: %d events, timed_out=%s, "
                "observed=%s",
                event_count,
                timed_out.is_set(),
                sorted({f"{e}:{i}" for e, i in observed_events}),
            )
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Codex CLI did not exit within 5s after stream ended; "
                    "killing it."
                )
                proc.kill()
                proc.wait(timeout=5)
            stderr_thread.join(timeout=2)
            stderr = "".join(stderr_lines)
            if stderr:
                logger.info("Codex stderr: %s", stderr[:2000])
            if proc.returncode and proc.returncode != 0:
                logger.warning(
                    "Codex CLI exited with code %d", proc.returncode
                )

    def _dispatch_codex_event(
        self, event: dict[str, Any], response_id: str, created: str
    ) -> Iterator[ModelResponseStream]:
        """Translate one Codex JSONL event into ``ModelResponseStream``s."""
        event_type = event.get("type", "")

        # Session bookkeeping events -- no-op for the stream.
        if event_type in ("thread.started", "turn.started"):
            return

        item = event.get("item") or {}
        item_type = item.get("type", "")

        if event_type == "item.started":
            if item_type == "command_execution":
                yield ModelResponseStream(
                    id=response_id,
                    created=created,
                    choice=StreamingChoice(
                        index=0,
                        delta=Delta(
                            reasoning_content=_format_codex_command_start(
                                item.get("command", "")
                            ),
                        ),
                    ),
                )
                return
            # Unknown started items: surface a generic header.
            yield ModelResponseStream(
                id=response_id,
                created=created,
                choice=StreamingChoice(
                    index=0,
                    delta=Delta(
                        reasoning_content=_format_codex_generic_item(
                            item_type, item
                        ),
                    ),
                ),
            )
            return

        if event_type == "item.completed":
            if item_type in _CODEX_ANSWER_ITEM_TYPES:
                text = _extract_codex_answer_text(item)
                if text:
                    yield ModelResponseStream(
                        id=response_id,
                        created=created,
                        choice=StreamingChoice(
                            index=0,
                            delta=Delta(content=text),
                        ),
                    )
                else:
                    logger.warning(
                        "Codex CLI emitted answer item '%s' with no "
                        "extractable text; keys=%s",
                        item_type,
                        sorted(item.keys()),
                    )
                return

            if item_type == "command_execution":
                yield ModelResponseStream(
                    id=response_id,
                    created=created,
                    choice=StreamingChoice(
                        index=0,
                        delta=Delta(
                            reasoning_content=_format_codex_command_result(
                                item.get("aggregated_output"),
                                item.get("exit_code"),
                                item.get("status"),
                            ),
                        ),
                    ),
                )
                return

            if item_type == "error":
                msg = item.get("message", "")
                # Known non-fatal deprecation warning -- skip silently.
                if "OPENAI_BASE_URL" in msg or (
                    "deprecated" in msg.lower() and "features" in msg.lower()
                ):
                    return
                logger.warning("Codex CLI error item: %s", msg)
                yield ModelResponseStream(
                    id=response_id,
                    created=created,
                    choice=StreamingChoice(
                        index=0,
                        delta=Delta(
                            reasoning_content=f"\n\n⚠️ **Error:** {msg}\n",
                        ),
                    ),
                )
                return

            # Bridged item types (e.g. future web_search) -- emit
            # delta.tool_calls so llm_step's bridge hands it off to the
            # chip UI via cli_tool_bridge.emit_bridge_packets.
            bridge_category = _CODEX_TOOL_BRIDGE.get(item_type)
            if bridge_category:
                arguments_dict: dict[str, Any] = {}
                for key in ("query", "url", "path"):
                    if key in item:
                        arguments_dict[key] = item[key]
                yield ModelResponseStream(
                    id=response_id,
                    created=created,
                    choice=StreamingChoice(
                        index=0,
                        delta=Delta(
                            tool_calls=[
                                ChatCompletionDeltaToolCall(
                                    id=item.get("id", f"codex_{item_type}"),
                                    index=0,
                                    type="function",
                                    function=FunctionCall(
                                        name=item_type,
                                        arguments=json.dumps(
                                            arguments_dict or item
                                        ),
                                    ),
                                )
                            ],
                        ),
                    ),
                )
                return

            # Unknown completed item: structured markdown fallback.
            logger.debug("Unknown Codex item.type: %s", item_type)
            yield ModelResponseStream(
                id=response_id,
                created=created,
                choice=StreamingChoice(
                    index=0,
                    delta=Delta(
                        reasoning_content=_format_codex_generic_item(
                            item_type, item
                        ),
                    ),
                ),
            )
            return

        logger.debug("Unknown Codex event type: %s", event_type)
