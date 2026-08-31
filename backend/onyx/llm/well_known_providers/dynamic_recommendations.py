"""Auto-detect the latest available models per provider from litellm.

Some providers (notably Google's Gemini endpoints) ship new models on a
fast cadence. Hand-maintaining a "recommended" list in the bundled JSON
quickly goes stale. This module derives the recommended set at runtime
by parsing version strings out of `litellm.model_cost`.

The current implementation covers Gemini on Google AI Studio and Vertex AI. Adding more
providers means writing a new `_compute_latest_<provider>_recommendations`
helper and registering it in `apply_dynamic_recommendations`.
"""

import re

from onyx.llm.well_known_providers.auto_update_models import (
    LLMProviderRecommendation,
    LLMRecommendations,
)
from onyx.llm.well_known_providers.constants import (
    GOOGLE_AI_STUDIO_PROVIDER_NAME,
    VERTEXAI_PROVIDER_NAME,
)
from onyx.llm.well_known_providers.models import SimpleKnownModel
from onyx.utils.logger import setup_logger

logger = setup_logger()


# ---------------------------------------------------------------------------
# Google AI Studio (Gemini) detection
# ---------------------------------------------------------------------------


# Strings that mark a Gemini entry as not a chat model we want to recommend.
_GEMINI_EXCLUDED_TOKENS: tuple[str, ...] = (
    "embed",
    "image",
    "video",
    "tts",
    "live",
    "veo",
    "audio",
    "search",
    "lyria",
    "learnlm",
    "robotics",
    "code",
    "gemma",
    "exp-",
    "computer-use",
    "customtools",
)

# Matches the version segment right after "gemini-": "3", "3.1", "2.5", etc.
_GEMINI_VERSION_RE = re.compile(r"^gemini-(\d+)(?:\.(\d+))?(?:-|$)")

# Matches a trailing date suffix like "-09-2025" or "-06-17" used on dated
# preview snapshots — we treat dated variants as older than the un-dated one
# at the same version.
_GEMINI_DATE_SUFFIX_RE = re.compile(r"-\d{2}-(?:\d{2}-)?\d{4}$")


def _gemini_tier(name: str) -> str | None:
    """Return 'pro' | 'flash' | 'flash-lite' or None if it isn't one we track."""
    if "flash-lite" in name:
        return "flash-lite"
    if "flash" in name:
        return "flash"
    if "pro" in name:
        return "pro"
    return None


def _parse_gemini_model(name: str) -> tuple[str, tuple[int, int], int] | None:
    """Parse a Gemini model name into (tier, (major, minor), priority).

    Returns None if the model should be ignored entirely. Higher priority
    wins ties on the same (tier, version).
    """
    lower = name.lower()
    if any(token in lower for token in _GEMINI_EXCLUDED_TOKENS):
        return None

    match = _GEMINI_VERSION_RE.match(lower)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) else 0

    tier = _gemini_tier(lower)
    if tier is None:
        return None

    # Sort priority within the same (tier, version):
    #   +1 if "preview" present (current cutting-edge variant Google ships)
    #   -2 if dated snapshot suffix is present (older snapshot of the same release)
    #   -1 if revision suffix like "-001"/"-002"
    priority = 0
    if "preview" in lower:
        priority += 1
    if _GEMINI_DATE_SUFFIX_RE.search(lower):
        priority -= 2
    if re.search(r"-\d{3}$", lower):
        priority -= 1

    return tier, (major, minor), priority


def _gemini_display_name(model_name: str, tier: str) -> str:
    """Build a human-readable label like 'Gemini 3.1 Pro Preview'."""
    match = _GEMINI_VERSION_RE.match(model_name.lower())
    if match:
        version = match.group(1)
        if match.group(2):
            version = f"{version}.{match.group(2)}"
    else:
        version = ""

    tier_label = {
        "pro": "Pro",
        "flash": "Flash",
        "flash-lite": "Flash Lite",
    }[tier]

    suffix = " Preview" if "preview" in model_name.lower() else ""
    return f"Gemini {version} {tier_label}{suffix}".strip()


def compute_latest_gemini_recommendations() -> LLMProviderRecommendation | None:
    """Pick the newest Gemini model per tier from litellm.model_cost.

    The newest release across all tiers is the default. Other tier leaders
    remain visible so admins can choose a different capability/cost profile.
    Returns None when no usable model is found so callers can use the bundled
    fallback.
    """
    try:
        import litellm
    except ImportError:
        logger.warning("litellm not importable, skipping dynamic Gemini detection")
        return None

    # Collect candidates per tier. We dedupe by model name across the
    # "gemini/" prefixed and bare key forms.
    candidates: dict[str, list[tuple[tuple[int, int], int, str]]] = {
        "pro": [],
        "flash": [],
        "flash-lite": [],
    }
    seen: set[str] = set()

    for key in list(litellm.model_cost.keys()):
        if key.startswith("gemini/"):
            name = key.removeprefix("gemini/")
        elif key.startswith("gemini-"):
            name = key
        else:
            continue
        if name in seen:
            continue
        seen.add(name)

        parsed = _parse_gemini_model(name)
        if parsed is None:
            continue
        tier, version, priority = parsed
        candidates[tier].append((version, priority, name))

    latest: dict[str, tuple[tuple[int, int], int, str]] = {}
    for tier, items in candidates.items():
        if not items:
            continue
        # Highest version, then highest priority, then alphabetical for stability.
        items.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        latest[tier] = items[0]

    if not latest:
        return None

    # Prefer the highest released version. On a version tie, Pro wins over
    # Flash, then Flash Lite.
    tier_priority = {"pro": 2, "flash": 1, "flash-lite": 0}
    default_tier = max(
        latest,
        key=lambda tier: (
            latest[tier][0],
            latest[tier][1],
            tier_priority[tier],
        ),
    )

    visible: list[SimpleKnownModel] = []
    tier_order = [
        default_tier,
        *(tier for tier in ("pro", "flash", "flash-lite") if tier != default_tier),
    ]
    for tier in tier_order:
        model = latest.get(tier)
        if model:
            name = model[2]
            visible.append(
                SimpleKnownModel(
                    name=name,
                    display_name=_gemini_display_name(name, tier),
                )
            )

    return LLMProviderRecommendation(
        default_model=visible[0],
        additional_visible_models=visible[1:],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_dynamic_recommendations(
    recommendations: LLMRecommendations,
) -> LLMRecommendations:
    """Override applicable provider entries with dynamically-detected ones.

    Google AI Studio and Vertex AI expose the same Gemini model IDs, so both
    recommendation sections track the newest detected tier leaders. Bundled
    JSON entries are used as fallbacks when detection fails.
    """
    dynamic_gemini = compute_latest_gemini_recommendations()
    if dynamic_gemini is None:
        return recommendations

    new_providers = dict(recommendations.providers)
    for provider_name in (GOOGLE_AI_STUDIO_PROVIDER_NAME, VERTEXAI_PROVIDER_NAME):
        if provider_name in new_providers:
            new_providers[provider_name] = dynamic_gemini
    logger.info(
        "Dynamic Gemini recommendation: default=%s, visible=%s",
        dynamic_gemini.default_model.name,
        [m.name for m in dynamic_gemini.additional_visible_models],
    )

    return LLMRecommendations(
        version=recommendations.version,
        updated_at=recommendations.updated_at,
        providers=new_providers,
    )
