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

顺序即注册顺序：NikkeBaseTask 按本字典顺序灌入 self.screens，而
current_screen() 按插入顺序首命中返回，因此必须保持 lobby 在前的既有次序。

本模块必须是纯数据模块：仅用 stdlib、不 import ok、不依赖任何框架对象，
以便 coco 完整性测试等工具低成本导入。
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
