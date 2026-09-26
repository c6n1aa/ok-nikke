from __future__ import annotations

import sys
import threading
import traceback

from ok import Logger, og
from PySide6.QtCore import QObject

from src import event_calendar

logger = Logger.get_logger(__name__)

REFRESH_TTL_SECONDS = 600  # 距上次成功拉取不足该秒数则跳过（频繁重启不重复请求）。
EXPIRE_TITLE = 'ok-nikke'  # InfoBar 提示标题。
EXPIRE_NOTIFY_DELAY_MS = 2000  # 启动补发提示的延迟：让主窗口先稳定显示，避免盖在加载/置顶动画上。


def _is_test_runner():
    """测试运行器（TaskTestCase/init_ok）会加载 ok.test；此时不起后台刷新，避免测试触网。"""
    return 'ok.test' in sys.modules


def expire_message(expiring):
    """即将结束活动的提示文案（单数/复数两种形态）。"""
    names = '、'.join(event.display_name for event in expiring)
    if len(expiring) > 1:
        return f'以下活动即将结束（24小时内）：{names}'
    return f'活动「{names}」即将结束（24小时内）'


class ExpiringEventNotifier(QObject):
    """活动日历刷新成功后，把「结束时间在 24 小时内的活动」弹成 Qt InfoBar 提示。

    刷新线程不直接碰 Qt 控件：通过 communicate.notification 与 UI 通信，框架内部会把
    回调投递到 Qt 主线程（ok.ui.qt.events.QtEventDispatcher）。主窗口尚不存在（刷新先
    完成）时暂存 pending 消息，主窗口挂载时由框架回调 on_show_main_window 补发，保证
    启动早期完成刷新时提示不丢。
    """

    def __init__(self, exit_event=None):
        super().__init__()
        self._exit_event = exit_event or threading.Event()  # 判空退出状态用。
        self._pending = None  # 待窗口挂载后发出的 message。

    def notify_expiring(self, events, now=None):
        """筛选并提示即将结束的活动；开关关闭/没有命中/应用已退出则什么都不做。"""
        if not expire_notify_enabled():
            return
        expiring = event_calendar.expiring_events(events, now=now)
        if not expiring:
            return
        if self._exit_event.is_set():
            return
        self._emit_info(expire_message(expiring))

    def _emit_info(self, message):
        """发 InfoBar 提示：窗口已就绪直接发，否则暂存等 on_show_main_window 补发。"""
        from ok.ui.qt.Communicate import communicate  # 延迟导入：无窗口环境不依赖 Qt UI。

        main_window = getattr(og, 'main_window', None)  # 主窗口在 show_main_window 后挂到 og。
        if main_window is not None:
            self._pending = None
            communicate.notification.emit(message, EXPIRE_TITLE, False, False, None, None, None)
            return
        if self._pending is None:
            logger.debug('主窗口未就绪，暂存即将结束活动提示')
        self._pending = message

    def on_show_main_window(self, main_window):
        """主窗口挂载钩子（框架在 show_main_window 里调用）：pending 提示延迟后补发。

        延后 EXPIRE_NOTIFY_DELAY_MS 再发，避免提示盖在窗口刚显示的置顶/加载动画上；
        通过 og.handler（全局 Handler）投递到 Qt 主线程，延迟期间应用退出则丢弃。
        """
        pending, self._pending = self._pending, None
        if pending is None or self._exit_event.is_set():
            return
        if getattr(og, 'handler', None) is None:
            self._emit_info(pending)  # 无 handler（headless/测试）退化为立即补发。
            return
        og.handler.post(lambda: self._emit_info(pending), delay=EXPIRE_NOTIFY_DELAY_MS / 1000.0)


def _refresh_event_calendar(exit_event, notifier=None):
    """后台刷新活动日历（状态 + 活动图）；刷新成功后提示即将结束的活动，失败只记日志。"""
    try:
        snapshot = event_calendar.load_snapshot()
        if snapshot is not None and snapshot.is_fresh(REFRESH_TTL_SECONDS):
            return
        if exit_event is not None and exit_event.is_set():  # 应用已在退出，不再发起请求。
            return
        snapshot = event_calendar.refresh()
        if snapshot.fetched_at:
            logger.info(f'活动日历刷新完成：{len(snapshot.events)} 个剧情活动')
            notifier = notifier or _default_notifier()
            if notifier is not None:
                notifier.notify_expiring(snapshot.events)
        else:
            logger.info('活动日历刷新失败（接口不可达），使用保底图/缓存')
    except Exception:  # noqa: BLE001 - 静默刷新，异常不影响启动。
        # ok 的 Logger 只收一个 message（没有 stdlib logging 的 exc_info 参数），堆栈自己拼进消息。
        logger.debug(f'event calendar refresh failed: {traceback.format_exc()}')


def _default_notifier():
    """取全局单例（og.my_app）上的 notifier；Globals 未就绪（如 headless）时返回 None。"""
    try:
        return getattr(getattr(og, 'my_app', None), 'notifier', None)
    except Exception:  # noqa: BLE001 - og 状态不确定时不提示，不影响启动。
        return None


def expire_notify_enabled():
    """「活动结束提醒」开关是否开启（通知配置卡片里的自定义项；取不到配置按开启处理，保证旧配置升级后行为不变）。"""
    try:
        from ok.util.GlobalConfig import NOTIFICATION_OPTION_NAME

        from src.patches.notification_tab import EXPIRE_NOTIFY_ENABLED_KEY
        return bool(og.global_config.get_config(NOTIFICATION_OPTION_NAME).get(EXPIRE_NOTIFY_ENABLED_KEY, True))
    except Exception:  # noqa: BLE001 - og/配置未就绪（headless、测试、早期启动）时不阻断，按开启走。
        return True


def _start_event_refresh(exit_event):
    """启动后台刷新线程（debug 启动同样生效）；测试运行器下不启动。"""
    if _is_test_runner():
        return
    # 线程释放策略：daemon=True 不阻塞进程退出；refresh() 的请求都有超时上限；
    # 落盘用 .tmp + os.replace，中途被杀不会留下半截文件；线程不持有 Qt 对象
    # （提示消息走 communicate.notification 事件总线，跨线程由框架投递到 Qt 主线程）。
    threading.Thread(target=_refresh_event_calendar, args=(exit_event, None),
                     daemon=True, name='ok-nikke-event-refresh').start()


class Globals(QObject):

    def __init__(self, exit_event):
        super().__init__()
        self.notifier = ExpiringEventNotifier(exit_event)
        # 后台刷新线程完成后经 notifier 提示；若刷新先于主窗口完成，
        # 框架会回调 og.my_app.on_show_main_window（即本类）补发 pending 提示。
        _start_event_refresh(exit_event)

    def on_show_main_window(self, main_window):
        """框架 show_main_window 钩的是 og.my_app（Globals）本身，转给 notifier 补发 pending 提示。"""
        self.notifier.on_show_main_window(main_window)
