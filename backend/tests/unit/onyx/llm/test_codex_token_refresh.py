"""Tests for Codex OAuth token expiry detection and refresh behavior.

Covers the OPENAI_CODEX branch in LitellmLLM.__init__ that checks
codex_token_expires_at, calls refresh_access_token() when expired,
and falls back to the existing access token on failure.
"""

import time
from unittest.mock import MagicMock, patch

from onyx.llm.constants import LlmProviderNames
from onyx.llm.well_known_providers.constants import (
    OPENAI_CODEX_ACCESS_TOKEN_KEY,
    OPENAI_CODEX_REFRESH_TOKEN_KEY,
    OPENAI_CODEX_TOKEN_EXPIRES_AT_KEY,
)


def _build_codex_llm(custom_config: dict) -> "LitellmLLM":  # noqa: F821
    """Helper to instantiate a LitellmLLM with the openai_codex provider."""
    from onyx.llm.multi_llm import LitellmLLM

    return LitellmLLM(
        api_key="fallback-key",
        model_provider=LlmProviderNames.OPENAI_CODEX,
        model_name="o3",
        max_input_tokens=128000,
        custom_config=custom_config,
    )


# ---------------------------------------------------------------------------
# Token expiry detection
# ---------------------------------------------------------------------------


def test_expired_token_triggers_refresh() -> None:
    """When codex_token_expires_at is in the past, refresh_access_token is called."""
    expired_ts = str(time.time() - 3600)  # 1 hour ago
    mock_token_response = MagicMock()
    mock_token_response.access_token = "new-access-token"
    mock_token_response.refresh_token = "new-refresh-token"
    mock_token_response.expires_in = 3600

    custom_config = {
        OPENAI_CODEX_ACCESS_TOKEN_KEY: "old-access-token",
        OPENAI_CODEX_REFRESH_TOKEN_KEY: "my-refresh-token",
        OPENAI_CODEX_TOKEN_EXPIRES_AT_KEY: expired_ts,
    }

    with patch(
        "onyx.server.manage.llm.codex_oauth.refresh_access_token",
        return_value=mock_token_response,
    ) as mock_refresh:
        llm = _build_codex_llm(custom_config)

    mock_refresh.assert_called_once_with("my-refresh-token")
    assert llm._api_key == "new-access-token"


def test_non_expired_token_skips_refresh() -> None:
    """When codex_token_expires_at is in the future, no refresh happens."""
    future_ts = str(time.time() + 3600)  # 1 hour from now

    custom_config = {
        OPENAI_CODEX_ACCESS_TOKEN_KEY: "still-valid-token",
        OPENAI_CODEX_REFRESH_TOKEN_KEY: "my-refresh-token",
        OPENAI_CODEX_TOKEN_EXPIRES_AT_KEY: future_ts,
    }

    with patch(
        "onyx.server.manage.llm.codex_oauth.refresh_access_token",
    ) as mock_refresh:
        llm = _build_codex_llm(custom_config)

    mock_refresh.assert_not_called()
    assert llm._api_key == "still-valid-token"


def test_missing_expiry_field_skips_refresh() -> None:
    """When codex_token_expires_at is absent, no refresh attempt is made."""
    custom_config = {
        OPENAI_CODEX_ACCESS_TOKEN_KEY: "access-token-no-expiry",
        OPENAI_CODEX_REFRESH_TOKEN_KEY: "my-refresh-token",
        # No OPENAI_CODEX_TOKEN_EXPIRES_AT_KEY
    }

    with patch(
        "onyx.server.manage.llm.codex_oauth.refresh_access_token",
    ) as mock_refresh:
        llm = _build_codex_llm(custom_config)

    mock_refresh.assert_not_called()
    assert llm._api_key == "access-token-no-expiry"


# ---------------------------------------------------------------------------
# Successful refresh
# ---------------------------------------------------------------------------


def test_successful_refresh_updates_api_key_and_config() -> None:
    """After a successful refresh, _api_key and custom_config are updated."""
    expired_ts = str(time.time() - 60)
    mock_token_response = MagicMock()
    mock_token_response.access_token = "refreshed-access-token"
    mock_token_response.refresh_token = "refreshed-refresh-token"
    mock_token_response.expires_in = 7200

    custom_config = {
        OPENAI_CODEX_ACCESS_TOKEN_KEY: "stale-token",
        OPENAI_CODEX_REFRESH_TOKEN_KEY: "original-refresh-token",
        OPENAI_CODEX_TOKEN_EXPIRES_AT_KEY: expired_ts,
    }

    with patch(
        "onyx.server.manage.llm.codex_oauth.refresh_access_token",
        return_value=mock_token_response,
    ):
        llm = _build_codex_llm(custom_config)

    assert llm._api_key == "refreshed-access-token"
    assert (
        llm._custom_config[OPENAI_CODEX_ACCESS_TOKEN_KEY] == "refreshed-access-token"
    )
    assert (
        llm._custom_config[OPENAI_CODEX_REFRESH_TOKEN_KEY]
        == "refreshed-refresh-token"
    )
    # The new expires_at should be in the future
    new_expires_at = float(llm._custom_config[OPENAI_CODEX_TOKEN_EXPIRES_AT_KEY])
    assert new_expires_at > time.time()


# ---------------------------------------------------------------------------
# Refresh failure fallback
# ---------------------------------------------------------------------------


def test_refresh_failure_keeps_original_token() -> None:
    """When refresh_access_token raises, the original access token is kept."""
    expired_ts = str(time.time() - 3600)

    custom_config = {
        OPENAI_CODEX_ACCESS_TOKEN_KEY: "original-token-before-failure",
        OPENAI_CODEX_REFRESH_TOKEN_KEY: "my-refresh-token",
        OPENAI_CODEX_TOKEN_EXPIRES_AT_KEY: expired_ts,
    }

    with patch(
        "onyx.server.manage.llm.codex_oauth.refresh_access_token",
        side_effect=Exception("network error"),
    ):
        llm = _build_codex_llm(custom_config)

    assert llm._api_key == "original-token-before-failure"


# ---------------------------------------------------------------------------
# Missing refresh token
# ---------------------------------------------------------------------------


def test_missing_refresh_token_skips_refresh() -> None:
    """When only access_token exists (no refresh_token), refresh is skipped."""
    expired_ts = str(time.time() - 3600)

    custom_config = {
        OPENAI_CODEX_ACCESS_TOKEN_KEY: "access-only-token",
        # No OPENAI_CODEX_REFRESH_TOKEN_KEY
        OPENAI_CODEX_TOKEN_EXPIRES_AT_KEY: expired_ts,
    }

    with patch(
        "onyx.server.manage.llm.codex_oauth.refresh_access_token",
    ) as mock_refresh:
        llm = _build_codex_llm(custom_config)

    mock_refresh.assert_not_called()
    assert llm._api_key == "access-only-token"
