"""活动签到印章流程：大活动地图页独有的独立整页界面，进入后领取再返回活动菜单页。

签到页没有跨期稳定的模板特征（各期美术不同），进入判据一律反向判「活动菜单页消失」，
可领判据复用「全部领取」原语（见 _claim.py）。
"""

from ok.task.exceptions import WaitFailedException  # 入口缺失等流程断言抛出的等待失败异常。

from src.tasks.event._const import (
    _SD_ARRIVE_TIMEOUT,
)


class EventCheckinMixin:
    """活动签到印章流程（自足重入）。

    进签到界面 → 等 SD 小人走到并切页 → 领「全部领取」→ 点返回回活动菜单页。
    签到是独立整页界面而非模态窗，领取后不用 dismiss_all_popups（其「全部领取」会被登录奖励面板清理链误认）。
    """

    def _flow_checkin(self):  # 签到印章流程（自足重入）：进签到界面 → 等 SD 小人到达 → 全部领取 → 点返回回活动菜单页。
        # 仅大活动有签到入口（_do_checkin 已按「签到印章」关键词探测）；签到是独立整页界面（非模态窗），
        # 各期美术不同，进入/可领判据一律走 OCR 文字（同登录奖励），不依赖模板。
        self._nav_to_event_main()  # 就位活动主页（正常已就位；恢复回大厅后由此重入）。
        entry = self._entry_box("签到")  # 签到印章入口命中框。
        if entry is None:  # 入口缺失（菜单未渲染或页面结构变化）。
            raise WaitFailedException("未找到签到印章入口")  # 抛异常由 try_step 恢复。
        self.click_box(entry, after_sleep=2)  # 点击签到入口，大活动 SD 小人开始走向签到地点。
        # 签到页无专有界面判据 → 反向判：点击后活动菜单页（event_main）消失即已切到签到页（小人已走到）；
        # 仍在菜单页 = 未走到签到地点、切页失败，告警后直接回菜单页跳过领取。
        if not self.wait_until(lambda: not self.is_screen("event_main"),  # 轮询等菜单页消失 = 已切到签到页。
                               time_out=_SD_ARRIVE_TIMEOUT, settle_time=0):  # 到达等待窗口（切页即返回）。
            self.log_warning("签到页未在预期时间内切换（仍在活动菜单页），跳过领取")  # 记录跳过原因。
            self._ensure_event_menu()  # 兜底回菜单页。
            return  # 结束签到流程。
        # 已切到签到页：等「全部领取」出现后判态领取（奖励界面与切页近乎同步，仍轮询容忍盖章动画）。
        if self.wait_until(lambda: self._find_claim_all() is not None,  # 轮询等「全部领取」出现 = 奖励界面就绪。
                           time_out=_SD_ARRIVE_TIMEOUT, settle_time=1.5):  # 命中后再稳定 1.5s，吸收盖章动画里按钮仍位移的过渡期。
            claim = self._find_claim_all()  # 「全部领取」按钮文字框。
            if self.is_feature_enabled(self._claim_button_box(claim)):  # 外扩取到按钮底色判态：彩色 = 仍有可领奖励。
                self.click_box(claim, after_sleep=1)  # 点击全部领取。
                self.log_info("已点击签到印章「全部领取」")  # 记录动作。
                self._close_claim_overlay()  # 领取后弹出奖励遮罩（盖住界面），复用登录奖励同一套遮罩清理。
            else:  # 按钮灰白 = 无可领奖励（今日已领完）。
                self.log_info("签到奖励无可领取（按钮灰白，可能今日已领取）")  # 记录状态。
        else:  # 已切页但未识别到「全部领取」。
            self.log_warning("签到奖励界面未在预期时间内出现（已切页但未识别到「全部领取」），跳过领取")  # 记录跳过原因。
        # 签到是独立整页界面（非模态窗）：点返回键回活动菜单页（已在菜单页则 no-op）。
        # 注意：不要用 dismiss_all_popups —— 签到界面「全部领取」与登录奖励面板判据同字，
        # 会被 _close_daily_login_popup 误认成登录奖励面板重复点击（其消歧只认 mission_page 与
        # 活动任务弹窗，签到页两者都不命中）。
        self._ensure_event_menu()  # 返回活动菜单页，供后续子流程接续。
