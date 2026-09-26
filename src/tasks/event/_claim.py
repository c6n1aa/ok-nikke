"""「全部领取」按钮原语：登录奖励、活动签到印章、活动任务弹窗三处同字同带，判据共用。

面板美术逐期变（同登录奖励），模板类判据必失效，故一律「区域 OCR 文字 + 外扩取底色判态」：
`_find_claim_all` 定位按钮文字，`_claim_button_box` 外扩到按钮底色供色彩判态，
`_claim_all_claimable` 判是否重新可领（多段式领取的第二段），`_close_claim_overlay` 清理领奖遮罩。
"""

from ok.feature.Box import Box  # 「全部领取」文字框按比例外扩成按钮框。

from src.tasks.event._const import _CLAIM_ALL_PAD, _CLAIM_ALL_SCAN_BOX, _CLAIM_ALL_TEXT


class EventClaimMixin:
    """「全部领取」按钮的文字定位、底色判态与领奖遮罩清理。

    签到印章、活动任务弹窗与登录奖励面板共用同字判据：先 OCR 定位文字，再按比例外扩取按钮底色，
    彩色 = 仍有可领，灰白 = 已领完。遮罩非必现，超时未出现不算失败。
    """

    def _find_claim_all(self):  # 在面板底部区域 OCR 识别「全部领取」按钮文字，返回匹配框或 None（签到印章/任务弹窗共用）。
        boxes = self.ocr(box=self.box_of_screen(*_CLAIM_ALL_SCAN_BOX),  # 按钮所在的屏幕下部区域。
                         match=[_CLAIM_ALL_TEXT])  # 正则部分匹配（兼容拆框/噪声）。
        return boxes[0] if boxes else None  # 文字长在按钮上，命中即按钮存在。

    def _claim_button_box(self, text_box):  # 「全部领取」文字框按比例外扩到按钮底色区域（供色彩判态）。
        pad_w = text_box.width * _CLAIM_ALL_PAD[0]  # 水平外扩量。
        pad_h = text_box.height * _CLAIM_ALL_PAD[1]  # 垂直外扩量。
        return Box(text_box.x - pad_w, text_box.y - pad_h,  # 左上各外扩一份。
                   text_box.width + pad_w * 2, text_box.height + pad_h * 2,  # 尺寸两端各加一份。
                   name="claim_all_button")  # 命名便于日志/调试识别。

    def _close_claim_overlay(self, time_out=5):  # 清理领奖遮罩（签到印章/任务弹窗共用，遮罩非必现，超时未出现不报错）。
        self.close_overlay(keywords=(self._MASK_CLAIM_PATTERN, self._MASK_ANYWHERE_PATTERN,
                                     self._CLICK_TO_PROCEED_PATTERN),
                           time_out=time_out, require_click=False)  # 遮罩非必现：没弹遮罩不算失败，避免把一次未领到奖励判成整条子流程失败。

    def _claim_all_claimable(self):  # 当前帧「全部领取」是否重新可领（文字在且底色彩色）；遮罩盖住/过渡灰白均视为未就绪。
        claim = self._find_claim_all()  # 弹窗底部「全部领取」文字框。
        return claim is not None and self.is_feature_enabled(self._claim_button_box(claim))  # 文字在且底色彩色 = 第二段已就绪可领。
