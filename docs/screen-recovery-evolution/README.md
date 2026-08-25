# 界面识别与失败恢复改造：执行 Prompt 索引

> 上游设计文档：`docs/screen-recovery-evolution-plan.md`（方案原理、局限证据、推荐判定）
> 工作分支：`feature/screen-recovery-evolution`（基于 `dev`）
> 用法：目录内每个 `phase*.md` 是一份完整、自包含的 Coding Agent 执行 Prompt，整文件内容直接交给执行 agent；无需再附加上下文。

## 执行顺序与依赖

| 顺序 | 文件 | 阶段 | 依赖 | 并行说明 |
|---|---|---|---|---|
| 1 | `phase0-1-dismiss-clear-condition.md` | 0 | 无 | 可与任何项并行 |
| 2 | `phase0-2-feature-geometry-convention.md` | 0 | 无 | 可与任何项并行（纯文档，含英文镜像） |
| 3 | `phase1-1-centralize-screen-registry.md` | 1 | 无 | 与 1、2 并行 |
| 4 | `phase1-2-frame-cache-and-ocr-merge.md` | 1 | 依赖 3 | 与 5 并行 |
| 5 | `phase1-3-coco-registry-integrity-test.md` | 1 | 依赖 3 | 与 4 并行 |
| 6 | `phase1-4-screen-spec-schema.md` | 1 | 依赖 3 | 与 4 同改 `NikkeBaseTask.py` 判定层，**两者务必串行**（先后均可） |
| 7 | `phase2-1-transition-primitive.md` | 2 | 依赖 3 | 与 8 并行 |
| 8 | `phase2-2-interrupt-watchdog.md` | 2 | 依赖 3 | 与 7 并行 |

方案 3（back 回退链）与方案 4（界面图状态机）本期不实施，触发条件见上游文档 §5.7/§5.8。

## 完成一个 Prompt 后的检查点

1. 按 Prompt 内「测试与验收」逐文件独立进程运行受影响测试（ok 单例在同一进程内不可重建，严禁一条命令连跑多个测试文件）。
2. 每个 Phase 收尾时跑全部测试文件（`run_tests.ps1` 或逐条 `unittest`）。
3. 改动到 `docs/**` 或 `mkdocs.yml` 时运行 `./.venv/Scripts/python.exe -m mkdocs build --strict`（退出码须为 0）。

## Backlog（已识别但本期不做）

- `simulation_mark`（1172,680，正中心）条件迁移：仅当 simulation_room 参与恢复期/全局分类时更换判据（上游文档 §5.2）。
- 模态覆盖区经验值（x∈[400,2160]、y∈[200,1150]）待实机用好友/邮箱弹窗校准后回填 `docs/screen-and-recovery.md`。
- `when_unobscured`（遮罩下不算命中）：字段语义已从 phase1-4 移除，待判定层稳定后单独实施。
- 方案 3 / 方案 4：见上游文档触发条件。
