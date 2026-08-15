# NIKKEAutoScript · Windows 窗口定位与执行机制（源码整理）

> 范围：仅 `module/device/win/` 与 `main.py` 中 Windows 平台（win32）相关的代码。
> 主题：脚本启动后**如何找到游戏窗口并执行**（进程查找 → 前台置顶 → 截图 → 点击/滑动）。

---

## 1. 整体调用链

```
main.py
  └─ NikkeAutoScript.loop()                 # 调度主循环
       └─ self.device  (cached_property)    # 懒加载 Device
            └─ module/device/win/device.py:Device(config)
                 └─ AppControl.__init__()   # 构造 Window 对象、校验路径、启动游戏
                      └─ app_start()        # 查找/启动 启动器→登录→切到游戏→锁定分辨率
                 └─ switch_to_program()      # 按 title+class 粗筛，再校验进程路径，置前台
       └─ Device.screenshot()               # 取画面（pyautogui / mss / PrintWindow）
       └─ Device.click() → Input.mouse_click()  # 执行点击
```

平台分支在 `module/base/base.py:42` 与 `main.py:79` 决定加载 win 还是 adb：
```python
# module/base/base.py
if config.CLIENT_PLATFORM == 'adb':
    from module.device.adb.device import Device as DeviceClass
if config.CLIENT_PLATFORM == 'win':
    from module.device.win.device import Device as DeviceClass
```

---

## 2. 入口与 Device 初始化

### 2.1 调度主循环（节选）

`module/main.py` 中 `device` 为懒加载属性，`loop()` 每轮取任务后访问 `self.device` 触发初始化：

```python
# module/main.py (节选)
@cached_property
def device(self):
    if self.config.Client_Platform == 'win':
        from module.device.win.device import Device
        device = Device(config=self.config)
    if self.config.Client_Platform == 'adb':
        from module.device.adb.device import Device
        device = Device(config=self.config)
    return device
```

### 2.2 Device 类（win）

`module/device/win/device.py` —— `Device` 继承 `AppControl` + `Automation`，构造函数最多重试 4 次拉起游戏：

```python
# module/device/win/device.py
class Device(AppControl, Automation):
    detect_record = set()                       # 尝试检测的 Button 集合
    click_record = deque(maxlen=15)             # 点击过的 Button 队列
    stuck_timer = Timer(360, count=60).start()
    stuck_timer_long = Timer(480, count=180).start()
    stuck_long_wait_list = ['LOGIN_CHECK', 'PAUSE']

    def __init__(self, *args, **kwargs):
        for trial in range(4):
            try:
                super().__init__(*args, **kwargs)
                break
            except GameNotRunningError:
                if trial >= 3:
                    logger.critical('Failed to start game after 3 trial')
                    raise RequestHumanTakeover
                self.current_window = self.game
                if not self.switch_to_program():
                    self.app_start()
                else:
                    break

    def screenshot(self):
        self.stuck_record_check()
        super().screenshot()
        self.image = self.current_window.image
        return self.image
```

---

## 3. 窗口对象与进程信息

### 3.1 进程/标题常量

`module/device/win/app_control.py` 顶部定义了不同客户端的窗口标题与进程名：

```python
# module/device/win/app_control.py
GAME_TITLE = {
    'intl': 'NIKKE',
    'hmt': '勝利女神：妮姬',
}
GAME_PROCESS = {
    'intl': 'nikke.exe',
    'hmt': 'nikke.exe',
}
LAUNCHER_TITLE = {
    'intl': 'NIKKE',
    'hmt': 'NIKKE',
}
LAUNCHER_PROCESS = {
    'intl': 'nikke_launcher.exe',
    'hmt': 'nikke_launcher_hmt.exe',
}
```

### 3.2 Window 数据类

`module/device/win/game_control.py` 统一窗口对象，含标题、类名、进程名、路径、句柄、分辨率、屏上偏移、截图：

