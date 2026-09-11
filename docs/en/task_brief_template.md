# Task Brief: <task name> (onetime / trigger)

Generate this task following the ok-script-tasks / ok-script-codegen skills and AGENTS.md conventions.
(Convention rules, code style, and testing all follow the skills and AGENTS.md; this file only contains task-specific info.)

## Basic Info

- **Class/file**: `src/tasks/<TaskName>.py` (PascalCase)
- **Description** (Chinese, shown in GUI): one sentence describing what the task does
- **done_keys**: none, or `{"key": "day|week|month"}` (pure orchestrator/debug tasks omit this)
- **Configs**: one per line: `key / default / type(bool|drop_down|line_edit...) / Chinese help text`; write "none" if empty; indented lines are child configs
- **Trigger**: onetime or trigger (for trigger, state the trigger_interval)

## Screens & Features

(Screens go into `SCREENS` in `src/screens.py` first; only task-private screens use `register_screen`. One per line; reference screens as `[screen_name]` in the flow.)

- `<screen_name>(<Chinese name>)` = detection: `features` (coco features, all must match) / `keywords` (OCR keywords, any match, with `ocr_box` to bound the region)
- Special small templates: `assets/template/xxx.png` (matched via `find_scaled_template` at runtime)

## Flow

(Starts from the lobby; an indented tree expressing sequence/loops/branches; click targets and
detection conditions on the same line.)

**Shorthand glossary** — the following tokens may be used directly in flow trees; the AI
implements them per the right-hand column:

| Shorthand | Standard implementation |
|---|---|
| `go to [screen]: click <entry>` | `transition("<screen>", click_feature="<entry>")`; click entry → confirm target screen (unified navigation edge) |
| `gate [screen]` | `ensure_screen("<screen>")`; idempotent siting at sub-flow start (incl. cold start / recovery routing) |
| `click <feature>` | `wait_click_feature("<feature>")`; single click that is not a navigation edge |
| `back` / `go back one level` | `common_back`, the coco generic back-button feature; clicking it goes one level back |
| `wait [screen]` | `wait_screen("<screen_name>")`; the screen must be defined under "Screens & Features" |
| `OCR <region> contains/lacks "<keyword>"` | keyword detection via OCR bounded by that region (`ocr_box`) |
| `battle wait` | base helper `wait_battle_finish(...)`; detect-only, follow-up actions written in the tree |
| `mark_done("<key>")` | base-class completion marking; the key must appear in done_keys under "Basic Info" |
| `<region> y+0.1 click` | click with a relative y offset on top of that box |
| `check <region> enabled` | `is_feature_enabled("<box>")`, whether the UI element is enabled (highlighted in color) |
| `dismiss popups` | `dismiss_all_popups(...)`; clear notice/overlay popups (`wait_for_popup=False` when none expected) |
| `box [region]` | `get_box_by_name("box_xxx")`; a `box_`-prefixed pure coordinate region (already scaled by resolution) |
| `wait until <condition> holds/gone` | `wait_until(lambda: <condition>, time_out=…)`; button enabled/disabled state flip |
| `red dot [region]` | `find_red_dot("box_xxx")`; badge-region red-dot detection for claimable content |
| `gray-find <feature> in [region]` | `find_one("<feature>", box=<region>, use_gray_scale=True)`; grayscale matching inside a panel |

Rules: only use tokens defined in this glossary or AGENTS.md; each lobby-starting, self-contained
sub-flow entry method is wrapped with `try_step` **once** in code (internal steps are not wrapped
individually). Self-invented fragment names (e.g. "battle segment") must be defined once under
"Shared fragments" or inline in this section. If unsure how to abbreviate a step, write it out in
plain language — do not invent new symbols.

**Single-flow task**: write one tree (skeleton below).
**Multi-sub-flow task**: the main flow only lists the dispatch order; each sub-flow gets its own
section and starts from the lobby (matching the try_step-wrapped entry methods in code); segments
repeated across sub-flows are defined once as named "shared fragments" referenced by name.
Incremental writing works well: write sub-flow 1 first, generate & verify, then append the rest.

```
### Main flow
1. Sub-flow: <nameA> (see below) → mark_done("<keyA>")
2. Sub-flow: <nameB> (see below)
3. Wrap-up: summary / notifications

### Shared fragments
- <fragment>: <steps…> (referenced by name from sub-flow trees)

### Sub-flow: <nameA>
1. Lobby → …
2. Loop …:
   - <condition>? no → next iteration
   - yes → click… → <fragment> → back path
3. Return → mark_done("<keyA>")
```

Or single flow:

```
1. Lobby → go to [ScreenA]: click <entry feature>
2. Loop <feature or region list>:
   - <condition>? no → next iteration
   - yes → click… → wait [ScreenB] → click…
     - branch condition 1 → action…
     - branch condition 2 → action… (including failure bypass: record state / notify user)
3. Finish → back path → mark_done("<key>") then end
```

### Alternative branches (optional)

(When some config is enabled, which flow segment it replaces and how it runs. Delete this section if unused.)

## Failures & Exceptions

(Which steps may be skipped and continue, which must abort; records that must be kept and summarized to notify the user at the end. Write "none" if empty.)

## Background Knowledge

(Only when the AI cannot infer it from common game knowledge: tower/stage names, special mechanics, etc. Delete this section if unused.)

## Output

src/tasks/<TaskName>.py + register in src/config.py (onetime_tasks or trigger_tasks) + tests/Test<TaskName>.py
(covering main branches: success/skip/failure/already-done skip), run tests and report results.
