# Packaging and Release

## Release Files

- `.github/workflows/build.yml`: watches `v*` tags, tests, packages, and creates a GitHub Release.
- `pyappify.yml`: defines the app name, entry point, icon, Python version, and update repositories.
- `deploy.txt`: lists files copied to a dedicated update repository (not used yet; the source repository is the update source).

## Adapt the Build Workflow

Before the first release, update `.github/workflows/build.yml`:

- Replace the Git identity.
- Replace source and update repository URLs.
- Replace installer names and Release download links.
- Configure required GitHub Actions secrets.

This project does not integrate MirrorChyan, CNB, or file-hosting channels. Refer to the sections below if you want to add them.

## Push a Version Tag

Commit and push the initialized project, then create a tag matching `v*`:

```bash
git add .
git commit -m "Initialize project"
git push origin HEAD
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions runs the tests, packages the EXE, and creates a matching GitHub Release. Search `.github/workflows` once more for stale template repositories, names, or missing secrets before release.