```python
# module/device/win/game_control.py
@dataclass
class Window:
    """统一的窗口对象"""
    name: str
    title: str
    class_name: str
    process: str
    path: str
    hwnd: int = field(default=0)
    resolution: tuple = field(default=None)
    offset: tuple = field(default=(0, 0))
    image: ndarray = field(default=None)
    screenshot_scale_factor: float = field(default=1.0)
```

> 关键点：游戏窗口 `class_name='UnityWndClass'`、`title='NIKKE'`、`process='nikke.exe'`，此后所有查找都基于这三者。

### 3.3 AppControl 构造：建立 Window 并启动

`module/device/win/app_control.py:37` 读取配置 → 构建 `launcher` / `game` 两个 `Window` → 回填配置 → 调用 `app_start()`：

```python
# module/device/win/app_control.py (节选)
class AppControl(WinClient, Login):
    def __init__(self, config):
        if isinstance(config, str):
            self.config = NikkeConfig(config, task=None)
        else:
            self.config = config
        super().__init__(config)

        if not self.config.PCClientInfo_LauncherPath:
            logger.error('Launcher path must be specified')
            raise RequestHumanTakeover
        launcher_path = os.path.normpath(self.config.PCClientInfo_LauncherPath)
        self.check_path_format(launcher_path, 'Launcher')

        if self.config.PCClientInfo_AutoFillName:
            launcher_process = LAUNCHER_PROCESS[self.config.PCClientInfo_Client]
            launcher_window_title = LAUNCHER_TITLE[self.config.PCClientInfo_Client]
            game_process = GAME_PROCESS[self.config.PCClientInfo_Client]
            game_window_title = GAME_TITLE[self.config.PCClientInfo_Client]
        else:
            launcher_process = (self.config.PCClientInfo_LauncherProcessName or LAUNCHER_PROCESS[self.config.PCClientInfo_Client])
            launcher_window_title = (self.config.PCClientInfo_LauncherTitleName or LAUNCHER_TITLE[self.config.PCClientInfo_Client])
            game_process = self.config.PCClientInfo_GameProcessName or GAME_PROCESS[self.config.PCClientInfo_Client]
            game_window_title = self.config.PCClientInfo_GameTitleName or GAME_TITLE[self.config.PCClientInfo_Client]

        launcher_window_class = 'TWINCONTROL'
        game_window_class = 'UnityWndClass'

        self.launcher = Window(name='Launcher', title=launcher_window_title,
                               class_name=launcher_window_class, process=launcher_process, path=launcher_path)
        launcher_dir = os.path.dirname(launcher_path)
        game_path = os.path.normpath(self.config.PCClientInfo_GamePath or os.path.join(launcher_dir, '..', 'NIKKE', 'game', game_process))
        self.check_path_format(game_path, 'Game')

        self.game = Window(name='Game', title=game_window_title,
                           class_name=game_window_class, process=game_process, path=game_path)

        # 回填配置
        self.config.PCClientInfo_LauncherProcessName = launcher_process
        self.config.PCClientInfo_LauncherTitleName = launcher_window_title
        self.config.PCClientInfo_GameProcessName = game_process
        self.config.PCClientInfo_GameTitleName = game_window_title
        self.config.PCClientInfo_GamePath = self.game.path

        # 设置屏幕方向
        if self.config.PCClient_ScreenRotate:
            self.screen_rotate(self.config.PCClient_ScreenNumber, 1)
            time.sleep(3)

        self.language = self.config.Client_Language
        Langs.use(self.language)

        self.app_start()                      # ← 启动流程
        ...
```

### 3.4 路径校验

```python
# module/device/win/app_control.py
def check_path_format(self, path, name):
    if not re.match(r'^[A-Za-z0-9_:/\\.\- ()]+$', path):
        logger.error(f'Please install the game in an English path ...')
        raise RequestHumanTakeover
    if not path.endswith('.exe'):
        logger.error(f'{name} path must end with .exe: [{path}]')
        raise RequestHumanTakeover
    if not os.path.isfile(path):
        logger.error(f'{name} file does not exist ...')
        raise RequestHumanTakeover
```

