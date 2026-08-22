# ok-script 1.0.189 → 2.0.2 升级：破坏性变更与项目风险

> 创建日期：2026-08-19
> 配合文档：`docs/framework-upgrade-plan.md`（升级执行计划，本文是其风险视角的补充）
> 验证依据：基于 `.venv` 中实际安装的 `ok-script==2.0.2` 源码与运行时检查（2026-08-19 核对）
> 适用分支：`upgrade-framework`

本文不重复升级操作步骤，只聚焦**这次升级给现有项目带来的问题、以及后续开发（尤其是再次升级 ok-script）会踩的坑**。所有结论已在 2.0.2 环境下核对；标「待运行时验证」的项是静态分析无法覆盖、需游戏环境实测的。

---

## 0. 一句话结论

代码层面迁移已落地（13 处 `ok.gui.*` → `ok.ui.qt.*`，config 迁到 `gui` 新格式，依赖更新，无残留）。**真正的风险不在「能不能跑起来」，而在「项目对 ok 框架内部做了大量运行时猴子补丁，这些补丁与框架版本强绑定、且部分是静默失败」**——这是后续每次升级 ok-script 都必须重做的成本，也是本次大跨度升级（1.0.189 → 2.0.2）暴露出来的最大隐患。

---

## 1. Import 路径变更（ok.gui → ok.ui.qt）

- **兼容 shim 仍在**：2.0.2 的 `ok/gui/__init__.py` 通过 `MetaPathFinder` 把 `ok.gui.X` 重定向到 `ok.ui.qt.X`，且用 `sys.modules[alias] = 目标模块对象`，保证新旧路径下拿到**同一个类对象**（不会重复定义）。所以旧 `from ok.gui.xxx import xxx` 在 2.0.2 下仍能跑。
- **已迁移完成**：`grep -rn "ok\.gui\." src/` 已无残留（5 个文件、13 处 import 全部改为 `ok.ui.qt.*`）。
- **风险点**：
  1. shim 是**过渡兼容层**，框架未来版本可能移除；新代码一律写 `ok.ui.qt.*`，不要回头用 `ok.gui.*`。
  2. **模块别名机制是补丁生效的前提，也是最易静默失效的点**（见 §5.3）。`ok.ui.qt.StartController` 内部 `sys.modules[__name__] = ok.core.start_controller`，即它**就是** `ok.core.start_controller` 模块对象。项目的 `start_controller.py` 补丁执行 `start_controller_module.StartController = NikkeStartController`，由于 `start_controller_module` 就是该核心模块，框架内部 `from ok.ui.qt.StartController import StartController`（或等效路径）拿到的也是被替换后的类。**一旦未来框架改为直接 `from ok.core.start_controller import StartController` 并绕开 `ok.ui.qt` 别名、或在别处缓存了类引用，替换就会静默不生效**——启动器自动化退回框架默认逻辑且不报错。

---

## 2. API 签名变更

