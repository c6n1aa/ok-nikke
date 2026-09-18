import os
import unittest
from unittest.mock import MagicMock, PropertyMock, call, patch

import numpy as np

from ok.feature.Box import Box
from ok.task.exceptions import WaitFailedException
from ok.test.TaskTestCase import TaskTestCase

from src import event_stage
from src.config import config
from src.tasks.EventTask import EventTask

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')


def _isolate_task_config(task, name):
    """把任务配置重定向到 dev_tools/test_configs 下的临时文件，避免污染真实 configs/。"""
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')
    task.config['_execution_states'] = {}


def _fixed_height(task, height=1440):
    """把任务的屏幕高度固定为 1440（去重容差、兜底行距按屏高比例计算，测试需确定值）。"""
    return patch.object(type(task), 'height', new_callable=PropertyMock, return_value=height)


def _fake_event(key, name, url, end_time=0):
    """构造一条假的 CalendarEvent（banner 匹配用，只动 key/name/url）。"""
    from src import event_calendar
    return event_calendar.CalendarEvent(key=key, name=name, category='version_event',
                                        event_type='StoryEvent', start_time=0, end_time=end_time, url=url)


class _DebugOffTestCase(TaskTestCase):
    """基类：测试环境强制 debug=True，本基类将其屏蔽，以便验证正常的已完成/记录逻辑。"""

    def setUp(self):
        patcher = patch.object(self.task, '_in_debug', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestEventTask(_DebugOffTestCase):
    task_class = EventTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'EventTask')
        self.task.clear_done('event')
        for key in ('签到', '剧情', '扫荡', '扫荡关卡', '挑战', '任务', '商店', '剧情模式'):
            self.task.config[key] = self.task.default_config[key]
        exit_patcher = patch.object(self.task, '_exit_to_lobby')  # 拦截收尾返回大厅步骤，避免测试触碰真实窗口。
        exit_patcher.start()
        self.addCleanup(exit_patcher.stop)

    def test_config_defaults(self):
        self.assertEqual('活动', self.task.name)
        self.assertIn('活动', self.task.description)
        self.assertEqual({'event': 'day'}, EventTask.done_keys)
        self.assertTrue(self.task.default_config['签到'])
        self.assertTrue(self.task.default_config['剧情'])
        self.assertFalse(self.task.default_config['扫荡'])
        self.assertEqual('1-11', self.task.default_config['扫荡关卡'])
        self.assertTrue(self.task.default_config['挑战'])
        self.assertTrue(self.task.default_config['任务'])
        self.assertFalse(self.task.default_config['商店'])
        self.assertEqual('NORMAL', self.task.default_config['剧情模式'])  # 难度选项沿用游戏内英文标签。
        for key in ('签到', '剧情', '扫荡', '扫荡关卡', '挑战', '任务', '商店', '剧情模式'):
            self.assertIn(key, self.task.config_description)
        self.assertEqual('drop_down', self.task.config_type['剧情模式']['type'])
        self.assertTrue(self.task.config_type['剧情模式']['hidden'])  # 难度选择未实现：入口隐藏。
        self.assertTrue(self.task.config_type['商店']['hidden'])  # 商店 v1 未实现：入口隐藏。
        self.assertNotIn('剧情', self.task.config_type)  # 难度未实现：不做开关联动（联动会把隐藏项渲染出来）。
        self.assertEqual(['NORMAL', 'HARD'], list(self.task.config_type['剧情模式']['options']))
        self.assertEqual(['1-11', '1-09', '1-07'], list(self.task.config_type['扫荡关卡']['options']))
        self.assertEqual('drop_down', self.task.config_type['扫荡关卡']['type'])
        self.assertEqual(['扫荡关卡'], self.task.config_type['扫荡']['sub_configs'][True])
        self.assertEqual([], self.task.config_type['扫荡']['sub_configs'][False])

    def test_screens_registered(self):
        self.assertIn('event_list_page', self.task.screens)
        self.assertIn('event_main', self.task.screens)
        self.assertEqual('box_sub_pages_title', self.task.screens['event_list_page']['ocr_box'])

    def test_skip_when_already_done(self):
        self.task.mark_done('event', 'day')
        with patch.object(self.task, 'ensure_screen', side_effect=AssertionError('已完成不应动窗口')), \
                patch.object(self.task, '_probe_event_context', side_effect=AssertionError('不应探测')), \
                patch.object(self.task, '_process_event_list', side_effect=AssertionError('不应处理列表')):
            self.task.run()
        self.assertTrue(self.task.is_done('event', 'day'))

    def test_abort_when_lobby_not_found(self):
        with patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'ensure_screen', return_value=False), \
                patch.object(self.task, '_process_event_list', side_effect=AssertionError('不应处理列表')):
            self.task.run()
        self.assertFalse(self.task.is_done('event', 'day'))

    def test_run_marks_done_when_list_flow_succeeds(self):
        with patch.object(self.task, 'ensure_screen', return_value=True), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_process_event_list') as list_mock:
            self.task.run()
        list_mock.assert_called_once()
        self.assertTrue(self.task.is_done('event', 'day'))

    def test_run_not_marked_when_list_flow_fails(self):
        with patch.object(self.task, 'ensure_screen', return_value=True), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'try_step', return_value=False):
            self.task.run()
        self.assertFalse(self.task.is_done('event', 'day'))

    def test_run_takeover_branch_when_already_in_event(self):
        # 用户手动进入活动（主页/子页面）时直接接管：不再走大厅闸门与列表遍历。
        with patch.object(self.task, 'ensure_screen', side_effect=AssertionError('接管分支不应回大厅')), \
                patch.object(self.task, '_probe_event_context', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_takeover_event') as takeover_mock, \
                patch.object(self.task, '_process_event_list', side_effect=AssertionError('接管分支不应遍历列表')):
            self.task.run()
        takeover_mock.assert_called_once()
        self.assertTrue(self.task.is_done('event', 'day'))

    def test_probe_event_context_detects_sub_pages(self):
        with patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, 'is_screen', side_effect=lambda name: name == 'event_stage_page'):
            self.assertTrue(self.task._probe_event_context())  # 关卡页也算「在活动内」。
        with patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_detail_page_open', return_value=True):
            self.assertTrue(self.task._probe_event_context())  # 详情页同样算。
        with patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_detail_page_open', return_value=False):
            self.assertFalse(self.task._probe_event_context())

    def test_ensure_event_menu_returns_from_stage_page(self):
        with patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, '_detail_page_open', return_value=False), \
                patch.object(self.task, 'transition') as transition_mock:
            self.task._ensure_event_menu()
        transition_mock.assert_called_once_with('event_main', click=self.task._click_back_to_menu,
                                                wait_confirm=10, after_sleep=1)

    def test_click_back_to_menu_uses_base_back_lookup(self):
        # 活动子页返回键样式逐期变（common_back 模板在签到页实测仅 0.41），走基类三层兜底定位。
        back = Box(26, 1342, 37, 35, confidence=1, name='common_back')
        with patch.object(self.task, '_find_back_button', return_value=back) as find_mock, \
                patch.object(self.task, 'click_box') as click_mock:
            self.task._click_back_to_menu()
        find_mock.assert_called_once()
        click_mock.assert_called_once_with(back, after_sleep=1)

    def test_click_back_to_menu_raises_without_button(self):
        with patch.object(self.task, '_find_back_button', return_value=None), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('无按钮不应点击')):
            self.assertRaises(WaitFailedException, self.task._click_back_to_menu)

    def test_ensure_event_menu_closes_detail_page_first(self):
        with patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_close_stage_detail') as close_mock, \
                patch.object(self.task, 'transition') as transition_mock:
            self.task._ensure_event_menu()
        close_mock.assert_called_once()  # 详情页先关到关卡列表。
        transition_mock.assert_called_once()  # 再从关卡列表退回菜单页。

    def test_ensure_event_menu_noop_when_on_menu(self):
        with patch.object(self.task, '_probe_event_main', return_value=True), \
                patch.object(self.task, '_probe_story_sub_page', return_value=False), \
                patch.object(self.task, 'transition', side_effect=AssertionError('已在菜单页不应导航')):
            self.task._ensure_event_menu()

    def test_ensure_event_menu_returns_twice_from_story_sub_page(self):
        # 关卡页的上一级是大活动剧情子页面（标题同为「剧情活动」）：退一级后仍在子页面上 → 再退一级回地图页。
        with patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, '_detail_page_open', return_value=False), \
                patch.object(self.task, '_probe_story_sub_page', return_value=True), \
                patch.object(self.task, 'transition') as transition_mock:
            self.task._ensure_event_menu()
        self.assertEqual(2, transition_mock.call_count)  # 关卡页 → 剧情子页面 → 地图页。
        transition_mock.assert_called_with('event_main', click=self.task._click_back_to_menu,
                                           wait_confirm=10, after_sleep=1)

    def test_ensure_event_menu_leaves_story_sub_page_on_takeover(self):
        # 接管时人在剧情子页面上：先退一级回地图页，落地后确认菜单可见即停（不再多点一次返回键）。
        with patch.object(self.task, '_probe_event_main', return_value=True), \
                patch.object(self.task, '_detail_page_open', return_value=False), \
                patch.object(self.task, '_probe_story_sub_page', side_effect=[True, False]), \
                patch.object(self.task, 'transition') as transition_mock:
            self.task._ensure_event_menu()
        transition_mock.assert_called_once_with('event_main', click=self.task._click_back_to_menu,
                                                wait_confirm=10, after_sleep=1)

    def test_probe_menu_entries_stops_at_first_hit(self):
        # 活动菜单可见性判据：挑战/任务/商店任一命中即菜单在（命中即短路，不查其余入口）。
        with patch.object(self.task, '_probe_entry', side_effect=lambda label: label == '任务') as probe_mock:
            self.assertTrue(self.task._probe_menu_entries())
        self.assertEqual(['挑战', '任务'], [call.args[0] for call in probe_mock.call_args_list])

    def test_probe_story_sub_page_needs_sub_entry_without_menu(self):
        # 剧情子页面判据 = 在活动主页 + 没有活动菜单 + 只有「加成」类剧情入口。
        sub_entry = Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')
        with patch.object(self.task, '_probe_event_main', return_value=True), \
                patch.object(self.task, '_probe_menu_entries', return_value=False), \
                patch.object(self.task, '_entry_box', return_value=sub_entry):
            self.assertTrue(self.task._probe_story_sub_page())
        with patch.object(self.task, '_probe_event_main', return_value=True), \
                patch.object(self.task, '_probe_menu_entries', return_value=True), \
                patch.object(self.task, '_entry_box', side_effect=AssertionError('菜单在不应探测剧情入口')):
            self.assertFalse(self.task._probe_story_sub_page())  # 菜单在 = 菜单页（小活动主页同款入口）。
        with patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, '_probe_menu_entries', side_effect=AssertionError('不在主页不应探测菜单')), \
                patch.object(self.task, '_entry_box', side_effect=AssertionError('不在主页不应探测入口')):
            self.assertFalse(self.task._probe_story_sub_page())

    def test_process_event_list_no_events(self):
        with patch.object(self.task, '_pending_events', return_value=[]), \
                patch.object(self.task, '_enter_event_list', side_effect=AssertionError('无活动不应进列表页')):
            self.task._process_event_list()

    def test_process_event_list_warns_when_event_never_matched(self):
        # 全部位置都没匹配到卡片（保底包过期/活动未上架）：遍历后打一条汇总告警便于排查。
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(self.task, '_pending_events', return_value=[event]), \
                patch.object(self.task, '_reposition_list', side_effect=[True, False]), \
                patch.object(self.task, '_find_event_row', return_value=None), \
                patch.object(self.task, '_enter_and_probe', side_effect=AssertionError('未匹配不应进入')), \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._process_event_list()
        warn_mock.assert_called_once()  # 只告警一次（汇总）。
        self.assertIn('key1', warn_mock.call_args.args[0])

    def test_pending_events_filters_expired(self):
        # 快照里的过期活动被剔除（end_time 已过不再空扫）；end_time=0 的时间未知活动保留。
        import time

        from src import event_calendar
        expired = _fake_event('old', '旧活动', 'https://cdn/old.png', end_time=1)
        unknown = _fake_event('unknown', '未知时间', 'https://cdn/unknown.png', end_time=0)
        snapshot = event_calendar.CalendarSnapshot(fetched_at=time.time(), events=(expired, unknown), status={})
        with patch.object(event_calendar, 'load_snapshot', return_value=snapshot):
            events = self.task._pending_events()
        self.assertEqual(['unknown'], [event.key for event in events])

    def test_pending_events_refreshes_when_snapshot_missing(self):
        # 无快照时走 refresh（唯一联网入口），结果按未过期过滤后取最新 2 个。
        from src import event_calendar
        new = _fake_event('new', '新活动', 'https://cdn/new.png', end_time=0)
        snapshot = event_calendar.CalendarSnapshot(fetched_at=1, events=(new,), status={})
        with patch.object(event_calendar, 'load_snapshot', return_value=None), \
                patch.object(event_calendar, 'refresh', return_value=snapshot) as refresh_mock:
            events = self.task._pending_events()
        refresh_mock.assert_called_once()
        self.assertEqual(['new'], [event.key for event in events])

    def test_process_event_list_matches_and_probes_events(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        with patch.object(self.task, '_pending_events', return_value=[event]), \
                patch.object(self.task, '_reposition_list', return_value=True), \
                patch.object(self.task, '_find_event_row', side_effect=[row, None]), \
                patch.object(self.task, '_enter_and_probe') as probe_mock, \
                patch.object(self.task, '_recover_to_lobby', return_value=True):
            self.task._process_event_list()
        probe_mock.assert_called_once_with(row)  # 第一个位置命中一次，第二个位置未命中即退出。

    def test_process_event_list_stops_when_list_hits_bottom(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(self.task, '_pending_events', return_value=[event]), \
                patch.object(self.task, '_reposition_list', return_value=False), \
                patch.object(self.task, '_find_event_row', side_effect=AssertionError('到底后不应再定位活动')) as find_mock:
            self.task._process_event_list()
        find_mock.assert_not_called()  # 进入列表即到底，直接退出遍历。

    def test_enter_and_probe_event_runs_subflows(self):
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=True), \
                patch.object(self.task, '_wait_menu_ready') as menu_ready_mock, \
                patch.object(self.task, '_run_event_subflows') as subflows_mock:
            self.task._enter_and_probe(row)
        click_mock.assert_called_once_with(row, after_sleep=10)  # 10s 覆盖过场动画 + 菜单稳定。
        menu_ready_mock.assert_called_once()  # 进入确认后先等菜单栏就绪再探测入口。
        subflows_mock.assert_called_once()

    def test_enter_and_probe_non_event_card_returns_to_lobby(self):
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=False), \
                patch.object(self.task, '_recover_to_lobby') as recover_mock, \
                patch.object(self.task, '_run_event_subflows', side_effect=AssertionError('非活动不应执行子流程')):
            self.task._enter_and_probe(row)
        recover_mock.assert_called_once()

    def test_enter_event_returns_true_and_waits_menu(self):
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=True), \
                patch.object(self.task, '_wait_menu_ready') as menu_ready_mock, \
                patch.object(self.task, '_run_event_subflows', side_effect=AssertionError('_enter_event 不应执行子流程')):
            self.assertTrue(self.task._enter_event(row))
        click_mock.assert_called_once_with(row, after_sleep=10)  # 点击卡片进入。
        menu_ready_mock.assert_called_once()  # 确认进入后先等菜单栏就绪。

    def test_enter_event_returns_false_without_confirmation(self):
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=False), \
                patch.object(self.task, '_wait_menu_ready', side_effect=AssertionError('未确认进入不应等菜单')):
            self.assertFalse(self.task._enter_event(row))

    def test_process_event_list_sets_current_event_context(self):
        # 子流程失败恢复回大厅后重入需要当前活动上下文：处理期间 _current_event 必须指向该活动。
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        seen = {}

        def probe(box):
            seen['key'] = self.task._current_event.key  # 处理中应能取到当前活动。

        with patch.object(self.task, '_pending_events', return_value=[event]), \
                patch.object(self.task, '_reposition_list', return_value=True), \
                patch.object(self.task, '_find_event_row', side_effect=[row, None]), \
                patch.object(self.task, '_enter_and_probe', side_effect=probe), \
                patch.object(self.task, '_recover_to_lobby', return_value=True):
            self.task._process_event_list()
        self.assertEqual('key1', seen['key'])  # 处理时上下文已设置。
        self.assertIsNone(self.task._current_event)  # 处理结束后清除。

    # ---- 失败恢复回大厅后的重入（_nav_to_event_main / _locate_event_row） ----

    def test_nav_to_event_main_noop_when_already_on_menu(self):
        with patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, 'ensure_screen', side_effect=AssertionError('已在主页不应导航')), \
                patch.object(self.task, '_ensure_event_menu', side_effect=AssertionError('已在主页不应退回')):
            self.task._nav_to_event_main()

    def test_nav_to_event_main_returns_from_sub_page(self):
        # 在活动子页面（关卡列表页/详情页）：逐级退回菜单页，不重新从大厅进入。
        with patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_probe_event_context', return_value=True), \
                patch.object(self.task, '_ensure_event_menu') as menu_mock, \
                patch.object(self.task, 'ensure_screen', side_effect=AssertionError('子页面不应回大厅')):
            self.task._nav_to_event_main()
        menu_mock.assert_called_once()

    def test_nav_to_event_main_reenters_from_lobby(self):
        # 失败恢复回大厅后：用当前活动上下文经 大厅→列表→banner 定位重新进入活动主页。
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        self.task._current_event = event
        with patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'ensure_screen') as lobby_mock, \
                patch.object(self.task, '_enter_event_list') as list_mock, \
                patch.object(self.task, '_locate_event_row', return_value=row) as locate_mock, \
                patch.object(self.task, '_enter_event', return_value=True) as enter_mock, \
                patch.object(self.task, '_run_event_subflows', side_effect=AssertionError('重入不应触发子流程')):
            self.task._nav_to_event_main()
        lobby_mock.assert_called_once_with('lobby')
        list_mock.assert_called_once()
        locate_mock.assert_called_once_with(event)
        enter_mock.assert_called_once_with(row)  # 只进活动，不递归探测子流程。

    def test_nav_to_event_main_raises_without_context(self):
        self.task._current_event = None
        with patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'ensure_screen', side_effect=AssertionError('无上下文不应回大厅')):
            self.assertRaises(WaitFailedException, self.task._nav_to_event_main)

    def test_nav_to_event_main_raises_when_row_not_located(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        self.task._current_event = event
        with patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'ensure_screen'), \
                patch.object(self.task, '_enter_event_list'), \
                patch.object(self.task, '_locate_event_row', return_value=None), \
                patch.object(self.task, '_enter_event', side_effect=AssertionError('未定位不应进入')):
            self.assertRaises(WaitFailedException, self.task._nav_to_event_main)

    def test_nav_to_event_main_raises_when_enter_not_confirmed(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        self.task._current_event = event
        with patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'ensure_screen'), \
                patch.object(self.task, '_enter_event_list'), \
                patch.object(self.task, '_locate_event_row', return_value=Box(1, 1, 2, 2, confidence=1, name='row')), \
                patch.object(self.task, '_enter_event', return_value=False):
            self.assertRaises(WaitFailedException, self.task._nav_to_event_main)

    def test_locate_event_row_scrolls_until_found(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        with patch.object(self.task, '_scroll_list_to_top') as top_mock, \
                patch.object(self.task, '_scroll_list_down', return_value=True) as down_mock, \
                patch.object(self.task, '_find_event_row', side_effect=[None, row]) as find_mock:
            found = self.task._locate_event_row(event)
        self.assertEqual(row, found)
        top_mock.assert_called_once()  # 先归一到顶部再逐位下滚。
        self.assertEqual(1, down_mock.call_count)  # 第一个位置未命中，下滚一位才命中。
        self.assertEqual(2, find_mock.call_count)

    def test_locate_event_row_returns_none_when_bottom(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(self.task, '_scroll_list_to_top'), \
                patch.object(self.task, '_scroll_list_down', return_value=False), \
                patch.object(self.task, '_find_event_row', return_value=None):
            self.assertIsNone(self.task._locate_event_row(event))  # 到底仍未命中返回 None。

    def test_run_event_subflows_small_event_scenario(self):
        # 小活动场景：签到/商店探测不到（None 不报错不阻塞），剧情/挑战/任务正常执行。
        def probe(label):
            return label in ('剧情', '挑战', '任务')

        with patch.object(self.task, '_probe_entry', side_effect=probe), \
                patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_flow_checkin', side_effect=AssertionError('签到不应执行')) as checkin_mock, \
                patch.object(self.task, '_flow_story') as story_mock, \
                patch.object(self.task, '_flow_challenge') as challenge_mock, \
                patch.object(self.task, '_flow_mission') as mission_mock, \
                patch.object(self.task, '_flow_shop', side_effect=AssertionError('商店不应执行')):
            self.task._run_event_subflows()
        checkin_mock.assert_not_called()
        story_mock.assert_called_once()
        challenge_mock.assert_called_once()
        mission_mock.assert_called_once()

    def test_run_event_subflows_aborts_when_leaving_event_page(self):
        # 上一子流程失败恢复回了大厅：后续子流程不再在错误页面上探测（否则入口探测全误判）。
        with patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_probe_entry', side_effect=AssertionError('不在活动主页不应探测')) as probe_mock:
            self.task._run_event_subflows()
        probe_mock.assert_not_called()  # 第一个子流程前就中止。

    def test_run_event_subflows_large_event_scenario(self):
        # 大活动场景：签到/剧情/挑战/任务全部探测到并各执行一次。
        def probe(label):
            return label in ('签到', '剧情', '挑战', '任务')

        with patch.object(self.task, '_probe_entry', side_effect=probe), \
                patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_flow_checkin') as checkin_mock, \
                patch.object(self.task, '_flow_story') as story_mock, \
                patch.object(self.task, '_flow_challenge') as challenge_mock, \
                patch.object(self.task, '_flow_mission') as mission_mock, \
                patch.object(self.task, '_flow_shop', side_effect=AssertionError('商店默认关闭不应执行')):
            self.task._run_event_subflows()
        self.assertEqual(1, checkin_mock.call_count)
        self.assertEqual(1, story_mock.call_count)
        self.assertEqual(1, challenge_mock.call_count)
        self.assertEqual(1, mission_mock.call_count)

    def test_do_shop_skipped_when_disabled(self):
        self.task.config['商店'] = False
        with patch.object(self.task, '_probe_entry', side_effect=AssertionError('关闭时不应探测')), \
                patch.object(self.task, '_flow_shop', side_effect=AssertionError('关闭时不应执行')):
            self.task._do_shop()

    def test_do_checkin_skipped_when_probe_missing(self):
        self.task.config['签到'] = True
        with patch.object(self.task, '_probe_entry', return_value=False), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('探测不到不应执行')):
            self.task._do_checkin()

    # ---- 签到印章流程（仅大活动；面板判据走 OCR 文字，同登录奖励） ----

    def _claim_all_box(self):
        return Box(1150, 1250, 260, 60, confidence=1, name='全部领取')

    def test_find_claim_all_scans_panel_region(self):
        hit = self._claim_all_box()
        with patch.object(self.task, 'box_of_screen', return_value=Box(0, 0, 10, 10, confidence=1, name='area')) as area_mock, \
                patch.object(self.task, 'ocr', return_value=[hit]) as ocr_mock:
            found = self.task._find_claim_all()
        self.assertEqual(hit, found)
        ocr_mock.assert_called_once()
        from src.tasks.EventTask import _CLAIM_ALL_TEXT
        self.assertEqual([_CLAIM_ALL_TEXT], ocr_mock.call_args.kwargs['match'])  # 用固定文案判据。

    def test_find_claim_all_returns_none_without_hit(self):
        with patch.object(self.task, 'box_of_screen', return_value=Box(0, 0, 10, 10, confidence=1, name='area')), \
                patch.object(self.task, 'ocr', return_value=[]):
            self.assertIsNone(self.task._find_claim_all())

    def test_claim_button_box_pads_text_box(self):
        from src.tasks.EventTask import _CLAIM_ALL_PAD
        text = Box(1000, 1200, 200, 50, confidence=1, name='全部领取')
        padded = self.task._claim_button_box(text)
        self.assertLess(padded.x, text.x)  # 水平外扩到按钮底色。
        self.assertLess(padded.y, text.y)  # 垂直外扩。
        self.assertGreater(padded.width, text.width)
        self.assertGreater(padded.height, text.height)
        self.assertAlmostEqual(text.width * _CLAIM_ALL_PAD[0], text.x - padded.x)  # 外扩量为比例值。

    def test_flow_checkin_claims_then_returns_to_menu(self):
        # 正常路径：进签到 → 反向判切页（菜单页消失）→ 等「全部领取」→ 全部领取（彩色可用）→ 清遮罩 → 回菜单页。
        entry = Box(60, 10, 30, 10, confidence=1, name='签到印章')
        claim = self._claim_all_box()

        def run_condition(condition, time_out=None, settle_time=0, **kwargs):
            return condition()  # 单测驱动：逐次实算条件（第一次菜单页消失、第二次全部领取出现）。

        with patch.object(self.task, '_nav_to_event_main') as nav_mock, \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', side_effect=run_condition) as wait_mock, \
                patch.object(self.task, 'is_screen', return_value=False) as screen_mock, \
                patch.object(self.task, '_find_claim_all', return_value=claim), \
                patch.object(self.task, 'is_feature_enabled', return_value=True) as enabled_mock, \
                patch.object(self.task, 'close_overlay') as overlay_mock, \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_checkin()
        nav_mock.assert_called_once()  # 进入前就位活动主页。
        self.assertEqual(2, wait_mock.call_count)  # 两次等待：切页 + 全部领取。
        screen_mock.assert_called_once_with('event_main')  # 反向判：菜单页消失即切页。
        click_mock.assert_any_call(entry, after_sleep=2)  # 点签到入口。
        click_mock.assert_any_call(claim, after_sleep=1)  # 点全部领取。
        enabled_mock.assert_called_once()  # 判一次按钮底色。
        overlay_mock.assert_called_once()  # 领后清奖励遮罩。
        back_mock.assert_called_once()  # 点返回键回菜单页（整页界面，非模态窗）。

    def test_flow_checkin_skips_claim_when_button_disabled(self):
        # 按钮灰白（今日已领完）：不点击领取，仍点返回回菜单页。
        entry = Box(60, 10, 30, 10, confidence=1, name='签到印章')
        claim = self._claim_all_box()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=True), \
                patch.object(self.task, '_find_claim_all', return_value=claim), \
                patch.object(self.task, 'is_feature_enabled', return_value=False), \
                patch.object(self.task, 'close_overlay', side_effect=AssertionError('无可领不应清遮罩')), \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_checkin()
        self.assertNotIn(claim, [call.args[0] for call in click_mock.call_args_list])  # 灰白不点领取。
        back_mock.assert_called_once()  # 仍要点返回。

    def test_flow_checkin_menu_still_present_returns(self):
        # 反向判切页失败：菜单页仍在（小人未走到签到地点/切页失败）→ 告警后直接回菜单页跳过领取，不抛异常。
        from src.tasks.EventTask import _SD_ARRIVE_TIMEOUT
        entry = Box(60, 10, 30, 10, confidence=1, name='签到印章')
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=False) as wait_mock, \
                patch.object(self.task, 'log_warning') as warn_mock, \
                patch.object(self.task, 'is_feature_enabled', side_effect=AssertionError('未切页不应判态')), \
                patch.object(self.task, 'close_overlay', side_effect=AssertionError('未切页不应清遮罩')), \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_checkin()
        self.assertEqual(_SD_ARRIVE_TIMEOUT, wait_mock.call_args.kwargs['time_out'])  # 用到达等待窗口。
        warn_mock.assert_called_once()
        back_mock.assert_called_once()  # 兜底回菜单页。

    def test_flow_checkin_page_switched_but_claim_not_found(self):
        # 已切到签到页（菜单页消失）但未识别到「全部领取」：告警后仍回菜单页，不抛异常。
        entry = Box(60, 10, 30, 10, confidence=1, name='签到印章')

        def run_condition(condition, time_out=None, settle_time=0, **kwargs):
            return condition()  # 单测驱动：第一次菜单页消失（True）、第二次全部领取未出现（False）。

        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', side_effect=run_condition) as wait_mock, \
                patch.object(self.task, 'is_screen', return_value=False) as screen_mock, \
                patch.object(self.task, '_find_claim_all', return_value=None), \
                patch.object(self.task, 'log_warning') as warn_mock, \
                patch.object(self.task, 'is_feature_enabled', side_effect=AssertionError('无全部领取不应判态')), \
                patch.object(self.task, 'close_overlay', side_effect=AssertionError('无全部领取不应清遮罩')), \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_checkin()
        self.assertEqual(2, wait_mock.call_count)  # 两次等待都跑完。
        screen_mock.assert_called_once_with('event_main')  # 第一次反向判切页命中。
        warn_mock.assert_called_once()  # 第二次等不到全部领取告警。
        back_mock.assert_called_once()  # 兜底回菜单页。

    def test_flow_checkin_missing_entry_raises(self):
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=None), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('入口缺失不应点击')):
            self.assertRaises(WaitFailedException, self.task._flow_checkin)

    # ---- 任务弹窗流程（大小活动同一套弹窗；判据走 coco 区域 + OCR 文案，无可复用模板特征） ----

    def _mission_entry(self):
        return Box(2418, 248, 141, 142, confidence=1, name='任务')

    def _mission_subtitle(self):
        return Box(942, 314, 221, 64, confidence=1, name='CHALLENGE')

    def _mission_tab(self, x=1035):
        return Box(x, 292, 44, 44, confidence=1, name='event_mission_tab')

    def test_entry_regions_scans_extra_box_before_menu_bands(self):
        extra = Box(2418, 248, 141, 142, confidence=1, name='box_event_menu_mission')
        menu = Box(0, 0, 10, 10, confidence=1, name='menu')
        with patch.object(self.task, '_optional_box', return_value=extra) as box_mock, \
                patch.object(self.task, '_menu_boxes', return_value=[menu]):
            regions = self.task._entry_regions('任务')
        self.assertEqual([(extra, True), (menu, False)], regions)  # 专属区优先并带专属标记，菜单带兜底。
        box_mock.assert_called_once_with('box_event_menu_mission')  # 只解析该入口声明的专属区。

    def test_entry_regions_without_extra_falls_back_to_menu_bands(self):
        menu = Box(0, 0, 10, 10, confidence=1, name='menu')
        with patch.object(self.task, '_optional_box', side_effect=AssertionError('无专属区不应解析')), \
                patch.object(self.task, '_menu_boxes', return_value=[menu]):
            self.assertEqual([(menu, False)], self.task._entry_regions('签到'))  # 未声明专属区的入口只走菜单带。

    def test_probe_mission_scans_extra_region(self):
        # 大活动「任务」不在菜单带内：该入口的专属区域被纳入探测范围并在其中识别到关键词。
        entry = self._mission_entry()
        with patch.object(self.task, '_optional_box', return_value=entry), \
                patch.object(self.task, '_menu_boxes', return_value=[]), \
                patch.object(self.task, 'ocr', return_value=[entry]) as ocr_mock:
            self.assertTrue(self.task._probe_entry('任务'))
        self.assertEqual(entry, ocr_mock.call_args.kwargs['box'])  # 在专属区域内识别。

    def test_find_mission_subtitle_uses_region_and_keyword(self):
        from src.tasks.EventTask import _MISSION_SUBTITLE_BOX, _MISSION_SUBTITLE_TEXT
        hit = self._mission_subtitle()
        region = Box(900, 300, 400, 100, confidence=1, name=_MISSION_SUBTITLE_BOX)
        with patch.object(self.task, '_optional_box', return_value=region) as box_mock, \
                patch.object(self.task, 'ocr', return_value=[hit]) as ocr_mock:
            found = self.task._find_mission_subtitle()
        self.assertEqual(hit, found)
        box_mock.assert_called_once_with(_MISSION_SUBTITLE_BOX)  # 弹窗就位判据取副标题区域。
        self.assertEqual(region, ocr_mock.call_args.kwargs['box'])
        self.assertEqual([_MISSION_SUBTITLE_TEXT], ocr_mock.call_args.kwargs['match'])  # 固定关键词判据。

    def test_find_mission_subtitle_returns_none_without_region(self):
        with patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'ocr', side_effect=AssertionError('区域缺失不应 OCR')):
            self.assertIsNone(self.task._find_mission_subtitle())  # 区域未标注视为弹窗未就位。

    def test_flow_mission_claims_then_closes_by_blank(self):
        # 正常路径：点任务入口 → 弹窗就位 → 分栏目领取 → 点空白关弹窗回菜单页。
        entry = self._mission_entry()
        with patch.object(self.task, '_nav_to_event_main') as nav_mock, \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=True) as wait_mock, \
                patch.object(self.task, '_claim_mission_pages') as pages_mock, \
                patch.object(self.task, 'close_popup_by_blank', return_value=True) as blank_mock:
            self.task._flow_mission()
        nav_mock.assert_called_once()  # 进入前就位活动主页。
        click_mock.assert_any_call(entry, after_sleep=2)  # 点任务入口弹出弹窗。
        from src.tasks.EventTask import _MISSION_READY_TIMEOUT
        self.assertEqual(_MISSION_READY_TIMEOUT, wait_mock.call_args.kwargs['time_out'])  # 用弹窗就位窗口等待。
        pages_mock.assert_called_once()  # 弹窗就位后按栏目领取。
        blank_mock.assert_called_once()  # 领取完点空白关弹窗。

    def test_mission_popup_ready_prefers_tabs_then_falls_back_to_subtitle(self):
        # 弹窗就位判据：大活动两个栏目定位到即就位；无栏目时回落小活动副标题关键词。
        tabs = {'daily': self._mission_tab(1035), 'challenge': self._mission_tab(1395)}
        with patch.object(self.task, '_mission_tabs', return_value=tabs), \
                patch.object(self.task, '_find_mission_subtitle', side_effect=AssertionError('有栏目无需认副标题')):
            self.assertTrue(self.task._mission_popup_ready())  # 大活动两栏目弹窗。
        with patch.object(self.task, '_mission_tabs', return_value=None), \
                patch.object(self.task, '_find_mission_subtitle', return_value=self._mission_subtitle()):
            self.assertTrue(self.task._mission_popup_ready())  # 小活动单页弹窗。
        with patch.object(self.task, '_mission_tabs', return_value=None), \
                patch.object(self.task, '_find_mission_subtitle', return_value=None):
            self.assertFalse(self.task._mission_popup_ready())  # 都不命中 = 弹窗未就位。

    def test_mission_tabs_locates_both_features_in_region(self):
        from src.tasks.EventTask import _MISSION_ICON_BOX
        daily = self._mission_tab(1035)
        challenge = self._mission_tab(1395)
        region = Box(927, 277, 707, 72, confidence=1, name=_MISSION_ICON_BOX)
        with patch.object(self.task, '_optional_box', return_value=region) as box_mock, \
                patch.object(self.task, 'find_feature', side_effect=[[daily], [challenge]]) as feature_mock:
            tabs = self.task._mission_tabs()
        box_mock.assert_called_once_with(_MISSION_ICON_BOX)  # 栏目固定在该区域内定位。
        self.assertEqual({'daily': daily, 'challenge': challenge}, tabs)
        self.assertEqual('event_mission_daily', feature_mock.call_args_list[0].args[0])  # 先定位每日任务栏目。
        self.assertEqual('event_mission_challenge', feature_mock.call_args_list[1].args[0])  # 再定位成就栏目。
        self.assertEqual(region, feature_mock.call_args_list[0].kwargs['box'])  # 特征匹配限定在栏目区。

    def test_mission_tabs_falls_back_to_tab_text_when_feature_missing(self):
        # 选中态会改变栏目图标外观：模板匹配落空时按栏目文案定位（文案跨期稳定）。
        daily = self._mission_tab(1035)
        challenge = self._mission_tab(1395)
        region = Box(927, 277, 707, 72, confidence=1, name='box_event_mission_icon')
        with patch.object(self.task, '_optional_box', return_value=region), \
                patch.object(self.task, 'find_feature', return_value=[]), \
                patch.object(self.task, 'ocr', side_effect=[[daily], [challenge]]) as ocr_mock:
            tabs = self.task._mission_tabs()
        self.assertEqual({'daily': daily, 'challenge': challenge}, tabs)
        from src.tasks.EventTask import _MISSION_TABS
        self.assertEqual([_MISSION_TABS[0][2]], ocr_mock.call_args_list[0].kwargs['match'])  # 用每日任务文案兜底。
        self.assertEqual([_MISSION_TABS[1][2]], ocr_mock.call_args_list[1].kwargs['match'])  # 用成就文案兜底。

    def test_mission_tabs_returns_none_without_region(self):
        with patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'find_feature', side_effect=AssertionError('区域缺失不应匹配特征')):
            self.assertIsNone(self.task._mission_tabs())  # 栏目区未标注 = 无栏目弹窗（小活动）。

    def test_mission_tabs_returns_none_when_one_tab_missing(self):
        daily = self._mission_tab(1035)
        region = Box(927, 277, 707, 72, confidence=1, name='box_event_mission_icon')
        with patch.object(self.task, '_optional_box', return_value=region), \
                patch.object(self.task, 'find_feature', return_value=[]), \
                patch.object(self.task, 'ocr', side_effect=[[daily], []]):
            self.assertIsNone(self.task._mission_tabs())  # 栏目不全不按多栏目流程处理。

    def test_mission_subtitle_text_joins_region_text(self):
        from src.tasks.EventTask import _MISSION_DAILY_SUBTITLE_BOX
        region = Box(943, 365, 262, 77, confidence=1, name=_MISSION_DAILY_SUBTITLE_BOX)
        texts = [Box(0, 0, 1, 1, confidence=1, name='DAILY '), Box(0, 0, 1, 1, confidence=1, name='MISSION')]
        with patch.object(self.task, '_optional_box', return_value=region) as box_mock, \
                patch.object(self.task, 'ocr', return_value=texts) as ocr_mock:
            text = self.task._mission_subtitle_text()
        box_mock.assert_called_once_with(_MISSION_DAILY_SUBTITLE_BOX)  # 页面状态判据取副标题区。
        self.assertEqual(region, ocr_mock.call_args.kwargs['box'])
        self.assertEqual('DAILY MISSION', text)  # 区域内文字整段拼接供前后比较。

    def test_mission_subtitle_text_returns_none_without_region_or_text(self):
        with patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'ocr', side_effect=AssertionError('区域缺失不应 OCR')):
            self.assertIsNone(self.task._mission_subtitle_text())  # 区域未标注视为状态未知。
        with patch.object(self.task, '_optional_box', return_value=Box(0, 0, 1, 1, confidence=1)), \
                patch.object(self.task, 'ocr', return_value=[]):
            self.assertIsNone(self.task._mission_subtitle_text())  # 区域内无文字视为状态未知。

    def test_switch_mission_tab_clicks_and_confirms_state_change(self):
        tab = self._mission_tab(1395)

        def run_condition(condition, **kwargs):
            return condition()  # 单测驱动：实算切换判据。

        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', side_effect=run_condition), \
                patch.object(self.task, '_mission_subtitle_text', return_value='CHALLENGE') as text_mock:
            state = self.task._switch_mission_tab(tab, 'DAILY MISSION')
        click_mock.assert_called_once_with(tab, after_sleep=1)  # 点栏目标签。
        self.assertEqual('CHALLENGE', state)  # 副标题与切换前不同即切换成功。
        text_mock.assert_called_once()  # 切换判据即副标题文字（切换后状态由判据返回）。

    def test_switch_mission_tab_returns_none_when_state_unchanged(self):
        tab = self._mission_tab(1035)
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=False), \
                patch.object(self.task, '_mission_subtitle_text', return_value='DAILY MISSION') as text_mock:
            self.assertIsNone(self.task._switch_mission_tab(tab, 'DAILY MISSION'))  # 副标题没变不算切换成功。
        text_mock.assert_not_called()  # 判据未通过不再取新状态。

    def test_claim_mission_pages_switches_challenge_then_daily(self):
        # 大活动两栏目：点开停在「每日任务」页 → 切「成就」领一轮 → 切回「每日任务」领一轮。
        tabs = {'daily': self._mission_tab(1035), 'challenge': self._mission_tab(1395)}
        manager = MagicMock()
        with patch.object(self.task, '_mission_tabs', return_value=tabs) as tabs_mock, \
                patch.object(self.task, '_mission_subtitle_text', return_value='DAILY MISSION') as text_mock, \
                patch.object(self.task, '_switch_mission_tab', side_effect=['CHALLENGE', 'DAILY MISSION']) as switch_mock, \
                patch.object(self.task, '_claim_mission_rewards') as claim_mock:
            manager.attach_mock(switch_mock, 'switch')
            manager.attach_mock(claim_mock, 'claim')
            self.task._claim_mission_pages()
        tabs_mock.assert_called_once()  # 先定位栏目。
        text_mock.assert_called_once()  # 点开先记录当前页面状态。
        self.assertEqual([call(tabs['challenge'], 'DAILY MISSION'), call(tabs['daily'], 'CHALLENGE')],
                         switch_mock.call_args_list)  # 先切成就（比记录状态），再切回每日任务（比成就页状态）。
        self.assertEqual(['switch', 'claim', 'switch', 'claim'],
                         [mock_call[0] for mock_call in manager.mock_calls])  # 每切换一次领一轮。

    def test_claim_mission_pages_claims_single_page_without_tabs(self):
        # 小活动弹窗（或栏目区未标注）：无栏目，直接领当前页。
        with patch.object(self.task, '_mission_tabs', return_value=None), \
                patch.object(self.task, '_switch_mission_tab', side_effect=AssertionError('无栏目不应切换')), \
                patch.object(self.task, '_claim_mission_rewards') as claim_mock:
            self.task._claim_mission_pages()
        claim_mock.assert_called_once()

    def test_claim_mission_pages_claims_current_when_subtitle_missing(self):
        tabs = {'daily': self._mission_tab(1035), 'challenge': self._mission_tab(1395)}
        with patch.object(self.task, '_mission_tabs', return_value=tabs), \
                patch.object(self.task, '_mission_subtitle_text', return_value=None), \
                patch.object(self.task, '_switch_mission_tab', side_effect=AssertionError('状态未知不应切换')), \
                patch.object(self.task, '_claim_mission_rewards') as claim_mock, \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._claim_mission_pages()
        claim_mock.assert_called_once()  # 无法判定页面状态时不冒险切换，只领当前页。
        warn_mock.assert_called_once()

    def test_claim_mission_pages_claims_current_when_challenge_switch_fails(self):
        tabs = {'daily': self._mission_tab(1035), 'challenge': self._mission_tab(1395)}
        with patch.object(self.task, '_mission_tabs', return_value=tabs), \
                patch.object(self.task, '_mission_subtitle_text', return_value='DAILY MISSION'), \
                patch.object(self.task, '_switch_mission_tab', return_value=None) as switch_mock, \
                patch.object(self.task, '_claim_mission_rewards') as claim_mock, \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._claim_mission_pages()
        switch_mock.assert_called_once_with(tabs['challenge'], 'DAILY MISSION')  # 尝试切成就栏目。
        claim_mock.assert_called_once()  # 切换未确认仍领当前页。
        warn_mock.assert_called_once()

    def test_claim_mission_pages_stops_when_switch_back_fails(self):
        tabs = {'daily': self._mission_tab(1035), 'challenge': self._mission_tab(1395)}
        with patch.object(self.task, '_mission_tabs', return_value=tabs), \
                patch.object(self.task, '_mission_subtitle_text', return_value='DAILY MISSION'), \
                patch.object(self.task, '_switch_mission_tab', side_effect=['CHALLENGE', None]), \
                patch.object(self.task, '_claim_mission_rewards') as claim_mock, \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._claim_mission_pages()
        claim_mock.assert_called_once()  # 只领了成就栏目：切不回每日任务即结束。
        warn_mock.assert_called_once()

    def test_flow_mission_blank_close_verify_checks_menu_screen(self):
        entry = self._mission_entry()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=True), \
                patch.object(self.task, '_claim_mission_pages'), \
                patch.object(self.task, 'close_popup_by_blank', return_value=True) as blank_mock, \
                patch.object(self.task, 'is_screen', return_value=True) as screen_mock:
            self.task._flow_mission()
            verify = blank_mock.call_args.args[0]  # 关闭判据：识别到活动菜单界面即完成。
            self.assertTrue(verify())
        screen_mock.assert_called_once_with('event_main')

    def test_flow_mission_popup_not_shown_skips_claim(self):
        # 弹窗未出现（栏目与副标题都没识别到）：不领取也不关闭，告警后结束（弹窗未开则无需关闭）。
        entry = self._mission_entry()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=False), \
                patch.object(self.task, 'log_warning') as warn_mock, \
                patch.object(self.task, '_claim_mission_pages', side_effect=AssertionError('弹窗未开不应领取')), \
                patch.object(self.task, 'close_popup_by_blank', side_effect=AssertionError('弹窗未开不需关闭')):
            self.task._flow_mission()
        warn_mock.assert_called_once()

    def test_flow_mission_missing_entry_raises(self):
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=None), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('入口缺失不应点击')):
            self.assertRaises(WaitFailedException, self.task._flow_mission)

    def test_flow_mission_warns_when_blank_close_fails(self):
        entry = self._mission_entry()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=True), \
                patch.object(self.task, '_claim_mission_pages'), \
                patch.object(self.task, 'close_popup_by_blank', return_value=False), \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._flow_mission()
        warn_mock.assert_called_once()  # 关不掉时仅告警，不抛异常。

    def test_claim_mission_rewards_returns_when_button_disabled(self):
        claim = self._claim_all_box()
        with patch.object(self.task, '_find_claim_all', return_value=claim), \
                patch.object(self.task, 'is_feature_enabled', return_value=False), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('灰白不应点击')), \
                patch.object(self.task, '_close_claim_overlay', side_effect=AssertionError('灰白不应清遮罩')):
            self.task._claim_mission_rewards()

    def test_claim_mission_rewards_stops_when_claim_text_missing(self):
        with patch.object(self.task, '_find_claim_all', return_value=None), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('未识别到按钮不应点击')), \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._claim_mission_rewards()
        warn_mock.assert_called_once()

    def test_claim_mission_rewards_hits_click_limit(self):
        from src.tasks.EventTask import _MISSION_CLAIM_MAX_CLICKS
        claim = self._claim_all_box()
        with patch.object(self.task, '_find_claim_all', return_value=claim), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_close_claim_overlay') as overlay_mock, \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._claim_mission_rewards()
        self.assertEqual(_MISSION_CLAIM_MAX_CLICKS, click_mock.call_count)  # 每轮都点，到上限为止。
        self.assertEqual(_MISSION_CLAIM_MAX_CLICKS, overlay_mock.call_count)  # 每轮点完都清遮罩。
        warn_mock.assert_called_once()  # 上限耗尽告警（防死循环）。

    # ---- 挑战流程（大小活动都有，同一套 UI；进入方式统一走 transition 守卫式进入） ----

    def _challenge_entry(self):
        return Box(60, 10, 30, 10, confidence=1, name='挑战')

    def _challenge_stage(self, y=985, x=1600):
        return Box(x, y, 25, 42, confidence=1, name='event_challenge_stage')

    def _challenge_stage_click(self, stage):
        """关卡标记的左移点击框（左移量由 _challenge_click_box 随机生成，流程测试里用固定值替身）。"""
        return Box(stage.x - 200, stage.y, stage.width, stage.height, confidence=1, name='event_challenge_stage')

    def _challenge_quick_box(self):
        return Box(1343, 1223, 34, 30, confidence=1, name='box_stage_detail_quick_battle')

    def _challenge_battle_box(self):
        return Box(1344, 1344, 37, 33, confidence=1, name='box_stage_detail_battle')

    def test_flow_challenge_enters_and_returns_to_menu_when_no_stage(self):
        # 进入路径：就位主页 → 定位挑战入口 → transition 守卫式进入挑战页 → 无可用关卡则直接回菜单页。
        from src.tasks.EventTask import _SD_ARRIVE_TIMEOUT
        entry = self._challenge_entry()
        with patch.object(self.task, '_nav_to_event_main') as nav_mock, \
                patch.object(self.task, '_entry_box', return_value=entry) as entry_mock, \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, '_wait_challenge_nodes'), \
                patch.object(self.task, '_find_available_challenge_stage', return_value=None), \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_challenge()
        nav_mock.assert_called_once()  # 进入前就位活动主页。
        entry_mock.assert_called_once_with('挑战')  # 定位挑战入口。
        transition_mock.assert_called_once_with('event_challenge_page', box=entry,  # 守卫式进入（补点不中断小人行为）。
                                                wait_confirm=_SD_ARRIVE_TIMEOUT,
                                                time_out=_SD_ARRIVE_TIMEOUT * 2, after_sleep=2)
        back_mock.assert_called_once()  # 收尾点返回回菜单页。

    def test_flow_challenge_raises_when_page_not_reached(self):
        # transition 确认挑战页失败（补点耗尽）：抛异常由 try_step 恢复。
        entry = self._challenge_entry()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'transition', side_effect=WaitFailedException('进入挑战页失败')), \
                patch.object(self.task, '_ensure_event_menu', side_effect=AssertionError('未进入不应收尾')):
            self.assertRaises(WaitFailedException, self.task._flow_challenge)

    def test_flow_challenge_missing_entry_raises(self):
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=None), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('入口缺失不应点击')):
            self.assertRaises(WaitFailedException, self.task._flow_challenge)

    def test_flow_challenge_quick_battle_available_runs_quick_then_returns(self):
        # 快速战斗可用：点关卡标记 → 详情页 → 走快速战斗链 → 结算后仍详情页则关页 → 回菜单。
        entry, stage = self._challenge_entry(), self._challenge_stage()
        quick, click = self._challenge_quick_box(), self._challenge_stage_click(stage)
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_wait_challenge_nodes'), \
                patch.object(self.task, '_find_available_challenge_stage', return_value=stage), \
                patch.object(self.task, '_challenge_click_box', return_value=click), \
                patch.object(self.task, 'wait_feature', return_value=True), \
                patch.object(self.task, '_optional_box', return_value=quick), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, '_run_quick_battle') as quick_mock, \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_close_stage_detail') as close_mock, \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_challenge()
        click_mock.assert_any_call(click, after_sleep=2)  # 点左移后的关卡点击框进详情页。
        quick_mock.assert_called_once()  # 快速战斗可用走快速战斗链。
        self.assertEqual(quick, quick_mock.call_args.args[0])  # 传入快速战斗区域。
        close_mock.assert_called_once_with(to_screen='event_challenge_page')  # 结算落回详情页则关页回挑战页。
        back_mock.assert_called_once()  # 收尾回菜单。

    def test_flow_challenge_normal_battle_when_quick_disabled(self):
        # 快速战斗灰白 → 普通战斗可用：进战斗界面等结束、点确认，结算回详情页后关页回菜单。
        entry, stage = self._challenge_entry(), self._challenge_stage()
        quick, battle = self._challenge_quick_box(), self._challenge_battle_box()
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_wait_challenge_nodes'), \
                patch.object(self.task, '_find_available_challenge_stage', return_value=stage), \
                patch.object(self.task, 'wait_feature', return_value=True), \
                patch.object(self.task, '_optional_box', side_effect=lambda name: {'box_stage_detail_quick_battle': quick,
                                                                                    'box_stage_detail_battle': battle}.get(name)), \
                patch.object(self.task, 'is_feature_enabled', side_effect=lambda box: box is battle), \
                patch.object(self.task, '_run_quick_battle', side_effect=AssertionError('快速灰白不应走快速战斗')), \
                patch.object(self.task, '_skip_story_if_present') as skip_mock, \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)) as battle_wait, \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_close_stage_detail') as close_mock, \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_challenge()
        click_mock.assert_any_call(battle, after_sleep=2)  # 点「战斗」进战斗界面。
        skip_mock.assert_called_once()  # 进战斗可能先播剧情，尝试跳过。
        battle_wait.assert_called_once()  # 等战斗结束。
        click_mock.assert_any_call(confirm, after_sleep=10)  # 点结算返回键。
        close_mock.assert_called_once_with(to_screen='event_challenge_page')
        back_mock.assert_called_once()

    def test_flow_challenge_both_disabled_closes_detail_and_returns(self):
        # 快速战斗与普通战斗都不可用 = 今日已挑战无次数：关详情页回挑战页，再点返回回菜单。
        entry, stage = self._challenge_entry(), self._challenge_stage()
        quick, battle = self._challenge_quick_box(), self._challenge_battle_box()
        click = self._challenge_stage_click(stage)
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_wait_challenge_nodes'), \
                patch.object(self.task, '_find_available_challenge_stage', return_value=stage), \
                patch.object(self.task, '_challenge_click_box', return_value=click), \
                patch.object(self.task, 'wait_feature', return_value=True), \
                patch.object(self.task, '_optional_box', side_effect=lambda name: {'box_stage_detail_quick_battle': quick,
                                                                                    'box_stage_detail_battle': battle}.get(name)), \
                patch.object(self.task, 'is_feature_enabled', return_value=False), \
                patch.object(self.task, '_run_quick_battle', side_effect=AssertionError('都灰白不应走战斗')), \
                patch.object(self.task, 'wait_battle_finish', side_effect=AssertionError('都灰白不应进战斗')), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_close_stage_detail') as close_mock, \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_challenge()
        click_mock.assert_any_call(click, after_sleep=2)  # 仍点了左移后的关卡点击框进详情页。
        close_mock.assert_called_once_with(to_screen='event_challenge_page')  # 关详情页回挑战页。
        back_mock.assert_called_once()  # 回菜单。

    def test_flow_challenge_retries_stage_click_then_enters_detail(self):
        # 首次点击没打开详情页（点空）：补点一次，第二次进入详情页后照常走战斗分支。
        from src.tasks.EventTask import _CHALLENGE_CLICK_ATTEMPTS
        entry, stage = self._challenge_entry(), self._challenge_stage()
        quick, click = self._challenge_quick_box(), self._challenge_stage_click(stage)
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_wait_challenge_nodes'), \
                patch.object(self.task, '_find_available_challenge_stage', return_value=stage), \
                patch.object(self.task, '_challenge_click_box', return_value=click) as offset_mock, \
                patch.object(self.task, 'is_screen', return_value=True) as screen_mock, \
                patch.object(self.task, 'wait_feature', side_effect=[False, True]) as wait_mock, \
                patch.object(self.task, '_optional_box', return_value=quick), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, '_run_quick_battle') as quick_mock, \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_close_stage_detail'), \
                patch.object(self.task, 'log_warning') as warn_mock, \
                patch.object(self.task, '_ensure_event_menu'):
            self.task._flow_challenge()
        self.assertEqual(_CHALLENGE_CLICK_ATTEMPTS, click_mock.call_count)  # 失败后重试一次。
        self.assertEqual(_CHALLENGE_CLICK_ATTEMPTS, offset_mock.call_count)  # 每次点击都重新取随机偏移。
        self.assertEqual(2, wait_mock.call_count)  # 每次点击后各等一次详情页。
        screen_mock.assert_any_call('event_challenge_page')  # 失败时记「是否仍在挑战页」便于定位原因。
        warn_mock.assert_not_called()  # 第二次进入详情页，不算失败。
        quick_mock.assert_called_once()  # 进详情页后照常走后续分支。

    def test_flow_challenge_stage_click_lands_not_on_detail(self):
        # 两次点击都没进详情页（异常落点）：告警 + 兜底回菜单，不做任何战斗。
        from src.tasks.EventTask import _CHALLENGE_CLICK_ATTEMPTS
        entry, stage = self._challenge_entry(), self._challenge_stage()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_wait_challenge_nodes'), \
                patch.object(self.task, '_find_available_challenge_stage', return_value=stage), \
                patch.object(self.task, 'wait_feature', return_value=False) as wait_mock, \
                patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, 'log_warning') as warn_mock, \
                patch.object(self.task, '_run_quick_battle', side_effect=AssertionError('未进详情页不应战斗')), \
                patch.object(self.task, '_detail_page_open', side_effect=AssertionError('未进详情页不应判详情页')), \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_challenge()
        self.assertEqual(_CHALLENGE_CLICK_ATTEMPTS, click_mock.call_count)  # 两次都点空。
        self.assertEqual(_CHALLENGE_CLICK_ATTEMPTS, wait_mock.call_count)  # 两次都等满窗口。
        warn_mock.assert_called_once()  # 用尽尝试次数才告警。
        back_mock.assert_called_once()  # 兜底回菜单页。

    def test_find_available_challenge_stage_picks_bottom_most_enabled(self):
        # 自下而上找第一个可用：最低的关卡灰白，取次低的可用关卡。
        low = self._challenge_stage(y=985)
        high = self._challenge_stage(y=700)
        list_box = Box(1580, 509, 66, 788, confidence=1, name='box_event_challenge_stage_list')
        with patch.object(self.task, '_optional_box', return_value=list_box), \
                patch.object(self.task, 'find_feature', return_value=[high, low]) as feature_mock, \
                patch.object(self.task, 'is_feature_enabled', side_effect=lambda box: box is high):
            found = self.task._find_available_challenge_stage()
        self.assertEqual(high, found)  # 最低的灰白被跳过，取次低可用。
        feature_mock.assert_called_once_with('event_challenge_stage', box=list_box, limit=0, use_gray_scale=True)  # 灰度定位、色彩判态分离。

    def test_find_available_challenge_stage_none_when_all_disabled(self):
        stages = [self._challenge_stage(y=985), self._challenge_stage(y=700)]
        list_box = Box(1580, 509, 66, 788, confidence=1, name='box_event_challenge_stage_list')
        with patch.object(self.task, '_optional_box', return_value=list_box), \
                patch.object(self.task, 'find_feature', return_value=stages), \
                patch.object(self.task, 'is_feature_enabled', return_value=False):
            self.assertIsNone(self.task._find_available_challenge_stage())

    def test_find_available_challenge_stage_none_when_region_missing(self):
        with patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'find_feature', side_effect=AssertionError('区域缺失不应匹配')):
            self.assertIsNone(self.task._find_available_challenge_stage())

    def test_find_available_challenge_stage_none_when_feature_missing(self):
        list_box = Box(1580, 509, 66, 788, confidence=1, name='box_event_challenge_stage_list')
        with patch.object(self.task, '_optional_box', return_value=list_box), \
                patch.object(self.task, 'find_feature', side_effect=ValueError('missing')):
            self.assertIsNone(self.task._find_available_challenge_stage())

    def test_challenge_click_box_shifts_left_by_random_offset_in_range(self):
        # 标记贴行右边缘：点击框沿 X 轴左移区间内的随机偏移，落回行主体；尺寸/置信度/名称不变。
        from src.tasks.EventTask import _CHALLENGE_CLICK_X_OFFSET
        stage = self._challenge_stage()
        with patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=2560), \
                patch('src.tasks.EventTask.random.randint', return_value=250) as randint_mock:
            click = self.task._challenge_click_box(stage)
        self.assertEqual((int(2560 * _CHALLENGE_CLICK_X_OFFSET[0]), int(2560 * _CHALLENGE_CLICK_X_OFFSET[1])),
                         randint_mock.call_args.args)  # 左移量在区间内随机取（占屏宽比例换算成像素）。
        self.assertEqual(Box(stage.x - 250, stage.y, stage.width, stage.height, confidence=1,
                             name='event_challenge_stage'), click)

    def test_challenge_click_box_offset_degrades_when_screen_too_narrow(self):
        # 分辨率极小时区间换算成同一像素：退化为定值，不抛异常。
        stage = self._challenge_stage()
        with patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=8), \
                patch('src.tasks.EventTask.random.randint', side_effect=AssertionError('区间退化不应取随机')):
            click = self.task._challenge_click_box(stage)
        self.assertEqual(Box(stage.x, stage.y, stage.width, stage.height, confidence=1,
                             name='event_challenge_stage'), click)  # 左移量为 0。

    def test_wait_challenge_nodes_polls_until_rendered(self):
        # 过场动画吸收：等关卡节点渲染出来再多等一会才继续（区域 + 特征名 + 到达窗口 + 停稳窗口都传给轮询）。
        from src.tasks.EventTask import _CHALLENGE_PAGE_SETTLE, _CHALLENGE_STAGE_FEATURE, _SD_ARRIVE_TIMEOUT
        list_box = Box(1580, 509, 66, 788, confidence=1, name='box_event_challenge_stage_list')
        node = self._challenge_stage()

        def run_condition(condition, time_out=None, settle_time=0, **kwargs):
            return condition()  # 单测驱动：执行一次条件判断。

        with patch.object(self.task, '_optional_box', return_value=list_box), \
                patch.object(self.task, 'find_feature', return_value=[node]) as feature_mock, \
                patch.object(self.task, 'wait_until', side_effect=run_condition) as wait_mock, \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._wait_challenge_nodes()
        feature_mock.assert_called_once_with(_CHALLENGE_STAGE_FEATURE, box=list_box, limit=0, use_gray_scale=True)  # 灰度找挑战关卡标记。
        self.assertEqual(_SD_ARRIVE_TIMEOUT, wait_mock.call_args.kwargs['time_out'])  # 用共享到达窗口。
        self.assertEqual(_CHALLENGE_PAGE_SETTLE, wait_mock.call_args.kwargs['settle_time'])  # 命中后再多等一会（行卡片入场动画）。
        warn_mock.assert_not_called()  # 已渲染不再告警。

    def test_wait_challenge_nodes_skips_without_region(self):
        with patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'wait_until', side_effect=AssertionError('区域缺失不应等待')), \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._wait_challenge_nodes()
        warn_mock.assert_not_called()  # 区域缺失不告警，由 _find_available_challenge_stage 记日志。

    def test_wait_challenge_nodes_logs_when_feature_missing(self):
        list_box = Box(1580, 509, 66, 788, confidence=1, name='box_event_challenge_stage_list')

        def run_condition(condition, time_out=None, settle_time=0, **kwargs):
            self.assertRaises(ValueError, condition)  # 特征缺失时条件抛 ValueError，不向外扩散。
            return False

        with patch.object(self.task, '_optional_box', return_value=list_box), \
                patch.object(self.task, 'find_feature', side_effect=ValueError('missing')), \
                patch.object(self.task, 'wait_until', side_effect=run_condition), \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._wait_challenge_nodes()
        warn_mock.assert_called_once()  # 特征缺失记一次告警。

    def test_run_quick_battle_pulls_max_and_confirms(self):
        # 快速战斗链：点按钮 → 等次数弹窗 → 拉满 → 开始 → 等结算 → 点结算确认。
        from src.tasks.EventTask import _SWEEP_PAGE_FEATURE, _SWEEP_START_BOX
        quick = self._challenge_quick_box()
        max_btn = Box(1424, 991, 75, 44, confidence=1, name='custom_quick_battle_max')
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature') as wait_mock, \
                patch.object(self.task, 'find_one', return_value=max_btn), \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)):
            result = self.task._run_quick_battle(quick, label='挑战')
        self.assertEqual('success', result)
        click_mock.assert_any_call(quick, after_sleep=1)  # 点快速战斗。
        click_mock.assert_any_call(max_btn, after_sleep=1)  # 拉满次数。
        click_mock.assert_any_call(_SWEEP_START_BOX, after_sleep=1)  # 点开始。
        click_mock.assert_any_call(confirm, after_sleep=2)  # 点结算确认。
        self.assertEqual(_SWEEP_PAGE_FEATURE, wait_mock.call_args.args[0])  # 等次数弹窗就位。

    def test_run_quick_battle_timeout_raises(self):
        quick = self._challenge_quick_box()
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_feature'), \
                patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, 'wait_battle_finish', return_value=(None, None)):
            self.assertRaises(WaitFailedException, self.task._run_quick_battle, quick)

    def test_close_stage_detail_asserts_target_screen(self):
        # _close_stage_detail 可指定回退目标页（挑战回挑战页，剧情/扫荡默认回关卡页）。
        with patch.object(self.task, 'wait_click_feature') as click_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._close_stage_detail(to_screen='event_challenge_page')
        click_mock.assert_called_once_with('stage_detail_close', raise_if_not_found=True, after_sleep=1)
        assert_mock.assert_called_once_with('event_challenge_page', time_out=15)

    def test_probe_event_context_includes_challenge_page(self):
        # 挑战页也算「在活动内」：失败恢复回大厅后的重入据此走 _ensure_event_menu 而非绕道大厅。
        def fake_is_screen(name):
            return name == 'event_challenge_page'
        with patch.object(self.task, 'is_screen', side_effect=fake_is_screen), \
                patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, '_detail_page_open', return_value=False):
            self.assertTrue(self.task._probe_event_context())

    def test_probe_entry_uses_menu_band_and_keywords(self):
        menu = Box(0, 0, 100, 50, confidence=1, name='menu')
        hit = Box(10, 10, 30, 10, confidence=1, name='签到印章')
        with patch.object(self.task, 'get_box_by_name', return_value=menu), \
                patch.object(self.task, 'ocr', return_value=[hit]):
            self.assertTrue(self.task._probe_entry('签到'))
        with patch.object(self.task, 'get_box_by_name', return_value=menu), \
                patch.object(self.task, 'ocr', return_value=[]):
            self.assertFalse(self.task._probe_entry('签到'))

    def test_probe_entry_missing_region_returns_false(self):
        with patch.object(self.task, 'get_box_by_name', side_effect=ValueError('missing')):
            self.assertFalse(self.task._probe_entry('挑战'))

    def test_probe_entry_scans_multiple_menu_bands(self):
        from src.tasks.EventTask import _MENU_BAND_BOXES
        band1, band2 = _MENU_BAND_BOXES[0], _MENU_BAND_BOXES[1]
        box1 = Box(0, 0, 100, 50, confidence=1, name=band1)
        box2 = Box(0, 200, 100, 50, confidence=1, name=band2)
        hit = Box(10, 210, 30, 10, confidence=1, name='挑战')

        def get_box(name):
            return {band1: box1, band2: box2}.get(name)

        def ocr(box, match=None):
            return [hit] if box is box2 else []

        with patch.object(self.task, 'get_box_by_name', side_effect=get_box), \
                patch.object(self.task, 'ocr', side_effect=ocr):
            self.assertTrue(self.task._probe_entry('挑战'))  # 第一区域未命中、第二区域命中。

    def test_wait_menu_ready_returns_when_hit(self):
        menu = Box(0, 0, 100, 50, confidence=1, name='menu')
        hit = Box(10, 10, 30, 10, confidence=1, name='加成')
        captured = {}

        def fake_wait_until(condition, time_out=0, pre_action=None, post_action=None,
                            settle_time=-1, raise_if_not_found=False):
            captured['time_out'] = time_out
            captured['settle_time'] = settle_time
            return condition()  # 真实执行一次条件，验证命中逻辑。

        with patch.object(self.task, 'wait_until', side_effect=fake_wait_until), \
                patch.object(self.task, '_menu_boxes', return_value=[menu]), \
                patch.object(self.task, 'ocr', return_value=[hit]):
            self.task._wait_menu_ready()
        self.assertEqual(6, captured['time_out'])  # 默认菜单渲染等待窗口。
        self.assertEqual(1.5, captured['settle_time'])  # 命中后稳定 1.5s 吸收动画过渡期。

    def test_wait_menu_ready_continues_on_timeout(self):
        with patch.object(self.task, 'wait_until', return_value=False), \
                patch.object(self.task, '_menu_boxes', return_value=[]), \
                patch.object(self.task, 'ocr', side_effect=AssertionError('超时不应 OCR')):
            self.task._wait_menu_ready()  # 超时仅记录告警，不抛异常、由探测器各自跳过。

    def test_region_changed(self):
        a = np.zeros((10, 10, 3), dtype=np.uint8)
        b = np.full((10, 10, 3), 255, dtype=np.uint8)
        self.assertTrue(self.task._region_changed(a, b))  # 画面显著不同。
        self.assertFalse(self.task._region_changed(a, a.copy()))  # 画面相同。
        self.assertTrue(self.task._region_changed(None, b))  # 无有效帧保守视为变化。

    def test_scroll_list_down_stops_at_bottom(self):
        box = Box(0, 0, 100, 200, confidence=1, name='list')
        a = np.zeros((20, 20, 3), dtype=np.uint8)
        b = np.full((20, 20, 3), 255, dtype=np.uint8)
        with patch.object(self.task, '_list_area_box', return_value=box), \
                patch.object(self.task, '_list_area_frame', side_effect=[a, a, a]), \
                patch.object(self.task, '_swipe_list_up') as swipe_mock:
            self.assertFalse(self.task._scroll_list_down(2))  # 滚动前后画面无变化 = 到底。
        swipe_mock.assert_called_once()  # 第一次滑动后即判到底，不再继续。

    def test_scroll_list_down_completes_steps(self):
        box = Box(0, 0, 100, 200, confidence=1, name='list')
        a = np.zeros((20, 20, 3), dtype=np.uint8)
        b = np.full((20, 20, 3), 255, dtype=np.uint8)
        with patch.object(self.task, '_list_area_box', return_value=box), \
                patch.object(self.task, '_list_area_frame',
                             side_effect=[a, b, a, b]), \
                patch.object(self.task, '_swipe_list_up') as swipe_mock:
            self.assertTrue(self.task._scroll_list_down(3))  # 每步都有变化，完整下滚 3 步。
        self.assertEqual(3, swipe_mock.call_count)

    def test_scroll_list_down_zero_steps_no_scroll(self):
        with patch.object(self.task, '_list_area_box', side_effect=AssertionError('零步不应取区域')), \
                patch.object(self.task, '_swipe_list_up', side_effect=AssertionError('零步不应滑动')):
            self.assertTrue(self.task._scroll_list_down(0))

    def test_scroll_list_to_top_stops_when_unchanged(self):
        box = Box(0, 0, 100, 200, confidence=1, name='list')
        a = np.zeros((20, 20, 3), dtype=np.uint8)
        with patch.object(self.task, '_list_area_box', return_value=box), \
                patch.object(self.task, '_list_area_frame',
                             side_effect=[a, a, a, a]), \
                patch.object(self.task, '_swipe_list_down') as swipe_mock:
            self.task._scroll_list_to_top()
        swipe_mock.assert_called_once()  # 第一次下滑后画面无变化即到顶，不再继续。

    # ---- 剧情关卡页：OCR 接线与行锚点切片（方案 §5/§11 ③） ----

    def test_ocr_blocks_maps_framework_boxes(self):
        listed = Box(100, 200, 30, 40, confidence=0.93, name='1-06')
        with patch.object(self.task, 'ocr', return_value=[listed]):
            blocks = self.task._ocr_blocks(Box(0, 0, 100, 100, confidence=1, name='list'))
        self.assertEqual(1, len(blocks))  # 框架 Box -> 解析层 Block。
        self.assertEqual('1-06', blocks[0].text)
        self.assertEqual(0.93, blocks[0].score)
        self.assertEqual((100, 200, 130, 240), (blocks[0].x1, blocks[0].y1, blocks[0].x2, blocks[0].y2))

    def test_ocr_blocks_drops_empty_text(self):
        empty = Box(1, 1, 2, 2, confidence=0.9, name='')
        with patch.object(self.task, 'ocr', return_value=[empty]):
            self.assertEqual([], self.task._ocr_blocks(Box(0, 0, 10, 10, confidence=1, name='list')))

    def test_stage_list_box_missing_returns_none(self):
        with patch.object(self.task, 'get_box_by_name', side_effect=ValueError('missing')):
            self.assertIsNone(self.task._stage_list_box())

    def test_stage_blocks_skip_slice_when_numbers_sufficient(self):
        # 编号块数与锚点数齐平（7 个编号、0 个锚点）：不触发降级，OCR 只调用一次列表区。
        numbers = [Box(1200, 400 + index * 120, 60, 40, confidence=0.9, name=f'EVENT V1-0{index + 1}')
                   for index in range(7)]
        with patch.object(self.task, 'ocr', side_effect=[numbers]) as ocr_mock:
            blocks = self.task._stage_blocks(Box(950, 342, 729, 867, confidence=1, name='list'))
        self.assertEqual(7, len(blocks))
        self.assertEqual(1, ocr_mock.call_count)

    def test_stage_blocks_slice_when_anchors_exceed_numbers(self):
        # 低对比页：裁剪层只读到 1 个编号 + 3 个锚点残片，每条窄带补扫一次。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        listed = [Box(1200, 1100, 60, 40, confidence=0.9, name='1-12'),
                  Box(1200, 400, 30, 20, confidence=0.83, name='eni'),
                  Box(1200, 520, 30, 20, confidence=0.86, name='eni'),
                  Box(1200, 640, 40, 20, confidence=0.93, name='vent')]
        sliced = Box(1200, 580, 60, 40, confidence=0.92, name='EVENT V1-04')
        with patch.object(self.task, 'ocr', side_effect=[listed, [sliced], [], []]) as ocr_mock:
            blocks = self.task._stage_blocks(list_box)
        self.assertEqual(4, ocr_mock.call_count)  # 1 次列表区 + 3 条锚点窄带。
        for call in ocr_mock.call_args_list[1:]:  # 窄带必须落在列表区内。
            band = call.kwargs['box']
            self.assertGreaterEqual(band.x, list_box.x)
            self.assertLessEqual(band.x + band.width, list_box.x + list_box.width)
        self.assertIn('EVENT V1-04', [block.text for block in blocks])  # 切片结果并入解析输入。

    def test_stage_blocks_uniform_slice_without_anchors_or_numbers(self):
        # 无 EVENT 家族的页面 + 编号也没读到：按标定行距均匀切片兜底，切片结果并入解析输入。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        locked = [Box(1200, 400, 300, 30, confidence=0.9, name='Access Denied'),
                  Box(1200, 520, 300, 30, confidence=0.9, name='Access Denied')]
        sliced = Box(1200, 360, 60, 40, confidence=0.92, name='EVENT V1-04')
        with patch.object(self.task, 'ocr', side_effect=[locked, [sliced]] + [[]] * 9) as ocr_mock:
            blocks = self.task._stage_blocks(list_box)
        self.assertGreater(ocr_mock.call_count, 1)  # 触发降级切片。
        for call in ocr_mock.call_args_list[1:]:  # 均匀窄带：整列表宽 × 一个标定行距，且落在列表区内。
            band = call.kwargs['box']
            self.assertEqual(list_box.x, band.x)
            self.assertEqual(list_box.width, band.width)
            self.assertEqual(int(event_stage.row_pitch_fallback(self.task._stage_scale())), band.height)
            self.assertGreaterEqual(band.y, list_box.y)
            self.assertLess(band.y, list_box.y + list_box.height)
        self.assertIn('EVENT V1-04', [block.text for block in blocks])  # 切片结果并入解析输入。

    def test_anchor_bands_extrapolate_missing_row(self):
        # 相邻锚点间隔约两倍行距：中间那行漏检，按中点外推补一条窄带。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        anchors = [event_stage.Block(text='eni', score=0.9, x1=1200, y1=400, x2=1230, y2=420),
                   event_stage.Block(text='eni', score=0.9, x1=1200, y1=520, x2=1230, y2=540),
                   event_stage.Block(text='vent', score=0.9, x1=1200, y1=760, x2=1240, y2=780)]
        with _fixed_height(self.task):
            bands = self.task._anchor_bands(anchors, list_box)
        centers = [band.y + band.height / 2 for band in bands]
        self.assertEqual(4, len(bands))  # 3 个锚点 + 外推 1 行。
        self.assertIn(650, centers)  # 410/530 之间的行距为 120；530 与 770 之间按中点 650 外推。

    def test_dedup_blocks_keeps_highest_score_per_row(self):
        # 同一元素被两层 OCR 各读一次：同类别且纵向邻近时只留置信度高的一块。
        blocks = [event_stage.Block(text='1-06', score=0.70, x1=1200, y1=400, x2=1300, y2=440),
                  event_stage.Block(text='EVENT V1O6', score=0.96, x1=1200, y1=405, x2=1300, y2=445),
                  event_stage.Block(text='CLEAR', score=0.80, x1=1200, y1=500, x2=1300, y2=540),
                  event_stage.Block(text='CLEAR', score=0.91, x1=1200, y1=498, x2=1300, y2=538)]
        with _fixed_height(self.task):
            kept = self.task._dedup_blocks(blocks)
        self.assertEqual([0.96, 0.91], sorted((block.score for block in kept), reverse=True))

    def test_stage_rows_parses_list_region(self):
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        listed = [Box(1200, 400, 60, 40, confidence=0.9, name='1-06'),
                  Box(1200, 483, 80, 30, confidence=0.9, name='CLEAR'),  # 编号下方约 0.65 行距 = 本行状态。
                  Box(1200, 520, 60, 40, confidence=0.9, name='1-07')]
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(self.task, 'ocr', return_value=listed):
            rows = self.task._stage_rows()
        self.assertEqual(['1-06', '1-07'], [row.stage_id for row in rows])
        self.assertEqual(['clear', 'available'], [row.status for row in rows])  # CLEAR 归给上方编号行。

    def test_stage_rows_repairs_sequence_gap(self):
        # 编号序列缺口（1-07 → 1-09）时按推断位置补扫缺失行窄带，再解析出 1-08。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        listed = [event_stage.Block(text='1-06', score=0.95, x1=1200, y1=400, x2=1260, y2=440),
                  event_stage.Block(text='1-07', score=0.95, x1=1200, y1=520, x2=1260, y2=560),
                  event_stage.Block(text='1-09', score=0.95, x1=1200, y1=760, x2=1260, y2=800)]
        repaired = event_stage.Block(text='1-08', score=0.9, x1=1200, y1=640, x2=1260, y2=680)
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(self.task, '_stage_blocks', return_value=listed), \
                patch.object(self.task, '_ocr_blocks', return_value=[repaired]) as ocr_mock:
            rows = self.task._stage_rows()
        self.assertEqual(['1-06', '1-07', '1-08', '1-09'], [row.stage_id for row in rows])
        self.assertEqual(1, ocr_mock.call_count)  # 只补扫缺口那一行。
        band = ocr_mock.call_args.args[0]
        self.assertLess(band.y, 660)  # 窄带以缺口中心 660 为中线。
        self.assertGreater(band.y + band.height, 660)

    def test_stage_rows_skips_repair_when_continuous(self):
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        listed = [event_stage.Block(text='1-06', score=0.95, x1=1200, y1=400, x2=1260, y2=440),
                  event_stage.Block(text='1-07', score=0.95, x1=1200, y1=520, x2=1260, y2=560)]
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(self.task, '_stage_blocks', return_value=listed), \
                patch.object(self.task, '_ocr_blocks', side_effect=AssertionError('编号连续不应补扫')):
            rows = self.task._stage_rows()
        self.assertEqual(['1-06', '1-07'], [row.stage_id for row in rows])

    def test_stage_rows_returns_empty_without_region(self):
        with patch.object(self.task, '_stage_list_box', return_value=None), \
                patch.object(self.task, 'ocr', side_effect=AssertionError('区域缺失不应 OCR')):
            self.assertEqual([], self.task._stage_rows())

    def test_stage_row_pitch_fallback_scales_with_resolution(self):
        # 兜底行距随分辨率缩放（不是固定像素）：1920x1080 下取 2560x1440 标定值的 0.75 倍。
        with _fixed_height(self.task, 1080), \
                patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=1920):
            self.assertAlmostEqual(event_stage.ROW_PITCH_AT_REF * 0.75, self.task._stage_row_pitch([]))

    def test_stage_rows_passes_resolution_scale(self):
        # 解析层兜底行距按分辨率缩放：调用层把当前缩放比透传给 parse。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(self.task, 'ocr', return_value=[]), \
                patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=1920), \
                patch.object(type(self.task), 'height', new_callable=PropertyMock, return_value=1080), \
                patch.object(event_stage, 'parse', return_value=[]) as parse_mock:
            self.task._stage_rows()
        self.assertAlmostEqual(0.75, parse_mock.call_args.kwargs['scale'])

    def _stage_row(self, stage_id, status='available'):
        """构造一行解析结果（跨屏拼接测试用）。"""
        return event_stage.StageRef(stage_id=stage_id, box=(950, 400, 1679, 520), status=status, source='number')

    def test_swipe_list_up_uses_stage_start_ratio(self):
        # 关卡列表的滚动手势起点在区域内垂直 2/3 处（终点仍在 0.2 处）。
        from src.tasks.EventTask import _STAGE_SWIPE_START_RATIO
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, 'swipe') as swipe_mock:
            self.task._swipe_list_up(box, _STAGE_SWIPE_START_RATIO)
        x1, y1, x2, y2 = swipe_mock.call_args.args
        self.assertEqual(box.x + box.width // 2, x1)
        self.assertEqual(int(box.y + box.height * 2 / 3), int(y1))  # 起点 = 区域内垂直 2/3。
        self.assertLess(y2, y1)  # 自下往上滑。

    def test_scroll_list_passes_area_and_start_ratio(self):
        from src.tasks.EventTask import _STAGE_LIST_BOX, _STAGE_SWIPE_START_RATIO
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        a = np.zeros((20, 20, 3), dtype=np.uint8)
        b = np.full((20, 20, 3), 255, dtype=np.uint8)
        with patch.object(self.task, '_list_area_box', return_value=box) as area_mock, \
                patch.object(self.task, '_list_area_frame', side_effect=[a, b]), \
                patch.object(self.task, '_scroll_list_to_top') as top_mock, \
                patch.object(self.task, '_swipe_list_up') as swipe_mock:
            self.task._scroll_list_to_top(box_name=_STAGE_LIST_BOX, start_ratio=_STAGE_SWIPE_START_RATIO)
            self.assertTrue(self.task._scroll_list_down(1, box_name=_STAGE_LIST_BOX,
                                                        start_ratio=_STAGE_SWIPE_START_RATIO))
        self.assertEqual(_STAGE_LIST_BOX, area_mock.call_args.args[0])  # 区域名透传到取框。
        top_mock.assert_called_once_with(box_name=_STAGE_LIST_BOX, start_ratio=_STAGE_SWIPE_START_RATIO)
        self.assertEqual(_STAGE_SWIPE_START_RATIO, swipe_mock.call_args.args[1])  # 起点比例透传到手势。

    def test_scan_stage_rows_stitches_screens(self):
        # 跨屏扫描：每屏解析后按编号去重拼接，列表顺序即发现顺序。
        from src.tasks.EventTask import _STAGE_LIST_BOX, _STAGE_SWIPE_START_RATIO
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        screens = [[self._stage_row('1-01'), self._stage_row('1-02')],
                   [self._stage_row('1-02'), self._stage_row('1-03')],
                   [self._stage_row('1-03')]]
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', side_effect=screens), \
                patch.object(self.task, '_scroll_list_to_top') as top_mock, \
                patch.object(self.task, '_scroll_list_down', side_effect=[True, True, False]) as down_mock:
            rows = self.task._scan_stage_rows()
        self.assertEqual(['1-01', '1-02', '1-03'], [row.stage_id for row in rows])
        top_mock.assert_called_once_with(box_name=_STAGE_LIST_BOX, start_ratio=_STAGE_SWIPE_START_RATIO)
        self.assertEqual(3, down_mock.call_count)  # 到底返回 False 后结束扫描。

    def test_scan_stage_rows_stops_when_screen_unchanged(self):
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', side_effect=[[self._stage_row('1-01')]] * 2), \
                patch.object(self.task, '_scroll_list_to_top'), \
                patch.object(self.task, '_scroll_list_down', return_value=True) as down_mock:
            rows = self.task._scan_stage_rows()
        self.assertEqual(['1-01'], [row.stage_id for row in rows])
        self.assertEqual(1, down_mock.call_count)  # 第二屏编号序列与首屏相同 = 到底，不再继续滚。

    def test_scan_stage_rows_returns_empty_without_region(self):
        with patch.object(self.task, '_stage_list_box', return_value=None), \
                patch.object(self.task, '_scroll_list_to_top', side_effect=AssertionError('区域缺失不应滚动')):
            self.assertEqual([], self.task._scan_stage_rows())

    # ---- 剧情入口定位与执行链（方案 §8 ④：点行 → 剧情跳过 → 连续战斗 → 回关卡页） ----

    def _story_row(self, stage_id='1-05', status='available'):
        """构造一行解析结果（剧情推图链测试用）。"""
        return event_stage.StageRef(stage_id=stage_id, box=(950, 400, 1679, 520), status=status,
                                    source=event_stage.SOURCE_NUMBER)

    def test_entry_box_prefers_keyword_order(self):
        # 关键词列表顺序即优先级：STORY II 命中时不再回退 STORY I。
        menu = Box(0, 0, 100, 50, confidence=1, name='band')
        hits = [Box(10, 10, 30, 10, confidence=1, name='STORY I'),
                Box(60, 10, 30, 10, confidence=1, name='STORY II')]
        with patch.object(self.task, '_menu_boxes', return_value=[menu]), \
                patch.object(self.task, 'ocr', return_value=hits):
            found = self.task._entry_box('剧情')
        self.assertEqual('STORY II', found.name)

    def test_entry_box_returns_none_without_menu_band(self):
        with patch.object(self.task, '_menu_boxes', return_value=[]), \
                patch.object(self.task, 'ocr', side_effect=AssertionError('无菜单带不应 OCR')):
            self.assertIsNone(self.task._entry_box('剧情'))

    def test_entry_box_shifts_small_event_story_click_up(self):
        # 小活动剧情入口「加成奖励妮姬」：命中文字在按钮下缘，点击框沿 Y 轴上移 0.06 屏高。
        menu = Box(0, 0, 100, 50, confidence=1, name='band')
        hit = Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')
        with patch.object(self.task, '_menu_boxes', return_value=[menu]), \
                patch.object(self.task, 'ocr', return_value=[hit]), \
                _fixed_height(self.task, 1000):
            found = self.task._entry_box('剧情')
        self.assertEqual(700 - 60, found.y)  # 上移 0.06 × 1000 = 60px。
        self.assertEqual((60, 30, 20), (found.x, found.width, found.height))  # 水平与尺寸不变。
        self.assertEqual(700, hit.y)  # 原命中框不被就地改写（同帧 OCR 结果被多处复用）。

    def test_entry_box_shifts_mission_click_up_for_extra_region(self):
        # 大活动专属区命中：文字在图标下方，点击框沿 Y 轴上移 0.033 屏高落到图标上。
        region = Box(2418, 248, 141, 142, confidence=1, name='box_event_menu_mission')
        hit = Box(2474, 700, 52, 33, confidence=1, name='任务')
        with patch.object(self.task, '_optional_box', return_value=region), \
                patch.object(self.task, '_menu_boxes', return_value=[]), \
                patch.object(self.task, 'ocr', return_value=[hit]), \
                _fixed_height(self.task, 1000):
            found = self.task._entry_box('任务')
        self.assertEqual(700 - 33, found.y)  # 上移 0.033 × 1000 = 33px。
        self.assertEqual((2474, 52, 33), (found.x, found.width, found.height))  # 水平与尺寸不变。
        self.assertEqual(700, hit.y)  # 原命中框不被就地改写（同帧 OCR 结果被多处复用）。

    def test_entry_box_keeps_small_event_mission_click_box(self):
        # 小活动同名入口在菜单带里、文字就在按钮上：点文字本身，不跟着专属区偏移。
        menu = Box(0, 0, 100, 50, confidence=1, name='band')
        hit = Box(60, 700, 30, 20, confidence=1, name='任务')
        with patch.object(self.task, '_menu_boxes', return_value=[menu]), \
                patch.object(self.task, 'ocr', return_value=[hit]), \
                _fixed_height(self.task, 1000):
            found = self.task._entry_box('任务')
        self.assertIs(hit, found)  # 菜单带命中不做任何修正。

    def test_entry_box_keeps_story_entry_click_box(self):
        # STORY II/I 命中框即点击框：无 Y 轴偏移。
        menu = Box(0, 0, 100, 50, confidence=1, name='band')
        hit = Box(60, 700, 30, 20, confidence=1, name='STORY II')
        with patch.object(self.task, '_menu_boxes', return_value=[menu]), \
                patch.object(self.task, 'ocr', return_value=[hit]), \
                _fixed_height(self.task, 1000):
            found = self.task._entry_box('剧情')
        self.assertEqual(700, found.y)  # 无偏移，命中框直接作为点击框。

    def test_flow_story_big_event_enters_sub_page_then_stage_page(self):
        # 大活动：STORY I/II 点开后先进剧情子页面（标题同为「剧情活动」、无活动菜单），再由子页面入口进关卡页。
        target = self._story_row('1-05')
        story = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        sub_entry = Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')
        with patch.object(self.task, '_nav_to_event_main') as nav_mock, \
                patch.object(self.task, '_entry_box', side_effect=[story, sub_entry]) as entry_mock, \
                patch.object(self.task, '_enter_story_sub_page') as sub_page_mock, \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, '_progress_target', return_value=target), \
                patch.object(self.task, '_push_stages') as push_mock, \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_story()
        nav_mock.assert_called_once()  # 子流程闸门：就位活动主页（恢复回大厅后由此重入）。
        sub_page_mock.assert_called_once()  # 先在菜单页内逐个尝试 STORY 入口并等剧情子页面就位。
        self.assertEqual(2, entry_mock.call_count)  # 子页面内重新定位剧情入口。
        self.assertEqual(['event_stage_page'],
                         [call.args[0] for call in transition_mock.call_args_list])  # 从剧情子页面入口进关卡页。
        self.assertEqual(sub_entry, transition_mock.call_args_list[0].kwargs['box'])  # 用子页面入口命中框点击。
        push_mock.assert_called_once_with(target)  # 推图目标透传。
        back_mock.assert_called_once()  # 收尾回活动菜单页（大活动由它多退一级）。

    def test_flow_story_small_event_enters_stage_page_directly(self):
        # 小活动：主页「加成」入口就是关卡页入口，不进剧情子页面。
        entry = Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry) as entry_mock, \
                patch.object(self.task, '_enter_story_sub_page', side_effect=AssertionError('小活动不应进子页面')), \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, '_progress_target', return_value=self._story_row('1-05')), \
                patch.object(self.task, '_push_stages'), \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_story()
        entry_mock.assert_called_once()  # 只定位一次入口。
        self.assertEqual(entry, transition_mock.call_args_list[0].kwargs['box'])  # 直接用该入口进关卡页。
        back_mock.assert_called_once()  # 收尾回活动菜单页。

    def test_flow_story_without_target_only_returns_to_event_main(self):
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')), \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, '_progress_target', return_value=None), \
                patch.object(self.task, '_push_stages', side_effect=AssertionError('无目标不应推图')), \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_story()
        self.assertEqual(['event_stage_page'],
                         [call.args[0] for call in transition_mock.call_args_list])  # 仍要走关卡页。
        back_mock.assert_called_once()  # 无目标也要回菜单页。

    def test_try_enter_story_sub_page_clicks_and_waits_for_entry(self):
        # 剧情子页面无独有界面判据 → 点 STORY 入口后轮询等「加成」类入口出现（反向判就位）。
        from src.tasks.EventTask import _SD_ARRIVE_TIMEOUT
        story = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=True) as wait_mock:
            ready = self.task._try_enter_story_sub_page(story)
        self.assertTrue(ready)  # 子页面就位即成功。
        click_mock.assert_called_once_with(story, after_sleep=2)  # 只点一次（切页不需补点）。
        self.assertEqual(_SD_ARRIVE_TIMEOUT, wait_mock.call_args.kwargs['time_out'])  # 用子页面到达窗口。

    def test_try_enter_story_sub_page_returns_false_when_not_ready(self):
        # 未开放的章节点开不切页：只返回 False（不抛异常），由调用方回落下一个入口。
        story = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=False):
            self.assertFalse(self.task._try_enter_story_sub_page(story))

    def test_story_entry_boxes_orders_story_ii_before_story_i(self):
        # 候选顺序 = _STORY_MENU_PATTERNS 顺序（STORY II 优先），且逐个关键词单独定位；未出现的入口不进候选。
        from src.tasks.EventTask import _STORY_MENU_PATTERNS
        story2 = Box(1, 1, 2, 2, confidence=1, name='STORY II')
        story1 = Box(1, 5, 2, 2, confidence=1, name='STORY I')
        asked = []

        def fake_entry_box(label, patterns=None):
            asked.append(patterns[0])
            return story1 if patterns[0] is _STORY_MENU_PATTERNS[1] else story2  # STORY I 也在菜单栏里。

        with patch.object(self.task, '_entry_box', side_effect=fake_entry_box):
            boxes = self.task._story_entry_boxes()
        self.assertEqual([story2, story1], boxes)  # STORY II 在前、STORY I 在后。
        self.assertEqual(list(_STORY_MENU_PATTERNS), asked)  # 每个关键词各探测一次（不做整表一次探测）。

    def test_story_entry_boxes_skips_missing_entries(self):
        # 当期只有 STORY I（或 STORY II 尚未出现在菜单栏）：候选里就没有它。
        from src.tasks.EventTask import _STORY_MENU_PATTERNS
        story1 = Box(1, 5, 2, 2, confidence=1, name='STORY I')
        with patch.object(self.task, '_entry_box',
                          side_effect=lambda label, patterns=None: (
                              story1 if patterns[0] is _STORY_MENU_PATTERNS[1] else None)):
            self.assertEqual([story1], self.task._story_entry_boxes())

    def test_enter_story_sub_page_falls_back_to_story_i_when_story_ii_locked(self):
        # STORY II 未开放（点开不切页）→ 回落 STORY I；STORY I 成功后不再点第二个之后的候选。
        story2 = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        story1 = Box(60, 50, 30, 10, confidence=1, name='STORY I')
        with patch.object(self.task, '_story_entry_boxes', return_value=[story2, story1]), \
                patch.object(self.task, '_try_enter_story_sub_page', side_effect=[False, True]) as try_mock, \
                patch.object(self.task, 'is_screen', return_value=True):
            self.task._enter_story_sub_page()
        self.assertEqual([story2, story1], [c.args[0] for c in try_mock.call_args_list])  # 按优先级逐个尝试。

    def test_enter_story_sub_page_returns_to_menu_before_next_candidate(self):
        # 点锁定入口落在别的页面：先退回菜单页再试下一个候选。
        story2 = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        story1 = Box(60, 50, 30, 10, confidence=1, name='STORY I')
        with patch.object(self.task, '_story_entry_boxes', return_value=[story2, story1]), \
                patch.object(self.task, '_try_enter_story_sub_page', side_effect=[False, True]), \
                patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_ensure_event_menu') as menu_mock:
            self.task._enter_story_sub_page()
        menu_mock.assert_called_once()  # 只在落点异常时补退一级。

    def test_enter_story_sub_page_raises_when_all_entries_unavailable(self):
        story2 = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        with patch.object(self.task, '_story_entry_boxes', return_value=[story2]), \
                patch.object(self.task, '_try_enter_story_sub_page', return_value=False), \
                patch.object(self.task, 'is_screen', return_value=True):
            self.assertRaises(WaitFailedException, self.task._enter_story_sub_page)

    def test_enter_story_sub_page_raises_when_no_story_entry(self):
        # 菜单页一个 STORY 入口都没定位到（OCR 失败/页面结构变化）：直接抛异常由 try_step 恢复。
        with patch.object(self.task, '_story_entry_boxes', return_value=[]), \
                patch.object(self.task, '_try_enter_story_sub_page', side_effect=AssertionError('无候选不应尝试')):
            self.assertRaises(WaitFailedException, self.task._enter_story_sub_page)

    # ---- 锁定入口的亮度前置判据（_entry_locked） ----

    @staticmethod
    def _fake_frame(value=30, bright_box=None):
        """构造单色帧（默认整帧灰暗），可按需叠一块高亮区域模拟白字/高亮底。"""
        frame = np.full((1440, 2560, 3), value, dtype='uint8')
        if bright_box is not None:
            x, y, w, h = bright_box
            frame[y:y + h, x:x + w] = 255
        return frame

    def _with_frame(self, frame):
        return patch.object(type(self.task), 'frame', new_callable=PropertyMock, return_value=frame)

    def test_entry_locked_true_when_row_dim(self):
        # 整行灰暗（锁图标 + 灰字，无任何高亮像素）= 锁定入口。
        with self._with_frame(self._fake_frame(30)):
            self.assertTrue(self.task._entry_locked(Box(900, 100, 100, 30)))

    def test_entry_locked_false_when_row_has_bright_pixels(self):
        # 框内有高亮像素（白字笔画或高亮底）= 可用态，即使底色很暗也不判锁定。
        frame = self._fake_frame(30, bright_box=(900, 100, 100, 12))  # 框内一半面积高亮。
        with self._with_frame(frame):
            self.assertFalse(self.task._entry_locked(Box(900, 100, 100, 30)))

    def test_entry_locked_false_without_frame_or_valid_region(self):
        # 判不出来（无帧/区域越界）一律保守按未锁定，交点开后的行为后验兜底。
        with self._with_frame(None):
            self.assertFalse(self.task._entry_locked(Box(10, 10, 20, 20)))
        with self._with_frame(self._fake_frame(30)):
            self.assertFalse(self.task._entry_locked(Box(3000, 2000, 50, 50)))  # 完全越界。

    def test_enter_story_sub_page_skips_locked_entry_by_brightness(self):
        # STORY II 亮度判据为锁定 → 不点它（省掉一次 _SD_ARRIVE_TIMEOUT 空等），直接试 STORY I。
        story2 = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        story1 = Box(60, 50, 30, 10, confidence=1, name='STORY I')
        with patch.object(self.task, '_story_entry_boxes', return_value=[story2, story1]), \
                patch.object(self.task, '_entry_locked', side_effect=[True, False]) as locked_mock, \
                patch.object(self.task, '_try_enter_story_sub_page', return_value=True) as try_mock, \
                patch.object(self.task, 'is_screen', return_value=True):
            self.task._enter_story_sub_page()
        self.assertEqual([story2, story1], [c.args[0] for c in locked_mock.call_args_list])  # 候选逐个过亮度判据。
        self.assertEqual([story1], [c.args[0] for c in try_mock.call_args_list])  # 锁定入口不点击。

    def test_enter_story_sub_page_raises_when_all_entries_locked(self):
        story2 = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        story1 = Box(60, 50, 30, 10, confidence=1, name='STORY I')
        with patch.object(self.task, '_story_entry_boxes', return_value=[story2, story1]), \
                patch.object(self.task, '_entry_locked', return_value=True), \
                patch.object(self.task, '_try_enter_story_sub_page', side_effect=AssertionError('锁定入口不应点击')):
            self.assertRaises(WaitFailedException, self.task._enter_story_sub_page)

    @unittest.skipUnless(os.path.exists('ok_templates/event_big_main_01.png'),
                         '缺少实机截图（ok_templates 子模块未检出）')
    def test_entry_locked_on_real_screenshot(self):
        # 实机标定回归（COINRUSH SHOWDOWN 大活动主页）：锁定的 STORY II（灰字 + 锁图标）判为锁定，
        # 同屏可用的 STORY I 判为可用；阈值见 _ENTRY_LOCK_BRIGHT_V / _ENTRY_LOCK_BRIGHT_RATIO。
        from src.tasks.EventTask import _STORY_MENU_PATTERNS
        self.set_image('ok_templates/event_big_main_01.png')
        locked = self.task._entry_box('剧情', patterns=[_STORY_MENU_PATTERNS[0]])
        unlocked = self.task._entry_box('剧情', patterns=[_STORY_MENU_PATTERNS[1]])
        self.assertIsNotNone(locked)  # 锁定态的 STORY II 仍能被 OCR 定位（故必须靠判据区分）。
        self.assertIsNotNone(unlocked)
        self.assertTrue(self.task._entry_locked(locked))
        self.assertFalse(self.task._entry_locked(unlocked))

    def test_story_sub_entry_ready_needs_sub_entry(self):
        # 就位判据：出现「加成」类入口才算（仍识别到 STORY I/II = 还停在大活动菜单页）。
        with patch.object(self.task, '_entry_box', return_value=Box(1, 1, 2, 2, confidence=1, name='STORY II')):
            self.assertFalse(self.task._story_sub_entry_ready())
        with patch.object(self.task, '_entry_box', return_value=Box(1, 1, 2, 2, confidence=1, name='加成奖励妮姬')):
            self.assertTrue(self.task._story_sub_entry_ready())
        with patch.object(self.task, '_entry_box', return_value=None):
            self.assertFalse(self.task._story_sub_entry_ready())

    def test_is_story_main_entry_matches_story_text_only(self):
        # STORY I/II 命中框 = 大活动菜单页入口（点击后进剧情子页面），「加成」类入口不是。
        for name, expected in (('STORY II', True), ('STORY I', True), ('加成奖励妮姬', False), (None, False)):
            self.assertEqual(expected, self.task._is_story_main_entry(Box(1, 1, 2, 2, confidence=1, name=name)))

    # ---- 推图目标：当前屏优先（游戏进页面自动定位到当前进度关） ----

    def test_progress_target_prefers_current_screen(self):
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        rows = [self._story_row('1-04', 'clear'), self._story_row('1-05')]  # 最下面那行可打 = 当前进度关。
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=rows) as stage_rows_mock, \
                patch.object(self.task, '_scan_stage_rows', side_effect=AssertionError('当前屏有目标不应扫全列表')):
            target = self.task._progress_target()
        self.assertEqual('1-05', target.stage_id)
        self.assertEqual(box, stage_rows_mock.call_args.args[0])  # 只解析当前屏。

    def test_progress_target_all_clear_on_current_screen(self):
        # 当前屏解析出了行但没有可打的（进度关之后是锁定行，无编号）= 已全通，不再扫全列表。
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=[self._story_row('1-04', 'clear')]), \
                patch.object(self.task, '_scan_stage_rows', side_effect=AssertionError('已全通不应扫全列表')):
            self.assertIsNone(self.task._progress_target())

    def test_progress_target_falls_back_when_current_screen_empty(self):
        # 当前屏一行都没解析出（OCR 漏检/页面未就绪）→ 兜底跨屏扫描。
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=[]), \
                patch.object(self.task, '_scan_stage_rows',
                             return_value=[self._story_row('1-05')]) as scan_mock:
            target = self.task._progress_target()
        self.assertEqual('1-05', target.stage_id)
        scan_mock.assert_called_once()

    def test_progress_target_falls_back_without_region(self):
        with patch.object(self.task, '_stage_list_box', return_value=None), \
                patch.object(self.task, '_stage_rows', side_effect=AssertionError('区域缺失不应解析')), \
                patch.object(self.task, '_scan_stage_rows', return_value=[]) as scan_mock:
            self.assertIsNone(self.task._progress_target())
        scan_mock.assert_called_once()  # 区域缺失也走兜底（兜底内部自行返回空）。

    def test_flow_story_missing_entry_raises(self):
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=None), \
                patch.object(self.task, 'transition', side_effect=AssertionError('入口缺失不应进入关卡页')):
            self.assertRaises(WaitFailedException, self.task._flow_story)

    def test_row_box_converts_stage_ref_tuple(self):
        box = self.task._row_box(self._story_row('1-05'))
        self.assertEqual((950, 400, 729, 120), (box.x, box.y, box.width, box.height))
        self.assertEqual('event_stage_1-05', box.name)

    def test_push_stages_chains_until_next_stage_disabled(self):
        # 结算「下一关」可用则续战（循环），不可用则点结算按钮结束并断言回到关卡页。
        target = self._story_row()
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        next_box = Box(200, 200, 20, 10, confidence=1, name='next')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_flow_entered', return_value=True), \
                patch.object(self.task, '_detail_page_open', return_value=False), \
                patch.object(self.task, '_skip_story_if_present') as skip_mock, \
                patch.object(self.task, 'wait_battle_finish',
                             side_effect=[('success', confirm), ('success', confirm)]) as battle_mock, \
                patch.object(self.task, '_optional_box', return_value=next_box), \
                patch.object(self.task, 'is_feature_enabled', side_effect=[True, False]) as enabled_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._push_stages(target)
        self.assertEqual(2, battle_mock.call_count)  # 第一场后点「下一关」续战，第二场后结束。
        clicked = [call.args[0] for call in click_mock.call_args_list]
        self.assertEqual('event_stage_1-05', clicked[0].name)  # 先点目标关卡行。
        self.assertEqual(['next', 'confirm'], [box.name for box in clicked[1:]])  # 续战 → 结算返回。
        self.assertEqual([2, 10, 10], [call.kwargs['after_sleep'] for call in click_mock.call_args_list])
        self.assertEqual(3, skip_mock.call_count)  # 进关卡、进下一关、结算返回各判一次剧情。
        self.assertEqual(2, enabled_mock.call_count)  # 两场结算都判「下一关」可用性。
        assert_mock.assert_called_once_with('event_stage_page', time_out=15)

    def test_push_stages_stops_on_failed_battle(self):
        target = self._story_row()
        back = Box(300, 300, 20, 10, confidence=1, name='failed_back')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_flow_entered', return_value=True), \
                patch.object(self.task, '_detail_page_open', return_value=False), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, 'wait_battle_finish', return_value=('failed', back)), \
                patch.object(self.task, '_optional_box', side_effect=AssertionError('失败不应判下一关')), \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._push_stages(target)
        self.assertEqual('failed_back', click_mock.call_args_list[-1].args[0].name)  # 点失败返回按钮结束。
        assert_mock.assert_called_once_with('event_stage_page', time_out=15)

    def test_push_stages_timeout_raises(self):
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, '_stage_flow_entered', return_value=True), \
                patch.object(self.task, '_detail_page_open', return_value=False), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, 'wait_battle_finish', return_value=(None, None)), \
                patch.object(self.task, 'assert_screen', side_effect=AssertionError('超时不应继续')):
            self.assertRaises(WaitFailedException, self.task._push_stages, self._story_row())

    def test_push_stages_stops_when_row_keeps_list(self):
        # 已通关且不可重复挑战的行：点开只弹提示、仍停在列表 → 视为无可推，直接结束（不进入战斗等待）。
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_flow_entered', return_value=None), \
                patch.object(self.task, 'wait_battle_finish', side_effect=AssertionError('未进关卡不应等战斗')), \
                patch.object(self.task, 'assert_screen', side_effect=AssertionError('仍在列表页不应断言')) as assert_mock:
            self.task._push_stages(self._story_row())
        self.assertEqual('event_stage_1-05', click_mock.call_args.args[0].name)  # 只点了关卡行。

    def test_push_stages_closes_detail_page_when_battle_disabled(self):
        # 已通关行的详情页：先判「战斗」按钮判态——灰白禁用 = 该关不可推（门票耗尽等）→ 关页后结束推图。
        battle_box = Box(1340, 1283, 80, 106, confidence=1, name='box_stage_detail_battle')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_flow_entered', return_value=True), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_optional_box', return_value=battle_box) as optional_mock, \
                patch.object(self.task, 'is_feature_enabled', return_value=False) as enabled_mock, \
                patch.object(self.task, '_close_stage_detail') as close_mock, \
                patch.object(self.task, 'wait_battle_finish', side_effect=AssertionError('不可推不应等战斗')):
            self.task._push_stages(self._story_row())
        self.assertEqual(1, click_mock.call_count)  # 只点了关卡行，未点「战斗」。
        optional_mock.assert_called_once_with('box_stage_detail_battle')
        enabled_mock.assert_called_once_with(battle_box)
        close_mock.assert_called_once()  # 关详情页回列表。

    def test_push_stages_enters_battle_from_detail_page_when_available(self):
        # 已通关行的详情页：「战斗」彩色可用 = 该关可推 → 点击进入战斗链（结算确认后收尾）。
        battle_box = Box(1340, 1283, 80, 106, confidence=1, name='box_stage_detail_battle')
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_flow_entered', return_value=True), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_optional_box', side_effect=[battle_box, None]), \
                patch.object(self.task, 'is_feature_enabled', return_value=True) as enabled_mock, \
                patch.object(self.task, '_skip_story_if_present') as skip_mock, \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)) as battle_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._push_stages(self._story_row())
        clicked = [call.args[0] for call in click_mock.call_args_list]
        self.assertEqual(['event_stage_1-05', 'box_stage_detail_battle', 'confirm'],
                         [box.name for box in clicked])  # 点行 → 详情页点「战斗」→ 结算确认结束。
        self.assertEqual([2, 2, 10], [call.kwargs['after_sleep'] for call in click_mock.call_args_list])
        enabled_mock.assert_called_once_with(battle_box)  # 结算「下一关」缺失不判态。
        self.assertEqual(1, battle_mock.call_count)
        self.assertEqual(2, skip_mock.call_count)  # 进战斗、结算返回各判一次剧情。
        assert_mock.assert_called_once_with('event_stage_page', time_out=15)

    def test_push_stages_missing_battle_region_from_detail_page(self):
        # 详情页「战斗」区域解析不出（coco 缺失/加载失败）→ 告警 + 关页结束（与灰白判态是两种问题）。
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_flow_entered', return_value=True), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'is_feature_enabled', side_effect=AssertionError('区域缺失不应判态')), \
                patch.object(self.task, '_close_stage_detail') as close_mock, \
                patch.object(self.task, 'wait_battle_finish', side_effect=AssertionError('无区域不应等战斗')):
            self.task._push_stages(self._story_row())
        self.assertEqual(1, click_mock.call_count)  # 只点了关卡行。
        close_mock.assert_called_once()  # 关详情页回列表。

    def test_push_stages_stops_at_battle_cap(self):
        # 安全上限：结算按钮持续判可用时不得死循环，达到上限即停止推图。
        from src.tasks.EventTask import _STORY_MAX_BATTLES
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        next_box = Box(200, 200, 20, 10, confidence=1, name='next')
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, '_stage_flow_entered', return_value=True), \
                patch.object(self.task, '_detail_page_open', return_value=False), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, 'wait_battle_finish',
                             return_value=('success', confirm)) as battle_mock, \
                patch.object(self.task, '_optional_box', return_value=next_box), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._push_stages(self._story_row())
        self.assertEqual(_STORY_MAX_BATTLES, battle_mock.call_count)  # 循环次数封顶。
        assert_mock.assert_called_once_with('event_stage_page', time_out=15)

    # ---- 剧情对话跳过（复用全局 conversation 界面与 conversation_skip 特征） ----

    def test_skip_story_clicks_skip_then_clears_popups(self):
        from src.tasks.EventTask import _STORY_DIALOG_WAIT
        icon_box = Box(0, 0, 10, 10, confidence=1, name='box_conversation_icon')
        captured = {}

        def fake_wait_until(condition, time_out=0, pre_action=None, post_action=None,
                            settle_time=-1, raise_if_not_found=False):
            captured['time_out'] = time_out
            captured['settle_time'] = settle_time
            return condition()  # 真实执行一次条件，验证「剧情界面命中」判定。

        # is_screen 序列：条件命中 → 确认在剧情界面 → 首次跳过后界面消失（三次命中 + 一次消失）。
        with patch.object(self.task, 'wait_until', side_effect=fake_wait_until), \
                patch.object(self.task, 'is_screen', side_effect=[True, True, True, False]) as screen_mock, \
                patch.object(self.task, '_optional_box', return_value=icon_box), \
                patch.object(self.task, 'wait_click_feature') as click_feature_mock, \
                patch.object(self.task, 'dismiss_all_popups') as dismiss_mock:
            self.assertTrue(self.task._skip_story_if_present())
        self.assertEqual('conversation', screen_mock.call_args_list[0].args[0])  # 条件判剧情界面。
        self.assertEqual(_STORY_DIALOG_WAIT, captured['time_out'])
        self.assertEqual(0, captured['settle_time'])  # 剧情/战斗信号都在场即返回，不加稳定窗口。
        click_feature_mock.assert_called_once_with('conversation_skip', box=icon_box,
                                                   raise_if_not_found=True, after_sleep=2)
        dismiss_mock.assert_called_once_with(wait_for_popup=False, time_out=5)  # 跳过后清奖励/好感遮罩。

    def test_skip_story_returns_false_without_dialog(self):
        with patch.object(self.task, 'wait_until', return_value=False), \
                patch.object(self.task, 'wait_click_feature', side_effect=AssertionError('无剧情不应点跳过')):
            self.assertFalse(self.task._skip_story_if_present())

    def test_skip_story_returns_false_when_battle_started(self):
        # 直接进入战斗（无剧情）：不点击跳过。
        with patch.object(self.task, 'wait_until', return_value=True), \
                patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_in_battle_page', return_value=True), \
                patch.object(self.task, 'wait_click_feature', side_effect=AssertionError('无剧情不应点跳过')):
            self.assertFalse(self.task._skip_story_if_present())

    # ---- 扫荡（方案 §8：配置关卡 → 详情页「快速战斗」，次数拉满到耗尽） ----

    def test_do_story_skipped_when_story_and_sweep_off(self):
        self.task.config['剧情'] = False
        self.task.config['扫荡'] = False
        with patch.object(self.task, '_probe_entry', side_effect=AssertionError('都关闭不应探测')), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('都关闭不应执行')):
            self.task._do_story()

    def test_do_story_runs_when_sweep_only(self):
        self.task.config['剧情'] = False
        self.task.config['扫荡'] = True
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_flow_story') as flow_mock:
            self.task._do_story()
        flow_mock.assert_called_once()  # 只开扫荡也要走剧情子流程（入口与关卡页共用）。

    def test_flow_story_pushes_then_sweeps(self):
        calls = []
        self.task.config['扫荡'] = True
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=Box(10, 10, 20, 20, confidence=1, name='加成奖励妮姬')), \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, '_probe_story_sub_page', return_value=False), \
                patch.object(self.task, '_progress_target', return_value=self._story_row()), \
                patch.object(self.task, '_push_stages', side_effect=lambda row: calls.append('push')), \
                patch.object(self.task, '_sweep_stage', side_effect=lambda stage: calls.append(f'sweep:{stage}')):
            self.task._flow_story()
        self.assertEqual(['push', 'sweep:1-11'], calls)  # 先推图后扫荡，扫荡用默认关卡。

    def test_flow_story_sweeps_configured_stage_without_push(self):
        self.task.config['剧情'] = False
        self.task.config['扫荡'] = True
        self.task.config['扫荡关卡'] = '1-09'
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=Box(10, 10, 20, 20, confidence=1, name='加成奖励妮姬')), \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, '_probe_story_sub_page', return_value=False), \
                patch.object(self.task, '_scan_stage_rows', side_effect=AssertionError('剧情关闭不应扫描推图')), \
                patch.object(self.task, '_push_stages', side_effect=AssertionError('剧情关闭不应推图')), \
                patch.object(self.task, '_sweep_stage') as sweep_mock:
            self.task._flow_story()
        sweep_mock.assert_called_once_with('1-09')  # 用配置的扫荡关卡。
        self.assertEqual(['event_stage_page', 'event_main'],
                         [call.args[0] for call in transition_mock.call_args_list])  # 仍进关卡页并回菜单页。

    def test_locate_stage_row_prefers_current_screen(self):
        # 当前屏能命中就不动列表：不回顶、不下滚（进页面时游戏常已停在最近位置）。
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=[self._story_row('1-11', 'repeat')]), \
                patch.object(self.task, '_scroll_list_to_top', side_effect=AssertionError('当前屏命中不应回顶')), \
                patch.object(self.task, '_scroll_list_down', side_effect=AssertionError('当前屏命中不应下滚')):
            row = self.task._locate_stage_row('1-11')
        self.assertEqual('1-11', row.stage_id)

    def test_locate_stage_row_finds_on_later_screen(self):
        # 当前屏没有才回顶逐屏找；行框必须对应当前屏幕（命中即返回，不再继续滚动）。
        from src.tasks.EventTask import _STAGE_LIST_BOX, _STAGE_SWIPE_START_RATIO
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows',
                             side_effect=[[self._story_row('1-01')], [self._story_row('1-11', 'repeat')]]), \
                patch.object(self.task, '_scroll_list_to_top') as top_mock, \
                patch.object(self.task, '_scroll_list_down', side_effect=AssertionError('命中的屏不应再下滚')) as down_mock:
            row = self.task._locate_stage_row('1-11')
        self.assertEqual('1-11', row.stage_id)
        top_mock.assert_called_once_with(box_name=_STAGE_LIST_BOX, start_ratio=_STAGE_SWIPE_START_RATIO)
        down_mock.assert_not_called()  # 回顶后第一屏即命中，不再下滚。

    def test_locate_stage_row_returns_none_when_bottom(self):
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=[self._story_row('1-01')]), \
                patch.object(self.task, '_scroll_list_to_top'), \
                patch.object(self.task, '_scroll_list_down', return_value=False):
            self.assertIsNone(self.task._locate_stage_row('1-11'))

    def test_locate_stage_row_returns_none_without_region(self):
        with patch.object(self.task, '_stage_list_box', return_value=None), \
                patch.object(self.task, '_scroll_list_to_top', side_effect=AssertionError('区域缺失不应滚动')):
            self.assertIsNone(self.task._locate_stage_row('1-11'))

    def _sweep_quick_box(self):
        return Box(1343, 1223, 34, 30, confidence=1, name='box_stage_detail_quick_battle')

    def test_sweep_stage_sweeps_then_stops_when_unavailable(self):
        # 第一轮实际扫荡（拉满次数），第二轮进详情页发现「快速战斗」灰白即结束。
        from src.tasks.EventTask import _SWEEP_START_BOX
        row = self._story_row('1-11', 'repeat')
        quick_box = self._sweep_quick_box()
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        max_btn = Box(1424, 991, 75, 44, confidence=1, name='custom_quick_battle_max')
        with patch.object(self.task, '_locate_stage_row', return_value=row) as locate_mock, \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature') as wait_feature_mock, \
                patch.object(self.task, '_optional_box', return_value=quick_box), \
                patch.object(self.task, 'is_feature_enabled', side_effect=[True, False]) as enabled_mock, \
                patch.object(self.task, 'find_one', return_value=max_btn), \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)) as battle_mock, \
                patch.object(self.task, 'wait_click_feature') as close_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._sweep_stage('1-11')
        self.assertEqual(2, locate_mock.call_count)  # 扫荡一轮 + 探测一轮（耗尽确认）。
        self.assertEqual([call.args[0] for call in locate_mock.call_args_list], ['1-11', '1-11'])
        click_mock.assert_any_call(quick_box, after_sleep=1)  # 点详情页「快速战斗」。
        click_mock.assert_any_call(max_btn, after_sleep=1)  # 次数拉满。
        click_mock.assert_any_call(_SWEEP_START_BOX, after_sleep=1)  # 点开始快速战斗。
        click_mock.assert_any_call(confirm, after_sleep=2)  # 结算确认。
        self.assertEqual(1, battle_mock.call_count)  # 只扫荡一轮就耗尽。
        self.assertEqual([quick_box, quick_box], [call.args[0] for call in enabled_mock.call_args_list])  # 两轮都判「快速战斗」可用性。
        # 特征等待顺序：第一轮详情页就位 → 次数弹窗就位；第二轮只等详情页就位（随即判灰白结束）。
        self.assertEqual(['stage_detail_close', 'custom_quick_battle_page', 'stage_detail_close'],
                         [call.args[0] for call in wait_feature_mock.call_args_list])
        close_mock.assert_any_call('stage_detail_close', raise_if_not_found=True, after_sleep=1)  # 关详情页动作。
        self.assertEqual(2, close_mock.call_count)  # 结算落回详情页关一次；第二轮灰白耗尽再关一次。
        self.assertEqual(3, assert_mock.call_count)  # 两次关页 + 首轮收尾各确认一次回到关卡列表。

    def test_sweep_stage_missing_row_skips(self):
        with patch.object(self.task, '_locate_stage_row', return_value=None), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('未定位到关卡不应点击')):
            self.task._sweep_stage('1-07')

    def test_sweep_stage_skips_when_detail_page_missing(self):
        # 已通关但不可重复挑战的行：点开只弹提示、不进详情页 → 软判定跳过，且不做关页动作（仍在列表页）。
        row = self._story_row('1-11', 'clear')
        with patch.object(self.task, '_locate_stage_row', return_value=row), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature', return_value=False), \
                patch.object(self.task, '_optional_box', side_effect=AssertionError('未进详情页不应判快速战斗')), \
                patch.object(self.task, 'wait_click_feature', side_effect=AssertionError('仍在列表页不应关详情页')):
            self.task._sweep_stage('1-11')
        self.assertEqual('event_stage_1-11', click_mock.call_args.args[0].name)  # 只点了关卡行。

    def test_sweep_stage_missing_quick_region_skips(self):
        # 区域特征解析不出来（coco 缺失）与「按钮灰白」是两种问题：前者要单独告警，不能误报成耗尽。
        row = self._story_row('1-11', 'repeat')
        with patch.object(self.task, '_locate_stage_row', return_value=row), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature'), \
                patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'is_feature_enabled', side_effect=AssertionError('区域缺失不应判态')), \
                patch.object(self.task, 'wait_click_feature') as close_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._sweep_stage('1-11')
        self.assertEqual('event_stage_1-11', click_mock.call_args.args[0].name)  # 只点了关卡行。
        close_mock.assert_called_once_with('stage_detail_close', raise_if_not_found=True, after_sleep=1)
        assert_mock.assert_called_once_with('event_stage_page', time_out=15)

    def test_sweep_stage_requires_count_popup_and_closes_detail_after_settlement(self):
        # 实机口径：点「快速战斗」必弹次数选择窗（缺失抛异常）；扫荡直接跳结算不进战斗界面；
        # 结算确认后落回关卡详情页，需先关详情页退回列表再进入下一轮。
        from src.tasks.EventTask import _SWEEP_PAGE_FEATURE, _SWEEP_START_BOX
        row = self._story_row('1-11', 'repeat')
        quick_box = self._sweep_quick_box()
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        close_btn = Box(1199, 544, 34, 34, confidence=1, name='stage_detail_close')

        def find_one(feature, **kwargs):  # 详情页关闭按钮命中、次数「拉满」未命中。
            return close_btn if feature == 'stage_detail_close' else None

        with patch.object(self.task, '_locate_stage_row', return_value=row), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature') as wait_feature_mock, \
                patch.object(self.task, '_optional_box', return_value=quick_box), \
                patch.object(self.task, 'is_feature_enabled', side_effect=[True, False]), \
                patch.object(self.task, 'find_one', side_effect=find_one), \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)), \
                patch.object(self.task, 'wait_click_feature') as close_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._sweep_stage('1-11')
        self.assertEqual(_SWEEP_PAGE_FEATURE, wait_feature_mock.call_args_list[1].args[0])  # 第一轮等次数弹窗。
        self.assertTrue(wait_feature_mock.call_args_list[1].kwargs['raise_if_not_found'])  # 弹窗必现语义。
        clicked = [call.args[0] for call in click_mock.call_args_list]
        self.assertIn(_SWEEP_START_BOX, clicked)  # 弹窗里点「开始」（按区域特征名点击）。
        click_mock.assert_any_call(confirm, after_sleep=2)  # 点结算确认。
        self.assertEqual(2, close_mock.call_count)  # 结算后关详情页 + 第二轮灰白再关一次。

    def test_sweep_stage_ignores_row_status(self):
        # 行状态不作门槛：已通关标记可能漏检（实机 1-11 已通关却读成 available），
        # 能否扫荡一律进详情页由「快速战斗」判态决定。
        row = self._story_row('1-11', 'available')
        with patch.object(self.task, '_locate_stage_row', return_value=row), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature'), \
                patch.object(self.task, '_optional_box', return_value=self._sweep_quick_box()), \
                patch.object(self.task, 'is_feature_enabled', return_value=False), \
                patch.object(self.task, 'wait_click_feature') as close_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._sweep_stage('1-11')
        self.assertEqual('event_stage_1-11', click_mock.call_args.args[0].name)  # 仍然点开了关卡详情页。
        close_mock.assert_called_once_with('stage_detail_close', raise_if_not_found=True, after_sleep=1)  # 灰白后关页收尾。
        assert_mock.assert_called_once_with('event_stage_page', time_out=15)

    def test_sweep_stage_timeout_raises(self):
        row = self._story_row('1-11', 'repeat')
        with patch.object(self.task, '_locate_stage_row', return_value=row), \
                patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_feature'), \
                patch.object(self.task, '_optional_box', return_value=self._sweep_quick_box()), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, 'wait_battle_finish', return_value=(None, None)), \
                patch.object(self.task, 'assert_screen', side_effect=AssertionError('超时不应继续')):
            self.assertRaises(WaitFailedException, self.task._sweep_stage, '1-11')

    def test_sweep_stage_stops_at_round_cap(self):
        # 安全上限：快速战斗持续判可用（次数不耗尽）时不得死循环。
        from src.tasks.EventTask import _SWEEP_MAX_ROUNDS
        row = self._story_row('1-11', 'repeat')
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        with patch.object(self.task, '_locate_stage_row', return_value=row) as locate_mock, \
                patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_feature'), \
                patch.object(self.task, '_optional_box', return_value=self._sweep_quick_box()), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)) as battle_mock, \
                patch.object(self.task, 'assert_screen'):
            self.task._sweep_stage('1-11')
        self.assertEqual(_SWEEP_MAX_ROUNDS, locate_mock.call_count)  # 轮次封顶。
        self.assertEqual(_SWEEP_MAX_ROUNDS, battle_mock.call_count)

    def test_is_completed_scope(self):
        self.assertFalse(self.task.is_completed())
        self.task.mark_done('event', 'day')
        self.assertTrue(self.task.is_completed())


if __name__ == '__main__':
    unittest.main()