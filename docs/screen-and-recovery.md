# 界面识别与失败恢复

本文是开发任务的统一约束：`NikkeBaseTask`（`src/tasks/NikkeBaseTask.py`）提供「界面识别 + 守卫式导航 + 失败恢复」三层骨架，全部复用 ok-script 现有 API。Agent 开发新任务必须遵守文末「约束」一节。

- 判定数据集中在 `src/screens.py`（单一数据源），判定/导航/恢复机制在 `NikkeBaseTask`。
- 帧级判定缓存对使用者完全透明：判定结果与无缓存逐位一致，使用本页 API 无需关心缓存。

## 界面识别

### 注册界面

全局界面统一注册在 `src/screens.py` 的 `SCREENS`（`NikkeBaseTask.__init__` 自动加载，不要重复注册）。**新增界面一律先加进 `SCREENS`**；`register_screen` 仅用于极少的任务私有界面（同名覆盖全局条目）：

```python
SCREENS = {
    "lobby": {"features": ["ark", "lobby"]},
    ...
    "新界面": {"features": ["xxx_feature"]},  # 追加在末尾
}
# 任务私有扩展（确有需要时）：
self.register_screen(name, features=(), keywords=(), ocr_box=None, **extra)
```

spec 字段（缺省即现状行为）：

| 字段 | 默认 | 语义 |
|---|---|---|
| `features` | `()` | coco 模板特征名列表，全部命中才算命中（与）。优先使用，匹配比 OCR 便宜且稳定 |
| `keywords` | `()` | OCR 关键词列表，任一命中即命中（或）；无稳定模板的页面才用 |
| `ocr_box` | `None` | 可选 OCR 区域：相对坐标 `[x, y, to_x, to_y]` 或 coco 区域特征名（按当前分辨率解析）；特征缺失退化为全屏 OCR |
| `absent` | `[]` | 消歧特征列表，任一命中则该界面直接判负（消歧特征子集重叠的相邻界面） |
| `priority` | `0` | 仅影响 `current_screen()` 返回顺序：降序遍历、同级保持注册序 |
| `min_frames` | `1` | 仅作用于 `wait_screen`/`assert_screen` 轮询：需连续 N 轮命中才判定进入；`is_screen` 恒为单帧语义，不受此字段影响 |

### 判断接口

| 方法 | 说明 |
| --- | --- |
| `current_screen()` | 在当前帧识别所处界面，按 `priority` 降序遍历，返回首个命中的界面名；未命中返回 `None`（常用于失败日志） |
| `is_screen(name)` | 单帧检测当前是否处于指定界面 |
| `wait_screen(name, time_out=10, raise_if_not_found=False)` | 等待进入指定界面；`min_frames` 连续命中语义在此生效 |
| `assert_screen(name, time_out=10)` | 断言处于指定界面，超时抛 `WaitFailedException`（配合 `try_step`） |

## 导航

### 入口闸门：`ensure_screen()`

子流程开头的「确保自己在某页面」统一用 `ensure_screen()`，不要再手写「`is_screen` 短路 + 等大厅 + 找入口 + 点入口 + 断言」的组合：

```python
self.ensure_screen("ark", click_feature="ark", wait_confirm=10, after_sleep=1)

# 入口需在进入大厅后动态查找，且入口缺失 = 本周期无可执行内容（如限时玩法）时，提供 entry 解析器：
def find_entry():
    box = self._find_panel_entry("coop", panel)
    if box is None:
        self.log_info("未找到协同作战入口，视为已完成。")
    return box
if not self.ensure_screen("coop_page", entry=find_entry, wait_confirm=10, after_sleep=1):
    return  # 入口缺失：由调用方标记完成。
```

内部行为：已在/正在过场进入目标页 → 直接返回（每轮 `wait_enter=5` 秒轮询容忍滑入动画）→ 清弹窗再等一轮 → 按分流走冷启动或恢复（正向命中 `login_page` 或无任何应用内证据 → 冷启动 `wait_until_lobby_after_start`；有应用内证据 → `_recover_to_lobby`）→ 清大厅弹窗 → 有点击源 `transition()` 守卫式进入（entry 解析器在到大厅之后才调用，返回 None 则返回 False）；无点击源（目标即大厅）→ 尾段 `wait_screen` 确认。默认 `raise_on_fail=True`（供 `try_step` 恢复）；任务开头用 `raise_on_fail=False` 优雅中止。登录页 `login_page`（关键词 TOUCH TO CONTINUE + `box_enter_game` 区域）注册在 `src/screens.py` 作为冷启动正向锚点——命中即明确冷启动入口，覆盖按钮推定。任务开头的就位大厅统一用 `ensure_screen("lobby")`（HarvestTask/OutpostDefenseTask/ShopTask/CashShopTask/RaidTask/DailyTask 六处开头已统一），它的大厅「入口」不是点击边而是冷启动引导这段程序化流程。

