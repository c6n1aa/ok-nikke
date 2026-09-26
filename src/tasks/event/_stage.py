"""活动关卡页的读取与基本操作：列表区 OCR 解析、点击落点分类、详情页进出、快速战斗链。

关卡编号的解析策略在 src/event_stage.py（纯计算，OCR 由本模块以回调注入）；本模块负责碰帧与发动作。
推图、扫荡与挑战共用这里的「点开一行 → 判落点 → 详情页判态 → 快速战斗」原语。
"""

import cv2  # OpenCV：按区域预放大后再送 OCR（检测器不放大输入，低分辨率下小字会丢）。
from ok.feature.Box import Box  # 解析层行框（x1,y1,x2,y2 四元组）转可点击 Box。
from ok.task.exceptions import WaitFailedException  # 战斗等待超时等流程断言抛出的等待失败异常。

from src import (
    event_calendar,  # 分辨率缩放比（OCR 预放大与兜底行距按它算）。
    event_stage,  # 关卡页读取策略（切片 / 预放大 / 行解析；OCR 以回调注入）。
)
from src.tasks.event._const import (
    _STAGE_ENTER_TIMEOUT,
    _STAGE_LIST_BOX,
    _STAGE_SCAN_MAX_SCROLLS,
    _STAGE_SWIPE_START_RATIO,
    _STORY_DIALOG_WAIT,
    _STORY_POLL_INTERVAL,
    _STORY_SKIP_MAX,
    _SWEEP_BATTLE_TIMEOUT,
    _SWEEP_CLOSE_FEATURE,
    _SWEEP_MAX_FEATURE,
    _SWEEP_PAGE_FEATURE,
    _SWEEP_START_BOX,
)


