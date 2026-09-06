# ok-nikke 框架升级计划（ok-script 1.0.189 → 2.0.2）

> 创建日期：2026-08-19
> 升级分支：`upgrade-framework`（基于 `dev` 创建）
> 涉及仓库：ok-nikke（本仓库）、ok-script（框架）、ok-script-app（模板）
> 文档状态：已评审，待执行

---

## 1. 背景与目标

本仓库基于模板 `ok-script-app` 创建，依赖框架 `ok-script`。近期框架已发布 2.x 系列，模板项目也已迁移到 2.x 结构。由于本项目处于开发早期（业务代码尚未固化），此时升级的成本最低、摩擦最小。

**目标：**
1. 将 `ok-script` 依赖从 `1.0.189` 升级到 pypi 最新正式版 `2.0.2`
2. 同步模板项目的新工程结构（依赖 profiles、config 新格式）
3. 迁移后保证现有业务代码（tasks / patches / ui）全部可用
4. 建立可重复的验证与回滚流程
5. 将自定义 Tab/补丁的 import 从旧路径 `ok.gui.*` 迁移到新路径 `ok.ui.qt.*`（见 3.2）

**非目标（本期不做）：**
- 迁移到 Web UI（`web_main.py` / `requirements-web.txt` 可选，见 6.3）

---

## 2. 版本现状

| 仓库 | 当前依赖版本 | 说明 |
|---|---|---|
| ok-nikke（本仓库） | `ok-script==1.0.189` | requirements.txt 精确锁定 |
| ok-script-app（模板） | `ok-script==2.0.0b7` | 模板已迁移 2.x，**但停在 beta** |
| ok-script（框架） | pypi 最新 **2.0.2**（正式版） | 本地仓库 HEAD = v2.0.2 + 5 未推送提交 |

> ⚠️ **关键提醒：不要照抄模板的版本号。** 模板锁定 `2.0.0b7`（beta），落后于正式版 `2.0.2`。本计划以 pypi 正式版 `2.0.2` 为升级目标。

### 2.1 相关版本差异（v1.0.189 → v2.0.2，共 34 个提交）

| 变更类别 | 具体内容 | 对本项目的影响 |
|---|---|---|
| GUI 模块迁移 | `ok/gui/` → `ok/ui/qt/`，新增 UI 无关的 `ok/core/` | 低（有兼容 shim） |
| 依赖管理重构 | 新增 extras profiles：`ok-script[adb,default,ocr,qt]` / `[web]` | **高（requirements 写法要改）** |
| config 新格式 | `gui: {type, launch_mode, window_size}` 替代 `use_gui` + `window_size` | 中（旧格式仍兼容，但应迁移） |
| Web UI | pywebview / fastapi 双端支持 | 低（本期不启用） |
| 修复 | pywin32 312 排除、overlay 关闭/帧取消、shutdown error、webview 闪烁等 | 正收益（本项目 overlay 逻辑直接受益） |

---

## 3. 兼容性验证结论（已完成的静态分析）

### 3.1 业务代码依赖矩阵

| 项目代码 | 依赖的框架 API | 2.0.2 验证结果 |
|---|---|---|
| `src/tasks/*`（9 个任务） | BaseTask / TriggerTask / Box / WaitFailedException / calculate_colorfulness / get_box_by_name / box_of_screen | ✅ 原样保留（`ok/task/task.py`、`ok/feature/Box.py`、`ok/util/color.py`） |
| `src/patches/runtime.py` | `TaskExecutor.next_frame(time_out=6)` | ✅ 签名一致（2.0.2 中 `ok/task/TaskExecutor.py:248`） |
| `src/patches/start_controller.py` | `StartController.start_device(initial_refresh_done=False)` 及全部辅助方法 | ✅ 方法签名逐字一致（2.0.2 中 `ok/core/start_controller.py:178`；类由 QObject 改为普通类，不影响继承重写） |
| `src/patches/basic_options.py` | `ok.util.GlobalConfig`、`LabelAndFileSelector._initial_directory` | ✅ 保留（`ok/util/GlobalConfig.py`、`ok/ui/qt/tasks/LabelAndFileSelector.py:82`） |
| `src/patches/tasks_tab.py` | TaskCard / OneTimeTaskTab / ConfigContentMixin / ExpandCardLayout / HorizontalSeparator | ✅ 保留（`ok/ui/qt/tasks/`、`ok/ui/qt/widget/`） |
| `src/patches/start_controller.py` | communicate 信号（starting_emulator / restart_admin）、bitblt_utils、util.window、util.process | ✅ 全保留（`ok/core/events.py:81-83`，`ok/device/capture_methods/bitblt_utils.py` 签名逐字一致） |
| `src/config.py` | `use_gui: True` + `window_size` | ✅ 旧格式被 `resolve_ui_config` 兼容（`ok/core/ui_config.py:29-32`），但计划迁移到新格式 |
| `main.py` / `main_debug.py` | `ok.OK(config)` | ✅ 构造签名未变 |

