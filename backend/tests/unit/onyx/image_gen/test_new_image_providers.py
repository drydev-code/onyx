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


def _credentials(api_key: str | None = None) -> ImageGenerationProviderCredentials:
    return ImageGenerationProviderCredentials(
        api_key=api_key,
        api_base=None,
        api_version=None,
        deployment_name=None,
        custom_config=None,
    )


def test_factory_registers_new_image_providers() -> None:
    assert ImageGenerationProviderName.IMAGEROUTER.value == "imagerouter"
    assert ImageGenerationProviderName.GOOGLE_AI_STUDIO.value == "google_ai_studio"
    assert (
        PROVIDERS[ImageGenerationProviderName.IMAGEROUTER]
        is ImageRouterImageGenerationProvider
    )
    assert (
        PROVIDERS[ImageGenerationProviderName.GOOGLE_AI_STUDIO]
        is GoogleAIStudioImageGenerationProvider
    )


@pytest.mark.parametrize("api_key", [None, ""])
def test_new_providers_reject_missing_api_keys(api_key: str | None) -> None:
    credentials = _credentials(api_key)

    assert not ImageRouterImageGenerationProvider.validate_credentials(credentials)
    assert not GoogleAIStudioImageGenerationProvider.validate_credentials(credentials)


def test_new_providers_accept_api_keys() -> None:
    credentials = _credentials("test-key")

    assert ImageRouterImageGenerationProvider.validate_credentials(credentials)
    assert GoogleAIStudioImageGenerationProvider.validate_credentials(credentials)


def test_build_imagerouter_provider_uses_default_api_base() -> None:
    provider = get_image_generation_provider("imagerouter", _credentials("ir-key"))

    assert isinstance(provider, ImageRouterImageGenerationProvider)
    assert provider._api_key == "ir-key"
    assert provider._api_base == "https://api.imagerouter.io/v1/openai"


def test_build_imagerouter_provider_uses_custom_api_base() -> None:
    credentials = _credentials("ir-key")
    credentials.api_base = "https://custom.imagerouter.example/v1"

    provider = get_image_generation_provider("imagerouter", credentials)

    assert isinstance(provider, ImageRouterImageGenerationProvider)
    assert provider._api_base == "https://custom.imagerouter.example/v1"


def test_build_google_ai_studio_provider() -> None:
    provider = get_image_generation_provider(
        "google_ai_studio", _credentials("aistudio-key")
    )

    assert isinstance(provider, GoogleAIStudioImageGenerationProvider)
    assert provider._api_key == "aistudio-key"


@pytest.mark.parametrize("provider", ["imagerouter", "google_ai_studio"])
def test_build_new_provider_fails_without_api_key(provider: str) -> None:
    with pytest.raises(ImageProviderCredentialsError):
        get_image_generation_provider(provider, _credentials())


def test_imagerouter_generate_image_calls_litellm() -> None:
    provider = ImageRouterImageGenerationProvider(api_key="ir-key")
    expected_response = object()

    with patch(
        "litellm.image_generation", return_value=expected_response
    ) as mock_generation:
        response = provider.generate_image(
            prompt="draw a cat",
            model="flux-schnell",
            size="1024x1024",
            n=1,
            quality="standard",
        )

    assert response is expected_response
    mock_generation.assert_called_once_with(
        prompt="draw a cat",
        model="openai/flux-schnell",
        api_key="ir-key",
        api_base="https://api.imagerouter.io/v1/openai",
        size="1024x1024",
        n=1,
        quality="standard",
    )


def test_google_ai_studio_generate_image_calls_litellm() -> None:
    provider = GoogleAIStudioImageGenerationProvider(api_key="aistudio-key")
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
        api_key="aistudio-key",
        size="1024x1024",
        n=1,
        quality="standard",
    )


def test_google_ai_studio_does_not_double_prefix_model() -> None:
    provider = GoogleAIStudioImageGenerationProvider(api_key="aistudio-key")

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


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        (ImageRouterImageGenerationProvider(api_key="ir-key"), "flux-schnell"),
        (
            GoogleAIStudioImageGenerationProvider(api_key="aistudio-key"),
            "imagen-3.0-generate-002",
        ),
    ],
)
def test_new_providers_reject_reference_images(
    provider: ImageRouterImageGenerationProvider
    | GoogleAIStudioImageGenerationProvider,
    model: str,
) -> None:
    with pytest.raises(ValueError, match="does not support reference images"):
        provider.generate_image(
            prompt="edit this",
            model=model,
            size="1024x1024",
            n=1,
            reference_images=[
                ReferenceImage(data=b"image-bytes", mime_type="image/png")
            ],
        )
