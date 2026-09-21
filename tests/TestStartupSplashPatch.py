"""启动画面补丁：主窗口构建期间显示进度、按 tab 推进、结束后关闭。

多为纯 mock 单测：用假启动画面驱动补丁逻辑，不建真实 Qt 窗口、不跑事件循环；
另有一条源码级断言，守住「改 window flags 后必须重挂无边框窗口效果」这个看不见的不变量。
"""
import ast
import os
import unittest
from unittest.mock import MagicMock

import ok as ok_module
from ok.ui.qt.widget.Tab import Tab

from src.patches import startup_splash as splash_patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _FakeSplash:
    """假启动画面：记录 show/set_stage/finish 的调用。"""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if self.fail_on == name:
            raise RuntimeError(f'{name} boom')

    def show_centered(self):
        self._record('show_centered')

    def set_stage(self, text, percent):
        self._record('set_stage', text, percent)

    def finish(self):
        self._record('finish')

    def stages(self):
        return [call[1:] for call in self.calls if call[0] == 'set_stage']


class _FakeTab:
    """假 tab：类名用真实 tab 名以命中文案表。"""


class DailyTab(_FakeTab):
    pass


class TestStartupSplashFlow(unittest.TestCase):
    """StartupSplashFlow：显示/推进/关闭的生命周期。"""

    def _flow(self, splash=None, factory=None):
        splash = splash or _FakeSplash()
        flow = splash_patch.StartupSplashFlow(splash_factory=factory or (lambda: splash))
        return flow, splash

    def test_start_shows_splash_with_start_stage(self):
        """start()：先显示再写第一段文案，进度为主窗口构建的起点。"""
        flow, splash = self._flow()
        flow.start()
        self.assertEqual([('show_centered',), ('set_stage', splash_patch._START_STAGE_TEXT,
                                               splash_patch.START_PERCENT)], splash.calls)

    def test_start_is_idempotent(self):
        """重复 start()：不重复创建启动画面。"""
        created = []

        def factory():
            splash = _FakeSplash()
            created.append(splash)
            return splash

        flow = splash_patch.StartupSplashFlow(splash_factory=factory)
        flow.start()
        flow.start()
        self.assertEqual(1, len(created))

    def test_tabs_advance_progress_with_text(self):
        """每个 tab：按类名换文案，进度单调递增。"""
        flow, splash = self._flow()
        flow.start()
        flow.tab_started(DailyTab())
        flow.tab_started(_FakeTab())  # 文案表里没有的 tab 用默认文案。
        percents = [percent for _, percent in splash.stages()]
        self.assertEqual('正在加载日常设置…', splash.stages()[1][0])
        self.assertEqual('正在加载界面…', splash.stages()[2][0])
        self.assertEqual(sorted(percents), percents)
        self.assertLess(percents[0], percents[-1])

    def test_progress_is_capped(self):
        """tab 很多时进度不超过上限，最后一格留给主窗口 show()。"""
        flow, splash = self._flow()
        flow.start()
        for _ in range(30):
            flow.tab_started(_FakeTab())
        self.assertEqual(splash_patch.MAX_PERCENT, splash.stages()[-1][1])

    def test_tab_started_without_start_is_noop(self):
        """没显示过启动画面（headless/异常）：推进调用被忽略。"""
        flow, splash = self._flow()
        flow.tab_started(DailyTab())
        self.assertEqual([], splash.calls)

    def test_finish_closes_and_resets(self):
        """finish()：关闭启动画面；重复调用不再关。"""
        flow, splash = self._flow()
        flow.start()
        flow.finish()
        flow.finish()
        self.assertEqual(1, len([call for call in splash.calls if call[0] == 'finish']))
        flow.start()  # 关闭后可以重新开始（例如重启界面）。

    def test_factory_failure_is_swallowed(self):
        """创建启动画面失败：只记日志，后续推进调用不抛异常。"""
        def factory():
            raise RuntimeError('boom')

        flow = splash_patch.StartupSplashFlow(splash_factory=factory)
        flow.start()
        flow.tab_started(DailyTab())
        flow.finish()
        self.assertIsNone(flow.splash)

    def test_finish_failure_is_swallowed(self):
        """关闭启动画面失败：只记日志，不影响主窗口。"""
        flow, splash = self._flow(splash=_FakeSplash(fail_on='finish'))
        flow.start()
        flow.finish()
        self.assertIsNone(flow.splash)


