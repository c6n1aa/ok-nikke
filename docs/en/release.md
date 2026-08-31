# Packaging and Release

## Release Files

- `.github/workflows/build.yml`: watches `v*` tags, runs tests, uses pyappify-action to compile only the launcher exe (`build_exe_only`), then runs `ok-nikke-maid.exe -c setup -p Release` to generate the `data/` folder (embedded Python + venv + code cloned at the tag), zips everything into a portable package and creates a GitHub Release. No NSIS installer.
- `pyappify.yml`: defines the app name, entry point, icon, Python version, and update repository. A single `Release` profile; no China/Global split. Keep the profile name in sync with the `-p` argument in the workflow.
- `deploy.txt`: lists files copied to a dedicated update repository (not used yet; the source repository is the update source).

## Release Artifact

Each tag publishes exactly one file:

- `ok-nikke-maid-win32-portable.zip`: full portable package (launcher exe + `data/` with all dependencies). Extract anywhere and run `ok-nikke-maid.exe` (administrator rights required).

In-app updates are handled by the launcher via git tags (fetch `git_url` -> checkout -> re-run pip when requirements change) and do not depend on the release artifact format. `git_url` is driven by the `pyappify.yml` tracked in the repository; changing it takes effect with the next release without rebuilding the launcher.

## Adapt the Build Workflow

Before the first release, update `.github/workflows/build.yml`:

- Replace the Git identity.
- Replace source and update repository URLs.
- Replace the portable package name and Release download links.

The workflow already declares `permissions: contents: write`; no extra secrets are required.

This project does not integrate MirrorChyan, CNB, or file-hosting channels. Refer to the sections of the framework docs if you want to add them.

## Push a Version Tag

Commit and push the initialized project, then create a tag matching `v*`:

```bash
git add .
git commit -m "Initialize project"
git push origin HEAD
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions runs the tests, packages the portable zip, and creates a matching GitHub Release. Search `.github/workflows` once more for stale template repositories, names, or missing secrets before release.

## Reusing the Launcher to Speed Up Builds

The launcher exe only needs recompiling when the icon or pyappify configuration changes. For routine releases you can add the `use_release` input to the `Build launcher with PyAppify Action` step to reuse the launcher from a previous release and shorten build times:

```yaml
- name: Build launcher with PyAppify Action
  id: build-app
  uses: ok-oldking/pyappify-action@master
  with:
    use_release: https://api.github.com/repos/c6n1aa/ok-nikke-maid/releases/tags/v0.1.0
```

Note that `use_release` downloads the `ok-nikke-maid-win32.zip` launcher-only asset from the referenced release, while this project's releases only ship the portable zip. To use this acceleration, the workflow must additionally publish that launcher-only zip, or the exe must be fetched from another location.
