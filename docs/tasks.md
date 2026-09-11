# 任务开发

任务类位于 `src/tasks/`：

- 一次性任务继承 `NikkeBaseTask`。
- 后台触发任务继承 `NikkeBaseTask` 与框架的 `TriggerTask`（`class MyTriggerTask(NikkeBaseTask, TriggerTask)`）。

不要直接继承框架的 `BaseTask`/`TriggerTask`——`NikkeBaseTask` 封装了界面识别、导航、失败恢复、完成状态与模板缩放。

起步模板：

- 一次性任务：`src/tasks/MyOneTimeTask.py`
- 后台触发任务：`src/tasks/MyTriggerTask.py`
- 基类与通用能力：`src/tasks/NikkeBaseTask.py`（实现按职责拆在 `src/tasks/base/` 下的 mixin，基类只做组合）

## 写一个任务

任务类通过属性声明 UI，不手写控件：

| 属性 | 说明 |
| --- | --- |
| `name` / `description` | 任务名与说明，直接写简体中文（本项目不做任务字符串 i18n） |
| `default_config` | 配置项默认值 |
| `config_type` | 配置项控件类型（下拉、布尔、数值、文本、多选等） |
| `done_keys` | 完成状态键与周期，如 `{"harvest": "day"}`；纯编排/调试任务不定义 |

自动化逻辑写在 `run()` 中。新增 `config_type` 需要同步 ok-script 框架 `ok/ui/qt/tasks/ConfigItemFactory.py` 的工厂分支。

## 任务开发约定

写任务前先读[界面识别与失败恢复](screen-and-recovery.md)，核心约定：

- **界面统一注册**在 `src/screens.py` 的 `SCREENS`，不在任务 `__init__` 里 `register_screen`。
- **导航**用 `transition()`（点入口 → 确认进入），**闸门**用 `ensure_screen()`（子流程开头就位）。
- **失败恢复**用 `try_step` 包「从大厅出发的入口方法」**一层**，内部步骤不逐个包，不手写重试或回大厅逻辑。
- **模板匹配**：coco 特征用 `find_feature`/`find_one`（按分辨率自动缩放）；`assets/template/` 小图必须经 `find_scaled_template()` 缩放后匹配，禁止未缩放模板直接匹配。
- **等待**优先挂在框架 API 的 `after_sleep`/`time_out` 参数上，不手写 `self.sleep`；战斗结束用 `wait_battle_finish`，不用 `wait_feature`/`wait_ocr` 忙轮询。
- **弹窗**由基类的 `dismiss_all_popups` 统一清理，新增弹窗只挂 `_try_close_one_popup`。

## 注册任务

在 `src/config.py` 中登记模块路径与类名：

```python
'onetime_tasks': [
    ['src.tasks.HarvestTask', 'HarvestTask'],
],
```

后台周期任务登记到 `trigger_tasks`（当前为空）。顺序即 GUI 中的展示顺序。

## 调试

```powershell
.\.venv\Scripts\python.exe main_debug.py
```

Debug 模式提供截图、模板匹配结果可视化与标注工具。调试截图统一截取 2560×1440 窗口，与素材基准一致。

## 测试

测试放在 `tests/` 下，命名 `TestXxxTask.py` 对应 `src/tasks/XxxTask.py`，继承 `ok.test.TaskTestCase` 并设置 `task_class`，用 `self.set_image()` 固定输入帧。范例见 `tests/TestShopTask.py`、`tests/TestArkTask.py`（覆盖成功/跳过/失败/已完成跳过分支）。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestMain
.\run_tests.ps1   # 全量，逐文件独立进程
```

- 不碰真实环境：`wait_for_lobby`、`dismiss_all_popups` 等必经方法用 `patch.object` 拦截并断言参数。
- `while True` 类流程用 `side_effect` 有限序列驱动，避免死循环。

## 用 AI 生成任务

仓库内置 Agent Skills：`$ok-script-tasks`（创建/修改/注册任务类）、`$ok-script-codegen`（根据需求或截图生成 `run()` 逻辑）、`$ok-script-i18n`（同步翻译）。

推荐流程：按[任务简报模板](task_brief_template.md)写好简报（界面、流程树、失败处理），再交给 Codegen 技能生成代码，最后补测试。
