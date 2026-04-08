"""OpenAI Codex CLI LLM provider.

Routes requests through the `codex` CLI binary when OAuth tokens are used,
since ChatGPT session tokens only work with the Codex CLI (not api.openai.com).
When an API key is provided instead, the standard LiteLLM path is used.
"""

import json
import subprocess
import time
import uuid
from collections.abc import Iterator
from typing import Any

from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.model_response import Choice
from onyx.llm.model_response import Delta
from onyx.llm.model_response import Message
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice
from onyx.llm.model_response import Usage
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.well_known_providers.constants import OPENAI_CODEX_ACCESS_TOKEN_KEY
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DEFAULT_CLI_PATH = "codex"
_DEFAULT_TIMEOUT = 300

# ── Background result cache ──────────────────────────────────
# The Codex CLI runs in a background thread so it completes even
# if the SSE connection drops (user closes browser tab). Results
# are cached here and served when the stream generator polls.
import threading as _threading
from dataclasses import dataclass as _dataclass, field as _field

_CACHE_TTL_SECONDS = 600  # 10 minutes


@_dataclass
class _CachedResult:
    text: str | None = None
    error: str | None = None
    done: bool = False
    created_at: float = _field(default_factory=time.time)


_result_cache: dict[str, _CachedResult] = {}
_cache_lock = _threading.Lock()
_DEFAULT_INSTRUCTIONS = (
    "You are a helpful AI assistant. "
    "Format your responses using proper Markdown with headings, "
    "lists, code blocks, and emphasis where appropriate."
)


