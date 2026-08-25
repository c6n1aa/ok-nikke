import os
import unittest
from contextlib import ExitStack
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
        self.task.config["企业塔"] = self.task.default_config["企业塔"]
        self.task.config["模拟室"] = False  # 默认关闭模拟室子流程，企业塔相关测试不受其干扰。
        self.task.config["新人竞技场"] = False  # 默认关闭新人竞技场子流程，企业塔相关测试不受其干扰。
        self.task.config["特殊竞技场"] = False  # 默认关闭特殊竞技场子流程，企业塔相关测试不受其干扰。
        self.task.clear_done("tribe_tower")
        self.task.clear_done("simulation")
        self.task.clear_done("rookie_arena")
        self.task.clear_done("special_arena")
        self.task.failed_towers = []

    def test_config_defaults(self):
        self.assertTrue(self.task.default_config["企业塔"])  # 企业塔子流程默认开启。
        self.assertIn("企业塔", self.task.config_description)  # 企业塔配置有中文帮助文本。
        sub = self.task.config_type["企业塔"]["sub_configs"]  # 开关联动子配置显隐。
        self.assertEqual(["关闭自动爬塔"], sub[True])  # 启用时显示爬塔模式开关。
        self.assertEqual([], sub[False])  # 关闭时收起配置。
        self.assertFalse(self.task.default_config["关闭自动爬塔"])
        self.assertIn("关闭自动爬塔", self.task.config_description)
        self.assertTrue(self.task.default_config["模拟室"])  # 模拟室子流程默认开启。
        self.assertIn("模拟室", self.task.config_description)  # 模拟室配置有中文帮助文本。
        self.assertEqual({"tribe_tower": "day", "simulation": "day", "rookie_arena": "day", "special_arena": "day"}, ArkTask.done_keys)
        self.assertTrue(self.task.default_config["新人竞技场"])  # 新人竞技场子流程默认开启。
        self.assertTrue(self.task.default_config["对手选择策略"])  # 对手选择策略默认开启。
        self.assertTrue(self.task.default_config["特殊竞技场"])  # 特殊竞技场子流程默认开启。
        self.assertIn("新人竞技场", self.task.config_description)  # 新人竞技场配置有中文帮助文本。
        self.assertIn("对手选择策略", self.task.config_description)  # 对手选择策略配置有中文帮助文本。
        self.assertIn("特殊竞技场", self.task.config_description)  # 特殊竞技场配置有中文帮助文本。
        rookie_sub = self.task.config_type["新人竞技场"]["sub_configs"]  # 开关联动对手选择策略显隐。
        self.assertEqual(["对手选择策略"], rookie_sub[True])  # 启用时显示对手选择策略开关。
        self.assertEqual([], rookie_sub[False])  # 关闭时收起配置。
        self.assertEqual("方舟", self.task.name)

    def test_skip_tribe_tower_when_disabled(self):
        self.task.config["企业塔"] = False  # 用户未启用企业塔。
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "_do_tribe_tower_flow", side_effect=AssertionError("不应执行企业塔流程")), \
                patch.object(self.task, "_do_simulation_flow"):
            self.task.run()
        self.assertFalse(self.task.is_done("tribe_tower", "day"))

    def test_skip_when_already_done(self):
        self.task.mark_done("tribe_tower", "day")
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "_do_tribe_tower_flow", side_effect=AssertionError("不应执行企业塔流程")):
            self.task.run()
        self.assertTrue(self.task.is_done("tribe_tower", "day"))

    def test_abort_when_lobby_not_found(self):
        with patch.object(self.task, "_nav_to_ark", side_effect=WaitFailedException("未能进入方舟")), \
                patch.object(self.task, "_recover_to_lobby", return_value=True), \
                patch.object(self.task, "_do_tribe_tower_flow", side_effect=AssertionError("不应执行企业塔流程")):
            self.task.run()
        self.assertFalse(self.task.is_done("tribe_tower", "day"))

    def test_runs_flow_and_marks_done(self):
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "try_step",
                            side_effect=lambda step_fn, **kw: step_fn()), \
                patch.object(self.task, "_do_tribe_tower_flow", return_value=True) as flow_mock, \
                patch.object(self.task, "_under_daily", return_value=True):
            self.task.run()
        flow_mock.assert_called_once()
        self.assertTrue(self.task.is_done("tribe_tower", "day"))

    def test_flow_failure_not_marked_done(self):
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "try_step", side_effect=[True, False]):
            self.task.run()
        self.assertFalse(self.task.is_done("tribe_tower", "day"))

    def test_standalone_notify_failed_towers(self):
        def fake_flow():
            self.task.failed_towers = [2, 4]
            return True

        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "try_step",
                            side_effect=lambda step_fn, **kw: step_fn()), \
                patch.object(self.task, "_do_tribe_tower_flow", side_effect=fake_flow), \
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

        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "try_step",
                            side_effect=lambda step_fn, **kw: step_fn()), \
                patch.object(self.task, "_do_tribe_tower_flow", side_effect=fake_flow), \
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
        click_mock.assert_called_once_with(cx, cy, after_sleep=3)

    def test_enter_tower_raises_when_box_missing(self):
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")):
            with self.assertRaises(WaitFailedException):
                self.task._enter_tower("box_tribe_tower1")

    def test_enter_tribe_tower(self):
        with patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True) as wait_mock:
            self.task._enter_tribe_tower()
        self.assertEqual([("ark_tribe_tower",)], [c.args for c in click_mock.call_args_list])
        self.assertEqual([("tribe_tower",)], [c.args for c in wait_mock.call_args_list])  # transition 内部确认目标界面。

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
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "_climb_battle", side_effect=AssertionError("不应进入战斗")):
            result = self.task._try_tower(1)
        self.assertFalse(result)
        click_box_mock.assert_any_call("box_tower_enter", raise_if_not_found=True, after_sleep=1)
        click_mock.assert_any_call("tribe_tower_close", raise_if_not_found=True, after_sleep=1)
        click_mock.assert_any_call("common_back", raise_if_not_found=True, after_sleep=1)

    def test_try_tower_battle_button_missing_returns_to_tower(self):
        stage_box = Box(1097, 588, 50, 26, confidence=1, name="tribe_tower_stage")
        with patch.object(self.task, "_tower_is_open", return_value=True), \
                patch.object(self.task, "_enter_tower"), \
                patch.object(self.task, "wait_feature", return_value=stage_box) as wait_mock, \
                patch.object(self.task, "get_box_by_name", return_value=None), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "_climb_battle", side_effect=AssertionError("不应进入战斗")):
            result = self.task._try_tower(1)
        self.assertFalse(result)
        wait_mock.assert_any_call("tribe_tower_stage", raise_if_not_found=True)
        click_box_mock.assert_any_call("box_tower_enter", raise_if_not_found=True, after_sleep=1)
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
                            side_effect=[("success", esc_box), ("success", esc_box)]), \
                patch.object(self.task, "find_one", side_effect=[next_box, None]), \
                patch.object(self.task, "wait_feature"), \
                patch.object(self.task, "wait_click_feature"), \
                patch.object(self.task, "dismiss_all_popups"):
            self.task._climb_battle(1, battle_btn)
        clicked = [c.args[0].name for c in click_mock.call_args_list]
        self.assertEqual(["battle_btn", "battile_finish_next_stage", "battle_finish_esc"], clicked)
        self.assertEqual([], self.task.failed_towers)

    def test_climb_battle_success_click_esc_when_no_next_stage(self):
        esc_box = Box(1252, 1268, 55, 34, confidence=1, name="battle_finish_esc")
        battle_btn = Box(10, 10, 5, 5, confidence=1, name="battle_btn")
        with patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_battle_finish",
                            return_value=("success", esc_box)), \
                patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "wait_feature"), \
                patch.object(self.task, "wait_click_feature") as back_mock, \
                patch.object(self.task, "dismiss_all_popups"):
            self.task._climb_battle(1, battle_btn)
        clicked = [c.args[0].name for c in click_mock.call_args_list]
        self.assertEqual(["battle_btn", "battle_finish_esc"], clicked)
        back_mock.assert_called_once_with("common_back", raise_if_not_found=True,
                                          after_sleep=1)  # 返回后不再固定等待，由流程在下一塔前断言无限之塔界面。
        self.assertEqual([], self.task.failed_towers)

    def test_climb_battle_failure_records_tower(self):
        back_box = Box(38, 1316, 38, 39, confidence=1, name="battle_finish_failed_back")
        battle_btn = Box(10, 10, 5, 5, confidence=1, name="battle_btn")
        with patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_battle_finish",
                            return_value=("failed", back_box)), \
                patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "wait_feature"), \
                patch.object(self.task, "wait_click_feature"), \
                patch.object(self.task, "dismiss_all_popups"):
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
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "_enter_tribe_tower"), \
                patch.object(self.task, "assert_screen") as assert_mock, \
                patch.object(self.task, "_try_tower", return_value=False) as try_mock, \
                patch.object(self.task, "wait_click_feature") as back_mock:
            self.task._do_tribe_tower_flow()
        self.assertEqual(4, try_mock.call_count)
        self.assertEqual(3, assert_mock.call_count)  # 塔 2-4 开始前必须先识别到无限之塔界面。
        self.assertEqual([("tribe_tower",), ("tribe_tower",), ("tribe_tower",)],
                         [c.args for c in assert_mock.call_args_list])
        back_mock.assert_called_once_with("common_back", raise_if_not_found=False, after_sleep=1)

    def test_flow_abandon_mode_ends_after_first_battle(self):
        self.task.config["关闭自动爬塔"] = True
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "_enter_tribe_tower"), \
                patch.object(self.task, "assert_screen") as assert_mock, \
                patch.object(self.task, "_try_tower", side_effect=[False, True]) as try_mock, \
                patch.object(self.task, "wait_click_feature") as back_mock:
            self.task._do_tribe_tower_flow()
        self.assertEqual(2, try_mock.call_count)
        assert_mock.assert_called_once_with("tribe_tower")  # 仅第 2 塔前做一次界面识别门控。
        back_mock.assert_not_called()

    def test_flow_normal_mode_processes_all_towers(self):
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "_enter_tribe_tower"), \
                patch.object(self.task, "assert_screen") as assert_mock, \
                patch.object(self.task, "_try_tower", return_value=True) as try_mock, \
                patch.object(self.task, "wait_click_feature") as back_mock:
            self.task._do_tribe_tower_flow()
        self.assertEqual(4, try_mock.call_count)
        self.assertEqual(3, assert_mock.call_count)  # 打完一塔返回后先识别到无限之塔界面再判断下一塔。
        back_mock.assert_called_once()


