# Quick Start

## Download and Run

1. Download `ok-nikke-win32-portable.zip` from [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) and extract it to an English path.
2. Run `ok-nikke.exe` as administrator (the entry shim requests elevation itself; accept the UAC prompt).

## Usage Notes

- Each subtask under the "Tasks" view can be run individually and once; changing a task's settings under the "Tasks" view syncs them into the daily settings.
- **Global server** users can set the launcher path via the settings view and afterwards start the game directly from inside the app.
- **Administrator privileges are required**: if the game runs as administrator, the automation app needs the same privilege level, otherwise capture or input may not work.
- The game must run at a 16:9 resolution of at least 1600×900.
- Keep the game window in the foreground: input is simulated via Windows interfaces (Pynput / PyDirect), background clicking is not supported; screenshots prefer WGC.
- Task switches and settings are all selected in the main window; the app tracks daily/weekly completion and skips already finished tasks.

## In-App Updates

Under "About → App update" you can check for updates, switch the update source (Auto / GitHub / CNB mirror) and upgrade or downgrade among the five most recent stable versions:

- The factory default is "Auto": Chinese systems use the CNB mirror, other systems use GitHub.
- "Check for updates" only offers stable releases: prereleases (alpha/beta) never raise the badge - download them manually from the Release page.
- The version dropdown lists the five most recent stable tags (excluding the current one; selecting an older tag turns the button into "Downgrade").
- The automatic check runs about 3 seconds after startup; a new version shows an in-app notice (InfoBar) and the "About" item gets a red dot.
- Updating pulls the code, reinstalls dependencies when needed and restarts the app; **a console window shows the progress** (fetch / dependencies / failure reason), the log is `logs/update.log`, and the failure reason is also shown in "About → App update".
- The update source is stored in `configs/update.json`, shared with the main program.

## Common Issues

- **Black screenshots or no recognition**: make sure the app and the game run at the same privilege level (both non-admin or both admin), and turn off HDR or allow the AutoHDR prompt.
- **Resolution mismatch**: make sure the game window is 16:9 and at least 1600×900.
- **App won't start after an update**: delete the `configs/` folder and restart (this resets task settings); if it still fails, re-download the portable package from Releases.
