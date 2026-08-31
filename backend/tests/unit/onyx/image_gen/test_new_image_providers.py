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

GOOGLE_AI_STUDIO_PROVIDER = "google_ai_studio"


def _get_default_image_gen_creds() -> ImageGenerationProviderCredentials:
    return ImageGenerationProviderCredentials(
        api_key=None,
        api_base=None,
        api_version=None,
        deployment_name=None,
        custom_config=None,
    )


def test_enum_includes_google_ai_studio() -> None:
    assert ImageGenerationProviderName.GOOGLE_AI_STUDIO.value == "google_ai_studio"


def test_providers_dict_maps_google_ai_studio() -> None:
    assert (
        PROVIDERS[ImageGenerationProviderName.GOOGLE_AI_STUDIO]
        is GoogleAIStudioImageGenerationProvider
    )


@pytest.mark.parametrize("api_key", [None, ""])
def test_google_ai_studio_validate_credentials_false_without_api_key(
    api_key: str | None,
) -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = api_key

    assert not GoogleAIStudioImageGenerationProvider.validate_credentials(credentials)


def test_google_ai_studio_validate_credentials_true_with_api_key() -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = "aistudio-test-key"

    assert GoogleAIStudioImageGenerationProvider.validate_credentials(credentials)


def test_build_google_ai_studio_provider_from_api_key() -> None:
    credentials = _get_default_image_gen_creds()
    credentials.api_key = "aistudio-test-key"

    provider = get_image_generation_provider(GOOGLE_AI_STUDIO_PROVIDER, credentials)

    assert isinstance(provider, GoogleAIStudioImageGenerationProvider)
    assert provider._api_key == "aistudio-test-key"


def test_build_google_ai_studio_provider_fails_without_api_key() -> None:
    credentials = _get_default_image_gen_creds()

    with pytest.raises(ImageProviderCredentialsError):
        get_image_generation_provider(GOOGLE_AI_STUDIO_PROVIDER, credentials)


def test_google_ai_studio_generate_image_prefixes_model_with_gemini() -> None:
    provider = GoogleAIStudioImageGenerationProvider(api_key="aistudio-test-key")
    expected_response = object()

    with patch(
        "litellm.image_generation", return_value=expected_response
    ) as mock_generation:
        response = provider.generate_image(
            prompt="draw a landscape",
            model="imagen-3.0-generate-002",
            size="1024x1024",
            n=1,
            quality="standard",
        )

    assert response is expected_response
    mock_generation.assert_called_once_with(
        prompt="draw a landscape",
        model="gemini/imagen-3.0-generate-002",
        api_key="aistudio-test-key",
        size="1024x1024",
        n=1,
        quality="standard",
    )


def test_google_ai_studio_generate_image_does_not_double_prefix() -> None:
    provider = GoogleAIStudioImageGenerationProvider(api_key="aistudio-test-key")

    with patch("litellm.image_generation", return_value=object()) as mock_generation:
        provider.generate_image(
            prompt="draw a landscape",
            model="gemini/imagen-3.0-generate-002",
            size="1024x1024",
            n=1,
        )

    assert mock_generation.call_args.kwargs["model"] == (
        "gemini/imagen-3.0-generate-002"
    )


def test_google_ai_studio_generate_image_rejects_reference_images() -> None:
    provider = GoogleAIStudioImageGenerationProvider(api_key="aistudio-test-key")

    with pytest.raises(ValueError, match="does not support reference images"):
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

    with patch("litellm.image_generation", return_value=object()) as mock_generation:
        provider.generate_image(
            prompt="draw something",
            model="imagen-3.0-generate-002",
            size="1024x1024",
            n=2,
            quality="hd",
            style="vivid",
        )

    call_kwargs = mock_generation.call_args.kwargs
    assert call_kwargs["n"] == 2
    assert call_kwargs["quality"] == "hd"
    assert call_kwargs["style"] == "vivid"
