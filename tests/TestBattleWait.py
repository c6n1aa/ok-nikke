import unittest
from unittest.mock import patch

from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
import src.tasks.NikkeBaseTask as nbt
from src.tasks.HarvestTask import HarvestTask


class TestBattleWait(TaskTestCase):
    task_class = HarvestTask

    config = config

    def setUp(self):
        self.set_image('tests/images/main.png')
        self.task.screens = {}

    def test_success_returns_outcome_and_esc_box_without_click(self):
        esc_box = Box(200, 200, 60, 60, confidence=1, name="battle_finish_esc")
        stable_box = Box(200, 210, 60, 60, confidence=1, name="battle_finish_esc")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one", side_effect=[esc_box, stable_box]) as find_mock, \
                patch.object(self.task, "click_box", side_effect=AssertionError("检测阶段不应点击")):
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertIs(stable_box, box)  # 返回的是结算动画收尾后重新定位的按钮框。
        self.assertEqual(2, find_mock.call_count)  # 胜利只依赖 esc 单特征：初检 + 稳定化复识别各一次。

    def test_failed_returns_outcome_and_back_box_without_click(self):
        failed_box = Box(300, 300, 70, 70, confidence=1, name="battle_finish_failed")
        failed_back_box = Box(400, 400, 80, 80, confidence=1, name="battle_finish_failed_back")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one",
                             side_effect=[None, None, None, None, failed_box, failed_back_box,
                                          failed_box, failed_back_box]) as find_mock, \
                patch.object(self.task, "click_box", side_effect=AssertionError("检测阶段不应点击")):
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("failed", result)
        self.assertIs(failed_back_box, box)  # 稳定化后重新定位到的返回按钮框。
        self.assertEqual(8, find_mock.call_count)  # 第一轮全未命中，第二轮失败双特征命中，稳定化复核再查一轮双特征。

    def test_success_on_later_iteration(self):
        esc_box = Box(100, 100, 50, 50, confidence=1, name="battle_finish_esc")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one",
                             side_effect=[None, None, None, esc_box, esc_box]) as find_mock:
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertIs(esc_box, box)
        self.assertEqual(5, find_mock.call_count)  # 第一轮 esc+失败双特征全未命中，第二轮 esc 命中，稳定化复识别一次。

    def test_timeout_returns_none_and_saves_screenshot(self):
        with patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "save_failure_screenshot") as shot_mock:
            result, box = self.task.wait_battle_finish(time_out=0)
        self.assertIsNone(result)
        self.assertIsNone(box)
        shot_mock.assert_called_once_with("wait_battle_finish")

    def test_interrupt_dialog_raises_fast(self):
        # 中断哨兵：第 2 轮轮询命中断线弹窗特征 → 快速抛 InterruptedByDialogException 并保存现场，而非空转等满超时。
        interrupt_box = Box(500, 300, 200, 80, confidence=1, name="disconnect_mark")

        def fake_next_frame():
            self.task._screen_cache.clear()  # 模拟帧推进：与基类覆写的失效语义一致。
            return None
        with patch.object(nbt, "INTERRUPTS", {"screens": [], "features": ["disconnect_mark"]}), \
                patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame", side_effect=fake_next_frame), \
                patch.object(self.task, "find_one",
                             side_effect=[None, None, None, None, interrupt_box]), \
                patch.object(self.task, "save_failure_screenshot") as shot_mock:
            with self.assertRaises(nbt.InterruptedByDialogException):
                self.task.wait_battle_finish(time_out=240)
        shot_mock.assert_called_once_with("interrupt")  # 第 2 轮即命中，远小于 240 秒超时。

    def test_interrupt_sentinel_inactive_by_default(self):
        # 空清单 = 哨兵未激活：不产生任何额外特征查找，行为与现状逐位一致。
        esc_box = Box(200, 200, 60, 60, confidence=1, name="battle_finish_esc")
        stable_box = Box(200, 210, 60, 60, confidence=1, name="battle_finish_esc")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "find_one", side_effect=[esc_box, stable_box]) as find_mock:
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertEqual(2, find_mock.call_count)  # 无中断路径的额外调用。

    def test_try_step_catches_interrupt_and_recovers(self):
        # try_step 兼容：InterruptedByDialogException 按 WaitFailedException 捕获，恢复后重跑成功。
        calls = []

        def step():
            calls.append(1)
            if len(calls) == 1:
                raise nbt.InterruptedByDialogException("long wait interrupted by dialog")
            return True

        with patch.object(self.task, "_recover_to_lobby", return_value=True) as recover_mock, \
                patch.object(self.task, "save_failure_screenshot"), \
                patch.object(self.task, "sleep"):
            self.assertTrue(self.task.try_step(step, name="中断恢复"))
        self.assertEqual(2, len(calls))  # 首次被中断，恢复后重跑成功。
        recover_mock.assert_called_once()

    def test_real_tower_victory_screenshot_detected(self):
        """回归测试：用户实测 1883x1058 窗口下胜利结算未被识别（REWARD 文字缩放失配）。"""
        self.set_image('tests/images/battle_finish_tower.png')  # 真实企业塔胜利结算截图。
        result, box = self.task.wait_battle_finish(time_out=4, check_interval=1)
        self.assertEqual("success", result)  # 必须能识别出战斗结束。
        self.assertIsNotNone(box)  # 返回确认按钮框供调用方点击。


if __name__ == '__main__':
    unittest.main()