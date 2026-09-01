"""Regression tests for Codex OAuth token masking/restore logic.

When the server returns an LLM provider to the frontend, sensitive fields
in custom_config (like codex_access_token, codex_refresh_token) are masked.
If the user then edits a non-sensitive field (e.g. display_name) and saves,
the masked values come back in the update request.  The server must detect
these masked placeholders and restore the original stored values so that
the real tokens are never overwritten.
"""

from onyx.server.manage.llm.api import (
    _is_masked_value_for_existing,
    _is_sensitive_custom_config_key,
    _mask_provider_credentials,
    _mask_string,
    _restore_masked_custom_config_values,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView


def _make_provider_view(
    custom_config: dict[str, str] | None = None,
    api_key: str | None = None,
) -> LLMProviderView:
    """Build a minimal LLMProviderView for testing."""
    return LLMProviderView(
        id=1,
        name="codex-provider",
        provider="codex",
        api_key=api_key,
        custom_config=custom_config,
        model_configurations=[
            ModelConfigurationView(
                name="codex-mini",
                is_visible=True,
                supports_image_input=False,
            )
        ],
    )


# ---------------------------------------------------------------------------
# _is_sensitive_custom_config_key recognises token keys
# ---------------------------------------------------------------------------


def test_codex_access_token_is_sensitive() -> None:
    assert _is_sensitive_custom_config_key("codex_access_token") is True


def test_codex_refresh_token_is_sensitive() -> None:
    assert _is_sensitive_custom_config_key("codex_refresh_token") is True


def test_non_sensitive_key_is_not_sensitive() -> None:
    assert _is_sensitive_custom_config_key("display_name") is False


# ---------------------------------------------------------------------------
# _mask_string produces the expected format
# ---------------------------------------------------------------------------


def test_mask_string_long_value() -> None:
    result = _mask_string("abcdefghijklmnop")
    assert result == "abcd****mnop"


def test_mask_string_short_value() -> None:
    result = _mask_string("short")
    assert result == "****"


# ---------------------------------------------------------------------------
# _mask_provider_credentials masks codex tokens in custom_config
# ---------------------------------------------------------------------------


def test_mask_provider_credentials_masks_codex_tokens() -> None:
    access_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.access"
    refresh_token = "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4.refresh"

    provider = _make_provider_view(
        custom_config={
            "codex_access_token": access_token,
            "codex_refresh_token": refresh_token,
            "some_non_sensitive_field": "visible-value",
        },
    )

    _mask_provider_credentials(provider)

    assert provider.custom_config is not None
    # Tokens must be masked
    assert provider.custom_config["codex_access_token"] != access_token
    assert provider.custom_config["codex_refresh_token"] != refresh_token
    assert "****" in provider.custom_config["codex_access_token"]
    assert "****" in provider.custom_config["codex_refresh_token"]
    # Non-sensitive field must remain untouched
    assert provider.custom_config["some_non_sensitive_field"] == "visible-value"


# ---------------------------------------------------------------------------
# _is_masked_value_for_existing detects masked codex tokens
# ---------------------------------------------------------------------------


def test_is_masked_value_for_existing_recognises_masked_codex_token() -> None:
    original = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.access"
    masked = _mask_string(original)
    assert _is_masked_value_for_existing(masked, original, "codex_access_token") is True


def test_is_masked_value_for_existing_rejects_non_sensitive_key() -> None:
    original = "some-value"
    masked = _mask_string(original)
    assert (
        _is_masked_value_for_existing(masked, original, "display_name") is False
    )


# ---------------------------------------------------------------------------
# _restore_masked_custom_config_values: the core regression scenario
# ---------------------------------------------------------------------------


def test_restore_preserves_codex_tokens_when_only_display_name_changes() -> None:
    """Editing only display_name must not overwrite stored OAuth tokens."""
    access_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.real_access"
    refresh_token = "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4.real_refresh"

    existing_config: dict[str, str] = {
        "codex_access_token": access_token,
        "codex_refresh_token": refresh_token,
        "display_name": "Old Name",
    }

    # Simulate the round-trip: tokens come back masked, display_name changed
    incoming_config: dict[str, str] = {
        "codex_access_token": _mask_string(access_token),
        "codex_refresh_token": _mask_string(refresh_token),
        "display_name": "New Name",
    }

    restored = _restore_masked_custom_config_values(existing_config, incoming_config)

    assert restored is not None
    assert restored["codex_access_token"] == access_token
    assert restored["codex_refresh_token"] == refresh_token
    assert restored["display_name"] == "New Name"


def test_restore_allows_real_token_update() -> None:
    """When the user provides a new (non-masked) token, it must be accepted."""
    existing_config: dict[str, str] = {
        "codex_access_token": "old-token-value-1234567890",
        "codex_refresh_token": "old-refresh-value-1234567890",
    }

    new_access = "brand-new-access-token-xyz"
    new_refresh = "brand-new-refresh-token-xyz"

    incoming_config: dict[str, str] = {
        "codex_access_token": new_access,
        "codex_refresh_token": new_refresh,
    }

    restored = _restore_masked_custom_config_values(existing_config, incoming_config)

    assert restored is not None
    assert restored["codex_access_token"] == new_access
    assert restored["codex_refresh_token"] == new_refresh


def test_restore_returns_none_when_new_config_is_none() -> None:
    existing_config: dict[str, str] = {
        "codex_access_token": "some-token",
    }
    assert _restore_masked_custom_config_values(existing_config, None) is None


def test_restore_returns_new_config_when_existing_is_none() -> None:
    incoming_config: dict[str, str] = {
        "codex_access_token": "some-token",
    }
    result = _restore_masked_custom_config_values(None, incoming_config)
    assert result == incoming_config


def test_restore_handles_star_mask_placeholder() -> None:
    """The server also recognises the generic '****' placeholder."""
    existing_config: dict[str, str] = {
        "codex_access_token": "real-token-value-abcdef",
    }
    incoming_config: dict[str, str] = {
        "codex_access_token": "****",
    }

    restored = _restore_masked_custom_config_values(existing_config, incoming_config)

    assert restored is not None
    assert restored["codex_access_token"] == "real-token-value-abcdef"
