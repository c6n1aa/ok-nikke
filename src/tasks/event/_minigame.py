"""活动内置小游戏流程：进小游戏 → 开局刷分 → 达标快速完成 → 领任务奖励 → 退出回活动菜单页。

小游戏是独立于活动页的整屏实时游戏，入口在活动菜单带（关键词「小游戏」）。关卡内只有两个输入
（点击改攻击与移动方向、必杀技按键），没有可读的胜负信号、只有分数区，故自动化只做「刷到达标分数」：
每 _MINIGAME_TAP_INTERVAL 点一次屏幕中央改向，每 _MINIGAME_SCORE_INTERVAL OCR 一次分数区，
达标即用暂停弹窗的「快速完成」结束本局。流程归属按活动身份查 MINIGAMES：未接入的活动不执行。
"""

import time  # 关卡内实时循环的节拍与单局整体超时。

import cv2  # OpenCV：任务弹窗「全部领取」是否高亮可领的色相判据。

from ok.task.exceptions import WaitFailedException  # 入口缺失 / 界面未就位等流程断言抛出的等待失败异常。

from src.tasks.event._const import (
    MINIGAMES, _MINIGAME_MAIN_SCREEN, _MINIGAME_SELECT_SCREEN, _MINIGAME_PLAY_SCREEN, _MINIGAME_RESULT_SCREEN,
    _MINIGAME_START_ENTRY, _MINIGAME_SELECT_START, _MINIGAME_SCORE_BOX, _MINIGAME_SCORE_PATTERN, _MINIGAME_PAUSE_BOX,
    _MINIGAME_QUICK_FINISH_BOX, _MINIGAME_RESULT_BACK_BOX, _MINIGAME_MISSION_ENTRY, _MINIGAME_MISSION_CLAIM_BOX,
    _MINIGAME_MISSION_CLOSE, _MINIGAME_MISSION_POPUP_SCREEN, _MINIGAME_PAUSE_DIALOG_SCREEN,
    _MINIGAME_EXIT_CONFIRM, _MINIGAME_TAP_POINT, _MINIGAME_TAP_INTERVAL,
    _MINIGAME_SCORE_INTERVAL, _MINIGAME_TARGET_SCORE, _MINIGAME_PLAY_TIMEOUT, _MINIGAME_ENTER_TIMEOUT,
    _MINIGAME_START_TIMEOUT, _MINIGAME_DIALOG_TIMEOUT, _MINIGAME_RESULT_TIMEOUT, _MINIGAME_CLAIM_MAX_CLICKS,
    _MINIGAME_BACK_ATTEMPTS, _MINIGAME_CLAIM_SETTLE, _MINIGAME_EXIT_TIMEOUT,
)