### 3.2 关键兼容机制：ok.gui 兼容层（计划迁移到新路径）

2.0 通过 `ok/gui/__init__.py` 中的 **MetaPathFinder shim** 把旧路径 `ok.gui.X` 重定向到 `ok.ui.qt.X`，且保证类在旧/新命名空间下单例（不会双重定义）。因此本项目现有 `from ok.gui.xxx import xxx` 导入在 2.0 下**仍然可用**，这是升级的兜底保障。

**但本期计划将自定义代码的 import 全部迁移到新路径 `ok.ui.qt.*`**，理由：
1. shim 是过渡兼容层，后续版本可能移除；新路径是唯一正路
2. 模块别名（`ok/ui/qt/StartController.py` 通过 `sys.modules[__name__] = _core` 指向 `ok.core.start_controller`）保证 `ok.ui.qt.StartController` 与框架内部模块是**同一对象**，`patches` 替换类后框架内部引用同样生效，行为与旧路径完全一致
3. 本项目是唯一自定义方（无第三方代码依赖 `ok.gui`），迁移范围可控（13 处 import / 5 个文件）

**迁移清单（共 13 处）：**

| 文件 | 旧路径 | 新路径 |
|---|---|---|
| `src/patches/start_controller.py:9` | `ok.gui.StartController` | `ok.ui.qt.StartController` |
| `src/patches/start_controller.py:12` | `ok.gui.Communicate` | `ok.ui.qt.Communicate` |
| `src/patches/basic_options.py:68` | `ok.gui.tasks.LabelAndFileSelector` | `ok.ui.qt.tasks.LabelAndFileSelector` |
| `src/patches/tasks_tab.py:10` | `ok.gui.tasks.TaskCard` | `ok.ui.qt.tasks.TaskCard` |
| `src/patches/tasks_tab.py:46,114` | `ok.gui.tasks.OneTimeTaskTab` | `ok.ui.qt.tasks.OneTimeTaskTab` |
| `src/patches/tasks_tab.py:47` | `ok.gui.widget.ExpandCardLayout` | `ok.ui.qt.widget.ExpandCardLayout` |
| `src/patches/tasks_tab.py:136` | `ok.gui.tasks.ConfigCard` | `ok.ui.qt.tasks.ConfigCard` |
| `src/ui/DailyTab.py:6` | `ok.gui.tasks.ConfigCard` | `ok.ui.qt.tasks.ConfigCard` |
| `src/ui/DailyTab.py:7` | `ok.gui.widget.CustomTab` | `ok.ui.qt.widget.CustomTab` |
| `src/ui/DailyTab.py:8` | `ok.gui.widget.ExpandCardLayout` | `ok.ui.qt.widget.ExpandCardLayout` |
| `src/ui/DailyTab.py:9` | `ok.gui.widget.Tab` | `ok.ui.qt.widget.Tab` |
| `src/ui/MyTab.py:6` | `ok.gui.widget.CustomTab` | `ok.ui.qt.widget.CustomTab` |

> 其他 `ok.*` import（`ok.feature` / `ok.task` / `ok.util` / `ok.device`）在新旧版本路径不变，无需迁移。

**结论：静态分析层面，本项目全部框架依赖在 2.0.2 下兼容。升级风险集中在 patches 运行时行为与依赖锁定，属可控范围。**

---

## 4. 升级步骤（按序执行）

### 步骤 1：同步模板工程结构（不升版本）

