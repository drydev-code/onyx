/**
 * Test: getProvider routing
 *
 * Verifies that each provider this fork adds routes to its own modal rather
 * than falling back to CustomModal, and that the CustomModal fallback still
 * applies to unknown providers.
 *
 * Replaces the old getModalForExistingProvider test: upstream consolidated
 * sections/modals/llmConfig/getModal.tsx into this registry.
 */

import { getProvider } from "@/lib/languageModels";
import { LLMProviderName } from "@/lib/languageModels/types";
import CustomModal from "@/sections/modals/languageModels/CustomModal";
import ZAIModal from "@/sections/modals/languageModels/ZAIModal";
import CodexModal from "@/sections/modals/languageModels/CodexModal";
import ClaudeCodeCLIModal from "@/sections/modals/languageModels/ClaudeCodeCLIModal";
import GoogleAIStudioModal from "@/sections/modals/languageModels/GoogleAIStudioModal";

describe("getProvider", () => {
  it.each([
    [LLMProviderName.ZAI, ZAIModal],
    [LLMProviderName.OPENAI_CODEX, CodexModal],
    [LLMProviderName.CLAUDE_CODE_CLI, ClaudeCodeCLIModal],
    [LLMProviderName.GOOGLE_AI_STUDIO, GoogleAIStudioModal],
  ])("routes %s to its own modal", (providerName, expectedModal) => {
    expect(getProvider(providerName).Modal).toBe(expectedModal);
  });

  it("falls back to CustomModal for an unknown provider", () => {
    const entry = getProvider("not-a-real-provider");
    expect(entry.Modal).toBe(CustomModal);
    expect(entry.productName).toBe("not-a-real-provider");
  });

  it("forces CustomModal when a well-known provider carries custom_config", () => {
    const entry = getProvider(LLMProviderName.OPENAI, {
      custom_config: { foo: "bar" },
    } as never);
    expect(entry.Modal).toBe(CustomModal);
  });
});
