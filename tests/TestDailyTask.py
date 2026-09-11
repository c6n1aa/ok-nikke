import os  # 配置重定向目录用。
import unittest  # 单元测试框架。
from unittest.mock import MagicMock, call, patch  # mock 工具：打桩、调用断言。

from ok.feature.Box import Box  # 构造假特征框。
from ok.task.exceptions import WaitFailedException  # 触发 try_step 恢复协议的等待失败异常。
from ok.test.TaskTestCase import TaskTestCase  # ok 任务测试基类。

from src.config import config  # 全局任务配置对象（TaskTestCase 要求传入）。
from src.tasks.DailyTask import DailyTask  # 被测任务类。

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')  # 测试专用配置目录，避免污染真实 configs/。


def _isolate_task_config(task, name):
    """把任务配置重定向到 dev_tools/test_configs 下的临时文件，避免污染真实 configs/。"""
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)  # 目录不存在则创建。
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')  # 重定向配置文件路径。
    task.config['_execution_states'] = {}  # 清空执行状态，避免读到真实环境遗留记录。


_SUB_FLOW_KEYS = ("收获", "歼灭", "前哨基地", "商店", "付费商店", "招募", "方舟", "Raid", "其他杂项")  # 日常编排的全部子流程开关。


class TestDailyTask(TaskTestCase):
    task_class = DailyTask  # 被测任务类。

    config = config  # 共享全局配置。

    def setUp(self):
        _isolate_task_config(self.task, 'DailyTask')  # 重定向配置文件。
        for key in _SUB_FLOW_KEYS:  # 默认关闭全部子流程。
            self.task.config[key] = False  # 让 run() 直接走到收尾流程，测试聚焦收尾编排。

    def test_end_flow_runs_after_all_subtasks(self):
        calls = []  # 记录执行顺序：子流程类名与收尾标记。
        ark = MagicMock()  # 方舟子任务桩：避免依赖真实实例。
        ark.failed_towers_message.return_value = None  # 无战斗失败提醒。
        for key in _SUB_FLOW_KEYS:  # 打开全部子流程开关。
            self.task.config[key] = True
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "run_task_by_class", side_effect=lambda cls: calls.append(cls.__name__)), \
                patch.object(self.task, "get_task_by_class", return_value=ark), \
                patch.object(self.task, "_daily_end_flow", side_effect=lambda: calls.append("end_flow")) as end_mock:
            self.task.run()  # 执行日常编排。
        end_mock.assert_called_once()  # 收尾流程执行且仅执行一次。
        self.assertEqual(10, len(calls))  # 9 个子流程 + 1 次收尾。
        self.assertIn("ExtrasTask", calls)  # 其他杂项作为日常子流程被执行。
        self.assertEqual("end_flow", calls[-1])  # 收尾流程在全部子流程之后执行。

    def test_run_executes_end_flow_when_all_subtasks_disabled(self):
        fake_box = Box(0, 0, 10, 10, name="box_mission_claim")  # 领取按钮区域桩。
        with patch.object(self.task, "ensure_screen"), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_feature"), \
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
                patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "is_feature_enabled", return_value=False) as enabled_mock, \
                patch.object(self.task, "find_red_dot", return_value=None) as dot_mock:
            self.task._daily_end_flow()  # 无可领奖励、无红点的空跑。
        ensure_mock.assert_called_once_with("lobby")  # 先幂等就位大厅。
        self.assertEqual(
            [call("mission", time_out=10, raise_if_not_found=True, after_sleep=1),
             call("mission_page_close", time_out=10, raise_if_not_found=True, after_sleep=1)],
            click_mock.call_args_list)  # 先点任务入口打开弹窗，收尾点击关闭按钮。
        wait_mock.assert_has_calls(
            [call("mission_page", time_out=10, raise_if_not_found=True),
             call("mission_page", time_out=10, raise_if_not_found=True)])  # 打开弹窗 + 关闭弹窗前各确认一次任务弹窗仍可见。
        self.assertEqual(1, enabled_mock.call_count)  # 领取按钮首次判定即灰白，直接结束领取。
        self.assertEqual(
            [call("box_mission_weekly_badge", template_path='assets/template/common/badge.png'),
             call("box_mission_msq_badge", template_path='assets/template/common/badge.png'),
             call("box_mission_achievement_badge", template_path='assets/template/common/badge.png')],
            dot_mock.call_args_list)  # 依次检查三个 tab 徽章红点（模板匹配优先）。

    def test_claim_current_tab_clicks_until_disabled(self):
        fake_box = Box(0, 0, 10, 10, name="box_mission_claim")  # 领取按钮区域桩。
        with patch.object(self.task, "is_feature_enabled", side_effect=[True, True, False]), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock:
            self.task._claim_current_tab(fake_box)  # 前两次可用（点击），第三次变灰（停止）。
        self.assertEqual(2, click_mock.call_count)  # 点击领取两次。
        self.assertEqual(2, dismiss_mock.call_count)  # 每次点击后清理弹窗两次。

    def test_claim_current_tab_caps_at_max_clicks(self):
        fake_box = Box(0, 0, 10, 10, name="box_mission_claim")  # 领取按钮区域桩。
        with patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "log_warning") as warn_mock:
            self.task._claim_current_tab(fake_box)  # 按钮永远可用，验证次数上限兜底。
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
        click_mock.assert_called_once_with(dot, after_sleep=1)  # 点击红点所在徽章。
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