1. **新建 `pyproject.toml`**（参照模板）：
   - `[project.optional-dependencies]` 定义 `qt` / `web` / `docs` profiles
   - `qt = ["ok-script[adb,default,ocr,qt]==2.0.2", "openvino", "opencv-python"]`
   - 本项目不需要 `adb`（纯 Windows 游戏），可去掉该 extra；若保留则无妨
2. **迁移 `src/config.py` 的 GUI 配置**（注意：实际路径是 `src/config.py`，非根目录）：
   - 旧：`'use_gui': True` + 顶层 `'window_size'`
   - 新：`'gui': {'type': 'qt', 'window_size': {...}}`
   - 保留 `'use_gui'` 会走兼容分支，但新格式是唯一正路
3. **重新生成 requirements**：以 pyproject 为源执行 `pip-compile`（或手工整理），锁定 `ok-script==2.0.2`
4. **校验**：本步骤结束后项目在 `1.0.189` 下仍可正常启动（结构改动对 1.x 无破坏，如有破坏则说明同步过头，立即回退本步）

### 步骤 2：升级框架依赖

1. `requirements.txt` / `pyproject.toml` 中 `ok-script` 改为 `==2.0.2`
2. **`pywin32` 必须排除 312**：框架官方已标记 pywin32 312 为 broken release 并排除（ok-script commit 936cb23）。框架 2.0.2 实际约束为 `pywin32>=306,!=312`（见 ok-script `pyproject.toml`）；本项目应保持一致。
   - ⚠️ **不要写 `pywin32>=313`**：PyPI 上 pywin32 当前可用版本为 `306/307/308/309/310/311/312`，**没有 313**（PyWin32 build 号不严格对应 Python 版本）。`!=312` 时 pip 会解析到 build 311（支持 Python 3.8–3.12），可在本项目 Python 3.12 环境下正常安装。
   - 当前 requirements.txt 锁定 `pywin32==312`，必须改为 `pywin32>=306,!=312`（或显式 `pywin32==311`）。
3. 删除本地 venv 中旧版本并重装：`pip install -r requirements.txt`（建议重建 venv 或 `pip uninstall ok-script` 后重装，避免残留）
4. 启动 `python main_debug.py` 冒烟验证

### 步骤 3：迁移 import 到新路径 ok.ui.qt

> 必须在步骤 2 之后执行（`ok.ui.qt` 仅在 2.0 存在，1.x 下无此路径）。

1. 按 §3.2 迁移清单，将 5 个文件中的 13 处 `ok.gui.*` import 改为 `ok.ui.qt.*`
   - `src/patches/start_controller.py`（2 处，含第 404 行注释同步更新）
   - `src/patches/basic_options.py`（1 处）
   - `src/patches/tasks_tab.py`（4 处）
   - `src/ui/DailyTab.py`（4 处）
   - `src/ui/MyTab.py`（1 处）
2. **校验无残留**：`grep -rn "ok\.gui\." src/` 应无输出（注释除外）
3. 启动 `python main_debug.py` 冒烟，确认 UI 正常渲染、patches 正常应用（shim 与新路径指向同一模块对象，行为应无变化）

### 步骤 4：回归验证（详见第 5 节）

### 步骤 5：提交与合并

1. 在 `upgrade-framework` 分支提交变更（建议 3-4 个逻辑提交：结构同步 / 依赖升级 / import 迁移 / 修复调整）
2. 全部验收通过后，合并回 `dev`（`git checkout dev && git merge upgrade-framework`）
3. 分支可保留供后续 Web UI 迁移复用

---

## 5. 验收标准（回归清单）

### 5.1 自动化测试（tests/ 目录）

| 测试文件 | 覆盖内容 | 预期 |
|---|---|---|
| TestMain.py | 启动/基础流程 | 全部通过 |
| TestRedDot.py | 红点检测 | 全部通过 |
| TestNoticePopup.py | 公告弹窗关闭 | 全部通过 |
| TestRupeePopup.py | 卢比弹窗 | 全部通过 |
| TestBattleWait.py | 战斗结束等待 | 全部通过 |
| TestDailySubtasks.py | 日常子任务编排 | 全部通过 |
| TestCashShopTask.py | 商店购买 | 全部通过 |
| TestScreenRecovery.py | 界面识别与失败恢复 | 全部通过 |
| TestArkTask.py | 无限之塔 | 全部通过 |

