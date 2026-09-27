"""游戏官方时间口径：官方时区与每日刷新时刻（纯 stdlib，供活动日历与任务完成状态共用）。

官方日历接口（GetCalendarDetail）的时间戳以官方时区 UTC+9 为基准，接口本身不返回时区字段，
所以时区在这里作为唯一常量维护；每日刷新按官方时区的 05:00 划分（= 北京时间 04:00）。
"""

from __future__ import annotations

import datetime  # 官方时区与每日刷新时刻的换算。
import time  # now 参数缺省时取真实时间。

GAME_TZ = datetime.timezone(datetime.timedelta(hours=9))  # 官方时区 UTC+9，无夏令时。
DAY_RESET_HOUR = 5  # 每日刷新时刻（官方时区，时）：UTC+9 05:00 = 北京时间 04:00。


def day_reset_time(now=None):
    """最近一次每日刷新时刻（官方时区 DAY_RESET_HOUR:00）的 unix 秒；now 供测试注入，缺省取真实时间。"""
    moment = datetime.datetime.fromtimestamp(time.time() if now is None else now, GAME_TZ)
    reset = moment.replace(hour=DAY_RESET_HOUR, minute=0, second=0, microsecond=0)
    if moment < reset:  # 官方时区 00:00-05:00 仍属于前一天的周期。
        reset -= datetime.timedelta(days=1)
    return int(reset.timestamp())
