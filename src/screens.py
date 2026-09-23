"""集中式界面识别注册表：全部界面的单一数据源。

注意：本模块必须是纯数据 + stdlib（禁止 import ok 框架），以便完整性测试低成本导入。

迁移前各界面分散注册在 NikkeBaseTask.__init__（lobby）、ArkTask.__init__
（ark、tribe_tower、simulation_room）、CashShopTask.__init__（cash_shop）与
RaidTask.__init__（coop_* / solo_raid_*）；集中后 DebugTask 与
current_screen() 能看到全量界面。
任务仍可用 NikkeBaseTask.register_screen 追加私有界面，同名覆盖全局条目。

判定语义（NikkeBaseTask._screen_match）：features 全部命中才算命中（与）；
keywords 任一命中即命中（或）；两者同时配置时再取「与」；ocr_box 仅用于
限定 keywords 的 OCR 区域。条目只写真实存在的键，缺省键省略不补空列表。

顺序即注册顺序：NikkeBaseTask 按本字典顺序灌入 self.screens；
current_screen() 按 priority 降序、同优先级按插入顺序遍历，
因此必须保持 lobby 在前的既有次序。

扩展字段（缺省 = 现状行为，现有条目未填充）：
- absent: list[str]，消歧特征，任一在当前帧命中则该界面判定失败
  （用于特征子集重叠的相邻界面互斥）。
- any_features: list[str]，任一命中特征，任一在当前帧命中即视为特征命中
  （与 features 的「全部命中」相对，用于图标三选一等「或」语义判定）。
- feature_box: str，可选匹配区域（coco 区域特征名），仅作用于 any_features
  的特征匹配；缺失时退化为全屏匹配。
- priority: int，默认 0。仅影响 current_screen() 的遍历顺序：
  按其降序、同优先级保持注册顺序；is_screen/wait_screen/assert_screen 不受影响。
- min_frames: int，默认 1。仅作用于 wait_screen/assert_screen 的轮询判定，
  需连续 N 轮命中才算进入（轮询每轮取新帧）；is_screen 恒为单帧语义。
"""

import re  # 关键词统一编译为正则（OCR 部分匹配 + 忽略大小写）。

LOGIN_PAGE_PATTERN = re.compile(r"TOUCH\s+TO\s+CONTINUE", re.IGNORECASE)  # 登录页进入游戏提示文字（TOUCH TO CONTINUE）。


def _keyword(text):
    """界面标题关键词：忽略大小写的正则（框架对裸字符串走全等比较）。"""
    return re.compile(text, re.IGNORECASE)

