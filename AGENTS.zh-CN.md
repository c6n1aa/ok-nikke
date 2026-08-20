# AGENTS.md（中文说明）

ok-nikke-maid 是基于 PyPI `ok-script` 库（ok-script-app 模板）构建的《NIKKE：胜利女神》Windows 客户端 Python GUI 自动化应用。本文是面向 AI 编码助手的项目说明与约束，英文副本见 `AGENTS.md`。

## 环境与命令

- Windows 平台下，所有终端命令一律用 PowerShell 7（`pwsh`）执行，不要切换到 cmd 或其他 shell，除非被明确要求。
- 这里的命令实际执行方式：opencode 全局配置（`~/.config/opencode/opencode.jsonc`）将 `"shell": "pwsh"` 设为短名（**不要**用 `C:\Users\<用户名>\AppData\Local\Microsoft\WindowsApps\pwsh.exe`，那是应用执行别名 reparse point，opencode 启动时的 `statSync` 会报 `EACCES` 失败；用 `pwsh` 短名，opencode 会通过 `which("pwsh")` 解析到真实安装路径，没有 `.cmd` 包装，也没有 `cmd.exe` 这一层）。opencode 通过 Node `spawn(cmd, [], {shell})` 执行每条命令，在 Windows 上会构造 `pwsh.exe -c "<命令>"`（不带 `-NoProfile`），所以完整命令串会原样到达 pwsh，只由 PowerShell 解析。因此：
  - 双引号字符串内的 `|`（管道符）是安全的（pwsh 看到的字面命令，例如 `Select-String -Pattern "test_|FAIL|OK|Ran|Error"` 可以正常工作）。旧的 cmd.exe 限制已不再适用。
  - 如果希望在字符串里传 `|` 时零插值、最清晰，仍然优先用**单引号**（`-Pattern 'test_|FAIL'`）——同样安全，还能避免 pwsh 的字符串插值问题。
  - 输出端到端为 UTF-8：`PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8` 已设置在 Windows **用户**级环境变量中（管道输出与 `chcp`/控制台代码页无关）。如果哪天看到中文乱码，先确认这两个环境变量还在、且 shell 配置没有被改回 `.cmd` 文件。
- 仅支持 Python 3.12。始终使用仓库本地虚拟环境，不要激活或使用全局 Python：`.\.venv\Scripts\python.exe`。
- 安装依赖必须加 `--no-deps`：`.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade`。因为 `pyside6-fluent-widgets` 声明了完整的 PySide6 元包，而本项目只需要 `pyside6-essentials`。`pyproject.toml`（`[project.optional-dependencies]`）是依赖源文件；每次 `pip-compile` 后都要再次删掉生成的 `pyside6`、`pyside6-addons` 条目。升级注意点（ok-script 2.x）：`pywin32` 必须保持 `>=306,!=312`（build 312 是坏版本；不要写成 `>=313` —— 该版本不存在，pip 会解析到 build 311，支持 Python 3.12）；`ok-d3dshot` 是新增的传递依赖，因打包用 `--no-deps` 跑 pip，所以必须显式列在 `requirements.txt` 里。
- 运行 GUI：`python main_debug.py`（调试模式）或 `python main.py`。必须在仓库根目录运行。
- 运行测试（在仓库根目录）：`python -m unittest tests.TestMain` 或 `.\.venv\Scripts\python.exe -m unittest tests.TestMain`，或通过 `run_tests.ps1` 运行全部测试。CI 会运行 `tests/` 下每个 `*.py` 文件，新增测试请放到 `tests/` 下。OCR 相关测试需要 onnxocr 模型（首次运行会自动下载）。标准测试写法见下文「测试」一节。
- 文档网站：`python -m pip install -r requirements-docs.txt`，然后 `python -m mkdocs serve` 或 `python -m mkdocs build --strict`。CI 要求 `--strict`。文档为中英双语（`docs/` 中文 + `docs/en/` 英文），必须保持结构对齐。

## 架构

