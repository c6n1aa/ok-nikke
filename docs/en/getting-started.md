# Quick Start

## Download and Run

1. Download `ok-nikke-win32-portable.zip` from [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) and extract it to an English path.
2. Run `ok-nikke.exe` as administrator (the entry shim requests elevation itself; accept the UAC prompt).
3. Start the game.
4. Open the "Daily settings" view and toggle or configure the tasks to run.

    ![Daily settings view](../images/daily_config.png)

5. Return to the "Tasks" view and click "Daily" to start.

    ![Tasks view](../images/task.png)

## Usage Notes

- Each subtask under the "Tasks" view can be run individually and once; changing a task's settings under the "Tasks" view syncs them into the daily settings.
- **Global server** users can set the launcher path via the settings view and afterwards start the game directly from inside the app.
- **Administrator privileges are required**: if the game runs as administrator, the automation app needs the same privilege level, otherwise capture or input may not work.
- The game must run at a 16:9 resolution of at least 1600×900.
- Keep the game window in the foreground: input is simulated via Windows interfaces (Pynput / PyDirect), background clicking is not supported; screenshots prefer WGC.
- Task switches and settings are all selected in the main window; the app tracks daily/weekly completion and skips already finished tasks.

## In-App Updates

Under "About → App update" you can check for updates and switch the update source (Auto / GitHub / CNB mirror):

- The factory default is "Auto": Chinese systems use the CNB mirror, other systems use GitHub.
- Updating pulls the code, reinstalls dependencies when needed and restarts the app; **a console window shows the progress** (fetch / dependencies / failure reason), the log is `logs/update.log`, and the failure reason is also shown in "About → App update".

## Common Issues

- **Black screenshots or no recognition**: make sure the app and the game run at the same privilege level (both non-admin or both admin), and turn off HDR or allow the AutoHDR prompt.
- **Resolution mismatch**: make sure the game window is 16:9 and at least 1600×900.
- **App won't start after an update**: delete the `configs/` folder and restart (this resets task settings); if it still fails, re-download the portable package from Releases.
