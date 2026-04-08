"""
Unit tests for the ImageRouter and Google AI Studio image generation providers.

Verifies that:
1. ImageGenerationProviderName enum includes IMAGEROUTER and GOOGLE_AI_STUDIO
2. PROVIDERS dict maps the new enum values to the correct provider classes
3. ImageRouter provider: credential validation, building, generate_image behavior
4. Google AI Studio provider: credential validation, building, generate_image behavior
"""

from unittest.mock import patch

import pytest

from onyx.image_gen.exceptions import ImageProviderCredentialsError
from onyx.image_gen.factory import get_image_generation_provider
from onyx.image_gen.factory import ImageGenerationProviderName
from onyx.image_gen.factory import PROVIDERS
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ReferenceImage
from onyx.image_gen.providers.google_ai_studio_img_gen import (
    GoogleAIStudioImageGenerationProvider,
)
from onyx.image_gen.providers.imagerouter_img_gen import (
    ImageRouterImageGenerationProvider,
)

IMAGEROUTER_PROVIDER = "imagerouter"
GOOGLE_AI_STUDIO_PROVIDER = "google_ai_studio"


def _get_default_image_gen_creds() -> ImageGenerationProviderCredentials:
    return ImageGenerationProviderCredentials(
        api_key=None,
        api_base=None,
        api_version=None,
        deployment_name=None,
        custom_config=None,
    )


# -------------------------------------------------------------------
# Factory / enum tests
# -------------------------------------------------------------------


def test_enum_includes_imagerouter() -> None:
    assert ImageGenerationProviderName.IMAGEROUTER.value == "imagerouter"


def test_enum_includes_google_ai_studio() -> None:
    assert ImageGenerationProviderName.GOOGLE_AI_STUDIO.value == "google_ai_studio"


def test_providers_dict_maps_imagerouter() -> None:
    assert (
        PROVIDERS[ImageGenerationProviderName.IMAGEROUTER]
        is ImageRouterImageGenerationProvider
    )


def test_providers_dict_maps_google_ai_studio() -> None:
    assert (
        PROVIDERS[ImageGenerationProviderName.GOOGLE_AI_STUDIO]
        is GoogleAIStudioImageGenerationProvider
    )


# -------------------------------------------------------------------
# ImageRouter credential validation
# -------------------------------------------------------------------


def test_imagerouter_validate_credentials_true_when_api_key_present() -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = "ir-test-key"

    assert ImageRouterImageGenerationProvider.validate_credentials(credentials) is True


def test_imagerouter_validate_credentials_false_when_api_key_missing() -> None:
    credentials = _get_default_image_gen_creds()

    assert ImageRouterImageGenerationProvider.validate_credentials(credentials) is False


def test_imagerouter_validate_credentials_false_when_api_key_empty() -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = ""

    assert ImageRouterImageGenerationProvider.validate_credentials(credentials) is False


# -------------------------------------------------------------------
# ImageRouter building
# -------------------------------------------------------------------


def test_build_imagerouter_provider_from_api_key() -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = "ir-test-key"

    provider = get_image_generation_provider(IMAGEROUTER_PROVIDER, credentials)

    assert isinstance(provider, ImageRouterImageGenerationProvider)
    assert provider._api_key == "ir-test-key"
    assert provider._api_base == "https://api.imagerouter.io/v1/openai"


def test_build_imagerouter_provider_with_custom_api_base() -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = "ir-test-key"
    credentials.api_base = "https://custom.imagerouter.io/v1"

    provider = get_image_generation_provider(IMAGEROUTER_PROVIDER, credentials)

    assert isinstance(provider, ImageRouterImageGenerationProvider)
    assert provider._api_base == "https://custom.imagerouter.io/v1"


def test_build_imagerouter_provider_fails_no_api_key() -> None:
    credentials = _get_default_image_gen_creds()

    with pytest.raises(ImageProviderCredentialsError):
        get_image_generation_provider(IMAGEROUTER_PROVIDER, credentials)


# -------------------------------------------------------------------
# ImageRouter generate_image
# -------------------------------------------------------------------


def test_imagerouter_generate_image_calls_litellm() -> None:
    provider = ImageRouterImageGenerationProvider(
        api_key="ir-test-key",
        api_base="https://api.imagerouter.io/v1/openai",
    )
    expected_response = object()

    with patch(
        "litellm.image_generation", return_value=expected_response
    ) as mock_gen:
        response = provider.generate_image(
            prompt="draw a cat",
            model="flux-schnell",
            size="1024x1024",
            n=1,
            quality="standard",
        )

    assert response is expected_response
    mock_gen.assert_called_once_with(
        prompt="draw a cat",
        model="flux-schnell",
        api_key="ir-test-key",
        api_base="https://api.imagerouter.io/v1/openai",
        size="1024x1024",
        n=1,
        quality="standard",
    )


