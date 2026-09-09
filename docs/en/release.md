# Packaging and Release

For developers. End users just download the portable package from [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases); see [Quick start](getting-started.md).

## Release Files

- `.github/workflows/build.yml`: watches `v*` tags, runs tests (one file per process), inlines ok-script into the source bundle (`inline_ok_requirements`, removed from requirements to speed up in-app updates), then uses pyappify-action to compile only the launcher exe (`build_exe_only`), runs `ok-nikke.exe -c setup -p Release` to generate the `data/` folder (embedded Python + venv + code cloned at the tag), zips everything into a portable package and creates a GitHub Release. No NSIS installer.
- `pyappify.yml`: defines the app name, entry point, icon, Python version, and update repository. A single `Release` profile; keep the profile name in sync with the `-p` argument of the `setup` step in the workflow.
- `pyappify-cn.yml` / `pyappify-global.yml`: update source configs shipped in the package root. Both currently point to GitHub (no China mirror yet); users rename one to `pyappify.yml` before the first run.
- `deploy.txt`: lists files synced to a dedicated update repository (unused; the source repository is the update source).

## Release Artifact

Each tag publishes exactly one file:

- `ok-nikke-win32-portable.zip`: full portable package (launcher exe + `data/` with all dependencies). Extract anywhere and run `ok-nikke.exe` (administrator rights required).

The package root also ships `pyappify-cn.yml` and `pyappify-global.yml`. Before the first run, rename one of them to `pyappify.yml` (next to `ok-nikke.exe`) according to your network; the launcher reads it as the update source config. Both currently point to GitHub; once a China mirror repository exists, `pyappify-cn.yml` will switch to the mirror address.

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

The launcher exe only needs recompiling when the icon or pyappify configuration changes. For routine releases you can add the `use_release` input to the `Build launcher with PyAppify Action` step to reuse the launcher from a previous release and shorten build times:

```yaml
- name: Build launcher with PyAppify Action
  id: build-app
  uses: ok-oldking/pyappify-action@master
  with:
    use_release: https://api.github.com/repos/c6n1aa/ok-nikke/releases/tags/v0.1.0
```

Note that `use_release` downloads the `ok-nikke-win32.zip` launcher-only asset from the referenced release, while this project's releases only ship the portable zip. To use this acceleration, the workflow must additionally publish that launcher-only zip, or the exe must be fetched from another location.
