# Branch Strategy for the Onyx Fork

This repository uses a branch model that keeps the fork easy to sync with upstream while allowing custom features to be developed and combined as needed.

## Goals

- Keep `main` as a clean mirror of upstream `onyx/main`
- Develop each custom feature in its own branch under `feature/*`
- Use `integration/base` for shared plumbing and cross-cutting changes
- Use `integration/merged` as the assembled branch that combines upstream plus selected custom branches
- Make it easy to rebuild the integrated fork after upstream changes

## Branch Roles

### `main`

`main` is a mirror branch.

Rules:
- It should always match upstream `main`
- No direct feature development happens here
- No fork-specific commits should live here
- It is the reset point for rebuilding integration branches

In practice, `main` is the local copy of upstream Onyx.

### `feature/*`

Each custom feature gets its own branch.

Examples:
- `feature/glm`
- `feature/imagerouter`
- `feature/aistudio-llm`
- `feature/aistudio-image`
- `feature/claude-code`
- `feature/codex`
- `feature/other-customization`

Rules:
- One feature branch should represent one logically independent feature
- Rebase or update these branches against `main`
- Keep shared plumbing out of feature branches when possible
- If a feature depends on shared integration code, put that shared part in `integration/base`

This naming also leaves room for non-provider features in the same model.

### `integration/base`

`integration/base` contains shared plumbing and cross-cutting changes needed by multiple feature branches.

Examples:
- shared provider abstractions
- routing or registration plumbing
- common config wiring
- shared UI or backend extension points used by several features

Rules:
- Only put code here that is truly shared
- Do not put feature-specific behavior here unless it is impossible to isolate
- Rebase this branch on top of `main`
- Feature branches that require shared plumbing can be based on or merged with this branch as needed

This branch reduces duplicated edits across many feature branches.

### `integration/merged`

`integration/merged` is the assembled branch.

It is built from:
- `main`
- `integration/base`
- one or more `feature/*` branches

Rules:
- Treat it as disposable and rebuildable
- Do not do long-term feature development directly on it
- Use it for testing the combined fork
- Recreate it whenever upstream or feature branches change significantly

This branch represents the fork variant you actually run.

## Recommended Workflow

### 1. Sync upstream into `main`

Update `main` so it matches upstream exactly.

Example:

```bash
git checkout main
git fetch upstream
git reset --hard upstream/main
```

If you also publish your fork's `main`, push it normally after verifying it is correct.

### 2. Update integration and feature branches

Rebase `integration/base` onto the updated `main`.

```bash
git checkout integration/base
git rebase main
```

Then update each feature branch.

```bash
git checkout feature/glm
git rebase main
```

If a feature depends on shared plumbing from `integration/base`, either:
- rebase the feature branch onto `integration/base`, or
- merge `integration/base` into the feature branch

Choose one approach and use it consistently.

Suggested default:
- independent features -> rebase onto `main`
- features depending on shared plumbing -> rebase onto `integration/base`

### 3. Rebuild `integration/merged`

Delete and recreate `integration/merged` from `main`, then merge in the branches you want.

```bash
git checkout main
git branch -D integration/merged
git checkout -b integration/merged
```

Merge the shared base first:

```bash
git merge integration/base
```

Then merge the desired feature branches:

```bash
git merge feature/glm
git merge feature/imagerouter
git merge feature/claude-code
git merge feature/codex
```

Resolve conflicts, run tests, and use this branch as the combined fork.

## Why This Structure Works

This model gives you:

- a clean upstream mirror in `main`
- isolated, maintainable feature branches
- one place for shared plumbing in `integration/base`
- a disposable assembled branch in `integration/merged`
- a repeatable rebuild process after upstream changes

It is especially useful when you want to enable, disable, or reorder custom features independently.

## Trade-offs

The main downside is merge maintenance.

If multiple feature branches touch the same core files, you may see repeated conflicts when:
- rebasing features after upstream changes
- merging features into `integration/merged`

Using `integration/base` for truly shared code helps reduce that problem, but it will not remove it entirely.

## Practical Guidelines

- Never commit fork-specific changes directly to `main`
- Keep feature branches focused and independent when possible
- Move only genuinely shared plumbing into `integration/base`
- Treat `integration/merged` as generated output, not as a long-lived development branch
- Test on `integration/merged`, not only on individual feature branches
- Keep branch names stable so rebuild scripts stay simple

## Automation

This repository now includes a rebuild script at `./rebuild-integration.sh`.

It does the following:
1. syncs `main` from `upstream` by default
2. deletes and recreates `integration/merged` from `main`
3. merges `integration/base`
4. merges either the feature branches you pass explicitly or all local `feature/*` branches
5. stops on conflicts so they can be resolved manually

### Basic usage

Rebuild `integration/merged` with all local `feature/*` branches:

```bash
./rebuild-integration.sh
```

Rebuild with only selected features:

```bash
./rebuild-integration.sh feature/glm feature/codex
```

Rebuild without syncing `main` first:

```bash
./rebuild-integration.sh --no-sync-main feature/imagerouter
```

Show all options:

```bash
./rebuild-integration.sh --help
```

### Notes

- Default remote: `upstream`
- Default mirror branch: `main`
- Default shared branch: `integration/base`
- Default assembled branch: `integration/merged`
- The script expects the relevant branches to already exist locally
- By default it requires a clean working tree before running

This makes the integration branch reproducible instead of hand-maintained.

## Recommended Default Policy

Use this as the default operating model:

- `main` = exact upstream mirror
- `feature/*` = one branch per independent feature
- `integration/base` = shared plumbing and cross-cutting support
- `integration/merged` = disposable assembled branch for testing and daily use

This is a good fit for a fork that tracks upstream closely while carrying a configurable set of custom additions.