class TestArkTaskSimulation(_DebugOffTestCase):
    """模拟室子流程测试：覆盖成功/跳过/失败/已完成跳过等主要分支。"""

    task_class = ArkTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'ArkTask')
        # 配置写穿透到共享临时文件：其他测试类留下的 企业塔/关闭自动爬塔 关闭态会泄漏进来
        # （典型症状：企业塔分支静默跳过导致 try_step side_effect 错位、顺序断言失败），必须显式钉死三个键。
        self.task.config["企业塔"] = self.task.default_config["企业塔"]
        self.task.config["关闭自动爬塔"] = self.task.default_config["关闭自动爬塔"]
        self.task.config["模拟室"] = True  # 模拟室子流程测试统一开启。
        self.task.config["新人竞技场"] = False  # 关闭新人竞技场子流程，保证测试顺序隔离。
        self.task.config["特殊竞技场"] = False  # 关闭特殊竞技场子流程，保证测试顺序隔离。
        self.task.clear_done("simulation")
        self.task.clear_done("tribe_tower")
        self.task.clear_done("rookie_arena")
        self.task.clear_done("special_arena")

    def _patch_common(self):
        """返回公共补丁栈：已确保在方舟界面、企业塔流程置空。"""
        stack = ExitStack()  # 统一管理补丁生命周期。
        stack.enter_context(patch.object(self.task, "_nav_to_ark"))
        stack.enter_context(patch.object(self.task, "_do_tribe_tower_flow"))
        return stack

    def test_skip_when_disabled(self):
        self.task.config["模拟室"] = False  # 用户未启用模拟室。
        with patch.object(self.task, "_do_simulation_flow", side_effect=AssertionError("不应执行模拟室流程")), \
                patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "_do_tribe_tower_flow"):
            self.task.run()
        self.assertFalse(self.task.is_done("simulation", "day"))

    def test_skip_when_already_done(self):
        self.task.mark_done("simulation", "day")  # 标记本周期已完成。
        with patch.object(self.task, "_do_simulation_flow", side_effect=AssertionError("不应执行模拟室流程")), \
                patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "_do_tribe_tower_flow"):
            self.task.run()
        self.assertTrue(self.task.is_done("simulation", "day"))

    def test_success_marks_done(self):
        with self._patch_common(), \
                patch.object(self.task, "_do_simulation_flow") as flow_mock:
            self.task.run()
        flow_mock.assert_called_once()
        self.assertTrue(self.task.is_done("simulation", "day"))

    def test_failure_not_marked_done(self):
        with self._patch_common(), \
                patch.object(self.task, "try_step", side_effect=[True, True, False]), \
                patch.object(self.task, "_do_simulation_flow"):
            self.task.run()
        self.assertFalse(self.task.is_done("simulation", "day"))

    def test_run_executes_subflows_in_order(self):
        order = []  # 记录子流程执行顺序。
        with self._patch_common(), \
                patch.object(self.task, "_do_tribe_tower_flow", side_effect=lambda: order.append("tower")), \
                patch.object(self.task, "_do_simulation_flow", side_effect=lambda: order.append("simulation")):
            self.task.run()
        self.assertEqual(["tower", "simulation"], order)

    def test_flow_no_red_dot_closes(self):
        def find_one_only_update(name, *args, **kwargs):
            self.assertEqual("simulation_overclock_update", name,
                             "无红点时除更新弹窗外不应继续识别其他特征")  # 守卫：不得进入红点后的流程识别。
            return None  # 未弹出超频更新弹窗。

        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "find_red_dot", return_value=None), \
                patch.object(self.task, "find_one", side_effect=find_one_only_update), \
                patch.object(self.task, "click_box", side_effect=AssertionError("无红点时不应点击")):
            self.task._do_simulation_flow()
        clicked = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual(["ark_simulation_room", "simulation_close"], clicked)

    def test_flow_dismisses_overclock_update_then_continues(self):
        red_dot = Box(1387, 804, 36, 45, confidence=1, name="red_dot")  # 徽标红点。
        level5 = Box(1511, 406, 74, 84, confidence=1, name="simulation_level5")  # 已选中 Lv.5。
        switch_box = Box(1192, 1115, 79, 41, confidence=1, name="box_simulation_quick_complete")  # 开关纯坐标区域（已激活）。
        quick = Box(1380, 1208, 49, 47, confidence=1, name="simulation_quick_battle")  # 快速战斗按钮。
        update_popup = Box(700, 300, 1160, 800, confidence=1, name="simulation_overclock_update")  # 超频更新弹窗存在。
        find_map = {"simulation_overclock_update": update_popup, "simulation_level5": level5,
                    "simulation_quick_battle": quick}  # 按特征名返回识别结果。
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "find_red_dot", return_value=red_dot), \
                patch.object(self.task, "find_one", side_effect=lambda name, *a, **k: find_map.get(name)), \
                patch.object(self.task, "get_box_by_name", return_value=switch_box), \
                patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "dismiss_all_popups"):
            self.task._do_simulation_flow()
        clicked = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual(["ark_simulation_room", "simulation_overclock_update_close",
                          "simulation_quick_battle_finishi", "simulation_close"], clicked)  # 先关更新弹窗再走正常快速模拟流程。

    def test_flow_full_success_skips_level_and_toggle(self):
        red_dot = Box(1387, 804, 36, 45, confidence=1, name="red_dot")  # 徽标红点。
        level5 = Box(1511, 406, 74, 84, confidence=1, name="simulation_level5")  # 已选中 Lv.5。
        switch_box = Box(1192, 1115, 79, 41, confidence=1, name="box_simulation_quick_complete")  # 开关纯坐标区域（已激活）。
        quick = Box(1380, 1208, 49, 47, confidence=1, name="simulation_quick_battle")  # 快速战斗按钮。
        find_map = {"simulation_level5": level5,
                    "simulation_quick_battle": quick}  # 按特征名返回识别结果。
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "find_red_dot", return_value=red_dot), \
                patch.object(self.task, "find_one", side_effect=lambda name, *a, **k: find_map.get(name)), \
                patch.object(self.task, "get_box_by_name", return_value=switch_box), \
                patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock:
            self.task._do_simulation_flow()
        clicked = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual(["ark_simulation_room", "simulation_quick_battle_finishi", "simulation_close"], clicked)
        self.assertEqual([red_dot, "box_simulation_region_selector", quick],
                         [c.args[0] for c in click_box_mock.call_args_list])
        dismiss_mock.assert_called_once()

    def test_flow_selects_level5_and_activates_quick_complete(self):
        red_dot = Box(1387, 804, 36, 45, confidence=1, name="red_dot")  # 徽标红点。
        switch_box = Box(1192, 1115, 79, 41, confidence=1, name="box_simulation_quick_complete")  # 开关纯坐标区域。
        quick = Box(1380, 1208, 49, 47, confidence=1, name="simulation_quick_battle")  # 快速战斗按钮。
        find_map = {"simulation_level5": None,
                    "simulation_quick_battle": quick}  # Lv.5 未选、开关为灰白未激活态。
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "find_red_dot", return_value=red_dot), \
                patch.object(self.task, "find_one", side_effect=lambda name, *a, **k: find_map.get(name)), \
                patch.object(self.task, "get_box_by_name", return_value=switch_box), \
                patch.object(self.task, "is_feature_enabled", return_value=False), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "dismiss_all_popups"):
            self.task._do_simulation_flow()
        clicked = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual(["ark_simulation_room", "simulation_level5", "simulation_quick_battle_finishi",
                          "simulation_close"], clicked)
        self.assertEqual([red_dot, "box_simulation_region_selector", switch_box, quick],
                         [c.args[0] for c in click_box_mock.call_args_list])

    def test_flow_no_quick_battle_closes(self):
        red_dot = Box(1387, 804, 36, 45, confidence=1, name="red_dot")  # 徽标红点。
        level5 = Box(1511, 406, 74, 84, confidence=1, name="simulation_level5")  # 已选中 Lv.5。
        switch_box = Box(1192, 1115, 79, 41, confidence=1, name="box_simulation_quick_complete")  # 开关纯坐标区域（已激活）。
        find_map = {"simulation_level5": level5,
                    "simulation_quick_battle": None}  # 无快速战斗按钮。
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "find_red_dot", return_value=red_dot), \
                patch.object(self.task, "find_one", side_effect=lambda name, *a, **k: find_map.get(name)), \
                patch.object(self.task, "get_box_by_name", return_value=switch_box), \
                patch.object(self.task, "is_feature_enabled", return_value=True), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock:
            self.task._do_simulation_flow()
        clicked = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual(["ark_simulation_room", "simulation_close"], clicked)
        self.assertEqual([red_dot, "box_simulation_region_selector"],
                         [c.args[0] for c in click_box_mock.call_args_list])
        dismiss_mock.assert_not_called()

    def test_flow_switch_disabled_state_gets_clicked(self):
        """开关为灰白未激活态（colorfulness 低于阈值）时应被点击激活。"""
        red_dot = Box(1387, 804, 36, 45, confidence=1, name="red_dot")  # 徽标红点。
        level5 = Box(1511, 406, 74, 84, confidence=1, name="simulation_level5")  # 已选中 Lv.5。
        switch_box = Box(1192, 1115, 79, 41, confidence=1, name="box_simulation_quick_complete")  # 开关纯坐标区域。
        quick = Box(1380, 1208, 49, 47, confidence=1, name="simulation_quick_battle")  # 快速战斗按钮。
        find_map = {"simulation_level5": level5, "simulation_quick_battle": quick}
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "find_red_dot", return_value=red_dot), \
                patch.object(self.task, "find_one", side_effect=lambda name, *a, **k: find_map.get(name)), \
                patch.object(self.task, "get_box_by_name", return_value=switch_box), \
                patch.object(self.task, "is_feature_enabled", return_value=False) as enabled_mock, \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "dismiss_all_popups"):
            self.task._do_simulation_flow()
        enabled_mock.assert_called_once_with(switch_box)  # 判态入参应为开关区域。
        self.assertEqual([red_dot, "box_simulation_region_selector", switch_box, quick],
                         [c.args[0] for c in click_box_mock.call_args_list])  # 未激活开关应被点击。

    def test_flow_switch_box_missing_skips_toggle(self):
        """开关区域缺失（coco 特征异常）时不应点击，直接继续快速模拟。"""
        red_dot = Box(1387, 804, 36, 45, confidence=1, name="red_dot")  # 徽标红点。
        level5 = Box(1511, 406, 74, 84, confidence=1, name="simulation_level5")  # 已选中 Lv.5。
        quick = Box(1380, 1208, 49, 47, confidence=1, name="simulation_quick_battle")  # 快速战斗按钮。
        find_map = {"simulation_level5": level5, "simulation_quick_battle": quick}
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "find_red_dot", return_value=red_dot), \
                patch.object(self.task, "find_one", side_effect=lambda name, *a, **k: find_map.get(name)), \
                patch.object(self.task, "get_box_by_name", return_value=None), \
                patch.object(self.task, "is_feature_enabled",
                             side_effect=AssertionError("区域缺失时不应做判态")), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "dismiss_all_popups"):
            self.task._do_simulation_flow()
        self.assertEqual([red_dot, "box_simulation_region_selector", quick],
                         [c.args[0] for c in click_box_mock.call_args_list])  # 跳过开关直接快速模拟。

    def test_simulation_screen_registered(self):
        self.assertIn("simulation_room", self.task.screens)  # 模拟室界面已注册。
        self.assertEqual(["simulation_mark"], self.task.screens["simulation_room"]["features"])  # 以室徽特征判定。


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

        with patch.object(daily, "ensure_screen", return_value=True), \
                patch.object(daily, "run_task_by_class", side_effect=fake_run_task_by_class), \
                patch.object(daily, "get_task_by_class", return_value=ark), \
                patch.object(daily, "log_info") as log_mock:
            daily.run()
        notify_calls = [c for c in log_mock.call_args_list if c.kwargs.get("notify")]
        self.assertEqual(1, len(notify_calls))
        self.assertIn("极乐净土", notify_calls[0].args[0])
        self.assertIn("朝圣者", notify_calls[0].args[0])


