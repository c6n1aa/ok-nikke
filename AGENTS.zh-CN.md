# AGENTS.md（中文说明）

ok-nikke-maid 是基于 PyPI `ok-script` 库（ok-script-app 模板）构建的《NIKKE：胜利女神》Windows 客户端 Python GUI 自动化应用。本文是面向 AI 编码助手的项目说明与约束，英文副本见 `AGENTS.md`。

## 环境与命令

- Windows 平台下，所有终端命令一律用 PowerShell 7（`pwsh`）执行，不要切换到 cmd 或其他 shell，除非被明确要求。
- 这里的命令实际执行方式：opencode 全局配置（`~/.config/opencode/opencode.jsonc`）将 `"shell": "pwsh"` 设为短名（**不要**用 `C:\Users\<用户名>\AppData\Local\Microsoft\WindowsApps\pwsh.exe`，那是应用执行别名 reparse point，opencode 启动时的 `statSync` 会报 `EACCES` 失败；用 `pwsh` 短名，opencode 会通过 `which("pwsh")` 解析到真实安装路径，没有 `.cmd` 包装，也没有 `cmd.exe` 这一层）。opencode 通过 Node `spawn(cmd, [], {shell})` 执行每条命令，在 Windows 上会构造 `pwsh.exe -c "<命令>"`（不带 `-NoProfile`），所以完整命令串会原样到达 pwsh，只由 PowerShell 解析。因此：
  - 双引号字符串内的 `|`（管道符）是安全的（pwsh 看到的字面命令，例如 `Select-String -Pattern "test_|FAIL|OK|Ran|Error"` 可以正常工作）。旧的 cmd.exe 限制已不再适用。
  - 如果希望在字符串里传 `|` 时零插值、最清晰，仍然优先用**单引号**（`-Pattern 'test_|FAIL'`）——同样安全，还能避免 pwsh 的字符串插值问题。
  - 输出端到端为 UTF-8：`PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8` 已设置在 Windows **用户**级环境变量中（管道输出与 `chcp`/控制台代码页无关）。如果哪天看到中文乱码，先确认这两个环境变量还在、且 shell 配置没有被改回 `.cmd` 文件。
- 仅支持 Python 3.12。始终使用仓库本地虚拟环境，不要激活或使用全局 Python：`.\.venv\Scripts\python.exe`。
- 安装依赖必须加 `--no-deps`：`.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade`。因为 `pyside6-fluent-widgets` 声明了完整的 PySide6 元包，而本项目只需要 `pyside6-essentials`。`requirements.in` 是 pip-compile 的源文件；每次 `pip-compile` 后都要再次删掉生成的 `pyside6`、`pyside6-addons` 条目。
- 运行 GUI：`python main_debug.py`（调试模式）或 `python main.py`。必须在仓库根目录运行。
- 运行测试（在仓库根目录）：`python -m unittest tests.TestMain` 或 `.\.venv\Scripts\python.exe -m unittest tests.TestMain`，或通过 `run_tests.ps1` 运行全部测试。CI 会运行 `tests/` 下每个 `*.py` 文件，新增测试请放到 `tests/` 下。OCR 相关测试需要 onnxocr 模型（首次运行会自动下载）。标准测试写法见下文「测试」一节。
- 文档网站：`python -m pip install -r requirements-docs.txt`，然后 `python -m mkdocs serve` 或 `python -m mkdocs build --strict`。CI 要求 `--strict`。文档为中英双语（`docs/` 中文 + `docs/en/` 英文），必须保持结构对齐。

## 架构

