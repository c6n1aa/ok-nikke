import os
import unittest
from unittest.mock import patch

from src.config import config
from src.tasks.HarvestTask import HarvestTask
from src.tasks.OutpostDefenseTask import OutpostDefenseTask
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


class TestHarvestTask(_DebugOffTestCase):
    task_class = HarvestTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'HarvestTask')
        self.task.clear_done("harvest")

    def test_config_defaults(self):
        self.assertTrue(self.task.default_config["收获友情点"])
        self.assertTrue(self.task.default_config["收取邮箱"])

    def test_skip_when_already_done(self):
        self.task.mark_done("harvest", "day")
        with patch.object(self.task, "_collect_friend", side_effect=AssertionError("不应执行友情点流程")):
            with patch.object(self.task, "_collect_mailbox", side_effect=AssertionError("不应执行邮箱流程")):
                self.task.run()
        self.assertTrue(self.task.is_done("harvest", "day"))

    def test_runs_sub_flows_when_not_done(self):
        with patch.object(self.task, "wait_for_lobby"), \
                patch.object(self.task, "_collect_friend") as friend_mock, \
                patch.object(self.task, "_collect_mailbox") as mailbox_mock:
            self.task.run()
        friend_mock.assert_called_once()
        mailbox_mock.assert_called_once()
        self.assertTrue(self.task.is_done("harvest", "day"))

    def test_abort_when_lobby_not_found(self):
        from ok.task.exceptions import WaitFailedException
        self.task.config["收获友情点"] = True
        self.task.config["收取邮箱"] = True
        with patch.object(self.task, "wait_for_lobby", side_effect=WaitFailedException("lobby not found")), \
                patch.object(self.task, "_collect_friend", side_effect=AssertionError("不应执行友情点流程")), \
                patch.object(self.task, "_collect_mailbox", side_effect=AssertionError("不应执行邮箱流程")):
            with self.assertRaises(WaitFailedException):
                self.task.run()
        self.assertFalse(self.task.is_done("harvest", "day"))

    def test_debug_mode_skips_done_state(self):
        with patch.object(self.task, '_in_debug', return_value=True):
            self.task.mark_done("harvest", "day")
            self.assertFalse(self.task.is_done("harvest", "day"))


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
        with patch.object(self.task, "wait_for_lobby"), \
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
        with patch.object(self.task, "wait_for_lobby"), \
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
        with patch.object(self.task, "wait_for_lobby", side_effect=WaitFailedException("lobby not found")), \
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
        with patch.object(self.task, 'get_box_by_name', return_value=None):
            with self.assertRaises(WaitFailedException):
                self.task._click_outpost_defense(time_out=1)


if __name__ == '__main__':
    unittest.main()