### 转换边：`transition()`

任务里「点击入口 → 确认进入目标界面」的转换**一律用 `transition()`**，不再手写 `wait_click_feature(...) + assert_screen(...)` 两行：

```python
self.transition("tribe_tower", click_feature="ark_tribe_tower", wait_confirm=10, after_sleep=1)
self.transition("coop_page", box=coop_box, after_sleep=1)  # 已预查出的框走 box=
```

- 点击源三选一：`click_feature`（coco 特征，走 `wait_click_feature`）、`box`（框/区域名，`click_box`）、`click`（自定义可调用）。
- 点击后未在 `wait_confirm` 秒内进入目标界面就**原地补点**，至多 `retry_click` 次（默认 2）；耗尽则保存失败截图并抛带 from/to 上下文的 `WaitFailedException`（由 `try_step` 捕获恢复）。
- 点击等待与确认等待共享 `time_out` 总预算；进战斗等长加载边调大 `wait_confirm`/`time_out`。

**不适用于**：战斗结算确认等已带专用语义的边（`wait_battle_finish` 后的确认/返回）、循环头部的「重确认仍在本页」断言（这类保留 `assert_screen`）、以及「入口在画面但已关闭」的休赛期入口边（如竞技场赛季已结束：点击后目标界面不会出现，`transition` 会按失败重试并触发恢复协议。这类改为点击后用 `wait_until` 赛跑「目标界面 vs 关闭态信号」——命中关闭信号 = 本周期无可执行内容，按「视为已完成」收尾而非走失败恢复；实现参考 `ArkTask._click_entry_race_closed`（新人/特殊竞技场入口共用）与其 `_hit_season_end_banner`，关闭态用 OCR 正则部分匹配判定（框架对普通字符串走全等，OCR 文本常带尾随标点，必须用 `re.Pattern`）、区域限横幅所在的中部横带；瞬态信号淡出快于框架默认 1 秒 settle 窗口时（实测横幅约 0.3~0.5 秒），赛跑的 `wait_until` 必须传 `settle_time=0` 首帧命中即短路；同理，一切瞬态 toast 检测（如 `ShopTask._buy_cell` 的资金不足提示，OCR 关键词走 `re.Pattern` 部分匹配）的赛跑也必须 `settle_time=0`，否则会「每帧命中却不返回」直至超时，把失败误判成成功。

### 逐级返回：`_back_through_screens()`

退出子页面逐级返回原语：`_back_through_screens(*screens)` 每级先 `wait_click_feature("common_back")` 再 `assert_screen(该级界面)`，逐级退回（如「子页面 → 竞技场 → 方舟」传 `("arena", "ark")`）。用于多级返回场景，代替手写多次「点 common_back + 断言」。

## 失败恢复

```python
self.try_step(step_fn, name=None, retries=2, recover=True, raise_on_fail=True) -> bool
```

`try_step` 包裹一个从大厅出发的子流程入口方法；步骤内抛出的 `WaitFailedException`（含子类 `InterruptedByDialogException`）触发恢复协议：

1. `save_failure_screenshot(tag)` 保存失败现场截图到 `screenshots/failure/`；
2. 记录本次失败；
3. `_recover_to_lobby()` 恢复：刷新帧 → `dismiss_all_popups(clear_condition=is_screen("lobby"))` 清弹窗 → 按 `common_home` 特征回大厅 → `wait_for_lobby()` 确认；
4. 有限重试（`retries` 次，默认共尝试 3 次）；恢复失败则提前放弃；重试耗尽后按 `raise_on_fail` 决定抛出异常或返回 `False`。

`dismiss_all_popups` 的语义要点：**每轮先尝试关一个弹窗，仅当本轮一个都关不到时才检查 `clear_condition`**——遮罩压暗下目标界面特征可能仍命中，先查条件会谎报清理完成。`clear_condition` 因此必须配合「条件满足且无弹窗可关」才成立理解。

