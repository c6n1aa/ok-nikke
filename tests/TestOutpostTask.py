import itertools
import os
import unittest
from unittest.mock import patch

from ok import og
from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

from ok.task.exceptions import WaitFailedException

from src.config import config
from src.tasks.OutpostTask import _ADVISE_MAX_SWITCH, _BF_LIST_OPEN_MAX_ATTEMPTS, _SINGLE_OPTION_CLICK_X, \
    OutpostTask, _normalize_answer_text, _normalize_query_name

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')


def _isolate_task_config(task, name):
    """把任务配置重定向到 dev_tools/test_configs 下的临时文件，避免污染真实 configs/。"""
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')
    task.config['_execution_states'] = {}


def _named_box(name):
    """构造带特征名的占位框，供 get_box_by_name 桩按名分发与点击断言。"""
    return Box(0, 0, 10, 10, confidence=1, name=name)


def _text_box(text):
    """构造带 OCR 文本的占位框，模拟 ocr() 的返回项。"""
    return Box(0, 0, 10, 10, confidence=1, name=text)


class _DebugOffTestCase(TaskTestCase):
    """基类：测试环境强制 debug=True，本基类将其屏蔽，以便验证正常的已完成/记录逻辑。"""

    def setUp(self):
        patcher = patch.object(self.task, '_in_debug', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestOutpostTaskMeta(_DebugOffTestCase):
    """元数据/注册表/纯函数测试，不触达子流程。"""

    task_class = OutpostTask

    config = config

    def test_config_defaults(self):
        self.assertEqual("前哨基地", self.task.name)
        self.assertEqual("执行派遣/咨询/突发剧情任务", self.task.description)
        self.assertTrue(self.task.default_config["派遣"])
        self.assertTrue(self.task.default_config["咨询"])
        self.assertTrue(self.task.default_config["突发剧情"])
        self.assertTrue(self.task.default_config["只咨询星标"])
        self.assertFalse(self.task.default_config["补齐咨询日志"])
        self.assertEqual({"bulletin_board": "day", "advise": "day", "brief_encounter": "week"},
                         OutpostTask.done_keys)
        sub = self.task.config_type["咨询"]["sub_configs"]  # 开关联动子配置显隐。
        self.assertEqual(["只咨询星标", "补齐咨询日志"], sub[True])
        self.assertEqual([], sub[False])
        self.assertIn("派遣", self.task.config_description)
        self.assertIn("突发剧情", self.task.config_description)
        self.assertIn("只咨询星标", self.task.config_description)
        self.assertIn("补齐咨询日志", self.task.config_description)

    def test_is_completed_only_counts_enabled(self):
        _isolate_task_config(self.task, 'OutpostTask')
        self.task.config["派遣"] = True  # 配置可能被真实 configs/ 带偏（未重置为默认），显式对齐默认口径。
        self.task.config["咨询"] = True
        self.task.config["突发剧情"] = True
        self.task.clear_done_all()
        self.assertFalse(self.task.is_completed())
        self.task.mark_done("bulletin_board", "day")
        self.assertFalse(self.task.is_completed())  # 咨询尚未完成。
        self.task.mark_done("advise", "day")
        self.assertFalse(self.task.is_completed())  # 突发剧情尚未完成。
        self.task.mark_done("brief_encounter", "week")
        self.assertTrue(self.task.is_completed())
        self.task.config["突发剧情"] = False  # 关闭突发剧情后只统计派遣与咨询。
        self.assertTrue(self.task.is_completed())
        self.task.config["咨询"] = False  # 关闭咨询后只统计派遣。
        self.assertTrue(self.task.is_completed())
        self.task.config["派遣"] = False
        self.assertFalse(self.task.is_completed())  # 全部关闭视为未完成。

    def test_screens_registered(self):
        self.assertEqual(["command_center"], self.task.screens["outpost"]["features"])
        self.assertEqual(["前哨基地"], self.task.screens["outpost"]["keywords"])
        self.assertEqual("box_sub_pages_title", self.task.screens["outpost"]["ocr_box"])
        self.assertEqual(["指挥中心"], self.task.screens["command_center"]["keywords"])
        self.assertEqual("box_sub_pages_title", self.task.screens["command_center"]["ocr_box"])
        self.assertEqual(["advise_page_icon"], self.task.screens["advise"]["features"])
        self.assertEqual(["咨询"], self.task.screens["advise"]["keywords"])
        self.assertEqual(["advise_detail_page", "advise_gift"], self.task.screens["advise_nikke"]["features"])
        self.assertEqual(["conversation_cancel", "conversation_log", "conversation_skip"],
                         self.task.screens["conversation"]["any_features"])
        self.assertEqual("box_conversation_icon", self.task.screens["conversation"]["feature_box"])

    def test_normalize_helpers(self):
        self.assertEqual("D", _normalize_query_name("D。"))  # 尾部标点折叠为通配符后收拢。
        self.assertEqual("Rapi%Red%Hood", _normalize_query_name("Rapi: Red Hood"))  # 内部标点转通配符。
        self.assertEqual("", _normalize_query_name("!!!"))  # 全标点名称视为空。
        self.assertEqual("", _normalize_query_name(None))
        self.assertEqual("好的交给我吧", _normalize_answer_text("好的，交给我吧！"))  # 去标点。
        self.assertEqual("", _normalize_answer_text(None))

    def test_advise_locale_mapping(self):
        for raw, expected in [("zh_CN", "zh_CN"), ("zh_TW", "zh_TW"), ("zh_HK", "zh_TW"),
                              ("en_US", "en"), ("ja_JP", "ja"), ("ko_KR", "")]:
            with patch.object(self.task.executor, "locale", raw):
                self.assertEqual(expected, self.task._advise_locale(), raw)

    def test_query_advise_rows_from_real_db(self):
        with patch.object(self.task, "_advise_locale", return_value="zh_CN"):
            rows = self.task._query_advise_rows("D")
        self.assertTrue(rows)  # 真库可查到角色 D 的咨询条目。
        self.assertEqual(3, len(rows[0]))  # (prompt, good, bad) 三元组。
        with patch.object(self.task, "_advise_locale", return_value="zh_CN"):
            self.assertEqual(rows, self.task._query_advise_rows("D。"))  # 尾部标点不影响查询结果。
        with patch.object(self.task, "_advise_locale", return_value="zh_CN"):
            self.assertTrue(self.task._query_advise_rows("拉毗:小红帽"))  # 内部标点转通配符后命中全名角色。
        with patch.object(self.task, "_advise_locale", return_value=""):
            self.assertEqual([], self.task._query_advise_rows("D"))  # 语言不支持返回空。
        with patch.object(self.task, "_advise_locale", return_value="zh_CN"):
            self.assertEqual([], self.task._query_advise_rows(""))  # 名称为空返回空。

    def test_advise_count_zero(self):
        with patch.object(self.task, "get_box_by_name", return_value=_named_box("box_advise_count")), \
                patch.object(self.task, "ocr", return_value=[_text_box("0/10")]):
            self.assertTrue(self.task._advise_count_zero())
        with patch.object(self.task, "get_box_by_name", return_value=_named_box("box_advise_count")), \
                patch.object(self.task, "ocr", return_value=[_text_box("O/10")]):
            self.assertTrue(self.task._advise_count_zero())  # OCR 把分子的 0 误识为 O 时仍判用尽。
        with patch.object(self.task, "get_box_by_name", return_value=_named_box("box_advise_count")), \
                patch.object(self.task, "ocr", return_value=[_text_box("10/10")]):
            self.assertFalse(self.task._advise_count_zero())  # "10/10" 不能因子串包含被误判为 0。
        with patch.object(self.task, "get_box_by_name", return_value=_named_box("box_advise_count")), \
                patch.object(self.task, "ocr", return_value=[_text_box("咨询 5/10")]):
            self.assertFalse(self.task._advise_count_zero())
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")):
            self.assertFalse(self.task._advise_count_zero())  # 区域缺失视为未用尽，交由切换上限兜底。


class TestOutpostTaskRun(_DebugOffTestCase):
    """run 入口编排测试。"""

    task_class = OutpostTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'OutpostTask')
        self.task.config["派遣"] = True
        self.task.config["咨询"] = True
        self.task.config["突发剧情"] = True
        self.task.clear_done_all()

    def test_skip_when_all_disabled(self):
        self.task.config["派遣"] = False
        self.task.config["咨询"] = False
        self.task.config["突发剧情"] = False
        with patch.object(self.task, "try_step",
                          side_effect=AssertionError("全部关闭时不应进入前哨基地")):
            self.task.run()

    def test_skip_when_all_done(self):
        self.task.mark_done("bulletin_board", "day")
        self.task.mark_done("advise", "day")
        self.task.mark_done("brief_encounter", "week")
        with patch.object(self.task, "try_step",
                          side_effect=AssertionError("全部完成时不应进入前哨基地")):
            self.task.run()

    def test_abort_when_outpost_entry_fails(self):
        with patch.object(self.task, "try_step", return_value=False), \
                patch.object(self.task, "_do_dispatch",
                             side_effect=AssertionError("未进入前哨基地不应执行子流程")):
            self.task.run()

    def test_runs_subflows_in_order(self):
        order = []
        with patch.object(self.task, "try_step", return_value=True), \
                patch.object(self.task, "_do_dispatch",
                             side_effect=lambda: order.append("dispatch")), \
                patch.object(self.task, "_do_advise",
                             side_effect=lambda: order.append("advise")), \
                patch.object(self.task, "_do_brief_encounter",
                             side_effect=lambda: order.append("brief_encounter")), \
                patch.object(self.task, "_exit_to_lobby"):
            self.task.run()
        self.assertEqual(["dispatch", "brief_encounter", "advise"], order)


