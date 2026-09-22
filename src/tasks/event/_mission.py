"""活动任务弹窗流程：点入口弹出模态框，按栏目分别领取「全部领取」，再点空白关闭回菜单页。

弹窗美术逐期变（标题就是当期活动名），故没有跨期模板特征，判据只用「coco 区域 + OCR 文案」：
就位认大活动栏目图标 / 小活动副标题关键词，可领认「全部领取」外扩底色（见 _claim.py）。
"""

from ok.task.exceptions import WaitFailedException  # 入口缺失等流程断言抛出的等待失败异常。

from src.tasks.event._const import (
    _MISSION_SUBTITLE_BOX, _MISSION_SUBTITLE_TEXT, _MISSION_ICON_BOX, _MISSION_TABS,
    _MISSION_DAILY_SUBTITLE_BOX, _MISSION_READY_TIMEOUT, _MISSION_TAB_SWITCH_TIMEOUT,
    _MISSION_CLAIM_MAX_CLICKS, _MISSION_CLAIM_SETTLE_TIMEOUT, _MISSION_CLAIM_SETTLE,
)


class EventMissionMixin:
    """活动任务弹窗的领取编排。

    大活动弹窗每次点开都停在「每日任务」页且分「每日任务 / 成就」两栏，故先切「成就」领完再切回；
    小活动无栏目，单页直接领。栏目切换无独立界面判据，靠副标题文字变化确认。
    """

    def _flow_mission(self):  # 任务流程（自足重入）：点任务入口弹模态框 → 分栏目领取 → 点空白关闭回菜单页。
        # 大小活动同一套弹窗 UI；弹窗美术逐期变（标题是当期活动名），无跨期稳定模板特征，
        # 判据只用「coco 区域 + OCR 文案」：就位认大活动栏目图标 / 小活动副标题关键词，
        # 可领认「全部领取」外扩底色（同签到印章那套）。
        self._nav_to_event_main()  # 就位活动主页（正常已就位；恢复回大厅后由此重入）。
        entry = self._entry_box("任务")  # 任务入口（大活动在专属区域 box_event_menu_mission，小活动在菜单带）。
        if entry is None:  # 入口缺失（菜单未渲染或页面结构变化）。
            raise WaitFailedException("未找到任务入口")  # 抛异常由 try_step 恢复。
        self.click_box(entry, after_sleep=2)  # 点击入口弹出任务弹窗（模态框，不注册为界面）。
        if not self.wait_until(self._mission_popup_ready,  # 轮询等弹窗就位（大活动认栏目图标，小活动认副标题）。
                               time_out=_MISSION_READY_TIMEOUT, settle_time=1.5):  # 命中后再稳定 1.5s，吸收弹窗开启动画。
            self.log_warning("任务弹窗未在预期时间内出现，跳过领取")  # 记录跳过原因（弹窗未开则无需关闭）。
            return  # 结束任务流程（仍在活动菜单页）。
        self._claim_mission_pages()  # 大活动两个栏目各领一轮，小活动单页领一轮。
        # 领取按钮灰白后点面板外空白关闭弹窗：确认回到活动菜单页即完成（模态框点空白等价点遮罩，对皮肤免疫）。
        if self.close_popup_by_blank(lambda: self.is_screen("event_main"), time_out=5):  # 关不掉时补点（默认次数）。
            self.log_info("任务奖励领取完成，已回到活动菜单页")  # 记录完成。
        else:  # 补点耗尽仍未确认关闭。
            self.log_warning("点击空白未能关闭任务弹窗")  # 记录失败（弹窗遮挡会让后续子流程探测跳过）。

    def _mission_popup_ready(self):  # 弹窗就位判据：大活动两个栏目都定位到，或小活动副标题关键词命中。
        if self._mission_tabs() is not None:  # 大活动两栏目弹窗：栏目出现即弹窗已打开。
            return True  # 就位。
        return self._find_mission_subtitle() is not None  # 小活动单页弹窗：副标题 CHALLENGE 命中即就位。

    def _other_claim_all_panel_present(self):  # 活动任务弹窗也带「全部领取」：弹窗在则不是登录奖励面板，跳过以免误点。
        return self._mission_popup_ready()  # 弹窗不在时该判据自然为 False，不影响大厅的登录奖励面板清理。

    def _mission_tabs(self):  # 在栏目区定位两个栏目，返回 {role: Box}；栏目区缺失或任一栏目未定位到返回 None。
        region = self._optional_box(_MISSION_ICON_BOX)  # 栏目区（coco 区域特征；缺失即无法判定栏目）。
        if region is None:  # 区域未标注（coco 版本不符 / 小活动弹窗无栏目）。
            return None  # 按无栏目处理。
        tabs = {}  # role -> 栏目框。
        for role, feature, pattern in _MISSION_TABS:  # 逐栏目定位。
            box = self._mission_tab_box(region, feature, pattern)  # 特征模板匹配优先，栏目文案兜底。
            if box is None:  # 该栏目未定位到。
                return None  # 栏目不全即不按多栏目流程处理。
            tabs[role] = box  # 记录栏目框。
        return tabs  # 返回全部栏目框。

    def _mission_tab_box(self, region, feature, pattern):  # 定位单个栏目：coco 特征模板匹配优先，未命中回落栏目文案 OCR。
        # 选中态会改变栏目图标外观（当前页图标高亮），模板匹配可能落空，故保一层稳定文案兜底。
        hits = self.find_feature(feature, box=region)  # 在栏目区内模板匹配该栏目图标。
        if hits:  # 特征命中。
            return hits[0]  # 返回命中框。
        texts = self.ocr(box=region, match=[pattern])  # 栏目文案（跨期稳定的游戏 UI 文案）。
        return texts[0] if texts else None  # 文案命中即栏目框，未命中返回 None。

    def _mission_subtitle_text(self):  # 识别大活动弹窗副标题文字（页面状态判据），区域缺失或无文字返回 None。
        box = self._optional_box(_MISSION_DAILY_SUBTITLE_BOX)  # 副标题区域（coco 区域特征）。
        if box is None:  # 区域未标注（coco 版本不符）。
            return None  # 无法判定页面状态。
        texts = self.ocr(box=box)  # 区域内全部文字（逐期大小写/断行有差异，只做整段比较）。
        return "".join(text.name for text in texts) if texts else None  # 拼接成一段文本供切换前后比较。

    def _mission_switched_text(self, previous):  # 栏目切换判据：返回与切换前不同的副标题文字；未变化返回 None。
        text = self._mission_subtitle_text()  # 当前副标题文字。
        if text is not None and text != previous:  # 有文字且与切换前不同即已切页。
            return text  # 返回新状态供下一次比较。
        return None  # 未变化（或未识别到）继续轮询。

    def _switch_mission_tab(self, tab_box, previous):  # 点栏目标签并在副标题区确认页面已切换，返回切换后的副标题文字；未确认返回 None。
        # 栏目切换在同一模态框内换内容，无独立界面特征，判据只有副标题文字变化（点开默认停在「每日任务」页）。
        self.click_box(tab_box, after_sleep=1)  # 点击栏目标签。
        current = self.wait_until(lambda: self._mission_switched_text(previous),  # 等副标题变成与切换前不同。
                                  time_out=_MISSION_TAB_SWITCH_TIMEOUT, settle_time=0)  # 瞬态判据不额外稳定等待。
        if not current:  # 超时未确认切换。
            return None  # 由调用方决定降级处理。
        self.log_info(f"任务弹窗栏目已切换：{previous} → {current}")  # 记录切换前后的页面状态。
        return current  # 返回切换后的副标题文字。

    def _claim_mission_pages(self):  # 任务奖励领取编排：大活动两栏目各领一轮（先成就后每日任务），小活动单页领一轮。
        # 大活动弹窗每次点开都停在「每日任务」页，故先切「成就」领完，再切回「每日任务」领完；小活动无栏目直接领。
        tabs = self._mission_tabs()  # 栏目定位（小活动弹窗 / 栏目区未标注返回 None）。
        if tabs is None:  # 无栏目弹窗：单页领取。
            self._claim_mission_rewards()  # 循环领到「全部领取」灰白。
            return  # 结束领取。
        state = self._mission_subtitle_text()  # 记录点开时的页面状态（默认停在「每日任务」页）。
        if state is None:  # 副标题未识别到（区域未标注 / 渲染异常）：不冒险切换，只领当前页。
            self.log_warning("未识别到任务弹窗副标题，仅领取当前栏目")  # 记录降级原因。
            self._claim_mission_rewards()  # 只领当前页。
            return  # 结束领取。
        state = self._switch_mission_tab(tabs["challenge"], state)  # 切到「成就」栏目。
        if state is None:  # 切换未确认。
            self.log_warning("任务弹窗未切换到「成就」栏目，仅领取当前栏目")  # 记录降级原因。
            self._claim_mission_rewards()  # 只领当前页。
            return  # 结束领取。
        self._claim_mission_rewards()  # 成就栏目：循环领到「全部领取」灰白。
        if self._switch_mission_tab(tabs["daily"], state) is None:  # 切回「每日任务」栏目未确认。
            self.log_warning("任务弹窗未切换回「每日任务」栏目，结束领取")  # 记录结束原因（成就栏目已领完）。
            return  # 结束领取。
        self._claim_mission_rewards()  # 每日任务栏目：循环领到「全部领取」灰白。

    def _find_mission_subtitle(self):  # 在小活动弹窗副标题区域内 OCR 识别关键词，返回匹配框或 None（弹窗就位判据）。
        box = self._optional_box(_MISSION_SUBTITLE_BOX)  # 副标题区域（coco 区域特征；缺失时无法判定）。
        if box is None:  # 区域未标注（coco 版本不符）。
            self.log_warning(f"缺少区域特征: {_MISSION_SUBTITLE_BOX}")  # 记录缺失，便于排查。
            return None  # 视为弹窗未就位。
        boxes = self.ocr(box=box, match=[_MISSION_SUBTITLE_TEXT])  # 区域内 OCR 部分匹配副标题关键词。
        return boxes[0] if boxes else None  # 命中即弹窗已就位。

    def _claim_mission_rewards(self):  # 循环点「全部领取」直到按钮灰白；每轮点完等第二段重新可领，再回到按钮判态进入下一轮。
        for _ in range(_MISSION_CLAIM_MAX_CLICKS):  # 次数上限保护：点击未生效时不再无限循环。
            claim = self._find_claim_all()  # 弹窗底部「全部领取」文字（与签到印章同一判据文字与搜索区域）。
            if claim is None:  # 文字消失（弹窗已被关掉或页面结构变化）。
                self.log_warning("未识别到任务弹窗「全部领取」，停止领取")  # 记录异常供排查。
                return  # 结束领取。
            if not self.is_feature_enabled(self._claim_button_box(claim)):  # 外扩取到按钮底色判态：灰白 = 已无可领奖励。
                self.log_info("任务奖励已无可领取（「全部领取」为灰白态）")  # 记录结束状态。
                return  # 结束领取。
            self.click_box(claim, after_sleep=1)  # 点击全部领取（每日任务栏目为两段式：第一段领积分、第二段领奖励）。
            self.log_info("已点击任务弹窗「全部领取」")  # 记录动作。
            # 等待第二段就绪：轮询「全部领取」重新可领并稳定，覆盖两段式第二段晚于 click 后 1s 渲染的过渡期。
            # 不再用 dismiss_all_popups 的恒真 clear_condition（_mission_popup_ready 全程为真，起不到等第二段的作用，
            # 且会拉起整条弹窗清理管线）；每轮趁此清掉可能弹出的奖励遮罩（非必现）。超时静默进入下一轮，
            # 由顶部的灰白判态兜底确认已领完。
            self.wait_until(self._claim_all_claimable,
                            time_out=_MISSION_CLAIM_SETTLE_TIMEOUT,
                            settle_time=_MISSION_CLAIM_SETTLE,
                            pre_action=lambda: self._close_claim_overlay(time_out=1),
                            raise_if_not_found=False)
        self.log_warning(f"任务奖励领取点击达到上限 {_MISSION_CLAIM_MAX_CLICKS}，停止领取")  # 上限耗尽仍未收敛，记录异常。