> 若框架升级导致个别测试失败，需先定位是**框架行为变化**还是**项目代码问题**，修复后补测。

### 5.2 手工验证（必须有游戏环境）

1. **启动器自动化**：`patches/start_controller.py` 的 NikkeStartController 是否正常接管启动流程（管理员提权 → 启动器 OCR → 游戏窗口检测）——这是升级风险最高的路径
2. **任务执行**：DailyTask / ShopTask / CashShopTask 各跑一遍
3. **overlay 关闭**：验证 2.0 的 overlay 修复（`eaf8967` / `91fdda5`）生效，任务结束 overlay 正常退出
4. **进程退出**：无 OpenVINO 遥测导致的退出挂起（本项目 runtime patch 已处理，需确认在 2.0 下仍生效）
5. **import 迁移验证**：`grep -rn "ok\.gui\." src/` 无残留；DailyTab / MyTab 正常渲染（CustomTab / Tab / ExpandCardLayout / ConfigContentMixin 均从 `ok.ui.qt.*` 导入）

### 5.3 打包验证（可选，发布前）

- `pyappify.yml` 的 China/Global profile 构建通过

---

## 6. 风险与应对

| # | 风险 | 等级 | 应对 |
|---|---|---|---|
| 1 | patches 猴子补丁与 2.0 重构后的内部实现不兼容（静态兼容 ≠ 运行时兼容） | 中 | 手工验证 5.2.1/5.2.2；import 已按步骤 3 迁移到 `ok.ui.qt.*`，不再依赖 shim |
| 2 | `TaskExecutor.next_frame` 补丁在 2.0 中行为变化 | 低 | 签名一致（2.0.2:248），运行时验证任务执行不卡帧 |
| 3 | pywin32 312 坏版本 | 中 | 升级时直接排除（`>=313`），见步骤 2 第 2 条 |
| 4 | 依赖 profiles 重构导致 requirements 漂移 | 中 | 以 pyproject 为唯一源重新生成 requirements；diff 检查 |
| 5 | 模板版本号误导（2.0.0b7） | 低 | 本计划已明确以 2.0.2 为准 |
| 6 | 本地 ok-script 仓库有 37 个未推送提交，若运行环境用了本地路径而非 pip 包 | 中 | 先确认 `ok.__file__` 指向；确保运行环境安装的是 pypi 2.0.2 |
| 7 | import 迁移遗漏或写错路径（如混用新旧路径导致类双重定义） | 低 | 按 §3.2 清单逐文件核对；迁移后 `grep -rn "ok\.gui\." src/` 无残留；新路径与 shim 指向同一模块对象，行为一致 |

### 6.1 回滚方案

```bash
# 若升级失败：
git checkout dev                       # 回到开发分支
git revert --no-commit <upgrade-merge> # 或直接 reset 合并提交
# 依赖回滚：pip install ok-script==1.0.189
# config.py / pyproject.toml 由 git 历史还原
```

### 6.2 回滚触发条件

- 步骤 4 回归测试出现无法在 2 小时内定位的失败
- 手工验证中启动器自动化、任务执行出现阻断性问题
- 升级分支上连续 3 个修复提交仍无法恢复

### 6.3 Web UI 迁移（可选，本期不做）

2.0 框架新增了 Web UI 支持，模板已配套提供 `web_main.py`、`web_main_debug.py`、`requirements-web.txt` 以及 `pyappify.yml` 中的 Web profile。本计划主路径为 **Qt GUI**，不启用 Web 端，故不涉及以下文件的引入：

- `web_main.py` / `web_main_debug.py`（Web 模式入口）
- `requirements-web.txt`（`ok-script[adb,default,ocr,web]` 依赖集）
- `pyappify.yml` 的 Web profile

若未来需要 Web 端，迁移方式为：从模板复制上述文件 → `config.py` 的 `gui.type` 设为 `'web'`（`launch_mode` 可选 `pywebview` / `browser` / `server`）→ 按需打包。本期无需任何动作。

---

## 7. 任务拆解与检查表

