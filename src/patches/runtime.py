import os

from ok import Logger

logger = Logger.get_logger(__name__)

# 运行时行为补丁：禁用 OpenVINO 遥测 + 一次性任务运行期间游戏窗口失焦自动暂停、回前台自动恢复。


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


class _FocusGuard:
    """游戏窗口焦点守卫：一次性任务运行期间，窗口失焦则暂停执行器，回前台自动恢复。

    注册为 HwndWindow.visible_monitors 成员后，随窗口前后台状态（0.2s 轮询）回调 on_visible，
    在 HwndWindow 自身的后台线程里执行。仅作用于一次性任务；后台轮询型 TriggerTask 不抢前台也不暂停。
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
            if task is None or isinstance(task, TriggerTask):
                # 无一次性任务在跑，或当前是后台触发任务，不干预并复位状态，避免污染下一次任务。
                self._paused_task = None
                self._was_paused = False
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


def _patch_executor_ocr_init_join():
    # 包装 TaskExecutor.destroy：退出前等待后台 DefaultOCRInit 线程收尾。
    # 该守护线程懒初始化 OCR（导入 openvino + 加载模型）。当进程在初始化完成前就
    # 退出（典型：跑得快的测试文件，如 RaidTask 全部用例 <1s），解释器终结阶段会
    # 冻结这个仍持有 import 锁的线程，导致进程在退出阶段永久死锁——测试全部通过、
    # CPU 归零、进程永不结束。先 join 把竞态窗口关掉；正常初始化约 1 秒内完成。
    from ok.task.TaskExecutor import TaskExecutor

    original_destroy = TaskExecutor.destroy

    def destroy_with_ocr_join(self):
        original_destroy(self)
        thread = getattr(self, "_ocr_init_thread", None)
        if thread is not None and thread.is_alive():
            logger.info("waiting for DefaultOCRInit thread before shutdown")
            thread.join(timeout=30)
            if thread.is_alive():
                logger.warning("DefaultOCRInit still running after 30s; interpreter shutdown may hang")

    TaskExecutor.destroy = destroy_with_ocr_join
    logger.info("patched TaskExecutor.destroy to join DefaultOCRInit thread")


def _patch_real_ocr_guard():
    """测试/CI 下禁用真实 OCR 推理（OK_NIKKE_NO_REAL_OCR=1）。

    部分 Windows runner 的 CPU 会让 onnxocr + OpenVINO 执行到非法指令（0xC000001D
    STATUS_ILLEGAL_INSTRUCTION），整个测试进程被直接带走：日志里没有 traceback、没有断言
    失败、没有 unittest 汇总，只剩一个十六进制退出码（已踩过两次，排查成本极高）。
    这里把推理入口换成显式异常，让漏网的真实 OCR 调用变成可定位的失败；真实 OCR 回归
    统一放 dev_tools/check_real_ocr.py（本地/发版前手动跑）。
    """
    if os.environ.get('OK_NIKKE_NO_REAL_OCR') != '1':
        return
    from ok.task.task import BaseTask

    def blocked_ocr(self, *args, **kwargs):
        raise RuntimeError('真实 OCR 在测试中被禁用（OK_NIKKE_NO_REAL_OCR=1）：'
                           '用例需 patch.object(task, "ocr") 打桩；真实 OCR 见 dev_tools/check_real_ocr.py')

    BaseTask.ocr = blocked_ocr
    logger.info('real OCR disabled in tests (OK_NIKKE_NO_REAL_OCR=1)')


def apply():
    # 测试期禁用真实 OCR（仅当 OK_NIKKE_NO_REAL_OCR=1）
    _patch_real_ocr_guard()
    # 禁用 OpenVINO 遥测，避免无网络时挂死进程退出
    _patch_openvino_telemetry()
    # 一次性任务运行期间，游戏窗口失焦则暂停执行器，回到前台自动恢复
    _patch_executor_focus_guard()
    # 退出前等待 OCR 初始化线程收尾，避免解释器终结阶段的 import 锁死锁
    _patch_executor_ocr_init_join()
