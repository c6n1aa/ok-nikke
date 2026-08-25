import os
import unittest
from unittest.mock import patch

from src.config import config
from src.tasks.ShopTask import ShopTask
from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')


def _isolate_task_config(task, name):
    """把任务配置重定向到 dev_tools/test_configs 下的临时文件，避免污染真实 configs/。"""
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')
    task.config['_execution_states'] = {}


class TestShopTask(TaskTestCase):
    task_class = ShopTask

    config = config

    def setUp(self):
        _isolate_task_config(self.task, 'ShopTask')
        self.task.clear_done_all()
        self.set_image('tests/images/main.png')  # 提供真实帧，保证 get_box_by_name 可解析标注区域。

    def _patch_common(self, enabled):
        """公共桩：wait_until 直通求值一次，is_feature_enabled 固定返回 enabled。"""
        return patch.object(self.task, "wait_until", side_effect=lambda cond, **kw: cond()), \
            patch.object(self.task, "is_feature_enabled", return_value=enabled)

    def test_config_defaults(self):
        self.assertEqual("商店", self.task.name)
        self.assertTrue(self.task.default_config["普通商店"])
        self.assertFalse(self.task.default_config["竞技场商店"])
        self.assertFalse(self.task.default_config["废铁商店"])

    def test_general_shop_skips_when_free_disabled(self):
        # box_shop_general_free 区域灰白（无免费刷新机会）：不点刷新按钮、不购买。
        wait_patch, enabled_patch = self._patch_common(enabled=False)
        with patch.object(self.task, "_is_sold_out", return_value=True), \
                wait_patch, enabled_patch, \
                patch.object(self.task, "_buy_cell") as buy_mock, \
                patch.object(self.task, "click_box") as click_mock:
            self.task._do_general_shop()
        click_mock.assert_not_called()
        buy_mock.assert_not_called()

    def test_general_shop_confirms_free_refresh_and_buys_again(self):
        # 区域高亮（有免费刷新）：点免费刷新 -> 弹窗零消耗 -> 确认并再买一次。
        wait_patch, enabled_patch = self._patch_common(enabled=True)
        sold_out_sequence = [False, False]  # 首格初始未售罄 + 刷新后仍未售罄。
        with patch.object(self.task, "_is_sold_out", side_effect=sold_out_sequence), \
                wait_patch, enabled_patch, \
                patch.object(self.task, "_buy_cell", return_value=True) as buy_mock, \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_feature", return_value=Box(0, 0, 1, 1)), \
                patch.object(self.task, "wait_click_feature") as wait_click_mock:
            self.task._do_general_shop()
        click_mock.assert_called_once_with("box_shop_general_refresh", after_sleep=1)
        wait_click_mock.assert_called_once_with("general_shop_refresh_confirm", time_out=5,
                                                raise_if_not_found=True, after_sleep=1)
        self.assertEqual(2, buy_mock.call_count)  # 刷新前后各买一次。

    def test_general_shop_cancels_paid_refresh_dialog(self):
        # 弹窗非零消耗（免费机会实际不可用）：取消刷新、不再购买。
        wait_patch, enabled_patch = self._patch_common(enabled=True)
        with patch.object(self.task, "_is_sold_out", return_value=True), \
                wait_patch, enabled_patch, \
                patch.object(self.task, "_buy_cell") as buy_mock, \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "wait_feature", return_value=None), \
                patch.object(self.task, "wait_click_feature") as wait_click_mock:
            self.task._do_general_shop()
        wait_click_mock.assert_called_once_with("general_shop_refresh_cancel", time_out=5,
                                                raise_if_not_found=True, after_sleep=1)
        buy_mock.assert_not_called()

    def test_general_shop_raises_wait_failed_when_box_missing(self):
        # 标注区域缺失：ValueError 转为 WaitFailedException，供 try_step 捕获恢复。
        from ok.task.exceptions import WaitFailedException
        with patch.object(self.task, "get_box_by_name",
                          side_effect=ValueError("No box found for category box_shop_general_free")):
            with self.assertRaises(WaitFailedException):
                self.task._do_general_shop()

    def test_enter_general_shop_transitions_then_asserts_tab(self):
        # 迁移到 transition 原语：点击入口后由原语等待确认进入商店界面，再校验激活标签页是普通商店。
        with patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True) as wait_mock, \
                patch.object(self.task, "_assert_shop_title") as title_mock:
            self.task._enter_general_shop()
        click_mock.assert_called_once_with("shop", time_out=10, raise_if_not_found=True, after_sleep=1)
        self.assertEqual(("shop",), wait_mock.call_args.args)  # transition 内部确认已注册的 shop 界面。
        self.assertEqual(10, wait_mock.call_args.kwargs["time_out"])
        title_mock.assert_called_once_with("普通商店")


if __name__ == '__main__':
    unittest.main()
