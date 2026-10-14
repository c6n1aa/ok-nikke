import os  # 配置重定向目录用。
import unittest  # 单元测试框架。
from unittest.mock import MagicMock, call, patch  # mock 工具：打桩、调用断言。

from ok.feature.Box import Box  # 构造假特征框。
from ok.task.exceptions import (  # 任务被停止的中断异常与触发 try_step 恢复协议的等待失败异常。
    TaskDisabledException,
    WaitFailedException,
)
from ok.test.TaskTestCase import TaskTestCase  # ok 任务测试基类。

from src.config import config  # 全局任务配置对象（TaskTestCase 要求传入）。
from src.tasks.base._navigation import NavigationMixin  # 基类恢复协议所在 mixin（断言 super() 调用）。
from src.tasks.DailyTask import DailyTask  # 被测任务类。
from src.tasks.HarvestTask import HarvestTask  # 收获子任务（PASS 流程整合在它里面）。
from tests.support.asserts import assert_called_once_semantic

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')  # 测试专用配置目录，避免污染真实 configs/。


def _stub_wait_until(rounds=2):
    """构造 wait_until 桩：模拟框架轮询——每轮先跑 pre_action 再求值条件，命中即返回 True。

    单次调用内最多求值 rounds 轮，全假返回 False（等价于超时），不真的等待。
    """
    def stub(condition, **kwargs):
        pre_action = kwargs.get("pre_action")  # 框架每轮取帧前都会跑 pre_action。
        for _ in range(rounds):
            if pre_action is not None:
                pre_action()
            if condition():
                return True
        return False

    return stub


def _isolate_task_config(task, name):
    """把任务配置重定向到 dev_tools/test_configs 下的临时文件并复位为任务默认值：既不污染真实 configs/，也不读它的值。"""
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)  # 目录不存在则创建。
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')  # 重定向配置文件路径。
    task.config.reset_to_default()  # 复位为任务默认值：用例只设自己关心的开关，不读开发者本地配置。
    task.config['_execution_states'] = {}  # 清空执行状态，避免读到真实环境遗留记录。


_SUB_FLOW_KEYS = ("收获", "歼灭", "前哨基地", "商店", "付费商店", "招募", "方舟", "Raid", "活动")  # 日常编排的全部子流程开关。


