# Review action items

## High priority

- [ ] Persist Codex OAuth expiry metadata and make token refresh durable.
  - `backend/onyx/server/manage/llm/api.py:1642` returns `expires_in`, and `backend/onyx/llm/well_known_providers/constants.py:45` defines `codex_token_expires_at`, but `web/src/sections/modals/llmConfig/CodexModal.tsx:311` only stores access and refresh tokens.
  - Save `codex_token_expires_at` in provider `custom_config` so the refresh path in `backend/onyx/llm/multi_llm.py:348` can actually trigger.
  - When a refresh happens, persist the updated access token, refresh token, and expiry back to stored provider config instead of only mutating in-memory state.

- [ ] Bundle both Claude Code and Codex CLI harnesses into the application Docker image(s) and validate server-side availability.
  - The runtime should have both `claude` and `codex` installed, on `PATH`, and usable non-interactively from the container.
  - Add startup or provider-test validation so admins do not save a configuration that cannot execute on the server.

- [ ] Make Claude Code CLI usable with Anthropic plan/OAuth-based authentication.
  - Support account-based auth for the bundled Claude CLI, not just API-key-style provider configuration.
  - Define how Anthropic plan/OAuth credentials are established, persisted in Docker, refreshed, and exposed safely to the runtime.
  - Make the routing explicit so it is clear when requests use `claude_code_cli` vs. a direct Anthropic API provider.

- [ ] Ensure MCP servers and connections work inside the containerized Claude Code and Codex harnesses.
  - Verify MCP config, auth, mounted state, and network access are available inside Docker.
  - Confirm both harnesses can discover configured MCP servers and successfully use MCP-backed tools during execution.

- [ ] Implement craft feature support for GLM, OpenAI Codex, and Claude Code.
  - The new providers are wired into admin/provider configuration, but they should also be available in the craft flow.
  - Audit craft provider/model selection, capability gating, and request execution paths so `zai`, `openai_codex`, and CLI-based Claude/Codex execution work there end to end.

## Medium priority

- [ ] Add tests for Codex OAuth expiry and refresh behavior.
  - Existing masking tests cover token round-tripping, but there is still no coverage for `codex_token_expires_at`, expired-token refresh, refresh failure fallback, or persistence of refreshed credentials.
  - Focus on `backend/onyx/llm/multi_llm.py:348`, `backend/onyx/server/manage/llm/codex_oauth.py:128`, and the Codex admin flow in `web/src/sections/modals/llmConfig/CodexModal.tsx:250`.

- [ ] Add runtime tests for the Claude Code CLI provider.
  - Cover invoke/stream command construction, non-zero exit handling, missing binary behavior, text output parsing, stream-json parsing, and cleanup behavior in `backend/onyx/llm/claude_code_cli.py:108` and `backend/onyx/llm/claude_code_cli.py:181`.

- [ ] Fix or explicitly define streaming timeout behavior for Claude Code CLI.
  - `backend/onyx/llm/claude_code_cli.py:204` computes `timeout`, but the streaming path does not enforce it while reading from the subprocess.
  - Add a real timeout strategy or document that streaming calls are unbounded and monitored elsewhere.

- [ ] Decide how unsupported LLM features should behave for Claude Code CLI and codify that behavior.
  - `backend/onyx/llm/claude_code_cli.py:119` and `backend/onyx/llm/claude_code_cli.py:192` currently warn and ignore `tools`, `tool_choice`, `structured_response_format`, `reasoning_effort`, and `user_identity`.
  - Decide where warnings are acceptable and where callers should receive explicit errors instead.

- [ ] Add frontend tests for the new provider modals and image generation forms.
  - Cover modal selection and submit payload shaping in `web/src/sections/modals/llmConfig/getModal.tsx:63`, `web/src/refresh-pages/admin/LLMConfigurationPage.tsx:155`, `web/src/sections/modals/llmConfig/CodexModal.tsx:250`, `web/src/sections/modals/llmConfig/ClaudeCodeCLIModal.tsx:122`, `web/src/refresh-pages/admin/ImageGenerationPage/forms/GoogleAIStudioImageGenForm.tsx:101`, and `web/src/refresh-pages/admin/ImageGenerationPage/forms/ImageRouterForm.tsx:99`.

- [ ] Decide whether Codex and Claude should be used via direct OAuth/API provider paths, CLI harness paths, or both, and make the product behavior explicit.
  - Avoid ambiguous overlapping configurations where the same capability can silently route through different auth/runtime mechanisms.
  - Document which flows are expected to use `openai_codex`, `claude_code_cli`, bundled `codex`, and bundled `claude`.

## Low priority

- [ ] Review Google AI Studio model discovery for stability.
  - `backend/onyx/llm/well_known_providers/llm_provider_options.py:260` derives available models from LiteLLM’s `model_cost` registry.
  - Confirm this list is stable enough for admin UX, or pin a curated allowlist if model churn causes noisy changes.

- [ ] Confirm the development-environment port changes do not break local tooling.
  - `deployment/docker_compose/docker-compose.dev.yml:28` changes Postgres from `5432` to `5433`, and `deployment/docker_compose/docker-compose.dev.yml:60` changes Redis from `6379` to `6380`.
  - Check local scripts, `.env` defaults, and onboarding docs that may still assume the old ports.

- [ ] Confirm the Vespa memory override is intentional for all dev workflows.
  - `deployment/docker_compose/docker-compose.dev.yml:34` sets `VESPA_IGNORE_NOT_ENOUGH_MEMORY=true`.
  - Verify this is acceptable for the team’s standard local setup and does not hide resource issues that should stay visible.