class TestOutpostTaskDispatch(_DebugOffTestCase):
    """派遣子流程测试：覆盖成功/跳过/失败/已完成跳过分支。"""

    task_class = OutpostTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'OutpostTask')
        self.task.config["派遣"] = True
        self.task.config["咨询"] = False
        self.task.clear_done_all()

    def _run_flow(self, enabled_side_effect):
        """公共补丁栈执行 _dispatch_flow，返回各 mock 便于断言。"""
        with patch.object(self.task, "_nav_to_outpost") as nav_mock, \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_ocr", return_value=[_text_box("派遣公告栏")]) as ocr_mock, \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "is_feature_enabled", side_effect=enabled_side_effect), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "assert_screen") as assert_mock, \
                patch.object(self.task, "sleep"):
            self.task._dispatch_flow()
        return nav_mock, click_mock, ocr_mock, click_box_mock, dismiss_mock, assert_mock

    def test_flow_claim_then_send(self):
        nav_mock, click_mock, ocr_mock, click_box_mock, dismiss_mock, assert_mock = \
            self._run_flow([True, True])  # 领取与全部派遣均可用。
        clicked_boxes = [c.args[0].name for c in click_box_mock.call_args_list]
        self.assertEqual(["box_bulletin_board_claim_feature", "box_bulletin_board_send_all_feature"],
                         clicked_boxes)  # 先领取再全部派遣。
        clicked_features = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual(["bulletin_board", "bulletin_board_send_all_confirm", "bulletin_board_windows_close"],
                         clicked_features)  # 进公告栏→确认派遣→关闭窗口。
        dismiss_mock.assert_called_once()  # 领取后清理奖励弹窗。
        nav_mock.assert_called_once()  # 入口闸门只进入一次。
        assert_mock.assert_called_once_with("outpost", time_out=10)  # 关闭后确认回到前哨基地。
        self.assertEqual("box_bulletin_board_title", ocr_mock.call_args.kwargs["box"].name)  # 标题 OCR 限定区域。

    def test_flow_no_claim_no_send(self):
        nav_mock, click_mock, _, click_box_mock, dismiss_mock, assert_mock = \
            self._run_flow([False, False])  # 领取与全部派遣均不可用。
        click_box_mock.assert_not_called()  # 不发生任何按钮点击。
        clicked_features = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual(["bulletin_board", "bulletin_board_windows_close"],
                         clicked_features)  # 仅进公告栏并关闭窗口。
        dismiss_mock.assert_not_called()
        nav_mock.assert_called_once()  # 入口闸门只进入一次。
        assert_mock.assert_called_once_with("outpost", time_out=10)  # 关闭后确认回到前哨基地。

    def test_flow_claim_only(self):
        nav_mock, click_mock, _, click_box_mock, dismiss_mock, _ = \
            self._run_flow([True, False])  # 仅领取可用。
        self.assertEqual(["box_bulletin_board_claim_feature"],
                         [c.args[0].name for c in click_box_mock.call_args_list])
        self.assertEqual(["bulletin_board", "bulletin_board_windows_close"],
                         [c.args[0] for c in click_mock.call_args_list])  # 无全部派遣时不点确认。
        dismiss_mock.assert_called_once()
        nav_mock.assert_called_once()  # 入口闸门只进入一次。

    def test_do_dispatch_marks_done(self):
        with patch.object(self.task, "_nav_to_outpost"), \
                patch.object(self.task, "wait_click_feature"), \
                patch.object(self.task, "wait_ocr", return_value=[_text_box("派遣公告栏")]), \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "is_feature_enabled", side_effect=[False, False]), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "dismiss_all_popups"), \
                patch.object(self.task, "assert_screen"), \
                patch.object(self.task, "sleep"):
            self.task._do_dispatch()
        self.assertTrue(self.task.is_done("bulletin_board", "day"))

    def test_do_dispatch_failure_not_marked_done(self):
        with patch.object(self.task, "try_step", return_value=False) as try_mock:
            self.task._do_dispatch()
        try_mock.assert_called_once()
        self.assertFalse(self.task.is_done("bulletin_board", "day"))

    def test_do_dispatch_skips_when_done(self):
        self.task.mark_done("bulletin_board", "day")
        with patch.object(self.task, "_dispatch_flow",
                          side_effect=AssertionError("已完成不应再执行流程")):
            self.task._do_dispatch()

    def test_do_dispatch_skips_when_disabled(self):
        self.task.config["派遣"] = False
        with patch.object(self.task, "_dispatch_flow",
                          side_effect=AssertionError("未开启不应执行流程")):
            self.task._do_dispatch()