class TestDailyTask(TaskTestCase):
    task_class = DailyTask  # 被测任务类。
    task: DailyTask

    config = config  # 共享全局配置。

    def setUp(self):
        _isolate_task_config(self.task, 'DailyTask')  # 重定向配置文件。
        for key in _SUB_FLOW_KEYS:  # 默认关闭全部子流程。
            self.task.config[key] = False  # 让 run() 直接走到收尾流程，测试聚焦收尾编排。

    def test_end_flow_runs_after_all_subtasks(self):
        calls = []  # 记录执行顺序：子流程类名、收获/PASS 与收尾标记。
        ark = MagicMock()  # 方舟子任务桩：避免依赖真实实例。
        ark.failed_towers_message.return_value = None  # 无战斗失败提醒。
        harvest = MagicMock()  # 收获子任务桩：避免真实抓帧。
        harvest.run_harvest.side_effect = lambda: calls.append("harvest")  # 记录收获流程调用。
        harvest.run_pass.side_effect = lambda: calls.append("pass")  # 记录 PASS 流程调用。
        for key in _SUB_FLOW_KEYS:  # 打开全部子流程开关。
            self.task.config[key] = True
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "run_task_by_class", side_effect=lambda cls: calls.append(cls.__name__)), \
                patch.object(self.task, "get_task_by_class",
                             side_effect=lambda cls: harvest if cls is HarvestTask else ark), \
                patch.object(self.task, "_daily_end_flow", side_effect=lambda: calls.append("end_flow")) as end_mock:
            self.task.run()  # 执行日常编排。
        end_mock.assert_called_once()  # 收尾流程执行且仅执行一次。
        self.assertEqual(11, len(calls))  # 9 个子流程（收获拆为收获/PASS 两步）+ 1 次收尾。
        self.assertEqual("harvest", calls[0])  # 收获流程最先执行。
        self.assertEqual("end_flow", calls[-2])  # 收尾流程在全部子流程之后执行。
        self.assertEqual("pass", calls[-1])  # PASS 流程在收尾之后最后执行。

    def test_run_executes_end_flow_when_all_subtasks_disabled(self):
        fake_box = Box(0, 0, 10, 10, name="box_mission_claim")  # 领取按钮区域桩。
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_feature"), \
                patch.object(self.task, "wait_until", side_effect=_stub_wait_until(rounds=1)), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "is_feature_enabled", return_value=False), \
                patch.object(self.task, "find_red_dot", return_value=None):
            self.task.run()  # 全部子流程关闭时也执行收尾流程。
        self.assertEqual(2, click_mock.call_count)  # 打开任务弹窗 + 关闭任务弹窗各点击一次。

    def test_end_flow_navigation_edges(self):
        fake_box = Box(0, 0, 10, 10, name="box_mission_claim")  # 领取按钮区域桩。
        with patch.object(self.task, "ensure_screen") as ensure_mock, \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_feature") as wait_mock, \
                patch.object(self.task, "wait_until", side_effect=_stub_wait_until(rounds=1)), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "is_feature_enabled", return_value=False) as enabled_mock, \
                patch.object(self.task, "find_red_dot", return_value=None) as dot_mock:
            self.task._daily_end_flow()  # 无可领奖励、无红点的空跑。
        ensure_mock.assert_called_once_with("lobby")  # 先幂等就位大厅。
        self.assertEqual(["mission", "mission_page_close"],
                         [c.args[0] for c in click_mock.call_args_list])  # 先点任务入口打开弹窗，收尾点击关闭按钮。
        self.assertEqual([True, True],
                         [c.kwargs["raise_if_not_found"] for c in click_mock.call_args_list])  # 两处点击都要求特征必须命中。
        self.assertEqual(["mission_page", "mission_page"],
                         [c.args[0] for c in wait_mock.call_args_list])  # 打开弹窗 + 关闭弹窗前各确认一次任务弹窗仍可见。
        self.assertEqual([False, False],
                         [c.kwargs["raise_if_not_found"] for c in wait_mock.call_args_list])  # 可见性确认走带上下文的复判，不直接抛空消息异常。
        self.assertEqual(1, enabled_mock.call_count)  # 领取按钮首次判定即灰白，直接结束领取。
        self.assertEqual(
            [call("box_mission_weekly_badge", template_path='assets/template/common/badge.png'),
             call("box_mission_msq_badge", template_path='assets/template/common/badge.png'),
             call("box_mission_achievement_badge", template_path='assets/template/common/badge.png')],
            dot_mock.call_args_list)  # 依次检查三个 tab 徽章红点（模板匹配优先）。

    def test_claim_current_tab_clicks_until_not_ready(self):
        fake_box = Box(0, 0, 10, 10, name="box_mission_claim")  # 领取按钮区域桩。
        with patch.object(self.task, "is_feature_enabled", side_effect=[True, True, False, False]), \
                patch.object(self.task, "wait_until", side_effect=_stub_wait_until()), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock:
            self.task._claim_current_tab(fake_box)  # 前两轮稳定可领（点击），第三轮清完遮罩仍灰（停止）。
        self.assertEqual(2, click_mock.call_count)  # 点击领取两次。
        self.assertEqual(4, dismiss_mock.call_count)  # 每次就绪判定前都先清一次弹窗/遮罩。

    def test_claim_current_tab_keeps_claiming_when_overlay_dims_button(self):
        """遮罩淡入帧上按钮被判灰白不得当成「已领完」：清掉遮罩后复判可领仍继续领（2026-10-13 实机事故）。"""
        fake_box = Box(0, 0, 10, 10, name="box_mission_claim")  # 领取按钮区域桩。
        # 判态序列：淡入帧判灰 → 清遮罩后复判可领（本轮点一次）→ 再判灰 → 清遮罩后仍灰（真领完）。
        with patch.object(self.task, "is_feature_enabled", side_effect=[False, True, False, False]), \
                patch.object(self.task, "wait_until", side_effect=_stub_wait_until()), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock:
            self.task._claim_current_tab(fake_box)
        self.assertEqual(1, click_mock.call_count)  # 首轮灰白没有终止领取，遮罩清掉后照常点击。
        self.assertEqual(4, dismiss_mock.call_count)  # 每次判态前都先清一次弹窗/遮罩。

    def test_claim_current_tab_caps_at_max_clicks(self):
        fake_box = Box(0, 0, 10, 10, name="box_mission_claim")  # 领取按钮区域桩。
        with patch.object(self.task, "wait_until", return_value=True), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "log_warning") as warn_mock:
            self.task._claim_current_tab(fake_box)  # 按钮永远可领，验证次数上限兜底。
        self.assertEqual(self.task._CLAIM_MAX_CLICKS, click_mock.call_count)  # 点击次数达到上限即停。
        warn_mock.assert_called_once()  # 上限触发时记录警告。

    def test_switch_to_tab_clicks_red_dot_and_verifies_subtitle(self):
        fake_box = Box(0, 0, 10, 10, name="box_mission_subtitle")  # 副标题区域桩。
        dot = Box(100, 200, 20, 20, name="red_dot_color")  # 红点命中框桩。
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "find_red_dot", side_effect=[dot, None, None]) as dot_mock, \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_ocr") as ocr_mock:
            switched = self.task._switch_to_tab_with_red_dot(set())  # 周任务徽章有红点，其余无。
        self.assertTrue(switched)  # 发生了一次 tab 切换。
        assert_called_once_semantic(click_mock, dot)  # 点击红点所在徽章。
        ocr_mock.assert_called_once()  # OCR 确认副标题切换。
        kwargs = ocr_mock.call_args.kwargs  # 读取关键字参数。
        self.assertIsNotNone(kwargs["match"].search("Weekly Mission"))  # 周任务副标题正则可命中。
        self.assertEqual(fake_box, kwargs["box"])  # 限定在副标题区域。
        self.assertFalse(kwargs["raise_if_not_found"])  # 确认失败不再抛异常，改为跳过该 tab。
        self.assertEqual('assets/template/common/badge.png', dot_mock.call_args.kwargs['template_path'])  # 红点走模板匹配优先。

    def test_switch_to_tab_skips_when_subtitle_not_confirmed(self):
        fake_box = Box(0, 0, 10, 10, name="box_mission_subtitle")  # 副标题区域桩。
        dot = Box(100, 200, 20, 20, name="red_dot_color")  # 红点命中框桩。
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "find_red_dot", side_effect=[dot, None, None]), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_ocr", return_value=None):
            switched = self.task._switch_to_tab_with_red_dot(set())  # 点击后副标题始终未确认。
        self.assertFalse(switched)  # 未发生有效切换，返回 False。
        self.assertEqual(1, click_mock.call_count)  # 仅点了第一个徽章，确认失败后跳过而非抛异常。

    def test_claim_box_missions_terminates_when_red_dot_persists(self):
        fake_box = Box(0, 0, 10, 10, name="box")  # 通用区域桩（领取按钮/副标题共用）。
        dot = Box(100, 200, 20, 20, name="red_dot_color")  # 永不消失的红点桩。
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "_claim_current_tab") as claim_mock, \
                patch.object(self.task, "find_red_dot", return_value=dot), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_ocr"):
            self.task._claim_box_missions()  # 红点持续存在时必须靠已访问集合终止。
        self.assertEqual(4, claim_mock.call_count)  # 初始 tab + 3 个红点 tab，每个只领一次。
        self.assertEqual(3, click_mock.call_count)  # 三个徽章各点击切换一次。

    def test_wait_mission_popup_clears_overlay_then_confirms(self):
        """弹窗首次未确认时先清一次残留遮罩再复判；复判命中即返回，不抛异常。"""
        fake_box = Box(950, 115, 108, 21, confidence=1, name="mission_page")  # 弹窗标题特征桩。
        with patch.object(self.task, "wait_feature", side_effect=[None, fake_box]) as wait_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock:
            self.task._wait_mission_popup(time_out=5, attempts=2)
        self.assertEqual(2, wait_mock.call_count)  # 首判未命中 + 清遮罩后复判。
        self.assertEqual([False, False],
                         [c.kwargs["raise_if_not_found"] for c in wait_mock.call_args_list])  # 由本方法补上下文，不让框架抛空消息异常。
        dismiss_mock.assert_called_once()  # 复判前清一次遮罩。

    def test_wait_mission_popup_raises_with_context(self):
        """两次确认都未命中：抛带上下文的等待失败异常（框架自身抛的异常消息为空）。"""
        with patch.object(self.task, "wait_feature", return_value=None), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "current_screen", return_value="mission_page"), \
                patch.object(self.task, "log_warning") as warn_mock:
            with self.assertRaises(WaitFailedException) as ctx:
                self.task._wait_mission_popup(time_out=5, attempts=2)
        self.assertEqual("任务弹窗未出现", str(ctx.exception))  # 异常消息带原因。
        self.assertIn("mission_page", warn_mock.call_args.args[0])  # 日志带当前界面便于排查。

    def test_close_mission_popup_tolerates_failure_for_recovery(self):
        """恢复路径用容错关闭：未命中只记日志并返回 False，不抛异常。"""
        with patch.object(self.task, "wait_click_feature", return_value=False) as click_mock, \
                patch.object(self.task, "log_warning") as warn_mock:
            closed = self.task._close_mission_popup(time_out=5, raise_on_fail=False)
        self.assertFalse(closed)
        self.assertFalse(click_mock.call_args.kwargs["raise_if_not_found"])  # 容错模式。
        warn_mock.assert_called_once()

    def test_recover_to_lobby_closes_mission_popup_first(self):
        """失败恢复追加动作：先清遮罩、关掉任务弹窗，再交给基类恢复协议。"""
        order = []  # 记录动作顺序。
        with patch.object(self.task, "next_frame"), \
                patch.object(self.task, "dismiss_all_popups",
                             side_effect=lambda **kwargs: order.append("dismiss")), \
                patch.object(self.task, "find_one",
                             return_value=Box(950, 115, 108, 21, confidence=1, name="mission_page")), \
                patch.object(self.task, "_close_mission_popup",
                             side_effect=lambda **kwargs: order.append("close") or True), \
                patch.object(NavigationMixin, "_recover_to_lobby",
                             side_effect=lambda **kwargs: order.append("base") or True):
            self.assertTrue(self.task._recover_to_lobby())
        self.assertEqual(["dismiss", "close", "base"], order)  # 清遮罩 → 关弹窗 → 基类恢复协议。

    def test_recover_to_lobby_gives_up_when_popup_not_closed(self):
        """任务弹窗关不掉时不得报「已回大厅」（基类 wait_for_lobby 只认 ark 会误报成功）。"""
        with patch.object(self.task, "next_frame"), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "find_one",
                             return_value=Box(950, 115, 108, 21, confidence=1, name="mission_page")), \
                patch.object(self.task, "_close_mission_popup", return_value=False), \
                patch.object(self.task, "log_warning") as warn_mock, \
                patch.object(NavigationMixin, "_recover_to_lobby", return_value=True) as base_mock:
            self.assertFalse(self.task._recover_to_lobby())
        base_mock.assert_not_called()  # 弹窗还在就不走基类恢复协议（否则会误报已回大厅）。
        warn_mock.assert_called_once()

    def test_recover_to_lobby_skips_close_without_popup(self):
        """任务弹窗不在时直接交给基类恢复协议，不做多余点击。"""
        with patch.object(self.task, "next_frame"), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "_close_mission_popup") as close_mock, \
                patch.object(NavigationMixin, "_recover_to_lobby", return_value=True) as base_mock:
            self.assertTrue(self.task._recover_to_lobby())
        close_mock.assert_not_called()
        base_mock.assert_called_once()

    def test_recover_to_lobby_tolerates_cleanup_error(self):
        """恢复动作异常不中断恢复：清弹窗抛非中断异常时只记日志并继续（与基类同一约定）。"""
        with patch.object(self.task, "next_frame"), \
                patch.object(self.task, "dismiss_all_popups", side_effect=FileNotFoundError("template not found")), \
                patch.object(self.task, "log_warning") as warn_mock, \
                patch.object(NavigationMixin, "_recover_to_lobby", return_value=True) as base_mock:
            self.assertTrue(self.task._recover_to_lobby())
        base_mock.assert_called_once()  # 清理异常不阻断恢复协议。
        warn_mock.assert_called_once()  # 记录失败原因。

    def test_recover_to_lobby_propagates_task_disabled(self):
        """任务被用户停止的中断异常必须继续上抛，不能被容错吞掉。"""
        with patch.object(self.task, "next_frame", side_effect=TaskDisabledException()), \
                patch.object(NavigationMixin, "_recover_to_lobby", return_value=True) as base_mock:
            with self.assertRaises(TaskDisabledException):
                self.task._recover_to_lobby()
        base_mock.assert_not_called()  # 中断异常直接结束恢复，不再走基类协议。

    def test_run_notifies_user_when_finished(self):
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "_daily_end_flow"), \
                patch.object(self.task, "log_info") as log_mock:
            self.task.run()  # 全部子流程关闭，走最短路径到流程结束。
        self.assertIn(call("日常完成。", notify=True), log_mock.call_args_list)  # 流程完成后发系统托盘通知。

    def test_end_flow_failure_does_not_break_daily(self):
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "_daily_end_flow",
                             side_effect=WaitFailedException("弹窗关闭失败")) as flow_mock, \
                patch.object(self.task, "_recover_to_lobby", return_value=True), \
                patch.object(self.task, "save_failure_screenshot"), \
                patch.object(self.task, "sleep"):
            self.task.run()  # 收尾失败不应让整个日常任务抛异常。
        self.assertEqual(3, flow_mock.call_count)  # 首次 + 2 次恢复重试。


if __name__ == '__main__':
    unittest.main()
