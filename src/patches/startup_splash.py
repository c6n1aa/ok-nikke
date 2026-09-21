# -*- coding: utf-8 -*-
"""启动画面补丁：把「正在启动」的进度反馈接到框架启动链路上。

`ok.OK(config)` → `App.do_show_main` → `MainWindow` 构造这一段没有事件循环，实测约 4 秒
（开发机 5.5 秒才出窗口，其中 QApplication 建好之后全在此段），期间屏幕没有任何反馈。
两处补丁配合：

1. 包装 `App.do_show_main`：进 MainWindow 构造前显示启动画面，`show()` 完成后关闭，
   构造抛异常时同样关闭（错误窗口才不会被启动画面盖住）。
2. 临时包装 `Tab.__init__`：每个 tab 开始构造时推进进度条并换文案（`Tab` 是所有 tab 的
   公共基类，`MainWindow` 逐个构造 tab，正好是启动期最耗时的几个阶段）。

headless（无 Qt UI）路径不经过 `do_show_main`，不会显示启动画面。
"""

import time

from ok import Logger

logger = Logger.get_logger(__name__)

START_PERCENT = 20  # 主窗口开始构建
PERCENT_PER_TAB = 12  # 每开始一个 tab 推进的百分比
MAX_PERCENT = 95  # 上限：最后一格留给主窗口 show()

# tab 类名 → 界面文案。取不到的类用默认文案，新增 tab 不必改这里。
_TAB_STAGE_TEXTS = {
    'StartTab': '正在加载截图方式界面…',
    'TriggerTaskTab': '正在加载触发器…',
    'OneTimeTaskTab': '正在加载任务列表…',
    'ScheduleTaskTab': '正在加载定时任务…',
    'DailyTab': '正在加载日常设置…',
    'SettingTab': '正在加载设置…',
    'GlobalConfigTab': '正在加载设置…',
    'AboutTab': '正在加载关于页面…',
}
_DEFAULT_STAGE_TEXT = '正在加载界面…'
_START_STAGE_TEXT = '正在启动，请稍候…'


class StartupSplashFlow:
    """一次启动画面的生命周期：start() → tab_started()（多次）→ finish()。"""

    def __init__(self, splash_factory=None):
        self.splash_factory = splash_factory or _create_splash
        self.splash = None
        self.tabs_started = 0
        self.started_at = None

    def start(self):
        if self.splash is not None:
            return
        try:
            splash = self.splash_factory()
        except Exception as e:  # 启动画面失败不能拖住启动流程
            logger.error(f'create startup splash error', e)
            return
        self.splash = splash
        self.started_at = time.monotonic()
        splash.show_centered()
        splash.set_stage(_START_STAGE_TEXT, START_PERCENT)

    def tab_started(self, tab):
        if self.splash is None:
            return
        self.tabs_started += 1
        text = _TAB_STAGE_TEXTS.get(type(tab).__name__, _DEFAULT_STAGE_TEXT)
        self.splash.set_stage(text, min(MAX_PERCENT, START_PERCENT + PERCENT_PER_TAB * self.tabs_started))

    def finish(self):
        splash, self.splash = self.splash, None
        self.tabs_started = 0
        if splash is None:
            return
        elapsed = time.monotonic() - self.started_at if self.started_at else 0
        self.started_at = None
        try:
            splash.finish()
        except Exception as e:
            logger.error(f'finish startup splash error', e)
        logger.info(f'startup splash closed after {elapsed:.1f}s')


def _create_splash():
    from ok import og
    from src.ui.StartupSplash import StartupSplash

    return StartupSplash(og.app.title, og.app.icon)


_flow = StartupSplashFlow()
_tab_hook_installed = False


def _install_tab_hook():
    """挂钩 Tab 基类的 __init__，tab 开始构造时推进启动画面。"""
    global _tab_hook_installed
    if _tab_hook_installed:
        return
    from ok.ui.qt.widget.Tab import Tab

    original_init = Tab.__init__

    def _init(self, *args, **kwargs):
        _flow.tab_started(self)
        original_init(self, *args, **kwargs)

    Tab.__init__ = _init
    _tab_hook_installed = True
    logger.info('patched Tab.__init__ to advance the startup splash')


def _patch_do_show_main():
    import ok as ok_module

    original = ok_module.App.do_show_main

    def _do_show_main(self):
        _install_tab_hook()
        _flow.start()
        try:
            original(self)
        finally:
            _flow.finish()

    ok_module.App.do_show_main = _do_show_main
    logger.info('patched App.do_show_main to show a startup splash while the main window is built')


def apply():
    # 启动画面只存在于 Qt 启动路径，headless 不受影响
    _patch_do_show_main()
