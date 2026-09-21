import os
import unittest
from unittest.mock import PropertyMock, patch

from src.config import config
from src.tasks.HarvestTask import HarvestTask
from src.tasks.OutpostDefenseTask import OutpostDefenseTask
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


class TestHarvestTask(_DebugOffTestCase):
    task_class = HarvestTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'HarvestTask')
        self.task.clear_done_all()
        self.task.config["PASS"] = True  # 覆盖配置文件里可能残留的关闭状态。

    def test_config_defaults(self):
        self.assertEqual("收获", self.task.name)
        self.assertEqual("收取友情点、邮箱与PASS奖励。", self.task.description)
        self.assertTrue(self.task.default_config["收获友情点"])
        self.assertTrue(self.task.default_config["收取邮箱"])
        self.assertTrue(self.task.default_config["PASS"])
        self.assertIn("PASS", self.task.config_description)
        self.assertEqual({"harvest": "day", "pass": "day"}, self.task.done_keys)

    def test_run_runs_harvest_then_pass(self):
        calls = []  # 记录流程执行顺序。
        with patch.object(self.task, "run_harvest", side_effect=lambda: calls.append("harvest")), \
                patch.object(self.task, "run_pass", side_effect=lambda: calls.append("pass")):
            self.task.run()
        self.assertEqual(["harvest", "pass"], calls)  # 收获流程在前，PASS 流程在后。

    def test_skip_when_already_done(self):
        self.task.mark_done("harvest", "day")
        with patch.object(self.task, "_collect_friend", side_effect=AssertionError("不应执行友情点流程")):
            with patch.object(self.task, "_collect_mailbox", side_effect=AssertionError("不应执行邮箱流程")):
                self.task.run_harvest()
        self.assertTrue(self.task.is_done("harvest", "day"))

    def test_runs_sub_flows_when_not_done(self):
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "_collect_friend") as friend_mock, \
                patch.object(self.task, "_collect_mailbox") as mailbox_mock:
            self.task.run_harvest()
        friend_mock.assert_called_once()
        mailbox_mock.assert_called_once()
        self.assertTrue(self.task.is_done("harvest", "day"))

    def test_abort_when_lobby_not_found(self):
        from ok.task.exceptions import WaitFailedException
        self.task.config["收获友情点"] = True
        self.task.config["收取邮箱"] = True
        with patch.object(self.task, "ensure_screen", side_effect=WaitFailedException("lobby not found")), \
                patch.object(self.task, "_collect_friend", side_effect=AssertionError("不应执行友情点流程")), \
                patch.object(self.task, "_collect_mailbox", side_effect=AssertionError("不应执行邮箱流程")):
            with self.assertRaises(WaitFailedException):
                self.task.run_harvest()
        self.assertFalse(self.task.is_done("harvest", "day"))

    def test_friend_flow_failure_recovered_and_skipped(self):
        from ok.task.exceptions import WaitFailedException
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "_recover_to_lobby", return_value=True), \
                patch.object(self.task, "save_failure_screenshot"), \
                patch.object(self.task, "sleep"), \
                patch.object(self.task, "_collect_friend",
                             side_effect=WaitFailedException("弹窗未完全关闭")) as friend_mock, \
                patch.object(self.task, "_collect_mailbox") as mailbox_mock:
            self.task.run_harvest()
        self.assertGreaterEqual(friend_mock.call_count, 1)  # 失败后尝试过至少一次（含重试）。
        mailbox_mock.assert_called_once()  # 友情点失败不阻塞邮箱流程。
        self.assertTrue(self.task.is_done("harvest", "day"))  # 全部子流程收尾后仍标记完成。

    def test_debug_mode_skips_done_state(self):
        with patch.object(self.task, '_in_debug', return_value=True):
            self.task.mark_done("harvest", "day")
            self.assertFalse(self.task.is_done("harvest", "day"))
            self.task.mark_done("pass", "day")
            self.assertFalse(self.task.is_done("pass", "day"))

    def test_run_pass_skips_when_already_done(self):
        self.task.mark_done("pass", "day")
        with patch.object(self.task, "ensure_screen", side_effect=AssertionError("已完成不应就位大厅")), \
                patch.object(self.task, "_combined_step", side_effect=AssertionError("已完成不应执行领取流程")):
            self.task.run_pass()
        self.assertTrue(self.task.is_done("pass", "day"))

    def test_run_pass_aborts_when_lobby_not_found(self):
        with patch.object(self.task, "ensure_screen", return_value=False), \
                patch.object(self.task, "_combined_step", side_effect=AssertionError("不应执行领取流程")):
            self.task.run_pass()
        self.assertFalse(self.task.is_done("pass", "day"))

    def test_run_pass_runs_combined_step_and_marks_done(self):
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "try_step") as try_mock:
            self.task.run_pass()
        try_mock.assert_called_once_with(self.task._combined_step, name="PASS", raise_on_fail=False)  # 失败恢复回大厅重试，重试耗尽不抛异常。
        self.assertTrue(self.task.is_done("pass", "day"))

    def test_run_pass_skips_pass_when_disabled_but_marks_done(self):
        self.task.config["PASS"] = False
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "_combined_step", side_effect=AssertionError("PASS关闭不应执行领取流程")):
            self.task.run_pass()
        self.assertTrue(self.task.is_done("pass", "day"))

    def test_combined_step_skips_claim_when_modal_not_opened(self):
        with patch.object(self.task, "_pass_multi", return_value=True), \
                patch.object(self.task, "_open_pass_modal", return_value=(False, 0)), \
                patch.object(self.task, "_claim_pass_modal", side_effect=AssertionError("未打开模态窗不应领取")):
            self.task._combined_step()

    def test_combined_step_opens_then_claims(self):
        with patch.object(self.task, "_pass_multi", return_value=False), \
                patch.object(self.task, "_open_pass_modal", return_value=(True, 0)) as open_mock, \
                patch.object(self.task, "_claim_pass_modal") as claim_mock:
            self.task._combined_step()
        claim_mock.assert_called_once()
        open_mock.assert_called_once_with(0, False)  # 单 PASS：初始累计翻页次数 0。

    def test_combined_step_claims_every_pass_with_red_dot(self):
        # 多个 PASS：领完一个后翻页继续找下一个，直到某次查找没命中红点才收工。
        results = [(True, 0), (True, 1), (False, 2)]  # 前两次命中红点，第三次（已累计翻 2 页）无红点。
        with patch.object(self.task, "_pass_multi", return_value=True), \
                patch.object(self.task, "_open_pass_modal", side_effect=results) as open_mock, \
                patch.object(self.task, "_claim_pass_modal") as claim_mock, \
                patch.object(self.task, "_swipe_pass_page") as swipe_mock:
            self.task._combined_step()
        self.assertEqual(2, claim_mock.call_count)  # 两个带红点的 PASS 各领取一次。
        self.assertEqual(2, swipe_mock.call_count)  # 两次领取后各翻一页继续查找。
        self.assertEqual([(0, True), (1, True), (2, True)],
                         [c.args for c in open_mock.call_args_list])  # 累计翻页次数跨轮次传递。

    def test_combined_step_single_pass_claims_once_without_swiping(self):
        with patch.object(self.task, "_pass_multi", return_value=False), \
                patch.object(self.task, "_open_pass_modal", return_value=(True, 0)), \
                patch.object(self.task, "_claim_pass_modal") as claim_mock, \
                patch.object(self.task, "_swipe_pass_page", side_effect=AssertionError("单个PASS不应翻页")):
            self.task._combined_step()
        claim_mock.assert_called_once()

    def test_combined_step_stops_when_swipe_limit_reached(self):
        limit = self.task._PASS_SWIPE_LIMIT  # 翻页次数已用尽。
        with patch.object(self.task, "_pass_multi", return_value=True), \
                patch.object(self.task, "_open_pass_modal", return_value=(True, limit)) as open_mock, \
                patch.object(self.task, "_claim_pass_modal") as claim_mock, \
                patch.object(self.task, "_swipe_pass_page", side_effect=AssertionError("次数用尽不应再翻页")):
            self.task._combined_step()
        claim_mock.assert_called_once()  # 上限内命中的这个 PASS 仍照常领取。
        open_mock.assert_called_once()

    def test_combined_step_raises_when_modal_not_closed(self):
        from ok.task.exceptions import WaitFailedException
        # 关闭失败（页签文字仍在）时画面还是模态窗，翻页拖拽会落在面板上，必须中止交给 try_step 恢复。
        with patch.object(self.task, "_pass_multi", return_value=True), \
                patch.object(self.task, "_open_pass_modal", return_value=(True, 0)), \
                patch.object(self.task, "_claim_pass_modal", return_value=False), \
                patch.object(self.task, "_swipe_pass_page", side_effect=AssertionError("模态窗未关闭不应翻页")):
            with self.assertRaises(WaitFailedException):
                self.task._combined_step()

    def test_pass_multi_detects_switch_or_selector(self):
        with patch.object(self.task, "find_one",
                          side_effect=lambda f: _fake_box(f) if f == "pass_selector" else None):
            self.assertTrue(self.task._pass_multi())  # pass_selector 存在即多个 PASS。
        with patch.object(self.task, "find_one", return_value=None):
            self.assertFalse(self.task._pass_multi())  # 两个入口特征都不存在即单个 PASS。

    def test_open_pass_modal_single_pass_with_red_dot(self):
        with patch.object(self.task, "find_red_dot", return_value=_fake_box("dot")) as dot_mock, \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 200, 300, 50, 60)), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_ocr", return_value=[_fake_box("奖励")]) as ocr_wait_mock:
            opened, swipes = self.task._open_pass_modal(0, False)
        self.assertTrue(opened)
        self.assertEqual(0, swipes)  # 单个 PASS 不翻页，累计翻页次数不变。
        dot_mock.assert_called_once_with("box_pass_badge", template_path=self.task._RED_DOT_TEMPLATE,
                                          use_color_fallback=False)
        click_mock.assert_called_once_with("box_pass_area", after_sleep=1)
        kwargs = ocr_wait_mock.call_args.kwargs  # 打开判据走页签文字 OCR，不用随皮肤变的徽章模板。
        self.assertEqual(list(self.task._PASS_TAB_PATTERNS), kwargs["match"])
        self.assertEqual(5, kwargs["time_out"])
        self.assertFalse(kwargs["raise_if_not_found"])  # 未命中由本方法抛带原因的异常。
        self.assertEqual("pass_tab_area", kwargs["box"].name)

    def test_open_pass_modal_raises_when_tab_text_missing(self):
        from ok.task.exceptions import WaitFailedException
        with patch.object(self.task, "find_red_dot", return_value=_fake_box("dot")), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "wait_ocr", return_value=None):
            with self.assertRaises(WaitFailedException):
                self.task._open_pass_modal(0, False)

    def test_pass_panel_opened_uses_tab_text(self):
        with patch.object(self.task, "ocr", return_value=[_fake_box("任务")]) as ocr_mock:
            self.assertTrue(self.task._pass_panel_opened())
        self.assertEqual(list(self.task._PASS_TAB_PATTERNS), ocr_mock.call_args.kwargs["match"])
        self.assertEqual("pass_tab_area", ocr_mock.call_args.kwargs["box"].name)
        with patch.object(self.task, "ocr", return_value=[]):
            self.assertFalse(self.task._pass_panel_opened())

    def test_open_pass_modal_single_pass_without_red_dot_skips(self):
        with patch.object(self.task, "find_red_dot", return_value=None), \
                patch.object(self.task, "click_box", side_effect=AssertionError("无红点不应点击徽章")), \
                patch.object(self.task, "_swipe_pass_page", side_effect=AssertionError("单个PASS不应翻页")):
            opened, swipes = self.task._open_pass_modal(0, False)
        self.assertFalse(opened)
        self.assertEqual(0, swipes)

    def test_open_pass_modal_multi_flips_until_red_dot(self):
        with patch.object(self.task, "find_red_dot",
                          side_effect=[None, None, _fake_box("dot")]) as dot_mock, \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 100, 100, 20, 20)), \
                patch.object(self.task, "mouse_down"), \
                patch.object(self.task, "sleep"), \
                patch.object(self.task, "move") as move_mock, \
                patch.object(self.task, "mouse_up"), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_ocr", return_value=[_fake_box("奖励")]):
            opened, swipes = self.task._open_pass_modal(0, True)
        self.assertTrue(opened)
        self.assertEqual(2, swipes)  # 前两页各翻一次，第三页命中。
        self.assertEqual(2 * self.task._PASS_FLICK_STEPS, move_mock.call_count)  # 前两页各翻页 20 步加速插值，第三页命中。
        self.assertEqual(3, dot_mock.call_count)  # 每次翻页后重新检测红点。
        click_mock.assert_called_once_with("box_pass_area", after_sleep=1)

    def test_open_pass_modal_multi_caps_at_limit(self):
        with patch.object(self.task, "find_red_dot", return_value=None), \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 100, 100, 20, 20)), \
                patch.object(self.task, "mouse_down"), \
                patch.object(self.task, "sleep"), \
                patch.object(self.task, "move") as move_mock, \
                patch.object(self.task, "mouse_up"), \
                patch.object(self.task, "click_box", side_effect=AssertionError("超过上限不应打开模态窗")):
            opened, swipes = self.task._open_pass_modal(0, True)
        self.assertFalse(opened)
        self.assertEqual(self.task._PASS_SWIPE_LIMIT, swipes)  # 翻页次数停在总上限。
        self.assertEqual(self.task._PASS_SWIPE_LIMIT * self.task._PASS_FLICK_STEPS, move_mock.call_count)  # 8 次翻页各含 20 步加速插值。

    def test_swipe_pass_page_slides_left_from_badge(self):
        badge = _fake_box("box_pass_area", 20, 60, 40, 20)
        with patch.object(self.task, "get_box_by_name", return_value=badge), \
                patch.object(HarvestTask, "width", new_callable=PropertyMock, return_value=200), \
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
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_feature", return_value=None), \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "_close_pass_modal") as close_mock:
            claimed = self.task._claim_pass_modal()
        self.assertTrue(claimed)  # 关闭成功时返回 True。
        tab_calls = [c.args[0] for c in click_mock.call_args_list if isinstance(c.args[0], str)]
        self.assertEqual(["box_pass_mission_page", "box_pass_reward_page"], tab_calls)  # 依次切任务页、奖励页。
        self.assertEqual(2, len([c for c in click_mock.call_args_list if c.args[0] is claim_box]))  # 两页各领一次。
        dismiss_mock.assert_called_once_with(time_out=5)  # 奖励页领取后处理一次奖励遮罩。
        close_mock.assert_called_once()

    def test_claim_pass_modal_handles_rank_up(self):
        claim_box = _fake_box("box_pass_reward_claim_feature", 100, 200, 50, 40)
        with patch.object(self.task, "get_box_by_name", return_value=claim_box), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_feature", return_value=_fake_box("pass_rank_up")), \
                patch.object(self.task, "wait_until"), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "_close_pass_modal"):
            self.task._claim_pass_modal()
        box_calls = [c for c in click_mock.call_args_list if not isinstance(c.args[0], str)]
        self.assertEqual(3, len(box_calls))  # 任务页领取 + 关闭RANK UP提示 + 奖励页领取。

    def test_claim_pass_modal_reward_not_available_still_closes(self):
        claim_box = _fake_box("box_pass_reward_claim_feature", 100, 200, 50, 40)
        with patch.object(self.task, "get_box_by_name", return_value=claim_box), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "is_feature_enabled", return_value=False), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_feature", return_value=None), \
                patch.object(self.task, "dismiss_all_popups", side_effect=AssertionError("未领取奖励不应处理遮罩")), \
                patch.object(self.task, "_close_pass_modal") as close_mock:
            self.task._claim_pass_modal()
        # 领取按钮灰白时只切页签，不点领取按钮。
        self.assertEqual(["box_pass_mission_page", "box_pass_reward_page"],
                         [c.args[0] for c in click_mock.call_args_list])
        close_mock.assert_called_once()

    def test_claim_pass_modal_reports_close_failure(self):
        claim_box = _fake_box("box_pass_reward_claim_feature", 100, 200, 50, 40)
        with patch.object(self.task, "get_box_by_name", return_value=claim_box), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "is_feature_enabled", return_value=False), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "wait_feature", return_value=None), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "_close_pass_modal", return_value=False) as close_mock:
            claimed = self.task._claim_pass_modal()
        self.assertFalse(claimed)  # 未确认关闭时把失败上报给调用方，避免上层继续翻页。
        close_mock.assert_called_once()

    def test_close_pass_modal_clicks_blank_and_verifies(self):
        with patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "close_popup_by_blank", return_value=True) as blank_mock:
            closed = self.task._close_pass_modal()
        self.assertTrue(closed)  # 确认关闭。
        dismiss_mock.assert_called_once_with(wait_for_popup=False, time_out=5)
        blank_mock.assert_called_once()  # 走基类通用「点空白 + 验证」。
        verify = blank_mock.call_args.args[0]  # 关闭判据。
        with patch.object(self.task, "_pass_panel_opened", return_value=False) as panel_mock:
            self.assertTrue(verify())  # 页签文字消失 = 已关闭。
        panel_mock.assert_called_once()
        with patch.object(self.task, "_pass_panel_opened", return_value=True):
            self.assertFalse(verify())  # 面板仍在 = 未确认关闭。

    def test_close_pass_modal_returns_false_when_modal_stays(self):
        with patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "close_popup_by_blank", return_value=False):
            closed = self.task._close_pass_modal()
        self.assertFalse(closed)  # 点空白后模态窗仍在：返回关闭失败。


