<div align="center">
  <h1 align="center">
    <img src="icons/icon.png" width="120" alt="ok-nikke logo"/>
    <br/>
    ok-nikke
  </h1>

  <p>
    一个基于图像识别的《胜利女神：NIKKE》自动化程序，PC 客户端仅支持前台运行，基于 <a href="https://ok-script.com">ok-script</a> 开发。
    <br />
    An image-recognition-based automation tool for Goddess of Victory: NIKKE; the PC client only supports foreground running, developed with <a href="https://ok-script.com">ok-script</a>.
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

**By using this software, you acknowledge that you have read, understood, and agreed to the above, and voluntarily assume all potential risks.**

## 🚀 Quick Start

1. Download the portable package `ok-nikke-win32-portable.zip` from [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) and extract it to an English path.
2. Run `ok-nikke.exe` as administrator.

Notes:

- **Administrator privileges are required**: if the game runs as administrator, the automation app needs the same privilege level, otherwise capture or input may not work.
- The game must run at a 16:9 resolution of at least 1600×900.
- See the documentation [Quick start](docs/en/getting-started.md) for more usage details and common issues.

## 📝 TODO

- [ ] Event story / event area
- [ ] Overclocked simulation room
- [ ] i18n
- [ ] TBD

## ✨ Features

| Task | Description |
| --- | --- |
| Daily | Orchestration task that runs the subtasks below according to its settings |
| Harvest | Collect friendship points and mailbox rewards |
| Outpost Defense | Farm the outpost defense, optionally spending gems for extra runs |
| Cash Shop | Claim free STEP UP / daily / weekly / monthly packages |
| Shop | Buy items from the ordinary / arena / scrapyard shops |
| Recruit | Event free recruit / friendship-point recruit / ordinary recruit |
| Outpost | Dispatch / advise / brief encounters |
| Ark | Manufacturer towers / simulation room / interception / arena |
| Raid | Limited-time challenges (co-op / solo raid) |

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
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade

# Debug mode (with screenshot/annotation dev tools)
.\.venv\Scripts\python.exe main_debug.py

# Release mode
.\.venv\Scripts\python.exe main.py
```

> `--no-deps` is required: dependencies are locked in `requirements.txt` (including all transitive ones); letting pip resolve them installs the `pyside6` meta-package and addons modules.

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
