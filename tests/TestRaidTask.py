
import os
import unittest
from unittest.mock import patch, MagicMock

from ok import og
from ok.feature.Box import Box
from ok.task.exceptions import WaitFailedException
from ok.test.TaskTestCase import TaskTestCase
from src.config import config
from src.tasks.ArkTask import ArkTask
from src.tasks.RaidTask import RaidTask

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')

def _isolate_task_config(task, name):
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')
    task.config['_execution_states'] = {}

def _fake_box(name, x=10, y=10, w=20, h=20):
    return Box(x, y, w, h, confidence=1, name=name)

class _DebugOffTestCase(TaskTestCase):
    def setUp(self):
        patcher = patch.object(self.task, '_in_debug', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

class TestRaidTaskConfig(_DebugOffTestCase):
    task_class = RaidTask
    config = config
    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'RaidTask')
        self.task.clear_done_all()
        self.task.config["协同作战"] = True
        self.task.config["个人突袭"] = True
    def test_done_keys(self):
        self.assertEqual({"coop": "day", "solo_raid": "day"}, RaidTask.done_keys)
    def test_name_and_description(self):
        self.assertEqual("Raid", self.task.name)
        self.assertEqual("执行限时挑战（协同作战/个人突袭）任务", self.task.description)
    def test_default_config(self):
        self.assertTrue(self.task.default_config["协同作战"])
        self.assertTrue(self.task.default_config["个人突袭"])
        self.assertIn("协同作战", self.task.config_description)
        self.assertIn("个人突袭", self.task.config_description)
    def test_screens_registered(self):
        self.assertIn("coop_page", self.task.screens)
        self.assertIn("coop_nikke_select_page", self.task.screens)
        self.assertEqual(["coop_page"], self.task.screens["coop_page"]["features"])
        self.assertEqual(["coop_nikke_select_page"], self.task.screens["coop_nikke_select_page"]["features"])

class TestRaidTaskSkip(_DebugOffTestCase):
    task_class = RaidTask
    config = config
    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'RaidTask')
        self.task.clear_done_all()
    def test_skip_when_coop_disabled(self):
        self.task.config["协同作战"] = False
        self.task.config["个人突袭"] = False
        with patch.object(self.task, "_do_coop_flow", side_effect=AssertionError("不应执行协同作战")):
            self.task._do_coop()
        self.assertFalse(self.task.is_done("coop", "day"))
    def test_skip_when_already_done(self):
        self.task.config["协同作战"] = True
        self.task.mark_done("coop", "day")
        with patch.object(self.task, "_do_coop_flow", side_effect=AssertionError("不应执行已完成流程")):
            self.task._do_coop()
        self.assertTrue(self.task.is_done("coop", "day"))
    def test_skip_solo_when_disabled(self):
        self.task.config["个人突袭"] = False
        with patch.object(self.task, "_do_solo_raid_flow", side_effect=AssertionError("不应执行个人突袭")):
            self.task._do_solo_raid()
        self.assertFalse(self.task.is_done("solo_raid", "day"))
    def test_skip_solo_when_already_done(self):
        self.task.config["个人突袭"] = True
        self.task.mark_done("solo_raid", "day")
        with patch.object(self.task, "_do_solo_raid_flow", side_effect=AssertionError("不应执行已完成流程")):
            self.task._do_solo_raid()
        self.assertTrue(self.task.is_done("solo_raid", "day"))

class TestRaidTaskRun(_DebugOffTestCase):
    task_class = RaidTask
    config = config
    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'RaidTask')
        self.task.clear_done_all()
        self.task.config["协同作战"] = True
        self.task.config["个人突袭"] = True
    def test_abort_when_lobby_not_found(self):
        with patch.object(self.task, "wait_until_lobby_after_start", return_value=False), patch.object(self.task, "_do_coop_flow", side_effect=AssertionError("不应执行")):
            self.task.run()
        self.assertFalse(self.task.is_done("coop", "day"))
        self.assertFalse(self.task.is_done("solo_raid", "day"))
    def test_runs_both_subflows_and_marks_done(self):
        with patch.object(self.task, "wait_until_lobby_after_start", return_value=True), patch.object(self.task, "try_step", side_effect=lambda fn, **kw: fn() or True), patch.object(self.task, "_do_coop_flow") as coop_mock, patch.object(self.task, "_do_solo_raid_flow") as solo_mock:
            self.task.run()
        coop_mock.assert_called_once()
        solo_mock.assert_called_once()
        self.assertTrue(self.task.is_done("coop", "day"))
        self.assertTrue(self.task.is_done("solo_raid", "day"))
    def test_failure_not_marked_done(self):
        with patch.object(self.task, "wait_until_lobby_after_start", return_value=True), patch.object(self.task, "try_step", side_effect=[False, False]):
            self.task.run()
        self.assertFalse(self.task.is_done("coop", "day"))
        self.assertFalse(self.task.is_done("solo_raid", "day"))
    def test_run_executes_in_order(self):
        order = []
        with patch.object(self.task, "wait_until_lobby_after_start", return_value=True), patch.object(self.task, "try_step", side_effect=lambda fn, **kw: (fn(), True)[1]), patch.object(self.task, "_do_coop_flow", side_effect=lambda: order.append("coop")), patch.object(self.task, "_do_solo_raid_flow", side_effect=lambda: order.append("solo")):
            self.task.run()
        self.assertEqual(["coop", "solo"], order)

