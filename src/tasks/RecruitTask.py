import re
import time  # 时间模块，招募结果确认循环的超时控制。

from ok.task.exceptions import WaitFailedException  # 特征缺失/确认超时抛出的框架等待失败异常。

from src.tasks.NikkeBaseTask import NikkeBaseTask  # 项目基类，所有任务统一继承它。

# 招募结果「确认」按钮 OCR 匹配模式：OCR 文本常带尾随标点/拆框，用正则部分匹配。
_CONFIRM_PATTERN = re.compile(r"确认")

# 招募页签翻页上限：目标入口翻遍所有页签仍未找到时结束查找，防止特征缺失导致死循环。
_MAX_RECRUIT_PAGES = 8


class RecruitTask(NikkeBaseTask):  # 招募任务：每日免费招募/友情点招募/折扣普通招募。

    done_keys = {"recruit": "day"}  # 完成状态：日常刷新。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "招募"  # 任务显示名称。
        self.description = "活动免费招募/友情点招募/普通招募"  # 任务说明。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/（总开关由日常编排的「招募」键承担，不在此重复）。
            # "免费活动单抽": True,  # 每日活动免费招募（暂缺截图特征未实现，见 recruit_task.md 补充知识2）。
            "友情点招募": True,  # 是否使用10友情点进行招募。
            "折扣普通招募": False,  # 是否使用150钻进行每日折扣招募。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "友情点招募": "使用10友情点进行招募",
            "折扣普通招募": "使用150钻进行每日折扣招募",
        })

    def run(self):  # 任务执行入口：就位大厅→进入招募界面→按配置执行各招募→返回大厅标记完成。
        self.log_info("招募任务开始。")  # 记录任务开始。
        if not self.ensure_screen("lobby", raise_on_fail=False):  # 启动后就位游戏大厅（幂等闸门：含冷启动引导与弹窗清理），失败则中止。
            self.log_error("未能进入游戏大厅，中止招募任务。")  # 记录失败原因。
            return  # 结束本次执行。
        if self.is_done("recruit", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日招募已完成，跳过。")  # 记录跳过原因。
            return  # 结束本次执行。
        if not self.try_step(self._do_recruit, name="招募", raise_on_fail=False):  # 招募整体流程：进入→各子招募→返回大厅，失败不标记完成。
            self.log_warning("招募流程多次失败，跳过。")  # 记录失败原因。
            return  # 结束本次执行。
        self.mark_done("recruit", "day")  # 记录本周期已完成。
        self.log_info("招募任务完成。")  # 记录任务完成。

    def _do_recruit(self):  # 招募整体流程（re-entrant，由 try_step 包裹）：进入招募界面→按配置执行各子招募→返回大厅。
        self.transition("recruit_page", click_feature="gacha", wait_confirm=10, after_sleep=1)  # 点大厅抽卡入口并确认进入招募界面。
        if self.config.get("友情点招募"):  # 启用友情点招募才执行。
            self._do_social_point_recruit()  # 友情点招募：翻页找入口→单抽→跳过动画→点确认。
        if self.config.get("折扣普通招募"):  # 启用折扣普通招募才执行。
            self._do_ordinary_recruit()  # 折扣普通招募：翻页找入口→确认→跳过动画→点确认。
        self.wait_click_feature("lobby", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点底部导航大厅按钮返回大厅。
        if not self.wait_for_lobby(time_out=10, raise_if_not_found=False):  # 等待确认回到大厅。
            raise WaitFailedException("招募后未能返回大厅")  # 抛异常由 try_step 恢复重试。

    def _find_recruit_entry(self, feature_name):  # 在当前招募页签查找目标入口，找不到则点击下一页直到翻遍所有页签。
        for _ in range(_MAX_RECRUIT_PAGES):  # 有限翻页，避免特征缺失时死循环。
            found = self.find_one(feature_name)  # 当前页查找目标入口。
            if found is not None:  # 命中。
                return found  # 返回入口框。
            if not self.wait_click_feature("recruit_next_page", time_out=3, raise_if_not_found=False, after_sleep=3):  # 点击下一页，等待3秒确保界面稳定。
                break  # 无下一页按钮（已到最后一页）结束查找。
        self.log_warning(f"翻遍招募页签未找到入口：{feature_name}")  # 记录查找失败。
        return None  # 返回未找到。

    def _do_social_point_recruit(self):  # 友情点招募：找入口→点击单抽→跳过动画→等待结果确认。
        target = self._find_recruit_entry("recruit_social_point_single")  # 翻页查找友情点单抽入口。
        if target is None:  # 未找到入口。
            raise WaitFailedException("未找到友情点招募入口")  # 抛异常由 try_step 恢复。
        self.click_box(target, after_sleep=3)  # 点击友情点单抽入口开始招募。
        self.wait_click_feature("recruit_skip", time_out=15, raise_if_not_found=True, after_sleep=1)  # 等待并点击跳过按钮跳过招募动画。
        self._click_recruit_result()  # 等待结果面板「确认」按钮并点击关闭。

    def _do_ordinary_recruit(self):  # 折扣普通招募：找入口→确认→跳过动画→等待结果确认。
        target = self._find_recruit_entry("recruit_ordinary_150")  # 翻页查找折扣普通招募入口。
        if target is None:  # 未找到入口。
            raise WaitFailedException("未找到折扣普通招募入口")  # 抛异常由 try_step 恢复。
        self.click_box(target, after_sleep=3)  # 点击折扣普通招募入口弹出确认弹窗。
        self.wait_click_feature("recruit_ordinary_confirm", time_out=10, raise_if_not_found=True, after_sleep=1)  # 等待并点击确认按钮开始招募。
        self.wait_click_feature("recruit_skip", time_out=15, raise_if_not_found=True, after_sleep=1)  # 等待并点击跳过按钮跳过招募动画。
        self._click_recruit_result()  # 等待结果面板「确认」按钮并点击关闭。

    def _click_recruit_result(self, time_out=15, interval=0.5):  # 等待招募结果「确认」按钮并点击：0.5秒间隔 OCR，出金/new 遮挡时点击结果区一次再识别。
        try:  # 区域特征可能尚未标注进 coco。
            result_box = self.get_box_by_name("box_recruit_result")  # 获取结果面板区域框（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失。
            raise WaitFailedException("box_recruit_result 特征缺失")  # 抛异常由 try_step 恢复。
        if result_box is None:  # 区域无效（如无可用帧）。
            raise WaitFailedException("box_recruit_result 区域无效")  # 抛异常由 try_step 恢复。
        deadline = time.time() + time_out  # 记录整体超时时刻。
        retried = False  # 出金/new 的点击结果区重试只做一次。
        while time.time() < deadline:  # 循环直到超时。
            self.next_frame()  # 刷新一帧，避免读到旧帧。
            matches = self.ocr(box=result_box, match=_CONFIRM_PATTERN)  # 结果面板区域 OCR 部分匹配「确认」。
            if matches:  # 识别到确认按钮。
                self.click_box(matches[0], after_sleep=1)  # 点击确认按钮关闭招募结果面板。
                return  # 结束本子招募。
            self.sleep(interval)  # 间隔 0.5 秒再识别。
            if not retried:  # 首次识别超时：点击结果区一次再识别（出金/new 动画遮挡关键字）。
                self.log_warning("招募结果区域未识别到「确认」，点击结果区后重试。")  # 记录重试原因。
                self.click_box(result_box, after_sleep=interval)  # 点击结果区关闭动画遮罩。
                self.next_frame()  # 刷新一帧后再进入下一轮识别。
                retried = True  # 置位标记，不再重复点击。
        raise WaitFailedException("招募结果「确认」按钮等待超时")  # 超时抛异常由 try_step 恢复。