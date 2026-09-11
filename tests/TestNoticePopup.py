import unittest  # 单元测试模块。
from unittest.mock import patch  # mock 模块，用于替换耗时/副作用方法。

from src.config import config  # 导入项目配置（含 feature_set 与模板配置）。
from src.tasks.DailyTask import DailyTask  # 导入待测任务类（继承 NikkeBaseTask）。
from ok.test.TaskTestCase import TaskTestCase  # 导入测试基类。


class TestNoticePopupDetection(TaskTestCase):
    task_class = DailyTask

    config = config

    def setUp(self):
        # 每个用例从干净的界面注册表开始，避免共享实例上残留其它用例注册的界面。
        self.task.screens = {}
        self.task.register_screen("lobby", features=["ark"])
        # 冻结任务列表与卡片不可用时的重复截图副作用。
        self.image = None

    def _set_image(self, path):
        """固定屏幕输入为指定截图并刷新一帧。"""
        from ok.test import ok
        ok.device_manager.capture_method.set_images([path])
        self.task.next_frame()

    def _close(self):
        """执行 _close_notice_popup 并抑制 after_sleep 的等待耗时。"""
        with patch.object(self.task, 'sleep'):
            return self.task._close_notice_popup()

    def _find_any_bell(self):
        """与实现一致地依次尝试所有铃铛模板，返回第一个命中的框。"""
        for template_path in self.task._NOTICE_BELL_TEMPLATES:  # 遍历所有铃铛模板。
            bell = self.task.find_scaled_template(  # 查找当前模板。
                'notice_bell', template_path,  # 使用模板并命名匹配结果。
                threshold=0.75,  # 与实现一致：阈值放宽到 0.75。
                box=self.task.box_of_screen(0.258, 0.05, 0.75, 0.5),  # 中上部区域。
            )
            if bell is not None:  # 命中。
                return bell  # 返回命中框。
        return None  # 全部未命中。

    def test_gonggao_01_closes_popup(self):
        """公告截图：应在中上部找到 notice_bell，并在右侧找到 common_close 后返回 True。"""
        self._set_image('tests/images/gonggao_01.png')  # 固定公告截图。
        self.assertTrue(self._close())  # 应成功关闭弹窗。

    def test_huodong_01_closes_popup(self):
        """活动截图1：应能识别公告横幅并关闭。"""
        self._set_image('tests/images/huodong_01.png')  # 固定活动截图。
        self.assertTrue(self._close())  # 应成功关闭弹窗。

    def test_huodong_02_closes_popup(self):
        """活动截图2：应能识别公告横幅并关闭。"""
        self._set_image('tests/images/huodong_02.png')  # 固定活动截图。
        self.assertTrue(self._close())  # 应成功关闭弹窗。

    def test_try_close_one_popup_closes_notice(self):
        """_try_close_one_popup 在公告横幅存在时返回 True，且不触发遮罩 OCR。"""
        self._set_image('tests/images/gonggao_01.png')  # 固定公告截图。
        with patch.object(self.task, 'ocr') as ocr_mock, \
                patch.object(self.task, 'sleep'), \
                patch.object(self.task, 'click_box'):
            self.assertTrue(self.task._try_close_one_popup())  # 横幅被关闭。
        ocr_mock.assert_not_called()  # 横幅命中后不走到遮罩 OCR。

    def test_click_position_within_bell_extended_region(self):
        """点击坐标应落在 notice_bell 右侧延伸出的搜索区域内（保证关闭按钮在横幅右侧）。"""
        from ok.feature.Box import Box  # 导入 Box 用于断言坐标。
        self._set_image('tests/images/gonggao_01.png')  # 固定公告截图。
        bell = self._find_any_bell()  # 依次尝试多个铃铛模板查找公告横幅。
        self.assertIsNotNone(bell)  # 横幅必须找到。
        region = Box(  # 构造与实现一致的搜索区域。
            bell.x + bell.width,  # 从横幅右边缘开始。
            max(0, bell.y - bell.height),  # 上扩一个横幅高度。
            self.task.width - (bell.x + bell.width),  # 延伸到右边缘。
            bell.height * 3,  # 高度为横幅三倍。
            name='notice_close_region',  # 区域名。
        )
        clicked = []  # 收集被点击的框。

        def fake_click_box(box, **_kwargs):  # 拦截点击记录坐标。
            clicked.append(box)  # 记录点击框。

        with patch.object(self.task, 'click_box', side_effect=fake_click_box):  # 替换点击实现。
            self.assertTrue(self._close())  # 应成功关闭。
        self.assertEqual(1, len(clicked))  # 必须恰好点击一次。
        close_box = clicked[0]  # 取出被点击的关闭按钮。
        # 关闭按钮中心应位于横幅右侧区域内：x 在区域起点之后、屏幕右边缘之前。
        self.assertGreaterEqual(close_box.x, region.x)  # 关闭按钮在横幅右侧。
        self.assertLessEqual(close_box.x, region.x + region.width)  # 不超过屏幕右边缘。
        # 关闭按钮中心 y 应在区域垂直范围内。
        self.assertGreaterEqual(close_box.y, region.y)  # 不低于区域顶部。
        self.assertLessEqual(close_box.y + close_box.height, region.y + region.height)  # 不超出区域底部。


if __name__ == '__main__':
    unittest.main()
