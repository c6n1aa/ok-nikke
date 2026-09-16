import re  # 正则模块，入口关键词用 OCR 部分匹配（忽略大小写）。

import cv2  # OpenCV，列表滚动前后像素对比判到底/到顶。

from ok.feature.Box import Box, find_boxes_by_name  # 行窄带的 Box（行锚点切片 OCR 用）+ 复刻 ocr(match=...) 的按名过滤（入口定位用）。

from ok.task.exceptions import WaitFailedException  # 返回大厅失败等流程断言抛出的等待失败异常，由 try_step 恢复。

from src import event_calendar  # 官方活动日历缓存 + 活动图行匹配（纯本地读取，刷新是其唯一联网入口）。
from src import event_stage  # 活动关卡页 OCR 解析（纯逻辑：编号/状态/序列）。
from src.tasks.NikkeBaseTask import NikkeBaseTask  # 项目基类，所有任务统一继承它。

# 大厅右侧「活动」入口图标特征（已标注进 coco）。
_EVENT_ICON = "event_icon"
# 活动主页菜单栏 OCR 区域（已标注进 coco）：大小活动的入口文字带位置不同，各自一个区域。
# _probe_entry 逐区 OCR，任一区域命中即视为该入口存在。
_MENU_BAND_BOXES = (
    "box_event_menu_band",  # 大活动主页底部菜单栏（STORY I/II/挑战/小游戏/签到印章/商店）。
    "box_event_menu_band_small",  # 小活动主页四周文字按钮区（挑战/任务/商店/记录保管所 + ENTER）。
)

_MAX_CARDS = 8  # 列表最多遍历的滚动位置数（卡片数不定，用带上限的循环防死循环）。

# 列表滚动手势与到底判据常量（实机按滚动步长精确性微调）。
_SCROLL_SWIPE_DURATION = 0.5  # 滚动手势时长（秒）。
_SCROLL_AFTER_SLEEP = 1.5  # 滚动后动画停稳等待（秒）。
_SCROLL_TOP_MAX_SWIPES = 5  # 归一化到顶部的最多下滑次数（防死循环）。
_SCROLL_UNCHANGED_RATIO = 0.02  # 列表区滚动前后像素差异比例阈值：低于视为画面无变化（到底/到顶）。
_SWIPE_START_RATIO = 0.8  # 滚动手势起点（占滚动区高度比例）：活动列表页默认自上而下 0.8 → 0.2。
_SWIPE_END_RATIO = 0.2  # 滚动手势终点（占滚动区高度比例）。
_STAGE_SWIPE_START_RATIO = 2 / 3  # 关卡列表滚动手势起点：从区域内垂直 2/3 处开始。
_STAGE_SCAN_MAX_SCROLLS = 6  # 关卡列表跨屏扫描的最多下滚次数（防死循环）。

_STORY_MODES = ("NORMAL", "HARD")  # 剧情关卡难度选项（沿用游戏内英文标签）；难度选择未实现，配置项暂隐藏入口。

# 活动关卡页（剧情子流程）区域特征与行切片参数（解析规则见 src/event_stage.py 与 dev_tools/handoff.md §4）。
_STAGE_LIST_BOX = "box_event_stage_list"  # 关卡列表区（OCR 裁剪范围 + 行锚点切片范围）。
_STAGE_MODE_BOX = "box_event_stage_mode"  # 关卡页难度区（NORMAL / HARD）。
_SLICE_GAP_RATIO = 1.5  # 相邻锚点间距超过行距的该倍数 = 中间漏了一行，按中点外推补一条。
_DEDUP_RATIO = 40 / 1440  # 多层 OCR 同一元素的纵向去重容差（占屏高比例）。
_UNIFORM_MAX_BANDS = 8  # 无行锚点时的兜底切片条数上限（列表区高度 ÷ 标定行距的估计上限，防病态参数刷 OCR）。

# 剧情执行链（点行 → 剧情跳过 → 连续战斗 → 回关卡页）参数（实机按加载/结算动画时长校准）。
_STORY_BATTLE_TIMEOUT = 240  # 单场战斗结束等待上限（秒），与其它任务的战斗等待一致。
_STORY_MAX_BATTLES = 20  # 连续「下一关」链的安全上限（防结算按钮识别抖动导致死循环）。
_STORY_DIALOG_WAIT = 8  # 点关卡/下一关/结算返回后等剧情对话界面或战斗界面出现的窗口（秒）。
_STORY_SKIP_MAX = 3  # 单次剧情跳过的最多点击次数（剧情可能分段）。
_STAGE_ENTER_TIMEOUT = 8  # 点关卡行后等界面落点的窗口（推图：离开列表 / 进详情页；扫荡：详情页就位）；加载慢导致误判时调大。
_STAGE_DETAIL_BATTLE_BOX = "box_stage_detail_battle"  # 关卡详情页「战斗」区域（推图判态：彩色可用 = 该关可推）。
_BATTLE_AFTER_SLEEP = 10  # 点「下一关」/结算按钮后等待下一场加载（秒），同 ArkTask 爬塔链。

# 扫荡（关卡详情页「快速战斗」）参数（实机按弹窗动画与结算时长校准）。
_SWEEP_STAGES = ("1-11", "1-09", "1-07")  # 「扫荡关卡」下拉选项：大多数活动都存在的可重复通关关卡。
_SWEEP_STAGE_DEFAULT = _SWEEP_STAGES[0]  # 默认扫荡关卡。
_SWEEP_MAX_ROUNDS = 10  # 扫荡轮次上限（每轮尽量拉满；实机有一轮只消耗 1 次的情况，上限按每日门票留足余量，防死循环）。
_SWEEP_BATTLE_TIMEOUT = 30  # 快速战斗结算等待上限（秒）：快速战斗直接出结果，无需按普通战斗给足时长。
_SWEEP_QUICK_BOX = "box_stage_detail_quick_battle"  # 关卡详情页「快速战斗」区域（仅活动关卡有）。
_SWEEP_PAGE_FEATURE = "custom_quick_battle_page"  # 快速战斗次数选择弹窗的就位特征。
_SWEEP_MAX_FEATURE = "custom_quick_battle_max"  # 次数选择弹窗的「拉满」按钮特征（弹窗可能已默认最大值）。
_SWEEP_START_BOX = "box_custom_quick_battle_start"  # 次数选择弹窗的「开始」按钮区域（与个人突袭快速战斗共用）。
_SWEEP_CLOSE_FEATURE = "stage_detail_close"  # 关卡详情页右上关闭按钮特征（判详情页就位 / 收尾关闭共用）。

# 挑战（大小活动都有，同一套 UI）：进入后自下而上找第一个可用关卡标记，点开详情页走快速/普通战斗。
# 判据全用 coco 特征（关卡标记 + 列表区），可用性（非灰白）用 is_feature_enabled 判态。
_CHALLENGE_LIST_BOX = "box_event_challenge_stage_list"  # 挑战关卡列表区域（关卡标记的搜索/定位范围）。
_CHALLENGE_STAGE_FEATURE = "event_challenge_stage"  # 单个挑战关卡标记（可点击 + 判态；自下而上取第一个可用）。

