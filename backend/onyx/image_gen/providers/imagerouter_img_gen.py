"""ImageRouter.co image generation provider.

Uses the OpenAI-compatible image generation endpoint at
https://api.imagerouter.io/v1/openai/images/generations
"""

from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ReferenceImage

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse

_DEFAULT_API_BASE = "https://api.imagerouter.io/v1/openai"


class ImageRouterImageGenerationProvider(ImageGenerationProvider):
    def __init__(
        self,
        api_key: str,
        api_base: str | None = None,
    ):
        self._api_key = api_key
        self._api_base = api_base or _DEFAULT_API_BASE

    @classmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> bool:
        return bool(credentials.api_key)

    @classmethod
    def _build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> ImageRouterImageGenerationProvider:
        assert credentials.api_key

        return cls(
            api_key=credentials.api_key,
            api_base=credentials.api_base,
        )

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,
        reference_images: list[ReferenceImage] | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResponse:
        if reference_images:
            raise ValueError(
                "ImageRouter does not support reference images for image editing."
            )

        from litellm import image_generation

        # Prefix model with openai/ for LiteLLM routing to OpenAI-compatible API
        litellm_model = model if model.startswith("openai/") else f"openai/{model}"

        return image_generation(
            prompt=prompt,
            model=litellm_model,
            api_key=self._api_key,
            api_base=self._api_base,
            size=size,
            n=n,
            quality=quality,
            **kwargs,
        )
