import unittest
from unittest.mock import patch

from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.HarvestTask import HarvestTask


class TestBattleWait(TaskTestCase):
    task_class = HarvestTask

    config = config

    def setUp(self):
        self.set_image('tests/images/main.png')
        self.task.screens = {}

    def test_success_returns_outcome_and_esc_box_without_click(self):
        reward_box = Box(100, 100, 50, 50, confidence=1, name="battle_finish_reward")
        esc_box = Box(200, 200, 60, 60, confidence=1, name="battle_finish_esc")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one", side_effect=[reward_box, esc_box]) as find_mock, \
                patch.object(self.task, "click_box", side_effect=AssertionError("检测阶段不应点击")):
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertIs(esc_box, box)
        self.assertEqual(2, find_mock.call_count)

    def test_failed_returns_outcome_and_back_box_without_click(self):
        failed_box = Box(300, 300, 70, 70, confidence=1, name="battle_finish_failed")
        failed_back_box = Box(400, 400, 80, 80, confidence=1, name="battle_finish_failed_back")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one",
                            side_effect=[None, None, failed_box, failed_back_box]) as find_mock, \
                patch.object(self.task, "click_box", side_effect=AssertionError("检测阶段不应点击")):
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("failed", result)
        self.assertIs(failed_back_box, box)
        self.assertEqual(4, find_mock.call_count)

    def test_success_on_later_iteration(self):
        reward_box = Box(100, 100, 50, 50, confidence=1, name="battle_finish_reward")
        esc_box = Box(200, 200, 60, 60, confidence=1, name="battle_finish_esc")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one",
                            side_effect=[None, None, None, None, reward_box, esc_box]) as find_mock:
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertIs(esc_box, box)
        self.assertEqual(6, find_mock.call_count)  # 第一轮全未命中，第二轮命中。

    def test_timeout_returns_none_and_saves_screenshot(self):
        with patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "save_failure_screenshot") as shot_mock:
            result, box = self.task.wait_battle_finish(time_out=0)
        self.assertIsNone(result)
        self.assertIsNone(box)
        shot_mock.assert_called_once_with("wait_battle_finish")


if __name__ == '__main__':
    unittest.main()