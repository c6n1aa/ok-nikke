"""启动控制器补丁：启动前置前后的窗口处理与启动器按钮点击兜底。

纯 mock 单测：不建真实窗口、不启动设备、不碰 Qt 事件循环、不跑真实 OCR，
只验证交互方式闸门、置前调用与各类失败语义、start_device 里的接线顺序，
以及启动按钮点击后的生效判定与重新定位重试。
"""
import unittest
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ok import og

from src.patches import runtime as runtime_patch  # noqa: E402  供 patch.object 替换 interaction_requires_foreground。
from src.patches import start_controller as start_controller_patch
from src.patches.start_controller import NikkeStartController


class _FakeHwndWindow:
    """假游戏窗口：记录 bring_to_front 调用次数并返回预设结果。"""

    def __init__(self, hwnd=0x1234, result=True):
        self.hwnd = hwnd
        self.result = result
        self.calls = 0

    def bring_to_front(self):
        self.calls += 1
        return self.result


def _controller():
    """绕过 __init__（会起 Handler 线程）构造控制器，仅测与构造无关的启动流程方法。"""
    return NikkeStartController.__new__(NikkeStartController)


class _FakeExitEvent:
    """假退出事件：始终未置位，让启动轮询循环按 mock 的返回值推进。"""

    def is_set(self):
        return False


def _launcher_controller():
    """带 exit_event 的控制器，供启动器按钮点击流程使用。"""
    controller = _controller()
    controller.exit_event = _FakeExitEvent()
    return controller


class TestStartControllerForeground(unittest.TestCase):
    """_bring_game_window_to_front：交互方式闸门 + 置前结果语义。"""

    def _bring(self, requires_foreground, hwnd_window):
        with patch.object(runtime_patch, 'interaction_requires_foreground', return_value=requires_foreground), \
                patch.object(og, 'device_manager', SimpleNamespace(hwnd_window=hwnd_window)):
            return _controller()._bring_game_window_to_front()

    def test_brings_to_front_when_interaction_requires_foreground(self):
        """Pynput/PyDirect 这类依赖前台的交互方式：调用 bring_to_front。"""
        hwnd = _FakeHwndWindow()
        self.assertTrue(self._bring(True, hwnd))  # 置前成功。
        self.assertEqual(1, hwnd.calls)  # 必须真正调用一次框架置前。

    def test_skips_when_interaction_supports_background(self):
        """Genshin/PostMessage 这类可后台点击的交互方式：不抢前台。"""
        hwnd = _FakeHwndWindow()
        self.assertFalse(self._bring(False, hwnd))  # 无需置前。
        self.assertEqual(0, hwnd.calls)  # 不调用 bring_to_front，保留后台运行能力。

    def test_missing_hwnd_window_returns_false(self):
        """窗口对象缺失（未挂载）：返回失败且不抛异常。"""
        self.assertFalse(self._bring(True, None))

    def test_missing_hwnd_handle_returns_false(self):
        """句柄为 0：直接返回失败，不调用 bring_to_front。"""
        hwnd = _FakeHwndWindow(hwnd=0)
        self.assertFalse(self._bring(True, hwnd))
        self.assertEqual(0, hwnd.calls)

    def test_bring_to_front_failure_returns_false(self):
        """框架置前返回 False：返回失败。"""
        self.assertFalse(self._bring(True, _FakeHwndWindow(result=False)))

    def test_exception_is_swallowed(self):
        """置前抛异常：吞掉并返回失败，不中断启动流程。"""
        class _Boom:
            hwnd = 0x1

            def bring_to_front(self):
                raise RuntimeError('boom')

        self.assertFalse(self._bring(True, _Boom()))

    def test_start_device_brings_to_front_after_resize(self):
        """start_device 在窗口尺寸调整之后、完成信号之前置前，返回值不受影响。"""
        order = []  # 记录两个步骤的实际调用顺序。
        device = {'connected': True, 'device': 'windows'}  # 设备已连接，跳过启动器分支。
        controller = _controller()
        communicate = MagicMock()
        with patch.object(og, 'device_manager',
                          SimpleNamespace(get_preferred_device=lambda: device)), \
                patch.object(NikkeStartController, '_wait_until_device_ready', lambda self, **kwargs: True), \
                patch.object(NikkeStartController, '_ensure_min_game_window_size',
                             lambda self: order.append('resize')), \
                patch.object(NikkeStartController, '_bring_game_window_to_front',
                             lambda self: order.append('front')), \
                patch.object(start_controller_patch, 'communicate', communicate):
            self.assertTrue(controller.start_device(initial_refresh_done=True))  # 启动成功。
        self.assertEqual(['resize', 'front'], order)  # 先调尺寸再置前。
        communicate.starting_emulator.emit.assert_called_with(True, None, 0)  # 收尾信号不变。


