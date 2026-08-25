# AGENTS.md

ok-nikke-maid 是基于 PyPI `ok-script` 库（ok-script-app 模板）构建的《胜利女神：NIKKE》Windows 客户端 Python GUI 自动化应用。仓库地址：https://github.com/c6n1aa/ok-nikke-maid 。本文是面向 AI Coding Agent 的项目说明与约束。

## 环境与命令

- 仅支持 Python 3.12。始终使用仓库本地虚拟环境，不要激活或使用全局 Python 或 Python launcher `py`：所有命令一律写 `.\.venv\Scripts\python.exe` 全路径。
- 安装依赖必须加 `--no-deps`：`.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade`。因为 `pyside6-fluent-widgets` 声明了完整的 PySide6 元包，而本项目只需要 `pyside6-essentials`。`pyproject.toml`（`[project.optional-dependencies]`）是依赖源文件；每次 `pip-compile` 后都要再次删掉生成的 `pyside6`、`pyside6-addons` 条目。升级注意点（ok-script 2.x）：`pywin32` 必须保持 `>=306,!=312`（build 312 是坏版本；不要写成 `>=313` —— 该版本不存在，pip 会解析到 build 311，支持 Python 3.12）；`ok-d3dshot` 是新增的传递依赖，因打包用 `--no-deps` 跑 pip，所以必须显式列在 `requirements.txt` 里。
- 运行测试（在仓库根目录）：`.\.venv\Scripts\python.exe -m unittest tests.TestMain`，或通过 `run_tests.ps1` 运行全部测试。CI 会运行 `tests/` 下每个 `*.py` 文件，新增测试请放到 `tests/` 下。OCR 相关测试需要 onnxocr 模型（首次运行会自动下载）。标准测试写法见下文「测试」一节。

## 架构

