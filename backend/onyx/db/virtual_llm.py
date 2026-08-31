from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from onyx.db.enums import LLMModelFlowType
from onyx.db.models import LLMModelFlow, ModelConfiguration, VirtualLLMModel
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import VIRTUAL_LLM_PROVIDER_NAME, LlmProviderNames
from onyx.llm.well_known_providers.llm_provider_options import (
    get_provider_display_name,
)
from onyx.server.manage.llm.models import (
    LLMProviderDescriptor,
    LLMProviderView,
    ModelConfigurationView,
    VirtualModelProfileRequest,
    VirtualModelProfileView,
)

_PROFILE_LOAD_OPTIONS = (
    selectinload(VirtualLLMModel.model_configuration).selectinload(
        ModelConfiguration.llm_model_flows
    ),
    selectinload(VirtualLLMModel.model_configuration).selectinload(
        ModelConfiguration.llm_provider
    ),
    selectinload(VirtualLLMModel.target_model_configuration).selectinload(
        ModelConfiguration.llm_model_flows
    ),
    selectinload(VirtualLLMModel.target_model_configuration).selectinload(
        ModelConfiguration.llm_provider
    ),
)


def fetch_virtual_model_profiles(db_session: Session) -> list[VirtualLLMModel]:
    return list(
        db_session.scalars(
            select(VirtualLLMModel)
            .join(
                ModelConfiguration,
                VirtualLLMModel.model_configuration_id == ModelConfiguration.id,
            )
            .options(*_PROFILE_LOAD_OPTIONS)
            .order_by(
                func.lower(ModelConfiguration.display_name), ModelConfiguration.id
            )
        ).all()
    )


def fetch_virtual_model_profile(
    db_session: Session, model_configuration_id: int
) -> VirtualLLMModel | None:
    return db_session.scalar(
        select(VirtualLLMModel)
        .where(VirtualLLMModel.model_configuration_id == model_configuration_id)
        .options(*_PROFILE_LOAD_OPTIONS)
    )


def fetch_virtual_model_target(
    db_session: Session, model_configuration_id: int
) -> ModelConfiguration | None:
    profile = fetch_virtual_model_profile(db_session, model_configuration_id)
    return profile.target_model_configuration if profile else None


def resolve_virtual_model_target(
    db_session: Session, model_configuration: ModelConfiguration | None
) -> ModelConfiguration | None:
    if model_configuration is None:
        return None
    return (
        fetch_virtual_model_target(db_session, model_configuration.id)
        or model_configuration
    )


def is_virtual_model_configuration(
    db_session: Session, model_configuration_id: int | None
) -> bool:
    if model_configuration_id is None:
        return False
    return (
        db_session.scalar(
            select(VirtualLLMModel.model_configuration_id).where(
                VirtualLLMModel.model_configuration_id == model_configuration_id
            )
        )
        is not None
    )


def fetch_virtual_model_configuration_ids(db_session: Session) -> set[int]:
    return set(db_session.scalars(select(VirtualLLMModel.model_configuration_id)).all())


def fetch_virtual_model_target_by_provider_and_name(
    db_session: Session, provider_id: int, model_name: str
) -> ModelConfiguration | None:
    profile_id = db_session.scalar(
        select(VirtualLLMModel.model_configuration_id)
        .join(
            ModelConfiguration,
            VirtualLLMModel.model_configuration_id == ModelConfiguration.id,
        )
        .where(
            ModelConfiguration.llm_provider_id == provider_id,
            ModelConfiguration.name == model_name,
        )
    )
    return (
        fetch_virtual_model_target(db_session, profile_id)
        if profile_id is not None
        else None
    )


def fetch_default_virtual_model(
    db_session: Session,
) -> ModelConfiguration | None:
    default_profile = db_session.scalar(
        select(ModelConfiguration)
        .join(
            VirtualLLMModel,
            VirtualLLMModel.model_configuration_id == ModelConfiguration.id,
        )
        .join(
            LLMModelFlow,
            LLMModelFlow.model_configuration_id == ModelConfiguration.id,
        )
        .where(
            LLMModelFlow.llm_model_flow_type == LLMModelFlowType.CHAT,
            LLMModelFlow.is_default.is_(True),
        )
        .options(
            selectinload(ModelConfiguration.llm_provider),
            selectinload(ModelConfiguration.llm_model_flows),
        )
    )
    if default_profile is not None:
        return default_profile

    profile = db_session.scalar(
        select(VirtualLLMModel)
        .options(*_PROFILE_LOAD_OPTIONS)
        .order_by(VirtualLLMModel.model_configuration_id)
    )
    return profile.model_configuration if profile else None


