# Quick Start

For end users: download the portable package, run it, and troubleshoot. To work on the project, see [Development setup](development.md).

## Download and Run

1. Download the latest `ok-nikke-win32-portable.zip` from [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) and extract it anywhere.
2. Rename `pyappify-cn.yml` (China) or `pyappify-global.yml` (global) in the package root to `pyappify.yml` (next to `ok-nikke.exe`) according to your network, to be used as the update source config.
3. Run `ok-nikke.exe` as administrator.

## Requirements

- **Administrator privileges are required**: if the game runs as administrator, the automation app needs the same privilege level, otherwise capture or input may not work.
- The game must run at a 16:9 resolution of at least 1600×900.
- Keep the game window in the foreground: input is simulated via Windows interfaces (Pynput / PyDirect), background clicking is not supported; screenshots prefer WGC.
- Task switches and settings are all selected in the main window; the app tracks daily/weekly completion and skips already finished tasks.

## In-App Updates

The launcher checks and applies updates by git tag automatically; no manual re-download is needed. The update source is decided by `pyappify.yml` in the package root.

## Common Issues

- **Black screenshots or no recognition**: make sure the app and the game run at the same privilege level (both non-admin or both admin), and turn off HDR or allow the AutoHDR prompt.
- **Resolution mismatch**: make sure the game window is 16:9 and at least 1600×900.
- **App won't start after an update**: delete the `configs/` folder and restart (this resets task settings); if it still fails, re-download the portable package from Releases.
