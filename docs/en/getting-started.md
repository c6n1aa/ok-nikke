# Quick Start

## Download and Run

1. Download `ok-nikke-win32-portable.zip` from [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) and extract it to an English path.
2. Run `ok-nikke.exe` (administrator privileges are required; it elevates automatically, so accept the UAC prompt).
3. Start the game.
4. Open the "Daily settings" view and toggle or configure the tasks to run.

    ![Daily settings view](../images/daily_config.png)

5. Return to the "Tasks" view and click "Daily" to start.

    ![Tasks view](../images/task.png)

## Usage Notes

- Each subtask under the "Tasks" view can be run individually and once; changing a task's settings under the "Tasks" view syncs them into the daily settings.
- **Global server** users can set the launcher path via the settings view and afterwards start the game directly from inside the app.
- The game must run at a 16:9 resolution of at least 1600×900.
- Input method: `SyntheticTouch` uses a synthetic touch pointer (WM_POINTER) to bypass the game's input filtering and requires the game window in the foreground.
- While a task runs, if the game window loses focus or is not in the foreground the app pauses automatically and resumes when the game window comes back, so clicks are not lost.
- Task switches and settings are all selected in the main window; the app tracks daily/weekly completion and skips already finished tasks.

## In-App Updates

Under "About → App update" you can check for updates and switch the update source (Auto / GitHub / CNB mirror) and the dependency index (Auto / official PyPI / Tsinghua mirror):

- The update source defaults to "Auto": Chinese systems use the CNB mirror, other systems use GitHub.
- The index defaults to "Auto": Chinese systems use the Tsinghua mirror, others use official PyPI.
- Updating pulls the code, reinstalls dependencies when needed and restarts the app; **a console window shows the progress** (fetch / dependencies / failure reason), the log is `logs/update.log`, and the failure reason is also shown in "About → App update".

## Common Issues

- **Black screenshots or no recognition**: make sure the game also runs as administrator (the app elevates itself), and turn off HDR or allow the AutoHDR prompt.
- **Game picture disturbed by overlays**: close other software that adds overlay layers to the game (e.g. MSI Afterburner, GamePP).
- **Resolution mismatch**: make sure the game window is 16:9 and at least 1600×900.
- **App won't start after an update**: delete the `configs/` folder and restart (this resets task settings); if it still fails, re-download the portable package from Releases.
