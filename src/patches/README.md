# src/patches — ok-script 猴子补丁

本目录集中存放所有针对 venv 内 `ok` 包的猴子补丁。**项目内任何其他代码都不得自行修补 ok 包**；新增补丁一律加到本目录对应主题模块，并在 `__init__.py` 的 `apply_all()` 中注册。

约定：

- 每个模块只负责一个主题，暴露一个 `apply()`；
- `apply_all()` 是唯一入口，在 `src/config.py` 顶部调用（早于 `ok.OK(config)` 构造），因此补丁在 GUI 初始化前生效。

## 各补丁说明

### basic_options.py

包装 `ok.util.GlobalConfig.create_basic_options`：移除与本项目无关的选项、调高 `Trigger Interval` 默认值，并把启动器路径配置行（「启动器路径」）注入「基础设置」顶部；文件选择框默认打开桌面目录由 `_patch_file_selector_initial_directory` 支持（`initial_directory: 'desktop'`）。不要直接改 `ok.util.GlobalConfig`。

### start_controller.py

把 `ok.ui.qt.StartController.StartController` 替换为 `NikkeStartController`，其 `start_device` 流程：管理员检查 → 判断 `nikke.exe` 游戏主进程是否已在运行（若在运行则跳过启动器）→ 否则启动配置的启动器（`nikke_launcher.exe` 或 `.lnk`，自动解析）→ 在可配置区域内 OCR 找到并点击启动按钮 → 等待游戏窗口出现。没有直接启动回退：若未配置启动器且游戏未在运行，提示用户配置启动器或手动启动游戏。

### runtime.py

禁用 OpenVINO 遥测；在 `HwndWindow.visible_monitors` 上注册焦点守卫：一次性任务运行期间游戏窗口失焦即暂停执行器（弹托盘通知），切回前台自动恢复（先经 `reset_scene` 丢弃暂停前的旧帧）。后台 `TriggerTask` 不受影响；不会主动抢占前台。包装 `TaskExecutor.destroy`：进程退出前 join 后台 `DefaultOCRInit` 线程（懒初始化 OCR、导入 openvino），否则初始化未完成时解释器终结会因 import 锁死锁导致进程永不退出（典型触发：跑得快的测试文件）。

### tasks_tab.py

把日常任务卡片置顶到任务 tab 顶部，其下插入 `HorizontalSeparator` 分割线（`ExpandCardLayout` 增加了 `insertWidget(index, widget)` 辅助方法用于放置分割线）；`TaskCard` 把日常卡片展开区过滤到只剩一行标准 `button` 配置行（`DailyTask.DAILY_SETTINGS_BUTTON_KEY`，回调 `DailyTask.open_daily_settings` 切换到日常设置 tab），并给 `done_keys` 非空的任务卡片注入「重置完成状态」按钮。