class TestEnsureLobby(_DebugOffTestCase):
    """ensure_screen("lobby") 的零点击尾段：任务开头就位大厅（含冷启动引导）的回归。"""

    task_class = ArkTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'ArkTask')
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(self.task, "dismiss_all_popups", return_value=True))
        self.stack.enter_context(patch.object(self.task, "find_one", return_value=None))
        self.stack.enter_context(patch.object(self.task, "current_screen", return_value=None))
        self.stack.enter_context(patch.object(self.task, "is_screen", return_value=False))
        self.stack.enter_context(patch.object(self.task, "_recover_to_lobby", return_value=True))
        self.lobby_mock = self.stack.enter_context(
            patch.object(self.task, "wait_until_lobby_after_start", return_value=True))
        self.transition_mock = self.stack.enter_context(patch.object(self.task, "transition"))
        self.shot_mock = self.stack.enter_context(patch.object(self.task, "save_failure_screenshot"))
        self.addCleanup(self.stack.close)

    def test_already_on_lobby_returns_immediately(self):
        """快路径：已在大厅直接返回，不触发任何分流。"""
        with patch.object(self.task, "wait_screen", return_value=True):
            self.assertTrue(self.task.ensure_screen("lobby", raise_on_fail=False))
        self.lobby_mock.assert_not_called()
        self.transition_mock.assert_not_called()

    def test_zero_click_tail_confirms_after_cold_start(self):
        """零点击尾段：冷启动引导后就位成功 → 返回 True，且不发生任何导航点击。"""
        with patch.object(self.task, "wait_screen", side_effect=[False, False, True]):
            self.assertTrue(self.task.ensure_screen("lobby", raise_on_fail=False))
        self.lobby_mock.assert_called_once()
        self.transition_mock.assert_not_called()

    def test_tail_confirm_failure_returns_false_when_asked(self):
        """尾段确认失败且 raise_on_fail=False → 返回 False（任务开头优雅中止）。"""
        with patch.object(self.task, "wait_screen", return_value=False):
            self.assertFalse(self.task.ensure_screen("lobby", raise_on_fail=False))
        self.transition_mock.assert_not_called()

    def test_tail_confirm_failure_raises_by_default(self):
        """尾段确认失败默认抛 WaitFailedException（供 try_step 恢复）。"""
        with patch.object(self.task, "wait_screen", return_value=False):
            with self.assertRaises(WaitFailedException):
                self.task.ensure_screen("lobby")


