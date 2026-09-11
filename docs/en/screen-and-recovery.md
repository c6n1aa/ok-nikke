# Screen Recognition & Failure Recovery

The unified constraint for task development: `NikkeBaseTask` (`src/tasks/NikkeBaseTask.py`) provides the three-layer skeleton "screen recognition + guarded navigation + failure recovery", all built on ok-script APIs. Detection data is centralized in `src/screens.py` (single source of truth); mechanics live in `NikkeBaseTask` (implementation split by responsibility into mixins under `src/tasks/base/`; the base class only composes them). The frame-level detection cache is transparent to callers: results are bit-identical to uncached detection.

## Screen Recognition

### Registering screens

Global screens are registered centrally in `src/screens.py` under `SCREENS` (auto-loaded by `NikkeBaseTask.__init__`, including the lobby; do not re-register). **New screens always go into `SCREENS` first** (appended at the end); `register_screen(name, features=(), keywords=(), ocr_box=None, **extra)` is reserved for the rare task-private screens (same name overrides the global entry).

Registration is **optional**: register only when you need to detect/wait for the screen (`is_screen`/`wait_screen`/`assert_screen`, or as a recovery target); transient overlays such as friends/mailbox and click-only simple tasks need no registration.

spec fields (defaults = current behavior; do not implement semantics that differ from the table):

| Field | Default | Semantics |
|---|---|---|
| `features` | `()` | coco template feature names; ALL must match (AND). Prefer these — cheaper and more stable than OCR; use OCR keywords only for pages without a stable template |
| `any_features` | `()` | Any-hit feature names; a single match counts as the feature check passing (OR); when combined with `keywords`, the AND rule applies on top. For icon-any-of "OR" semantics |
| `feature_box` | `None` | Optional match region (a coco region feature name, resolved to the current resolution), applies only to `any_features`; missing region falls back to full-screen matching |
| `keywords` | `()` | OCR keyword list; ANY hit matches (OR). Prefer bounding with `ocr_box` |
| `ocr_box` | `None` | OCR region: relative `[x, y, to_x, to_y]` or a coco region feature name; missing region falls back to full-screen OCR |
| `absent` | `[]` | Disambiguation features; any match fails the screen outright (for adjacent screens with overlapping feature subsets) |
| `priority` | `0` | Only affects `current_screen()` iteration order: descending priority, ties keep registration order |
| `min_frames` | `1` | Only applies to `wait_screen`/`assert_screen` polling: N consecutive poll hits required; `is_screen` stays single-frame |

### Detection API

| Method | Description |
| --- | --- |
| `current_screen()` | Detects the current screen on this frame, iterating in descending `priority`; returns the first match or `None` (useful for failure logs) |
| `is_screen(name)` | Single-frame check for the given screen |
| `wait_screen(name, time_out=10, raise_if_not_found=False)` | Waits until the screen is reached; `min_frames` consecutive-hit semantics apply here |
| `assert_screen(name, time_out=10)` | Asserts the screen, raising `WaitFailedException` on timeout (pairs with `try_step`) |

## Navigation

### Entry gate: `ensure_screen()`

At the start of a sub-flow, "make sure I'm on screen X" is always `ensure_screen()`, never the hand-written "`is_screen` shortcut + wait-for-lobby + find entry + click entry + assert" sequence:

```python
self.ensure_screen("ark", click_feature="ark", wait_confirm=10, after_sleep=1)

# When a missing entry means "nothing to do this cycle" (e.g. limited-time modes),
# provide an entry resolver (called only after the lobby is reached):
def find_entry():
    box = self._find_panel_entry("coop", panel)
    if box is None:
        self.log_info("未找到协同作战入口，视为已完成。")
    return box
if not self.ensure_screen("coop_page", entry=find_entry, wait_confirm=10, after_sleep=1):
    return  # missing entry returns False; the caller marks done
```

Behavior: already on / currently transitioning into the target -> return immediately (polls `wait_enter=5` per round, tolerating slide-in animations) -> dismiss popups and poll once more -> route: a positive `login_page` match or zero in-app evidence -> cold-start `wait_until_lobby_after_start`; in-app evidence -> `_recover_to_lobby` -> dismiss lobby popups -> with a click source, guarded `transition()` entry; without a click source (target is the lobby) -> tail `wait_screen` confirmation. Defaults to `raise_on_fail=True` (for `try_step` recovery); pass `raise_on_fail=False` at task starts for a graceful abort.

