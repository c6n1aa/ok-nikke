import os
import unittest
from unittest.mock import PropertyMock, patch

from src.config import config
from src.tasks.ExtrasTask import ExtrasTask
from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')


def _isolate_task_config(task, name):
    """把任务配置重定向到 dev_tools/test_configs 下的临时文件，避免污染真实 configs/。"""
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')
    task.config['_execution_states'] = {}


class _DebugOffTestCase(TaskTestCase):
    """基类：测试环境强制 debug=True，本基类将其屏蔽，以便验证正常的已完成/记录逻辑。"""

    def setUp(self):
        patcher = patch.object(self.task, '_in_debug', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)


def _fake_box(name, x=1, y=1, w=10, h=10):
    """构造一个用于 mock 返回的 Box。"""
    return Box(x, y, w, h, name=name)


class TestExtrasTask(_DebugOffTestCase):
    task_class = ExtrasTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'ExtrasTask')
        self.task.clear_done_all()

    def test_config_defaults(self):
        self.assertEqual("其他杂项", self.task.name)
        self.assertEqual("收取PASS（活动/任务通行证）奖励。", self.task.description)
        self.assertTrue(self.task.default_config["PASS"])
        self.assertIn("PASS", self.task.config_description)
        self.assertEqual({"extras": "day"}, self.task.done_keys)

    def test_skip_when_already_done(self):
        self.task.mark_done("extras", "day")
        with patch.object(self.task, "ensure_screen", side_effect=AssertionError("已完成不应就位大厅")), \
                patch.object(self.task, "_combined_step", side_effect=AssertionError("已完成不应执行领取流程")):
            self.task.run()
        self.assertTrue(self.task.is_done("extras", "day"))

    def test_abort_when_lobby_not_found(self):
        with patch.object(self.task, "ensure_screen", return_value=False), \
                patch.object(self.task, "_combined_step", side_effect=AssertionError("不应执行领取流程")):
            self.task.run()
        self.assertFalse(self.task.is_done("extras", "day"))

    def test_runs_combined_step_and_marks_done(self):
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "try_step") as try_mock:
            self.task.run()
        try_mock.assert_called_once()
        self.assertTrue(self.task.is_done("extras", "day"))

    def test_skips_pass_when_disabled_but_marks_done(self):
        self.task.config["PASS"] = False
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "_combined_step", side_effect=AssertionError("PASS关闭不应执行领取流程")):
            self.task.run()
        self.assertTrue(self.task.is_done("extras", "day"))

    def test_combined_step_skips_claim_when_modal_not_opened(self):
        with patch.object(self.task, "_open_pass_modal", return_value=False), \
                patch.object(self.task, "_claim_pass_modal", side_effect=AssertionError("未打开模态窗不应领取")):
            self.task._combined_step()

    def test_combined_step_opens_then_claims(self):
        with patch.object(self.task, "_open_pass_modal", return_value=True), \
                patch.object(self.task, "_claim_pass_modal") as claim_mock:
            self.task._combined_step()
        claim_mock.assert_called_once()

    def test_open_pass_modal_single_pass_with_red_dot(self):
        badge = _fake_box("box_pass_badge", 100, 100, 20, 20)
        with patch.object(self.task, "find_one", return_value=None) as find_mock, \
                patch.object(self.task, "find_red_dot", return_value=_fake_box("dot")) as dot_mock, \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 200, 300, 50, 60)), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_feature") as wait_mock:
            opened = self.task._open_pass_modal()
        self.assertTrue(opened)
        dot_mock.assert_called_once_with("box_pass_badge", template_path=self.task._RED_DOT_TEMPLATE,
                                          use_color_fallback=False)
        click_mock.assert_called_once_with("box_pass_area", after_sleep=1)
        wait_mock.assert_called_once_with("pass_page", box=_fake_box("box_pass_page", 200, 300, 50, 60),
                                          use_gray_scale=True, time_out=5, raise_if_not_found=True)

    def test_open_pass_modal_single_pass_without_red_dot_skips(self):
        with patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "find_red_dot", return_value=None), \
                patch.object(self.task, "click_box", side_effect=AssertionError("无红点不应点击徽章")), \
                patch.object(self.task, "swipe", side_effect=AssertionError("单个PASS不应翻页")):
            opened = self.task._open_pass_modal()
        self.assertFalse(opened)

    def test_open_pass_modal_multi_flips_until_red_dot(self):
        with patch.object(self.task, "find_one", return_value=_fake_box("pass_switch")), \
                patch.object(self.task, "find_red_dot",
                             side_effect=[None, None, _fake_box("dot")]) as dot_mock, \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 100, 100, 20, 20)), \
                patch.object(self.task, "mouse_down"), \
                patch.object(self.task, "sleep"), \
                patch.object(self.task, "move") as move_mock, \
                patch.object(self.task, "mouse_up"), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_feature"):
            opened = self.task._open_pass_modal()
        self.assertTrue(opened)
        self.assertEqual(2 * self.task._PASS_FLICK_STEPS, move_mock.call_count)  # 前两页各翻页 20 步加速插值，第三页命中。
        self.assertEqual(3, dot_mock.call_count)  # 每次翻页后重新检测红点。
        click_mock.assert_called_once_with("box_pass_area", after_sleep=1)

    def test_open_pass_modal_multi_caps_at_limit(self):
        with patch.object(self.task, "find_one", return_value=_fake_box("pass_selector")), \
                patch.object(self.task, "find_red_dot", return_value=None), \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 100, 100, 20, 20)), \
                patch.object(self.task, "mouse_down"), \
                patch.object(self.task, "sleep"), \
                patch.object(self.task, "move") as move_mock, \
                patch.object(self.task, "mouse_up"), \
                patch.object(self.task, "click_box", side_effect=AssertionError("超过上限不应打开模态窗")):
            opened = self.task._open_pass_modal()
        self.assertFalse(opened)
        self.assertEqual(self.task._PASS_SWIPE_LIMIT * self.task._PASS_FLICK_STEPS, move_mock.call_count)  # 8 次翻页各含 20 步加速插值。

    def test_swipe_pass_page_slides_left_from_badge(self):
        badge = _fake_box("box_pass_area", 20, 60, 40, 20)
        with patch.object(self.task, "get_box_by_name", return_value=badge), \
                patch.object(ExtrasTask, "width", new_callable=PropertyMock, return_value=200), \
                patch.object(self.task, "mouse_down") as down_mock, \
                patch.object(self.task, "sleep") as sleep_mock, \
                patch.object(self.task, "move") as move_mock, \
                patch.object(self.task, "mouse_up") as up_mock:
            self.task._swipe_pass_page()
        down_mock.assert_called_once_with(40, 70)  # 先在徽章区域中心按下不松开。
        self.assertEqual(1 + self.task._PASS_FLICK_STEPS, sleep_mock.call_count)  # 每步 10ms 停顿 + 翻页动画停稳各一次。
        self.assertEqual(self.task._PASS_FLICK_STEPS, move_mock.call_count)  # 逐帧插值移动。
        self.assertEqual((100, 70), move_mock.call_args_list[-1].args)  # 终点到达半屏宽 (100,70)。
        self.assertEqual(40, move_mock.call_args_list[0].args[0])  # 起点从徽章中心 (40) 开始。
        up_mock.assert_called_once()  # 终点以最高速度松开。

    def test_claim_pass_modal_claims_both_pages_and_closes(self):
        claim_box = _fake_box("box_pass_reward_claim_feature", 100, 200, 50, 40)
        with patch.object(self.task, "get_box_by_name", return_value=claim_box), \
                patch.object(self.task, "wait_click_feature") as tab_mock, \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_feature", return_value=None), \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "_close_pass_modal") as close_mock:
            self.task._claim_pass_modal()
        self.assertEqual(2, tab_mock.call_count)  # 任务页 + 奖励页各点击一次。
        self.assertEqual(2, click_mock.call_count)  # 两页各领一次。
        dismiss_mock.assert_called_once_with(time_out=5)  # 奖励页领取后处理一次奖励遮罩。
        close_mock.assert_called_once()

    def test_claim_pass_modal_handles_rank_up(self):
        claim_box = _fake_box("box_pass_reward_claim_feature", 100, 200, 50, 40)
        with patch.object(self.task, "get_box_by_name", return_value=claim_box), \
                patch.object(self.task, "wait_click_feature"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_feature", return_value=_fake_box("pass_rank_up")), \
                patch.object(self.task, "wait_until"), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "_close_pass_modal"):
            self.task._claim_pass_modal()
        self.assertEqual(3, click_mock.call_count)  # 任务页领取 + 关闭RANK UP提示 + 奖励页领取。

    def test_claim_pass_modal_reward_not_available_still_closes(self):
        claim_box = _fake_box("box_pass_reward_claim_feature", 100, 200, 50, 40)
        with patch.object(self.task, "get_box_by_name", return_value=claim_box), \
                patch.object(self.task, "wait_click_feature"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "is_feature_enabled", return_value=False), \
                patch.object(self.task, "click_box", side_effect=AssertionError("无可领奖励不应点击")), \
                patch.object(self.task, "wait_feature", return_value=None), \
                patch.object(self.task, "dismiss_all_popups", side_effect=AssertionError("未领取奖励不应处理遮罩")), \
                patch.object(self.task, "_close_pass_modal") as close_mock:
            self.task._claim_pass_modal()
        close_mock.assert_called_once()

    def test_close_pass_modal_clicks_blank_and_verifies(self):
        with patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "close_popup_by_blank", return_value=True) as blank_mock:
            closed = self.task._close_pass_modal()
        self.assertTrue(closed)  # 确认关闭。
        dismiss_mock.assert_called_once_with(wait_for_popup=False, time_out=5)
        blank_mock.assert_called_once()  # 走基类通用「点空白 + 验证」。
        verify = blank_mock.call_args.args[0]  # 关闭判据。
        with patch.object(self.task, "find_one", return_value=None) as find_mock:
            self.assertTrue(verify())  # 模态窗特征消失 = 已关闭。
        find_mock.assert_called_once_with("pass_page", use_gray_scale=True)

    def test_close_pass_modal_returns_false_when_modal_stays(self):
        with patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "close_popup_by_blank", return_value=False):
            closed = self.task._close_pass_modal()
        self.assertFalse(closed)  # 点空白后模态窗仍在：返回关闭失败。


if __name__ == '__main__':
    unittest.main()