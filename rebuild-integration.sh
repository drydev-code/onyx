#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REMOTE="upstream"
MAIN_BRANCH="main"
BASE_BRANCH="integration/base"
MERGED_BRANCH="integration/merged"
SYNC_MAIN=true
ALLOW_DIRTY=false
DEFAULT_FEATURE_BRANCHES=(
    "feature/glm"
    "feature/google-ai-studio-llm"
    "feature/google-ai-studio-image"
    "feature/imagerouter"
    "feature/codex"
    "feature/claude-code"
)

usage() {
    cat <<'EOF'
Rebuild the assembled integration branch for this fork.

Usage:
  ./rebuild-integration.sh [options] [feature/branch ...]

Options:
  --remote <name>        Remote to mirror into main (default: upstream)
  --main <branch>        Mirror branch name (default: main)
  --base <branch>        Shared plumbing branch (default: integration/base)
  --merged <branch>      Assembled branch to recreate (default: integration/merged)
  --no-sync-main         Skip fetching/resetting main from the remote
  --allow-dirty          Allow running with local uncommitted changes
  -h, --help             Show this help text

Examples:
  ./rebuild-integration.sh
  ./rebuild-integration.sh feature/glm feature/codex
  ./rebuild-integration.sh --no-sync-main feature/imagerouter

Behavior:
  - Syncs main from the remote unless --no-sync-main is set
  - Deletes and recreates integration/merged from main
  - Merges integration/base first
  - Merges either the provided feature branches or the default fork feature order

Default feature merge order:
  1. feature/glm
  2. feature/google-ai-studio-llm
  3. feature/google-ai-studio-image
  4. feature/imagerouter
  5. feature/codex
  6. feature/claude-code
EOF
}

require_command() {
    local command_name="$1"
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Error: required command not found: $command_name" >&2
        exit 1
    fi
}

require_git_repo() {
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "Error: this script must be run inside a git repository." >&2
        exit 1
    fi
}

require_clean_worktree() {
    if [[ "$ALLOW_DIRTY" == true ]]; then
        return
    fi

    if [[ -n "$(git status --short)" ]]; then
        echo "Error: working tree is not clean. Commit, stash, or rerun with --allow-dirty." >&2
        exit 1
    fi
}

require_local_branch() {
    local branch_name="$1"
    if ! git show-ref --verify --quiet "refs/heads/$branch_name"; then
        echo "Error: local branch not found: $branch_name" >&2
        exit 1
    fi
}

sync_main_branch() {
    require_command git

    if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
        echo "Error: remote not found: $REMOTE" >&2
        exit 1
    fi

    echo "==> Fetching $REMOTE"
    git fetch "$REMOTE"

    echo "==> Resetting $MAIN_BRANCH to $REMOTE/$MAIN_BRANCH"
    git checkout "$MAIN_BRANCH"
    git reset --hard "$REMOTE/$MAIN_BRANCH"
}

collect_feature_branches() {
    if [[ $# -gt 0 ]]; then
        FEATURE_BRANCHES=("$@")
        return
    fi

    FEATURE_BRANCHES=("${DEFAULT_FEATURE_BRANCHES[@]}")
}

rebuild_merged_branch() {
    echo "==> Recreating $MERGED_BRANCH from $MAIN_BRANCH"
    git checkout "$MAIN_BRANCH"

    if git show-ref --verify --quiet "refs/heads/$MERGED_BRANCH"; then
        git branch -D "$MERGED_BRANCH"
    fi

    git checkout -b "$MERGED_BRANCH" "$MAIN_BRANCH"

    echo "==> Merging $BASE_BRANCH"
    git merge --no-ff --no-edit "$BASE_BRANCH"

    for branch_name in "${FEATURE_BRANCHES[@]}"; do
        echo "==> Merging $branch_name"
        git merge --no-ff --no-edit "$branch_name"
    done

    echo "==> Done"
    echo "Current branch: $MERGED_BRANCH"
}

FEATURE_BRANCHES=()
POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)
            REMOTE="$2"
            shift 2
            ;;
        --main)
            MAIN_BRANCH="$2"
            shift 2
            ;;
        --base)
            BASE_BRANCH="$2"
            shift 2
            ;;
        --merged)
            MERGED_BRANCH="$2"
            shift 2
            ;;
        --no-sync-main)
            SYNC_MAIN=false
            shift
            ;;
        --allow-dirty)
            ALLOW_DIRTY=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            while [[ $# -gt 0 ]]; do
                POSITIONAL_ARGS+=("$1")
                shift
            done
            ;;
        -*)
            echo "Error: unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            POSITIONAL_ARGS+=("$1")
            shift
            ;;
    esac
done

require_git_repo
require_clean_worktree
require_local_branch "$MAIN_BRANCH"
require_local_branch "$BASE_BRANCH"
collect_feature_branches "${POSITIONAL_ARGS[@]}"

for branch_name in "${FEATURE_BRANCHES[@]}"; do
    require_local_branch "$branch_name"
done

if [[ "$SYNC_MAIN" == true ]]; then
    sync_main_branch
else
    echo "==> Skipping sync of $MAIN_BRANCH"
    git checkout "$MAIN_BRANCH"
fi

rebuild_merged_branch
