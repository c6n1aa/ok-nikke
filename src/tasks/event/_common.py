"""活动任务的通用小工具：coco 区域解析、列表区滚动手势、滚动前后画面变化判据。

不绑定具体页面：滚动区由调用方以 Box 传入（缺省用活动列表区），活动列表页与关卡列表页共用。
"""

import cv2  # OpenCV：滑动前后截取列表区做像素差，判画面有没有变化（到底 / 到顶）。

from src import event_calendar  # 活动列表区标注特征名（缺省滚动区）。
from src.tasks.event._const import (
    _SCROLL_AFTER_SLEEP,
    _SCROLL_SWIPE_DURATION,
    _SCROLL_TOP_MAX_SWIPES,
    _SCROLL_UNCHANGED_RATIO,
    _SWIPE_END_RATIO,
    _SWIPE_START_RATIO,
)


class EventCommonMixin:
    """任务内通用小工具：coco 区域解析 + 列表区滚动。

    `_optional_box` 把「可选区域特征」的解析收敛到一处（特征未标注进 coco 时返回 None，
    调用方按不可用处理）；其余方法是滚动手势与滚动前后像素对比判到底 / 到顶，
    滚动区由调用方传入（缺省活动列表区），活动列表页与关卡列表页共用。
    """

    def _optional_box(self, box_name):  # 解析 coco 区域框，特征缺失返回 None（可选区域判态统一走它）。
        try:  # 区域特征可能尚未标注进 coco。
            return self.get_box_by_name(box_name)  # 区域框（按当前分辨率缩放）。
        except ValueError:  # 特征缺失。
            return None  # 视为不可用。

    def _list_area_box(self):  # 活动列表滚动/扫描区（box_event_banner_area），缺失返回 None。
        return self._optional_box(event_calendar.SEARCH_BOX)  # 区域缺失视为不可滚动。

    def _list_area_frame(self, box):  # 截取列表区当前帧（无帧/越界返回 None），供滚动前后像素对比。
        frame = self.frame  # 取当前帧；无帧（单测 mock）返回 None。
        if frame is None:  # 无帧。
            return None  # 无法比对，由调用方保守处理。
        x1, y1 = max(box.x, 0), max(box.y, 0)  # 裁剪左上角到帧范围内。
        x2, y2 = min(box.x + box.width, frame.shape[1]), min(box.y + box.height, frame.shape[0])  # 裁剪右下角。
        if x2 <= x1 or y2 <= y1:  # 区域越界无效。
            return None  # 无法比对。
        return frame[y1:y2, x1:x2]  # 返回列表区子图。

    def _region_changed(self, before, after):  # 比较两帧列表区是否发生变化；无有效图像时保守视为变化。
        if before is None or after is None or before.shape != after.shape:  # 任一帧无效/尺寸不一致。
            return True  # 保守视为变化，避免误判到底。
        diff = cv2.absdiff(before, after)  # 逐像素绝对差。
        return float((diff > 10).sum()) / diff.size > _SCROLL_UNCHANGED_RATIO  # 显著变化像素占比超阈值才视为有变化。

    def _swipe_list_up(self, box, start_ratio=_SWIPE_START_RATIO):  # 在给定列表区上滑（内容上移，露出下方行）。
        x = box.x + box.width // 2  # 列表区水平中点。
        self.swipe(x, box.y + box.height * start_ratio, x, box.y + box.height * _SWIPE_END_RATIO,
                   duration=_SCROLL_SWIPE_DURATION, after_sleep=_SCROLL_AFTER_SLEEP)  # 自下往上滑。

    def _swipe_list_down(self, box, start_ratio=_SWIPE_START_RATIO):  # 在给定列表区下滑（内容下移，回到顶部）。
        x = box.x + box.width // 2  # 列表区水平中点。
        self.swipe(x, box.y + box.height * _SWIPE_END_RATIO, x, box.y + box.height * start_ratio,
                   duration=_SCROLL_SWIPE_DURATION, after_sleep=_SCROLL_AFTER_SLEEP)  # 自上往下滑（与上滑互为镜像）。

    def _scroll_area(self, swipe, box, start_ratio, max_steps):  # 用给定手势逐次滑动，返回画面实际发生变化的滑动次数。
        before = self._list_area_frame(box)  # 初始区域画面。
        for count in range(max_steps):  # 带上限防死循环。
            swipe(box, start_ratio)  # 滑动一步。
            after = self._list_area_frame(box)  # 滑动后画面。
            if not self._region_changed(before, after):  # 画面无变化 = 到底/到顶。
                return count  # 返回已生效的滑动次数。
            before = after  # 更新基准继续滑动。
        return max_steps  # 每一步都生效。

    def _scroll_list_to_top(self, box=None, start_ratio=_SWIPE_START_RATIO):  # 把列表滚动到顶部：连续下滑，画面不再变化即视为到顶。
        box = self._list_area_box() if box is None else box  # 缺省活动列表的 banner 区；关卡列表传自己的竖条。
        if box is None:  # 区域缺失。
            return  # 无法滚动。
        self._scroll_area(self._swipe_list_down, box, start_ratio, _SCROLL_TOP_MAX_SWIPES)  # 下滑到画面不再变化或次数上限。

    def _scroll_list_down(self, steps, box=None, start_ratio=_SWIPE_START_RATIO):  # 列表向下滚动 steps 步，返回是否发生实际滚动（到底返回 False）。
        if steps <= 0:  # 无下滚需求。
            return True  # 视为位置有效。
        box = self._list_area_box() if box is None else box  # 缺省活动列表的 banner 区；关卡列表传自己的竖条。
        if box is None:  # 区域缺失。
            return False  # 不可滚动视为到底。
        return self._scroll_area(self._swipe_list_up, box, start_ratio, steps) >= steps  # 少滚一步即视为到底。
