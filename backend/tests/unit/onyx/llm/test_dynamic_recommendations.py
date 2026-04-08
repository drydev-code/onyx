"""Unit tests for dynamic_recommendations.compute_latest_gemini_recommendations.

The function reads `litellm.model_cost` to pick the newest Gemini model per
tier. We monkeypatch litellm.model_cost in each test so the assertions don't
depend on whichever litellm version is installed.
"""

from unittest.mock import patch

import pytest

from onyx.llm.well_known_providers.dynamic_recommendations import (
    _gemini_display_name,
    _parse_gemini_model,
    apply_dynamic_recommendations,
    compute_latest_gemini_recommendations,
)
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("gemini-3.1-pro-preview", ("pro", (3, 1), 1)),
        ("gemini-3-pro-preview", ("pro", (3, 0), 1)),
        ("gemini-2.5-pro", ("pro", (2, 5), 0)),
        ("gemini-3-flash-preview", ("flash", (3, 0), 1)),
        ("gemini-3.1-flash-lite-preview", ("flash-lite", (3, 1), 1)),
        ("gemini-2.5-flash-lite", ("flash-lite", (2, 5), 0)),
        # Dated snapshot — same version as 2.5 flash but lower priority.
        ("gemini-2.5-flash-preview-09-2025", ("flash", (2, 5), -1)),
        # Revision suffix — penalised vs the un-suffixed entry.
        ("gemini-2.0-flash-001", ("flash", (2, 0), -1)),
        ("gemini-1.5-flash", ("flash", (1, 5), 0)),
    ],
)
def test_parse_gemini_model_extracts_tier_and_version(
    name: str, expected: tuple[str, tuple[int, int], int]
) -> None:
    assert _parse_gemini_model(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        # Customtools / experimental / computer-use variants are skipped.
        "gemini-3.1-pro-preview-customtools",
        "gemini-2.5-computer-use-preview-10-2025",
        "gemini-exp-1206",
        # "-latest" aliases don't have a parseable version.
        "gemini-pro-latest",
        "gemini-flash-latest",
        # Sibling families that share the prefix but aren't gemini chat models.
        "gemma-3-27b-it",
        "gemini-embedding-001",
    ],
)
def test_parse_gemini_model_skips_non_chat_variants(name: str) -> None:
    assert _parse_gemini_model(name) is None


# ---------------------------------------------------------------------------
# Display name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,tier,expected",
    [
        ("gemini-3.1-pro-preview", "pro", "Gemini 3.1 Pro Preview"),
        ("gemini-3-pro-preview", "pro", "Gemini 3 Pro Preview"),
        ("gemini-3.1-flash-lite-preview", "flash-lite", "Gemini 3.1 Flash Lite Preview"),
        ("gemini-2.5-pro", "pro", "Gemini 2.5 Pro"),
        ("gemini-2.5-flash", "flash", "Gemini 2.5 Flash"),
    ],
)
def test_gemini_display_name(name: str, tier: str, expected: str) -> None:
    assert _gemini_display_name(name, tier) == expected


# ---------------------------------------------------------------------------
# Picker
# ---------------------------------------------------------------------------


def _fake_model_cost(*names: str) -> dict[str, dict]:
    """Build a stand-in for litellm.model_cost containing only the given names."""
    return {n: {} for n in names}


def test_compute_latest_picks_highest_version_per_tier() -> None:
    fake_cost = _fake_model_cost(
        "gemini-3.1-pro-preview",
        "gemini-3-pro-preview",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-3.1-flash-lite-preview",
        "gemini-2.5-flash-lite",
    )
    with patch("litellm.model_cost", fake_cost):
        rec = compute_latest_gemini_recommendations()

    assert rec is not None
    assert rec.default_model.name == "gemini-3.1-pro-preview"
    additional = {m.name for m in rec.additional_visible_models}
    assert additional == {
        "gemini-3-flash-preview",  # no 3.1 flash exists, so 3.0 wins
        "gemini-3.1-flash-lite-preview",
    }


