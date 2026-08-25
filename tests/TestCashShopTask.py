import os
import unittest
from unittest.mock import patch

from src.config import config
from src.tasks.CashShopTask import CashShopTask
from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')


def _isolate_task_config(task, name):
    """把任务配置重定向到 dev_tools/test_configs 下的临时文件，避免污染真实 configs/。"""
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')
    task.config['_execution_states'] = {}


class _DebugOffTestCase(TaskTestCase):
    """基类：测试环境强制 debug=True，本基类将其屏蔽，以便验证正常的已完成/记录逻辑。"""

    def setUp(self):
        patcher = patch.object(self.task, '_in_debug', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)


def _fake_box(name, x=1, y=1, w=10, h=10):
    """构造一个用于 mock 返回的 Box。"""
    return Box(x, y, w, h, name=name)


class TestCashShopTask(_DebugOffTestCase):
    task_class = CashShopTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'CashShopTask')
        self.task.clear_done_all()

    def test_config_defaults(self):
        self.assertEqual("付费商店", self.task.name)
        self.assertEqual("自动领取付费商店中STEP UP/每日/每周/每月的免费礼包。", self.task.description)
        # 无任何用户配置项，仅保留基类的内部完成状态。
        self.assertEqual({"_execution_states"}, set(self.task.default_config.keys()))

    def test_registers_cash_shop_screen(self):
        # 标题区域 OCR 判定付费商店界面，供 assert_screen 复用。
        self.assertEqual("box_sub_pages_title", self.task.screens["cash_shop"]["ocr_box"])

    def test_enter_cash_shop_transitions_to_screen(self):
        # 迁移到 transition 原语：点击入口后由原语等待确认进入付费商店界面。
        with patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True) as wait_mock:
            self.task._enter_cash_shop()
        click_mock.assert_called_once_with("cash_shop", time_out=10, raise_if_not_found=True, after_sleep=1)
        wait_mock.assert_called_once_with("cash_shop", time_out=10)

    def test_done_keys(self):
        self.assertEqual(
            {
                "cash_shop_stepup": "day",
                "cash_shop_daily": "day",
                "cash_shop_weekly": "week",
                "cash_shop_monthly": "month",
            },
            self.task.done_keys,
        )

    def test_skip_when_all_done(self):
        self.task.mark_done("cash_shop_stepup", "day")
        self.task.mark_done("cash_shop_daily", "day")
        self.task.mark_done("cash_shop_weekly", "week")
        self.task.mark_done("cash_shop_monthly", "month")
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "_combined_step", side_effect=AssertionError("不应执行领取流程")):
            self.task.run()
        self.assertTrue(self.task.is_completed())

    def test_runs_combined_step_when_not_done(self):
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "_combined_step") as combined_mock:
            self.task.run()
        combined_mock.assert_called_once()

    def test_abort_when_lobby_not_found(self):
        with patch.object(self.task, "ensure_screen", return_value=False), \
                patch.object(self.task, "_combined_step", side_effect=AssertionError("不应执行领取流程")):
            self.task.run()
        self.assertFalse(self.task.is_done("cash_shop_stepup", "day"))

    def test_stepup_pack_buys_when_free_found(self):
        with patch.object(self.task, "_switch_nav"), \
                patch.object(self.task, "wait_feature", return_value=_fake_box("page")), \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 100, 100, 50, 50)), \
                patch.object(self.task, "wait_click_ocr", return_value=_fake_box("STEP UP")) as tab_mock, \
                patch.object(self.task, "wait_ocr", return_value=[_fake_box("免费")]) as ocr_mock, \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "dismiss_all_popups") as mask_mock:
            self.task._do_stepup_pack()
        self.assertEqual(1, tab_mock.call_count)
        ocr_mock.assert_called_once()
        self.assertEqual(1, click_mock.call_count)
        mask_mock.assert_called_once()
        self.assertTrue(self.task.is_done("cash_shop_stepup", "day"))

    def test_stepup_pack_skips_buy_when_free_not_found(self):
        with patch.object(self.task, "_switch_nav"), \
                patch.object(self.task, "wait_feature", return_value=_fake_box("page")), \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 100, 100, 50, 50)), \
                patch.object(self.task, "wait_click_ocr", return_value=_fake_box("STEP UP")), \
                patch.object(self.task, "wait_ocr", return_value=[]), \
                patch.object(self.task, "click_box", side_effect=AssertionError("不应点击")), \
                patch.object(self.task, "dismiss_all_popups"):
            self.task._do_stepup_pack()
        self.assertTrue(self.task.is_done("cash_shop_stepup", "day"))

    def test_ordinary_packs_skip_done_tabs(self):
        self.task.mark_done("cash_shop_daily", "day")
        with patch.object(self.task, "_switch_nav"), \
                patch.object(self.task, "wait_feature",
                             side_effect=lambda feature, *a, **kw: None
                             if feature == "cash_shop_free_package_sold_out" else _fake_box(feature)), \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 100, 100, 50, 50)), \
                patch.object(self.task, "wait_click_ocr",
                             return_value=_fake_box("tab")) as tab_mock, \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "dismiss_all_popups") as mask_mock:
            self.task._do_ordinary_packs()
        # 每日已完成被跳过，只点击了每周/每月两个页签。
        self.assertEqual(2, tab_mock.call_count)
        self.assertEqual(2, click_mock.call_count)
        self.assertEqual(2, mask_mock.call_count)
        self.assertTrue(self.task.is_done("cash_shop_daily", "day"))
        self.assertTrue(self.task.is_done("cash_shop_weekly", "week"))
        self.assertTrue(self.task.is_done("cash_shop_monthly", "month"))

    def test_ordinary_pack_sold_out_skips_buy(self):
        with patch.object(self.task, "_switch_nav"), \
                patch.object(self.task, "wait_feature",
                             side_effect=lambda feature, *a, **kw: _fake_box(feature)
                             if feature == "cash_shop_free_package_sold_out" else _fake_box("page")), \
                patch.object(self.task, "get_box_by_name",
                             side_effect=lambda name: _fake_box(name, 100, 100, 50, 50)), \
                patch.object(self.task, "wait_click_ocr",
                             return_value=_fake_box("tab")), \
                patch.object(self.task, "click_box", side_effect=AssertionError("售罄不应点击购买")), \
                patch.object(self.task, "dismiss_all_popups", side_effect=AssertionError("售罄不应处理遮罩")):
            self.task._do_ordinary_packs()
        # 三个页签均售罄：跳过购买但全部标记完成。
        self.assertTrue(self.task.is_done("cash_shop_daily", "day"))
        self.assertTrue(self.task.is_done("cash_shop_weekly", "week"))
        self.assertTrue(self.task.is_done("cash_shop_monthly", "month"))

    def test_combined_step_enters_and_exits(self):
        with patch.object(self.task, "_enter_cash_shop") as enter_mock, \
                patch.object(self.task, "_do_stepup_pack") as setup_mock, \
                patch.object(self.task, "_do_ordinary_packs") as ordinary_mock, \
                patch.object(self.task, "_exit_to_lobby") as exit_mock:
            self.task._combined_step()
        enter_mock.assert_called_once()
        setup_mock.assert_called_once()
        ordinary_mock.assert_called_once()
        exit_mock.assert_called_once()


if __name__ == '__main__':
    unittest.main()
