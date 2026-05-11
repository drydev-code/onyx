"""Tests for new LLM providers: zai, google_ai_studio, openai_codex, claude_code_cli.

Covers:
- factory.get_llm() routing: claude_code_cli returns ClaudeCodeCLI, others return LitellmLLM
- LitellmLLM.__init__ model name transformation for zai, google_ai_studio, openai_codex
- Well-known provider model list functions
"""

from unittest.mock import patch

from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import get_llm
from onyx.llm.well_known_providers.constants import (
    OPENAI_CODEX_ACCESS_TOKEN_KEY,
    ZAI_DEFAULT_API_BASE,
)
from onyx.llm.well_known_providers.llm_provider_options import (
    get_claude_code_cli_model_names,
    get_openai_codex_model_names,
    get_zai_model_names,
)


# ---------------------------------------------------------------------------
# factory.get_llm() routing tests
# ---------------------------------------------------------------------------


def test_get_llm_claude_code_cli_returns_claude_code_cli_instance() -> None:
    """claude_code_cli provider should return a ClaudeCodeCLI, not LitellmLLM."""
    llm = get_llm(
        provider=LlmProviderNames.CLAUDE_CODE_CLI,
        model="claude-sonnet-4-6",
        deployment_name=None,
        max_input_tokens=200000,
    )

    from onyx.llm.claude_code_cli import ClaudeCodeCLI

    assert isinstance(llm, ClaudeCodeCLI)


def test_get_llm_zai_returns_litellm_instance() -> None:
    """zai provider should return a LitellmLLM instance."""
    with patch("onyx.llm.factory.LitellmLLM") as mock_litellm_llm:
        get_llm(
            provider=LlmProviderNames.ZAI,
            model="glm-5.1",
            deployment_name=None,
            api_key="test-key",
            max_input_tokens=128000,
        )

        mock_litellm_llm.assert_called_once()


def test_get_llm_google_ai_studio_returns_litellm_instance() -> None:
    """google_ai_studio provider should return a LitellmLLM instance."""
    with patch("onyx.llm.factory.LitellmLLM") as mock_litellm_llm:
        get_llm(
            provider=LlmProviderNames.GOOGLE_AI_STUDIO,
            model="gemini-2.5-pro",
            deployment_name=None,
            api_key="test-key",
            max_input_tokens=1000000,
        )

        mock_litellm_llm.assert_called_once()


def test_get_llm_openai_codex_returns_litellm_instance() -> None:
    """openai_codex provider should return a LitellmLLM instance."""
    with patch("onyx.llm.factory.LitellmLLM") as mock_litellm_llm:
        get_llm(
            provider=LlmProviderNames.OPENAI_CODEX,
            model="o3",
            deployment_name=None,
            api_key="test-key",
            max_input_tokens=128000,
        )

        mock_litellm_llm.assert_called_once()


# ---------------------------------------------------------------------------
# LitellmLLM.__init__ model name transformation tests
# ---------------------------------------------------------------------------


def test_litellm_zai_sets_openai_custom_provider_and_api_base() -> None:
    """zai provider should set _custom_llm_provider='openai' and default api_base."""
    from onyx.llm.multi_llm import LitellmLLM

    llm = LitellmLLM(
        api_key="zai-test-key",
        model_provider=LlmProviderNames.ZAI,
        model_name="glm-5.1",
        max_input_tokens=128000,
    )

    assert llm._custom_llm_provider == "openai"
    assert llm._api_base == ZAI_DEFAULT_API_BASE


def test_litellm_zai_preserves_custom_api_base() -> None:
    """zai provider should keep a user-provided api_base instead of the default."""
    from onyx.llm.multi_llm import LitellmLLM

    custom_base = "https://custom.zai.example.com/v1"
    llm = LitellmLLM(
        api_key="zai-test-key",
        model_provider=LlmProviderNames.ZAI,
        model_name="glm-5-turbo",
        max_input_tokens=128000,
        api_base=custom_base,
    )

    assert llm._custom_llm_provider == "openai"
    assert llm._api_base == custom_base


def test_litellm_google_ai_studio_sets_gemini_custom_provider() -> None:
    """google_ai_studio provider should set _custom_llm_provider='gemini'."""
    from onyx.llm.multi_llm import LitellmLLM

    llm = LitellmLLM(
        api_key="google-test-key",
        model_provider=LlmProviderNames.GOOGLE_AI_STUDIO,
        model_name="gemini-2.5-pro",
        max_input_tokens=1000000,
    )

    assert llm._custom_llm_provider == "gemini"


def test_litellm_openai_codex_sets_openai_provider_and_reads_access_token() -> None:
    """openai_codex provider should set _custom_llm_provider='openai' and use access token as api_key."""
    from onyx.llm.multi_llm import LitellmLLM

    access_token = "codex-oauth-token-abc123"
    llm = LitellmLLM(
        api_key="original-key",
        model_provider=LlmProviderNames.OPENAI_CODEX,
        model_name="o3",
        max_input_tokens=128000,
        custom_config={OPENAI_CODEX_ACCESS_TOKEN_KEY: access_token},
    )

    assert llm._custom_llm_provider == "openai"
    assert llm._api_key == access_token


def test_litellm_openai_codex_without_access_token_keeps_api_key() -> None:
    """openai_codex provider without access token in custom_config should keep original api_key."""
    from onyx.llm.multi_llm import LitellmLLM

    llm = LitellmLLM(
        api_key="original-key",
        model_provider=LlmProviderNames.OPENAI_CODEX,
        model_name="o3",
        max_input_tokens=128000,
        custom_config={},
    )

    assert llm._custom_llm_provider == "openai"
    assert llm._api_key == "original-key"


# ---------------------------------------------------------------------------
# Well-known provider model list tests
# ---------------------------------------------------------------------------


def test_get_zai_model_names_returns_expected_models() -> None:
    """get_zai_model_names should return the static GLM model list."""
    models = get_zai_model_names()
    assert models == ["glm-5.1", "glm-5-turbo", "glm-5v-turbo"]


def test_get_claude_code_cli_model_names_returns_three_models() -> None:
    """get_claude_code_cli_model_names should return exactly 3 claude models."""
    models = get_claude_code_cli_model_names()
    assert len(models) == 3
    assert all("claude" in m for m in models)


def test_get_claude_code_cli_model_names_contains_expected_models() -> None:
    """get_claude_code_cli_model_names should contain the expected model names."""
    models = get_claude_code_cli_model_names()
    assert "claude-opus-4-6" in models
    assert "claude-sonnet-4-6" in models
    assert "claude-haiku-4-5" in models


def test_get_openai_codex_model_names_returns_seven_models() -> None:
    """get_openai_codex_model_names should return exactly 7 models."""
    models = get_openai_codex_model_names()
    assert len(models) == 7


def test_get_openai_codex_model_names_contains_expected_models() -> None:
    """get_openai_codex_model_names should contain the expected model names."""
    models = get_openai_codex_model_names()
    expected = {"gpt-5.4", "gpt-5.2", "o4-mini", "o3", "o3-mini", "gpt-4.1", "gpt-4.1-mini"}
    assert set(models) == expected
