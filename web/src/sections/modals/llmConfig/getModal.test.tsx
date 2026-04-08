/**
 * Test: getModalForExistingProvider routing
 *
 * Verifies that each LLMProviderName enum value routes to the correct
 * modal component in getModalForExistingProvider.
 */

import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import { LLMProviderName, LLMProviderView } from "@/interfaces/llm";
import { getModalForExistingProvider } from "@/sections/modals/llmConfig/getModal";

// ---------------------------------------------------------------------------
// Mock every modal so we can assert which one was rendered without pulling
// in their full dependency trees.
// ---------------------------------------------------------------------------

jest.mock("@/sections/modals/llmConfig/AnthropicModal", () => ({
  __esModule: true,
  default: () => <div data-testid="AnthropicModal" />,
}));

jest.mock("@/sections/modals/llmConfig/OpenAIModal", () => ({
  __esModule: true,
  default: () => <div data-testid="OpenAIModal" />,
}));

jest.mock("@/sections/modals/llmConfig/OllamaModal", () => ({
  __esModule: true,
  default: () => <div data-testid="OllamaModal" />,
}));

jest.mock("@/sections/modals/llmConfig/AzureModal", () => ({
  __esModule: true,
  default: () => <div data-testid="AzureModal" />,
}));

jest.mock("@/sections/modals/llmConfig/VertexAIModal", () => ({
  __esModule: true,
  default: () => <div data-testid="VertexAIModal" />,
}));

jest.mock("@/sections/modals/llmConfig/BedrockModal", () => ({
  __esModule: true,
  default: () => <div data-testid="BedrockModal" />,
}));

jest.mock("@/sections/modals/llmConfig/OpenRouterModal", () => ({
  __esModule: true,
  default: () => <div data-testid="OpenRouterModal" />,
}));

jest.mock("@/sections/modals/llmConfig/CustomModal", () => ({
  __esModule: true,
  default: () => <div data-testid="CustomModal" />,
}));

jest.mock("@/sections/modals/llmConfig/LMStudioForm", () => ({
  __esModule: true,
  default: () => <div data-testid="LMStudioForm" />,
}));

jest.mock("@/sections/modals/llmConfig/LiteLLMProxyModal", () => ({
  __esModule: true,
  default: () => <div data-testid="LiteLLMProxyModal" />,
}));

jest.mock("@/sections/modals/llmConfig/BifrostModal", () => ({
  __esModule: true,
  default: () => <div data-testid="BifrostModal" />,
}));

jest.mock("@/sections/modals/llmConfig/ClaudeCodeCLIModal", () => ({
  __esModule: true,
  default: () => <div data-testid="ClaudeCodeCLIModal" />,
}));

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function makeProvider(
  overrides: Partial<LLMProviderView> = {}
): LLMProviderView {
  return {
    id: 1,
    name: "Test Provider",
    provider: LLMProviderName.OPENAI,
    api_key: "sk-test",
    api_base: null,
    api_version: null,
    model_configurations: [],
    custom_config: {},
    is_public: true,
    is_auto_mode: false,
    groups: [],
    personas: [],
    deployment_name: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("getModalForExistingProvider", () => {
  const cases: [string, Partial<LLMProviderView>, string][] = [
    [
      "routes CLAUDE_CODE_CLI to ClaudeCodeCLIModal",
      { provider: LLMProviderName.CLAUDE_CODE_CLI },
      "ClaudeCodeCLIModal",
    ],
    // Existing providers for regression
    [
      "routes ANTHROPIC to AnthropicModal",
      { provider: LLMProviderName.ANTHROPIC },
      "AnthropicModal",
    ],
    [
      "routes real OPENAI to OpenAIModal",
      {
        provider: LLMProviderName.OPENAI,
        api_key: "sk-test",
        api_base: null,
        custom_config: {},
      },
      "OpenAIModal",
    ],
    [
      "routes OPENAI with custom base to CustomModal",
      {
        provider: LLMProviderName.OPENAI,
        api_key: "sk-test",
        api_base: "https://custom.endpoint.com/v1",
        custom_config: {},
      },
      "CustomModal",
    ],
    [
      "routes OLLAMA_CHAT to OllamaModal",
      { provider: LLMProviderName.OLLAMA_CHAT },
      "OllamaModal",
    ],
    [
      "routes AZURE to AzureModal",
      { provider: LLMProviderName.AZURE },
      "AzureModal",
    ],
    [
      "routes VERTEX_AI to VertexAIModal",
      { provider: LLMProviderName.VERTEX_AI },
      "VertexAIModal",
    ],
    [
      "routes BEDROCK to BedrockModal",
      { provider: LLMProviderName.BEDROCK },
      "BedrockModal",
    ],
    [
      "routes OPENROUTER to OpenRouterModal",
      { provider: LLMProviderName.OPENROUTER },
      "OpenRouterModal",
    ],
    [
      "routes LM_STUDIO to LMStudioForm",
      { provider: LLMProviderName.LM_STUDIO },
      "LMStudioForm",
    ],
    [
      "routes LITELLM_PROXY to LiteLLMProxyModal",
      { provider: LLMProviderName.LITELLM_PROXY },
      "LiteLLMProxyModal",
    ],
    [
      "routes BIFROST to BifrostModal",
      { provider: LLMProviderName.BIFROST },
      "BifrostModal",
    ],
    [
      "routes unknown provider to CustomModal (fallback)",
      { provider: "some_unknown_provider" as LLMProviderName },
      "CustomModal",
    ],
  ];

  test.each(cases)("%s", (_label, overrides, expectedTestId) => {
    const provider = makeProvider(overrides);
    const element = getModalForExistingProvider(provider, true, jest.fn());
    render(<>{element}</>);
    expect(screen.getByTestId(expectedTestId)).toBeInTheDocument();
  });
});
