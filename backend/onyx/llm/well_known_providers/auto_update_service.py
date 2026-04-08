"""Service for fetching and syncing LLM model configurations from GitHub.

This service manages Auto mode LLM providers, where models and configuration
are managed centrally via a GitHub-hosted JSON file. In Auto mode:
- Model list is controlled by GitHub config
- Model visibility is controlled by GitHub config
- Default model is controlled by GitHub config
- Admin only needs to provide API credentials
"""

import json
import pathlib
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import AUTO_LLM_CONFIG_URL
from onyx.db.llm import fetch_auto_mode_providers
from onyx.db.llm import sync_auto_mode_models
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.llm.well_known_providers.dynamic_recommendations import (
    apply_dynamic_recommendations,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CACHE_KEY_LAST_UPDATED_AT = "auto_llm_update:last_updated_at"
_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours


def _get_cached_last_updated_at() -> datetime | None:
    try:
        value = get_cache_backend().get(_CACHE_KEY_LAST_UPDATED_AT)
        if value is not None:
            return datetime.fromisoformat(value.decode("utf-8"))
    except Exception as e:
        logger.warning(f"Failed to get cached last_updated_at: {e}")
    return None


def _set_cached_last_updated_at(updated_at: datetime) -> None:
    try:
        get_cache_backend().set(
            _CACHE_KEY_LAST_UPDATED_AT,
            updated_at.isoformat(),
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception as e:
        logger.warning(f"Failed to set cached last_updated_at: {e}")


def load_bundled_recommendations() -> LLMRecommendations:
    """Load the recommendations JSON file bundled with the backend."""
    json_path = pathlib.Path(__file__).parent / "recommended-models.json"
    with open(json_path, "r") as f:
        json_config = json.load(f)
    return LLMRecommendations.model_validate(json_config)


def fetch_llm_recommendations_from_github(
    timeout: float = 30.0,
) -> LLMRecommendations | None:
    """Fetch LLM configuration from GitHub.

    Returns:
        GitHubLLMConfig if successful, None on error.
    """
    if not AUTO_LLM_CONFIG_URL:
        logger.debug("AUTO_LLM_CONFIG_URL not configured, skipping fetch")
        return None

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(AUTO_LLM_CONFIG_URL)
            response.raise_for_status()

            data = response.json()
            return LLMRecommendations.model_validate(data)
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch LLM config from GitHub: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing LLM config: {e}")
        return None


def get_merged_recommendations() -> LLMRecommendations:
    """Return bundled recommendations merged with the remote GitHub config.

    GitHub takes precedence on conflicts so upstream can override bundled
    defaults, but bundled providers (e.g. zai, google_ai_studio) survive when
    upstream omits them. If the GitHub fetch fails or AUTO_LLM_CONFIG_URL is
    unset, the bundled config is used alone.

    After merging, dynamic per-provider detection (e.g. latest Gemini per tier
    pulled from litellm) is applied so visible model lists stay current
    without hand-editing the JSON.
    """
    bundled = load_bundled_recommendations()
    remote = fetch_llm_recommendations_from_github()

    if remote is None:
        merged = bundled
    else:
        merged_providers = dict(bundled.providers)
        merged_providers.update(remote.providers)
        merged = LLMRecommendations(
            version=remote.version,
            updated_at=remote.updated_at,
            providers=merged_providers,
        )

    return apply_dynamic_recommendations(merged)


def sync_llm_models_from_github(
    db_session: Session,
    force: bool = False,
) -> dict[str, int]:
    """Sync models from GitHub config to database for all Auto mode providers.

    In Auto mode, EVERYTHING is controlled by GitHub config:
    - Model list
    - Model visibility (is_visible)
    - Default model
    - Fast default model

    Args:
        db_session: Database session
        config: GitHub LLM configuration
        force: If True, skip the updated_at check and force sync

    Returns:
        Dict of provider_name -> number of changes made.
    """
    results: dict[str, int] = {}

    # Get all providers in Auto mode
    auto_providers = fetch_auto_mode_providers(db_session)
    if not auto_providers:
        logger.debug("No providers in Auto mode found")
        return {}

    # Build the merged config (bundled + GitHub). Bundled gives us coverage for
    # providers that the upstream JSON doesn't know about (zai, google_ai_studio,
    # openai_codex, claude_code_cli); GitHub overrides on conflicts.
    config = get_merged_recommendations()

    # Skip if we've already processed this version (unless forced)
    last_updated_at = _get_cached_last_updated_at()
    if not force and last_updated_at and config.updated_at <= last_updated_at:
        logger.debug("LLM recommendations unchanged, skipping sync")
        _set_cached_last_updated_at(config.updated_at)
        return {}

    for provider in auto_providers:
        provider_type = provider.provider  # e.g., "openai", "anthropic"

        if provider_type not in config.providers:
            logger.debug(
                f"No config for provider type '{provider_type}' in GitHub config"
            )
            continue

        # Sync models - this replaces the model list entirely for Auto mode
        changes = sync_auto_mode_models(
            db_session=db_session,
            provider=provider,
            llm_recommendations=config,
        )

        if changes > 0:
            results[provider.name] = changes
            logger.info(
                f"Applied {changes} model changes to provider '{provider.name}'"
            )

    _set_cached_last_updated_at(config.updated_at)
    return results


def reset_cache() -> None:
    """Reset the cache timestamp. Useful for testing."""
    try:
        get_cache_backend().delete(_CACHE_KEY_LAST_UPDATED_AT)
    except Exception as e:
        logger.warning(f"Failed to reset cache: {e}")
