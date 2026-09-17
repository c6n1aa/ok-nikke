# -*- coding: utf-8 -*-
"""src/win_input.py 合成触控指针输入后端的纯逻辑单元测试。

不触碰真实环境（不创建合成设备、不注入、不抓窗口），只测坐标转换、锚点位置选择、
触摸序列状态机与键盘 no-op。真实注入验证见 dev_tools/anchored_touch.py。
"""

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import src.win_input as win_input
from src.win_input import SyntheticTouch, _Command


def _metrics(side_effect):
    """按 GetSystemMetrics 索引返回固定值的 helper。"""
    return mock.patch.object(win_input._user32, 'GetSystemMetrics', side_effect=side_effect)


class TestCoordinateConversion(unittest.TestCase):

    def test_to_inject_coord_subtracts_virtual_origin(self):
        metrics = {win_input.SM_XVIRTUALSCREEN: -1440, win_input.SM_YVIRTUALSCREEN: -480}
        with _metrics(lambda i: metrics.get(i, 0)):
            self.assertEqual(win_input._to_inject_coord(100, 200), (1540, 680))

    def test_to_inject_coord_single_monitor_unchanged(self):
        with _metrics(lambda i: 0):
            self.assertEqual(win_input._to_inject_coord(100, 200), (100, 200))

    def test_to_screen_inject_uses_abs_cords(self):
        at = SyntheticTouch(capture=mock.Mock(), hwnd_window=mock.Mock())
        at.capture.get_abs_cords.return_value = (300, 400)
        metrics = {win_input.SM_XVIRTUALSCREEN: -1440, win_input.SM_YVIRTUALSCREEN: -480}
        with _metrics(lambda i: metrics.get(i, 0)):
            self.assertEqual(at._to_screen_inject(10, 20), (1740, 880))


class TestKeyboardNoop(unittest.TestCase):

    def setUp(self):
        self.at = SyntheticTouch(capture=mock.Mock(), hwnd_window=mock.Mock())

    def test_keyboard_methods_do_not_raise(self):
        # 键盘未实现，这些方法只记录告警，不应抛异常或触发任何输入
        self.at.send_key('esc')
        self.at.send_key_down('esc')
        self.at.send_key_up('esc')
        self.at.input_text('abc')
        self.at.back()

    def test_mouse_down_without_position_is_ignored(self):
        # 触控无「当前位置」概念，缺坐标时直接拒绝，不注入 (0,0)
        self.assertFalse(self.at.mouse_down(-1, -1))
        self.assertFalse(self.at._holding)
        self.assertFalse(self.at.mouse_down(10, -1))


class TestClickJitter(unittest.TestCase):

    def test_click_applies_jitter_to_coordinates(self):
        at = SyntheticTouch(capture=mock.Mock(), hwnd_window=mock.Mock())
        at.mouse_down = mock.Mock(return_value=True)
        at.mouse_up = mock.Mock()
        with mock.patch('src.win_input.time.sleep'):
            with mock.patch('src.win_input.random.randint', return_value=2):
                at.click(100, 200)
        at.mouse_down.assert_called_once_with(102, 202, name=None)
        at.mouse_up.assert_called_once()

    def test_click_without_position_is_ignored(self):
        at = SyntheticTouch(capture=mock.Mock(), hwnd_window=mock.Mock())
        at.mouse_down = mock.Mock()
        at.click(-1, -1)
        at.mouse_down.assert_not_called()


class TestTouchStateMachine(unittest.TestCase):

    def setUp(self):
        self.at = SyntheticTouch(capture=mock.Mock(), hwnd_window=mock.Mock())
        self.at._anchor_inject_pos = (10, 10)
        self.at._inject_frame = mock.Mock()

    def test_down_then_move_then_up_updates_contact_pos(self):
        self.at._execute(_Command("down", 100, 200))
        self.assertEqual(self.at._contact_pos, (100, 200))
        self.at._execute(_Command("move", 150, 250))
        self.assertEqual(self.at._contact_pos, (150, 250))
        self.at._execute(_Command("up"))

    def test_down_injects_anchor_first_then_contact(self):
        self.at._execute(_Command("down", 100, 200))
        # down 共注入 2 帧：锚点单独按下 + 锚点保持/操作点按下
        self.assertEqual(self.at._inject_frame.call_count, 2)
        # 第一帧只有锚点（占主指针），第二帧才是锚点+操作点
        first_frame = self.at._inject_frame.call_args_list[0].args[0]
        self.assertEqual(len(first_frame), 1)
        self.assertEqual(first_frame[0].touchInfo.pointerInfo.pointerId, win_input.ANCHOR_POINTER_ID)
        second_frame = self.at._inject_frame.call_args_list[1].args[0]
        self.assertEqual(len(second_frame), 2)
        self.assertEqual(second_frame[1].touchInfo.pointerInfo.pointerId, win_input.CONTACT_POINTER_ID)

    def test_move_injects_anchor_and_contact_update(self):
        self.at._execute(_Command("down", 100, 200))
        self.at._inject_frame.reset_mock()
        self.at._execute(_Command("move", 150, 250))
        self.assertEqual(self.at._inject_frame.call_count, 1)
        frame = self.at._inject_frame.call_args.args[0]
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame[1].touchInfo.pointerInfo.ptPixelLocation.x, 150)

    def test_up_releases_contact_then_anchor(self):
        self.at._execute(_Command("down", 100, 200))
        self.at._inject_frame.reset_mock()
        self.at._execute(_Command("up"))
        self.assertEqual(self.at._inject_frame.call_count, 2)
        # 先抬起操作点，再抬起锚点
        first = self.at._inject_frame.call_args_list[0].args[0]
        self.assertEqual(first[0].touchInfo.pointerInfo.pointerId, win_input.CONTACT_POINTER_ID)
        second = self.at._inject_frame.call_args_list[1].args[0]
        self.assertEqual(second[0].touchInfo.pointerInfo.pointerId, win_input.ANCHOR_POINTER_ID)


class TestAnchorOrigin(unittest.TestCase):

    def _at(self, hwnd=12345):
        at = SyntheticTouch(capture=mock.Mock(), hwnd_window=mock.Mock())
        at.hwnd_window.hwnd = hwnd
        return at

    def test_window_covers_full_screen_uses_first_corner(self):
        at = self._at()
        with _metrics(lambda i: {0: 2560, 1: 1440}.get(i, 0)):
            with mock.patch.object(win_input.win32gui, 'GetWindowRect', return_value=(0, 0, 2560, 1440)):
                self.assertEqual(at._choose_anchor_origin(), (win_input.ANCHOR_MARGIN, win_input.ANCHOR_MARGIN))

    def test_avoids_window_at_top_left(self):
        at = self._at()
        with _metrics(lambda i: {0: 2560, 1: 1440}.get(i, 0)):
            with mock.patch.object(win_input.win32gui, 'GetWindowRect', return_value=(0, 0, 1280, 720)):
                # 左上角被窗口覆盖，改选右上角
                self.assertEqual(at._choose_anchor_origin(),
                                 (2560 - win_input.ANCHOR_SIZE - win_input.ANCHOR_MARGIN, win_input.ANCHOR_MARGIN))


if __name__ == '__main__':
    unittest.main()