- `src/tasks/NikkeBaseTask.py` 是项目基类，新任务应继承它而不是直接继承 `BaseTask`。`MyOneTimeTask`（一次性任务范例，覆盖每个 `config_type` 工厂分支）、`MyTriggerTask`（后台重复检查的 TriggerTask 模板）位于同目录。当前 `onetime_tasks` 注册的任务类见 `src/tasks/`（DailyTask 是日常编排总任务，下含 Harvest / OutpostDefense / Shop / CashShop / Ark / Raid 等子任务，外加 ok 包的 DiagnosisTask 诊断任务；定义了 `done_keys` 的范例见 HarvestTask / CashShopTask / ArkTask / OutpostDefenseTask / ShopTask / RaidTask）。`trigger_tasks` 当前为空 —— `MyTriggerTask` 仅作模板保留，新增 TriggerTask 需从零编写。自定义 GUI 标签页见下文「GUI 框架与样式约束」节。
- `src/patches/` 集中存放所有针对 venv 内 ok-script 的猴子补丁（在 `src/config.py` 顶部经 `apply_all()` 应用，因而在 `ok.OK(config)` 构造前运行）。每个模块暴露一个 `apply()` 且只负责一个主题 —— 项目内任何其他代码都不得自行修补 ok 包，新增补丁一律加到这里并注册进 `apply_all()`。各补丁（`basic_options`、`start_controller`、`runtime`、`tasks_tab`）的具体行为见 `src/patches/README.md`。
- 运行时产物目录（`configs/`、`logs/`、`screenshots/`、`cache/`、`update/` 等）与 ok-script 框架本体（`ok` 包目录、`models/`、`paddle_model/`、`fonts/`、`tesseract/`）均不入仓；完整清单以 `.gitignore` 为准，本文不重复枚举（手工清单必然漂移）。关键语义只有三条：框架本体**不要尝试 `import ok.*` 后改其源码**，扩展/修正一律在 `src/patches/` 走受控补丁；一次性临时脚本与中间产物放 `dev_tools/`（已 gitignore），详见下条；`ok_templates/` 是 XAL 标注工作区，其内容经压缩后成为下文的模板图集。
- 一次性开发脚本及其生成的文件（如 OCR 批量报告、重命名映射表、XAL→coco 转换中间产物、备份）都放在仓库根目录的 `dev_tools/` 下 —— 绝不要放到系统临时目录。新增的临时脚本及其输出一律存到 `dev_tools/`，路径使用相对仓库根目录的写法，并保持该目录被 gitignore。该目录已积累的范例（改 Ark/Shop/OCR 相关任务时可参考）：`import_xal.py`（XAL 标注导入）、`crop_tribe.py`、`dump_simulation_coco.py`、`inspect_api.py`/`inspect_sim_features.py`（特征/API 检查）、`perf_check.py`（性能基准）等；新增类似工具优先复用既有脚本结构。
- 模板匹配的 coco 标注文件受版本控制，位于 `assets/coco_annotations.json`（`src/config.py` 的 `template_matching` 引用它）。
- **`assets/images/` 下的图片不是单纯的游戏截图**，而是压缩后的模板图集（atlas）。它们由标注的 2560x1440 截图生成：标注来源有两种 —— XAL（x-anylabeling）标注经 `dev_tools/import_xal.py` 导入，或使用本框架自带开发工具的截图标注（GUI「模板 tab → 保存压缩」），两条路径都走 ok 框架的 `FeatureSet.compress_copy_coco`/`compress_coco`：全部已标注特征按 (width,height) 分组、按 bbox 冲突贪心拼到 N 张白底大图（默认 2560x1440）上，只保留被标注区域，其余区域以白色填充。因此**不要把 `assets/images/*.png` 当作游戏截图去读画面/OCR/理解 UI**。配套的 `assets/coco_annotations.json` 是 COCO 格式标注：`images[].file_name` 指向 `images/*.png`，`annotations[].bbox` 是**图集上的坐标**（不是原游戏画面的坐标），`categories[].name` 为特征名；`FeatureSet` 通过 `src/config.py` 的 `template_matching` 读取它，并在运行时把坐标与图片一起缩放到当前游戏分辨率后匹配。
- 模板匹配：coco 里标注的模板由 `FeatureSet` 按当前游戏分辨率自动缩放（坐标和图片都会缩放）。相比之下，`assets/template/` 下是手动裁剪、无 coco 标注（位置不确定、无法标注）的小 UI 元素图（如公告铃铛、关闭按钮），一律调用 `NikkeBaseTask` 的 `find_scaled_template(feature_name, template_path, ref_width, ref_height)` 辅助方法 —— 它会按当前游戏分辨率等比缩放模板（源截图默认 2560x1440，按路径+缩放比例缓存），再执行 `find_one(template=...)`。禁止把未缩放的原始模板直接传给 `find_one`/`find_feature`，否则在非 2560x1440 分辨率下匹配会失效。

## GUI 框架与样式约束

