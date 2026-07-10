/**
 * Unit Test: fork provider registration coverage
 *
 * Guards that the providers this fork adds stay wired into the three places
 * that must agree: the LLMProviderName enum, the PROVIDERS registry, and the
 * admin page's display order.
 *
 * These are non-exported module-level constants, so we verify via static
 * source analysis rather than runtime imports.
 */

import fs from "fs";
import path from "path";

const FORK_PROVIDERS = [
  "google_ai_studio",
  "openai_codex",
  "claude_code_cli",
] as const;

const ENUM_MEMBERS = [
  "GOOGLE_AI_STUDIO",
  "OPENAI_CODEX",
  "CLAUDE_CODE_CLI",
] as const;

const readSource = (...segments: string[]): string =>
  fs.readFileSync(path.resolve(__dirname, ...segments), "utf-8");

describe("fork provider coverage", () => {
  describe("LLMProviderName enum", () => {
    const source = readSource("../../lib/languageModels/types.ts");

    test.each(FORK_PROVIDERS)("defines %s", (providerKey) => {
      expect(source).toContain(`= "${providerKey}"`);
    });
  });

  describe("PROVIDERS registry", () => {
    const source = readSource("../../lib/languageModels/index.ts");

    test.each(ENUM_MEMBERS)("has an entry for %s", (member) => {
      expect(source).toMatch(
        new RegExp(`\\[LLMProviderName\\.${member}\\]\\s*:\\s*\\{`)
      );
    });
  });

  describe("provider display order", () => {
    const source = readSource("LanguageModelsPage.tsx");

    test.each(ENUM_MEMBERS)("includes %s", (member) => {
      expect(source).toContain(`LLMProviderName.${member}`);
    });
  });
});
