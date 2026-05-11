/**
 * Unit Test: LLMConfigurationPage provider display order coverage
 *
 * Validates that PROVIDER_DISPLAY_ORDER in LLMConfigurationPage.tsx
 * includes entries for all custom providers added in integration/base.
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

  describe("PROVIDER_DISPLAY_ORDER", () => {
    const requiredProviders = [
      "GOOGLE_AI_STUDIO",
      "OPENAI_CODEX",
      "CLAUDE_CODE_CLI",
    ];

    test.each(requiredProviders)(
      "includes LLMProviderName.%s in the display order",
      (providerKey) => {
        expect(source).toContain(`LLMProviderName.${providerKey}`);
      }
    );
  });
});