---

## 4. 启动与查找游戏窗口：app_start

`module/device/win/app_control.py:163` —— 核心启动逻辑，最多重试 3 次。先 `switch_to_program()` 看游戏是否在跑；不在则启动启动器 → `login()` → 切到游戏 → 锁定 720×1280 分辨率：

```python
# module/device/win/app_control.py
def app_start(self):
    logger.info('Game starting')
    MAX_RETRY = 3

    def wait_until(condition, timeout, period=1):
        end_time = time.time() + timeout
        while time.time() < end_time:
            if condition():
                return True
            time.sleep(period)
        return False

    self.check_screen_resolution(self.config.PCClient_ScreenNumber, 720, 1280)
    self.launcher_running = False
    self.current_window = self.game
    if self.config.PCClient_CloseAutoHdr:
        self.change_auto_hdr('disable')
    else:
        self.change_auto_hdr('unset')

    for retry in range(MAX_RETRY):
        try:
            # 检查是否已进入游戏
            if self.switch_to_program():
                logger.info('Game is already running, verifying resolution')
                self.ensure_resolution(self.config.PCClient_ScreenNumber, 720, 1280, self.config.PCClient_GameWindowPosition)
                self.check_resolution(720, 1280)
                if self.config.PCClient_DisableVoice:
                    self.mute_window(True)
                break

            # 启动启动器
            self.current_window = self.launcher
            if not self.switch_to_program() and not self.start_program():
                logger.error('Launcher failed to start')
                raise RequestHumanTakeover
            if not wait_until(lambda: self.switch_to_program(), 30):
                logger.error('Timeout while switching to launcher')
                raise RequestHumanTakeover

            # 登录
            self.login()
            if not wait_until(lambda: self.switch_to_program(), 60):
                logger.error('Timeout while switching to game')
                raise RequestHumanTakeover
            # 设置游戏分辨率
            self.ensure_resolution(self.config.PCClient_ScreenNumber, 720, 1280, self.config.PCClient_GameWindowPosition)
            self.check_resolution(720, 1280)
            if self.config.PCClient_DisableVoice:
                self.mute_window(True)
            break
        except AccountError:
            raise AccountError
        except Exception as e:
            logger.error(f'Startup error: {e}, retrying {retry + 1}/{MAX_RETRY}')
            self.current_window = self.game
            self.stop_program()
            if not self.launcher_running:
                self.current_window = self.launcher
                self.stop_program()
            time.sleep(5)
            if retry == MAX_RETRY - 1:
                raise

    logger.info('Game started')
```

`app_is_running` 与 `app_stop`：

```python
# module/device/win/app_control.py
def app_is_running(self) -> bool:
    return self.switch_to_program()

def app_stop(self, program='Game'):
    try:
        self.current_window = self.launcher if program == 'Launcher' else self.game
        logger.info(f'{program} stop: {self.current_window.path}')
        if self.stop_program():
            logger.info(f'{program} stop success')
        else:
            logger.warning(f'{program} path config error')
            raise RequestHumanTakeover
    except Exception as e:
        logger.exception(e)
        raise RequestHumanTakeover
```

---

## 5. 窗口查找核心：switch_to_program

`module/device/win/game_control.py:238` —— **这是"找到游戏窗口"的关键函数**：

1. `win32gui.EnumWindows` 枚举所有顶层窗口，用 `class_name + title` 粗筛可见窗口；
2. 对每个候选，用 `win32process.GetWindowThreadProcessId` 取 PID → `psutil` 取进程路径，与配置路径**精确比对**（防止同名窗口误判）；
3. 命中后用 `set_foreground_window_with_retry` 置前台。

