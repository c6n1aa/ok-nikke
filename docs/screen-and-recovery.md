# 界面识别与失败恢复

开发任务的统一约束：`NikkeBaseTask`（`src/tasks/NikkeBaseTask.py`）提供「界面识别 + 守卫式导航 + 失败恢复」三层骨架，全部复用 ok-script API。判定数据集中在 `src/screens.py`（单一数据源），机制在 `NikkeBaseTask`（实现按职责拆在 `src/tasks/base/` 下的 mixin，基类只做组合）。帧级判定缓存对使用者透明：判定结果与无缓存逐位一致，无需关心。

## 界面识别

### 注册界面

全局界面统一注册在 `src/screens.py` 的 `SCREENS`（`NikkeBaseTask.__init__` 自动加载，含大厅 `lobby`，不要重复注册）。**新增界面一律先加进 `SCREENS`**（追加在末尾）；`register_screen(name, features=(), keywords=(), ocr_box=None, **extra)` 仅用于极少的任务私有界面（同名覆盖全局条目）。

注册是**可选**的：仅在需要识别/等待某界面（`is_screen`/`wait_screen`/`assert_screen`，或作为恢复目标）时才注册；好友、邮箱等临时弹层与只点几次的简单任务不需要注册。

spec 字段（缺省即现状行为；不要实现与表格不符的语义）：

| 字段 | 默认 | 语义 |
|---|---|---|
| `features` | `()` | coco 模板特征名列表，全部命中才算命中（与）。优先使用，比 OCR 便宜且稳定；无稳定模板的页面才用 OCR |
| `any_features` | `()` | 特征名任一命中即特征命中（或）；与 `keywords` 同配时再取「与」。用于图标三选一等「或」语义 |
| `feature_box` | `None` | 匹配区域（coco 区域特征名，按当前分辨率解析），仅作用于 `any_features`；缺失退化为全屏匹配 |
| `keywords` | `()` | OCR 关键词列表，任一命中即命中（或）；尽量配合 `ocr_box` 限定区域 |
| `ocr_box` | `None` | OCR 区域：相对坐标 `[x, y, to_x, to_y]` 或 coco 区域特征名；缺失退化为全屏 OCR |
| `absent` | `[]` | 消歧特征列表，任一命中则该界面判负（用于特征子集重叠的相邻界面） |
| `priority` | `0` | 仅影响 `current_screen()` 顺序：降序遍历、同级保持注册序 |
| `min_frames` | `1` | 仅作用于 `wait_screen`/`assert_screen` 轮询：连续 N 轮命中才算进入；`is_screen` 恒为单帧语义 |

### 判断接口

| 方法 | 说明 |
| --- | --- |
| `current_screen()` | 当前帧识别所处界面，按 `priority` 降序返回首个命中；未命中返回 `None`（常用于失败日志） |
| `is_screen(name)` | 单帧检测是否处于指定界面 |
| `wait_screen(name, time_out=10, raise_if_not_found=False)` | 等待进入指定界面；`min_frames` 连续命中语义在此生效 |
| `assert_screen(name, time_out=10)` | 断言处于指定界面，超时抛 `WaitFailedException`（配合 `try_step`） |

## 导航

### 入口闸门：`ensure_screen()`

子流程开头的「确保自己在某页面」统一用 `ensure_screen()`，不要手写「`is_screen` 短路 + 等大厅 + 找入口 + 点入口 + 断言」组合：

```python
self.ensure_screen("ark", click_feature="ark", wait_confirm=10, after_sleep=1)

# 入口缺失 = 本周期无可执行内容（如限时玩法）时，提供 entry 解析器（到大厅后才调用）：
def find_entry():
    box = self._find_panel_entry("coop", panel)
    if box is None:
        self.log_info("未找到协同作战入口，视为已完成。")
    return box
if not self.ensure_screen("coop_page", entry=find_entry, wait_confirm=10, after_sleep=1):
    return  # 入口缺失返回 False，由调用方标记完成
```

行为：已在/正在过场进入目标页 → 直接返回（每轮 `wait_enter=5` 轮询容忍滑入动画）→ 清弹窗再等一轮 → 分流：正向命中 `login_page` 或无任何应用内证据 → 冷启动 `wait_until_lobby_after_start`；有应用内证据 → `_recover_to_lobby` → 清大厅弹窗 → 有点击源走 `transition()` 进入；无点击源（目标即大厅）→ 尾段 `wait_screen` 确认。`raise_on_fail` 默认 `True`（供 `try_step` 恢复）；任务开头用 `raise_on_fail=False` 优雅中止。

任务开头的就位大厅统一用 `ensure_screen("lobby")`（大厅「入口」是冷启动引导这段程序化流程，不是点击边）。冷启动正向锚点 `login_page`（TOUCH TO CONTINUE + `box_enter_game` 区域）注册在 `src/screens.py`。

### 转换边：`transition()`

