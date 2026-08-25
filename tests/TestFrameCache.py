import unittest
from unittest.mock import patch

from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.HarvestTask import HarvestTask


def _fake_box(name):
    return Box(100, 100, 50, 50, confidence=1, name=name)


class TestFrameCache(TaskTestCase):
    """帧级判定缓存：同帧只匹配一次、换帧即失效、OCR 区域合并与退化隔离。"""
    task_class = HarvestTask

    config = config

    def setUp(self):
        self.set_image('tests/images/main.png')
        # 每个用例从干净的界面注册表开始，避免共享实例上残留其它用例注册的界面。
        self.task.screens = {}
        self.task._screen_cache.clear()

    def test_feature_matched_once_per_frame(self):
        # 同一帧内重复判定（current_screen + is_screen×2），每个特征只真正 find_one 一次。
        self.task.register_screen("lobby", features=["ark", "lobby"])
        with patch.object(self.task, "find_one", side_effect=lambda name: _fake_box(name)) as find_mock:
            self.task.current_screen()
            self.assertTrue(self.task.is_screen("lobby"))
            self.assertTrue(self.task.is_screen("lobby"))
        self.assertEqual(2, find_mock.call_count)  # ark/lobby 各一次。

    def test_next_frame_invalidates_feature_cache(self):
        # set_image 内部调用 next_frame：换帧后同一特征重新匹配。
        self.task.register_screen("lobby", features=["ark"])
        with patch.object(self.task, "find_one", side_effect=lambda name: _fake_box(name)) as find_mock:
            self.assertTrue(self.task.is_screen("lobby"))
            self.assertEqual(1, find_mock.call_count)
            self.set_image('tests/images/main.png')  # 触发 next_frame，缓存失效。
            self.assertTrue(self.task.is_screen("lobby"))
        self.assertEqual(2, find_mock.call_count)

    def test_feature_miss_is_cached_too(self):
        # 未命中（None）同样进缓存：同帧重复判定的未命中分支不重跑匹配。
        self.task.register_screen("空页", features=["不存在特征甲"])
        with patch.object(self.task, "find_one", return_value=None) as find_mock, \
                patch.object(self.task, "log_warning"):
            self.assertFalse(self.task.is_screen("空页"))
            self.assertFalse(self.task.is_screen("空页"))
        self.assertEqual(1, find_mock.call_count)

    def test_ocr_region_shared_across_keyword_sets(self):
        # 同帧同区域的标题 OCR 只跑一次，两个界面的关键词集各自比对同一次结果。
        self.task.register_screen("页面甲", keywords=["甲关键词"], ocr_box="box_sub_pages_title")
        self.task.register_screen("页面乙", keywords=["乙关键词"], ocr_box="box_sub_pages_title")
        title_box = _fake_box("box_sub_pages_title")
        with patch.object(self.task, "get_box_by_name", return_value=title_box), \
                patch.object(self.task, "ocr", side_effect=lambda *a, **k: [_fake_box("甲关键词")]) as ocr_mock:
            self.assertTrue(self.task.is_screen("页面甲"))  # 关键词命中。
            self.assertFalse(self.task.is_screen("页面乙"))  # 另一关键词集不命中，但共享同一次 OCR。
        self.assertEqual(1, ocr_mock.call_count)

    def test_ocr_result_cached_until_new_frame(self):
        self.task.register_screen("cash_shop", keywords=["付费商店"], ocr_box="box_sub_pages_title")
        with patch.object(self.task, "get_box_by_name", return_value=_fake_box("t")), \
                patch.object(self.task, "ocr", return_value=[_fake_box("付费商店")]) as ocr_mock:
            self.assertTrue(self.task.is_screen("cash_shop"))
            self.assertTrue(self.task.is_screen("cash_shop"))  # 同帧走缓存。
            self.set_image('tests/images/main.png')  # 换帧失效。
            self.assertTrue(self.task.is_screen("cash_shop"))
        self.assertEqual(2, ocr_mock.call_count)

    def test_fullscreen_degradation_not_merged(self):
        # ocr_box 特征缺失退化为全屏时按条目隔离：两个界面各自全屏 OCR，互不合并。
        self.task.register_screen("页A", keywords=["关键词A"], ocr_box="缺失区域特征")
        self.task.register_screen("页B", keywords=["关键词B"], ocr_box="缺失区域特征")
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")), \
                patch.object(self.task, "ocr", return_value=[]) as ocr_mock:
            self.assertFalse(self.task.is_screen("页A"))
            self.assertFalse(self.task.is_screen("页B"))
        self.assertEqual(2, ocr_mock.call_count)
        for call in ocr_mock.call_args_list:  # 两次都是无区域的全屏 OCR。
            self.assertNotIn("box", call.kwargs)

    def test_relative_coordinate_list_region(self):
        # 相对坐标列表形式的 ocr_box 走位置参数调用且参与缓存。
        self.task.register_screen("坐标页", keywords=["命中词"], ocr_box=[0.1, 0.1, 0.5, 0.5])
        with patch.object(self.task, "ocr", side_effect=lambda *a, **k: [_fake_box("命中词")]) as ocr_mock:
            self.assertTrue(self.task.is_screen("坐标页"))
            self.assertTrue(self.task.is_screen("坐标页"))
        self.assertEqual(1, ocr_mock.call_count)
        self.assertEqual((0.1, 0.1, 0.5, 0.5), ocr_mock.call_args.args)  # 与旧实现相同的位置参数形态。


if __name__ == '__main__':
    unittest.main()
