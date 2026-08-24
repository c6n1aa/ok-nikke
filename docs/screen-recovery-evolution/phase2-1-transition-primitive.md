# P2.1 守卫式转换原语 transition()

> 上游依据：`docs/screen-recovery-evolution-plan.md` §5.5、§6 Phase 2.1
> 工作分支：`feature/screen-recovery-evolution`；依赖：P1.1（注册表集中后可引用全局界面）。
> 预计改动面：`src/tasks/NikkeBaseTask.py`（新增原语）+ 各任务导航边迁移 + 相关测试。

## 目标

把「点入口 → 等到目标界面」的成对手写代码收敛为基类方法，就地消化「动画期吞点击」这类瞬时故障，避免一次误点就触发整段回大厅重跑。**仅新增原语并迁移现有转换对，不改任何其它流程语义。**

## 现状锚点（以源码为准逐一核对）

现存转换对（`wait_click_feature` 后紧跟 `assert_screen`）：
- `ArkTask.py:75-76`（→ `ark`）、`118-119`（→ `simulation_room`）、`191-192`（→ `tribe_tower`）。
- `CashShopTask.py:40-41`（→ `付费商店`）。
- `RaidTask.py:86-87`（→ `coop_page`）、`103-104`（→ `coop_nikke_select_page`）、`167-168`（→ `solo_raid_battle_team_select_page`）、`178-179`（→ `solo_raid_page`）、`206-207`（→ `solo_raid_page`）。
- 非典型边（战斗结算后确认、`wait_battle_finish` 语义）**不迁移**。

## 实施步骤

1. 基类新增 `transition(to_screen, click_feature=None, box=None, click=None, time_out=10, wait_confirm=3, retry_click=2, after_sleep=1)`：
   - 执行一次点击动作（支持 coco 特征名走 `wait_click_feature`、或框/区域走 `click_box`、或传入可调用对象）。
   - 随后 `wait_screen(to_screen, time_out=wait_confirm)`；未命中时原地重做点击，至多 `retry_click` 次（每次重新等待确认）。
   - 重试耗尽仍未进入 → `save_failure_screenshot(to_screen)` 并抛 `WaitFailedException(f"transition to {to_screen} failed (current: {current_screen()})")`——携带 from/to 的上下文信息，供 `try_step` 捕获恢复。
   - 进入战斗等长加载边通过 `wait_confirm`/`time_out` 配置放大。
2. 迁移上述转换对：把 `wait_click_feature(...)` + `assert_screen(...)` 两行替换为一次 `transition(...)` 调用，保留各自原有的 `after_sleep`、`time_out` 参数值，**不改变其它语义**（迁移后这些点的失败行为 = 原 `assert_screen` 超时抛 `WaitFailedException`，仍可被外层 `try_step` 捕获）。
3. 逐处迁移后核对对应任务测试的 mock 面（`transition` 内部调用 `wait_screen`，测试里对 assertion 的期望可能需改为对 `transition`/`wait_screen` 的期望）。

## 修改文件

- `src/tasks/NikkeBaseTask.py`；`src/tasks/ArkTask.py`、`CashShopTask.py`、`RaidTask.py`。
- 测试：`tests/TestBattleWait.py`（若含该逻辑）、`tests/TestArkTask.py`、`TestRaidTask.py`、`TestCashShopTask.py`、`TestScreenRecovery.py` 更新 + 新增用例。

## 测试与验收

- 新增用例（mock 驱动）：
  - 吞点击：`wait_screen` 第一次超时、第二次成功（配合点击可 mock 成触发成功）→ 断言点击被执行至少 2 次、且不抛出 `WaitFailedException`。
  - 重试耗尽：`wait_screen` 恒不命中 → `retry_click` 次点击后抛 `WaitFailedException`，且消息含 from/to 名、失败截图被保存。
- 迁移涉及的任务测试文件逐文件独立进程运行：`TestArkTask`、`TestRaidTask`、`TestCashShopTask`、`TestScreenRecovery`、必要时 `TestBattleWait`。
- 提交前对每一处迁移点人工 diff 确认：除 `wait_click_feature`+`assert_screen` → `transition` 外无行为变化。

## 提交

`feat(navigation): add guarded transition() primitive and migrate nav edges`

正文说明：原语语义（点击→等待→原地补点→带上下文抛错）、迁移范围清单、非典型边不迁移的理由。

## 超范围禁止

不重构 `wait_battle_finish`；不把战斗结果确认/结算这类边纳入 `transition`；不改 `try_step` 本身；不新增配置项。