「点击入口 → 确认进入目标界面」的转换**一律用 `transition()`**，不手写 `wait_click_feature(...) + assert_screen(...)` 两行：

```python
self.transition("tribe_tower", click_feature="ark_tribe_tower", wait_confirm=10, after_sleep=1)
self.transition("coop_page", box=coop_box, after_sleep=1)  # 已预查出的框走 box=
```

- 点击源三选一：`click_feature`（coco 特征）、`box`（框/区域名）、`click`（自定义可调用）。
- 未在 `wait_confirm` 秒内进入目标界面就**原地补点**，至多 `retry_click` 次（默认 2）；耗尽则保存失败截图并抛带 from/to 上下文的 `WaitFailedException`。点击等待与确认等待共享 `time_out` 总预算；进战斗等长加载边调大 `wait_confirm`/`time_out`。

**不适用的边**：

- 战斗结算确认等专用边（`wait_battle_finish` 后的确认/返回）；
- 循环头部「重确认仍在本页」断言（保留 `assert_screen`）；
- 「入口在画面但已关闭」的休赛期入口（如竞技场赛季结束）：点击后目标界面不会出现，`transition` 会误判失败触发恢复。改为点击后用 `wait_until` 赛跑「目标界面 vs 关闭态信号」，命中关闭信号 = 本周期无可执行内容，按「视为已完成」收尾。参考 `ArkTask._click_entry_race_closed` / `_hit_season_end_banner`：关闭态用 `re.Pattern` 部分匹配（框架对普通字符串走全等，OCR 文本常带尾随标点），区域限中部横幅横带；瞬态信号（横幅约 0.3~0.5 秒，快于框架默认 1 秒 settle 窗口）的赛跑必须传 `settle_time=0`，否则「每帧命中却不返回」直至超时、把失败误判成成功。瞬态 toast 检测（如 `ShopTask._buy_cell` 的资金不足提示）同理。

### 逐级返回：`_back_through_screens()`

`_back_through_screens(*screens)` 每级先 `wait_click_feature("common_back")` 再 `assert_screen(该级界面)`，逐级退回（如「子页面 → 竞技场 → 方舟」传 `("arena", "ark")`）。用于多级返回场景，代替手写多次「点 common_back + 断言」。

## 失败恢复

```python
self.try_step(step_fn, name=None, retries=2, recover=True, raise_on_fail=True) -> bool
```

包裹一个从大厅出发的子流程入口方法；步骤内抛出的 `WaitFailedException`（含子类 `InterruptedByDialogException`）触发恢复协议：

1. `save_failure_screenshot(tag)` 存现场到 `screenshots/failure/`（失败截图统一走它，`transition`/哨兵内部已调用，业务代码不另存）；
2. 记录失败；
3. `_recover_to_lobby()`：刷新帧 → `dismiss_all_popups(clear_condition=is_screen("lobby"))` → 按 `common_home` 回大厅 → `wait_for_lobby()` 确认。它是普通实例方法，子任务可覆盖追加恢复动作；禁止绕过它硬编码「按坐标回大厅」；
4. 有限重试（默认共尝试 3 次）；恢复失败提前放弃；重试耗尽按 `raise_on_fail` 决定抛异常或返回 `False`。

`dismiss_all_popups` 语义要点：**每轮先尝试关一个弹窗，仅当本轮一个都关不到时才检查 `clear_condition`**——遮罩压暗下目标界面特征可能仍命中，先查条件会谎报清理完成。

### 粒度：包「入口方法」一层

正确粒度是**入口方法**：一个「从大厅出发、自己完成整段导航与操作」的子流程。失败后要回大厅重跑，被包裹的步骤必须能从大厅重入；内部步骤依赖入口方法的前置导航链，逐个包裹只会造成冗余恢复和上下文丢失。

- 每个入口方法在 `run()` 里包**一层**；内部步骤**不单独包**——任一步抛 `WaitFailedException` 冒泡到外层，回大厅后整个入口方法从头重跑。
- 只需原地重试（瞬时 OCR/模板抖动）时用 `recover=False`，不恢复回大厅。
- 禁止手写临时重试/恢复逻辑。

## 长等待与中断哨兵

- 自动战斗结束等待用 `wait_battle_finish(time_out=240, check_interval=3, settle_time=2)`：节流轮询、只检测不点击；胜利结算对 `box_battle_finish_text` 区域 OCR 识别 ESC 文字，`box_battle_finish_bottom_right` 内 `battle_finish_statistics` 兜底，命中稳定后返回 `("success", text_box)`（可点击框统一为 `box_battle_finish_text` 区域）/ `("failed", back)` / `(None, None)`，后续动作由调用方决定。长时间等战斗不要用 `wait_feature`/`wait_ocr` 忙轮询。
- 中断哨兵：`wait_battle_finish` 每轮轮询先查 `src/screens.py` 的 `INTERRUPTS["features"]`，命中即抛 `InterruptedByDialogException`（继承 `WaitFailedException`，`try_step` 自动兼容）。清单为空 = 未激活、零开销。
- 实机遇到断线/维护/登录过期弹窗：标注进 coco → 特征名加入 `INTERRUPTS["features"]` → 给 `tests/TestBattleWait.py` 补用例。

