import subprocess

from onyx.utils.logger import setup_logger

logger = setup_logger()


def check_claude_cli_available() -> bool:
    """Check if the Claude Code CLI is installed and reachable."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    except Exception:
        logger.warning("Unexpected error checking Claude CLI availability")
        return False


def check_codex_cli_available() -> bool:
    """Check if the OpenAI Codex CLI is installed and reachable."""
    try:
        result = subprocess.run(
            ["codex", "--version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    except Exception:
        logger.warning("Unexpected error checking Codex CLI availability")
        return False


def get_cli_availability() -> dict[str, bool]:
    """Return availability status for all supported CLI tools."""
    return {
        "claude_code": check_claude_cli_available(),
        "codex": check_codex_cli_available(),
    }
