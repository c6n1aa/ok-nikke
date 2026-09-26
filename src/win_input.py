"""合成触控指针（WM_POINTER）输入后端。

用 CreateSyntheticPointerDevice / InjectSyntheticPointerInput 注入 PT_TOUCH 触控，
游戏收到 WM_POINTER 消息，绕过 NIKKE 对 SendInput / PostMessage 的过滤。机制取自
MaaFramework AnchoredTouchInput：
- 首个接触点是「主指针」会被提升为鼠标事件抢光标，故放 4x4 锚点窗口先按下占住主指针，
  操作点作第二接触点注入。
- ptPixelLocation 期望虚拟屏幕左上角相对坐标，须减 (SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN)。
- 命中判定认 Z 序，注入前把游戏窗口提到最上层。
- 键盘未实现（no-op 告警）。
"""

import ctypes
import queue
import random
import threading
import time
from ctypes import wintypes

import win32con
import win32gui
from ok.device.interaction_methods.base import BaseInteraction
from ok.util.logger import Logger

logger = Logger.get_logger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
PT_TOUCH = 2
POINTER_FEEDBACK_NONE = 3

POINTER_FLAG_INRANGE = 0x00000002
POINTER_FLAG_INCONTACT = 0x00000004
POINTER_FLAG_CONFIDENCE = 0x00000400
POINTER_FLAG_DOWN = 0x00010000
POINTER_FLAG_UPDATE = 0x00020000
POINTER_FLAG_UP = 0x00040000

FLAG_DOWN = POINTER_FLAG_DOWN | POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT | POINTER_FLAG_CONFIDENCE
FLAG_UPDATE = POINTER_FLAG_UPDATE | POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT | POINTER_FLAG_CONFIDENCE
FLAG_UP = POINTER_FLAG_UP

TOUCH_FLAG_NONE = 0x00000000
TOUCH_MASK = 0x00000001 | 0x00000002 | 0x00000004  # CONTACTAREA | ORIENTATION | PRESSURE

# 锚点窗口参数
ANCHOR_SIZE = 4
ANCHOR_MARGIN = 8
ANCHOR_ALPHA = 1  # alpha 为 0 时命中穿透，取最小可见值

# 锚点接触点 id=1，操作点 id=2（id 必须是小整数，大值会被合成设备整帧拒绝）
ANCHOR_POINTER_ID = 1
CONTACT_POINTER_ID = 2

HOLD_KEEPALIVE_SECONDS = 0.1  # 按住期间无新命令时的保活注入间隔；超过约 400ms 不提交新帧会被系统回收接触点
HOLD_TIMEOUT_SECONDS = 5  # 按住超过该秒数无新命令则自动释放，避免任务暂停时残留按住状态

# 窗口样式
WS_POPUP = 0x80000000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002
SW_SHOWNOACTIVATE = 4
COLOR_WINDOW = 5

# 锚点窗口 WndProc 需要消费的指针消息（返回 0，否则主指针被提升为鼠标事件）
WM_NCHITTEST = 0x0084
WM_MOUSEACTIVATE = 0x0021
WM_POINTERACTIVATE = 0x024B
_POINTER_MSGS = {
    0x0246,  # WM_POINTERDOWN
    0x0247,  # WM_POINTERUP
    0x0245,  # WM_POINTERUPDATE
    0x0249,  # WM_POINTERENTER
    0x024A,  # WM_POINTERLEAVE
    0x024C,  # WM_POINTERCAPTURECHANGED
    0x0242,  # WM_NCPOINTERDOWN
    0x0241,  # WM_NCPOINTERUPDATE
    0x0243,  # WM_NCPOINTERUP
    0x024D,  # WM_TOUCHHITTESTING
}
HTCLIENT = 1
MA_NOACTIVATE = 3
PA_NOACTIVATE = 3

PM_REMOVE = 0x0001

# 系统指标索引
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77

# DPI：注入坐标必须用物理像素
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