`_recover_to_lobby` 是普通实例方法，子任务需要额外恢复动作时可覆盖它。

### 粒度：包「入口方法」，不要逐个包内部步骤

`try_step` 的正确粒度是**入口方法**：一个「从大厅出发、自己完成整段导航与操作」的子流程方法。因为失败后要恢复回大厅再重跑，被包裹的步骤必须能从大厅重入；内部步骤依赖入口方法的前置导航链才能到达目标页面，逐个包裹反而会造成冗余恢复和上下文丢失。

- 每个入口方法在 `run()` 里用 `try_step` 包**一层**。
- 方法内部步骤**不单独包**：任一步抛 `WaitFailedException` 会冒泡到外层，回大厅后整个入口方法从头重跑。
- 某个步骤只需原地重试（如瞬时 OCR/模板抖动）时，用 `recover=False` 只重试、不恢复回大厅。

## 长等待与中断哨兵

- 自动战斗结束等待用 `wait_battle_finish(time_out=240, check_interval=3, settle_time=2)`（节流轮询、只检测不点击，返回 `("success", esc)` / `("failed", back)` / `(None, None)`，后续动作由调用方决定）。长时间等战斗不要用 `wait_feature`/`wait_ocr` 忙轮询。
- 中断哨兵：`wait_battle_finish` 与 `RaidTask` 的 60s 匹配等待在每轮轮询中先查 `src/screens.py` 的 `INTERRUPTS["features"]`，命中即抛 `InterruptedByDialogException`（继承 `WaitFailedException`，`try_step` 自动兼容）。清单当前为空 = 未激活、零开销。
- 实机遇到断线/维护/登录过期弹窗：先把弹窗特征标注进 coco，再把特征名加入 `INTERRUPTS["features"]`，并给 `tests/TestBattleWait.py` 加对应用例。

## 弹窗与临时子页面约定

- **不把好友/邮箱/公告等模态弹窗注册为界面**——它们是「什么挡着我」的独立维度，由 `dismiss_all_popups`/`close_overlay` 机制处理。
- **不把塔卡/关卡选择、队伍编成等流程内顺序子页面注册为界面**——它们顶替父页面、父特征消失，流程内靠特征/坐标推进；做失败恢复时注意这些页面不一定有 `common_home`。
- 进入流程前先 `dismiss_all_popups` 清弹窗再判定界面；`_nav_*` 型入口沿用「刷新帧 → 判定 → 清弹窗 → 再刷新 → 再判定」的两段式。
- 判据特征几何约束：判据优先选**顶栏/底栏/边缘**元素，避免全部判据落入典型模态覆盖区（约 x∈[400,2160]、y∈[200,1150]，2560×1440 基准，经验值待实机校准）。适用对象：今后新注册的界面、以及将参与全局分类/恢复期判定的界面；流程内部导航后立即断言的界面不受此约束。

## 素材分辨率基准（2560x1440）

本项目所有模板相关素材都以 **2560x1440 作为唯一基准分辨率**。Agent 在做调试、截图、标注时务必遵守：

- **调试截图**：用于复现问题、调试 OCR、失败分析的用户/测试截图，尽量截 2560x1440 的窗口。低分辨率截图（如 1280x720）细节少，用它在 1440p 环境下调试模板/OCR，会得出与真实环境不一致的结论（缩放、阈值、OCR 误识别都会偏移）。
- **coco 标注**：在 2560x1440 截图上画框标注（`assets/coco_annotations.json`）。`FeatureSet` 会把标注自动缩放到当前游戏分辨率，源图分辨率越低，放大后的模板越模糊、越容易失配。
- **手动裁剪模板**：`assets/template/` 下的小模板一律从 2560x1440 截图裁剪，再交给 `find_scaled_template`（`ref_width=2560, ref_height=1440` 默认值）。1440p 是所有受支持分辨率（1920x1080/1600x900/1280x720）的天花板，从此基准出发只会缩小、不会放大，匹配最稳。

例外：如果确实只有非 1440p 截图，技术上仍可用（coco 按源图自身尺寸缩放；`find_scaled_template` 可传 `ref_width`/`ref_height` 覆盖），但必须记住该素材的原始分辨率并显式声明，不要把它当成默认基准。

## 使用示例

