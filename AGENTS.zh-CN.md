# AGENTS.md（中文说明）

ok-nikke-daily 是基于 PyPI `ok-script` 库（ok-script-app 模板）构建的《NIKKE：胜利女神》Windows 客户端 Python GUI 自动化应用。本文是面向 AI 编码助手的项目说明与约束，英文副本见 `AGENTS.md`。

## 环境与命令

- 仅支持 Python 3.12。始终使用仓库本地虚拟环境，不要激活或使用全局 Python：`.\.venv\Scripts\python.exe`。
- 安装依赖必须加 `--no-deps`：`.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade`。因为 `pyside6-fluent-widgets` 声明了完整的 PySide6 元包，而本项目只需要 `pyside6-essentials`。`requirements.in` 是 pip-compile 的源文件；每次 `pip-compile` 后都要再次删掉生成的 `pyside6`、`pyside6-addons` 条目。
- 运行 GUI：`python main_debug.py`（调试模式）或 `python main.py`。必须在仓库根目录运行。
- 运行测试（在仓库根目录）：`python -m unittest tests.TestMain` 或 `.\.venv\Scripts\python.exe -m unittest tests.TestMain`。CI 会运行 `tests/` 下每个 `*.py` 文件，新增测试请放到 `tests/` 下。OCR 相关测试需要 onnxocr 模型（首次运行会自动下载）。
- 文档网站：`python -m pip install -r requirements-docs.txt`，然后 `python -m mkdocs serve` 或 `python -m mkdocs build --strict`。CI 要求 `--strict`。文档为中英双语（`docs/` 中文 + `docs/en/` 英文），必须保持结构对齐。

## 架构

- `src/config.py` —— 整个应用配置就是其中的 `config` 字典。任务注册为 `["模块路径", "类名"]`，一次性任务放 `onetime_tasks`，后台任务放 `trigger_tasks`。
- `src/config.py` 中的 `version = "dev"` 由 CI 在打 tag 打包时自动改写 —— 不要修改它。
- `src/tasks/MyBaseTask.py` 是项目基类，新任务应继承它而不是直接继承 `BaseTask`。`MyOneTimeTask` 为一次性任务，`MyTriggerTask` 为后台重复检查的 TriggerTask。自定义 GUI 标签页在 `src/ui/MyTab.py`。
- `src/start_game.py`（在 `src/config.py` 顶部导入，因而在 `ok.OK(config)` 构造前运行）不打补丁文件即实现对 venv 内 ok-script 的猴子补丁：包装 `ok.register_basic_options` 以向「基础设置」添加启动器设置项，并把 `ok.gui.StartController.StartController` 替换为 `NikkeStartController`，其 `start_device` 先做管理员检查、再判断 `nikke.exe` 游戏主进程是否已在运行（若在运行则跳过启动器），否则启动配置的启动器（`nikke_launcher.exe` 或 `.lnk`，自动解析），在可配置区域内 OCR 找到并点击启动按钮，最后等待游戏。没有直接启动回退：若未配置启动器且游戏未在运行，会提示用户配置启动器或手动启动游戏。启动器文件选择框默认打开桌面目录，方便直接看到桌面快捷方式。
- 以下为被 gitignore 的运行时目录（不要提交）：`configs/`（生成的配置 JSON）、`ok_tasks/`、`ok_templates/`（模板匹配素材）、`screenshots/`、`logs/`、`cache/`、`site/`。
- 模板匹配的 coco 标注文件受版本控制，位于 `assets/coco_annotations.json`（`src/config.py` 的 `template_matching` 引用它）。

## 约定（与默认行为不同）

- 任务 UI 字符串（`name`、`description`、`default_config` 键与值、`config_description`、`config_type` 选项）目前直接写简体中文，不做 i18n 文本处理。GUI 会对每个显示的字符串调用 `og.app.tr()`，目录中查不到时原样返回，因此中文可直接显示。`i18n/<locale>/LC_MESSAGES/ok.{po,mo}` 目录保留（目前只有 `zh_CN`、`en_US`，模板示例 `MyOneTimeTask` 仍依赖它）；以后若恢复国际化，用 `$ok-script-i18n` 技能同步目录并重新编译 `.mo`。
- 使用 `.agents/skills/` 下的内置技能：任务类用 `ok-script-tasks`；`run()` 自动化逻辑用 `ok-script-codegen`（其输出要求每行代码都带中文行内注释）；翻译目录用 `ok-script-i18n`；运行 Python 命令用 `use-local-venv`。
- 提交信息语言与最近一次非 merge 提交的标题保持一致。

## 发布

- `.github/workflows/build.yml` 监听 `v*` tag：运行测试、执行 `python -m ok.update.inline_ok_requirements --tag <ref>`、通过 `ok-oldking/pyappify-action` 打包 EXE、创建 GitHub Release。`pyappify.yml` 定义了 China/Global 两个配置档。
- 发布使用 `deploy` 技能，它通过 `.agents/skills/deploy/scripts/next_tag.py` 计算下一个版本号（注意：技能文档里写的路径是 `.agent`，实际路径是 `.agents`）。