# ---------------------------------------------------------------------------
# ctypes 结构定义
# ---------------------------------------------------------------------------
class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _POINTER_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerType", wintypes.UINT),
        ("pointerId", wintypes.UINT),
        ("frameId", wintypes.UINT),
        ("pointerFlags", wintypes.UINT),
        ("sourceDevice", wintypes.HANDLE),
        ("hwndTarget", wintypes.HWND),
        ("ptPixelLocation", _POINT),
        ("ptHimetricLocation", _POINT),
        ("ptPixelLocationRaw", _POINT),
        ("ptHimetricLocationRaw", _POINT),
        ("dwTime", wintypes.DWORD),
        ("historyCount", wintypes.UINT),
        ("InputData", ctypes.c_int32),
        ("dwKeyStates", wintypes.DWORD),
        ("PerformanceCount", ctypes.c_uint64),
        ("ButtonChangeType", ctypes.c_int32),
    ]


class _POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", _POINTER_INFO),
        ("touchFlags", wintypes.UINT),
        ("touchMask", wintypes.UINT),
        ("rcContact", _RECT),
        ("rcContactRaw", _RECT),
        ("orientation", wintypes.UINT),
        ("pressure", wintypes.UINT),
    ]


class _POINTER_TYPE_INFO(ctypes.Structure):
    # C 里 type 后面是匿名 union，这里只用 PT_TOUCH，touchInfo 的对齐偏移与 union 一致
    _fields_ = [
        ("type", wintypes.UINT),
        ("touchInfo", _POINTER_TOUCH_INFO),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", _POINT),
        ("lPrivate", wintypes.DWORD),
    ]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                              ctypes.c_size_t, ctypes.c_ssize_t)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


# ---------------------------------------------------------------------------
# API 声明（显式声明 restype/argtypes，避免 64 位句柄/指针被截断）
# ---------------------------------------------------------------------------
# use_last_error=True：保住 GetLastError，ctypes.get_last_error() 才能取到 API 真实错误码
_user32 = ctypes.WinDLL('user32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

_user32.CreateSyntheticPointerDevice.restype = wintypes.HANDLE
_user32.CreateSyntheticPointerDevice.argtypes = [wintypes.UINT, wintypes.ULONG, wintypes.UINT]

_user32.InjectSyntheticPointerInput.restype = wintypes.BOOL
_user32.InjectSyntheticPointerInput.argtypes = [wintypes.HANDLE,
                                                ctypes.POINTER(_POINTER_TYPE_INFO), wintypes.UINT]

_user32.DestroySyntheticPointerDevice.restype = None
_user32.DestroySyntheticPointerDevice.argtypes = [wintypes.HANDLE]

_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]

_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]

_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]

_user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
_user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]

_user32.ShowWindow.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

_user32.DestroyWindow.restype = wintypes.BOOL
_user32.DestroyWindow.argtypes = [wintypes.HWND]

_user32.UnregisterClassW.restype = wintypes.BOOL
_user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]

_user32.PeekMessageW.restype = wintypes.BOOL
_user32.PeekMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]

_user32.TranslateMessage.restype = wintypes.BOOL
_user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]

_user32.DispatchMessageW.restype = ctypes.c_ssize_t
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]

_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]

_user32.SetThreadDpiAwarenessContext.restype = wintypes.BOOL
_user32.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]

_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


@_WNDPROC
def _anchor_wnd_proc(hwnd, msg, wparam, lparam):
    # 消费指针消息返回 0，阻止主指针被提升为鼠标事件
    if msg in _POINTER_MSGS:
        return 0
    if msg == WM_NCHITTEST:
        return HTCLIENT
    if msg == WM_MOUSEACTIVATE:
        return MA_NOACTIVATE
    if msg == WM_POINTERACTIVATE:
        return PA_NOACTIVATE
    return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _pump_messages():
    msg = _MSG()
    while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
        _user32.TranslateMessage(ctypes.byref(msg))
        _user32.DispatchMessageW(ctypes.byref(msg))


