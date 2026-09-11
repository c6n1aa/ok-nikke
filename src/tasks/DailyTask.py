import re  # 任务页副标题关键字用正则（OCR 部分匹配，忽略大小写）。

from ok import og  # 导入框架全局对象。

from src.tasks.HarvestTask import HarvestTask  # 导入收获子任务。
from src.tasks.NikkeBaseTask import NikkeBaseTask  # 导入项目基类，所有任务统一继承它。
from src.tasks.OutpostDefenseTask import OutpostDefenseTask  # 导入歼灭子任务。
from src.tasks.OutpostTask import OutpostTask  # 导入前哨基地子任务（派遣/咨询）。
from src.tasks.ShopTask import ShopTask  # 导入商店子任务。
from src.tasks.CashShopTask import CashShopTask  # 导入付费商店子任务。
from src.tasks.RecruitTask import RecruitTask  # 导入招募子任务（友情点/折扣普通招募）。
from src.tasks.ArkTask import ArkTask  # 导入方舟子任务（企业塔/模拟室/拦截战/竞技场）。
from src.tasks.RaidTask import RaidTask  # 导入讨伐子任务（协同作战/个人突袭）。
from src.tasks.ExtrasTask import ExtrasTask  # 导入其他杂项子任务（PASS奖励收取）。


