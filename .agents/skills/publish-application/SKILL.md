---
name: publish-application
description: Publish this Electron application through its GitHub tag workflow by deriving the next version from the latest remote release, updating package manifests, validating the release surface, pushing the tag, monitoring Actions, and verifying release assets and checksums. Use when asked to publish, release, tag, or distribute the application through GitHub.
---

# Publish Application

Use this workflow for a real application release. Treat the latest GitHub tag or release as the source of truth for version progression; do not invent a version from the local checkout.

## Workflow

1. Inspect `AGENTS.md`, the current branch, remotes, and `git status`. Preserve unrelated changes and never stage untracked files outside the release scope.

2. Determine the next version from GitHub:

   - Read the latest `vX.Y.Z`, `vX.Y.Z-alpha.N`, `vX.Y.Z-beta.N`, or `vX.Y.Z-rc.N` tag/release with `git ls-remote --tags origin` or `gh release list`.
   - If the latest release is an alpha, beta, or release candidate, increment its numeric suffix (`rc.1` → `rc.2`).
   - If the next channel cannot be inferred safely, ask the user before changing files.
   - Require the release tag to match `v<package version>` exactly.

3. Update application metadata before publishing:

   - Change `frontend/package.json` version.
   - Change the root package version and `packages[""].version` in `frontend/package-lock.json`.
   - Confirm all three values match the derived version.
   - Keep release notes and workflow paths consistent with the new tag. Do not add screenshot placeholders unless the user supplied screenshots.

4. Run the smallest required checks from `AGENTS.md`. For this repository, release metadata and workflow changes require frontend typecheck/unit tests when frontend files change, backend runtime invariant tests when runtime packaging is involved, and a YAML parse plus `git diff --check` for workflow changes. The CI matrix must verify `.exe`, `.dmg`, `.AppImage`, and `.deb` assets and enforce the configured minimum size.

5. Review the staged diff. Commit only release files with a Conventional Commit message. Create an annotated tag `v<version>` on that commit. Never overwrite an existing published tag or release without explicit direction.

6. Publish by pushing the tag to `origin`. The tag-triggered workflow must retain frontend checks, runtime invariants, all three platform builds, `contents: write`, checksum generation, and a publisher allowed by the repository Actions policy. Do not publish diagnostics as release assets.

7. Monitor the exact workflow run with `gh run list` and `gh run view`. On failure, inspect `gh run view <run-id> --log-failed` before changing files. Do not claim success while the build or publish job is still running.

8. Verify the resulting release with `gh release view` or the GitHub API:

   - tag matches the package version;
   - prerelease metadata is true for alpha, beta, and rc tags and false for stable tags;
   - Windows, macOS, and Linux installer assets are present;
   - `SHA256SUMS.txt` is present and contains only published installer assets;
   - freshly downloaded assets match every checksum entry.

## Safety

- Preserve unrelated worktree changes, including untracked tests or local caches.
- Do not delete releases, tags, artifacts, or user data as part of a normal publish.
- Stop if the remote has a newer release than the local assumption or if the target tag already exists.
- Report the commit, tag, workflow run, release URL, asset verification, and any platform limitations.
