# P1.4 spec schema 扩展：absent / priority / min_frames

> 上游依据：`docs/screen-recovery-evolution-plan.md` §5.4、§6 Phase 1.4
> 工作分支：`feature/screen-recovery-evolution`；依赖：P1.1；**与 P1.2 串行**（同改判定层）。
> 预计改动面：`src/screens.py`（spec 结构）+ `src/tasks/NikkeBaseTask.py`（判定逻辑）+ 测试。

## 目标

为界面 spec 增加三个生效字段，消除判定层三处隐性缺陷（注册顺序依赖、特征子集重叠误判、单帧抖动）。**默认值下行为与现状完全一致**（字段缺省即退化为现状语义）。

## spec 字段定义

在现有 `"features" / "keywords" / "ocr_box"` 基础上扩展（新增字段缺省 = 现状行为）：

- `absent`：`list[str]` 特征名，默认 `[]`。任一 `absent` 特征命中 → 该界面判定失败（用于消歧特征子集重叠的相邻界面）。
- `priority`：`int`，默认 `0`。仅影响 `current_screen()` 返回顺序：按 `priority` 降序、同优先级按注册顺序。`is_screen`/`wait_screen`/`assert_screen` 不受影响。
- `min_frames`：`int`，默认 `1`。仅影响 `wait_screen`/`assert_screen` 的轮询判定：需连续 `min_frames` 帧命中才算进入该界面；`is_screen` 恒为单帧语义（文档写明）。

## 实施步骤

1. `src/screens.py`：更新模块 docstring 描述新字段及缺省语义；`SCREENS` 现有 9 个条目**本次不填充**新字段（保持现状；字段仅供后续界面与需要时使用，避免本期改动行为）。
2. `_screen_match`：在 features 命中后、判定返回 True 前执行 `absent` 检查（任一命中 → False）。`absent` 中的特征走与 `features` 相同的 `find_one` 路径（并与 P1.2 缓存兼容；若 P1.2 尚未合入则直接 `find_one`）。
3. `current_screen`：按 `priority` 降序稳定排序后遍历（同优先级保持插入序→用带序号的排序保证稳定）。
4. `wait_screen`/`assert_screen`：在轮询 condition 内实现 `min_frames` 连续命中计数（实例级状态，仅跨轮次递增，未命中清零）。注意 `wait_until` 每次轮询取的帧不同——计数以「轮询条件返回 True 的次数」为准，天然逐帧。
5. `is_screen`：保持单帧语义不变；docstring 写明与 `min_frames` 的关系。
6. 同步更新 `docs/screen-and-recovery.md` 与 `docs/en/screen-and-recovery.md` 的「界面识别」一节（新增字段语义，中英对齐）。

## 修改文件

- `src/screens.py`、`src/tasks/NikkeBaseTask.py`。
- `tests/TestScreenRecovery.py` 新增用例；`docs/screen-and-recovery.md`、`docs/en/screen-and-recovery.md`。

## 测试与验收

- `absent`：临时注册一个 `absent=["ark"]` 的界面，mock `find_one("ark")` 命中 → 该界面判定为 False；未命中 → 判定跳过单调路径。
- `priority`：注册两个 priority 不同的界面（mock 使其同时命中）→ `current_screen()` 返回高优先级的；priority 相等时返回注册序前列者。
- `min_frames=2`：`wait_screen` 用 `side_effect=[False, True, True, True]` 驱动轮询条件 → 断言不因单次 True 返回，需连续两帧 True 后才返回 True。
- 缺省回归：现有 9 个界面不加新字段时，既有判定用例（TestScreenRecovery）全部通过，证明默认行为不变。
- docs 改动后执行 `.\.venv\Scripts\python.exe -m mkdocs build --strict`，退出码 0。

## 提交

`feat(screens): add absent, priority, min_frames to screen spec schema`

正文说明：三字段语义、缺省退化保证、与 is_screen 单帧语义的区别。

## 超范围禁止

本期不实现 `when_unobscured`（遮罩下不算命中）；不改变 features/ keywords 的既有「与/或」语义；不引入 exceed 现有协议的负索引/复杂条件。
