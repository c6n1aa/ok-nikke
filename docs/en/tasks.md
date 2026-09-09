# Task Development

Task classes live in `src/tasks/`:

- One-shot tasks inherit `NikkeBaseTask`.
- Background trigger tasks inherit `NikkeBaseTask` and the framework's `TriggerTask` (`class MyTriggerTask(NikkeBaseTask, TriggerTask)`).

Never inherit the framework's `BaseTask`/`TriggerTask` directly — `NikkeBaseTask` encapsulates screen recognition, navigation, failure recovery, completion state, and template scaling.

Starter templates:

- One-shot task: `src/tasks/MyOneTimeTask.py`
- Background trigger task: `src/tasks/MyTriggerTask.py`
- Base class and shared capabilities: `src/tasks/NikkeBaseTask.py` (implementation split by responsibility into mixins under `src/tasks/base/`; the base class only composes them)

## Write a Task

Task classes declare their UI through attributes; no manual widgets:

| Attribute | Description |
| --- | --- |
| `name` / `description` | Task name and description, written in Simplified Chinese directly (this project does not i18n task strings) |
| `default_config` | Default values of config items |
| `config_type` | Widget type of each config item (drop-down, boolean, numeric, text, multi-select, etc.) |
| `done_keys` | Completion-state keys and periods, e.g. `{"harvest": "day"}`; pure orchestrator/debug tasks omit it |

Automation logic goes in `run()`. Adding a new `config_type` requires a matching branch in the `ConfigItemFactory` factory.

## Task Conventions

Read [Screen recognition & failure recovery](screen-and-recovery.md) before writing tasks. Core conventions:

- **Screens are registered centrally** in `SCREENS` in `src/screens.py`; never `register_screen` in a task's `__init__`.
- **Navigation** uses `transition()` (click entry → confirm arrival); **entry gates** use `ensure_screen()` (idempotent siting at sub-flow start).
- **Failure recovery** wraps the lobby-starting entry method with `try_step` **once**; internal steps are not wrapped individually, and no hand-written retry or back-to-lobby logic.
- **Template matching**: coco features use `find_feature`/`find_one` (scaled automatically by resolution); small templates under `assets/template/` must go through `find_scaled_template()`; never match an unscaled template directly.
- **Waits** hang on framework API parameters such as `after_sleep`/`time_out` instead of hand-written `self.sleep`; battle end uses `wait_battle_finish`, never `wait_feature`/`wait_ocr` busy-polling.
- **Popups** are cleared by the base class's `dismiss_all_popups`; new popups only hook `_try_close_one_popup`.

## Register a Task

Register the module path and class name in `src/config.py`:

```python
'onetime_tasks': [
    ['src.tasks.HarvestTask', 'HarvestTask'],
],
```

Background periodic tasks go into `trigger_tasks` (currently empty). Order equals GUI display order.

## Debugging

```powershell
.\.venv\Scripts\python.exe main_debug.py
```

Debug mode provides screenshots, template-matching visualization, and annotation tools. Debug screenshots should use a 2560×1440 window, matching the asset baseline.

## Tests

Tests live under `tests/`, named `TestXxxTask.py` to match `src/tasks/XxxTask.py`, inheriting `ok.test.TaskTestCase` with `task_class` set, and fixing input frames with `self.set_image()`. Examples: `tests/TestShopTask.py`, `tests/TestArkTask.py` (covering success/skip/failure/already-done branches).

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestMain
.\run_tests.ps1   # full suite, one file per process
```

- Never touch the real environment: must-run methods like `wait_for_lobby` and `dismiss_all_popups` are intercepted with `patch.object` and asserted.
- Drive `while True`-style flows with finite `side_effect` sequences instead of looping mocks.

## AI-Assisted Development

The repository includes Agent Skills: `$ok-script-tasks` (create/modify/register task classes), `$ok-script-codegen` (generate `run()` logic from requirements or screenshots), `$ok-script-i18n` (sync translations).

Recommended flow: write a brief following the [task brief template](task_brief_template.md) (screens, flow tree, failure handling), let the Codegen skill generate the code, then add tests.
