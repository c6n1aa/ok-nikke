import re  # 正则模块，用于 OCR 关键词的部分匹配。

from ok import og  # 全局单例，读取当前执行任务以判断是否由日常编排。
from ok.task.exceptions import WaitFailedException  # 界面断言/战斗超时抛出的框架等待失败异常。

from src.tasks.NikkeBaseTask import NikkeBaseTask  # 项目基类，所有任务统一继承它。

# 塔号 -> 企业名，用于战斗失败时提醒用户。
_TOWER_NAMES = {
    1: "极乐净土",  # 1号塔。
    2: "米西利斯",  # 2号塔。
    3: "泰特拉",  # 3号塔。
    4: "朝圣者/超标准",  # 4号塔。
}

# 塔卡 OPEN 关键词：OCR 忽略大小写匹配英文 OPEN。
_OPEN_PATTERN = re.compile(r"OPEN", re.IGNORECASE)
# 新人竞技场稳定战力压制比例：己方战力 * 0.846 > 对手战力才视为可稳定压制。
_ROOKIE_ARENA_CP_RATIO = 0.846

# 新人竞技场刷新对手列表的最大次数：用尽后结束子流程（标记完成）。
_ROOKIE_ARENA_MAX_REFRESH = 10

# 新人竞技场（战力标注区域， 免费挑战区域）对，自上而下对应 1-3 号对手。
_ROOKIE_CP_ENCOUNTER_PAIRS = (
    ("box_rookie_arena_o1_cp", "box_rookie_arena_o1_free_encounter"),  # 1号对手。
    ("box_rookie_arena_o2_cp", "box_rookie_arena_o2_free_encounter"),  # 2号对手。
    ("box_rookie_arena_o3_cp", "box_rookie_arena_o3_free_encounter"),  # 3号对手。
)