class TestNavToArk(_DebugOffTestCase):
    """_nav_to_ark 分支回归：实机事故（2026-08-25 02:19 日志）——企业塔收尾返回方舟的过场动画期间
    单帧 is_screen("ark") 失败，且方舟页没有 common_back/common_home 按钮，被误判为冷启动，
    卡在 wait_until_lobby_after_start 空等大厅 60 秒以上（游戏实际已停在方舟页）。"""

    task_class = ArkTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'ArkTask')

    def _patch_common(self, wait_screen_side_effect, find_one_box=None, current_screen=None,
                      recover=True, on_login=False):
        """统一 mock 导航各判定/动作原语：wait_screen 用 side_effect 序列驱动流程分支；
        on_login=True 时正向命中 login_page 锚点（其余界面名一律未命中）。"""
        stack = ExitStack()
        stack.enter_context(patch.object(self.task, "wait_screen",
                                         side_effect=wait_screen_side_effect))
        stack.enter_context(patch.object(self.task, "dismiss_all_popups", return_value=True))
        stack.enter_context(patch.object(self.task, "find_one", return_value=find_one_box))
        stack.enter_context(patch.object(self.task, "current_screen",
                                         return_value=current_screen))
        stack.enter_context(patch.object(self.task, "is_screen",
                                         side_effect=lambda name: name == "login_page" and on_login))
        recover_mock = stack.enter_context(patch.object(self.task, "_recover_to_lobby",
                                                        return_value=recover))
        lobby_mock = stack.enter_context(
            patch.object(self.task, "wait_until_lobby_after_start", return_value=True))
        transition_mock = stack.enter_context(patch.object(self.task, "transition"))
        return stack, recover_mock, lobby_mock, transition_mock

    def test_animation_tolerance_ark_hit_after_first_wait(self):
        """过场动画：首次轮询即命中方舟 → 不清弹窗、不导航，直接返回。"""
        with patch.object(self.task, "wait_screen", return_value=True) as wait_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "transition") as transition_mock:
            self.task._nav_to_ark()
        wait_mock.assert_called_once_with("ark", time_out=5)
        dismiss_mock.assert_not_called()
        transition_mock.assert_not_called()

    def test_animation_tolerance_ark_hit_after_popup_dismiss(self):
        """首次未命中 → 清弹窗后第二次轮询命中 → 直接返回，不触发恢复/冷启动分支。"""
        stack, recover_mock, lobby_mock, transition_mock = self._patch_common([False, True])
        with stack:
            self.task._nav_to_ark()
        recover_mock.assert_not_called()
        lobby_mock.assert_not_called()
        transition_mock.assert_not_called()

    def test_in_app_screen_without_back_home_is_not_cold_start(self):
        """回归本体：无 back/home 按钮但命中其它已注册应用内界面 → 走 _recover_to_lobby，绝不进冷启动等大厅。"""
        stack, recover_mock, lobby_mock, transition_mock = self._patch_common(
            [False, False], find_one_box=None, current_screen="simulation_room")
        with stack:
            self.task._nav_to_ark()
        recover_mock.assert_called_once()
        lobby_mock.assert_not_called()
        transition_mock.assert_called_once_with("ark", click_feature="ark",
                                                wait_confirm=10, after_sleep=1)

    def test_true_cold_start_goes_to_lobby_wait(self):
        """真冷启动（无按钮且无任何已注册界面命中）才进入 wait_until_lobby_after_start。"""
        stack, recover_mock, lobby_mock, transition_mock = self._patch_common(
            [False, False], find_one_box=None, current_screen=None)
        with stack:
            self.task._nav_to_ark()
        recover_mock.assert_not_called()
        lobby_mock.assert_called_once()
        transition_mock.assert_called_once_with("ark", click_feature="ark",
                                                wait_confirm=10, after_sleep=1)

    def test_login_page_anchor_skips_recovery(self):
        """登录页正向锚点：命中 login_page 即明确冷启动入口，即使有按钮证据也跳过恢复，
        直接进入大厅引导流程。"""
        stack, recover_mock, lobby_mock, transition_mock = self._patch_common(
            [False, False], find_one_box=Box(0, 0, 10, 10), current_screen="login_page",
            on_login=True)
        with stack:
            self.task._nav_to_ark()
        recover_mock.assert_not_called()
        lobby_mock.assert_called_once()
        transition_mock.assert_called_once_with("ark", click_feature="ark",
                                                wait_confirm=10, after_sleep=1)

    def test_cold_start_lobby_wait_failure_raises(self):
        """冷启动等大厅失败 → 抛 WaitFailedException 交给 try_step 恢复重试。"""
        stack, recover_mock, lobby_mock, _ = self._patch_common(
            [False, False], find_one_box=None, current_screen=None)
        lobby_mock.return_value = False
        with stack:
            with self.assertRaises(WaitFailedException):
                self.task._nav_to_ark()

    def test_back_or_home_button_takes_recover_path(self):
        """存在返回/主页按钮 → 恢复回大厅路径（既有行为保持），不进冷启动分支。"""
        stack, recover_mock, lobby_mock, transition_mock = self._patch_common(
            [False, False], find_one_box=Box(0, 0, 10, 10), current_screen=None)
        with stack:
            self.task._nav_to_ark()
        recover_mock.assert_called_once()
        lobby_mock.assert_not_called()
        transition_mock.assert_called_once()


