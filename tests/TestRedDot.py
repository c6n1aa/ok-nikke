import os
import tempfile
import unittest

import cv2
import numpy as np

from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.HarvestTask import HarvestTask

W, H = 256, 144          # 合成帧尺寸（模板匹配用 ref_width/ref_height 对齐该尺寸，缩放比=1）
BG = (200, 100, 50)      # 蓝色背景 BGR
RED = (50, 50, 230)      # 实心亮红 BGR
DOT_CENTER = (60, 50)    # 红点圆心
DOT_RADIUS = 8           # 红点半径


def make_frame(dot_color=None, dot_center=DOT_CENTER, dot_radius=DOT_RADIUS):
    """生成蓝底帧，可选在指定位置画一个圆点。"""
    frame = np.full((H, W, 3), BG, dtype=np.uint8)
    if dot_color is not None:
        cv2.circle(frame, dot_center, dot_radius, dot_color, -1)
    return frame


class TestRedDot(TaskTestCase):
    task_class = HarvestTask
    config = config

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.mkdtemp(prefix='ok_reddot_')

    def _write(self, name, frame):
        path = os.path.join(self._tmp, name)
        cv2.imwrite(path, frame)
        return path

    def _box(self):
        return Box(40, 30, 40, 40, name='test_box')  # 覆盖红点 (60,50) 的搜索区域

    def test_color_detection_finds_bright_red_dot(self):
        self.set_image(self._write('bright.png', make_frame(RED)))
        found = self.task.find_red_dot(self._box())
        self.assertIsNotNone(found)  # 实心红点应被颜色检测命中
        self.assertEqual(found.name, 'red_dot_color')  # 未传模板时走颜色兜底路径

    def test_color_detection_absent_returns_none(self):
        self.set_image(self._write('plain.png', make_frame()))
        self.assertIsNone(self.task.find_red_dot(self._box()))  # 无红点返回 None

    def test_color_detection_finds_semi_transparent_dot(self):
        # 半透明红点：红与蓝背景 75%/25% 混合，饱和度明显低于实心红
        semi = tuple(int(0.75 * RED[i] + 0.25 * BG[i]) for i in range(3))
        self.set_image(self._write('semi.png', make_frame(semi)))
        found = self.task.find_red_dot(self._box())
        self.assertIsNotNone(found)  # 半透明红点也应命中

    def test_template_matching_returns_precise_position(self):
        frame = make_frame(RED)
        self.set_image(self._write('tm_frame.png', frame))
        patch = frame[42:58, 52:68]  # 与红点完全一致的 16x16 模板（源自当前帧）
        template = self._write('tm_badge.png', patch)
        found = self.task.find_red_dot(self._box(), template_path=template,
                                       ref_width=W, ref_height=H)
        self.assertIsNotNone(found)  # 模板命中
        self.assertEqual((found.x, found.y), (52, 42))  # 返回精确位置（模板起点）
        self.assertEqual((found.width, found.height), (16, 16))

    def test_template_miss_falls_back_to_color(self):
        # 绿点模板与红点不匹配，模板漏检后应被颜色兜底命中
        green_frame = make_frame((80, 200, 80))
        green_patch = green_frame[42:58, 52:68]
        template = self._write('green_badge.png', green_patch)
        self.set_image(self._write('fb_frame.png', make_frame(RED)))
        found = self.task.find_red_dot(self._box(), template_path=template,
                                       ref_width=W, ref_height=H)
        self.assertIsNotNone(found)  # 颜色兜底命中
        self.assertEqual(found.name, 'red_dot_color')

    def test_requires_box(self):
        with self.assertRaises(ValueError):
            self.task.find_red_dot(None)  # 必须传入 box 区域


if __name__ == '__main__':
    unittest.main()