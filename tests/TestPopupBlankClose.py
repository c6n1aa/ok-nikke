import unittest  # 单元测试模块。
from unittest.mock import patch  # mock 模块，用于替换点击/等待方法。

from ok.task.exceptions import WaitFailedException  # 关闭失败抛出的等待失败异常。
from ok.test.TaskTestCase import TaskTestCase  # 导入测试基类。

from src.config import config  # 导入项目配置。
from src.tasks.DailyTask import DailyTask  # 通用弹窗能力挂在 PopupsMixin，用 DailyTask 作为载体。


class TestPopupBlankClose(TaskTestCase):
    """基类通用「点击空白关闭模态弹窗」：缺省坐标、补点与失败语义。"""

    task_class = DailyTask

    config = config

    def _run(self, verify_results, **kwargs):
        """执行 close_popup_by_blank：verify 按序列返回结果，返回 (执行结果, 点击参数列表)。"""
        clicks = []  # 收集 click_relative 调用参数。
        results = list(verify_results)  # verify 的预设结果序列。

        def fake_verify():  # 按序列返回，耗尽后恒 False。
            return results.pop(0) if results else False

        with patch.object(self.task, 'click_relative',
                          side_effect=lambda x, y, **kw: clicks.append((x, y, kw))), \
                patch.object(self.task, 'wait_until',
                             side_effect=lambda cond, **kw: cond()):  # 立即求值 verify 条件。
            result = self.task.close_popup_by_blank(fake_verify, **kwargs)
        return result, clicks

    def test_defaults_click_once_and_confirm(self):
        """verify 首次成立：点一次缺省坐标即返回成功。"""
        result, clicks = self._run([True])
        self.assertTrue(result)  # 已确认关闭。
        self.assertEqual([(self.task._MODAL_BLANK_CLOSE_X, self.task._MODAL_BLANK_CLOSE_Y,
                           {'after_sleep': 1})], clicks)  # 使用缺省坐标点一次空白。

    def test_retries_until_confirmed(self):
        """首次点击未确认关闭时补点，第二次 verify 成立即返回成功。"""
        result, clicks = self._run([False, True])
        self.assertTrue(result)  # 补点后确认关闭。
        self.assertEqual(self.task._MODAL_BLANK_CLOSE_ATTEMPTS, len(clicks))  # 点满 2 次。

    def test_returns_false_when_attempts_exhausted(self):
        """点击次数耗尽仍未确认关闭：返回 False。"""
        result, clicks = self._run([False, False, False])
        self.assertFalse(result)  # 未确认关闭。
        self.assertEqual(self.task._MODAL_BLANK_CLOSE_ATTEMPTS, len(clicks))  # 只点缺省次数，不多点。

    def test_raise_on_fail(self):
        """raise_on_fail=True 且未关闭时抛 WaitFailedException。"""
        with self.assertRaises(WaitFailedException):
            self._run([False, False], raise_on_fail=True)

    def test_custom_point_and_attempts(self):
        """自定义坐标与点击次数生效。"""
        result, clicks = self._run([False, False, True], x=0.2, y=0.3, attempts=3, time_out=5)
        self.assertTrue(result)  # 第三次确认关闭。
        self.assertEqual(3, len(clicks))  # 按自定义次数点击。
        self.assertEqual((0.2, 0.3, {'after_sleep': 1}), clicks[0])  # 使用自定义坐标。


if __name__ == '__main__':
    unittest.main()