def _fetch_or_create_virtual_provider(db_session: Session) -> LLMProviderModel:
    provider = db_session.scalar(
        select(LLMProviderModel)
        .where(LLMProviderModel.provider == LlmProviderNames.ONYX_VIRTUAL)
        .order_by(LLMProviderModel.id)
    )
    if provider is not None:
        return provider

    provider = LLMProviderModel(
        name=VIRTUAL_LLM_PROVIDER_NAME,
        provider=LlmProviderNames.ONYX_VIRTUAL,
        is_public=True,
        is_auto_mode=False,
    )
    db_session.add(provider)
    db_session.flush()
    return provider


def _validate_target(
    db_session: Session, target_model_configuration_id: int
) -> ModelConfiguration:
    target = db_session.scalar(
        select(ModelConfiguration)
        .where(ModelConfiguration.id == target_model_configuration_id)
        .options(
            selectinload(ModelConfiguration.llm_provider),
            selectinload(ModelConfiguration.llm_model_flows),
        )
    )
    if target is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Target model was not found")
    if target.llm_provider.provider == LlmProviderNames.ONYX_VIRTUAL:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "A model profile cannot target another model profile",
        )
    if LLMModelFlowType.CHAT not in target.llm_model_flow_types:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "A model profile target must support chat",
        )
    if not target.is_visible:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "A model profile target must be visible",
        )
    return target


def _validate_unique_name(
    db_session: Session, name: str, exclude_model_configuration_id: int | None = None
) -> None:
    stmt = (
        select(ModelConfiguration.id)
        .join(
            VirtualLLMModel,
            VirtualLLMModel.model_configuration_id == ModelConfiguration.id,
        )
        .where(func.lower(ModelConfiguration.display_name) == name.lower())
    )
    if exclude_model_configuration_id is not None:
        stmt = stmt.where(ModelConfiguration.id != exclude_model_configuration_id)
    if db_session.scalar(stmt) is not None:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"A model profile named '{name}' already exists",
        )


def create_virtual_model_profile(
    db_session: Session, request: VirtualModelProfileRequest
) -> VirtualLLMModel:
    target = _validate_target(db_session, request.target_model_configuration_id)
    _validate_unique_name(db_session, request.name)
    provider = _fetch_or_create_virtual_provider(db_session)

    model_configuration = ModelConfiguration(
        llm_provider_id=provider.id,
        name=f"profile-{uuid4().hex}",
        is_visible=True,
        max_input_tokens=None,
        display_name=request.name,
    )
    db_session.add(model_configuration)
    db_session.flush()
    db_session.add(
        LLMModelFlow(
            llm_model_flow_type=LLMModelFlowType.CHAT,
            model_configuration_id=model_configuration.id,
            is_default=False,
        )
    )
    db_session.add(
        VirtualLLMModel(
            model_configuration_id=model_configuration.id,
            target_model_configuration_id=target.id,
        )
    )
    db_session.commit()
    profile = fetch_virtual_model_profile(db_session, model_configuration.id)
    if profile is None:
        raise RuntimeError("Failed to create model profile")
    return profile


def update_virtual_model_profile(
    db_session: Session,
    model_configuration_id: int,
    request: VirtualModelProfileRequest,
) -> VirtualLLMModel:
    profile = fetch_virtual_model_profile(db_session, model_configuration_id)
    if profile is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Model profile was not found")
    target = _validate_target(db_session, request.target_model_configuration_id)
    _validate_unique_name(db_session, request.name, model_configuration_id)

    profile.model_configuration.display_name = request.name
    profile.target_model_configuration_id = target.id
    db_session.commit()
    updated = fetch_virtual_model_profile(db_session, model_configuration_id)
    if updated is None:
        raise RuntimeError("Failed to update model profile")
    return updated


