# App Configuration

For developers. App configuration lives in `src/config.py` and takes effect before `ok.OK(config)`. End users choose task switches and settings in the app's main window; no code changes are needed.

## App Info

| Key | Description |
| --- | --- |
| `gui_title` | Window title, currently `ok-nikke` |
| `gui_icon` | Window icon path; replacing `icons/icon.png` (and `icons/icon.ico`) while keeping the filename avoids config changes |
| `gui` | `type` fixed to `'qt'` (this project does not use the Web UI) + `window_size` window/minimum size |
| `supported_resolution` | Supported ratio (16:9), minimum resolution (1600×900), and `resize_to` targets for non-16:9 |
| `links` | Project home, share text, and feedback links shown on the "About" page |
| `version` | Rewritten by the packaging workflow automatically; keep `"dev"` in source |
| `screenshots_folder` | Screenshot output folder, cleared on every start |

## Runtime Target

This project **only enables the native Windows target** (the Windows client of Goddess of Victory: NIKKE). The `adb` (emulator/Android) and `browser` targets are kept as comments in `src/config.py` and not enabled: enabling the browser target requires installing `playwright` extra and re-locking dependencies from `pyproject.toml`.

The `windows` section:

| Key | Current value | Description |
| --- | --- | --- |
| `exe` | `['nikke.exe']` | Game process name; the launcher starts or matches the window by it |
| `interaction` | `['Pynput', 'PyDirect']` | Input methods and priority |
| `capture_method` | `['WGC', 'BitBlt_RenderFull', 'BitBlt']` | Capture methods and priority; WGC first to support background capture |
| `require_bg` | `True` | Require background capture capability |
| `check_hdr` / `force_no_hdr` | `False` | Prompt for / forbid running with AutoHDR |
| `start_timeout` | `120` | Launcher timeout waiting for the game to be ready |

## Recognition

- `ocr`: uses `onnxocr` with `use_openvino` enabled.
- `template_matching`: points to `coco_feature_json` (`assets/coco_annotations.json`) plus default threshold/offset. Asset conventions are described in [Screen recognition & failure recovery](screen-and-recovery.md).

## Tasks and UI

- `onetime_tasks`: one-shot tasks started by the user, one entry per task class in `src/tasks/`.
- `trigger_tasks`: background periodic tasks, currently empty.
- `custom_tabs`: custom tabs; currently `DailyTab` from `src/ui/DailyTab.py` is registered.
- `custom_tasks`: disabled; release builds do not show the "Scripts"/"Templates" tabs.

Register new or modified tasks here; see [Task development](tasks.md).

## Framework Patches

`src/config.py` calls `src/patches.apply_all()` at the top, applying all ok-script monkey patches (launcher, runtime, task list, etc.) before `ok.OK(config)` is constructed.

- Extend or fix framework behavior only in `src/patches/`, registered in `apply_all()`; each patch's responsibility is documented in `src/patches/README.md`.
- Do not monkey-patch `ok.*` directly from tasks or other modules.

## Dependencies and Update Source

- The dependency source is `pyproject.toml`: `pip-compile pyproject.toml -o requirements.txt`, then delete the generated `pyside6`/`pyside6-addons` entries (only `pyside6-essentials` is installed).
- The update repository URL is `git_url` in `pyappify.yml`; the portable package ships `pyappify-cn.yml` / `pyappify-global.yml` for users to pick an update source. See [Packaging and release](release.md).