class TestArkTaskRookieArena(_DebugOffTestCase):
    """新人竞技场子流程测试：覆盖成功/跳过/失败/已完成跳过及对手选择策略各分支。"""

    task_class = ArkTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'ArkTask')
        self.task.config["企业塔"] = False  # 关闭企业塔子流程，隔离新人竞技场测试。
        self.task.config["关闭自动爬塔"] = self.task.default_config["关闭自动爬塔"]
        self.task.config["模拟室"] = False  # 关闭模拟室子流程，隔离新人竞技场测试。
        self.task.config["新人竞技场"] = True  # 新人竞技场子流程测试统一开启。
        self.task.config["对手选择策略"] = self.task.default_config["对手选择策略"]
        self.task.config["特殊竞技场"] = False  # 关闭特殊竞技场子流程，隔离新人竞技场测试。
        self.task.clear_done("tribe_tower")
        self.task.clear_done("simulation")
        self.task.clear_done("rookie_arena")
        self.task.clear_done("special_arena")
        self.task.failed_towers = []

    def test_skip_when_disabled(self):
        self.task.config["新人竞技场"] = False  # 用户未启用新人竞技场。
        with patch.object(self.task, "_do_rookie_arena_flow", side_effect=AssertionError("不应执行新人竞技场流程")), \
                patch.object(self.task, "_nav_to_ark"):
            self.task.run()
        self.assertFalse(self.task.is_done("rookie_arena", "day"))

    def test_skip_when_already_done(self):
        self.task.mark_done("rookie_arena", "day")  # 标记本周期已完成。
        with patch.object(self.task, "_do_rookie_arena_flow", side_effect=AssertionError("不应执行新人竞技场流程")), \
                patch.object(self.task, "_nav_to_ark"):
            self.task.run()
        self.assertTrue(self.task.is_done("rookie_arena", "day"))

    def test_success_marks_done(self):
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "_do_rookie_arena_flow") as flow_mock:
            self.task.run()
        flow_mock.assert_called_once()
        self.assertTrue(self.task.is_done("rookie_arena", "day"))

    def test_failure_not_marked_done(self):
        with patch.object(self.task, "try_step", side_effect=[True, False]):
            self.task.run()
        self.assertFalse(self.task.is_done("rookie_arena", "day"))

    def _common_encounter(self):
        return Box(1800, 600, 120, 40, confidence=1, name="box_rookie_arena_o1_free_encounter")  # 1号对手免费挑战区域框（纯坐标区域）。

    def _flow_patches(self, encounter_side_effect, enabled_side_effect, battle_result):
        """构造 _do_rookie_arena_flow 的公共补丁栈：导航/战斗全部 mock，按 side_effect 驱动分支。"""
        toggle = Box(700, 1150, 80, 40, confidence=1, name="box_rookie_arena_quick_battle_feature")  # 快速战斗开关区域。
        settle = Box(1280, 1200, 100, 50, confidence=1, name="battle_finish_esc")  # 结算确认按钮框。
        encounters = iter(encounter_side_effect)  # 每次循环取下一个 1 号对手区域结果。

        def get_box(name, *args, **kwargs):  # 按名分发：1 号对手区域按序列返回，其余（快速战斗开关）恒返回开关区域。
            if name == "box_rookie_arena_o1_free_encounter":
                return next(encounters)
            return toggle

        stack = ExitStack()
        stack.enter_context(patch.object(self.task, "_nav_to_arena"))
        transition_mock = stack.enter_context(patch.object(self.task, "transition"))
        enabled_mock = stack.enter_context(patch.object(self.task, "is_feature_enabled", side_effect=enabled_side_effect))
        click_feature_mock = stack.enter_context(patch.object(self.task, "wait_click_feature"))
        stack.enter_context(patch.object(self.task, "wait_feature", return_value=Box(900, 200, 600, 400, confidence=1, name="rookie_arena_battle_modal")))
        stack.enter_context(patch.object(self.task, "get_box_by_name", side_effect=get_box))
        click_box_mock = stack.enter_context(patch.object(self.task, "click_box"))
        stack.enter_context(patch.object(self.task, "wait_battle_finish", return_value=(battle_result, settle)))
        stack.enter_context(patch.object(self.task, "assert_screen", return_value=True))
        return stack, transition_mock, enabled_mock, click_feature_mock, click_box_mock, toggle, settle

    def test_flow_success_strategy_off(self):
        """策略关闭：固定挑战最下面对手；开关为灰白态先激活再进入战斗；胜利后第二轮免费次数用尽收尾。"""
        self.task.config["对手选择策略"] = False  # 固定选择最下面的对手。
        encounter = self._common_encounter()
        stack, transition_mock, enabled_mock, click_feature_mock, click_box_mock, toggle, settle = \
            self._flow_patches([encounter, encounter], [True, False, False], "success")
        with stack:
            self.task._do_rookie_arena_flow()
        transition_mock.assert_called_once_with("rookie_arena", click_feature="rookie_arena",
                                                wait_confirm=10, after_sleep=3)  # 确认了进入新人竞技场界面。
        clicked = [c.args[0] for c in click_feature_mock.call_args_list]
        self.assertEqual(["common_back", "common_back"], clicked)  # 模板特征点击仅剩两次返回。
        self.assertEqual(["box_rookie_arena_o3_free_encounter", toggle, "box_rookie_arena_quick_battle", settle],
                         [c.args[0] for c in click_box_mock.call_args_list])  # 点3号对手→激活开关→进入战斗→点结算确认。
        self.assertEqual(3, enabled_mock.call_count)  # 免费可用→开关判态→第二轮免费已用尽。

    def test_flow_toggle_enabled_skips_activation(self):
        """快速战斗开关已是激活态时不重复点击。"""
        self.task.config["对手选择策略"] = False
        encounter = self._common_encounter()
        stack, _, _, _, click_box_mock, _, settle = \
            self._flow_patches([encounter, encounter], [True, True, False], "success")
        with stack:
            self.task._do_rookie_arena_flow()
        self.assertEqual(["box_rookie_arena_o3_free_encounter", "box_rookie_arena_quick_battle", settle],
                         [c.args[0] for c in click_box_mock.call_args_list])  # 开关已激活则点对手后直接进入战斗。

    def test_flow_no_free_encounter_backs_out(self):
        """免费次数已用尽：不挑战，直接逐级返回方舟。"""
        encounter = self._common_encounter()
        stack, transition_mock, enabled_mock, click_feature_mock, click_box_mock, _, _ = \
            self._flow_patches([None], [False], "success")  # 免费挑战区域缺失（None）直接进入用尽分支。
        with stack:
            self.task._do_rookie_arena_flow()
        self.assertEqual(0, enabled_mock.call_count)  # 区域缺失时不再判态，直接视为用尽。
        clicked = [c.args[0] for c in click_feature_mock.call_args_list]
        self.assertEqual(["common_back", "common_back"], clicked)  # 只发生两次返回点击。
        click_box_mock.assert_not_called()  # 未发生任何战斗点击。

    def test_flow_battle_timeout_raises_for_retry(self):
        """战斗等待超时抛 WaitFailedException，交由 try_step 恢复重试。"""
        encounter = self._common_encounter()
        self.task.config["对手选择策略"] = False
        stack, _, _, _, _, _, _ = self._flow_patches([encounter], [True, True], None)
        with stack:
            with self.assertRaises(WaitFailedException):
                self.task._do_rookie_arena_flow()

    def _cp_boxes(self, name):
        """get_box_by_name side_effect：按特征名返回带名字的占位框。"""
        return Box(0, 0, 10, 10, confidence=1, name=name)

    def _ocr_texts(self, *args, **kwargs):
        """ocr side_effect：己方战力读 100000，对手战力按 box 名尾段映射到 _opponent_values。"""
        box = kwargs.get("box")
        name = getattr(box, "name", "") or ""
        if "player" in name:
            return [Box(0, 0, 10, 10, confidence=1, name="100000")]
        tail = name.split("_")[-2] if name.endswith("_cp") else ""  # box_rookie_arena_o1_cp -> "o1"。
        return [Box(0, 0, 10, 10, confidence=1, name=str(self._opponent_values.get(tail, 90000)))]

    def test_pick_opponent_strategy_off(self):
        """策略关闭：不做 OCR，直接固定选最下面对手。"""
        self.task.config["对手选择策略"] = False
        with patch.object(self.task, "ocr", side_effect=AssertionError("策略关闭时不应 OCR")):
            self.assertEqual("box_rookie_arena_o3_free_encounter", self.task._rookie_arena_pick_opponent())

    def test_pick_opponent_picks_first_beatable(self):
        """策略开启：自上而下选第一个满足 己方*0.846>对手 的对手（84600>90000 不成立，84600>80000 命中o2）。"""
        self._opponent_values = {"o1": 90000, "o2": 80000, "o3": 200000}
        with patch.object(self.task, "get_box_by_name", side_effect=self._cp_boxes), \
                patch.object(self.task, "ocr", side_effect=self._ocr_texts) as ocr_mock:
            self.assertEqual("box_rookie_arena_o2_free_encounter", self.task._rookie_arena_pick_opponent())
        self.assertEqual(3, ocr_mock.call_count)  # 己方 + o1 + o2（命中即停，不读 o3）。

    def test_pick_opponent_threshold_strictly_greater(self):
        """阈值严格大于：84600 == 84600 不算压制，继续向下找。"""
        self._opponent_values = {"o1": 84600, "o2": 84599, "o3": 999999}
        with patch.object(self.task, "get_box_by_name", side_effect=self._cp_boxes), \
                patch.object(self.task, "ocr", side_effect=self._ocr_texts):
            self.assertEqual("box_rookie_arena_o2_free_encounter", self.task._rookie_arena_pick_opponent())

    def test_pick_opponent_refresh_until_limit_returns_none(self):
        """始终无压制对手：刷新10次后返回 None 结束子流程。"""
        self._opponent_values = {"o1": 90000, "o2": 90000, "o3": 90000}  # 全部强于 84600。
        with patch.object(self.task, "get_box_by_name", side_effect=self._cp_boxes), \
                patch.object(self.task, "ocr", side_effect=self._ocr_texts), \
                patch.object(self.task, "wait_click_feature") as refresh_mock:
            self.assertIsNone(self.task._rookie_arena_pick_opponent())
        self.assertEqual(10, refresh_mock.call_count)  # 刷新恰好 10 次。
        self.assertEqual("rookie_arena_refresh", refresh_mock.call_args_list[0].args[0])

    def test_pick_opponent_player_cp_unreadable_fallback(self):
        """己方战力读取失败：保守回退固定挑战最下面对手。"""
        with patch.object(self.task, "get_box_by_name", side_effect=self._cp_boxes), \
                patch.object(self.task, "ocr", return_value=[Box(0, 0, 10, 10, confidence=1, name="")]):
            self.assertEqual("box_rookie_arena_o3_free_encounter", self.task._rookie_arena_pick_opponent())

    def test_pick_opponent_region_missing_fallback(self):
        """战力标注区域缺失（coco 特征异常）时同样回退固定最下面对手。"""
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")):
            self.assertEqual("box_rookie_arena_o3_free_encounter", self.task._rookie_arena_pick_opponent())