- [x] 确认 `ok.__file__` 指向 pypi 安装路径（排除本地仓库干扰）
- [x] 新建 `pyproject.toml`（extras profiles，ok-script==2.0.2，`requires-python = ">=3.12,<3.13"`）
- [x] 迁移 `src/config.py` 到 `gui` 新格式（注意：是 `src/config.py`，非根目录）
- [x] 重新生成 requirements.txt（`pywin32>=306,!=312`；移除 `requirements.in`，改用 `pyproject.toml` 作为 pip-compile 源）
- [x] pip-compile 后 diff 检查 `--no-deps` 兼容性（所有传递依赖显式列出，特别是新增的 `ok-d3dshot` 及其传递依赖）
- [x] 重建/刷新 venv，安装依赖
- [x] `main_debug.py` 冒烟启动
- [x] 按 §3.2 清单迁移 13 处 `ok.gui.*` → `ok.ui.qt.*`（5 个文件）
- [x] `grep -rn "ok\.gui\." src/` 无残留
- [x] 运行 tests/ 全部 9 个测试文件
- [ ] 手工验证启动器自动化 + 3 个核心任务 + overlay 退出 + import 迁移后 UI 渲染
- [ ] 提交（结构同步 / 依赖升级 / import 迁移 / 修复调整 3-4 个提交）
- [ ] 合并回 dev（待用户确认后执行）
- [ ] （发布前）pyappify 打包验证

---

## 8. 参考

- 框架版本线：`v1.0.189` → `v1.0.190` → `v2.0.0b1~b7` → `v2.0.0` → `v2.0.2`
- 兼容 shim：`ok/gui/__init__.py`（`ok-script` 仓库 commit 026cf9e "Preserve legacy Qt module identity"）
- config 兼容：`ok/core/ui_config.py` `resolve_ui_config()`
- pywin32 修复：ok-script commit 936cb23 "fix: exclude broken pywin32 312 release"
- 模板新结构参考：`ok-script-app` 仓库 `pyproject.toml`、`web_main.py`、`src/config.py`

---

## 9. 最终校验记录（2026-08-19）

> 校验方式：对照 ok-script 2.0.2 实际 pyproject.toml / commit 936cb23 / HEAD、ok-script-app 模板实际文件、本项目 src/ 全量 grep，逐项验证文档主张。
> 校验结论：**主干可行、自洽**；已就地修正 2 处错误（pywin32 约束、config.py 路径），下列各项为补充说明与残留风险，按"已确认 / 需补充 / 待运行时验证"分类。

### 9.1 已就地修正

| # | 原主张 | 实际情况 | 修正位置 |
|---|---|---|---|
| 1 | 步骤 2 第 2 条建议 `pywin32>=313` | PyPI 上 pywin32 可用版本为 `306–312`，**313 不存在**；312 broken；框架实际约束 `pywin32>=306,!=312`（解析到 build 311，支持 Python 3.12） | §4 步骤 2 第 2 条、§7 检查表 |
| 2 | 步骤 1 第 2 条 / §7 检查表说"迁移 `config.py`" | 实际路径 `src/config.py`（模板 ok-script-app 同此路径），非根目录 | §4 步骤 1 第 2 条、§7 检查表 |

### 9.2 需补充的疏漏

#### 9.2.1 ok-d3dshot 新依赖（文档未提）

- ok-script 2.0 的 `[default]` extras 新引入 `ok-d3dshot>=0.1.5`（见 ok-script `pyproject.toml`），1.0.189 无此依赖
- 升级后 `pip-compile` 会自动在 requirements.txt 中新增 `ok-d3dshot==0.1.5` 及其传递依赖（如 `comtypes`，与 pycaw 重复但无冲突）
- **影响**：体积小幅增加；首次重建 venv 时会出现新包，需知悉；`--no-deps` 打包要求 ok-d3dshot 必须显式列入 requirements.txt（pip-compile 会处理，但人工 diff 时不要误删）

#### 9.2.2 pyappify.yml 的 `pip_args: "--no-deps"` 约束（文档未提）

- 本项目与模板的 `pyappify.yml` 均使用 `pip_args: "--no-deps"`，打包时 pip **不解析传递依赖**
- 含义：requirements.txt 必须显式列出**全部**传递依赖（当前已如此，如 adbutils/mouse/pycaw/pydirectinput/psutil/requests/pyappify 都是 ok-script 的传递依赖但被显式列出）
- 升级动作：`pip-compile` 后必须 diff 检查无遗漏，特别是 9.2.1 的 ok-d3dshot 及其传递依赖
- **此约束与 §6 风险 #4"依赖 profiles 重构导致 requirements 漂移"叠加**，应在步骤 1 第 3 条之后追加一步：diff 检查 `--no-deps` 兼容性

