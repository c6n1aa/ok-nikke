# P1.1 集中式界面注册表 src/screens.py

> 上游依据：`docs/screen-recovery-evolution-plan.md` §5.3（方案 1 子项 1）、§6 Phase 1.1
> 工作分支：`feature/screen-recovery-evolution`；依赖：无。
> 预计改动面：`src/screens.py`（新增）+ `src/tasks/NikkeBaseTask.py` + `ArkTask.py` / `CashShopTask.py` / `RaidTask.py` + 相关测试。

## 目标

把分散在各任务 `__init__` 里的界面声明收敛为单一数据源，让 `DebugTask` 与 `current_screen()`（以及后续方案）能识别全部界面。**判定语义必须逐位不变**——运行结果应于迁移前完全一致。

## 现状锚点（以源码为准逐一核对）

- 注册集合（共 9 个）：
  - 基类 `NikkeBaseTask.__init__`（约 32 行）：`lobby` → features `[ark, lobby]`。
  - `ArkTask.py:48-50`：`ark` → `[ark_tribe_tower, ark_simulation_room]`；`tribe_tower` → `[tribe_tower_mark]`；`simulation_room` → `[simulation_mark]`。
  - `CashShopTask.py:28`：`付费商店` → keywords `[付费商店]`, ocr_box `box_sub_pages_title`。
  - `RaidTask.py:25-28`：`coop_page`、`coop_nikke_select_page`、`solo_raid_page`、`solo_raid_battle_team_select_page`（各 1 个 features）。
- 判定入口：`register_screen`（`NikkeBaseTask.py:563-578`）、`_screen_match`（580-602）、`current_screen`（621-626，按字典插入顺序首命中返回）。
- `DebugTask.debug_current_screen`（`DebugTask.py:20-34`）：遍历本实例 `self.screens`——集中化后自动看到全部界面，无需改它。

## 实施步骤

1. 新建 `src/screens.py`：模块级 `SCREENS: dict[str, dict]`，收录全部 9 个界面，顺序即注册顺序（`lobby` 在前）。每个条目形如 `{"features": [...], "keywords": [...], "ocr_box": ...}`，仅含迁移前真实存在的键（缺省键省略，不补空列表）。文件头部写 docstring：数据来源、判定语义（features 与、keywords 或、同时配置再与）、以及集中化的动机（引用上游文档）。
2. **`screens.py` 必须是纯数据模块**：不 `import ok`、不依赖任何框架对象，仅用 stdlib——这样后续 coco 完整性测试（P1.3）可低成本导入。
3. `NikkeBaseTask.__init__`：改为从 `SCREENS` 加载全部界面（每个条目灌入 `self.screens[name]`，保持与 `register_screen` 相同的字典结构）。**保留 `register_screen` 为其公开 API**：任务仍可追加/覆盖任务私有界面，同名覆盖全局（注释说明该语义）。
4. 删除 `ArkTask` / `CashShopTask` / `RaidTask` `__init__` 里对应的 `register_screen` 调用及其上方注释。
5. 核对导入：`src/screens.py` 只被 `NikkeBaseTask` 导入，各任务无需额外 import 变化。

## 修改文件

- 新增：`src/screens.py`。
- 修改：`src/tasks/NikkeBaseTask.py`、`src/tasks/ArkTask.py`、`src/tasks/CashShopTask.py`、`src/tasks/RaidTask.py`。
- 测试：`tests/TestScreenRecovery.py` 及各任务测试按后果更新（见下）。

## 测试与验收

- `HarvestTask`（继承基类）实例现在拥有全部 9 个界面——任何断言 `screens` 键集合/遍历顺序的既有用例需按新集合更新；对 `find_one`/`ocr` 的 mock 需覆盖新增界面路径（未命中分支），防止失败路径用例因多出的调用数产生误 FAIL 或漏断言。
- 新增轻量用例：断言 `src.screens.SCREENS` 键集合 == 迁移前的 9 个，且每项判定描述与迁移前一致。
- 注册表搬家影响所有任务 → 逐文件独立进程全量回归：`run_tests.ps1`，或逐条 `unittest` 跑 `tests/TestScreenRecovery.py`、`TestArkTask.py`、`TestRaidTask.py`、`TestCashShopTask.py`、`TestBattleWait.py`、`TestDailySubtasks.py` 等。

验收标准：全部受影响测试文件逐文件通过；`DebugTask.debug_current_screen` 能列出并判定全量界面（人工/实机可选验证）。

## 提交

`refactor(screens): centralize screen registry into src/screens.py`

正文说明：9 个界面从各任务 `__init__` 收敛到单一数据源，行为语义不变；`register_screen` 保留为任务扩展口。

## 超范围禁止

不改判定逻辑、不改 `_match_ocr_keywords`/`current_screen` 迭代方式；不引入缓存（那是 P1.2）；不给 spec 加字段（那是 P1.4）。
