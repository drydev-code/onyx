/**
 * Integration Test: GoogleAIStudioImageGenForm
 *
 * Tests that the Google AI Studio image generation form renders
 * the API key field with the expected label and help text.
 */

import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import { GoogleAIStudioImageGenForm } from "@/refresh-pages/admin/ImageGenerationPage/forms/GoogleAIStudioImageGenForm";
import { ImageGenFormBaseProps } from "@/refresh-pages/admin/ImageGenerationPage/forms/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

jest.mock("@/components/modals/ProviderModal", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="provider-modal">{children}</div>
  ),
}));

jest.mock("@/app/admin/configuration/llm/ProviderIcon", () => ({
  ProviderIcon: () => <span data-testid="provider-icon" />,
}));

jest.mock("@/refresh-components/ConnectionProviderIcon", () => ({
  __esModule: true,
  default: () => <span data-testid="connection-provider-icon" />,
}));

jest.mock("@/hooks/useToast", () => {
  const toastFn = Object.assign(jest.fn(), {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warning: jest.fn(),
    dismiss: jest.fn(),
    clearAll: jest.fn(),
    _markLeaving: jest.fn(),
  });
  return {
    toast: toastFn,
    useToast: () => ({
      toast: toastFn,
      dismiss: toastFn.dismiss,
      clearAll: toastFn.clearAll,
    }),
  };
});

jest.mock("@/refresh-pages/admin/ImageGenerationPage/svc", () => ({
  testImageGenerationApiKey: jest.fn(),
  createImageGenerationConfig: jest.fn(),
  updateImageGenerationConfig: jest.fn(),
  fetchImageGenerationCredentials: jest.fn().mockResolvedValue(null),
}));

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const mockImageProvider = {
  image_provider_id: "aistudio_gemini_2_5_flash_image",
  model_name: "gemini-2.5-flash-preview-image-generation",
  provider_name: "google_ai_studio",
  title: "Gemini 2.5 Flash Image (Nano Banana)",
  description:
    "Gemini 2.5 Flash Image via Google AI Studio API key. Fast and efficient image generation.",
};

const mockModal = {
  close: jest.fn(),
  open: jest.fn(),
  isOpen: true,
} as any;

function getBaseProps(): ImageGenFormBaseProps {
  return {
    modal: mockModal,
    imageProvider: mockImageProvider,
    existingProviders: [],
    onSuccess: jest.fn(),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GoogleAIStudioImageGenForm", () => {
  test("renders the API Key field with correct label", () => {
    render(<GoogleAIStudioImageGenForm {...getBaseProps()} />);

    expect(
      screen.getByText("Google AI Studio API Key")
    ).toBeInTheDocument();
  });

  test("renders the API key input placeholder", () => {
    render(<GoogleAIStudioImageGenForm {...getBaseProps()} />);

    expect(
      screen.getByPlaceholderText(/enter your google ai studio api key/i)
    ).toBeInTheDocument();
  });

  test("shows idle help text directing to aistudio.google.com", () => {
    render(<GoogleAIStudioImageGenForm {...getBaseProps()} />);

    expect(
      screen.getByText(/get your api key from aistudio\.google\.com/i)
    ).toBeInTheDocument();
  });
});
