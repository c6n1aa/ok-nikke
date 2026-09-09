<div align="center">
  <h1 align="center">
    <img src="icons/icon.png" width="120" alt="ok-nikke logo"/>
    <br/>
    ok-nikke
  </h1>

  <p>
    一个基于图像识别的《胜利女神: NIKKE》自动化程序，PC 客户端仅支持前台运行，基于 <a href="https://ok-script.com">ok-script</a> 开发。
    <br />
    An image-recognition-based automation tool for Goddess of Victory: NIKKE; the PC client only supports foreground running, developed with <a href="https://ok-script.com">ok-script</a>.
  </p>

  <p><i>Simulates user input via Windows interfaces; no memory reads, no file modification</i></p>
</div>

### English | [中文说明](README.md)

---

## ⚠️ Disclaimer

This software is an external helper tool that automates parts of the Windows client of Goddess of Victory: NIKKE. It interacts with the game entirely by simulating normal user-interface input, complies with applicable laws and regulations, and never modifies any game files or data.

This software is open-source and free, provided for personal learning and communication only. Do not use it for any commercial or profit-making purpose. The developers retain the final interpretation. Any problems arising from using this software (including, without limitation, account restrictions or bans) are unrelated to the project and its developers.

**By using this software, you acknowledge that you have read, understood, and agreed to the above, and voluntarily assume all potential risks.**

## ✨ Features

- **Foreground running**: The PC client only supports foreground running (Pynput / PyDirect input); keep the game window in the foreground and visible.
- **Image recognition**: OpenCV template matching (COCO-managed assets) combined with onnxocr (PaddleOCR v5 + OpenVINO) to read text and locate buttons.
- **Resolution adaptive**: Smooth support for 16:9 resolutions (minimum 1600×900); assets are scaled to the current resolution automatically.
- **Completion state**: Built-in daily/weekly completion tracking to avoid repeating finished tasks.
- **Failure recovery**: Automatically returns to the lobby and retries when recognition fails or the flow stalls.

Implemented tasks:

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

## 🚀 Quick Start

Run from source; requires Python 3.12 (other versions untested):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --no-deps -r requirements.txt --upgrade

# Debug mode (with dev tools)
python main_debug.py

# Release mode
python main.py
```

If the target game runs as administrator, the automation program must also run with administrator privileges, otherwise capture or input may not take effect. See [Quick start](docs/en/getting-started.md) for runtime-target configuration and packaging.

## 📥 Downloads

- **[GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases)**: Official release page. Each tag provides an `ok-nikke-win32-portable.zip`; extract anywhere and run the included `ok-nikke.exe` (administrator privileges required).

## 📖 Documentation

The complete documentation is organized as an MkDocs site; preview it locally with `python -m mkdocs serve`:

- [Home](docs/en/index.md)
- [Quick start](docs/en/getting-started.md)
- [App and runtime target configuration](docs/en/configuration.md)
- [Task development](docs/en/tasks.md)
- [Screen recognition & failure recovery](docs/en/screen-and-recovery.md)
- [Packaging and release](docs/en/release.md)
- [中文文档](docs/index.md)

## 💻 Developers

Run tests (after completing the environment setup):

```powershell
python -m unittest tests.TestMain
# Full suite: run each test file in its own process
.\run_tests.ps1
```

This project is built on the [ok-script](https://ok-script.com) framework. Feel free to use [ok-script](https://ok-script.com) to build your own automation projects.

## ❤️ Credits

- [ok-script](https://github.com/ok-oldking/ok-script)