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

import re  # 登录页关键词用正则（OCR 部分匹配，忽略大小写）。

LOGIN_PAGE_PATTERN = re.compile(r"TOUCH TO\s+CONTINUE", re.IGNORECASE)  # 登录页进入游戏提示文字（TOUCH TO CONTINUE）。

SCREENS = {
    "lobby": {"features": ["ark", "lobby"]},
    "login_page": {"keywords": [LOGIN_PAGE_PATTERN], "ocr_box": "box_enter_game"},
    "ark": {"features": ["ark_tribe_tower", "ark_simulation_room"]},
    "tribe_tower": {"features": ["tribe_tower_mark"]},
    "simulation_room": {"features": ["simulation_mark"]},
    "shop": {"keywords": ["百货商店"], "ocr_box": "box_sub_pages_title"},
    "cash_shop": {"keywords": ["付费商店"], "ocr_box": "box_sub_pages_title"},
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
                          "keywords": ["拦截战"], "ocr_box": "box_sub_pages_title"},
    "anomaly_interception_page": {"features": ["anomaly_interception_page", "anomaly_interception_active"]},
    "common_interception_page": {"features": ["common_interception_page"]},
    "anomaly_interception_team_select_page": {"features": ["anomaly_interception_team_select_page"]},
    # 前哨基地相关界面：前哨基地主页 → 指挥中心弹窗页 → 咨询列表页 → 咨询详情页 → 咨询对话页。
    "outpost": {"features": ["command_center"], "keywords": ["前哨基地"], "ocr_box": "box_sub_pages_title"},
    "command_center": {"keywords": ["指挥中心"], "ocr_box": "box_sub_pages_title"},
    "advise": {"features": ["advise_page_icon"], "keywords": ["咨询"], "ocr_box": "box_sub_pages_title"},
    "advise_nikke": {"features": ["advise_detail_page", "advise_gift"]},
    # 咨询对话（谈话）页：三个对话图标（取消/记录/跳过）任一出现即判定，
    # 走 any_features「任一命中」扩展字段（与 features 的「全部命中」相对），
    # feature_box 为可选的匹配区域限定（字符串形式的 coco 区域特征名）。
    "conversation": {"any_features": ["conversation_cancel", "conversation_log", "conversation_skip"],
                     "feature_box": "box_conversation_icon"},
}

# 长等待中断哨兵：断线/维护/登录过期等致命中断弹窗的特征清单。
# 本期为空（哨兵未激活）：实机遇到对应弹窗并标注进 coco 后，把特征名加入
# features 即激活。激活后 wait_battle_finish 等长轮询会在每轮先查本清单
# （复用帧级缓存、不新增抓帧频率），命中即保存现场并快速失败，不再空转等满超时。
INTERRUPTS = {
    "screens": [],
    "features": [],
}
