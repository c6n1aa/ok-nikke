# EventTask 的子流程拆分包：常量在 `_const`，各子流程 mixin 后续按职责拆到这里，
# 再由 src/tasks/EventTask.py 组合成一个任务类。外部继续 `from src.tasks.EventTask import EventTask`，
# 不要直接 import 本包下的 mixin。
