import React from "react";
import type { ModalCreationInterface } from "@opal/components";
import { render, screen } from "@tests/setup/test-utils";
import { GoogleAIStudioImageGenForm } from "@/views/admin/ImageGenerationPage/forms/GoogleAIStudioImageGenForm";
import { ImageProvider } from "@/views/admin/ImageGenerationPage/constants";
import { ImageGenFormBaseProps } from "@/views/admin/ImageGenerationPage/forms/types";

jest.mock("@/sections/modals/ProviderModal", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="provider-modal">{children}</div>
  ),
}));

jest.mock("@/refresh-components/ConnectionProviderIcon", () => ({
  __esModule: true,
  default: () => <span data-testid="connection-provider-icon" />,
}));

jest.mock("@/views/admin/ImageGenerationPage/svc", () => ({
  testImageGenerationApiKey: jest.fn(),
  createImageGenerationConfig: jest.fn(),
  updateImageGenerationConfig: jest.fn(),
  fetchImageGenerationCredentials: jest.fn().mockResolvedValue(null),
}));

const mockImageProvider: ImageProvider = {
  image_provider_id: "aistudio_gemini_2_5_flash_image",
  model_name: "gemini-2.5-flash-image",
  provider_name: "google_ai_studio",
  title: "Gemini 2.5 Flash Image (Nano Banana)",
  descriptionKey: "providers.googleAiStudioGemini25FlashImage.description",
};

const mockModal: ModalCreationInterface = {
  isOpen: true,
  toggle: jest.fn(),
  Provider: ({ children }) => <>{children}</>,
};

function getBaseProps(): ImageGenFormBaseProps {
  return {
    modal: mockModal,
    imageProvider: mockImageProvider,
    existingProviders: [],
    onSuccess: jest.fn(),
  };
}

describe("GoogleAIStudioImageGenForm", () => {
  test("renders the API key field", () => {
    render(<GoogleAIStudioImageGenForm {...getBaseProps()} />);

    expect(screen.getByText("API Key")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Enter your API key")
    ).toBeInTheDocument();
  });

  test("shows the shared API key guidance", () => {
    render(<GoogleAIStudioImageGenForm {...getBaseProps()} />);

    expect(
      screen.getByText("Enter a new API key or select an existing provider.")
    ).toBeInTheDocument();
  });
});