- `src/config.py` —— 整个应用配置就是其中的 `config` 字典。任务注册为 `["模块路径", "类名"]`，一次性任务放 `onetime_tasks`，后台任务放 `trigger_tasks`。
- `src/config.py` 中的 `version = "dev"` 由 CI 在打 tag 打包时自动改写 —— 不要修改它。
- `src/tasks/MyBaseTask.py` 是项目基类，新任务应继承它而不是直接继承 `BaseTask`。`MyOneTimeTask` 为一次性任务，`MyTriggerTask` 为后台重复检查的 TriggerTask。自定义 GUI 标签页在 `src/ui/MyTab.py`。
- `src/patches/` 集中存放所有针对 venv 内 ok-script 的猴子补丁（在 `src/config.py` 顶部经 `apply_all()` 应用，因而在 `ok.OK(config)` 构造前运行）。每个模块暴露一个 `apply()` 且只负责一个主题 —— 项目内任何其他代码都不得自行修补 ok 包，新增补丁一律加到这里并注册进 `apply_all()`。`basic_options.py` 通过框架官方扩展点 `ok.util.GlobalConfig.register_config` 注册一个独立的「NIKKE 启动器」配置分区 —— 触发点在 `src/globals.py` 的 `Globals.__init__`（框架的 `my_app` 钩子），此时 `og.global_config` 已就绪，但早于设置 UI 枚举分区。这取代了旧版把启动器选项猴子补丁注入「基础设置」的做法。启动器路径持久化到 `configs/nikke_launcher.json`；文件选择框默认打开桌面目录由 `_patch_file_selector_initial_directory` 补丁支持 `initial_directory: 'desktop'`。该补丁仍会包装 `ok.util.GlobalConfig.create_basic_options` 以移除与本项目无关的选项、并调高 `Trigger Interval` 默认值。`start_controller.py` 把 `ok.ui.qt.StartController.StartController` 替换为 `NikkeStartController`，其 `start_device` 先做管理员检查、再判断 `nikke.exe` 游戏主进程是否已在运行（若在运行则跳过启动器），否则启动配置的启动器（`nikke_launcher.exe` 或 `.lnk`，自动解析），在可配置区域内 OCR 找到并点击启动按钮，最后等待游戏。没有直接启动回退：若未配置启动器且游戏未在运行，会提示用户配置启动器或手动启动游戏。`runtime.py` 禁用 OpenVINO 遥测，并在一次性任务执行期间保持游戏窗口前台。`tasks_tab.py` 把日常任务卡片置顶到任务 tab 顶部并在其下插入 `HorizontalSeparator` 分割线（`ExpandCardLayout` 增加了 `insertWidget(index, widget)` 辅助方法用于放置分割线），`TaskCard` 把日常卡片展开区过滤到只剩一行标准 `button` 配置行（`DailyTask.DAILY_SETTINGS_BUTTON_KEY`，其回调 `DailyTask.open_daily_settings` 切换到日常设置 tab）。后续新增配置类 UI 一律优先复用现有 `config_type` 类型（见下文「任务卡片/行是数据驱动的」条目），不要手写自定义控件。
- 以下为被 gitignore 的运行时目录（不要提交）：`configs/`（生成的配置 JSON）、`ok_tasks/`、`ok_templates/`（模板匹配素材）、`screenshots/`、`logs/`、`cache/`、`site/`、`dev_tools/`（临时脚本与生成的开发产物）。
- 一次性开发脚本及其生成的文件（如 OCR 批量报告、重命名映射表、XAL→coco 转换中间产物、备份）都放在仓库根目录的 `dev_tools/` 下 —— 绝不要放到系统临时目录。新增的临时脚本及其输出一律存到 `dev_tools/`，路径使用相对仓库根目录的写法，并保持该目录被 gitignore。
- 模板匹配的 coco 标注文件受版本控制，位于 `assets/coco_annotations.json`（`src/config.py` 的 `template_matching` 引用它）。
- **`assets/images/` 下的图片不是单纯的游戏截图**，而是压缩后的模板图集（atlas）。它们由标注的 2560x1440 截图生成：标注来源有两种 —— XAL（x-anylabeling）标注经 `dev_tools/import_xal.py` 导入，或使用本框架自带开发工具的截图标注（GUI「模板 tab → 保存压缩」），两条路径都走 ok 框架的 `FeatureSet.compress_copy_coco`/`compress_coco`：全部已标注特征按 (width,height) 分组、按 bbox 冲突贪心拼到 N 张白底大图（默认 2560x1440）上，只保留被标注区域，其余区域以白色填充。因此**不要把 `assets/images/*.png` 当作游戏截图去读画面/OCR/理解 UI**。配套的 `assets/coco_annotations.json` 是 COCO 格式标注：`images[].file_name` 指向 `images/*.png`，`annotations[].bbox` 是**图集上的坐标**（不是原游戏画面的坐标），`categories[].name` 为特征名；`FeatureSet` 通过 `src/config.py` 的 `template_matching` 读取它，并在运行时把坐标与图片一起缩放到当前游戏分辨率后匹配。相比之下，`assets/template/` 下是手动裁剪、无 coco 标注的小 UI 元素图（如公告铃铛、关闭按钮），一律用 `find_scaled_template` 匹配。
- 模板匹配：coco 里标注的模板由 `FeatureSet` 按当前游戏分辨率自动缩放（坐标和图片都会缩放）。对于 `assets/template/` 下手动裁剪、无法标注（位置不确定）的小模板，一律调用 `MyBaseTask` 的 `find_scaled_template(feature_name, template_path, ref_width, ref_height)` 辅助方法 —— 它会按当前游戏分辨率等比缩放模板（源截图默认 2560x1440，按路径+缩放比例缓存），再执行 `find_one(template=...)`。禁止把未缩放的原始模板直接传给 `find_one`/`find_feature`，否则在非 2560x1440 分辨率下匹配会失效。

