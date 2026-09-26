"""活动挑战流程：进挑战页 → 自下而上找第一个可用关卡 → 快速 / 普通战斗 → 返回菜单页。

大小活动同一套 UI；可用性用 coco 关卡标记 + 色彩判态，点标记需沿 X 轴左移落进行主体。
"""

import random  # 随机模块：关卡标记点击落点在左移区间内随机取偏移。

from ok.feature.Box import Box  # 关卡标记命中框左移后的点击框。
from ok.task.exceptions import WaitFailedException  # 入口缺失等流程断言抛出的等待失败异常。

from src.tasks.event._const import (
    _BATTLE_AFTER_SLEEP,
    _CHALLENGE_CLICK_ATTEMPTS,
    _CHALLENGE_CLICK_X_OFFSET,
    _CHALLENGE_LIST_BOX,
    _CHALLENGE_PAGE_SETTLE,
    _CHALLENGE_STAGE_FEATURE,
    _SD_ARRIVE_TIMEOUT,
    _STAGE_DETAIL_BATTLE_BOX,
    _STAGE_ENTER_TIMEOUT,
    _STORY_BATTLE_TIMEOUT,
    _SWEEP_CLOSE_FEATURE,
    _SWEEP_QUICK_BOX,
)


class EventChallengeMixin:
    """活动挑战关卡的执行链。

    进入挑战页后自下而上找第一个非灰白的关卡标记（最下面的最接近当前进度），点开详情页，
    有快速战斗就走快速战斗链，否则走普通战斗；收尾回活动菜单页。
    """

    def _flow_challenge(self):  # 挑战流程（自足重入）：进挑战页 → 战斗/扫荡 → 返回活动菜单页。
        # 大小活动都有「挑战」，且为同一套 UI（已确认）。
        # 进入方式差异（大活动点击后 SD 小人先走到地点再切页、小活动点击即切页）统一走 transition
        # 守卫式进入：其 retry_click 补点实测不中断小人行为（仍继续走到挑战地点再切页），故可安全复用，
        # 不再手写「只点一次 + 轮询等挑战页」。
        self._nav_to_event_main()  # 就位活动主页（正常已就位；恢复回大厅后由此重入）。
        entry = self._entry_box("挑战")  # 挑战入口命中框（大小活动入口文字都是「挑战」，_entry_box 已统一）。
        if entry is None:  # 入口缺失（菜单未渲染或页面结构变化）。
            raise WaitFailedException("未找到挑战入口")  # 抛异常由 try_step 恢复。
        # wait_confirm 覆盖小人到达窗口（_SD_ARRIVE_TIMEOUT），time_out 留出补点预算。
        try:  # 点击入口并确认进入挑战页。
            self.transition("event_challenge_page", box=entry, wait_confirm=_SD_ARRIVE_TIMEOUT,
                            time_out=_SD_ARRIVE_TIMEOUT * 2, after_sleep=2)
        except WaitFailedException:  # 补点耗尽仍未进挑战页。
            if not self.is_screen("event_main"):  # 落在别的界面：按失败交 try_step 恢复（不看错误页继续猜）。
                raise  # 重新抛出，交给 try_step。
            # 仍在活动菜单页 = 入口点击无效（往期活动/未开放入口：文字可读、点击无响应）：
            # 这里直接结束挑战流程，不再让 try_step 反复重跑（每次都要把补点重来一遍，白等一分多钟）。
            self.log_info("挑战入口点击无效（仍在活动菜单页，可能为锁定/未开放入口），跳过挑战")  # 记录跳过原因。
            return  # 结束挑战流程（已在菜单页，无需收尾导航）。
        self._wait_challenge_nodes()  # 等节点渲染完成再选关（吸收过场动画）。
        stage = self._find_available_challenge_stage()  # 自下而上找第一个可用（非灰白）关卡标记。
        if stage is None:  # 无可用关卡（今日次数已用完/列表未标注）：无需进详情页，直接返回菜单页。
            self._ensure_event_menu()  # 点返回键回活动菜单页。
            return  # 结束挑战流程。
        for attempt in range(1, _CHALLENGE_CLICK_ATTEMPTS + 1):  # 点空时重试（落点每次重新随机取，两次落点不重合）。
            self.click_box(self._challenge_click_box(stage), after_sleep=2)  # 点关卡标记（左移入行主体）进入关卡详情页。
            if self.wait_feature(_SWEEP_CLOSE_FEATURE, time_out=_STAGE_ENTER_TIMEOUT, raise_if_not_found=False):  # 等详情页就位（右上关闭按钮特征）。
                break  # 详情页已就位，继续详情页内的战斗分支。
            if attempt < _CHALLENGE_CLICK_ATTEMPTS:  # 还有剩余尝试次数。
                # 仍在挑战页 = 点击被吃掉/落点无效；已离开挑战页 = 页面开了但关闭按钮特征没认出来（改调 _STAGE_ENTER_TIMEOUT）。
                self.log_info(f"第 {attempt} 次点击挑战关卡未进入详情页"
                              f"（仍在挑战页={self.is_screen('event_challenge_page')}），重试")  # 记录重试原因与落点状态。
        else:  # 尝试次数用尽仍未进入详情页（正常应进详情页）。
            self.log_warning(f"点击挑战关卡 {_CHALLENGE_CLICK_ATTEMPTS} 次均未进入详情页，结束挑战")  # 记录异常落点供排查。
            self._ensure_event_menu()  # 兜底回菜单页。
            return  # 结束挑战流程。
        quick_box = self._optional_box(_SWEEP_QUICK_BOX)  # 详情页「快速战斗」区域。
        if quick_box is not None and self.is_feature_enabled(quick_box):  # 快速战斗可用：走快速战斗链。
            self._run_quick_battle(quick_box, label="挑战")  # 点快速战斗 → 次数拉满 → 开始 → 等结算 → 点确认。
        else:  # 快速战斗不可用（或区域缺失）：改判普通战斗「战斗」按钮。
            battle_box = self._optional_box(_STAGE_DETAIL_BATTLE_BOX)  # 详情页「战斗」区域。
            if battle_box is not None and self.is_feature_enabled(battle_box):  # 普通战斗可用：进战斗界面等结束。
                self.click_box(battle_box, after_sleep=2)  # 点「战斗」进入战斗界面（可能先播剧情）。
                self._skip_story_if_present()  # 进战斗可能先播剧情：识别并点跳过。
                result, confirm_box = self.wait_battle_finish(time_out=_STORY_BATTLE_TIMEOUT)  # 节流等待战斗结束（只检测不点击）。
                if result is None:  # 等待战斗结束超时。
                    raise WaitFailedException("等待挑战关卡战斗结束超时")  # 抛异常由 try_step 恢复。
                self.log_info(f"挑战战斗结束（{result}）")  # 记录结算结果。
                self.click_box(confirm_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 点结算返回键（回详情页或挑战页）。
            else:  # 快速战斗与普通战斗都不可用 = 当天已挑战过、没有次数。
                self.log_info("挑战快速战斗与普通战斗均不可用（今日已挑战/次数已用完），结束挑战")  # 记录结束原因。
        # 收尾：结算后可能落回详情页，则先关详情页；再点返回键回活动菜单页（挑战页/详情页返回键逐期不同，走三层兜底）。
        if self._detail_page_open():  # 仍在关卡详情页（快速/普通战斗后常见落点）。
            self._close_stage_detail(to_screen="event_challenge_page")  # 关详情页回挑战页。
        self._ensure_event_menu()  # 点返回键回活动菜单页（已在菜单页则 no-op）。

    def _find_available_challenge_stage(self):  # 挑战页自下而上找第一个可用（非灰白）关卡标记，返回其 Box；无可用返回 None。
        list_box = self._optional_box(_CHALLENGE_LIST_BOX)  # 挑战关卡列表区域（定位范围；特征缺失返回 None）。
        if list_box is None:  # 列表区未标注。
            self.log_warning(f"缺少区域特征 {_CHALLENGE_LIST_BOX}，无法定位挑战关卡")  # 记录缺失，便于排查。
            return None  # 无法定位。
        try:  # 关卡标记特征可能尚未标注进 coco。
            stages = self.find_feature(_CHALLENGE_STAGE_FEATURE, box=list_box, limit=0, use_gray_scale=True)  # 灰度匹配全部关卡标记（颜色无关），可用性再走 is_feature_enabled。
        except ValueError:  # 特征缺失。
            self.log_warning(f"缺少特征 {_CHALLENGE_STAGE_FEATURE}，无法定位挑战关卡")  # 记录缺失，便于排查。
            return None  # 无法定位。
        self.log_debug(f"挑战关卡标记命中 {len(stages)} 个：{[(s.x, s.y) for s in stages]}")  # 命中明细便于实机校准。
        for stage in sorted(stages, key=lambda item: item.y, reverse=True):  # 自下而上（y 由大到小）逐个判态。
            if self.is_feature_enabled(stage):  # 非灰白 = 可用关卡。
                self.log_info(f"挑战选中可用关卡标记 {stage}")  # 记录选中目标。
                return stage  # 返回第一个可用的（自下而上最近）。
        self.log_info("挑战列表全部关卡标记均为灰白禁用态（今日次数已用完）")  # 记录无可打原因。
        return None  # 无可用关卡。

    def _challenge_click_box(self, stage):  # 关卡标记 -> 点击框：标记贴行右边缘，沿 X 轴随机左移落进行主体。
        low = int(self.width * _CHALLENGE_CLICK_X_OFFSET[0])  # 左移量下限（像素）。
        high = int(self.width * _CHALLENGE_CLICK_X_OFFSET[1])  # 左移量上限（像素）。
        offset = random.randint(low, high) if high > low else low  # 区间随机取偏移（分辨率过小时退化为定值）。
        box = Box(stage.x - offset, stage.y, stage.width, stage.height,  # 同尺寸左移，不改写原命中框。
                  confidence=stage.confidence, name=stage.name)
        self.log_debug(f"挑战关卡点击框左移 {offset}px：{stage} -> {box}")  # 偏移量便于实机校准落点。
        return box  # 返回落入行主体的点击框。

    def _wait_challenge_nodes(self, time_out=_SD_ARRIVE_TIMEOUT):  # 挑战页过场动画：等关卡节点渲染出来，再多等一会（标题先于节点出现）。
        list_box = self._optional_box(_CHALLENGE_LIST_BOX)  # 挑战关卡列表区域（搜索范围）。
        if list_box is None:  # 区域未标注。
            return  # 交 _find_available_challenge_stage 记日志兜底。
        try:  # 关卡标记特征可能尚未标注进 coco。
            ready = self.wait_until(lambda: bool(self.find_feature(_CHALLENGE_STAGE_FEATURE, box=list_box, limit=0,
                                                                    use_gray_scale=True)),
                                    time_out=time_out, settle_time=_CHALLENGE_PAGE_SETTLE)  # 轮询等节点渲染（灰度匹配）。
        except ValueError:  # 特征缺失。
            ready = False
        if not ready:  # 节点未在窗口内渲染完成。
            self.log_warning("挑战关卡节点未在预期窗口内渲染完成")  # 记录后由 finder 兜底。
