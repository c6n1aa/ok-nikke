"""活动任务的常量与身份工具：模块级常量 + 罗马数字归一 + 活动身份 / 完成状态键。

从 `src/tasks/EventTask.py` 拆出（值与注释原样搬运）：任务类与各子流程 mixin 共用这些常量，
故集中在叶子模块，避免 mixin 反向从 `src.tasks.EventTask` 取值构成环形导入。
"""

import hashlib  # 哈希模块，活动身份段在归一后为空时回落该键的短哈希（保证身份非空且稳定）。
import re  # 正则模块，入口关键词用 OCR 部分匹配（忽略大小写），身份段白名单归一也用正则。

from src import event_calendar  # 日历键前缀剥离（活动身份段取展示名）。


# 大厅右侧「活动」入口图标特征（已标注进 coco）。
_EVENT_ICON = "event_icon"
# 活动主页菜单栏 OCR 区域（已标注进 coco）：大小活动的入口文字带位置不同，各自一个区域。
# _probe_entry 逐区 OCR，任一区域命中即视为该入口存在。
_MENU_BAND_BOXES = (
    "box_event_menu_band",  # 大活动主页底部菜单栏（STORY I/II/挑战/小游戏/签到印章/商店）。
    "box_event_menu_band_small",  # 小活动主页四周文字按钮区（挑战/任务/商店/记录保管所 + ENTER）。
)

_MAX_CARDS = 10  # 列表最多遍历的滚动位置数（卡片数不定，用带上限的循环防死循环）。

# 列表滚动手势与到底判据常量（实机按滚动步长精确性微调）。
_SCROLL_SWIPE_DURATION = 2  # 滚动手势 duration 参数（swipe 步数 = duration/100，与框架 pynput/post_message 同口径；2 即 1 步快速甩动）。
_SCROLL_AFTER_SLEEP = 1.8  # 滚动后动画停稳等待（秒）。
_SCROLL_TOP_MAX_SWIPES = 8  # 归一化到顶部的最多下滑次数（防死循环）。
_SCROLL_UNCHANGED_RATIO = 0.02  # 列表区滚动前后像素差异比例阈值：低于视为画面无变化（到底/到顶）。
_SWIPE_START_RATIO = 0.8  # 滚动手势起点（占滚动区高度比例）。
_SWIPE_END_RATIO = 0.55  # 滚动手势终点（占滚动区高度比例）。
_STAGE_SWIPE_START_RATIO = 2 / 3  # 关卡列表滚动手势起点：从区域内垂直 2/3 处开始（避开标题与底部导航）。
_STAGE_SCAN_MAX_SCROLLS = 6  # 关卡列表跨屏查找的最多下滚次数（防死循环）。

_STORY_MODES = ("NORMAL", "HARD")  # 剧情关卡难度选项（沿用游戏内英文标签）；难度选择未实现，配置项暂隐藏入口。

# 活动关卡页（剧情子流程）区域特征（解析规则与切片参数见 src/event_stage.py）。
_STAGE_LIST_BOX = "box_event_stage_list"  # 关卡列表区（只取横向 x/width：纵向标注逐期不同，解析时拉满整屏，见 event_stage.list_strip）。
_STAGE_MODE_BOX = "box_event_stage_mode"  # 关卡页难度区（NORMAL / HARD）；难度选择未实现，暂未接线。

