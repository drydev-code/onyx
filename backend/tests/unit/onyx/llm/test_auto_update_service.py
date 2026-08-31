from datetime import datetime, timezone
from unittest.mock import patch

from onyx.llm.well_known_providers import auto_update_service
from onyx.llm.well_known_providers.auto_update_models import (
    LLMProviderRecommendation,
    LLMRecommendations,
)
from onyx.llm.well_known_providers.models import SimpleKnownModel


def _recommendations(
    *, version: str, updated_at: datetime, models_by_provider: dict[str, str]
) -> LLMRecommendations:
    return LLMRecommendations(
        version=version,
        updated_at=updated_at,
        providers={
            provider_name: LLMProviderRecommendation(
                default_model=SimpleKnownModel(name=model_name),
                additional_visible_models=[],
            )
            for provider_name, model_name in models_by_provider.items()
        },
    )


def test_bundled_recommendations_override_older_remote_conflicts() -> None:
    remote = _recommendations(
        version="1.0",
        updated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        models_by_provider={"openai": "gpt-old", "remote_only": "remote-model"},
    )
    bundled = _recommendations(
        version="1.1",
        updated_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        models_by_provider={"openai": "gpt-new", "bundled_only": "local-model"},
    )

    with (
        patch.object(
            auto_update_service, "load_bundled_recommendations", return_value=bundled
        ),
        patch.object(
            auto_update_service,
            "fetch_llm_recommendations_from_github",
            return_value=remote,
        ),
        patch.object(
            auto_update_service,
            "apply_dynamic_recommendations",
            side_effect=lambda recommendations: recommendations,
        ),
    ):
        merged = auto_update_service.get_merged_recommendations()

    assert merged.version == "1.1"
    assert merged.updated_at == bundled.updated_at
    assert merged.providers["openai"].default_model.name == "gpt-new"
    assert merged.providers["remote_only"].default_model.name == "remote-model"
    assert merged.providers["bundled_only"].default_model.name == "local-model"


def test_newer_remote_recommendations_override_bundled_conflicts() -> None:
    bundled = _recommendations(
        version="1.1",
        updated_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        models_by_provider={"openai": "gpt-bundled"},
    )
    remote = _recommendations(
        version="1.2",
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        models_by_provider={"openai": "gpt-remote"},
    )

    with (
        patch.object(
            auto_update_service, "load_bundled_recommendations", return_value=bundled
        ),
        patch.object(
            auto_update_service,
            "fetch_llm_recommendations_from_github",
            return_value=remote,
        ),
        patch.object(
            auto_update_service,
            "apply_dynamic_recommendations",
            side_effect=lambda recommendations: recommendations,
        ),
    ):
        merged = auto_update_service.get_merged_recommendations()

    assert merged.version == "1.2"
    assert merged.updated_at == remote.updated_at
    assert merged.providers["openai"].default_model.name == "gpt-remote"
