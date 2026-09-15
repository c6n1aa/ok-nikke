"""启动控制器置前补丁：按交互方式决定启动任务前是否把游戏窗口切到前台。

纯 mock 单测：不建真实窗口、不启动设备、不碰 Qt 事件循环，只验证交互方式闸门、
置前调用与各类失败语义，以及 start_device 里的接线顺序。
"""
import unittest
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


if __name__ == '__main__':
    unittest.main()