class TestOutpostTaskAdvise(_DebugOffTestCase):
    """咨询子流程测试：覆盖成功/跳过/失败/已完成跳过及各判断分支。"""

    task_class = OutpostTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'OutpostTask')
        self.task.config["派遣"] = False
        self.task.config["咨询"] = True
        self.task.config["只咨询星标"] = False
        self.task.config["补齐咨询日志"] = False
        self.task.clear_done_all()

    def test_do_advise_marks_done(self):
        with patch.object(self.task, "_enter_advise"), \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "is_feature_enabled", side_effect=[False]), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "_exit_advise_to_lobby"), \
                patch.object(self.task, "sleep"):
            self.task._do_advise()  # 无剩余咨询次数也算流程成功，标记完成。
        self.assertTrue(self.task.is_done("advise", "day"))

    def test_do_advise_failure_not_marked_done(self):
        with patch.object(self.task, "try_step", return_value=False):
            self.task._do_advise()
        self.assertFalse(self.task.is_done("advise", "day"))

    def test_do_advise_skips_when_done_or_disabled(self):
        self.task.mark_done("advise", "day")
        with patch.object(self.task, "_advise_flow",
                          side_effect=AssertionError("已完成不应再执行流程")):
            self.task._do_advise()
        self.task.clear_done("advise")
        self.task.config["咨询"] = False
        with patch.object(self.task, "_advise_flow",
                          side_effect=AssertionError("未开启不应执行流程")):
            self.task._do_advise()

    def test_flow_count_unavailable_ends(self):
        with patch.object(self.task, "_enter_advise") as enter_mock, \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "is_feature_enabled", side_effect=[False]), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "find_one",
                             side_effect=AssertionError("无次数不应继续识别")), \
                patch.object(self.task, "_exit_advise_to_lobby") as exit_mock, \
                patch.object(self.task, "sleep"):
            self.task._advise_flow()
        enter_mock.assert_called_once()  # 入口拆分：先单独进入咨询界面。
        click_box_mock.assert_not_called()  # 无剩余次数不点角色。
        exit_mock.assert_called_once()  # 直接返回大厅标记完成。

    def test_flow_star_not_starred_ends(self):
        self.task.config["只咨询星标"] = True
        with patch.object(self.task, "_enter_advise"), \
                patch.object(self.task, "assert_screen"), \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "is_feature_enabled", side_effect=[True, False]), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "find_one",
                             side_effect=AssertionError("未星标不应继续识别好感度")), \
                patch.object(self.task, "_read_advise_name", return_value="拉毗"), \
                patch.object(self.task, "_advise_once",
                             side_effect=AssertionError("未星标不应咨询")), \
                patch.object(self.task, "_exit_advise_to_lobby") as exit_mock, \
                patch.object(self.task, "sleep"):
            self.task._advise_flow()
        exit_mock.assert_called_once()

    def test_flow_full_round_advises_then_count_zero_ends(self):
        advise_box = _named_box("box_advise_feature")
        with patch.object(self.task, "_enter_advise"), \
                patch.object(self.task, "assert_screen"), \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "is_feature_enabled", side_effect=[True, True]), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "_read_advise_name", return_value="拉毗"), \
                patch.object(self.task, "_advise_once") as advise_once_mock, \
                patch.object(self.task, "_advise_count_zero", return_value=True), \
                patch.object(self.task, "_exit_advise_to_lobby") as exit_mock, \
                patch.object(self.task, "sleep"):
            self.task._advise_flow()
        advise_once_mock.assert_called_once()  # 恰好咨询一次。
        self.assertEqual("拉毗", advise_once_mock.call_args.args[0])
        self.assertEqual("box_advise_feature", advise_once_mock.call_args.args[1].name)
        exit_mock.assert_called_once()  # 次数用尽直接返回大厅。

    def test_flow_bond_max_progress_skips_without_advise(self):
        self.task.config["补齐咨询日志"] = True
        bond_box = _named_box("advise_bond_max")
        with patch.object(self.task, "_enter_advise"), \
                patch.object(self.task, "assert_screen"), \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "is_feature_enabled", side_effect=[True, True, True]), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "find_one", side_effect=[bond_box, None]), \
                patch.object(self.task, "_read_advise_name", side_effect=["A", "B", "B"]), \
                patch.object(self.task, "_advise_once") as advise_once_mock, \
                patch.object(self.task, "_advise_count_zero", return_value=True), \
                patch.object(self.task, "_exit_advise_to_lobby") as exit_mock, \
                patch.object(self.task, "sleep"):
            self.task._advise_flow()
        advise_once_mock.assert_called_once()  # 仅第二个角色被咨询。
        self.assertEqual("B", advise_once_mock.call_args.args[0])
        self.assertEqual(["advise_next"],  # 第一个角色（图鉴已完成）直接切换下一个。
                         [c.args[0].name for c in click_box_mock.call_args_list
                          if c.args[0].name == "advise_next"])
        exit_mock.assert_called_once()

    def test_flow_switch_retry_cleans_popups_then_ends(self):
        with patch.object(self.task, "_enter_advise"), \
                patch.object(self.task, "assert_screen"), \
                patch.object(self.task, "wait_screen", return_value=True) as wait_screen_mock, \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "is_feature_enabled", side_effect=[True, True]), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "_read_advise_name", return_value="拉毗"), \
                patch.object(self.task, "_advise_once"), \
                patch.object(self.task, "_advise_count_zero", return_value=False), \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "_exit_advise_to_lobby") as exit_mock, \
                patch.object(self.task, "sleep"):
            self.task._advise_flow()
        next_clicks = [c for c in click_box_mock.call_args_list if c.args[0].name == "advise_next"]
        self.assertEqual(5, len(next_clicks))  # 名称未变更最多重试 5 次。
        self.assertEqual(5, dismiss_mock.call_count)  # 每次重试前清理弹窗。
        for call in dismiss_mock.call_args_list:
            self.assertFalse(call.kwargs["wait_for_popup"])  # 快速清理语义。
        self.assertEqual(10, wait_screen_mock.call_count)  # 每次重试点后确认一次、清理后复核一次。
        for call in wait_screen_mock.call_args_list:
            self.assertEqual(("advise_nikke",), call.args)  # 复核以咨询详情页特征在场为准。
        exit_mock.assert_called_once()  # 无法切换时优雅结束。

    def test_switch_advise_nikke_rechecks_after_popup_dismiss(self):
        # 延迟弹出的好感度升级遮罩盖住已切换的新详情页：点击其实已生效，特征被压暗导致首轮确认失败；
        # 清理遮罩后复核成功，不得再补点（补点会跳过当前角色）。
        with patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_screen", side_effect=[False, True]), \
                patch.object(self.task, "_read_advise_name", return_value="白雪公主"), \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock:
            self.assertTrue(self.task._switch_advise_nikke("拉毗"))
        click_mock.assert_called_once()  # 清理后复核已成功，不得补点跳过角色。
        dismiss_mock.assert_called_once_with(wait_for_popup=False, time_out=5)  # 确认失败后清理遮罩。

    def test_enter_advise_navigates_and_confirms(self):
        # 入口拆分：前哨基地→指挥中心→咨询入口，确认到达[咨询]列表页。
        with patch.object(self.task, "_nav_to_outpost") as nav_mock, \
                patch.object(self.task, "wait_click_feature") as click_feature_mock, \
                patch.object(self.task, "transition") as transition_mock, \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "assert_screen") as assert_mock:
            self.task._enter_advise()
        nav_mock.assert_called_once()  # 先就位前哨基地。
        self.assertEqual("command_center", click_feature_mock.call_args.args[0])  # 点指挥中心建筑。
        transition_mock.assert_called_once_with(
            "command_center", click_feature="command_center_enter", wait_confirm=10, after_sleep=1)
        self.assertEqual("box_command_center_advise_enter", click_box_mock.call_args.args[0].name)  # 点咨询入口。
        assert_mock.assert_called_once_with("advise", time_out=10)  # 确认到达咨询列表页。

    def test_exit_advise_to_lobby_delegates(self):
        # 出口拆分：咨询结束直接返回大厅，委托基类幂等收尾（含主页按钮坐标偏移兜底与延迟遮罩重试）。
        with patch.object(self.task, "_exit_to_lobby") as exit_mock:
            self.task._exit_advise_to_lobby()
        exit_mock.assert_called_once_with()

    def test_flow_switch_cap_force_ends(self):
        counter = itertools.count()  # 每次读取返回新名称，模拟一直能切换成功。
        with patch.object(self.task, "_enter_advise"), \
                patch.object(self.task, "assert_screen"), \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "is_feature_enabled", side_effect=lambda box: True), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "_read_advise_name",
                             side_effect=lambda: f"角色{next(counter)}"), \
                patch.object(self.task, "_advise_once"), \
                patch.object(self.task, "_advise_count_zero", return_value=False), \
                patch.object(self.task, "_exit_advise_to_lobby") as exit_mock, \
                patch.object(self.task, "sleep"):
            self.task._do_advise()  # 经 try_step 成功路径标记完成。
        next_clicks = [c for c in click_box_mock.call_args_list if c.args[0].name == "advise_next"]
        self.assertEqual(31, len(next_clicks))  # 切换 31 次后触发上限强行结束。
        exit_mock.assert_called_once()
        self.assertTrue(self.task.is_done("advise", "day"))  # 强行结束视为流程完成。

    def test_switch_cap_constant(self):
        self.assertEqual(30, _ADVISE_MAX_SWITCH)  # 切换上限与简报一致。


