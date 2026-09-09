# NikkeBaseTask 的能力拆分包：各职责以 mixin 形式拆到这里，再由
# src/tasks/NikkeBaseTask.py 组合成一个基类。子任务继续 `from src.tasks.NikkeBaseTask import NikkeBaseTask`，
# 不要直接 import 本包下的 mixin。