# 大活动子页面到达等待（秒）：点击底部菜单入口后，SD 小人先走到地点、子界面才打开（签到/挑战共用同一物理量）。
# 小活动点击入口即切页，轮询首帧就命中，故本窗口只影响大活动「小人走过去」的耗时；一处校准两处受益。
_SD_ARRIVE_TIMEOUT = 12  # 点到子界面出现的等待上限（秒）：轮询命中即提前返回，仅小人未到达时才等满。

# 面板底部「全部领取」判据（签到印章面板与活动任务弹窗共用：文字同字、都落在面板底部同一带）。
# 面板美术逐期变，模板类判据必失效（同登录奖励的思路），故只用「相对区域 OCR 文字 + 外扩取底色判态」。
_CLAIM_ALL_TEXT = re.compile("全部领取", re.IGNORECASE)  # 「全部领取」按钮文字（跨皮肤唯一稳定判据，OCR 部分匹配）。
_CLAIM_ALL_SCAN_BOX = (1 / 3, 0.6, 2 / 3, 1.0)  # 按钮的 OCR 搜索区域（相对坐标 x1,y1,x2,y2；实机校准）。
_CLAIM_ALL_PAD = (0.2, 0.36)  # 文字框外扩比例（宽, 高）：外扩取到按钮底色才能判可领与否（同登录奖励，比例外扩适配各分辨率）。

# 活动任务弹窗（大小活动同一套 UI）：点入口弹出模态框，弹窗内「全部领取」可反复点到无可领。
# 弹窗美术逐期变（标题是当期活动名），无跨期稳定的模板特征，判据只用「coco 区域 + OCR 文案」。
_MISSION_SUBTITLE_BOX = "box_event_mission_subtitle"  # 弹窗副标题区域（coco 区域，位置逐期固定）。
_MISSION_SUBTITLE_TEXT = re.compile("CHALLENGE", re.IGNORECASE)  # 副标题关键词（弹窗就位唯一跨期稳定判据）。
_MISSION_READY_TIMEOUT = 10  # 点入口后等弹窗就位（副标题出现）的窗口（秒）。
_MISSION_CLAIM_MAX_CLICKS = 20  # 单次领取循环的点击上限（点击未生效时防死循环）。

# 活动主页功能入口探测表：label -> 关键词正则列表（列表顺序即探测顺序）。
# OCR 在 _MENU_BAND_BOXES 各区域内逐区匹配；预留 feature 位：实机若发现某入口只有图标无文字，
# 再改成 {label: (feature, [keywords])} 形式补 coco 特征匹配（handoff §1）。
_ENTRIES = {
    "签到": [re.compile(r"签到印章", re.IGNORECASE)],
    "剧情": [
        re.compile(r"STORY\s*II", re.IGNORECASE),
        re.compile(r"STORY\s*I(?!I)", re.IGNORECASE),  # 与 STORY II 消歧：STORY I 是 II 的前缀。
        re.compile(r"加成", re.IGNORECASE),  # 小活动剧情入口（界面文案为「加成奖励妮姬」，只取前两字避免整词识别不到）。
    ],
    "挑战": [re.compile(r"挑战", re.IGNORECASE)],
    "任务": [re.compile(r"任务", re.IGNORECASE)],  # 小活动在菜单带；大活动在专属区域（见 _ENTRY_EXTRA_BOXES）。
    "商店": [re.compile(r"商店", re.IGNORECASE)],
    "小游戏": [re.compile(r"小游戏", re.IGNORECASE)],
}

# 入口专属区域（在默认菜单带之前追加探测，不替换）：大活动「任务」入口不在菜单带内，另有专属区域。
_ENTRY_EXTRA_BOXES = {
    "任务": ("box_event_menu_mission",),  # 大活动主页右侧的任务入口区域。
}

# v1 已实现的子流程（执行顺序即探测顺序）；小游戏不在其列，探测到仅记录跳过。
_SUBFLOW_ORDER = ("签到", "剧情", "挑战", "任务", "商店")

# 子流程名 -> 入口方法名（开关/探测/try_step 分派，沿用 ArkTask 的 _do_* 结构）。
_SUBFLOW_METHODS = {
    "签到": "_do_checkin",
    "剧情": "_do_story",
    "挑战": "_do_challenge",
    "任务": "_do_mission",
    "商店": "_do_shop",
}

# v1 跳过的入口：探测到只记日志（小游戏留 MINIGAMES 注册表钩子）。
_SKIPPED_ENTRIES = ("小游戏",)

# 入口点击框修正：关键词（pattern.pattern）-> 沿 Y 轴的上移量（占屏高比例）。
# 小活动剧情入口「加成奖励妮姬」的命中文字在按钮下缘，点击落点需上移到按钮主体（实机标定）。
_ENTRY_CLICK_Y_OFFSET = {
    "加成": 0.06,
}

# 小游戏注册表钩子（v1 预留，未实现）：实机接入各小游戏独立流程时填充。
MINIGAMES = {}


