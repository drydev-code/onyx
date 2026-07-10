#!/usr/bin/env bash
# integration-pipeline.sh - Merge, lint, build, test for integration branches
#
# Designed for AI agents: produces structured error reports that an agent
# can read, diagnose, fix, and re-run.
#
# Usage:
#   ./integration-pipeline.sh                   # Full pipeline (merge + verify + deploy)
#   ./integration-pipeline.sh --skip-merge       # Skip merge, verify current branch
#   ./integration-pipeline.sh --stage build      # Run only the build stage
#   ./integration-pipeline.sh --no-deploy        # Everything except deploy
#   ./integration-pipeline.sh --fix-cycle 3      # Auto re-run up to 3 fix cycles
#
# Stages (in order):
#   merge    - Rebuild integration/merged via rebuild-integration.sh
#   lint     - ESLint + TypeScript type checking
#   build    - Next.js production build (catches import/export errors)
#   backend  - Python syntax + import validation
#   test     - Jest unit tests
#   deploy   - Build Docker images and deploy to server
#
# On failure:
#   - Writes integration-build-report.json with stage, errors, failing files
#   - Exits non-zero so the calling agent can read the report and fix
#
# Exit codes:
#   0  - All stages passed
#   1  - A stage failed (see report)
#   2  - Script usage error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Configuration ─────────────────────────────────────────────────────────────
REPORT_FILE="$SCRIPT_DIR/integration-build-report.json"
LOG_DIR="$SCRIPT_DIR/.integration-logs"
SKIP_MERGE=false
DEPLOY=true
SINGLE_STAGE=""
FIX_CYCLES=0
REBUILD_ARGS=()

# ── Argument parsing ─────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: ./integration-pipeline.sh [options] [-- rebuild-integration-args...]

Options:
  --skip-merge         Skip the merge stage (verify current branch as-is)
  --no-deploy          Skip the deploy stage
  --stage <name>       Run only this stage: merge|lint|build|backend|test|deploy
  --fix-cycle <n>      Reserved for AI agents: max fix-then-rerun iterations
  --rebuild-args "..." Extra arguments forwarded to rebuild-integration.sh
  -h, --help           Show this help text

Examples:
  ./integration-pipeline.sh                         # Full pipeline
  ./integration-pipeline.sh --skip-merge            # Verify without re-merging
  ./integration-pipeline.sh --stage build           # Re-check build only
  ./integration-pipeline.sh --no-deploy             # Everything except deploy
  ./integration-pipeline.sh -- --no-sync-main       # Pass args to rebuild-integration.sh
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-merge)   SKIP_MERGE=true; shift ;;
        --no-deploy)    DEPLOY=false; shift ;;
        --stage)        SINGLE_STAGE="$2"; shift 2 ;;
        --fix-cycle)    FIX_CYCLES="$2"; shift 2 ;;
        --rebuild-args) REBUILD_ARGS+=($2); shift 2 ;;
        -h|--help)      usage; exit 0 ;;
        --)             shift; REBUILD_ARGS+=("$@"); break ;;
        -*)             echo "Error: unknown option: $1" >&2; usage >&2; exit 2 ;;
        *)              REBUILD_ARGS+=("$1"); shift ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"

STAGES_RUN=()
STAGES_PASSED=()
STAGES_FAILED=()

timestamp() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# JSON encoders. jq is not present on every dev box (notably Git Bash on
# Windows), and without a fallback write_report emitted a malformed report --
# exactly when an agent needs to read it.
json_array() {
    if command -v jq >/dev/null 2>&1; then
        jq -R -s 'split("\n") | map(select(length > 0))'
    else
        python -c 'import json,sys; print(json.dumps([l for l in sys.stdin.read().split("\n") if l]))'
    fi
}

json_string() {
    if command -v jq >/dev/null 2>&1; then
        jq -R -s .
    else
        python -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
    fi
}

write_report() {
    local failed_stage="${1:-}"
    local log_file="${2:-}"
    local error_summary="${3:-}"

    # Extract failing files from log if possible
    local failing_files="[]"
    if [[ -n "$log_file" && -f "$log_file" ]]; then
        # Grep for common error patterns: file paths with line numbers
        failing_files=$(grep -oP '(?:^|\s)\./?\S+\.[jt]sx?(?::\d+)?' "$log_file" 2>/dev/null \
            | sort -u | head -20 \
            | json_array 2>/dev/null || echo "[]")
    fi

    cat > "$REPORT_FILE" <<ENDJSON
{
  "timestamp": "$(timestamp)",
  "branch": "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")",
  "commit": "$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")",
  "stages_run": $(printf '%s\n' "${STAGES_RUN[@]}" | json_array),
  "stages_passed": $(printf '%s\n' "${STAGES_PASSED[@]}" | json_array),
  "stages_failed": $(printf '%s\n' "${STAGES_FAILED[@]}" | json_array),
  "failed_stage": "$failed_stage",
  "error_summary": $(echo "$error_summary" | json_string),
  "failing_files": $failing_files,
  "log_file": "$log_file",
  "fix_hint": "Read the log file for full error output. Fix the failing files, commit, then re-run: ./integration-pipeline.sh --skip-merge --stage $failed_stage"
}
ENDJSON
    echo ""
    echo "================================================================"
    echo "PIPELINE FAILED at stage: $failed_stage"
    echo "Report written to: $REPORT_FILE"
    echo "Full log: $log_file"
    echo "Re-run after fixing: ./integration-pipeline.sh --skip-merge --stage $failed_stage"
    echo "================================================================"
}

