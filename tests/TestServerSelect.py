import unittest  # 单元测试模块。
from unittest.mock import patch  # mock 模块，用于替换耗时/副作用方法。

from ok.feature.Box import Box  # 检测框对象，用于构造模拟的区域/按钮框。
from ok.task.exceptions import TaskDisabledException  # 任务被停止异常，验证其向上传播。
from ok.test.TaskTestCase import TaskTestCase  # 导入测试基类。

from src.config import config  # 导入项目配置（含 feature_set 与模板配置）。
from src.tasks.DailyTask import DailyTask  # 导入继承基类的任务类。


class TestServerSelect(TaskTestCase):
    """服务器选择界面确认：登录前弹窗清理阶段 OCR 识别 box_server_select 内的「选择」并点击 server_select_confirm。"""

    task_class = DailyTask

    config = config

    def setUp(self):
        self.task.screens = {}  # 隔离界面注册表，避免共享实例上残留其它用例注册的界面。
        self._set_image('tests/images/lobby.png')  # 提供一帧真实分辨率，使区域/相对坐标可解析。

    def _set_image(self, path):
        """固定屏幕输入为指定截图并刷新一帧。"""
        from ok.test import ok  # 延迟导入，避免模块导入期依赖 ok 单例。
        ok.device_manager.capture_method.set_images([path])
        self.task.next_frame()

    def _box(self, x=100, y=200, w=30, h=30, name='box'):
        """构造一个用于断言点击的模拟检测框。"""
        return Box(x, y, w, h, name=name)  # 返回构造的框。

    def test_clicks_confirm_when_select_text_found(self):
        """在 box_server_select 区域内 OCR 命中「选择」时点击 server_select_confirm。"""
        region = self._box(name='box_server_select')  # 模拟服务器选择文字区域。
        text = self._box(name='选择')  # 模拟 OCR 命中的文字框。
        confirm = self._box(name='server_select_confirm')  # 模拟确认按钮。
        clicked = []  # 收集被点击的框。
        with patch.object(self.task, 'get_box_by_name', return_value=region) as box_mock, \
                patch.object(self.task, 'ocr', return_value=[text]) as ocr_mock, \
                patch.object(self.task, 'find_one', return_value=confirm) as find_mock, \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'log_info'), \
                patch.object(self.task, 'sleep'):  # 屏蔽 after_sleep 等待。
            result = self.task._confirm_server_select()
        self.assertTrue(result)  # 返回已处理。
        self.assertEqual([confirm], clicked)  # 恰好点击一次确认按钮。
        box_mock.assert_called_once_with('box_server_select')  # OCR 区域取自 coco 特征名。
        find_mock.assert_called_once_with('server_select_confirm')  # 按特征名查找确认按钮。
        match = ocr_mock.call_args.kwargs['match']  # 读取 OCR 关键词。
        self.assertTrue(any(pattern.search('选择') for pattern in match))  # 「选择」为部分匹配正则。

    def test_no_action_when_select_text_missing(self):
        """OCR 未命中「选择」= 当前帧无服务器选择界面，不查按钮也不点击。"""
        with patch.object(self.task, 'get_box_by_name', return_value=self._box(name='box_server_select')), \
                patch.object(self.task, 'ocr', return_value=[]), \
                patch.object(self.task, 'find_one') as find_mock, \
                patch.object(self.task, 'click_box') as click_mock:
            result = self.task._confirm_server_select()
        self.assertFalse(result)  # 返回未处理。
        find_mock.assert_not_called()  # 文字未命中时不查找确认按钮。
        click_mock.assert_not_called()  # 不产生点击。

    def test_returns_false_when_region_feature_missing(self):
        """区域特征缺失（ValueError）时视为无该界面，不抛异常、不做 OCR。"""
        with patch.object(self.task, 'get_box_by_name', side_effect=ValueError('missing')), \
                patch.object(self.task, 'ocr') as ocr_mock:
            self.assertFalse(self.task._confirm_server_select())  # 返回未处理。
        ocr_mock.assert_not_called()  # 区域不可用时不跑 OCR。

    def test_defers_click_when_confirm_not_found(self):
        """文字命中但确认按钮未识别到时不点击，交由下一轮重试。"""
        with patch.object(self.task, 'get_box_by_name', return_value=self._box(name='box_server_select')), \
                patch.object(self.task, 'ocr', return_value=[self._box(name='选择')]), \
                patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('按钮未识别不应点击')):
            self.assertFalse(self.task._confirm_server_select())  # 返回未处理。

    def test_try_close_one_popup_handles_server_select_first(self):
        """服务器选择界面优先于其它弹窗分支被处理。"""
        with patch.object(self.task, '_confirm_server_select', return_value=True) as select_mock, \
                patch.object(self.task, '_close_rupee_flash_sale_popup') as sale_mock, \
                patch.object(self.task, '_close_notice_popup') as notice_mock:
            self.assertTrue(self.task._try_close_one_popup())  # 已处理服务器选择。
        select_mock.assert_called_once()  # 最先尝试服务器选择。
        sale_mock.assert_not_called()  # 命中后不再走后续分支。
        notice_mock.assert_not_called()  # 命中后不再走后续分支。

    def test_try_close_one_popup_swallows_ocr_error(self):
        """服务器选择 OCR 抛普通异常时记录警告并继续后续弹窗清理。"""
        with patch.object(self.task, '_confirm_server_select', side_effect=RuntimeError('ocr fail')), \
                patch.object(self.task, '_close_rupee_flash_sale_popup', return_value=False), \
                patch.object(self.task, '_close_notice_popup', return_value=False), \
                patch.object(self.task, 'ocr', return_value=[]), \
                patch.object(self.task, '_close_daily_login_popup', return_value=False), \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.assertFalse(self.task._try_close_one_popup())  # 本帧无弹窗可关。
        warn_mock.assert_called_once()  # 记录一次警告。

    def test_try_close_one_popup_propagates_task_disabled(self):
        """任务被停止时 TaskDisabledException 必须继续向上传播，不被吞掉。"""
        with patch.object(self.task, '_confirm_server_select', side_effect=TaskDisabledException()), \
                patch.object(self.task, 'log_warning'):
            with self.assertRaises(TaskDisabledException):
                self.task._try_close_one_popup()


if __name__ == '__main__':
    unittest.main()
