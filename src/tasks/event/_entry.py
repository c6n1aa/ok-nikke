"""活动主页的入口探测、菜单导航、接管与子流程分派。

大小活动形态不同（大活动是地图页 + 签到印章，小活动是主页 + 加成入口），差异一律由
「探测不到即跳过」吸收：入口区域由 coco 标注（大小活动菜单带各一区），点击框按命中关键词微调。
接管路径没有列表定位结果，只能靠屏幕形态反推活动身份，故身份只读、不写完成状态。
"""

import cv2  # OpenCV：入口锁定判据的 HSV 亮度掩码（白字 / 高亮底）。

from ok.feature.Box import Box, find_boxes_by_name  # 入口点击框构造 + 复刻 ocr(match=...) 的按名过滤。

from ok.task.exceptions import WaitFailedException  # 入口缺失 / 退回菜单页失败等流程断言抛出的等待失败异常。

from src.tasks.event._const import (
    _MENU_BAND_BOXES, normalize_roman_numerals, _STORY_MENU_PATTERNS, _STORY_SUB_PATTERN, _ENTRY_LOCK_BRIGHT_V,
    _ENTRY_LOCK_BRIGHT_RATIO, _MENU_PROBE_ENTRIES, _ENTRIES, _ENTRY_EXTRA_BOXES, _SUBFLOW_ORDER,
    _SUBFLOW_METHODS, _SKIPPED_ENTRIES, _ENTRY_CLICK_Y_OFFSET, _ENTRY_EXTRA_CLICK_Y_OFFSET, _EVENT_FLOW_PERIOD,
    _PER_EVENT_FLOWS, _BIG_EVENT_TYPE, event_identity, event_done_key,
)


