"""集中式界面识别注册表：全部界面的单一数据源。

上游设计见 docs/screen-recovery-evolution-plan.md §5.3（方案 1 子项 1）。
迁移前各界面分散注册在 NikkeBaseTask.__init__（lobby）、ArkTask.__init__
（ark、tribe_tower、simulation_room）、CashShopTask.__init__（付费商店）与
RaidTask.__init__（coop_* / solo_raid_*）；集中后 DebugTask 与
current_screen() 能看到全量界面，后续方案也以本表为准。
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
- priority: int，默认 0。仅影响 current_screen() 的遍历顺序：
  按其降序、同优先级保持注册顺序；is_screen/wait_screen/assert_screen 不受影响。
- min_frames: int，默认 1。仅作用于 wait_screen/assert_screen 的轮询判定，
  需连续 N 轮命中才算进入（轮询每轮取新帧）；is_screen 恒为单帧语义。
"""

SCREENS = {
    "lobby": {"features": ["ark", "lobby"]},
    "ark": {"features": ["ark_tribe_tower", "ark_simulation_room"]},
    "tribe_tower": {"features": ["tribe_tower_mark"]},
    "simulation_room": {"features": ["simulation_mark"]},
    "付费商店": {"keywords": ["付费商店"], "ocr_box": "box_sub_pages_title"},
    "coop_page": {"features": ["coop_page"]},
    "coop_nikke_select_page": {"features": ["coop_nikke_select_page"]},
    "solo_raid_page": {"features": ["solo_raid_page"]},
    "solo_raid_battle_team_select_page": {"features": ["solo_raid_battle_team_select_page"]},
}

# 长等待中断哨兵：断线/维护/登录过期等致命中断弹窗的特征清单。
# 本期为空（哨兵未激活）：实机遇到对应弹窗并标注进 coco 后，把特征名加入
# features 即激活。激活后 wait_battle_finish 等长轮询会在每轮先查本清单
# （复用帧级缓存、不新增抓帧频率），命中即保存现场并快速失败，不再空转等满超时。
INTERRUPTS = {
    "screens": [],
    "features": [],
}