# 剧情执行链（点行 → 剧情跳过 → 连续战斗 → 回关卡页）参数（实机按加载/结算动画时长校准）。
_STORY_BATTLE_TIMEOUT = 240  # 单场战斗结束等待上限（秒），与其它任务的战斗等待一致。
_STORY_MAX_BATTLES = 20  # 连续「下一关」链的安全上限（防结算按钮识别抖动导致死循环）。
_STORY_FIELD_CHANGED_FEATURE = "event_story_field_changed"  # 大活动（FieldHub）换地区提示按钮（coco 已标注）：点完回到活动地区页。
_STORY_FIELD_CHANGED_WAIT = 5  # 换地区提示的容错等待窗口（秒）：只在「战斗已结束/未开始」时付，详见 _field_changed_stop。
_STORY_MAX_PUSH_ROUNDS = 10  # 换地区后重新进关卡页继续推图的轮次上限（防提示识别抖动导致死循环；一次运行连清多个地区属正常）。
_STORY_DIALOG_WAIT = 8  # 点关卡/下一关/结算返回后等剧情对话界面或战斗界面出现的窗口（秒）。
_STORY_SKIP_MAX = 3  # 单次剧情跳过的最多点击次数（剧情可能分段）。
_STAGE_ENTER_TIMEOUT = 8  # 点关卡行后等界面落点的窗口（推图：离开列表 / 进详情页；扫荡：详情页就位）；加载慢导致误判时调大。
_STAGE_DETAIL_BATTLE_BOX = "box_stage_detail_battle"  # 关卡详情页「战斗」区域（推图判态：彩色可用 = 该关可推）。
_BATTLE_AFTER_SLEEP = 5  # 点「下一关」/结算按钮后等待下一场加载（秒），同 ArkTask 爬塔链。
# 等待循环的采样间隔（秒）：ok 的 wait_condition 循环体内没有 sleep，逐帧抓帧+匹配实测约 54 fps
# （wait_battle_finish 的注释也写明要节流避免与游戏抢 CPU）。挂在 post_action 上只降低采样频率，
# 容错窗口与判据不变；条件命中时框架直接返回，不付这段间隔。
_STORY_POLL_INTERVAL = 0.3

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
# 关卡标记点击框沿 X 轴的左移量范围（占屏宽比例）：标记是行右端的像素点装饰、命中框贴行右边缘
# （dev_tools/event/event_challenge.png 实测标记 (1600,565,25,42)，行主体左边界约在屏宽 0.34 处），
# 直接点标记会落在行右边缘上，左移后落进行主体（0.06~0.12 → 2560 下 154~307px，落点 x ≈ 1305~1458）。
# 区间随机取偏移：每次落点不固定在同一像素。
_CHALLENGE_CLICK_X_OFFSET = (0.06, 0.12)
_CHALLENGE_CLICK_ATTEMPTS = 2  # 点关卡标记进详情页的最多尝试次数：点空（落点被遮挡/界面未响应）时重试，两次都没出来才结束。
_CHALLENGE_PAGE_SETTLE = 2  # 挑战页节点渲染出来后再多等的时间（秒）：行卡片入场动画没走完时点击会被游戏吃掉。

# 大活动子页面到达等待（秒）：点击底部菜单入口后，SD 小人先走到地点、子界面才打开（签到/挑战/剧情子页面共用同一物理量）。
# 小活动点击入口即切页，轮询首帧就命中；大活动每期地图大小不同、小人走到地点后还有切页动画，故取统一可用上限而非逐期精确值。
_SD_ARRIVE_TIMEOUT = 12  # 点到子界面出现的等待上限（秒）：轮询命中即提前返回，仅小人未到达时才等满。

# 面板底部「全部领取」判据（签到印章面板与活动任务弹窗共用：文字同字、都落在面板底部同一带）。
# 面板美术逐期变，模板类判据必失效（同登录奖励的思路），故只用「相对区域 OCR 文字 + 外扩取底色判态」。
_CLAIM_ALL_TEXT = re.compile("全部领取", re.IGNORECASE)  # 「全部领取」按钮文字（跨皮肤唯一稳定判据，OCR 部分匹配）。
_CLAIM_ALL_SCAN_BOX = (1 / 3, 0.6, 2 / 3, 1.0)  # 按钮的 OCR 搜索区域（相对坐标 x1,y1,x2,y2；实机校准）。
_CLAIM_ALL_PAD = (0.2, 0.36)  # 文字框外扩比例（宽, 高）：外扩取到按钮底色才能判可领与否（同登录奖励，比例外扩适配各分辨率）。

