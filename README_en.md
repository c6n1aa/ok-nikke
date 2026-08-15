# ok-nikke-maid

English | [中文](README.md)

ok-nikke-maid is a Python automation app built on [ok-script](https://github.com/ok-oldking/ok-script), providing a GUI automation app for the Windows client of Goddess of Victory: NIKKE.

## Documentation

The complete documentation is organized as an MkDocs site:

- [Documentation home](docs/en/index.md)
- [Quick start](docs/en/getting-started.md)
- [App and runtime target configuration](docs/en/configuration.md)
- [Task development](docs/en/tasks.md)
- [Packaging and release](docs/en/release.md)
- [Build the documentation site](docs/en/documentation.md)
- [中文文档](docs/index.md)

## Quick Preview

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --no-deps -r requirements.txt --upgrade
python main_debug.py
```

See the [Quick start](docs/en/getting-started.md) for runtime target configuration, the first task, and tag-based packaging.

## Build the Documentation Site

```powershell
python -m pip install -r requirements-docs.txt
python -m mkdocs serve
```

Open `http://127.0.0.1:8000/` to preview the site. Build static HTML with:

```powershell
python -m mkdocs build --strict
```

The output is written to `site/`. `.github/workflows/docs.yml` can publish it automatically to GitHub Pages; see the [documentation-site guide](docs/en/documentation.md) for setup.

## Community

- QQ user group: `1097603920`
- QQ developer group: `938132715`
- [Discord](https://discord.gg/vVyCatEBgA)

## Credits

- [ok-script](https://github.com/ok-oldking/ok-script)
- [OnnxOCR](https://github.com/ok-oldking/OnnxOCR)
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)