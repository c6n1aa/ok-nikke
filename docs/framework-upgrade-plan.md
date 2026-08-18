# ok-nikke-maid 框架升级计划（ok-script 1.0.189 → 2.0.2）

> 创建日期：2026-08-19
> 升级分支：`upgrade-framework`（基于 `dev` 创建）
> 涉及仓库：ok-nikke-maid（本仓库）、ok-script（框架）、ok-script-app（模板）
> 文档状态：已评审，待执行

---

## 1. 背景与目标

本仓库基于模板 `ok-script-app` 创建，依赖框架 `ok-script`。近期框架已发布 2.x 系列，模板项目也已迁移到 2.x 结构。由于本项目处于开发早期（业务代码尚未固化），此时升级的成本最低、摩擦最小。

**目标：**
1. 将 `ok-script` 依赖从 `1.0.189` 升级到 pypi 最新正式版 `2.0.2`
2. 同步模板项目的新工程结构（依赖 profiles、config 新格式）
3. 迁移后保证现有业务代码（tasks / patches / ui）全部可用
4. 建立可重复的验证与回滚流程

**非目标（本期不做）：**
- 迁移到 Web UI（`web_main.py` / `requirements-web.txt` 可选，见 6.3）
- 迁移自定义 Tab/补丁的 import 到新路径 `ok.ui.qt.*`（旧路径 `ok.gui.*` 有兼容层，暂不动，见 3.2）

---

## 2. 版本现状

| 仓库 | 当前依赖版本 | 说明 |
|---|---|---|
| ok-nikke-maid（本仓库） | `ok-script==1.0.189` | requirements.txt 精确锁定 |
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

### 3.2 关键兼容机制：ok.gui 兼容层

2.0 通过 `ok/gui/__init__.py` 中的 **MetaPathFinder shim** 把旧路径 `ok.gui.X` 重定向到 `ok.ui.qt.X`，且保证类在旧/新命名空间下单例（不会双重定义）。因此本项目现有 `from ok.gui.xxx import xxx` 导入**无需修改**即可工作。

**结论：静态分析层面，本项目全部框架依赖在 2.0.2 下兼容。升级风险集中在 patches 运行时行为与依赖锁定，属可控范围。**

---

## 4. 升级步骤（按序执行）

### 步骤 1：同步模板工程结构（不升版本）

1. **新建 `pyproject.toml`**（参照模板）：
   - `[project.optional-dependencies]` 定义 `qt` / `web` / `docs` profiles
   - `qt = ["ok-script[adb,default,ocr,qt]==2.0.2", "openvino", "opencv-python"]`
   - 本项目不需要 `adb`（纯 Windows 游戏），可去掉该 extra；若保留则无妨
2. **迁移 `config.py` 的 GUI 配置**：
   - 旧：`'use_gui': True` + 顶层 `'window_size'`
   - 新：`'gui': {'type': 'qt', 'window_size': {...}}`
   - 保留 `'use_gui'` 会走兼容分支，但新格式是唯一正路
3. **重新生成 requirements**：以 pyproject 为源执行 `pip-compile`（或手工整理），锁定 `ok-script==2.0.2`
4. **校验**：本步骤结束后项目在 `1.0.189` 下仍可正常启动（结构改动对 1.x 无破坏，如有破坏则说明同步过头，立即回退本步）

### 步骤 2：升级框架依赖

1. `requirements.txt` / `pyproject.toml` 中 `ok-script` 改为 `==2.0.2`
2. **`pywin32` 必须排除 312**：框架官方已标记 pywin32 312 为 broken release 并排除（ok-script commit 936cb23）。锁定 `pywin32>=313` 或去掉精确锁
3. 删除本地 venv 中旧版本并重装：`pip install -r requirements.txt`（建议重建 venv 或 `pip uninstall ok-script` 后重装，避免残留）
4. 启动 `python main_debug.py` 冒烟验证

### 步骤 3：回归验证（详见第 5 节）

### 步骤 4：提交与合并

1. 在 `upgrade/ok-script-2.0.2` 分支提交变更（建议分 2-3 个逻辑提交：结构同步 / 依赖升级 / 修复调整）
2. 全部验收通过后，合并回 `dev`（`git checkout dev && git merge upgrade/ok-script-2.0.2`）
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

### 5.3 打包验证（可选，发布前）

- `pyappify.yml` 的 China/Global profile 构建通过

---

## 6. 风险与应对

| # | 风险 | 等级 | 应对 |
|---|---|---|---|
| 1 | patches 猴子补丁与 2.0 重构后的内部实现不兼容（静态兼容 ≠ 运行时兼容） | 中 | 手工验证 5.2.1/5.2.2；若 `ok.gui` shim 有边界问题，将 import 改为 `ok.ui.qt.*`（改动极小） |
| 2 | `TaskExecutor.next_frame` 补丁在 2.0 中行为变化 | 低 | 签名一致（2.0.2:248），运行时验证任务执行不卡帧 |
| 3 | pywin32 312 坏版本 | 中 | 升级时直接排除（`>=313`），见步骤 2.2 |
| 4 | 依赖 profiles 重构导致 requirements 漂移 | 中 | 以 pyproject 为唯一源重新生成 requirements；diff 检查 |
| 5 | 模板版本号误导（2.0.0b7） | 低 | 本计划已明确以 2.0.2 为准 |
| 6 | 本地 ok-script 仓库有 37 个未推送提交，若运行环境用了本地路径而非 pip 包 | 中 | 先确认 `ok.__file__` 指向；确保运行环境安装的是 pypi 2.0.2 |

### 6.1 回滚方案

```bash
# 若升级失败：
git checkout dev                       # 回到开发分支
git revert --no-commit <upgrade-merge> # 或直接 reset 合并提交
# 依赖回滚：pip install ok-script==1.0.189
# config.py / pyproject.toml 由 git 历史还原
```

### 6.2 回滚触发条件

- 步骤 3 回归测试出现无法在 2 小时内定位的失败
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

- [ ] 确认 `ok.__file__` 指向 pypi 安装路径（排除本地仓库干扰）
- [ ] 新建 `pyproject.toml`（extras profiles，ok-script==2.0.2）
- [ ] 迁移 `config.py` 到 `gui` 新格式
- [ ] 重新生成 requirements.txt（pywin32 排除 312）
- [ ] 重建/刷新 venv，安装依赖
- [ ] `main_debug.py` 冒烟启动
- [ ] 运行 tests/ 全部 9 个测试文件
- [ ] 手工验证启动器自动化 + 3 个核心任务 + overlay 退出
- [ ] 提交（结构同步 / 依赖升级 / 修复调整 3 个提交）
- [ ] 合并回 dev
- [ ] （发布前）pyappify 打包验证

---

## 8. 参考

- 框架版本线：`v1.0.189` → `v1.0.190` → `v2.0.0b1~b7` → `v2.0.0` → `v2.0.2`
- 兼容 shim：`ok/gui/__init__.py`（`ok-script` 仓库 commit 026cf9e "Preserve legacy Qt module identity"）
- config 兼容：`ok/core/ui_config.py` `resolve_ui_config()`
- pywin32 修复：ok-script commit 936cb23 "fix: exclude broken pywin32 312 release"
- 模板新结构参考：`ok-script-app` 仓库 `pyproject.toml`、`web_main.py`、`config.py`
