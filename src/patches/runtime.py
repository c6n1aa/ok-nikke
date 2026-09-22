from ok import Logger

logger = Logger.get_logger(__name__)

# 运行时行为补丁：禁用 OpenVINO 遥测 + 一次性任务运行期间游戏窗口失焦自动暂停（仅前台交互方式）、回前台自动恢复。


def _patch_openvino_telemetry():
    # 禁用 OpenVINO 遥测上报，避免无网络时阻塞进程退出。
    # backend_ga4 在 Windows 上直接用 urlopen()（无超时）在非 daemon 线程池里发请求，
    # 断网时 socket 永久挂起，解释器退出时 join 该线程导致进程无法结束。
    # backend_ga 同样用无超时的 urlopen。这里把两个后端的实际发送替换为直接返回。
    try:
        from openvino_telemetry.backend import backend_ga4, backend_ga
    except ImportError:  # 当前 OCR 后端是 onnxruntime，未装 openvino 时跳过
        return

    try:
        def _noop_send(request_data):
            pass

        backend_ga4._send_func = _noop_send

        def _ga_send_noop(self, message):
            pass

        backend_ga.GABackend.send = _ga_send_noop
        logger.info('openvino telemetry disabled to avoid network hang on exit')
    except Exception as e:
        logger.warning(f'disable openvino telemetry failed: {e}')


class _FocusGuard:
    """游戏窗口焦点守卫：一次性任务运行期间，窗口失焦则暂停执行器，回前台自动恢复。

    注册为 HwndWindow.visible_monitors 成员后，随窗口前后台状态（0.2s 轮询）回调 on_visible，
    在 HwndWindow 自身的后台线程里执行。仅作用于一次性任务；后台轮询型 TriggerTask 不抢前台也不暂停。
    且仅当前交互方式依赖窗口前台（Pynput/PyDirect/ForegroundPostMessage）时才暂停：PostMessage/Genshin
    走窗口消息、后台也能点击，暂停会抵消其后台运行能力。
    使用全局暂停（executor.pause/start），与用户手动全局暂停共用一个状态位，故用 _was_paused
    记录暂停前状态，恢复时只解除“由失焦引起”的那次暂停，不覆盖用户手动暂停。
    """

    def __init__(self):
        self._paused_task = None  # 当前被失焦暂停的任务对象；None 表示无失焦暂停。
        self._was_paused = False  # 暂停前执行器是否已暂停（用于避免覆盖用户手动全局暂停）。

    def on_visible(self, visible):
        try:
            from ok import og
            from ok.task.task import TriggerTask
            executor = og.executor
            task = executor.current_task
            if task is None or isinstance(task, TriggerTask) or not interaction_requires_foreground():
                # 无一次性任务在跑、当前是后台触发任务、或交互方式可后台点击（PostMessage/Genshin）：
                # 不干预并复位状态，避免污染下一次任务；若暂停仍由失焦引起且任务未变
                # （运行中把交互方式切成了可后台点击），就地解除，否则任务会一直停住。
                self.release(task)
                return
            if not visible:
                # 失焦：仅当该任务尚未被失焦暂停时暂停一次。
                if self._paused_task is not task:
                    self._was_paused = executor.paused
                    self._paused_task = task
                    if not self._was_paused:
                        executor.pause()
                    logger.info(f'游戏窗口失去焦点，任务已暂停: {getattr(task, "name", task)}')
                    from ok.ui.qt.Communicate import communicate
                    communicate.notification.emit('游戏窗口失去焦点，任务已暂停，切回游戏窗口后自动继续。',
                                                  None, False, True, None, None, None)
            else:
                # 恢复前台：仅当暂停由失焦引起、且暂停前未手动暂停时才恢复。
                if self._paused_task is task:
                    self._paused_task = None
                    if not self._was_paused:
                        executor.reset_scene(check_enabled=False)  # 丢弃暂停前的旧帧，避免基于旧画面误判。
                        executor.start()
                    logger.info('游戏窗口回到前台，任务恢复执行。')
        except Exception as e:
            logger.warning(f'focus guard on_visible failed: {e}')

    def release(self, task):
        """解除由失焦引起的暂停并复位状态；用户手动暂停、或任务已换时不解除执行器暂停。"""
        paused_task, was_paused = self._paused_task, self._was_paused
        self._paused_task = None
        self._was_paused = False
        if paused_task is None or was_paused or paused_task is not task:
            return
        try:
            from ok import og
            executor = og.executor
            if not executor.paused:
                return
            executor.reset_scene(check_enabled=False)  # 丢弃暂停期间的旧帧，避免基于旧画面误判。
            executor.start()
            logger.info('失焦暂停已解除，任务继续执行。')
        except Exception as e:
            logger.warning(f'focus guard release failed: {e}')