class EventTask(NikkeBaseTask):  # 活动任务：自动处理限时活动的通用内容（签到/剧情/挑战/任务/商店）。

    done_keys = {"event": "day"}  # 完成状态：活动聚合一个「日」周期键（不做大小活动/子流程分键，避免串台）。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "活动"  # 任务显示名称。
        self.description = "自动处理限时活动，活动首次开放时需手动进入并配队（剧情(BETA)/扫荡/挑战/任务/商店/签到印章）。"  # 任务说明。
        self._current_event = None  # 当前处理的活动（日历条目）；失败恢复回大厅后重入时用它 banner 定位。
        self.default_config.update({  # 子流程专属设置，独立持久化到 configs/。
            "签到": True,  # 是否收取活动签到印章奖励（仅大活动）。
            "剧情": True,  # 是否推进活动剧情。
            "扫荡": False,  # 是否对可重复关卡执行快速战斗扫荡（默认关闭，避免误耗资源）。
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

    def run(self):  # 任务执行入口：完成状态短路 → 接管（已在活动内）/大厅闸门+列表遍历 → 统一返回大厅收尾。
        self.log_info("活动任务开始")  # 记录任务开始。
        if self.is_done("event", "day"):  # 本周期内已完成则直接跳过（放最前，避免无谓地动游戏窗口）。
            self.log_info("今日活动已完成，跳过")  # 记录跳过原因。
            return  # 结束任务。
        if self._probe_event_context():  # 用户已手动进入活动（主页或关卡页/详情页）：就地接管，省去「回大厅再重进」。
            self.log_info("已在活动内，就地接管处理")  # 记录接管分支。
            if not self.try_step(self._takeover_event, name="活动接管", raise_on_fail=False):  # 接管流程用恢复协议包裹。
                self.log_warning("活动接管处理多次失败，本周期不标记完成")  # 记录失败原因。
                return  # 不标记完成，下次可重试。
        else:  # 正常路径：先就位大厅，再遍历活动列表。
            if not self.ensure_screen("lobby", raise_on_fail=False):  # 就位游戏大厅（幂等闸门：含冷启动引导与弹窗清理），失败则中止。
                self.log_error("未能进入游戏大厅，中止活动任务")  # 记录中止原因。
                return  # 结束任务。
            if not self.try_step(self._process_event_list, name="活动列表处理", raise_on_fail=False):  # 列表处理整体流程以大厅为起点，用恢复协议包裹。
                self.log_warning("活动列表处理多次失败，本周期不标记完成")  # 记录失败原因。
                return  # 不标记完成，下次可重试。
        self.mark_done("event", "day")  # 记录本周期已完成（全部卡片处理成功才落盘，失败在上一分支已返回）。
        self._exit_to_lobby()  # 统一返回大厅收尾（基类幂等实现）。
        self.log_info("活动任务完成")  # 记录任务完成。

    def _probe_event_main(self):  # 探测当前是否处于活动主页。
        return self.is_screen("event_main")  # 单帧判定（进入后的动画容忍由 _enter_and_probe 的轮询负责）。

    def _probe_event_context(self):  # 探测当前是否已在活动内（活动主页 / 关卡页 / 挑战页 / 关卡详情页）。
        return (self._probe_event_main() or self.is_screen("event_stage_page")  # 主页 / 剧情关卡页。
                or self.is_screen("event_challenge_page") or self._detail_page_open())  # 挑战页 / 详情页（任一命中即视为在活动内）。

    def _ensure_event_menu(self):  # 把活动子页面退回活动菜单页（已在菜单页则不动），供接管分支与重入使用。
        if self._probe_event_main():  # 已在活动菜单页（主页）。
            return  # 无需导航。
        if self._detail_page_open():  # 关卡详情页。
            self._close_stage_detail()  # 先关到关卡列表页。
        # 返回键样式逐期/逐子页不同（签到等活动子页的 common_back 模板实测仅 0.41，模板匹配会失败），
        # 故走基类 _find_back_button（模板精确 → 左下角区域兜底 → OCR「返回」三层）。
        self.transition("event_main", click=self._click_back_to_menu, wait_confirm=10, after_sleep=1)  # 子页面 → 活动菜单页。

    def _click_back_to_menu(self):  # 点击活动子页面的返回按钮回菜单页（基类三层兜底定位，功能同 click_box(common_back)）。
        back = self._find_back_button()  # 模板精确 → 左下角区域模板 → OCR「返回」。
        if back is None:  # 三层都未命中（页面非活动子页或按钮被遮挡）。
            raise WaitFailedException("未找到活动子页面返回按钮")  # 抛异常由 try_step/transition 处理。
        self.click_box(back, after_sleep=1)  # 点击返回键。

    def _takeover_event(self):  # 接管流程：已在活动内时先回到菜单页，再逐入口探测执行已开启子流程。
        self._ensure_event_menu()  # 子页面先退回菜单页（菜单带不在子页面上）。
        self._run_event_subflows()  # 在菜单页内按 _ENTRIES 探测各功能入口并执行。

    # ---- 列表处理 ----

    def _process_event_list(self):  # 活动列表处理主循环：大厅→列表页→逐位置滚动→banner 定位剧情活动并进入处理，最后返回大厅。
        events = self._pending_events()  # 待处理剧情活动（日历快照取最新 2 个）。
        if not events:  # 无活动图/日历数据时无法定位，直接结束。
            self.log_info("无待处理剧情活动（日历无数据），结束列表处理")  # 记录结束原因。
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
                self._current_event = event  # 记录当前活动，供子流程失败恢复回大厅后重入时 banner 定位。
                self._enter_and_probe(row)  # 点击进入并确认是活动，命中则执行子流程。
                self._current_event = None  # 处理结束清除上下文，避免下次重入定位到错误活动。
                processed.add(event.key)  # 记录已处理。
                unmatched.discard(event.key)  # 已定位到卡片，不再算未匹配。
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
            self.log_warning(f"活动 {key} 在列表页未匹配到卡片（未上架/已下架，或保底包已过期）")  # 记录便于排查。
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

    def _list_area_box(self, box_name=event_calendar.SEARCH_BOX):  # 滚动/扫描区（默认活动列表的 box_event_banner_area），缺失返回 None。
        return self._optional_box(box_name)  # 区域缺失视为不可滚动。

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

    def _swipe_list_up(self, box, start_ratio=_SWIPE_START_RATIO, end_ratio=_SWIPE_END_RATIO):  # 在列表区上滑（内容上移，露出下方行）。
        x = box.x + box.width // 2  # 列表区水平中点。
        self.swipe(x, box.y + box.height * start_ratio, x, box.y + box.height * end_ratio,
                   duration=_SCROLL_SWIPE_DURATION, after_sleep=_SCROLL_AFTER_SLEEP)  # 自下往上滑。

    def _swipe_list_down(self, box, start_ratio=_SWIPE_START_RATIO, end_ratio=_SWIPE_END_RATIO):  # 在列表区下滑（内容下移，回到顶部）。
        x = box.x + box.width // 2  # 列表区水平中点。
        self.swipe(x, box.y + box.height * end_ratio, x, box.y + box.height * start_ratio,
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

    def _scroll_list_to_top(self, box_name=event_calendar.SEARCH_BOX, start_ratio=_SWIPE_START_RATIO):  # 把列表滚动到顶部：连续下滑，画面不再变化即视为到顶。
        box = self._list_area_box(box_name)  # 列表滚动区。
        if box is None:  # 区域缺失。
            return  # 无法滚动。
        self._scroll_area(self._swipe_list_down, box, start_ratio, _SCROLL_TOP_MAX_SWIPES)  # 下滑到画面不再变化或次数上限。

    def _scroll_list_down(self, steps, box_name=event_calendar.SEARCH_BOX, start_ratio=_SWIPE_START_RATIO):  # 向下滚动 steps 步，返回是否发生实际滚动（到底返回 False）。
        if steps <= 0:  # 无下滚需求。
            return True  # 视为位置有效。
        box = self._list_area_box(box_name)  # 列表滚动区。
        if box is None:  # 区域缺失。
            return False  # 不可滚动视为到底。
        return self._scroll_area(self._swipe_list_up, box, start_ratio, steps) >= steps  # 少滚一步即视为到底。

    def _pending_events(self):  # 待处理剧情活动快照：本地读快照，过期才刷新（唯一联网入口，不抛异常）。
        snapshot = event_calendar.load_snapshot()  # 应用启动已在后台静默刷新，纯本地读。
        if snapshot is None:  # 无快照（首次运行/缓存缺失）。
            snapshot = event_calendar.refresh()  # 刷新（内部含保底包兜底，不抛异常）。
        elif not snapshot.is_fresh(600):  # 快照超过 600s TTL。
            snapshot = event_calendar.refresh()  # 刷新日历与活动图。
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

    def _enter_and_probe(self, row_box):  # 进入活动并执行子流程（列表处理路径）；非活动条目退回大厅。
        if self._enter_event(row_box):  # 确认为活动主页（含菜单就绪等待）。
            self._run_event_subflows()  # 进入后按 _ENTRIES 探测各功能入口并执行。
        else:  # 抽卡/登录奖励等非活动条目。
            self._recover_to_lobby()  # 退回大厅（活动页返回键直接回大厅，此处用恢复协议兜底）。

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

    def _entry_regions(self, label):  # 该入口的可探测区域：专属追加区（若有）在前，再回落大小活动菜单带。
        boxes = []  # 已解析区域列表。
        for extra in _ENTRY_EXTRA_BOXES.get(label, ()):  # 该入口的专属区域（如大活动「任务」不在菜单带内）。
            box = self._optional_box(extra)  # 区域框（特征缺失返回 None）。
            if box is not None:  # 区域有效。
                boxes.append(box)  # 收集。
        return boxes + self._menu_boxes()  # 专属区优先，菜单带兜底（小活动入口仍在菜单带内）。

    def _entry_box(self, label):  # 按 _ENTRIES 关键词顺序定位入口点击框；未命中返回 None。
        patterns = _ENTRIES.get(label) or []  # 该入口的关键词正则列表（列表顺序即优先级）。
        if not patterns:  # 未知入口。
            return None  # 无法定位。
        for menu_box in self._entry_regions(label):  # 逐区（专属区 + 大小活动菜单带各一区）。
            boxes = self.ocr(box=menu_box)  # 该区域一次 OCR（不按关键词过滤，供多关键词复用）。
            for pattern in patterns:  # 按优先级逐个关键词过滤（STORY II 先于 STORY I）。
                matched = find_boxes_by_name(boxes, self.fix_match_regex([pattern]))  # 与 ocr(match=...) 相同的部分匹配语义。
                if matched:  # 命中该关键词。
                    return self._entry_click_box(matched[0], pattern)  # 命中文本框按关键词补偏移后作为点击框。
        return None  # 全部关键词未命中。

    def _entry_click_box(self, hit, pattern):  # 入口命中框 -> 点击框：按关键词沿 Y 轴上移（命中文字可能落在按钮边缘）。
        offset = _ENTRY_CLICK_Y_OFFSET.get(pattern.pattern, 0)  # 该关键词的上移量（占屏高比例），缺省不修正。
        if offset <= 0:  # 无需修正。
            return hit  # 命中框本身即点击框。
        return Box(hit.x, hit.y - int(self.height * offset), hit.width, hit.height,  # 同尺寸上移，不改写原命中框。
                   confidence=hit.confidence, name=hit.name)

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
        for menu_box in boxes:  # 逐区探测（专属区 + 大小活动菜单带范围不同）。
            if self.ocr(box=menu_box, match=list(patterns)):  # 区域内 OCR 部分匹配任一关键词（首区命中即短路）。
                return True  # 命中即返回，无需查其余区域。
        return False  # 未命中。

    def _do_checkin(self):  # 签到子流程：开关 → 探测 → try_step（仅大活动有签到印章入口）。
        if not self.config.get("签到"):  # 用户未启用签到子流程。
            self.log_info("签到未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self._probe_entry("签到"):  # 探测不到 = 当期小活动无此功能入口。
            self.log_info("未探测到签到入口（小活动无此功能），跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self.try_step(self._flow_checkin, name="签到", raise_on_fail=False):  # 签到整体流程用恢复协议包裹（自足重入）。
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
        if not self.try_step(self._flow_challenge, name="挑战", raise_on_fail=False):  # 挑战整体流程用恢复协议包裹。
            self.log_warning("挑战子流程多次失败，跳过")  # 记录失败原因。

    def _do_mission(self):  # 任务子流程：开关 → 探测（大活动专属区 / 小活动菜单带）→ try_step。
        if not self.config.get("任务"):  # 用户未启用任务子流程。
            self.log_info("任务未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self._probe_entry("任务"):  # 探测不到 = 当期活动无任务入口（大活动入口在 box_event_menu_mission 区）。
            self.log_info("未探测到任务入口，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self.try_step(self._flow_mission, name="任务", raise_on_fail=False):  # 任务整体流程用恢复协议包裹。
            self.log_warning("任务子流程多次失败，跳过")  # 记录失败原因。

    def _do_shop(self):  # 商店子流程：开关（默认关闭）→ 探测 → try_step（非幂等流程，留 v1.5）。
        if not self.config.get("商店"):  # 用户未启用商店子流程（v1 默认关闭）。
            self.log_info("商店未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self._probe_entry("商店"):  # 探测不到商店入口。
            self.log_info("未探测到商店入口，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self.try_step(self._flow_shop, name="商店", raise_on_fail=False):  # 商店整体流程用恢复协议包裹。
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
        # 会被 _close_daily_login_popup 误认成登录奖励面板重复点击（其消歧只认 mission_page）。
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
                                     self._CLICK_TO_PROCEED_PATTERN), time_out=time_out)  # 复用登录奖励同一套遮罩提示词。

    # ---- 剧情关卡页 OCR 与解析（方案 §5：全屏/裁剪 → 行锚点切片三级降级） ----

    def _stage_list_box(self):  # 关卡列表区 Box（coco 区域特征，按分辨率缩放）；未标注返回 None。
        box = self._optional_box(_STAGE_LIST_BOX)  # 区域框。
        if box is None:  # 特征缺失。
            self.log_warning(f"缺少区域特征: {_STAGE_LIST_BOX}")  # 记录缺失，便于排查。
        return box  # 无法定位列表区时为 None。

    def _ocr_blocks(self, box):  # 一次区域 OCR -> 解析层 Block 列表（整图坐标）。
        return [event_stage.Block(text=item.name, score=item.confidence, x1=item.x, y1=item.y,
                                  x2=item.x + item.width, y2=item.y + item.height)
                for item in self.ocr(box=box) if item.name]  # 空文本块丢弃。

    def _block_kind(self, block):  # 块类别（去重只在同类别之间进行）。
        if event_stage.stage_id_candidates(block.text):  # 编号块。
            return "number"
        if event_stage.match_status(block.text):  # 状态文案块。
            return "status"
        return "other"  # 锚点等其它块。

    def _dedup_blocks(self, blocks):  # 多层 OCR 的重复块：同类别且纵向邻近时只保留置信度最高的一块。
        tolerance = max(1.0, self.height * _DEDUP_RATIO)  # 去重容差（按屏高缩放）。
        kept = []  # 已保留的（块, 类别）。
        for block in sorted(blocks, key=lambda item: item.score, reverse=True):  # 高分优先保留。
            kind = self._block_kind(block)  # 当前块类别。
            if all(kind != other_kind or abs(block.center_y - other.center_y) > tolerance
                   for other, other_kind in kept):  # 与同类已保留块不重叠即保留。
                kept.append((block, kind))
        return [block for block, _ in kept]  # 返回去重后的块（顺序不敏感，解析层会排序）。

    def _stage_scale(self):  # 当前分辨率相对 2560x1440 标定截图的缩放比（0 = 无有效分辨率，兜底按标定值）。
        return event_calendar.screen_scale(self.width, self.height)

    def _stage_row_pitch(self, anchors):  # 行距：锚点 y 中心间距的中位数（先剔除漏行造成的双倍间距）。
        centers = sorted(block.center_y for block in anchors)  # 锚点按 y 排序。
        gaps = [b - a for a, b in zip(centers, centers[1:]) if b - a > 1]  # 相邻间距。
        if not gaps:  # 单锚点/无锚点。
            fallback = event_stage.row_pitch_fallback(self._stage_scale())  # 兜底行距（按分辨率缩放）。
            self.log_debug(f"行距兜底：锚点 {len(anchors)} 个测不出间距，用 {fallback:.0f}px")  # 行距来源便于实机校准。
            return fallback
        regular = [gap for gap in gaps if gap <= min(gaps) * _SLICE_GAP_RATIO]  # 剔除漏行位置的双倍间距。
        regular.sort()
        pitch = regular[len(regular) // 2]  # 正常行距的中位数。
        self.log_debug(f"行距估计：锚点间距 {[round(gap) for gap in gaps]} -> {pitch:.0f}px")  # 行距来源便于实机校准。
        return pitch

    def _band_box(self, list_box, center_y, pitch):  # 列表区内以 center_y 为中心的行窄带 Box。
        return Box(list_box.x, int(center_y - pitch / 2), list_box.width, int(pitch))

    def _anchor_bands(self, anchors, list_box):  # 锚点 -> 逐行切片窄带；相邻锚点间隔过大时按中点外推补一行。
        pitch = self._stage_row_pitch(anchors)  # 行距。
        centers = sorted(block.center_y for block in anchors)  # 锚点中心 y。
        bands = []  # 窄带列表。
        for index, center in enumerate(centers):  # 每个锚点一条窄带。
            bands.append(self._band_box(list_box, center, pitch))
            if index + 1 < len(centers):  # 与下一个锚点比较间隔。
                gap = centers[index + 1] - center
                if gap > pitch * _SLICE_GAP_RATIO:  # 间隔约两倍行距 = 中间那行漏检。
                    bands.append(self._band_box(list_box, (center + centers[index + 1]) / 2, pitch))
        self.log_debug(f"锚点切片：{len(centers)} 个锚点、行距 {pitch:.0f}px -> {len(bands)} 条窄带")  # 切片概览。
        return bands  # 可能是外推补齐的行数。

    def _uniform_bands(self, list_box):  # 无行锚点的兜底切片：按标定行距（含分辨率缩放）在列表区自上而下切等距窄带。
        pitch = event_stage.row_pitch_fallback(self._stage_scale())  # 兜底行距（2560x1440 标定值按当前缩放比缩放）。
        bands = []  # 窄带列表。
        center = list_box.y + pitch / 2  # 首条带中心：列表区顶往下半个行距（行首文字通常不在区域最顶端）。
        while center < list_box.y + list_box.height and len(bands) < _UNIFORM_MAX_BANDS:  # 逐行下移直到区域底部或条数上限。
            bands.append(self._band_box(list_box, center, pitch))  # 整列表宽 × 一个行距的行窄带。
            center += pitch  # 下移一行。
        self.log_debug(f"均匀切片：行距 {pitch:.0f}px -> {len(bands)} 条窄带（列表区高 {list_box.height}px）")  # 切片概览便于校准。
        return bands  # 条数 = 列表区高度 ÷ 行距（封顶 _UNIFORM_MAX_BANDS）。

    def _stage_blocks(self, list_box):  # 列表区 OCR；编号读不全时降级切片补扫（有锚点按锚点切，无锚点按标定行距均匀切）并去重。
        blocks = self._ocr_blocks(list_box)  # 第一层：列表区裁剪 OCR。
        self.log_debug(f"列表区 OCR {len(blocks)} 块：{[block.text for block in blocks]}")  # 原始文本便于排查识别问题。
        anchors = [block for block in blocks if event_stage.is_anchor(block.text)
                   and not event_stage.stage_id_candidates(block.text)]  # 行锚点（含 eni/vent 残片）。
        numbers = event_stage.count_numbers(blocks)  # 编号块数。
        if numbers and numbers >= len(anchors):  # 读到编号且不比锚点少 = 无需降级（普通页多为「有编号、无锚点」）。
            return blocks
        if anchors:  # 有锚点：按锚点 y 逐行切片（低对比页里锚点是唯一可靠的行定位信号）。
            bands = self._anchor_bands(anchors, list_box)  # 逐行窄带（间距过大时按中点外推补条）。
            self.log_info(f"编号块 {numbers} 个 < 锚点 {len(anchors)} 个，按行锚点切片补扫")  # 记录降级原因。
        else:  # 连行锚点都没有（行首文案换成了非 EVENT 家族，或整行是图形）：按标定行距均匀切片补扫。
            bands = self._uniform_bands(list_box)  # 均匀窄带。
            self.log_info(f"编号块 {numbers} 个且无行锚点，按标定行距均匀切片补扫 {len(bands)} 条")  # 记录降级原因。
        for band in bands:  # 逐行切片 OCR（第三层）。
            blocks.extend(self._ocr_blocks(band))
        merged = self._dedup_blocks(blocks)  # 合并两层结果并去重。
        self.log_debug(f"切片补扫去重：{len(blocks)} -> {len(merged)} 块：{[block.text for block in merged]}")  # 去重效果。
        return merged

    def _parse_rows(self, box, blocks):  # 解析成行条目，并按编号序列缺口补扫缺失行后重解析（只补一轮）。
        list_rect = (box.x, box.y, box.width, box.height)  # 解析层用的列表区矩形。
        rows = event_stage.parse(blocks, list_box=list_rect, scale=self._stage_scale())  # 首次解析（兜底行距按分辨率缩放）。
        gaps = event_stage.sequence_gaps(rows)  # 编号序列缺口（中间漏行的位置估计）。
        if not gaps:  # 编号连续。
            return rows  # 无需补扫。
        self.log_info(f"编号序列缺口 {len(gaps)} 处，补扫缺失行")  # 记录补扫原因。
        for center_y, height in gaps:  # 逐个缺口区补扫。
            blocks.extend(self._ocr_blocks(self._band_box(box, center_y, height)))  # 取整列表宽度的高带，覆盖两侧已知行之间（蛇形同带的行也能扫到）。
        repaired = event_stage.parse(self._dedup_blocks(blocks), list_box=list_rect,  # 合并去重后重解析。
                                     scale=self._stage_scale())
        self.log_debug(f"缺口补扫：{len(rows)} -> {len(repaired)} 行")  # 补扫效果便于核对。
        return repaired

    def _stage_rows(self, list_box=None):  # 关卡页列表区 -> 行条目列表（编号/状态/行框）；区域缺失返回空列表。
        box = list_box if list_box is not None else self._stage_list_box()  # 列表区。
        if box is None:  # 区域缺失。
            return []  # 无法解析。
        self.log_debug(f"关卡列表区 {box}，分辨率缩放比 {self._stage_scale():.3f}")  # 区域与分辨率参数便于核对。
        blocks = self._stage_blocks(box)  # 两级 OCR 块。
        rows = self._parse_rows(box, blocks)  # 解析 + 序列缺口修复。
        self.log_info(f"关卡页解析：{len(rows)} 行，状态 {[row.status for row in rows]}")  # 记录解析结果便于实机核对。
        self.log_debug(f"关卡页行明细：{[(row.stage_id, row.status, row.source, row.box) for row in rows]}")  # 编号/状态/来源/行框。
        return rows

    def _scan_stage_rows(self):  # 跨屏扫描关卡列表：逐屏解析并按编号去重拼接，返回按列表顺序排列的编号行。
        box = self._stage_list_box()  # 列表区（同时是滚动区）。
        if box is None:  # 区域缺失。
            return []  # 无法扫描。
        self._scroll_list_to_top(box_name=_STAGE_LIST_BOX, start_ratio=_STAGE_SWIPE_START_RATIO)  # 先归一到顶部再扫。
        collected = {}  # stage_id -> 行条目（跨屏去重，保留首次出现）。
        previous = None  # 上一屏的编号序列。
        for index in range(_STAGE_SCAN_MAX_SCROLLS):  # 逐屏扫描（带上限防死循环）。
            rows = self._stage_rows(box)  # 当前屏解析。
            signature = tuple(row.stage_id for row in rows if row.stage_id)  # 当前屏编号序列。
            for row in rows:  # 收集编号行（锁定行无编号，不参与拼接）。
                if row.stage_id and row.stage_id not in collected:
                    collected[row.stage_id] = row
            self.log_debug(f"扫描第 {index + 1} 屏：编号 {signature}，累计 {len(collected)} 关")  # 跨屏拼接过程。
            if signature == previous:  # 滚动后编号序列没变 = 已到底或列表不可滚。
                break
            previous = signature
            if not self._scroll_list_down(1, box_name=_STAGE_LIST_BOX, start_ratio=_STAGE_SWIPE_START_RATIO):  # 下滚一屏步。
                self.log_debug("列表已到底（滚动前后像素比对无变化）")  # 扫描结束原因。
                break  # 像素比对判到底。
        self.log_info(f"关卡列表扫描完成：{len(collected)} 关（{list(collected)}）")  # 记录跨屏拼接结果。
        return list(collected.values())  # 按发现顺序（即列表顺序）返回。

    # ---- 剧情执行链（方案 §8：推图链 + 扫荡链） ----

    def _row_box(self, row):  # 解析层行框（x1,y1,x2,y2 四元组）-> 可点击 Box（click_box 只接受 Box/特征名）。
        x1, y1, x2, y2 = row.box  # 行框为整图坐标四元组。
        return Box(x1, y1, x2 - x1, y2 - y1, name=f"event_stage_{row.stage_id or 'locked'}")  # 行窄条区域。

    def _skip_story_if_present(self, time_out=_STORY_DIALOG_WAIT):  # 剧情对话界面出现则点跳过；未播剧情直接返回。
        """点关卡/进下一关/结算返回后都可能先播剧情（首次进非可重复挑战的关卡必有）。

        剧情对话复用全局 [谈话] 界面判定（`conversation`：右上角图标区任一图标命中），
        跳过按钮与咨询/突发剧情同一个 `conversation_skip` 特征——实机若发现活动剧情
        图标区位置不同，再补该页专属特征与区域。
        """
        if not self.wait_until(lambda: self.is_screen("conversation") or self._in_battle_page(),  # 剧情界面出现，或已直接进入战斗（无剧情）。
                               time_out=time_out, settle_time=0):  # 两信号都在场即返回，无需稳定窗口。
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

    def _stage_flow_entered(self, time_out=_STAGE_ENTER_TIMEOUT):  # 点关卡行后是否进入关卡流程（离开列表或进详情页）。
        return self.wait_until(lambda: not self.is_screen("event_stage_page") or self._detail_page_open(),  # 仍在列表 = 点击没打开任何页面。
                               time_out=time_out, settle_time=0)  # 两信号都在场即返回。

    def _push_stages(self, target):  # 连续推图链：点目标关（详情页判「战斗」可用则点击）→ 逐场战斗（结算「下一关」可用则续战，跳到门票耗尽）→ 回关卡页。
        self.click_box(self._row_box(target), after_sleep=2)  # 点击目标关卡行进入关卡（可能先播剧情）。
        if not self._stage_flow_entered():  # 点开后仍停在关卡列表 = 该关已通关且不可重复挑战（只弹提示、不进详情页）。
            self.log_info(f"{target.stage_id} 点开后仍停在关卡列表（已通关不可重复挑战），推图结束")  # 记录结束原因。
            return  # 结束推图（仍在列表页，无需收尾动作）。
        if self._detail_page_open():  # 点开的是关卡详情页 = 未开战：按「战斗」按钮判态决定点击或收尾。
            battle_box = self._optional_box(_STAGE_DETAIL_BATTLE_BOX)  # 详情页「战斗」区域（缺失按不可点）。
            if battle_box is None:  # 区域特征解析不出来（coco 缺失/加载失败）。
                self.log_warning(f"缺少区域特征 {_STAGE_DETAIL_BATTLE_BOX}，推图结束")  # 记录跳过原因。
                self._close_stage_detail()  # 关详情页回关卡列表。
                return  # 结束推图。
            if not self.is_feature_enabled(battle_box):  # 灰白禁用：该关不可推（门票耗尽等）。
                self.log_info(f"{target.stage_id} 详情页「战斗」为灰白禁用态（门票耗尽等），推图结束")  # 记录结束原因。
                self._close_stage_detail()  # 关详情页回关卡列表。
                return  # 结束推图。
            self.log_info(f"{target.stage_id} 详情页「战斗」可用，点击进入战斗")  # 记录推进（可能先播剧情）。
            self.click_box(battle_box, after_sleep=2)  # 点「战斗」进入战斗链。
        for _ in range(_STORY_MAX_BATTLES):  # 连续战斗安全上限（正常由门票耗尽自然结束）。
            self._skip_story_if_present()  # 进关卡/进下一关可能先播剧情：识别并点跳过。
            result, confirm_box = self.wait_battle_finish(time_out=_STORY_BATTLE_TIMEOUT)  # 节流等待战斗结束，只检测不点击。
            if result is None:  # 等待战斗结束超时。
                raise WaitFailedException("等待活动关卡战斗结束超时")  # 抛异常由 try_step 恢复。
            if result == "failed":  # 战斗失败（门票已消耗，不再续战）。
                self.log_warning("活动关卡战斗失败")  # 记录失败供排查。
                self.click_box(confirm_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 点击失败返回按钮。
                self._skip_story_if_present()  # 返回时也可能先播剧情。
                break  # 结束推图。
            next_box = self._optional_box("box_battle_finish_next_stage")  # 结算界面右下角「下一关」区域（缺失按不可用）。
            if next_box is not None and self.is_feature_enabled(next_box):  # 彩色高亮 = 还有门票可续战。
                self.log_info("结算界面「下一关」可用，继续推进")  # 记录续战。
                self.click_box(next_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 点击下一关，回到循环头部等待下一场。
                continue  # 续战。
            self.click_box(confirm_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 「下一关」不可用 = 门票耗尽，点击结算返回按钮。
            self._skip_story_if_present()  # 返回时也可能先播剧情。
            break  # 推图结束。
        else:  # 循环用尽仍未自然结束 = 异常状态。
            self.log_warning(f"连续战斗达到上限 {_STORY_MAX_BATTLES} 场，停止推图")  # 提示异常，交界面断言兜底。
        self.assert_screen("event_stage_page", time_out=15)  # 确认已回到活动关卡界面（剧情跳过后的落点）。

    def _progress_target(self):  # 推图目标：先认当前屏（进关卡页游戏会自动定位到当前进度关），解析不出才回退跨屏扫描。
        box = self._stage_list_box()  # 列表区（区域缺失时由兜底路径返回空）。
        rows = self._stage_rows(box) if box is not None else []  # 当前屏解析（行框即当前屏坐标）。
        target = event_stage.progress_target(rows)  # 当前屏最下面的可打行 = 当前进度关。
        if target is not None:  # 当前屏有可打行。
            return target  # 直接使用。
        if rows:  # 当前屏解析出了行但没有可打的 = 已全通（进度关之后的行都是锁定行，没有编号）。
            return None  # 无需再扫全列表。
        self.log_info("当前屏未解析出关卡行，回退为跨屏扫描")  # 记录兜底原因（OCR 漏检/页面未就绪）。
        return event_stage.progress_target(self._scan_stage_rows())  # 兜底：扫全列表再取目标。

    def _locate_stage_row(self, stage_id):  # 查找指定关卡行并返回（行框对应当前屏幕，可直接点击）；未找到返回 None。
        box = self._stage_list_box()  # 列表区（同时是滚动区）。
        if box is None:  # 区域缺失。
            return None  # 无法定位。
        row = event_stage.find_stage(self._stage_rows(box), stage_id)  # 先在当前屏找：进页面时游戏常已停在最近位置，能命中就不动列表。
        if row is not None:  # 当前屏命中。
            self.log_debug(f"当前屏定位到关卡 {stage_id}（行框 {row.box}）")  # 定位过程便于校准。
            return row  # 直接返回。
        self._scroll_list_to_top(box_name=_STAGE_LIST_BOX, start_ratio=_STAGE_SWIPE_START_RATIO)  # 当前屏没有才归一化到顶部，再向下逐屏找。
        for index in range(_STAGE_SCAN_MAX_SCROLLS):  # 逐屏查找（带上限防死循环）。
            row = event_stage.find_stage(self._stage_rows(box), stage_id)  # 在当前屏解析结果里按编号定位。
            if row is not None:  # 命中（行框即当前屏坐标）。
                self.log_debug(f"第 {index + 1} 屏定位到关卡 {stage_id}（行框 {row.box}）")  # 定位过程便于校准。
                return row  # 返回可点击的行条目。
            if not self._scroll_list_down(1, box_name=_STAGE_LIST_BOX, start_ratio=_STAGE_SWIPE_START_RATIO):  # 下滚一屏步。
                break  # 到底仍未命中。
        self.log_debug(f"逐屏查找未定位到关卡 {stage_id}")  # 记录未命中。
        return None  # 未找到。

    def _close_stage_detail(self, to_screen="event_stage_page"):  # 关闭关卡详情页回退到指定列表页（剧情/扫荡回关卡页，挑战回挑战页）。
        self.wait_click_feature(_SWEEP_CLOSE_FEATURE, raise_if_not_found=True, after_sleep=1)  # 点详情页右上关闭按钮。
        self.assert_screen(to_screen, time_out=15)  # 确认回到目标列表界面（默认活动关卡列表）。

    def _sweep_stage(self, stage_id):  # 扫荡：点配置关卡行 → 详情页「快速战斗」（次数拉满）→ 结算回列表，循环到不可用（耗尽）。
        for round_index in range(1, _SWEEP_MAX_ROUNDS + 1):  # 带上限防死循环（次数拉满后正常一轮即耗尽）。
            row = self._locate_stage_row(stage_id)  # 逐屏定位配置关卡（行框对应当前屏幕）。
            if row is None:  # 当期列表没有该关卡 = 该关尚未通关/未开放（不是识别失败），不做任何降级替代。
                self.log_warning(f"列表中没有可扫荡关卡 {stage_id}（尚未通关/未开放），跳过扫荡")  # 记录跳过原因。
                return  # 结束扫荡。
            # 行状态只记日志、不作门槛：已通关标记（√ / CLEAR / REPEAT）可能漏检，
            # 能否扫荡一律以关卡详情页的「快速战斗」判态为准（门票用光时详情页仍可打开）。
            self.log_debug(f"关卡 {stage_id} 列表行状态 {row.status}（仅供参考，不作门槛）")  # 行状态便于校准。
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

    def _wait_challenge_nodes(self, time_out=_SD_ARRIVE_TIMEOUT):  # 挑战页过场动画：等关卡节点渲染出来（标题先于节点出现）。
        list_box = self._optional_box(_CHALLENGE_LIST_BOX)  # 挑战关卡列表区域（搜索范围）。
        if list_box is None:  # 区域未标注。
            return  # 交 _find_available_challenge_stage 记日志兜底。
        try:  # 关卡标记特征可能尚未标注进 coco。
            ready = self.wait_until(lambda: bool(self.find_feature(_CHALLENGE_STAGE_FEATURE, box=list_box, limit=0,
                                                                    use_gray_scale=True)),
                                    time_out=time_out, settle_time=0)  # 轮询等节点渲染（灰度匹配）。
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
        entry = self._entry_box("剧情")  # 剧情入口命中框（大活动 STORY II → STORY I，小活动「加成」）。
        if entry is None:  # 入口缺失（页面结构变化或菜单未渲染）。
            raise WaitFailedException("未找到剧情入口")  # 抛异常由 try_step 恢复。
        self.transition("event_stage_page", box=entry, wait_confirm=10, after_sleep=1)  # 点击剧情入口并确认进入关卡页。
        if self.config.get("剧情"):  # 推图开关（与扫荡独立，任一开启都进关卡页）。
            target = self._progress_target()  # 目标 = 最下面的可打行（进页面即自动定位到当前进度关，先认当前屏）。
            if target is None:  # 无可打关卡：当前进度之后都是锁定行 = 已全通（或本期还没开放新关）。
                self.log_info("无可打的剧情关卡（已全通或尚未开放），推图结束")  # 记录结束原因。
            else:  # 有可打关卡。
                self._push_stages(target)  # 点行进入连续战斗链，结束落回关卡页。
        if self.config.get("扫荡"):  # 扫荡开关：对配置的可重复关卡快速战斗。
            self._sweep_stage(self.config.get("扫荡关卡", _SWEEP_STAGE_DEFAULT))  # 点行 → 详情页快速战斗（次数拉满）→ 扫到不可用。
        self.transition("event_main", click=self._click_back_to_menu, wait_confirm=10, after_sleep=1)  # 点返回回活动菜单页，供后续子流程接续。

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
        self.transition("event_challenge_page", box=entry, wait_confirm=_SD_ARRIVE_TIMEOUT,
                        time_out=_SD_ARRIVE_TIMEOUT * 2, after_sleep=2)  # 点击入口并确认进入挑战页。
        self._wait_challenge_nodes()  # 等节点渲染完成再选关（吸收过场动画）。
        stage = self._find_available_challenge_stage()  # 自下而上找第一个可用（非灰白）关卡标记。
        if stage is None:  # 无可用关卡（今日次数已用完/列表未标注）：无需进详情页，直接返回菜单页。
            self._ensure_event_menu()  # 点返回键回活动菜单页。
            return  # 结束挑战流程。
        self.click_box(stage, after_sleep=2)  # 点关卡标记进入关卡详情页。
        if not self.wait_feature(_SWEEP_CLOSE_FEATURE, time_out=_STAGE_ENTER_TIMEOUT, raise_if_not_found=False):  # 等详情页就位（右上关闭按钮特征）。
            self.log_warning("点开挑战关卡后未进入详情页，结束挑战")  # 记录异常落点（正常应进详情页）。
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

    def _flow_mission(self):  # 任务流程（自足重入）：点任务入口弹模态框 → 循环领取 → 点空白关闭回菜单页。
        # 大小活动同一套弹窗 UI；弹窗美术逐期变（标题是当期活动名），无跨期稳定模板特征，
        # 判据只用「coco 区域 + OCR 文案」：就位认副标题关键词，可领认「全部领取」外扩底色（同签到印章那套）。
        self._nav_to_event_main()  # 就位活动主页（正常已就位；恢复回大厅后由此重入）。
        entry = self._entry_box("任务")  # 任务入口（大活动在专属区域 box_event_menu_mission，小活动在菜单带）。
        if entry is None:  # 入口缺失（菜单未渲染或页面结构变化）。
            raise WaitFailedException("未找到任务入口")  # 抛异常由 try_step 恢复。
        self.click_box(entry, after_sleep=2)  # 点击入口弹出任务弹窗（模态框，不注册为界面）。
        if not self.wait_until(lambda: self._find_mission_subtitle() is not None,  # 轮询等弹窗就位（副标题出现）。
                               time_out=_MISSION_READY_TIMEOUT, settle_time=1.5):  # 命中后再稳定 1.5s，吸收弹窗开启动画。
            self.log_warning("任务弹窗未在预期时间内出现，跳过领取")  # 记录跳过原因（弹窗未开则无需关闭）。
            return  # 结束任务流程（仍在活动菜单页）。
        self._claim_mission_rewards()  # 循环领取，直到「全部领取」变灰白（无可领奖励）。
        # 领取按钮灰白后点面板外空白关闭弹窗：确认回到活动菜单页即完成（模态框点空白等价点遮罩，对皮肤免疫）。
        if self.close_popup_by_blank(lambda: self.is_screen("event_main"), time_out=5):  # 关不掉时补点（默认次数）。
            self.log_info("任务奖励领取完成，已回到活动菜单页")  # 记录完成。
        else:  # 补点耗尽仍未确认关闭。
            self.log_warning("点击空白未能关闭任务弹窗")  # 记录失败（弹窗遮挡会让后续子流程探测跳过）。

    def _find_mission_subtitle(self):  # 在弹窗副标题区域内 OCR 识别关键词，返回匹配框或 None（弹窗就位判据）。
        box = self._optional_box(_MISSION_SUBTITLE_BOX)  # 副标题区域（coco 区域特征；缺失时无法判定）。
        if box is None:  # 区域未标注（coco 版本不符）。
            self.log_warning(f"缺少区域特征: {_MISSION_SUBTITLE_BOX}")  # 记录缺失，便于排查。
            return None  # 视为弹窗未就位。
        boxes = self.ocr(box=box, match=[_MISSION_SUBTITLE_TEXT])  # 区域内 OCR 部分匹配副标题关键词。
        return boxes[0] if boxes else None  # 命中即弹窗已就位。

    def _claim_mission_rewards(self):  # 循环点「全部领取」直到按钮灰白；每轮点完清掉领奖遮罩再判下一轮。
        for _ in range(_MISSION_CLAIM_MAX_CLICKS):  # 次数上限保护：点击未生效时不再无限循环。
            claim = self._find_claim_all()  # 弹窗底部「全部领取」文字（与签到印章同一判据文字与搜索区域）。
            if claim is None:  # 文字消失（弹窗已被关掉或页面结构变化）。
                self.log_warning("未识别到任务弹窗「全部领取」，停止领取")  # 记录异常供排查。
                return  # 结束领取。
            if not self.is_feature_enabled(self._claim_button_box(claim)):  # 外扩取到按钮底色判态：灰白 = 已无可领奖励。
                self.log_info("任务奖励已无可领取（「全部领取」为灰白态）")  # 记录结束状态。
                return  # 结束领取。
            self.click_box(claim, after_sleep=1)  # 点击全部领取（一次性领取当前全部可领档位）。
            self.log_info("已点击任务弹窗「全部领取」")  # 记录动作。
            self._close_claim_overlay()  # 领取后可能弹奖励遮罩（复用登录奖励同一套遮罩清理）。
        self.log_warning(f"任务奖励领取点击达到上限 {_MISSION_CLAIM_MAX_CLICKS}，停止领取")  # 上限耗尽仍未收敛，记录异常。

    def _flow_shop(self):  # 商店流程（自足重入）：购买活动商店商品。实机未标定前占位，非幂等流程留 v1.5。
        self.log_info("商店流程占位：TODO 实机标定商店页判据")  # 记录占位。