class TestRaidTaskCoopFlow(_DebugOffTestCase):
    task_class = RaidTask
    config = config
    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'RaidTask')
        self.task.clear_done("coop")
        self.task.config["协同作战"] = True
    def test_coop_entry_not_found_marks_done(self):
        panel = _fake_box("box_lobby_left_side_panel", 0, 0, 100, 100)
        with patch.object(self.task, "is_screen", return_value=False), patch.object(self.task, "wait_until_lobby_after_start", return_value=True), patch.object(self.task, "dismiss_all_popups"), patch.object(self.task, "get_box_by_name", return_value=panel), patch.object(self.task, "find_one", return_value=None) as find_mock, patch.object(self.task, "click_box", side_effect=AssertionError("未找到入口不应点击")):
            self.task._do_coop_flow()
        find_mock.assert_called_once()
        args, kwargs = find_mock.call_args
        self.assertEqual("coop", args[0])
        self.assertTrue(kwargs.get("use_gray_scale"))
    def test_coop_count_finished_skips_battle(self):
        panel = _fake_box("box_lobby_left_side_panel", 0, 0, 100, 100)
        coop_box = _fake_box("coop", 5, 5, 10, 10)
        count_box = _fake_box("box_coop_count", 20, 20, 30, 10)
        ocr_03 = _fake_box("0/3", 21, 21, 5, 5)
        with patch.object(self.task, "is_screen", return_value=False), patch.object(self.task, "wait_until_lobby_after_start", return_value=True), patch.object(self.task, "dismiss_all_popups"), patch.object(self.task, "get_box_by_name", side_effect=lambda n: {"box_lobby_left_side_panel": panel, "box_coop_count": count_box}.get(n, _fake_box(n))), patch.object(self.task, "find_one", side_effect=lambda name, **kw: coop_box if name=="coop" else _fake_box(name) if name=="common_home" else None), patch.object(self.task, "click_box") as click_mock, patch.object(self.task, "assert_screen") as assert_mock, patch.object(self.task, "ocr", return_value=[ocr_03]), patch.object(self.task, "wait_feature", side_effect=AssertionError("次数已用尽不应进入匹配")):
            self.task._do_coop_flow()
        self.assertEqual(1, sum(1 for c in click_mock.call_args_list if c.args[0]==coop_box))
        assert_mock.assert_any_call("coop_page")
    def test_coop_is_finished_detection(self):
        count_box = _fake_box("box_coop_count", 0, 0, 50, 20)
        with patch.object(self.task, "get_box_by_name", return_value=count_box), patch.object(self.task, "ocr", return_value=[_fake_box("1/3"), _fake_box("0/3")]):
            self.assertTrue(self.task._is_coop_finished())
        with patch.object(self.task, "get_box_by_name", return_value=count_box), patch.object(self.task, "ocr", return_value=[_fake_box("1/3"), _fake_box("2/3")]):
            self.assertFalse(self.task._is_coop_finished())
        with patch.object(self.task, "get_box_by_name", return_value=count_box), patch.object(self.task, "ocr", return_value=[]):
            self.assertFalse(self.task._is_coop_finished())
    def test_coop_full_loop_one_battle(self):
        panel = _fake_box("box_lobby_left_side_panel", 0, 0, 100, 100)
        coop_box = _fake_box("coop", 5, 5, 10, 10)
        count_box = _fake_box("box_coop_count", 20, 20, 30, 10)
        home_box = _fake_box("common_home", 0, 0, 5, 5)
        esc_box = _fake_box("battle_finish_esc", 100, 100, 20, 10)
        ocr_seq = [[_fake_box("剩余次数 1/3")], [_fake_box("0/3")]]
        with patch.object(self.task, "is_screen", return_value=False), patch.object(self.task, "wait_until_lobby_after_start", return_value=True), patch.object(self.task, "dismiss_all_popups"), patch.object(self.task, "get_box_by_name", side_effect=lambda n: {"box_lobby_left_side_panel": panel, "box_coop_count": count_box}.get(n, _fake_box(n))), patch.object(self.task, "find_one", side_effect=lambda name, **kw: {"coop": coop_box, "common_home": home_box}.get(name)), patch.object(self.task, "click_box") as click_mock, patch.object(self.task, "assert_screen") as assert_mock, patch.object(self.task, "ocr", side_effect=ocr_seq), patch.object(self.task, "wait_feature") as wait_mock, patch.object(self.task, "wait_click_feature") as wait_click_mock, patch.object(self.task, "sleep"), patch.object(self.task, "wait_battle_finish", return_value=("success", esc_box)), patch.object(self.task, "wait_for_lobby") as lobby_mock:
            self.task._do_coop_flow()
        wait_mock.assert_any_call("coop_match_page", time_out=10, raise_if_not_found=True)
        wait_click_mock.assert_any_call("coop_accpet", time_out=60, raise_if_not_found=True, after_sleep=1)
        esc_clicked = any(c.args[0]==esc_box for c in click_mock.call_args_list)
        self.assertTrue(esc_clicked)
        lobby_mock.assert_called_once()
    def test_coop_battle_timeout_raises(self):
        panel = _fake_box("box_lobby_left_side_panel", 0, 0, 100, 100)
        coop_box = _fake_box("coop", 5, 5, 10, 10)
        count_box = _fake_box("box_coop_count", 20, 20, 30, 10)
        with patch.object(self.task, "is_screen", return_value=False), patch.object(self.task, "wait_until_lobby_after_start", return_value=True), patch.object(self.task, "dismiss_all_popups"), patch.object(self.task, "get_box_by_name", side_effect=lambda n: {"box_lobby_left_side_panel": panel, "box_coop_count": count_box}.get(n, _fake_box(n))), patch.object(self.task, "find_one", return_value=coop_box), patch.object(self.task, "click_box"), patch.object(self.task, "assert_screen"), patch.object(self.task, "ocr", return_value=[_fake_box("1/3")]), patch.object(self.task, "wait_feature", return_value=_fake_box("coop_match_page")), patch.object(self.task, "wait_click_feature", return_value=_fake_box("coop_accpet")), patch.object(self.task, "sleep"), patch.object(self.task, "wait_battle_finish", return_value=(None, None)):
            with self.assertRaises(WaitFailedException):
                self.task._do_coop_flow()
    def test_get_panel_box_missing_raises(self):
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")):
            with self.assertRaises(WaitFailedException):
                self.task._get_panel_box()