#### 9.2.3 Python 版本约束（文档未提）

- 模板 `pyproject.toml` 显式锁定 `requires-python = ">=3.12,<3.13"`
- 本项目与模板 `pyappify.yml` 均 `requires_python: "3.12"`
- 含义：升级**不能跨 Python 大版本**；pywin32 选 build 也受 Python 版本限制（build 311 支持 Python 3.8–3.12，build 313 不存在）
- 升级动作：本项目 `pyproject.toml` 应写 `requires-python = ">=3.12,<3.13"`，与模板一致
- 修订 §7 检查表已补充此项

#### 9.2.4 requirements.in 应被 pyproject.toml 取代（文档未明说）

- 本项目当前用 `requirements.in` 作为 pip-compile 输入（内容含 `ok-script`、`OpenCC`、`adbutils`、`onnxocr-ppocrv5`、`openvino`、`opencv-python`、`pynput`、`pyside6-essentials`、`pyside6-fluent-widgets`）
- 模板 ok-script-app **没有 requirements.in**，只用 `pyproject.toml` 的 `[project.optional-dependencies]` 作为 pip-compile 输入
- 升级动作：新建 `pyproject.toml` 后**删除 `requirements.in`**，改用 `pip-compile pyproject.toml -o requirements.txt`，避免两套源不一致
- §7 检查表已补充此项

#### 9.2.5 adbutils 处理需厘清（文档措辞含糊）

- 文档 §4 步骤 1 说"本项目不需要 adb（纯 Windows 游戏），可去掉该 extra；若保留则无妨"
- 实际：adbutils 当前是 **requirements.in 中的显式独立依赖**（不是通过 ok-script[adb] extra 引入的）
- 三种处理方案：

| 方案 | pyproject.toml | requirements.in | 结果 |
|---|---|---|---|
| A（与模板一致，推荐） | `ok-script[adb,default,ocr,qt]==2.0.2` | 删除 `adbutils` 行 | adbutils 由 extra 提供，无重复 |
| B（去掉 adb） | `ok-script[default,ocr,qt]==2.0.2` | 保留 `adbutils` 行（或一并删除） | 减少 adbutils/retry2/deprecation/pillow(重复) 4 个依赖 |
| C（混用，**不推荐**） | `ok-script[default,ocr,qt]==2.0.2` | 保留 `adbutils` 行 | 与方案 B 同效果，但语义不清 |

- **建议方案 A**：与模板一致，减少偏离；adbutils 在 Windows 路径下不会被实际调用，仅增加约 2MB 体积

#### 9.2.6 main_debug.py 的 UAC 提权（文档未提）

- `main_debug.py` 在 `ok.OK(config)` 之前有 `is_admin()` / `request_admin()` 逻辑，会触发 UAC 弹窗
- 步骤 2 第 4 条 / 步骤 3 第 3 条说"`python main_debug.py` 冒烟"，未提示 UAC
- 影响：小；开发者首次跑可能误判 UAC 弹窗为故障
- 升级动作：无；仅提示知晓

#### 9.2.7 §6 风险 #6 措辞修正

- 原措辞："本地 ok-script 仓库有 37 个未推送提交"
- 实际：相对 `origin/master` 有 **37 个未推送提交**；其中相对 `v2.0.2` tag 有 **5 个后续提交**（91fdda5 / 41a59bc / c05ca2f / eaf8967 / 3b2495a）
- 两个数字描述对象不同，不矛盾，但易混淆
- 风险触发条件应明确：**仅当用 editable install（`pip install -e D:\dev\vibespace\ok-script`）指向本地 HEAD 时才有风险**；安装 pypi 2.0.2 包不受影响
- 修订建议：将 §6 风险 #6 改为"本地 ok-script 仓库 HEAD 领先 origin/master 37 个提交（含 v2.0.2 自身及之后 5 个）；若运行环境用 `pip install -e` 指向本地仓库 HEAD，会用到未发布的 5 个提交，与 pypi 2.0.2 行为可能存在差异"