class ArkTask(NikkeBaseTask):  # 方舟任务：执行企业塔/模拟室/拦截战/竞技场等子流程。

    done_keys = {"tribe_tower": "day", "simulation": "day", "rookie_arena": "day", "special_arena": "day"}  # 完成状态：企业塔/模拟室/新人竞技场/特殊竞技场（日常刷新）。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "方舟"  # 任务显示名称。
        self.description = "执行企业塔/模拟室/拦截战/竞技场相关任务。"  # 任务说明。
        self.failed_towers = []  # 本次运行中战斗失败的塔号记录，供日常编排统一提醒。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "企业塔": True,  # 是否执行企业塔子流程。
            "关闭自动爬塔": False,  # 进入战斗后自动撤退，默认正常爬塔。
            "模拟室": True,  # 使用立即完成-快速模拟，通关模拟室流程。
            "新人竞技场": True,  # 使用每天5次的免费战斗（启用此功能请先配置好队伍）。
            "对手选择策略": True,  # 优先选择稳定战力压制的对手；关闭则固定选择最下面的对手。
            "特殊竞技场": True,  # 收取特殊竞技场累计奖励。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "企业塔": "是否执行企业塔（无限之塔）子流程。",
            "关闭自动爬塔": "进入战斗后自动撤退，适合只完成日常任务而不需要爬塔的指挥官。",
            "模拟室": "使用立即完成-快速模拟，通关模拟室流程。",
            "新人竞技场": "使用每天5次的免费战斗（启用此功能请先配置好队伍）。",
            "对手选择策略": "优先选择稳定战力压制的对手（己方战力 * 0.846 > 对手战力）；关闭则固定选择最下面的对手。",
            "特殊竞技场": "收取特殊竞技场累计奖励。",
        })
        self.config_type.update({  # 配置类型与显隐控制：布尔开关联动子配置显隐（参考 ShopTask）。
            "企业塔": {  # 布尔开关，启用时才展开企业塔配置。
                "sub_configs": {  # 开关联动子配置显隐。
                    True: ["关闭自动爬塔"],  # 启用时显示爬塔模式开关。
                    False: [],  # 关闭时收起配置。
                },
            },
            "新人竞技场": {  # 布尔开关，启用时才展开对手选择策略配置。
                "sub_configs": {  # 开关联动子配置显隐。
                    True: ["对手选择策略"],  # 启用时显示对手选择策略开关。
                    False: [],  # 关闭时收起配置。
                },
            },
        })

    def run(self):  # 任务执行入口：先统一进入方舟，再依次执行各子流程。
        self.log_info("方舟任务开始。")  # 记录任务开始。
        self.failed_towers = []  # 重置本次运行的失败塔记录，避免残留上次数据。
        if not self.try_step(self._nav_to_ark, name="进入方舟", raise_on_fail=False):  # 统一入口：确认进入方舟界面，失败则中止整个任务。
            self.log_error("未能进入方舟界面，中止方舟任务。")  # 记录中止原因。
            return  # 结束任务。
        self._do_tribe_tower()  # 执行企业塔子流程。
        self._do_simulation()  # 执行模拟室子流程。
        self._do_rookie_arena()  # 执行新人竞技场子流程。
        self._do_special_arena()  # 执行特殊竞技场子流程。

    def _nav_to_ark(self):  # 导航到方舟界面（幂等入口闸门，供子流程开头与统一入口复用）。
        self.ensure_screen("ark", click_feature="ark", wait_confirm=10, after_sleep=1)  # 过场动画容忍、弹窗清理与恢复/冷启动分流均在 ensure_screen 内。

    def _do_tribe_tower(self):  # 企业塔子流程：方舟→无限之塔→逐塔挑战→返回方舟。
        if not self.config.get("企业塔"):  # 用户未启用企业塔子流程。
            self.log_info("企业塔未开启，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        if self.is_done("tribe_tower", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日企业塔已完成，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        success = self.try_step(  # 企业塔整体流程以方舟为起点，用恢复协议包裹。
            lambda: self._do_tribe_tower_flow(),  # 执行企业塔流程。
            name="企业塔",  # 步骤名用于日志与失败截图。
            raise_on_fail=False,  # 多次失败后跳过而非抛异常。
        )
        if not success:  # 流程多次失败。
            self.log_warning("企业塔流程多次失败，跳过。")  # 记录跳过原因。
            return  # 不标记完成，下次可重试。
        self.mark_done("tribe_tower", "day")  # 记录本周期已完成。
        if not self._under_daily():  # 非日常编排时由本任务直接提醒。
            self.notify_failed_towers()  # 提醒战斗失败的塔。
        self.log_info("企业塔任务完成。")  # 记录子流程完成。

    def _do_simulation(self):  # 模拟室子流程：方舟→模拟室→红点判断→快速模拟→返回方舟。
        if not self.config.get("模拟室"):  # 用户未启用模拟室子流程。
            self.log_info("模拟室未开启，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        if self.is_done("simulation", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日模拟室已完成，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        success = self.try_step(  # 模拟室整体流程以方舟为起点，用恢复协议包裹。
            lambda: self._do_simulation_flow(),  # 执行模拟室流程。
            name="模拟室",  # 步骤名用于日志与失败截图。
            raise_on_fail=False,  # 多次失败后跳过而非抛异常。
        )
        if not success:  # 流程多次失败。
            self.log_warning("模拟室流程多次失败，跳过。")  # 记录跳过原因。
            return  # 不标记完成，下次可重试。
        self.mark_done("simulation", "day")  # 记录本周期已完成。
        self.log_info("模拟室任务完成。")  # 记录子流程完成。

    def _do_simulation_flow(self):  # 模拟室整体流程：确保在方舟→模拟室→更新弹窗处理→红点判断→快速模拟→关闭返回方舟。
        self._nav_to_ark()  # 确保处于方舟界面（正常已就位；失败恢复回大厅后由此重新进入）。
        self.transition("simulation_room", click_feature="ark_simulation_room", wait_confirm=10, after_sleep=1)  # 点击模拟室入口并确认已进入模拟室界面。
        update_popup = self.find_one("simulation_overclock_update")  # 进入模拟室后识别是否弹出超频更新公告弹窗。
        if update_popup is not None:  # 弹窗存在时会遮挡界面，必须先关闭再继续后续流程。
            self.log_info("检测到模拟室更新弹窗，先关闭。")  # 记录弹窗处理。
            self.wait_click_feature("simulation_overclock_update_close", raise_if_not_found=True, after_sleep=1)  # 点击弹窗关闭按钮，关闭后继续原流程。
        red_dot = self.find_red_dot("box_simulation_badge")  # 在模拟室徽标区域检测通知红点。
        if red_dot is None:  # 无红点说明今日模拟室已完成或不可挑战。
            self._click_simulation_close()  # 点击关闭按钮返回方舟。
            return  # 结束本流程（由调用方统一标记完成）。
        self.click_box(red_dot, after_sleep=1)  # 点击带红点的徽标进入关卡选择。
        if self.find_one("simulation_level5") is None:  # 当前未选中最高难度 Lv.5。
            self.wait_click_feature("simulation_level5", raise_if_not_found=True, after_sleep=1)  # 选择 Lv.5 难度。
        self.click_box("box_simulation_region_selector", raise_if_not_found=True, after_sleep=1)  # 点击地区选择器确认地区。
        switch_box = self.get_box_by_name("box_simulation_quick_complete")  # 开关两态几何位置不变，用纯坐标区域定位，不依赖模板匹配（规避布局横移导致的匹配脱靶）。
        if switch_box is not None and not self.is_feature_enabled(switch_box):  # 色彩丰富度判态：灰白为未激活。
            self.click_box(switch_box, after_sleep=1)  # 点击开关激活立即完成；已激活（彩色）直接继续快速模拟。
        quick_battle = self.find_one("simulation_quick_battle")  # 识别快速战斗按钮。
        if quick_battle is None:  # 无快速战斗按钮（今日已完成或不可快速完成）。
            self._click_simulation_close()  # 点击关闭按钮返回方舟。
            return  # 结束本流程（由调用方统一标记完成）。
        self.click_box(quick_battle, after_sleep=1)  # 点击快速战斗立即完成本场模拟。
        self.wait_click_feature("simulation_quick_battle_finishi", raise_if_not_found=True, after_sleep=1)  # 点击快速模拟结算的完成按钮。
        self.dismiss_all_popups(wait_for_popup=False, time_out=10)  # 清理结算后可能弹出的奖励/公告弹窗。
        self._click_simulation_close(raise_if_not_found=False)  # 尝试点击关闭按钮返回方舟（可能已在方舟则跳过）。

    def _click_simulation_close(self, raise_if_not_found=True):  # 点击模拟室右上角关闭按钮返回方舟。
        self.wait_click_feature("simulation_close", raise_if_not_found=raise_if_not_found, after_sleep=1)  # 等待关闭按钮出现并点击。

    def _do_tribe_tower_flow(self):  # 企业塔整体流程：确保在方舟→无限之塔→逐塔挑战→返回方舟。
        self._nav_to_ark()  # 确保处于方舟界面（正常已就位；失败恢复回大厅后由此重新进入）。
        self._enter_tribe_tower()  # 从方舟进入无限之塔界面（首塔入口已断言本界面）。
        abandoned = False  # 自动撤退模式是否已处理并返回方舟。
        for index in range(1, 5):  # 依次处理 1-4 号塔。
            if index > 1:  # 非首塔：上一塔返回后必须先重新识别到无限之塔界面（结算动画可能未收尾），再判断下一塔是否开放。
                self.assert_screen("tribe_tower")  # 轮询等待界面特征命中；超时抛 WaitFailedException 由 try_step 恢复重跑。
            handled = self._try_tower(index)  # 处理单号塔，返回是否进入过塔。
            if handled and self.config.get("关闭自动爬塔"):  # 自动撤退模式下进入一次即结束流程。
                abandoned = True  # 标记已结束。
                break  # 停止循环。
        if not abandoned:  # 正常模式走完所有塔后统一返回方舟。
            if not self.wait_click_feature("common_back", raise_if_not_found=False, after_sleep=1):  # 点击返回方舟界面。
                self.log_warning("返回方舟界面失败，后续任务会自动恢复。")  # 记录未返回，依赖后续任务的失败恢复。

    def _tower_is_open(self, box_key):  # 在塔卡区域 OCR 识别 OPEN 关键词，判断该塔是否开放。
        try:  # 区域特征可能缺失。
            box = self.get_box_by_name(box_key)  # 获取塔卡 OPEN 标注区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失。
            return False  # 视为未开放。
        if box is None:  # 区域无效。
            return False  # 视为未开放。
        return bool(self.ocr(box=box, match=_OPEN_PATTERN))  # 区域内 OCR 命中 OPEN 才算开放。

    def _try_tower(self, index):  # 处理单号塔：OPEN 判断→进入→战斗按钮可用性→战斗，返回是否进入过塔。
        box_key = f"box_tribe_tower{index}"  # 塔卡 OPEN 标注区域特征名。
        if not self._tower_is_open(box_key):  # 该塔未开放。
            self.log_info(f"{index}号塔未开放，跳过。")  # 记录跳过。
            return False  # 未进入塔。
        self._enter_tower(box_key)  # 点击塔卡进入该塔。
        self.wait_feature("tribe_tower_stage", raise_if_not_found=True)  # 等待进入塔关卡界面。
        self.click_box("box_tower_enter", raise_if_not_found=True, after_sleep=1)  # box_ 前缀特征为纯坐标区域无模板，直接按坐标点击进入关卡。
        battle_box = self.get_box_by_name("box_tribe_tower_battle")  # 获取战斗按钮区域（box_ 前缀特征为纯坐标区域，无模板）。
        if battle_box is None or not self.is_feature_enabled(battle_box):  # 区域缺失或按钮为灰白禁用态说明次数用尽。
            self.log_info(f"{index}号塔通关次数用尽，跳过。")  # 记录跳过。
            self.wait_click_feature("tribe_tower_close", raise_if_not_found=True, after_sleep=1)  # 点击关闭按钮关闭弹出的开始战斗卡片。
            self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 返回无限之塔界面。
            return False  # 未进入战斗。
        if self.config.get("关闭自动爬塔"):  # 关闭自动爬塔模式。
            self._abandon_battle(battle_box)  # 进入战斗后自动撤退，结束后已返回方舟界面。
        else:  # 正常爬塔模式。
            self._climb_battle(index, battle_box)  # 正常战斗并处理结算，结束后返回无限之塔界面。
        return True  # 已进入过塔。

    def _enter_tribe_tower(self):  # 从方舟进入无限之塔界面（调用时已确保处于方舟界面）。
        self.transition("tribe_tower", click_feature="ark_tribe_tower", wait_confirm=10, after_sleep=1)  # 点击企业塔入口并确认已进入无限之塔界面。

    def _enter_tower(self, box_key):  # 点击塔卡进入该塔。
        try:  # 区域特征可能缺失。
            box = self.get_box_by_name(box_key)  # 获取塔卡 OPEN 标注区域。
        except ValueError:  # 特征缺失。
            box = None  # 置空以便统一处理。
        if box is None:  # 区域无效。
            raise WaitFailedException(f"缺少区域特征: {box_key}")  # 抛异常由 try_step 恢复。
        cx = box.x + box.width // 2  # 点击 x 取 OPEN 区域水平中心。
        cy = box.y + box.height + int(0.1 * self.height)  # 点击 y 取区域底边下移 0.1 倍屏幕高度（塔卡中部）。
        self.click(cx, cy, after_sleep=3)  # 点击塔卡进入该塔。

    def _climb_battle(self, index, battle_btn):  # 正常爬塔：进入战斗、连续挑战下一关直到无下一关，最后返回无限之塔界面。
        self.click_box(battle_btn, after_sleep=10)  # 点击开始战斗按钮进入战斗。
        while True:  # 爬塔循环：每场战斗结束后按结算界面按钮决定继续挑战还是收尾。
            result, confirm_box = self.wait_battle_finish(time_out=240)  # 节流等待战斗结束，只检测不点击。
            if result == "success":  # 战斗胜利。
                next_stage = self.find_one("battle_finish_next_stage")  # 识别结算界面的下一关按钮。
                if next_stage is not None:  # 存在下一关按钮。
                    self.click_box(next_stage, after_sleep=10)  # 点击继续挑战下一关并等待下一场战斗加载。
                    continue  # 重新进入等待战斗结束的循环。
                self.click_box(confirm_box, after_sleep=10)  # 无下一关说明已到当前最高层，点击结算确认按钮返回塔关卡界面（wait_battle_finish 已等结算稳定后返回坐标）。
                break  # 结束爬塔循环。
            elif result == "failed":  # 战斗失败。
                self.failed_towers.append(index)  # 记录本次失败的塔号，供结束时提醒用户。
                self.click_box(confirm_box, after_sleep=1)  # 点击失败返回按钮。
                break  # 结束爬塔循环。
            else:  # 等待战斗结束超时。
                raise WaitFailedException("等待企业塔战斗结束超时")  # 抛异常由 try_step 恢复重试。
        self.dismiss_all_popups(wait_for_popup=False, time_out=10)  # 清理结算后可能弹出的奖励/公告弹窗。
        self.wait_feature("tribe_tower_stage", raise_if_not_found=True)  # 等待回到塔关卡界面。
        self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 点击返回无限之塔界面（下一塔开始前由流程断言该界面）。

    def _abandon_battle(self, battle_btn):  # 关闭自动爬塔模式：进入战斗后暂停撤退，消耗一次次数后返回方舟。
        self.click_box(battle_btn, after_sleep=10)  # 点击开始战斗并等待战斗加载约 10 秒。
        pause = self.wait_feature("battle_pause", time_out=15, raise_if_not_found=True)  # 识别战斗暂停按钮。
        self.click_box(pause, after_sleep=1)  # 点击暂停按钮。
        escape = self.wait_feature("battle_escape", raise_if_not_found=True)  # 识别撤退按钮。
        self.click_box(escape, after_sleep=1)  # 点击撤退放弃本场战斗。
        failed_back = self.wait_feature("battle_finish_failed_back", time_out=15, raise_if_not_found=True)  # 识别失败结算返回按钮。
        self.click_box(failed_back, after_sleep=1)  # 点击返回。
        self.wait_feature("tribe_tower_stage", raise_if_not_found=True)  # 等待回到塔关卡界面。
        self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 点击返回无限之塔界面。
        self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 点击返回方舟界面。

    def _do_rookie_arena(self):  # 新人竞技场子流程：竞技场→新人竞技场→免费挑战→返回方舟。
        if not self.config.get("新人竞技场"):  # 用户未启用新人竞技场子流程。
            self.log_info("新人竞技场未开启，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        if self.is_done("rookie_arena", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日新人竞技场已完成，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        success = self.try_step(  # 新人竞技场整体流程以方舟为起点，用恢复协议包裹。
            lambda: self._do_rookie_arena_flow(),  # 执行新人竞技场流程。
            name="新人竞技场",  # 步骤名用于日志与失败截图。
            raise_on_fail=False,  # 多次失败后跳过而非抛异常。
        )
        if not success:  # 流程多次失败。
            self.log_warning("新人竞技场流程多次失败，跳过。")  # 记录跳过原因。
            return  # 不标记完成，下次可重试。
        self.mark_done("rookie_arena", "day")  # 记录本周期已完成。
        self.log_info("新人竞技场任务完成。")  # 记录子流程完成。

    def _do_special_arena(self):  # 特殊竞技场子流程：竞技场→特殊竞技场→领取累计奖励→返回方舟。
        if not self.config.get("特殊竞技场"):  # 用户未启用特殊竞技场子流程。
            self.log_info("特殊竞技场未开启，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        if self.is_done("special_arena", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日特殊竞技场已完成，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        success = self.try_step(  # 特殊竞技场整体流程以方舟为起点，用恢复协议包裹。
            lambda: self._do_special_arena_flow(),  # 执行特殊竞技场流程。
            name="特殊竞技场",  # 步骤名用于日志与失败截图。
            raise_on_fail=False,  # 多次失败后跳过而非抛异常。
        )
        if not success:  # 流程多次失败。
            self.log_warning("特殊竞技场流程多次失败，跳过。")  # 记录跳过原因。
            return  # 不标记完成，下次可重试。
        self.mark_done("special_arena", "day")  # 记录本周期已完成。
        self.log_info("特殊竞技场任务完成。")  # 记录子流程完成。

    def _nav_to_arena(self):  # 导航到竞技场界面：先就位方舟，再点击竞技场入口（供竞技场子流程复用）。
        self._nav_to_ark()  # 确保处于方舟界面（过场动画容忍与恢复/冷启动分流均在 ensure_screen 内）。
        self.transition("arena", click_feature="ark_pvp", wait_confirm=10, after_sleep=3)  # 点击竞技场入口并确认已进入竞技场界面。

    def _do_rookie_arena_flow(self):  # 新人竞技场整体流程：竞技场→新人竞技场→循环免费挑战→逐级返回方舟。
        self._nav_to_arena()  # 确保处于竞技场界面（正常已就位；失败恢复回大厅后由此重新进入）。
        self.transition("rookie_arena", click_feature="rookie_arena", wait_confirm=10, after_sleep=3)  # 点击新人竞技场入口并确认已进入新人竞技场界面。
        while True:  # 循环使用免费挑战次数（每天5次），直到免费挑战不可用或刷新对手用尽。
            try:  # box_ 前缀特征为纯坐标区域，无模板可匹配，直接按标注坐标取区域。
                encounter = self.get_box_by_name("box_rookie_arena_o1_free_encounter")  # 以1号对手免费挑战区域判断免费次数是否还有剩余。
            except ValueError:  # 特征缺失。
                encounter = None  # 视为免费次数已用尽。
            if encounter is None or not self.is_feature_enabled(encounter):  # 特征缺失或灰白禁用态说明免费次数已用尽。
                self.log_info("新人竞技场免费挑战次数已用尽。")  # 记录结束原因。
                break  # 结束循环。
            target = self._rookie_arena_pick_opponent()  # 按对手选择策略确定要挑战的对手免费挑战区域名。
            if target is None:  # 刷新用尽仍未找到战力压制对手。
                break  # 结束循环（标记完成由调用方统一处理）。
            self._rookie_arena_fight(target)  # 挑战所选对手并等待战斗结束，回到新人竞技场界面。
        self._back_to_ark_via_arena()  # 逐级返回到方舟界面。

    def _rookie_arena_pick_opponent(self):  # 按配置选择对手：策略关闭固定选最下面；开启时选稳定战力压制对手，否则刷新对手列表（最多10次）。
        if not self.config.get("对手选择策略"):  # 对手选择策略已关闭。
            self.log_info("对手选择策略已关闭，固定挑战最下面的对手。")  # 记录选择方式。
            return "box_rookie_arena_o3_free_encounter"  # 固定返回3号（最下面）对手。
        refresh_count = 0  # 刷新对手列表次数统计。
        while True:  # 循环读取战力并判断是否存在可稳定压制的对手。
            player = self._rookie_arena_read_cp("box_rookie_arena_player_cp")  # OCR 读取己方战力。
            if player is None:  # 己方战力读取失败无法比较。
                self.log_warning("己方战力读取失败，回退固定挑战最下面的对手。")  # 记录回退原因。
                return "box_rookie_arena_o3_free_encounter"  # 保守回退固定最下面对手。
            threshold = player * _ROOKIE_ARENA_CP_RATIO  # 稳定战力压制阈值：己方战力 * 0.846。
            for cp_name, encounter_name in _ROOKIE_CP_ENCOUNTER_PAIRS:  # 自上而下检查 1-3 号对手。
                opponent = self._rookie_arena_read_cp(cp_name)  # OCR 读取该对手战力。
                if opponent is not None and threshold > opponent:  # 找到可稳定压制的对手。
                    self.log_info(f"选择对手{encounter_name[-5]}：己方 {player} * 0.846 = {threshold:.0f} > 对手 {opponent}。")  # 记录选择依据。
                    return encounter_name  # 返回该对手的免费挑战区域名。
            if refresh_count >= _ROOKIE_ARENA_MAX_REFRESH:  # 刷新次数已达上限。
                self.log_warning(f"刷新 {refresh_count} 次仍未找到战力压制对手，结束新人竞技场。")  # 记录结束原因。
                return None  # 结束子流程。
            self.wait_click_feature("rookie_arena_refresh", raise_if_not_found=True, after_sleep=3)  # 点击刷新对手列表并等待刷新完成。
            refresh_count += 1  # 刷新次数加一。
            self.log_info(f"未找到战力压制对手，刷新对手（第 {refresh_count} 次）。")  # 记录刷新。

    def _rookie_arena_read_cp(self, feature_name):  # 在指定战力标注区域内 OCR 读数，失败返回 None。
        try:  # 区域特征可能缺失。
            box = self.get_box_by_name(feature_name)  # 获取战力标注区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失。
            return None  # 读取失败。
        if box is None:  # 区域无效（如无可用帧）。
            return None  # 读取失败。
        texts = self.ocr(box=box)  # 区域内 OCR 获取全部文本框。
        if not texts:  # 无识别结果。
            return None  # 读取失败。
        digits = re.sub(r"\D", "", texts[-1].name or "")  # 取最后一段文字并去除非数字字符。
        return int(digits) if digits else None  # 有数字返回数值，否则视为读取失败。

    def _rookie_arena_fight(self, encounter_feature):  # 挑战所选对手：确认弹窗→快速战斗开关→进入战斗→等待结算→回到新人竞技场界面。
        self.click_box(encounter_feature, raise_if_not_found=True, after_sleep=2)  # 点击对手的免费挑战区域进确认弹窗（box_ 前缀为纯坐标区域，按坐标点击）。
        self.wait_feature("rookie_arena_battle_modal", raise_if_not_found=True)  # 等待确认战斗弹窗出现。
        try:  # 快速战斗开关区域特征可能缺失。
            quick_toggle = self.get_box_by_name("box_rookie_arena_quick_battle_feature")  # 获取快速战斗开关标注区域（纯坐标区域）。
        except ValueError:  # 特征缺失。
            quick_toggle = None  # 置空做兜底处理。
        if quick_toggle is not None and not self.is_feature_enabled(quick_toggle):  # 开关为灰白未激活态时先点击激活快速战斗。
            self.click_box(quick_toggle, after_sleep=1)  # 点击开关激活快速战斗。
        self.click_box("box_rookie_arena_quick_battle", raise_if_not_found=True, after_sleep=10)  # 点击进入战斗并等待战斗加载。
        result, confirm_box = self.wait_battle_finish(time_out=240)  # 节流等待战斗结束，只检测不点击。
        if result is None:  # 等待战斗结束超时。
            raise WaitFailedException("等待新人竞技场战斗结束超时")  # 抛异常由 try_step 恢复重试。
        self.click_box(confirm_box, after_sleep=3)  # 点击结算确认/失败返回按钮回到新人竞技场界面。
        self.assert_screen("rookie_arena", time_out=15)  # 确认回到新人竞技场界面，供下一轮循环判定。

    def _do_special_arena_flow(self):  # 特殊竞技场整体流程：竞技场→特殊竞技场→领取累计奖励→逐级返回方舟。
        self._nav_to_arena()  # 确保处于竞技场界面（正常已就位；失败恢复回大厅后由此重新进入）。
        self.transition("special_arena", click_feature="special_arena", wait_confirm=10, after_sleep=3)  # 点击特殊竞技场入口并确认已进入特殊竞技场界面。
        self.click_box("box_special_arena_reward", raise_if_not_found=True, after_sleep=2)  # 点击累计奖励区域打开奖励弹窗（box_ 前缀特征为纯坐标区域）。
        self.wait_click_feature("special_arena_reward_claim", raise_if_not_found=True, after_sleep=2)  # 点击领取按钮收取累计奖励。
        self.dismiss_all_popups(wait_for_popup=False, time_out=10)  # 清理领取后弹出的奖励遮罩弹窗。
        self._back_to_ark_via_arena()  # 逐级返回到方舟界面。

    def _back_to_ark_via_arena(self):  # 逐级返回：竞技场子页面→竞技场界面→方舟界面。
        self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 点击返回按钮回到竞技场界面。
        self.assert_screen("arena", time_out=10)  # 断言已回到竞技场界面。
        self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 点击返回按钮回到方舟界面。
        self.assert_screen("ark", time_out=10)  # 断言已回到方舟界面。

    def _under_daily(self):  # 判断当前是否由日常任务编排执行（日常里统一在全部子任务完成后提醒）。
        executor = getattr(og, "executor", None)  # 读取全局执行器。
        return executor is not None and executor.current_task is not None and executor.current_task is not self  # 当前执行者是其他编排任务时返回 True。

    def failed_towers_message(self):  # 构造战斗失败塔的提醒文本，无失败记录返回 None。
        if not self.failed_towers:  # 无失败记录。
            return None  # 无需提醒。
        unique = []  # 去重后的失败塔号列表。
        for i in self.failed_towers:  # 遍历记录（失败重试可能重复记录）。
            if i not in unique:  # 未记录过才加入。
                unique.append(i)  # 加入去重列表。
        names = "、".join(_TOWER_NAMES.get(i, f"{i}号塔") for i in unique)  # 拼接失败塔的企业名。
        return f"今日企业塔战斗失败：{names}，请手动处理。"  # 返回提醒文本。

    def notify_failed_towers(self):  # 系统通知提醒战斗失败的塔（供单独运行与日常编排共用）。
        message = self.failed_towers_message()  # 构造提醒文本。
        if message:  # 有失败记录才提醒。
            self.log_info(message, notify=True)  # 发送系统通知。
