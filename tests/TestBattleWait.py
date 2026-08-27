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

    def test_success_returns_text_box_without_click(self):
        text_box = Box(1097, 1197, 376, 216, confidence=1, name="box_battle_finish_text")
        esc_ocr = Box(1200, 1250, 60, 30, confidence=0.9, name="ESC")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "get_box_by_name", return_value=text_box) as box_mock, \
                patch.object(self.task, "_region_ocr_cached", return_value=[esc_ocr]) as ocr_mock, \
                patch.object(self.task, "find_one", return_value=None) as find_mock, \
                patch.object(self.task, "click_box", side_effect=AssertionError("检测阶段不应点击")):
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertIs(text_box, box)  # 返回统一的可点击区域框 box_battle_finish_text。
        self.assertEqual(3, box_mock.call_count)  # 初检取区域 + 稳定化复识别取区域 + 稳定化返回值取区域。
        self.assertEqual(2, ocr_mock.call_count)  # 初检 OCR + 稳定化复识别 OCR。
        self.assertEqual(0, find_mock.call_count)  # 胜利主路径不依赖模板特征。

    def test_success_on_later_iteration(self):
        text_box = Box(1097, 1197, 376, 216, confidence=1, name="box_battle_finish_text")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "get_box_by_name", return_value=text_box), \
                patch.object(self.task, "_esc_visible", side_effect=[False, True, True]) as esc_mock, \
                patch.object(self.task, "find_one",
                             side_effect=[None, None, None]) as find_mock:
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertIs(text_box, box)
        self.assertEqual(3, esc_mock.call_count)  # 第1轮未命中，第2轮初检 + 稳定化复识别命中。
        self.assertEqual(3, find_mock.call_count)  # 第1轮 statistics + 失败双特征各一次。

    def test_statistics_fallback_returns_text_box(self):
        """OCR 未命中但 statistics 兜底命中：判定胜利，返回的可点击框统一为 box_battle_finish_text 区域。"""
        text_box = Box(1097, 1197, 376, 216, confidence=1, name="box_battle_finish_text")
        statistics_box = Box(2210, 1339, 34, 38, confidence=0.85, name="battle_finish_statistics")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "get_box_by_name", return_value=text_box) as box_mock, \
                patch.object(self.task, "_region_ocr_cached", return_value=[]) as ocr_mock, \
                patch.object(self.task, "find_one",
                             side_effect=[statistics_box, statistics_box]) as find_mock:
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertIs(text_box, box)  # 兜底路径同样返回 box_battle_finish_text 区域框。
        self.assertEqual(2, find_mock.call_count)  # 初检 statistics + 稳定化复识别 statistics。
        self.assertEqual(2, ocr_mock.call_count)  # 初检 OCR + 稳定化复识别 OCR（均未命中 ESC）。

    def test_failed_returns_outcome_and_back_box_without_click(self):
        text_box = Box(1097, 1197, 376, 216, confidence=1, name="box_battle_finish_text")
        failed_box = Box(300, 300, 70, 70, confidence=1, name="battle_finish_failed")
        failed_back_box = Box(400, 400, 80, 80, confidence=1, name="battle_finish_failed_back")
        # 每轮轮询：statistics + 失败双特征 共 3 次查找；命中后稳定化再查失败双特征。
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "get_box_by_name", return_value=text_box), \
                patch.object(self.task, "_region_ocr_cached", return_value=[]), \
                patch.object(self.task, "find_one",
                             side_effect=[None, None, None, None,
                                          failed_box, failed_back_box,
                                          failed_box, failed_back_box]) as find_mock, \
                patch.object(self.task, "click_box", side_effect=AssertionError("检测阶段不应点击")):
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("failed", result)
        self.assertIs(failed_back_box, box)  # 稳定化后重新定位到的返回按钮框。
        self.assertEqual(8, find_mock.call_count)  # 第一轮 statistics+失败双特征(3)，第二轮(3)，稳定化复核再查一轮双特征(2)。

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
                patch.object(self.task, "get_box_by_name", side_effect=ValueError), \
                patch.object(self.task, "find_one",
                             side_effect=[None, None, None, None, interrupt_box]), \
                patch.object(self.task, "save_failure_screenshot") as shot_mock:
            with self.assertRaises(nbt.InterruptedByDialogException):
                self.task.wait_battle_finish(time_out=240)
        shot_mock.assert_called_once_with("interrupt")  # 第 2 轮即命中，远小于 240 秒超时。

    def test_interrupt_sentinel_inactive_by_default(self):
        # 空清单 = 哨兵未激活：不产生任何额外特征查找，行为与现状逐位一致。
        text_box = Box(1097, 1197, 376, 216, confidence=1, name="box_battle_finish_text")
        esc_ocr = Box(1200, 1250, 60, 30, confidence=0.9, name="ESC")
        with patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "get_box_by_name", return_value=text_box), \
                patch.object(self.task, "_region_ocr_cached", return_value=[esc_ocr]), \
                patch.object(self.task, "find_one", return_value=None) as find_mock:
            result, box = self.task.wait_battle_finish(time_out=30)
        self.assertEqual("success", result)
        self.assertEqual(0, find_mock.call_count)  # 无中断路径的额外调用，胜利主路径不依赖模板特征。

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

    def test_real_statistics_box_victory_detected(self):
        """回归测试：OCR 未命中 ESC 的竖屏 Tetra Tower 结算界面，
        依靠 box_battle_finish_bottom_right 内的 battle_finish_statistics 兜底判定胜利。"""
        self.set_image('tests/images/battle_finish_statistics.png')  # 真实竖屏通关结算截图（ESC 不可识别）。
        result, box = self.task.wait_battle_finish(time_out=4, check_interval=1)
        self.assertEqual("success", result)  # statistics 兜底必须能识别出战斗结束。
        self.assertIsNotNone(box)  # 返回确认按钮框供调用方点击。


if __name__ == '__main__':
    unittest.main()