def test_imagerouter_generate_image_rejects_reference_images() -> None:
    provider = ImageRouterImageGenerationProvider(api_key="ir-test-key")

    with pytest.raises(
        ValueError,
        match="ImageRouter does not support reference images",
    ):
        provider.generate_image(
            prompt="edit this",
            model="flux-schnell",
            size="1024x1024",
            n=1,
            reference_images=[
                ReferenceImage(data=b"image-bytes", mime_type="image/png")
            ],
        )


def test_imagerouter_generate_image_no_reference_images_is_fine() -> None:
    provider = ImageRouterImageGenerationProvider(api_key="ir-test-key")

    with patch("litellm.image_generation", return_value=object()):
        # Should not raise for None reference_images
        provider.generate_image(
            prompt="draw a dog",
            model="flux-schnell",
            size="1024x1024",
            n=1,
            reference_images=None,
        )

    with patch("litellm.image_generation", return_value=object()):
        # Should not raise for empty list reference_images
        provider.generate_image(
            prompt="draw a dog",
            model="flux-schnell",
            size="1024x1024",
            n=1,
            reference_images=[],
        )


# -------------------------------------------------------------------
# Google AI Studio credential validation
# -------------------------------------------------------------------


def test_google_ai_studio_validate_credentials_true_when_api_key_present() -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = "aistudio-test-key"

    assert (
        GoogleAIStudioImageGenerationProvider.validate_credentials(credentials) is True
    )


def test_google_ai_studio_validate_credentials_false_when_api_key_missing() -> None:
    credentials = _get_default_image_gen_creds()

    assert (
        GoogleAIStudioImageGenerationProvider.validate_credentials(credentials) is False
    )


def test_google_ai_studio_validate_credentials_false_when_api_key_empty() -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = ""

    assert (
        GoogleAIStudioImageGenerationProvider.validate_credentials(credentials) is False
    )


# -------------------------------------------------------------------
# Google AI Studio building
# -------------------------------------------------------------------


def test_build_google_ai_studio_provider_from_api_key() -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = "aistudio-test-key"

    provider = get_image_generation_provider(GOOGLE_AI_STUDIO_PROVIDER, credentials)

    assert isinstance(provider, GoogleAIStudioImageGenerationProvider)
    assert provider._api_key == "aistudio-test-key"


def test_build_google_ai_studio_provider_fails_no_api_key() -> None:
    credentials = _get_default_image_gen_creds()

    with pytest.raises(ImageProviderCredentialsError):
        get_image_generation_provider(GOOGLE_AI_STUDIO_PROVIDER, credentials)


# -------------------------------------------------------------------
# Google AI Studio generate_image
# -------------------------------------------------------------------


def test_google_ai_studio_generate_image_prefixes_model_with_gemini() -> None:
    provider = GoogleAIStudioImageGenerationProvider(api_key="aistudio-test-key")
    expected_response = object()

    with patch(
        "litellm.image_generation", return_value=expected_response
    ) as mock_gen:
        response = provider.generate_image(
            prompt="draw a landscape",
            model="imagen-3.0-generate-002",
            size="1024x1024",
            n=1,
            quality="standard",
        )

    assert response is expected_response
    mock_gen.assert_called_once_with(
        prompt="draw a landscape",
        model="gemini/imagen-3.0-generate-002",
        api_key="aistudio-test-key",
        size="1024x1024",
        n=1,
        quality="standard",
    )


def test_google_ai_studio_generate_image_does_not_double_prefix() -> None:
    provider = GoogleAIStudioImageGenerationProvider(api_key="aistudio-test-key")
    expected_response = object()

    with patch(
        "litellm.image_generation", return_value=expected_response
    ) as mock_gen:
        response = provider.generate_image(
            prompt="draw a landscape",
            model="gemini/imagen-3.0-generate-002",
            size="1024x1024",
            n=1,
        )

    assert response is expected_response
    # Model already prefixed - should NOT become gemini/gemini/...
    assert mock_gen.call_args.kwargs["model"] == "gemini/imagen-3.0-generate-002"


def test_google_ai_studio_generate_image_rejects_reference_images() -> None:
    provider = GoogleAIStudioImageGenerationProvider(api_key="aistudio-test-key")

    with pytest.raises(
        ValueError,
        match="does not support reference images",
    ):
        provider.generate_image(
            prompt="edit this",
            model="imagen-3.0-generate-002",
            size="1024x1024",
            n=1,
            reference_images=[
                ReferenceImage(data=b"image-bytes", mime_type="image/png")
            ],
        )


def test_google_ai_studio_generate_image_passes_kwargs() -> None:
    provider = GoogleAIStudioImageGenerationProvider(api_key="aistudio-test-key")

    with patch("litellm.image_generation", return_value=object()) as mock_gen:
        provider.generate_image(
            prompt="draw something",
            model="imagen-3.0-generate-002",
            size="1024x1024",
            n=2,
            quality="hd",
            style="vivid",
        )

    call_kwargs = mock_gen.call_args.kwargs
    assert call_kwargs["n"] == 2
    assert call_kwargs["quality"] == "hd"
    assert call_kwargs["style"] == "vivid"
