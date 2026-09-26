"""start_tab 补丁：正式版保留「Debug」排障卡片，只隐藏调试悬浮窗开关。

纯 mock 单测：用假 StartTab.__init__ 驱动补丁包装器，不建真实 Qt 控件、不启动 GUI，
只验证开关的显隐分支、持久化悬浮窗配置的清理，以及框架换掉锚点后不炸。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ok import og
from ok.ui.qt.start.StartTab import StartTab

from src.patches import start_tab as start_tab_patch


class _FakeSwitch:
    """假悬浮窗开关：只记录 setVisible 的结果。"""

    def __init__(self):
        self.visible = True

    def setVisible(self, visible):
        self.visible = visible


class TestStartTabOverlaySwitch(unittest.TestCase):
    """apply() 后的 StartTab.__init__：按 debug 配置决定隐藏调试悬浮窗开关。"""

    def setUp(self):
        self.saved_init = StartTab.__init__  # 补丁会永久替换类方法，测试后还原。

    def tearDown(self):
        StartTab.__init__ = self.saved_init

    def _build_tab(self, debug, overlay_enabled, has_switch=True, overlay_state_error=False):
        """用假 init 顶掉框架实现后应用补丁，再实例化（不碰 Qt），返回实例、假 og.app 与假 init。"""
        fake_init = MagicMock()
        if has_switch:  # 模拟框架把开关挂到实例上。
            fake_init.side_effect = lambda self, config, exit_event: setattr(self, 'overlay_switch', _FakeSwitch())
        StartTab.__init__ = fake_init  # 补丁包装的“原实现”。
        start_tab_patch.apply()
        if overlay_state_error:  # 模拟取悬浮窗状态失败。
            overlay_state = MagicMock(side_effect=RuntimeError('boom'))
        else:  # 模拟取悬浮窗状态成功。
            def overlay_state():
                return {'boxes': overlay_enabled}
        app = SimpleNamespace(overlay_state=overlay_state, set_overlay_setting=MagicMock(return_value={'boxes': False}))
        with patch.object(og, 'app', app):
            tab = StartTab.__new__(StartTab)
            tab.__init__({'debug': debug}, MagicMock())
        return tab, app, fake_init

    def test_release_hides_overlay_switch_but_still_builds_card(self):
        """正式版：只隐藏开关，框架原有的卡片构建照常执行（排障按钮保留）。"""
        tab, _, fake_init = self._build_tab(debug=False, overlay_enabled=False)
        self.assertFalse(tab.overlay_switch.visible)  # 调试悬浮窗开关已隐藏。
        fake_init.assert_called_once()  # Debug 卡片本身照常构建。

    def test_release_disables_persisted_overlay(self):
        """正式版：历史配置里开着悬浮窗时显式关掉，避免启动就冒标记框。"""
        _, app, _ = self._build_tab(debug=False, overlay_enabled=True)
        app.set_overlay_setting.assert_called_once_with('boxes', False)

    def test_release_keeps_persisted_overlay_untouched_when_already_off(self):
        """正式版：悬浮窗本来就是关的，不写配置。"""
        _, app, _ = self._build_tab(debug=False, overlay_enabled=False)
        app.set_overlay_setting.assert_not_called()

    def test_debug_keeps_overlay_switch(self):
        """debug 模式：开关保留，配置不动。"""
        tab, app, _ = self._build_tab(debug=True, overlay_enabled=True)
        self.assertTrue(tab.overlay_switch.visible)
        app.set_overlay_setting.assert_not_called()

    def test_missing_switch_does_not_raise(self):
        """框架换掉锚点（没有 overlay_switch）：不抛异常，配置清理照做。"""
        _, app, _ = self._build_tab(debug=False, overlay_enabled=True, has_switch=False)
        app.set_overlay_setting.assert_called_once_with('boxes', False)

    def test_overlay_config_error_is_swallowed(self):
        """取悬浮窗状态抛异常：吞掉异常，不影响 UI 构建。"""
        tab, app, _ = self._build_tab(debug=False, overlay_enabled=True, overlay_state_error=True)
        self.assertFalse(tab.overlay_switch.visible)
        app.set_overlay_setting.assert_not_called()


if __name__ == '__main__':
    unittest.main()
