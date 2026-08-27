# AGENTS.md

ok-nikke-maid 是基于 PyPI `ok-script`（2.x）构建的《NIKKE》Windows 客户端 GUI 自动化应用。技术栈：PySide6 + qfluentwidgets（GUI）、OpenCV 模板匹配 + onnxocr（识别）。仓库：<https://github.com/c6n1aa/ok-nikke-maid> 。本文只写给 coding agent 的规则与命令，背景细节看代码或 `docs/`。

## 红线

- 新任务继承 `src.tasks.NikkeBaseTask`，不直接继承 `BaseTask`。
- **禁止 `import ok.*` 后改其源码**：扩展/修正一律走 `src/patches/`（新增补丁在 `apply_all()` 注册），不得在其他地方 monkey-patch。
- **禁止导入 PySide6 Essentials 之外的 Qt 模块**（`QtMultimedia`/`QtWebEngineWidgets`/`QtCharts`/`QtSql` 等）——这些是 addons 模块，本项目只装 `pyside6-essentials`，导入即 `ImportError`。
- **禁止新增 `.qss`、硬编码颜色、控件级 `setStyleSheet`**；布局复用 `ok.ui.qt.common.design_system` 令牌。
- **`assets/images/*.png` 是模板图集，不是游戏截图**，不要读画面/OCR/理解 UI。
- 不覆写 `click_box`；战斗结束等结果用 `wait_battle_finish`，不用 `wait_feature`/`wait_ocr` 忙轮询。

## 关键机制

- **界面识别/导航/恢复**（详见 `docs/screen-and-recovery.md`）：界面统一注册在 `src/screens.py` 的 `SCREENS`（不在任务 `__init__` 里 `register_screen`）；「点入口→确认进入」用 `transition()`；子流程开头闸门用 `ensure_screen()`；失败恢复用 `try_step` 包入口方法**一层**（内部步骤不逐个包，禁止手写重试/回大厅）。范例：`DailyTask.run` 开头就位大厅、`ArkTask` 各 `_do_*`/`_nav_*` 入口方法。
- **完成状态**：声明 `done_keys = {key: period}`（如 `{"harvest": "day"}`），基类给 `is_completed()`/`clear_done_all()`，自动接 UI；纯编排/调试任务（`DailyTask`/`DebugTask`）不定义。
- **模板匹配 / coco 标注**：`assets/coco_annotations.json` 是 COCO 格式——`images[].file_name` 指向图集 `images/*.png`、`annotations[].bbox` 是图集坐标（非游戏画面坐标）、`categories[].name` 是特征名，运行时由 `FeatureSet` 按当前分辨率缩放匹配。`assets/template/` 小图（铃铛、关闭按钮等）用 `find_scaled_template(...)` 缩放后匹配，禁止未缩放模板直接传 `find_one`/`find_feature`。
- **任务 UI 数据驱动**：改用户看到的内容就改任务属性（`name`/`description`/`default_config`/`config_type` 等），不手写控件；新增 `config_type` 需同步 `ConfigItemFactory` 工厂分支。标准范例见 `src/tasks/MyOneTimeTask.py`。

## 架构概览

- `src/tasks/`：全部任务类所在，`NikkeBaseTask.py` 是基类（集成界面识别/导航/恢复、完成状态、模板缩放、弹窗清理、战斗等待等通用方法，用法见「关键机制」）；新增任务模板见同目录 `MyOneTimeTask`（一次性）/`MyTriggerTask`（后台触发）。任务清单注册在 `src/config.py` 的 `onetime_tasks`（`trigger_tasks` 当前为空）。
- `src/patches/`：ok-script 猴子补丁唯一入口（`basic_options`/`start_controller`/`runtime`/`tasks_tab`），各补丁职责见 `src/patches/README.md`。
- `src/screens.py`：界面识别单一数据源（`SCREENS` 注册表 + `INTERRUPTS` 中断哨兵）。
- `src/ui/`：自定义 tab（当前仅 `DailyTab`，经 `src/config.py` 的 `custom_tabs` 注册）。
- 资产：`assets/coco_annotations.json`（COCO 标注）+ `assets/images/`（图集）+ `assets/template/`（手动裁剪小图）。
- 运行时产物（`configs/`/`logs/`/`screenshots/` 等）与框架本体（`ok/` 等）不入仓，以 `.gitignore` 为准；开发时使用或生产的一次性脚本/中间产物放 `dev_tools/`（已 gitignore），XAL 标注导入在 `scripts/import_xal.py`。
- CI：`.github/workflows/build.yml`（监听 `v*` tag → 测试+打包+Release）、`docs.yml`（部署 mkdocs）。

## 环境与命令

- 仅 Python 3.12，一律 `.\.venv\Scripts\python.exe`，不用全局 python / `py`。

| 操作 | 命令 |
|---|---|
| 装依赖 | `.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade` |
| 跑测试 | `.\.venv\Scripts\python.exe -m unittest tests.TestMain`（全量 `run_tests.ps1`） |
| 发布 | `deploy` 技能（`.agents/skills/deploy/scripts/next_tag.py`） |

- 装依赖必须 `--no-deps`（只装 `pyside6-essentials`，不要 `pyside6` 元包）；依赖源是 `pyproject.toml`，`pip-compile` 后删掉生成的 `pyside6`/`pyside6-addons` 条目。
- 发布技能的脚本路径：技能文档写 `.agent`，实际是 `.agents`。

## 编码约定

- 任务 UI 字符串直接写简体中文，不做 i18n（框架 `og.app.tr()` 查不到原样返回）。
- 非必要不手写 `self.sleep`：等待优先挂在框架 API 的 `after_sleep`/`time_out` 参数上，写在产生界面变化的那个调用的挂点处。
- 技能（`.agents/skills/`）：任务类 `ok-script-tasks`；`run()` 逻辑 `ok-script-codegen`；翻译 `ok-script-i18n`；跑 Python `use-local-venv`。查 ok-script 框架 API：venv `ok` 包源码、`docs/api_doc/README.md`、`.agents/skills/ok-script-tasks/references/`。
- 提交信息用 Conventional Commits：`<type>[optional scope]: <description>`。

## 测试策略

- 测试放 `tests/` 下，命名 `TestXxxTask.py` 对应 `src/tasks/XxxTask.py`；继承 `ok.test.TaskTestCase`，设 `task_class`（参考 `docs/after_quick_start/README.md` §3）。现成范例见 `tests/TestShopTask.py`/`tests/TestArkTask.py`（覆盖成功/跳过/失败/已完成跳过分支）。
- **不碰真实环境**：`wait_for_lobby`（真实置前窗口）、`dismiss_all_popups`（真实抓帧+OCR）等必经方法必须 `patch.object` 拦截并断言参数。
- mock 保证被测循环可终止：`while True` 流程（如爬塔）用 `side_effect` 有限序列，别 `return_value` 死循环。
- 被测流程内 `sleep` 一律 patch；引用（方法名、config 键名）以源码为准。
- 小范围机械改动（改参数名/方法名，不动功能或业务逻辑）不必跑测试；其余按影响面只跑相关单个测试文件。**全量必须逐文件独立进程**（CI/`run_tests.ps1` 方式），连跑多文件会因 ok 单例无法重建产生假错误。
