import re  # 正则模块，用于 OCR 文字的部分匹配。

from src.screens import SCREENS, INTERRUPTS  # 集中式界面注册表与中断哨兵清单。

import datetime  # 日期时间模块，处理北京时区与周期刷新。
import os  # 操作系统路径模块，处理 assets/template/ 下模板文件的绝对路径。
import time  # 时间模块，处理超时与等待。

import cv2  # OpenCV，模板缩放匹配使用 cv2.resize / cv2.imread。
from ok.feature.Box import Box, find_boxes_by_name  # 检测框对象与按名过滤工具（find_boxes_by_name 用于复刻 ocr(match=...) 的过滤语义）。
from ok import BaseTask
from ok.task.exceptions import TaskDisabledException, WaitFailedException  # 界面断言失败与任务被停止（用户点击中断）时使用的框架异常。
from ok.util.color import calculate_colorfulness  # 框架颜色工具：计算区域色彩丰富度。


_CACHE_MISS = object()  # 帧级判定缓存的「未命中」哨兵：与「命中但结果为 None」区分。

class InterruptedByDialogException(WaitFailedException):
    """长等待期间命中致命中断弹窗（断线/维护/登录过期等）时抛出。

    继承 WaitFailedException：try_step/_recover_to_lobby 的现有捕获与
    恢复路径自动兼容，无需任何改动。
    """


_BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间 UTC+8，无夏令时