class TestOutpostTaskAdviseOnce(_DebugOffTestCase):
    """单次咨询（_advise_once/_answer_conversation）测试。"""

    task_class = OutpostTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'OutpostTask')

    def test_advise_once_sequence(self):
        advise_box = _named_box("box_advise_feature")
        rows = [("提问", "好答案", "坏答案")]
        with patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_click_feature") as click_feature_mock, \
                patch.object(self.task, "_query_advise_rows", return_value=rows) as query_mock, \
                patch.object(self.task, "assert_screen") as assert_mock, \
                patch.object(self.task, "_answer_conversation") as answer_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "sleep"):
            self.task._advise_once("拉毗", advise_box)
        click_mock.assert_called_once_with(advise_box, after_sleep=1)  # 点击咨询按钮。
        clicked_features = [c.args[0] for c in click_feature_mock.call_args_list]
        self.assertEqual(["advise_confirm", "conversation_skip"], clicked_features)  # 确认弹窗→跳过对话。
        skip_call = click_feature_mock.call_args_list[-1]
        self.assertEqual("box_conversation_icon", skip_call.kwargs["box"].name)  # 跳过按钮限定在对话图标区。
        dismiss_mock.assert_called_once_with(wait_for_popup=False, time_out=5)  # 跳过后先清好感度提升遮罩再断言回详情页。
        query_mock.assert_called_once_with("拉毗")  # 以角色名查询答案库。
        self.assertEqual([("conversation",), ("advise_nikke",)],
                         [c.args for c in assert_mock.call_args_list])  # 等谈话界面→确认回详情。
        answer_mock.assert_called_once_with(rows)

    def _answer_with(self, find_one_side_effect, ocr_boxes, rows, time_side_effect=None):
        """公共补丁栈执行 _answer_conversation，返回 click_relative/click_box mock。"""
        with patch.object(self.task, "get_box_by_name",
                          side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "find_one", side_effect=find_one_side_effect), \
                patch.object(self.task, "click_relative") as relative_mock, \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "ocr", return_value=ocr_boxes), \
                patch.object(self.task, "sleep"), \
                patch("src.tasks.OutpostTask.time") as time_mock:
            time_mock.time.side_effect = time_side_effect if time_side_effect is not None \
                else itertools.count(step=0.1)  # 默认单调递增时钟，避免超时误触发。
            self.task._answer_conversation(rows)
        return relative_mock, click_mock

    def test_answer_clicks_heart_when_visible(self):
        option1 = _named_box("advise_option1")
        option2 = _named_box("advise_option2")
        heart = _named_box("advise_option_heart")
        relative_mock, click_mock = self._answer_with(
            [None, None, option1, option2, heart], [], [])  # 第一轮无选项→点空白→第二轮出现选项与爱心。
        relative_mock.assert_called_once_with(0.7, 0.85, after_sleep=0.5)  # 点空白推进对话。
        click_mock.assert_called_once_with(heart, after_sleep=1)  # 爱心可见直接点爱心。

    def test_answer_matches_good_answer_precisely(self):
        option1 = _named_box("advise_option1")
        option2 = _named_box("advise_option2")
        text_good = _text_box("好的，交给我吧！")
        text_bad = _text_box("还是算了吧")
        rows = [("提问", "好的交给我吧", "还是算了吧")]
        _, click_mock = self._answer_with(
            [None, None, option1, option2, None], [text_good, text_bad], rows)
        click_mock.assert_called_once_with(text_good, after_sleep=1)  # 同行 good/bad 精准命中。

    def test_answer_excludes_bad_answer(self):
        option1 = _named_box("advise_option1")
        option2 = _named_box("advise_option2")
        text_other = _text_box("好的，交给我吧！")
        text_bad = _text_box("还是算了吧")
        rows = [("提问", "完全不同的回答", "还是算了吧")]  # good 与 OCR 不符，仅 bad 可排除。
        _, click_mock = self._answer_with(
            [None, None, option1, option2, None], [text_other, text_bad], rows)
        click_mock.assert_called_once_with(text_other, after_sleep=1)  # 命中 bad 即选另一个。

    def test_answer_random_when_no_rows(self):
        option1 = _named_box("advise_option1")
        option2 = _named_box("advise_option2")
        text_a = _text_box("答案甲")
        text_b = _text_box("答案乙")
        _, click_mock = self._answer_with(
            [None, None, option1, option2, None], [text_a, text_b], [])  # 无查询结果随机二选一。
        self.assertEqual(1, click_mock.call_count)
        self.assertIn(click_mock.call_args.args[0], [text_a, text_b])

    def test_answer_random_option_box_when_ocr_empty(self):
        option1 = _named_box("advise_option1")
        option2 = _named_box("advise_option2")
        _, click_mock = self._answer_with(
            [option1, option2, None], [], [("提问", "好", "坏")])  # OCR 未读到文本。
        self.assertEqual(1, click_mock.call_count)
        self.assertIn(click_mock.call_args.args[0], [option1, option2])  # 随机点选项框兜底。

    def test_answer_clicks_single_option_to_advance(self):
        option1 = Box(938, 1067, 23, 22, confidence=1, name="advise_option1")
        option2 = Box(938, 1043, 23, 22, confidence=1, name="advise_option2")
        # 第1拍只出现选项1开始计时（静候不点空白避免抖动漏检）；第2拍仍单个且超过确认窗口→点击推进；第3拍双框出现进入作答。
        with patch.object(self.task, "get_box_by_name",
                          side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "find_one",
                             side_effect=[option1, None, option1, None, option1, option2, None]), \
                patch.object(self.task, "click_relative") as relative_mock, \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "sleep") as sleep_mock, \
                patch("src.tasks.OutpostTask.time") as time_mock:
            time_mock.time.side_effect = [100, 100, 101.5, 102]
            self.task._answer_conversation([])
        relative_mock.assert_not_called()  # 单框在场时不点空白，避免抖动漏检单框。
        sleep_mock.assert_called_once_with(0.5)  # 确认窗口内静候复检直到单框持续在场。
        self.assertEqual(2, click_mock.call_count)  # 推进点击 + 作答点击（无 rows 走随机兜底）。
        first = click_mock.call_args_list[0]
        self.assertIs(first.args[0], option1)  # 直接点匹配到的角标框。
        self.assertEqual(_SINGLE_OPTION_CLICK_X, first.kwargs["relative_x"])  # 框内相对 X 右移点框体。
        self.assertEqual(1, first.kwargs["after_sleep"])

    def test_answer_waits_confirm_window_before_single_click(self):
        option1 = _named_box("advise_option1")
        option2 = _named_box("advise_option2")
        # 单框刚出现未过确认窗口就出现双框：不能误点第一框，静候后双框出现直接进入作答。
        relative_mock, click_mock = self._answer_with(
            [option1, None, option1, option2, None], [], [("提问", "好", "坏")],
            time_side_effect=[100, 100, 100.2, 100.2])
        relative_mock.assert_not_called()  # 单框在场时不点空白，避免抖动漏检单框。
        click_mock.assert_called_once()  # 只有作答点击，没有推进点击。


