# AGENTS.md

ok-nikke is a Python GUI automation app for the NIKKE Windows game client, built on the PyPI `ok-script` library (ok-script-app template). Chinese copy of this file: `AGENTS.zh-CN.md`.

## Environment & commands

- Python 3.12 only. Always use the repo-local venv, never activate/global python: `.\.venv\Scripts\python.exe`.
- Install deps with `--no-deps`: `.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade`. This is required — `pyside6-fluent-widgets` declares the full PySide6 metapackage and only `pyside6-essentials` is wanted. `requirements.in` is the pip-compile source; after `pip-compile`, re-remove the generated `pyside6`/`pyside6-addons` entries.
- Run GUI: `python main_debug.py` (debug) or `python main.py`. Must be run from the repo root.
- Tests (run from repo root): `python -m unittest tests.TestMain` or `.\.venv\Scripts\python.exe -m unittest tests.TestMain`. CI runs every `tests/*.py` file; put new test files under `tests/`. OCR tests need the onnxocr model (first run downloads it).
- Docs site: `python -m pip install -r requirements-docs.txt`, then `python -m mkdocs serve` or `python -m mkdocs build --strict`. `--strict` is required by CI. Docs are bilingual (`docs/` zh + `docs/en/`) and must stay structurally aligned.

## Architecture

- `src/config.py` — the single `config` dict is the whole app config. Register tasks as `["module.path", "ClassName"]` pairs in `onetime_tasks` (and `trigger_tasks` for background tasks).
- `version = "dev"` in `src/config.py` is overwritten by CI on tag builds — do not edit it.
- `src/tasks/MyBaseTask.py` is the project base class; new tasks should subclass it rather than raw `BaseTask`. `MyOneTimeTask` (one-shot), `MyTriggerTask` (TriggerTask, repeated background checks). Custom GUI tabs live in `src/ui/MyTab.py`.
- `src/start_game.py` (imported at the top of `src/config.py`, so it runs before `ok.OK(config)` is constructed) monkey-patches the venv ok-script without editing it: it wraps `ok.register_basic_options` to add launcher settings to `Basic Options`, and replaces `ok.gui.StartController.StartController` with `NikkeStartController`, whose `start_device` does an admin check, checks whether the `nikke.exe` game process is already running (if so it skips the launcher), otherwise launches the configured launcher (`nikke_launcher.exe` or `.lnk`, auto-resolved), OCR-finds and clicks the start button in a configurable region, then waits for the game. There is no direct-launch fallback: if no launcher is configured and the game is not running, the user is prompted to configure one or start the game manually. The launcher file selector defaults to the Desktop folder so desktop shortcuts are visible.
- Gitignored runtime dirs (do not commit): `configs/` (generated config JSON), `ok_tasks/`, `ok_templates/` (template matching assets), `screenshots/`, `logs/`, `cache/`, `site/`.
- Template matching coco file is tracked at `assets/coco_annotations.json` (referenced in `src/config.py` `template_matching`).

## Conventions (differ from defaults)

- Task UI strings (`name`, `description`, `default_config` keys/values, `config_description`, `config_type` options) are written directly in Simplified Chinese for now — no i18n text pass. The GUI calls `og.app.tr()` on every displayed string, which returns the string unchanged when the catalog has no entry, so Chinese works as-is. Keep the gettext catalogs in `i18n/<locale>/LC_MESSAGES/ok.{po,mo}` (currently template demo `MyOneTimeTask` still relies on them); if i18n is re-enabled later, sync catalogs via the `$ok-script-i18n` skill (`zh_CN`, `en_US` only) and recompile `.mo`.
- Use the bundled skills in `.agents/skills/`: `ok-script-tasks` for task classes, `ok-script-codegen` for `run()` automation logic (its output requires a per-line Chinese inline comment on every code line), `ok-script-i18n` for catalogs, `use-local-venv` for python commands.
- Commit messages follow the language of the most recent non-merge commit subject.

## Release

- `.github/workflows/build.yml` triggers on `v*` tags: runs tests, `python -m ok.update.inline_ok_requirements --tag <ref>`, builds EXEs via `ok-oldking/pyappify-action`, creates a GitHub Release. `pyappify.yml` defines the China/Global profiles.
- Use the `deploy` skill for releases; it computes the next tag with `.agents/skills/deploy/scripts/next_tag.py` (note the real path is `.agents`, despite the skill doc's `.agent` typo).