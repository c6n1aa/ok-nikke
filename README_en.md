<div align="center">
  <h1 align="center">
    <img src="icons/icon.png" width="120" alt="ok-nikke logo"/>
    <br/>
    ok-nikke
  </h1>

  <p>
    一个基于图像识别的《胜利女神：NIKKE》自动化程序，基于 <a href="https://ok-script.com">ok-script</a> 开发。
    <br />
    An image-recognition-based automation tool for Goddess of Victory: NIKKE, developed with <a href="https://ok-script.com">ok-script</a>.
  </p>

  <p><i>Simulates user input via Windows interfaces; no memory reads, no file modification</i></p>

  <p>Focuses on daily automation, freeing your hands</p>
</div>

### English | [中文说明](README.md)

---

**Development is based on an early-game account at the latest game progress; some features may not be fully adapted.**

## ⚠️ Disclaimer

This software is an external helper tool that automates parts of the Windows client of Goddess of Victory: NIKKE. It interacts with the game entirely by simulating normal user-interface input, complies with applicable laws and regulations, and never modifies any game files or data.

This software is open-source and free, provided for personal learning and communication only. Do not use it for any commercial or profit-making purpose. The developers retain the final interpretation. Any problems arising from using this software (including, without limitation, account restrictions or bans) are unrelated to the project and its developers.

### The Official Stance on Automation

The official notice dated 2026/09/16:

> **3-2. Macros and Gameplay Automation Programs**
>
> In NIKKE, it is not permitted to use external programs or devices instead of officially provided functions to automate, repeat, or substitute or repeat actions that players must perform themselves.
>
> This includes mouse macros, auto clickers, automation scripts, automated gameplay systems, or other external methods to perform actions on behalf of the player.
>
> Such behavior uses external tools to replace actions that players must perform themselves. This can negatively affect battle results and, in competitive content, rankings and rewards.
>
> We cannot provide detailed information about specific program types or lists of detection targets, as this could be used to evade detection or for malicious purposes. However, we will continue to review and refine the list of detection targets and related programs we check. We will also examine input and gameplay records more closely. These improvements will help our automated checks determine more accurately whether these methods were actually used.
>
> **Updated sanction: Account ban for up to 10 years**
>
> We will apply sanctions at different levels by comprehensively considering the frequency and the duration of the violations, whether the behavior was repeated, whether detection or restriction measures were bypassed, the impact on the competitive environment, any unfair benefits obtained, and other relevant factors.
>
> In particular, repeated circumvention of relevant restrictions or continuing the same behavior will be considered aggravating circumstances.

**Be aware: using this software carries the risk of account restriction or ban, with penalties of up to 10 years. Evaluate the risk yourself before deciding to use it.**

**By using this software, you acknowledge that you have read, understood, and agreed to the above, and voluntarily assume all potential risks.**

## 🚀 Quick Start

1. Download the portable package `ok-nikke-win32-portable.zip` from [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) and extract it to an English path.
2. Run `ok-nikke.exe` as administrator.
3. Start the game.
4. Open the "Daily settings" view and toggle or configure the tasks to run.
![daily_config.png](docs/images/daily_config.png)
5. Return to the "Tasks" view and click "Daily" to start.
![task.png](docs/images/task.png)

Notes:

- **Administrator privileges are required**: if the game runs as administrator, the automation app needs the same privilege level, otherwise capture or input may not work.
- The game must run at a 16:9 resolution of at least 1600×900.
- Input method: `SyntheticTouch` uses a synthetic touch pointer (WM_POINTER) to bypass the game's input filtering and requires the game window in the foreground.
- See the documentation [Quick start](docs/en/getting-started.md) for more usage details and common issues.

## 📝 TODO

- [ ] Overclocked simulation room
- [ ] i18n
- [ ] TBD

## ✨ Features

| Task | Description |
| --- | --- |
| Daily | Orchestration task that runs the subtasks below according to its settings |
| Harvest | Collect friendship points, mailbox rewards and PASS (event/task pass) rewards |
| Outpost Defense | Farm the outpost defense, optionally spending gems for extra runs |
| Cash Shop | Claim free STEP UP / daily / weekly / monthly packages |
| Shop | Buy items from the ordinary / arena / scrapyard shops |
| Recruit | Event free recruit / friendship-point recruit / ordinary recruit |
| Outpost | Dispatch / advise / brief encounters |
| Ark | Manufacturer towers / simulation room / interception / arena |
| Raid | Limited-time challenges (co-op / solo raid) |
| Event | Generic handling of limited-time events (check-in stamp / story push + sweep / challenge) |

## 🔧 Troubleshooting

If you run into problems, check the following steps one by one before asking:

1. **Install path**: make sure the app is installed under a path with English characters only; avoid folders containing Chinese characters.
2. **Antivirus**: add the app's install folder to your antivirus (including Windows Defender) trust list or whitelist, to prevent files from being mistakenly deleted or blocked.
3. **Display settings**:
   - Turn off Windows Auto HDR.
   - Graphics quality: the higher the better.
4. **Game language**: Simplified Chinese is preferred.
5. **App version**: make sure you are using the latest version.
6. **Ask for help**: if none of the above solves your problem, submit a detailed bug report via a GitHub ISSUE or community channels.

## 💻 Developers

Run from source; requires Python 3.12 (other versions untested):

```powershell
git clone https://github.com/c6n1aa/ok-nikke.git
cd ok-nikke
uv sync

# Debug mode (with screenshot/annotation dev tools)
.\.venv\Scripts\python.exe main_debug.py

# Release mode
.\.venv\Scripts\python.exe main.py
```

> Dependencies are managed by `uv`: `uv sync` builds `.venv` from `uv.lock`; `uv export --no-dev` produces the shipped lock `requirements.txt` (`exclude-dependencies` already drops the `pyside6` meta-package/addons, keeping only `pyside6-essentials`; in-app updates in `update.py` still use `pip install --no-deps`).

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestMain
# Full suite: run each test file in its own process
.\run_tests.ps1
```

More developer docs: [Development setup](docs/en/development.md) · [App configuration](docs/en/configuration.md) · [Task development](docs/en/tasks.md) · [Screen recognition & failure recovery](docs/en/screen-and-recovery.md) · [Packaging and release](docs/en/release.md)

This project is built on the [ok-script](https://ok-script.com) framework. Feel free to use [ok-script](https://ok-script.com) to build your own automation projects.

## ❤️ Credits

- [ok-script](https://github.com/ok-oldking/ok-script)
- [MaaFramework](https://github.com/MaaXYZ/MaaFramework) — the synthetic touch pointer (WM_POINTER) interaction method is adapted from this framework
