# P1.2 帧级匹配缓存 + 标题区 OCR 合并

> 上游依据：`docs/screen-recovery-evolution-plan.md` §5.3 子项 2、§6 Phase 1.2
> 工作分支：`feature/screen-recovery-evolution`；依赖：P1.1。
> 预计改动面：`src/tasks/NikkeBaseTask.py`（判定调用路径）+ 新增测试文件。

## 目标

同一帧上重复的判定不再重复匹配：`current_screen()`/`is_screen()`/`wait_screen()` 在同一帧内对同一特征只匹配一次；共享 `ocr_box` 的标题类界面同帧内只做一次区域 OCR。**判定结果必须与之前逐位一致**——本项是纯性能优化，不得改变任何命中判定。

## 背景与现状

框架只有模板预处理缓存（`FeatureSet.py:279-298`，按灰度/canny 参数缓存模板），**没有**按帧缓存匹配结果：`find_one` 每次调用重跑 `matchTemplate`（搜索范围 = 标注框 ± variance，`FeatureSet.py:211-281`）；`_match_ocr_keywords`（`NikkeBaseTask.py:604-619`）每次调用重跑区域 OCR。现状 `current_screen` 逐界面全扫、`assert_screen` 失败还要为日志再全扫一遍。

## 实施步骤

1. 在 `NikkeBaseTask` 增加帧级缓存：`{frame_key: {feature_name: Box | None}}`（以及 OCR 结果缓存 `{frame_key: {(box_key): [boxes]}}`）。**frame_key 必须在帧变化时失效**。实现建议（以最终源码为准）：
   - 基类覆写 `next_frame(...)`：调用父类取得新帧后递增单调计数器并清空缓存。
   - 缓存 key 同时携带帧对象身份（如 `id(self.frame)`）与计数器，二者任一变化即视为新帧——覆盖 `tests` 里 `set_image`（不经 `next_frame`）替换静态图的场景，避免陈旧缓存。
   - 实现前先阅读 `src/patches/runtime.py` 与 `ok` 框架 `TaskExecutor`/`TaskTestCase.set_image`，确认 `next_frame` 的签章与调用链，避免覆写处把 `TaskDisabledException` 这类异常吞掉。
2. 判定路径接入缓存：`_screen_match` 内对每个 `find_one(feature)` 走缓存包装；`_match_ocr_keywords` 对区域 OCR 走缓存。
3. 标题区 OCR 合并：遍历注册集合同帧内解析 `ocr_box`（字符串特征名解析为框；解析失败退化为全屏 OCR，与现状一致——**合并优化仅作用于可解析且框相同的条目，退化路径不得合并**）；同一 (frame_key, box) 只做一次区域 OCR，各界面的关键词集合并行对同一次结果比对。
4. 不允许改动框架（venv 内 `ok` 包）；所有缓存逻辑落在 `src/`。

## 修改文件

- `src/tasks/NikkeBaseTask.py`。
- 新增测试文件（如 `tests/TestFrameCache.py`，或以 `TestScreenRecovery.py` 新增用例承载——以仓库测试风格为准）。

## 测试与验收

- 语义回归：既有判定用例（`TestScreenRecovery`）全部通过（证明结果逐位一致）。
- 缓存生效用例：mock `find_one`（或框架底层匹配）与 `ocr`：
  - 同一帧内连续调用 `current_screen()` + `is_screen("lobby")` 数次 → 断言每个涉及特征/OCR 区域的实际匹配调用次数 == 1。
  - 调用 `next_frame()` 后再判 → 首次命中调用次数 +1（缓存已失效）。
  - 若可触发 `set_image` 换帧场景（核对测试基类行为），换帧后应 +1。
- 计数 mock 需直接打在判定层真正触匹配的调用点（`find_one`/`self.ocr`），不要 m 掉缓存本身。

## 提交

`perf(screens): cache per-frame match results for screen detection`

正文说明：frame_key 失效规则、标题区 OCR 合并范围、语义不变的安全保证。

## 超范围禁止

不改变任何命中语义；不合并不同 box 的 OCR；不改注册表结构（P1.1 已定）；不引入跨帧的判定去重（那是 P1.4 的 min_frames）。