- `src/config.py` —— 整个应用配置就是其中的 `config` 字典。任务注册为 `["模块路径", "类名"]`，一次性任务放 `onetime_tasks`，后台任务放 `trigger_tasks`。
- `src/config.py` 中的 `version = "dev"` 由 CI 在打 tag 打包时自动改写 —— 不要修改它。
- `src/tasks/MyBaseTask.py` 是项目基类，新任务应继承它而不是直接继承 `BaseTask`。`MyOneTimeTask` 为一次性任务，`MyTriggerTask` 为后台重复检查的 TriggerTask。自定义 GUI 标签页在 `src/ui/MyTab.py`。
- `src/start_game.py`（在 `src/config.py` 顶部导入，因而在 `ok.OK(config)` 构造前运行）不打补丁文件即实现对 venv 内 ok-script 的猴子补丁：包装 `ok.register_basic_options` 以向「基础设置」添加启动器设置项，并把 `ok.gui.StartController.StartController` 替换为 `NikkeStartController`，其 `start_device` 先做管理员检查、再判断 `nikke.exe` 游戏主进程是否已在运行（若在运行则跳过启动器），否则启动配置的启动器（`nikke_launcher.exe` 或 `.lnk`，自动解析），在可配置区域内 OCR 找到并点击启动按钮，最后等待游戏。没有直接启动回退：若未配置启动器且游戏未在运行，会提示用户配置启动器或手动启动游戏。启动器文件选择框默认打开桌面目录，方便直接看到桌面快捷方式。
- 以下为被 gitignore 的运行时目录（不要提交）：`configs/`（生成的配置 JSON）、`ok_tasks/`、`ok_templates/`（模板匹配素材）、`screenshots/`、`logs/`、`cache/`、`site/`、`dev_tools/`（临时脚本与生成的开发产物）。
- 一次性开发脚本及其生成的文件（如 OCR 批量报告、重命名映射表、XAL→coco 转换中间产物、备份）都放在仓库根目录的 `dev_tools/` 下 —— 绝不要放到系统临时目录。新增的临时脚本及其输出一律存到 `dev_tools/`，路径使用相对仓库根目录的写法，并保持该目录被 gitignore。
- 模板匹配的 coco 标注文件受版本控制，位于 `assets/coco_annotations.json`（`src/config.py` 的 `template_matching` 引用它）。
- 模板匹配：coco 里标注的模板由 `FeatureSet` 按当前游戏分辨率自动缩放（坐标和图片都会缩放）。对于 `assets/template/` 下手动裁剪、无法标注（位置不确定）的小模板，一律调用 `MyBaseTask` 的 `find_scaled_template(feature_name, template_path, ref_width, ref_height)` 辅助方法 —— 它会按当前游戏分辨率等比缩放模板（源截图默认 2560x1440，按路径+缩放比例缓存），再执行 `find_one(template=...)`。禁止把未缩放的原始模板直接传给 `find_one`/`find_feature`，否则在非 2560x1440 分辨率下匹配会失效。

## 约定（与默认行为不同）

- 任务 UI 字符串（`name`、`description`、`default_config` 键与值、`config_description`、`config_type` 选项）目前直接写简体中文，不做 i18n 文本处理。GUI 会对每个显示的字符串调用 `og.app.tr()`，目录中查不到时原样返回，因此中文可直接显示。`i18n/<locale>/LC_MESSAGES/ok.{po,mo}` 目录保留（目前只有 `zh_CN`、`en_US`，模板示例 `MyOneTimeTask` 仍依赖它）；以后若恢复国际化，用 `$ok-script-i18n` 技能同步目录并重新编译 `.mo`。
- 使用 `.agents/skills/` 下的内置技能：任务类用 `ok-script-tasks`；`run()` 自动化逻辑用 `ok-script-codegen`（其输出要求每行代码都带中文行内注释）；翻译目录用 `ok-script-i18n`；运行 Python 命令用 `use-local-venv`。
- 点击节奏一律使用 `wait_click_feature`/`click_box`/`click` 内置的 `after_sleep` 参数（点击后的固定等待）。不要在步骤之间手动加 `time.sleep`/`sleep`，也不要覆写 `click_box` —— 该参数已经覆盖了等待。
- 提交信息语言与最近一次非 merge 提交的标题保持一致。

## 测试

- 任务测试用 `unittest` 编写，继承 `ok.test.TaskTestCase`，并设置 `task_class` 指向被测任务（例如 `from src.tasks.MyTask import MyTask`）。标准参考见 `docs/after_quick_start/README.md`（§3 自动化测试）。
- 核心技术：`self.set_image(<路径>)` 把屏幕输入固定为一张静态图片，从而创造稳定、可复现的运行环境，用于断言识别、点击、OCR 等行为。
- 复现用户报告的问题：把用户上传的截图作为测试图（如 `self.set_image('tests/user_screenshots/user_bug_report_01.png')`），调用出错的精确方法，并断言修复后的行为符合预期。
- 运行测试：`run_tests.ps1` 运行 `tests/` 下全部测试；单个文件或方法可在 PyCharm 中右键运行。在 PyCharm 中，运行/调试配置的「工作目录」必须设为仓库根目录，否则 `tests/images/` 等相对路径无法解析。

## 发布

- `.github/workflows/build.yml` 监听 `v*` tag：运行测试、执行 `python -m ok.update.inline_ok_requirements --tag <ref>`、通过 `ok-oldking/pyappify-action` 打包 EXE、创建 GitHub Release。`pyappify.yml` 定义了 China/Global 两个配置档。
- 发布使用 `deploy` 技能，它通过 `.agents/skills/deploy/scripts/next_tag.py` 计算下一个版本号（注意：技能文档里写的路径是 `.agent`，实际路径是 `.agents`）。