## 弹窗与临时子页面约定

- **不把好友/邮箱/公告/登录奖励等模态弹窗注册为界面**——它们是「什么挡着我」的独立维度，由 `dismiss_all_popups`/`close_overlay` 处理。
- **新增弹窗只挂 `_try_close_one_popup`**（在 `src/tasks/base/_popups.py` 的 `PopupsMixin` 加 `_close_xxx_popup`，每次只走一步，多段由 `dismiss_all_popups` 逐轮推进）：一次挂接覆盖冷启动/恢复/子流程全部清理入口；顺序**按遮挡层级从上到下**（卢比 → 公告 → 遮罩 → 登录奖励面板），压上层的先关，否则下层关闭按钮会跳过上层遮罩。
- **模态弹窗关闭统一走 `close_popup_by_blank(verify)`**：点面板外空白（缺省 `_MODAL_BLANK_CLOSE_X/_Y`）+ 按 `verify`（不随皮肤变的「弹窗已关闭」判据，如界面特征消失、判据文字消失）确认关闭，未确认自动补点。面板皮肤逐期变化、关闭按钮外观/位置随之漂移，模板识别需逐期追加维护；面板外区域恒被模态遮罩覆盖，点空白等价于点遮罩关闭、对皮肤免疫。`ExtrasTask` 关 PASS 模态窗、`_close_daily_login_popup` 关登录奖励面板均用它。
- **皮肤会变的弹窗只挑不随皮肤变的判据**：登录奖励每期样式不同，存在判据只认「全部领取」文字（OCR）；判可领与否看按钮底色，OCR 只给白字框，按 `_DAILY_LOGIN_CLAIM_PAD` 外扩后再 `is_feature_enabled`。
- **不把塔卡/关卡选择、队伍编成等流程内顺序子页面注册为界面**——它们顶替父页面、父特征消失，流程内靠特征/坐标推进；注意这些页面不一定有 `common_home`。
- 进入流程前先 `dismiss_all_popups` 再判定界面；`_nav_*` 型入口沿用「刷新帧 → 判定 → 清弹窗 → 再刷新 → 再判定」两段式。
- `close_overlay` 默认 `require_click=True`：必须成功点击关闭至少一次遮罩，超时未点到抛 `WaitFailedException`；恢复流程等容错场景必须传 `require_click=False`。
- 判据特征几何约束：判据优先选**顶栏/底栏/边缘**元素，避免全部判据落入典型模态覆盖区（x∈[400,2160]、y∈[200,1150]，2560×1440 基准，经验值待实机以好友/邮箱弹窗校准）。适用于新注册界面及参与全局分类/恢复判定的界面；流程内导航后立即断言的界面不受此约束。判据落在遮挡区时用 `any_features` 并列遮挡物特征（`simulation_mark` 与模拟室超频更新弹窗即如此）。

## 素材分辨率基准（2560x1440）

所有模板素材以 **2560x1440 为唯一基准**：调试截图截 1440p 窗口（低分辨率截图调模板/OCR 会因缩放、阈值、误识别偏移得出与真实环境不一致的结论）；coco 标注在 2560x1440 截图上画框；`assets/template/` 小图从 2560x1440 截图裁剪（`find_scaled_template` 默认 `ref_width=2560, ref_height=1440`）。1440p 是所有受支持分辨率（1920x1080/1600x900/1280x720）的天花板，只会缩小不会放大，匹配最稳。

例外：非 1440p 素材技术上可用（coco 按源图自身尺寸缩放；`find_scaled_template` 可传 `ref_width`/`ref_height`），但必须记住该素材的原始分辨率并显式声明。

## 测试

- `tests/TestScreenRecovery.py`：界面识别各分支、`absent`/`any_features`/`priority`/`min_frames`、`transition()`、`try_step`、`dismiss_all_popups`、`_recover_to_lobby`。调整恢复协议或判定方式时同步更新；新增关注点（缓存、注册表完整性等）配独立测试文件。
- `tests/TestFrameCache.py`：帧级缓存的同帧去重与换帧失效（含 `set_image` 路径）。
- `tests/TestScreenRegistryIntegrity.py`：静态校验 `SCREENS` 引用的特征存在于 `assets/coco_annotations.json`（coco 重建删特征会被 CI 拦下）。
- `tests/TestBattleWait.py`：战斗等待轮询与中断哨兵快速失败。
- 全量验证必须逐文件独立进程执行（`run_tests.ps1`）；严禁一条命令连跑多个测试文件（ok 单例同进程不可重建，会产生假错误）。
