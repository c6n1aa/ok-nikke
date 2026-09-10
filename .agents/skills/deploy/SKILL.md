---
name: deploy
description: Commit completed repository changes, create the next annotated version tag, and push the commit and tag to the publishing remote (GitHub origin), which triggers the CI release build. Use when the user asks to deploy, release, publish a version, create or push a release tag, run `deploy` for a stable release, `deploy beta` for a beta prerelease, or `deploy alpha`/`release alpha` for an alpha prerelease.
---

# Deploy

Use this workflow to turn validated local changes into one commit and one annotated version tag, then push both to `origin`. If the user explicitly requests a local-only deployment, stop after creating the local tag.

## Repository facts (ok-nikke)

- Pushing a `v*` tag runs `.github/workflows/build.yml`: per-file tests → download python-build-standalone and MinGit → install `requirements.txt` into the package interpreter → write `version.txt` and `configs/update.json` → build the entry exe with MSVC → sync the CNB mirror and assert the tag exists → zip the single portable package → create the GitHub Release. **Never build or upload release artifacts by hand.**
- CI pushes the CNB mirror with the `CNB_DEPLOY_TOKEN` secret; `origin` is the only remote configured locally. Never push CNB manually.
- The release artifact is one portable zip. `python/`, `git/` and the entry exe cannot be delivered by git updates: when a release changes `launcher/` or the package layout, the release notes must tell users to re-download the package.
- In-app updates track **stable tags only**. Tags containing `-` are published as GitHub prereleases and synced to CNB, but they never raise the update badge and never appear in the version dropdown (`src/update_config.py`, `is_prerelease`). Prereleases are manual-download only.
- Old packages update themselves with **the `update.py` inside the installed package**, then check out the target tag. Keep `update.py` at the package root and keep its CLI (`--target` / `--list-tags` / `--wait-pid`) compatible, or old packages cannot update to this tag.
- When the framework version changes, bump `pyproject.toml` and re-run `pip-compile` so the tag ships the new `requirements.txt`; otherwise users update the app but keep the old framework. Details in `docs/release.md`.

## Verification before tagging

Run the repository's documented check - the same per-file loop CI runs (about 2.5 minutes):

```powershell
Get-ChildItem -Path ".\tests\*.py" | ForEach-Object {
    .\.venv\Scripts\python.exe -m unittest $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Tests failed in $($_.FullName)" }
}
```

Stop before committing or tagging if it fails, unless the user explicitly accepts the failure.

## Variants

- `deploy` or `deploy release`: create a stable tag, such as `v0.1.1`.
- `deploy beta`: create a beta tag, such as `v0.1.2-beta.1`.
- `deploy alpha` or `release alpha`: create an alpha tag, such as `v0.1.2-alpha.1`.

Stable versions increment the patch number of the latest stable `vMAJOR.MINOR.PATCH` tag. For alpha and beta independently:

- Continue an unreleased prerelease line by incrementing its suffix, for example `v0.1.2-beta.1` to `v0.1.2-beta.2`.
- If no prerelease exists for a version beyond the latest stable release, begin the next patch at `.1`, for example stable `v0.1.1` creates `v0.1.2-beta.1`.
- Treat a prerelease whose base version has already been released as closed; start the following patch rather than tagging a prerelease after its stable release.

Use `scripts/next_tag.py` (in this skill directory: `<repo>\.agents\skills\deploy\scripts\next_tag.py`; the IDE-side copy lives in `<repo>\.codebuddy\skills\deploy\scripts\`) to calculate tags; it ignores tags outside these formats.

## Workflow

1. Inspect the worktree with `git status --short --branch` and inspect the relevant diff.
   Do not include unrelated user changes in the deployment commit. If the intended commit contents are ambiguous, confirm them before staging.
2. Confirm the changes are ready to ship with the verification loop above. If verification fails, stop before committing or tagging unless the user explicitly accepts the failure.
3. Read the most recent non-merge commit subject before composing the new message:

   ```powershell
   git log --no-merges -1 --format=%s
   ```

   Write a concise commit message describing the staged changes in the same natural language as that subject. This repository's recent subjects are English `type(scope): subject` - keep that style. Preserve a recognizable local style when practical.
4. Calculate the tag before committing, selecting `release`, `beta`, or `alpha` from the user's command. Include the publishing remote so local and published tag names are both considered without overwriting an existing local tag:

   ```powershell
   .\.venv\Scripts\python.exe .agents\skills\deploy\scripts\next_tag.py release --remote origin
   .\.venv\Scripts\python.exe .agents\skills\deploy\scripts\next_tag.py beta --remote origin
   .\.venv\Scripts\python.exe .agents\skills\deploy\scripts\next_tag.py alpha --remote origin
   ```

   If no repository `.venv` exists, run the script with available Python. If remote tag lookup fails, stop before creating a version tag rather than guessing from stale local tags.
5. Stage only the intended files, inspect `git diff --cached`, then create the commit:

   ```powershell
   git add -- <intended-files>
   git diff --cached --stat
   git commit -q -m "<subject>" -m "<body paragraph>" -m "<more detail>"
   ```

   Pass the message as repeated `-m` arguments with plain ASCII text: PowerShell here-strings get mangled when the command is transported, and a broken message makes `git commit` fail while the rest of the chain keeps running. Do not create an empty commit unless the user explicitly requests it.
6. Verify the commit exists, **then** create the annotated tag as a separate command:

   ```powershell
   git log --oneline -1
   git tag -a "<calculated-tag>" -m "<calculated-tag>"
   git show --no-patch --decorate HEAD
   ```

   Never tag a previous commit because the commit step failed silently.
7. Push the commit and annotated tag to `origin`, unless the user explicitly requested local-only operation:

   ```powershell
   git push origin HEAD "<calculated-tag>"
   ```

   Verify the push succeeded before reporting the deployment complete.
8. Report the commit subject, tag, remote, and whether the push succeeded. CI publishing (release assets plus the CNB mirror tag) is a separate, slower step: report it as pending until the workflow finishes.

## Guardrails

- Never rewrite, move, or delete a published tag. `git tag -f` also erases the previous target, so record the old commit first (`git rev-parse <tag>^{commit}`) if a tag must ever be replaced.
- Never create a tag or push when the commit step did not succeed - verify `git log --oneline -1` first.
- Re-pushing the same tag starts a second workflow run for that tag; both runs publish to the same Release, and the later one wins. After a corrected push, wait for **all** runs to finish and confirm which one landed (release notes text or asset timestamps) instead of assuming.
- Never include merge commits when choosing the commit-message language.
- Never infer a successful release from a local tag alone; report push success separately from CI publishing.
- Do not push when the user explicitly requests a local-only commit or tag.
- Keep stable, beta, and alpha numbering independent except that the latest stable release closes older or equal prerelease base versions.
