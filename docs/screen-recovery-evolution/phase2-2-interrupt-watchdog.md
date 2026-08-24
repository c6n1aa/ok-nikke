# P2.2 长等待中断哨兵

> 上游依据：`docs/screen-recovery-evolution-plan.md` §5.6、§6 Phase 2.2、§4-C
> 工作分支：`feature/screen-recovery-evolution`；依赖：P1.1（`src/screens.py` 提供中断界面组容器）。
> 预计改动面：`src/screens.py` + `src/tasks/NikkeBaseTask.py`（异常 + 哨兵挂点）+ 长等待点 + 测试。

## 目标

让 `wait_battle_finish`（240s）等长轮询在遭遇断线/维护/登录过期等致命弹窗时快速失败，而不是空转等满超时。**机制先行：中断特征清单本期可为空/占位，实机遇到对应弹窗标注进 coco 后再激活；不得影响无中断状态下的既有行为。**

## 实施步骤

1. `src/screens.py` 增加中断界面组声明（独立常量，如 `INTERRUPTS`）：`{"screens": [...], "features": [...]}`。本期允许 `features=[]`（空清单 = 哨兵未激活），docstring 说明「实机遇到断线/维护/登录过期弹窗后，将对应 coco 特征名加入此清单」。
2. 新增专用异常 `InterruptedByDialogException(WaitFailedException)`（放 `src/tasks/NikkeBaseTask.py` 或独立模块，以最小改动与导入环为准）；它继承 `WaitFailedException`，故 `try_step`（687-718）现有捕获路径自动兼容，无需改动 `try_step`。
3. `wait_battle_finish`（`NikkeBaseTask.py:259-303`）的每轮轮询追加中断检测：在 hit `battle_finish_*` 前先查中断特征（复用 P1.2 缓存路径；未合入则直接 `find_one`）；命中 → `save_failure_screenshot("interrupt")` 并抛 `InterruptedByDialogException`。检测复用既有轮询节奏，不新增抓帧频率。
4. 长等待点（如 `RaidTask` 协同匹配约 60s 的等待）按同样模式挂点；`wait_click_feature` 的 60s 超时等待可暂不挂（本期范围以 `wait_battle_finish` 与显式长等待循环为准）。

## 修改文件

- `src/screens.py`、`src/tasks/NikkeBaseTask.py`、`RaidTask.py`（若其匹配等待需要挂点）。
- 测试：`tests/TestBattleWait.py` 新增/更新；必要时 `tests/TestScreenRecovery.py`。

## 测试与验收

- 新增用例：把中断特征 mock 成在第 N 轮命中（`side_effect` 有限序列，`find_one` 前 N-1 次返回 None 命中战斗/中断目标，第 N 次返回中断特征 Box）→ 断言 `wait_battle_finish` 抛出 `InterruptedByDialogException` 且耗时显著小于正常超时。
- 回归：无中断特征命中时 `wait_battle_finish` 行为与现状完全一致（既有用例保持通过）。
- `try_step` 兼容用例：中断异常被外层 `try_step` 按 `WaitFailedException` 捕获、走恢复重试（mock 路径）。

## 提交

`feat(recovery): fail fast on interrupt dialogs during long waits`

正文说明：`InterruptedByDialogException` 继承关系、中断清单空值的激活策略、轮询节流不变。

## 超范围禁止

不改造 `try_step`/`_recover_to_lobby` 的恢复手段（那是方案 3）；本期不把中断清单填充非实机验证过的特征；不改 `wait_battle_finish` 的既有返回协议（`(result, box)`）。
