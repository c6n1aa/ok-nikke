# Packaging and Release

For developers. Regular users can download the portable package from [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) — see [Getting started](getting-started.md).

## Release Format

**A single package**: `ok-nikke-win32-portable.zip`, extract and run.

Package layout:

```
ok-nikke/
├── ok-nikke.exe            # entry shim: self-elevates (UAC) and launches python\pythonw.exe main.py with cwd = package root
├── python/                 # python-build-standalone (relocatable, ships pip); dependencies live in its Lib/site-packages
├── git/                    # MinGit (cmd/git.exe) used by in-app updates for fetch/checkout
├── src/ assets/ icons/ i18n/ main.py main_debug.py update.py
├── version.txt             # version number (written by the build, maintained by update.py; never committed)
└── configs/update.json     # update source (channel: auto|github|cnb)
```

- Dependencies come from `requirements.txt`, which **keeps `ok-script`/`pyappify`**.
- The update channel defaults to `auto` (by system language: Chinese → CNB mirror, otherwise → GitHub) and can be changed under "About → App update".

## Release Files

- `.github/workflows/build.yml`: watches `v*` tags and, in order: installs runner dependencies → runs tests (one file per process) → downloads python-build-standalone into `python/` → downloads MinGit into `git/` → installs `requirements.txt` into the package interpreter (`--no-deps`) → writes `version.txt` and the default `configs/update.json` → builds the entry exe with MSVC (`launcher/build.py`, which validates the UAC manifest after linking) → syncs the CNB mirror and asserts the tag exists → zips the single portable package → generates the release notes (`.github/scripts/release_notes.py`) → creates a GitHub Release. No NSIS installer.
- `deploy.txt`: files synced to the CNB mirror repository (`src`, `main.py`, `update.py`, `launcher`, `assets`, ...). The mirror shares the same tags and serves in-app updates for China.
- `launcher/`: entry shim sources (`launcher.c`, `launcher.manifest`, `launcher.rc`) plus `build.py` (auto-detects MinGW or MSVC). Changing the icon/elevation requires a new release — **the entry exe, `python/` and `git/` cannot be updated through git**.
- `update.py`: in-app update bootstrap (standard library only): fetch tag → checkout → pip when needed → write version → restart the app.
- `.github/scripts/release_notes.py`: release-note generation (standard library only; handwritten override plus conventional-commit sections, see below).
- `changelog/`: optional user-facing release notes (`changelog/<tag>.md`); the `deploy` skill writes them only when release notes are explicitly requested, and the file takes precedence over the generated list (see below).

## Release Notes

The GitHub Release body is no longer hard-coded: before creating the release, CI runs `.github/scripts/release_notes.py` to write `release_notes.md` and passes it to `softprops/action-gh-release` via `body_path`. Rules:

- **Handwritten override first**: when `changelog/<tag>.md` exists, its body becomes the changelog section verbatim (group with `####` subheadings; do not add a `### 更新日志` heading inside it; reference issues as `（#12）` and GitHub links them automatically), and it **must be committed with the tag** so CI can read it. The `deploy` skill does **not** write it by default - only when the user explicitly asks for release notes; manual releases may write it by hand. Leave it out to use the generated list.
- **Auto-generated fallback**: otherwise the script classifies the non-merge commits in `<previous tag>..<tag>` — `feat` features, `fix` fixes, `perf` performance, `revert`/`refactor` other changes; `docs`/`chore`/`ci`/`test`/`build`/`style` stay hidden unless nothing else remains; entries marked `!` or with a `BREAKING CHANGE` body get their own section. The previous tag is the closest `v*` tag; a first release simply says so.
- Both modes append: a prerelease notice (tags containing `-`), the download section (portable zip link) and a full-changelog compare link; auto mode also tells users to re-download the full package when `launcher/` changed in the range (the entry exe cannot be delivered through in-app git updates).
- Preview locally without releasing (`release_notes.md` is git-ignored, safe to write at the repo root):

  ```powershell
  .\.venv\Scripts\python.exe .github\scripts\release_notes.py --tag v0.2.0 --out release_notes.md
  ```

## Release Artifact

Each tag publishes one file:

- `ok-nikke-win32-portable.zip`: the complete portable package. Extract anywhere and run `ok-nikke.exe` (administrator rights required; the UAC prompt shows "unknown publisher" until the exe is code-signed).

## Update Mechanism

In-app updates are fully handled by `update.py` (git tag semantics, upgrades and downgrades):

1. "Check for updates" runs `update.py --list-tags`; "Update/Downgrade" runs `update.py --target <tag> --wait-pid <current pid>`.
2. `update.py` waits for the old process to exit → `git init`/seed (first run) → `git fetch --depth=1 origin tag <tag>` → installs dependencies first when the requirements fingerprint changed → `checkout -f` → writes `version.txt`.
3. Any failing step falls back to launching the old version; the package must never be left unbootable. Logs: `logs/update.log`.
4. **Stable releases only**: prereleases (tags containing `-`, e.g. `v0.2.0-beta.1`) never raise the navigation badge and never appear in the version dropdown (see `is_prerelease` in `src/update_config.py`, which shares its rule with `update.py.version_key`); users who want a prerelease download it manually from the Release page. The dropdown lists the five most recent stable tags (`update_config.selectable_versions` / `MAX_VERSION_OPTIONS`), excluding the current version; selecting an older tag turns the button into "Downgrade".

**Release checklist (option C)**: when upgrading the framework, bump `pyproject.toml` and re-run `pip-compile` so `requirements.txt` matches the tag; otherwise the lock inside the tag is stale and users see an updated version with an old framework. Never commit `version.txt` / `version.txt.prev`, and never add them to `deploy.txt`.

## Adapt the Build Workflow

Edit `.github/workflows/build.yml` to change:

- the standalone Python version line (`STANDALONE_PYTHON`), git user info, repository URLs.
- the package name and the Release download links.

The workflow already declares `permissions: contents: write`; the CNB sync uses the `CNB_DEPLOY_TOKEN` repository secret.

## Publishing a New Version

Use the built-in `deploy` skill (`.agents/skills/deploy/`), which commits, creates the next annotated tag and pushes; when release notes are explicitly requested it also writes the user-facing `changelog/<tag>.md`. Or do it manually:

```bash
git tag v0.x.0
git push origin v0.x.0
```

After a `v*` tag is pushed, GitHub Actions runs the tests, builds the portable zip and creates the GitHub Release; tags containing `-` (e.g. `v0.2.0-beta.1`) are marked as prereleases **and are never offered by the in-app update check** - prereleases are manual-download only.

