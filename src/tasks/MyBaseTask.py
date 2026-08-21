import re  # 正则模块，用于 OCR 文字的部分匹配。

import datetime  # 日期时间模块，处理北京时区与周期刷新。
import os  # 操作系统路径模块，处理 assets/template/ 下模板文件的绝对路径。
import time  # 时间模块，处理超时与等待。

import cv2  # OpenCV，模板缩放匹配使用 cv2.resize / cv2.imread。

from ok import BaseTask
from ok.feature.Box import Box  # 检测框对象，find_red_dot 返回值类型。
from ok.task.exceptions import WaitFailedException  # 界面断言/失败恢复使用的框架等待失败异常。
from ok.util.color import calculate_colorfulness  # 框架颜色工具：计算区域色彩丰富度。

_BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间 UTC+8，无夏令时


class MyBaseTask(BaseTask):
    # NIKKE 刷新规则：日常每天北京时间 04:00，周常每周二刷新。
    _day_reset_hour = 4        # 日常刷新时刻（北京时间，时）
    _week_reset_weekday = 1    # 周常刷新星期（周一=0，周二=1）
    _execution_states_key = "_execution_states"  # 下划线前缀为内部状态，不进 GUI 选项列表

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 注册到 default_config，否则 verify_config 重载时会丢弃非 default 键，状态无法跨重启保留。
        self.default_config[self._execution_states_key] = {}
        # 按 (路径, 缩放比例) 缓存缩放后的模板，避免循环查找时反复读取/缩放。
        self._scaled_template_cache = {}
        # 界面识别注册表：界面名 -> 判定描述（features 为 coco 模板特征，keywords 为 OCR 关键词）。
        self.screens = {}
        # 默认注册大厅界面：以方舟按钮(ark)特征判定已进入游戏大厅。
        self.register_screen("lobby", features=["ark", "lobby"])

    def _now_bj(self) -> datetime.datetime:
        """当前北京时间（带时区）。"""
        return datetime.datetime.now(_BEIJING_TZ)

    def _in_debug(self) -> bool:
        """是否处于 debug 模式（main_debug.py 运行）。"""
        return bool(self.executor.debug)  # debug 模式下返回 True。

    def bring_game_to_front(self):
        """把游戏窗口切换到前台，避免窗口在后台时 pynput 等交互方法静默跳过点击。

        返回 True 表示成功，False 表示失败（此时点击可能不会生效）。
        """
        try:
            hwnd = self.executor.device_manager.hwnd_window  # 获取游戏窗口句柄对象。
            if hwnd is not None and hwnd.hwnd:  # 窗口存在才操作。
                if hwnd.bring_to_front():  # ok 方案成功则返回，失败返回 False。
                    return True  # ok 方案成功。
                self.log_warning("bring_to_front returned False")  # ok 方案失败，记录原因。
        except Exception as e:  # ok 方案抛异常时退化为手动置前。
            self.log_warning(f"bring_to_front failed: {e}")  # 记录 ok 方案的失败原因。
        return self._force_foreground()  # 使用更强的置前兜底。

    def _force_foreground(self):
        """绕过 Windows 前台锁手动把游戏窗口切到前台，返回是否成功。"""
        try:
            import win32con  # 延迟导入，避免测试环境无窗口时失败。
            import win32gui  # Windows 窗口 API。
            import win32process  # 线程/进程 API，用于 AttachThreadInput。
            import win32api  # 获取当前线程 ID。
            hwnd_obj = self.executor.device_manager.hwnd_window  # 获取窗口对象。
            if hwnd_obj is None or not hwnd_obj.hwnd:  # 窗口无效则直接失败。
                self.log_warning("force_foreground: no hwnd")  # 记录窗口缺失。
                return False  # 返回失败。
            hwnd = hwnd_obj.hwnd  # 获取窗口句柄。
            game_thread, _ = win32process.GetWindowThreadProcessId(hwnd)  # 游戏窗口所属线程。
            cur_thread = win32api.GetCurrentThreadId()  # 当前线程 ID。
            attached = False  # 标记是否成功连接线程输入。
            if game_thread != cur_thread:  # 游戏线程与当前线程不同才需要连接。
                try:
                    win32process.AttachThreadInput(cur_thread, game_thread, True)  # 连接到游戏窗口线程，允许抢焦点。
                    attached = True  # 连接成功。
                except Exception:  # 连接失败（权限不足等）。
                    attached = False  # 保持未连接，继续尝试。
            try:
                if win32gui.IsIconic(hwnd):  # 窗口最小化则恢复。
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)  # 恢复窗口。
                win32gui.BringWindowToTop(hwnd)  # 置顶窗口。
                win32gui.SetForegroundWindow(hwnd)  # 设为前台窗口。
            finally:
                if attached:  # 已连接则解除连接。
                    win32process.AttachThreadInput(cur_thread, game_thread, False)  # 断开线程输入连接。
            time.sleep(0.1)  # 等待系统完成焦点切换。
            ok = win32gui.GetForegroundWindow() == hwnd  # 校验切换是否成功。
            self.log_info(f"force_foreground {'ok' if ok else 'failed'}")  # 记录切换结果。
            return ok  # 返回是否成功。
        except Exception as e:  # 任何异常都记录并返回失败。
            self.log_warning(f"force_foreground failed: {e}")  # 记录失败原因。
            return False  # 返回失败。

    def _period_start(self, period: str, now: datetime.datetime) -> datetime.datetime:
        """计算 now 所属周期的起始时刻（按刷新规则）。period: day/week/month"""
        if period == "day":
            start = now.replace(hour=self._day_reset_hour, minute=0, second=0, microsecond=0)
            if now < start:  # 凌晨 0:00-04:00 属于前一个周期
                start -= datetime.timedelta(days=1)
            return start
        if period == "week":
            days_since_reset = (now.weekday() - self._week_reset_weekday) % 7
            start = (now - datetime.timedelta(days=days_since_reset)).replace(
                hour=self._day_reset_hour, minute=0, second=0, microsecond=0)
            if now < start:
                start -= datetime.timedelta(days=7)
            return start
        if period == "month":
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return now

    def is_done(self, key: str, period: str = "day") -> bool:
        """判断 key 在本次周期（day/week/month，按刷新规则）内是否已执行完成。"""
        if self._in_debug():  # debug 模式下不判断已完成，便于反复调试。
            return False  # 跳过完成判断，直接执行。
        states = self.config.get(self._execution_states_key) or {}
        stored = states.get(key)
        if not stored:
            return False
        try:
            stored_dt = datetime.datetime.fromisoformat(stored)
        except (ValueError, TypeError):
            return False
        return self._period_start(period, stored_dt) == self._period_start(period, self._now_bj())

    def mark_done(self, key: str, period: str = "day") -> None:
        """记录 key 在本周期已完成（存当前北京时间，立即落盘到 configs/）。"""
        if self._in_debug():  # debug 模式下不记录已完成状态。
            return  # 不落盘，避免调试时被误判为已完成。
        states = dict(self.config.get(self._execution_states_key) or {})
        states[key] = self._now_bj().isoformat()
        self.config[self._execution_states_key] = states
        self.config.save_file()  # 同键内容更新时 __setitem__ 判定值未变不落盘，需手动保存

    def clear_done(self, key: str) -> None:
        """清除 key 的执行记录，使其在本周期内可重新执行。"""
        states = dict(self.config.get(self._execution_states_key) or {})
        states.pop(key, None)
        self.config[self._execution_states_key] = states
        self.config.save_file()  # 同上，手动保存确保删除立即生效

    def is_completed(self) -> bool:
        """判断任务是否整体已完成：所有完成状态项均已完成。

        UI 据此展示完成图标。无 done_keys 的任务（如纯编排的 DailyTask）
        视为未完成。子类可覆盖以自定义口径（如 ShopTask 只统计开启的子商店）。
        """
        keys = getattr(self, "done_keys", None)  # 子类定义的完成状态映射 {key: period}。
        if not keys:  # 未定义完成状态的任务视为未完成。
            return False  # 返回未完成。
        return all(self.is_done(key, period) for key, period in keys.items())  # 全部完成才算完成。

    def clear_done_all(self) -> None:
        """清除任务所有完成状态记录，使各子流程可重新执行。"""
        for key in getattr(self, "done_keys", {}):  # 遍历所有完成状态键。
            self.clear_done(key)  # 逐个清除完成记录并落盘。

    def wait_for_lobby(self, time_out=120, raise_if_not_found=True):
        """等待游戏大厅出现，通过识别大厅中的方舟按钮(ark)判断是否已进入游戏大厅。

        各子任务在点击自己的入口前应先调用本方法，避免游戏仍在加载/登录页
        时就按大厅坐标点击，导致后续特征查找超时。time_out 默认 120 秒。
        """
        self.bring_game_to_front()  # 先把游戏窗口切到前台，确保 pynput 点击生效。
        return self.wait_feature("ark", time_out=time_out, raise_if_not_found=raise_if_not_found)

    _NOTICE_BELL_TEMPLATES = (  # 公告弹窗铃铛模板列表：公告(notice_bell1)与活动(notice_bell2)弹窗图标样式略有差异，依次尝试任一命中即可。
        os.path.join('assets', 'template', 'common', 'notice_bell1.png'),  # 活动弹窗铃铛模板，来自 2560x1440 截图。
        os.path.join('assets', 'template', 'common', 'notice_bell2.png'),  # 公告弹窗铃铛模板，来自 2560x1440 截图。
    )
    _COMMON_CLOSE_TEMPLATE = os.path.join('assets', 'template', 'common', 'common_close.png')  # 通用关闭按钮模板，来自 2560x1440 截图。
    _ENTER_GAME_TEXT = re.compile("TOUCH TO CONTINUE", re.IGNORECASE)  # 进入游戏提示文字，OCR 部分匹配并忽略大小写。

    def _close_notice_popup(self):
        """在屏幕中上部依次尝试多个公告铃铛模板，命中后向右延伸查找通用关闭按钮并点击，返回是否成功点击。"""
        bell = None  # 初始化铃铛匹配结果。
        for template_path in self._NOTICE_BELL_TEMPLATES:  # 依次尝试每个铃铛模板。
            bell = self.find_scaled_template(  # 在屏幕中上部查找当前铃铛模板。
                "notice_bell", template_path,  # 使用模板并命名匹配结果。
                threshold=0.75,  # 铃铛图标在不同弹窗间样式有差异，阈值放宽到 0.75 提高命中率。
                box=self.box_of_screen(0.258, 0.05, 0.75, 0.5),  # 限定 x 约25.8%-75%（2560x1440 下约 660-1920 像素）、y 5%-50% 的屏幕中上部区域。
            )
            if bell is not None:  # 当前模板命中铃铛。
                break  # 停止尝试后续模板。
        if bell is None:  # 所有模板均未命中，当前帧无公告横幅。
            return False  # 返回未命中，让上层继续后续流程。
        from ok.feature.Box import Box  # 局部导入，用于动态构造关闭按钮搜索区域。
        close_region = Box(  # 从公告横幅右侧延伸到屏幕右边缘作为关闭按钮搜索区域。
            bell.x + bell.width,  # 从铃铛右边缘开始。
            max(0, bell.y - bell.height),  # 上扩一个铃铛高度，允许垂直方向轻微误差。
            self.width - (bell.x + bell.width),  # 水平方向延伸到屏幕右边缘。
            bell.height * 3,  # 垂直范围取铃铛高度的三倍，覆盖同高度附近的关闭按钮。
            name="notice_close_region",  # 搜索区域名称，用于日志/调试。
        )
        close = self.find_scaled_template(  # 在公告横幅右侧查找通用关闭按钮。
            "common_close", self._COMMON_CLOSE_TEMPLATE, box=close_region,  # 仅在右侧区域搜索。
        )
        if close is None:  # 找不到关闭按钮（可能不是公告弹窗）。
            return False  # 返回未命中，跳过本轮关闭。
        self.click_box(close, after_sleep=1)  # 点击关闭按钮并等待弹窗关闭动画完成。
        self.log_info("已关闭公告/活动弹窗。")  # 记录关闭动作。
        return True  # 返回成功，供上层继续检测大厅。

    def _close_rupee_flash_sale_popup(self):
        """处理卢比限时特卖（Rupee Flash Sale）弹窗：优先点关闭确认，否则点入口横幅，返回是否已处理。

        该弹窗为两段式：先出现入口横幅 rupee_flash_sale，点击后弹出详情弹窗，
        需再识别 rupee_flash_sale_close_confirm 点击关闭。每次只处理一步，
        由 dismiss_all_popups 逐轮调用完成整段流程。
        """
        confirm = self.find_one("rupee_flash_sale_close_confirm")  # 优先识别详情弹窗的关闭确认按钮。
        if confirm is not None:  # 详情弹窗已打开。
            self.click_box(confirm, after_sleep=1)  # 点击关闭确认按钮关闭详情弹窗。
            self.log_info("已关闭卢比限时特卖弹窗。")  # 记录关闭动作。
            return True  # 返回已处理。
        banner = self.find_one("rupee_flash_sale")  # 识别限时特卖入口横幅。
        if banner is not None:  # 入口横幅存在。
            self.click_box(banner, after_sleep=1)  # 点击横幅打开详情弹窗，下一轮再关闭。
            self.log_info("已点击卢比限时特卖入口。")  # 记录点击动作。
            return True  # 返回已处理。
        return False  # 当前帧无卢比限时特卖相关界面。

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

    def wait_battle_finish(self, time_out=240, check_interval=2):
        """节流轮询等待自动战斗结束，返回 (结果, 确认按钮框)，不自动点击。

        战斗时长不确定（约10秒~3分钟）：每 check_interval 秒才刷新一帧做单次
        模板匹配，命中结算界面即提前返回；超时返回 (None, None)。避免用
        wait_feature 等忙轮询长时间对游戏窗口持续抓帧/匹配，与游戏抢 CPU。

        正常结束：识别 battle_finish_esc（ESC 确认提示，图标粗壮跨分辨率可靠；
        battle_finish_reward 为细笔画文字，实测在非原生分辨率下缩放后匹配分
        仅约 0.45，不可作为判据）。
        战斗失败：同时识别 battle_finish_failed 与 battle_finish_failed_back。

        此处只检测不点击——战斗结束后的动作由调用方决定（连续战斗的胜利界面
        可能有"下一关"等其它按钮），返回值带上了识别到的确认按钮框，调用方
        需要点击时可直接用它。

        Returns:
            ("success", esc_box) 正常结束，esc 为确认按钮框；
            ("failed", failed_back_box) 战斗失败，failed_back_box 为返回按钮框；
            (None, None) 超时。
        """
        deadline = time.time() + time_out  # 记录整体超时时刻。
        polls = 0  # 轮询计数，用于 debug 日志观察节流间隔。
        while time.time() < deadline:  # 节流循环直到超时。
            self.sleep(check_interval)  # 轻量等待，不抓帧不匹配。
            self.next_frame()  # 刷新一帧，避免使用旧帧。
            polls += 1  # 轮询次数加一。
            self.log_debug(f"战斗轮询第 {polls} 次（每 {check_interval} 秒一帧），已耗时 {time.time() - (deadline - time_out):.0f} 秒。")  # debug 日志确认轮询节奏。
            v_variance = 100 / 1440  # Y 轴上下各扩展约 100 像素（以 2560x1440 为基准的相对比例，随分辨率等比缩放；不同战斗结算界面的 ESC 位置可能上下偏移）。
            esc = self.find_one("battle_finish_esc", vertical_variance=v_variance)  # 纵向扩大搜索范围匹配正常结束确认按钮特征（粗壮图标，跨分辨率可靠）。
            if esc is not None:  # 正常战斗结束。
                self.log_info("检测到战斗胜利结算界面。")  # 记录正常结束。
                return "success", esc  # 返回结果与确认按钮框，由调用方决定后续动作。
            failed = self.find_one("battle_finish_failed")  # 单帧匹配战斗失败特征。
            failed_back = self.find_one("battle_finish_failed_back")  # 单帧匹配失败返回按钮特征。
            if failed is not None and failed_back is not None:  # 战斗失败。
                self.log_info("检测到战斗失败结算界面。")  # 记录失败结束。
                return "failed", failed_back  # 返回结果与返回按钮框，由调用方决定后续动作。
        self.save_failure_screenshot("wait_battle_finish")  # 超时保存现场截图便于排查。
        self.log_warning(f"等待战斗结束超时（{time_out}秒）。")  # 记录超时原因。
        return None, None  # 返回超时结果。

    def find_scaled_template(self, feature_name: str, template_path: str, ref_width: int = 2560,
                             ref_height: int = 1440, **kwargs):
        """读取 assets/template 下的小图模板，按当前游戏分辨率等比缩放后匹配（模板源自 ref_width x ref_height 截图裁剪）。

        Args:
            feature_name: 匹配名，仅用于日志/调试框命名。
            template_path: 模板图片路径，如 'assets/template/notice_bell.jpg'。
            ref_width/ref_height: 模板裁剪时的源截图分辨率，默认 2560x1440。
            其余参数（threshold、box、use_gray_scale 等）透传给 self.find_one。

        Returns:
            Box | None。
        """
        scale = min(self.width / ref_width, self.height / ref_height)  # 等比例缩放，取小者避免超出
        if scale <= 0:  # 分辨率无效（如测试环境无窗口/无帧）时无法缩放，视为未命中。
            return None
        cache_key = (os.path.abspath(template_path), round(scale, 6))
        template = self._scaled_template_cache.get(cache_key)
        if template is None:
            template = cv2.imread(template_path)  # 读取小图模板
            if template is None:
                raise FileNotFoundError(f'template not found: {template_path}')
            if scale != 1:
                # 按当前分辨率等比缩放：缩小用 INTER_AREA，放大用 INTER_LINEAR
                interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
                template = cv2.resize(template, (0, 0), fx=scale, fy=scale, interpolation=interp)
            self._scaled_template_cache[cache_key] = template
        return self.find_one(feature_name, template=template, **kwargs)

    def find_red_dot(self, box, template_path=None, threshold=0.6, min_blob_area=8,
                     ref_width=2560, ref_height=1440) -> Box | None:
        """在指定 box 区域内检测通知红点：模板匹配为主（返回精确位置），颜色检测兜底半透明/样式变体红点。

        红点检测必须限定在 box 区域内，不支持全图扫描（全图颜色检测误检率极高）。
        box 必须是 coco 特征名或 Box 对象，拒绝 None。

        Args:
            box: 搜索区域。coco box 特征名（如 'box_mission_daily_badge'，自动按当前
                分辨率缩放）或 Box 对象（可用 self.box_of_screen 生成相对坐标区域）。
            template_path: 红点模板路径（如 'assets/template/common/badge.png'）。传入时先做
                模板匹配，命中返回精确位置；未命中或未传时用颜色检测兜底。
            threshold: 模板匹配阈值。默认 0.6，低于框架默认 0.8——半透明红点分数
                偏低（实测 0.70-0.73），必须显式传阈值，不能回落默认 0.8。
            min_blob_area: 颜色检测判定红点存在的最小红色连通域面积（默认 8，
                原分辨率红点约 70-95、720p 约 12-20，8 可跨分辨率通用）。
            ref_width/ref_height: 模板裁剪时的源截图分辨率，默认 2560x1440。

        Returns:
            命中返回红点位置 Box（模板命中为精确模板框，颜色兜底为最大红色连通域
            外接框）；未命中返回 None。
        """
        box = self.get_box_by_name(box)  # 解析搜索区域：字符串为 coco 特征名/框架快捷名，Box 原样返回。
        if box is None:  # 区域无效。
            raise ValueError("find_red_dot 必须传入有效的 box 区域")  # 红点检测必须限定区域。
        if template_path is not None:  # 配置了模板则先做模板匹配。
            found = self.find_scaled_template(  # 复用模板缩放+匹配，限定在 box 区域内。
                "red_dot", template_path,  # 匹配命名与模板路径。
                ref_width=ref_width, ref_height=ref_height,  # 模板源截图分辨率。
                box=box, threshold=threshold,  # 限定搜索区域并显式传阈值，避免回落默认 0.8。
            )
            if found is not None:  # 模板命中。
                return found  # 返回模板的精确位置。
        frame = self.frame  # 取当前帧用于颜色检测兜底。
        if frame is None:  # 无帧可做颜色检测。
            return None  # 返回未命中。
        x1, y1 = max(box.x, 0), max(box.y, 0)  # 裁剪 box 左上角到帧范围内。
        x2, y2 = min(box.x + box.width, frame.shape[1]), min(box.y + box.height, frame.shape[0])  # 裁剪右下角。
        if x2 <= x1 or y2 <= y1:  # 区域越界无效。
            return None  # 返回未命中。
        roi = frame[y1:y2, x1:x2]  # 取 box 区域子图。
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)  # 转 HSV 便于提取红色。
        m1 = cv2.inRange(hsv, (0, 40, 40), (12, 255, 255))  # 红色低色相段（0-12°）。
        m2 = cv2.inRange(hsv, (165, 40, 40), (180, 255, 255))  # 红色高色相段（165-180°，色相环绕）。
        mask = cv2.bitwise_or(m1, m2)  # 合并两段红色掩码。
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)  # 提取红色连通域。
        for c in sorted(contours, key=cv2.contourArea, reverse=True):  # 按面积从大到小检查。
            if cv2.contourArea(c) >= min_blob_area:  # 连通域面积达到阈值视为红点。
                cx, cy, cw, ch = cv2.boundingRect(c)  # 取红色连通域外接框。
                from ok.feature.Box import Box  # 局部导入 Box 构造返回值。
                return Box(x1 + cx, y1 + cy, cw, ch, name="red_dot_color")  # 转回帧坐标返回。
        return None  # 无红点返回未命中。

    def is_feature_enabled(self, box: Box, colorfulness_thresh: float = 0.1) -> bool:
        """判断 UI 元素是否处于可用（高亮彩色）状态。

        游戏内可用/禁用按钮常用"高亮彩色 vs 灰白"表达（如无限之塔"进入战斗"蓝色
        可用态 vs 灰色禁用态）。CCOEFF 模板匹配会忽略颜色，无法区分这两种状态；
        此方法用框架的颜色工具计算 box 区域色彩丰富度（RGB 对立轴统计，对灰白压
        得更狠），低于 colorfulness_thresh 视为灰白禁用。

        Args:
            box: 元素所在区域（coco 特征框或模板匹配结果 Box）。
            colorfulness_thresh: 色彩丰富度阈值（0~1），低于则判定为禁用。

        Returns:
            True 可用；False 禁用（灰白）。无帧/区域越界时保守返回 True。
        """
        frame = self.frame  # 取当前帧；无帧（如单测 mock）时保守视为可用。
        if frame is None:  # 无帧可做颜色检测。
            return True  # 返回可用，避免误跳可用功能。
        x1, y1 = max(box.x, 0), max(box.y, 0)  # 裁剪 box 左上角到帧范围内。
        x2, y2 = min(box.x + box.width, frame.shape[1]), min(box.y + box.height, frame.shape[0])  # 裁剪右下角。
        if x2 <= x1 or y2 <= y1:  # 区域越界无效。
            return True  # 保守视为可用。
        roi = frame[y1:y2, x1:x2]  # 取 box 区域子图。
        colorfulness = calculate_colorfulness(roi)  # 用框架颜色工具计算色彩丰富度（0~1）。
        return colorfulness > colorfulness_thresh  # 超过阈值判定为可用。

    def close_overlay(self, keywords=("点击领取奖励",), time_out=5, after_sleep=1, max_clicks=3,
                      require_click=True):
        """点击遮罩窗按钮关闭弹窗，避免后续点击被遮罩拦截。

        在屏幕中下部区域（x 1/3-2/3，y 0.6-1）做 OCR："点击领取奖励"文字
        位于屏幕中央偏下（约 rel_y 0.64），因此 OCR 区域从 y=0.6 开始覆盖，
        每次只点第一个匹配框（同一弹窗的文字阴影会重复命中，不能连点），
        点完继续检测，弹窗连续出现时逐个关闭。遮罩未出现时会一直等到
        time_out 超时，方便处理点击后延迟弹出的遮罩。

        Args:
            keywords: OCR 匹配关键词（支持正则），默认“点击领取奖励”。
            time_out: 等待遮罩出现/关闭的最长时间（秒）。
            after_sleep: 点击后的固定等待时间（秒）。
            max_clicks: 最多连续点击次数，防止异常时死循环。
            require_click: True 时若超时仍未点到任何遮罩则抛 WaitFailedException；
                恢复流程等容错场景应传 False，超时未出现则跳过不报错。
        Returns:
            True 表示至少点击过一次；require_click=False 且未点到时返回 False。
        """
        start = time.time()  # 记录开始时间，用于超时控制。
        clicked = False  # 标记是否至少成功点击过一次。
        clicks = 0  # 统计连续点击次数。
        while time.time() - start < time_out:  # 循环直到超时。
            boxes = self.ocr(x=1 / 3, y=0.6, to_x=2 / 3, to_y=1, match=list(keywords))  # 在中下部区域 OCR 匹配关键词，覆盖位于 rel_y≈0.64 的“点击领取奖励”。
            if boxes:  # 当前仍有遮罩按钮。
                if clicks >= max_clicks:  # 超过最大连续点击次数。
                    self.log_warning(f"遮罩点击 {max_clicks} 次仍存在，停止。")  # 记录异常并停止，避免死循环。
                    break  # 退出循环。
                self.click_box(boxes[0], after_sleep=after_sleep)  # 点击第一个匹配框并等待弹窗响应。
                self.log_info(f"点击遮罩按钮: {keywords}")  # 记录本次点击。
                clicked = True  # 标记已点击过。
                clicks += 1  # 点击次数加一。
                continue  # 继续检测下一个弹窗或确认已关闭。
            if clicked:  # 点过且当前无遮罩，说明弹窗已关闭。
                self.log_info("遮罩已全部关闭。")  # 记录全部关闭完成。
                return True  # 关闭成功，立即返回。
            self.sleep(1)  # 遮罩尚未出现，等待 1 秒后重试直到超时。
        if not clicked:  # 全程未出现遮罩。
            if require_click:  # 明确要求至少关闭一次但未点到。
                raise WaitFailedException(f"未找到遮罩按钮 {keywords}，未能关闭弹窗。")  # 抛出等待失败异常，便于上层 try_step 捕获重试。
            self.log_info("未出现遮罩，跳过。")  # 记录超时未出现。
        return clicked  # 超时或点满次数后返回当前状态。

    def _try_close_one_popup(self, after_sleep=1):
        """尝试关闭当前帧上的一个弹窗：先卢比限时特卖，再公告/活动横幅，最后领取奖励/点击任意处遮罩。返回是否成功关掉一个。

        每次只关一个，由 dismiss_all_popups 循环调用，避免一次点击后界面动画未完成导致误判。
        """
        if self._close_rupee_flash_sale_popup():  # 卢比限时特卖（两段式：入口横幅点击后弹详情，再点关闭确认）。
            return True  # 已处理卢比限时特卖。
        if self._close_notice_popup():  # 公告/活动横幅（右上角铃铛+关闭按钮）。
            return True  # 已关闭横幅弹窗。
        try:  # 遮罩 OCR 异常不应中断统一清理。
            boxes = self.ocr(x=1 / 3, y=0.6, to_x=2 / 3, to_y=1, match=["点击领取奖励", "点击任意处"])  # 中下部区域查找领取奖励/任意处关闭遮罩按钮。
        except Exception as e:  # OCR 失败。
            self.log_warning(f"遮罩 OCR 失败: {e}")  # 记录失败原因。
            return False  # 本帧无遮罩可关。
        if boxes:  # 存在遮罩按钮。
            self.click_box(boxes[0], after_sleep=after_sleep)  # 点击关闭遮罩。
            self.log_info("点击遮罩按钮关闭弹窗。")  # 记录关闭动作。
            return True  # 已关闭一个遮罩。
        return False  # 本帧没有可关闭的弹窗。

    def dismiss_all_popups(self, clear_condition=None, time_out=10, after_sleep=1, max_passes=6,
                           wait_for_popup=True):
        """统一弹窗清理入口：循环关闭卢比限时特卖、公告/活动横幅与领取奖励/点击任意处遮罩等弹窗。

        语义与 close_overlay 一致：点击后弹窗可能延迟出现，因此当前帧无弹窗时
        默认不会立即返回，而是继续等待（wait_for_popup=True，适用于"点击领取后"等
        必出弹窗的场景）；纯入口清理等"可能有弹窗也可能没有"的场景应传
        wait_for_popup=False，无弹窗时立即返回。也可传 clear_condition 等待目标界面。

        Args:
            clear_condition: 可选完成条件（返回 True 表示清理完成/已回到目标界面）；
                优先于其它判断，条件满足即返回。
            time_out: 清理的总超时（秒）。
            after_sleep: 每次点击后的固定等待（秒）。
            max_passes: 最大清理轮数上限，防止异常画面下死循环。
            wait_for_popup: True 时无弹窗也继续等待直到超时（处理延迟弹窗）；
                False 时当前帧无弹窗且未关过任何弹窗则立即返回 True。
        Returns:
            True 清理完成；False 超时且仍有弹窗未能关闭。
        """
        start = time.time()  # 记录开始时间。
        passes = 0  # 统计清理轮数。
        closed_any = False  # 是否至少关闭过一个弹窗。
        while time.time() - start < time_out:  # 循环直到超时。
            passes += 1  # 轮数加一。
            if passes > max_passes:  # 超过轮次上限。
                self.log_warning(f"清理弹窗达到轮次上限（{max_passes}），停止。")  # 记录异常并停止。
                return False  # 返回失败。
            if clear_condition is not None and clear_condition():  # 完成条件已满足。
                return True  # 清理完成。
            if self._try_close_one_popup(after_sleep=after_sleep):  # 关掉了一个弹窗。
                closed_any = True  # 标记已关闭过弹窗。
                try:  # 刷新帧后再继续，避免基于旧帧重复匹配。
                    self.next_frame()  # 获取最新屏幕帧。
                except Exception:  # 无可用帧时忽略。
                    pass  # 继续下一轮。
                continue  # 继续清理剩余弹窗。
            if clear_condition is not None:  # 有完成条件但尚未满足。
                self.sleep(1)  # 等待界面变化后重试。
                continue  # 继续等待。
            if closed_any:  # 关闭过弹窗且当前无弹窗可关。
                return True  # 清理完成。
            if not wait_for_popup:  # 快速清理场景：从未出现过弹窗。
                return True  # 无需清理，立即返回。
            self.sleep(1)  # 弹窗可能尚未出现（点击后延迟），等待出现。
        if closed_any:  # 超时但关闭过弹窗，仍有弹窗残留。
            self.log_warning(f"清理弹窗超时（{time_out}秒）。")  # 记录超时。
            return False  # 返回失败。
        self.log_info("未发现弹窗，无需清理。")  # 超时未出现任何弹窗。
        return True  # 视为清理完成。

    def register_screen(self, name: str, features=(), keywords=(), ocr_box=None):
        """注册一个界面及判定条件。

        Args:
            name: 界面名（子任务用 is_screen/wait_screen/assert_screen 时传入的名称）。
            features: coco 标注的模板特征名列表，全部命中才判定为该界面。
            keywords: OCR 关键词列表，任一命中即判定为该界面（多用于无稳定模板的页面）。
            ocr_box: 可选 OCR 区域，避免全屏 OCR 的开销。可为相对坐标列表
                [x, y, to_x, to_y]，也可为 coco 标注的区域特征名（字符串），
                匹配时按当前分辨率解析。
        """
        self.screens[name] = {  # 保存界面判定描述到注册表。
            "features": list(features),  # 模板特征名列表。
            "keywords": list(keywords),  # OCR 关键词列表。
            "ocr_box": ocr_box,  # OCR 区域相对坐标。
        }

    def _screen_match(self, spec: dict) -> bool:
        """按判定描述在当前帧检测是否处于该界面。

        features 与 keywords 同时配置时取「与」：所有特征命中 且 命中任一关键词。
        """
        features = spec.get("features")  # 模板特征名列表。
        keywords = spec.get("keywords")  # OCR 关键词列表。
        if features:  # 有模板特征则先逐个检测特征。
            for name in features:  # 逐个检测特征。
                if self.find_one(name) is None:  # 任一特征缺失则不在该界面。
                    return False  # 返回未命中。
            if not keywords:  # 未配置关键词时特征全部命中即判定为该界面。
                return True  # 返回命中。
            return self._match_ocr_keywords(spec)  # 同时配置了关键词则还需命中任一关键词。
        if keywords:  # 无模板特征时退化为 OCR 关键词判定。
            return self._match_ocr_keywords(spec)  # 按关键词判定。
        self.log_warning(f"界面 {spec} 未配置判定条件")  # 记录空配置。
        return False  # 空配置判定为不在该界面。

    def _match_ocr_keywords(self, spec: dict) -> bool:
        """按界面判定描述在当前帧 OCR 匹配关键词，命中任一关键词返回 True。"""
        box = spec.get("ocr_box")  # 读取可选 OCR 区域。
        if isinstance(box, str):  # ocr_box 为 coco 区域特征名时解析为当前分辨率的框。
            try:  # 特征可能缺失。
                box = self.get_box_by_name(box)  # 解析区域框。
            except ValueError:  # 特征缺失时退化为全屏 OCR。
                box = None  # 置空走全屏逻辑。
        if box:  # 指定了区域则只在该区域 OCR。
            if isinstance(box, (list, tuple)):  # 相对坐标列表形式。
                boxes = self.ocr(*box, match=spec["keywords"])  # 区域内匹配关键词。
            else:  # 已解析的 Box 对象。
                boxes = self.ocr(box=box, match=spec["keywords"])  # 区域内匹配关键词。
        else:  # 未指定区域则全屏 OCR。
            boxes = self.ocr(match=spec["keywords"])  # 全屏匹配关键词。
        return bool(boxes)  # 命中任一关键词即判定为该界面。

    def current_screen(self) -> str | None:
        """在当前帧识别所处界面，返回界面名；未命中返回 None（常用于失败日志）。"""
        for name, spec in self.screens.items():  # 遍历所有已注册界面。
            if self._screen_match(spec):  # 命中则返回该界面名。
                return name  # 返回界面名。
        return None  # 全部未命中返回 None。

    def is_screen(self, name: str) -> bool:
        """单帧检测当前是否处于指定界面。"""
        spec = self.screens.get(name)  # 读取界面判定描述。
        if spec is None:  # 界面未注册。
            self.log_warning(f"未注册界面: {name}")  # 记录未注册。
            return False  # 未注册判定为不在该界面。
        return self._screen_match(spec)  # 按判定描述检测。

    def wait_screen(self, name: str, time_out=10, raise_if_not_found=False):
        """等待进入指定界面，复用 wait_until 的轮询与超时机制。"""
        spec = self.screens.get(name)  # 读取界面判定描述。
        if spec is None:  # 界面未注册。
            raise ValueError(f"未注册界面: {name}")  # 未注册直接报错。
        return self.wait_until(lambda: self._screen_match(spec),  # 轮询界面判定条件。
                               time_out=time_out,  # 超时时间。
                               raise_if_not_found=raise_if_not_found)  # 超时是否抛异常。

    def assert_screen(self, name: str, time_out=10):
        """断言处于指定界面，超时抛 WaitFailedException（由 try_step 捕获并恢复）。"""
        if not self.wait_screen(name, time_out=time_out):  # 等待界面超时。
            cur = self.current_screen()  # 识别当前实际界面用于日志。
            self.log_warning(f"界面断言失败: 期望 {name}，当前 {cur}")  # 记录断言失败。
            raise WaitFailedException(f"not on screen: {name} (current: {cur})")  # 抛等待失败异常。

    def save_failure_screenshot(self, tag: str):
        """保存失败现场截图到 screenshots/failure/，复用框架截图能力。"""
        try:  # 截图失败不应影响主流程。
            self.screenshot(name=f"failure/{tag}")  # 按失败步骤命名截图。
        except Exception as e:  # 截图异常。
            self.log_warning(f"save_failure_screenshot failed: {e}")  # 记录截图失败原因。

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
        except Exception as e:  # 清理弹窗异常不中断恢复。
            self.log_warning(f"recover dismiss_all_popups failed: {e}")  # 记录清理弹窗失败。
        if self.is_screen("lobby"):  # 已在大厅则无需额外操作。
            return True  # 恢复成功。
        try:
            if self.feature_exists("common_home"):  # 存在大厅按钮特征则点击回大厅。
                home = self.find_one("common_home")  # 查找大厅按钮。
                if home is not None:  # 找到才点击。
                    self.click_box(home, after_sleep=1)  # 点击大厅按钮返回大厅。
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