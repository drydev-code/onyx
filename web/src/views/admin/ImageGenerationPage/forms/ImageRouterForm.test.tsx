import React from "react";
import type { ModalCreationInterface } from "@opal/components";
import { render, screen } from "@tests/setup/test-utils";
import { ImageRouterForm } from "@/views/admin/ImageGenerationPage/forms/ImageRouterForm";
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
  image_provider_id: "imagerouter_custom",
  model_name: "",
  provider_name: "imagerouter",
  title: "ImageRouter",
  descriptionKey: "providers.imageRouter.description",
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

describe("ImageRouterForm", () => {
  test("renders the model name field", () => {
    render(<ImageRouterForm {...getBaseProps()} />);

    expect(screen.getByText("Model Name")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Enter a supported model name")
    ).toBeInTheDocument();
  });

  test("renders the API key field", () => {
    render(<ImageRouterForm {...getBaseProps()} />);

    expect(screen.getByText("API Key")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Enter your API key")
    ).toBeInTheDocument();
  });

  test("shows guidance for both fields", () => {
    render(<ImageRouterForm {...getBaseProps()} />);

    expect(
      screen.getByText("Enter any model name supported by ImageRouter.")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Enter a new API key or select an existing provider.")
    ).toBeInTheDocument();
  });
});