## GUI 框架与样式约束

- UI 基于 PySide6（Qt 6.11）+ PySide6-Fluent-Widgets（`qfluentwidgets`），但 `requirements.txt` 只安装了 `pyside6-essentials` —— `pyside6`/`pyside6-addons` 是被刻意排除的。**禁止导入 Essentials 之外的 Qt 模块**（`QtMultimedia`、`QtWebEngineWidgets`、`QtCharts`、`QtSql`、`QtNetwork`、`QtOpenGL`、`QtPdf` 等），否则打包后的 EXE 启动时会直接崩溃。优先使用 `qfluentwidgets` 控件（`PrimaryPushButton`、`BodyLabel`、`StrongBodyLabel`、`SwitchButton`、`ComboBox`、`InfoBar`、`MessageBox`、`FluentIcon` 等），而不是裸 `QWidget`/`QPushButton` 加 `setStyleSheet`，这样明/暗主题切换与 Windows 系统强调色能自动生效。
- 主窗口是 ok-script 的 `ok.ui.qt.MainWindow.MainWindow`（`FluentWindow` 子类）；整套 GUI 框架都位于 venv 的 `ok` 包内，不在本仓库跟踪范围内。自定义标签页在 `src/ui/` 下继承 `ok.ui.qt.widget.CustomTab`，并通过 `src/config.py` 的 `custom_tabs` 列表注册（`["模块路径", "类名"]`，由 `MainWindow.addSubInterface` 消费）。禁止复刻或修补其他 `ok.ui.qt` 模块 —— 唯一允许的猴子补丁只有 `src/patches/` 里的那几处。
- 仓库内没有自定义 QSS。所有共享样式来自 ok-script 内置样式表（`ok/ui/qt/qss/{light,dark}/*.qss`，由 `ok.ui.qt.common.StyleSheet` 以 `:/qss/...` 引用）以及 qfluentwidgets 自身的主题系统。**新增代码不要添加 `.qss` 文件、硬编码颜色或控件级 `setStyleSheet`。** 需要套用共享外观时，复用内置样式表已支持的对象名（`#card`、`#configRow`、`#view`、`#titleLabel`、`#contentLabel`、`#configContentFrame`）。
- 主题为 `Theme.AUTO`（跟随 Windows 明/暗设置），主窗口会把系统强调色同步到 `qconfig.themeColor`（`_sync_system_accent_color`）。新 UI 不得假定某一主题：应使用 qfluentwidgets 的主题感知颜色（`ThemeColor`、`isDarkTheme()`），不要用裸 `QColor`/十六进制字面量。
- 复用 `ok.ui.qt.common.design_system` 的共享布局令牌与辅助函数：`DesignToken`（8 点网格 —— PAGE_MARGIN 24、CARD_PADDING 16、ROW_MIN_HEIGHT 56、CONTROL_WIDTH 180 等）、`configure_page_layout`、`configure_card_layout`、`configure_row`、`control_width()`。用 `Tab.add_widget`/`add_card` 和 `ok.ui.qt.widget.Card` 容器来组织页面。不要自创边距、间距或控件宽度。
- 图标：界面图标统一用 `FluentIcon`（或 ok-script 的 `OKIcon`）。应用窗口图标固定为 `icons/icon.png`（`src/config.py` 的 `gui_icon`）—— 保持该文件名不变，尽量避免新增图片素材。
- 任务卡片/行是数据驱动的，不是控件代码：任务页根据任务的 `name`、`description`、`default_config`、`config_description`、`config_type`、`group_name`/`group_icon` 自动渲染。要改用户看到的内容，改这些任务属性即可。`config_type` 在 `ok.ui.qt.tasks.ConfigItemFactory` 中映射为具体控件（`drop_down`、`multi_selection`、`text_edit`、`line_edit`、`file_selector`、`button`/`buttons`；bool→开关、int→数字框、float→小数框、str→单行/多行文本框、list→多选列表项）—— 新增 `config_type` 类型时必须同步添加对应的工厂分支。`src/tasks/MyOneTimeTask.py` 是各类配置控件的标准范例（覆盖每个工厂分支，含 `button`/`buttons` 及回调）—— 新增任何配置 UI 时先参考它，优先复用已有 `config_type` 类型，而不是手写自定义行控件；当卡片只需展示部分配置时，行仍用标准 `config_type` 渲染，再在受控的 `src/patches/tasks_tab.py` 补丁里做过滤。
- 启动器选项**不再**注入「基础设置」—— 它独立成「NIKKE 启动器」分区（磁盘文件 `configs/nikke_launcher.json`，由 `src/globals.py` 触发的官方 `GlobalConfig.register_config` API 创建）。若要在「基础设置」新增其他自定义行，仍通过 `src/patches/basic_options.py` 的 `_patch_create_basic_options` 猴子补丁（它包装 `ok.util.GlobalConfig.create_basic_options`）—— 不要直接改 `ok.util.GlobalConfig`。
- GUI 改动用仓库根目录下的 `python main_debug.py`（或 `python main.py`）实际运行验证；项目没有自动化 GUI 测试套件。`i18n/` 翻译目录不要动。

