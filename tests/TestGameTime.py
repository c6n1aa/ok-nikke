"""官方时间口径：UTC+9 与每日 05:00 刷新，活动日历新鲜期与任务完成状态共用（不触网）。"""
import datetime
import os
import unittest
from unittest.mock import patch

from ok.test.TaskTestCase import TaskTestCase

from src import game_time
from src.config import config
from src.tasks.HarvestTask import HarvestTask

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')  # 临时任务配置目录（已 gitignore）。


class TestDayResetTime(unittest.TestCase):
    """官方时区与每日刷新时刻的换算（纯函数）。"""

    _BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 仅用于核对换算，不参与实现。

    @staticmethod
    def _game(day, hour, minute=0):
        """2026-09 某日官方时区（UTC+9）时刻的 unix 秒（只关心日/时/分）。"""
        return int(datetime.datetime(2026, 9, day, hour, minute, tzinfo=game_time.GAME_TZ).timestamp())

    def test_official_timezone_and_reset_hour(self):
        self.assertEqual(datetime.timedelta(hours=9), game_time.GAME_TZ.utcoffset(None))  # 官方时区 UTC+9。
        self.assertEqual(5, game_time.DAY_RESET_HOUR)

    def test_reset_time_is_today_5am_after_reset(self):
        self.assertEqual(self._game(27, 5), game_time.day_reset_time(self._game(27, 5)))  # 正好 05:00 归当天周期。
        self.assertEqual(self._game(27, 5), game_time.day_reset_time(self._game(27, 23, 59)))

    def test_reset_time_is_previous_5am_before_reset(self):
        self.assertEqual(self._game(26, 5), game_time.day_reset_time(self._game(27, 4, 59)))  # 05:00 前仍属前一天周期。

    def test_reset_hour_is_4am_beijing(self):
        beijing_4am = int(datetime.datetime(2026, 9, 27, 4, 0, tzinfo=self._BEIJING_TZ).timestamp())
        self.assertEqual(beijing_4am, self._game(27, 5))  # 官方时区 05:00 与北京时间 04:00 是同一时刻。
        self.assertEqual(beijing_4am, game_time.day_reset_time(beijing_4am))


class TestDoneStateBoundary(TaskTestCase):
    """完成状态的周期边界：与活动日历同一口径，按官方时区 05:00 划天、周二 05:00 划周。"""

    task_class = HarvestTask
    task: HarvestTask

    config = config

    def setUp(self):
        os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)
        self.task.config.config_file = os.path.join(_TEST_CONFIG_DIR, 'HarvestTask.json')  # 不写真实 configs/。
        self.task.config.reset_to_default()
        self.task.config['_execution_states'] = {}
        patcher = patch.object(self.task, '_in_debug', return_value=False)  # 测试环境强制 debug=True，这里屏蔽。
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _at(day, hour, minute=0):
        """2026-09 某日官方时区的时刻。"""
        return datetime.datetime(2026, 9, day, hour, minute, tzinfo=game_time.GAME_TZ)

    def test_day_period_rolls_over_at_5am_official(self):
        with patch.object(type(self.task), '_now_game', return_value=self._at(27, 4, 59)):
            self.task.mark_done('probe', 'day')
            self.assertTrue(self.task.is_done('probe', 'day'))  # 同一周期内。
        with patch.object(type(self.task), '_now_game', return_value=self._at(27, 5, 0)):
            self.assertFalse(self.task.is_done('probe', 'day'))  # 跨过 05:00 刷新即新周期。

    def test_legacy_beijing_offset_record_matches_by_instant(self):
        # 旧记录带 +08:00 偏移：换算到官方时区后仍在同一周期（09-27 04:30 北京 = 09-27 05:30 官方）。
        self.task.config['_execution_states'] = {'probe': '2026-09-27T04:30:00+08:00'}
        with patch.object(type(self.task), '_now_game', return_value=self._at(27, 6, 0)):
            self.assertTrue(self.task.is_done('probe', 'day'))

    def test_week_period_rolls_over_tuesday_5am_official(self):
        with patch.object(type(self.task), '_now_game', return_value=self._at(28, 23, 0)):  # 2026-09-28 周一。
            self.task.mark_done('probe', 'week')
            self.assertTrue(self.task.is_done('probe', 'week'))
        with patch.object(type(self.task), '_now_game', return_value=self._at(29, 6, 0)):  # 2026-09-29 周二。
            self.assertFalse(self.task.is_done('probe', 'week'))
