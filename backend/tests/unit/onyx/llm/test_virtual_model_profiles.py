from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

from pytest import MonkeyPatch

from onyx.db import llm as db_llm
from onyx.db import virtual_llm
from onyx.db.enums import LLMModelFlowType
from onyx.db.models import LLMModelFlow, ModelConfiguration, User, VirtualLLMModel
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.llm import factory
from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import ReasoningEffort
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView


def _provider_view(provider: str, model_name: str, provider_id: int) -> LLMProviderView:
    return LLMProviderView(
        id=provider_id,
        name=provider,
        provider=provider,
        api_key=None,
        api_base=None,
        api_version=None,
        custom_config=None,
        is_public=True,
        is_auto_mode=False,
        groups=[],
        personas=[],
        deployment_name=None,
        model_configurations=[
            ModelConfigurationView(
                id=provider_id,
                name=model_name,
                is_visible=True,
                max_input_tokens=128_000,
                supports_image_input=True,
            )
        ],
    )


def test_llm_from_virtual_provider_resolves_current_physical_target(
    monkeypatch: MonkeyPatch,
) -> None:
    alias_provider = _provider_view(
        LlmProviderNames.ONYX_VIRTUAL, "profile-stable-id", 41
    )
    physical_provider = _provider_view(LlmProviderNames.OPENAI, "gpt-4o", 7)
    target_provider_model = object()
    target = SimpleNamespace(name="gpt-4o", llm_provider=target_provider_model)
    profile = SimpleNamespace(target_model_configuration=target)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        factory,
        "get_session_with_current_tenant",
        lambda: nullcontext(object()),
    )
    monkeypatch.setattr(
        factory,
        "fetch_virtual_model_profile_by_provider_and_name",
        lambda _session, provider_id, model_name: (
            profile if (provider_id, model_name) == (41, "profile-stable-id") else None
        ),
    )
    monkeypatch.setattr(
        factory,
        "virtual_model_configuration_to_view",
        lambda _profile: ModelConfigurationView(
            id=41,
            name="profile-stable-id",
            is_visible=True,
            max_input_tokens=32_000,
            supports_image_input=True,
            reasoning_effort_max=ReasoningEffort.HIGH,
            reasoning_effort_default=ReasoningEffort.MEDIUM,
            temperature_default=0.4,
        ),
    )
    monkeypatch.setattr(
        factory.LLMProviderView,
        "from_model",
        lambda _provider: physical_provider,
    )

    def fake_get_llm(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(factory, "get_llm", fake_get_llm)

    factory.llm_from_provider("profile-stable-id", alias_provider)

    assert captured["provider"] == LlmProviderNames.OPENAI
    assert captured["model"] == "gpt-4o"
    assert captured["max_input_tokens"] == 32_000
    assert captured["reasoning_effort_max"] == ReasoningEffort.HIGH
    assert captured["reasoning_effort_default"] == ReasoningEffort.MEDIUM
    assert captured["temperature"] == 0.4


def test_virtual_model_view_uses_alias_identity_and_target_capabilities(
    monkeypatch: MonkeyPatch,
) -> None:
    target_provider = LLMProviderModel(
        id=7,
        name="OpenAI Production",
        provider=LlmProviderNames.OPENAI,
        is_public=True,
        is_auto_mode=False,
    )
    target = ModelConfiguration(
        id=17,
        llm_provider_id=7,
        name="gpt-4o",
        is_visible=True,
        max_input_tokens=64_000,
        display_name="GPT-4o",
        custom_display_name=None,
        reasoning_effort_max=None,
        reasoning_effort_default=None,
        temperature_default=None,
    )
    target.llm_provider = target_provider
    target.llm_model_flows = [
        LLMModelFlow(
            llm_model_flow_type=LLMModelFlowType.CHAT,
            model_configuration_id=17,
            is_default=False,
        ),
        LLMModelFlow(
            llm_model_flow_type=LLMModelFlowType.VISION,
            model_configuration_id=17,
            is_default=False,
        ),
    ]

    alias_provider = LLMProviderModel(
        id=41,
        name="Model Profiles",
        provider=LlmProviderNames.ONYX_VIRTUAL,
        is_public=True,
        is_auto_mode=False,
    )
    alias = ModelConfiguration(
        id=51,
        llm_provider_id=41,
        name="profile-stable-id",
        is_visible=True,
        max_input_tokens=32_000,
        display_name="Normal Agent",
        custom_display_name=None,
        reasoning_effort_max=ReasoningEffort.HIGH,
        reasoning_effort_default=ReasoningEffort.MEDIUM,
        temperature_default=0.3,
    )
    alias.llm_provider = alias_provider
    alias.llm_model_flows = [
        LLMModelFlow(
            llm_model_flow_type=LLMModelFlowType.CHAT,
            model_configuration_id=51,
            is_default=False,
        )
    ]
    profile = VirtualLLMModel(
        model_configuration_id=51,
        target_model_configuration_id=17,
    )
    profile.model_configuration = alias
    profile.target_model_configuration = target

    monkeypatch.setattr(
        virtual_llm.ModelConfigurationView,
        "from_model",
        lambda *_args, **_kwargs: ModelConfigurationView(
            id=17,
            name="gpt-4o",
            is_visible=True,
            max_input_tokens=64_000,
            supports_image_input=True,
            display_name="GPT-4o",
            provider_display_name="OpenAI",
            vendor="OpenAI",
            reasoning_effort_max=ReasoningEffort.XHIGH,
            reasoning_effort_default=ReasoningEffort.HIGH,
            temperature_default=0.7,
        ),
    )

    view = virtual_llm.virtual_model_configuration_to_view(profile)

    assert view.id == 51
    assert view.name == "profile-stable-id"
    assert view.display_name == "Normal Agent"
    assert view.max_input_tokens == 32_000
    assert view.reasoning_effort_max == ReasoningEffort.HIGH
    assert view.reasoning_effort_default == ReasoningEffort.MEDIUM
    assert view.temperature_default == 0.3
    assert view.supports_image_input is True
    assert view.provider_display_name is None
    assert view.vendor is None


def test_managed_catalog_returns_only_virtual_provider(
    monkeypatch: MonkeyPatch,
) -> None:
    virtual_provider = _provider_view(
        LlmProviderNames.ONYX_VIRTUAL, "profile-stable-id", 41
    )
    monkeypatch.setattr(
        "onyx.server.settings.store.load_settings",
        lambda: SimpleNamespace(virtual_model_profiles_enabled=True),
    )
    monkeypatch.setattr(
        virtual_llm,
        "fetch_virtual_provider_view",
        lambda _session: virtual_provider,
    )

    providers = db_llm.fetch_all_accessible_llm_providers(
        cast(Any, object()), cast(User, object())
    )

    assert providers == [virtual_provider]
    assert (
        db_llm.fetch_accessible_llm_provider_by_id(
            cast(Any, object()), cast(User, object()), 41
        )
        == virtual_provider
    )
    assert (
        db_llm.fetch_accessible_llm_provider_by_id(
            cast(Any, object()), cast(User, object()), 7
        )
        is None
    )
