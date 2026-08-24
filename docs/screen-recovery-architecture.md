# 界面识别 / 导航 / 失败恢复：机制详解（演进后）

> 本文面向维护者，详解 `feature/screen-recovery-evolution` 分支演进后的三套机制现状。
> 相关文档：开发约束（给 Coding Agent）见 `docs/screen-and-recovery.md`；演进动机与方案取舍见 `docs/screen-recovery-evolution-plan.md`；分步执行 Prompt 见 `docs/screen-recovery-evolution/`。
> 本文为内部文档，经 `mkdocs.yml` 的 `exclude_docs` 排除出发布站点。

## 0. 一页总览

| 层 | 组件 | 位置 | 职责 |
|---|---|---|---|
| 判定（数据） | `SCREENS` / `INTERRUPTS` | `src/screens.py` | 全部界面判定条件与中断特征清单的单一数据源 |
| 判定（机制） | `_screen_match` / `_check_absent` / `_match_ocr_keywords` | `src/tasks/NikkeBaseTask.py` | 单帧界面判定、扩展字段语义 |
| 判定（性能） | `_find_feature_cached` / `_region_ocr_cached` / `next_frame` 覆写 | 同上 | 同帧去重：同特征/同区域同帧只真正匹配一次 |
| 判定（入口） | `is_screen` / `wait_screen` / `assert_screen` / `current_screen` | 同上 | 任务侧四个判定 API |
| 导航 | `transition()` | 同上 | 「点击入口 → 确认进入目标界面」守卫式转换原语 |
| 恢复 | `try_step` / `_recover_to_lobby` / `dismiss_all_popups` | 同上 | 失败截图 → 回大厅 → 有限重试 |
| 长等待 | `wait_battle_finish` + `_hit_interrupt` | 同上 | 节流轮询战斗结算；中断弹窗快速失败 |

## 1. 判定层

### 1.1 注册表 `src/screens.py`

纯数据模块（不 import ok 框架），两个常量：

- `SCREENS: dict`：9 个全局界面，字典顺序即注册顺序（`lobby` 在前）。基类构造时按序灌入 `self.screens`；任务可用 `register_screen(name, ..., **extra)` 追加私有界面，**同名覆盖全局**。
- `INTERRUPTS: {"screens": [...], "features": [...]}`：长等待中断哨兵的特征清单。当前为空 = 哨兵未激活、零开销；实机遇到断线/维护/登录过期弹窗后，把对应 coco 特征名加入 `features` 即激活。

现有 9 个界面：

| 界面 | 判据 | 原属任务 |
|---|---|---|
| `lobby` | features `[ark, lobby]` | 基类 |
| `ark` | features `[ark_tribe_tower, ark_simulation_room]` | ArkTask |
| `tribe_tower` | features `[tribe_tower_mark]` | ArkTask |
| `simulation_room` | features `[simulation_mark]` | ArkTask |
| `付费商店` | keywords `[付费商店]`, ocr_box `box_sub_pages_title` | CashShopTask |
| `coop_page` / `coop_nikke_select_page` / `solo_raid_page` / `solo_raid_battle_team_select_page` | 各 1 个 features | RaidTask |

### 1.2 spec 全字段

| 字段 | 默认 | 语义 | 作用面 |
|---|---|---|---|
| `features` | `()` | coco 特征名列表，全部命中（与） | 全部判定 API |
| `keywords` | `()` | OCR 关键词列表，任一命中（或）；与 features 同时配置时再取「与」 | 全部判定 API |
| `ocr_box` | `None` | OCR 区域：相对坐标列表或 coco 区域特征名；缺失退化为全屏 | 关键词判定 |
| `absent` | `[]` | 消歧特征：任一命中则该界面**直接判负**（消歧特征子集重叠的相邻界面） | `_screen_match`（影响全部判定 API） |
| `priority` | `0` | 仅影响 `current_screen()` 遍历顺序：降序、同级稳定保持注册序 | 仅 `current_screen` |
| `min_frames` | `1` | 轮询判定需连续 N 帧命中；未命中清零。`is_screen` 恒为单帧语义 | 仅 `wait_screen`/`assert_screen` |

缺省 = 演进前行为，现有 9 个条目均未填充扩展字段。

### 1.3 判定流程（`_screen_match`）

```
features 非空 ──逐个 find（缓存）──任一缺失/未命中──> False
      │全部命中
      ├─ 无 keywords ──> absent 检查
      └─ 有 keywords ──> 区域/全屏 OCR 关键词（或）──命中──> absent 检查
features 为空且 keywords 非空 ──> OCR 关键词（或）──命中──> absent 检查
两者皆空 ──> 记 warning，判 False
```