Task-start lobby-siting is uniformly `ensure_screen("lobby")` (the lobby's "entry" is the cold-start procedural flow, not a click edge). The positive cold-start anchor `login_page` (TOUCH TO CONTINUE + `box_enter_game` region) is registered in `src/screens.py`.

### Transition edges: `transition()`

For any "click the entry -> confirm the target screen" edge, always use `transition()`, not the hand-written `wait_click_feature(...) + assert_screen(...)` pair:

```python
self.transition("tribe_tower", click_feature="ark_tribe_tower", wait_confirm=10, after_sleep=1)
self.transition("coop_page", box=coop_box, after_sleep=1)  # pass a pre-located box via box=
```

- Click source, pick one: `click_feature` (coco feature), `box` (box/region name), `click` (custom callable).
- If the target screen is not reached within `wait_confirm` seconds, the click is **retried in place**, up to `retry_click` times (default 2); on exhaustion it saves a failure screenshot and raises `WaitFailedException` carrying from/to context. Click waiting and confirm waiting share the `time_out` total budget; for long-loading edges such as entering battle, enlarge `wait_confirm`/`time_out`.

**Edges where it does not apply**:

- Dedicated battle-settlement edges (confirm/return clicks after `wait_battle_finish`);
- Loop-head re-confirmation asserts (keep `assert_screen` for those);
- Off-season entries whose entry is visible but closed (e.g. arena after the season ends): the target screen never appears after the click, so `transition` would falsely fail and trigger recovery. Instead, after the click, race "target screen vs closed-state signal" with `wait_until`; hitting the closed signal means nothing to do this cycle, and the task wraps up as "treated as done". See `ArkTask._click_entry_race_closed` / `_hit_season_end_banner`: the closed state uses a `re.Pattern` partial match (the framework compares plain strings for exact equality, and OCR text often carries trailing punctuation), with the region limited to the mid-screen banner band; racing a transient signal (the banner lasts ~0.3–0.5 s, faster than the framework's default 1 s settle window) must pass `settle_time=0`, otherwise "every frame matches but it never returns" until timeout, misreading failure as success. Transient toast detection (e.g. the insufficient-funds toast in `ShopTask._buy_cell`) works the same way.

### Backing out level by level: `_back_through_screens()`

`_back_through_screens(*screens)` clicks `common_back` then asserts the reached screen for each level, walking back one level at a time (e.g. for "sub-page -> arena -> ark" pass `("arena", "ark")`). Use it for multi-level returns instead of hand-writing repeated "click common_back + assert" pairs.

## Failure Recovery

```python
self.try_step(step_fn, name=None, retries=2, recover=True, raise_on_fail=True) -> bool
```

Wraps a sub-flow entry method that starts from the lobby; a `WaitFailedException` raised inside (including its subclass `InterruptedByDialogException`) triggers the recovery protocol:

1. `save_failure_screenshot(tag)` saves the scene to `screenshots/failure/` (all failure screenshots go through it; `transition` and the sentinel call it internally — business code does not save elsewhere);
2. logs the failure;
3. `_recover_to_lobby()`: refresh frame -> `dismiss_all_popups(clear_condition=is_screen("lobby"))` -> click `common_home` back to the lobby -> `wait_for_lobby()` to confirm. It is a plain instance method; subtasks may override it to add recovery actions; never bypass it with hard-coded "click home by coordinates";
4. bounded retries (3 attempts in total by default); gives up early if recovery fails; after exhaustion, raises or returns `False` per `raise_on_fail`.

Key `dismiss_all_popups` semantics: **each pass tries to close one popup first; `clear_condition` is only checked on a pass where nothing could be closed** — under a dimming overlay the target screen's features may still match, and checking the condition first would falsely report "cleaned up".

### Granularity: wrap the entry method, one layer

The correct unit is the **entry method**: a sub-flow that starts from the lobby and completes its whole navigation and operations by itself. On failure it must recover to the lobby and re-run, so the wrapped step must be re-entrant from the lobby; internal steps depend on the entry method's navigation chain, and wrapping them individually only adds redundant recovery and lost context.

- Wrap each entry method **once** in `run()`; internal steps are **not** wrapped individually — any `WaitFailedException` bubbles up to the outer layer, and after returning to the lobby the whole entry method re-runs from the start.
- For steps that only need in-place retry (transient OCR/template jitter), use `recover=False` to retry without recovering to the lobby.
- Hand-written ad-hoc retry/recovery logic is forbidden.

## Long Waits & the Interrupt Sentinel

- For auto-battle completion, use `wait_battle_finish(time_out=240, check_interval=3, settle_time=2)`: throttled polling, detect-only; victory is detected by OCR of the ESC text within the `box_battle_finish_text` region, with `battle_finish_statistics` inside `box_battle_finish_bottom_right` as fallback; once stable it returns `("success", text_box)` (the clickable box is uniformly the `box_battle_finish_text` region) / `("failed", back)` / `(None, None)`, and follow-up actions belong to the caller. Never busy-poll long battle waits with `wait_feature`/`wait_ocr`.
- Interrupt sentinel: on every poll `wait_battle_finish` first checks `INTERRUPTS["features"]` from `src/screens.py`; a hit raises `InterruptedByDialogException` (subclass of `WaitFailedException`, `try_step`-compatible). An empty list = inactive, zero overhead.
- When you encounter a disconnect/maintenance/login-expired dialog on device: annotate it into coco -> add the feature name to `INTERRUPTS["features"]` -> add a case in `tests/TestBattleWait.py`.

## Popups & Transient Sub-Screens

- **Do NOT register modal popups such as friends/mailbox/notices/login rewards as screens** — they are a separate "what is blocking me" axis, handled by `dismiss_all_popups`/`close_overlay`.
- **Hook new popups only into `_try_close_one_popup`** (add `_close_xxx_popup` to `PopupsMixin` in `src/tasks/base/_popups.py`; each call advances one step, multi-step popups progress pass by pass via `dismiss_all_popups`): one hook covers cold start, recovery, and every sub-flow cleanup entry. Order by occlusion level, top layer first (rupee -> notice -> overlay -> login-reward panel); otherwise the lower layer's close button is clicked while the upper overlay is still up.
- **Close modal popups uniformly via `close_popup_by_blank(verify)`**: click the blank area outside the panel (default `_MODAL_BLANK_CLOSE_X/_Y`) plus a `verify` predicate — a "popup is closed" criterion that does not vary with panel skins (e.g. a screen feature disappearing, a criterion text disappearing); it re-clicks automatically when closing is not confirmed. Panel skins change per period and the close button's look/position drifts with them, so template matching needs per-period upkeep; the area outside the panel is always covered by the modal overlay, so clicking blank is equivalent to clicking the overlay and immune to skins. `ExtrasTask` closing the PASS modal and `_close_daily_login_popup` closing the login-reward panel both use it.
- **For popups whose skins change, only pick criteria that do not**: login rewards differ in style per period and the criterion only reads the "Claim All" text (OCR); claimable state is judged by the button background color — OCR only boxes the white text, so `is_feature_enabled` runs after expanding the box by `_DAILY_LOGIN_CLAIM_PAD`.
- **Do NOT register in-flow sequential sub-screens (tower-card/stage select, team composition) as screens** — they replace the parent screen, the parent features vanish, and the flow proceeds via features/coordinates; note these pages do not always have `common_home`.
- Before entering a flow, call `dismiss_all_popups` first, then detect screens; `_nav_*`-style entries keep the two-stage "refresh frame -> detect -> dismiss popups -> refresh -> detect again" pattern.
- `close_overlay` defaults to `require_click=True`: it must successfully click and close at least one overlay and raises `WaitFailedException` if none was clicked within the timeout; fault-tolerant flows such as recovery must pass `require_click=False`.
- Criterion feature geometry: prefer **top-bar/bottom-bar/edge** elements for criteria; avoid putting all criteria inside the typical modal-overlay region (x∈[400,2160], y∈[200,1150], 2560×1440 baseline; empirical values pending on-device calibration with friend/mailbox popups). Applies to newly registered screens and screens participating in global classification/recovery detection; screens asserted right after in-flow navigation are exempt. When a criterion falls inside the overlay region, list the occluder alongside via `any_features` (`simulation_mark` and the simulation-room overclock-update popup do exactly this).

## Asset Resolution Baseline (2560x1440)

All template assets use **2560x1440 as the single baseline**: debug screenshots are captured from a 1440p window (debugging templates/OCR against low-resolution shots yields conclusions that diverge from the real environment due to scaling, thresholds, and misread offsets); coco annotations are drawn on 2560x1440 screenshots; small templates under `assets/template/` are cropped from 2560x1440 screenshots (`find_scaled_template` defaults to `ref_width=2560, ref_height=1440`). 1440p is the ceiling of all supported resolutions (1920x1080/1600x900/1280x720) — matching only ever downscales, never upscales, and is the most stable.

Exception: non-1440p assets technically work (coco scales by the source image's own dimensions; `find_scaled_template` accepts `ref_width`/`ref_height`), but the asset's original resolution must be remembered and declared explicitly.

## Tests

- `tests/TestScreenRecovery.py`: screen-detection branches, `absent`/`any_features`/`priority`/`min_frames`, `transition()`, `try_step`, `dismiss_all_popups`, `_recover_to_lobby`. Update it when changing the recovery protocol or detection semantics; new concerns (cache, registry integrity, ...) get their own test file.
- `tests/TestFrameCache.py`: per-frame cache dedup and frame-change invalidation (including the `set_image` path).
- `tests/TestScreenRegistryIntegrity.py`: static check that every feature referenced by `SCREENS` exists in `assets/coco_annotations.json` (CI blocks coco drift).
- `tests/TestBattleWait.py`: battle polling and interrupt-sentinel fast-fail.
- Full verification MUST run one test file per process (`run_tests.ps1`); never run multiple test files in one command (the ok singleton cannot be rebuilt in-process and produces false failures).
