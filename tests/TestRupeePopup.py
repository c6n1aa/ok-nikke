import unittest  # 单元测试模块。
from unittest.mock import patch  # mock 模块，用于替换耗时/副作用方法。

from src.config import config  # 导入项目配置（含 feature_set 与模板配置）。
from src.tasks.DailyTask import DailyTask  # 导入待测任务类（继承 MyBaseTask）。
from ok.test.TaskTestCase import TaskTestCase  # 导入测试基类。


class TestRupeeFlashSalePopup(TaskTestCase):
    task_class = DailyTask

    config = config

    def setUp(self):
        # 每个用例从干净的界面注册表开始，避免共享实例上残留其它用例注册的界面。
        self.task.screens = {}
        self.task.register_screen("lobby", features=["ark"])

    def _box(self, x=100, y=200, w=30, h=30, name='box'):
        """构造一个用于断言点击的模拟检测框。"""
        from ok.feature.Box import Box  # 导入 Box 构造检测框。
        return Box(x, y, w, h, name=name)  # 返回构造的框。

    def test_banner_clicked_when_flash_sale_detected(self):
        """识别到 rupee_flash_sale 入口横幅时点击它，返回 True。"""
        banner = self._box(name='rupee_flash_sale')  # 模拟入口横幅命中框。

        def fake_find_one(name):  # 模拟特征查找。
            return banner if name == 'rupee_flash_sale' else None  # 仅命中横幅。

        clicked = []  # 收集被点击的框。

        def fake_click_box(box, **_kwargs):  # 拦截点击记录坐标。
            clicked.append(box)  # 记录点击框。

        with patch.object(self.task, 'find_one', side_effect=fake_find_one), \
                patch.object(self.task, 'click_box', side_effect=fake_click_box):  # 替换查找与点击。
            self.assertTrue(self.task._close_rupee_flash_sale_popup())  # 应返回已处理。
        self.assertEqual([banner], clicked)  # 恰好点击一次横幅。

    def test_confirm_clicked_when_popup_open(self):
        """详情弹窗已打开时识别 rupee_flash_sale_close_confirm 并点击。"""
        confirm = self._box(name='rupee_flash_sale_close_confirm')  # 模拟关闭确认命中框。

        def fake_find_one(name):  # 模拟特征查找。
            return confirm if name == 'rupee_flash_sale_close_confirm' else None  # 仅命中确认按钮。

        clicked = []  # 收集被点击的框。

        def fake_click_box(box, **_kwargs):  # 拦截点击记录坐标。
            clicked.append(box)  # 记录点击框。

        with patch.object(self.task, 'find_one', side_effect=fake_find_one), \
                patch.object(self.task, 'click_box', side_effect=fake_click_box):  # 替换查找与点击。
            self.assertTrue(self.task._close_rupee_flash_sale_popup())  # 应返回已处理。
        self.assertEqual([confirm], clicked)  # 恰好点击一次确认按钮。

    def test_confirm_takes_priority_over_banner(self):
        """详情弹窗与入口横幅同时存在时优先点击关闭确认。"""
        confirm = self._box(x=500, name='rupee_flash_sale_close_confirm')  # 模拟关闭确认命中框。
        banner = self._box(x=100, name='rupee_flash_sale')  # 模拟入口横幅命中框。

        def fake_find_one(name):  # 模拟两个特征同时命中。
            return confirm if name == 'rupee_flash_sale_close_confirm' else banner  # 确认按钮优先返回。

        clicked = []  # 收集被点击的框。

        def fake_click_box(box, **_kwargs):  # 拦截点击记录坐标。
            clicked.append(box)  # 记录点击框。

        with patch.object(self.task, 'find_one', side_effect=fake_find_one), \
                patch.object(self.task, 'click_box', side_effect=fake_click_box):  # 替换查找与点击。
            self.assertTrue(self.task._close_rupee_flash_sale_popup())  # 应返回已处理。
        self.assertEqual([confirm], clicked)  # 点击的是关闭确认而非横幅。

    def test_no_action_when_no_rupee_popup(self):
        """当前帧无卢比限时特卖相关界面时返回 False。"""
        with patch.object(self.task, 'find_one', return_value=None):  # 全部特征未命中。
            self.assertFalse(self.task._close_rupee_flash_sale_popup())  # 应返回未处理。

    def test_try_close_one_popup_uses_click_anywhere_keyword(self):
        """无模板弹窗命中时，遮罩 OCR 关键词同时包含“点击领取奖励”与“点击任意处”。"""
        mask = self._box(name='mask')  # 模拟遮罩按钮命中框。

        with patch.object(self.task, '_close_rupee_flash_sale_popup', return_value=False), \
                patch.object(self.task, '_close_notice_popup', return_value=False), \
                patch.object(self.task, 'ocr', return_value=[mask]) as ocr_mock, \
                patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'sleep'):
            self.assertTrue(self.task._try_close_one_popup())  # 遮罩被点击关闭。
        match = ocr_mock.call_args.kwargs['match']  # 读取传给 OCR 的关键词列表。
        self.assertIn("点击领取奖励", match)  # 原有遮罩关键词保留。
        self.assertIn("点击任意处", match)  # 新增“点击任意处”关键词生效。


if __name__ == '__main__':
    unittest.main()