`absent` 检查 = 逐个特征「命中即 False」，走与 `features` 相同的缓存查找路径，特征在 coco 中缺失时按未命中处理（与 features 容错一致）。

四个入口的语义差异：

- `is_screen(name)`：单帧判定，不读 `min_frames`。
- `wait_screen(name, time_out=10, ...)`：`wait_until` 轮询；`min_frames` 生效——轮询每轮取新帧，连续命中计数，未命中清零，达到 N 才算进入。
- `assert_screen(name, time_out=10)`：wait 超时 → 调 `current_screen()` 写日志 → 抛 `WaitFailedException`（由 `try_step` 捕获）。
- `current_screen()`：按 `priority` 降序、同级注册序遍历，首个命中返回。

### 1.4 帧级缓存（为什么选择「帧对象同一性」）

- 缓存结构：`{("feat", 特征名) → (帧对象, Box|None)}`、`{("ocr", 区域键) → (帧对象, [boxes])}`；命中与**未命中**都进缓存（None 也是结果）。
- 失效双保险：① `next_frame()` 覆写——成功取到新帧即整体清空（取帧抛异常时不清，保证异常传播路径干净）；② 命中校验 `entry[0] is self.frame`——同一性校验兜住不经 `next_frame` 的换帧路径（测试的 `set_image` 等）。
- `ValueError`（特征在 coco 中缺失）不缓存、由调用方容错处理——避免把「特征缺失」误当「未命中」缓存下来。
- 对判定的影响：**零**。相同输入下结果与无缓存逐位一致，`tests/TestFrameCache.py` 用计数 mock 锁定了「同帧重复调用只匹配一次、换帧后重新匹配」。

### 1.5 标题区 OCR 合并

配置相同 `ocr_box` 的界面（如未来的多个标题类页面）同帧只跑一次区域 OCR，各条目的关键词集合对同一次 OCR 结果分别过滤。等价性依据：框架四个 OCR 后端的 `match` 过滤统一为 `fix_texts` 后 `find_boxes_by_name(detected, fix_match_regex(match))`；合并路径对未过滤结果调用同一对函数，语义逐位一致。全屏退化路径按条目隔离，不跨界面合并。

## 2. 导航层：`transition()`

### 2.1 语义

```python
transition(to_screen, click_feature=None, box=None, click=None,
           time_out=10, wait_confirm=3, retry_click=2, after_sleep=1)
```

```
循环至多 1 + retry_click 次：
  点击（三源之一：coco 特征 wait_click_feature / 框 click_box / 自定义可调用）
  wait_screen(to_screen, time_out=min(wait_confirm, 剩余总预算))
  命中 → return True
耗尽 → save_failure_screenshot(to_screen) → 抛 WaitFailedException（消息含目标与 current 识别结果）
```

要点：点击动作的等待与确认等待共享 `time_out` 总预算；每次确认等待被截到 `wait_confirm` 与剩余预算的较小值——短确认 + 原地补点消化「动画期吞点击」，不再让一次瞬时抖动触发整段回大厅重跑。

### 2.2 迁移点与有意保留点

已迁移 9 处（「点击入口 → assert_screen 确认」对）：

| 任务 | 转换 | 形式 |
|---|---|---|
| ArkTask | → `ark` / → `simulation_room` / → `tribe_tower` | `click_feature=...`，`wait_confirm=10` |
| CashShopTask | → `付费商店` | `click_feature="cash_shop"` |
| RaidTask | → `coop_page` | `box=`（预查框） |
| RaidTask | → `coop_nikke_select_page` | `click_feature="coop_accpet"`，`time_out=60` |
| RaidTask | → `solo_raid_battle_team_select_page` / → `solo_raid_page`（结算确认） | `click_feature=...` |
| RaidTask | → `solo_raid_page`（入口） | `box=`（预查框） |

有意保留 `assert_screen` 的两处：

- `ArkTask.py` 爬塔循环头 `assert_screen("tribe_tower")`：跨轮次重确认（点击发生在上一轮 `_climb_battle` 的 `common_back`），不是「点击→确认」转换边。
- `RaidTask.py` 战斗胜利后 `wait_click_feature("battle_finish_esc") + assert_screen("coop_page")`：战斗结算边（兜底确认点击 + 回页断言沿用既有结算语义）。

## 3. 恢复层

### 3.1 `try_step` 协议（语义未变）

包「入口方法」一层；内部步骤不逐个包；捕获 `WaitFailedException` → `save_failure_screenshot` → `_recover_to_lobby()` → 默认共尝试 3 次；耗尽后 `raise_on_fail` 决定抛出或跳过。

