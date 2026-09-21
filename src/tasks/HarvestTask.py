import re  # OCR 关键词统一编译为正则（部分匹配 + 忽略大小写）。

from ok.task.exceptions import WaitFailedException  # 等待失败异常，交给 try_step 恢复回大厅重试。
from src.tasks.NikkeBaseTask import NikkeBaseTask  # 导入项目基类，所有任务统一继承它。


class HarvestTask(NikkeBaseTask):  # 定义收获子任务类：收取友情点、邮箱与 PASS（活动/任务通行证）奖励。

    done_keys = {"harvest": "day", "pass": "day"}  # 完成状态：收获、PASS（日常刷新）。

    _RED_DOT_TEMPLATE = 'assets/template/common/badge.png'  # 通知红点模板：与任务弹窗共用，模板匹配优先命中角标红点。
    _PASS_ENTRY_FEATURES = ("pass_switch", "pass_selector")  # 大厅 PASS 入口的两种形态：任一存在即代表多个 PASS 可切换。
    _PASS_SWIPE_LIMIT = 8  # 多个 PASS 翻页查找红点的总次数上限，超过也标记完成。
    _PASS_FLICK_STEPS = 20  # 加速度翻页的插值步数（每步停顿 10ms，总拖拽约 0.2 秒）。
    _PASS_FLICK_STEP_SLEEP = 0.01  # 每步插值停顿秒数。
    # 面板存在判据：面板左上徽章在灰度/高亮态之间切换、关闭 X 位置随皮肤漂移，模板逐期失效
    # （实测徽章灰度匹配 0.648 < 阈值 0.8），改用不随皮肤变的页签文字（OCR）。
    _PASS_TAB_PATTERNS = (re.compile("奖励", re.IGNORECASE), re.compile("任务", re.IGNORECASE))  # 面板两个页签的文字，命中任一即面板已打开。
    _PASS_TAB_OCR_BOX = (0.25, 0.20, 0.75, 0.44)  # 页签行所在的屏幕区域（相对比例，按当前分辨率缩放）；大厅同区域无文字。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "收获"  # 任务显示名称。
        self.description = "收取友情点、邮箱与PASS奖励。"  # 任务说明。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "收获友情点": True,  # 是否收取友情点。
            "收取邮箱": True,  # 是否收取邮箱奖励。
            "PASS": True,  # 是否收取 PASS 奖励。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "收获友情点": "是否点击好友送礼并收取友情点。",
            "收取邮箱": "是否收取邮箱中的奖励。",
            "PASS": "是否收取PASS（活动/任务通行证）奖励。",
        })

    def run(self):  # 一次性任务入口：收获流程 → PASS 流程。
        self.run_harvest()  # 收取友情点与邮箱。
        self.run_pass()  # 收取 PASS 奖励。

    def run_harvest(self):  # 收获流程入口（日常编排在收尾之前调用）。
        if self.is_done("harvest", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今天已收获过，跳过。")  # 记录跳过原因。
            return  # 结束本次执行。
        self.ensure_screen("lobby")  # 先就位游戏大厅（含冷启动引导与弹窗清理），避免游戏仍在加载/登录页就按大厅坐标点击；失败抛 WaitFailedException。
        if self.config.get("收获友情点"):  # 开关开启时才执行友情点流程。
            if not self.try_step(self._collect_friend, name="收获友情点", raise_on_fail=False):  # 收取友情点，弹窗未关/卡住时恢复回大厅重试。
                self.log_warning("友情点收取失败，跳过。")  # 记录失败并跳过，不阻塞后续邮箱流程。
        if self.config.get("收取邮箱"):  # 开关开启时才执行邮箱流程。
            if not self.try_step(self._collect_mailbox, name="收取邮箱", raise_on_fail=False):  # 收取邮箱，同样失败恢复重试。
                self.log_warning("邮箱收取失败，跳过。")  # 记录失败并跳过。
        self.mark_done("harvest", "day")  # 记录本周期已完成。
        self.log_info("收获完成。")  # 记录子流程完成。

    def run_pass(self):  # PASS 流程入口（日常编排在收尾之后调用）。
        if self.is_done("pass", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今天已收取PASS，跳过。")  # 记录跳过原因。
            return  # 结束本次执行。
        if not self.ensure_screen("lobby", raise_on_fail=False):  # 先就位游戏大厅（幂等闸门：含冷启动引导与弹窗清理），失败则中止。
            self.log_error("未能进入游戏大厅，中止PASS收取。")  # 记录失败原因。
            return  # 结束本次执行。
        if self.config.get("PASS"):  # 开关开启时才执行 PASS 流程。
            self.try_step(self._combined_step, name="PASS", raise_on_fail=False)  # 打开模态窗→领取→关闭，失败恢复回大厅重试，重试耗尽不阻塞收尾。
        else:  # PASS 开关关闭。
            self.log_info("PASS 收取未开启，跳过。")  # 记录跳过原因。
        self.mark_done("pass", "day")  # 记录本周期已完成。
        self.log_info("PASS收取完成。")  # 记录任务完成。

    def _collect_friend(self):  # 收取友情点子流程。
        self.wait_click_feature("friend", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击好友入口进入好友页。
        self.wait_feature("friend_close", time_out=10, raise_if_not_found=True)  # 确认好友页已打开（面板内独有的关闭按钮）。
        gift_box = self.get_box_by_name("box_friend_gift_feature")  # 获取送礼按钮区域（box_ 前缀特征为纯坐标区域，已按当前分辨率缩放）。
        if self.wait_until(lambda: self.is_feature_enabled(gift_box), time_out=5, raise_if_not_found=False):  # 等待送礼按钮变为可用（高亮彩色）；超时说明今日已送完或页面异常。
            self.click_box(gift_box, after_sleep=1)  # 点击送礼按钮。
            self.wait_click_feature("friend_modal_confirm", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击确认弹窗。
            self.wait_until(lambda: not self.is_feature_enabled(gift_box), time_out=10, raise_if_not_found=True)  # 等待送礼按钮变灰禁用，即送完。
        self.wait_click_feature("friend_close", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击关闭按钮返回。

    def _collect_mailbox(self):  # 收取邮箱子流程。
        self.wait_click_feature("mailbox", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击邮箱入口进入邮箱页。
        self.wait_feature("mailbox_close", time_out=10, raise_if_not_found=True)  # 确认邮箱页已打开（页面内独有的关闭按钮）。
        claim_box = self.get_box_by_name("box_mailbox_claim_feature")  # 获取领取按钮区域（box_ 前缀特征为纯坐标区域，已按当前分辨率缩放）。
        if self.wait_until(lambda: self.is_feature_enabled(claim_box), time_out=5, raise_if_not_found=False):  # 等待领取按钮变为可用（高亮彩色）；超时说明没有可领奖励。
            self.click_box(claim_box, after_sleep=1)  # 点击领取奖励。
            self.dismiss_all_popups(time_out=10)  # 统一清理领取奖励弹窗，返回邮箱页（默认等待弹窗出现）。
            self.wait_until(lambda: not self.is_feature_enabled(claim_box), time_out=10, raise_if_not_found=True)  # 等待领取按钮变灰禁用，即全部领完。
        self.wait_click_feature("mailbox_close", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击关闭按钮返回。

    def _combined_step(self):  # 合并子流程：逐个处理带红点的 PASS（打开模态窗→领取→关闭），直到无红点或翻页次数用尽。
        multi = self._pass_multi()  # 多个 PASS 才需要翻页查找；单个 PASS 只处理一次。
        swipes = 0  # 累计翻页次数，整轮流程共享 _PASS_SWIPE_LIMIT 上限。
        while True:  # 每轮处理一个带红点的 PASS。
            opened, swipes = self._open_pass_modal(swipes, multi)  # 翻页找红点并打开模态框，拿回累计翻页次数。
            if not opened:  # 无红点或翻页次数用尽：结束。
                break
            if not self._claim_pass_modal():  # 模态窗未确认关闭时画面上仍是面板，继续翻页会把拖拽落在面板上。
                raise WaitFailedException("PASS 模态窗未关闭")  # 抛异常交由 try_step 恢复回大厅重试。
            if not multi:  # 单个 PASS 领完即结束，不翻页。
                break
            if swipes >= self._PASS_SWIPE_LIMIT:  # 翻页次数用尽：不再找下一个 PASS。
                self.log_warning(f"PASS 翻页达到上限（{self._PASS_SWIPE_LIMIT}），停止查找。")  # 记录上限停止原因。
                break
            self._swipe_pass_page()  # 当前 PASS 已领完，翻页继续找下一个带红点的 PASS。
            swipes += 1  # 翻页次数加一。

    def _pass_multi(self):  # 是否多个 PASS：大厅存在 pass_switch/pass_selector 任一即说明 PASS 可切换。
        return any(self.find_one(f) is not None for f in self._PASS_ENTRY_FEATURES)  # 任一入口特征存在即多个 PASS。

    def _open_pass_modal(self, swipes, multi):  # 从大厅打开 PASS 模态框：翻页找红点，命中后点击徽章并确认模态框打开。返回 (是否已打开, 累计翻页次数)。
        red_dot = self.find_red_dot("box_pass_badge", template_path=self._RED_DOT_TEMPLATE, use_color_fallback=False)  # 在 PASS 徽章区域检测通知红点（模板匹配优先）。
        while red_dot is None and multi and swipes < self._PASS_SWIPE_LIMIT:  # 多个 PASS 且无红点：循环翻页切换 PASS 直到命中红点或达到上限。
            self._swipe_pass_page()  # 按住徽章向左滑动翻页。
            swipes += 1  # 翻页计数加一。
            red_dot = self.find_red_dot("box_pass_badge", template_path=self._RED_DOT_TEMPLATE, use_color_fallback=False)  # 翻页后重新检测红点。
        if red_dot is None:  # 无可领取奖励（单个 PASS 无红点，或多个 PASS 翻到上限仍无红点）。
            if multi and swipes >= self._PASS_SWIPE_LIMIT:  # 翻页次数用尽而终止，与"本来就没红点"区分日志。
                self.log_warning(f"PASS 翻页达到上限（{self._PASS_SWIPE_LIMIT}），停止查找。")  # 记录上限停止原因。
            else:  # 单 PASS 无红点或翻页后确实没有红点。
                self.log_warning("PASS 无可领取奖励，跳过。")  # 记录跳过原因。
            return False, swipes  # 不打开模态窗，由上层收尾标记完成。
        self.click_box("box_pass_area", after_sleep=1)  # 点击 PASS 徽章区域打开模态框（box_pass_badge 仅用于查找红点）。
        if self.wait_ocr(box=self._pass_tab_box(), match=list(self._PASS_TAB_PATTERNS), time_out=5,
                         raise_if_not_found=False) is None:  # 页签行 OCR 到文字才算模态框已打开。
            raise WaitFailedException("PASS 模态框未打开")  # 抛异常交由 try_step 恢复回大厅重试。
        return True, swipes  # 已打开 PASS 模态框，带回累计翻页次数。

    def _pass_tab_box(self):  # 面板页签行的 OCR 区域（按当前分辨率换算）。
        return self.box_of_screen(*self._PASS_TAB_OCR_BOX, name="pass_tab_area")

    def _pass_panel_opened(self):  # PASS 面板是否打开：页签行 OCR 到页签文字即视为打开。
        return bool(self.ocr(box=self._pass_tab_box(), match=list(self._PASS_TAB_PATTERNS)))

    def _swipe_pass_page(self):  # 点击 PASS 徽章先按住 0.5 秒，再沿 x 轴加速向左滑动（flick 手感），切换当前显示的 PASS。
        badge = self.get_box_by_name("box_pass_area")  # 获取 PASS 徽章拖拽区域（已按当前分辨率缩放）。
        x1 = badge.x + badge.width // 2  # 滑动起点：徽章区域水平中心。
        y = badge.y + badge.height // 2  # 滑动垂直位置：徽章区域垂直中心。
        x2 = int(self.width * 0.5)  # 滑动终点：向左滑动约半个屏宽完成翻页。
        self.mouse_down(x1, y)  # 在徽章处按下鼠标不松开。
        for i in range(1, self._PASS_FLICK_STEPS + 1):  # 平方加速曲线插值拖动：起始慢、越滑越快，模拟真实翻页 flick 手感（框架 swipe 为匀速线性插值，无法模拟）。
            progress = (i / self._PASS_FLICK_STEPS) ** 3  # 加速进度（ease-in），终点达到最高速度。
            self.move(round(x1 + (x2 - x1) * progress), y)  # 按加速曲线移动鼠标。
            self.sleep(self._PASS_FLICK_STEP_SLEEP)  # 每步 10ms 停顿。
        self.mouse_up()  # 终点以最高速度松开，完成翻页。
        self.sleep(1.8)  # 等待翻页动画停稳，再让上层重新检测红点（避免动画中间帧误判导致连滑）。

    def _claim_pass_modal(self):  # 在 PASS 模态框内领取：先任务页再奖励页，收尾关闭模态窗。返回模态窗是否已确认关闭。
        claim_box = self.get_box_by_name("box_pass_reward_claim_feature")  # 领取按钮区域（两页共用同一按钮位置）。
        self.click_box("box_pass_mission_page", after_sleep=1)  # 点任务页页签：box_ 为纯坐标区域，直接按标注中心点击。
        self.next_frame()  # 刷新一帧，确保后续判定读到切换后的画面。
        if self.is_feature_enabled(claim_box):  # 任务页领取按钮可用（高亮彩色）。
            self.click_box(claim_box, after_sleep=1)  # 点击领取任务页奖励。
            if self.wait_feature("pass_rank_up", time_out=3, raise_if_not_found=False) is not None:  # 领取触发等级提升提示。
                self.click_box(claim_box, after_sleep=1)  # 再次点击领取按钮位置关闭 RANK UP 提示。
                self.wait_until(lambda: self.find_one("pass_rank_up") is None, time_out=3,
                                raise_if_not_found=False)  # 等待 RANK UP 提示消失。
        self.click_box("box_pass_reward_page", after_sleep=1)  # 点奖励页页签：box_ 为纯坐标区域，直接按标注中心点击。
        self.next_frame()  # 刷新一帧，确保后续判定读到切换后的画面。
        if self.is_feature_enabled(claim_box):  # 奖励页领取按钮可用（高亮彩色）。
            self.click_box(claim_box, after_sleep=1)  # 点击领取奖励页奖励。
            self.dismiss_all_popups(time_out=5)  # 处理领取后弹出的奖励遮罩层（默认等待遮罩出现）。
        return self._close_pass_modal()  # 收尾关闭 PASS 模态窗（已领取或无可领均关闭，回到大厅），返回是否已确认关闭。

    def _close_pass_modal(self):  # 关闭 PASS 模态窗：清理领奖遮罩后点击面板外空白关闭（关闭 X 外观/位置随面板样式漂移，模板识别不稳定）。
        self.dismiss_all_popups(wait_for_popup=False, time_out=5)  # 快速清理领奖遮罩等弹窗，无弹窗不白等。
        if not self.close_popup_by_blank(lambda: not self._pass_panel_opened()):  # 点空白关闭，按面板页签文字消失确认（遮罩吞点击时自动补点）。
            self.log_warning("点击空白未能关闭PASS模态窗，跳过关闭。")  # 记录失败（补点耗尽后页签文字仍在，即面板未关或被页面吞掉点击）。
            return False  # 关闭失败。
        self.log_info("已关闭PASS模态窗。")  # 记录关闭动作。
        return True  # 关闭成功。