class EventStageMixin:
    """活动关卡页的读取与基本操作。

    读取：`_stage_list_box` 定出竖条，`_stage_rows` 注入 OCR 回调交给 src/event_stage 切片解析出可选关卡行；
    操作：`_stage_landing` 把「点开一行后的落点」分成详情页 / 关卡流程 / 仍在列表 / 认不出四类，
    `_close_stage_detail` 与 `_run_quick_battle` 负责详情页的进出，`_skip_story_if_present` 处理进关先行播放的剧情。
    行状态（已通关 / 可重复挑战 / 未解锁）一律靠点开后的按钮态后验判定，不在解析层猜。
    """

    def _stage_list_box(self):  # 关卡列表竖条：横向用 coco 标注，纵向拉满整屏（标注框纵向逐期不同）。
        box = self._optional_box(_STAGE_LIST_BOX)  # 标注框。
        if box is None:  # 特征缺失。
            self.log_warning(f"缺少区域特征: {_STAGE_LIST_BOX}")  # 记录缺失，便于排查。
            return None  # 无法定位列表区时为 None。
        return event_stage.list_strip(box, self.height)  # 横向沿用标注范围、纵向整屏；无有效屏高时保守用标注框。

    def _ocr_region(self, box):  # 唯一的 OCR 缝：裁剪 → 按需预放大 → 引擎 OCR → 坐标映射回整图。
        """检测器只压缩超限的最长边、不放大输入，低分辨率下小字就没了：这里按 ocr_upscale 补像素
        （整屏竖条几乎不放大，按行距切的行块放大到上限），再把结果框映射回整图坐标。"""
        frame = self.frame  # 当前帧（无帧时引擎也没得读）。
        if frame is None:
            return []
        upscale = event_stage.ocr_upscale(box, self._stage_scale())  # 1.0 = 不放大（按原生尺寸送）。
        x, y = int(box.x), int(box.y)  # 裁剪区左上角（映射回整图用）。
        crop = frame[y:y + int(box.height), x:x + int(box.width)]
        if upscale > 1.0:  # 检测器不会替我们放大，只能自己放大后再送。
            crop = cv2.resize(crop, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
        return [event_stage.to_block(item, box, upscale)  # 引擎返回的是放大后裁剪图坐标。
                for item in self.ocr(frame=crop) if item.name]  # 空文本块丢弃。

    def _stage_scale(self):  # 当前分辨率相对 2560x1440 标定截图的缩放比（0 = 无有效分辨率，兜底按标定值）。
        return event_calendar.screen_scale(self.width, self.height)

    def _stage_rows(self, list_box=None):  # 关卡页列表区 -> 可选关卡行（编号 + 行框）；区域缺失返回空列表。
        box = list_box if list_box is not None else self._stage_list_box()  # 列表区。
        if box is None:  # 区域缺失。
            return []  # 无法解析。
        scale = self._stage_scale()  # 分辨率缩放比（兜底行距按它缩放）。
        self.log_debug(f"关卡列表区 {box}，分辨率缩放比 {scale:.3f}")  # 区域与分辨率参数便于核对。
        rows, notes = event_stage.read_rows(self._ocr_region, box, self.height, scale)  # 分层 OCR → 切片降级 → 缺口补扫。
        for note in notes:  # 策略轨迹在下层产生、在这里按任务日志级别呈现。
            self.log_info(note)
        self.log_info(f"关卡页解析：{len(rows)} 个可选关卡 {[row.stage_id for row in rows]}")  # 记录解析结果便于实机核对。
        self.log_debug(f"关卡页行明细：{[(row.stage_id, row.source, row.box) for row in rows]}")  # 编号/来源/行框。
        return rows

    def _row_box(self, row):  # 解析层行框（x1,y1,x2,y2 四元组）-> 可点击 Box（click_box 只接受 Box/特征名）。
        x1, y1, x2, y2 = row.box  # 行框为整图坐标四元组。
        return Box(x1, y1, x2 - x1, y2 - y1, name=f"event_stage_{row.stage_id or 'unknown'}")  # 行窄条区域。

    def _detail_page_open(self):  # 关卡详情页是否就位（右上关闭按钮特征；特征缺失按未就位）。
        try:  # 特征可能尚未标注进 coco。
            return self.find_one(_SWEEP_CLOSE_FEATURE) is not None
        except ValueError:  # 特征缺失。
            return False  # 视为未就位。

    def _in_stage_flow(self):  # 是否在关卡流程里：剧情对话或战斗界面（点关卡的两种正常落点）。
        return self.is_screen("conversation") or self._in_battle_page()

    def _stage_landing(self, time_out=_STAGE_ENTER_TIMEOUT):  # 点开候选行后等落点分类：'detail'/'flow'/'list'/None。
        """把落点分成四类，都用界面特征判（不靠时间假设），供调用方决定可推性：

        - `'detail'`：关卡详情页（右上关闭按钮特征）→ 由调用方判详情页按钮态；
        - `'flow'`：剧情对话或战斗界面 → 这一关就是当前进度关，已进入关卡流程；
        - `'list'`：仍停在关卡列表 → 该行不可推（已通关不可重复挑战/未解锁）；
        - `None`：窗口内落点没变成任何一种已知界面（过场卡住/未知页面）→ 判不了。

        「离开关卡列表」不等于「进了关卡流程」：不可推的行可能弹出提示框把标题盖住，让列表判定消失。
        故轮询期间顺手清提示框（没弹框时立即返回），并以落点分类而不是「列表消失」作为判据。
        """
        def classify():
            if self._detail_page_open():  # 详情页。
                return "detail"
            if self._in_stage_flow():  # 剧情对话 / 战斗界面。
                return "flow"
            if self.is_screen("event_stage_page"):  # 仍在关卡列表（提示框已清）。
                return "list"
            return None  # 都不是：继续轮询（过场加载中）。

        return self.wait_until(classify, time_out=time_out, settle_time=0,  # 命中即返回，无需稳定窗口。
                               pre_action=lambda: self.dismiss_all_popups(wait_for_popup=False, time_out=1),  # 每轮取帧前清提示框（框架每轮都跑 pre_action，不只是未命中轮）。
                               post_action=self._story_poll_throttle,  # 轮询节流（见 _STORY_POLL_INTERVAL）。
                               raise_if_not_found=False)  # 超时返回 None，由调用方判「判不了」。

    def _skip_story_if_present(self, time_out=_STORY_DIALOG_WAIT):  # 剧情对话界面出现则点跳过；未播剧情直接返回。
        """点关卡/进下一关/结算返回后都可能先播剧情（首次进非可重复挑战的关卡必有）。

        剧情对话复用全局 [谈话] 界面判定（`conversation`：右上角图标区任一图标命中），
        跳过按钮与咨询/突发剧情同一个 `conversation_skip` 特征——实机若发现活动剧情
        图标区位置不同，再补该页专属特征与区域。
        """
        if not self.wait_until(lambda: self.is_screen("conversation") or self._in_battle_page(),  # 剧情界面出现，或已直接进入战斗（无剧情）。
                               time_out=time_out, settle_time=0,  # 两信号都在场即返回，无需稳定窗口。
                               post_action=self._story_poll_throttle):  # 轮询节流（见 _STORY_POLL_INTERVAL）。
            self.log_warning("未识别到剧情界面与战斗界面，按无剧情继续")  # 交由后续战斗等待兜底。
            return False  # 未处理剧情。
        if not self.is_screen("conversation"):  # 已进入战斗界面 = 本次无剧情。
            return False  # 无事可做。
        for _ in range(_STORY_SKIP_MAX):  # 跳过点击上限（剧情可能分段）。
            if not self.is_screen("conversation"):  # 剧情界面已消失。
                break  # 结束跳过。
            self.wait_click_feature("conversation_skip", box=self._optional_box("box_conversation_icon"),  # 在对话图标区识别跳过按钮。
                                    raise_if_not_found=True, after_sleep=2)  # 特征缺失抛异常由 try_step 恢复。
        self.dismiss_all_popups(wait_for_popup=False, time_out=5)  # 剧情结束可能弹奖励/好感遮罩，先清掉再继续。
        self.log_info("已跳过剧情对话")  # 记录跳过。
        return True  # 已处理剧情。

    def _story_poll_throttle(self):  # 等待循环节流：挂在 post_action 上，未命中那轮才执行。
        self.sleep(_STORY_POLL_INTERVAL)  # 降低采样频率（窗口与判据不变）。

    def _locate_stage_row(self, stage_id):  # 查找指定关卡行并返回（行框对应当前屏幕，可直接点击）；未找到返回 None。
        """先在当前屏找：进关卡页时列表停在当前进度关，能命中就不动列表。当前屏没有才归一到顶部再逐屏下滚
        查找——扫荡目标都是已通关的关卡，通常在当前进度关上方，当前屏不一定看得到（列表停在进度关处）。"""
        box = self._stage_list_box()  # 列表区（同时是滚动区）。
        if box is None:  # 区域缺失。
            return None  # 无法定位。
        row = event_stage.find_stage(self._stage_rows(box), stage_id)  # 先在当前屏找。
        if row is not None:  # 当前屏命中。
            self.log_debug(f"当前屏定位到关卡 {stage_id}（行框 {row.box}）")  # 定位过程便于校准。
            return row  # 返回可点击的行条目。
        self._scroll_list_to_top(box, _STAGE_SWIPE_START_RATIO)  # 当前屏没有才归一到顶部，再向下逐屏找。
        for index in range(_STAGE_SCAN_MAX_SCROLLS):  # 逐屏查找（带上限防死循环）。
            row = event_stage.find_stage(self._stage_rows(box), stage_id)  # 在当前屏解析结果里按编号定位。
            if row is not None:  # 命中（行框即当前屏坐标）。
                self.log_debug(f"第 {index + 1} 屏定位到关卡 {stage_id}（行框 {row.box}）")  # 定位过程便于校准。
                return row  # 返回可点击的行条目。
            if not self._scroll_list_down(1, box, _STAGE_SWIPE_START_RATIO):  # 下滚一屏步；到底返回 False。
                break  # 到底仍未命中。
        self.log_debug(f"逐屏查找未定位到关卡 {stage_id}")  # 记录未命中。
        return None  # 未找到。

    def _close_stage_detail(self, to_screen="event_stage_page"):  # 关闭关卡详情页回退到指定列表页（剧情/扫荡回关卡页，挑战回挑战页）。
        self.wait_click_feature(_SWEEP_CLOSE_FEATURE, raise_if_not_found=True, after_sleep=1)  # 点详情页右上关闭按钮。
        self.assert_screen(to_screen, time_out=15)  # 确认回到目标列表界面（默认活动关卡列表）。

    def _run_quick_battle(self, quick_box, label="快速战斗"):  # 详情页「快速战斗」链：点按钮 → 次数弹窗拉满 → 开始 → 等结算 → 点结算确认。返回结算结果。
        self.click_box(quick_box, after_sleep=1)  # 点「快速战斗」，弹出次数选择弹窗（与个人突袭同款 UI）。
        self.wait_feature(_SWEEP_PAGE_FEATURE, time_out=10, raise_if_not_found=True)  # 等次数选择弹窗就位（缺失抛异常由 try_step 恢复）。
        max_btn = self.find_one(_SWEEP_MAX_FEATURE)  # 次数「拉满」按钮（弹窗可能已默认最大值）。
        if max_btn is not None:  # 识别到拉满按钮。
            self.click_box(max_btn, after_sleep=1)  # 点拉满剩余次数（默认取最大）。
            self.log_info(f"{label}次数弹窗：已点「拉满」，按最大次数开始")  # 记录拉满命中，便于核对每次消耗。
        else:  # 未识别到拉满按钮。
            self.log_info(f"{label}次数弹窗：未识别到「拉满」按钮，按弹窗默认次数开始")  # 记录兜底路径（可能每次只消耗 1 次）。
        self.click_box(_SWEEP_START_BOX, after_sleep=1)  # 点开始：快速战斗直接跳结算画面，不进战斗界面。
        result, confirm_box = self.wait_battle_finish(time_out=_SWEEP_BATTLE_TIMEOUT)  # 节流等待快速战斗结算画面（只检测不点击）。
        if confirm_box is None:  # 未识别到结算画面。
            raise WaitFailedException("未识别到快速战斗结算画面")  # 抛异常由 try_step 恢复。
        self.log_info(f"{label}快速战斗结束（{result}）")  # 记录结算结果。
        self.click_box(confirm_box, after_sleep=2)  # 点结算确认关闭结果画面。
        return result  # 返回结算结果供调用方记录。