class NikkeBaseTask(BaseTask):
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
        # 从集中式注册表加载全部界面；任务仍可用 register_screen 追加私有界面，同名覆盖全局条目（后写者胜）。
        for _name, _spec in SCREENS.items():
            self.register_screen(_name, **_spec)
        # 帧级判定缓存：同一帧内重复的界面判定（模板匹配/区域 OCR）只真正执行一次。
        # 条目为 (计算时的帧对象, 结果)，读取时校验帧对象同一性——帧一换即失效，无陈旧风险。
        self._screen_cache = {}

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

    _NOTICE_BELL_TEMPLATES = (  # 公告弹窗铃铛模板列表：公告(notice_bell1)与活动(notice_bell2)弹窗图标样式略有差异，依次尝试任一命中即可。
        os.path.join('assets', 'template', 'common', 'notice_bell1.png'),  # 活动弹窗铃铛模板，来自 2560x1440 截图。
        os.path.join('assets', 'template', 'common', 'notice_bell2.png'),  # 公告弹窗铃铛模板，来自 2560x1440 截图。
    )
    _COMMON_CLOSE_TEMPLATE = os.path.join('assets', 'template', 'common', 'common_close.png')  # 通用关闭按钮模板，来自 2560x1440 截图。
    _ENTER_GAME_TEXT = re.compile("TOUCH TO CONTINUE", re.IGNORECASE)  # 进入游戏提示文字，OCR 部分匹配并忽略大小写。
    # 登录奖励（DAILY LOGIN）弹窗判据：七天制小型登录奖励每期面板皮肤不同，判据一律取
    # 不受皮肤影响的部分——「全部领取」认文字（OCR），关闭按钮认 X 图形（模板只留图形本身）。
    _DAILY_LOGIN_CLAIM_ALL_TEXT = re.compile("全部领取")  # 「全部领取」按钮文字，OCR 部分匹配（兼容拆框/噪声）。
    _DAILY_LOGIN_CLAIM_PAD = (0.2, 0.36)  # 文字框外扩比例（宽, 高）：OCR 只框到白字，外扩取到按钮底色才能判断可领与否；用比例而非固定像素，保证各分辨率下都不超出按钮本体。
    _DAILY_LOGIN_CLOSE_TEMPLATES = (  # 面板右上角关闭 X 模板列表；出现新皮肤样式时追加即可，依次尝试任一命中。
        os.path.join('assets', 'template', 'daily_login', 'daily_login_close.png'),  # 来自 2560x1440 截图。
    )

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

    def _find_daily_login_claim_all(self):
        """在屏幕底部区域 OCR 识别登录奖励弹窗的「全部领取」按钮文字，返回匹配框或 None。

        走 OCR 而非模板：七天制登录奖励每期皮肤不同，按钮配色/尺寸随之变化，
        但「全部领取」这行文字固定不变。
        """
        boxes = self.ocr(box=self.box_of_screen(1 / 3, 0.85, 0.7, 1.0),  # 按钮恒在面板底部。
                         match=[self._DAILY_LOGIN_CLAIM_ALL_TEXT])  # 正则部分匹配。
        return boxes[0] if boxes else None  # 文字长在按钮上，命中即按钮存在。

    def _daily_login_button_box(self, text_box):
        """把 OCR 得到的「全部领取」文字框按 _DAILY_LOGIN_CLAIM_PAD 比例外扩到按钮底色区域。

        OCR 只框到白色文字，彩色可领与灰白已领完两种状态下文字都是白的，无法据此区分；
        外扩取到按钮底色后才能用 is_feature_enabled 判定。外扩用比例而非固定像素，
        保证在 1600x900 等小分辨率下也不会撑出按钮本体而混进背景色。
        """
        pad_w = text_box.width * self._DAILY_LOGIN_CLAIM_PAD[0]  # 水平外扩量。
        pad_h = text_box.height * self._DAILY_LOGIN_CLAIM_PAD[1]  # 垂直外扩量。
        return Box(text_box.x - pad_w, text_box.y - pad_h,  # 左上各外扩一份。
                   text_box.width + pad_w * 2, text_box.height + pad_h * 2,  # 尺寸两端各加一份。
                   name="daily_login_claim_button")  # 命名便于日志/调试识别。

    def _find_daily_login_close(self):
        """在屏幕右上区域依次尝试各期关闭按钮模板，返回第一个命中的框或 None。

        七天制登录奖励每期面板皮肤不同，关闭 X 的背景纹理/描边随之变化，故模板只保留
        X 图形本身（不含周边背景）以应对该变化；出现新样式时把裁剪好的小图路径追加到
        _DAILY_LOGIN_CLOSE_TEMPLATES 即可，无需改动本方法。
        """
        for template_path in self._DAILY_LOGIN_CLOSE_TEMPLATES:  # 依次尝试每个关闭按钮模板。
            found = self.find_scaled_template(  # 关闭 X 恒在面板右上角约 x 0.62、y 0.095。
                "daily_login_close", template_path,
                box=self.box_of_screen(0.5, 0.03, 0.8, 0.2),
            )
            if found is not None:  # 当前模板命中。
                return found  # 停止尝试后续模板。
        return None  # 所有模板均未命中，当前帧无该弹窗（或遇到未收录的新皮肤）。

    def _close_daily_login_popup(self):
        """处理登录奖励（DAILY LOGIN）弹窗：有可领奖励先点「全部领取」，无可领则点右上角关闭按钮。

        每次只走一步，由 dismiss_all_popups 逐轮调用完成「领取 → 关奖励遮罩 → 关闭弹窗」
        整段流程——领取后弹出的奖励遮罩由上一层的遮罩分支处理，不在本方法内处理。
        可领与否用按钮底色判定（彩色可领 / 灰白已领完），避免已领完时反复点击同一步。
        """
        claim = self._find_daily_login_claim_all()  # 查找「全部领取」文字。
        if claim is not None and self.is_feature_enabled(self._daily_login_button_box(claim)):  # 底色彩色 = 仍有可领奖励。
            self.click_box(claim, after_sleep=1)  # 点击领取，奖励遮罩交由下一轮的遮罩分支关闭。
            self.log_info("已点击登录奖励全部领取。")  # 记录动作。
            return True  # 返回已处理。
        close = self._find_daily_login_close()  # 无可领（按钮灰白/缺失）时直接关闭弹窗。
        if close is not None:  # 关闭按钮存在。
            self.click_box(close, after_sleep=1)  # 点击关闭按钮关闭整个弹窗。
            self.log_info("已关闭登录奖励弹窗。")  # 记录动作。
            return True  # 返回已处理。
        return False  # 当前帧无登录奖励弹窗。

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

    _BATTLE_FINISH_ESC_PATTERN = re.compile(r"\bESC\b", re.IGNORECASE)  # 结算界面 ESC 确认文字（OCR 部分匹配，忽略大小写）。
    _BATTLE_AUTO_BOXES = ("box_battle_auto_aim", "box_battle_auto_burst")  # 自动瞄准/自动爆裂按钮区域（coco 区域；彩色=已开启，灰白=已关闭）。

    def wait_battle_finish(self, time_out=240, check_interval=3, settle_time=2):
        """节流轮询等待自动战斗结束，返回 (结果, 确认按钮框)，不自动点击。

        战斗时长不确定（约10秒~3分钟）：每 check_interval 秒才刷新一帧做单次
        检测；命中结算界面后先等待 settle_time 秒让结算入场动画收尾，再刷新
        一帧复识别确认仍在结算界面并返回——结算界面刚出现时直接返回会让调用方
        在动画期间误操作。超时返回 (None, None)。避免用 wait_feature 等
        忙轮询长时间对游戏窗口持续抓帧/匹配，与游戏抢 CPU。

        正常结束：对 box_battle_finish_text 区域 OCR 识别 ESC 确认文字
        （区域框随分辨率等比缩放，比图标模板跨分辨率更可靠）。OCR 未命中时在
        box_battle_finish_bottom_right 区查找 battle_finish_statistics 兜底判定
        胜利。两条胜利路径返回的可点击框统一为 box_battle_finish_text 区域框。
        战斗失败：同时识别 battle_finish_failed 与 battle_finish_failed_back。

        此处只检测不点击——战斗结束后的动作由调用方决定（连续战斗的胜利界面
        可能有"下一关"等其它按钮），返回值带上了识别到的确认按钮框，调用方
        需要点击时可直接用它。

        进入战斗界面时附带一次性开启自动瞄准/自动爆裂：轮询中一旦识别到
        battle_pause（暂停按钮只在战斗界面出现）即认为已进入自动战斗界面，
        调用 _enable_battle_auto_once 把两个灰白的自动按钮点成彩色，之后置位
        标记不再重复触发（按钮是开关，重复点会关掉）。快速战斗等不进入战斗
        界面的流程结算界面先被识别到而直接返回，不会触发该流程。

        Returns:
            ("success", text_box) 正常结束，text_box 为 box_battle_finish_text 区域框；
            ("failed", failed_back_box) 战斗失败，failed_back_box 为返回按钮框；
            (None, None) 超时。
        """
        deadline = time.time() + time_out  # 记录整体超时时刻。
        polls = 0  # 轮询计数，用于 debug 日志观察节流间隔。
        auto_checked = False  # 自动按钮只开启一次：放开会导致每轮轮询重复点击（按钮是开关，点第二次就关掉了）。
        while time.time() < deadline:  # 节流循环直到超时。
            self.sleep(check_interval)  # 轻量等待，不抓帧不匹配。
            self.next_frame()  # 刷新一帧，避免使用旧帧。
            polls += 1  # 轮询次数加一。
            self.log_debug(f"战斗轮询第 {polls} 次（每 {check_interval} 秒一帧），已耗时 {time.time() - (deadline - time_out):.0f} 秒。")  # debug 日志确认轮询节奏。
            if self._hit_interrupt() is not None:  # 先查中断哨兵：断线/维护/登录过期弹窗会让后续匹配全部落空，快速失败优于空转等满超时。
                self.save_failure_screenshot("interrupt")  # 保存中断现场截图便于排查。
                self.log_warning("检测到致命中断弹窗，中止长等待。")  # 记录中断原因。
                raise InterruptedByDialogException("long wait interrupted by dialog")  # 由 try_step 按等待失败恢复。
            # 胜利判定主路径：对 box_battle_finish_text 区域 OCR 识别 ESC 确认文字。
            text_box = self._battle_finish_text_box()  # 获取结算文字区域框（coco 坐标区域，按当前分辨率缩放；特征缺失为 None）。
            if text_box is not None and self._esc_visible(text_box):  # 该区域命中 ESC 文字，判定正常结束。
                confirm = self._stabilize_battle_finish_box(text_box, settle_time=settle_time)  # 等结算动画收尾后复识别确认仍在结算界面，返回统一可点击区域框。
                self.log_info("检测到战斗胜利结算界面。")  # 记录正常结束。
                return "success", confirm  # 返回结果与确认按钮框，由调用方决定后续动作。
            # OCR 未命中兜底：在结算右下区查找 battle_finish_statistics，命中即判胜利。
            # 返回的可点击框仍统一为 box_battle_finish_text 区域：statistics 仅做检测，不做可点击框。
            statistics = self.find_one("battle_finish_statistics", box="box_battle_finish_bottom_right")  # 限定在右下角结算信息区匹配统计文字特征，避免全屏误命中。
            if statistics is not None:  # OCR 未命中但 statistics 兜底命中，判定为战斗胜利。
                confirm = self._stabilize_battle_finish_box(text_box if text_box is not None else statistics, settle_time=settle_time)  # 等结算动画收尾后复识别确认，返回统一可点击区域框。
                self.log_info("检测到战斗胜利结算界面（statistics 兜底）。")  # 记录经兜底判定的正常结束。
                return "success", confirm  # 返回结果与确认按钮框，由调用方决定后续动作。
            failed = self.find_one("battle_finish_failed")  # 单帧匹配战斗失败特征。
            failed_back = self.find_one("battle_finish_failed_back")  # 单帧匹配失败返回按钮特征。
            if failed is not None and failed_back is not None:  # 战斗失败。
                failed_back = self._stabilize_battle_finish_box(failed_back, failed=True, settle_time=settle_time)  # 同样等稳定后重新定位失败返回按钮。
                self.log_info("检测到战斗失败结算界面。")  # 记录失败结束。
                return "failed", failed_back  # 返回结果与返回按钮框，由调用方决定后续动作。
            if not auto_checked and self._in_battle_page():  # 结算判定都未命中且识别到暂停按钮=确已进入自动战斗界面（快速战斗无战斗界面，不会走到这里）。
                auto_checked = True  # 置位标记：整个等待流程内只开启一次。
                self._enable_battle_auto_once()  # 开启自动瞄准/自动爆裂（内部吞异常，失败也不影响继续等待战斗结束）。
        self.save_failure_screenshot("wait_battle_finish")  # 超时保存现场截图便于排查。
        self.log_warning(f"等待战斗结束超时（{time_out}秒）。")  # 记录超时原因。
        return None, None  # 返回超时结果。

    def _in_battle_page(self) -> bool:
        """是否处于自动战斗界面：单帧匹配 battle_pause（战斗内暂停按钮）特征。

        暂停按钮只出现在战斗界面，命中即认为已进入自动战斗界面；快速战斗等
        不进入战斗界面的流程不会命中。匹配异常一律按未命中处理，不影响等待
        战斗结束的主流程；用户主动停止（TaskDisabledException）必须传播。
        """
        try:  # 特征缺失/匹配异常都不应影响等待战斗结束。
            return self.find_one("battle_pause") is not None  # 命中暂停按钮即视为在战斗界面。
        except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
            raise  # 重新抛出，交由执行器结束任务。
        except Exception as e:  # 特征缺失等其它异常。
            self.log_debug(f"battle_pause 匹配失败，按未进入战斗界面处理: {e}")  # 记录原因。
            return False  # 返回未命中。

    def _enable_battle_auto_once(self, max_attempts=3, after_sleep=1):
        """进入自动战斗界面后一次性开启自动瞄准/自动爆裂：区域灰白（关闭）则点击，直到判定为已开启或试满次数。

        逐个区域判态：is_feature_enabled 为 True（彩色高亮）即已开启；为 False
        （灰白）则点击切换，刷新帧后复判，最多 max_attempts 次——点击后必须刷新
        帧，因为 click 内部的 reset_scene 会把当前帧置空，无帧时 is_feature_enabled
        会保守判为已开启而漏点。

        全程吞掉异常只记日志：自动按钮开启失败不得影响后续等待战斗结束；
        用户主动停止（TaskDisabledException）必须原样向上传播，否则无法中断任务。
        """
        for name in self._BATTLE_AUTO_BOXES:  # 逐个处理两个自动按钮区域。
            try:  # coco 区域缺失等异常不应影响另一个区域与后续等待。
                box = self.get_box_by_name(name)  # 按当前分辨率解析区域框。
            except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
                raise  # 重新抛出，交由执行器结束任务。
            except Exception as e:  # 特征缺失等异常。
                self.log_debug(f"{name} 区域不可用，跳过开启: {e}")  # 记录跳过原因。
                continue  # 处理下一个区域。
            if box is None:  # 区域无效。
                continue  # 跳过该区域。
            for attempt in range(max_attempts):  # 点击后复判，直到开启或试满次数。
                try:  # 点击/取帧异常不应中断等待战斗结束。
                    if self.frame is None:  # 当前帧被清空（上一次点击的 reset_scene）。
                        self.next_frame()  # 先取帧，避免无帧时判态失真。
                    if self.is_feature_enabled(box):  # 彩色高亮=已开启。
                        break  # 该区域已开启，处理下一个。
                    self.log_info(f"点击开启 {name}（第 {attempt + 1} 次）。")  # 记录点击动作。
                    self.click_box(box, after_sleep=after_sleep)  # 点击切换为开启态并等待界面响应。
                    self.next_frame()  # 刷新一帧，复判时读的是点击后的画面。
                except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
                    raise  # 重新抛出，交由执行器结束任务。
                except Exception as e:  # 点击/取帧失败等异常。
                    self.log_warning(f"开启 {name} 失败，跳过: {e}")  # 记录失败原因。
                    break  # 放弃该区域，处理下一个。

    def _battle_finish_text_box(self):
        """获取 box_battle_finish_text 结算文字区域框（coco 坐标区域，按当前分辨率缩放）。

        该区域固定不随结算动画漂移，同时用作胜利结算的 OCR 检测区与统一返回的
        可点击框；特征缺失（coco 未标注）时返回 None，由调用方跳过主路径。
        """
        try:  # 特征可能尚未标注进 coco。
            return self.get_box_by_name("box_battle_finish_text")  # 按当前分辨率解析区域框。
        except ValueError:  # 特征缺失视为区域不可用。
            return None  # 返回 None。

    def _esc_visible(self, text_box) -> bool:
        """在 box_battle_finish_text 区域 OCR 识别 ESC 确认文字，命中返回 True。

        走帧级缓存：同一帧内重复判定只真正 OCR 一次。
        """
        boxes = self._region_ocr_cached(self._ocr_box_key(text_box), text_box)  # 区域 OCR（同帧缓存）。
        return bool(find_boxes_by_name(boxes, self.fix_match_regex(self._BATTLE_FINISH_ESC_PATTERN)))  # 与 ocr(match=...) 相同的部分匹配过滤。

    def _victory_settle_still_visible(self) -> bool:
        """结算稳定化后的复识别：OCR box_battle_finish_text 命中 ESC，或
        box_battle_finish_bottom_right 内 statistics 兜底命中，即认为仍在胜利结算界面。

        任一判据命中即视为仍在结算界面（防止动画一帧误命中后界面已跳走）。
        """
        text_box = self._battle_finish_text_box()  # 获取结算文字区域框。
        if text_box is not None and self._esc_visible(text_box):  # 主判据仍命中。
            return True  # 仍在胜利结算界面。
        try:  # 主判据失配时查兜底判据。
            return self.find_one("battle_finish_statistics", box="box_battle_finish_bottom_right") is not None  # statistics 兜底仍在。
        except ValueError:  # 特征缺失视为未命中。
            return False  # 返回 False。

    def _stabilize_battle_finish_box(self, box, failed=False, settle_time=2):
        """结算界面命中后的稳定化：等待 settle_time 秒让入场动画收尾，刷新一帧复识别确认仍在结算界面。

        胜利结算：复识别（OCR box_battle_finish_text 命中 ESC 或 statistics 兜底命中）
        确认仍在结算界面后返回 box_battle_finish_text 区域框——该区域固定不随动画
        漂移，两条胜利路径统一用它作可点击框；复识别未命中（界面已自动跳转等异常）
        时退回原检测框，交由调用方的后续动作兜底。
        失败结算：先复核 failed 特征仍在前台，再重新定位 failed_back 返回按钮。

        Args:
            box: 初次命中的检测框（胜利路径为 text_box 区域框，失败路径为 failed_back 按钮框）。
            failed: 是否为失败结算分支。
            settle_time: 稳定化等待秒数。
        Returns:
            稳定后的可点击框；复识别未命中时为原框。
        """
        self.sleep(settle_time)  # 等待结算入场动画收尾（时长见 wait_battle_finish 的 settle_time 参数）。
        self.next_frame()  # 刷新一帧获取稳定后的结算画面。
        if failed:  # 失败结算：先复核 failed 特征仍在前台。
            if self.find_one("battle_finish_failed") is None:  # 失败界面已不在。
                return box  # 退回原检测框兜底。
            stable = self.find_one("battle_finish_failed_back")  # 重新定位失败返回按钮。
            return stable if stable is not None else box  # 复识别命中则采用稳定坐标，否则退回原框。
        if not self._victory_settle_still_visible():  # 胜利结算：复识别确认仍在结算界面。
            return box  # 界面已跳走，退回原检测框兜底。
        text_box = self._battle_finish_text_box()  # 复识别通过，取统一可点击区域框。
        return text_box if text_box is not None else box  # 区域可取则返回区域框，否则退回原框。

    def _hit_interrupt(self):
        """检查当前帧是否命中致命中断弹窗特征（src/screens.py 的 INTERRUPTS 清单）。

        返回命中的 Box，未命中返回 None。清单为空 = 哨兵未激活，零开销直接跳过；
        复用 P1.2 帧级缓存路径，检测不新增抓帧频率。特征未标注进 coco（ValueError）
        时按未命中处理。
        """
        for name in INTERRUPTS.get("features", ()):  # 遍历中断特征清单。
            try:  # 特征可能尚未标注进 coco。
                box = self._find_feature_cached(name)  # 同帧只匹配一次。
            except ValueError:  # 未标注视为未命中。
                continue
            if box is not None:  # 命中断线/维护/登录过期等弹窗。
                return box
        return None

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

    def is_feature_enabled(self, box: Box, colorfulness_thresh: float = 0.1, after_sleep: float = 0) -> bool:
        """判断 UI 元素是否处于可用（高亮彩色）状态。

        游戏内可用/禁用按钮常用"高亮彩色 vs 灰白"表达（如无限之塔"进入战斗"蓝色
        可用态 vs 灰色禁用态）。CCOEFF 模板匹配会忽略颜色，无法区分这两种状态；
        此方法用框架的颜色工具计算 box 区域色彩丰富度（RGB 对立轴统计，对灰白压
        得更狠），低于 colorfulness_thresh 视为灰白禁用。

        Args:
            box: 元素所在区域（coco 特征框或模板匹配结果 Box）。
            colorfulness_thresh: 色彩丰富度阈值（0~1），低于则判定为禁用。
            after_sleep: 判断后的固定等待时间（秒），参考框架 click/send_key 等方法的 after_sleep 实现。

        Returns:
            True 可用；False 禁用（灰白）。无帧/区域越界时保守返回 True。
        """
        frame = self.frame  # 取当前帧；无帧（如单测 mock）时保守视为可用。
        if frame is None:  # 无帧可做颜色检测。
            if after_sleep > 0:  # 参考框架 click 等方法的 after_sleep 实现：操作后等待。
                self.sleep(after_sleep)  # 等待指定时间。
            return True  # 返回可用，避免误跳可用功能。
        x1, y1 = max(box.x, 0), max(box.y, 0)  # 裁剪 box 左上角到帧范围内。
        x2, y2 = min(box.x + box.width, frame.shape[1]), min(box.y + box.height, frame.shape[0])  # 裁剪右下角。
        if x2 <= x1 or y2 <= y1:  # 区域越界无效。
            if after_sleep > 0:  # 参考框架实现。
                self.sleep(after_sleep)  # 等待指定时间。
            return True  # 保守视为可用。
        roi = frame[y1:y2, x1:x2]  # 取 box 区域子图。
        colorfulness = calculate_colorfulness(roi)  # 用框架颜色工具计算色彩丰富度（0~1）。
        result = colorfulness > colorfulness_thresh  # 超过阈值判定为可用。
        if after_sleep > 0:  # 参考框架 click/send_key 的 after_sleep 实现。
            self.sleep(after_sleep)  # 等待指定时间。
        return result  # 返回可用性判定结果。

    # 遮罩提示文字 OCR 关键词：框架对字符串是全等匹配，OCR 常把提示拆成多个文本框
    # （如实测「点击进行下一步」被拆成「点击进行下一」+「步」），一律用正则走部分匹配。
    _MASK_CLAIM_PATTERN = re.compile("点击领取奖励")  # 领奖遮罩提示。
    _MASK_ANYWHERE_PATTERN = re.compile("点击任意处")  # 点击任意处关闭遮罩提示。
    _CLICK_TO_PROCEED_PATTERN = re.compile("点击进行")  # 「点击进行下一步」好感度提升等遮罩提示。

    def close_overlay(self, keywords=None, time_out=5, after_sleep=1, max_clicks=3,
                      require_click=True):
        """点击遮罩窗按钮关闭弹窗，避免后续点击被遮罩拦截。

        在屏幕中下部区域（x 1/3-2/3，y 0.6-1）做 OCR："点击领取奖励"文字
        位于屏幕中央偏下（约 rel_y 0.64），因此 OCR 区域从 y=0.6 开始覆盖，
        每次只点第一个匹配框（同一弹窗的文字阴影会重复命中，不能连点），
        点完继续检测，弹窗连续出现时逐个关闭。遮罩未出现时会一直等到
        time_out 超时，方便处理点击后延迟弹出的遮罩。

        Args:
            keywords: OCR 匹配关键词（支持正则），缺省为领奖遮罩提示（正则部分匹配）。
            time_out: 等待遮罩出现/关闭的最长时间（秒）。
            after_sleep: 点击后的固定等待时间（秒）。
            max_clicks: 最多连续点击次数，防止异常时死循环。
            require_click: True 时若超时仍未点到任何遮罩则抛 WaitFailedException；
                恢复流程等容错场景应传 False，超时未出现则跳过不报错。
        Returns:
            True 表示至少点击过一次；require_click=False 且未点到时返回 False。
        """
        if keywords is None:  # 未指定关键词。
            keywords = (self._MASK_CLAIM_PATTERN,)  # 默认领奖遮罩提示（正则部分匹配，兼容 OCR 拆框/噪声）。
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
        """尝试关闭当前帧上的一个弹窗：卢比限时特卖 → 公告/活动横幅 → 领取奖励/点击任意处遮罩 → 登录奖励弹窗。返回是否成功关掉一个。

        顺序按遮挡层级从上到下：遮罩压在登录奖励面板之上，故面板排在遮罩之后——
        否则「点完全部领取弹出的奖励遮罩」会被面板的关闭按钮抢先跳过后者的点击。
        每次只关一个，由 dismiss_all_popups 循环调用，避免一次点击后界面动画未完成导致误判。
        """
        if self._close_rupee_flash_sale_popup():  # 卢比限时特卖（两段式：入口横幅点击后弹详情，再点关闭确认）。
            return True  # 已处理卢比限时特卖。
        if self._close_notice_popup():  # 公告/活动横幅（右上角铃铛+关闭按钮）。
            return True  # 已关闭横幅弹窗。
        try:  # 遮罩 OCR 异常不应中断统一清理。
            boxes = self.ocr(x=1 / 3, y=0.6, to_x=2 / 3, to_y=1,
                             match=[self._MASK_CLAIM_PATTERN, self._MASK_ANYWHERE_PATTERN,
                                    self._CLICK_TO_PROCEED_PATTERN])  # 中下部区域查找领奖/任意处/进行下一步遮罩提示（正则部分匹配）。
        except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
            raise  # 重新抛出，交由执行器结束任务。
        except Exception as e:  # 其它 OCR 失败。
            self.log_warning(f"遮罩 OCR 失败: {e}")  # 记录失败原因。
            return False  # 本帧无遮罩可关。
        if boxes:  # 存在遮罩按钮。
            self.click_box(boxes[0], after_sleep=after_sleep)  # 点击关闭遮罩。
            self.log_info("点击遮罩按钮关闭弹窗。")  # 记录关闭动作。
            return True  # 已关闭一个遮罩。
        try:  # 登录奖励面板含 OCR 与模板匹配，异常同样不应中断统一清理。
            if self._close_daily_login_popup():  # 位于遮罩之下，故排在遮罩之后处理。
                return True  # 已处理登录奖励弹窗。
        except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
            raise  # 重新抛出，交由执行器结束任务。
        except Exception as e:  # OCR/模板匹配失败。
            self.log_warning(f"登录奖励弹窗清理失败: {e}")  # 记录失败原因。
            return False  # 本帧视为无可关闭的弹窗。
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
                每轮先尝试关弹窗，仅当本轮未关到任何弹窗时才检查该条件——遮罩压暗下
                目标界面特征可能仍命中，若先查条件会误报清理完成而留下未关弹窗。
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
            if self._try_close_one_popup(after_sleep=after_sleep):  # 关掉了一个弹窗。
                closed_any = True  # 标记已关闭过弹窗。
                try:  # 刷新帧后再继续，避免基于旧帧重复匹配。
                    self.next_frame()  # 获取最新屏幕帧。
                except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
                    raise  # 重新抛出，交由执行器结束任务。
                except Exception:  # 无可用帧时忽略。
                    pass  # 继续下一轮。
                continue  # 继续清理剩余弹窗。
            if clear_condition is not None and clear_condition():  # 本轮已无弹窗可关且完成条件满足。
                return True  # 清理完成。
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

    def next_frame(self):
        """覆写框架取帧：拿到新帧后清空帧级判定缓存。

        框架抛出的 TaskDisabledException/WaitFailedException 等异常原样向上传播；
        取帧失败时不清缓存（旧帧未变，缓存仍然有效）。
        """
        frame = super().next_frame()  # 框架取新帧。
        self._screen_cache.clear()  # 新帧已就位，旧帧判定结果全部失效。
        return frame

    def _cache_get(self, key):
        entry = self._screen_cache.get(key)  # 条目结构 (帧对象, 结果)。
        if entry is not None and entry[0] is self.frame:  # 帧对象同一性成立才视为命中。
            return entry[1]
        return _CACHE_MISS

    def _cache_put(self, key, value):
        self._screen_cache[key] = (self.frame, value)  # 记录结果所属的帧。

    def _find_feature_cached(self, name):
        """带帧级缓存的 find_one：同一帧内同名特征只真正匹配一次。"""
        key = ("feat", name)
        cached = self._cache_get(key)
        if cached is not _CACHE_MISS:
            return cached
        found = self.find_one(name)  # ValueError（特征缺失）由调用方处理，不进缓存。
        self._cache_put(key, found)
        return found

    @staticmethod
    def _ocr_box_key(box):
        if isinstance(box, Box):  # coco 区域框：按坐标归一化，同框不同名也可共享。
            return ("box", round(box.x, 3), round(box.y, 3), round(box.width, 3), round(box.height, 3))
        return ("box", tuple(round(v, 3) for v in box))  # 相对坐标列表 [x, y, to_x, to_y]。

    def _region_ocr_cached(self, box_key, box):
        """带帧级缓存的区域 OCR（不做关键词过滤），同帧同区域只真正 OCR 一次。"""
        key = ("ocr", box_key)
        cached = self._cache_get(key)
        if cached is not _CACHE_MISS:
            return cached
        if box is None:  # 全屏 OCR。
            result = self.ocr()
        elif isinstance(box, (list, tuple)):  # 相对坐标列表形式。
            result = self.ocr(*box)
        else:  # 已解析的区域框。
            result = self.ocr(box=box)
        self._cache_put(key, result)
        return result

    def register_screen(self, name: str, features=(), keywords=(), ocr_box=None, **extra):
        """注册一个界面及判定条件。

        全局界面已由基类从 src/screens.py 的 SCREENS 加载；本方法是任务的
        扩展口：可追加任务私有界面，同名调用覆盖全局（或先前）条目。
        扩展字段（absent/priority/min_frames 等）经 **extra 原样并入判定描述。

        Args:
            name: 界面名（子任务用 is_screen/wait_screen/assert_screen 时传入的名称）。
            features: coco 标注的模板特征名列表，全部命中才判定为该界面。
            keywords: OCR 关键词列表，任一命中即判定为该界面（多用于无稳定模板的页面）。
            ocr_box: 可选 OCR 区域，避免全屏 OCR 的开销。可为相对坐标列表
                [x, y, to_x, to_y]，也可为 coco 标注的区域特征名（字符串），
                匹配时按当前分辨率解析。
        """
        self.screens[name] = {  # 保存界面判定描述到注册表；扩展字段（absent/priority/min_frames）原样并入。
            "features": list(features),  # 模板特征名列表。
            "keywords": list(keywords),  # OCR 关键词列表。
            "ocr_box": ocr_box,  # OCR 区域相对坐标。
            **extra,  # 扩展字段：缺省时为空，不改变既有条目结构。
        }

    def _screen_match(self, spec: dict) -> bool:
        """按判定描述在当前帧检测是否处于该界面。

        features 与 keywords 同时配置时取「与」：所有特征命中 且 命中任一关键词。
        any_features（任一命中特征，与 features 的「全部命中」相对）与 keywords
        同时配置时同样取「与」：任一特征命中 且 命中任一关键词。
        absent 中的特征（消歧字段，默认空）任一命中则直接判负，作用于各条命中路径。
        """
        features = spec.get("features")  # 模板特征名列表。
        keywords = spec.get("keywords")  # OCR 关键词列表。
        absent = spec.get("absent") or []  # 消歧特征：任一命中即否定该界面。
        if features:  # 有模板特征则先逐个检测特征。
            for name in features:  # 逐个检测特征。
                try:  # 特征可能已不存在（如 coco 重建后旧特征被移除）。
                    found = self._find_feature_cached(name)  # 查找模板特征（同帧只匹配一次）。
                except ValueError:  # 特征缺失时视为未命中，避免因 coco 变更导致异常冒泡。
                    self.log_warning(f"界面特征缺失: {name}")  # 记录缺失。
                    return False  # 返回未命中。
                if found is None:  # 任一特征缺失则不在该界面。
                    return False  # 返回未命中。
            if not keywords:  # 未配置关键词时特征全部命中即判定为该界面。
                return self._check_absent(absent)  # absent 检查后返回。
            if not self._match_ocr_keywords(spec):  # 同时配置了关键词则还需命中任一关键词。
                return False  # 关键词未命中。
            return self._check_absent(absent)  # 关键词命中后再做 absent 检查。
        if spec.get("any_features"):  # 任一命中特征：任一特征在当前帧命中即视为特征命中。
            if not self._match_any_features(spec):  # 逐个检测，任一命中即通过。
                return False  # 全部未命中。
            if not keywords:  # 未配置关键词时任一特征命中即判定为该界面。
                return self._check_absent(absent)  # absent 检查后返回。
            if not self._match_ocr_keywords(spec):  # 同时配置了关键词则还需命中任一关键词。
                return False  # 关键词未命中。
            return self._check_absent(absent)  # 关键词命中后再做 absent 检查。
        if keywords:  # 无模板特征时退化为 OCR 关键词判定。
            if not self._match_ocr_keywords(spec):  # 按关键词判定。
                return False  # 关键词未命中。
            return self._check_absent(absent)  # 关键词命中后再做 absent 检查。
        self.log_warning(f"界面 {spec} 未配置判定条件")  # 记录空配置。
        return False  # 空配置判定为不在该界面。

    def _match_any_features(self, spec: dict) -> bool:
        """any_features 判定：列表中任一特征在当前帧命中即返回 True（「或」语义）。

        feature_box（可选，coco 区域特征名）限定匹配区域，缺失时退化为全屏匹配；
        区域匹配不做帧级缓存（小区域模板匹配开销低，且轮询判定每轮都是新帧）。
        """
        raw_box = spec.get("feature_box")  # 可选匹配区域。
        box = None  # None 表示全屏匹配。
        if isinstance(raw_box, str):  # 区域限定为 coco 区域特征名。
            try:  # 区域特征可能缺失。
                box = self.get_box_by_name(raw_box)  # 按当前分辨率解析区域框。
            except ValueError:  # 区域缺失时退化为全屏匹配。
                box = None  # 置空走全屏逻辑。
        for name in spec.get("any_features") or ():  # 逐个检测任一命中特征。
            try:  # 特征可能已不存在（如 coco 重建后旧特征被移除）。
                found = self.find_one(name, box=box) if box is not None \
                    else self._find_feature_cached(name)  # 区域匹配或全屏缓存匹配。
            except ValueError:  # 特征缺失时视为未命中，避免因 coco 变更导致异常冒泡。
                self.log_warning(f"界面特征缺失: {name}")  # 记录缺失。
                continue  # 检查下一个特征。
            if found is not None:  # 任一特征命中。
                return True  # 判定通过。
        return False  # 全部未命中。

    def _check_absent(self, absent) -> bool:
        """absent 消歧检查：列表中任一特征在当前帧命中则返回 False。走与 features 相同的缓存查找路径。"""
        for name in absent:  # 逐个检测消歧特征。
            try:  # 与 features 相同的容错：特征缺失视为未命中。
                if self._find_feature_cached(name) is not None:  # 消歧特征命中。
                    return False  # 该界面判定失败。
            except ValueError:  # coco 变更导致特征缺失时按未命中处理。
                self.log_warning(f"界面 absent 特征缺失: {name}")  # 记录缺失。
        return True  # 无消歧特征命中。

    def _match_ocr_keywords(self, spec: dict) -> bool:
        """按界面判定描述在当前帧 OCR 匹配关键词，命中任一关键词返回 True。

        同帧内共享同一区域的 OCR 结果（未过滤的全量文本框），各条目的关键词集
        各自比对——与框架 ocr(match=...) 的过滤语义逐位一致；全屏退化路径按
        条目隔离，不跨界面合并。
        """
        raw_box = spec.get("ocr_box")  # 读取可选 OCR 区域。
        box = None  # None 表示全屏 OCR。
        box_key = ("full", id(spec))  # 全屏退化不合并：键带上条目身份互相隔离。
        if isinstance(raw_box, str):  # ocr_box 为 coco 区域特征名时解析为当前分辨率的框。
            try:  # 特征可能缺失。
                box = self.get_box_by_name(raw_box)  # 解析区域框。
                box_key = self._ocr_box_key(box)
            except ValueError:  # 特征缺失时退化为全屏 OCR（与现状一致）。
                box = None  # 置空走全屏逻辑。
        elif isinstance(raw_box, (list, tuple)):  # 相对坐标列表形式。
            box = raw_box
            box_key = self._ocr_box_key(raw_box)
        elif raw_box is not None:  # 直接给了 Box 对象。
            box = raw_box
            box_key = self._ocr_box_key(raw_box)
        boxes = self._region_ocr_cached(box_key, box)  # 同帧同区域只跑一次 OCR。
        matched = find_boxes_by_name(boxes, self.fix_match_regex(spec["keywords"]))  # 与 ocr(match=...) 相同的过滤。
        return bool(matched)  # 命中任一关键词即判定为该界面。

    def current_screen(self) -> str | None:
        """在当前帧识别所处界面，返回界面名；未命中返回 None（常用于失败日志）。

        按 spec 的 priority 降序遍历（默认 0）；同优先级保持注册顺序
        （sorted 稳定排序），消除对注册先后顺序的隐性依赖。
        """
        ordered = sorted(self.screens.items(), key=lambda item: -item[1].get("priority", 0))  # 降序且稳定。
        for name, spec in ordered:  # 遍历所有已注册界面。
            if self._screen_match(spec):  # 命中则返回该界面名。
                return name  # 返回界面名。
        return None  # 全部未命中返回 None。

    def is_screen(self, name: str) -> bool:
        """单帧检测当前是否处于指定界面。

        恒为单帧语义：即使 spec 配置了 min_frames，本方法也不做多帧确认；
        连续帧确认仅作用于 wait_screen/assert_screen 的轮询判定。
        """
        spec = self.screens.get(name)  # 读取界面判定描述。
        if spec is None:  # 界面未注册。
            self.log_warning(f"未注册界面: {name}")  # 记录未注册。
            return False  # 未注册判定为不在该界面。
        return self._screen_match(spec)  # 按判定描述检测。

    def wait_screen(self, name: str, time_out=10, raise_if_not_found=False):
        """等待进入指定界面，复用 wait_until 的轮询与超时机制。

        spec 的 min_frames（默认 1）表示需连续多少次轮询命中才算进入：
        轮询条件每轮在不同帧上求值，连续命中计数天然逐帧；未命中即清零。
        默认值下与原单帧判定行为一致。
        """
        spec = self.screens.get(name)  # 读取界面判定描述。
        if spec is None:  # 界面未注册。
            raise ValueError(f"未注册界面: {name}")  # 未注册直接报错。
        min_frames = max(1, int(spec.get("min_frames", 1)))  # 缺省退化为单帧语义。
        consecutive = {"hits": 0}  # 实例级计数状态：跨轮次递增，未命中清零。

        def condition():  # 轮询条件：wait_until 每轮取新帧后调用一次。
            if self._screen_match(spec):  # 本轮命中。
                consecutive["hits"] += 1  # 连续命中数递增。
            else:  # 本轮未命中。
                consecutive["hits"] = 0  # 清零重来。
            return consecutive["hits"] >= min_frames  # 达到连续帧要求才算进入。

        return self.wait_until(condition,  # 轮询界面判定条件。
                               time_out=time_out,  # 超时时间。
                               raise_if_not_found=raise_if_not_found)  # 超时是否抛异常。

    def assert_screen(self, name: str, time_out=10):
        """断言处于指定界面，超时抛 WaitFailedException（由 try_step 捕获并恢复）。"""
        if not self.wait_screen(name, time_out=time_out):  # 等待界面超时。
            cur = self.current_screen()  # 识别当前实际界面用于日志。
            self.log_warning(f"界面断言失败: 期望 {name}，当前 {cur}")  # 记录断言失败。
            raise WaitFailedException(f"not on screen: {name} (current: {cur})")  # 抛等待失败异常。

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