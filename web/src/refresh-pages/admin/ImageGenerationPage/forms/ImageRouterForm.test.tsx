/**
 * Integration Test: ImageRouterForm
 *
 * Tests that the ImageRouter image generation form renders the expected
 * fields: a model name input and an API key input.
 */

import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import { ImageRouterForm } from "@/refresh-pages/admin/ImageGenerationPage/forms/ImageRouterForm";
import { ImageGenFormBaseProps } from "@/refresh-pages/admin/ImageGenerationPage/forms/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock the ProviderModal used by ImageGenFormWrapper so we do not need
// the full modal portal / overlay infrastructure in tests.
jest.mock("@/components/modals/ProviderModal", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="provider-modal">{children}</div>
  ),
}));

// Mock the icon components that are used in the form wrapper
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

// Mock the image generation service calls
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
  image_provider_id: "imagerouter_custom",
  model_name: "",
  provider_name: "imagerouter",
  title: "ImageRouter",
  description: "Access 80+ image generation models with one API key.",
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

describe("ImageRouterForm", () => {
  test("renders the Model Name field", () => {
    render(<ImageRouterForm {...getBaseProps()} />);

    expect(screen.getByText("Model Name")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(
        /flux-schnell/i
      )
    ).toBeInTheDocument();
  });

  test("renders the API Key field", () => {
    render(<ImageRouterForm {...getBaseProps()} />);

    expect(screen.getByText("ImageRouter API Key")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/enter your imagerouter api key/i)
    ).toBeInTheDocument();
  });

  test("shows idle help text for both fields", () => {
    render(<ImageRouterForm {...getBaseProps()} />);

    expect(
      screen.getByText(/enter any model name supported by imagerouter/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/get your api key from imagerouter/i)
    ).toBeInTheDocument();
  });
});