SCREENS = {
    "lobby": {"features": ["ark", "lobby"]},
    "login_page": {"keywords": [LOGIN_PAGE_PATTERN], "ocr_box": "box_enter_game"},
    "ark": {"features": ["ark_tribe_tower", "ark_simulation_room"]},
    "tribe_tower": {"features": ["tribe_tower_mark"]},
    # 模拟室：超频更新弹窗会遮住室徽 simulation_mark，故把该弹窗也列为判据（命中即已进入）。
    "simulation_room": {"any_features": ["simulation_mark", "simulation_overclock_update"]},
    "shop": {"keywords": [_keyword("百货商店")], "ocr_box": "box_sub_pages_title"},
    # 付费商店内的两个礼包子页面：页面标题特征互相误命中（普通页标记在限时页上实测 0.862 > 阈值），
    # 故用 absent 消歧；置于 cash_shop 之前，使 current_screen() 优先报出更细的子页面。
    "cash_shop_limited_time_page": {"features": ["cash_shop_limited_time_package"]},
    "cash_shop_ordinary_page": {"features": ["cash_shop_ordinary_package"],
                                "absent": ["cash_shop_limited_time_package"]},
    "cash_shop": {"keywords": [_keyword("付费商店")], "ocr_box": "box_sub_pages_title"},
    "recruit_page": {"keywords": [_keyword("招募队员")], "ocr_box": "box_sub_pages_title"},
    "coop_page": {"features": ["coop_page"]},
    "coop_nikke_select_page": {"features": ["coop_nikke_select_page"]},
    "solo_raid_page": {"features": ["solo_raid_page"]},
    "solo_raid_battle_team_select_page": {"features": ["solo_raid_battle_team_select_page"]},
    # 竞技场相关界面：方舟→竞技场（主界面）→新人/特殊竞技场（子页面）。
    "arena": {"features": ["arena_page"]},
    "rookie_arena": {"features": ["rookie_arena_page"]},
    "special_arena": {"features": ["special_arena_page"]},
    # 方舟相关子页面：方舟→排名。
    "ark_ranking": {"features": ["ark_ranking_page"]},
    # 拦截战入口双标签页：从方舟点 ark_interception 后停在通用或异常个体标签页，
    # 两个标签页的 active/disable 特征成对消歧（当前标签显示 active，另一标签显示 disable）。
    "interception_page": {"features": ["common_interception_active"],
                          "keywords": [_keyword("拦截战")], "ocr_box": "box_sub_pages_title"},
    "anomaly_interception_page": {"features": ["anomaly_interception_page", "anomaly_interception_active"]},
    "common_interception_page": {"features": ["common_interception_page"]},
    "anomaly_interception_team_select_page": {"features": ["anomaly_interception_team_select_page"]},
    # 前哨基地相关界面：前哨基地主页 → 指挥中心页 → 咨询列表页 → 咨询详情页 → 咨询对话页。
    "outpost": {"features": ["command_center"], "keywords": [_keyword("前哨基地")], "ocr_box": "box_sub_pages_title"},
    "command_center": {"keywords": [_keyword("指挥中心")], "ocr_box": "box_sub_pages_title"},
    "advise": {"features": ["advise_page_icon"], "keywords": [_keyword("咨询")], "ocr_box": "box_sub_pages_title"},
    "advise_nikke": {"features": ["advise_detail_page", "advise_gift"]},
    # 咨询对话（谈话）页：三个对话图标（取消/记录/跳过）任一出现即判定，
    # 走 any_features「任一命中」扩展字段（与 features 的「全部命中」相对），
    # feature_box 为可选的匹配区域限定（字符串形式的 coco 区域特征名）。
    "conversation": {"any_features": ["conversation_cancel", "conversation_log", "conversation_skip"],
                     "feature_box": "box_conversation_icon"},
    # 活动列表页：大厅右侧「活动」图标进入的整页列表（返回+主页双蓝键）。
    "event_list_page": {"keywords": [_keyword("活动页面")], "ocr_box": "box_sub_pages_title"},
    # 活动主页（大小活动两形态）：大活动底部菜单栏 / 小活动四周按钮均带「剩余时间」，
    # 以其为跨期稳定判据（无稳定模板）；进入判定容忍入场动画见 EventTask._enter_and_probe。
    # 大活动点 STORY I/II 后的剧情子页面左上标题同为「剧情活动」（但无活动菜单），也归入本界面：
    # 菜单页 / 剧情子页面的区分由 EventTask 的入口关键词与菜单可见性判据承担（_probe_story_sub_page）。
    "event_main": {"keywords": [_keyword("剧情活动"), _keyword("活动地区")], "ocr_box": "box_sub_pages_title"},
    # 活动关卡页：剧情入口后的关卡列表（左上标题「活动关卡」）；关卡行解析见 src/event_stage.py，
    # 列表区与难度区分别是 box_event_stage_list / box_event_stage_mode。
    "event_stage_page": {"keywords": [_keyword("活动关卡")], "ocr_box": "box_sub_pages_title"},
    # 活动挑战页：大小活动为同一套 UI（已确认），左上标题「挑战关卡」。
    # 仅用关键词「挑战」判定（不依赖 coco 特征）。
    "event_challenge_page": {"keywords": [_keyword("挑战")], "ocr_box": "box_sub_pages_title"},
    # 活动内置小游戏（本期 THREE COMPANY RUMBLE）：独立于活动页的整屏实时小游戏，入口在活动菜单带
    # （关键词「小游戏」，见 _ENTRIES），判据全部用本期已标注的 coco 特征，不依赖逐期变化的弹窗美术。
    # 顺序即 current_screen() 的报出顺序（同优先级按注册序）：两个模态框（暂停弹窗 / 任务弹窗）放最前，
    # 粗判据「主界面」放最后——弹窗都盖在主界面/关卡上面，让更具体的界面先被报出。
    # 暂停弹窗：弹窗右上关闭钮（弹窗开启判据，关卡内与结算页都不出现）。
    "event_minigame_pause_dialog": {"features": ["event_minigame_pause_close"]},
    # 关卡内：右上暂停钮在暂停弹窗与结算页下仍可见，作为「本局进行中」的判据。
    "event_minigame_play": {"features": ["event_minigame_pause"]},
    # 主界面「任务」弹窗：弹窗右上关闭钮（弹窗自身元素，位置逐期固定且不被别的界面覆盖）。
    "event_minigame_mission_popup": {"features": ["event_minigame_mission_close"]},
    # 本局结算页（GAME OVER）：顶部标题特征。
    "event_minigame_result": {"features": ["event_minigame_result"]},
    # 选择妮姬页（角色 / 特殊技能 / 必杀技键位 + 底部 START）：判据在页面底部，不被弹窗遮挡。
    "event_minigame_select": {"features": ["event_minigame_start"]},
    # 小游戏主界面：左上标题栏文案（与活动菜单入口同名，只是入口在活动菜单带、标题在小游戏自己的标题栏）；
    # OCR 文字判据，不依赖逐期变化的美术模板。
    "event_minigame_main": {"keywords": [_keyword(r"小\s*游\s*戏")], "ocr_box": "box_sub_pages_title"},
}

# 长等待中断哨兵：断线/维护/登录过期等致命中断弹窗的特征清单。
# 本期为空（哨兵未激活）：实机遇到对应弹窗并标注进 coco 后，把特征名加入
# features 即激活。激活后 wait_battle_finish 等长轮询会在每轮先查本清单
# （复用帧级缓存、不新增抓帧频率），命中即保存现场并快速失败，不再空转等满超时。
INTERRUPTS = {
    "screens": [],
    "features": [],
}
