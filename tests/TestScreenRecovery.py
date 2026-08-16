import unittest
from unittest.mock import patch

from ok.feature.Box import Box
from ok.task.exceptions import WaitFailedException
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.HarvestTask import HarvestTask


class TestScreenRecovery(TaskTestCase):
    task_class = HarvestTask

    config = config

    def setUp(self):
        self.set_image('tests/images/main.png')
        # 每个用例从干净的界面注册表开始，避免共享实例上残留其它用例注册的界面。
        self.task.screens = {}
        self.task.register_screen("lobby", features=["ark"])

    def test_is_screen_lobby_when_ark_present(self):
        self.assertTrue(self.task.is_screen("lobby"))

    def test_current_screen_returns_lobby(self):
        self.assertEqual("lobby", self.task.current_screen())

    def test_current_screen_none_when_no_screen_matches(self):
        # 只注册一个当前帧上不存在的界面，验证未命中时返回 None。
        self.task.screens = {}
        self.task.register_screen("好友页", features=["friend_gift"])
        self.assertIsNone(self.task.current_screen())

    def test_register_screen_features_negative(self):
        self.task.register_screen("好友页", features=["friend_gift"])
        self.assertFalse(self.task.is_screen("好友页"))

    def test_unregistered_screen_warns_and_returns_false(self):
        with patch.object(self.task, "log_warning") as warn_mock:
            self.assertFalse(self.task.is_screen("不存在"))
        warn_mock.assert_called_once()

    def test_wait_screen_raises_for_unregistered(self):
        with self.assertRaises(ValueError):
            self.task.wait_screen("未注册", time_out=1)

    def test_screen_ocr_keywords_with_region(self):
        self.task.register_screen("大厅ocr", keywords=["方舟"], ocr_box=[0.5, 0.5, 1, 1])
        self.assertTrue(self.task.is_screen("大厅ocr"))

    def test_assert_screen_success(self):
        self.task.assert_screen("lobby", time_out=5)

    def test_assert_screen_raises_when_not_present(self):
        with patch.object(self.task, "wait_screen", return_value=None):
            with self.assertRaises(WaitFailedException):
                self.task.assert_screen("lobby", time_out=1)

    def test_try_step_success(self):
        calls = []

        def step():
            calls.append(1)

        with patch.object(self.task, "save_failure_screenshot") as shot_mock:
            result = self.task.try_step(step, name="成功步骤")
        self.assertTrue(result)
        self.assertEqual(1, len(calls))
        shot_mock.assert_not_called()

    def test_try_step_retries_then_raises(self):
        calls = []

        def step():
            calls.append(1)
            raise WaitFailedException("找不到特征")

        with patch.object(self.task, "_recover_to_lobby", return_value=True) as recover_mock, \
                patch.object(self.task, "save_failure_screenshot") as shot_mock, \
                patch.object(self.task, "sleep"):
            with self.assertRaises(WaitFailedException):
                self.task.try_step(step, name="失败步骤", retries=2)
        self.assertEqual(3, len(calls))
        self.assertEqual(2, recover_mock.call_count)
        self.assertEqual(3, shot_mock.call_count)

    def test_try_step_retries_then_success(self):
        calls = []

        def step():
            calls.append(1)
            if len(calls) < 3:
                raise WaitFailedException("暂时失败")

        with patch.object(self.task, "_recover_to_lobby", return_value=True) as recover_mock, \
                patch.object(self.task, "save_failure_screenshot"):
            result = self.task.try_step(step, name="恢复成功", retries=2)
        self.assertTrue(result)
        self.assertEqual(3, len(calls))
        self.assertEqual(2, recover_mock.call_count)

    def test_try_step_skip_on_fail(self):
        def step():
            raise WaitFailedException("失败")

        with patch.object(self.task, "_recover_to_lobby", return_value=True), \
                patch.object(self.task, "save_failure_screenshot"), \
                patch.object(self.task, "sleep"):
            result = self.task.try_step(step, name="跳过步骤", retries=1, raise_on_fail=False)
        self.assertFalse(result)

    def test_try_step_stops_when_recovery_fails(self):
        calls = []

        def step():
            calls.append(1)
            raise WaitFailedException("失败")

        with patch.object(self.task, "_recover_to_lobby", return_value=False) as recover_mock, \
                patch.object(self.task, "save_failure_screenshot"), \
                patch.object(self.task, "sleep"):
            with self.assertRaises(WaitFailedException):
                self.task.try_step(step, name="恢复失败步骤", retries=2)
        self.assertEqual(1, len(calls))
        self.assertEqual(1, recover_mock.call_count)

    def test_recover_to_lobby_clicks_home_feature(self):
        fake_home = Box(100, 100, 50, 50, confidence=1, name="common_home")
        with patch.object(self.task, "next_frame"), \
                patch.object(self.task, "close_overlay", return_value=False), \
                patch.object(self.task, "is_screen", return_value=False), \
                patch.object(self.task, "feature_exists", return_value=True), \
                patch.object(self.task, "find_one", return_value=fake_home) as find_mock, \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_for_lobby", return_value=True) as lobby_mock:
            result = self.task._recover_to_lobby()
        self.assertTrue(result)
        find_mock.assert_called_once_with("common_home")
        click_mock.assert_called_once()
        lobby_mock.assert_called_once_with(time_out=30, raise_if_not_found=False)

    def test_recover_to_lobby_skips_when_already_lobby(self):
        with patch.object(self.task, "next_frame"), \
                patch.object(self.task, "close_overlay", return_value=False), \
                patch.object(self.task, "is_screen", return_value=True), \
                patch.object(self.task, "feature_exists") as fe_mock, \
                patch.object(self.task, "wait_for_lobby") as lobby_mock:
            result = self.task._recover_to_lobby()
        self.assertTrue(result)
        fe_mock.assert_not_called()
        lobby_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()