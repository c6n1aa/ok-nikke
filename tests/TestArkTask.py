import os
import unittest
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

import numpy as np

from ok import og
from ok.feature.Box import Box
from ok.task.exceptions import WaitFailedException
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.ArkTask import ArkTask

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


class TestArkTask(_DebugOffTestCase):
    task_class = ArkTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'ArkTask')
        self.task.config["关闭自动爬塔"] = self.task.default_config["关闭自动爬塔"]
        self.task.clear_done("tribe_tower")
        self.task.failed_towers = []

    def test_config_defaults(self):
        self.assertFalse(self.task.default_config["关闭自动爬塔"])
        self.assertIn("关闭自动爬塔", self.task.config_description)
        self.assertEqual({"tribe_tower": "day"}, ArkTask.done_keys)
        self.assertEqual("方舟", self.task.name)

    def test_skip_when_already_done(self):
        self.task.mark_done("tribe_tower", "day")
        with patch.object(self.task, "_tribe_tower_flow", side_effect=AssertionError("不应执行企业塔流程")):
            self.task.run()
        self.assertTrue(self.task.is_done("tribe_tower", "day"))

    def test_abort_when_lobby_not_found(self):
        with patch.object(self.task, "wait_until_lobby_after_start", return_value=False), \
                patch.object(self.task, "_tribe_tower_flow", side_effect=AssertionError("不应执行企业塔流程")):
            self.task.run()
        self.assertFalse(self.task.is_done("tribe_tower", "day"))

    def test_runs_flow_and_marks_done(self):
        with patch.object(self.task, "wait_until_lobby_after_start", return_value=True), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "try_step",
                            side_effect=lambda step_fn, **kw: step_fn()), \
                patch.object(self.task, "_tribe_tower_flow", return_value=True) as flow_mock, \
                patch.object(self.task, "_under_daily", return_value=True):
            self.task.run()
        flow_mock.assert_called_once()
        self.assertTrue(self.task.is_done("tribe_tower", "day"))

    def test_flow_failure_not_marked_done(self):
        with patch.object(self.task, "wait_until_lobby_after_start", return_value=True), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "try_step", return_value=False):
            self.task.run()
        self.assertFalse(self.task.is_done("tribe_tower", "day"))

    def test_standalone_notify_failed_towers(self):
        def fake_flow():
            self.task.failed_towers = [2, 4]
            return True

        with patch.object(self.task, "wait_until_lobby_after_start", return_value=True), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "try_step",
                            side_effect=lambda step_fn, **kw: step_fn()), \
                patch.object(self.task, "_tribe_tower_flow", side_effect=fake_flow), \
                patch.object(self.task, "_under_daily", return_value=False), \
                patch.object(self.task, "log_info") as log_mock:
            self.task.run()
        self.assertTrue(self.task.is_done("tribe_tower", "day"))
        notify_calls = [c for c in log_mock.call_args_list if c.kwargs.get("notify")]
        self.assertEqual(1, len(notify_calls))
        self.assertIn("米西利斯", notify_calls[0].args[0])
        self.assertIn("朝圣者", notify_calls[0].args[0])

    def test_under_daily_suppresses_notify(self):
        def fake_flow():
            self.task.failed_towers = [1]
            return True

        with patch.object(self.task, "wait_until_lobby_after_start", return_value=True), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "try_step",
                            side_effect=lambda step_fn, **kw: step_fn()), \
                patch.object(self.task, "_tribe_tower_flow", side_effect=fake_flow), \
                patch.object(self.task, "_under_daily", return_value=True), \
                patch.object(self.task, "log_info") as log_mock:
            self.task.run()
        notify_calls = [c for c in log_mock.call_args_list if c.kwargs.get("notify")]
        self.assertEqual(0, len(notify_calls))

    def test_notify_message_dedup(self):
        self.task.failed_towers = [2, 2, 4]
        message = self.task.failed_towers_message()
        self.assertIsNotNone(message)
        self.assertEqual(1, message.count("米西利斯"))
        self.assertIn("朝圣者", message)

    def test_notify_message_none_when_no_failures(self):
        self.task.failed_towers = []
        self.assertIsNone(self.task.failed_towers_message())

    def test_notify_failed_towers_skips_when_empty(self):
        with patch.object(self.task, "log_info") as log_mock:
            self.task.notify_failed_towers()
        log_mock.assert_not_called()

    def test_under_daily_when_current_task_is_other(self):
        with patch.object(og, "executor", SimpleNamespace(current_task=object())):
            self.assertTrue(self.task._under_daily())

    def test_under_daily_false_when_current_task_is_self(self):
        with patch.object(og, "executor", SimpleNamespace(current_task=self.task)):
            self.assertFalse(self.task._under_daily())

    def test_under_daily_false_when_no_executor(self):
        with patch.object(og, "executor", None):
            self.assertFalse(self.task._under_daily())

    def test_tower_is_open_true(self):
        fake_box = Box(959, 762, 84, 29, confidence=1, name="box_tribe_tower1")
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "ocr", return_value=[fake_box]):
            self.assertTrue(self.task._tower_is_open("box_tribe_tower1"))

    def test_tower_is_open_false_when_no_open(self):
        fake_box = Box(959, 762, 84, 29, confidence=1, name="box_tribe_tower1")
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "ocr", return_value=[]):
            self.assertFalse(self.task._tower_is_open("box_tribe_tower1"))

    def test_tower_is_open_false_when_box_missing(self):
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")):
            self.assertFalse(self.task._tower_is_open("box_tribe_tower1"))

    def test_is_feature_enabled_true_when_colored(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)  # 蓝色背景帧（B 通道高）。
        frame[:, :, 0] = 255  # 设定 B=255 使像素呈蓝色（高饱和）。
        box = Box(10, 10, 50, 50, confidence=1, name="btn")  # 构造检测区域。
        with patch.object(ArkTask, "frame", new_callable=PropertyMock, return_value=frame):  # mock 当前帧。
            self.assertTrue(self.task.is_feature_enabled(box))  # 彩色区域判定可用。

    def test_is_feature_enabled_false_when_gray(self):
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)  # 灰白帧（RGB 接近、低饱和）。
        box = Box(10, 10, 50, 50, confidence=1, name="btn")  # 构造检测区域。
        with patch.object(ArkTask, "frame", new_callable=PropertyMock, return_value=frame):  # mock 当前帧。
            self.assertFalse(self.task.is_feature_enabled(box))  # 灰白区域判定禁用。

    def test_is_feature_enabled_true_when_no_frame(self):
        box = Box(10, 10, 50, 50, confidence=1, name="btn")  # 构造检测区域。
        with patch.object(ArkTask, "frame", new_callable=PropertyMock, return_value=None):  # mock 无帧。
            self.assertTrue(self.task.is_feature_enabled(box))  # 无帧时保守判定可用。

    def test_enter_tower_click_position(self):
        fake_box = Box(959, 762, 84, 29, confidence=1, name="box_tribe_tower1")
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(ArkTask, "height", new_callable=PropertyMock, return_value=1440), \
                patch.object(self.task, "click") as click_mock:
            self.task._enter_tower("box_tribe_tower1")
        cx, cy = 959 + 42, 762 + 29 + 144
        click_mock.assert_called_once_with(cx, cy, after_sleep=1)

    def test_enter_tower_raises_when_box_missing(self):
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")):
            with self.assertRaises(WaitFailedException):
                self.task._enter_tower("box_tribe_tower1")

    def test_enter_ark_and_tower(self):
        with patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "assert_screen") as assert_mock:
            self.task._enter_ark_and_tower()
        self.assertEqual(
            [("ark",), ("ark_tribe_tower",)],
            [c.args for c in click_mock.call_args_list],
        )
        self.assertEqual(
            [("ark",), ("infinite_tower",)],
            [c.args for c in assert_mock.call_args_list],
        )

    def test_try_tower_skips_when_not_open(self):
        with patch.object(self.task, "_tower_is_open", return_value=False), \
                patch.object(self.task, "_enter_tower", side_effect=AssertionError("不应进入塔")):
            self.assertFalse(self.task._try_tower(1))

    def test_try_tower_skips_when_battle_disabled(self):
        stage_box = Box(1097, 588, 50, 26, confidence=1, name="tribe_tower_stage")
        battle_box = Box(1340, 1283, 80, 106, confidence=1, name="box_tribe_tower_battle")
        with patch.object(self.task, "_tower_is_open", return_value=True), \
                patch.object(self.task, "_enter_tower"), \
                patch.object(self.task, "wait_feature", return_value=stage_box), \
                patch.object(self.task, "get_box_by_name", return_value=battle_box), \
                patch.object(self.task, "is_feature_enabled", return_value=False), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "_climb_battle", side_effect=AssertionError("不应进入战斗")):
            result = self.task._try_tower(1)
        self.assertFalse(result)
        click_mock.assert_any_call("box_tower_enter", raise_if_not_found=True, after_sleep=1)
        click_mock.assert_any_call("tribe_tower_close", raise_if_not_found=True, after_sleep=1)
        click_mock.assert_any_call("common_back", raise_if_not_found=True, after_sleep=1)

    def test_try_tower_battle_button_missing_returns_to_tower(self):
        stage_box = Box(1097, 588, 50, 26, confidence=1, name="tribe_tower_stage")
        with patch.object(self.task, "_tower_is_open", return_value=True), \
                patch.object(self.task, "_enter_tower"), \
                patch.object(self.task, "wait_feature", return_value=stage_box) as wait_mock, \
                patch.object(self.task, "get_box_by_name", return_value=None), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "_climb_battle", side_effect=AssertionError("不应进入战斗")):
            result = self.task._try_tower(1)
        self.assertFalse(result)
        wait_mock.assert_any_call("tribe_tower_stage", raise_if_not_found=True)
        click_mock.assert_any_call("box_tower_enter", raise_if_not_found=True, after_sleep=1)
        click_mock.assert_any_call("tribe_tower_close", raise_if_not_found=True, after_sleep=1)
        click_mock.assert_any_call("common_back", raise_if_not_found=True, after_sleep=1)

    def test_try_tower_normal_climb(self):
        battle_box = Box(1340, 1283, 80, 106, confidence=1, name="box_tribe_tower_battle")
        stage_box = Box(1097, 588, 50, 26, confidence=1, name="tribe_tower_stage")
        with patch.object(self.task, "_tower_is_open", return_value=True), \
                patch.object(self.task, "_enter_tower"), \
                patch.object(self.task, "wait_feature", return_value=stage_box), \
                patch.object(self.task, "get_box_by_name", return_value=battle_box), \
                patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "wait_click_feature"), \
                patch.object(self.task, "_climb_battle") as climb_mock:
            result = self.task._try_tower(2)
        self.assertTrue(result)
        climb_mock.assert_called_once_with(2, battle_box)

    def test_try_tower_abandon_mode(self):
        self.task.config["关闭自动爬塔"] = True
        battle_box = Box(1340, 1283, 80, 106, confidence=1, name="box_tribe_tower_battle")
        stage_box = Box(1097, 588, 50, 26, confidence=1, name="tribe_tower_stage")
        with patch.object(self.task, "_tower_is_open", return_value=True), \
                patch.object(self.task, "_enter_tower"), \
                patch.object(self.task, "wait_feature", return_value=stage_box), \
                patch.object(self.task, "get_box_by_name", return_value=battle_box), \
                patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "wait_click_feature"), \
                patch.object(self.task, "_abandon_battle") as abandon_mock, \
                patch.object(self.task, "_climb_battle", side_effect=AssertionError("不应正常爬塔")):
            result = self.task._try_tower(1)
        self.assertTrue(result)
        abandon_mock.assert_called_once_with(battle_box)

    def test_climb_battle_success_with_next_stage(self):
        esc_box = Box(1252, 1268, 55, 34, confidence=1, name="battle_finish_esc")
        next_box = Box(2300, 1343, 36, 26, confidence=1, name="battile_finish_next_stage")
        battle_btn = Box(10, 10, 5, 5, confidence=1, name="battle_btn")
        with patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_battle_finish",
                            return_value=("success", esc_box)), \
                patch.object(self.task, "find_one", return_value=next_box), \
                patch.object(self.task, "wait_feature"), \
                patch.object(self.task, "wait_click_feature"):
            self.task._climb_battle(1, battle_btn)
        clicked = [c.args[0].name for c in click_mock.call_args_list]
        self.assertEqual(["battle_btn", "battile_finish_next_stage"], clicked)
        self.assertEqual([], self.task.failed_towers)

    def test_climb_battle_success_click_esc_when_no_next_stage(self):
        esc_box = Box(1252, 1268, 55, 34, confidence=1, name="battle_finish_esc")
        battle_btn = Box(10, 10, 5, 5, confidence=1, name="battle_btn")
        with patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_battle_finish",
                            return_value=("success", esc_box)), \
                patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "wait_feature"), \
                patch.object(self.task, "wait_click_feature"):
            self.task._climb_battle(1, battle_btn)
        clicked = [c.args[0].name for c in click_mock.call_args_list]
        self.assertEqual(["battle_btn", "battle_finish_esc"], clicked)
        self.assertEqual([], self.task.failed_towers)

    def test_climb_battle_failure_records_tower(self):
        back_box = Box(38, 1316, 38, 39, confidence=1, name="battle_finish_failed_back")
        battle_btn = Box(10, 10, 5, 5, confidence=1, name="battle_btn")
        with patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_battle_finish",
                            return_value=("failed", back_box)), \
                patch.object(self.task, "find_one"), \
                patch.object(self.task, "wait_feature"), \
                patch.object(self.task, "wait_click_feature"):
            self.task._climb_battle(3, battle_btn)
        clicked = [c.args[0].name for c in click_mock.call_args_list]
        self.assertEqual(["battle_btn", "battle_finish_failed_back"], clicked)
        self.assertEqual([3], self.task.failed_towers)

    def test_climb_battle_timeout_raises(self):
        battle_btn = Box(10, 10, 5, 5, confidence=1, name="battle_btn")
        with patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_battle_finish", return_value=(None, None)):
            with self.assertRaises(WaitFailedException):
                self.task._climb_battle(1, battle_btn)
        self.assertEqual(["battle_btn"], [c.args[0].name for c in click_mock.call_args_list])

    def test_abandon_battle(self):
        battle_btn = Box(1562, 1341, 24, 36, confidence=1, name="battle_btn")
        pause = Box(2496, 22, 53, 51, confidence=1, name="battle_pause")
        escape = Box(1058, 1308, 31, 37, confidence=1, name="battle_escape")
        failed_back = Box(38, 1316, 38, 39, confidence=1, name="battle_finish_failed_back")
        stage_box = Box(1097, 588, 50, 26, confidence=1, name="tribe_tower_stage")
        with patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_feature",
                             side_effect=[pause, escape, failed_back, stage_box]), \
                patch.object(self.task, "wait_click_feature") as back_mock:
            self.task._abandon_battle(battle_btn)
        first_click = click_mock.call_args_list[0]
        self.assertIs(battle_btn, first_click.args[0])
        self.assertEqual(10, first_click.kwargs["after_sleep"])
        self.assertEqual(
            ["battle_pause", "battle_escape", "battle_finish_failed_back"],
            [c.args[0].name for c in click_mock.call_args_list[1:]],
        )
        self.assertEqual(2, back_mock.call_count)

    def test_flow_all_towers_skipped_returns_ark(self):
        with patch.object(self.task, "_enter_ark_and_tower"), \
                patch.object(self.task, "_try_tower", return_value=False) as try_mock, \
                patch.object(self.task, "wait_click_feature") as back_mock:
            self.task._tribe_tower_flow()
        self.assertEqual(4, try_mock.call_count)
        back_mock.assert_called_once_with("common_back", raise_if_not_found=False, after_sleep=1)

    def test_flow_abandon_mode_ends_after_first_battle(self):
        self.task.config["关闭自动爬塔"] = True
        with patch.object(self.task, "_enter_ark_and_tower"), \
                patch.object(self.task, "_try_tower", side_effect=[False, True]) as try_mock, \
                patch.object(self.task, "wait_click_feature") as back_mock:
            self.task._tribe_tower_flow()
        self.assertEqual(2, try_mock.call_count)
        back_mock.assert_not_called()

    def test_flow_normal_mode_processes_all_towers(self):
        with patch.object(self.task, "_enter_ark_and_tower"), \
                patch.object(self.task, "_try_tower", return_value=True) as try_mock, \
                patch.object(self.task, "wait_click_feature") as back_mock:
            self.task._tribe_tower_flow()
        self.assertEqual(4, try_mock.call_count)
        back_mock.assert_called_once()