```python
# module/device/win/game_control.py
def switch_to_program(self) -> bool:
    """将程序窗口切换到前台，并精确匹配进程路径"""
    logger.info(f'Switching window to foreground: [{self.current_window.name}]:{self.current_window.title}')

    matched_hwnd = None
    try:
        def enum_windows_callback(hwnd, hwnd_list):
            try:
                title = win32gui.GetWindowText(hwnd)
                class_name = win32gui.GetClassName(hwnd)
                if not title or not win32gui.IsWindowVisible(hwnd):
                    return
                if class_name == self.current_window.class_name and title == self.current_window.title:
                    hwnd_list.append(hwnd)
            except Exception:
                pass

        hwnd_list = []
        win32gui.EnumWindows(enum_windows_callback, hwnd_list)
        if not hwnd_list:
            logger.warning('No matching window found by title/class.')
            return False
        logger.debug(f'Found {len(hwnd_list)} matching windows, checking process path...')

        # 按路径匹配窗口
        for hwnd in hwnd_list:
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process = psutil.Process(pid)
                exe_path = process.exe()
                logger.debug(f'Checking window HWND=[{hwnd}], PID=[{pid}], Path=[{exe_path}]')
                if hasattr(self.current_window, 'path') and self.current_window.path:
                    expected_path = self.current_window.path
                    if exe_path.lower() == expected_path.lower():
                        matched_hwnd = hwnd
                        logger.info(f'Path matched: [{exe_path}]')
                        break
                    else:
                        logger.debug(f'Path mismatch:\nExpected: [{expected_path}]\nActual:   [{exe_path}]')
            except Exception as e:
                logger.warning(f'Failed to check process path for window: {e}')
        if not matched_hwnd:
            logger.error(f'No window matched expected process path=[{self.current_window.path}]')
            return False

        self.set_foreground_window_with_retry(matched_hwnd)
        logger.info('Window switched to foreground successfully.')
        return True
    except Exception as e:
        logger.error(f'Error activating window: {e}')
        return False
```

### 5.1 前台置顶（绕过锁定的重试策略）

`module/device/win/game_control.py:188` —— 模拟按 Alt 键绕过前台锁，失败则最小化/恢复后重试 `SetForegroundWindow`：

```python
# module/device/win/game_control.py
@staticmethod
def set_foreground_window_with_retry(hwnd):
    hwnd_hex = hex(hwnd) if isinstance(hwnd, int) else hwnd
    logger.debug(f'Attempting to set window {hwnd_hex} to foreground.')

    def toggle_window_state(hwnd, minimize=False):
        SW_MINIMIZE = 6
        SW_RESTORE = 9
        state = SW_MINIMIZE if minimize else SW_RESTORE
        ctypes.windll.user32.ShowWindow(hwnd, state)

    def bypass_foreground_lock():
        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

    bypass_foreground_lock()
    time.sleep(0.5)
    toggle_window_state(hwnd, minimize=False)

    if ctypes.windll.user32.SetForegroundWindow(hwnd) == 0:
        logger.warning(f'Initial attempt to set window {hwnd_hex} to foreground [FAILED]. Retrying...')
        bypass_foreground_lock()
        time.sleep(0.5)
        toggle_window_state(hwnd, minimize=True)
        toggle_window_state(hwnd, minimize=False)
        if ctypes.windll.user32.SetForegroundWindow(hwnd) == 0:
            error_code = ctypes.GetLastError()
            logger.error(f'Retry [FAILED]: Error Code: {error_code}')
            raise Exception(f'Failed to set window foreground for hwnd: {hwnd_hex}')
        else:
            logger.info(f'Retry [SUCCESS]: Window {hwnd_hex} is now in the foreground.')
    else:
        logger.info(f'Initial attempt [SUCCESS]: Window {hwnd_hex} is now in the foreground.')
```

---

## 6. 进程判定与启停辅助

`module/device/win/game_control.py` 中的进程级辅助函数：