def test_compute_latest_handles_gemini_prefixed_keys() -> None:
    """litellm exposes both 'gemini/<name>' and bare '<name>' keys; we dedupe."""
    fake_cost = _fake_model_cost(
        "gemini/gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview",  # duplicate of the above
        "gemini/gemini-3-flash-preview",
    )
    with patch("litellm.model_cost", fake_cost):
        rec = compute_latest_gemini_recommendations()

    assert rec is not None
    assert rec.default_model.name == "gemini-3.1-pro-preview"
    assert {m.name for m in rec.additional_visible_models} == {
        "gemini-3-flash-preview"
    }


def test_compute_latest_prefers_undated_over_dated_snapshot() -> None:
    fake_cost = _fake_model_cost(
        "gemini-2.5-flash",
        "gemini-2.5-flash-preview-09-2025",
        "gemini-2.5-pro",
    )
    with patch("litellm.model_cost", fake_cost):
        rec = compute_latest_gemini_recommendations()

    assert rec is not None
    flash_models = [
        m for m in [rec.default_model] + list(rec.additional_visible_models)
        if m.name.startswith("gemini-2.5-flash")
    ]
    assert flash_models[0].name == "gemini-2.5-flash"


def test_compute_latest_returns_none_without_pro_model() -> None:
    """Without a pro tier the recommendation would be lopsided — fall back."""
    fake_cost = _fake_model_cost("gemini-3-flash-preview")
    with patch("litellm.model_cost", fake_cost):
        rec = compute_latest_gemini_recommendations()
    assert rec is None


def test_compute_latest_skips_customtools_and_exp_variants() -> None:
    fake_cost = _fake_model_cost(
        "gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview-customtools",
        "gemini-exp-1206",
        "gemini-2.5-computer-use-preview-10-2025",
    )
    with patch("litellm.model_cost", fake_cost):
        rec = compute_latest_gemini_recommendations()
    assert rec is not None
    assert rec.default_model.name == "gemini-3.1-pro-preview"
    assert rec.additional_visible_models == []


# ---------------------------------------------------------------------------
# apply_dynamic_recommendations integration
# ---------------------------------------------------------------------------


def test_apply_dynamic_recommendations_overrides_google_ai_studio() -> None:
    from datetime import datetime, timezone

    from onyx.llm.well_known_providers.auto_update_models import (
        LLMProviderRecommendation,
    )
    from onyx.llm.well_known_providers.models import SimpleKnownModel

    bundled = LLMRecommendations(
        version="1.0",
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        providers={
            "google_ai_studio": LLMProviderRecommendation(
                default_model=SimpleKnownModel(
                    name="gemini-2.5-pro", display_name="Old"
                ),
                additional_visible_models=[],
            ),
            # Should be left alone — only google_ai_studio is dynamic.
            "openai": LLMProviderRecommendation(
                default_model=SimpleKnownModel(name="gpt-4o", display_name="GPT-4o"),
                additional_visible_models=[],
            ),
        },
    )
    fake_cost = _fake_model_cost("gemini-3.1-pro-preview", "gemini-3-flash-preview")
    with patch("litellm.model_cost", fake_cost):
        result = apply_dynamic_recommendations(bundled)

    assert (
        result.providers["google_ai_studio"].default_model.name
        == "gemini-3.1-pro-preview"
    )
    # OpenAI must be untouched
    assert result.providers["openai"].default_model.name == "gpt-4o"


def test_apply_dynamic_recommendations_falls_back_when_detection_fails() -> None:
    from datetime import datetime, timezone

    from onyx.llm.well_known_providers.auto_update_models import (
        LLMProviderRecommendation,
    )
    from onyx.llm.well_known_providers.models import SimpleKnownModel

    bundled = LLMRecommendations(
        version="1.0",
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        providers={
            "google_ai_studio": LLMProviderRecommendation(
                default_model=SimpleKnownModel(
                    name="gemini-3-pro-preview", display_name="Gemini 3 Pro"
                ),
                additional_visible_models=[],
            ),
        },
    )
    # No pro models in litellm → detection returns None → bundled is preserved.
    with patch("litellm.model_cost", _fake_model_cost("gemini-3-flash-preview")):
        result = apply_dynamic_recommendations(bundled)

    assert (
        result.providers["google_ai_studio"].default_model.name
        == "gemini-3-pro-preview"
    )