def _to_inject_coord(x, y):
    """把屏幕绝对坐标转为 ptPixelLocation 期望的虚拟屏幕左上角相对坐标。"""
    return x - _user32.GetSystemMetrics(SM_XVIRTUALSCREEN), y - _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)


def _bring_to_front(hwnd):
    """把窗口提到 Z 序最上层。SetForegroundWindow 受前台锁限制可能失败，用 topmost 切换兜底。"""
    if not hwnd:
        return
    try:
        if win32gui.GetForegroundWindow() == hwnd:
            return  # 已在前台，跳过后续置前流程
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        if win32gui.GetForegroundWindow() != hwnd:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            time.sleep(0.05)
    except Exception as e:
        logger.warning(f'bring to front failed: {e}')


class _Command:
    """一条注入命令：down / move / up。"""

    __slots__ = ("action", "x", "y", "done")

    def __init__(self, action, x=0, y=0):
        self.action = action
        self.x = x
        self.y = y
        self.done = threading.Event()


class SyntheticTouch(BaseInteraction):
    """合成触控指针交互后端，仅实现鼠标/触控，键盘一律 no-op。"""

    CLICK_JITTER = 3  # 点击坐标抖动幅度（像素）

    def __init__(self, capture, hwnd_window):
        super().__init__(capture)
        self.hwnd_window = hwnd_window
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker = None
        self._ready = False
        self._setup_failed = False
        # 以下字段仅 worker 线程访问
        self._device = None
        self._anchor_hwnd = None
        self._class_name = None
        self._anchor_inject_pos = (0, 0)
        self._holding = False
        self._contact_pos = (0, 0)

    # ------------------------------------------------------------------
    # 框架接口
    # ------------------------------------------------------------------
    def should_capture(self):
        return True

    def click(self, x=-1, y=-1, move_back=False, name=None, down_time=0.05, move=True, key="left"):
        if key != "left":
            logger.warning(f'SyntheticTouch only supports left click, got key={key}')
            return
        if x == -1 or y == -1:
            logger.warning('SyntheticTouch requires explicit coordinates, ignored click without position')
            return
        jx = x + random.randint(-self.CLICK_JITTER, self.CLICK_JITTER)
        jy = y + random.randint(-self.CLICK_JITTER, self.CLICK_JITTER)
        if not self.mouse_down(jx, jy, name=name):
            return
        time.sleep(max(down_time, 0.05) + random.uniform(0, 0.02))  # 按住时长微随机，避免固定时长指纹
        self.mouse_up()

    def swipe(self, from_x, from_y, to_x, to_y, duration, settle_time=0):
        if not self.mouse_down(from_x, from_y):
            return
        # duration 单位是毫秒。步数=duration/100、每步 10ms，与框架 pynput/post_message 同口径，
        # 实际耗时约为 duration 的 1/10，即所有滑动手势偏快。
        steps = max(1, int(duration / 100))
        for i in range(1, steps + 1):
            x = round(from_x + (to_x - from_x) * i / steps)
            y = round(from_y + (to_y - from_y) * i / steps)
            self.move(x, y)
            time.sleep(0.01)
        self.mouse_up()
        if settle_time > 0:
            time.sleep(settle_time)

    def scroll(self, x, y, scroll_amount):
        # 触控拖动近似滚轮：滚轮向上（scroll_amount>0）等效手指向下拖
        if scroll_amount == 0:
            return
        direction = 1 if scroll_amount > 0 else -1
        distance = 200
        self.swipe(x, y, x, y + direction * distance, duration=300)  # swipe 的 duration 单位是毫秒

    def move(self, x, y):
        if not self._holding or x == -1 or y == -1:
            return
        self._submit(_Command("move", *self._to_screen_inject(x, y)))

    def mouse_down(self, x=-1, y=-1, name=None, key="left"):
        if key != "left":
            logger.warning(f'SyntheticTouch only supports left button, got key={key}')
            return False
        if x == -1 or y == -1:
            logger.warning('SyntheticTouch requires explicit coordinates, ignored mouse_down without position')
            return False
        if not self._ensure_worker():
            return False
        if self._holding:
            # 已按住时重复按下：先抬掉旧接触点，同一 pointerId 重复 DOWN 会被系统拒绝
            self._submit(_Command("up"))
        _bring_to_front(self.hwnd_window.hwnd if self.hwnd_window else 0)
        self._submit(_Command("down", *self._to_screen_inject(x, y)))
        self._holding = True
        return True

    def mouse_up(self, key="left"):
        if key != "left":
            return
        if not self._holding:
            return
        self._submit(_Command("up"))
        self._holding = False

    # 键盘未实现，一律 no-op 并告警
    def send_key(self, key, down_time=0.02):
        logger.warning(f'SyntheticTouch does not support keyboard, ignored key={key}')

    def send_key_down(self, key):
        logger.warning(f'SyntheticTouch does not support keyboard, ignored key={key}')

    def send_key_up(self, key):
        logger.warning(f'SyntheticTouch does not support keyboard, ignored key={key}')

    def input_text(self, text):
        logger.warning('SyntheticTouch does not support keyboard, ignored input_text')

    def back(self):
        logger.warning('SyntheticTouch does not support keyboard, ignored back')

    def on_run(self):
        if self.hwnd_window and getattr(self.hwnd_window, 'hwnd', 0):
            _bring_to_front(self.hwnd_window.hwnd)

    def on_destroy(self):
        if self._holding:
            self._submit(_Command("up"))  # 销毁前补发 UP，游戏侧收到配对的抬起
            self._holding = False
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=2)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _to_screen_inject(self, x, y):
        """把画面相对坐标转为注入坐标（屏幕绝对坐标减虚拟屏幕原点）。"""
        abs_x, abs_y = self.capture.get_abs_cords(x, y) if x != -1 and y != -1 else (0, 0)
        # get_abs_cords 可能返回浮点（OCR/模板中心点、DPI 缩放换算），而 _POINT/_RECT
        # 字段是 LONG，赋浮点会抛 TypeError，这里统一取整
        return _to_inject_coord(int(round(abs_x)), int(round(abs_y)))

    def _submit(self, cmd):
        if not self._ready or self._worker is None or not self._worker.is_alive():
            logger.warning(f'SyntheticTouch worker not ready, drop {cmd.action} command')
            return
        self._queue.put(cmd)
        if not cmd.done.wait(timeout=3):
            logger.warning(f'SyntheticTouch {cmd.action} timed out after 3s, worker may be stuck')

    def _ensure_worker(self):
        if self._ready:
            return True
        if self._setup_failed:
            return False
        try:
            _ = _user32.CreateSyntheticPointerDevice
            _ = _user32.InjectSyntheticPointerInput
            _ = _user32.DestroySyntheticPointerDevice
        except AttributeError:
            logger.error('synthetic pointer injection unavailable, Windows 10 1809+ required')
            self._setup_failed = True
            return False
        self._worker = threading.Thread(target=self._worker_main, name="synthetic-touch", daemon=True)
        self._worker.start()
        # 等待 worker 完成初始化（最多 3 秒）
        deadline = time.monotonic() + 3
        while not self._ready and not self._setup_failed and time.monotonic() < deadline:
            time.sleep(0.01)
        return self._ready

    def _worker_main(self):
        try:
            _user32.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        except Exception as e:
            logger.warning(f'SetThreadDpiAwarenessContext failed: {e}')
        try:
            self._setup_device()
        except Exception as e:
            logger.error('SyntheticTouch setup failed', e)
            self._setup_failed = True
            return
        self._ready = True
        last_keepalive = time.monotonic()
        last_command = time.monotonic()
        try:
            while not self._stop_event.is_set():
                _pump_messages()
                # 阻塞等第一条命令：put 立即唤醒 worker，消除旧 5ms 轮询对注入节奏的抖动；
                # 空闲时最多等一个保活周期再醒来做保活/超时检查。
                try:
                    cmd = self._queue.get(timeout=HOLD_KEEPALIVE_SECONDS)
                except queue.Empty:
                    cmd = None
                if cmd is not None:
                    self._execute(cmd)
                    cmd.done.set()
                    if cmd.action in ("down", "move"):
                        last_command = last_keepalive = time.monotonic()
                    # 同一唤醒内排空积压命令，避免一条命令一次阻塞等待的节流。
                    while True:
                        try:
                            cmd = self._queue.get_nowait()
                        except queue.Empty:
                            break
                        self._execute(cmd)
                        cmd.done.set()
                        if cmd.action in ("down", "move"):
                            last_command = last_keepalive = time.monotonic()
                if self._holding and time.monotonic() - last_command > HOLD_TIMEOUT_SECONDS:
                    self._release_hold()  # 任务暂停/卡住时自动释放，避免残留按住状态
                    self._holding = False
                    continue
                if self._holding and time.monotonic() - last_keepalive > HOLD_KEEPALIVE_SECONDS:
                    self._inject_hold_update()
                    last_keepalive = time.monotonic()
        except Exception as e:
            # 不清 _setup_failed：崩溃后 teardown 已收尾，下次 _ensure_worker 可重建 worker
            logger.error('SyntheticTouch worker crashed', e)
        finally:
            self._ready = False
            self._teardown_device()

    def _setup_device(self):
        # 锚点窗口放在主屏四角之一，避开目标窗口
        ox, oy = self._choose_anchor_origin()
        self._class_name = f"PySyntheticTouch_{id(self)}"
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = _anchor_wnd_proc
        wc.hInstance = _kernel32.GetModuleHandleW(None)
        wc.hbrBackground = COLOR_WINDOW + 1
        wc.lpszClassName = self._class_name
        if _user32.RegisterClassExW(ctypes.byref(wc)) == 0:
            raise RuntimeError(f'RegisterClassExW failed: {ctypes.get_last_error()}')

        self._anchor_hwnd = _user32.CreateWindowExW(
            WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_LAYERED,
            self._class_name, "", WS_POPUP,
            ox, oy, ANCHOR_SIZE, ANCHOR_SIZE,
            None, None, wc.hInstance, None)
        if not self._anchor_hwnd:
            raise RuntimeError(f'CreateWindowExW failed: {ctypes.get_last_error()}')

        _user32.SetLayeredWindowAttributes(self._anchor_hwnd, 0, ANCHOR_ALPHA, LWA_ALPHA)
        _user32.ShowWindow(self._anchor_hwnd, SW_SHOWNOACTIVATE)
        self._anchor_inject_pos = _to_inject_coord(ox + ANCHOR_SIZE // 2, oy + ANCHOR_SIZE // 2)
        _pump_messages()

        self._device = _user32.CreateSyntheticPointerDevice(PT_TOUCH, 2, POINTER_FEEDBACK_NONE)
        if not self._device:
            raise RuntimeError(f'CreateSyntheticPointerDevice failed: {ctypes.get_last_error()}')
        logger.info(f'SyntheticTouch ready, anchor at {self._anchor_inject_pos}')

    def _teardown_device(self):
        if self._device:
            _user32.DestroySyntheticPointerDevice(self._device)
            self._device = None
        if self._anchor_hwnd:
            _user32.DestroyWindow(self._anchor_hwnd)
            self._anchor_hwnd = None
        if self._class_name:
            _user32.UnregisterClassW(self._class_name, _kernel32.GetModuleHandleW(None))
            self._class_name = None

    def _choose_anchor_origin(self):
        # 主屏四角（非负坐标），避开目标窗口矩形
        width = _user32.GetSystemMetrics(SM_CXSCREEN)
        height = _user32.GetSystemMetrics(SM_CYSCREEN)
        candidates = [
            (ANCHOR_MARGIN, ANCHOR_MARGIN),
            (width - ANCHOR_SIZE - ANCHOR_MARGIN, ANCHOR_MARGIN),
            (ANCHOR_MARGIN, height - ANCHOR_SIZE - ANCHOR_MARGIN),
            (width - ANCHOR_SIZE - ANCHOR_MARGIN, height - ANCHOR_SIZE - ANCHOR_MARGIN),
        ]
        hwnd = self.hwnd_window.hwnd if self.hwnd_window else 0
        if hwnd:
            try:
                wr = win32gui.GetWindowRect(hwnd)
            except Exception:
                wr = None
            if wr:
                for cx, cy in candidates:
                    if not (cx < wr[2] and cx + ANCHOR_SIZE > wr[0] and cy < wr[3] and cy + ANCHOR_SIZE > wr[1]):
                        return cx, cy
        return candidates[0]

    def _make_touch_info(self, pid, x, y, flags):
        info = _POINTER_TYPE_INFO()
        info.type = PT_TOUCH
        ti = info.touchInfo
        ti.pointerInfo.pointerType = PT_TOUCH
        ti.pointerInfo.pointerId = pid
        ti.pointerInfo.pointerFlags = flags
        ti.pointerInfo.ptPixelLocation = _POINT(x, y)
        ti.touchFlags = TOUCH_FLAG_NONE
        ti.touchMask = TOUCH_MASK
        ti.rcContact = _RECT(x - 2, y - 2, x + 2, y + 2)
        ti.rcContactRaw = ti.rcContact
        ti.orientation = 90
        ti.pressure = 32000
        return info

    def _inject_frame(self, touches):
        arr = (_POINTER_TYPE_INFO * len(touches))(*touches)
        if not _user32.InjectSyntheticPointerInput(self._device, arr, len(touches)):
            logger.warning(f'InjectSyntheticPointerInput failed: {ctypes.get_last_error()}')
        _pump_messages()

    def _execute(self, cmd):
        ax, ay = self._anchor_inject_pos
        if cmd.action == "down":
            # 帧1：锚点单独按下，占住主指针身份
            self._inject_frame([self._make_touch_info(ANCHOR_POINTER_ID, ax, ay, FLAG_DOWN)])
            # 帧2：锚点保持 + 操作点按下（操作点作为第二接触点，不是主指针）
            self._inject_frame([
                self._make_touch_info(ANCHOR_POINTER_ID, ax, ay, FLAG_UPDATE),
                self._make_touch_info(CONTACT_POINTER_ID, cmd.x, cmd.y, FLAG_DOWN),
            ])
            self._contact_pos = (cmd.x, cmd.y)
        elif cmd.action == "move":
            self._contact_pos = (cmd.x, cmd.y)
            self._inject_frame([
                self._make_touch_info(ANCHOR_POINTER_ID, ax, ay, FLAG_UPDATE),
                self._make_touch_info(CONTACT_POINTER_ID, cmd.x, cmd.y, FLAG_UPDATE),
            ])
        elif cmd.action == "up":
            self._release_hold()

    def _release_hold(self):
        ax, ay = self._anchor_inject_pos
        cx, cy = self._contact_pos
        self._inject_frame([self._make_touch_info(CONTACT_POINTER_ID, cx, cy, FLAG_UP)])
        self._inject_frame([self._make_touch_info(ANCHOR_POINTER_ID, ax, ay, FLAG_UP)])

    def _inject_hold_update(self):
        ax, ay = self._anchor_inject_pos
        cx, cy = self._contact_pos
        self._inject_frame([
            self._make_touch_info(ANCHOR_POINTER_ID, ax, ay, FLAG_UPDATE),
            self._make_touch_info(CONTACT_POINTER_ID, cx, cy, FLAG_UPDATE),
        ])