class TestStartControllerLauncherClick(unittest.TestCase):
    """_click_launcher_button：点击启动按钮未生效时重新 OCR 定位再点的兜底流程。"""

    @contextmanager
    def _click_env(self, centers, effective, clicked, click_result=True, search_timeout=None):
        """拦截真实窗口/OCR/点击，按给定序列返回识别坐标与生效判定。"""
        communicate = MagicMock()
        centers_iter = iter(centers)
        effective_iter = iter(effective)
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(NikkeStartController, '_wait_until_launcher_window', lambda self, exe: 0x1111))
            stack.enter_context(
                patch.object(NikkeStartController, '_wait_until_launcher_stable', lambda self, hwnd: True))
            stack.enter_context(patch.object(NikkeStartController, '_bring_window_forward', lambda self, hwnd: None))
            stack.enter_context(patch.object(NikkeStartController, '_game_window_found', lambda self: False))
            stack.enter_context(patch.object(NikkeStartController, '_capture_and_find_button',
                                             lambda self, *args: next(centers_iter)))
            stack.enter_context(patch.object(NikkeStartController, '_click_screen_point',
                                             lambda self, hwnd, x, y: clicked.append((x, y)) or click_result))
            stack.enter_context(patch.object(NikkeStartController, '_launcher_click_effective',
                                             lambda self, *args: next(effective_iter)))
            stack.enter_context(patch.object(start_controller_patch.win32gui, 'IsWindow', lambda hwnd: True))
            stack.enter_context(patch.object(start_controller_patch, 'communicate', communicate))
            stack.enter_context(patch.object(start_controller_patch, 'clean_up_bitblt', MagicMock()))
            if search_timeout is not None:
                stack.enter_context(
                    patch.object(NikkeStartController, 'LAUNCHER_BUTTON_SEARCH_TIMEOUT', search_timeout))
            yield communicate

    def test_single_click_when_effective(self):
        """点击生效：只点一次并返回成功，不发任何提示。"""
        clicked = []
        with self._click_env(centers=[(100, 200)], effective=[True], clicked=clicked) as communicate:
            self.assertTrue(_launcher_controller()._click_launcher_button('nikke_launcher.exe'))
        self.assertEqual([(100, 200)], clicked)  # 只点一次。
        communicate.starting_emulator.emit.assert_not_called()

    def test_relocates_and_clicks_again_when_click_missed(self):
        """首次点击未生效：按新识别到的坐标再点一次，不中断启动流程。"""
        clicked = []
        with self._click_env(centers=[(100, 200), (140, 205)], effective=[False, True],
                             clicked=clicked) as communicate:
            self.assertTrue(_launcher_controller()._click_launcher_button('nikke_launcher.exe'))
        self.assertEqual([(100, 200), (140, 205)], clicked)  # 第二次用的是重新识别到的坐标。
        communicate.starting_emulator.emit.assert_not_called()

    def test_returns_false_when_simulated_click_fails(self):
        """模拟点击本身抛错：不当作点击成功，直接返回失败。"""
        clicked = []
        with self._click_env(centers=[(100, 200)], effective=[], clicked=clicked, click_result=False):
            self.assertFalse(_launcher_controller()._click_launcher_button('nikke_launcher.exe'))
        self.assertEqual([(100, 200)], clicked)

    def test_stops_after_max_attempts_and_reports_failure(self):
        """连续未生效：点击次数封顶后只等游戏窗口，超时报"已多次点击"而非"按钮未找到"。"""
        max_attempts = NikkeStartController.LAUNCHER_CLICK_MAX_ATTEMPTS
        clicked = []
        with self._click_env(centers=[(100 + i, 200) for i in range(max_attempts)],
                             effective=[False] * max_attempts, clicked=clicked,
                             search_timeout=0) as communicate:
            self.assertFalse(_launcher_controller()._click_launcher_button('nikke_launcher.exe'))
        self.assertEqual(max_attempts, len(clicked))  # 不超过次数上限。
        communicate.starting_emulator.emit.assert_any_call(True, '已多次点击启动按钮但游戏未启动，请手动启动游戏!', 0)

    def test_reports_missing_button_without_clicking(self):
        """一次都没识别到启动按钮：沿用手册提示，不产生点击。"""
        clicked = []
        with self._click_env(centers=[None], effective=[], clicked=clicked, search_timeout=0) as communicate:
            self.assertFalse(_launcher_controller()._click_launcher_button('nikke_launcher.exe'))
        self.assertEqual([], clicked)
        communicate.starting_emulator.emit.assert_any_call(True, '启动按钮未找到，请检查是否已经登录以及网络环境', 0)


class TestStartControllerLauncherClickEffective(unittest.TestCase):
    """_launcher_click_effective：点击启动按钮后的生效判定。"""

    def _effective(self, game_window=False, game_process=False, window_alive=True, center=(10, 20),
                   verify_timeout=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(NikkeStartController, '_game_window_found',
                                             lambda self: game_window))
            stack.enter_context(patch.object(NikkeStartController, '_game_process_running',
                                             lambda self: game_process))
            stack.enter_context(patch.object(NikkeStartController, '_capture_and_find_button',
                                             lambda self, *args: center))
            stack.enter_context(patch.object(start_controller_patch.win32gui, 'IsWindow',
                                             lambda hwnd: window_alive))
            if verify_timeout is not None:
                stack.enter_context(
                    patch.object(NikkeStartController, 'LAUNCHER_CLICK_VERIFY_TIMEOUT', verify_timeout))
            return _launcher_controller()._launcher_click_effective(0x1111, None, '启动', (0.05, 0.83, 0.30, 0.93))

    def test_game_window_appearing_counts_as_effective(self):
        """游戏窗口出现：判定生效。"""
        self.assertTrue(self._effective(game_window=True))

    def test_game_process_starting_counts_as_effective(self):
        """游戏进程已拉起（窗口还没出来）：判定生效，避免重复点击。"""
        self.assertTrue(self._effective(game_process=True))

    def test_launcher_window_closed_counts_as_effective(self):
        """启动器窗口已退出：判定生效，后续由外层等游戏窗口。"""
        self.assertTrue(self._effective(window_alive=False))

    def test_missing_button_counts_as_effective(self):
        """启动按钮不再被识别（文字变化/界面切换）：判定生效。"""
        self.assertTrue(self._effective(center=None))

    def test_button_still_there_after_timeout_counts_as_not_effective(self):
        """观察超时后启动按钮仍在：判定这一轮点击落空，交由外层重新定位。"""
        self.assertFalse(self._effective(center=(10, 20), verify_timeout=0))


if __name__ == '__main__':
    unittest.main()
