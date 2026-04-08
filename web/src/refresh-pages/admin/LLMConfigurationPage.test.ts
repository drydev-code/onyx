/**
 * Unit Test: LLMConfigurationPage provider map coverage
 *
 * Validates that PROVIDER_MODAL_MAP and PROVIDER_DISPLAY_ORDER in
 * LLMConfigurationPage.tsx include entries for all new providers.
 *
 * Since these are non-exported module-level constants, we verify via
 * static source analysis rather than runtime imports.
 */

import fs from "fs";
import path from "path";

const SOURCE_PATH = path.resolve(
  __dirname,
  "LLMConfigurationPage.tsx"
);

describe("LLMConfigurationPage provider coverage", () => {
  let source: string;

  beforeAll(() => {
    source = fs.readFileSync(SOURCE_PATH, "utf-8");
  });

  describe("PROVIDER_MODAL_MAP", () => {
    const requiredProviders = [
      "zai",
      "google_ai_studio",
      "openai_codex",
      "claude_code_cli",
    ];

    test.each(requiredProviders)(
      "has an entry for %s",
      (providerKey) => {
        // The map uses string keys like: zai: (d, open, onOpenChange) => (
        const pattern = new RegExp(
          `${providerKey}\\s*:\\s*\\(`
        );
        expect(source).toMatch(pattern);
      }
    );
  });

  describe("PROVIDER_DISPLAY_ORDER", () => {
    const requiredProviders = [
      "zai",
      "google_ai_studio",
      "openai_codex",
      "claude_code_cli",
    ];

    test.each(requiredProviders)(
      "includes %s in the display order",
      (providerKey) => {
        // The array uses string literals like: "zai",
        expect(source).toContain(`"${providerKey}"`);
      }
    );
  });

  describe("modal component imports", () => {
    const requiredImports = [
      "ZAIModal",
      "GoogleAIStudioModal",
      "CodexModal",
      "ClaudeCodeCLIModal",
    ];

    test.each(requiredImports)(
      "imports %s component",
      (componentName) => {
        expect(source).toContain(componentName);
      }
    );
  });
});
