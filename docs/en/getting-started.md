# Quick Start

## 1. Get the Source

The project repository is at [github.com/c6n1aa/ok-nikke-daily](https://github.com/c6n1aa/ok-nikke-daily):

```bash
git clone https://github.com/c6n1aa/ok-nikke-daily.git
cd ok-nikke-daily
```

## 2. Install Python 3.12

Install [Python 3.12.10](https://www.python.org/downloads/release/python-31210/), then run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --no-deps -r requirements.txt --upgrade
```

Administrator privileges are normally unnecessary. If the target game runs as administrator, launch the automation app at the same privilege level or capture and input may not work.

## 3. Initialize the App

1. Set the application identity, runtime targets, icons, and update repository in [App configuration](configuration.md).
2. Create and register the first task with [Task development](tasks.md).
3. Start Debug mode:

```powershell
python main_debug.py
```

4. Run tests:

```powershell
python -m unittest tests.TestMain
```

5. After validation, configure the workflows and push a tag using [Packaging and release](release.md).
