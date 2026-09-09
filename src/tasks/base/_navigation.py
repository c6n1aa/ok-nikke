import re  # 正则模块，用于进入游戏提示文字的部分匹配。
import time  # 时间模块，处理导航等待与超时。

from ok.task.exceptions import TaskDisabledException, WaitFailedException  # 任务被停止与等待失败异常。


class NavigationMixin:
    """守卫式导航 + 失败恢复 + 冷启动引导：大厅就位、入口转换、回大厅与单步恢复协议。"""

    _ENTER_GAME_TEXT = re.compile("TOUCH TO CONTINUE", re.IGNORECASE)  # 进入游戏提示文字，OCR 部分匹配并忽略大小写。

    def wait_for_lobby(self, time_out=120, raise_if_not_found=True):
        """等待游戏大厅出现，通过识别大厅中的方舟按钮(ark)判断是否已进入游戏大厅。

        各子任务在点击自己的入口前应先调用本方法，避免游戏仍在加载/登录页
        时就按大厅坐标点击，导致后续特征查找超时。time_out 默认 120 秒。
        """
        self.bring_game_to_front()  # 先把游戏窗口切到前台，确保 pynput 点击生效。
        return self.wait_feature("ark", time_out=time_out, raise_if_not_found=raise_if_not_found)

    def _find_home_button(self):
        """查找大厅按钮：先按标注位置（默认 variance 容差）匹配，未命中再在屏幕左下角区域内全范围模板匹配兜底。

        咨询等界面的 home/back 按钮坐标与其他界面有数像素偏差，超出默认容差导致
        特征锚点匹配失败；兜底区域限定左下角，避免误命中画面中部元素。
        """
        home = self.find_one("common_home")  # 标注位置精确匹配。
        if home is not None:  # 精确命中。
            return home  # 直接返回。
        return self.find_one("common_home",
                             box=self.box_of_screen(0, 0.8, 0.25, 1))  # 兜底：左下角区域（按钮锚点在 y≈0.93，覆盖 ±0.02 以上偏移）。

    def _find_back_button(self):
        """查找返回按钮：先按标注位置（默认 variance 容差）匹配，未命中再在屏幕左下角区域内全范围模板匹配兜底。

        咨询详情等界面的 home/back 按钮坐标与其他界面有数像素偏差，超出默认容差导致
        特征锚点匹配失败；兜底区域限定左下角，避免误命中画面中部元素。
        """
        back = self.find_one("common_back")  # 标注位置精确匹配。
        if back is not None:  # 精确命中。
            return back  # 直接返回。
        return self.find_one("common_back",
                             box=self.box_of_screen(0, 0.8, 0.25, 1))  # 兜底：左下角区域（按钮锚点在 y≈0.9，覆盖偏移）。

    def _exit_to_lobby(self):
        """退出当前子页面返回大厅（幂等：失败恢复已带回大厅时找不到主页按钮，只确认不点击）。

        好感度升级等遮罩常在回到详情页后约 0.5~1 秒才延迟弹出，时机不可预测，「点击前清理」
        拦不住；改为结果导向：点击主页按钮后确认回到大厅，未确认则清理吞点击的遮罩后补点一轮。
        """
        for attempt in range(2):  # 首轮直点；未确认回大厅则清理遮罩弹窗后补点一轮。
            home = self._find_home_button()  # 查找大厅按钮（含左下角区域兜底）。
            if home is not None:  # 找到则点击返回大厅。
                self.click_box(home, after_sleep=1)  # 点击大厅按钮并等待。
            if self.wait_for_lobby(time_out=10, raise_if_not_found=False):  # 已确认回到大厅。
                return  # 成功收尾。
            if attempt == 0:  # 首轮未确认：点击可能被延迟弹出的遮罩吞掉。
                self.log_warning("返回大厅未确认，清理弹窗后重试")  # 暴露遮罩吞点击的异常路径。
                self.dismiss_all_popups(wait_for_popup=False, time_out=5)  # 清理遮罩后进入补点轮。
        self.log_warning("返回大厅两轮仍未确认，交由上层恢复兜底")  # 保持静默语义，但留下诊断日志。

    def _click_enter_game(self):
        """在 coco 特征 box_enter_game 区域内 OCR 识别 TOUCH TO CONTINUE 并点击进入游戏，返回是否点击。"""
        try:
            enter_box = self.get_box_by_name("box_enter_game")  # 获取 coco 标注的进入游戏文字区域（已按当前分辨率缩放）。
        except ValueError:  # coco 特征缺失等异常情况，视为未命中。
            return False
        if enter_box is None:  # 当前帧该区域不可用。
            return False
        matches = self.ocr(box=enter_box, match=self._ENTER_GAME_TEXT)  # 在区域内 OCR 匹配进入游戏文字（正则部分匹配）。
        if not matches:  # 当前帧未识别到目标文字。
            return False
        self.click_box(matches[0], after_sleep=1)  # 点击进入游戏按钮（命中识别框中心）并等待响应。
        self.log_info("已点击 TOUCH TO CONTINUE 进入游戏。")  # 记录点击动作。
        return True  # 返回成功。

    def wait_until_lobby_after_start(self, time_out=180):
        """点击任务开始后确保进入游戏大厅：已在大厅直接返回 True；否则循环关闭公告/活动弹窗并点击 TOUCH TO CONTINUE，直到确认大厅或超时。"""
        if self.is_screen("lobby"):  # 单帧检测当前是否已在大厅。
            self.log_info("已在大厅，跳过游戏启动流程。")  # 记录无需等待。
            return True
        self.log_info("游戏尚未进入大厅，开始等待加载完成。")  # 记录开始等待。
        deadline = time.time() + time_out  # 记录整体超时时刻。
        while time.time() < deadline:  # 循环直到超时。
            self.next_frame()  # 刷新一帧，避免使用旧帧。
            if self.is_screen("lobby"):  # 当前帧已进入大厅（可能在弹窗遮挡下提前出现）。
                self.sleep(1)  # 等待大厅界面完全加载，避免漏关延迟弹出的弹窗。
                self.dismiss_all_popups(clear_condition=lambda: self.is_screen("lobby"), time_out=10)  # 统一清理进入游戏后可能残留的公告/活动弹窗。
                self.log_info("已进入游戏大厅。")  # 记录到达大厅。
                return True
            self.dismiss_all_popups(wait_for_popup=False, time_out=10)  # 统一清理 loading 阶段可能弹出的公告/活动弹窗与领取奖励遮罩，无弹窗时立即返回。
            self._click_enter_game()  # 识别并点击 TOUCH TO CONTINUE 进入游戏。
            self.sleep(1)  # 等待界面变化后进入下一轮。
        self.save_failure_screenshot("wait_until_lobby_after_start")  # 超时保存现场截图便于排查。
        self.log_warning(f"等待进入游戏大厅超时（{time_out}秒）。")  # 记录超时原因。
        return False  # 返回失败，由调用方决定是否中止后续流程。

    def _back_through_screens(self, *screens):
        """退出子页面逐级返回原语：每级点击 common_back 后断言到达的界面。

        Args:
            *screens: 沿途依次经过的界面名（须已注册），最后一个是最终目标；
                例如子页面→竞技场→方舟传 ("arena", "ark")，单级返回只传 ("ark",)。
        """
        for screen in screens:  # 逐级返回：先点返回再确认到达该级界面。
            self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 点击返回按钮。
            self.assert_screen(screen)  # 断言已到达该级界面，超时抛 WaitFailedException 由 try_step 恢复。

    def transition(self, to_screen, click_feature=None, box=None, click=None,
                   time_out=10, wait_confirm=3, retry_click=2, after_sleep=1):
        """守卫式转换原语：点击入口 → 等待目标界面 → 未命中原地补点 → 带上下文抛错。

        就地消化「动画期吞点击」这类瞬时故障，避免一次误点触发整段回大厅重跑；
        重试耗尽后保存失败现场并抛 WaitFailedException（消息含目标界面与当前
        识别结果），由外层 try_step 捕获恢复。战斗结算确认等非典型边不使用本原语。

        Args:
            to_screen: 目标界面名（须已注册）。
            click_feature: 点击的 coco 特征名，走 wait_click_feature（raise_if_not_found=True）。
            box: 点击的框/区域/区域特征名，走 click_box；与 click_feature 二选一。
            click: 自定义无参可调用对象；提供时忽略前两者。
            time_out: 点击动作的等待超时（秒），即 wait_click_feature 的 time_out。
            wait_confirm: 每次点击后等待确认的单次超时（秒）；长加载边调大它。
            retry_click: 确认未命中时原地补点的最大次数（总尝试 = 1 + retry_click）。
            after_sleep: 每次点击后的固定等待（秒）。
        """

        def _click_once():  # 单次点击动作：三种形态之一。
            if click is not None:  # 自定义点击。
                click()
            elif click_feature is not None:  # coco 特征入口。
                self.wait_click_feature(click_feature, time_out=time_out,
                                        raise_if_not_found=True, after_sleep=after_sleep)
            elif box is not None:  # 框/区域入口。
                self.click_box(box, after_sleep=after_sleep)
            else:
                raise ValueError("transition 需要提供 click_feature/box/click 之一")

        deadline = time.time() + time_out  # 整个转换的总预算。
        for attempt in range(1 + max(0, retry_click)):  # 首次点击 + 至多 retry_click 次补点。
            if attempt > 0 and time.time() >= deadline:  # 总超时后不再补点。
                break
            _click_once()
            remain = max(1, int(deadline - time.time()))  # 确认等待不超过总预算剩余。
            if self.wait_screen(to_screen, time_out=min(wait_confirm, remain)):
                return True  # 已进入目标界面。
            self.log_info(f"transition: {to_screen} 未确认（第 {attempt + 1} 次尝试），原地重试。")
        self.save_failure_screenshot(to_screen)  # 重试耗尽，保存失败现场截图。
        current = self.current_screen()  # 识别当前界面作为异常上下文。
        self.log_warning(f"界面转换失败: 目标 {to_screen}，当前 {current}")  # 记录失败。
        raise WaitFailedException(f"transition to {to_screen} failed (current: {current})")

    def ensure_screen(self, name: str, wait_enter=5, entry=None, raise_on_fail=True, **transition_kwargs) -> bool:
        """幂等进入指定界面的统一闸门：已在（或正在进入）目标界面则直接返回；
        否则先按「正向命中登录页 / 应用内证据 / 无任何证据」分流——登录页与无证据
        走冷启动引导（wait_until_lobby_after_start），应用内走恢复回大厅——就位后：
        有点击源则经 transition 守卫式进入目标，无点击源（目标即锚点大厅）则尾部确认。

        子流程入口统一用它代替手写的「is_screen 短路 + 等大厅 + 点入口」序列；
        任务开头的就位大厅同理（`ensure_screen("lobby")`——大厅没有指向自己的点击边，
        它的「入口」是清弹窗 + 点 TOUCH TO CONTINUE 这段冷启动程序化流程，就是第 3 段）。
        内置过场动画容忍（短轮询而非单帧判定）与误分类护栏——单帧判定撞上过场动画、
        且目标页又无返回/主页按钮时，旧式序列会把应用内页面误判为冷启动而空等大厅。

        Args:
            name: 目标界面名（须在 SCREENS 注册）。
            wait_enter: 每次等待目标界面的秒数（过场动画容忍窗口，默认 5）。
            entry: 可选入口解析器（callable → Box | 特征名 str | None）。返回 None
                表示入口不存在（如当期限时玩法已结束）——此时本方法返回 False，
                由调用方决定「视为已完成」等收尾。解析器在进入大厅之后才调用。
            raise_on_fail: True（默认）失败抛 WaitFailedException（供 try_step 恢复）；
                False 时返回 False（任务开头等优雅中止调用点用）。
            transition_kwargs: 透传给 transition（click_feature/box/click、time_out、
                wait_confirm、retry_click、after_sleep）。entry 返回 Box 时自动作为
                box= 传入，返回 str 时作为 click_feature= 传入。

        Returns:
            True 已进入目标界面；False = 入口缺失（entry 返回 None）或
                raise_on_fail=False 时失败。
        Raises:
            WaitFailedException: raise_on_fail=True 且恢复回大厅 / 冷启动等待 / 进入目标界面失败。
        """
        if self.wait_screen(name, time_out=wait_enter):  # 已在目标界面或正在过场：轮询容忍滑入动画。
            return True  # 无需导航。
        self.dismiss_all_popups(wait_for_popup=False, time_out=10)  # 弹窗可能遮挡目标界面特征。
        if self.wait_screen(name, time_out=wait_enter):  # 清弹窗后已在目标界面。
            return True  # 无需导航。
        if self.is_screen("login_page"):  # 正向命中登录页：明确冷启动入口，覆盖应用内推定，跳过恢复动作。
            in_app = False
        elif self.find_one("common_back") is not None or self.find_one("common_home") is not None:  # 存在返回/主页按钮：处于应用内其它界面。
            in_app = True
        else:  # 无按钮：再靠全局分类区分「应用内已注册界面」与「无证据」（登录页命中不计入——它本身就是冷启动入口）。
            current = self.current_screen()  # 帧级缓存，本轮内不重复匹配。
            in_app = current is not None and current != "login_page"
        if in_app:  # 处于应用内其它界面：走统一失败恢复协议回大厅，再重进。
            # 页面可能正处于过场动画、该帧上返回/主页按钮尚未出现（实机事故：企业塔收尾返回方舟的过场），仅靠按钮检测会把它误判成冷启动。
            if not self._recover_to_lobby():
                if raise_on_fail:
                    raise WaitFailedException("未能回到游戏大厅")
                return False
        elif not self.wait_until_lobby_after_start():  # 登录页或无任何应用内证据：冷启动/加载中，走引导流程。
            if raise_on_fail:
                raise WaitFailedException("未能进入游戏大厅")
            return False
        self.dismiss_all_popups(wait_for_popup=False, time_out=10)  # 统一清理大厅残留弹窗。
        if entry is not None:  # 入口解析器（进入大厅之后才解析）。
            resolved = entry()  # 解析入口位置。
            if resolved is None:  # 入口缺失（如限时玩法已结束）。
                return False  # 交由调用方收尾。
            if isinstance(resolved, str):  # 解析结果是特征名。
                transition_kwargs["click_feature"] = resolved  # 作为特征点击。
            else:  # 解析结果是 Box。
                transition_kwargs["box"] = resolved  # 作为框点击。
        if not any(k in transition_kwargs for k in ("click_feature", "box", "click")):
            # 无点击源：目标即锚点大厅——其入口是第 3 段的就位/冷启动流程而非点击边，尾部只做确认。
            if not self.wait_screen(name, time_out=5):
                self.save_failure_screenshot(name)  # 保存现场便于排查。
                if raise_on_fail:
                    raise WaitFailedException(f"ensure_screen {name} 尾部确认失败 (current: {self.current_screen()})")
                return False
            return True
        try:
            self.transition(name, **transition_kwargs)  # 守卫式进入目标界面。
        except WaitFailedException:
            if raise_on_fail:
                raise
            return False
        return True  # 已进入目标界面。

    def _recover_to_lobby(self, time_out=30) -> bool:
        """失败恢复协议：刷新帧 → 关遮罩 → 按 common_home 回大厅 → 等待大厅确认。

        子任务可覆盖本方法追加自己的恢复动作。返回是否已回到大厅。
        """
        try:
            self.next_frame()  # 刷新一帧后再判断，避免用到异常前的旧帧。
        except Exception as e:  # 无可用帧时忽略。
            self.log_warning(f"recover next_frame failed: {e}")  # 记录帧刷新失败。
        try:
            self.dismiss_all_popups(clear_condition=lambda: self.is_screen("lobby"), time_out=10)  # 先统一清理可能遮挡后续操作的弹窗，容错：没有弹窗也继续恢复。
        except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
            raise  # 重新抛出，交由执行器结束任务，避免恢复流程变成停不下来的僵尸任务。
        except Exception as e:  # 清理弹窗异常不中断恢复。
            self.log_warning(f"recover dismiss_all_popups failed: {e}")  # 记录清理弹窗失败。
        if self.is_screen("lobby"):  # 已在大厅则无需额外操作。
            return True  # 恢复成功。
        try:
            if self.feature_exists("common_home"):  # 存在大厅按钮特征则点击回大厅。
                home = self._find_home_button()  # 查找大厅按钮（含左下角区域兜底，覆盖咨询等按钮坐标偏移的界面）。
                if home is not None:  # 找到才点击。
                    self.click_box(home, after_sleep=1)  # 点击大厅按钮返回大厅。
        except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
            raise  # 重新抛出，交由执行器结束任务。
        except Exception as e:  # 回大厅操作异常不中断恢复。
            self.log_warning(f"recover common_home failed: {e}")  # 记录回大厅失败。
        return self.wait_for_lobby(time_out=time_out, raise_if_not_found=False)  # 等待确认回到大厅。

    def try_step(self, step_fn, name: str = None, retries: int = 2, recover: bool = True,
                 raise_on_fail: bool = True) -> bool:
        """以恢复协议执行单步：失败截图存档 → 恢复回大厅 → 有限重试。

        Args:
            step_fn: 步骤函数，内部导航失败时以 raise_if_not_found=True 抛 WaitFailedException。
            name: 步骤名，用于日志与截图文件名。
            retries: 失败后的重试次数（默认 2，即总共尝试 3 次）。
            recover: 每次失败后是否先恢复回大厅再重试。
            raise_on_fail: 重试耗尽后是否抛异常；False 则记录并返回 False。
        Returns:
            True 成功；False 失败且 raise_on_fail=False。
        """
        tag = name or getattr(step_fn, "__name__", "step")  # 步骤标识，用于日志与截图。
        for attempt in range(1, retries + 2):  # 首次执行加上重试次数。
            try:
                step_fn()  # 执行步骤。
                return True  # 成功直接返回。
            except WaitFailedException as e:  # 仅捕获等待失败类异常。
                self.save_failure_screenshot(tag)  # 保存失败现场截图。
                self.log_warning(f"步骤 {tag} 第 {attempt}/{retries + 1} 次失败: {e}")  # 记录本次失败。
                if attempt > retries:  # 已用完全部尝试次数。
                    break  # 结束重试循环。
                if recover:  # 需要恢复后再重试。
                    if not self._recover_to_lobby():  # 恢复回大厅失败。
                        self.log_warning(f"步骤 {tag} 恢复回大厅失败，放弃重试。")  # 记录放弃原因。
                        break  # 恢复失败则不再重试。
                self.sleep(1)  # 刷新一帧后进入下次尝试。
        if raise_on_fail:  # 配置为重试耗尽后抛异常。
            raise WaitFailedException(f"步骤 {tag} 多次失败后放弃")  # 抛出失败异常。
        self.log_warning(f"步骤 {tag} 失败，已跳过。")  # 记录跳过步骤。
        return False  # 返回失败状态。

    def save_failure_screenshot(self, tag: str):
        """保存失败现场截图到 screenshots/failure/，复用框架截图能力。"""
        try:  # 截图失败不应影响主流程。
            self.screenshot(name=f"failure/{tag}")  # 按失败步骤命名截图。
        except Exception as e:  # 截图异常。
            self.log_warning(f"save_failure_screenshot failed: {e}")  # 记录截图失败原因。