- UI 基于 PySide6（Qt 6.11）+ PySide6-Fluent-Widgets（`qfluentwidgets`），但 `requirements.txt` 只安装了 `pyside6-essentials` —— `pyside6`/`pyside6-addons` 是被刻意排除的。**禁止导入 Essentials 之外的 Qt 模块**（`QtMultimedia`、`QtWebEngineWidgets`、`QtCharts`、`QtSql`、`QtNetwork`、`QtOpenGL`、`QtPdf` 等），否则打包后的 EXE 启动时会直接崩溃。优先使用 `qfluentwidgets` 控件（`PrimaryPushButton`、`BodyLabel`、`StrongBodyLabel`、`SwitchButton`、`ComboBox`、`InfoBar`、`MessageBox`、`FluentIcon` 等），而不是裸 `QWidget`/`QPushButton` 加 `setStyleSheet`，这样明/暗主题切换与 Windows 系统强调色能自动生效。
- 主窗口是 ok-script 的 `ok.ui.qt.MainWindow.MainWindow`（`FluentWindow` 子类）；整套 GUI 框架都位于 venv 的 `ok` 包内（且 `ok/` 目录被 gitignore，不入仓）。自定义标签页在 `src/ui/` 下继承 `ok.ui.qt.widget.CustomTab`，并通过 `src/config.py` 的 `custom_tabs` 列表注册（`["模块路径", "类名"]`，由 `MainWindow.addSubInterface` 消费）。当前实际注册的是 `["src.ui.DailyTab", "DailyTab"]`（日常设置 tab）；`src/ui/MyTab.py` 是 ok-script-app 模板自带的示例 tab，仅作参考、未被 `custom_tabs` 引用。禁止复刻或修补其他 `ok.ui.qt` 模块 —— 唯一允许的猴子补丁只有 `src/patches/` 里的那几处。
- 仓库内没有自定义 QSS。所有共享样式来自 ok-script 内置样式表（`ok/ui/qt/qss/{light,dark}/*.qss`，由 `ok.ui.qt.common.StyleSheet` 以 `:/qss/...` 引用）以及 qfluentwidgets 自身的主题系统。**新增代码不要添加 `.qss` 文件、硬编码颜色或控件级 `setStyleSheet`。** 需要套用共享外观时，复用内置样式表已支持的对象名（`#card`、`#configRow`、`#view`、`#titleLabel`、`#contentLabel`、`#configContentFrame`）。
- 复用 `ok.ui.qt.common.design_system` 的共享布局令牌与辅助函数：`DesignToken`（8 点网格 —— PAGE_MARGIN 24、CARD_PADDING 16、ROW_MIN_HEIGHT 56、CONTROL_WIDTH 180 等）、`configure_page_layout`、`configure_card_layout`、`configure_row`、`control_width()`。用 `Tab.add_widget`/`add_card` 和 `ok.ui.qt.widget.Card` 容器来组织页面。不要自创边距、间距或控件宽度。
- 图标：界面图标统一用 `FluentIcon`（或 ok-script 的 `OKIcon`）。应用窗口图标固定为 `icons/icon.png`（`src/config.py` 的 `gui_icon`）—— 保持该文件名不变，尽量避免新增图片素材。
- 任务卡片/行是数据驱动的，不是控件代码：任务页根据任务的 `name`、`description`、`default_config`、`config_description`、`config_type`、`group_name`/`group_icon` 自动渲染。要改用户看到的内容，改这些任务属性即可。`config_type` 在 `ok.ui.qt.tasks.ConfigItemFactory` 中映射为具体控件（`drop_down`、`multi_selection`、`text_edit`、`line_edit`、`file_selector`、`button`/`buttons`；bool→开关、int→数字框、float→小数框、str→单行/多行文本框、list→多选列表项）—— 新增 `config_type` 类型时必须同步添加对应的工厂分支。`src/tasks/MyOneTimeTask.py` 是各类配置控件的标准范例（覆盖每个工厂分支，含 `button`/`buttons` 及回调）—— 新增任何配置 UI 时先参考它，优先复用已有 `config_type` 类型，而不是手写自定义行控件；当卡片只需展示部分配置时，行仍用标准 `config_type` 渲染，再在受控的 `src/patches/tasks_tab.py` 补丁里做过滤。

## 约定（与默认行为不同）

