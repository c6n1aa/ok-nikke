# Screen Recognition & Failure Recovery

This page is the shared constraint for task development: `NikkeBaseTask` (`src/tasks/NikkeBaseTask.py`) provides a three-layer skeleton — "screen recognition + guarded navigation + failure recovery" — built entirely on existing ok-script APIs. Agents must follow the "Constraints" section when building new tasks.

- Detection data is centralized in `src/screens.py` (single source of truth); detection/navigation/recovery mechanics live in `NikkeBaseTask`.
- The frame-level detection cache is fully transparent: results are bit-identical to uncached detection; callers of the APIs below never need to think about it.

## Screen Recognition

### Registering screens

Global screens are registered centrally in `src/screens.py` under `SCREENS` (auto-loaded by `NikkeBaseTask.__init__`; do not re-register). **New screens go into `SCREENS` first**; `register_screen` is reserved for rare task-private screens (same name overrides the global entry):

```python
SCREENS = {
    "lobby": {"features": ["ark", "lobby"]},
    ...
    "new_screen": {"features": ["xxx_feature"]},  # append at the end
}
# Task-private extension (only when genuinely needed):
self.register_screen(name, features=(), keywords=(), ocr_box=None, **extra)
```

spec fields (absent fields = current/legacy behavior):

| Field | Default | Semantics |
|---|---|---|
| `features` | `()` | coco template feature names; ALL must match (AND). Prefer these — cheaper and more stable than OCR |
| `any_features` | `()` | Any-hit feature names; a single match counts as the feature check passing (OR); when combined with `keywords`, the AND rule applies on top. For icon-any-of semantics (e.g. the cancel/log/skip icons on the advise conversation page) |
| `feature_box` | `None` | Optional match region (a coco region feature name, resolved to current resolution), applies only to `any_features` matching; missing region falls back to full-screen matching |
| `keywords` | `()` | OCR keyword list; ANY hit matches (OR). Only for pages without a stable template |
| `ocr_box` | `None` | Optional OCR region: relative `[x, y, to_x, to_y]` or a coco region feature name (resolved to current resolution); missing feature falls back to full-screen OCR |
| `absent` | `[]` | Disambiguation features; any match fails the screen outright (disambiguates adjacent screens with overlapping feature subsets) |
| `priority` | `0` | Only affects `current_screen()` return order: descending priority, ties keep registration order |
| `min_frames` | `1` | Only applies to `wait_screen`/`assert_screen` polling: N consecutive poll hits required; `is_screen` stays single-frame and ignores this field |

### Detection API

| Method | Description |
| --- | --- |
| `current_screen()` | Detects the current screen on this frame, iterating in descending `priority`; returns the first match, or `None` (useful for failure logs) |
| `is_screen(name)` | Single-frame check for the given screen |
| `wait_screen(name, time_out=10, raise_if_not_found=False)` | Waits until the screen is reached; `min_frames` consecutive-hit semantics apply here |
| `assert_screen(name, time_out=10)` | Asserts the screen, raising `WaitFailedException` on timeout (pairs with `try_step`) |

## Navigation

### Entry gate: `ensure_screen()`

At the start of a sub-flow, "make sure I'm on screen X" is ALWAYS `ensure_screen()` — never hand-roll the "`is_screen` shortcut + wait-for-lobby + find entry + click entry + assert" sequence:

```python
self.ensure_screen("ark", click_feature="ark", wait_confirm=10, after_sleep=1)

# When the entry must be located dynamically after reaching the lobby, and a missing
# entry means "nothing to do this cycle" (e.g. limited-time modes), pass an entry resolver:
def find_entry():
    box = self._find_panel_entry("coop", panel)
    if box is None:
        self.log_info("未找到协同作战入口，视为已完成。")
    return box
if not self.ensure_screen("coop_page", entry=find_entry, wait_confirm=10, after_sleep=1):
    return  # entry missing: caller marks done.
```