## 约定（与默认行为不同）

- 任务 UI 字符串（`name`、`description`、`default_config` 键与值、`config_description`、`config_type` 选项）目前直接写简体中文，不做 i18n 文本处理。GUI 会对每个显示的字符串调用 `og.app.tr()`，目录中查不到时原样返回，因此中文可直接显示。`i18n/<locale>/LC_MESSAGES/ok.{po,mo}` 目录保留（目前只有 `zh_CN`、`en_US`，模板示例 `MyOneTimeTask` 仍依赖它）；以后若恢复国际化，用 `$ok-script-i18n` 技能同步目录并重新编译 `.mo`。
- 使用 `.agents/skills/` 下的内置技能：任务类用 `ok-script-tasks`；`run()` 自动化逻辑用 `ok-script-codegen`（其输出要求每行代码都带中文行内注释）；翻译目录用 `ok-script-i18n`；运行 Python 命令用 `use-local-venv`。
- 点击节奏一律使用 `wait_click_feature`/`click_box`/`click` 内置的 `after_sleep` 参数（点击后的固定等待）。不要在步骤之间手动加 `time.sleep`/`sleep`，也不要覆写 `click_box` —— 该参数已经覆盖了等待。
- 界面识别与失败恢复（详见 `docs/screen-and-recovery.md`）：`MyBaseTask` 提供界面识别注册表（`register_screen`、`current_screen`、`is_screen`、`wait_screen`、`assert_screen`）与失败恢复协议（`save_failure_screenshot`、`_recover_to_lobby`、`try_step`）。注册界面是**可选**的，仅当任务确实需要识别该界面（`is_screen`/`wait_screen`/`assert_screen`）或把它作为恢复目标时才注册；好友、邮箱等临时弹层/弹窗页面以及只点击几次的简单任务一般不需要注册。大厅 `lobby` 已默认注册为恢复目标，不要重复注册。每个「从大厅出发、自行完成导航」的入口方法（子流程）用 `try_step(...)` 包**一层**即可，方法内部步骤不要逐个包（失败会冒泡到外层，回大厅后整个子流程重跑）。禁止手写临时重试/恢复逻辑、绕过 `try_step`，或绕过 `_recover_to_lobby` 硬编码「按坐标回大厅」。界面判定优先用 coco 模板特征；仅在没有稳定模板时才用 OCR 关键词，并尽量限定 `ocr_box`。失败截图统一存到 `screenshots/failure/`。调整恢复协议或判定方式时，同步更新 `tests/TestScreenRecovery.py`。
- 完成状态：任务需要记录「本周期已完成」状态（用 `is_done`/`mark_done`/`clear_done`）时，声明类属性 `done_keys = {key: period}`（例如 `HarvestTask.done_keys = {"harvest": "day"}`、`ShopTask.done_keys = {"shop_general": "day", "shop_arena": "day", "shop_recycling": "week"}`）。基类据此提供 `is_completed()`（所有 done_keys 都完成才返回 True）与 `clear_done_all()`；完成口径特殊时覆盖 `is_completed()`（例如 `ShopTask` 只统计用户开启的子商店）。这两个方法自动接入 UI：「日常设置」tab 每个子任务卡片头部显示状态图标（切 tab 时刷新，完成→`FluentIcon.COMPLETED`，未完成→卡片默认图标）；`src/patches/tasks_tab.py` 会给所有 `done_keys` 非空的 `MyBaseTask` 卡片在 Operation 行、`Reset Config` 前注入固定的「重置完成状态」按钮（点击调用 `clear_done_all()`）。纯编排任务（自身从不 `mark_done`，如 `DailyTask`）不定义 `done_keys`。
- 自动战斗等待：需要进入自动战斗并等待结果的任务使用基类 `wait_battle_finish(time_out=240, check_interval=2)`。它采用节流轮询（每 `check_interval` 秒才抓一帧做单次模板匹配），战斗时长约 10 秒~3 分钟不定，不会用忙轮询长时间与游戏抢 CPU；且**只检测不点击**，返回 `("success", esc_box)` / `("failed", failed_back_box)` / `(None, None)`，战斗结束后的动作（点 `esc` 确认、连续战斗的胜利界面点「下一关」等）由调用方决定。长时间等战斗不要用 `wait_feature`/`wait_ocr` 忙轮询。新增战斗结果界面时，核对 `assets/coco_annotations.json` 里的 `battle_finish_*` 特征。
- 提交信息语言与最近一次非 merge 提交的标题保持一致。

