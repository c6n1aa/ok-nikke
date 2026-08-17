from src.tasks.MyBaseTask import MyBaseTask  # 导入项目基类，所有任务统一继承它。


class HarvestTask(MyBaseTask):  # 定义收获子任务类。

    done_keys = {"harvest": "day"}  # 完成状态：收获（日常刷新）。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "收获"  # 任务显示名称。
        self.description = "收取友情点与邮箱奖励。"  # 任务说明。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "收获友情点": True,  # 是否收取友情点。
            "收取邮箱": True,  # 是否收取邮箱奖励。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "收获友情点": "是否点击好友送礼并收取友情点。",
            "收取邮箱": "是否收取邮箱中的奖励。",
        })

    def run(self):  # 子任务执行入口。
        if self.is_done("harvest", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今天已收获过，跳过。")  # 记录跳过原因。
            return  # 结束本次执行。
        self.wait_for_lobby()  # 先确认已进入游戏大厅，避免游戏仍在加载/登录页就按大厅坐标点击。
        self.dismiss_all_popups(wait_for_popup=False, time_out=10)  # 统一清理进入大厅后残留的公告/活动弹窗，无弹窗时立即返回不等待。
        if self.config.get("收获友情点"):  # 开关开启时才执行友情点流程。
            if not self.try_step(self._collect_friend, name="收获友情点", raise_on_fail=False):  # 收取友情点，弹窗未关/卡住时恢复回大厅重试。
                self.log_warning("友情点收取失败，跳过。")  # 记录失败并跳过，不阻塞后续邮箱流程。
        if self.config.get("收取邮箱"):  # 开关开启时才执行邮箱流程。
            if not self.try_step(self._collect_mailbox, name="收取邮箱", raise_on_fail=False):  # 收取邮箱，同样失败恢复重试。
                self.log_warning("邮箱收取失败，跳过。")  # 记录失败并跳过。
        self.mark_done("harvest", "day")  # 记录本周期已完成。
        self.log_info("收获完成。")  # 记录子流程完成。

    def _collect_friend(self):  # 收取友情点子流程。
        self.wait_click_feature("friend", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击好友入口进入好友页。
        gift = self.wait_feature("friend_gift", time_out=5, raise_if_not_found=False)  # 判断送礼按钮是否可用。
        if gift:  # 存在可用送礼按钮才点击。
            self.click_box(gift, after_sleep=1)  # 点击送礼按钮。
            self.wait_click_feature("friend_modal_confirm", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击确认弹窗。
            self.wait_feature("friend_gift_disable", time_out=10, raise_if_not_found=True)  # 等待送礼变为不可用，即送完。
        self.wait_click_feature("friend_close", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击关闭按钮返回。

    def _collect_mailbox(self):  # 收取邮箱子流程。
        self.wait_click_feature("mailbox", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击邮箱入口进入邮箱页。
        claim = self.wait_feature("mailbox_claim", time_out=5, raise_if_not_found=False)  # 判断是否为可收取状态。
        if claim:  # 存在可收取按钮才点击。
            self.click_box(claim, after_sleep=1)  # 点击领取奖励。
            self.dismiss_all_popups(time_out=10)  # 统一清理领取奖励弹窗，返回邮箱页。
            self.wait_feature("mailbox_claim_disable", time_out=10, raise_if_not_found=True)  # 等待领取变为不可用，即全部领完。
        self.wait_click_feature("mailbox_close", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击关闭按钮返回。