| API | 1.0.189 | 2.0.2 | 影响与现状 |
|---|---|---|---|
| `Tab.__init__` | 接受 `layout_class` 自定义布局 | `Tab.__init__(self)` 只创建 `QVBoxLayout`，**不再接受 `layout_class`** | 旧代码若传 `layout_class` 直接 `TypeError` 崩溃。已规避：`DailyTab.__init__` 改为「先移除 `self.view` 旧布局 → 再挂 `ExpandCardLayout`」手动管理布局。**后续自定义 Tab 不能再依赖 `layout_class`** |
| `StartController.start_device(initial_refresh_done=False)` | 签名一致 | 签名逐字一致（2.0.2 `ok/core/start_controller.py`） | 方法可重写；但**基类从 `QObject` 改为普通类**，信号机制移到 `ok/core/events.py` 的 `communicate` 单例，不再依赖 Qt 元对象 |
| `TaskExecutor.next_frame(time_out=6)` | 签名一致 | 签名一致（2.0.2 `ok/task/TaskExecutor.py:248`） | 签名一致 ≠ 行为一致，需运行时验证（见 §6 待验证项） |
| `ExpandCardLayout.insertWidget` | 有 | **无原生 `insertWidget`**（qfluentwidgets `ExpandLayout` 本身也没有） | 项目补丁仅在「`not hasattr(ExpandCardLayout,'insertWidget')」时注入自定义 `insertWidget`（见 §5.1） |

> 说明：`ok.task` / `ok.feature` / `ok.util` / `ok.device` 等任务侧路径在 1.x→2.0 未变，`BaseTask` / `TriggerTask` / `Box` / `WaitFailedException` / `calculate_colorfulness` / `get_box_by_name` 等任务 API 原样保留，任务代码（`src/tasks/*`）无需改动。

---

## 3. Config 格式变更（gui config）

- **旧格式**：顶层 `'use_gui': True` + 顶层 `'window_size': {...}`。
- **新格式**：`'gui': {'type': 'qt' | 'web', 'window_size': {...}, 'launch_mode'（仅 web 需要）}`。
- **兼容性**：2.0.2 的 `ok/core/ui_config.py:resolve_ui_config()` 同时支持两种写法（`use_gui` 走 legacy 分支）。项目 `src/config.py` 已迁移到新格式。
- **风险点**：
  1. 新格式下 `gui.type` **必须是 `'qt'` 或 `'web'`**，否则启动即 `ValueError("gui.type must be 'qt' or 'web'")`。
  2. `window_size` 若遗漏，会回退到默认值 `{1200×800, min 1200×800}`；项目当前显式指定了更小的最小尺寸，需注意不要丢字段。
  3. legacy 分支是临时兼容，若未来框架删除该分支，仍用旧格式的 config 会直接失效——新格式是唯一正路。
  4. Web UI（`type: 'web'` + `launch_mode: pywebview/browser/server`）本期未启用，但 2.0 已内置支持，未来若启用需引入 `web_main*.py` / `requirements-web.txt` / `pyappify.yml` 的 web profile，与当前 Qt 路径是两条独立依赖集。

---

## 4. 依赖变更

`requirements.txt` 已由 `pip-compile` 从 `pyproject.toml` 的 `[project.optional-dependencies].qt` 重新生成（extras profile：`ok-script[adb,default,ocr,qt]==2.0.2`）。关键变化：

- **新增 `ok-d3dshot==0.1.5`**（ok-script 2.0 的 `[default]` extra 新引入），带来传递依赖 `comtypes`（与 `pycaw` 重复但无冲突）。首次重建 venv 体积增大；**`--no-deps` 打包必须把 `ok-d3dshot` 及其传递依赖显式列入**，否则运行时 `ImportError`。
- **`pywin32` 必须排除 312（broken release）**，当前锁定 `pywin32==311`。注意 PyPI 上 pywin32 可用 build 为 `306–312`，**313 不存在**；Python 3.12 只能用 build 311。误写 `pywin32>=313` 会解析失败。
- **Python 版本锁定**：`requires-python = ">=3.12,<3.13"`，**不能跨大版本**（pywin32 build 选择也受其约束）。
- **新增传递依赖**（关注即可，已自动列入）：`pysidesix-frameless-window==0.8.2`（fluent-widgets 拉入）、`openvino-telemetry==2025.2.0`、`shapely==2.1.2`（onnxocr 拉入）、`pillow`/`packaging` 等。
- **`--no-deps` 打包约束**：本项目与模板 `pyappify.yml` 均用 `pip_args: "--no-deps"`，pip 不解析传递依赖，因此 `requirements.txt` 必须显式列出**全部**传递依赖。`pip-compile` 后务必 diff 检查无遗漏（尤其 §4 的 `ok-d3dshot` 链）。
- **依赖来源单一化**：删掉旧的 `requirements.in`，以 `pyproject.toml` 为唯一源 `pip-compile pyproject.toml -o requirements.txt`，避免两套源漂移。

---

## 5. 其他破坏性变更 / 隐性风险（重点：猴子补丁脆弱性）

这是本次升级暴露、且对**后续开发影响最大**的部分。项目通过 `src/patches/*` 在 `ok.OK(config)` 构造前对 ok 框架内部做运行时猴子补丁（`apply_all()` 在 `src/config.py` 顶部调用）。这些补丁与框架 2.0.2 的内部实现深度耦合，每升级一次框架都要逐点重验。

### 5.1 `tasks_tab.py` 补丁（最高危，依赖框架 + qfluentwidgets 私有结构）

- **`insertWidget` 注入依赖 qfluentwidgets 的 name-mangled 私有属性**：补丁的 `_insert_widget` 直接读写 `self._ExpandLayout__widgets` / `self._ExpandLayout__items`。运行时已确认 qfluentwidgets `ExpandLayout` 确实以这两个名字存储卡片列表（`_widgets`/`_items` 在类中以双下划线 `self.__widgets` 声明，被 Python 改写为此名）。**问题**：这是 qfluentwidgets 内部实现细节，任何 qfluentwidgets 升级若重命名/重构这两个属性，`layout.insertWidget(...)` 调用处会抛 `AttributeError`，导致「日常卡片置顶 + 分割线」功能失效，且**只在运行时触发、导入期不报错**。
- **`daily_card` 补丁依赖 `TaskCard`/`ConfigCard` 内部布局结构**：直接操作 `self.viewLayout`、`self.config_widget_by_key`、`self.config_widgets`、`self.config_keys`、`self._adjust_config_content_size()`。这些全是框架内部，随框架重构极易失效。
- **`daily_pin` 补丁依赖 `TaskTab` 内部属性**：`self.taskCardLayout`、`self.task_info_container`、`self.card_widgets`（均为非公开 API，框架可随时改名）。
- **`reset_done_button` 补丁依赖 `ConfigContentMixin.add_buttons` 的布局约定**：通过定位 `self.reset_config` 父控件的 `QHBoxLayout` 来插入按钮；若框架调整 Operation 行结构，插入位置失效。
- **结论**：这四个补丁几乎把「任务列表渲染」的整套内部实现当成了稳定契约。2.0.2 下已验证可用，但**没有一处是框架承诺的扩展点**。

### 5.2 `basic_options.py` 补丁（依赖 GlobalConfig 返回对象契约）

- `_patch_create_basic_options` 现在**只**负责两件事，二者均无官方替代 API、仍需补丁：① 调高 `Trigger Interval` 默认值到 100ms；② 从 Basic Options 移除与本项目无关的项（`_BASIC_OPTIONS_REMOVE_KEYS`）。它依赖 `ok.util.GlobalConfig.create_basic_options` 返回对象的 `.default_config` / `.config_description` / `.config_type` 字段与调用签名 `(enable_blur=False)`。
- **已改造成官方扩展点（2026-08-19）**：原补丁中「把启动器路径选项注入 Basic Options」的部分已删除，改为用框架官方 `GlobalConfig.register_config(ConfigOption(...))` 注册独立的「NIKKE 启动器」配置分区。注册时机在 `src/globals.py` 的 `Globals.__init__`（框架 `my_app` 扩展点），此时 `og.global_config` 已就绪、且早于设置 UI 枚举分区。此项不再依赖 `create_basic_options` 的猴子补丁，且磁盘持久化由 `Config` 构造自动处理。`start_controller._get_launcher_path` 改为调用 `basic_options.get_launcher_path()` 读取该分区。
- `_patch_file_selector_initial_directory` 补丁 `LabelAndFileSelector._initial_directory`（单下划线「受保护」方法），用于支持文件选择器 `initial_directory:'desktop'`。框架改其实现即失效，暂无官方替代。

### 5.3 `start_controller.py` 补丁（静默失败风险最高）

- `apply()` 执行 `start_controller_module.StartController = NikkeStartController`，依赖 §1 所述的 `ok.ui.qt.StartController` 模块别名机制。**若该机制在未来版本失效（见 §1 第 2 点），NikkeStartController 不会被采用，启动器自动化退回框架默认逻辑，且全程不报错**——这是最难排查的一类故障。
- `NikkeStartController` 重写了 `start_device` 及大量辅助方法（OCR 找启动按钮、窗口稳定判定、bitblt 截图等），与框架 `StartController` 实现高度耦合。框架升级若改动父类流程/方法名/参数，需逐个重新对齐。
- 依赖 `communicate.starting_emulator` / `communicate.restart_admin` 信号、`ok.device.capture_methods.bitblt_utils`、`ok.util.window` / `ok.util.process`。任一信号或工具函数改名，补丁的 `emit`/`connect` 会失败。

### 5.4 `runtime.py` 补丁（依赖执行器内部调用时机）

- `_patch_executor_foreground` 包装 `TaskExecutor.next_frame`，在取帧前把游戏窗口置前（依赖 `pynput` 前台）。若框架改为不调用 `next_frame`、改其签名、或换用其他取帧路径，前台保持逻辑失效。
- `_patch_openvino_telemetry` 直接改写 `openvino_telemetry.backend.backend_ga4._send_func` / `backend_ga.GABackend.send`，是**对第三方包内部属性**的猴子补丁，openvino 升级改实现即失效。

### 5.5 补丁整体脆弱性

- `apply_all()` 必须在 `ok.OK(config)` 构造前执行（`src/config.py` 顶部），且依赖 `src/patches` 内各模块的 import 路径。若框架未来重命名 `ok.ui.qt.*` 下模块（虽然 2.0 刚迁移完、短期稳定），补丁会在启动早期 `ImportError`。
- 补丁目前**没有任何启动期自检**：例如未断言关键内部属性存在、未断言 `og.start_controller.__class__ is NikkeStartController`、未断言 `ok.ui.qt.StartController is ok.core.start_controller`。一旦静默失效，只能在「启动器不接管 / 任务列表渲染异常」时才被发现。

---

## 6. 手工验收清单（运行时验证，静态分析无法覆盖）

> 适用：每次升级 ok-script 后、以及本分支首次合并到 dev 后都应完整跑一遍。
> 前置条件：在仓库根目录、用项目 venv 运行 `.\.venv\Scripts\python.exe main_debug.py`（以管理员身份，否则启动器流程会提示提权）。
> 每一项都给出「前置 → 步骤 → 期望 → 判定标准 → 关联的脆弱补丁」。勾选式记录用 `[ ]` / `[x]`。

### 6.1 补丁生效前提（最先做，5 分钟，无需游戏）

- [ ] **A1 模块别名一致（start_controller 补丁生效前提）**
  - 步骤：`.\.venv\Scripts\python.exe -c "import ok.ui.qt.StartController as m, ok.core.start_controller as c; assert m is c"`
  - 期望：命令静默成功（无 `AssertionError`、无 traceback）。
  - 判定：`m is c` 必须为真，否则 `start_controller.py` 的类替换会在框架内部不生效（静默失效）。
  - 关联：§5.3 `start_controller.py`。

- [ ] **A2 NikkeStartController 实际被采用（非静默失效）**
  - 步骤：启动 `main_debug.py`，待主窗口出现后，在 Python 控制台执行 `og.start_controller.__class__.__name__`
  - 期望：返回 `'NikkeStartController'`（不是 `'StartController'`）。
  - 判定：若返回 `'StartController'`，说明别名机制失效或 `apply()` 未执行，启动器自动化会退回框架默认逻辑且不报错——**阻断性失败**。
  - 关联：§5.3。

- [ ] **A3 启动期自检（建议补齐，见 §7.2）**
  - 步骤：确认 `og.start_controller.__class__ is NikkeStartController`、且不抛任何导入期错误。
  - 期望：App 正常启动到主窗口，无红色异常日志。
  - 判定：若补丁在 `apply_all()` 或 `Globals.__init__` 抛异常，应在启动早期就报错（目前未加自检，属 §7 待办）。

### 6.2 启动器自动化（风险最高，需游戏 + 真实启动器，~15 分钟）

- [ ] **B1 管理员提权提示**
  - 步骤：非管理员启动 `main_debug.py`。
  - 期望：弹出 UAC 提示 / 或界面提示「PC版本需要管理员权限，请以管理员身份重新启动本程序」。
  - 判定：未以管理员运行时不应直接尝试启动游戏。

- [ ] **B2 游戏已运行时跳过启动器（不重复启动）**
  - 步骤：先手动打开 NIKKE 到登录界面（进程 `nikke.exe` 已在），再在 App 点「启动」。
  - 期望：直接等待游戏就绪，不弹启动器、不重新拉起启动器。
  - 判定：没有「已有一个 NIKKE 进程」冲突报错，且日志显示 `game main process already running, skip launcher`。

- [ ] **B3 冷启动走启动器（OCR 找启动按钮 + 等待稳定）**
  - 步骤：关闭游戏，确保 `NIKKE 启动器` 配置里已选好 `nikke_launcher.exe`（见 §6.5 迁移验证），点「启动」。
  - 期望：启动器被拉起 → 窗口稳定判定 → OCR 在 `LAUNCHER_BUTTON_REGION`(0.05,0.83,0.30,0.93) 找到「启动」按钮 → 点击 → 等待游戏窗口。
  - 判定：最终进入游戏且 `communicate.starting_emulator` 完成；若卡在「启动器启动按钮未找到」，检查区域坐标与 OCR 是否识别到「启动」二字。

- [ ] **B4 未配置启动器时的兜底提示**
  - 步骤：清空 `NIKKE 启动器` 分区里的路径，点「启动」。
  - 期望：弹提示「未配置启动器路径，请在设置->基础设置中选择启动器，或手动启动游戏」（实际文案在 `start_controller.py`，确认与 UI 一致）。
  - 判定：不崩溃、不无限卡在 loading。

### 6.3 任务执行（前台保持 + 不卡帧，~10 分钟）

- [ ] **C1 一次性任务前台保持（`runtime` 补丁）**
  - 步骤：把 NIKKE 窗口切到后台（别的窗口盖住），启动一个一次性任务（如 DailyTask 的某个子任务）。
  - 期望：`runtime._patch_executor_foreground` 会把游戏窗口拉回前台（`_ensure_game_foreground` 节流每秒一次）。
  - 判定：任务不因「后台时 `can_capture` 为 False」而卡在 `next_frame` 超时；任务正常完成。
  - 关联：§5.4 `runtime.py` `_patch_executor_foreground`。

- [ ] **C2 `TaskExecutor.next_frame` 行为（`time_out=6` 签名一致 ≠ 行为一致）**
  - 步骤：跑一个耗时 >30s 的一次性任务，观察日志是否有频繁的 `ensure game foreground` 节流提示（应约每秒一次，而非每帧）。
  - 期望：取帧正常、任务不卡帧、不报 `next_frame` 超时。
  - 判定：签名一致已静态确认（2.0.2:248），此处验证运行时行为。
  - 关联：§5.4 `runtime.py` + §2 表「TaskExecutor.next_frame」。

### 6.4 任务列表 / 日常设置 UI 渲染（tasks_tab 四个补丁，~10 分钟）

- [ ] **D1 日常卡片置顶 + 分割线**（`_patch_tasks_tab_daily_pin`）
  - 步骤：打开「任务」Tab。
  - 期望：DailyTask 卡片排在最顶部，「任务信息」容器之后、其余任务卡片之前，且下方有一条 `HorizontalSeparator` 分割线；刷新列表（如改配置触发 `task_list_updated`）后分割线不重复累积。
  - 判定：布局与 §5.1 描述一致；重复刷新不产生多条分割线（`_daily_separator` 复用逻辑）。

- [ ] **D2 日常卡片展开只留跳转按钮**（`_patch_tasks_tab_daily_card`）
  - 步骤：展开 DailyTask 卡片。
  - 期望：展开区只剩「日常设置」导航按钮（由 `DailyTask.DAILY_SETTINGS_BUTTON_KEY` 渲染），开关行与 Operation 行已移除。
  - 判定：点击该按钮能切到「日常设置」Tab（`DailyTask.open_daily_settings`）。

- [ ] **D3 切回任务 Tab 同步 config**（`_patch_tasks_tab_sync_config_on_show`）
  - 步骤：在「日常设置」Tab 改某个子任务开关 → 切回「任务」Tab 看 DailyTask 卡片。
  - 期望：卡片控件值与 `task.config` 当前值同步（不显示过期值）。

- [ ] **D4 重置完成状态按钮**（`_patch_tasks_tab_reset_done_button`）
  - 步骤：对一个有 `done_keys` 的 NikkeBaseTask（如 HarvestTask，先让它标记完成）→ 展开卡片。
  - 期望：Operation 行、`Reset Config` 之前出现「重置完成状态」按钮（`FluentIcon.SYNC`）。
  - 判定：点击后弹 InfoBar「已重置完成状态」，`clear_done_all()` 生效，状态图标复位。

- [ ] **D5 任务列表整体渲染不崩**（`_patch_tasks_tab_*` 依赖 `TaskCard`/`ConfigCard` 内部）
  - 步骤：浏览所有任务卡片，展开/收起若干次。
  - 期望：无 `AttributeError`/布局错乱；重点关注 qfluentwidgets 升级是否会改 `_ExpandLayout__widgets/_ExpandLayout__items`（§5.1 的 `insertWidget` 私有属性依赖）。

### 6.5 配置分区迁移与持久化（basic_options 改造，~5 分钟）

- [ ] **E1 旧启动器路径自动迁移**
  - 步骤：升级前若旧的 `configs/Basic Options.json` 含「启动器路径」非空值，升级后首次启动应自动搬到 `configs/nikke_launcher.json`（UI 显示「NIKKE 启动器」分区）。
  - 期望：`configs/nikke_launcher.json` 内容含 `{"启动器路径": "<旧值>"}`；旧的 `Basic Options.json` 里该键被框架 `verify_config` 自动裁剪。
  - 判定：无需用户重新选启动器即可直接 B3 冷启动。

- [ ] **E2 新分区在设置 UI 出现且可保存**
  - 步骤：打开「设置 → NIKKE 启动器」，改/清空路径并保存，重启 App。
  - 期望：改动持久化到 `configs/nikke_launcher.json`；分区名是「NIKKE 启动器」（中文），磁盘文件名是 `nikke_launcher.json`（英文，避免中文路径）。
  - 判定：重启后值仍在；`_migrate_legacy_launcher_path` 幂等，不会覆盖已迁移值。

- [ ] **E3 文件选择器默认桌面目录**（`_patch_file_selector_initial_directory`）
  - 步骤：在「NIKKE 启动器」点文件选择框。
  - 期望：默认打开到桌面目录（`initial_directory: 'desktop'`），方便直接选桌面 `.lnk` 快捷方式。
  - 关联：§5.2 `basic_options._patch_file_selector_initial_directory`。

### 6.6 overlay 关闭 / 帧取消修复（2.0 commits，~10 分钟）

- [ ] **F1 任务结束后 overlay 正常退出**
  - 步骤：跑一个会显示 overlay 的任务到结束。
  - 期望：overlay 随任务结束正常关闭，无残留半透明层、无「帧取消」报错。
  - 判定：2.0 的 overlay 修复（`eaf8967` / `91fdda5`）在本项目实际生效，不回退到 1.x 的残留行为。

### 6.7 OpenVINO 遥测退出挂死（runtime 补丁，~10 分钟，需断网）

- [ ] **G1 断网退出不卡死**
  - 步骤：断开网络（或屏蔽 openvino telemetry 上报），正常退出 App（关闭窗口 / 结束进程）。
  - 期望：进程在数秒内干净退出，不卡在 `atexit`/非 daemon 线程 join。
  - 判定：`runtime._patch_openvino_telemetry` 在 2.0.2 仍把 `backend_ga4._send_func` / `backend_ga.GABackend.send` 替换为 no-op，避免无超时 `urlopen` 挂死。
  - 关联：§5.4 `runtime.py` `_patch_openvino_telemetry`（这是第三方 `openvino_telemetry` 内部补丁，openvino 升级即可能失效）。

### 6.8 打包（发布前，--no-deps，~20 分钟，CI 或本地）

- [ ] **H1 `ok-d3dshot` 链不缺包**
  - 步骤：本地用 `pyappify.yml` 构建 EXE（或等 CI `build.yml`），启动打包产物。
  - 期望：启动不报 `ModuleNotFoundError: ok_d3dshot` / `comtypes` 等。
  - 判定：`requirements.txt`（`--no-deps` 不解析传递依赖）已显式列全 `ok-d3dshot` 及其传递依赖（comtypes 等）；升级时若 pip-compile 新增传递依赖务必补进 requirements。
  - 关联：§4 依赖变更。

- [ ] **H2 Python / pywin32 版本合规**
  - 步骤：确认打包环境 Python 3.12、`pywin32==311`（非 312）。
  - 期望：`requires-python = ">=3.12,<3.13"`，`pywin32` 排除 312。
  - 判定：打包节点与 `pyproject.toml` 一致；误装 312 会触发框架标记过的 broken release。

### 6.9 验收结论记录模板

```
验收日期：____
环境：Windows ___, Python 3.12, ok-script 2.0.2, NIKKE 客户端版本 ___
A1 模块别名一致        [ ]
A2 NikkeStartController [ ]
A3 启动期自检          [ ]
B1 管理员提权          [ ]
B2 已运行跳过          [ ]
B3 冷启动启动器        [ ]
B4 未配置兜底          [ ]
C1 前台保持            [ ]
C2 不卡帧              [ ]
D1 置顶+分割线         [ ]
D2 只留按钮            [ ]
D3 切回同步            [ ]
D4 重置完成状态        [ ]
D5 列表不崩            [ ]
E1 旧值迁移            [ ]
E2 新分区持久化        [ ]
E3 桌面默认目录        [ ]
F1 overlay 退出        [ ]
G1 断网退出            [ ]
H1 ok-d3dshot 打包     [ ]
H2 版本合规            [ ]
未通过项 / 备注：____
```

## 7. 对未来开发 / 再次升级的建议

1. **把 `src/patches/*` 视为「与 ok-script 版本强绑定」的代码**：每次升级 ok-script（哪怕小版本）都要重跑 §5 + §6 的逐点验证，并把验证结果记入升级清单。本次 1.0.189 → 2.0.2 跨度大、风险高，建议此后保持小步升级节奏。
2. **给补丁加启动期自检**（`src/patches/__init__.py` 的 `apply_all()` 内或 App 启动后）：
   - 断言模块别名一致：`ok.ui.qt.StartController is ok.core.start_controller`；
   - 断言 `og.start_controller.__class__ is NikkeStartController`；
   - 断言 `ExpandCardLayout` 实例存在 `_ExpandLayout__widgets` / `_ExpandLayout__items`（或改用更稳的插入方式）；
   - 断言 `TaskTab` 实例存在 `taskCardLayout` / `task_info_container`。
   让「静默失效」变成「启动即报错」，缩短排查时间。
3. **优先用框架提供的扩展点，减少猴子补丁**：`basic_options` 中启动器选项已改用官方 `GlobalConfig.register_config`（`src/globals.py` 的 `my_app` 扩展点触发）；`custom_tabs` / `config_type` 也是官方扩展点。对「任务列表渲染 / 启动控制器 / 文件选择器默认目录」这类深度耦合补丁，考虑是否能在框架侧提 PR 增加官方 hook，而非长期本地补丁。
4. **不要依赖 `ok.gui` 兼容 shim**：新代码一律 `ok.ui.qt.*`；若未来框架删除 shim，本仓库已无 `ok.gui` 残留，不受波及。
5. **依赖锁定纪律**：始终以 `pyproject.toml` 为唯一源 `pip-compile`；`--no-deps` 打包前必 diff 检查（重点 `ok-d3dshot` 链）；`pywin32` 维持 `!=312` 且 `requires-python` 锁 3.12。
6. **config 用新格式**：`gui.type` 只填 `'qt'`/`'web'`，保留完整 `window_size`，不要回退 legacy `use_gui`。

---

## 8. 已核对为兼容的项（无需改，列作安心清单）

- `ok.task` / `ok.feature` / `ok.util` / `ok.device` 路径未变。
- `BaseTask` / `TriggerTask` / `Box` / `WaitFailedException` / `calculate_colorfulness` / `get_box_by_name` / `box_of_screen` 任务 API 原样保留。
- `TaskExecutor.next_frame(time_out=6)` 签名一致。
- `StartController` 方法签名逐字一致（基类 QObject → 普通类，但重写无需改）。
- `communicate` 信号、`bitblt_utils`、`util.window`、`util.process` 全部保留。
- `ok.gui` 兼容 shim 在 2.0.2 仍存在，迁移无残留（`grep -rn "ok\.gui\." src/` 为空）。

---

## 9. 参考

- 升级执行计划：`docs/framework-upgrade-plan.md`
- 兼容 shim：`ok/gui/__init__.py`（2.0.2，MetaPathFinder 重定向 + 同一模块对象）
- config 兼容：`ok/core/ui_config.py` `resolve_ui_config()`
- 模块别名：`ok/ui/qt/StartController.py`（`sys.modules[__name__] = ok.core.start_controller`）
- 验证版本：`.venv` 内 `ok-script==2.0.2`，核对日期 2026-08-19