#### 9.2.8 §3.2 清单第 1 处 import 形式需注明

- 文档清单第 1 行写"`ok.gui.StartController` → `ok.ui.qt.StartController`"
- 实际 `src/patches/start_controller.py:9` 是 `import ok.gui.StartController as start_controller_module`（**module import 形式，含 `as` 别名**），非 `from X import Y` 形式
- 迁移后：`import ok.ui.qt.StartController as start_controller_module`
- 迁移规则一致（路径替换即可），但开发者执行时应注意保留 `as start_controller_module` 别名（`apply()` 第 405 行依赖此别名访问 `start_controller_module.StartController`）

### 9.3 经核查确认无问题

| # | 校验项 | 结论 |
|---|---|---|
| 1 | import 清单行号 | §3.2 清单 12 处实际 import + 1 处注释（404 行）= 13 处，全部行号准确（`grep -rn "ok\.gui" src/` 已逐行核对） |
| 2 | `src/globals.py` 是否依赖 `ok.gui` | 否；仅 `from ok import Logger` + `PySide6.QtCore.QObject`，无需迁移 |
| 3 | §3.1 StartController "类由 QObject 改为普通类，不影响继承重写" | 正确；信号机制由独立模块 `ok/core/events.py` 的 `communicate` 提供，不依赖 QObject 基类 |
| 4 | §2 表格 ok-script HEAD 描述 | "v2.0.2 + 5 未推送提交"准确（HEAD=91fdda5，v2.0.2..HEAD 共 5 个提交）；与 §6 风险 #6 的 37 个未推送提交是不同维度（origin/master..HEAD = 37），不矛盾 |
| 5 | tests/ 目录 9 个测试文件 | 全部存在，文件名与 §5.1 表格一致 |
| 6 | 模板 pyproject.toml `requires-python = ">=3.12,<3.13"` | 与本项目 pyappify.yml `requires_python: "3.12"` 一致，升级方向正确 |
| 7 | 模板 `[qt]` extras 写法 `ok-script[adb,default,ocr,qt]==2.0.0b7` | 文档步骤 1 第 1 条引用正确，仅版本号需改为 2.0.2（文档已明确提醒） |

### 9.4 待运行时验证（静态分析无法覆盖）

| # | 项 | 验证方式 |
|---|---|---|
| 1 | `ok.gui.StartController` module alias 在 2.0.2 下是否指向 `ok.core.start_controller`（与 shim 同对象） | 步骤 3 完成后 `python -c "import ok.ui.qt.StartController as m; import ok.core.start_controller as c; assert m is c"` |
| 2 | `NikkeStartController(start_controller_module.StartController)` 继承链在父类从 QObject 改为普通 class 后，子类无 Qt 元对象冲突 | 步骤 4 手工验证 5.2.1（启动器自动化） |
| 3 | `TaskExecutor.next_frame(time_out=6)` 运行时行为（签名一致 ≠ 行为一致） | 步骤 4 手工验证 5.2.2（任务执行不卡帧） |
| 4 | overlay 关闭/帧取消修复（commits eaf8967 / 91fdda5）在本项目实际生效 | 步骤 4 手工验证 5.2.3 |
| 5 | OpenVINO 遥测导致的退出挂起（runtime patch）在 2.0.2 下仍生效 | 步骤 4 手工验证 5.2.4 |
| 6 | `pip-compile` 生成的 requirements.txt 与 `--no-deps` 打包兼容（无传递依赖遗漏） | 步骤 1 完成后 diff 检查；步骤 5.3 打包验证 |

### 9.5 校验总结

- **主干可行性**：✅ 通过。文档核心路径（结构同步 → 依赖升级 → import 迁移 → 回归验证）逻辑自洽，与模板/框架 2.0.2 实际状态一致
- **已修正错误**：2 处（pywin32 约束、config.py 路径）
- **补充疏漏**：8 项（ok-d3dshot / --no-deps / Python 版本 / requirements.in / adbutils / main_debug UAC / 风险 #6 措辞 / import 形式注明）
- **待运行时验证**：6 项（无法静态判定，已列入 §5 验收清单与 §9.4）
- **建议**：执行升级前先完成 §9.4 第 1 项的 module alias 一致性验证（成本极低、能提前发现 shim 与新路径指向不一致的极端情况）
