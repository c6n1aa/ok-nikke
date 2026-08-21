# Task Brief: <task name> (onetime / trigger)

Generate this task following the ok-script-tasks / ok-script-codegen skills and AGENTS.md conventions.
(Convention rules, code style, and testing all follow the skills and AGENTS.md; this file only contains task-specific info.)

## Basic Info

- **Class/file**: `src/tasks/<TaskName>.py` (PascalCase)
- **Description** (Chinese, shown in GUI): one sentence describing what the task does
- **done_keys**: none, or `{"key": "day|week|month"}` (pure orchestrator tasks omit this)
- **Configs**: one per line: `key / default / type(bool|drop_down|line_edit...) / Chinese help text`; write "none" if empty
- **Trigger**: onetime or trigger (for trigger, state the trigger_interval)

## Screens & Features

(One per line; reference screens as `[screen_name]` in the flow. Only list what this task uses.)

- `<screen_name>(<Chinese name>)` = detection: coco feature names / box_ region OCR "keyword" combos
- Special small templates: `assets/template/xxx.png` (must be matched via find_scaled_template at runtime)

## Flow

(Starts from the lobby; an indented tree expressing sequence/loops/branches; click targets and
detection conditions on the same line.)

**Shorthand glossary** — the following tokens may be used directly in flow trees; the AI
implements them per the right-hand column:

| Shorthand | Standard implementation |
|---|---|
| `click <feature>` | `wait_click_feature("<feature>")`; feature must be a coco-annotated name or a small template declared in "Screens & Features" |
| `common_back` | coco generic back-button feature; clicking it goes one level back |
| `wait [screen]` | `wait_screen("<screen_name>")`; screen must be defined in "Screens & Features" |
| `OCR <region> contains/lacks "<keyword>"` | keyword detection via OCR bounded by that region (`ocr_box`) |
| `battle wait` | base helper `wait_battle_finish(...)`; detect-only, follow-up actions written in the tree |
| `mark_done("<key>")` | base-class completion marking; key must appear in done_keys under "Basic Info" |
| `<region> y+0.1 click` | click with a relative y offset on top of that box |

Rules: only use tokens defined in this glossary or AGENTS.md; self-invented fragment names
(e.g. "battle segment") must be defined once in "Shared fragments" or inline in this section.
If unsure how to abbreviate a step, write it out in plain language — do not invent new symbols.

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
1. Lobby → click <entry feature> → [ScreenA]
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

src/tasks/<TaskName>.py + register in src/config.py + tests/Test<TaskName>.py
(covering main branches: success/skip/failure/already-done skip), run tests and report results.
