
from ok.task.exceptions import WaitFailedException  # 导入等待失败异常，流程断言失败时抛出由 try_step 捕获恢复。

from src.tasks.MyBaseTask import MyBaseTask  # 导入项目基类，所有任务统一继承它。


class RaidTask(MyBaseTask):  # 定义讨伐任务类，包含协同作战与个人突袭两个子流程。

    done_keys = {"coop": "day", "solo_raid": "day"}  # 完成状态：协同作战与个人突袭均为日常刷新。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "Raid"  # 任务显示名称。
        self.description = "执行限时挑战（协同作战/个人突袭）任务"  # 任务说明。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "协同作战": True,  # 是否自动匹配协同作战-普通。
            "个人突袭": True,  # 是否自动执行个人突襲任务。
        })  # 结束默认配置更新。
        self.config_description.update({  # 每个配置项的帮助文本。
            "协同作战": "自动匹配协同作战-普通难度",  # 协同作战开关说明。
            "个人突袭": "自动执行个人突袭任务",  # 个人突袭开关说明。
        })  # 结束帮助文本更新。
        # 界面注册：协同作战首页以 coop_page 特征判定（文档写 solo_raid_page，实测应为 coop_page）；NIKKE 选择页以 coop_nikke_select_page 判定。
        self.register_screen("coop_page", features=["coop_page"])  # 注册协同作战首页，已按当前分辨率缩放的 coco 特征判定。
        self.register_screen("coop_nikke_select_page", features=["coop_nikke_select_page"])  # 注册协同作战 NIKKE 选择界面。

    # ---- 协同作战 helpers ----

    def _get_panel_box(self):  # 获取大厅左侧面板区域框，供灰度识别 coop 入口使用。
        try:  # 尝试读取 coco 标注区域。
            box = self.get_box_by_name("box_lobby_left_side_panel")  # 获取左侧面板标注区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失时抛 ValueError。
            box = None  # 置空由调用方统一判断。
        if box is None:  # 区域不可用。
            raise WaitFailedException("缺少区域特征: box_lobby_left_side_panel")  # 抛异常由 try_step 捕获恢复。
        return box  # 返回面板区域框。

    def _find_coop_entry(self, panel):  # 在左侧面板内灰度识别协同作战入口，命中返回 Box 否则 None。
        return self.find_one("coop", box=panel, use_gray_scale=True)  # 在面板区域内灰度匹配 coop 入口（灰度可弱化颜色干扰）。

    def _is_coop_finished(self):  # 判断协同作战次数是否已用尽（OCR 识别 0/3）。
        try:  # 区域特征可能缺失。
            count_box = self.get_box_by_name("box_coop_count")  # 获取次数标注区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失。
            return False  # 视为未完成，避免误判完成。
        if count_box is None:  # 区域无效。
            return False  # 视为未完成。
        ocr_boxes = self.ocr(box=count_box)  # 对次数区域做 OCR，获取全部文本框。
        if not ocr_boxes:  # 无识别结果。
            return False  # 视为未完成。
        last_text = (ocr_boxes[-1].name or "").strip()  # 取最后一段文字（通常为 x/3 形式）。
        if "0/3" in last_text:  # 最后文字包含 0/3 视为次数已用尽。
            return True  # 已完成。
        # 兜底：任一 OCR 结果包含 0/3 也算完成（兼容 OCR 切分差异）。
        for b in ocr_boxes:  # 遍历全部 OCR 框。
            if "0/3" in (b.name or ""):  # 命中 0/3。
                return True  # 已完成。
        return False  # 未识别到 0/3，视为未完成。

    def _do_coop_flow(self):  # 协同作战主流程：从大厅出发，循环匹配普通难度直到次数用尽（re-entrant，由 try_step 包裹）。
        # A 识别当前在大厅：若已在协同作战页则无需再从大厅进入；否则确保在大厅。
        if not self.is_screen("coop_page"):  # 当前不在协同作战页。
            if not self.wait_until_lobby_after_start(time_out=30):  # 确保进入游戏大厅（处理公告弹窗与 TOUCH TO CONTINUE）。
                raise WaitFailedException("未能进入游戏大厅")  # 抛异常由 try_step 恢复重试。
            self.dismiss_all_popups(wait_for_popup=False, time_out=10)  # 统一清理大厅残留弹窗，无弹窗立即返回。
            panel = self._get_panel_box()  # 获取左侧面板区域。
            coop_box = self._find_coop_entry(panel)  # B 在 box_lobby_left_side_panel 识别 coop 使用灰度识别。
            if coop_box is None:  # B -- false 分支：未找到协同作战入口。
                self.log_info("未找到协同作战入口，视为已完成。")  # 记录跳过原因。
                return  # 直接返回，由调用方标记完成。
            self.click_box(coop_box, after_sleep=1)  # 点击协同作战入口进入协同作战页面。
            self.assert_screen("coop_page")  # C 识别 coop_page 判别当前处在协同作战页面。
        # 已确保在协同作战页面，开始循环处理次数。
        while True:  # 循环直到次数用尽。
            # D 在 box_coop_count 区域进行 OCR 识别 最后的文字是否为 0/3。
            if self._is_coop_finished():  # D -- true 分支：次数已用尽。
                self.log_info("协同作战次数已用尽（0/3），结束。")  # 记录次数用尽。
                break  # 结束循环。
            # D -- false 分支：次数未用尽，继续匹配。
            try:  # 次数区域可能缺失。
                count_box = self.get_box_by_name("box_coop_count")  # 获取次数区域用于点击。
            except ValueError:  # 特征缺失。
                raise WaitFailedException("缺少区域特征: box_coop_count")  # 抛异常恢复。
            self.click_box(count_box, after_sleep=1)  # E 点击 box_coop_count 区域打开匹配弹窗。
            self.wait_feature("coop_match_page", time_out=10, raise_if_not_found=True)  # F 识别 coop_match_page 确认匹配弹窗已出现。
            self.click_box("box_coop_normal", after_sleep=1)  # G 点击 box_coop_normal（文档写 box_normal，实际为 box_coop_normal）选择普通难度。
            self.click_box("box_coop_confirm", after_sleep=1)  # H 点击 box_coop_confirm 确认匹配。
            self.wait_click_feature("coop_accpet", time_out=60, raise_if_not_found=True, after_sleep=1)  # I 等待识别 coop_accpet 并点击接受匹配。
            self.assert_screen("coop_nikke_select_page")  # J 识别 coop_nikke_select_page 确认当前处于 NIKKE 选择界面。
            self.sleep(3)  # J 等待 3 秒（界面动画稳定）。
            self.click_box("box_coop_ready", after_sleep=1)  # K 点击 box_coop_ready 准备就绪。
            result, confirm_box = self.wait_battle_finish(time_out=240, check_interval=2)  # L 等待战斗结束 wait_battle_finish（节流轮询，只检测不点击）。
            if result is None:  # 超时未检测到结算界面。
                raise WaitFailedException("等待协同作战战斗结束超时")  # 抛异常由 try_step 恢复。
            if confirm_box is not None:  # 命中结算确认框。
                self.click_box(confirm_box, after_sleep=1)  # M 点击 battle_finish_esc（或失败返回框）返回协同作战页。
            else:  # 兜底：未返回确认框。
                self.wait_click_feature("battle_finish_esc", time_out=10, raise_if_not_found=True, after_sleep=1)  # 兜底点击胜利确认。
            self.assert_screen("coop_page")  # 循环回到 C：确认已回到协同作战页面。
        # 循环结束，尝试返回大厅。
        try:  # 返回大厅容错。
            home = self.find_one("common_home")  # 查找大厅按钮。
            if home is not None:  # 找到大厅按钮。
                self.click_box(home, after_sleep=1)  # 点击大厅按钮返回大厅。
            self.wait_for_lobby(time_out=10, raise_if_not_found=False)  # 等待确认回到大厅，超时不抛异常。
        except Exception as e:  # 返回大厅异常不影响标记完成。
            self.log_warning(f"返回大厅失败: {e}")  # 记录异常。

    def _do_coop(self):  # 协同作战子流程：开关与完成状态检查后以恢复协议执行主流程。
        if not self.config.get("协同作战"):  # 用户未启用协同作战。
            self.log_info("协同作战未开启，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        if self.is_done("coop", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日协同作战已完成，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        success = self.try_step(  # 协同作战整体流程以大厅为起点，用恢复协议包裹。
            lambda: self._do_coop_flow(),  # 执行协同作战主流程。
            name="协同作战",  # 步骤名用于日志与失败截图。
            raise_on_fail=False,  # 多次失败后跳过而非抛异常。
        )  # 结束 try_step 调用。
        if not success:  # 流程多次失败。
            self.log_warning("协同作战流程多次失败，跳过。")  # 记录跳过原因。
            return  # 不标记完成，下次可重试。
        self.mark_done("coop", "day")  # 记录本周期已完成。
        self.log_info("协同作战任务完成。")  # 记录子流程完成。

    # ---- 个人突袭（占位，后续补充） ----

    def _do_solo_raid_flow(self):  # 个人突袭主流程占位：后续补充具体实现，当前仅日志占位。
        self.log_info("个人突袭流程暂未实现，跳过。")  # 记录占位跳过。
        # 后续在此补充：进入个人突袭页 → 关卡选择 → 战斗 → 结算等流程。
        return  # 结束占位流程。

    def _do_solo_raid(self):  # 个人突袭子流程：开关与完成状态检查后以恢复协议执行主流程。
        if not self.config.get("个人突袭"):  # 用户未启用个人突袭。
            self.log_info("个人突袭未开启，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        if self.is_done("solo_raid", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日个人突袭已完成，跳过。")  # 记录跳过原因。
            return  # 结束本子流程。
        success = self.try_step(  # 个人突袭整体流程用恢复协议包裹。
            lambda: self._do_solo_raid_flow(),  # 执行个人突袭主流程。
            name="个人突袭",  # 步骤名用于日志与失败截图。
            raise_on_fail=False,  # 多次失败后跳过而非抛异常。
        )  # 结束 try_step 调用。
        if not success:  # 流程多次失败。
            self.log_warning("个人突袭流程多次失败，跳过。")  # 记录跳过原因。
            return  # 不标记完成，下次可重试。
        self.mark_done("solo_raid", "day")  # 记录本周期已完成。
        self.log_info("个人突袭任务完成。")  # 记录子流程完成。

    def run(self):  # 任务执行入口：统一进入大厅后依次执行协同作战与个人突襲。
        self.log_info("讨伐任务开始。")  # 记录任务开始。
        if not self.wait_until_lobby_after_start():  # 启动后等待进入游戏大厅，失败则中止。
            self.log_error("未能进入游戏大厅，中止讨伐任务。")  # 记录失败原因。
            return  # 结束本次执行。
        self._do_coop()  # 执行协同作战子流程。
        self._do_solo_raid()  # 执行个人突袭子流程。
        self.log_info("讨伐任务完成。")  # 记录任务完成。
