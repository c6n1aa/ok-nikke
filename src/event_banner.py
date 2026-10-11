"""官方活动图 -> 活动列表行匹配模板的几何标定与面板区域名（2560x1440 实测，纯 cv2，不碰帧/不联网）。

- 游戏内把官方活动图等比渲染成列表一行：行宽 749（屏宽 29.26%）、行高 250、长宽比 3:1；
- 模板取 SUBJECT = banner 的 x[0.60,0.95] × y[0,0.70]：避开左下日期浮层与最右行边框，
  列表最后一行只有 175/250 = 70% 可见，模板更高即装不下（y=0.92 时该行掉到 0.29）；
- 匹配限定在 SEARCH_BOX 内：三行 0.89~0.96，其它行 ≤0.61，阈值 0.8。

回归见 tests/TestEventCalendar.py；调用方是活动列表行匹配（src/tasks/base/_vision.py 的 find_event_row）。
"""

import cv2  # 活动图裁剪与缩放。

from src.resolution import REF_HEIGHT, REF_WIDTH, screen_scale  # 分辨率基准与缩放比（单一实现）。

ROW_WIDTH_AT_REF = 749  # 列表单行宽度（像素）；行高 250。
SUBJECT = (0.60, 0.00, 0.95, 0.70)  # 模板在 banner 内的子区域（左、上、右、下，相对比例）。
SEARCH_BOX = 'box_event_banner_area'  # 列表面板的 coco 框特征名（1440p 下 881,286,799x1038）。
FALLBACK_SCALES = (0.97, 0.98, 0.99, 1.01, 1.02, 1.03)  # 基准尺度未命中时的备选档位。


def row_width(screen_width, screen_height, ref_width=REF_WIDTH, ref_height=REF_HEIGHT):
    """当前分辨率下列表单行的宽度（像素）。"""
    return ROW_WIDTH_AT_REF * screen_scale(screen_width, screen_height, ref_width, ref_height)


def build_row_template(banner, row_width_px, scale=1.0):
    """活动图 -> 行匹配模板：等比缩放到 row_width_px，再裁出 SUBJECT。

    Args:
        banner: 活动图 BGR ndarray。
        row_width_px: 目标行宽（由 row_width() 算得）。
        scale: 额外缩放系数（FALLBACK_SCALES 档位）。

    Returns:
        裁剪后的 BGR ndarray。
    """
    if banner is None or getattr(banner, 'size', 0) == 0 or banner.ndim != 3:  # 空图或非 BGR。
        raise ValueError('event banner image is empty or not a BGR image')
    height, width = banner.shape[:2]
    target_w = max(8, int(round(row_width_px * scale)))
    target_h = max(8, int(round(target_w * height / width)))
    factor = target_w / width
    interpolation = cv2.INTER_AREA if factor < 1 else cv2.INTER_LINEAR  # 缩小用 AREA，放大用 LINEAR。
    resized = cv2.resize(banner, (target_w, target_h), interpolation=interpolation)
    x1, y1, x2, y2 = SUBJECT
    return resized[int(target_h * y1):int(target_h * y2), int(target_w * x1):int(target_w * x2)]