- 任务 UI 字符串（`name`、`description`、`default_config` 键与值、`config_description`、`config_type` 选项）目前直接写简体中文，不做 i18n 文本处理。GUI 会对每个显示的字符串调用 `og.app.tr()`，目录中查不到时原样返回，因此中文可直接显示。`i18n/<locale>/LC_MESSAGES/ok.{po,mo}` 目录保留（目前只有 `zh_CN`、`en_US`，模板示例 `MyOneTimeTask` 仍依赖它）；以后若恢复国际化，用 `$ok-script-i18n` 技能同步目录并重新编译 `.mo`。
- 使用 `.agents/skills/` 下的内置技能：任务类用 `ok-script-tasks`；`run()` 自动化逻辑用 `ok-script-codegen`；翻译目录用 `ok-script-i18n`；运行 Python 命令用 `use-local-venv`。
- 不要覆写 `click_box`；非必要不要手动调用 `self.sleep(...)`：点击/识别后的固定等待一律优先挂在框架参数上（`click*`/`wait_click_*` 的 `after_sleep`、`wait_*` 的 `time_out` 等），把等待写在产生界面变化的那个调用的挂点处，而不是由调用方在流程里补 sleep；仅当确实没有对应挂点（如无点击动作的纯动画收尾）才允许短 `sleep`。其余 Frame Refresh Rules 详见 `ok-script-codegen` skill。
- 界面识别、守卫式导航与失败恢复的完整约定见 `docs/screen-and-recovery.md`，红线只有四条：全局界面注册集中在 `src/screens.py` 的 `SCREENS`（新界面加进去，别再在任务 `__init__` 里 `register_screen`；`lobby` 已注册）；「点击入口 → 确认目标界面」的导航边一律用基类 `transition()`；子流程开头的幂等入口闸门用基类 `ensure_screen()`（内部已处理过场动画容忍、清弹窗、冷启动/恢复分流；默认失败抛 `WaitFailedException` 供 `try_step` 恢复，任务开头就位大厅可传 `raise_on_fail=False` 优雅中止，可选 `entry` 解析器返回 None 表示入口缺失、方法返回 False 按已完成收尾）；失败恢复用 `try_step` 包入口方法**一层**（内部步骤不逐个包；禁止手写临时重试/恢复逻辑、绕过 `_recover_to_lobby` 硬编码回大厅）；判定优先 coco 模板特征、OCR 关键词需配 `ocr_box`。注册可选原则、spec 字段（`absent`/`priority`/`min_frames`）、弹窗与临时子页面约定、判据几何约束等细节一律以该文档为准。
- 完成状态：任务需要记录「本周期已完成」状态（用 `is_done`/`mark_done`/`clear_done`）时，声明类属性 `done_keys = {key: period}`（例如 `HarvestTask.done_keys = {"harvest": "day"}`、`ShopTask.done_keys = {"shop_general": "day", "shop_arena": "day", "shop_recycling": "week"}`）。基类据此提供 `is_completed()`（所有 done_keys 都完成才返回 True）与 `clear_done_all()`；完成口径特殊时覆盖 `is_completed()`（例如 `ShopTask` 只统计用户开启的子商店）。这两个方法自动接入 UI：「日常设置」tab 每个子任务卡片头部显示状态图标（切 tab 时刷新，完成→`FluentIcon.COMPLETED`，未完成→卡片默认图标）；`src/patches/tasks_tab.py` 会给所有 `done_keys` 非空的 `NikkeBaseTask` 卡片在 Operation 行、`Reset Config` 前注入固定的「重置完成状态」按钮（点击调用 `clear_done_all()`；该补丁还负责日常卡片置顶、`HorizontalSeparator` 分割线、日常卡片展开区行过滤，完整职责见 `src/patches/README.md`）。纯编排任务（自身从不 `mark_done`，如 `DailyTask`）不定义 `done_keys`。
- 自动战斗等待：进入自动战斗后等结果一律用基类 `wait_battle_finish`（节流轮询、**只检测不点击**，返回 `("success"/"failed"/None, box)`，结算后动作由调用方决定）；长等待期间遇断线/维护等弹窗由 `src/screens.py` 的 `INTERRUPTS` 哨兵快速失败。新增战斗结果界面时核对 coco 里的 `battle_finish_*` 特征；中断弹窗的标注与激活流程见 `docs/screen-and-recovery.md`「长等待与中断哨兵」。禁止用 `wait_feature`/`wait_ocr` 忙轮询长等战斗。
- 提交信息一律使用 Conventional Commits 格式：`type(scope): 英文主题`（type 取 feat/fix/refactor/docs/chore/build/test；scope 在能明确时用任务或模块名），非琐碎改动附英文正文。不要从历史提交推断语言或风格 —— 本条规则是权威约定。