write_success_report() {
    cat > "$REPORT_FILE" <<ENDJSON
{
  "timestamp": "$(timestamp)",
  "branch": "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")",
  "commit": "$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")",
  "stages_run": $(printf '%s\n' "${STAGES_RUN[@]}" | json_array),
  "stages_passed": $(printf '%s\n' "${STAGES_PASSED[@]}" | json_array),
  "stages_failed": [],
  "failed_stage": null,
  "result": "ALL_PASSED"
}
ENDJSON
}

run_stage() {
    local stage_name="$1"
    local log_file="$LOG_DIR/${stage_name}.log"
    shift

    # Skip if running a single stage and this isn't it
    if [[ -n "$SINGLE_STAGE" && "$SINGLE_STAGE" != "$stage_name" ]]; then
        return 0
    fi

    STAGES_RUN+=("$stage_name")
    echo ""
    echo "==> [$stage_name] Starting at $(timestamp)"

    if "$@" > "$log_file" 2>&1; then
        STAGES_PASSED+=("$stage_name")
        echo "==> [$stage_name] PASSED"
        return 0
    else
        local exit_code=$?
        STAGES_FAILED+=("$stage_name")
        # Extract a useful error summary (last 50 lines, filtered for errors)
        local error_summary
        error_summary=$(tail -50 "$log_file" | grep -iE "error|fail|cannot|not found|missing|conflict|CONFLICT" | head -20 || echo "See log file for details")
        write_report "$stage_name" "$log_file" "$error_summary"
        return $exit_code
    fi
}

# ── Stage implementations ─────────────────────────────────────────────────────

stage_merge() {
    if [[ "$SKIP_MERGE" == true ]]; then
        echo "    Skipping merge (--skip-merge)"
        return 0
    fi
    echo "    Running rebuild-integration.sh ${REBUILD_ARGS[*]:-}"
    bash "$SCRIPT_DIR/rebuild-integration.sh" "${REBUILD_ARGS[@]:-}"
}

stage_lint() {
    # Upstream moved to bun + oxlint + tsgo; `next lint` no longer exists in Next 16.
    echo "    Running oxlint..."
    (cd "$SCRIPT_DIR/web" && bun run lint) || return $?
    echo "    Running TypeScript type check..."
    (cd "$SCRIPT_DIR/web" && bun run types:check) || return $?
}

stage_build() {
    echo "    Running Next.js production build..."
    (cd "$SCRIPT_DIR/web" && bun run build)
}

stage_backend() {
    echo "    Checking Python syntax..."
    local errors=0
    # Find all .py files in backend/onyx and compile-check them
    while IFS= read -r -d '' pyfile; do
        if ! python -m py_compile "$pyfile" 2>&1; then
            errors=$((errors + 1))
        fi
    done < <(find "$SCRIPT_DIR/backend/onyx" -name '*.py' -print0)

    if [[ $errors -gt 0 ]]; then
        echo "    $errors Python files have syntax errors"
        return 1
    fi
    echo "    All Python files OK"

    # Check for broken imports in new provider files, and assert that every
    # provider this fork adds actually survived the merge.
    echo "    Checking provider module imports..."
    (cd "$SCRIPT_DIR/backend" && python -c "
from onyx.llm.constants import LlmProviderNames, WELL_KNOWN_PROVIDER_NAMES
from onyx.llm.well_known_providers.constants import *
from onyx.llm.well_known_providers.llm_provider_options import (
    fetch_available_well_known_llms,
)

FORK_PROVIDERS = {
    LlmProviderNames.ZAI,
    LlmProviderNames.GOOGLE_AI_STUDIO,
    LlmProviderNames.OPENAI_CODEX,
    LlmProviderNames.CLAUDE_CODE_CLI,
}
registered = {d.name for d in fetch_available_well_known_llms()}
missing = sorted(p.value for p in FORK_PROVIDERS if p.value not in registered)
if missing:
    raise SystemExit(f'  ERROR: fork providers missing from registry: {missing}')
print(f'  Provider constants OK ({len(WELL_KNOWN_PROVIDER_NAMES)} providers)')
print(f'  Fork providers OK ({len(FORK_PROVIDERS)} present)')
" 2>&1) || return $?
}

stage_test() {
    # Jest's 5s default is too tight for the heavier modal suites on slower dev
    # boxes (CustomModal's userEvent-driven tests take >10s on Windows), so they
    # time out here while passing on upstream's Linux CI runners.
    echo "    Running Jest tests..."
    (cd "$SCRIPT_DIR/web" && npx jest --ci --passWithNoTests --forceExit --testTimeout=30000 2>&1) || return $?
}

stage_deploy() {
    if [[ "$DEPLOY" == false ]]; then
        echo "    Skipping deploy (--no-deploy)"
        return 0
    fi
    echo "    Running deploy-dev.sh..."
    bash "$SCRIPT_DIR/deploy-dev.sh"
}

# ── Main pipeline ─────────────────────────────────────────────────────────────

echo "============================================="
echo " Integration Pipeline"
echo " $(timestamp)"
echo "============================================="

# Remove stale report
rm -f "$REPORT_FILE"

# Run stages in order, stop on first failure
run_stage "merge"   stage_merge   || exit 1
run_stage "lint"    stage_lint    || exit 1
run_stage "build"   stage_build   || exit 1
run_stage "backend" stage_backend || exit 1
run_stage "test"    stage_test    || exit 1
run_stage "deploy"  stage_deploy  || exit 1

write_success_report

echo ""
echo "============================================="
echo " ALL STAGES PASSED"
if [[ -n "$SINGLE_STAGE" ]]; then
    echo " (ran: $SINGLE_STAGE only)"
fi
echo "============================================="