class TestOutpostTaskBriefEncounter(_DebugOffTestCase):
    """突发剧情子流程测试：覆盖跳过/次数用尽/空列表/逐条清理/展开失败分支。"""

    task_class = OutpostTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'OutpostTask')
        self.task.config["突发剧情"] = True
        self.task.clear_done_all()

    def _run_flow(self, ocr_boxes_per_call, enabled_side_effect):
        """公共补丁栈经 try_step 执行突发剧情子流程（成功路径），返回各 mock 便于断言。"""
        with patch.object(self.task, "_nav_to_outpost"), \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "ocr", side_effect=ocr_boxes_per_call), \
                patch.object(self.task, "is_feature_enabled",
                             side_effect=enabled_side_effect) as enabled_mock, \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "wait_click_feature") as click_feature_mock, \
                patch.object(self.task, "wait_until",
                             return_value=_named_box("command_center_close")), \
                patch.object(self.task, "assert_screen") as assert_mock, \
                patch.object(self.task, "dismiss_all_popups") as dismiss_mock, \
                patch.object(self.task, "sleep"):
            self.task._do_brief_encounter()
        return enabled_mock, click_box_mock, click_feature_mock, assert_mock, dismiss_mock

    def test_count_zero_ends_and_marks_done(self):
        enabled_mock, click_box_mock, click_feature_mock, _, dismiss_mock = self._run_flow(
            [[_text_box("0/5")]], AssertionError("0/5 已用尽不应再判列表状态"))
        enabled_mock.assert_not_called()  # 0/5 用尽不再判列表状态。
        click_box_mock.assert_not_called()  # 不发生任何点击。
        click_feature_mock.assert_not_called()
        dismiss_mock.assert_not_called()
        self.assertTrue(self.task.is_done("brief_encounter", "week"))  # 标记本周完成。

    def test_card1_empty_ends_and_marks_done(self):
        enabled_mock, click_box_mock, click_feature_mock, _, dismiss_mock = self._run_flow(
            [[_text_box("5/5")], []], [True])  # 列表已在展开态，卡片区域无文字。
        enabled_mock.assert_called_once()  # 判一次展开态即继续。
        click_box_mock.assert_not_called()  # 无可触发条目不发生点击。
        click_feature_mock.assert_not_called()
        dismiss_mock.assert_not_called()
        self.assertTrue(self.task.is_done("brief_encounter", "week"))

    def test_opens_list_by_click_when_grey(self):
        enabled_mock, click_box_mock, _, _, _ = self._run_flow(
            [[_text_box("5/5")], []], [False, True])  # 首次灰色未展开：点击后复核转蓝色高亮。
        self.assertEqual(2, enabled_mock.call_count)  # 判灰→点击→复核为蓝。
        self.assertEqual(["box_outpost_bf_list"],
                         [c.args[0].name for c in click_box_mock.call_args_list])  # 仅点一次气泡。
        self.assertTrue(self.task.is_done("brief_encounter", "week"))

    def test_clears_all_then_count_zero(self):
        ocr_seq = [[_text_box("5/5")], [_text_box("休息不像休息")],  # 第 1 轮：有次数有可触发条目。
                   [_text_box("1/5")], [_text_box("凶猛的兔子士兵")],  # 第 2 轮：继续清理。
                   [_text_box("0/5")]]  # 第 3 轮：用尽结束。
        _, click_box_mock, click_feature_mock, assert_mock, dismiss_mock = \
            self._run_flow(ocr_seq, [True, True])  # 两轮均处于展开态。
        clicked = [c.args[0].name for c in click_box_mock.call_args_list]
        self.assertEqual(["box_outpost_bf_card1", "box_outpost_bf_entry", "command_center_close"] * 2,
                         clicked)  # 每轮：点卡片→点进入→点关闭。
        clicked_features = [c.args[0] for c in click_feature_mock.call_args_list]
        self.assertEqual(["outpost_bf_confirm", "conversation_skip"] * 2,
                         clicked_features)  # 每轮：点确认进入→点跳过对话。
        skip_call = click_feature_mock.call_args_list[1]
        self.assertEqual("box_conversation_icon", skip_call.kwargs["box"].name)  # 跳过限定在对话图标区。
        self.assertEqual([("conversation",)] * 2,
                         [c.args for c in assert_mock.call_args_list])  # 每轮确认进入[谈话]界面。
        self.assertEqual(2, dismiss_mock.call_count)  # 每轮清理一次奖励弹窗。
        for call in dismiss_mock.call_args_list:
            self.assertTrue(call.kwargs.get("wait_for_popup", True))  # 奖励弹窗必定出现，走等待式清理（默认 wait_for_popup=True）。
        self.assertTrue(self.task.is_done("brief_encounter", "week"))  # 用尽后标记本周完成。

    def test_list_open_failure_raises(self):
        with patch.object(self.task, "_nav_to_outpost"), \
                patch.object(self.task, "get_box_by_name", side_effect=lambda name: _named_box(name)), \
                patch.object(self.task, "ocr", return_value=[_text_box("5/5")]), \
                patch.object(self.task, "is_feature_enabled", return_value=False), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "sleep"):
            with self.assertRaises(WaitFailedException):  # 反复点击仍不展开视为失败，抛异常交 try_step。
                self.task._brief_encounter_flow()
        clicks = [c.args[0].name for c in click_box_mock.call_args_list]
        self.assertEqual(["box_outpost_bf_list"] * _BF_LIST_OPEN_MAX_ATTEMPTS,
                         clicks)  # 有限次点击后放弃。

    def test_do_brief_encounter_failure_not_marked_done(self):
        with patch.object(self.task, "try_step", return_value=False):
            self.task._do_brief_encounter()
        self.assertFalse(self.task.is_done("brief_encounter", "week"))

    def test_do_brief_encounter_skips_when_done_or_disabled(self):
        self.task.mark_done("brief_encounter", "week")
        with patch.object(self.task, "_brief_encounter_flow",
                          side_effect=AssertionError("已完成不应再执行流程")):
            self.task._do_brief_encounter()
        self.task.clear_done("brief_encounter")
        self.task.config["突发剧情"] = False
        with patch.object(self.task, "_brief_encounter_flow",
                          side_effect=AssertionError("未开启不应执行流程")):
            self.task._do_brief_encounter()