Internals: already on / currently transitioning into the target -> return immediately (polls `wait_enter=5`s per round, tolerating slide-in animations) -> dismiss popups and poll once more -> route by cold-start or recovery (positive `login_page` match or zero in-app evidence -> cold-start `wait_until_lobby_after_start`; in-app evidence -> `_recover_to_lobby`) -> dismiss lobby popups -> if a click source is given, guarded `transition()` entry (the `entry` resolver runs only after the lobby is reached; returning None makes this method return False); if no click source (target is the lobby itself), tail `wait_screen` confirmation. Defaults to `raise_on_fail=True` (for `try_step` recovery); pass `raise_on_fail=False` at task starts for graceful abort. The login page `login_page` (keyword TOUCH TO CONTINUE + `box_enter_game` region) is registered in `src/screens.py` as a positive cold-start anchor — a match definitively means cold-start entry, overriding button-based inference. Task-start lobby-siting is uniformly `ensure_screen("lobby")` (HarvestTask/OutpostDefenseTask/ShopTask/CashShopTask/RaidTask/DailyTask all converged); the lobby's "entry" is not a click edge but the cold-start procedural flow itself.

### Transition edges: `transition()`

For any "click the entry -> confirm the target screen" edge, ALWAYS use `transition()` — do not hand-write `wait_click_feature(...) + assert_screen(...)` pairs:

```python
self.transition("tribe_tower", click_feature="ark_tribe_tower", wait_confirm=10, after_sleep=1)
self.transition("coop_page", box=coop_box, after_sleep=1)  # pass a pre-located box via box=
```

- Click source, pick one: `click_feature` (coco feature, via `wait_click_feature`), `box` (box/region via `click_box`), or `click` (custom callable).
- If the target screen is not reached within `wait_confirm` seconds after a click, the click is **retried in place**, up to `retry_click` times (default 2). On exhaustion it saves a failure screenshot and raises `WaitFailedException` carrying from/to context (caught by `try_step`).
- Click waiting and confirm waiting share the `time_out` total budget; for long-loading edges such as entering battle, enlarge `wait_confirm`/`time_out`.

**Not for**: battle-settlement edges with dedicated semantics (confirm/return clicks after `wait_battle_finish`) and loop-head re-confirmation asserts (keep `assert_screen` for those).

## Failure Recovery

```python
self.try_step(step_fn, name=None, retries=2, recover=True, raise_on_fail=True) -> bool
```

`try_step` wraps a sub-flow entry method that starts from the lobby; a `WaitFailedException` raised inside (including its subclass `InterruptedByDialogException`) triggers the recovery protocol:

1. `save_failure_screenshot(tag)` saves the failure frame to `screenshots/failure/`;
2. logs the failure;
3. `_recover_to_lobby()` recovers: refresh frame -> `dismiss_all_popups(clear_condition=is_screen("lobby"))` -> click `common_home` -> `wait_for_lobby()` to confirm the lobby;
4. retries up to `retries` times (3 attempts by default); gives up early if recovery fails; after exhaustion, raises or returns `False` per `raise_on_fail`.

Key `dismiss_all_popups` semantics: **each pass tries to close one popup FIRST; `clear_condition` is only checked on passes where nothing was closed** — under a dimming overlay, target-screen features may still match, and checking the condition first would falsely report "cleaned up". Read `clear_condition` as satisfied only when "condition holds AND no popup remained this pass".

`_recover_to_lobby` is a plain instance method; subclasses may override it to add extra recovery actions.

### Granularity: wrap entry methods, not individual internal steps

The right unit for `try_step` is the **entry method**: a sub-flow method that starts from the lobby and completes its whole navigation and operations by itself. Because failure triggers a lobby recovery before retrying, the wrapped step must be re-entrant from the lobby; wrapping internal steps individually would cause redundant recovery and lost context.

