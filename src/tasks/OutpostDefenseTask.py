import time

from ok.task.exceptions import WaitFailedException

from src.tasks.MyBaseTask import MyBaseTask  # 导入项目基类，所有任务统一继承它。


class OutpostDefenseTask(MyBaseTask):  # 定义歼灭子任务类。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "歼灭"  # 任务显示名称。
        self.description = "防御前哨基地进行收菜，可选使用珠宝追加次数。"  # 任务说明。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "使用珠宝歼灭次数": 0,  # 使用珠宝进行歼灭的次数。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "使用珠宝歼灭次数": "使用珠宝进行一举歼灭的次数，0-10，0表示仅使用免费次数。",
        })

    def _click_outpost_defense(self, time_out=10):
        """进入防御前哨基地页：按 outpost_defense 标注区域中心直接点击入口，不依赖模板匹配/OCR。"""
        start = time.time()  # 记录开始时间，用于超时控制。
        while time.time() - start < time_out:  # 循环直到超时或成功点击。
            try:
                box = self.get_box_by_name("outpost_defense")  # 读取标注区域框（已按当前分辨率缩放）。
                if box is not None:  # 区域框存在则直接点击其中心。
                    self.click_box(box, after_sleep=1)  # 点击歼灭入口并等待界面响应。
                    return True  # 点击成功返回。
            except WaitFailedException:  # 画面暂不可用等情况时忽略并重试。
                pass
            self.sleep(1)  # 等待一帧后重试。
        raise WaitFailedException("未能进入前哨基地歼灭页。")  # 超时仍失败则抛出异常。

    def run(self):  # 子任务执行入口。
        if self.is_done("outpost_defense", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今天已歼灭过，跳过。")  # 记录跳过原因。
            return  # 结束本次执行。
        times = self.config.get("使用珠宝歼灭次数", 0)  # 读取使用珠宝的歼灭次数。
        if times < 0 or times > 10:  # 校验次数是否在合法范围。
            self.log_error(f"歼灭次数 {times} 超出 0-10 范围。")  # 记录非法配置。
            return  # 结束本次执行。
        self.wait_for_lobby()  # 先确认已进入游戏大厅，避免游戏仍在加载/登录页就按大厅坐标点击。
        self._click_outpost_defense(time_out=10)  # 按标注区域中心点击。
        if times == 0:  # 次数为0时执行免费歼灭。
            self._wipe_out_free()  # 免费歼灭一次。
        else:  # 次数大于0时执行珠宝歼灭循环。
            for _ in range(times):  # 按配置次数循环。
                self._wipe_out_with_gem()  # 使用珠宝歼灭一次。
        self.wait_click_feature("outpost_defense_claim", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击领取歼灭奖励。
        self.close_overlay();
        self.mark_done("outpost_defense", "day")  # 记录本周期已完成。
        self.log_info("歼灭完成。")  # 记录子流程完成。

    def _wipe_out_free(self):  # 免费歼灭子流程。
        self.wait_click_feature("outpost_defense_wipe_out", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击歼灭按钮弹出确认框。
        free = self.wait_feature("wipe_out", time_out=5, raise_if_not_found=False)  # 尝试查找免费歼灭按钮，若存在则点击。
        if free:  # 存在免费歼灭按钮则点击。
            self.click_box(free, after_sleep=1)  # 点击免费歼灭确认。
            self.close_overlay();
        else:  # 找不到免费歼灭按钮则关闭弹窗。
            self.wait_click_feature("wipe_out_close", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击关闭按钮。
        self.wait_feature("outpost_defense_wipe_out", time_out=10, raise_if_not_found=True)  # 等待回到歼灭页。

    def _wipe_out_with_gem(self):  # 珠宝歼灭子流程。
        self.wait_click_feature("outpost_defense_wipe_out", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击歼灭按钮。
        free = self.wait_feature("wipe_out", time_out=5, raise_if_not_found=False)  # 尝试查找免费歼灭按钮，若存在则点击。
        if free:  # 若存在免费歼灭按钮则点击。
            self.click_box(free, after_sleep=1)  # 点击免费歼灭确认。
            self.wait_feature("outpost_defense_wipe_out", time_out=10, raise_if_not_found=True)  # 等待回到歼灭页。
            return  # 免费歼灭后直接返回，不再使用珠宝。
        self.wait_click_feature("wipe_out_with_gem", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击使用珠宝歼灭。
        self.wait_click_feature("wipe_out_confirm", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击确认弹窗。
        self.close_overlay();
        self.wait_click_feature("wipe_out_close", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击关闭弹窗。

    def validate_config(self, key, value):  # 配置校验入口。
        if key == "使用珠宝歼灭次数":  # 只校验歼灭次数。
            if not isinstance(value, int) or value < 0 or value > 10:  # 次数必须是0-10的整数。
                return "使用珠宝歼灭次数必须在 0 到 10 之间。"  # 返回非法提示。