# 活动任务弹窗（大小活动同一套 UI）：点入口弹出模态框，弹窗内「全部领取」可反复点到无可领。
# 弹窗美术逐期变（标题是当期活动名），无跨期稳定的模板特征，判据只用「coco 区域 + OCR 文案」。
_MISSION_SUBTITLE_BOX = "box_event_mission_subtitle"  # 小活动弹窗副标题区域（单页弹窗，coco 区域，位置逐期固定）。
_MISSION_SUBTITLE_TEXT = re.compile("CHALLENGE", re.IGNORECASE)  # 小活动副标题关键词（弹窗就位的跨期稳定判据）。
_MISSION_ICON_BOX = "box_event_mission_icon"  # 大活动弹窗栏目区（「每日任务」「成就」两个栏目的搜索范围）。
_MISSION_TABS = (  # 大活动弹窗栏目（点开默认停在「每日任务」页）：role -> (coco 特征, 栏目文案)。
    ("daily", "event_mission_daily", re.compile("每日任务")),  # 每日任务栏目。
    ("challenge", "event_mission_challenge", re.compile("成就")),  # 成就（挑战）栏目。
)
_MISSION_DAILY_SUBTITLE_BOX = "box_event_daily_subtitle"  # 大活动弹窗副标题区（页面状态判据：文字随栏目变）。
_MISSION_READY_TIMEOUT = 10  # 点入口后等弹窗就位（大活动认栏目图标，小活动认副标题）的窗口（秒）。
_MISSION_TAB_SWITCH_TIMEOUT = 5  # 点栏目标签后等副标题变化的窗口（秒）。
_MISSION_CLAIM_MAX_CLICKS = 20  # 单次领取循环的点击上限（点击未生效时防死循环）。
_MISSION_CLAIM_SETTLE_TIMEOUT = 5  # 点击「全部领取」后等第二段重新可领的观察窗（秒）。
_MISSION_CLAIM_SETTLE = 1.5  # 第二段重新可领后的稳定确认时间（秒），吸收按钮入场/位移动画。

# OCR 对游戏内美术字的罗马数字吐 Unicode 码点而非 ASCII 字母：实测 2560x1440 下菜单栏「STORY II」被识别为
# "STORYⅡI"（U+2161 ROMAN NUMERAL TWO）或 "STORYⅢ"（U+2162 ROMAN NUMERAL THREE），
# 不归一的话只认 ASCII 的 STORY 关键词永远匹配不上，剧情入口会静默回落到 STORY I。
_ROMAN_NUMERALS = {0x2160 + index: "I" * (index + 1) for index in range(12)}  # Ⅰ~Ⅻ（U+2160~U+216B）-> 等长 ASCII I 串。


def normalize_roman_numerals(text):  # 入口 OCR 文本 -> Unicode 罗马数字还原成 ASCII I 串（Ⅱ -> II、Ⅲ -> III）。
    if not isinstance(text, str):  # 非文本（无文本的框）原样返回。
        return text  # 无需归一。
    return "".join(_ROMAN_NUMERALS.get(ord(char), char) for char in text)  # 逐字符查表，未命中原样保留。


# 剧情入口关键词（探测顺序即优先级；_ENTRIES['剧情'] 直接引用，大小活动差异由命中的关键词区分）。
# 大活动菜单页是 STORY I/II，小活动主页与大活动剧情子页面是「加成奖励妮姬」。
# STORY I/II 会同时出现在菜单栏；未开放的章节仍是可读文字（锁图标 + 灰字），点开不切页，
# 故顺序即候选顺序：STORY II 优先，点不开由 _enter_story_sub_page 回落到 STORY I。
_STORY_MENU_PATTERNS = (  # 大活动菜单页的剧情入口。
    re.compile(r"STORY\s*II", re.IGNORECASE),  # STORY II 先于 STORY I：STORY I 是 STORY II 的前缀。
    re.compile(r"STORY\s*I(?!I)", re.IGNORECASE),  # 与 STORY II 消歧。
)
_STORY_SUB_PATTERN = re.compile(r"加成", re.IGNORECASE)  # 文案为「加成奖励妮姬」，只取前两字避免整词识别不到。

