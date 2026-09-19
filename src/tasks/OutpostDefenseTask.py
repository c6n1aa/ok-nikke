import time

from ok.task.exceptions import WaitFailedException

from src import log_fields  # 日志字段取值词表（单一数据源）。
from src.tasks.NikkeBaseTask import NikkeBaseTask  # 导入项目基类，所有任务统一继承它。


class OutpostDefenseTask(NikkeBaseTask):  # 定义歼灭子任务类。

    done_keys = {"outpost_defense": "day"}  # 完成状态：歼灭（日常刷新）。

    _MAX_GEM_TIMES = 10  # 使用珠宝歼灭次数的上限（与 validate_config 同源）。

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
        key, period = "outpost_defense", self.done_keys["outpost_defense"]  # 完成状态键与周期。
        if self.is_done(key, period):  # 本周期内已完成则直接跳过。
            self.log_info(f"event={log_fields.EVENT_SKIP} reason={log_fields.REASON_ALREADY_DONE} key={key} period={period}")  # 记录跳过。
            return  # 结束本次执行。
        times = self.config.get("使用珠宝歼灭次数", 0)  # 读取使用珠宝的歼灭次数。
        if times < 0 or times > self._MAX_GEM_TIMES:  # 校验次数是否在合法范围。
            self.log_error(f"event={log_fields.EVENT_ABORT} reason=config_out_of_range key=使用珠宝歼灭次数 value={times} range=0-{self._MAX_GEM_TIMES}")  # 记录非法配置。
            return  # 结束本次执行。
        self.log_info(f"event={log_fields.EVENT_START} gem_times={times}")  # 记录流程开始与生效配置。
        self.ensure_screen("lobby")  # 先就位游戏大厅（含冷启动引导与弹窗清理），避免游戏仍在加载/登录页就按大厅坐标点击；失败抛 WaitFailedException。
        if not self.try_step(self._do_outpost_defense, name="歼灭", raise_on_fail=False):  # 从大厅出发完成整个歼灭子流程，失败恢复回大厅重试。
            self.log_warning(f"event={log_fields.EVENT_SKIP} reason={log_fields.REASON_RETRIES_EXHAUSTED}")  # 记录跳过，不中断整个日常。
            return  # 失败时不标记已完成，留待下次重试。
        self.mark_done(key, period)  # 记录本周期已完成。
        self.log_info(f"event={log_fields.EVENT_END} result={log_fields.RESULT_SUCCESS} key={key} period={period}")  # 记录子流程完成。

    def _do_outpost_defense(self):  # 歼灭入口子流程：从大厅进入、歼灭并领取奖励，由 try_step 整体包裹。
        self._click_outpost_defense(time_out=10)  # 按标注区域中心点击进入前哨基地歼灭页。
        times = self.config.get("使用珠宝歼灭次数", 0)  # 读取使用珠宝的歼灭次数。
        if times == 0:  # 次数为0时执行免费歼灭。
            self._wipe_out_free()  # 免费歼灭一次。
        else:  # 次数大于0时执行珠宝歼灭循环。
            for index in range(times):  # 按配置次数循环。
                self.log_info(f"event={log_fields.EVENT_ROUND} index={index + 1} total={times}")  # 记录本轮珠宝歼灭。
                self._wipe_out_with_gem()  # 使用珠宝歼灭一次。
        self.wait_click_feature("outpost_defense_claim", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击领取歼灭奖励，弹窗未关会抛异常被 try_step 捕获。
        self.dismiss_all_popups(time_out=5);  # 统一清理可能残留的领取弹窗，等待弹窗出现并关闭后再继续。

    def _wipe_out_free(self):  # 免费歼灭子流程。
        self._open_wipe_out_dialog()  # 打开歼灭确认框，免费次数仍在时顺带点掉这次免费歼灭。
        self.click_box("box_wipe_out_close", raise_if_not_found=True, after_sleep=1)  # 点击关闭按钮。
        self.wait_feature("outpost_defense_wipe_out", time_out=10, raise_if_not_found=True)  # 等待回到歼灭页。

    def _wipe_out_with_gem(self):  # 珠宝歼灭子流程。
        self._open_wipe_out_dialog()  # 打开歼灭确认框，免费次数仍在时先点掉这次免费歼灭。
        self.wait_click_feature("wipe_out_with_gem", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击使用珠宝歼灭。
        self.wait_click_feature("wipe_out_confirm", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击确认弹窗。
        self.dismiss_all_popups(time_out=10);
        self.click_box("box_wipe_out_close", raise_if_not_found=True, after_sleep=1)  # 点击关闭弹窗。

    def _open_wipe_out_dialog(self):  # 打开歼灭确认框：没有珠宝消耗图标说明免费次数仍在，顺带点掉这次免费歼灭。
        self.wait_click_feature("outpost_defense_wipe_out", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击歼灭按钮弹出确认框。
        if not self.wait_feature("wipe_out_with_gem", time_out=5, raise_if_not_found=False):  # 珠宝歼灭的反例：确认框没有珠宝消耗图标，说明本次是免费歼灭。
            self.click_box("wipe_out_with_gem", raise_if_not_found=True, after_sleep=1)  # 点击歼灭按钮（宝石图标所在区域，免费状态下点它即为免费歼灭，按标注点击不依赖模板匹配）。
            self.dismiss_all_popups(time_out=5);  # 统一清理确认弹窗。

    def validate_config(self, key, value):  # 配置校验入口。
        if key == "使用珠宝歼灭次数":  # 只校验歼灭次数。
            if not isinstance(value, int) or value < 0 or value > self._MAX_GEM_TIMES:  # 次数必须是 0 到上限之间的整数。
                return f"使用珠宝歼灭次数必须在 0 到 {self._MAX_GEM_TIMES} 之间。"  # 返回非法提示。