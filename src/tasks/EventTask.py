import random  # 随机模块，挑战关卡点击落点在区间内随机取偏移（避免每次点同一像素）。

import cv2  # OpenCV，列表滚动前后像素对比判到底/到顶。

from ok.feature.Box import Box, find_boxes_by_name  # 任务侧矩形构造（入口/行框/按钮区域）+ 复刻 ocr(match=...) 的按名过滤（入口定位用）。

from ok.task.exceptions import WaitFailedException  # 返回大厅失败等流程断言抛出的等待失败异常，由 try_step 恢复。

from src import event_calendar  # 官方活动日历缓存 + 活动图行匹配（纯本地读取，刷新是其唯一联网入口）。
from src import event_stage  # 活动关卡页读取策略（文本判据 + 几何切片 + 解析 + OCR 流水线；OCR 以回调注入）。
from src.tasks.NikkeBaseTask import NikkeBaseTask  # 项目基类，所有任务统一继承它。

from src.tasks.event._const import (  # 常量与身份工具集中处（避免 mixin 反向依赖本模块构成环）。
    _EVENT_ICON, _MENU_BAND_BOXES, _MAX_CARDS, _SCROLL_SWIPE_DURATION, _SCROLL_AFTER_SLEEP,
    _SCROLL_TOP_MAX_SWIPES, _SCROLL_UNCHANGED_RATIO, _SWIPE_START_RATIO, _SWIPE_END_RATIO,
    _STAGE_SWIPE_START_RATIO, _STAGE_SCAN_MAX_SCROLLS, _STORY_MODES, _STAGE_LIST_BOX, _STORY_BATTLE_TIMEOUT,
    _STORY_MAX_BATTLES, _STORY_FIELD_CHANGED_FEATURE, _STORY_FIELD_CHANGED_WAIT, _STORY_MAX_PUSH_ROUNDS,
    _STORY_DIALOG_WAIT, _STORY_SKIP_MAX, _STAGE_ENTER_TIMEOUT, _STAGE_DETAIL_BATTLE_BOX, _BATTLE_AFTER_SLEEP,
    _STORY_POLL_INTERVAL, _SWEEP_STAGES, _SWEEP_STAGE_DEFAULT, _SWEEP_MAX_ROUNDS, _SWEEP_BATTLE_TIMEOUT,
    _SWEEP_QUICK_BOX, _SWEEP_PAGE_FEATURE, _SWEEP_MAX_FEATURE, _SWEEP_START_BOX, _SWEEP_CLOSE_FEATURE,
    _CHALLENGE_LIST_BOX, _CHALLENGE_STAGE_FEATURE, _CHALLENGE_CLICK_X_OFFSET, _CHALLENGE_CLICK_ATTEMPTS,
    _CHALLENGE_PAGE_SETTLE, _SD_ARRIVE_TIMEOUT, _CLAIM_ALL_TEXT, _CLAIM_ALL_SCAN_BOX, _CLAIM_ALL_PAD,
    _MISSION_SUBTITLE_BOX, _MISSION_SUBTITLE_TEXT, _MISSION_ICON_BOX, _MISSION_TABS,
    _MISSION_DAILY_SUBTITLE_BOX, _MISSION_READY_TIMEOUT, _MISSION_TAB_SWITCH_TIMEOUT,
    _MISSION_CLAIM_MAX_CLICKS, _MISSION_CLAIM_SETTLE_TIMEOUT, _MISSION_CLAIM_SETTLE,
    normalize_roman_numerals, _STORY_MENU_PATTERNS, _STORY_SUB_PATTERN, _ENTRY_LOCK_BRIGHT_V,
    _ENTRY_LOCK_BRIGHT_RATIO, _MENU_PROBE_ENTRIES, _ENTRIES, _ENTRY_EXTRA_BOXES, _SUBFLOW_ORDER,
    _SUBFLOW_METHODS, _SKIPPED_ENTRIES, _ENTRY_CLICK_Y_OFFSET, _ENTRY_EXTRA_CLICK_Y_OFFSET,
    _EVENT_KEY_PREFIX, _EVENT_FLOW_PERIOD, _PER_EVENT_FLOWS, _LEGACY_DONE_KEY, _BIG_EVENT_TYPE,
    event_identity, event_done_key,
)