def _extract_system_and_user(
    prompt: LanguageModelInput,
) -> tuple[str, str]:
    """Split messages into system instructions and user prompt.

    Returns (system_text, user_text) where system_text contains all
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
        self._temperature = temperature if temperature is not None else GEN_AI_TEMPERATURE
        self._custom_config = custom_config or {}
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._max_input_tokens = max_input_tokens
        self._cli_path = _DEFAULT_CLI_PATH

    def _setup_auth(self) -> None:
        """Ensure Codex CLI has file-based authentication available.

        Writes config.toml (forces file-based credential store to bypass
        the system keyring, which doesn't work in headless Docker) and
        auth.json with the proper structure the CLI expects.
        """
        import os

        access_token = self._custom_config.get(OPENAI_CODEX_ACCESS_TOKEN_KEY)
        if not access_token:
            return

        from onyx.llm.well_known_providers.constants import (
            OPENAI_CODEX_ID_TOKEN_KEY,
            OPENAI_CODEX_REFRESH_TOKEN_KEY,
            OPENAI_CODEX_TOKEN_EXPIRES_AT_KEY,
        )

        refresh_token = self._custom_config.get(OPENAI_CODEX_REFRESH_TOKEN_KEY, "")
        id_token = self._custom_config.get(OPENAI_CODEX_ID_TOKEN_KEY, access_token)

        codex_home = os.path.expanduser("~/.codex")
        os.makedirs(codex_home, exist_ok=True)

        # Write config.toml to force file-based credential storage.
        # Without this, the CLI tries to use the system keyring (D-Bus
        # Secret Service) which doesn't exist in Docker containers.
        config_path = os.path.join(codex_home, "config.toml")
        if not os.path.exists(config_path):
            with open(config_path, "w") as f:
                f.write('cli_auth_credentials_store = "file"\n')

        # Write auth.json matching the format produced by `codex login`.
        # Key fields: auth_mode, OPENAI_API_KEY, tokens (with account_id
        # and last_refresh), which the CLI uses for ChatGPT subscription auth.
        auth_path = os.path.join(codex_home, "auth.json")

        # Extract account_id from the JWT if possible
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

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai_codex",
            model_name=self._model_name,
            temperature=self._temperature,
            custom_config=self._custom_config,
            max_input_tokens=self._max_input_tokens,
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
        system_text, user_text = _extract_system_and_user(prompt)
        timeout = timeout_override or self._timeout

        self._setup_auth()

        import os
        import tempfile

        # Use -o to capture the last message to a temp file
        # instead of --json which outputs JSON-RPC events
        output_file = os.path.join(
            tempfile.gettempdir(), f"codex-{uuid.uuid4().hex[:8]}.txt"
        )

        cmd = [
            self._cli_path,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--ephemeral",
            "-o", output_file,
            "-m", self._model_name,
        ]
        # Pass system message as instructions config
        instructions = system_text or _DEFAULT_INSTRUCTIONS
        # Escape for TOML string: backslash-escape quotes and newlines
        escaped = instructions.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        cmd.extend(["-c", f'instructions="{escaped}"'])
        cmd.append(user_text)

        env = os.environ.copy()
        # Suppress color output and terminal interaction
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        # Use Popen with activity-based timeout: reset the idle timer
        # whenever the CLI produces output (stderr has progress/thinking).
        idle_timeout = timeout  # max seconds without ANY output
        try:
            import select
            import threading

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

        def _drain_stderr():
            """Read stderr in a thread to prevent blocking."""
            nonlocal last_activity
            assert proc.stderr is not None
            for line in iter(proc.stderr.readline, b""):
                decoded = line.decode("utf-8", errors="replace")
                stderr_lines.append(decoded)
                last_activity = time.time()
            proc.stderr.close()

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        # Wait for process, checking idle timeout periodically
        while proc.poll() is None:
            elapsed_idle = time.time() - last_activity
            if elapsed_idle > idle_timeout:
                proc.kill()
                proc.wait()
                raise TimeoutError(
                    f"Codex CLI idle for {idle_timeout}s with no output"
                )
            time.sleep(1)

        stderr_thread.join(timeout=5)
        stdout_data = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""

        if proc.returncode != 0:
            error_msg = "".join(stderr_lines).strip() or "Unknown error"
            # Filter out non-fatal warnings
            fatal_lines = [
                l for l in error_msg.split("\n")
                if "ERROR:" in l and "Reconnecting" not in l
            ]
            raise RuntimeError(
                f"Codex CLI error: {fatal_lines[-1] if fatal_lines else error_msg[-500:]}"
            )

        # Read the last message from the output file
        response_text = ""
        try:
            with open(output_file, "r") as f:
                response_text = f.read().strip()
        except FileNotFoundError:
            # Fall back to stdout if output file wasn't created
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
                message=Message(content=response_text.strip(), role="assistant"),
            ),
            usage=_make_usage(),
        )

    def _run_cli_background(self, cache_key: str, prompt: LanguageModelInput) -> None:
        """Run the Codex CLI in a background thread, storing results in cache.

        This ensures the CLI completes even if the SSE connection drops
        (e.g. user closes browser tab). The stream() generator polls the
        cache for results.
        """
        import os
        import tempfile

        system_text, user_text = _extract_system_and_user(prompt)

        self._setup_auth()

        output_file = os.path.join(
            tempfile.gettempdir(), f"codex-{cache_key}.txt"
        )

        cmd = [
            self._cli_path,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--ephemeral",
            "-o", output_file,
            "-m", self._model_name,
        ]
        instructions = system_text or _DEFAULT_INSTRUCTIONS
        escaped = instructions.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        cmd.extend(["-c", f'instructions="{escaped}"'])
        cmd.append(user_text)

        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        try:
            # Use -o for output file — process runs independently
            last_activity = time.time()
            timeout = self._timeout

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=env,
            )

            # Drain stderr to track activity
            import threading
            def _drain():
                nonlocal last_activity
                assert proc.stderr is not None
                for line in iter(proc.stderr.readline, b""):
                    last_activity = time.time()
                proc.stderr.close()

            t = threading.Thread(target=_drain, daemon=True)
            t.start()

            # Wait for completion with idle timeout
            while proc.poll() is None:
                if time.time() - last_activity > timeout:
                    proc.kill()
                    proc.wait()
                    with _cache_lock:
                        _result_cache[cache_key] = _CachedResult(
                            error=f"Codex CLI idle for {timeout}s", done=True
                        )
                    return
                time.sleep(1)

            t.join(timeout=5)
            stdout_data = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""

            if proc.returncode != 0:
                stderr_text = "".join(
                    line.decode("utf-8", errors="replace")
                    for line in (proc.stderr or [])
                )
                with _cache_lock:
                    _result_cache[cache_key] = _CachedResult(
                        error=f"Codex CLI error (exit {proc.returncode})",
                        done=True,
                    )
                return

            # Read result from output file
            response_text = ""
            try:
                with open(output_file) as f:
                    response_text = f.read().strip()
            except FileNotFoundError:
                response_text = stdout_data.strip()
            finally:
                try:
                    os.unlink(output_file)
                except OSError:
                    pass

            with _cache_lock:
                _result_cache[cache_key] = _CachedResult(
                    text=response_text, done=True
                )

        except Exception as e:
            logger.exception("Codex CLI background thread failed")
            with _cache_lock:
                _result_cache[cache_key] = _CachedResult(
                    error=str(e), done=True
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
        """Stream Codex CLI output via background execution.

        The CLI runs in a background thread that completes independently
        of the SSE connection. If the user closes the browser tab, the
        CLI still finishes and caches the result. When the stream
        generator polls, it yields the cached result.
        """
        import threading

        response_id = f"codex-{uuid.uuid4().hex[:12]}"
        created = str(int(time.time()))
        cache_key = uuid.uuid4().hex[:16]

        # Evict stale cache entries
        now = time.time()
        with _cache_lock:
            stale = [k for k, v in _result_cache.items()
                     if now - v.created_at > _CACHE_TTL_SECONDS]
            for k in stale:
                del _result_cache[k]
            _result_cache[cache_key] = _CachedResult()

        # Launch CLI in background thread
        bg = threading.Thread(
            target=self._run_cli_background,
            args=(cache_key, prompt),
            daemon=True,
        )
        bg.start()

        # Poll cache until result is ready
        timeout = timeout_override or self._timeout
        deadline = time.time() + timeout + 30  # extra buffer over CLI timeout
        while time.time() < deadline:
            with _cache_lock:
                entry = _result_cache.get(cache_key)
            if entry and entry.done:
                break
            time.sleep(1)
            # Yield empty keep-alive to prevent SSE timeout
            # (some proxies close idle connections)
        else:
            raise TimeoutError("Codex CLI did not complete in time")

        # Read result from cache
        with _cache_lock:
            entry = _result_cache.pop(cache_key, None)

        if not entry or entry.error:
            error_msg = entry.error if entry else "No result"
            raise RuntimeError(f"Codex CLI error: {error_msg}")

        if entry.text:
            yield ModelResponseStream(
                id=response_id,
                created=created,
                choice=StreamingChoice(
                    index=0,
                    delta=Delta(content=entry.text),
                ),
            )

        # Final stop event
        yield ModelResponseStream(
            id=response_id,
            created=created,
            choice=StreamingChoice(
                finish_reason="stop",
                index=0,
                delta=Delta(),
            ),
            usage=_make_usage(),
        )