# 锁定入口的亮度前置判据（_entry_locked）：未开放的菜单入口整行为灰暗态（锁图标 + 灰字，无任何高亮像素），
# 可用入口必有白色笔画或高亮底。实测 2560x1440 命中框内高亮像素占比：锁定 0.000~0.007（两张往期截图）、
# 可用 0.16~0.45（STORY I/挑战/签到印章/商店等），阈值取中间留 8 倍余量。
# 方向保守：只用于「提前跳过」省掉一次 _SD_ARRIVE_TIMEOUT 空等，判不出来一律当可用，交行为后验（点开等子页面就位）。
# 不靠锁图标模板：锁图标属美术资源，逐期可能不一致（实测两期分别为「锁图标 + 灰字」与「灰字 + 亮底条」）。
_ENTRY_LOCK_BRIGHT_V = 200  # 高亮像素的亮度门限（HSV 的 V 通道，0~255）。
_ENTRY_LOCK_BRIGHT_RATIO = 0.02  # 高亮像素占比低于该值 = 无白字/高亮底 → 视为锁定态。

# 活动菜单可见性判据入口：大活动地图页与小活动主页都有（大活动剧情子页面只是布局上「像小活动」，没有活动菜单）。
_MENU_PROBE_ENTRIES = ("挑战", "任务", "商店")

# 活动主页功能入口探测表：label -> 关键词正则列表（列表顺序即探测顺序）。
# OCR 在 _MENU_BAND_BOXES 各区域内逐区匹配；预留 feature 位：实机若发现某入口只有图标无文字，
# 再改成 {label: (feature, [keywords])} 形式补 coco 特征匹配。
_ENTRIES = {
    "签到": [re.compile(r"签到印章", re.IGNORECASE)],
    "剧情": [*_STORY_MENU_PATTERNS, _STORY_SUB_PATTERN],
    "挑战": [re.compile(r"挑战", re.IGNORECASE)],
    "任务": [re.compile(r"任务", re.IGNORECASE)],  # 小活动在菜单带；大活动在专属区域（见 _ENTRY_EXTRA_BOXES）。
    "商店": [re.compile(r"商店", re.IGNORECASE)],
    "小游戏": [re.compile(r"小游戏", re.IGNORECASE)],
}

# 入口专属区域（在默认菜单带之前追加探测，不替换）：大活动「任务」入口不在菜单带内，另有专属区域。
_ENTRY_EXTRA_BOXES = {
    "任务": ("box_event_menu_mission",),  # 大活动主页右侧的任务入口区域。
}

# 已实现的子流程（执行顺序即探测顺序）：小游戏排最后——它是实时游玩、耗时最长，失败恢复会退回大厅，
# 放最后不会把前面已完成的子流程牵连进恢复流程。
_SUBFLOW_ORDER = ("签到", "剧情", "挑战", "任务", "商店", "小游戏")

# 子流程名 -> 入口方法名（开关/探测/try_step 分派，沿用 ArkTask 的 _do_* 结构）。
_SUBFLOW_METHODS = {
    "签到": "_do_checkin",
    "剧情": "_do_story",
    "挑战": "_do_challenge",
    "任务": "_do_mission",
    "商店": "_do_shop",
    "小游戏": "_do_minigame",
}

# 尚未接入的入口：探测到只记日志（本期为空——小游戏已按 MINIGAMES 注册表接入）。
_SKIPPED_ENTRIES = ()

# 入口点击框修正：关键词（pattern.pattern）-> 沿 Y 轴的上移量（占屏高比例），作用于菜单带 / 子页面里的命中。
# 「加成奖励妮姬」的命中文字在按钮下缘，点击落点需上移到按钮主体（小活动主页与剧情子页面同款布局，实机标定）。
_ENTRY_CLICK_Y_OFFSET = {
    "加成": 0.06,
}

# 入口专属区（_ENTRY_EXTRA_BOXES）内的点击框修正：关键词 -> 沿 Y 轴的上移量（占屏高比例）。
# 与上面的通用表分开：小活动同名入口落在菜单带里，是文字就在按钮上的纯文字按钮，点文字本身，不能跟着上移。
# 大活动「任务」入口的文字在图标下方，点击落点需上移到图标（dev_tools/event/event_big_main_01.png 实测：
# 专属区 box_event_menu_mission 内文字框中心 (2500,356)、图标中心 y≈309，上移 47px ≈ 0.033 × 1440）。
_ENTRY_EXTRA_CLICK_Y_OFFSET = {
    "任务": 0.033,
}

