# Packaging and Release

For developers. End users just download the portable package from [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases); see [Quick start](getting-started.md).

## Release Files

- `.github/workflows/build.yml`: watches `v*` tags, runs tests (one file per process), inlines ok-script into the source bundle (`inline_ok_requirements`, removed from requirements to speed up in-app updates), then uses pyappify-action to compile only the launcher exe (`build_exe_only`), runs `ok-nikke.exe -c setup -p Release` to generate the `data/` folder (embedded Python + venv + code cloned at the tag), zips everything into a portable package and creates a GitHub Release. No NSIS installer.
- `pyappify.yml`: defines the app name, entry point, icon, Python version, and update repository. Two profiles: `Release` (GitHub) and `Release-CN` (CNB mirror, inheriting all other fields); the profile names correspond to the `-p` arguments of the `setup` step in the workflow.
- `deploy.txt`: lists files synced to the CNB mirror repository (`src`, `ok`, `main.py`, `assets`, `pyappify.yml`, etc.).

## Release Artifact

Each tag publishes the following files:

- `ok-nikke-win32-portable.zip`: global portable package (launcher exe + `data/` with all dependencies), updating from GitHub. Extract anywhere and run `ok-nikke.exe` (administrator rights required).
- `ok-nikke-win32-portable-cn.zip`: China portable package, updating from the CNB mirror (`https://cnb.cool/c6n1aa/ok-nikke`). Extract anywhere and run `ok-nikke.exe` (administrator rights required).
- `ok-nikke-win32.zip`: launcher exe only, for CI reuse to speed up later builds (see "Reusing the Launcher to Speed Up Builds" below); end users do not need it.

The two packages share the same exe; they differ only in the profile used at `setup` time (global uses `Release`, CN uses `Release-CN`), so each package bakes a different update source (its active profile) into `data/`.

In-app updates are handled by the launcher via git tags (fetch `git_url` -> checkout -> re-run pip when requirements change) and do not depend on the release artifact format. `git_url` is driven by the `pyappify.yml` tracked in the repository; changing it takes effect with the next release without rebuilding the launcher.

## Adapt the Build Workflow

To adjust release settings, edit `.github/workflows/build.yml`:

- Git identity, source and update repository URLs.
- Portable package name and Release download links.

The workflow already declares `permissions: contents: write`; no extra secrets are required.

This project does not integrate MirrorChyan, CNB, or file-hosting channels; refer to the framework docs if you want to add them.

## Publish a New Version

Prefer the built-in `deploy` skill (`.agents/skills/deploy/`): it commits, creates the next annotated tag, and pushes automatically. You can also do it manually:

```bash
git tag v0.x.0
git push origin v0.x.0
```

After a `v*` tag is pushed, GitHub Actions runs the tests, packages the portable zip, and creates the GitHub Release. Tag names containing `-` (e.g. `v0.2.0-beta.1`) are marked as prerelease.

## Reusing the Launcher to Speed Up Builds

Compiling the launcher exe (Tauri) takes about 70% of the build time (~12 minutes). Both the icons (`icons/`) and `pyappify.yml` are embedded in the exe, so as long as neither has changed since a published release, later releases can reuse that release's launcher:

1. Every release ships an `ok-nikke-win32.zip` launcher-only asset (top-level folder `ok-nikke/ok-nikke.exe`, same layout as pyappify's base zip).
2. Set the `USE_RELEASE` env var in `.github/workflows/build.yml` to a release API URL (e.g. `https://api.github.com/repos/c6n1aa/ok-nikke/releases/tags/v0.1.1`); the build then skips compilation and downloads the exe from that release. Leave it empty for routine builds.

The pyappify-action's own `use_release` input is mutually exclusive with `build_exe_only` and would additionally bundle NSIS installers, so this workflow does not use it; the `Reuse launcher from previous release` step implements the equivalent instead. Any release that changes the icons or `pyappify.yml` must leave `USE_RELEASE` empty and compile from scratch, otherwise the packages would ship a stale launcher with the old configuration.
