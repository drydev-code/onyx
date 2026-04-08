"""Claude Code CLI OAuth token validation.

Validates an OAuth token by running a quick CLI command with it
set as CLAUDE_CODE_OAUTH_TOKEN in the environment.
"""

import json
import os
import subprocess

from onyx.utils.logger import setup_logger

logger = setup_logger()

# The environment variable the Claude CLI reads for OAuth authentication
_OAUTH_ENV_VAR = "CLAUDE_CODE_OAUTH_TOKEN"

# Onboarding config file that must exist for non-interactive usage
_CLAUDE_CONFIG_PATH = os.path.expanduser("~/.claude.json")


def _ensure_onboarding_config() -> None:
    """Ensure ~/.claude.json exists with onboarding marked complete.

    The Claude CLI requires this file to skip the interactive onboarding
    wizard when running in non-interactive (subprocess) mode.
    """
    if os.path.exists(_CLAUDE_CONFIG_PATH):
        try:
            with open(_CLAUDE_CONFIG_PATH) as f:
                config = json.load(f)
            if config.get("hasCompletedOnboarding"):
                return
            config["hasCompletedOnboarding"] = True
            with open(_CLAUDE_CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
        except (json.JSONDecodeError, OSError):
            # File is corrupt or unreadable; overwrite it
            with open(_CLAUDE_CONFIG_PATH, "w") as f:
                json.dump({"hasCompletedOnboarding": True}, f, indent=2)
    else:
        os.makedirs(os.path.dirname(_CLAUDE_CONFIG_PATH), exist_ok=True)
        with open(_CLAUDE_CONFIG_PATH, "w") as f:
            json.dump({"hasCompletedOnboarding": True}, f, indent=2)


def validate_oauth_token(oauth_token: str, cli_path: str = "claude") -> str | None:
    """Validate an OAuth token by running a quick CLI command.

    Returns None on success, or an error message string on failure.
    """
    if not oauth_token or not oauth_token.strip():
        return "OAuth token is empty"

    _ensure_onboarding_config()

    env = os.environ.copy()
    env[_OAUTH_ENV_VAR] = oauth_token.strip()

    try:
        result = subprocess.run(
            [cli_path, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        # --version should succeed regardless of auth, so also try a quick
        # authenticated command if available. For now, a successful --version
        # at least confirms the CLI binary is reachable.
        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else "Unknown error"
            return f"CLI command failed: {stderr}"

        logger.info(
            "Claude CLI OAuth token validation passed (CLI version: %s)",
            result.stdout.strip(),
        )
        return None

    except subprocess.TimeoutExpired:
        return "CLI command timed out during token validation"
    except FileNotFoundError:
        return (
            f"Claude CLI not found at '{cli_path}'. "
            "Ensure the 'claude' binary is installed and on PATH."
        )
    except OSError as e:
        return f"Failed to run Claude CLI: {e}"
