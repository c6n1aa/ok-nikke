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

    def test_success_clicks_esc_and_returns_success(self):
        reward_box = Box(100, 100, 50, 50, confidence=1, name="battle_finish_reward")
        esc_box = Box(200, 200, 60, 60, confidence=1, name="battle_finish_esc")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one", side_effect=[reward_box, esc_box]) as find_mock, \
                patch.object(self.task, "click_box") as click_mock:
            result = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertEqual(2, find_mock.call_count)
        click_mock.assert_called_once_with(esc_box, after_sleep=1)

    def test_failed_clicks_back_and_returns_failed(self):
        failed_box = Box(300, 300, 70, 70, confidence=1, name="battle_finish_failed")
        failed_back_box = Box(400, 400, 80, 80, confidence=1, name="battle_finish_failed_back")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one",
                            side_effect=[None, None, failed_box, failed_back_box]) as find_mock, \
                patch.object(self.task, "click_box") as click_mock:
            result = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("failed", result)
        self.assertEqual(4, find_mock.call_count)
        click_mock.assert_called_once_with(failed_back_box, after_sleep=1)

    def test_success_on_later_iteration(self):
        reward_box = Box(100, 100, 50, 50, confidence=1, name="battle_finish_reward")
        esc_box = Box(200, 200, 60, 60, confidence=1, name="battle_finish_esc")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one",
                            side_effect=[None, None, None, None, reward_box, esc_box]) as find_mock, \
                patch.object(self.task, "click_box") as click_mock:
            result = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertEqual(6, find_mock.call_count)  # 第一轮全未命中，第二轮命中。
        click_mock.assert_called_once_with(esc_box, after_sleep=1)

    def test_timeout_returns_none_and_saves_screenshot(self):
        with patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "save_failure_screenshot") as shot_mock:
            result = self.task.wait_battle_finish(time_out=0)
        self.assertIsNone(result)
        shot_mock.assert_called_once_with("wait_battle_finish")


if __name__ == '__main__':
    unittest.main()