```python
# 启动程序（脱离桌面壳 Job Object，避免脚本退出时游戏被连带终止）
def start_program(self) -> bool:
    logger.info(f'Starting program: [{self.current_window.name}]:[{self.current_window.path}]')
    path = self.current_window.path
    if not os.path.exists(path):
        logger.error('Path does not exist')
        return False
    folder = path.rpartition('\\')[0]
    creationflags = subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(path, cwd=folder, creationflags=creationflags)
        logger.info('Program started successfully')
        return True
    except OSError as e:
        logger.warning(f'Failed to start program with breakaway: {e}')
    if not os.system(f'cmd /C start "" /D "{folder}" "{path}"'):
        logger.info('Program started successfully')
        return True
    else:
        logger.error('Error occurred while starting program')
        try:
            subprocess.Popen(path)
            return True
        except Exception as e:
            logger.error(f'Error occurred while starting program: {e}')
        return False

# 终止指定进程（仅限当前用户）
@staticmethod
def terminate_named_process(target_process, termination_timeout=10):
    system_username = os.getlogin()
    for process in psutil.process_iter(attrs=['pid', 'name']):
        if target_process in process.info['name']:
            process_username = process.username().split('\\')[-1]
            if system_username == process_username:
                proc_to_terminate = psutil.Process(process.info['pid'])
                proc_to_terminate.terminate()
                proc_to_terminate.wait(termination_timeout)

# 检查进程是否运行（仅限当前用户）
@staticmethod
def is_process_running(target_process: str) -> bool:
    try:
        system_username = os.getlogin()
    except Exception:
        import getpass
        system_username = getpass.getuser()
    for process in psutil.process_iter(attrs=['pid', 'name', 'username']):
        try:
            if target_process.lower() in (process.info['name'] or '').lower():
                process_username = process.info['username'].split('\\')[-1]
                if system_username == process_username:
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False
```

---

## 7. 截图获取画面

`module/device/win/screenshot.py` —— **执行侧"看"的入口**。先用标题找到窗口，计算客户区，再按方法捕获：

```python
# module/device/win/screenshot.py
class Screenshot:
    @staticmethod
    def get_window(title):
        windows = pyautogui.getWindowsWithTitle(title)
        if windows:
            return windows[0]
        return False

    @staticmethod
    def get_window_region(window):
        if Screenshot.is_application_fullscreen(window):
            return (window.left, window.top, window.width, window.height)
        else:
            real_width, real_height = Screenshot.get_window_real_resolution(window)
            other_border = (window.width - real_width) // 2
            up_border = window.height - real_height - other_border
            return (window.left + other_border, window.top + up_border,
                    window.width - other_border - other_border,
                    window.height - up_border - other_border)

    @staticmethod
    def take_screenshot(title, resolution, screens=False, crop=(0, 0, 1, 1), screenshot_method='pyautogui'):
        window = Screenshot.get_window(title)
        if window:
            left, top, width, height = Screenshot.get_window_region(window)
            capture_left = int(left + width * crop[0])
            capture_top = int(top + height * crop[1])
            capture_width = int(width * crop[2])
            capture_height = int(height * crop[3])
            if capture_width <= 0 or capture_height <= 0:
                return False

            method = str(screenshot_method or 'pyautogui')
            if method == 'pyautogui':
                image = Screenshot._capture_pyautogui(capture_left, capture_top, capture_width, capture_height, screens)
            elif method == 'mss':
                image = Screenshot._capture_mss(capture_left, capture_top, capture_width, capture_height)
            elif method == 'PrintWindow':
                image = Screenshot._capture_printwindow(window=window, capture_left=capture_left,
                                                        capture_top=capture_top, capture_width=capture_width,
                                                        capture_height=capture_height)
            else:
                raise ValueError(f'Unknown PC screenshot method: {method}')

            real_width, _ = Screenshot.get_window_real_resolution(window)
            screenshot_scale_factor = resolution[0] / real_width if real_width > resolution[0] else 1
            screenshot_pos = (capture_left, capture_top,
                              int(capture_width * screenshot_scale_factor),
                              int(capture_height * screenshot_scale_factor))
            if screenshot_scale_factor != 1:
                image = np.array(Image.fromarray(image).resize((screenshot_pos[2], screenshot_pos[3])))
            return image, screenshot_pos, screenshot_scale_factor
        return False
```