class TestOutpostDailyIntegration(_DebugOffTestCase):
    """验证日常编排：前哨基地开关开启时 DailyTask 调度 OutpostTask，关闭则跳过。"""

    task_class = OutpostTask

    config = config

    def _build_daily(self):
        from ok.test import ok

        from src.tasks.DailyTask import DailyTask
        daily = DailyTask(og.executor, None)  # 与 TestArkTask 集成测试同款构造方式。
        daily.after_init(executor=ok.task_executor, scene=ok.task_executor.scene)
        _isolate_task_config(daily, 'DailyTask')
        return daily

    def test_daily_dispatches_outpost_by_switch(self):
        daily = self._build_daily()
        self.assertTrue(daily.default_config["前哨基地"])  # 日常默认开启前哨基地。
        with patch.object(daily, "ensure_screen", return_value=True), \
                patch.object(daily, "run_task_by_class") as run_mock, \
                patch.object(daily, "_daily_end_flow"):  # 收尾流程会真实抓帧/置前窗口，必须拦截（不碰真实环境）。
            daily.config["前哨基地"] = True
            daily.run()
            self.assertIn(OutpostTask, [c.args[0] for c in run_mock.call_args_list])  # 开启时被调度。
            run_mock.reset_mock()
            daily.config["前哨基地"] = False
            daily.run()
            self.assertNotIn(OutpostTask, [c.args[0] for c in run_mock.call_args_list])  # 关闭后跳过。


if __name__ == '__main__':
    unittest.main()