class EventTask(NikkeBaseTask):  # 活动任务：自动处理限时活动的通用内容（签到/剧情/挑战/任务/商店）。

    # 完成状态：真实键按活动身份动态生成（event_<身份>[_<流程>]，见 event_done_key），
    # 本表只作「本任务有完成状态」的声明锚（任务卡的「重置完成状态」按钮据此显示），不参与读写；
    # is_completed/clear_done_all 已覆盖为按身份判定与整族清理，旧版聚合键 event 只清不写。
    done_keys = {_LEGACY_DONE_KEY: "day"}

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "活动"  # 任务显示名称。
        self.description = "自动处理限时活动，活动首次开放时需手动进入并配队（剧情(BETA)/扫荡/挑战/任务/商店/签到印章）。"  # 任务说明。
        self._current_event = None  # 当前处理的活动（日历条目）；失败恢复回大厅后重入时用它 banner 定位。
        self._event_identity = None  # 当前处理的活动身份（完成状态键用）；接管路径也会填，但那条是非权威身份。
        self._identity_authoritative = False  # 身份是否来自日历 key（权威）；只有权威身份允许写完成状态。
        self.default_config.update({  # 子流程专属设置，独立持久化到 configs/。
            "签到": True,  # 是否收取活动签到印章奖励（仅大活动）。
            "剧情": False,  # 是否推进活动剧情。
            "扫荡": True,  # 是否对可重复关卡执行快速战斗扫荡。
            "扫荡关卡": _SWEEP_STAGE_DEFAULT,  # 扫荡目标关卡编号。
            "挑战": True,  # 是否执行活动挑战。
            "任务": True,  # 是否领取活动任务奖励。
            "商店": False,  # 是否购买活动商店（v1 默认关闭，非幂等流程留 v1.5）。
            "剧情模式": _STORY_MODES[0],  # 剧情关卡难度（难度选择未实现，先隐藏入口，见 config_type）。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "签到": "收取活动签到印章奖励。",
            "剧情": "自动推进活动剧情关卡（BETA）。",
            "扫荡": "对可重复通关的关卡执行快速战斗扫荡。扫荡与剧情共用门票，流程固定先推图后扫荡。",
            "扫荡关卡": "扫荡目标关卡（1-11/1-09/1-07 为大多数活动都存在的可重复关卡）。",
            "挑战": "执行活动挑战关卡。",
            "任务": "领取活动任务奖励。",
            "商店": "购买活动商店商品（v1 暂不启用）。",
            "剧情模式": "剧情关卡难度（v1 仅支持普通）。",
        })
        self.config_type.update({  # 配置类型与显隐控制：下拉选项、开关联动（sub_configs）与隐藏项在此声明。
            # 难度选择尚未实现：「剧情模式」只保留选项定义并 hidden 隐藏入口。
            # 注意不能挂到「剧情」的 sub_configs 下——框架渲染子配置的路径
            # （ConfigCard.__addConfigWithSubConfigs）只跳过 `_` 前缀、不检查 hidden，会被渲染出来。
            "剧情模式": {  # 剧情关卡难度下拉单选。
                "type": "drop_down",  # 下拉选项类型。
                "options": list(_STORY_MODES),  # NORMAL / HARD（沿用游戏内标签）。
                "hidden": True,  # 隐藏入口：框架 ConfigCard.__is_hidden_config 跳过顶层渲染。
            },
            "商店": {  # 商店子流程 v1 未实现：先隐藏入口（同剧情模式，不挂 sub_configs）。
                "hidden": True,  # 隐藏入口：框架 ConfigCard.__is_hidden_config 跳过顶层渲染。
            },
            "扫荡": {  # 布尔开关，启用时才展开关卡选择。
                "sub_configs": {  # 开关联动子配置显隐。
                    True: ["扫荡关卡"],  # 启用时显示扫荡关卡。
                    False: [],  # 关闭时收起配置。
                },
            },
            "扫荡关卡": {  # 扫荡目标关卡下拉单选。
                "type": "drop_down",  # 下拉选项类型。
                "options": list(_SWEEP_STAGES),  # 1-11 / 1-09 / 1-07。
            },
        })

    # ---- 入口编排 ----

    def run(self):  # 任务执行入口：已在活动内→就地接管（含日历外的往期活动/档案馆）；否则按日历完成状态短路或走列表。
        self.log_info("活动任务开始")  # 记录任务开始。
        if self._probe_event_context():  # 已在活动内：一律就地接管，先判它再判日历完成状态。
            # 顺序不能反：往期活动/档案馆页面不在日历里，先过「在架活动均已完成」的短路会让这类页面本轮什么都不做。
            # 本判据只读帧（is_screen/特征匹配），不点击、不置前，所以对「不在活动内」的正常路径没有额外代价。
            self.log_info("已在活动内，就地接管处理")  # 记录接管分支。
            if not self.try_step(self._takeover_event, name="活动接管", raise_on_fail=False):  # 接管流程用恢复协议包裹。
                self.log_warning("活动接管处理多次失败，本周期不标记完成")  # 记录失败原因。
                return  # 不标记完成，下次可重试。
            if not self._todo_events():  # 接管已覆盖全部待处理活动（或日历没有待处理活动）：无需再走列表。
                self.log_info("接管已覆盖全部待处理活动，直接收尾")  # 记录提前收尾原因。
                self._finish_run()  # 剪枝 + 返回大厅 + 收尾日志。
                return  # 结束任务。
            # 接管只处理了当前这一页（往期活动页/日历外活动页做不了 banner 定位）：在架活动仍需回大厅按列表处理。
            self.log_info("接管后仍有待处理活动，回大厅按列表继续处理")  # 记录转列表处理原因。
        elif self._all_live_events_done():  # 不在活动内且在架活动均已按身份完成：跳过（纯本地快照判定：不联网、不动窗口）。
            self.log_info("今日活动均已完成，跳过")  # 记录跳过原因。
            return  # 结束任务。
        if not self.ensure_screen("lobby", raise_on_fail=False):  # 就位游戏大厅（幂等闸门：含冷启动引导与弹窗清理），失败则中止。
            self.log_error("未能进入游戏大厅，中止活动任务")  # 记录中止原因。
            return  # 结束任务。
        if not self.try_step(self._process_event_list, name="活动列表处理", raise_on_fail=False):  # 列表处理整体流程以大厅为起点，用恢复协议包裹。
            self.log_warning("活动列表处理多次失败，本周期不标记完成")  # 记录失败原因。
            return  # 不标记完成，下次可重试。
        self._finish_run()  # 剪枝 + 返回大厅 + 收尾日志。

    def _finish_run(self):  # 运行收尾：清理已轮换活动的完成状态键 → 返回大厅 → 记录完成。
        # 完成状态由 _process_event_list 逐个活动落盘（身份化键），接管路径只读不写：此处只做键的剪枝与收尾。
        self._prune_identity_keys()  # 清掉不在当前活动清单里的旧身份键（活动轮换后完成状态不再累积）。
        self._exit_to_lobby()  # 统一返回大厅收尾（基类幂等实现）。
        self.log_info("活动任务完成")  # 记录任务完成。

    # ---- 完成状态：按活动身份判定 / 清理 ----

    def _live_identities(self):  # 在架活动身份列表（纯本地快照读，用于完成判定与剪枝，不联网）。
        return [event_identity(event.key) for event in self._pending_events(refresh=False)]  # 日历 key -> 身份段。

    def _all_live_events_done(self):  # 在架活动是否已全部按身份完成；无活动数据时 False（不谎报完成）。
        identities = self._live_identities()  # 在架活动身份。
        return bool(identities) and all(self.is_done(event_done_key(identity), "day") for identity in identities)  # 全部完成才算完成。

    def _todo_events(self):  # 本日尚未处理的活动（在架活动里滤掉已完成身份），是列表遍历的实际目标集合。
        return [event for event in self._pending_events()  # 待处理活动快照（快照过期才联网刷新）。
                if not self.is_done(event_done_key(event_identity(event.key)), "day")]  # 身份键已完成则该活动本日不再处理。

    def is_completed(self):  # 覆盖基类：完成口径 = 在架活动是否已全部按身份完成（与 run 的短路判据同源，UI 与行为一致）。
        if self._in_debug():  # debug 模式不判完成（同基类：便于反复调试）。
            return False  # 直接返回未完成。
        return self._all_live_events_done()  # 纯本地快照判定，UI 刷新不触发联网。

    def clear_done_all(self):  # 覆盖基类：完成键是身份化动态键，按前缀整族清理（含历史身份与旧版聚合键）。
        removed = self.clear_done_matching(  # 走基类清理工具，完成状态的读写细节留在 DoneStateMixin。
            lambda key: key.startswith(_EVENT_KEY_PREFIX) or key == _LEGACY_DONE_KEY)  # 活动身份键族 + 旧版聚合键。
        self.log_debug(f"已清除 {removed} 条活动完成状态")  # 记录清理数量，便于排查。

    def _prune_identity_keys(self):  # 清理配置里已不在当前活动清单里的身份键（活动轮换后完成状态不再累积）。
        identities = set(self._live_identities())  # 当前快照的在架活动身份。
        if not identities:  # 无本地活动清单（离线/无快照）：不动，避免把好数据删掉。
            return  # 结束清理。

        def stale(key):  # 该键是否属于已轮换掉的身份（含其子流程键）。
            if not key.startswith(_EVENT_KEY_PREFIX):  # 非身份键。
                return key == _LEGACY_DONE_KEY  # 旧版聚合键顺手清掉。
            rest = key[len(_EVENT_KEY_PREFIX):]  # 去掉前缀后的「身份[_流程]」段。
            return not any(rest == identity or rest.startswith(identity + "_") for identity in identities)  # 身份段不在在架清单内。

        removed = self.clear_done_matching(stale)  # 清掉轮换前遗留的身份键。
        if removed:  # 只在确实清理时记日志。
            self.log_debug(f"清理已轮换活动的完成状态 {removed} 条")  # 记录清理数量。

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

    # ---- 列表处理 ----

    def _process_event_list(self):  # 活动列表处理主循环：大厅→列表页→逐位置滚动→banner 定位待处理活动并进入处理，最后返回大厅。
        events = self._todo_events()  # 待处理活动：在架活动里本日尚未完成身份键的那些。
        if not events:  # 无日历数据或本日已全部处理完时不必进列表页。
            self.log_info("无待处理剧情活动（日历无数据或今日均已完成），结束列表处理")  # 记录结束原因。
            return  # 结束列表处理（由 run 统一收尾）。
        processed = set()  # 本运行内已处理的活动 key（双活动去重，不落持久状态）。
        unmatched = {event.key for event in events}  # 本运行尚未匹配到卡片的活动（遍历结束仍在 = 列表里没有）。
        for step in range(_MAX_CARDS):  # 带上限的滚动位置遍历。
            if not self._reposition_list(step):  # 进入列表页并滚动到第 step 位；到底返回 False 退出。
                self.log_info("列表已滚动到底，退出遍历")  # 记录到底。
                break  # 退出循环。
            for event in events:  # 扫描全部待处理活动（find_event_row 按 banner 匹配，未命中 = 该位置无此活动）。
                if event.key in processed:  # 已处理过则跳过。
                    continue  # 下一个活动。
                row = self._find_event_row(event)  # banner 匹配定位该活动所在行。
                if row is None:  # 当前滚动位置没有该活动。
                    continue  # 下一个活动。
                identity = event_identity(event.key)  # 列表路径拿到日历 key：身份权威，允许读写身份键。
                self._current_event = event  # 记录当前活动，供子流程失败恢复回大厅后重入时 banner 定位。
                self._event_identity = identity  # 子流程按它落身份化完成状态。
                self._identity_authoritative = True  # 权威身份：允许落盘。
                self._enter_and_probe(row)  # 点击进入并确认是活动，命中则执行子流程。
                self._current_event = None  # 处理结束清除上下文，避免下次重入定位到错误活动。
                self._event_identity = None  # 同步清除身份，避免后续流程误用别的活动的身份。
                self._identity_authoritative = False  # 身份权限同步复位。
                processed.add(event.key)  # 记录已处理。
                unmatched.discard(event.key)  # 已定位到卡片，不再算未匹配。
                # 卡片定位到即视为本日已处理（含命中卡片但未确认进入活动的误命中）：与旧版聚合键的落盘口径一致，
                # 避免下一次运行为了同一个活动再扫一遍列表。
                self.mark_done(event_done_key(identity), "day")  # 记录该活动本日已完成。
                self.log_info(f"活动 {identity} 本日完成状态已记录")  # 记录落盘键，便于排查串台。
                if not self._recover_to_lobby():  # 活动页返回键直接回大厅，此处确认已回大厅。
                    raise WaitFailedException("活动处理结束未回到大厅")  # 抛异常由 try_step 恢复。
                if not unmatched:  # 剩余待处理活动都已定位处理，没有第二张卡要扫，无需再进列表点 event_icon。
                    break  # 退出内层；外层随后依据 unmatched 为空提前结束。
                if not self._reposition_list(step):  # 返回大厅后重进列表并滚回本位置，继续扫描同位置剩余活动。
                    self.log_info("列表已滚动到底，退出遍历")  # 记录到底。
                    break  # 退出内层扫描。
            if not unmatched:  # 全部待处理活动均已定位处理，无需再往下滚动找卡片。
                break  # 提前结束遍历。
        for key in unmatched:  # 全部位置扫完仍未匹配到卡片：活动未上架/已下架，或保底包已过期。
            self.log_warning(f"活动 {key} 在列表页未匹配到卡片（未上架/已下架，或保底包已过期），本日不再重试")  # 记录便于排查。
            # 未匹配也按「本日已处理」落盘：否则此后每次运行都会为了这张不存在的卡片把列表重新扫一遍。
            self.mark_done(event_done_key(event_identity(key)), "day")  # 记录该活动本日已完成（未上架/已下架口径）。
        self._exit_to_lobby()  # 收尾返回大厅（run 里还会再幂等确认一次）。

    def _reposition_list(self, step):  # 进入列表页并滚动到第 step 个位置，返回是否定位成功（到底返回 False）。
        self._enter_event_list()  # 从大厅进入活动列表页。
        self._scroll_list_to_top()  # 先向上滚到底归一化到顶部。
        return step == 0 or self._scroll_list_down(step)  # 顶部位置无需下滚；下滚到底返回 False。

    def _enter_event_list(self):  # 大厅 -> 活动列表页（大厅右侧「活动」图标入口）。
        if self.is_screen("event_list_page"):  # 已在列表页（跨屏扫描连调 _reposition_list 时）则跳过：event_icon 是大厅图标，列表页上不存在，再点必超时。
            return  # 幂等：不重复点入口。
        self.transition("event_list_page", click_feature=_EVENT_ICON, wait_confirm=10, after_sleep=5)  # 点击入口并确认进入列表页。

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

    def _pending_events(self, refresh=True):  # 待处理剧情活动快照：本地读快照；快照缺失/过期时按 refresh 决定是否联网刷新。
        snapshot = event_calendar.load_snapshot()  # 应用启动已在后台静默刷新，纯本地读。
        if refresh and (snapshot is None or not snapshot.is_fresh(600)):  # 无快照或快照超过 600s TTL，且允许联网。
            snapshot = event_calendar.refresh()  # 刷新（内部含保底包兜底，不抛异常）。
        if snapshot is None:  # 不联网且没有本地快照（首次运行且离线）。
            return []  # 无本地数据即无待处理活动。
        return list(snapshot.pick_events(2))  # 按 start_time 倒序取最新 2 个未过期剧情活动（end_time=0 视为未知保留）。

    def _find_event_row(self, event):  # 用官方活动图在列表内 banner 匹配定位该活动所在行，返回行 Box 或 None。
        path = event_calendar.local_banner_path(event.key, event.url)  # 本地活动图路径（cache -> 保底包，纯本地）。
        if path is None:  # 无本地活动图（断网且不在保底包）。
            self.log_warning(f"活动「{event.display_name}」无本地活动图，无法定位")  # 记录跳过原因。
            return None  # 视为该活动当前不可定位。
        return self.find_event_row(event.display_name, path)  # 在 box_event_banner_area 内匹配该活动行。

    def _enter_event(self, row_box):  # 点击卡片进入活动主页并等菜单就绪；返回是否确认为活动（超时判非活动条目）。
        self.click_box(row_box, after_sleep=10)  # 点击卡片（10 秒覆盖过场动画与菜单稳定）。
        # 入场动画容忍 + 遮罩清理：特殊活动页面可能有入场动画或「点击任意处/跳过」遮罩，
        # 轮询期间每轮顺手清理遮罩（dismiss_all_popups 无遮罩立即返回），超时前不得判「非活动」。
        entered = self.wait_until(  # 轮询判定已进入活动主页（每轮取新帧）。
            lambda: self.is_screen("event_main"),  # event_main 判定（剩余时间关键词 OCR）。
            time_out=12,  # 动画容忍窗口 8~12s。
            pre_action=lambda: self.dismiss_all_popups(wait_for_popup=False, time_out=2),  # 期间清理入场遮罩。
        )
        if not entered:  # 超时未确认到活动主页 = 抽卡/登录奖励等非活动条目。
            self.log_info("未进入活动（抽卡/登录奖励等非活动条目）")  # 记录未确认原因。
            return False  # 由调用方决定退回大厅或抛异常。
        self.log_info("已进入活动主页，等待菜单栏就绪")  # 记录进入确认与后续等待。
        self._wait_menu_ready()  # 等菜单栏渲染并停稳再探测（标题先于菜单出现，过早探测会误判子流程全跳过）。
        return True  # 已确认为活动主页。

    def _enter_and_probe(self, row_box):  # 进入活动并执行子流程（列表处理路径）；返回是否确认为活动。
        if self._enter_event(row_box):  # 确认为活动主页（含菜单就绪等待）。
            self._run_event_subflows()  # 进入后按 _ENTRIES 探测各功能入口并执行。
            return True  # 已确认为活动并处理完子流程。
        self._recover_to_lobby()  # 退回大厅（活动页返回键直接回大厅，此处用恢复协议兜底）。
        return False  # 抽卡/登录奖励等非活动条目。

    def _locate_event_row(self, event):  # 在活动列表页内自上而下滚动定位指定活动的卡片行，返回行 Box；未找到返回 None。
        self._scroll_list_to_top()  # 归一到顶部再逐位下滚（进入列表页时可能停在任意滚动位置）。
        for _ in range(_MAX_CARDS):  # 带上限防死循环。
            row = self._find_event_row(event)  # banner 匹配定位该活动所在行。
            if row is not None:  # 当前滚动位置命中该活动。
                return row  # 返回可点击的行 Box。
            if not self._scroll_list_down(1):  # 下滚一位；到底返回 False。
                break  # 到底仍未命中。
        return None  # 遍历上限内未找到。

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

    # ---- 功能子流程 ----

    def _run_event_subflows(self):  # 在活动主页内逐入口探测并执行已开启的子流程（大小活动差异由「探测不到即跳过」吸收）。
        for label in _SUBFLOW_ORDER:  # 按 _SUBFLOW_ORDER 顺序分派。
            if not self.is_screen("event_main"):  # 上一子流程中途恢复回了大厅/别的页面：菜单带与入口都不在，继续探测只会误判。
                self.log_warning(f"执行 {label} 前不在活动主页，中止剩余子流程")  # 记录中止原因（正常收尾由 run 统一负责）。
                return  # 中止剩余子流程，避免在错误页面上继续探测。
            getattr(self, _SUBFLOW_METHODS[label])()  # 调用 _do_* 入口方法（内部做开关/探测/try_step）。
        for label in _SKIPPED_ENTRIES:  # v1 跳过的入口：仅探测并记录，不执行。
            if self._probe_entry(label):  # 探测到该入口。
                # 小游戏后续接入 MINIGAMES 注册表分派。
                self.log_info(f"探测到 {label}，v1 暂不支持，跳过")  # 记录跳过。

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

    def _flow_checkin(self):  # 签到印章流程（自足重入）：进签到界面 → 等 SD 小人到达 → 全部领取 → 点返回回活动菜单页。
        # 仅大活动有签到入口（_do_checkin 已按「签到印章」关键词探测）；签到是独立整页界面（非模态窗），
        # 各期美术不同，进入/可领判据一律走 OCR 文字（同登录奖励），不依赖模板。
        self._nav_to_event_main()  # 就位活动主页（正常已就位；恢复回大厅后由此重入）。
        entry = self._entry_box("签到")  # 签到印章入口命中框。
        if entry is None:  # 入口缺失（菜单未渲染或页面结构变化）。
            raise WaitFailedException("未找到签到印章入口")  # 抛异常由 try_step 恢复。
        self.click_box(entry, after_sleep=2)  # 点击签到入口，大活动 SD 小人开始走向签到地点。
        # 签到页无专有界面判据 → 反向判：点击后活动菜单页（event_main）消失即已切到签到页（小人已走到）；
        # 仍在菜单页 = 未走到签到地点、切页失败，告警后直接回菜单页跳过领取。
        if not self.wait_until(lambda: not self.is_screen("event_main"),  # 轮询等菜单页消失 = 已切到签到页。
                               time_out=_SD_ARRIVE_TIMEOUT, settle_time=0):  # 到达等待窗口（切页即返回）。
            self.log_warning("签到页未在预期时间内切换（仍在活动菜单页），跳过领取")  # 记录跳过原因。
            self._ensure_event_menu()  # 兜底回菜单页。
            return  # 结束签到流程。
        # 已切到签到页：等「全部领取」出现后判态领取（奖励界面与切页近乎同步，仍轮询容忍盖章动画）。
        if self.wait_until(lambda: self._find_claim_all() is not None,  # 轮询等「全部领取」出现 = 奖励界面就绪。
                           time_out=_SD_ARRIVE_TIMEOUT, settle_time=1.5):  # 命中后再稳定 1.5s，吸收盖章动画里按钮仍位移的过渡期。
            claim = self._find_claim_all()  # 「全部领取」按钮文字框。
            if self.is_feature_enabled(self._claim_button_box(claim)):  # 外扩取到按钮底色判态：彩色 = 仍有可领奖励。
                self.click_box(claim, after_sleep=1)  # 点击全部领取。
                self.log_info("已点击签到印章「全部领取」")  # 记录动作。
                self._close_claim_overlay()  # 领取后弹出奖励遮罩（盖住界面），复用登录奖励同一套遮罩清理。
            else:  # 按钮灰白 = 无可领奖励（今日已领完）。
                self.log_info("签到奖励无可领取（按钮灰白，可能今日已领取）")  # 记录状态。
        else:  # 已切页但未识别到「全部领取」。
            self.log_warning("签到奖励界面未在预期时间内出现（已切页但未识别到「全部领取」），跳过领取")  # 记录跳过原因。
        # 签到是独立整页界面（非模态窗）：点返回键回活动菜单页（已在菜单页则 no-op）。
        # 注意：不要用 dismiss_all_popups —— 签到界面「全部领取」与登录奖励面板判据同字，
        # 会被 _close_daily_login_popup 误认成登录奖励面板重复点击（其消歧只认 mission_page 与
        # 活动任务弹窗，签到页两者都不命中）。
        self._ensure_event_menu()  # 返回活动菜单页，供后续子流程接续。

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

    # ---- 剧情关卡页 OCR 与解析（横向标注整屏竖条 → 行锚点/均匀切片降级） ----

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

    # ---- 剧情执行链（方案 §8：推图链 + 扫荡链） ----

    def _row_box(self, row):  # 解析层行框（x1,y1,x2,y2 四元组）-> 可点击 Box（click_box 只接受 Box/特征名）。
        x1, y1, x2, y2 = row.box  # 行框为整图坐标四元组。
        return Box(x1, y1, x2 - x1, y2 - y1, name=f"event_stage_{row.stage_id or 'unknown'}")  # 行窄条区域。

    def _story_poll_throttle(self):  # 等待循环节流：挂在 post_action 上，未命中那轮才执行。
        self.sleep(_STORY_POLL_INTERVAL)  # 降低采样频率（窗口与判据不变）。

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

    def _push_stages(self):  # 连续推图链：自下而上找第一个能推的关卡并点开 → 逐场战斗（结算「下一关」可用则续战，跳到门票耗尽）→ 回关卡页。
        """返回本轮推图是否收工：True = 正常结束（无可推关卡/门票耗尽/战斗失败）；False = 出现换地区提示并已点掉。

        False 时当前界面是「活动地区」页（关卡页已消失），调用方需重新识别菜单页的剧情入口、
        重新进关卡页再推一轮（见 _flow_story 的轮次循环）。
        """
        if not self._open_pushable_stage():  # 自下而上找可推关卡并点开（没有就说明本地区推完了）。
            return True  # 结束推图（仍在关卡列表页，无需收尾动作）。
        for _ in range(_STORY_MAX_BATTLES):  # 连续战斗安全上限（正常由门票耗尽自然结束）。
            self._skip_story_if_present()  # 进关卡/进下一关可能先播剧情：识别并点跳过。
            if self._field_changed_stop():  # 跳过剧情后可能已换地区：本轮到此为止，交调用方重推一轮。
                return False  # 已回到活动地区页：交调用方重新进关卡页再推一轮。
            result, confirm_box = self.wait_battle_finish(time_out=_STORY_BATTLE_TIMEOUT)  # 节流等待战斗结束，只检测不点击。
            if result is None:  # 等待战斗结束超时。
                if self._field_changed_stop():  # 兜底：换地区比预想晚（战斗根本没开起来）时，别白等满超时再判失败。
                    return False  # 已回到活动地区页：交调用方重新进关卡页再推一轮。
                raise WaitFailedException("等待活动关卡战斗结束超时")  # 抛异常由 try_step 恢复。
            if result == "failed":  # 战斗失败（门票已消耗，不再续战）。
                self.log_warning("活动关卡战斗失败")  # 记录失败供排查。
                self.click_box(confirm_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 点击失败返回按钮。
                self._skip_story_if_present()  # 返回时也可能先播剧情。
                if self._field_changed_stop():  # 失败返回后同样可能换地区。
                    return False  # 已回到活动地区页。
                break  # 结束推图。
            next_box = self._optional_box("box_battle_finish_next_stage")  # 结算界面右下角「下一关」区域（缺失按不可用）。
            if next_box is not None and self.is_feature_enabled(next_box):  # 彩色高亮 = 还有门票可续战。
                self.log_info("结算界面「下一关」可用，继续推进")  # 记录续战。
                self.click_box(next_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 点击下一关，回到循环头部等待下一场。
                # 实机：点「下一关」后也可能直接切地区（不经过剧情/战斗）——这里紧跟一次判定，别等满 240s 超时。
                if self._field_changed_stop():
                    return False  # 已回到活动地区页：交调用方重新进关卡页再推一轮。
                continue  # 续战。
            self.click_box(confirm_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 「下一关」不可用 = 门票耗尽，点击结算返回按钮。
            self._skip_story_if_present()  # 返回时也可能先播剧情。
            if self._field_changed_stop():  # 结算返回后同样可能换地区。
                return False  # 已回到活动地区页。
            break  # 推图结束。
        else:  # 循环用尽仍未自然结束 = 异常状态。
            self.log_warning(f"连续战斗达到上限 {_STORY_MAX_BATTLES} 场，停止推图")  # 提示异常，交界面断言兜底。
        self.assert_screen("event_stage_page", time_out=15)  # 确认已回到活动关卡界面（剧情跳过后的落点）。
        return True  # 本轮推图收工。

    def _field_changed_stop(self, time_out=_STORY_FIELD_CHANGED_WAIT):  # 是否发生换地区：True = 需重新进关卡页再推一轮。
        """大活动（FieldHub）清完一个地区后切到新地区，两个信号任一成立即算（都不依赖时间假设）：

        ① 提示按钮 `event_story_field_changed` 在画面上 → 点掉它（点完回到活动地区页）；
        ② 人已经回到「活动地区」页 → 关卡流程已结束——按钮可能没渲染出来，也可能刚被跳过剧情的
           弹窗清理顺手点掉，所以不能只认按钮（实机：按钮会出现在「战斗结束 → 点击下一关」之后）。
        按钮只可能在「战斗已结束/未开始」时出现，故在战斗界面内不等待（不拖慢正常推图）。
        """
        if not self.feature_exists(_STORY_FIELD_CHANGED_FEATURE):  # coco 未标注：只认状态信号（旧包/未标定也能跑）。
            return self._stop_on_event_area_page()  # 只看是否已回到活动地区页。
        hit = self._wait_field_changed_hit(time_out)  # 取提示按钮：当前帧命中即返回，必要时给一小段出现窗口。
        if hit is not None:  # 提示在画面上：点掉它（点完自动回活动地区页），需要重推一轮。
            self.log_info("识别到活动地区切换提示，点击返回活动地区页")  # 记录动作，便于核对换地区时机。
            self.click_box(hit, after_sleep=_BATTLE_AFTER_SLEEP)  # 点击提示按钮（等待覆盖切页动画）。
            return True  # 需要重推一轮。
        return self._stop_on_event_area_page()  # 按钮没看到：再看是否已经回到活动地区页。

    def _stop_on_event_area_page(self):  # 是否已回到「活动地区」页 = 关卡流程已结束（换地区，或异常退出）。
        if not self._probe_event_main():  # 仍在关卡页/战斗/对话等：没有换地区。
            return False  # 不处理。
        self.log_info("已回到活动地区页（关卡流程结束），按换地区收尾，重新进关卡页再推一轮")  # 记录判据来源便于实机核对。
        return True  # 需要重推一轮。

    def _wait_field_changed_hit(self, time_out):  # 取换地区提示按钮：当前帧命中即返回；不在战斗界面才等一小段。
        try:  # 特征名在配置里但模板加载失败时按不出现处理。
            hit = self.find_one(_STORY_FIELD_CHANGED_FEATURE)  # 即时：帧上就有，零额外等待。
            if hit is not None or self._in_battle_page():  # 已命中，或正在战斗（提示不可能在场）：不进等待。
                return hit  # 返回当前结果（None = 没命中）。
            return self.wait_feature(_STORY_FIELD_CHANGED_FEATURE, time_out=time_out, settle_time=0,  # 命中即返回，不等稳定窗口。
                                     raise_if_not_found=False,  # 不在战斗：提示可能正在渲染，给一小段出现窗口。
                                     post_action=self._story_poll_throttle)  # 轮询节流（见 _STORY_POLL_INTERVAL）。
        except ValueError:  # 特征缺失/模板加载失败。
            return None  # 按不出现处理。

    def _open_pushable_stage(self):  # 自下而上找第一个能推的关卡并点开：进到关卡流程（剧情/战斗）返回 True，全不可推返回 False。
        """可用性一律走界面后验：候选行上的 CLEAR / REPEAT / 锁图标既不参与解析也不作门槛
        （实机会漏检，锁孔还会被读成编号），逐个点开看详情页「战斗」是否可用。

        只看当前屏：点剧情入口进关卡页后列表停在当前进度关，能推的关就在这一屏里，故不滚动、不跨屏扫描。
        当前屏有候选行但都点不出可推的关 = 本地区推完了。扫荡目标不同（已通关的关卡可能在当前屏外），
        故 `_locate_stage_row` 会滚动查找。
        """
        box = self._stage_list_box()  # 列表区。
        rows = self._stage_rows(box) if box is not None else []  # 当前屏候选行（行框即当前屏坐标）。
        if self._open_first_pushable(rows):  # 自下而上找（最下面的候选行最接近当前进度关）。
            return True  # 已进入关卡流程。
        if not rows:  # 一行都没解析出：多半是 OCR 漏检/页面没就绪，而不是真的没得推。
            self.log_warning("当前屏未解析出任何关卡行（OCR 漏检或页面未就绪），推图结束")  # 与「有行但都不可推」分开记，便于实机排查。
            return False  # 本地区按推完收工（列表停在当前进度关，不滑动查找）。
        self.log_info("当前屏没有可推的关卡（已全通或未开放），推图结束")  # 记录结束原因。
        return False  # 本地区推完（列表停在当前进度关，不滑动查找）。

    def _open_first_pushable(self, rows):  # 自下而上逐个点开候选行，命中可推关卡返回 True；都不可推返回 False。
        for row in reversed(rows):  # 最下面的候选行最接近当前进度关（列表顺序 = 解锁顺序）。
            if row.stage_id is None:  # 没有编号的行点不中（编号漏检时序列共识会补号，补不出来就不试）。
                continue
            opened = self._open_row_for_push(row)  # 点开并判态。
            if opened:  # 已在关卡流程里（或「战斗」已点）。
                return True  # 命中可推关卡。
            if opened is None:  # 可推性判不了（详情页区域特征缺失）：每行都会卡在同一处，不再往下试。
                return False  # 结束本轮找关卡。
        return False  # 这一屏没有可推的关。

    def _open_row_for_push(self, row):  # 点开候选行判可推性：可推/已开战返回 True、不可推返回 False、判不了返回 None。
        self.click_box(self._row_box(row), after_sleep=2)  # 点击关卡行进入关卡（可能先播剧情）。
        landing = self._stage_landing()  # 等落点分类（离开列表不等于进了关卡流程，见 _stage_landing）。
        if landing == "list":  # 仍停在关卡列表 = 该关不可推（已通关不可重复挑战/未解锁，只弹提示）。
            self.log_info(f"{row.stage_id} 点开后仍停在关卡列表（已通关不可重复挑战或未解锁），试上一行")  # 记录跳过原因。
            return False  # 列表没动，继续试上一行。
        if landing == "flow":  # 直接进了剧情/战斗 = 这一关就是当前进度关（首次进关先播剧情）。
            self.log_info(f"{row.stage_id} 点开后直接进入关卡流程（剧情/战斗），按当前进度关推进")  # 记录选中原因。
            return True  # 已在流程里，交给战斗链。
        if landing is None:  # 落点没认出来（过场卡住/未知页面）：判不了可推性。
            self.log_warning(f"{row.stage_id} 点开后未识别到关卡流程落点（详情页/剧情/战斗/列表），停止找关卡")  # 记录跳过原因。
            return None  # 交调用方停止找关卡（每行都会卡在同一处）。
        battle_box = self._optional_box(_STAGE_DETAIL_BATTLE_BOX)  # 详情页「战斗」区域（缺失按不可点）。
        if battle_box is None:  # 区域特征解析不出来（coco 缺失/加载失败）。
            self.log_warning(f"缺少区域特征 {_STAGE_DETAIL_BATTLE_BOX}，推图结束")  # 记录跳过原因。
            self._close_stage_detail()  # 关详情页回关卡列表。
            return None  # 判不了可推性：交调用方停止找关卡。
        if not self.is_feature_enabled(battle_box):  # 灰白禁用：该关不可推（门票耗尽/已通关不可重复挑战）。
            self.log_info(f"{row.stage_id} 详情页「战斗」为灰白禁用态（门票耗尽等），试上一行")  # 记录结束原因。
            self._close_stage_detail()  # 关详情页回关卡列表（下一行还要在列表上点）。
            return False  # 继续试上一行。
        self.log_info(f"{row.stage_id} 详情页「战斗」可用，点击进入战斗")  # 记录推进（可能先播剧情）。
        self.click_box(battle_box, after_sleep=2)  # 点「战斗」进入战斗链。
        return True  # 已开战。

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

    def _sweep_stage(self, stage_id):  # 扫荡：点配置关卡行 → 详情页「快速战斗」（次数拉满）→ 结算回列表，循环到不可用（耗尽）。
        for round_index in range(1, _SWEEP_MAX_ROUNDS + 1):  # 带上限防死循环（次数拉满后正常一轮即耗尽）。
            row = self._locate_stage_row(stage_id)  # 定位配置关卡（当前屏没有会滚动查找；行框对应当前屏幕，可直接点击）。
            if row is None:  # 整份列表都没有该关 = 该关尚未通关/未开放（不是识别失败），不做任何降级替代。
                self.log_warning(f"列表中没有可扫荡关卡 {stage_id}（尚未通关/未开放），跳过扫荡")  # 记录跳过原因。
                return  # 结束扫荡。
            # 行上的已通关标记（√ / CLEAR / REPEAT）一律不看、也不解析：能否扫荡以关卡详情页的
            # 「快速战斗」判态为准（门票用光时详情页仍可打开）。
            self.click_box(self._row_box(row), after_sleep=2)  # 点关卡行进入关卡详情页。
            if not self.wait_feature(_SWEEP_CLOSE_FEATURE, time_out=_STAGE_ENTER_TIMEOUT, raise_if_not_found=False):  # 等详情页就位（右上关闭按钮特征）。
                self.log_info(f"{stage_id} 点开后未进入关卡详情页（已通关但不可重复挑战会弹提示、停在列表），跳过扫荡")  # 记录跳过原因。
                return  # 仍在关卡列表页：无需关页，直接结束扫荡（交由调用方回菜单页）。
            quick_box = self._optional_box(_SWEEP_QUICK_BOX)  # 「快速战斗」区域。
            if quick_box is None:  # 区域特征解析不出来（coco 缺失/加载失败）——与「按钮不可用」是两种问题，分开记日志。
                self.log_warning(f"缺少区域特征 {_SWEEP_QUICK_BOX}，跳过扫荡")  # 记录跳过原因。
                self._close_stage_detail()  # 关闭详情页回列表。
                return  # 结束扫荡。
            enabled = self.is_feature_enabled(quick_box)  # 色彩判态：彩色=可用，灰白=禁用。
            self.log_debug(f"{stage_id}「快速战斗」区域 {quick_box}，色彩判态 {enabled}")  # 判态明细便于实机校准。
            if not enabled:  # 灰白禁用：门票已被推图耗尽，或该关当前不可重复挑战。
                self.log_info(f"{stage_id}「快速战斗」为灰白禁用态（与剧情共用门票，可能已被推图耗尽；或该关不可重复挑战），扫荡结束")  # 记录结束原因。
                self._close_stage_detail()  # 关闭详情页回列表。
                return  # 结束扫荡。
            self._run_quick_battle(quick_box, label=f"扫荡 {stage_id} 第 {round_index} 轮")  # 快速战斗链（拉满 → 开始 → 等结算 → 点确认）。
            if self._detail_page_open():  # 结算关闭后落回关卡详情页（扫荡页面的默认落点）。
                self._close_stage_detail()  # 先关详情页退回活动关卡列表，下一轮重新定位关卡行。
            self.assert_screen("event_stage_page", time_out=15)  # 确认已回到活动关卡列表界面。
        self.log_warning(f"扫荡达到轮次上限 {_SWEEP_MAX_ROUNDS} 轮，结束")  # 上限兜底（异常状态）。

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

    def _find_available_challenge_stage(self):  # 挑战页自下而上找第一个可用（非灰白）关卡标记，返回其 Box；无可用返回 None。
        list_box = self._optional_box(_CHALLENGE_LIST_BOX)  # 挑战关卡列表区域（定位范围；特征缺失返回 None）。
        if list_box is None:  # 列表区未标注。
            self.log_warning(f"缺少区域特征 {_CHALLENGE_LIST_BOX}，无法定位挑战关卡")  # 记录缺失，便于排查。
            return None  # 无法定位。
        try:  # 关卡标记特征可能尚未标注进 coco。
            stages = self.find_feature(_CHALLENGE_STAGE_FEATURE, box=list_box, limit=0, use_gray_scale=True)  # 灰度匹配全部关卡标记（颜色无关），可用性再走 is_feature_enabled。
        except ValueError:  # 特征缺失。
            self.log_warning(f"缺少特征 {_CHALLENGE_STAGE_FEATURE}，无法定位挑战关卡")  # 记录缺失，便于排查。
            return None  # 无法定位。
        self.log_debug(f"挑战关卡标记命中 {len(stages)} 个：{[(s.x, s.y) for s in stages]}")  # 命中明细便于实机校准。
        for stage in sorted(stages, key=lambda item: item.y, reverse=True):  # 自下而上（y 由大到小）逐个判态。
            if self.is_feature_enabled(stage):  # 非灰白 = 可用关卡。
                self.log_info(f"挑战选中可用关卡标记 {stage}")  # 记录选中目标。
                return stage  # 返回第一个可用的（自下而上最近）。
        self.log_info("挑战列表全部关卡标记均为灰白禁用态（今日次数已用完）")  # 记录无可打原因。
        return None  # 无可用关卡。

    def _challenge_click_box(self, stage):  # 关卡标记 -> 点击框：标记贴行右边缘，沿 X 轴随机左移落进行主体。
        low = int(self.width * _CHALLENGE_CLICK_X_OFFSET[0])  # 左移量下限（像素）。
        high = int(self.width * _CHALLENGE_CLICK_X_OFFSET[1])  # 左移量上限（像素）。
        offset = random.randint(low, high) if high > low else low  # 区间随机取偏移（分辨率过小时退化为定值）。
        box = Box(stage.x - offset, stage.y, stage.width, stage.height,  # 同尺寸左移，不改写原命中框。
                  confidence=stage.confidence, name=stage.name)
        self.log_debug(f"挑战关卡点击框左移 {offset}px：{stage} -> {box}")  # 偏移量便于实机校准落点。
        return box  # 返回落入行主体的点击框。

    def _wait_challenge_nodes(self, time_out=_SD_ARRIVE_TIMEOUT):  # 挑战页过场动画：等关卡节点渲染出来，再多等一会（标题先于节点出现）。
        list_box = self._optional_box(_CHALLENGE_LIST_BOX)  # 挑战关卡列表区域（搜索范围）。
        if list_box is None:  # 区域未标注。
            return  # 交 _find_available_challenge_stage 记日志兜底。
        try:  # 关卡标记特征可能尚未标注进 coco。
            ready = self.wait_until(lambda: bool(self.find_feature(_CHALLENGE_STAGE_FEATURE, box=list_box, limit=0,
                                                                    use_gray_scale=True)),
                                    time_out=time_out, settle_time=_CHALLENGE_PAGE_SETTLE)  # 轮询等节点渲染（灰度匹配）。
        except ValueError:  # 特征缺失。
            ready = False
        if not ready:  # 节点未在窗口内渲染完成。
            self.log_warning("挑战关卡节点未在预期窗口内渲染完成")  # 记录后由 finder 兜底。

    def _flow_story(self):  # 剧情流程（自足重入）：进关卡页 → 推图（剧情开关）→ 扫荡（扫荡开关）→ 返回活动菜单页。
        # 闸门：本流程从活动主页出发；失败恢复回大厅后由 _nav_to_event_main 用当前活动上下文
        # （大厅→列表→banner→活动主页）重新进入，不递归触发子流程（只进活动，不探测入口）。
        self._nav_to_event_main()  # 就位活动主页（正常已就位；恢复回大厅后由此重入）。
        mode = self.config.get("剧情模式", _STORY_MODES[0])  # 剧情关卡难度（配置项已隐藏，实现前保持默认）。
        if mode != _STORY_MODES[0]:  # 非默认值（历史配置残留或手改）：难度选择未实现。
            self.log_info(f"剧情模式 {mode} 暂未支持，按页面当前难度继续")  # TODO 实机标定 box_event_stage_mode 的选中态与点击。
        self._enter_stage_page()  # 活动菜单页 → 关卡页（大活动要经 STORY I/II 剧情子页面绕一级）。
        if self.config.get("剧情"):  # 推图开关（与扫荡独立，任一开启都进关卡页）。
            for round_index in range(1, _STORY_MAX_PUSH_ROUNDS + 1):  # 换地区后要重新进关卡页再来一轮（带上限防死循环）。
                if round_index > 1:  # 第 2 轮起：上一轮以换地区收尾，当前在活动地区页，需重新识别菜单页的剧情入口。
                    self.log_info(f"第 {round_index} 轮推图：重新识别菜单页并进入关卡页")  # 记录轮次与重新进入的原因。
                    self._enter_stage_page()  # 活动地区页 → 关卡页（入口与 STORY 章节重新定位，新地区可能解锁了下一章）。
                if self._push_stages():  # 本轮推图收工（无可推关卡/门票耗尽/战斗失败）。
                    break  # 结束推图。
                # False = 出现换地区提示并已点掉：当前在活动地区页，进入下一轮（重新进关卡页）。
            else:  # 轮次用尽仍在换地区 = 异常状态。
                self.log_warning(f"推图达到轮次上限 {_STORY_MAX_PUSH_ROUNDS} 轮，停止推图")  # 记录异常，交由后续界面断言兜底。
                return  # 当前是活动地区页（不是关卡页）：直接结束子流程，免得在错误页面上做扫荡/导航。
        if self.config.get("扫荡"):  # 扫荡开关：对配置的可重复关卡快速战斗。
            self._sweep_stage(self.config.get("扫荡关卡", _SWEEP_STAGE_DEFAULT))  # 点行 → 详情页快速战斗（次数拉满）→ 扫到不可用。
        try:  # 点返回回活动菜单页，供后续子流程接续（大活动剧情子页面多退一级）。
            self._ensure_event_menu()
        except WaitFailedException:  # 往期活动/档案馆页面退不回活动菜单页：剧情已经推进完，不该把整条剧情判失败。
            self.log_warning("剧情收尾未能退回活动菜单页（可能是往期活动/档案馆页面），按当前页面继续")  # 记录降级原因。

    def _enter_stage_page(self):  # 活动菜单页 → 关卡页：小活动直接用「加成」入口进，大活动先经 STORY I/II 剧情子页面。
        entry = self._entry_box("剧情")  # 剧情入口命中框（大活动菜单页 STORY II → STORY I，小活动主页「加成」）。
        if entry is None:  # 入口缺失（页面结构变化或菜单未渲染）。
            raise WaitFailedException("未找到剧情入口")  # 抛异常由 try_step 恢复。
        if self._is_story_main_entry(entry):  # 大活动菜单页：STORY I/II 打开的是剧情子页面而非关卡页。
            self._enter_story_sub_page()  # 逐个尝试 STORY 入口（STORY II 优先，未开放的章节回落下一个入口）。
            entry = self._entry_box("剧情")  # 子页面内重新定位剧情入口（与小活动同款）。
            if entry is None:  # 子页面内没有剧情入口（未渲染完或该期页面结构不同）。
                raise WaitFailedException("剧情子页面内未找到剧情入口")  # 抛异常由 try_step 恢复。
        self.transition("event_stage_page", box=entry, wait_confirm=10, after_sleep=1)  # 点击剧情入口并确认进入关卡页。

    def _story_entry_boxes(self):  # 菜单页各 STORY 入口命中框（按 _STORY_MENU_PATTERNS 优先级：STORY II → STORY I）；未出现的跳过。
        entries = []  # 候选入口命中框。
        for pattern in _STORY_MENU_PATTERNS:  # 优先级即列表顺序。
            box = self._entry_box("剧情", patterns=[pattern])  # 只按该关键词定位（STORY I/II 同时出现时是两个独立入口）。
            if box is not None:  # 该入口出现在菜单栏（未开放的章节也会被 OCR 读到文字）。
                entries.append(box)  # 收集候选。
        return entries  # 至多两个。

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

    def _enter_story_sub_page(self):  # 点开 STORY 入口进入剧情子页面：STORY II 优先，点不开的章节回落下一个入口。
        # STORY I/II 会同时出现在菜单栏，未开放的章节只多了锁图标、文字仍是灰字（OCR 照常读到），
        # 点它不会切页；只认第一个命中框会让「锁一个入口」拖垮整条剧情链（含 STORY I 的推图与扫荡）。
        for entry_box in self._story_entry_boxes():  # 候选按优先级：STORY II → STORY I。
            if self._entry_locked(entry_box):  # 亮度前置判断：整行灰暗 = 锁定入口，跳过省掉一次 _SD_ARRIVE_TIMEOUT 空等。
                self.log_info(f"{entry_box.name} 亮度判据为锁定态（整行灰暗），跳过并尝试下一个剧情入口")  # 记录跳过原因。
                continue  # 下一个候选。
            if self._try_enter_story_sub_page(entry_box):  # 点开并等剧情子页面就位。
                return  # 已进入剧情子页面。
            if not self.is_screen("event_main"):  # 点开后不在活动菜单页（锁定提示等落点）：先退回菜单页再试下一个候选。
                self._ensure_event_menu()  # 逐级退回菜单页。
        raise WaitFailedException("STORY 入口均不可用（章节未开放或页面结构变化）")  # 抛异常由 try_step 恢复。

    def _try_enter_story_sub_page(self, entry_box):  # 点 STORY 入口并等剧情子页面就位，返回是否成功。
        # 子页面左上标题同为「剧情活动」（event_main 判定命中）、没有活动菜单，没有可用于 wait_screen 的独有判据，
        # 故反向判就位：小活动同款剧情入口（「加成」）出现即子页面可操作（同签到页反向判切页）。
        self.click_box(entry_box, after_sleep=2)  # 点击 STORY 入口切页。
        ready = self.wait_until(lambda: self._story_sub_entry_ready(),  # 轮询等剧情入口出现（每轮取新帧）。
                                time_out=_SD_ARRIVE_TIMEOUT, settle_time=1.5)  # 命中后再稳定 1.5s，吸收切页动画里按钮仍位移的过渡期。
        if not ready:  # 窗口内未出现剧情子页面入口 = 该章节未开放/不可用。
            self.log_warning(f"{entry_box.name} 点开后未进入剧情子页面（章节未开放/不可用）")  # 记录回落原因。
        return ready  # 交由调用方决定回落下一个入口。

    def _story_sub_entry_ready(self):  # 剧情子页面就位判据：出现小活动同款剧情入口（STORY I/II 入口只在大活动菜单页）。
        entry = self._entry_box("剧情")  # 当前页面的剧情入口。
        return entry is not None and not self._is_story_main_entry(entry)  # 命中「加成」类入口即子页面已可操作。

    def _flow_challenge(self):  # 挑战流程（自足重入）：进挑战页 → 战斗/扫荡 → 返回活动菜单页。
        # 大小活动都有「挑战」，且为同一套 UI（已确认）。
        # 进入方式差异（大活动点击后 SD 小人先走到地点再切页、小活动点击即切页）统一走 transition
        # 守卫式进入：其 retry_click 补点实测不中断小人行为（仍继续走到挑战地点再切页），故可安全复用，
        # 不再手写「只点一次 + 轮询等挑战页」。
        self._nav_to_event_main()  # 就位活动主页（正常已就位；恢复回大厅后由此重入）。
        entry = self._entry_box("挑战")  # 挑战入口命中框（大小活动入口文字都是「挑战」，_entry_box 已统一）。
        if entry is None:  # 入口缺失（菜单未渲染或页面结构变化）。
            raise WaitFailedException("未找到挑战入口")  # 抛异常由 try_step 恢复。
        # wait_confirm 覆盖小人到达窗口（_SD_ARRIVE_TIMEOUT），time_out 留出补点预算。
        try:  # 点击入口并确认进入挑战页。
            self.transition("event_challenge_page", box=entry, wait_confirm=_SD_ARRIVE_TIMEOUT,
                            time_out=_SD_ARRIVE_TIMEOUT * 2, after_sleep=2)
        except WaitFailedException:  # 补点耗尽仍未进挑战页。
            if not self.is_screen("event_main"):  # 落在别的界面：按失败交 try_step 恢复（不看错误页继续猜）。
                raise  # 重新抛出，交给 try_step。
            # 仍在活动菜单页 = 入口点击无效（往期活动/未开放入口：文字可读、点击无响应）：
            # 这里直接结束挑战流程，不再让 try_step 反复重跑（每次都要把补点重来一遍，白等一分多钟）。
            self.log_info("挑战入口点击无效（仍在活动菜单页，可能为锁定/未开放入口），跳过挑战")  # 记录跳过原因。
            return  # 结束挑战流程（已在菜单页，无需收尾导航）。
        self._wait_challenge_nodes()  # 等节点渲染完成再选关（吸收过场动画）。
        stage = self._find_available_challenge_stage()  # 自下而上找第一个可用（非灰白）关卡标记。
        if stage is None:  # 无可用关卡（今日次数已用完/列表未标注）：无需进详情页，直接返回菜单页。
            self._ensure_event_menu()  # 点返回键回活动菜单页。
            return  # 结束挑战流程。
        for attempt in range(1, _CHALLENGE_CLICK_ATTEMPTS + 1):  # 点空时重试（落点每次重新随机取，两次落点不重合）。
            self.click_box(self._challenge_click_box(stage), after_sleep=2)  # 点关卡标记（左移入行主体）进入关卡详情页。
            if self.wait_feature(_SWEEP_CLOSE_FEATURE, time_out=_STAGE_ENTER_TIMEOUT, raise_if_not_found=False):  # 等详情页就位（右上关闭按钮特征）。
                break  # 详情页已就位，继续详情页内的战斗分支。
            if attempt < _CHALLENGE_CLICK_ATTEMPTS:  # 还有剩余尝试次数。
                # 仍在挑战页 = 点击被吃掉/落点无效；已离开挑战页 = 页面开了但关闭按钮特征没认出来（改调 _STAGE_ENTER_TIMEOUT）。
                self.log_info(f"第 {attempt} 次点击挑战关卡未进入详情页"
                              f"（仍在挑战页={self.is_screen('event_challenge_page')}），重试")  # 记录重试原因与落点状态。
        else:  # 尝试次数用尽仍未进入详情页（正常应进详情页）。
            self.log_warning(f"点击挑战关卡 {_CHALLENGE_CLICK_ATTEMPTS} 次均未进入详情页，结束挑战")  # 记录异常落点供排查。
            self._ensure_event_menu()  # 兜底回菜单页。
            return  # 结束挑战流程。
        quick_box = self._optional_box(_SWEEP_QUICK_BOX)  # 详情页「快速战斗」区域。
        if quick_box is not None and self.is_feature_enabled(quick_box):  # 快速战斗可用：走快速战斗链。
            self._run_quick_battle(quick_box, label="挑战")  # 点快速战斗 → 次数拉满 → 开始 → 等结算 → 点确认。
        else:  # 快速战斗不可用（或区域缺失）：改判普通战斗「战斗」按钮。
            battle_box = self._optional_box(_STAGE_DETAIL_BATTLE_BOX)  # 详情页「战斗」区域。
            if battle_box is not None and self.is_feature_enabled(battle_box):  # 普通战斗可用：进战斗界面等结束。
                self.click_box(battle_box, after_sleep=2)  # 点「战斗」进入战斗界面（可能先播剧情）。
                self._skip_story_if_present()  # 进战斗可能先播剧情：识别并点跳过。
                result, confirm_box = self.wait_battle_finish(time_out=_STORY_BATTLE_TIMEOUT)  # 节流等待战斗结束（只检测不点击）。
                if result is None:  # 等待战斗结束超时。
                    raise WaitFailedException("等待挑战关卡战斗结束超时")  # 抛异常由 try_step 恢复。
                self.log_info(f"挑战战斗结束（{result}）")  # 记录结算结果。
                self.click_box(confirm_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 点结算返回键（回详情页或挑战页）。
            else:  # 快速战斗与普通战斗都不可用 = 当天已挑战过、没有次数。
                self.log_info("挑战快速战斗与普通战斗均不可用（今日已挑战/次数已用完），结束挑战")  # 记录结束原因。
        # 收尾：结算后可能落回详情页，则先关详情页；再点返回键回活动菜单页（挑战页/详情页返回键逐期不同，走三层兜底）。
        if self._detail_page_open():  # 仍在关卡详情页（快速/普通战斗后常见落点）。
            self._close_stage_detail(to_screen="event_challenge_page")  # 关详情页回挑战页。
        self._ensure_event_menu()  # 点返回键回活动菜单页（已在菜单页则 no-op）。

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

    def _claim_all_claimable(self):  # 当前帧「全部领取」是否重新可领（文字在且底色彩色）；遮罩盖住/过渡灰白均视为未就绪。
        claim = self._find_claim_all()  # 弹窗底部「全部领取」文字框。
        return claim is not None and self.is_feature_enabled(self._claim_button_box(claim))  # 文字在且底色彩色 = 第二段已就绪可领。

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

    def _flow_shop(self):  # 商店流程（自足重入）：购买活动商店商品。实机未标定前占位，非幂等流程留 v1.5。
        self.log_info("商店流程占位：TODO 实机标定商店页判据")  # 记录占位。