# 小游戏注册表：活动身份（event_identity(日历 banner 键)，与完成状态键同源）-> 该活动小游戏流程的方法名。
# 键跟着当期活动的名称走，不给小游戏另起代号；换期换小游戏时只在这里加一条，
# 同一套小游戏 UI 复用时多条键可指向同一流程方法。
MINIGAMES = {
    "COINRUSHSHOWDOWN": "_flow_minigame",  # THREE COMPANY RUMBLE（本期在架活动的小游戏）。
}

# ---- 小游戏（活动内置的实时小游戏）----
# 入口在活动菜单带（关键词「小游戏」，见 _ENTRIES）；进入后是独立于活动页的整屏界面：
# 主界面 → 选择妮姬页 → 关卡 → 结算页 → 主界面。关卡内只有两个输入（点击改攻击与移动方向、必杀技按键），
# 没有可读的胜负信号、只有分数区，故自动化只做「刷到达标分数」→ 用暂停弹窗的「快速完成」结束本局。
# 页面判据与点击框全部走本期已标注的 coco 特征/区域（判据不带逐期变化的弹窗美术）。
_MINIGAME_MAIN_SCREEN = "event_minigame_main"  # 小游戏主界面（左上标题栏「小游戏」）。
_MINIGAME_SELECT_SCREEN = "event_minigame_select"  # 选择妮姬页（角色 / 特殊技能 / 必杀技键位）。
_MINIGAME_PLAY_SCREEN = "event_minigame_play"  # 关卡内（判据是右上暂停钮：暂停弹窗与结算页都不覆盖它）。
_MINIGAME_RESULT_SCREEN = "event_minigame_result"  # 本局结算页（GAME OVER）。
_MINIGAME_PAUSE_DIALOG_SCREEN = "event_minigame_pause_dialog"  # 暂停弹窗（点关卡右上暂停钮弹出）。
_MINIGAME_MISSION_POPUP_SCREEN = "event_minigame_mission_popup"  # 主界面「任务」弹窗（模态框）。
_MINIGAME_START_ENTRY = "box_event_minigame_enter"  # 主界面 START 区域（点击进入选择妮姬页）。
_MINIGAME_SELECT_START = "event_minigame_start"  # 选择妮姬页底部 START（点击开始本局）。
_MINIGAME_SCORE_BOX = "box_event_minigame_score"  # 关卡内分数区（OCR 取当前分数）。
_MINIGAME_PAUSE_BOX = "event_minigame_pause"  # 关卡内右上角暂停钮（ESC）。
_MINIGAME_QUICK_FINISH_BOX = "box_event_minigame_quick_finish"  # 暂停弹窗「快速完成」（记录目前分数并退出游戏）。
_MINIGAME_RESULT_BACK_BOX = "box_event_minigame_result_back"  # 结算页「返回」（回小游戏主界面）。
_MINIGAME_MISSION_ENTRY = "event_minigame_mission"  # 主界面左侧「任务」入口图标。
_MINIGAME_MISSION_CLAIM_BOX = "box_event_minigame_mission_claim"  # 任务弹窗底部「全部领取」按钮区域。
_MINIGAME_MISSION_CLOSE = "event_minigame_mission_close"  # 任务弹窗右上关闭钮。
_MINIGAME_EXIT_CONFIRM = "event_minigame_exit_confirm"  # 「确定要退出小游戏吗？」的「确认」钮。
_MINIGAME_SCORE_PATTERN = re.compile(r"\d[\d,]*")  # 分数区 OCR 文本取数字（兼容千分位分隔符）。
_MINIGAME_TAP_POINT = (0.5, 0.5)  # 关卡内点击落点（屏幕相对坐标）：画面中央，避开顶部 HUD 与底部技能栏。
_MINIGAME_TAP_INTERVAL = 0.5  # 关卡内点击间隔（秒）：每次点击改变攻击与移动方向。
_MINIGAME_SCORE_INTERVAL = 2.5  # 分数区 OCR 间隔（秒）。
_MINIGAME_TARGET_SCORE = 4000  # 达标分数：达到即用「快速完成」结束本局。
_MINIGAME_PLAY_TIMEOUT = 600  # 单局游玩上限（秒）：到点仍未达标也按当前分数快速完成（本局自然结束会提前退出）。
_MINIGAME_ENTER_TIMEOUT = 30  # 点活动菜单「小游戏」入口后等小游戏主界面出现的窗口（秒，含整屏加载）。
_MINIGAME_START_TIMEOUT = 20  # 主界面 START 后等选择妮姬页 / 关卡就位的窗口（秒，含加载）。
_MINIGAME_DIALOG_TIMEOUT = 8  # 模态框（暂停弹窗 / 任务弹窗 / 退出确认框）就位窗口（秒）。
_MINIGAME_RESULT_TIMEOUT = 20  # 「快速完成」后等结算页出现的窗口（秒，含结算动画）。
_MINIGAME_CLAIM_MAX_CLICKS = 3  # 任务「全部领取」最多点击次数（两段式领取留余量，点击未生效时防死循环）。
_MINIGAME_BACK_ATTEMPTS = 2  # 结算页「返回」的最多尝试次数：结算动画期间点「返回」会被吃掉（点完不回主界面）。
_MINIGAME_CLAIM_SETTLE = 1  # 每次领取点击后的等待（秒），等遮罩与第二段渲染。
_MINIGAME_EXIT_TIMEOUT = 20  # 退出小游戏后等回活动菜单页的窗口（秒）。

