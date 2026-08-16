import time

from ok import Logger

logger = Logger.get_logger(__name__)

# 后台触发任务轮询间隔、OpenVINO 遥测等运行时行为补丁。

_FOREGROUND_LAST_ATTEMPT = 0.0  # 上次尝试把游戏窗口置前的时间戳（节流用）
_FOREGROUND_INTERVAL = 1.0  # 两次置前尝试的最小间隔（秒），避免高频系统调用


def _patch_openvino_telemetry():
    # 禁用 OpenVINO 遥测上报，避免无网络时阻塞进程退出。
    # backend_ga4 在 Windows 上直接用 urlopen()（无超时）在非 daemon 线程池里发请求，
    # 断网时 socket 永久挂起，解释器退出时 join 该线程导致进程无法结束。
    # backend_ga 同样用无超时的 urlopen。这里把两个后端的实际发送替换为直接返回。
    try:
        from openvino_telemetry.backend import backend_ga4, backend_ga

        def _noop_send(request_data):
            pass

        backend_ga4._send_func = _noop_send

        def _ga_send_noop(self, message):
            pass

        backend_ga.GABackend.send = _ga_send_noop
        logger.info('openvino telemetry disabled to avoid network hang on exit')
    except Exception as e:
        logger.warning(f'disable openvino telemetry failed: {e}')


def _ensure_game_foreground():
    # 游戏窗口不在前台时强制切到前台，保证 pynput 交互与捕获可用。
    # 节流：1 秒内只尝试一次，避免任务运行中每帧都触发系统调用。
    global _FOREGROUND_LAST_ATTEMPT
    now = time.monotonic()
    if now - _FOREGROUND_LAST_ATTEMPT < _FOREGROUND_INTERVAL:
        return
    _FOREGROUND_LAST_ATTEMPT = now
    try:
        from ok import og
        hwnd_obj = getattr(og.executor.device_manager, 'hwnd_window', None)
        hwnd = getattr(hwnd_obj, 'hwnd', 0)
        if not hwnd:
            return
        import win32api
        import win32con
        import win32gui
        import win32process
        if win32gui.GetForegroundWindow() == hwnd:
            return
        game_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
        cur_thread = win32api.GetCurrentThreadId()
        attached = False
        if game_thread != cur_thread:
            try:
                win32process.AttachThreadInput(cur_thread, game_thread, True)
                attached = True
            except Exception:
                attached = False
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            logger.warning(f'ensure game foreground error: {e}')
        finally:
            if attached:
                try:
                    win32process.AttachThreadInput(cur_thread, game_thread, False)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f'ensure game foreground failed: {e}')


def _patch_executor_foreground():
    # 包装 TaskExecutor.next_frame：一次性任务在取帧/等待场景时先确保游戏窗口在前台。
    # 窗口后台时 ok 的 can_capture 返回 False（pynput 依赖前台），导致 executor 在
    # 任务启动前（execute 的 next_frame）和任务运行中都拿不到帧而卡住/超时。
    # 后台轮询型 TriggerTask 不抢前台，避免干扰用户做其他事。
    from ok.task.TaskExecutor import TaskExecutor
    from ok.task.task import TriggerTask

    original_next_frame = TaskExecutor.next_frame

    def next_frame(self, time_out=6):
        try:
            if self.current_task is not None and not isinstance(self.current_task, TriggerTask):
                _ensure_game_foreground()
        except Exception:
            pass
        return original_next_frame(self, time_out=time_out)

    TaskExecutor.next_frame = next_frame
    logger.info('patched TaskExecutor.next_frame to keep game window in foreground')


def apply():
    # 禁用 OpenVINO 遥测，避免无网络时挂死进程退出
    _patch_openvino_telemetry()
    # 一次性任务执行期间把游戏窗口保持在前台，避免后台时 pynput 捕获/点击失效
    _patch_executor_foreground()