## 测试

- 任务测试用 `unittest` 编写，继承 `ok.test.TaskTestCase`，并设置 `task_class` 指向被测任务（例如 `from src.tasks.MyTask import MyTask`）。标准参考见 `docs/after_quick_start/README.md`（§3 自动化测试）。
- 核心技术：`self.set_image(<路径>)` 把屏幕输入固定为一张静态图片，从而创造稳定、可复现的运行环境，用于断言识别、点击、OCR 等行为。
- 复现用户报告的问题：把用户上传的截图作为测试图（如 `self.set_image('tests/user_screenshots/user_bug_report_01.png')`），调用出错的精确方法，并断言修复后的行为符合预期。
- 运行测试：`run_tests.ps1` 运行 `tests/` 下全部测试；单个文件或方法可在 PyCharm 中右键运行。在 PyCharm 中，运行/调试配置的「工作目录」必须设为仓库根目录，否则 `tests/images/` 等相对路径无法解析。

## 发布

- `.github/workflows/build.yml` 监听 `v*` tag：运行测试、执行 `python -m ok.update.inline_ok_requirements --tag <ref>`、通过 `ok-oldking/pyappify-action` 打包 EXE、创建 GitHub Release。`pyappify.yml` 定义了 China/Global 两个配置档。
- 发布使用 `deploy` 技能，它通过 `.agents/skills/deploy/scripts/next_tag.py` 计算下一个版本号（注意：技能文档里写的路径是 `.agent`，实际路径是 `.agents`）。