class TestRaidTaskSolo(_DebugOffTestCase):
    task_class = RaidTask
    config = config
    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'RaidTask')
        self.task.clear_done("solo_raid")
        self.task.config["个人突袭"] = True
    def test_solo_flow_placeholder_marks_done(self):
        with patch.object(self.task, "try_step", side_effect=lambda fn, **kw: fn() or True):
            self.task._do_solo_raid()
        self.assertTrue(self.task.is_done("solo_raid", "day"))
    def test_solo_failure_not_marked(self):
        with patch.object(self.task, "try_step", return_value=False):
            self.task._do_solo_raid()
        self.assertFalse(self.task.is_done("solo_raid", "day"))

class TestDailyTaskRaidIntegration(_DebugOffTestCase):
    """验证日常编排：日常开关开启讨伐时按顺序运行 RaidTask 子任务。"""

    task_class = RaidTask

    config = config

    def test_daily_runs_raid_subtask(self):
        from ok.test import ok

        from src.tasks.DailyTask import DailyTask
        daily = DailyTask(og.executor, None)
        daily.after_init(executor=ok.task_executor, scene=ok.task_executor.scene)
        _isolate_task_config(daily, 'DailyTask')
        daily.config["讨伐"] = True
        raid_ran = []
        real_run = self.task.run

        def fake_run():
            raid_ran.append("raid")
            return real_run()

        with patch.object(daily, "wait_until_lobby_after_start", return_value=True), \
                patch.object(daily, "run_task_by_class") as run_mock, \
                patch.object(self.task, "run", side_effect=fake_run):
            # 拦截 run_task_by_class：仅验证调用顺序与开关判断，不真正执行子任务。
            run_mock.side_effect = lambda cls: raid_ran.append(cls.__name__) if cls is RaidTask else None
            daily.run()
        run_calls = [c.args[0] for c in run_mock.call_args_list]
        self.assertIn(RaidTask, run_calls)
        self.assertLess(run_calls.index(ArkTask), run_calls.index(RaidTask))  # 讨伐排在方舟之后。
        self.assertIn("RaidTask", raid_ran)

if __name__ == '__main__':
    unittest.main()