- Wrap each entry method **once** with `try_step` in `run()`.
- Do **not** wrap internal navigation/operation steps individually: any `WaitFailedException` bubbles up to the outer wrapper, which recovers to the lobby and re-runs the whole entry method.
- If a step only needs in-place retry (transient OCR/template jitter), use `recover=False` to retry without the lobby round-trip.

## Long Waits & the Interrupt Sentinel

- Use `wait_battle_finish(time_out=240, check_interval=3, settle_time=2)` for auto-battle completion (throttled polling, detect-only: victory is detected by OCR of the ESC text within `box_battle_finish_text`, with `battle_finish_statistics` inside `box_battle_finish_bottom_right` as fallback, then stabilized before returning; returns `("success", text_box)` with the clickable box always the `box_battle_finish_text` region, `("failed", back)` / `(None, None)`; follow-up actions are the caller's choice). Never busy-poll battle screens with `wait_feature`/`wait_ocr`.
- Interrupt sentinel: `wait_battle_finish` and RaidTask's 60s matchmaking wait check `INTERRUPTS["features"]` from `src/screens.py` before checking battle-settlement features on every poll; a hit raises `InterruptedByDialogException` (subclass of `WaitFailedException`, `try_step`-compatible). The list is currently empty = inactive, zero overhead.
- When you on-device encounter a disconnect/maintenance/login-expired dialog: annotate its feature into coco, add the feature name to `INTERRUPTS["features"]`, and add a case in `tests/TestBattleWait.py`.

## Popups & Transient Sub-Screens

- **Do NOT register friend/mailbox/notice modal popups as screens** — they are a separate "what is blocking me" axis, handled by `dismiss_all_popups`/`close_overlay`.
- **Do NOT register in-flow sequential sub-screens** (tower-card/stage select, team composition, quick-battle confirm) — they replace the parent screen instead of overlaying it, and the parent features vanish; flows proceed via features/coordinates. Note for failure recovery: these pages do not always have `common_home`.
- Before starting a flow, call `dismiss_all_popups` first, then detect screens; `_nav_*`-style entries keep the two-stage "refresh -> detect -> dismiss -> refresh -> detect again" pattern.
- Criterion feature geometry: prefer top-bar/bottom-bar/edge elements for criterion features; avoid putting ALL criterion features inside the typical modal-overlay region (approx. x in [400,2160], y in [200,1150], 2560x1440 baseline; empirical values pending on-device calibration with friend/mailbox popups). Applies to: screens registered from now on, and screens that will join global classification or recovery-phase detection; in-flow asserts executed right after navigation are exempt.

## Asset Resolution Baseline (2560x1440)

All template-related assets in this project use **2560x1440 as the single baseline resolution**. Agents must follow this when debugging, screenshotting, or annotating:

- **Debugging screenshots**: screenshots for reproducing issues, debugging OCR, or analyzing failures should be captured from a 2560x1440 window. Low-resolution shots (e.g. 1280x720) carry less detail, so debugging templates/OCR against them in a 1440p environment yields results that diverge from the real environment (scaling, thresholds, OCR misreads all shift).
- **coco annotations**: annotate boxes on 2560x1440 screenshots (`assets/coco_annotations.json`). `FeatureSet` auto-scales annotations to the current game resolution; the lower the source resolution, the blurrier the upscaled template and the more likely matching fails.
- **Manually cropped templates**: small templates under `assets/template/` must be cropped from 2560x1440 screenshots, then passed to `find_scaled_template` (defaults `ref_width=2560, ref_height=1440`). 1440p is the ceiling of all supported resolutions (1920x1080/1600x900/1280x720); starting from it only downscales, never upscales.

Exception: if only a non-1440p screenshot is available, it technically still works (coco scales by the source image's own dimensions; `find_scaled_template` accepts `ref_width`/`ref_height` overrides), but the asset's original resolution must be remembered and declared explicitly — never treat it as the default baseline.

## Usage Example

```python
# Wrap each entry method (sub-flow) once; never wrap internal steps individually.
if not self.try_step(self._collect_friend, name="收获友情点", raise_on_fail=False):
    self.log_warning("友情点收取失败，跳过。")

# New screens go into SCREENS in src/screens.py:
#   "my_page": {"features": ["my_page_mark"]},
# Navigation edges use transition():
self.transition("my_page", click_feature="my_entry", wait_confirm=10, after_sleep=1)

# Skip-navigation-if-already-there entry pattern:
if not self.is_screen("my_page"):
    self.wait_for_lobby()
    self.dismiss_all_popups(wait_for_popup=False, time_out=10)
    self.transition("my_page", click_feature="my_entry")
```

## Constraints (agents must follow)

- Register global screens in `src/screens.py` (`SCREENS`); use `register_screen` only for task-private screens; `lobby` is already registered by the base class — do not re-register it.
- Screen registration is **optional**: register only when you genuinely need to detect/wait for that screen (`is_screen`/`wait_screen`/`assert_screen`, as a recovery target, or for classification). Transient overlays (friend/mailbox) and click-only tasks need no extra registration.
- spec field semantics follow the table above: `absent`/`any_features`/`feature_box`/`priority`/`min_frames` default to legacy behavior; never repurpose them.
- "Click entry -> confirm target screen" edges ALWAYS use `transition()` — exceptions limited to battle-settlement edges and in-loop re-confirmation asserts. Sub-flow idempotent entry gates use `ensure_screen()`; never hand-roll the "is_screen shortcut + wait-for-lobby + find entry + click entry" sequence.
- `try_step` granularity is the **entry method**: wrap each lobby-starting self-contained sub-flow **once** in `run()`; never hand-roll ad-hoc retry/recovery logic.
- Never bypass `_recover_to_lobby` with hard-coded "click home by coordinates" recovery.
- Failure screenshots are always written by `save_failure_screenshot` to `screenshots/failure/`; `transition` and the sentinel already call it internally — business code must not save elsewhere.
- Prefer coco template features for screen detection; use OCR keywords only when no stable template exists, bounded by `ocr_box`.
- `close_overlay` defaults to `require_click=True`: an explicit call must close (click) at least one overlay and raises `WaitFailedException` on timeout. Fault-tolerant callers such as recovery flows must pass `require_click=False` so a missing overlay does not block recovery.
- Criterion feature geometry: for newly registered screens prefer top-bar/bottom-bar/edge elements; do not put all criterion bboxes inside the modal-overlay region (x in [400,2160], y in [200,1150], 2560x1440 baseline, empirical values pending on-device calibration). screens asserted right after in-flow navigation are exempt; when a criterion sits in the overlay region, list the occluder alongside it via `any_features` (e.g. `simulation_mark` + the simulation-room overclock update popup).
- Asset resolution baseline: debugging screenshots, coco annotations, and cropped templates all use 2560x1440 (see above); never debug or annotate against low-resolution shots.
- Interrupt dialog upkeep: on-device encounter (disconnect/maintenance/expired login) -> annotate into coco -> add to `INTERRUPTS["features"]` -> add a `tests/TestBattleWait.py` case.
- When changing the recovery protocol or detection semantics, update `tests/TestScreenRecovery.py`; new concerns (cache, registry integrity, ...) get their own test file.

## Tests

- `tests/TestScreenRecovery.py`: all `_screen_match` branches, `absent`/`any_features`/`priority`/`min_frames`, `transition()`, `try_step`, `dismiss_all_popups`, `_recover_to_lobby`.
- `tests/TestFrameCache.py`: per-frame dedup and frame-change invalidation (including the `set_image` path).
- `tests/TestScreenRegistryIntegrity.py`: static check that every feature referenced by `SCREENS` exists in `assets/coco_annotations.json` (CI blocks coco drift).
- `tests/TestBattleWait.py`: battle polling and interrupt-sentinel fast-fail.
- Full verification MUST run one test file per process (e.g. `run_tests.ps1`); never run multiple test files in one command (the ok singleton cannot be rebuilt in-process and produces false failures).