`Automation.screenshot`（`module/device/win/automation.py:115`）封装调用，并受 `_screenshot_interval` 节流：

```python
# module/device/win/automation.py
def screenshot(self, crop=(0, 0, 1, 1), retry=True):
    start_time = time.time()
    while True:
        self._screenshot_interval.wait()      # ← 真正的循环节奏节流（time.sleep）
        self._screenshot_interval.reset()
        try:
            result = Screenshot.take_screenshot(
                self.current_window.title, self.current_window.resolution,
                self.config.PCClient_Screens, crop=crop,
                screenshot_method=self.config.PCClientInfo_ScreenshotMethod)
            if result:
                image, pos, scale = result
                self.current_window.image = self._handle_orientated_image(image, self.current_window.resolution)
                self.current_window.offset = (pos[0], pos[1])
                self.current_window.screenshot_scale_factor = scale
                self.screenshot_deque.append({'time': datetime.now(), 'image': self.current_window.image})
                return result
            else:
                raise ScreenshotError(f'没有找到窗口 {self.current_window.name}:{self.current_window.title}')
        except Exception as e:
            logger.warning(f'截图失败：{e}')
            if not retry:
                raise ScreenshotError(str(e))
        if not retry:
            break
        time.sleep(1)
        if time.time() - start_time > 30:
            raise ScreenshotError('截图超时')
```

---

## 8. 点击执行（Input）

`module/device/win/input.py` —— **执行侧"动"的入口**，基于 `pyautogui` 与 `pynput`：

```python
# module/device/win/input.py
class Input:
    pyautogui.FAILSAFE = False

    def mouse_click(self, x, y):
        try:
            pyautogui.click(x, y)
            logger.debug(f'鼠标点击 ({x}, {y})')
        except Exception as e:
            logger.error(f'鼠标点击出错：{e}')

    def press_mouse_click(self, x, y, wait_time=0.2):
        """长按：Down → 睡 wait_time → Up"""
        try:
            pyautogui.mouseDown(x, y)
            time.sleep(wait_time)
            pyautogui.mouseUp()
        except Exception as e:
            logger.error(f'按下鼠标左键出错：{e}')

    def mouse_down(self, x, y):
        pyautogui.mouseDown(x, y)

    def mouse_up(self):
        pyautogui.mouseUp()

    def mouse_move(self, x, y):
        pyautogui.moveTo(x, y)

    def mouse_scroll(self, count, direction=-1, pause=True):
        for _ in range(count):
            pyautogui.scroll(direction, _pause=pause)

    def press_key(self, key, wait_time=0.2):
        pyautogui.keyDown(key); time.sleep(wait_time); pyautogui.keyUp(key)

    def press_mouse(self, wait_time=0.2):
        pyautogui.mouseDown(); time.sleep(wait_time); pyautogui.mouseUp()

    def mouse_swipe(self, p1, p2, speed=1.0):
        """pynput 贝塞尔曲线自然滑动"""
        distance = np.linalg.norm(np.array(p2) - np.array(p1))
        segments = int(distance / 20)
        total_time = max(0.05, min(distance / (100 * speed), 0.15))
        step_delay = total_time / segments
        self.mouse.position = (p1[0], p1[1])
        time.sleep(0.01)
        self.mouse.press(Button.left)
        for i in range(1, segments + 1):
            t = i / segments
            x = p1[0] + (p2[0] - p1[0]) * t
            y = p1[1] + (p2[1] - p1[1]) * t
            self.mouse.position = (x, y)
            time.sleep(step_delay)
        self.mouse.release(Button.left)
```

