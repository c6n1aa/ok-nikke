from src.tasks.NikkeBaseTask import NikkeBaseTask  # 项目基类，所有任务统一继承它。


class ExtrasTask(NikkeBaseTask):  # 其他杂项任务：收取 PASS（活动/任务通行证）奖励。

    done_keys = {"extras": "day"}  # 完成状态：杂项（日常刷新）。

    _RED_DOT_TEMPLATE = 'assets/template/common/badge.png'  # 通知红点模板：与任务弹窗共用，模板匹配优先命中角标红点。
    _PASS_ENTRY_FEATURES = ("pass_switch", "pass_selector")  # 大厅 PASS 入口的两种形态：任一存在即代表多个 PASS 可切换。
    _PASS_CLOSE_FEATURES = ("pass_close1", "pass_close2")  # PASS 模态窗两种尺寸的关闭 X 按钮，依次尝试任一命中。
    _PASS_SWIPE_LIMIT = 8  # 多个 PASS 翻页查找红点的总次数上限，超过也标记完成。
    _PASS_FLICK_STEPS = 20  # 加速度翻页的插值步数（每步停顿 10ms，总拖拽约 0.2 秒）。
    _PASS_FLICK_STEP_SLEEP = 0.01  # 每步插值停顿秒数。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "其他杂项"  # 任务显示名称。
        self.description = "收取PASS（活动/任务通行证）奖励。"  # 任务说明。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "PASS": True,  # 是否收取 PASS 奖励。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "PASS": "是否收取PASS（活动/任务通行证）奖励。",
        })

    def run(self):  # 任务执行入口。
        self.log_info("杂项任务开始。")  # 记录任务开始。
        if self.is_done("extras", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日杂项已完成，跳过。")  # 记录跳过原因。
            return  # 结束本次执行。
        if not self.ensure_screen("lobby", raise_on_fail=False):  # 启动后就位游戏大厅（幂等闸门：含冷启动引导与弹窗清理），失败则中止。
            self.log_error("未能进入游戏大厅，中止杂项任务。")  # 记录失败原因。
            return  # 结束本次执行。
        if self.config.get("PASS"):  # 开关开启时才执行 PASS 流程。
            self.try_step(self._combined_step, name="PASS", raise_on_fail=False)  # 打开模态窗→领取→关闭，失败恢复回大厅重试，重试耗尽不阻塞收尾。
        else:  # PASS 开关关闭。
            self.log_info("PASS 收取未开启，跳过。")  # 记录跳过原因。
        self.mark_done("extras", "day")  # 记录本周期已完成。
        self.log_info("杂项任务完成。")  # 记录任务完成。

    def _combined_step(self):  # 合并子流程：打开 PASS 模态窗→领取→关闭，结束回大厅。
        if self._open_pass_modal():  # 打开 PASS 模态框（含多个 PASS 的翻页找红点）。
            self._claim_pass_modal()  # 领取任务页/奖励页奖励，收尾关闭模态窗。

    def _open_pass_modal(self):  # 从大厅打开 PASS 模态框：多个 PASS 先翻页找红点，命中后点击徽章并确认模态框打开。返回是否已打开。
        is_multi = any(self.find_one(f) is not None for f in self._PASS_ENTRY_FEATURES)  # 判断 pass_switch/pass_selector 是否存在其一：任一存在即多个 PASS。
        swipes = 0  # 翻页计数。
        red_dot = self.find_red_dot("box_pass_badge", template_path=self._RED_DOT_TEMPLATE, use_color_fallback=False)  # 在 PASS 徽章区域检测通知红点（模板匹配优先）。
        while red_dot is None and is_multi and swipes < self._PASS_SWIPE_LIMIT:  # 多个 PASS 且无红点：循环翻页切换 PASS 直到命中红点或达到上限。
            self._swipe_pass_page()  # 按住徽章向左滑动翻页。
            swipes += 1  # 翻页计数加一。
            red_dot = self.find_red_dot("box_pass_badge", template_path=self._RED_DOT_TEMPLATE, use_color_fallback=False)  # 翻页后重新检测红点。
        if red_dot is None:  # 无可领取奖励（单个 PASS 无红点，或多个 PASS 翻到上限仍无红点）。
            self.log_warning("PASS 无可领取奖励，跳过。")  # 记录跳过原因。
            return False  # 不打开模态窗，由 run 收尾标记完成。
        self.click_box("box_pass_badge", after_sleep=1)  # 点击徽章打开 PASS 模态框。
        self.wait_feature("pass_page", box=self.get_box_by_name("box_pass_page"), use_gray_scale=True,
                          time_out=5, raise_if_not_found=True)  # 在 box_pass_page 区域灰度匹配 pass_page 确认模态框打开。
        return True  # 已打开 PASS 模态框。

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

    def _claim_pass_modal(self):  # 在 PASS 模态框内领取：先任务页再奖励页，无可领时关闭模态窗。
        claim_box = self.get_box_by_name("box_pass_reward_claim_feature")  # 领取按钮区域（两页共用同一按钮位置）。
        self.wait_click_feature("box_pass_mission_page", time_out=5, raise_if_not_found=True, after_sleep=1)  # 点击任务页页签。
        self.next_frame()  # 刷新一帧，确保后续判定读到切换后的画面。
        if self.is_feature_enabled(claim_box):  # 任务页领取按钮可用（高亮彩色）。
            self.click_box(claim_box, after_sleep=1)  # 点击领取任务页奖励。
            if self.wait_feature("pass_rank_up", time_out=3, raise_if_not_found=False) is not None:  # 领取触发等级提升提示。
                self.click_box(claim_box, after_sleep=1)  # 再次点击领取按钮位置关闭 RANK UP 提示。
                self.wait_until(lambda: self.find_one("pass_rank_up") is None, time_out=3,
                                raise_if_not_found=False)  # 等待 RANK UP 提示消失。
        self.wait_click_feature("box_pass_reward_page", time_out=5, raise_if_not_found=True, after_sleep=1)  # 点击奖励页页签。
        self.next_frame()  # 刷新一帧，确保后续判定读到切换后的画面。
        if self.is_feature_enabled(claim_box):  # 奖励页领取按钮可用（高亮彩色）。
            self.click_box(claim_box, after_sleep=1)  # 点击领取奖励页奖励。
            self.dismiss_all_popups(time_out=5)  # 处理领取后弹出的奖励遮罩层（默认等待遮罩出现）。
        self._close_pass_modal()  # 收尾关闭 PASS 模态窗（已领取或无可领均关闭，回到大厅）。

    def _close_pass_modal(self):  # 关闭 PASS 模态窗：先清理可能遮挡关闭按钮的领奖遮罩，再按两种尺寸的关闭 X 依次尝试。
        self.dismiss_all_popups(wait_for_popup=False, time_out=5)  # 快速清理领奖遮罩等弹窗，无弹窗不白等。
        for close in self._PASS_CLOSE_FEATURES:  # 依次尝试两种尺寸的关闭按钮。
            found = self.find_one(close, use_gray_scale=True)  # 灰度匹配关闭 X，减少背景对纯色 X 图形的干扰。
            if found is not None:  # 当前关闭按钮命中。
                self.click_box(found, after_sleep=1)  # 点击关闭按钮。
                self.log_info("已关闭PASS模态窗。")  # 记录关闭动作。
                return True  # 关闭成功。
        self.log_warning("未找到PASS关闭按钮，跳过关闭。")  # 两种关闭按钮均未命中（模态窗可能已自行关闭）。
        return False  # 关闭失败。