### 3.2 `_recover_to_lobby` 步骤

1. `next_frame()` 刷新（异常仅记录，不阻断）；
2. `dismiss_all_popups(clear_condition=lambda: is_screen("lobby"))`；
3. 已在 `lobby` → 返回 True；
4. `common_home` 特征存在则点击；
5. `wait_for_lobby(30s)` 确认。

`dismiss_all_popups` 的演进后语义：**每轮先尝试关一个弹窗；仅当本轮一个弹窗都没关到时才检查 `clear_condition`**。修复前的顺序是「先查条件、再关弹窗」——遮罩压暗下大厅特征可能仍命中（TM_CCOEFF_NORMED 对均匀变暗基本免疫），第一轮就谎报「清理完成」，弹窗留着而恢复报告成功。这是个已修复的确定缺陷（回归用例：`TestScreenRecovery.test_dismiss_all_popups_closes_popup_before_honoring_clear_condition`）。

### 3.3 中断哨兵

`wait_battle_finish` 每轮轮询顺序：**先 `_hit_interrupt()` 查 `INTERRUPTS["features"]`，再查 `battle_finish_*`**。命中中断特征 → `save_failure_screenshot("interrupt")` → 抛 `InterruptedByDialogException`（定义在 `NikkeBaseTask.py:18`，**继承 `WaitFailedException`**，故 `try_step` 的现有捕获/恢复自动生效，无需改恢复协议）。清单为空时 `_hit_interrupt` 零开销。`RaidTask` 协同匹配 60s 等待点同样挂了哨兵。

## 4. 弹窗 / 子界面的处理约定（三类）

| 类别 | 例 | 不注册为「界面」 | 处理机制 |
|---|---|---|---|
| A 模态弹窗（叠加在父页面上） | 好友/邮箱/公告/遮罩 | 是（独立维度） | 进流程前 `dismiss_all_popups`；恢复路径由 `_recover_to_lobby` 统一清；`_nav_*` 系列用「刷新→判定→清弹窗→再判定」两段式 |
| B 流程内顺序子页面 | 塔卡/关卡选择、队伍编成、快速战斗确认 | 是（顶替父页面，父特征消失） | 流程内特征/相对坐标推进；异常恢复依赖该页有无 `common_home` |
| C 全屏中断页 | 加载、断线、维护 | 是 | `INTERRUPTS` 哨兵在长等待中快速失败（特征待实机标注逐步补齐） |

判据特征几何约定：判据优先选顶栏/底栏/边缘元素；避免全部判据落入模态覆盖区（约 x∈[400,2160]、y∈[200,1150]，经验值待实机校准）。约束面向「新注册界面」与「将参与全局分类/恢复期判定的界面」；导航后立即断言的流程内界面不受此约束。

## 5. 测试地图

| 测试文件 | 覆盖层 |
|---|---|
| `TestScreenRecovery.py` | 注册表数据集、`_screen_match` 各分支、absent/priority/min_frames、`transition()` 吞点击与耗尽、`dismiss_all_popups` 顺序修复、`try_step`、`_recover_to_lobby` |
| `TestFrameCache.py` | 同帧去重、miss 缓存、`next_frame` 失效、`set_image` 失效兜底、区域 OCR 共享、全屏退化隔离 |
| `TestScreenRegistryIntegrity.py` | SCREENS 引用 ⊆ coco categories、无空 spec（纯静态、CI 拦截特征漂移） |
| `TestBattleWait.py` | 战斗轮询、中断快速失败、哨兵空清单零开销、`try_step` + 中断恢复兼容 |
| 各任务测试 | 迁移后的导航/流程行为 |

约定：全量验证必须逐文件独立进程（ok 单例同一进程不可重建，连跑会产生假错误）；改判定/恢复协议时同步更新 `TestScreenRecovery.py`，新关注点配独立测试文件。

## 6. Backlog（已识别，未做）

| 项 | 触发条件 |
|---|---|
| `simulation_mark`（正中心判据）条件迁移 | simulation_room 参与恢复期/全局分类时 |
| 模态覆盖区经验值实机校准 | 好友/邮箱弹窗实机复核后回填文档 |
| `when_unobscured`（遮罩下不算命中） | 判定层稳定后单独实施 |
| 方案 3：`common_back` 回退链 | 深层玩法增加 / 回大厅重跑成本实测不可接受 |
| 方案 4：界面图状态机 | 界面 ≥20 且共享前缀导航成为负担（前置：方案 1 + 3） |
| `INTERRUPTS` 特征清单 | 实机遭遇断线/维护/过期弹窗并标注 coco |
