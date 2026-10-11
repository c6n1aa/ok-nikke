"""分辨率基准（2560x1440）与缩放比：以标定截图实测的像素常量都按它换算。

唯一基准见 docs/screen-and-recovery.md 的「素材分辨率基准」；本模块只做换算，不碰帧、不联网、不依赖 ok 框架。
"""

REF_WIDTH = 2560  # 标定截图宽度。
REF_HEIGHT = 1440  # 标定截图高度。


def screen_scale(screen_width, screen_height, ref_width=REF_WIDTH, ref_height=REF_HEIGHT):
    """当前分辨率相对标定分辨率的缩放比（取 min，与框架 find_scaled_template 一致）。"""
    if not screen_width or not screen_height:  # 无帧（测试环境）。
        return 0.0
    return min(screen_width / ref_width, screen_height / ref_height)
