# P0.2 判定特征几何约束写入 screen-and-recovery.md（中英双语）

> 上游依据：`docs/screen-recovery-evolution-plan.md` §4、§5.2、§6 Phase 0.2
> 工作分支：`feature/screen-recovery-evolution`；依赖：无。
> 预计改动面：`docs/screen-and-recovery.md` 与 `docs/en/screen-and-recovery.md`（本文件已入 mkdocs nav，中英必须同步）。

## 目标

把「注册界面判据特征的几何选取约束」固化为开发约定，避免后续注册的界面把全部判据放在模态弹窗覆盖区。

## 背景与数据

判据特征 bbox（2560×1440，dump 自 `assets/coco_annotations.json`）：`tribe_tower_mark` (1214,109) 顶栏（好判据）；`ark_tribe_tower` (1350,319)、`ark_simulation_room` (928,571)、`simulation_mark` (1172,680) 均在典型模态覆盖区；lobby 判据在底栏/右下，多数模态不覆盖。模态覆盖区经验值：x∈[400,2160]、y∈[200,1150]（居中弹窗+全屏压暗遮罩），**待实机以好友/邮箱弹窗校准**——文档中原样写明这是经验值。

## 实施步骤

1. 在 `docs/screen-and-recovery.md` 的「约束（Agent 开发必须遵守）」一节追加条款：
   - 新注册界面的判据特征优先选择顶栏/底栏/边缘元素；避免全部判据特征的 bbox 落入典型模态覆盖区（x∈[400,2160]、y∈[200,1150]，2560×1440 基准，经验值待实机校准）。
   - 约束适用对象：(a) 今后新注册的界面；(b) 将参与全局分类或恢复期判定的界面。流程内部、导航后立即执行的 `assert_screen`（断言点前已由 `_nav_*` 确保无弹窗）不受此约束。
   - Backlog 登记：`simulation_mark`（1172,680，正中心）当前唯一使用点是 `ArkTask.py:119`（`_nav_to_ark` 导航后立即断言），不在适用范围内，现状无问题；仅当 simulation_room 日后参与恢复期/全局分类时才更换判据。
2. 在「方案 A：界面识别」的 `register_screen` 小节末尾加一句指引，指向上述约束条款。
3. `docs/en/screen-and-recovery.md` 同步英文镜像（逐条对应，条数一致）。

## 修改文件

- `docs/screen-and-recovery.md`、`docs/en/screen-and-recovery.md`。

## 测试与验收

- 执行 `.\venv\Scripts\python.exe -m mkdocs build --strict`，退出码必须为 0。
- 人工核对：中英两版新增条款逐条对应，`-` 列表项数量一致；行内代码/路径引用与仓库实际一致（`ArkTask.py:119`、`tribe_tower_mark` 等）。
- 无需运行功能测试（纯文档改动）。

## 提交

`docs(screen-recovery): add geometry constraint for screen criterion features`

正文说明：动机（模态覆盖区与判据位置的关系）、适用对象限定、simulation_mark backlog 登记。

## 超范围禁止

不改 `docs/screen-recovery-evolution-plan.md`；不动任何 `.py` 与 coco 标注。
