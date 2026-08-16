# 界面识别与失败恢复

本文介绍 `MyBaseTask`（`src/tasks/MyBaseTask.py`）提供的通用「界面识别」与「失败恢复」骨架。这是后续任务开发的统一约束，Agent 在开发新任务时必须遵守文末的「约束」一节。

## 背景

早期任务各自用 `wait_feature`/`wait_click_feature`，默认「点完入口就已在目标页面」。一旦遇到弹窗、加载慢、网络波动等意外界面，后续等待会超时并抛出 `WaitFailedException`，任务停在半路且没有任何恢复动作，下一个任务还会基于错误的界面假设继续操作。

为此，`MyBaseTask` 沉淀了一套轻量、可抽象、可扩展的通用机制，全部复用 ok-script 现有 API，不引入新的框架概念。

## 方案 A：界面识别

界面注册表 `self.screens` 把「界面名」映射为「判定条件」，判定复用模板特征与 OCR 两类 ok-script 能力。

### 注册界面

```python
self.register_screen(name, features=(), keywords=(), ocr_box=None)
```

- `features`：coco 标注的模板特征名列表，全部命中才判定为该界面。优先使用模板特征——匹配比 OCR 便宜且稳定（如 `"ark"`、`"friend"`）。
- `keywords`：OCR 关键词列表，任一命中即判定为该界面，用于没有稳定模板的页面。
- `ocr_box`：可选 OCR 区域相对坐标 `[x, y, to_x, to_y]`，缩小 OCR 范围以降低开销。

`MyBaseTask.__init__` 默认注册了大厅界面：`register_screen("lobby", features=["ark"])`，即「识别到方舟按钮 = 已回到大厅」。

> 注册是**可选**的：只在确实需要识别/等待该界面（`is_screen`/`wait_screen`/`assert_screen`）或把它作为恢复目标时才注册。好友、邮箱等临时弹层/弹窗页面，以及只点击几次的简单任务，都不需要注册额外界面。

### 判断接口

| 方法 | 说明 |
| --- | --- |
| `current_screen()` | 在当前帧识别所处界面，返回界面名；未命中返回 `None`（常用于失败日志）。 |
| `is_screen(name)` | 单帧检测当前是否处于指定界面。 |
| `wait_screen(name, time_out=10, raise_if_not_found=False)` | 等待进入指定界面，复用 `wait_until` 的轮询与超时机制。 |
| `assert_screen(name, time_out=10)` | 断言处于指定界面，超时抛 `WaitFailedException`（通常配合 `try_step` 使用）。 |

## 方案 B：失败恢复

```python
self.try_step(step_fn, name=None, retries=2, recover=True, raise_on_fail=True) -> bool
```

`try_step` 包裹一个从大厅出发的子流程（入口方法），步骤内以 `raise_if_not_found=True` 抛出的 `WaitFailedException` 会触发恢复协议：

1. `save_failure_screenshot(tag)` 保存失败现场截图到 `screenshots/failure/`；
2. 记录本次失败；
3. `_recover_to_lobby()` 恢复：刷新帧 → `close_overlay()` 关闭弹窗 → 按 `common_home` 特征回大厅 → `wait_for_lobby()` 确认已回到大厅；
4. 有限重试（`retries` 次，默认共尝试 3 次）；
5. 恢复回大厅失败则提前放弃；重试耗尽后按 `raise_on_fail` 决定抛出异常，或返回 `False` 由调用方决定「跳过继续」。

`_recover_to_lobby` 是普通实例方法，子任务需要额外恢复动作（如额外的关闭按钮）时可覆盖它。

### 粒度：包「入口方法」，不要逐个包内部步骤

`try_step` 的正确粒度是**入口方法**：一个「从大厅出发、自己完成整段导航与操作」的子流程方法。因为失败后要恢复回大厅再重跑，被包裹的步骤必须能从大厅重入；内部步骤依赖入口方法的前置导航链才能到达目标页面，逐个包裹反而会造成冗余恢复和上下文丢失。

- 每个入口方法在 `run()` 里用 `try_step` 包**一层**。
- 方法内部的导航/操作步骤**不单独包**：任一步抛 `WaitFailedException` 会冒泡到外层 `try_step`，回大厅后整个入口方法从头重跑，前置步骤链自然重来。
- 若某个步骤只需原地重试（如瞬时 OCR/模板抖动），可用 `recover=False` 只重试、不恢复回大厅。

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
if not self.try_step(self._collect_mailbox, name="收取邮箱", raise_on_fail=False):
    self.log_warning("邮箱收取失败，跳过。")

# 只有确实需要识别/等待某个界面时才注册，再配合断言使用。
self.register_screen("方舟塔", features=["ark_tribe_tower"])
self.assert_screen("方舟塔", time_out=10)
```

## 约束（Agent 开发必须遵守）

- 注册界面是**可选**的：仅在任务确实需要识别某个界面（`is_screen`/`wait_screen`/`assert_screen`）或把它作为恢复目标时才用 `register_screen` 注册。好友、邮箱等临时弹层/弹窗页面，以及只点击几次的简单任务，都不需要注册额外界面。
- 大厅 `lobby` 已默认注册，作为 `_recover_to_lobby` 的恢复目标，无需重复注册。
- `try_step` 的粒度是「入口方法」：每个从大厅出发、自包含导航的子流程方法在 `run()` 里包**一层** `try_step(...)`；方法内部步骤不要逐个包（失败会冒泡到外层，回大厅后整个子流程重跑）。禁止手写临时重试/恢复逻辑。
- 不要绕过 `_recover_to_lobby` 自行硬编码「按坐标回大厅」等恢复动作。
- 失败截图统一由 `save_failure_screenshot` 存到 `screenshots/failure/`，不要在别处另存。
- 界面判定优先用 coco 模板特征；只有无稳定模板的页面才用 OCR 关键词，并尽量限定 `ocr_box`。
- 素材分辨率基准：调试截图、coco 标注、手动裁剪模板一律以 2560x1440 为基准（见上文「素材分辨率基准」一节），不要拿低分辨率截图调试或标注。
- 调整恢复协议或新增判定方式时，同步更新 `tests/TestScreenRecovery.py`。

## 测试

`tests/TestScreenRecovery.py` 覆盖界面识别（模板/OCR 判定、未命中）、`try_step`（成功、重试、跳过、恢复失败提前放弃）以及 `_recover_to_lobby`（已在大厅 / 按 `common_home` 回大厅）等行为。