class TestArkTaskSpecialArena(_DebugOffTestCase):
    """特殊竞技场子流程测试：覆盖成功/跳过/失败/已完成跳过等主要分支。"""

    task_class = ArkTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'ArkTask')
        self.task.config["企业塔"] = False  # 关闭企业塔子流程，隔离特殊竞技场测试。
        self.task.config["关闭自动爬塔"] = self.task.default_config["关闭自动爬塔"]
        self.task.config["模拟室"] = False  # 关闭模拟室子流程，隔离特殊竞技场测试。
        self.task.config["新人竞技场"] = False  # 关闭新人竞技场子流程，隔离特殊竞技场测试。
        self.task.config["对手选择策略"] = self.task.default_config["对手选择策略"]
        self.task.config["特殊竞技场"] = True  # 特殊竞技场子流程测试统一开启。
        self.task.clear_done("tribe_tower")
        self.task.clear_done("simulation")
        self.task.clear_done("rookie_arena")
        self.task.clear_done("special_arena")
        self.task.failed_towers = []

    def test_skip_when_disabled(self):
        self.task.config["特殊竞技场"] = False  # 用户未启用特殊竞技场。
        with patch.object(self.task, "_do_special_arena_flow", side_effect=AssertionError("不应执行特殊竞技场流程")), \
                patch.object(self.task, "_nav_to_ark"):
            self.task.run()
        self.assertFalse(self.task.is_done("special_arena", "day"))

    def test_skip_when_already_done(self):
        self.task.mark_done("special_arena", "day")  # 标记本周期已完成。
        with patch.object(self.task, "_do_special_arena_flow", side_effect=AssertionError("不应执行特殊竞技场流程")), \
                patch.object(self.task, "_nav_to_ark"):
            self.task.run()
        self.assertTrue(self.task.is_done("special_arena", "day"))

    def test_success_marks_done(self):
        with patch.object(self.task, "_nav_to_ark"), \
                patch.object(self.task, "_do_special_arena_flow") as flow_mock:
            self.task.run()
        flow_mock.assert_called_once()
        self.assertTrue(self.task.is_done("special_arena", "day"))

    def test_failure_not_marked_done(self):
        with patch.object(self.task, "try_step", side_effect=[True, False]):
            self.task.run()
        self.assertFalse(self.task.is_done("special_arena", "day"))

    def test_flow_claims_reward_and_backs_out(self):
        """成功分支：进入特殊竞技场→点累计奖励区域→点领取→清弹窗→依次返回竞技场与方舟。"""
        with patch.object(self.task, "_nav_to_arena"), \
                patch.object(self.task, "transition") as transition_mock, \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "wait_click_feature") as click_feature_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "assert_screen", return_value=True) as assert_mock:
            self.task._do_special_arena_flow()
        transition_mock.assert_called_once_with("special_arena", click_feature="special_arena",
                                                wait_confirm=10, after_sleep=3)  # 确认了进入特殊竞技场界面。
        self.assertEqual(["box_special_arena_reward"], [c.args[0] for c in click_box_mock.call_args_list])  # 点击累计奖励区域。
        clicked = [c.args[0] for c in click_feature_mock.call_args_list]
        self.assertEqual(["special_arena_reward_claim", "common_back", "common_back"], clicked)  # 领取后逐级返回。
        dismiss_mock.assert_called_once()  # 领取后清理一次遮罩弹窗。
        self.assertEqual(["arena", "ark"], [c.args[0] for c in assert_mock.call_args_list])  # 依次断言回到竞技场与方舟界面。


if __name__ == '__main__':
    unittest.main()
