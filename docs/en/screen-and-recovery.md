# Screen Recognition & Failure Recovery

This page describes the generic "screen recognition" and "failure recovery" skeleton provided by `MyBaseTask` (`src/tasks/MyBaseTask.py`). It is the shared constraint for future task development; agents must follow the "Constraints" section below when building new tasks.

## Background

Early tasks relied on `wait_feature`/`wait_click_feature` under the assumption that "clicking the entry lands on the target screen". When an unexpected state appears (popup, slow loading, network hiccup), the next wait times out and raises `WaitFailedException`, leaving the task stuck mid-flow with no recovery — and the next task keeps operating on a wrong screen assumption.

`MyBaseTask` now provides a lightweight, abstractable, extensible mechanism built entirely on existing ok-script APIs, without introducing new framework concepts.

## Plan A: Screen Recognition

The screen registry `self.screens` maps a "screen name" to its "detection spec", reusing both template matching and OCR.

### Register a screen

```python
self.register_screen(name, features=(), keywords=(), ocr_box=None)
```

- `features`: list of coco-annotated template feature names; all must match for the screen to count. Prefer template features — matching is cheaper and more stable than OCR (e.g. `"ark"`, `"friend"`).
- `keywords`: list of OCR keywords; any hit identifies the screen. Use only for pages without a stable template.
- `ocr_box`: optional OCR region as relative coordinates `[x, y, to_x, to_y]` to keep OCR cost down.

`MyBaseTask.__init__` registers the lobby by default: `register_screen("lobby", features=["ark"])` — "ark button visible = back in the lobby".

> Registration is **optional**: only register a screen when the task actually needs to detect it (`is_screen`/`wait_screen`/`assert_screen`) or needs it as a recovery target. Transient overlay pages (friend/mailbox), popups, and simple click-through tasks need no extra registration.

### Detection API

| Method | Description |
| --- | --- |
| `current_screen()` | Returns the matched screen name on the current frame, or `None` (useful for failure logs). |
| `is_screen(name)` | Single-frame check whether the task is on the given screen. |
| `wait_screen(name, time_out=10, raise_if_not_found=False)` | Waits until the screen is reached, reusing `wait_until` polling/timeout. |
| `assert_screen(name, time_out=10)` | Asserts the screen, raising `WaitFailedException` on timeout (usually combined with `try_step`). |

## Plan B: Failure Recovery

```python
self.try_step(step_fn, name=None, retries=2, recover=True, raise_on_fail=True) -> bool
```

`try_step` wraps a sub-flow entry method that starts from the lobby; a `WaitFailedException` raised inside (via `raise_if_not_found=True`) triggers the recovery protocol:

1. `save_failure_screenshot(tag)` saves the failure frame to `screenshots/failure/`;
2. logs the failure;
3. `_recover_to_lobby()` recovers: refresh frame → `close_overlay()` → click the `common_home` feature → `wait_for_lobby()` to confirm the lobby;
4. retries up to `retries` times (3 attempts by default);
5. gives up early if recovery fails; after retries are exhausted, either raises or returns `False` (caller decides to skip), depending on `raise_on_fail`.

`_recover_to_lobby` is a normal instance method; subclasses may override it to add extra recovery actions.

### Granularity: wrap entry methods, not individual internal steps

The right unit for `try_step` is the **entry method**: a sub-flow method that starts from the lobby and completes its whole navigation and operations by itself. Because a failure triggers recovery to the lobby before retrying, the wrapped step must be re-entrant from the lobby; internal steps only work after the entry method's prerequisite navigation chain, so wrapping each of them individually would cause redundant recovery and lost context.

- Wrap each entry method **once** with `try_step` in `run()`.
- Do **not** wrap the method's internal navigation/operation steps individually: any `WaitFailedException` bubbles up to the outer wrapper, which recovers to the lobby and re-runs the whole entry method (its prerequisite chain restarts naturally).
- If a step only needs in-place retry (e.g. transient OCR/template jitter), use `recover=False` to retry without the lobby round-trip.

## Asset Resolution Baseline (2560x1440)

All template-related assets in this project use **2560x1440 as the single baseline resolution**. Agents must follow this when debugging, screenshotting, or annotating:

- **Debugging screenshots**: screenshots used to reproduce issues, debug OCR, or analyze failures (user/test shots) should preferably be captured from a 2560x1440 window. Low-resolution shots (e.g. 1280x720) carry less detail, so debugging templates/OCR against them in a 1440p environment yields results that diverge from the real one (scaling, thresholds, and OCR misreads all shift).
- **coco annotations**: annotate boxes on 2560x1440 screenshots (`assets/coco_annotations.json`). `FeatureSet` auto-scales annotations to the current game resolution; the lower the source resolution, the blurrier the upscaled template and the more likely matching fails.
- **Manually cropped templates**: small templates under `assets/template/` must be cropped from 2560x1440 screenshots, then passed to `find_scaled_template` (defaults `ref_width=2560, ref_height=1440`). 1440p is the ceiling of all supported resolutions (1920x1080/1600x900/1280x720); starting from it always downscales and never upscales, giving the most reliable matches.

Exception: if only a non-1440p screenshot is available, it technically still works (coco scales by the source image's own dimensions; `find_scaled_template` accepts `ref_width`/`ref_height` overrides), but the asset's original resolution must be remembered and declared explicitly — never treat it as the default baseline.

## Usage Example

```python
# Wrap each entry method (sub-flow) once; do not wrap its internal steps individually.
if not self.try_step(self._collect_friend, name="收获友情点", raise_on_fail=False):
    self.log_warning("友情点收取失败，跳过。")
if not self.try_step(self._collect_mailbox, name="收取邮箱", raise_on_fail=False):
    self.log_warning("邮箱收取失败，跳过。")

# Register a screen only when you actually need to detect/wait for it, then assert.
self.register_screen("方舟塔", features=["ark_tribe_tower"])
self.assert_screen("方舟塔", time_out=10)
```

## Constraints (agents must follow)

- Screen registration is **optional**: use `register_screen` only when the task really needs to detect a screen (`is_screen`/`wait_screen`/`assert_screen`) or needs it as a recovery target. Transient overlay pages (friend/mailbox), popups, and simple click-through tasks need no extra registration.
- The lobby `lobby` is registered by default as `_recover_to_lobby`'s target; do not re-register it.
- The granularity of `try_step` is the **entry method**: wrap each self-contained sub-flow that starts from the lobby **once** with `try_step(...)` in `run()`; do **not** wrap individual internal steps (failures bubble up to the outer wrapper, which recovers to the lobby and re-runs the whole sub-flow). Never hand-roll ad-hoc retry/recovery logic.
- Do not bypass `_recover_to_lobby` with hard-coded "click home by coordinates" recovery.
- Failure screenshots are always written by `save_failure_screenshot` to `screenshots/failure/`; do not save them elsewhere.
- Prefer coco template features for screen detection; use OCR keywords only when no stable template exists, and bound the region with `ocr_box`.
- Asset resolution baseline: debugging screenshots, coco annotations, and manually cropped templates all use 2560x1440 as the baseline (see "Asset Resolution Baseline" above); do not debug or annotate against low-resolution screenshots.
- When changing the recovery protocol or adding detection methods, update `tests/TestScreenRecovery.py` accordingly.

## Tests

`tests/TestScreenRecovery.py` covers screen recognition (template/OCR matching, no-match), `try_step` (success, retry, skip, give-up-on-recovery-failure), and `_recover_to_lobby` (already in lobby / returns via `common_home`).