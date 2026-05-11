"""Google AI Studio image generation provider.

Uses the Gemini API via API key for image generation,
routing through LiteLLM's gemini provider.
"""

from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ReferenceImage

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse


class GoogleAIStudioImageGenerationProvider(ImageGenerationProvider):
    def __init__(
        self,
        api_key: str,
    ):
        self._api_key = api_key

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
    ) -> GoogleAIStudioImageGenerationProvider:
        assert credentials.api_key

        return cls(
            api_key=credentials.api_key,
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
                "Google AI Studio image generation does not support reference images via this provider."
            )

        from litellm import image_generation

        # Prefix model with gemini/ for LiteLLM routing
        litellm_model = model if model.startswith("gemini/") else f"gemini/{model}"

        return image_generation(
            prompt=prompt,
            model=litellm_model,
            api_key=self._api_key,
            size=size,
            n=n,
            quality=quality,
            **kwargs,
        )
