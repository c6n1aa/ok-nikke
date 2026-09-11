# Development Setup

For developers: running from source, running tests, and the developer documentation map.

## Run from Source

Only Python 3.12 is supported (other versions untested):

```powershell
git clone https://github.com/c6n1aa/ok-nikke.git
cd ok-nikke
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade
```

`--no-deps` is required: dependencies are locked in `requirements.txt` (including all transitive ones); letting pip resolve them installs the `pyside6` meta-package and addons modules (this project only installs `pyside6-essentials`).

Then start the app:

```powershell
.\.venv\Scripts\python.exe main_debug.py   # Debug mode, with screenshot/annotation dev tools
.\.venv\Scripts\python.exe main.py         # Release mode
```

## Run Tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestMain   # single test file
.\run_tests.ps1                                         # full suite, one file per process
```

The full suite must run one file per process: running multiple test files in the same process cannot rebuild the ok singleton and produces false failures.

## Developer Documentation

Once the environment is ready, continue as needed:

1. [App configuration](configuration.md): runtime target, task registration, custom tabs, and patch entry.
2. [Task development](tasks.md): add tasks, register them, and write tests.
3. [Screen recognition & failure recovery](screen-and-recovery.md): core conventions for task development; read before writing tasks.
4. [Task brief template](task_brief_template.md): drive AI task code generation with a brief.
5. [Packaging and release](release.md): tag-triggered portable package releases.
6. [Documentation site](documentation.md): local preview and GitHub Pages deployment.

The repository includes Agent Skills: `ok-script-tasks` (create/modify/register task classes), `ok-script-codegen` (generate `run()` logic from descriptions or screenshots), `ok-script-i18n` (sync translations), and `deploy` (cut release tags).