# ---- 完成状态：按活动身份分键（键格式见 event_done_key） ----

_EVENT_KEY_PREFIX = "event_"  # 完成状态键前缀：event_<活动身份>[_<子流程>]，与旧版聚合键 event 区分。
_EVENT_KEY_MAX = 48  # 身份段长度上限：日历键是外部数据，截断避免脏键把配置撑大。
_EVENT_FLOW_PERIOD = "day"  # 活动子流程完成周期（游戏日常 04:00 刷新，与活动内的次数/门票同周期）。
_PER_EVENT_FLOWS = {  # 需要按活动身份各记一次的子流程：子流程名 -> 键内 ASCII 段。
    "签到": "checkin",  # 签到印章：面板「全部领取」与登录奖励同字，重复进入会走误判链，按活动记一次。
    "商店": "shop",  # 商店：购买消耗资源、非幂等，必须按活动分键（流程实现时直接复用本键）。
}
_LEGACY_DONE_KEY = "event"  # 旧版本的活动聚合键：只清不写（保留在 done_keys 里仅作「本任务有完成状态」的声明锚）。
_BIG_EVENT_TYPE = "FieldHubEvent"  # 日历里的大活动类型（地图页 + 签到印章）；不落此类型的即小活动形态。

_IDENTITY_SAFE_PATTERN = re.compile(r"[^0-9A-Za-z_]+")  # 身份段白名单：非字母数字下划线一律归一为下划线。


def event_identity(key):  # 日历 banner 键 -> 身份段（跨运行稳定、配置可读）。
    """日历条目 key -> 活动身份段：去 EVENT_BANNER_ 前缀 + 白名单归一 + 长度截断。

    日历 key 是外部数据，白名单归一后再进配置键，避免脏键把 configs 写坏；
    归一后为空（整串都是非法字符）时回落该 key 的 md5 短哈希，保证身份非空且同键稳定。
    """
    raw = event_calendar.strip_banner_prefix(key)  # 展示名（去掉 banner 前缀，与日志里的活动名一致）。
    safe = _IDENTITY_SAFE_PATTERN.sub("_", raw).strip("_")[:_EVENT_KEY_MAX]  # 白名单归一 + 首尾去下划线 + 截断。
    if safe:  # 归一后仍有可用字符。
        return safe  # 用归一结果作身份。
    return hashlib.md5(str(key).encode()).hexdigest()[:8]  # 兜底：确定性短哈希。


def event_done_key(identity, flow=None):  # 活动身份（+ 子流程）-> 完成状态键。
    """活动身份 -> 完成状态键：聚合键 event_<身份>，子流程键 event_<身份>_<流程>。"""
    if not identity:  # 身份为空说明调用方漏了判断。
        raise ValueError("event identity is required")  # 显式报错，避免写出 event_None 这类脏键。
    base = f"{_EVENT_KEY_PREFIX}{identity}"  # 聚合键：该活动本周期内是否已处理。
    return base if not flow else f"{base}_{flow}"  # 带子流程段时拼子流程键。