class TestStartupSplashPatchWiring(unittest.TestCase):
    """apply() 后的框架接线：do_show_main 显示/关闭启动画面，Tab 构造推进进度。"""

    def setUp(self):
        self.saved_init = Tab.__init__
        self.saved_do_show_main = ok_module.App.do_show_main
        self.saved_hook_flag = splash_patch._tab_hook_installed
        self.saved_flow = splash_patch._flow

    def tearDown(self):
        Tab.__init__ = self.saved_init
        ok_module.App.do_show_main = self.saved_do_show_main
        splash_patch._tab_hook_installed = self.saved_hook_flag
        splash_patch._flow = self.saved_flow

    def test_do_show_main_starts_and_finishes_splash(self):
        """包装后：先显示启动画面再构建主窗口，构建完成后关闭。"""
        order = []
        splash = _FakeSplash()
        splash_patch._flow = splash_patch.StartupSplashFlow(splash_factory=lambda: splash)
        splash_patch._tab_hook_installed = False
        Tab.__init__ = lambda self, *args, **kwargs: order.append('tab')
        ok_module.App.do_show_main = lambda self: order.append('main_window')

        splash_patch.apply()
        ok_module.App.do_show_main(MagicMock())

        self.assertEqual('show_centered', splash.calls[0][0])
        self.assertEqual('finish', splash.calls[-1][0])
        self.assertEqual(['main_window'], order)  # 原来的构建逻辑照常执行，且不被启动画面进度打断。

    def test_do_show_main_finishes_splash_on_error(self):
        """主窗口构建抛异常：启动画面同样关闭，异常继续抛出。"""
        splash = _FakeSplash()
        splash_patch._flow = splash_patch.StartupSplashFlow(splash_factory=lambda: splash)
        splash_patch._tab_hook_installed = False
        Tab.__init__ = lambda self, *args, **kwargs: None

        def boom(self):
            raise RuntimeError('main window boom')

        ok_module.App.do_show_main = boom
        splash_patch.apply()
        with self.assertRaises(RuntimeError):
            ok_module.App.do_show_main(MagicMock())
        self.assertIn('finish', [call[0] for call in splash.calls])

    def test_tab_hook_advances_splash(self):
        """Tab.__init__ 挂钩：构造任何 tab 都推进一次启动画面。"""
        advanced = []
        flow = MagicMock()
        flow.tab_started.side_effect = lambda tab: advanced.append(type(tab).__name__)
        splash_patch._flow = flow
        splash_patch._tab_hook_installed = False
        Tab.__init__ = lambda self, *args, **kwargs: None

        splash_patch._install_tab_hook()
        Tab.__init__(DailyTab())  # 框架 Tab 基类的 __init__ 已被换成挂钩版本。

        self.assertEqual(['DailyTab'], advanced)


class TestStartupSplashWindowFlags(unittest.TestCase):
    """源码级不变量：改过 window flags 之后必须再走一次 updateFrameless()。

    setWindowFlags 会重建原生窗口，而 DWM 的失焦模糊/亚克力、窗口动画、阴影都是按句柄挂的
    （qframelesswindow 的 AcrylicWindow.updateFrameless 里逐句柄设置）；漏掉这次重挂，
    效果就留在被丢弃的旧句柄上。这种行为在单测里跑真实窗口才能发现，所以退一步用源码断言守住。
    """

    SOURCE_PATH = os.path.join(ROOT, 'src', 'ui', 'StartupSplash.py')

    def _init_call_nodes(self):
        with open(self.SOURCE_PATH, encoding='utf-8') as f:
            source = f.read()
        init = next(node for node in ast.walk(ast.parse(source))
                    if isinstance(node, ast.FunctionDef) and node.name == '__init__')
        calls = [node for node in ast.walk(init)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self']
        return source, sorted(calls, key=lambda node: node.lineno)

    def test_update_frameless_called_after_set_window_flags(self):
        _, calls = self._init_call_nodes()
        names = [node.func.attr for node in calls]
        self.assertIn('setWindowFlags', names)
        self.assertIn('updateFrameless', names, '改 window flags 后必须调用 updateFrameless() 重挂 DWM 效果')
        self.assertLess(names.index('setWindowFlags'), names.index('updateFrameless'),
                        'updateFrameless() 必须在 setWindowFlags() 之后调用，否则效果挂在旧句柄上')

    def test_flags_include_stay_on_top(self):
        """置顶在 __init__ 里设好（show_centered 之后不再改 flags）。"""
        source, calls = self._init_call_nodes()
        flags_call = next(node for node in calls if node.func.attr == 'setWindowFlags')
        self.assertIn('WindowStaysOnTopHint', ast.get_source_segment(source, flags_call) or '')

    def test_size_is_applied_after_flags(self):
        """尺寸要在 flags 之后重设：句柄重建会让窗口恢复到基类构造里的 500x500。"""
        _, calls = self._init_call_nodes()
        names = [node.func.attr for node in calls]
        self.assertLess(names.index('setWindowFlags'), names.index('_apply_size'))


if __name__ == '__main__':
    unittest.main()