class DailyTask(NikkeBaseTask):  # 定义清日常总编排的父任务类。

    DAILY_SETTINGS_BUTTON_KEY = "点击前往日常任务设置"  # 任务列表卡片里跳转日常设置 tab 的按钮配置键。

    _MISSION_TABS = (  # 任务弹窗可切换的 tab：副标题关键字（OCR 部分匹配，忽略大小写）+ 徽章红点区域（coco 区域特征名），顺序即检查优先级。
        (re.compile(r"WEEKLY\s*MISSION", re.IGNORECASE), "box_mission_weekly_badge"),  # 周任务 tab。
        (re.compile(r"MAIN\s*MISSION", re.IGNORECASE), "box_mission_msq_badge"),  # 主线任务 tab。
        (re.compile(r"CHALLENGE", re.IGNORECASE), "box_mission_achievement_badge"),  # 成就（挑战）tab。
    )
    _CLAIM_MAX_CLICKS = 20  # 单个 tab 领取点击次数上限：点击未生效时防止死循环。
    _RED_DOT_TEMPLATE = 'assets/template/common/badge.png'  # 通知红点模板：模板匹配优先命中角标红点，减少徽章图标被颜色兜底误判为红点。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "日常"  # 任务显示名称。
        self.description = "按日常任务设置进行自动化操作。"  # 任务说明。
        self.default_config.update({  # 父任务配置：为每个子流程放一个常驻开关。
            "收获": True,  # 收获子流程的开关。
            "歼灭": True,  # 歼灭子流程的开关。
            "付费商店": True,  # 付费商店子流程的开关。
            "商店": True,  # 商店子流程的开关。
            "招募": True,  # 招募子流程的开关。
            "前哨基地": True,  # 前哨基地子流程的开关。
            "方舟": True,  # 方舟子流程的开关。
            "Raid": True,  # Raid子流程的开关。
            "其他杂项": True,  # 其他杂项子流程的开关。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "收获": "是否执行收获（友情点、邮箱）。",
            "歼灭": "是否执行前哨基地歼灭。",
            "付费商店": "是否执行付费商店免费礼包领取（STEP UP/每日/每周/每月）。",
            "商店": "是否执行商店购买（普通/竞技场/废铁）。",
            "招募": "是否执行招募（友情点/折扣普通招募）。",
            "前哨基地": "是否执行前哨基地（派遣/咨询）。",
            "方舟": "是否执行方舟（企业塔/模拟室/拦截战/竞技场）。",
            "Raid": "是否执行限时挑战活动（协同作战/个人突袭）。",
            "其他杂项": "是否执行其他杂项（PASS奖励收取）。",
        })
        self.config_type.update({  # 任务列表的日常卡片展开后只显示这一个按钮行。
            self.DAILY_SETTINGS_BUTTON_KEY: {
                "type": "button",  # 复用标准按钮配置行，样式与其他任务设置保持一致。
                "text": "前往日常设置",  # 按钮文字。
                "callback": self.open_daily_settings,  # 点击后跳转到日常设置 tab。
            },
        })

    def open_daily_settings(self):  # 按钮点击回调：切换到「日常设置」tab。
        from src.ui.DailyTab import DailyTab  # 延迟导入，避免与 DailyTab 模块互相循环导入。
        mw = getattr(og, 'main_window', None)  # 主窗口在 show_main_window 后才挂到 og 上。
        if mw is None:  # 主窗口未就绪时不处理。
            return
        for index in range(mw.stackedWidget.count()):  # 遍历主窗口的页面栈。
            tab = mw.stackedWidget.widget(index)  # 逐个取出页面。
            if isinstance(tab, DailyTab):  # 找到日常设置 tab 实例。
                mw.switchTo(tab)  # 切换到该 tab。
                return

    def _daily_end_flow(self):  # 收尾子流程入口：大厅 → 打开任务弹窗 → 循环领取 → 无红点后关闭。
        self.ensure_screen("lobby")  # 幂等就位大厅（收尾在全部子任务之后执行，兜底处理子任务遗留的界面/弹窗）。
        self.wait_click_feature("mission", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击任务入口打开任务弹窗。
        self.wait_feature("mission_page", time_out=10, raise_if_not_found=True)  # 确认任务弹窗稳定打开（弹窗属临时弹层，不注册为界面）。
        self._claim_box_missions()  # 领取任务弹窗内全部可领奖励（当前 tab + 红点 tab）。
        self.wait_feature("mission_page", time_out=10, raise_if_not_found=True)  # 确认遮罩已清、任务弹窗重新出现后再关闭。
        self.wait_click_feature("mission_page_close", time_out=10, raise_if_not_found=True, after_sleep=1)  # 关闭任务弹窗结束收尾。

    def _claim_box_missions(self):  # 任务弹窗领取编排：先领当前 tab，再按徽章红点逐个切 tab 领取。
        claim_box = self.get_box_by_name("box_mission_claim")  # 领取按钮区域（box_ 前缀纯坐标区域，已按当前分辨率缩放）。
        self._claim_current_tab(claim_box)  # 打开弹窗默认停留的 tab 先领到变灰。
        visited = set()  # 已切换过的徽章区域名：红点未及时消失时防止反复切换，保证收尾必然终止。
        while self._switch_to_tab_with_red_dot(visited):  # 还有带红点的未访问 tab 就切换过去。
            self.dismiss_all_popups(wait_for_popup=False, time_out=5)  # 切 tab 本身不弹遮罩，仅在必要时快速清理残留弹窗。
            self._claim_current_tab(claim_box)  # 领取刚切换到的 tab，领到变灰。

    def _claim_current_tab(self, claim_box):  # 领取当前 tab 全部可领奖励：领取按钮可用（彩色）就点，直到变灰。
        for _ in range(self._CLAIM_MAX_CLICKS):  # 次数上限保护：点击未生效时不再无限循环。
            if not self.is_feature_enabled(claim_box):  # 领取按钮灰白禁用 = 当前 tab 已无可领奖励。
                return  # 本 tab 领取完成。
            self.click_box(claim_box, after_sleep=1)  # 点击领取按钮。
            # 领取后可能弹奖励遮罩盖住任务弹窗（每日/每周的第二段 + 主线/成就的一段式）：有关就关、没关不白等，
            # 以「任务弹窗重新出现」为准进入下一轮判定，避免读到遮罩帧误判。
            if not self.dismiss_all_popups(clear_condition=lambda: self.find_one("mission_page") is not None, time_out=10):
                self.log_warning("领取后任务弹窗未重新出现，停止本轮领取。")  # 遮罩关不掉或弹窗被卡住，交由上层收尾兜底。
                return  # 停止本轮，避免在遮罩帧上空转 20 次。
        self.log_warning("任务领取点击达到上限，停止本轮领取。")  # 上限耗尽仍未收敛，记录异常。

    def _switch_to_tab_with_red_dot(self, visited):  # 在三个徽章区域找红点，命中则点击切换并确认副标题，返回是否发生了切换。
        for keyword, badge in self._MISSION_TABS:  # 依次检查三个 tab 的徽章红点。
            if badge in visited:  # 已访问过的 tab 不再进入，防止红点残留导致反复切换。
                continue
            red_dot = self.find_red_dot(badge, template_path=self._RED_DOT_TEMPLATE)  # 在徽章区域检测通知红点（模板匹配优先，减少徽章图标被颜色兜底误判）。
            if red_dot is None:  # 无红点说明该 tab 无待领内容。
                continue
            self.click_box(red_dot, after_sleep=1)  # 点击红点所在徽章，切换到对应 tab。
            visited.add(badge)  # 记录该 tab 已访问。
            if not self.wait_ocr(match=keyword, box=self.get_box_by_name("box_mission_subtitle"), time_out=5, raise_if_not_found=False):  # 确认副标题已切到目标 tab。
                self.log_warning(f"切换 {badge} 后副标题未确认，跳过该 tab。")  # 点击未生效（红点误报等）时记录并继续，避免中断整个收尾流程。
                continue  # 跳到下一个徽章，不因单个 tab 切换失败中止领取。
            return True  # 已切换到新 tab 并确认副标题。
        return False  # 三个徽章均无未访问的红点，领取收尾完成。

    def run(self):  # 父任务执行入口，按顺序编排子流程。
        self.log_info("日常开始。")  # 记录父任务开始。
        if not self.ensure_screen("lobby", raise_on_fail=False):  # 启动后就位游戏大厅（幂等闸门：含冷启动引导与弹窗清理），失败则中止后续任务。
            self.log_error("未能进入游戏大厅，中止日常任务。")  # 记录失败原因。
            return  # 结束本次执行，不执行子流程。
        if self.config.get("收获"):  # 只有开关开启时才执行收获。
            self.run_task_by_class(HarvestTask)  # 运行收获子任务，子任务读取自己的配置。
        if self.config.get("歼灭"):  # 只有开关开启时才执行歼灭。
            self.run_task_by_class(OutpostDefenseTask)  # 运行歼灭子任务，子任务读取自己的配置。
        if self.config.get("付费商店"):  # 只有开关开启时才执行付费商店。
            self.run_task_by_class(CashShopTask)  # 运行付费商店子任务，子任务读取自己的配置。
        if self.config.get("商店"):  # 只有开关开启时才执行商店。
            self.run_task_by_class(ShopTask)  # 运行商店子任务，子任务读取自己的配置。
        if self.config.get("招募"):  # 只有开关开启时才执行招募。
            self.run_task_by_class(RecruitTask)  # 运行招募子任务，子任务读取自己的配置。
        if self.config.get("前哨基地"):  # 只有开关开启时才执行前哨基地。
            self.run_task_by_class(OutpostTask)  # 运行前哨基地子任务（派遣/咨询），子任务读取自己的配置。
        if self.config.get("方舟"):  # 只有开关开启时才执行方舟。
            self.run_task_by_class(ArkTask)  # 运行方舟子任务，子任务读取自己的配置。
        if self.config.get("Raid"):  # 只有开关开启时才执行讨伐。
            self.run_task_by_class(RaidTask)  # 运行讨伐子任务，子任务读取自己的配置。
        if self.config.get("其他杂项"):  # 只有开关开启时才执行其他杂项。
            self.run_task_by_class(ExtrasTask)  # 运行其他杂项子任务（PASS奖励收取），子任务读取自己的配置。
        # 后续新增子流程时，在此追加相同的开关判断和 run_task_by_class 调用即可。
        if self.config.get("方舟"):  # 只有开启方舟子流程才需要检查失败塔提醒。
            ark = self.get_task_by_class(ArkTask)  # 获取方舟子任务实例。
            if ark is not None:  # 子任务已注册。
                message = ark.failed_towers_message()  # 读取本次运行的战斗失败塔记录。
                if message:  # 存在战斗失败的塔。
                    self.log_info(message, notify=True)  # 在所有日常子任务执行完成后统一提醒。
        if not self.try_step(self._daily_end_flow, name="日常收尾", raise_on_fail=False):  # 收尾流程失败不回滚已完成的子任务，恢复重试耗尽后记录并跳过。
            self.log_warning("日常收尾流程失败，已跳过。")  # 记录收尾结果，便于排查。
        self.log_info("日常完成。", notify=True)  # 记录父任务执行完成，并发送系统托盘通知提示用户。
