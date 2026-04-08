export interface ImageProvider {
  image_provider_id: string; // Static unique key for UI-DB mapping
  model_name: string; // Actual model name for LLM API
  provider_name: string;
  title: string;
  description: string;
}

export interface ProviderGroup {
  name: string;
  providers: ImageProvider[];
}

export const IMAGE_PROVIDER_GROUPS: ProviderGroup[] = [
  {
    name: "OpenAI",
    providers: [
      {
        image_provider_id: "openai_gpt_image_1_5",
        model_name: "gpt-image-1.5",
        provider_name: "openai",
        title: "GPT Image 1.5",
        description:
          "OpenAI's latest Image Generation model with the highest prompt fidelity.",
      },
      {
        image_provider_id: "openai_gpt_image_1",
        model_name: "gpt-image-1",
        provider_name: "openai",
        title: "GPT Image 1",
        description:
          "A capable image generation model from OpenAI with strong prompt adherence.",
      },
      {
        image_provider_id: "openai_dalle_3",
        model_name: "dall-e-3",
        provider_name: "openai",
        title: "DALL-E 3",
        description:
          "OpenAI image generation model capable of generating rich and expressive images.",
      },
    ],
  },
  {
    name: "Azure OpenAI",
    providers: [
      {
        image_provider_id: "azure_gpt_image_1_5",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 1.5",
        description:
          "GPT Image 1.5 image generation model hosted on Microsoft Azure.",
      },
      {
        image_provider_id: "azure_gpt_image_1",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 1",
        description:
          "GPT Image 1 image generation model hosted on Microsoft Azure.",
      },
      {
        image_provider_id: "azure_dalle_3",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI DALL-E 3",
        description:
          "DALL-E 3 image generation model hosted on Microsoft Azure.",
      },
    ],
  },
  {
    name: "Google Cloud Vertex AI",
    providers: [
      {
        image_provider_id: "gemini-3.1-flash-image-preview",
        model_name: "gemini-3.1-flash-image-preview",
        provider_name: "vertex_ai",
        title: "Gemini 3.1 Flash Image (Nano Banana 2)",
        description:
          "Nano Banana 2 combines Nano Banana Pro quality with Flash speed, up to 4K resolution.",
      },
      {
        image_provider_id: "gemini-3-pro-image-preview",
        model_name: "gemini-3-pro-image-preview",
        provider_name: "vertex_ai",
        title: "Gemini 3 Pro Image Preview (Nano Banana Pro)",
        description:
          "Nano Banana Pro is designed for professional asset production with improved text rendering.",
      },
      {
        image_provider_id: "gemini-2.5-flash-image",
        model_name: "gemini-2.5-flash-image",
        provider_name: "vertex_ai",
        title: "Gemini 2.5 Flash Image (Nano Banana)",
        description:
          "Gemini 2.5 Flash Image (Nano Banana) model is designed for speed and efficiency.",
      },
    ],
  },
  {
    name: "Google AI Studio",
    providers: [
      {
        image_provider_id: "aistudio_gemini_3_1_flash_image",
        model_name: "gemini-3.1-flash-image-preview",
        provider_name: "google_ai_studio",
        title: "Gemini 3.1 Flash Image (Nano Banana 2)",
        description:
          "Nano Banana 2 via Google AI Studio. Combines Nano Banana Pro quality with Flash speed, up to 4K resolution.",
      },
      {
        image_provider_id: "aistudio_gemini_3_pro_image",
        model_name: "gemini-3-pro-image-preview",
        provider_name: "google_ai_studio",
        title: "Gemini 3 Pro Image Preview (Nano Banana Pro)",
        description:
          "Nano Banana Pro via Google AI Studio. Designed for professional asset production with improved text rendering.",
      },
      {
        image_provider_id: "aistudio_gemini_2_5_flash_image",
        model_name: "gemini-2.5-flash-image",
        provider_name: "google_ai_studio",
        title: "Gemini 2.5 Flash Image (Nano Banana)",
        description:
          "Gemini 2.5 Flash Image via Google AI Studio API key. Fast and efficient image generation.",
      },
    ],
  },
  {
    name: "ImageRouter",
    providers: [
      {
        image_provider_id: "imagerouter_custom",
        model_name: "", // User specifies any model name
        provider_name: "imagerouter",
        title: "ImageRouter",
        description:
          "Access 80+ image generation models with one API key via ImageRouter.co. Specify any model name supported by the ImageRouter API.",
      },
    ],
  },
];
