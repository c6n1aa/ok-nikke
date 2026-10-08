# pyright: reportOptionalMemberAccess=false, reportOptionalSubscript=false
# 仅本测试文件：mock 出来的 find_one/load_snapshot 返回值已知非空，直接取属性；src/ 仍由这两条规则把关。
import unittest  # 单元测试模块。
from unittest.mock import patch  # mock 模块，用于替换耗时/副作用方法。

from ok.test.TaskTestCase import TaskTestCase  # 导入测试基类。

from src.config import config  # 导入项目配置（含 feature_set 与模板配置）。
from src.tasks.DailyTask import DailyTask  # 导入待测任务类（继承 NikkeBaseTask）。


class TestDailyLoginRewardPopup(TaskTestCase):
    """登录奖励（DAILY LOGIN）界面清理：领奖/关闭分支与在 _try_close_one_popup 中的顺序。

    全部用 mock 驱动，不依赖 dev_tools 下的实机截图（该目录不入仓）。

    判据选取受一条实机约束驱动：七天制小型登录奖励每期界面皮肤不同、领完就不再弹，
    故存在判据只认「全部领取」文字（OCR）；关闭动作不识别界面右上角 X（模板随皮肤失效、
    需持续追加），按界面形态二选一——整页奖励界面（同活动签到奖励页）面板外没有可点的
    空白遮罩，走基类 _find_back_button + 点返回键；模态面板形态才走 close_popup_by_blank。
    """

    task_class = DailyTask
    task: DailyTask

    config = config

    # 2560x1440 基准下的实测值（原截图见 dev_tools/test_daily_login_reward/login.png，已不在仓库）。
    CLAIM_TEXT_BOX = (1456, 1333, 103, 33)  # OCR 识别到的「全部领取」文字框。
    CLAIM_BUTTON_BOX = (1373, 1317, 274, 63)  # 按钮本体外接框（外扩后不得超出它）。
    CLOSE_CENTER = (1611, 137)  # 面板右上角关闭 X 中心（用于推算面板右界）。

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

    def _run_close(self, claim_text=None, enabled=True, blank_close=True, back=None, back_close=True):
        """以预设的 OCR 命中、底色可用性、返回键与关闭确认结果执行一次 _close_daily_login_popup。

        Args:
            claim_text: 「全部领取」OCR 命中框（None = 当前帧无登录奖励界面）。
            enabled: 按钮底色是否彩色（有可领奖励）。
            blank_close: close_popup_by_blank（点空白关闭）的返回值。
            back: _find_back_button 的命中框（非 None = 整页形态奖励界面）。
            back_close: 点返回键后 verify 的确认结果（False = 补点后仍未确认关闭）。

        Returns:
            (返回值, 被点击的框列表, close_popup_by_blank 的 mock,
             记录 {ocr_box, expanded, verify, verify_now, back_mock})。
        """
        info = {}  # 收集调用参数用于断言。
        clicked = []  # 收集被点击的框。

        def fake_ocr(box=None, **_kwargs):  # 模拟「全部领取」文字 OCR。
            info['ocr_box'] = box  # 记录 OCR 区域。
            return [claim_text] if claim_text is not None else []

        def fake_enabled(box, **_kwargs):  # 模拟按钮底色可用性判定。
            info['expanded'] = box  # 记录被判色的框（应已是外扩后的）。
            return enabled

        def fake_wait(condition, **_kwargs):  # 模拟关闭确认等待：记录判据并按预设结果返回。
            info['verify'] = condition  # 记录关闭判据（供断言判据语义）。
            info['verify_now'] = condition()  # 在 mock 生效期间求值判据（离开 with 后 OCR 已还原为真实实现）。
            return back_close

        with patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, 'ocr', side_effect=fake_ocr), \
                patch.object(self.task, 'is_feature_enabled', side_effect=fake_enabled), \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'close_popup_by_blank',
                             return_value=blank_close) as blank_mock, \
                patch.object(self.task, '_find_back_button', return_value=back) as back_mock, \
                patch.object(self.task, 'wait_until', side_effect=fake_wait), \
                patch.object(self.task, 'close_overlay'), \
                patch.object(self.task, 'sleep'):  # 屏蔽 after_sleep 等待。
            result = self.task._close_daily_login_popup()
        info['back_mock'] = back_mock  # 返回键定位 mock，供断言是否被咨询。
        return result, clicked, blank_mock, info

    def test_claim_all_clicked_when_button_colorful(self):
        """OCR 命中「全部领取」且按钮底色为彩色（有可领奖励）时点击该文字框。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框。
        result, clicked, blank_mock, _ = self._run_close(claim_text=text, enabled=True)
        self.assertTrue(result)  # 返回已处理。
        self.assertEqual([text], clicked)  # 恰好点击一次领取按钮。
        blank_mock.assert_not_called()  # 可领时不点空白。

    def test_blank_close_when_button_gray_out(self):
        """按钮底色灰白（已领完/无可领）且未命中返回键（模态面板形态）时跳过领取，走通用点空白关闭。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框仍命中。
        result, clicked, blank_mock, _ = self._run_close(claim_text=text, enabled=False)
        self.assertTrue(result)  # 返回已处理。
        self.assertEqual([], clicked)  # 不点领取按钮。
        blank_mock.assert_called_once()  # 恰好调用一次点空白关闭。
        verify = blank_mock.call_args.args[0]  # 关闭判据。
        self.assertTrue(callable(verify))  # 判据是可调用的「弹窗已关闭」检查。
        self.assertTrue(verify())  # OCR 未命中「全部领取」= 面板已关闭。

    def test_returns_false_when_blank_close_fails(self):
        """点空白未能确认关闭（面板仍在）时返回 False，由外层继续轮转处理。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框仍命中。
        result, clicked, _, _ = self._run_close(claim_text=text, enabled=False, blank_close=False)
        self.assertFalse(result)  # 返回未处理。
        self.assertEqual([], clicked)  # 不点领取按钮。

    def test_back_button_closes_full_page_reward(self):
        """整页形态的奖励界面（同活动签到奖励页）面板外没有可点的空白：命中返回键时点返回键关闭，不点空白。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框仍命中（按钮已灰白）。
        back = self._box(name='common_back')  # 模拟返回键命中框。
        result, clicked, blank_mock, info = self._run_close(claim_text=text, enabled=False, back=back)
        self.assertTrue(result)  # 返回已处理。
        self.assertEqual([back], clicked)  # 只点返回键，不点领取按钮。
        blank_mock.assert_not_called()  # 整页形态不走点空白。
        self.assertFalse(info['verify_now'])  # 关闭判据仍是「全部领取」文字消失：文字仍在 = 未关闭。

    def test_back_button_failure_returns_false(self):
        """点返回键后未能确认关闭时返回 False（交由外层继续轮转），不退化去点空白。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框仍命中。
        back = self._box(name='common_back')  # 模拟返回键命中框。
        result, clicked, blank_mock, _ = self._run_close(
            claim_text=text, enabled=False, back=back, back_close=False)
        self.assertFalse(result)  # 返回未处理。
        self.assertEqual([back] * self.task._MODAL_BLANK_CLOSE_ATTEMPTS, clicked)  # 按补点次数点满返回键。
        blank_mock.assert_not_called()  # 返回键在时不退回点空白。

    def test_back_button_not_consulted_without_claim_text(self):
        """「全部领取」文字未命中 = 当前帧无登录奖励界面，不查返回键（避免在正常界面上误点返回）。"""
        result, _, _, info = self._run_close(claim_text=None)
        self.assertFalse(result)  # 返回未处理。
        info['back_mock'].assert_not_called()  # 界面判据未命中时不定位返回键。

    def test_no_action_when_claim_text_missing(self):
        """「全部领取」文字未命中 = 当前帧无登录奖励弹窗，不产生任何点击。"""
        result, clicked, blank_mock, _ = self._run_close(claim_text=None)
        self.assertFalse(result)  # 返回未处理。
        self.assertEqual([], clicked)  # 不产生点击。
        blank_mock.assert_not_called()  # 也不点空白（避免在正常界面上乱点）。

    def test_skip_claim_when_mission_page_present(self):
        """任务弹窗在前时，底部「全部领取」是任务页按钮，不当作登录奖励弹窗误点。"""
        text = self._box(name='全部领取')  # 模拟任务页的「全部领取」文字框（OCR 命中也不应点）。
        clicked = []  # 收集被点击的框。
        mission = self._box(name='mission_page')  # 模拟任务弹窗标题特征命中。
        with patch.object(self.task, 'find_one', return_value=mission), \
                patch.object(self.task, 'ocr', return_value=[text]), \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'close_popup_by_blank') as blank_mock, \
                patch.object(self.task, 'sleep'):
            result = self.task._close_daily_login_popup()
        self.assertFalse(result)  # 判定为任务页而非登录奖励弹窗。
        self.assertEqual([], clicked)  # 不产生任何点击。
        blank_mock.assert_not_called()  # 也不点空白。

    def test_skip_claim_when_other_claim_all_panel_present(self):
        """其它同样带「全部领取」的面板（活动任务弹窗）由任务侧声明，命中时不当作登录奖励弹窗误点。"""
        text = self._box(name='全部领取')  # 模拟活动任务弹窗的「全部领取」文字框（OCR 命中也不应点）。
        clicked = []  # 收集被点击的框。
        with patch.object(self.task, '_other_claim_all_panel_present', return_value=True), \
                patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, 'ocr', return_value=[text]), \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'close_popup_by_blank') as blank_mock, \
                patch.object(self.task, 'sleep'):
            result = self.task._close_daily_login_popup()
        self.assertFalse(result)  # 判定为其它面板而非登录奖励弹窗。
        self.assertEqual([], clicked)  # 不产生任何点击。
        blank_mock.assert_not_called()  # 也不点空白。

    def test_claim_all_dismisses_reward_mask(self):
        """点击「全部领取」后立即清理弹出的奖励遮罩。"""
        text = self._box(name='全部领取')  # 模拟 OCR 命中的「全部领取」文字框。
        clicked = []  # 收集被点击的框。
        with patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, '_find_daily_login_claim_all', return_value=text), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'close_popup_by_blank'), \
                patch.object(self.task, 'close_overlay') as overlay_mock, \
                patch.object(self.task, 'sleep'):
            result = self.task._close_daily_login_popup()
        self.assertTrue(result)  # 返回已处理。
        self.assertEqual([text], clicked)  # 只点击一次领取按钮。
        overlay_mock.assert_called_once()  # 领取后清理一次奖励遮罩。
        kwargs = overlay_mock.call_args.kwargs  # 读取关键字参数。
        self.assertNotIn("require_click", kwargs)  # 有意不传：遮罩并非必现（可能无奖励动画），超时异常由 dismiss_all_popups 统一兜底。
        self.assertEqual(5, kwargs["time_out"])  # 给遮罩出现留出等待窗口。
        patterns = kwargs["keywords"]  # 遮罩关键词。
        self.assertTrue(any(p.search("点击领取奖励") for p in patterns))  # 覆盖领奖遮罩。
        self.assertTrue(any(p.search("点击任意处") for p in patterns))  # 覆盖任意处遮罩。

    def test_ocr_region_covers_claim_text(self):
        """OCR 区域必须覆盖「全部领取」文字在 2560x1440 基准下的实测范围。"""
        _, _, _, info = self._run_close(claim_text=self._box(name='全部领取'))
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
        _, _, _, info = self._run_close(claim_text=self._box(x=tx, y=ty, w=tw, h=th, name='全部领取'))
        expanded = info.get('expanded')  # 读取被判色的外扩框。
        self.assertIsNotNone(expanded)  # 必须做过外扩。
        self.assertNotEqual((tx, ty, tw, th),
                            (expanded.x, expanded.y, expanded.width, expanded.height))  # 确实被放大了。
        bx, by, bw, bh = self.CLAIM_BUTTON_BOX  # 按钮本体实测范围。
        self.assertGreaterEqual(expanded.x, bx)  # 不超出按钮左边界。
        self.assertLessEqual(expanded.x + expanded.width, bx + bw)  # 不超出按钮右边界。
        self.assertGreaterEqual(expanded.y, by)  # 不超出按钮上边界。
        self.assertLessEqual(expanded.y + expanded.height, by + bh)  # 不超出按钮下边界。

    def test_blank_point_outside_panel(self):
        """通用空白点击点必须落在面板之外：位于实测关闭 X 中心的右侧，且不压「全部领取」按钮。"""
        px = int(self.task._MODAL_BLANK_CLOSE_X * 2560)  # 2560x1440 基准下的像素坐标。
        py = int(self.task._MODAL_BLANK_CLOSE_Y * 1440)
        self.assertGreater(px, self.CLOSE_CENTER[0] + 200)  # 明显在关闭 X（面板右上角）右侧外。
        bx, by, bw, bh = self.CLAIM_BUTTON_BOX  # 按钮本体范围。
        self.assertFalse(bx <= px <= bx + bw and by <= py <= by + bh)  # 不落在「全部领取」按钮上。
        self.assertTrue(0 < py < 1440)  # 纵向在画面内。

    def test_try_close_one_popup_prefers_mask_over_panel(self):
        """奖励遮罩与登录奖励面板同时存在时先关遮罩（面板排在遮罩之后）。"""
        mask = self._box(name='mask')  # 模拟遮罩提示命中框。
        clicked = []  # 收集被点击的框。
        with patch.object(self.task, '_confirm_server_select', return_value=False), \
                patch.object(self.task, '_close_rupee_flash_sale_popup', return_value=False), \
                patch.object(self.task, '_close_notice_popup', return_value=False), \
                patch.object(self.task, 'ocr', return_value=[mask]) as ocr_mock, \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'close_popup_by_blank') as blank_mock, \
                patch.object(self.task, 'sleep'):
            self.assertTrue(self.task._try_close_one_popup())  # 遮罩被关闭。
        self.assertEqual([mask], clicked)  # 点击的是遮罩。
        self.assertEqual(1, ocr_mock.call_count)  # 命中遮罩后不再为面板跑第二次 OCR。
        blank_mock.assert_not_called()  # 也不点空白。

    def test_try_close_one_popup_falls_back_to_panel(self):
        """无遮罩时 _try_close_one_popup 走到登录奖励面板并点击「全部领取」。"""
        text = self._box(name='全部领取')  # 模拟 OCR 文字框。
        clicked = []  # 收集被点击的框。
        # 第一次 OCR 为遮罩分支（无遮罩），第二次为面板的「全部领取」。
        with patch.object(self.task, '_confirm_server_select', return_value=False), \
                patch.object(self.task, '_close_rupee_flash_sale_popup', return_value=False), \
                patch.object(self.task, '_close_notice_popup', return_value=False), \
                patch.object(self.task, 'ocr', side_effect=[[], [text]]), \
                patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'click_box', side_effect=lambda box, **_k: clicked.append(box)), \
                patch.object(self.task, 'close_popup_by_blank'), \
                patch.object(self.task, 'close_overlay'), \
                patch.object(self.task, 'sleep'):
            self.assertTrue(self.task._try_close_one_popup())  # 面板被处理。
        self.assertEqual([text], clicked)  # 点击的是领取按钮。


if __name__ == '__main__':
    unittest.main()
