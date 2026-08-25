# P0.1 修复 dismiss_all_popups 的 clear_condition 短路

> 上游依据：`docs/screen-recovery-evolution-plan.md` §4-A、§5.1、§6 Phase 0.1
> 工作分支：`feature/screen-recovery-evolution`；依赖：无。
> 预计改动面：`src/tasks/NikkeBaseTask.py` 一处循环 + `tests/TestScreenRecovery.py`。

## 目标

修复失败恢复路径里的确定性缺陷：遮罩弹窗未关闭时恢复协议谎报成功。

## 背景与现状锚点

- `_recover_to_lobby`（`src/tasks/NikkeBaseTask.py:659-685`）调用 `dismiss_all_popups(clear_condition=lambda: self.is_screen("lobby"))`（约 669 行）。
- `dismiss_all_popups`（510-561）的循环**每一轮先查 `clear_condition`、再尝试关弹窗**（538-540 行顺序）。
- TM_CCOEFF_NORMED 对半透明压暗遮罩基本免疫，大厅特征在公告/遮罩弹窗下可能仍命中 → 第一轮 `clear_condition` 即为真 → 直接 `return True`，弹窗一个未关；随后 `is_screen("lobby")` 为真，恢复「成功」，重试流程的第一次点击落在弹窗上。

## 实施步骤

1. 调整 `dismiss_all_popups` 循环为「关弹窗优先于条件判定」：每轮先 `_try_close_one_popup`；若关到弹窗 → `next_frame()` 刷新 → `continue`；**仅当本轮未关到任何弹窗时**才检查 `clear_condition()`。
2. 保持其余语义不变：`clear_condition is None` 且未关到弹窗时的 `wait_for_popup` 分支、`closed_any` 语义、超时返回 False 的行为、最大轮数 `max_passes` 均不动。
3. 同步更新方法 docstring 的行为描述（条件生效时机变化）。
4. `TaskDisabledException` 必须继续原样向上传播，不要吞。

## 修改文件

- `src/tasks/NikkeBaseTask.py`：仅 `dismiss_all_popups` 内部循环顺序与 docstring；不改签名。
- `tests/TestScreenRecovery.py`：新增用例 + 视现状更新绑定旧顺序的用例。

## 测试与验收

新增的验收用例（核心）：
- mock 使 `is_screen("lobby")` 恒为 True；`_try_close_one_popup` 用 `side_effect=[True, False]`（第一轮还有弹窗，第二轮没了）→ 断言 `_try_close_one_popup` 至少被调用一次之后才返回，且返回 True 时弹窗已被处理（验证「条件满足但弹窗未关时不得提前返回」）。
- `require_click`/`wait_for_popup` 等既有分支行为用例保持通过。

执行（在仓库根目录，逐文件独立进程）：

```
.\venv\Scripts\python.exe -m unittest tests.TestScreenRecovery
```

验收标准：该文件全部用例通过；无其他源文件改动。

## 提交

`fix(recovery): close popups before honoring clear_condition in dismiss_all_popups`

正文说明：缺陷现象（遮罩下 lobby 特征命中 → 恢复谎报成功）、修复方式（清弹窗优先于条件判定）、影响范围（仅恢复路径判定时机）。

## 超范围禁止

不改 `_recover_to_lobby` 的其他部分；不调整 `close_overlay`；不引入新配置项。