def delete_virtual_model_profile(
    db_session: Session, model_configuration_id: int
) -> None:
    profile = fetch_virtual_model_profile(db_session, model_configuration_id)
    if profile is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Model profile was not found")
    if any(flow.is_default for flow in profile.model_configuration.llm_model_flows):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Change the default model profile before you delete this profile",
        )
    db_session.delete(profile.model_configuration)
    db_session.commit()


def fetch_profiles_targeting_models(
    db_session: Session, model_configuration_ids: list[int]
) -> list[str]:
    if not model_configuration_ids:
        return []
    return list(
        db_session.scalars(
            select(
                func.coalesce(ModelConfiguration.display_name, ModelConfiguration.name)
            )
            .join(
                VirtualLLMModel,
                VirtualLLMModel.model_configuration_id == ModelConfiguration.id,
            )
            .where(
                VirtualLLMModel.target_model_configuration_id.in_(
                    model_configuration_ids
                )
            )
            .order_by(ModelConfiguration.display_name)
        ).all()
    )


def _virtual_model_view(profile: VirtualLLMModel) -> ModelConfigurationView:
    target = profile.target_model_configuration
    target_view = ModelConfigurationView.from_model(
        target,
        target.llm_provider.provider,
        use_stored_display_name=target.llm_provider.custom_config is not None,
        custom_config=target.llm_provider.custom_config,
        deployment_name=target.llm_provider.deployment_name,
    )
    return target_view.model_copy(
        update={
            "id": profile.model_configuration.id,
            "name": profile.model_configuration.name,
            "is_visible": True,
            "display_name": profile.model_configuration.display_name,
            "custom_display_name": profile.model_configuration.custom_display_name,
            "provider_display_name": None,
            "vendor": None,
            "version": None,
            "region": None,
            "is_recommended_default": False,
        }
    )


def fetch_virtual_provider_descriptor(
    db_session: Session,
) -> LLMProviderDescriptor | None:
    profiles = fetch_virtual_model_profiles(db_session)
    if not profiles:
        return None
    provider = profiles[0].model_configuration.llm_provider
    return LLMProviderDescriptor(
        id=provider.id,
        name=provider.name,
        provider=provider.provider,
        provider_display_name=VIRTUAL_LLM_PROVIDER_NAME,
        model_configurations=[_virtual_model_view(profile) for profile in profiles],
    )


def fetch_virtual_provider_view(db_session: Session) -> LLMProviderView | None:
    descriptor = fetch_virtual_provider_descriptor(db_session)
    if descriptor is None:
        return None
    return LLMProviderView(
        id=descriptor.id,
        name=descriptor.name,
        provider=descriptor.provider,
        api_key=None,
        api_base=None,
        api_version=None,
        custom_config=None,
        is_public=True,
        is_auto_mode=False,
        groups=[],
        personas=[],
        deployment_name=None,
        model_configurations=descriptor.model_configurations,
    )


def virtual_model_profile_to_view(
    profile: VirtualLLMModel,
) -> VirtualModelProfileView:
    target = profile.target_model_configuration
    target_provider = target.llm_provider
    target_view = ModelConfigurationView.from_model(
        target,
        target_provider.provider,
        use_stored_display_name=target_provider.custom_config is not None,
        custom_config=target_provider.custom_config,
        deployment_name=target_provider.deployment_name,
    )
    target_display_name = (
        target_view.custom_display_name or target_view.display_name or target.name
    )
    provider_display_name = target_provider.name or get_provider_display_name(
        target_provider.provider
    )
    return VirtualModelProfileView(
        provider_id=profile.model_configuration.llm_provider_id,
        model_configuration_id=profile.model_configuration.id,
        model_name=profile.model_configuration.name,
        name=profile.model_configuration.display_name
        or profile.model_configuration.name,
        target_model_configuration_id=target.id,
        target_model_name=target.name,
        target_model_display_name=target_display_name,
        target_provider_id=target_provider.id,
        target_provider_name=provider_display_name,
        target_provider_type=target_provider.provider,
    )