class EventEntryMixin:
    """活动主页的入口探测、菜单导航、接管与子流程分派。

    探测：`_entry_box` / `_probe_entry` 在专属区与大小活动菜单带内按关键词 OCR 定位入口；
    导航：`_ensure_event_menu` 逐级退回菜单页，`_nav_to_event_main` 是各子流程的统一闸门；
    接管：`_takeover_event` 在已在活动内时用屏幕形态 + 本地日历候选反推身份（只读，不落完成状态）；
    分派：`_run_event_subflows` 按 `_SUBFLOW_ORDER` 调 `_do_*`，各 `_do_*` 负责开关、探测、完成状态与 try_step。
    """

    def _probe_event_main(self):  # 探测当前是否处于活动主页。
        return self.is_screen("event_main")  # 单帧判定（进入后的动画容忍由 _enter_and_probe 的轮询负责）。

    def _probe_event_context(self):  # 探测当前是否已在活动内（活动主页 / 关卡页 / 挑战页 / 关卡详情页）。
        return (self._probe_event_main() or self.is_screen("event_stage_page")  # 主页 / 剧情关卡页。
                or self.is_screen("event_challenge_page") or self._detail_page_open())  # 挑战页 / 详情页（任一命中即视为在活动内）。

    def _probe_menu_entries(self):  # 活动菜单入口是否可见（大活动地图页 / 小活动主页都有这些入口）。
        return any(self._probe_entry(label) for label in _MENU_PROBE_ENTRIES)  # 任一菜单入口命中即菜单在。

    def _probe_story_sub_page(self):  # 是否处于大活动剧情子页面：左上标题同为「剧情活动」，但只有小活动同款剧情入口、没有活动菜单。
        if not self._probe_event_main() or self._probe_menu_entries():  # 不在活动主页，或活动菜单在（= 菜单页）。
            return False  # 不是剧情子页面。
        entry = self._entry_box("剧情")  # 该页面唯一可用的剧情入口。
        return entry is not None and not self._is_story_main_entry(entry)  # 命中「加成」类入口才算。

    def _ensure_event_menu(self):  # 把活动子页面退回活动菜单页（已在菜单页则不动），供接管分支与子流程收尾使用。
        if self._probe_event_main() and not self._probe_story_sub_page():  # 已在活动菜单页（大活动地图页 / 小活动主页）。
            return  # 无需导航。
        if self._detail_page_open():  # 关卡详情页。
            self._close_stage_detail()  # 先关到关卡列表页。
        # 返回键样式逐期/逐子页不同（签到等活动子页的 common_back 模板实测仅 0.41，模板匹配会失败），
        # 故走基类 _find_back_button（模板精确 → 左下角区域兜底 → OCR「返回」三层）。
        self.transition("event_main", click=self._click_back_to_menu, wait_confirm=10, after_sleep=1)  # 子页面 → 上一级。
        if self._probe_story_sub_page():  # 落在剧情子页面（关卡页的上一级就是它）：再退一级回活动菜单页。
            self.transition("event_main", click=self._click_back_to_menu, wait_confirm=10, after_sleep=1)  # 剧情子页面 → 地图页。

    def _click_back_to_menu(self):  # 点击活动子页面的返回按钮回菜单页（基类三层兜底定位，功能同 click_box(common_back)）。
        back = self._find_back_button()  # 模板精确 → 左下角区域模板 → OCR「返回」。
        if back is None:  # 三层都未命中（页面非活动子页或按钮被遮挡）。
            raise WaitFailedException("未找到活动子页面返回按钮")  # 抛异常由 try_step/transition 处理。
        self.click_box(back, after_sleep=1)  # 点击返回键。

    def _takeover_event(self):  # 接管流程：已在活动内时先回菜单页，用屏幕形态反推活动身份，再逐入口探测执行已开启子流程。
        try:  # 子页面先退回菜单页（菜单带不在子页面上，形态判据也只在菜单页成立）。
            self._ensure_event_menu()  # 已在菜单页时是 no-op。
        except WaitFailedException:  # 往期活动/档案馆页面结构不同：退不回去就按当前页面继续，不让整条接管失败。
            # 这类页面不是活动子页面，返回键会把页面带出活动；宁可留在当前页让子流程各自探测入口
            # （剧情入口在往期活动页上通常仍可探测），也不要一路往上退把用户带跑。
            self.log_warning("接管时未能退回活动菜单页（可能是往期活动/档案馆页面），按当前页面继续")  # 记录降级原因。
        identity = self._resolve_takeover_identity()  # 接管身份：屏幕形态 + 本地日历候选反推，判不出为 None。
        self._event_identity = identity  # 身份只供读取：接管不是权威来源，不写完成状态（见 _mark_subflow_done）。
        self._identity_authoritative = False  # 明确非权威：身份键只读。
        try:  # 无论流程怎么退出都要复位身份上下文。
            # 接管不做整体短路：当前页可能是日历里没有的往期活动（档案馆，通常只开放剧情），
            # 身份要么判不出、要么恰好撞上别的候选——一旦整体跳过，就把「往期活动的剧情推进」也一起跳过了。
            # 非幂等流程（签到/商店）由各自的 _subflow_completed 读身份键跳过，幂等流程（剧情/挑战/任务）照跑。
            if identity:  # 形态 + 候选唯一命中：身份可用于读身份键。
                self.log_info(f"接管身份推断为 {identity}（只读，不落完成状态）")  # 记录身份来源与权限。
            else:  # 形态判不出/候选不唯一/无本地日历。
                self.log_info("接管路径未能判定活动身份（可能是日历外的往期活动），按身份未知处理")  # 记录降级原因。
            self._run_event_subflows()  # 在菜单页内按 _ENTRIES 探测各功能入口并执行。
        finally:  # 复位身份上下文，运行内不残留。
            self._event_identity = None  # 清空身份。

    def _probe_event_form(self):  # 当前活动页形态：返回 (是否大活动形态, 是否小活动形态)，两者互斥才可用。
        big = self._probe_entry("签到")  # 大活动地图页独有「签到印章」入口。
        small = self._entry_box("剧情", patterns=[_STORY_SUB_PATTERN]) is not None  # 小活动/剧情子页面独有的「加成奖励妮姬」入口。
        return big, small  # 都命中或都不命中 = 形态判不出。

    def _resolve_takeover_identity(self):  # 接管路径的活动身份：本地日历候选 + 屏幕形态自证；判不出返回 None。
        """接管路径没有列表定位结果，只能反推身份：用「大/小活动形态」筛日历候选。

        形态与日历类型（FieldHubEvent = 大活动）必须一致，且恰好剩一个候选才算确定；
        判不出（无快照 / 形态同真同假 / 候选不唯一）一律返回 None，调用方按「身份未知」处理
        （不读也不写身份键），宁可重复跑一遍幂等流程，也不冒误标到别的活动头上的风险。
        """
        events = self._pending_events(refresh=False)  # 纯本地快照：接管路径不新增联网。
        if not events:  # 无本地活动清单。
            self.log_debug("无本地活动清单，接管路径不判定活动身份")  # 记录降级原因。
            return None  # 身份未知。
        big, small = self._probe_event_form()  # 形态探针只跑一次（各一次区域 OCR）。
        if big == small:  # 都命中/都不命中：形态无法消歧。
            self.log_warning("活动形态判不出（签到印章与加成入口同真同假），接管路径不判定活动身份")  # 记录降级原因。
            return None  # 身份未知。
        matched = [event for event in events if (event.event_type == _BIG_EVENT_TYPE) == big]  # 形态与日历类型一致的候选。
        if len(matched) != 1:  # 无候选或多个候选：无法唯一确定当前活动。
            self.log_warning(f"活动候选不唯一（形态命中 {len(matched)} 个，日历共 {len(events)} 个），接管路径不判定活动身份")  # 记录降级原因。
            return None  # 身份未知。
        return event_identity(matched[0].key)  # 唯一命中：返回该候选的身份段。

    def _subflow_key(self, label):  # 子流程的身份化完成键；身份未知或该流程不按身份记时返回 None。
        slug = _PER_EVENT_FLOWS.get(label)  # 该流程是否按活动身份各记一次。
        if not slug or not self._event_identity:  # 不按身份记，或当前身份未知。
            return None  # 无身份化完成键。
        return event_done_key(self._event_identity, slug)  # event_<身份>_<流程>。

    def _subflow_completed(self, label):  # 该子流程在本活动本周期内是否已记录完成（身份未知时按未完成处理）。
        key = self._subflow_key(label)  # 身份化完成键。
        return key is not None and self.is_done(key, _EVENT_FLOW_PERIOD)  # 有键且本周期已完成。

    def _mark_subflow_done(self, label):  # 记录该子流程在本活动本周期已完成；非权威身份只读，不落盘。
        key = self._subflow_key(label)  # 身份化完成键。
        if key is None:  # 身份未知或该流程不按身份记。
            return  # 无需落盘。
        if not self._identity_authoritative:  # 接管路径的身份是推断出来的：写错会把别的活动误标成本周期已完成。
            self.log_debug(f"{label} 完成状态未落盘（活动身份非权威来源）")  # 记录未落盘原因。
            return  # 只读身份不落盘。
        self.mark_done(key, _EVENT_FLOW_PERIOD)  # 记录本周期已完成。
        self.log_info(f"{label} 完成状态已记录：{key}")  # 记录落盘键，便于排查串台。

    def _menu_boxes(self):  # 解析出当前可用的菜单栏 OCR 区域（大小活动菜单带各自一区，缺失跳过）。
        boxes = []  # 已解析区域列表。
        for band in _MENU_BAND_BOXES:  # 大小活动菜单带范围不同，逐区解析。
            box = self._optional_box(band)  # 区域框（特征缺失/无可用帧均为 None）。
            if box is not None:  # 区域有效。
                boxes.append(box)  # 收集。
        return boxes  # 返回全部已解析区域。

    def _entry_regions(self, label):  # 该入口的可探测区域：[(区域框, 是否专属区)]，专属追加区（若有）在前，再回落大小活动菜单带。
        regions = []  # 已解析区域列表。
        for extra in _ENTRY_EXTRA_BOXES.get(label, ()):  # 该入口的专属区域（如大活动「任务」不在菜单带内）。
            box = self._optional_box(extra)  # 区域框（特征缺失返回 None）。
            if box is not None:  # 区域有效。
                regions.append((box, True))  # 标记专属区：点击框修正按专属区表算（小活动同关键词入口在菜单带里）。
        return regions + [(box, False) for box in self._menu_boxes()]  # 专属区优先，菜单带兜底（小活动入口仍在菜单带内）。

    def _entry_box(self, label, patterns=None):  # 按关键词顺序定位入口点击框（patterns 缺省取 _ENTRIES[label]）；未命中返回 None。
        patterns = _ENTRIES.get(label) if patterns is None else patterns  # 显式传入时只按这些关键词探测（STORY 候选逐个回落用）。
        if not patterns:  # 未知入口。
            return None  # 无法定位。
        for region, extra in self._entry_regions(label):  # 逐区（专属区 + 大小活动菜单带各一区）。
            boxes = self.ocr(box=region)  # 该区域一次 OCR（不按关键词过滤，供多关键词复用）。
            for box in boxes:  # 就地归一识别文本（Ⅱ/Ⅲ -> II/III）：关键词匹配与后续 name 判据（_is_story_main_entry）共用。
                box.name = normalize_roman_numerals(box.name)  # 归一后的文本即命中框名称。
            for pattern in patterns:  # 按优先级逐个关键词过滤（STORY II 先于 STORY I）。
                matched = find_boxes_by_name(boxes, self.fix_match_regex([pattern]))  # 与 ocr(match=...) 相同的部分匹配语义。
                if matched:  # 命中该关键词。
                    return self._entry_click_box(matched[0], pattern, extra)  # 命中文本框按命中区域补偏移后作为点击框。
        return None  # 全部关键词未命中。

    def _entry_click_box(self, hit, pattern, extra=False):  # 入口命中框 -> 点击框：按命中区域沿 Y 轴上移（命中文字可能落在图标/按钮边缘）。
        offsets = _ENTRY_EXTRA_CLICK_Y_OFFSET if extra else _ENTRY_CLICK_Y_OFFSET  # 专属区命中查专属区表，其余查通用表。
        offset = offsets.get(pattern.pattern, 0)  # 该关键词的上移量（占屏高比例），缺省不修正。
        if offset <= 0:  # 无需修正。
            return hit  # 命中框本身即点击框。
        return Box(hit.x, hit.y - int(self.height * offset), hit.width, hit.height,  # 同尺寸上移，不改写原命中框。
                   confidence=hit.confidence, name=hit.name)

    def _is_story_main_entry(self, entry):  # 命中框是否为大活动菜单页的 STORY I/II 入口（点开后进剧情子页面，不是关卡页）。
        name = entry.name  # 入口命中的 OCR 文字（_ENTRY_CLICK_Y_OFFSET 的偏移框也保留原文字）。
        return isinstance(name, str) and any(pattern.search(name) for pattern in _STORY_MENU_PATTERNS)

    def _wait_menu_ready(self, time_out=6):  # 等菜单栏内容渲染就绪：标题先于菜单出现，菜单另有入场动画不可立即点击。
        patterns = [p for ps in _ENTRIES.values() for p in ps]  # 全部入口关键词并集（任一命中即视为菜单已渲染）。
        ready = self.wait_until(  # 轮询菜单带 OCR（每轮取新帧）。
            lambda: any(self.ocr(box=box, match=patterns) for box in self._menu_boxes()),  # 任一菜单带命中任一关键词。
            time_out=time_out,  # 菜单渲染等待窗口。
            pre_action=lambda: self.dismiss_all_popups(wait_for_popup=False, time_out=2),  # 期间顺手清理入场遮罩。
            settle_time=1.5,  # 命中后再稳定 1.5s，吸收「文字已可识别却仍在位移动画、点击会落空」的过渡期。
        )
        if not ready:  # 窗口内菜单未就绪：可能为无功能菜单的纯剧情活动，不中断调用方。
            self.log_warning("菜单栏未在预期窗口内就绪（可能为无功能菜单的纯剧情活动）")  # 记录后继续，由探测器各自跳过。

    def _probe_entry(self, label):  # 在活动主页入口区域（专属区 + 菜单带）OCR 探测入口关键词，命中返回 True 否则 False。
        patterns = _ENTRIES.get(label) or []  # 该入口的关键词正则列表。
        if not patterns:  # 未知入口。
            return False  # 视为未命中。
        boxes = self._entry_regions(label)  # 当前可用的入口区域。
        if not boxes:  # 全部入口区域都未标注进 coco。
            self.log_warning(f"入口区域特征均未标注: {_MENU_BAND_BOXES}")  # 记录缺失，便于排查。
            return False  # 未命中。
        for region, _ in boxes:  # 逐区探测（专属区 + 大小活动菜单带范围不同）。
            if self.ocr(box=region, match=list(patterns)):  # 区域内 OCR 部分匹配任一关键词（首区命中即短路）。
                return True  # 命中即返回，无需查其余区域。
        return False  # 未命中。

    def _entry_locked(self, entry_box):  # 亮度前置判据：命中框内几乎无高亮像素（整行灰暗）= 锁定入口；判不出来保守返回 False。
        frame = self.frame  # 当前帧（无帧时判不了）。
        if frame is None:  # 单测/无帧：保守按未锁定处理，由点开后的行为后验兜底。
            return False  # 不跳过。
        x1, y1 = max(int(entry_box.x), 0), max(int(entry_box.y), 0)  # 命中框左上角裁到帧内。
        x2 = min(int(entry_box.x + entry_box.width), frame.shape[1])  # 右下角裁到帧内。
        y2 = min(int(entry_box.y + entry_box.height), frame.shape[0])
        if x2 <= x1 or y2 <= y1:  # 区域越界无效。
            return False  # 保守按未锁定。
        roi = frame[y1:y2, x1:x2]  # 命中框子图。
        bright = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)[:, :, 2] >= _ENTRY_LOCK_BRIGHT_V  # 高亮像素掩码（白字/高亮底）。
        ratio = float(bright.mean())  # 高亮像素占比。
        self.log_debug(f"入口 {entry_box.name} 高亮像素占比 {ratio:.3f}（锁定阈值 {_ENTRY_LOCK_BRIGHT_RATIO}）")  # 判据明细便于实机校准。
        return ratio < _ENTRY_LOCK_BRIGHT_RATIO  # 低于阈值 = 整行灰暗 = 锁定态。

    def _entry_locked_skip(self, label):  # 入口探测命中但呈锁定态（文字可读、点击无效）时返回 True；供 _do_* 提前跳过。
        """往期活动（档案馆）/未开放入口的文字照样能被 OCR 读到，但点击没有任何效果：

        靠亮度判据（_entry_locked）提前跳过，省掉一次注定失败的进入尝试（挑战那类 transition 补点要白点一分多钟）。
        只用在「命中框就是文字本身」的入口（签到/挑战/任务/商店）：「剧情」不适用——它的点击框按
        _ENTRY_CLICK_Y_OFFSET 上移到按钮主体，落到暗色按钮上会被误判成锁定态，
        而 STORY I/II 章节锁定另由 _enter_story_sub_page 的亮度判据处理。
        """
        entry = self._entry_box(label)  # 入口命中框（区域与关键词同 _probe_entry）。
        if entry is None or not self._entry_locked(entry):  # 定位不到（保守按可用）或非锁定态。
            return False  # 不跳过。
        self.log_info(f"{label}入口为锁定态（文字可读但点击无效），跳过")  # 记录跳过原因。
        return True  # 通知调用方跳过该子流程。

    def _nav_to_event_main(self):  # 幂等导航到活动主页（子流程闸门 + 失败恢复回大厅后的重入）。
        if self.is_screen("event_main"):  # 已在活动主页。
            return  # 无需导航（单帧命中即返回）。
        if self._probe_event_context():  # 在活动子页面（关卡列表页/关卡详情页）。
            self._ensure_event_menu()  # 逐级退回活动菜单页。
            return  # 已就位。
        event = self._current_event  # 失败恢复回大厅后的重入：需当前活动上下文才能 banner 定位。
        if event is None:  # 无上下文（非列表处理路径）时无法定位。
            raise WaitFailedException("不在活动内且无当前活动上下文，无法导航到活动主页")  # 抛异常由 try_step 恢复。
        self.ensure_screen("lobby")  # 就位游戏大厅（幂等闸门）。
        self._enter_event_list()  # 大厅 -> 活动列表页。
        row = self._locate_event_row(event)  # 在列表页内滚动定位当前活动卡片。
        if row is None:  # 保底包过期/活动已下架：无法重新定位。
            raise WaitFailedException(f"未能定位活动 {event.key} 的卡片，无法重入活动主页")  # 抛异常由 try_step 恢复。
        if not self._enter_event(row):  # 点击卡片进入活动主页（含菜单就绪等待）。
            raise WaitFailedException(f"重入活动 {event.key} 未确认进入活动主页")  # 抛异常由 try_step 恢复。

    def _run_event_subflows(self):  # 在活动主页内逐入口探测并执行已开启的子流程（大小活动差异由「探测不到即跳过」吸收）。
        for label in _SUBFLOW_ORDER:  # 按 _SUBFLOW_ORDER 顺序分派。
            if not self.is_screen("event_main"):  # 上一子流程中途恢复回了大厅/别的页面：菜单带与入口都不在，继续探测只会误判。
                self.log_warning(f"执行 {label} 前不在活动主页，中止剩余子流程")  # 记录中止原因（正常收尾由 run 统一负责）。
                return  # 中止剩余子流程，避免在错误页面上继续探测。
            getattr(self, _SUBFLOW_METHODS[label])()  # 调用 _do_* 入口方法（内部做开关/探测/try_step）。
        for label in _SKIPPED_ENTRIES:  # 尚未接入的入口：仅探测并记录，不执行（本期为空）。
            if self._probe_entry(label):  # 探测到该入口。
                self.log_info(f"探测到 {label}，尚未接入，跳过")  # 记录跳过。

    def _do_checkin(self):  # 签到子流程：开关 → 本活动完成状态 → 探测 → try_step → 落身份化完成状态。
        if not self.config.get("签到"):  # 用户未启用签到子流程。
            self.log_info("签到未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if self._subflow_completed("签到"):  # 本活动本周期内已领过（身份键命中）。
            self.log_info("本活动签到印章本周期已完成，跳过")  # 记录跳过原因（避免重入奖励面板走登录奖励误判链）。
            return  # 结束本子流程。
        if not self._probe_entry("签到"):  # 探测不到 = 当期小活动无此功能入口。
            self.log_info("未探测到签到入口（小活动无此功能），跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if self._entry_locked_skip("签到"):  # 往期活动/未开放入口：文字可读但点击无效。
            return  # 结束本子流程。
        if self.try_step(self._flow_checkin, name="签到", raise_on_fail=False):  # 签到整体流程用恢复协议包裹（自足重入）。
            self._mark_subflow_done("签到")  # 成功才记录完成状态。
        else:  # 恢复重试耗尽。
            self.log_warning("签到子流程多次失败，跳过")  # 记录失败原因。

    def _do_story(self):  # 剧情子流程：开关（剧情/扫荡任一开启）→ 探测（STORY II/I/加成 任一）→ try_step。
        if not self.config.get("剧情") and not self.config.get("扫荡"):  # 推图与扫荡都未开启。
            self.log_info("剧情与扫荡均未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self._probe_entry("剧情"):  # 探测不到剧情入口。
            self.log_info("未探测到剧情入口，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self.try_step(self._flow_story, name="剧情", raise_on_fail=False):  # 剧情整体流程（含扫荡）用恢复协议包裹。
            self.log_warning("剧情子流程多次失败，跳过")  # 记录失败原因。

    def _do_challenge(self):  # 挑战子流程：开关 → 探测 → try_step。
        if not self.config.get("挑战"):  # 用户未启用挑战子流程。
            self.log_info("挑战未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self._probe_entry("挑战"):  # 探测不到挑战入口。
            self.log_info("未探测到挑战入口，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if self._entry_locked_skip("挑战"):  # 往期活动/未开放入口：文字可读但点击无效。
            return  # 结束本子流程。
        if not self.try_step(self._flow_challenge, name="挑战", raise_on_fail=False):  # 挑战整体流程用恢复协议包裹。
            self.log_warning("挑战子流程多次失败，跳过")  # 记录失败原因。

    def _do_mission(self):  # 任务子流程：开关 → 探测（大活动专属区 / 小活动菜单带）→ try_step。
        if not self.config.get("任务"):  # 用户未启用任务子流程。
            self.log_info("任务未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self._probe_entry("任务"):  # 探测不到 = 当期活动无任务入口（大活动入口在 box_event_menu_mission 区）。
            self.log_info("未探测到任务入口，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if self._entry_locked_skip("任务"):  # 往期活动/未开放入口：文字可读但点击无效。
            return  # 结束本子流程。
        if not self.try_step(self._flow_mission, name="任务", raise_on_fail=False):  # 任务整体流程用恢复协议包裹。
            self.log_warning("任务子流程多次失败，跳过")  # 记录失败原因。

    def _do_shop(self):  # 商店子流程：开关（默认关闭）→ 本活动完成状态 → 探测 → try_step（非幂等流程，留 v1.5）。
        if not self.config.get("商店"):  # 用户未启用商店子流程（v1 默认关闭）。
            self.log_info("商店未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if self._subflow_completed("商店"):  # 本活动本周期内已购买过（身份键命中）：非幂等流程不得重跑。
            self.log_info("本活动商店本周期已完成，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self._probe_entry("商店"):  # 探测不到商店入口。
            self.log_info("未探测到商店入口，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if self._entry_locked_skip("商店"):  # 往期活动/未开放入口：文字可读但点击无效。
            return  # 结束本子流程。
        if self.try_step(self._flow_shop, name="商店", raise_on_fail=False):  # 商店整体流程用恢复协议包裹。
            self._mark_subflow_done("商店")  # 成功才记录完成状态（失败不落盘，下次可重试）。
        else:  # 恢复重试耗尽。
            self.log_warning("商店子流程多次失败，跳过")  # 记录失败原因。
