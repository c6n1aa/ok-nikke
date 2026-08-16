import datetime
import os
import time

import cv2

from ok import BaseTask
from ok.task.exceptions import WaitFailedException  # 界面断言/失败恢复使用的框架等待失败异常。

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
        self.register_screen("lobby", features=["ark"])

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

    def wait_for_lobby(self, time_out=120, raise_if_not_found=True):
        """等待游戏大厅出现，通过识别大厅中的方舟按钮(ark)判断是否已进入游戏大厅。

        各子任务在点击自己的入口前应先调用本方法，避免游戏仍在加载/登录页
        时就按大厅坐标点击，导致后续特征查找超时。time_out 默认 120 秒。
        """
        self.bring_game_to_front()  # 先把游戏窗口切到前台，确保 pynput 点击生效。
        return self.wait_feature("ark", time_out=time_out, raise_if_not_found=raise_if_not_found)

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

    def register_screen(self, name: str, features=(), keywords=(), ocr_box=None):
        """注册一个界面及判定条件。

        Args:
            name: 界面名（子任务用 is_screen/wait_screen/assert_screen 时传入的名称）。
            features: coco 标注的模板特征名列表，全部命中才判定为该界面。
            keywords: OCR 关键词列表，任一命中即判定为该界面（多用于无稳定模板的页面）。
            ocr_box: 可选 OCR 区域相对坐标 [x, y, to_x, to_y]，避免全屏 OCR 的开销。
        """
        self.screens[name] = {  # 保存界面判定描述到注册表。
            "features": list(features),  # 模板特征名列表。
            "keywords": list(keywords),  # OCR 关键词列表。
            "ocr_box": ocr_box,  # OCR 区域相对坐标。
        }

    def _screen_match(self, spec: dict) -> bool:
        """按判定描述在当前帧检测是否处于该界面。"""
        if spec.get("features"):  # 有模板特征则以特征判定为准。
            for name in spec["features"]:  # 逐个检测特征。
                if self.find_one(name) is None:  # 任一特征缺失则不在该界面。
                    return False  # 返回未命中。
            return True  # 全部命中才算处于该界面。
        if spec.get("keywords"):  # 无模板特征时退化为 OCR 关键词判定。
            box = spec.get("ocr_box")  # 读取可选 OCR 区域。
            if box:  # 指定了区域则只在该区域 OCR。
                boxes = self.ocr(*box, match=spec["keywords"])  # 区域内匹配关键词。
            else:  # 未指定区域则全屏 OCR。
                boxes = self.ocr(match=spec["keywords"])  # 全屏匹配关键词。
            return bool(boxes)  # 命中任一关键词即判定为该界面。
        self.log_warning(f"界面 {spec} 未配置判定条件")  # 记录空配置。
        return False  # 空配置判定为不在该界面。

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
            self.close_overlay(time_out=3, require_click=False)  # 先关闭可能遮挡后续操作的弹窗，容错：没有遮罩可关也继续恢复。
        except Exception as e:  # 关遮罩异常不中断恢复。
            self.log_warning(f"recover close_overlay failed: {e}")  # 记录关遮罩失败。
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