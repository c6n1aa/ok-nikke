import datetime

from ok import BaseTask

_BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间 UTC+8，无夏令时


class MyBaseTask(BaseTask):
    # NIKKE 刷新规则：日常每天北京时间 04:00，周常每周二刷新。
    _day_reset_hour = 4        # 日常刷新时刻（北京时间，时）
    _week_reset_weekday = 1    # 周常刷新星期（周一=0，周二=1）
    _execution_states_key = "_execution_states"  # 下划线前缀为内部状态，不进 GUI 选项列表

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 注册到 default_config，否则 verify_config 重载时会丢弃非 default 键，状态无法跨重启保留。
        self.default_config[self._execution_states_key] = {}

    def _now_bj(self) -> datetime.datetime:
        """当前北京时间（带时区）。"""
        return datetime.datetime.now(_BEIJING_TZ)

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