from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject
from ok import Logger, og

from src import event_calendar

logger = Logger.get_logger(__name__)

REFRESH_TTL_SECONDS = 600  # 距上次成功拉取不足该秒数则跳过（频繁重启不重复请求）。


def _is_test_runner():
    """测试运行器（TaskTestCase/init_ok）会加载 ok.test；此时不起后台刷新，避免测试触网。"""
    return 'ok.test' in sys.modules


def _refresh_event_calendar(exit_event):
    """后台刷新活动日历（状态 + 活动图）；失败只记日志。"""
    try:
        snapshot = event_calendar.load_snapshot()
        if snapshot is not None and snapshot.is_fresh(REFRESH_TTL_SECONDS):
            return
        if exit_event is not None and exit_event.is_set():  # 应用已在退出，不再发起请求。
            return
        snapshot = event_calendar.refresh()
        if snapshot.fetched_at:
            logger.info(f'活动日历刷新完成：{len(snapshot.events)} 个剧情活动')
        else:
            logger.info('活动日历刷新失败（接口不可达），使用保底图/缓存')
    except Exception:  # noqa: BLE001 - 静默刷新，异常不影响启动。
        logger.debug('event calendar refresh failed', exc_info=True)


def _start_event_refresh(exit_event):
    """启动后台刷新线程（debug 启动同样生效）；测试运行器下不启动。"""
    if _is_test_runner():
        return
    # 线程释放策略：daemon=True 不阻塞进程退出；refresh() 的请求都有超时上限；
    # 落盘用 .tmp + os.replace，中途被杀不会留下半截文件；线程不持有 Qt 对象。
    threading.Thread(target=_refresh_event_calendar, args=(exit_event,),
                     daemon=True, name='ok-nikke-event-refresh').start()


class Globals(QObject):

    def __init__(self, exit_event):
        super().__init__()
        _start_event_refresh(exit_event)
