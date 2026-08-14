import os
import time

import cv2
import win32con
import win32gui

import ok
import ok.gui.StartController as start_controller_module
from ok import Logger, og
from ok.device.capture_methods.bitblt_utils import clean_up_bitblt, capture_by_bitblt
from ok.gui.Communicate import communicate
import ok.util.GlobalConfig as _global_config_module
from ok.util.process import execute, is_admin
from ok.util.window import find_hwnd, get_window_bounds, resize_window, show_title_bar

logger = Logger.get_logger(__name__)

# 基础设置中新增的启动器相关选项
LAUNCHER_PATH_KEY = '启动器路径'
LAUNCHER_BUTTON_TEXT = '启动'
LAUNCHER_BUTTON_REGION = (0.05, 0.83, 0.30, 0.93)

# 游戏窗口最小尺寸(客户端区域)，低于此尺寸会自动调整为该尺寸，保证后续识别正常
MIN_GAME_WINDOW_SIZE = (1280, 720)

# 后台触发任务轮询间隔(毫秒)，调高可降低系统资源占用
TRIGGER_INTERVAL_KEY = 'Trigger Interval'
TRIGGER_INTERVAL_MS = 100

# 与本项目无关、需要从基础设置中移除的选项
_BASIC_OPTIONS_REMOVE_KEYS = [
    'Mute Game while in Background',
    'Auto Resize Game Window',
    'Use DirectML',
    _global_config_module.KILL_LAUNCHER_AFTER_START,
    'Launch with DX11',
]

_basic_options_extra_default = {
    LAUNCHER_PATH_KEY: '',
}
_basic_options_extra_type = {
    LAUNCHER_PATH_KEY: {
        'type': 'file_selector',
        'selector_type': 'file',
        'dialog_title': '选择 NIKKE 启动器文件',
        'filter': '所有文件 (*)',
        'initial_directory': 'desktop',
    },
}
_basic_options_extra_description = {
    LAUNCHER_PATH_KEY: 'NIKKE 启动器文件路径(nikke_launcher.exe)。选择桌面快捷方式(.lnk)时会自动解析其指向的执行文件。',
    TRIGGER_INTERVAL_KEY: '后台触发任务每轮检测之间的额外延时(毫秒)。调大可降低系统资源占用，但会让后台响应变慢。',
}


def _launcher_path_first(conf_dict):
    # 让启动器路径选项排在基础设置最上面
    new = {}
    if LAUNCHER_PATH_KEY in conf_dict:
        new[LAUNCHER_PATH_KEY] = conf_dict[LAUNCHER_PATH_KEY]
    for key, value in conf_dict.items():
        if key != LAUNCHER_PATH_KEY:
            new[key] = value
    return new


def _get_desktop_path():
    # 获取当前用户的桌面目录(CSIDL_DESKTOPDIRECTORY = 0x10)
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
        if buf.value and os.path.isdir(buf.value):
            return buf.value
    except Exception as e:
        logger.error(f'get desktop path error', e)
    return None


def _patch_file_selector_initial_directory():
    # 让启动器路径选择框默认打开到桌面目录，方便直接看到桌面快捷方式
    from ok.gui.tasks.LabelAndFileSelector import LabelAndFileSelector

    original = LabelAndFileSelector._initial_directory

    def _initial_directory(self, current_value):
        initial = self.config_type.get('initial_directory')
        if initial == 'desktop':
            desktop = _get_desktop_path()
            if desktop:
                return desktop
        return original(self, current_value)

    LabelAndFileSelector._initial_directory = _initial_directory


def _patch_create_basic_options():
    # 把启动器相关选项注入 create_basic_options 返回的默认配置中。
    # 这样 Config 从磁盘加载时会把这些键当作已知默认项，已保存的启动器路径
    # 才不会被 Config.verify_config 当作未知键丢弃。
    original = _global_config_module.create_basic_options

    def _create_basic_options(enable_blur=False):
        options = original(enable_blur=enable_blur)
        # 调高后台触发任务轮询间隔的默认值，避免过快地空转占用系统资源
        options.default_config[TRIGGER_INTERVAL_KEY] = TRIGGER_INTERVAL_MS
        # 移除与本项目无关的设置项
        for key in _BASIC_OPTIONS_REMOVE_KEYS:
            options.default_config.pop(key, None)
            options.config_description.pop(key, None)
            if options.config_type:
                options.config_type.pop(key, None)
        for key, value in _basic_options_extra_default.items():
            options.default_config.setdefault(key, value)
        options.config_description.update(_basic_options_extra_description)
        if options.config_type is None:
            options.config_type = {}
        options.config_type.update(_basic_options_extra_type)
        options.default_config = _launcher_path_first(options.default_config)
        return options

    _global_config_module.create_basic_options = _create_basic_options


