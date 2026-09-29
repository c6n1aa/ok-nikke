# pyright: reportOptionalMemberAccess=false, reportOptionalSubscript=false
# 仅本测试文件：mock 出来的 find_one/load_snapshot 返回值已知非空，直接取属性；src/ 仍由这两条规则把关。
import unittest  # 单元测试模块。
from unittest.mock import patch  # mock 模块，用于替换耗时/副作用方法。

from ok.test.TaskTestCase import TaskTestCase  # 导入测试基类。

from src.config import config  # 导入项目配置（含 feature_set 与模板配置）。
from src.tasks.DailyTask import DailyTask  # 导入待测任务类（继承 NikkeBaseTask）。


class TestNoticePopupDetection(TaskTestCase):
    task_class = DailyTask
    task: DailyTask

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
                threshold=self.task._NOTICE_BELL_THRESHOLD,  # 与实现一致：真横幅实测 0.96~1.00。
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
        # 遮罩检测走 ocr(x=, y=, ...) 坐标分支，服务器选择检测走 ocr(box=, ...) 分支；
        # 横幅命中后不走到遮罩 OCR，但服务器选择检测会先执行一次区域 OCR，故只断言坐标分支未触发。
        for _args, kwargs in ocr_mock.call_args_list:
            self.assertNotIn('x', kwargs)

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

    def test_bell_threshold_keeps_margin_over_non_notice_frames(self):
        """铃铛阈值必须留出足够余量：非横幅画面实测最高约 0.73（大厅 0.55~0.56、领奖遮罩 0.68~0.73）。

        原阈值 0.75 的余量只有 0.02，2026-09-28、09-29 实测邮箱页有元素越过它，公告分支被误触发后
        点掉了邮箱面板自己的关闭按钮，导致邮箱子流程空等超时、步骤被判失败并重跑。
        """
        self.assertGreaterEqual(self.task._NOTICE_BELL_THRESHOLD, 0.9)  # 真横幅实测 0.96~1.00，收紧后仍有充足余量。

    def test_lobby_screenshot_has_no_notice_popup(self):
        """大厅截图不含公告横幅：铃铛阈值收紧后不得误判，也不得误点画面上的元素。"""
        from ok.feature.Box import Box  # 导入 Box 用于类型注解。

        self._set_image('tests/images/lobby.png')  # 固定大厅截图（实测两个铃铛模板最高约 0.55~0.59）。
        clicked: list[Box] = []  # 收集被点击的框。

        def fake_click_box(box, **_kwargs):  # 拦截点击记录坐标。
            clicked.append(box)  # 记录点击框。

        with patch.object(self.task, 'click_box', side_effect=fake_click_box):
            self.assertFalse(self._close())  # 无横幅：返回 False。
        self.assertEqual([], clicked)  # 一个都不点。

    def test_skips_close_button_of_open_panel(self):
        """命中的关闭按钮属于正开着的我方面板时必须跳过（邮箱关闭按钮与通用关闭模板同形，实测 0.88~0.95）。"""
        from ok.feature.Box import Box  # 导入 Box 用于构造预置检测框。

        self._set_image('tests/images/lobby.png')  # 提供一帧真实分辨率，供 box_of_screen 换算。
        panel_close = Box(1579, 179, 32, 31, name='mailbox_close')  # 邮箱面板自身关闭按钮的标注位置。
        bell = Box(660, 120, 33, 41, name='notice_bell')  # 预置的铃铛命中（位置只需让关闭搜索区成立）。
        close = Box(1583, 183, 20, 21, name='common_close')  # 预置的关闭命中：正好落在面板关闭按钮上。

        def fake_find_scaled(_feature_name, template_path, **_kwargs):  # 铃铛与关闭按钮都返回预置框。
            return bell if 'bell' in template_path else close  # 按模板路径区分两次查找。

        clicked: list[Box] = []  # 收集被点击的框。

        def fake_click_box(box, **_kwargs):  # 拦截点击记录坐标。
            clicked.append(box)  # 记录点击框。

        with patch.object(self.task, 'find_scaled_template', side_effect=fake_find_scaled), \
                patch.object(self.task, 'get_box_by_name', return_value=panel_close), \
                patch.object(self.task, 'find_one', return_value=panel_close), \
                patch.object(self.task, 'click_box', side_effect=fake_click_box):
            self.assertFalse(self._close())  # 命中的是面板自己的关闭按钮：跳过不点。
        self.assertEqual([], clicked)  # 点击会关掉正在操作的面板，必须一次都不点。


if __name__ == '__main__':
    unittest.main()