_FOCUS_GUARD = _FocusGuard()  # 全局单例守卫。
_FOCUS_GUARD_REGISTERED = False  # 是否已注册到 hwnd_window.visible_monitors。


def _ensure_focus_guard_registered():
    # 惰性把焦点守卫注册到 hwnd_window.visible_monitors。补丁在 ok.OK() 构造前应用，og 尚未就绪，
    # 只能在任务首次取帧时（og 已就绪）注册，之后随窗口前后台变化触发暂停/恢复。
    global _FOCUS_GUARD_REGISTERED
    if _FOCUS_GUARD_REGISTERED:
        return
    try:
        from ok import og
        hwnd_window = getattr(og.executor.device_manager, 'hwnd_window', None)
        if hwnd_window is None:
            return
        monitors = getattr(hwnd_window, 'visible_monitors', None)
        if monitors is None or _FOCUS_GUARD in monitors:
            return
        monitors.append(_FOCUS_GUARD)
        _FOCUS_GUARD_REGISTERED = True
        logger.info('focus guard registered to hwnd_window.visible_monitors')
    except Exception as e:
        logger.warning(f'register focus guard failed: {e}')


def _patch_executor_focus_guard():
    # 包装 TaskExecutor.next_frame：一次性任务取帧时确保焦点守卫已注册，
    # 由守卫在窗口失焦时暂停执行器、回前台时恢复，取代原先的“自动抢前台”。
    from ok.task.TaskExecutor import TaskExecutor
    from ok.task.task import TriggerTask

    original_next_frame = TaskExecutor.next_frame

    def next_frame(self, time_out=6):
        try:
            if self.current_task is not None and not isinstance(self.current_task, TriggerTask):
                _ensure_focus_guard_registered()
        except Exception:
            pass
        return original_next_frame(self, time_out=time_out)

    TaskExecutor.next_frame = next_frame
    logger.info('patched TaskExecutor.next_frame to pause on game window unfocus')


def interaction_requires_foreground(interaction=None):
    """交互方式是否依赖游戏窗口在前台；不传则取当前生效的交互实例。

    Pynput/PyDirect/ForegroundPostMessage 的 clickable() 要求 is_foreground()，窗口在后台时
    会静默跳过点击，靠失焦暂停与窗口置前兜住；PostMessage/Genshin 走窗口消息、后台也能点击，
    暂停或抢占前台反而让后台运行失效。取不到交互方式或类型未知时按依赖前台处理。
    ForegroundPostMessage 是 Genshin 的子类，必须先判前台集合。
    焦点守卫用它决定是否失焦暂停，任务基类与启动控制器用它决定是否把游戏窗口置前。
    """
    try:
        if interaction is None:
            from ok import og
            interaction = getattr(og.device_manager, 'interaction', None)
            if interaction is None:  # 交互实例由 do_start 异步创建，未就绪时回退到已选的交互类型。
                interaction = getattr(og.device_manager, 'win_interaction_class', None)
        if interaction is None:
            return True
        interaction_type = interaction if isinstance(interaction, type) else type(interaction)
        from src.win_input import SyntheticTouch  # 延迟导入，按当前交互方式判断是否依赖前台。
        if issubclass(interaction_type, SyntheticTouch):
            return True  # 合成触控命中认 Z 序，点击前把游戏窗口置前，需要窗口位于前台。
        from ok.device.interaction_methods import (ForegroundPostMessageInteraction, GenshinInteraction,
                                                   PostMessageInteraction, PyDirectInteraction, PynputInteraction)
        if issubclass(interaction_type, (PynputInteraction, PyDirectInteraction, ForegroundPostMessageInteraction)):
            return True  # 窗口在后台时点击被静默跳过。
        if issubclass(interaction_type, (PostMessageInteraction, GenshinInteraction)):
            return False  # 可后台点击，不需要失焦暂停。
        return True  # 未知交互方式按依赖前台处理。
    except Exception as e:
        logger.warning(f'resolve interaction mode failed: {e}')
        return True