class TestOutpostDefenseTask(_DebugOffTestCase):
    task_class = OutpostDefenseTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'OutpostDefenseTask')
        self.task.clear_done("outpost_defense")

    def test_config_default(self):
        self.assertEqual(0, self.task.default_config["使用珠宝歼灭次数"])

    def test_validate_config_range(self):
        self.assertIsNone(self.task.validate_config("使用珠宝歼灭次数", 0))
        self.assertIsNone(self.task.validate_config("使用珠宝歼灭次数", 10))
        self.assertIsNotNone(self.task.validate_config("使用珠宝歼灭次数", -1))
        self.assertIsNotNone(self.task.validate_config("使用珠宝歼灭次数", 11))

    def test_skip_when_already_done(self):
        self.task.mark_done("outpost_defense", "day")
        with patch.object(self.task, "_wipe_out_free", side_effect=AssertionError("不应执行免费歼灭")):
            with patch.object(self.task, "_wipe_out_with_gem", side_effect=AssertionError("不应执行珠宝歼灭")):
                self.task.run()
        self.assertTrue(self.task.is_done("outpost_defense", "day"))

    def test_free_wipe_out_when_zero_times(self):
        self.task.config["使用珠宝歼灭次数"] = 0
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "_click_outpost_defense"), \
                patch.object(self.task, "_wipe_out_free") as free_mock, \
                patch.object(self.task, "_wipe_out_with_gem") as gem_mock, \
                patch.object(self.task, "wait_click_feature"):
            self.task.run()
        free_mock.assert_called_once()
        gem_mock.assert_not_called()
        self.assertTrue(self.task.is_done("outpost_defense", "day"))

    def test_gem_wipe_out_loop_when_times_set(self):
        self.task.config["使用珠宝歼灭次数"] = 3
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "_click_outpost_defense"), \
                patch.object(self.task, "_wipe_out_free") as free_mock, \
                patch.object(self.task, "_wipe_out_with_gem") as gem_mock, \
                patch.object(self.task, "wait_click_feature"):
            self.task.run()
        free_mock.assert_not_called()
        self.assertEqual(3, gem_mock.call_count)
        self.assertTrue(self.task.is_done("outpost_defense", "day"))

    def test_abort_when_lobby_not_found(self):
        from ok.task.exceptions import WaitFailedException
        with patch.object(self.task, "ensure_screen", side_effect=WaitFailedException("lobby not found")), \
                patch.object(self.task, "_wipe_out_free", side_effect=AssertionError("不应执行免费歼灭")), \
                patch.object(self.task, "_wipe_out_with_gem", side_effect=AssertionError("不应执行珠宝歼灭")):
            with self.assertRaises(WaitFailedException):
                self.task.run()
        self.assertFalse(self.task.is_done("outpost_defense", "day"))

    def test_debug_mode_skips_done_state(self):
        with patch.object(self.task, '_in_debug', return_value=True):
            self.task.mark_done("outpost_defense", "day")
            self.assertFalse(self.task.is_done("outpost_defense", "day"))

    def test_click_entry_clicks_annotated_region_center(self):
        from ok.feature.Box import Box
        fake_box = Box(623, 1122, 90, 26, confidence=1, name='outpost_defense')
        with patch.object(self.task, 'get_box_by_name', return_value=fake_box) as get_mock, \
                patch.object(self.task, 'click_box') as click_mock:
            result = self.task._click_outpost_defense(time_out=3)
        self.assertTrue(result)
        get_mock.assert_called_once_with('outpost_defense')
        self.assertEqual(1, click_mock.call_count)
        clicked = click_mock.call_args_list[0][0][0]
        self.assertEqual('outpost_defense', clicked.name)
        # 标注区域 DEFENSE 文字中心点：源图 (707.5, 1202)，缩放 0.9444 后约为 (668, 1135)
        cx = clicked.x + clicked.width / 2
        cy = clicked.y + clicked.height / 2
        self.assertAlmostEqual(cx, 668, delta=15)
        self.assertAlmostEqual(cy, 1135, delta=15)

    def test_click_entry_raises_when_region_missing(self):
        from ok.task.exceptions import WaitFailedException
        with patch.object(self.task, 'get_box_by_name', return_value=None), \
                patch.object(self.task, 'sleep'):
            with self.assertRaises(WaitFailedException):
                self.task._click_outpost_defense(time_out=1)


if __name__ == '__main__':
    unittest.main()