class EventMinigameMixin:
    """活动内置小游戏的执行链（自足重入）。

    入口 → 小游戏主界面 → 选择妮姬页 → 关卡 → 结算页 → 主界面 → 退出，全程整屏界面（非模态弹窗），
    收尾自行退出回活动菜单页，供 _run_event_subflows 接续后面的子流程。
    这一版只做「进游戏到结束游戏 + 领小游戏任务奖励」：不刷名次（分数达标即收工），不等每日奖励。
    """

    def _do_minigame(self):  # 小游戏子流程：开关 → 按活动身份查注册表 → 探测 → try_step。
        if not self.config.get("小游戏"):  # 用户未启用小游戏子流程。
            self.log_info("小游戏未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        flow = self._minigame_flow()  # 当前活动身份对应的小游戏流程方法（未接入 / 身份未知为 None）。
        if flow is None:  # 本期活动没有已接入的小游戏流程。
            return  # 结束本子流程（_minigame_flow 已记跳过原因）。
        if not self._probe_entry("小游戏"):  # 探测不到小游戏入口（该活动没有小游戏）。
            self.log_info("未探测到小游戏入口，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if self._entry_locked_skip("小游戏"):  # 往期活动/未开放入口：文字可读但点击无效。
            return  # 结束本子流程。
        if self.try_step(flow, name="小游戏", raise_on_fail=False):  # 小游戏整体流程用恢复协议包裹（自足重入）。
            self.log_info("小游戏子流程完成")  # 记录完成（不落完成状态：重复游玩不消耗游戏资源）。
        else:  # 恢复重试耗尽。
            self.log_warning("小游戏子流程多次失败，跳过")  # 记录失败原因。

    def _minigame_flow(self):  # 按活动身份取小游戏流程方法；身份未知或该活动未接入返回 None。
        identity = self._event_identity  # 当前活动身份（列表路径权威，接管路径为推断值）。
        if not identity:  # 身份未知（接管路径判不出）：无法确定走哪个活动的小游戏流程。
            self.log_info("活动身份未知，跳过小游戏")  # 记录跳过原因。
            return None  # 不执行。
        method = MINIGAMES.get(identity)  # 该活动身份注册的小游戏流程方法名。
        if not method:  # 该活动未接入小游戏流程（注册表见 _const.MINIGAMES）。
            self.log_info(f"活动 {identity} 未接入小游戏流程，跳过")  # 记录跳过原因。
            return None  # 不执行。
        return getattr(self, method)  # 返回绑定的流程方法。

    # ---- 主流程 ----

    def _flow_minigame(self):  # 小游戏流程（自足重入）：进小游戏 → 开局 → 刷分快速完成 → 领任务奖励 → 退出。
        self._nav_to_event_main()  # 就位活动主页（正常已就位；恢复回大厅后由此重入）。
        if not self._enter_minigame():  # 点「小游戏」入口进小游戏主界面（入口点击无效时直接结束）。
            return  # 结束流程（仍在活动菜单页，无需收尾导航）。
        self._start_minigame_run()  # 主界面 START →（选择妮姬页 START）→ 关卡内。
        if self._play_minigame_run():  # 关卡内实时循环：True = 刷到达标分数（或到游玩上限），本局仍需主动结束。
            self._quick_finish_minigame_run()  # 暂停 → 快速完成（记录目前分数并退出游戏）。
        self._wait_minigame_result()  # 等本局结算页（主动快速完成与本局自然结束共用）。
        self._claim_minigame_missions()  # 结算页返回主界面 → 任务弹窗 → 领已达成奖励 → 关弹窗。
        self._exit_minigame()  # 点返回 → 退出确认 → 回活动菜单页。

    def _enter_minigame(self):  # 点活动菜单「小游戏」入口并确认进入小游戏主界面；入口点不动时返回 False。
        entry = self._entry_box("小游戏")  # 小游戏入口命中框（活动菜单带内）。
        if entry is None:  # 入口缺失（菜单未渲染或页面结构变化）。
            raise WaitFailedException("未找到小游戏入口")  # 抛异常由 try_step 恢复。
        try:  # 点击入口并确认进入小游戏主界面（小游戏是整屏加载，等待窗口比活动子页面长）。
            self.transition(_MINIGAME_MAIN_SCREEN, box=entry, time_out=_MINIGAME_ENTER_TIMEOUT,
                            wait_confirm=_MINIGAME_ENTER_TIMEOUT, after_sleep=2)  # 补点重试由 transition 负责。
        except WaitFailedException:  # 补点耗尽仍未进小游戏。
            if not self.is_screen("event_main"):  # 落在别的界面：按失败交 try_step 恢复（不看错误页继续猜）。
                raise  # 重新抛出，交给 try_step。
            # 仍在活动菜单页 = 入口点击无效（往期活动/未开放入口：文字可读、点击无响应）：
            # 直接结束流程，不再让 try_step 反复重跑（每次都要把补点重来一遍）。
            self.log_info("小游戏入口点击无效（仍在活动菜单页，可能为锁定/未开放入口），跳过小游戏")  # 记录跳过原因。
            return False  # 通知调用方结束流程。
        return True  # 已进入小游戏主界面。

    def _start_minigame_run(self):  # 开启一局：主界面 START →（停留在选择妮姬页则点它的 START）→ 关卡内。
        self.click_box(_MINIGAME_START_ENTRY, after_sleep=2)  # 点主界面 START（进选择妮姬页或直接开局）。
        # 开局路径有两种：出现「选择妮姬」页（选角色 / 特殊技能 / 必杀技键位），或沿用上次配置直接进关卡；
        # 两者都算开始成功，故用「或」判据等其中之一出现。
        if not self.wait_until(lambda: self.is_screen(_MINIGAME_SELECT_SCREEN) or self.is_screen(_MINIGAME_PLAY_SCREEN),
                               time_out=_MINIGAME_START_TIMEOUT, settle_time=0.5):  # 命中后再稳 0.5s，避开切换动画帧。
            raise WaitFailedException("点 START 后未进入选择妮姬页或关卡")  # 抛异常由 try_step 恢复。
        if self.is_screen(_MINIGAME_SELECT_SCREEN):  # 停在选择妮姬页：点页面底部 START 用当前配置开局。
            self.click_box(_MINIGAME_SELECT_START, after_sleep=2)  # 点选择妮姬页 START（不改角色与技能）。
        if not self.wait_until(lambda: self.is_screen(_MINIGAME_PLAY_SCREEN),  # 等关卡内就位（暂停钮可见）。
                               time_out=_MINIGAME_START_TIMEOUT, settle_time=0.5):  # 命中后再稳 0.5s，避开加载画面。
            raise WaitFailedException("点开始后未进入小游戏关卡")  # 抛异常由 try_step 恢复。
        self.log_info("小游戏本局已开始")  # 记录开局。

    def _play_minigame_run(self):  # 关卡内实时循环；返回本局是否仍需主动结束（True = 走快速完成）。
        """点击与判态的节奏不同，故用手写节拍循环而不是 wait_until：

        每轮先判是否还在关卡内（离开即本局自然结束，避免盲点落进别的界面），再点屏幕中央改向
        （点击自带 after_sleep 间隔，不另加 sleep），隔 _MINIGAME_SCORE_INTERVAL 采一次分数区。
        """
        deadline = time.time() + _MINIGAME_PLAY_TIMEOUT  # 单局游玩上限。
        next_score_at = time.time() + _MINIGAME_SCORE_INTERVAL  # 首次分数采样时刻（开局先点几下再采）。
        while time.time() < deadline:  # 节拍循环。
            if not self.is_screen(_MINIGAME_PLAY_SCREEN):  # 已离开关卡：本局自然结束（HP 耗尽进结算页）。
                self.log_info("小游戏本局已自然结束（已离开关卡），按结算页收尾")  # 记录结束方式。
                return False  # 无需快速完成。
            self.click_relative(*_MINIGAME_TAP_POINT, after_sleep=_MINIGAME_TAP_INTERVAL)  # 点屏幕中央改攻击与移动方向。
            self.next_frame()  # 点击会清空当前帧，判态与 OCR 前重新抓帧。
            if time.time() < next_score_at:  # 未到分数采样时刻。
                continue  # 继续点。
            next_score_at = time.time() + _MINIGAME_SCORE_INTERVAL  # 排下一次采样。
            score = self._minigame_score()  # OCR 分数区取当前分数。
            self.log_info(f"小游戏当前分数 {score}（达标线 {_MINIGAME_TARGET_SCORE}）")  # 记录进度便于实机观察。
            if score is not None and score >= _MINIGAME_TARGET_SCORE:  # 刷到达标分数。
                return True  # 走快速完成结束本局。
        self.log_warning(f"小游戏单局游玩达到上限 {_MINIGAME_PLAY_TIMEOUT} 秒仍未达标，按当前分数快速完成")  # 记录超时。
        return True  # 仍在对局中就主动结束（比留着半局被恢复流程打断干净）。

    def _minigame_score(self):  # OCR 分数区取当前分数；区域缺失或识别不到数字返回 None。
        box = self._optional_box(_MINIGAME_SCORE_BOX)  # 分数区（coco 区域特征）。
        if box is None:  # 区域未标注（coco 版本不符）。
            self.log_warning(f"缺少区域特征: {_MINIGAME_SCORE_BOX}")  # 记录缺失，便于排查。
            return None  # 无法读分。
        texts = self.ocr(box=box)  # 区域内全部文字（数字可能被拆成多段）。
        text = "".join(text.name for text in texts if isinstance(text.name, str))  # 拼接识别文本。
        matched = _MINIGAME_SCORE_PATTERN.search(text)  # 取其中的数字串（可能带千分位分隔符）。
        return int(matched.group().replace(",", "")) if matched else None  # 去分隔符转整数。

    def _quick_finish_minigame_run(self):  # 结束本局：暂停 → 快速完成（记录目前分数并退出游戏）。
        pause = self._optional_box(_MINIGAME_PAUSE_BOX)  # 关卡右上角暂停钮（ESC）。
        if pause is None:  # 区域未标注（coco 版本不符）。
            raise WaitFailedException(f"缺少区域特征: {_MINIGAME_PAUSE_BOX}")  # 抛异常由 try_step 恢复。
        self.click_box(pause, after_sleep=3)  # 点暂停钮弹出「暂停」弹窗（3 秒等开启动画走完，再点「快速完成」）。
        if not self.wait_until(lambda: self.is_screen(_MINIGAME_PAUSE_DIALOG_SCREEN),  # 等暂停弹窗就位（弹窗关闭钮可见）。
                               time_out=_MINIGAME_DIALOG_TIMEOUT, settle_time=1):  # 命中后再稳 1s，吸收弹窗开启动画。
            raise WaitFailedException("小游戏暂停弹窗未在预期时间内出现")  # 弹窗没开就不盲点：交 try_step 恢复。
        self.click_box(_MINIGAME_QUICK_FINISH_BOX, after_sleep=1)  # 点「快速完成」：记录目前分数并退出本局。
        self.log_info("已按快速完成结束本局")  # 记录结束方式。

    def _back_to_minigame_main(self):  # 结算页「返回」→ 小游戏主界面；结算动画期间点击会被吃掉，故带补点。
        for attempt in range(1, _MINIGAME_BACK_ATTEMPTS + 1):  # 尝试次数封顶（点完仍停在结算页就再来一次）。
            self.click_box(_MINIGAME_RESULT_BACK_BOX, after_sleep=2)  # 点结算页「返回」（2 秒覆盖转场与结算动画）。
            if self.wait_until(lambda: self.is_screen(_MINIGAME_MAIN_SCREEN),  # 等主界面回来（左上标题栏可见）。
                               time_out=_MINIGAME_DIALOG_TIMEOUT, settle_time=0.5):  # 命中后再稳 0.5s。
                return  # 已回到小游戏主界面。
            if attempt < _MINIGAME_BACK_ATTEMPTS:  # 还有剩余尝试次数。
                self.log_info(f"第 {attempt} 次点结算页「返回」未回到小游戏主界面（结算动画可能吃掉点击），补点")  # 记录补点原因。
        raise WaitFailedException(f"小游戏结算页「返回」连续 {_MINIGAME_BACK_ATTEMPTS} 次未回到主界面")  # 抛异常由 try_step 恢复。

    def _claim_minigame_missions(self):  # 结算页收尾与任务奖励领取。
        self._back_to_minigame_main()  # 点结算页「返回」回小游戏主界面（结算动画吃掉点击时自动补点）。
        self._close_claim_overlay(time_out=2)  # 领奖遮罩非必现（每日奖励可能弹）：有就清掉，别挡住任务入口。
        self._wait_click_feature(_MINIGAME_MISSION_ENTRY, "小游戏任务入口")  # 点左侧「任务」图标弹出任务弹窗。
        if not self.wait_until(lambda: self.is_screen(_MINIGAME_MISSION_POPUP_SCREEN),  # 等任务弹窗就位（弹窗关闭钮可见）。
                               time_out=_MINIGAME_DIALOG_TIMEOUT, settle_time=1):  # 命中后再稳 1s，吸收弹窗开启动画。
            self.log_warning("小游戏任务弹窗未在预期时间内出现，跳过领取")  # 弹窗没开就无需关闭：领取整体跳过。
            return  # 结束领取（仍在主界面，退出流程照走）。
        self._claim_minigame_mission_rewards()  # 领已达成的小游戏任务奖励。
        self._wait_click_feature(_MINIGAME_MISSION_CLOSE, "小游戏任务弹窗关闭钮")  # 点右上关闭钮回主界面。

    def is_box_highlighted(self, box, hue_low=32, hue_high=80, sat_floor=50, ratio=0.5, after_sleep=0):
        """判断 box 区域是否为高亮彩色态（小游戏任务「全部领取」：可领为亮黄、不可领为暗棕）。

        两态是换色不是换形：互相匹配得 0.718 / 0.724，离默认阈值 0.8 只差 0.08，模板匹配区分不开；
        亮度判据也无效（两态 V>200 像素占比均为 1.0）。两态差别在色相（实测不可领约 20 度、
        可领约 45 度），故统计框内落在色相带内的像素占比：720p~1440p、亮度 ±30/60、
        对比度 ×0.8/1.2、gamma 0.8 下不可领恒 0.000、可领恒 1.000。无帧 / 区域越界时保守返回 False。
        """
        frame = self.frame  # 取当前帧；无帧（如单测 mock）时无法判态。
        if frame is None:  # 无帧可判。
            if after_sleep > 0:  # 参考框架 click 等方法的 after_sleep 实现：判断后等待。
                self.sleep(after_sleep)  # 等待指定时间。
            return False  # 保守返回非高亮。
        x1, y1 = max(box.x, 0), max(box.y, 0)  # 裁剪 box 左上角到帧范围内。
        x2, y2 = min(box.x + box.width, frame.shape[1]), min(box.y + box.height, frame.shape[0])  # 裁剪右下角。
        if x2 <= x1 or y2 <= y1:  # 区域越界无效。
            if after_sleep > 0:  # 参考框架实现。
                self.sleep(after_sleep)  # 等待指定时间。
            return False  # 保守返回非高亮。
        roi = frame[y1:y2, x1:x2, :3]  # 取 box 区域子图。
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)  # 转 HSV，按色相判态。
        mask = cv2.inRange(hsv, (round(hue_low / 2), sat_floor, 0), (round(hue_high / 2), 255, 255))  # 色相带 + 饱和度下限掩码。
        hit = cv2.countNonZero(mask) / mask.size  # 命中像素占比（0~1）。
        if after_sleep > 0:  # 参考框架 click/send_key 的 after_sleep 实现。
            self.sleep(after_sleep)  # 等待指定时间。
        return hit >= ratio  # 达到占比阈值即视为高亮态。

    def _claim_minigame_mission_rewards(self):  # 点「全部领取」领已达成的小游戏任务奖励，按钮转暗棕即结束。
        for _ in range(_MINIGAME_CLAIM_MAX_CLICKS):  # 次数上限保护（两段式领取留余量，点击未生效时不死循环）。
            claim = self._optional_box(_MINIGAME_MISSION_CLAIM_BOX)  # 弹窗底部「全部领取」按钮区域。
            if claim is None:  # 区域未标注（coco 版本不符）。
                self.log_warning(f"缺少区域特征: {_MINIGAME_MISSION_CLAIM_BOX}，跳过小游戏任务领取")  # 记录缺失。
                return  # 结束领取。
            if not self.is_screen(_MINIGAME_MISSION_POPUP_SCREEN):  # 弹窗已不在（遮罩误点关掉了）。
                # 按钮区域是固定坐标，弹窗没了再点就是盲点主界面，故每轮先确认弹窗还在。
                self.log_info("小游戏任务弹窗已不在，停止领取")  # 记录结束原因。
                return  # 结束领取。
            if not self.is_box_highlighted(claim):  # 色相判态：亮黄 = 仍有可领，暗棕 = 已领完（未达成项本来也点不动）。
                self.log_info("小游戏任务奖励已无可领取（「全部领取」为暗棕非高亮态）")  # 记录结束状态。
                return  # 结束领取。
            self.click_box(claim, after_sleep=_MINIGAME_CLAIM_SETTLE)  # 点击全部领取（未达成的项不发放，安全）。
            self.log_info("已点击小游戏任务「全部领取」")  # 记录动作。
            self._close_claim_overlay(time_out=2)  # 领奖遮罩非必现：每轮趁此清掉。
        self.log_warning(f"小游戏任务奖励领取点击达到上限 {_MINIGAME_CLAIM_MAX_CLICKS}，停止领取")  # 上限耗尽，记录异常。

    def _exit_minigame(self):  # 退出小游戏回活动菜单页：返回 → 「确定要退出小游戏吗？」确认。
        back = self._find_back_button()  # 小游戏左下角「返回」（基类三层兜底：模板 → 左下角区域 → OCR「返回」）。
        if back is None:  # 三层都未命中（按钮被遮挡 / 页面结构变化）。
            raise WaitFailedException("未找到小游戏返回按钮")  # 抛异常由 try_step 恢复。
        self.click_box(back, after_sleep=1)  # 点返回，弹出退出确认框。
        self._wait_click_feature(_MINIGAME_EXIT_CONFIRM, "退出小游戏确认框「确认」")  # 确认框就位即点「确认」。
        if not self.wait_until(lambda: self.is_screen("event_main"),  # 等回活动菜单页（活动页标题可见）。
                               time_out=_MINIGAME_EXIT_TIMEOUT, settle_time=0.5):  # 命中后再稳 0.5s，避开过场。
            raise WaitFailedException("退出小游戏后未回到活动菜单页")  # 抛异常由 try_step 恢复。
        self.log_info("已退出小游戏，回到活动菜单页")  # 记录退出。

    def _wait_minigame_result(self):  # 等本局结算页出现（主动快速完成与本局自然结束共用）。
        if self.wait_until(lambda: self.is_screen(_MINIGAME_RESULT_SCREEN),  # 轮询 GAME OVER 标题特征。
                           time_out=_MINIGAME_RESULT_TIMEOUT, settle_time=1):  # 命中后再稳 1s，吸收结算动画。
            self.log_info("小游戏本局结算页已就位")  # 记录结算页就位。
            return  # 继续收尾。
        raise WaitFailedException("小游戏本局结束后未出现结算页")  # 抛异常由 try_step 恢复。

    def _wait_click_feature(self, feature, label, time_out=_MINIGAME_DIALOG_TIMEOUT):  # 等特征出现即点击（模态框内按钮共用）。
        try:  # 特征名可能尚未标注进 coco（旧 assets）。
            self.wait_click_feature(feature, time_out=time_out, raise_if_not_found=True,
                                    settle_time=0.5, after_sleep=1)  # 命中后再稳 0.5s，避开弹窗开启动画。
        except ValueError:  # 特征缺失（coco 版本不符）。
            raise WaitFailedException(f"缺少特征: {feature}（{label}）")  # 转成可恢复的等待失败，交 try_step 统一处理。
        self.log_info(f"已点击{label}")  # 记录动作。
