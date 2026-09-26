from src.tasks.event._challenge import EventChallengeMixin  # 活动挑战。
from src.tasks.event._checkin import EventCheckinMixin  # 活动签到印章。
from src.tasks.event._claim import EventClaimMixin  # 「全部领取」按钮原语。
from src.tasks.event._common import EventCommonMixin  # 通用小工具（区域解析 / 列表滚动）。
from src.tasks.event._const import (  # 常量与身份工具集中处（避免 mixin 反向依赖本模块构成环）。
    _EVENT_KEY_PREFIX,
    _LEGACY_DONE_KEY,
    _STORY_MODES,
    _SWEEP_STAGE_DEFAULT,
    _SWEEP_STAGES,
    event_done_key,
    event_identity,
)
from src.tasks.event._entry import EventEntryMixin  # 入口探测 / 菜单导航 / 接管 / 子流程分派。
from src.tasks.event._list import EventListMixin  # 活动列表处理（滚动 + banner 定位）。
from src.tasks.event._minigame import EventMinigameMixin  # 活动内置小游戏。
from src.tasks.event._mission import EventMissionMixin  # 活动任务弹窗领取。
from src.tasks.event._stage import EventStageMixin  # 关卡页读取 / 详情页 / 快速战斗。
from src.tasks.event._story import EventStoryMixin  # 剧情推图链与扫荡。
from src.tasks.NikkeBaseTask import NikkeBaseTask  # 项目基类，所有任务统一继承它。


class EventTask(EventEntryMixin, EventListMixin, EventStoryMixin, EventStageMixin,
                EventChallengeMixin, EventMissionMixin, EventMinigameMixin, EventCheckinMixin,
                EventClaimMixin, EventCommonMixin, NikkeBaseTask):  # 活动任务：自动处理限时活动的通用内容（签到/剧情/挑战/任务/小游戏）。

    # 完成状态：真实键按活动身份动态生成（event_<身份>[_<流程>]，见 event_done_key），
    # 本表只作「本任务有完成状态」的声明锚（任务卡的「重置完成状态」按钮据此显示），不参与读写；
    # is_completed/clear_done_all 已覆盖为按身份判定与整族清理，旧版聚合键 event 只清不写。
    done_keys = {_LEGACY_DONE_KEY: "day"}

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "活动"  # 任务显示名称。
        self.description = "自动处理限时活动，活动首次开放时需手动进入并配队（剧情(BETA)/扫荡/挑战/任务/签到印章/小游戏）。"  # 任务说明。
        # 以下三项是跨 mixin 的共享状态：由列表路径（EventListMixin）写入，各子流程 mixin 读取。
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
            "小游戏": True,  # 是否游玩活动内置小游戏（仅 MINIGAMES 注册表里已接入的活动会执行）。
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
            "小游戏": "游玩活动内置小游戏：点位刷分到达标分数后快速完成结束本局，并领取小游戏任务奖励；当期活动的小游戏未支持时自动跳过。",
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

    # ---- 商店（v1 占位：实机标定商店页判据后独立成 _shop.py） ----

    def _flow_shop(self):  # 商店流程（自足重入）：购买活动商店商品。实机未标定前占位，非幂等流程留 v1.5。
        self.log_info("商店流程占位：TODO 实机标定商店页判据")  # 记录占位。