def _patch_device_set_interaction():
    # 包装 DeviceManager.set_interaction：运行中切换交互方式（如 Pynput → PostMessage）时按新方式
    # 重判失焦暂停。切到可后台点击的方式时必须顺手解除已有暂停：暂停态下框架不再取帧，也不会再有
    # on_visible 回调来唤醒，任务会一直停住；反之切到前台方式时窗口仍在后台，不能解除（点击会失效）。
    # 用 win_interaction_class 判新方式：它在 set_interaction 内同步更新，交互实例由 do_start 异步重建。
    from ok.device.DeviceManager import DeviceManager

    original_set_interaction = DeviceManager.set_interaction

    def set_interaction(self, interaction):
        result = original_set_interaction(self, interaction)
        try:
            if not interaction_requires_foreground(getattr(self, 'win_interaction_class', None)):
                from ok import og
                executor = getattr(og, 'executor', None)
                if executor is not None:
                    _FOCUS_GUARD.release(executor.current_task)
        except Exception as e:
            logger.warning(f'release focus pause after interaction change failed: {e}')
        return result

    DeviceManager.set_interaction = set_interaction
    logger.info('patched DeviceManager.set_interaction to release focus pause on interaction change')


_OCR_INIT_JOIN_TIMEOUT = 120  # 秒；CI 冷缓存下加载/编译 OCR 推理模型可能耗时数十秒


def _join_ocr_init_thread(executor=None):
    # 等后台 DefaultOCRInit 线程收尾。框架起了这个守护线程（懒初始化 OCR、import 推理后端）
    # 却从不 join；进程退出得比它快时，主线程会在解释器终结阶段卡在全局 import 锁上
    # （_imp.acquire_lock），锁被该线程占着，进程永不退出。
    if executor is None:
        from ok import og
        executor = getattr(og, 'executor', None)
    if executor is None:
        return
    thread = getattr(executor, "_ocr_init_thread", None)
    if thread is None or not thread.is_alive():
        return
    logger.info("waiting for DefaultOCRInit thread before shutdown")
    thread.join(_OCR_INIT_JOIN_TIMEOUT)
    if thread.is_alive():
        logger.warning(f"DefaultOCRInit still running after {_OCR_INIT_JOIN_TIMEOUT}s; "
                       "interpreter shutdown may hang on the import lock")


def _patch_executor_ocr_init_join():
    # 包装 TaskExecutor.destroy：执行器收尾时先等 OCR 初始化线程。
    from ok.task.TaskExecutor import TaskExecutor

    original_destroy = TaskExecutor.destroy

    def destroy_with_ocr_join(self):
        original_destroy(self)
        _join_ocr_init_thread(self)

    TaskExecutor.destroy = destroy_with_ocr_join
    logger.info("patched TaskExecutor.destroy to join DefaultOCRInit thread")


def _patch_shutdown_ocr_init_join():
    # 只挂 destroy 不够：它跑在 TaskExecutor 线程上，主线程不等它。必须在主线程的退出阶段等，
    # 这些回调都早于解释器开始 module 清理（即那次抢 import 锁的 import）。
    import atexit
    import threading

    atexit.register(_join_ocr_init_thread)
    if hasattr(threading, "_register_atexit"):  # 更早，随 threading._shutdown 执行
        threading._register_atexit(_join_ocr_init_thread)
    logger.info("patched process shutdown to join DefaultOCRInit thread")


def apply():
    # 禁用 OpenVINO 遥测，避免无网络时挂死进程退出
    _patch_openvino_telemetry()
    # 一次性任务运行期间，游戏窗口失焦则暂停执行器（仅前台交互方式），回到前台自动恢复
    _patch_executor_focus_guard()
    # 运行中切换交互方式时按新方式重判失焦暂停，必要时解除已有暂停
    _patch_device_set_interaction()
    # 执行器收尾与进程退出阶段都要等 OCR 初始化线程，避免解释器终结阶段的 import 锁死锁
    _patch_executor_ocr_init_join()
    _patch_shutdown_ocr_init_join()