`Automation` 将 `Input` 方法绑定到实例（`module/device/win/automation.py:99`）：

```python
def _init_input(self):
    self.input_handler = Input()
    self.mouse_click = self.input_handler.mouse_click
    self.press_mouse_click = self.input_handler.press_mouse_click
    self.mouse_down = self.input_handler.mouse_down
    self.mouse_up = self.input_handler.mouse_up
    self.mouse_move = self.input_handler.mouse_move
    self.mouse_scroll = self.input_handler.mouse_scroll
    self.mouse_swipe = self.input_handler.mouse_swipe
    self.press_key = self.input_handler.press_key
    self.secretly_press_key = self.input_handler.secretly_press_key
    self.press_mouse = self.input_handler.press_mouse
```

`Device.click`（`module/device/win/automation.py:174`）—— 把 Button 中心坐标 + 窗口屏上偏移换算成绝对坐标后派发：

```python
def click(self, button: Button, click_offset=0, action='click'):
    x, y = button.location
    if isinstance(click_offset, (int, float)):
        x += click_offset; y += click_offset
    elif isinstance(click_offset, (tuple, list)) and len(click_offset) == 2:
        x += click_offset[0]; y += click_offset[1]
    x, y = ensure_int(x, y)
    logger.info('Click %s @ %s' % (point2str(x, y), button))
    x += self.current_window.offset[0]
    y += self.current_window.offset[1]
    action_map = {'click': self.mouse_click, 'down': self.mouse_down,
                  'move': self.mouse_move, 'hold': self.press_mouse}
    if action in action_map:
        action_map[action](x, y)
    else:
        raise ValueError(f'未知的动作类型: {action}')
```

---

## 9. 防卡死检测（简述）

`module/device/win/device.py` 在点击/识别时维护记录，超时则抛异常由 `main.py` 捕获重启：

```python
def handle_control_check(self, button: Button):
    self.stuck_record_clear()
    self.click_record_add(button)
    self.click_record_check()

def stuck_record_check(self):
    reached = self.stuck_timer.reached()
    reached_long = self.stuck_timer_long.reached()
    if not reached:
        return False
    if not reached_long:
        for button in self.stuck_long_wait_list:
            if button in self.detect_record:
                return False
    logger.warning('Wait too long')
    if self.app_is_running():
        raise GameStuckError('Wait too long')
    else:
        raise GameNotRunningError('Game died')

def click_record_check(self):
    count = {}
    for key in self.click_record:
        count[key] = count.get(key, 0) + 1
    count = sorted(count.items(), key=lambda item: item[1])
    if count[0][1] >= 12:
        raise GameTooManyClickError(f'Too many click for a button: {count[0][0]}')
    if len(count) >= 2 and count[0][1] >= 6 and count[1][1] >= 6:
        raise GameTooManyClickError(f'Too many click between 2 buttons: {count[0][0]}, {count[1][0]}')
```

---

## 附：关键文件索引

| 文件 | 职责 |
|---|---|
| `module/main.py` | 调度主循环、device 懒加载、异常捕获重启 |
| `module/device/win/device.py` | `Device` 类，整合启动/截图/点击，防卡死检测 |
| `module/device/win/app_control.py` | 构造 `Window`、路径校验、`app_start`/`app_stop` |
| `module/device/win/game_control.py` | `Window` 数据类、`switch_to_program`、`set_foreground_window_with_retry`、进程启停 |
| `module/device/win/screenshot.py` | `Screenshot.take_screenshot` 三种捕获方式 |
| `module/device/win/input.py` | `Input` 鼠标/键盘真实事件（pyautogui + pynput） |
| `module/device/win/automation.py` | `screenshot`/`click`/`swipe` 封装与输入绑定 |
| `module/base/base.py` | 平台分支选择 win/adb `Device` |
