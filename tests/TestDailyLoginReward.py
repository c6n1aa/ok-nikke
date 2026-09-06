import unittest  # 单元测试模块。
from unittest.mock import patch  # mock 模块，用于替换耗时/副作用方法。

from src.config import config  # 导入项目配置（含 feature_set 与模板配置）。
from src.tasks.DailyTask import DailyTask  # 导入待测任务类（继承 NikkeBaseTask）。
from ok.test.TaskTestCase import TaskTestCase  # 导入测试基类。


class TestDailyLoginRewardPopup(TaskTestCase):
    """登录奖励（DAILY LOGIN）弹窗清理：领奖/关闭分支与在 _try_close_one_popup 中的顺序。

    全部用 mock 驱动，不依赖 dev_tools 下的实机截图（该目录不入仓）；模板质量与
    OCR 命中由 dev_tools/diag_claim_ocr.py 在真实截图上验证。

    判据选取受一条实机约束驱动：七天制小型登录奖励每期面板皮肤不同、领完就不再弹，
    故「全部领取」认文字（OCR）、关闭按钮认 X 图形（模板列表，新皮肤追加即可）。
    """

    task_class = DailyTask

    config = config

    # 2560x1440 基准下的实测值（见 dev_tools/test_daily_login_reward/login.png）。
    CLAIM_TEXT_BOX = (1456, 1333, 103, 33)  # OCR 识别到的「全部领取」文字框。
    CLAIM_BUTTON_BOX = (1373, 1317, 274, 63)  # 按钮本体外接框（外扩后不得超出它）。
    CLOSE_CENTER = (1611, 137)  # 面板右上角关闭 X 中心。

    def setUp(self):
        # 每个用例从干净的界面注册表开始，避免共享实例上残留其它用例注册的界面。
        self.task.screens = {}
        self.task.register_screen("lobby", features=["ark"])
        self._set_image('tests/images/lobby.png')  # 提供 2560x1440 的一帧，使 box_of_screen 有真实分辨率。

    def _set_image(self, path):
        """固定屏幕输入为指定截图并刷新一帧。"""
        from ok.test import ok  # 延迟导入，避免模块导入期依赖 ok 单例。
        ok.device_manager.capture_method.set_images([path])
        self.task.next_frame()

    def _box(self, x=100, y=200, w=30, h=30, name='box'):
        """构造一个用于断言点击的模拟检测框。"""
        from ok.feature.Box import Box  # 导入 Box 构造检测框。
        return Box(x, y, w, h, name=name)  # 返回构造的框。

    def _run_close(self, claim_text=None, close=None, enabled=True):
        """以预设的 OCR 命中、关闭按钮命中与底色可用性执行一次 _close_daily_login_popup。

        Returns:
            (返回值, 被点击的框列表, 记录 {ocr_box, expanded, paths})。
        """
        info = {}  # 收集调用参数用于断言。
        clicked = []  # 收集被点击的框。

        def fake_ocr(box=None, **_kwargs):  # 模拟「全部领取」文字 OCR。
            info['ocr_box'] = box  # 记录 OCR 区域。
            return [claim_text] if claim_text is not None else []

        def fake_find(name, path, **_kwargs):  # 模拟关闭按钮模板匹配。
            info.setdefault('paths', []).append(path)  # 记录尝试过的模板。
            return close if name == 'daily_login_close' else None

        def fake_enabled(box, **_kwargs):  # 模拟按钮底色可用性判定。
            info['expanded'] = box  # 记录被判色的框（应已是外扩后的）。
            return enabled

        with patch.object(self.task, 'ocr', side_effect=fake_ocr), \
                patch.object(self.task, 'find_scaled_template', side_effect=fake_find), \
                patch.object(self.task, 'is_feature_enabled', side_effect=fake_enabled), \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'sleep'):  # 屏蔽 after_sleep 等待。
            result = self.task._close_daily_login_popup()
        return result, clicked, info

    def test_claim_all_clicked_when_button_colorful(self):
        """OCR 命中「全部领取」且按钮底色为彩色（有可领奖励）时点击该文字框。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框。
        close = self._box(name='daily_login_close')  # 模拟关闭按钮命中框（不应被点）。
        result, clicked, _ = self._run_close(claim_text=text, close=close, enabled=True)
        self.assertTrue(result)  # 返回已处理。
        self.assertEqual([text], clicked)  # 恰好点击一次领取按钮。

    def test_close_clicked_when_button_gray_out(self):
        """按钮底色灰白（已领完/无可领）时跳过领取，改点关闭按钮。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框仍命中。
        close = self._box(x=500, name='daily_login_close')  # 模拟关闭按钮命中框。
        result, clicked, _ = self._run_close(claim_text=text, close=close, enabled=False)
        self.assertTrue(result)  # 返回已处理。
        self.assertEqual([close], clicked)  # 点击的是关闭按钮而非领取按钮。

    def test_close_clicked_when_claim_text_missing(self):
        """领取文字未命中（可能已被奖励遮罩遮挡）但关闭按钮可见时点击关闭。"""
        close = self._box(name='daily_login_close')  # 模拟仅关闭按钮命中。
        result, clicked, _ = self._run_close(claim_text=None, close=close)
        self.assertTrue(result)  # 返回已处理。
        self.assertEqual([close], clicked)  # 恰好点击一次关闭按钮。

    def test_no_action_when_no_popup(self):
        """当前帧无登录奖励弹窗时返回 False 且不产生任何点击。"""
        result, clicked, _ = self._run_close(claim_text=None, close=None)
        self.assertFalse(result)  # 返回未处理。
        self.assertEqual([], clicked)  # 不产生点击。

    def test_no_action_when_only_gray_claim_but_no_close(self):
        """只有灰白的领取按钮而关闭按钮不可见时返回 False（避免无止境重复点击）。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框命中。
        result, clicked, _ = self._run_close(claim_text=text, close=None, enabled=False)
        self.assertFalse(result)  # 无可关动作。
        self.assertEqual([], clicked)  # 不产生点击。

    def test_ocr_region_covers_claim_text(self):
        """OCR 区域必须覆盖「全部领取」文字在 2560x1440 基准下的实测范围。"""
        _, _, info = self._run_close(claim_text=self._box(name='全部领取'),
                                     close=self._box(name='daily_login_close'))
        box = info.get('ocr_box')  # 读取传给 OCR 的区域。
        self.assertIsNotNone(box)  # 必须限定区域而非全屏 OCR。
        tx, ty, tw, th = self.CLAIM_TEXT_BOX  # 文字框实测范围。
        self.assertLessEqual(box.x, tx)  # 区域左边界在文字左侧。
        self.assertGreaterEqual(box.x + box.width, tx + tw)  # 区域右边界在文字右侧。
        self.assertLessEqual(box.y, ty)  # 区域上边界在文字上方。
        self.assertGreaterEqual(box.y + box.height, ty + th)  # 区域下边界在文字下方。

    def test_expanded_box_stays_inside_button(self):
        """文字框外扩取底色的区域必须仍落在按钮本体内（否则会混进背景色误判）。"""
        tx, ty, tw, th = self.CLAIM_TEXT_BOX  # 文字框实测范围。
        _, _, info = self._run_close(claim_text=self._box(x=tx, y=ty, w=tw, h=th, name='全部领取'),
                                     close=self._box(name='daily_login_close'))
        expanded = info.get('expanded')  # 读取被判色的外扩框。
        self.assertIsNotNone(expanded)  # 必须做过外扩。
        self.assertNotEqual((tx, ty, tw, th),
                            (expanded.x, expanded.y, expanded.width, expanded.height))  # 确实被放大了。
        bx, by, bw, bh = self.CLAIM_BUTTON_BOX  # 按钮本体实测范围。
        self.assertGreaterEqual(expanded.x, bx)  # 不超出按钮左边界。
        self.assertLessEqual(expanded.x + expanded.width, bx + bw)  # 不超出按钮右边界。
        self.assertGreaterEqual(expanded.y, by)  # 不超出按钮上边界。
        self.assertLessEqual(expanded.y + expanded.height, by + bh)  # 不超出按钮下边界。

    def test_close_templates_tried_in_order(self):
        """关闭按钮有多个候选模板时依次尝试，前一个未命中则继续下一个。"""
        tpl_a = 'assets/template/daily_login/a.png'  # 模拟第一期的样式。
        tpl_b = 'assets/template/daily_login/b.png'  # 模拟另一期的新皮肤样式。
        close = self._box(name='daily_login_close')  # 模拟第二个模板命中。
        tried = []  # 记录尝试顺序。

        def fake_find(_name, path, **_kwargs):  # 仅第二个模板命中。
            tried.append(path)  # 记录尝试过的路径。
            return close if path == tpl_b else None

        with patch.object(self.task, '_DAILY_LOGIN_CLOSE_TEMPLATES', (tpl_a, tpl_b)), \
                patch.object(self.task, 'find_scaled_template', side_effect=fake_find):
            found = self.task._find_daily_login_close()
        self.assertIs(close, found)  # 返回第二个模板的命中框。
        self.assertEqual([tpl_a, tpl_b], tried)  # 按声明顺序依次尝试。

    def test_close_search_region_covers_close_button(self):
        """关闭按钮的搜索区域必须覆盖其在 2560x1440 基准下的实测中心。"""
        self._run_close(claim_text=None, close=self._box(name='daily_login_close'))
        region = self.task.box_of_screen(0.5, 0.03, 0.8, 0.2)  # 与实现一致的区域。
        cx, cy = self.CLOSE_CENTER  # 关闭按钮实测中心。
        self.assertLessEqual(region.x, cx)  # 区域左边界在按钮左侧。
        self.assertGreaterEqual(region.x + region.width, cx)  # 区域右边界在按钮右侧。
        self.assertLessEqual(region.y, cy)  # 区域上边界在按钮上方。
        self.assertGreaterEqual(region.y + region.height, cy)  # 区域下边界在按钮下方。

    def test_try_close_one_popup_prefers_mask_over_panel(self):
        """奖励遮罩与登录奖励面板同时存在时先关遮罩（面板排在遮罩之后）。"""
        mask = self._box(name='mask')  # 模拟遮罩提示命中框。
        clicked = []  # 收集被点击的框。
        with patch.object(self.task, '_close_rupee_flash_sale_popup', return_value=False), \
                patch.object(self.task, '_close_notice_popup', return_value=False), \
                patch.object(self.task, 'ocr', return_value=[mask]) as ocr_mock, \
                patch.object(self.task, 'find_scaled_template', return_value=None) as find_mock, \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'sleep'):
            self.assertTrue(self.task._try_close_one_popup())  # 遮罩被关闭。
        self.assertEqual([mask], clicked)  # 点击的是遮罩。
        self.assertEqual(1, ocr_mock.call_count)  # 命中遮罩后不再为面板跑第二次 OCR。
        self.assertEqual(0, find_mock.call_count)  # 也不查找面板的关闭按钮模板。

    def test_try_close_one_popup_falls_back_to_panel(self):
        """无遮罩时 _try_close_one_popup 走到登录奖励面板并点击「全部领取」。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框。
        clicked = []  # 收集被点击的框。
        # 第一次 OCR 为遮罩分支（无遮罩），第二次为面板的「全部领取」。
        with patch.object(self.task, '_close_rupee_flash_sale_popup', return_value=False), \
                patch.object(self.task, '_close_notice_popup', return_value=False), \
                patch.object(self.task, 'ocr', side_effect=[[], [text]]), \
                patch.object(self.task, 'find_scaled_template', return_value=None), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'sleep'):
            self.assertTrue(self.task._try_close_one_popup())  # 面板被处理。
        self.assertEqual([text], clicked)  # 点击的是领取按钮。


if __name__ == '__main__':
    unittest.main()
