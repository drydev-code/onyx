# Integration Pipeline - AI Agent Guide

## Quick Start

```bash
# Full pipeline: merge all feature branches, lint, build, test, deploy
./integration-pipeline.sh

# After fixing issues, re-run just the failing stage
./integration-pipeline.sh --skip-merge --stage build

# Everything except deploy (dry run)
./integration-pipeline.sh --no-deploy
```

## Pipeline Stages

| Stage | What it does | Common failures |
|-------|-------------|-----------------|
| `merge` | Runs `rebuild-integration.sh` to merge feature branches | Git merge conflicts |
| `lint` | ESLint + TypeScript type checking | Unused imports, type errors |
| `build` | `next build` (production) | Missing/renamed exports, broken imports |
| `backend` | Python syntax + provider imports | Syntax errors, broken imports |
| `test` | Jest unit tests | Test assertion failures |
| `deploy` | `deploy-dev.sh` (Docker build + SSH deploy) | Docker build failures |

## Error Report

On failure, the pipeline writes `integration-build-report.json`:

```json
{
  "failed_stage": "build",
  "error_summary": "Export FieldSeparator doesn't exist in module shared.tsx",
  "failing_files": ["./src/sections/modals/llmConfig/CodexModal.tsx"],
  "log_file": ".integration-logs/build.log",
  "fix_hint": "./integration-pipeline.sh --skip-merge --stage build"
}
```

**Agent workflow:**
1. Read `integration-build-report.json`
2. Read the `log_file` for full error details
3. Fix the `failing_files`
4. Commit the fix
5. Re-run using the `fix_hint` command

## Common Fix Patterns

### Missing/renamed exports from `shared.tsx`

**Symptom:** `The export X was not found in module shared.tsx`

**Cause:** Upstream refactored `shared.tsx`. Feature branch modals import old names.

**Fix pattern:**
1. Read `web/src/sections/modals/llmConfig/shared.tsx` to find current exports
2. Read a working modal (e.g., `AnthropicModal.tsx`, `OpenAIModal.tsx`) for the correct import pattern
3. Update the broken modal to match

**Common renames:**
- `LLMConfigurationModalWrapper` -> `ModalWrapper`
- `FieldSeparator` -> `InputLayouts.FieldSeparator` (from `@/layouts/input-layouts`)
- `ModelsField` -> `ModelSelectionField`
- `ModelsAccessField` -> `ModelAccessField`
- `buildDefaultInitialValues` -> `useInitialValues` (hook)
- `buildDefaultValidationSchema` -> `buildValidationSchema`
- `submitLLMProvider` -> `submitProvider`

### Files deleted upstream but modified in feature branch

**Symptom:** `CONFLICT (modify/delete): web/src/lib/llmConfig/providers.ts deleted in HEAD`

**Cause:** Upstream consolidated files. Our changes need to go to the new location.

**Consolidated files:**
- `web/src/lib/llmConfig/providers.ts` -> `web/src/lib/llmConfig/index.ts` (PROVIDERS record)
- `web/src/sections/modals/llmConfig/getModal.tsx` -> `web/src/lib/llmConfig/index.ts` (getProvider)
- `web/src/app/admin/configuration/llm/utils.ts` -> deleted (utils moved to index.ts)

**Fix:** Accept deletion (`git rm`), apply changes to `index.ts` instead.

### ZAI -> OPENAI_COMPATIBLE rename

**Symptom:** `LlmProviderNames.ZAI` not found

**Cause:** Upstream renamed the ZAI provider to OPENAI_COMPATIBLE.

**Fix:** Replace all references:
- `LlmProviderNames.ZAI` -> `LlmProviderNames.OPENAI_COMPATIBLE`
- `ZAI_PROVIDER_NAME` -> `OPENAI_COMPATIBLE_PROVIDER_NAME`
- `is_zai` -> `is_openai_compatible`

### Merge conflicts in shared constants

**Symptom:** Git merge conflict in `constants.py`, `llm_provider_options.py`

**Fix:** Keep BOTH sides - upstream additions (OPENAI_COMPATIBLE) AND our custom providers (GOOGLE_AI_STUDIO, OPENAI_CODEX, CLAUDE_CODE_CLI).

## Architecture

```
rebuild-integration.sh     # Merge-only script (existing)
    |
integration-pipeline.sh    # Wraps merge + adds verification stages
    |
    +-- merge    -> rebuild-integration.sh
    +-- lint     -> next lint + types:check
    +-- build    -> next build
    +-- backend  -> py_compile + import check
    +-- test     -> jest --ci
    +-- deploy   -> deploy-dev.sh
```

## Branch Structure

```
main (upstream mirror)
  |
  +-- integration/base (shared plumbing on top of main)
        |
        +-- feature/google-ai-studio-llm
        +-- feature/google-ai-studio-image
        +-- feature/imagerouter
        +-- feature/codex
        +-- feature/claude-code
        |
        +-- integration/merged (all features merged together)
```
