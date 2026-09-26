import os  # 操作系统路径模块，处理 assets/template/ 下模板文件的绝对路径。

import cv2  # OpenCV，模板缩放匹配使用 cv2.resize / cv2.imread。
from ok.feature.Box import Box  # 检测框对象，用于构造搜索区域与红点返回框。
from ok.util.color import calculate_colorfulness  # 框架颜色工具：计算区域色彩丰富度。

from src import event_calendar  # 活动图模板几何标定与缩放（纯图像/网络工具，不依赖框架）。


class VisionMixin:
    """图像工具：缩放模板匹配、活动列表行匹配、通知红点检测、UI 元素色彩判态。"""

    def find_scaled_template(self, feature_name: str, template_path: str, ref_width: int = 2560,
                             ref_height: int = 1440, **kwargs):
        """读取 assets/template 下的小图模板，按当前游戏分辨率等比缩放后匹配（模板源自 ref_width x ref_height 截图裁剪）。

        Args:
            feature_name: 匹配名，仅用于日志/调试框命名。
            template_path: 模板图片路径，如 'assets/template/notice_bell.jpg'。
            ref_width/ref_height: 模板裁剪时的源截图分辨率，默认 2560x1440。
            其余参数（threshold、box、use_gray_scale 等）透传给 self.find_one。

        Returns:
            Box | None。
        """
        scale = min(self.width / ref_width, self.height / ref_height)  # 等比例缩放，取小者避免超出
        if scale <= 0:  # 分辨率无效（如测试环境无窗口/无帧）时无法缩放，视为未命中。
            return None
        cache_key = (os.path.abspath(template_path), round(scale, 6))
        template = self._scaled_template_cache.get(cache_key)
        if template is None:
            template = cv2.imread(template_path)  # 读取小图模板
            if template is None:
                raise FileNotFoundError(f'template not found: {template_path}')
            if scale != 1:
                # 按当前分辨率等比缩放：缩小用 INTER_AREA，放大用 INTER_LINEAR
                interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
                template = cv2.resize(template, (0, 0), fx=scale, fy=scale, interpolation=interp)
            self._scaled_template_cache[cache_key] = template
        return self.find_one(feature_name, template=template, **kwargs)

    def find_event_row(self, feature_name: str, banner, box=None, threshold: float = 0.8, limit: int = 1):
        """在活动列表里匹配官方活动图，返回命中行的 Box（未命中返回 None）。

        模板由官方活动图现场生成（裁剪 + 按当前分辨率缩放到行尺寸），活动更新不需要人工换模板。
        与 find_scaled_template 的差别：模板不是磁盘上的固定裁剪图，而是按行宽比例现算的，
        且只取活动图中不含游戏内浮层的子区域（为什么不能整图直接用，见 src/event_calendar 的模块注释）。

        Args:
            feature_name: 匹配名，仅用于日志/调试框命名（建议传活动名）。
            banner: 官方活动图路径（str）或已读入的 BGR ndarray（可用 event_calendar.ensure_cached 取路径）。
            box: 搜索区域，缺省固定在活动列表面板框（coco 特征 event_calendar.SEARCH_BOX）；
                仅在确有别的区域时才传，可传 coco 框名或 Box。
            threshold: 匹配阈值。默认 0.8：实测命中行 0.89~0.96、其它行 ≤0.61。
            limit: 透传给 find_one（1 = 只取最优命中）。

        Returns:
            Box | None：命中行为模板区域（行内 logo 区），未命中 None。
        """
        if event_calendar.screen_scale(self.width, self.height) <= 0:  # 无有效分辨率（测试环境无帧等）。
            return None  # 无法按分辨率生成模板，直接视为未命中。
        image = cv2.imread(banner) if isinstance(banner, str) else banner  # 支持路径与 ndarray 两种入参。
        if image is None:  # 模板图读不到（路径错/缓存损坏）：显式报错，不静默当成"活动不存在"。
            raise FileNotFoundError(f'event banner not found: {banner}')
        if isinstance(box, str):  # 允许传 coco 框名，与 find_red_dot 的用法保持一致。
            box = self.get_box_by_name(box)
        elif box is None:  # 缺省：固定在活动列表面板框内匹配（不在面板外乱匹配）。
            box = self.get_box_by_name(event_calendar.SEARCH_BOX)
        row_width = event_calendar.row_width(self.width, self.height)  # 当前分辨率下的行宽（像素）。
        for scale in (1.0,) + event_calendar.FALLBACK_SCALES:  # 先基准尺度；命中即返回，不会白跑兜底档位。
            template = event_calendar.build_row_template(image, row_width, scale)
            found = self.find_one(feature_name, template=template, box=box, threshold=threshold, limit=limit)
            if found is not None:  # 命中该活动所在行。
                return found
        return None  # 所有尺度都没超过阈值：该活动当前不在列表里。

    def find_red_dot(self, box, template_path=None, threshold=0.6, min_blob_area=8,
                     ref_width=2560, ref_height=1440, use_color_fallback=True) -> Box | None:
        """在指定 box 区域内检测通知红点：模板匹配为主（返回精确位置），颜色检测兜底半透明/样式变体红点。

        红点检测必须限定在 box 区域内，不支持全图扫描（全图颜色检测误检率极高）。
        box 必须是 coco 特征名或 Box 对象，拒绝 None。

        Args:
            box: 搜索区域。coco box 特征名（如 'box_mission_daily_badge'，自动按当前
                分辨率缩放）或 Box 对象（可用 self.box_of_screen 生成相对坐标区域）。
            template_path: 红点模板路径（如 'assets/template/common/badge.png'）。传入时先做
                模板匹配，命中返回精确位置；未命中或未传时按 use_color_fallback 决定是否
                用颜色检测兜底。
            threshold: 模板匹配阈值。默认 0.6，低于框架默认 0.8——半透明红点分数
                偏低（实测 0.70-0.73），必须显式传阈值，不能回落默认 0.8。
            min_blob_area: 颜色检测判定红点存在的最小红色连通域面积（默认 8，
                原分辨率红点约 70-95、720p 约 12-20，8 可跨分辨率通用）。
            ref_width/ref_height: 模板裁剪时的源截图分辨率，默认 2560x1440。
            use_color_fallback: 是否启用颜色检测兜底（默认 True 保持原行为）。False 时
                仅做模板匹配，未传模板或模板未命中直接返回 None，适合红点样式固定、
                颜色检测易误检（区域含红色 UI 元素）的场景。

        Returns:
            命中返回红点位置 Box（模板命中为精确模板框，颜色兜底为最大红色连通域
            外接框）；未命中返回 None。
        """
        box = self.get_box_by_name(box)  # 解析搜索区域：字符串为 coco 特征名/框架快捷名，Box 原样返回。
        if box is None:  # 区域无效。
            raise ValueError("find_red_dot 必须传入有效的 box 区域")  # 红点检测必须限定区域。
        if template_path is not None:  # 配置了模板则先做模板匹配。
            found = self.find_scaled_template(  # 复用模板缩放+匹配，限定在 box 区域内。
                "red_dot", template_path,  # 匹配命名与模板路径。
                ref_width=ref_width, ref_height=ref_height,  # 模板源截图分辨率。
                box=box, threshold=threshold,  # 限定搜索区域并显式传阈值，避免回落默认 0.8。
            )
            if found is not None:  # 模板命中。
                return found  # 返回模板的精确位置。
        if not use_color_fallback:  # 未开启颜色兜底：仅模板匹配，到此即视为未命中。
            return None
        frame = self.frame  # 取当前帧用于颜色检测兜底。
        if frame is None:  # 无帧可做颜色检测。
            return None  # 返回未命中。
        x1, y1 = max(box.x, 0), max(box.y, 0)  # 裁剪 box 左上角到帧范围内。
        x2, y2 = min(box.x + box.width, frame.shape[1]), min(box.y + box.height, frame.shape[0])  # 裁剪右下角。
        if x2 <= x1 or y2 <= y1:  # 区域越界无效。
            return None  # 返回未命中。
        roi = frame[y1:y2, x1:x2]  # 取 box 区域子图。
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)  # 转 HSV 便于提取红色。
        m1 = cv2.inRange(hsv, (0, 40, 40), (12, 255, 255))  # 红色低色相段（0-12°）。
        m2 = cv2.inRange(hsv, (165, 40, 40), (180, 255, 255))  # 红色高色相段（165-180°，色相环绕）。
        mask = cv2.bitwise_or(m1, m2)  # 合并两段红色掩码。
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)  # 提取红色连通域。
        for c in sorted(contours, key=cv2.contourArea, reverse=True):  # 按面积从大到小检查。
            if cv2.contourArea(c) >= min_blob_area:  # 连通域面积达到阈值视为红点。
                cx, cy, cw, ch = cv2.boundingRect(c)  # 取红色连通域外接框。
                return Box(x1 + cx, y1 + cy, cw, ch, name="red_dot_color")  # 转回帧坐标返回。
        return None  # 无红点返回未命中。

    def is_feature_enabled(self, box: Box, colorfulness_thresh: float = 0.1, after_sleep: float = 0) -> bool:
        """判断 UI 元素是否处于可用（高亮彩色）状态。

        游戏内可用/禁用按钮常用"高亮彩色 vs 灰白"表达（如无限之塔"进入战斗"蓝色
        可用态 vs 灰色禁用态）。CCOEFF 模板匹配会忽略颜色，无法区分这两种状态；
        此方法用框架的颜色工具计算 box 区域色彩丰富度（RGB 对立轴统计，对灰白压
        得更狠），低于 colorfulness_thresh 视为灰白禁用。

        Args:
            box: 元素所在区域（coco 特征框或模板匹配结果 Box）。
            colorfulness_thresh: 色彩丰富度阈值（0~1），低于则判定为禁用。
            after_sleep: 判断后的固定等待时间（秒），参考框架 click/send_key 等方法的 after_sleep 实现。

        Returns:
            True 可用；False 禁用（灰白）。无帧/区域越界时保守返回 True。
        """
        frame = self.frame  # 取当前帧；无帧（如单测 mock）时保守视为可用。
        if frame is None:  # 无帧可做颜色检测。
            if after_sleep > 0:  # 参考框架 click 等方法的 after_sleep 实现：操作后等待。
                self.sleep(after_sleep)  # 等待指定时间。
            return True  # 返回可用，避免误跳可用功能。
        x1, y1 = max(box.x, 0), max(box.y, 0)  # 裁剪 box 左上角到帧范围内。
        x2, y2 = min(box.x + box.width, frame.shape[1]), min(box.y + box.height, frame.shape[0])  # 裁剪右下角。
        if x2 <= x1 or y2 <= y1:  # 区域越界无效。
            if after_sleep > 0:  # 参考框架实现。
                self.sleep(after_sleep)  # 等待指定时间。
            return True  # 保守视为可用。
        roi = frame[y1:y2, x1:x2]  # 取 box 区域子图。
        colorfulness = calculate_colorfulness(roi)  # 用框架颜色工具计算色彩丰富度（0~1）。
        result = colorfulness > colorfulness_thresh  # 超过阈值判定为可用。
        if after_sleep > 0:  # 参考框架 click/send_key 的 after_sleep 实现。
            self.sleep(after_sleep)  # 等待指定时间。
        return result  # 返回可用性判定结果。
