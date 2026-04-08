/**
 * Integration Test: getImageGenForm factory
 *
 * Verifies that the factory function routes to the correct form component
 * for new providers (imagerouter, google_ai_studio).
 */

import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import { getImageGenForm } from "@/refresh-pages/admin/ImageGenerationPage/forms/getImageGenForm";
import { ImageGenFormBaseProps } from "@/refresh-pages/admin/ImageGenerationPage/forms/types";

// ---------------------------------------------------------------------------
// Mock all form components to identify which one renders
// ---------------------------------------------------------------------------

jest.mock(
  "@/refresh-pages/admin/ImageGenerationPage/forms/OpenAIImageGenForm",
  () => ({
    OpenAIImageGenForm: () => <div data-testid="OpenAIImageGenForm" />,
  })
);

jest.mock(
  "@/refresh-pages/admin/ImageGenerationPage/forms/AzureImageGenForm",
  () => ({
    AzureImageGenForm: () => <div data-testid="AzureImageGenForm" />,
  })
);

jest.mock(
  "@/refresh-pages/admin/ImageGenerationPage/forms/VertexImageGenForm",
  () => ({
    VertexImageGenForm: () => <div data-testid="VertexImageGenForm" />,
  })
);

jest.mock(
  "@/refresh-pages/admin/ImageGenerationPage/forms/ImageRouterForm",
  () => ({
    ImageRouterForm: () => <div data-testid="ImageRouterForm" />,
  })
);

jest.mock(
  "@/refresh-pages/admin/ImageGenerationPage/forms/GoogleAIStudioImageGenForm",
  () => ({
    GoogleAIStudioImageGenForm: () => (
      <div data-testid="GoogleAIStudioImageGenForm" />
    ),
  })
);

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function makeProps(providerName: string): ImageGenFormBaseProps {
  return {
    modal: { close: jest.fn(), open: jest.fn(), isOpen: true } as any,
    imageProvider: {
      image_provider_id: "test_id",
      model_name: "test-model",
      provider_name: providerName,
      title: "Test Provider",
      description: "Test description",
    },
    existingProviders: [],
    onSuccess: jest.fn(),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("getImageGenForm", () => {
  test("routes imagerouter to ImageRouterForm", () => {
    const element = getImageGenForm(makeProps("imagerouter"));
    render(<>{element}</>);
    expect(screen.getByTestId("ImageRouterForm")).toBeInTheDocument();
  });

  test("routes google_ai_studio to GoogleAIStudioImageGenForm", () => {
    const element = getImageGenForm(makeProps("google_ai_studio"));
    render(<>{element}</>);
    expect(
      screen.getByTestId("GoogleAIStudioImageGenForm")
    ).toBeInTheDocument();
  });

  test("routes openai to OpenAIImageGenForm", () => {
    const element = getImageGenForm(makeProps("openai"));
    render(<>{element}</>);
    expect(screen.getByTestId("OpenAIImageGenForm")).toBeInTheDocument();
  });

  test("routes azure to AzureImageGenForm", () => {
    const element = getImageGenForm(makeProps("azure"));
    render(<>{element}</>);
    expect(screen.getByTestId("AzureImageGenForm")).toBeInTheDocument();
  });

  test("routes vertex_ai to VertexImageGenForm", () => {
    const element = getImageGenForm(makeProps("vertex_ai"));
    render(<>{element}</>);
    expect(screen.getByTestId("VertexImageGenForm")).toBeInTheDocument();
  });

  test("falls back to OpenAIImageGenForm for unknown provider", () => {
    const consoleSpy = jest
      .spyOn(console, "warn")
      .mockImplementation(() => {});
    const element = getImageGenForm(makeProps("unknown_provider"));
    render(<>{element}</>);
    expect(screen.getByTestId("OpenAIImageGenForm")).toBeInTheDocument();
    consoleSpy.mockRestore();
  });
});
