# ok-nikke

[English](README_en.md) | 中文

ok-nikke 是一个基于 [ok-script](https://github.com/ok-oldking/ok-script) 的 Python 自动化应用，为《NIKKE：胜利女神》（Goddess of Victory: NIKKE）Windows 客户端提供带 GUI 的自动化。

## 文档

完整文档已整理为 MkDocs 网站源文件：

- [文档首页](docs/index.md)
- [快速开始](docs/getting-started.md)
- [应用与运行目标配置](docs/configuration.md)
- [任务开发](docs/tasks.md)
- [打包与发布](docs/release.md)
- [构建文档网站](docs/documentation.md)
- [English documentation](docs/en/index.md)

## 快速预览

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --no-deps -r requirements.txt --upgrade
python main_debug.py
```

详细的运行目标配置、首个任务和 tag 打包流程请阅读[快速开始](docs/getting-started.md)。

## 构建文档网站

```powershell
python -m pip install -r requirements-docs.txt
python -m mkdocs serve
```

访问 `http://127.0.0.1:8000/` 预览。生成静态 HTML：

```powershell
python -m mkdocs build --strict
```

输出位于 `site/`。`.github/workflows/docs.yml` 可将网站自动发布到 GitHub Pages，具体设置见[文档网站说明](docs/documentation.md)。

## 社区

- 用户群：`1097603920`
- 开发者群：`938132715`
- [Discord](https://discord.gg/vVyCatEBgA)

## 致谢

- [ok-script](https://github.com/ok-oldking/ok-script)
- [OnnxOCR](https://github.com/ok-oldking/OnnxOCR)
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
