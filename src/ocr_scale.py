"""区域 OCR 的预放大策略：低分辨率下把小区域补像素再送引擎（检测器只压缩、不放大）。

检测器只压缩超限的最长边（onnxocr det_limit_side_len=960 / limit_type=max），低于标定分辨率时得
调用方自己补像素：把最长边填到 `TILE_LIMIT`，上限 `UPSCALE_MAX` 兜住成本（整屏竖条几乎放不动，
按行距切的行块能顶到上限，小字的等效像素数因此在各档接近）。

活动关卡列表（src/event_stage.py）与界面判定的区域 OCR（src/tasks/base/_vision.py）共用本模块。
"""

TILE_LIMIT = 960  # 单块最长边（像素），与检测器上限同值。
UPSCALE_MAX = 2.0  # 喂给引擎前的预放大上限（检测器不放大，低分辨率下靠它补像素）。


def upscale(box, scale=1.0):
    """把该区域喂给 OCR 引擎前的预放大倍数（1.0 = 不放大）。

    标定分辨率（`scale ≥ 1`，2560x1440）下**不放大**：那时小字本来就够大，插值放大只会糊掉笔画、让
    检测器多认出噪声（实机 03.png 在 1.32 倍下多出 `1-04`/`1-05` 两个假行）。
    """
    if scale >= 1.0:  # 标定分辨率及以上：按原生尺寸送，与标定口径一致。
        return 1.0
    longest = max(int(box.width), int(box.height), 1)  # 最长边（决定检测器的缩放比例）。
    return min(UPSCALE_MAX, max(1.0, TILE_LIMIT / longest))  # 填满检测器上限，但不超上限。
