
from ok.task.exceptions import WaitFailedException  # 导入等待失败异常，流程断言失败时抛出由 try_step 捕获恢复。

from src.tasks.NikkeBaseTask import NikkeBaseTask  # 导入项目基类，所有任务统一继承它。


class RaidTask(NikkeBaseTask):  # 定义讨伐任务类，包含协同作战与个人突袭两个子流程。

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

    # ---- 协同作战 helpers ----

    def _get_panel_box(self):  # 获取大厅左侧面板区域框，供灰度识别 coop 入口使用。
        try:  # 尝试读取 coco 标注区域。
            box = self.get_box_by_name("box_lobby_left_side_panel")  # 获取左侧面板标注区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失时抛 ValueError。
            box = None  # 置空由调用方统一判断。
        if box is None:  # 区域不可用。
            raise WaitFailedException("缺少区域特征: box_lobby_left_side_panel")  # 抛异常由 try_step 捕获恢复。
        return box  # 返回面板区域框。

    def _find_panel_entry(self, name, panel):  # 在左侧面板内灰度识别指定入口（coop/solo_raid），命中返回 Box 否则 None。
        return self.find_one(name, box=panel, use_gray_scale=True)  # 在面板区域内灰度匹配目标入口（灰度可弱化颜色干扰）。

    def _is_coop_finished(self):  # 判断协同作战次数是否已用尽（OCR 识别 0/3）。
        try:  # 先判断协同作战功能入口是否可用（灰白禁用视为已完成）。
            feature_box = self.get_box_by_name("box_coop_feature")  # 获取协同作战功能区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失。
            feature_box = None  # 置空由后续 OCR 逻辑兜底。
        if feature_box is not None:  # 区域有效时才做可用性判断。
            try:  # is_feature_enabled 内部访问 frame，执行器已退出时会抛 SystemExit。
                if not self.is_feature_enabled(feature_box):  # 功能入口为灰白禁用态说明次数用尽或未开放。
                    return True  # 视为已完成。
            except SystemExit:  # 执行器已退出（单测 teardown 后访问 frame 会直接 sys.exit）。
                pass  # 保守视为可用，交由后续 OCR 兜底。
            except Exception:  # 其他颜色检测异常同样保守处理。
                pass  # 交由后续 OCR 兜底。
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
        def find_coop_entry():  # B 在 box_lobby_left_side_panel 识别 coop 入口（ensure_screen 进入大厅之后才解析）。
            panel = self._get_panel_box()  # 获取左侧面板区域。
            coop_box = self._find_panel_entry("coop", panel)  # 使用灰度识别。
            if coop_box is None:  # 未找到协同作战入口。
                self.log_info("未找到协同作战入口，视为已完成。")  # 记录跳过原因。
            return coop_box  # 返回入口框或 None。

        # A 幂等就位协同作战页：已在页面直接返回；否则分流恢复/冷启动后从大厅点入口。
        if not self.ensure_screen("coop_page", entry=find_coop_entry, wait_confirm=10, after_sleep=1):  # 入口缺失视为已完成，直接返回（由调用方标记完成）。
            return
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
            self.transition("coop_nikke_select_page", click_feature="coop_accpet", time_out=60, wait_confirm=10, after_sleep=1)  # I 等待识别 coop_accpet 并点击接受匹配，确认进入 NIKKE 选择界面。
            self.sleep(3)  # J 等待 3 秒（界面动画稳定）。
            self.click_box("box_coop_ready", after_sleep=1)  # K 点击 box_coop_ready 准备就绪。
            result, confirm_box = self.wait_battle_finish(time_out=240)  # L 等待战斗结束 wait_battle_finish（节流轮询，只检测不点击）。
            if result is None:  # 超时未检测到结算界面。
                raise WaitFailedException("等待协同作战战斗结束超时")  # 抛异常由 try_step 恢复。
            if confirm_box is not None:  # 命中结算确认框。
                self.click_box(confirm_box, after_sleep=1)  # M 点击胜利结算的 box_battle_finish_text 区域（或失败返回框）返回协同作战页。
            else:  # 兜底：未返回确认框。
                self.click_box("box_battle_finish_text", after_sleep=1)  # 兜底点击胜利结算确认区域。
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

    # ---- 个人突袭 ----

    def _is_solo_raid_option_enabled(self, box_name):  # 判断个人突袭出战方式按钮是否可用（高亮彩色），区域缺失一律视为禁用。
        try:  # 区域特征可能缺失。
            box = self.get_box_by_name(box_name)  # 获取按钮标注区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失。
            return False  # 无法判定时视为禁用，避免误点不可用按钮。
        if box is None:  # 区域无效。
            return False  # 同样视为禁用。
        return self.is_feature_enabled(box, after_sleep=2)  # 用色彩丰富度区分可用（彩色）与禁用（灰白）状态。

    def _do_solo_raid_battle(self):  # 个人突袭普通出战分支：F→N 从点击出战到结算返回首页（由主流程 try_step 包裹）。
        self.click_box("box_solo_raid_battle_feature", after_sleep=1)  # F 点击出战按钮，弹出出战确认弹窗。
        self.transition("solo_raid_battle_team_select_page", click_feature="solo_raid_battle_confirm", time_out=10, wait_confirm=10, after_sleep=1)  # G 等待识别出战确认弹窗并点击，断言已进入队伍选择界面。
        self.click_box("box_solo_raid_battle_start", after_sleep=1)  # I 点击开始战斗。
        result, confirm_box = self.wait_battle_finish(time_out=240)  # J 节流轮询等待自动战斗结束（只检测不点击）。
        if result is None:  # 超时未检测到结算界面。
            raise WaitFailedException("等待个人突袭战斗结束超时")  # 抛异常由 try_step 捕获恢复。
        if confirm_box is not None:  # 命中结算确认框。
            self.click_box(confirm_box, after_sleep=1)  # M 点击战斗结束后的 box_battle_finish_text 区域（或失败返回框）。
        else:  # 兜底：未返回确认框。
            self.click_box("box_battle_finish_text", after_sleep=1)  # 兜底点击胜利结算确认区域。
        self.wait_feature("solo_raid_battle_finish", time_out=15, raise_if_not_found=True)  # R 等待识别战斗结果页出现。
        self.transition("solo_raid_page", click_feature="solo_raid_battle_finish_confirm", time_out=10, wait_confirm=10, after_sleep=1)  # N 识别并点击结果确认，确认回到个人突袭首页。

    def _do_solo_raid_quick_battle(self):  # 个人突袭快速战斗分支：K→P 扫荡剩余次数并确认即时结算（由主流程 try_step 包裹）。
        self.click_box("box_solo_raid_quick_battle_feature", after_sleep=1)  # 点击快速战斗按钮
        self.wait_feature("solo_raid_quick_battle_page", time_out=10, raise_if_not_found=True)  # S 识别快速战斗界面已出现。
        max_btn = self.find_one("solo_raid_quick_battle_max")  # L 识别次数拉满按钮是否存在。
        if max_btn is not None:  # L -- true 分支。
            self.click_box(max_btn, after_sleep=1)  # O 点击拉满剩余次数。
        self.click_box("box_solo_raid_quick_battle", after_sleep=1)  # Q 点击开始快速战斗（L -- false 时直接走到这里）。
        result, confirm_box = self.wait_battle_finish(time_out=10)  # P 节流轮询等待快速战斗结算画面（基类方法：含结算动画稳定化与中断哨兵，超时返回 (None, None)）。
        if confirm_box is None:  # 未识别到结算画面。
            raise WaitFailedException("未识别到个人突袭快速战斗结算画面")  # 抛异常由 try_step 捕获恢复。
        self.log_info(f"个人突袭快速战斗结束: {result}")  # 记录结算结果。
        self.click_box(confirm_box, after_sleep=1)  # 点击结算确认关闭结果画面。

    def _do_solo_raid_flow(self):  # 个人突袭主流程：从大厅出发，优先快速战斗扫荡，否则逐次普通出战直到全部不可用（re-entrant，由 try_step 包裹）。
        def find_solo_entry():  # B 在 box_lobby_left_side_panel 识别个人突袭入口（ensure_screen 进入大厅之后才解析）。
            panel = self._get_panel_box()  # 获取左侧面板区域。
            raid_box = self._find_panel_entry("solo_raid", panel)  # 使用灰度识别。
            if raid_box is None:  # 未找到个人突袭入口。
                self.log_info("未找到个人突袭入口，视为已完成。")  # 记录跳过原因。
            return raid_box  # 返回入口框或 None。

        # A 幂等就位个人突袭页：已在页面直接返回；否则分流恢复/冷启动后从大厅点入口。
        if not self.ensure_screen("solo_raid_page", entry=find_solo_entry, wait_confirm=10, after_sleep=1):  # 入口缺失视为已完成，直接返回（由调用方标记完成）。
            return
        rounds = 0  # 出战轮次保护计数，防止按钮状态误判导致死循环。
        while True:  # 循环直到没有可用的出战方式。
            rounds += 1  # 轮次加一。
            if rounds > 5:  # 超过安全上限仍未自然结束。
                self.log_warning("个人突袭出战轮次超过上限，停止。")  # 记录异常并停止，避免死循环。
                break  # 结束循环。
            if self._is_solo_raid_option_enabled("box_solo_raid_quick_battle_feature"):  # D 快速战斗按钮可用（高亮彩色）。
                self._do_solo_raid_quick_battle()  # K→S→L/O→Q→P 快速战斗一次扫荡全部剩余次数。
                break  # P --> END 快速战斗已覆盖全部次数，直接结束。
            if self._is_solo_raid_option_enabled("box_solo_raid_battle_feature"):  # E 普通出战按钮可用（高亮彩色）。
                self._do_solo_raid_battle()  # F→G→H→I→J→M→R→N 完整出战一轮。
                continue  # N --> C 回到首页重新判断剩余次数。
            self.log_info("个人突袭无可用出战方式，结束。")  # D/E 均 false：当日次数已用尽或功能未解锁。
            break  # E -- false --> END。
        # 循环结束，尝试返回大厅。
        try:  # 返回大厅容错。
            home = self.find_one("common_home")  # 查找大厅按钮。
            if home is not None:  # 找到大厅按钮。
                self.click_box(home, after_sleep=1)  # 点击大厅按钮返回大厅。
            self.wait_for_lobby(time_out=10, raise_if_not_found=False)  # 等待确认回到大厅，超时不抛异常。
        except Exception as e:  # 返回大厅异常不影响标记完成。
            self.log_warning(f"返回大厅失败: {e}")  # 记录异常。

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
        if not self.ensure_screen("lobby", raise_on_fail=False):  # 启动后就位游戏大厅（幂等闸门：含冷启动引导与弹窗清理），失败则中止。
            self.log_error("未能进入游戏大厅，中止讨伐任务。")  # 记录失败原因。
            return  # 结束本次执行。
        self._do_coop()  # 执行协同作战子流程。
        self._do_solo_raid()  # 执行个人突袭子流程。
        self.log_info("讨伐任务完成。")  # 记录任务完成。