## 测试

- `tests/` 下已有多个测试文件，覆盖各任务和恢复协议；新增任务的测试参考同目录现成范例，覆盖主要分支（成功/跳过/失败/已完成跳过）。
- 任务测试用 `unittest` 编写，继承 `ok.test.TaskTestCase`，并设置 `task_class` 指向被测任务（例如 `from src.tasks.MyTask import MyTask`）。标准参考见 `docs/after_quick_start/README.md`（§3 自动化测试）。
- **禁止测试触碰真实环境**。`init_ok` 虽强制静态图抓帧和 `DoNothingInteraction`（点击为空操作），但个别方法绕过该保护直接操作系统窗口 —— 典型是 `wait_for_lobby` 内部调用 `bring_game_to_front()`/`_force_foreground()` 真实置前游戏窗口。被测流程会途经的这类方法必须 `patch.object(self.task, ...)` 拦截并断言其调用参数；同理必须 mock 的还有 `dismiss_all_popups`（真实抓帧+OCR 找弹窗，且内部会调用被 mock 的 `click_box`，把额外点击污染进断言列表，既造成误 FAIL 也拖慢测试）。
- **mock 必须保证被测循环可终止**。对 `while True` 型流程（如 `ArkTask._climb_battle` 爬塔循环），`wait_battle_finish`/`find_one` 用 `return_value` 固定返回「胜利+存在下一关」会让循环永不结束、测试挂死；用 `side_effect` 提供有限序列驱动流程走到收尾分支。
- **一切引用以源码为准，防改名漂移**。`patch.object` 的目标方法、`register_screen` 名与 `assert_screen` 参数必须与当前源码逐一核对；给任务 config 设值时键名必须与 `default_config` 完全一致。
- **保持快速确定**。被测流程内的 `self.sleep(...)` 一律 patch 掉；仅当用例本身就是在验证超时行为时才允许真实的短等待。
- **按影响面选择测试范围，避免动辄全量**。细小改动只跑直接相关的单个测试文件：改 `src/tasks/XxxTask.py` 跑对应 `tests.TestXxxTask`，改 `NikkeBaseTask` 的恢复协议跑 `tests.TestScreenRecovery` 与 `tests.TestBattleWait`，改判定层/注册表（`src/screens.py`、缓存、spec 语义）再加跑 `tests.TestFrameCache` 与 `tests.TestScreenRegistryIntegrity`，以此类推；一次一条命令只跑一个文件，通过即可继续下一步工作。仅当改动触及共享层（`src/config.py`、`src/patches/`、`assets/coco_annotations.json`、自定义 tab 等被多个任务依赖的部分），或在提交前做整体回归时，才需要全量验证。
- **全量验证必须逐文件独立进程**。CI 与 `run_tests.ps1` 都按「每个 `tests/*.py` 一个 Python 进程」运行；ok 单例 quit 后无法在同一进程内重建，一条命令连跑多个测试文件会产生大量假错误（典型如 `set_image` 报 `'NoneType' object has no attribute 'set_images'`），不能作为通过依据。


## 发布

- `.github/workflows/build.yml` 监听 `v*` tag：运行测试、执行 `python -m ok.update.inline_ok_requirements --tag <ref>`、通过 `ok-oldking/pyappify-action` 打包 EXE、创建 GitHub Release。`pyappify.yml` 定义了 China/Global 两个配置档。另有 `.github/workflows/docs.yml` 监听 `master`/`main` 分支 push（路径限定 `docs/**`、`mkdocs.yml`、`requirements-docs.txt`、`.github/workflows/docs.yml`），用于部署 mkdocs 文档站。
- 发布使用 `deploy` 技能，它通过 `.agents/skills/deploy/scripts/next_tag.py` 计算下一个版本号（注意：技能文档里写的路径是 `.agent`，实际路径是 `.agents`）。