class _CaptureContext:
    # capture_by_bitblt 需要的上下文对象，用于复用 DC 与位图
    def __init__(self):
        self.last_hwnd = 0
        self.last_width = 0
        self.last_height = 0
        self.window_dc = None
        self.dc_object = None
        self.compatible_dc = None
        self.bitmap = None


class NikkeStartController(start_controller_module.StartController):
    LAUNCHER_START_TIMEOUT = 60
    LAUNCHER_BUTTON_SEARCH_TIMEOUT = 120
    LAUNCHER_POLL_INTERVAL = 1.0
    LAUNCHER_SETTLE_SECONDS = 3
    LAUNCHER_STABLE_SECONDS = 2

    def start_device(self, initial_refresh_done=False):
        device = og.device_manager.get_preferred_device()
        logger.info(f'start_device: {device}')
        # 先做管理员判断（PC 版需要管理员权限）
        if device and not device['connected'] and device['device'] == 'windows' and not is_admin():
            communicate.starting_emulator.emit(True,
                                               'PC版本需要管理员权限，请以管理员身份重新启动本程序!', 0)
            communicate.restart_admin.emit()
            return False
        if device and not device['connected']:
            if device['device'] != 'windows':
                return super().start_device(initial_refresh_done=initial_refresh_done)
            if self._game_process_running():
                # 游戏主进程已存在，直接等待游戏就绪，不再启动启动器
                logger.info('game main process already running, skip launcher')
            else:
                launcher_path = self._get_launcher_path()
                if not launcher_path:
                    communicate.starting_emulator.emit(True,
                                                       '未配置启动器路径，请在设置->基础设置中选择启动器，或手动启动游戏!', 0)
                    return False
                if not self._start_device_via_launcher(device, launcher_path):
                    return False
        if not self._wait_until_device_ready(refresh_first=not initial_refresh_done):
            return False
        self._ensure_min_game_window_size()
        communicate.starting_emulator.emit(True, None, 0)
        return True

    def check_resolution(self):
        # 窗口尺寸由 _ensure_min_game_window_size 在挂载后显式调整，
        # 启动等待阶段不在这里做硬性分辨率检查，避免自动缩放与最小尺寸调整逻辑冲突
        return None

    def _ensure_min_game_window_size(self):
        # 检测游戏主进程窗口尺寸，若小于 1280x720(客户端区域) 则自动调整为 1280x720
        try:
            capture_method = getattr(og.device_manager, 'capture_method', None)
            hwnd_window = getattr(capture_method, 'hwnd_window', None)
            if hwnd_window is None or not hwnd_window.hwnd:
                logger.warning('game window not attached, skip resize')
                return
            target_width, target_height = MIN_GAME_WINDOW_SIZE
            if hwnd_window.width >= target_width and hwnd_window.height >= target_height:
                logger.info(
                    f'game window {hwnd_window.width}x{hwnd_window.height} already >= {target_width}x{target_height}, skip resize')
                return
            show_title_bar(hwnd_window.hwnd)
            _, _, window_width, window_height, client_width, client_height, _ = get_window_bounds(hwnd_window.hwnd)
            title_height = max(0, window_height - client_height)
            border = max(0, window_width - client_width)
            resize_window(hwnd_window.hwnd, target_width + border, target_height + title_height)
            hwnd_window.do_update_window_size()
            logger.info(
                f'game window resized to {target_width}x{target_height}, now {hwnd_window.width}x{hwnd_window.height}')
        except Exception as e:
            logger.error(f'ensure min game window size error', e)

    def _start_device_via_launcher(self, device, launcher_path):
        exe = self._resolve_launcher_exe(launcher_path)
        if not exe:
            communicate.starting_emulator.emit(True, '启动器路径无效，请在设置->基础设置中重新选择!', 0)
            return False
        if not execute(exe, start_method=self.start_method):
            communicate.starting_emulator.emit(True, '启动器启动失败，请手动启动游戏!', 0)
            return False
        if not self._click_launcher_button(os.path.basename(exe)):
            return False
        return True

    def _get_launcher_path(self):
        basic = og.global_config.get_config('Basic Options')
        return str(basic.get(LAUNCHER_PATH_KEY) or '').strip()

    def _launcher_button_text(self):
        return LAUNCHER_BUTTON_TEXT

    def _launcher_button_region(self):
        return LAUNCHER_BUTTON_REGION

    def _resolve_launcher_exe(self, path):
        if not path:
            return None
        if path.lower().endswith('.lnk'):
            try:
                import win32com.client
                shell = win32com.client.Dispatch('WScript.Shell')
                shortcut = shell.CreateShortCut(path)
                target = (shortcut.TargetPath or '').strip()
                if target and os.path.exists(target):
                    logger.info(f'resolved .lnk {path} -> {target}')
                    return target
                logger.error(f'.lnk target not found: {target} from {path}')
                return None
            except Exception as e:
                logger.error(f'resolve .lnk error {path}', e)
                return None
        if os.path.exists(path):
            return path
        logger.error(f'launcher path not exists {path}')
        return None

    def _game_exe_names(self):
        names = self.config.get('windows', {}).get('exe') or ['nikke.exe']
        if isinstance(names, str):
            names = [names]
        return [n for n in names if n]

    def _game_window_found(self):
        try:
            _, hwnd, _, _, _, _, _, _ = find_hwnd(None, self._game_exe_names(), 1, 1)
            return hwnd is not None and hwnd > 0
        except Exception as e:
            logger.error(f'find game hwnd error', e)
            return False

    def _game_process_running(self):
        # 判断游戏主进程是否已存在（即使窗口未显示也算运行中）
        exe_names = [n.lower() for n in self._game_exe_names()]
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                try:
                    name = (proc.info.get('name') or '').lower()
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
                if name in exe_names:
                    return True
        except Exception as e:
            logger.error(f'check game process error', e)
            return False
        return False

    def _wait_until_launcher_window(self, exe_name):
        # 配置的启动器本身可能就是游戏本体(或其快捷方式指向游戏)，直接跳过启动器交互
        if exe_name.lower() in [n.lower() for n in self._game_exe_names()]:
            logger.info(f'launcher exe {exe_name} is a game exe, skip launcher interaction')
            return 0
        deadline = time.monotonic() + self.LAUNCHER_START_TIMEOUT
        while not self.exit_event.is_set():
            if self._game_window_found():
                return 0
            try:
                _, hwnd, full_path, _, _, _, _, _ = find_hwnd(None, [exe_name], 1, 1)
            except Exception as e:
                logger.error(f'find launcher hwnd error', e)
                hwnd = 0
            if hwnd and hwnd > 0:
                logger.info(f'launcher window found hwnd={hwnd} {full_path}')
                return hwnd
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            communicate.starting_emulator.emit(False, None, int(remaining))
            time.sleep(self.LAUNCHER_POLL_INTERVAL)
        return None

    def _wait_until_launcher_stable(self, launcher_hwnd):
        # 等待启动器加载完成：窗口尺寸稳定一段时间，且至少经过最小等待时间，期间持续置于前台
        deadline = time.monotonic() + self.LAUNCHER_START_TIMEOUT
        first_seen = time.monotonic()
        stable_size = None
        stable_since = None
        while not self.exit_event.is_set():
            if not win32gui.IsWindow(launcher_hwnd):
                logger.error(f'launcher window disappeared while waiting to stabilize')
                return False
            self._bring_window_forward(launcher_hwnd)
            rect = win32gui.GetWindowRect(launcher_hwnd)
            size = (rect[2] - rect[0], rect[3] - rect[1])
            now = time.monotonic()
            if size[0] <= 0 or size[1] <= 0:
                stable_size = None
                stable_since = None
            elif size != stable_size:
                stable_size = size
                stable_since = now
            elif now - stable_since >= self.LAUNCHER_STABLE_SECONDS and now - first_seen >= self.LAUNCHER_SETTLE_SECONDS:
                logger.info(f'launcher window stable {size[0]}x{size[1]}, start ocr')
                return True
            if now > deadline:
                logger.error(f'launcher window not stable within {self.LAUNCHER_START_TIMEOUT}s')
                return False
            communicate.starting_emulator.emit(False, None, int(deadline - now))
            time.sleep(self.LAUNCHER_POLL_INTERVAL)
        return False

    def _click_launcher_button(self, exe_name):
        launcher_hwnd = self._wait_until_launcher_window(exe_name)
        if launcher_hwnd == 0:
            return True
        if launcher_hwnd is None:
            communicate.starting_emulator.emit(True, '启动器窗口未找到，请手动启动游戏!', 0)
            return False
        # 先等待启动器加载完成并置于前台，再进行特定区域 OCR
        if not self._wait_until_launcher_stable(launcher_hwnd):
            communicate.starting_emulator.emit(True, '启动器界面未加载完成，请手动启动游戏!', 0)
            return False
        button_text = self._launcher_button_text()
        region = self._launcher_button_region()
        context = _CaptureContext()
        deadline = time.monotonic() + self.LAUNCHER_BUTTON_SEARCH_TIMEOUT
        try:
            while not self.exit_event.is_set():
                if self._game_window_found():
                    return True
                self._bring_window_forward(launcher_hwnd)
                center = self._capture_and_find_button(context, launcher_hwnd, button_text, region)
                if center is not None:
                    self._click_screen_point(launcher_hwnd, *center)
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    communicate.starting_emulator.emit(True, '启动器启动按钮未找到，请手动启动游戏!', 0)
                    return False
                communicate.starting_emulator.emit(False, None, int(remaining))
                time.sleep(self.LAUNCHER_POLL_INTERVAL)
        finally:
            clean_up_bitblt(context)
        return False

    def _capture_and_find_button(self, context, launcher_hwnd, button_text, region):
        try:
            _, _, _, _, client_w, client_h, _ = get_window_bounds(launcher_hwnd)
        except Exception as e:
            logger.error(f'get launcher window bounds error', e)
            return None
        if not client_w or not client_h:
            return None
        frame = capture_by_bitblt(context, launcher_hwnd, client_w, client_h, 0, 0, True)
        if frame is None:
            return None
        center = self._find_button_center(frame, button_text, region)
        if center is None:
            return None
        rect = win32gui.GetWindowRect(launcher_hwnd)
        return rect[0] + center[0], rect[1] + center[1]

    def _find_button_center(self, frame, button_text, region):
        height, width = frame.shape[:2]
        if region is not None:
            x1 = max(0, int(region[0] * width))
            y1 = max(0, int(region[1] * height))
            x2 = min(width, int(region[2] * width))
            y2 = min(height, int(region[3] * height))
            if x2 > x1 and y2 > y1:
                crop = frame[y1:y2, x1:x2]
                center = self._find_button_in_image(crop, button_text, x1, y1)
                if center is not None:
                    return center
        return self._find_button_in_image(frame, button_text, 0, 0)

    def _find_button_in_image(self, image, button_text, offset_x, offset_y):
        result = self._ocr_frame(image)
        if not result or result[0] is None:
            return None
        best = None
        best_area = 0
        try:
            for i in range(len(result[0])):
                pos = result[0][i][0]
                text = str(result[0][i][1][0])
                if button_text and button_text.lower() not in text.lower():
                    continue
                xs = [p[0] for p in pos]
                ys = [p[1] for p in pos]
                bx = min(xs)
                by = min(ys)
                bw = max(xs) - bx
                bh = max(ys) - by
                area = bw * bh
                if area > best_area:
                    best = (bx + bw / 2, by + bh / 2)
                    best_area = area
        except Exception as e:
            logger.error(f'parse ocr result error', e)
            return None
        if best is None:
            return None
        return best[0] + offset_x, best[1] + offset_y

    def _ocr_frame(self, frame):
        try:
            # onnxocr 需要 3 通道 BGR，而 capture_by_bitblt 返回的是 4 通道 BGRA
            if frame is not None and frame.ndim == 3 and frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            return og.executor.ocr_lib('default').ocr(frame)
        except Exception as e:
            logger.error(f'launcher ocr error', e)
            return None

    def _bring_window_forward(self, hwnd):
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            logger.warning(f'bring launcher window forward failed: {e}')

    def _click_screen_point(self, launcher_hwnd, screen_x, screen_y):
        self._bring_window_forward(launcher_hwnd)
        time.sleep(0.15)
        try:
            from pynput import mouse as pynput_mouse
            controller = pynput_mouse.Controller()
            controller.position = (int(screen_x), int(screen_y))
            time.sleep(0.05)
            controller.click(pynput_mouse.Button.left)
            logger.info(f'launcher start button clicked at {int(screen_x)},{int(screen_y)}')
            return True
        except Exception as e:
            logger.error(f'click launcher start button error', e)
            communicate.starting_emulator.emit(True, f'模拟点击启动器失败: {e}', 0)
            return False


# 通过包装 create_basic_options 注入自定义基础设置项（在 Config 加载磁盘配置之前生效）
_patch_create_basic_options()
# App.__init__ 中 `from ok.gui.StartController import StartController` 会取到子类
start_controller_module.StartController = NikkeStartController
# 启动器路径选择框默认打开桌面目录
_patch_file_selector_initial_directory()