```python
# 每个入口方法（子流程）包一层 try_step，方法内部步骤不逐个包。
if not self.try_step(self._collect_friend, name="收获友情点", raise_on_fail=False):
    self.log_warning("友情点收取失败，跳过。")

# 新界面加到 src/screens.py 的 SCREENS:
#   "我的页面": {"features": ["my_page_mark"]},
# 导航边用 transition()：
self.transition("我的页面", click_feature="my_entry", wait_confirm=10, after_sleep=1)

# 已在目标页则跳过导航的入口模式：
if not self.is_screen("我的页面"):
    self.wait_for_lobby()
    self.dismiss_all_popups(wait_for_popup=False, time_out=10)
    self.transition("我的页面", click_feature="my_entry")
```

## 约束（Agent 开发必须遵守）

- 全局界面注册在 `src/screens.py` 的 `SCREENS`；`register_screen` 只用于任务私有界面；大厅 `lobby` 已由基类注册，不要重复注册。
- 注册界面是**可选**的：仅在确实需要识别/等待某界面（`is_screen`/`wait_screen`/`assert_screen`，或作为恢复目标/分类需求）时才注册。好友、邮箱等临时弹层与只点击几次的简单任务，都不需要注册额外界面。
- spec 字段语义以本页表格为准：`absent`/`priority`/`min_frames` 缺省即现状行为；不要用它们实现与表格不符的语义。
- 「点击入口 → 确认进入目标界面」的导航边一律用 `transition()`；例外仅限战斗结算类专用边与循环内重确认断言。子流程开头的幂等入口闸门用 `ensure_screen()`，不要手写「`is_screen` 短路 + 等大厅 + 找入口 + 点入口」的组合。
- `try_step` 的粒度是「入口方法」：每个从大厅出发、自包含导航的子流程在 `run()` 里包**一层**；方法内部步骤不要逐个包；禁止手写临时重试/恢复逻辑。
- 不要绕过 `_recover_to_lobby` 自行硬编码「按坐标回大厅」等恢复动作。
- 失败截图统一由 `save_failure_screenshot` 存到 `screenshots/failure/`；`transition`/哨兵内部已统一调用，业务代码不要另存。
- 界面判定优先用 coco 模板特征；只有无稳定模板的页面才用 OCR 关键词，并尽量限定 `ocr_box`。
- `close_overlay` 默认 `require_click=True`：显式调用它时必定要成功关闭（点击）至少一次遮罩，超时未点到抛 `WaitFailedException`。恢复流程等容错场景调用时必须传 `require_click=False`。
- 判定特征几何约束：新注册界面的判据特征优先选顶栏/底栏/边缘元素；避免全部判据特征的 bbox 落入典型模态覆盖区（x∈[400,2160]、y∈[200,1150]，2560×1440 基准，经验值待实机以好友/邮箱弹窗校准）。Backlog：`simulation_mark`（正中心）当前唯一使用点是导航后立即断言，不受约束；仅当 simulation_room 参与恢复期/全局分类时才更换判据。
- 素材分辨率基准：调试截图、coco 标注、手动裁剪模板一律以 2560x1440 为基准（见上文），不要拿低分辨率截图调试或标注。
- 中断弹窗维护：实机遇到断线/维护/登录过期弹窗 → 标注进 coco → 加入 `INTERRUPTS["features"]` → `TestBattleWait.py` 补用例。
- 调整恢复协议或判定方式时，同步更新 `tests/TestScreenRecovery.py`；新增关注点（如缓存、注册表完整性）配独立测试文件。

## 测试

- `tests/TestScreenRecovery.py`：界面识别各分支、`absent`/`priority`/`min_frames`、`transition()`、`try_step`、`dismiss_all_popups`、`_recover_to_lobby`。
- `tests/TestFrameCache.py`：帧级缓存的同帧去重与换帧失效（含 `set_image` 路径）。
- `tests/TestScreenRegistryIntegrity.py`：静态校验 `SCREENS` 引用的特征都存在于 `assets/coco_annotations.json`（coco 重建删特征会被 CI 拦下）。
- `tests/TestBattleWait.py`：战斗等待轮询与中断哨兵快速失败。
- 全量验证必须逐文件独立进程执行（如 `run_tests.ps1`）；严禁一条命令连跑多个测试文件（ok 单例在同一进程内不可重建，会产生假错误）。