class TestDailyTaskArkIntegration(_DebugOffTestCase):
    """验证日常编排：方舟子流程记录失败塔后，日常在全部子任务完成后统一提醒。"""

    task_class = ArkTask

    config = config

    def test_daily_runs_ark_and_notifies_after_all(self):
        from ok.test import ok

        from src.tasks.DailyTask import DailyTask
        daily = DailyTask(og.executor, None)
        daily.after_init(executor=ok.task_executor, scene=ok.task_executor.scene)
        _isolate_task_config(daily, 'DailyTask')
        daily.config["方舟"] = True
        ark = self.task
        ark.failed_towers = []

        def fake_run_task_by_class(cls):
            if cls is ArkTask:
                ark.failed_towers = [1, 4]

        with patch.object(daily, "wait_until_lobby_after_start", return_value=True), \
                patch.object(daily, "run_task_by_class", side_effect=fake_run_task_by_class), \
                patch.object(daily, "get_task_by_class", return_value=ark), \
                patch.object(daily, "log_info") as log_mock:
            daily.run()
        notify_calls = [c for c in log_mock.call_args_list if c.kwargs.get("notify")]
        self.assertEqual(1, len(notify_calls))
        self.assertIn("极乐净土", notify_calls[0].args[0])
        self.assertIn("朝圣者", notify_calls[0].args[0])


if __name__ == '__main__':
    unittest.main()