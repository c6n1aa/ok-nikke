# pyright: reportOptionalMemberAccess=false, reportOptionalSubscript=false
# 仅本测试文件：mock 出来的 find_one/load_snapshot 返回值已知非空，直接取属性；src/ 仍由这两条规则把关。
import os
import time
import unittest
from unittest.mock import MagicMock, PropertyMock, call, patch

import numpy as np
from ok.feature.Box import Box
from ok.task.exceptions import WaitFailedException
from ok.test.TaskTestCase import TaskTestCase

from src import event_calendar, event_stage
from src.config import config
from src.tasks.event._const import event_done_key, event_identity
from src.tasks.EventTask import EventTask
from tests.support.asserts import assert_any_call_semantic, assert_called_once_semantic, assert_last_call_semantic

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')


def _isolate_task_config(task, name):
    """把任务配置重定向到 dev_tools/test_configs 下的临时文件并复位为任务默认值：既不污染真实 configs/，也不读它的值。"""
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')
    task.config.reset_to_default()  # 复位为任务默认值：用例只设自己关心的开关，不读开发者本地配置。
    task.config['_execution_states'] = {}


def _fixed_height(task, height=1440):
    """把任务的屏幕高度固定为 1440（去重容差、兜底行距按屏高比例计算，测试需确定值）。"""
    return patch.object(type(task), 'height', new_callable=PropertyMock, return_value=height)


def _fake_event(key, name, url, end_time=0, event_type='StoryEvent'):
    """构造一条假的 CalendarEvent（banner 匹配与身份判定用，只动 key/name/url/type）。"""
    return event_calendar.CalendarEvent(key=key, name=name, category='version_event',
                                        event_type=event_type, start_time=0, end_time=end_time, url=url)


def _snapshot(events):
    """构造一条本地日历快照（fetched_at 取当前时间，避免被判定为过期）。"""
    return event_calendar.CalendarSnapshot(fetched_at=time.time(), events=tuple(events), status={})


class _DebugOffTestCase(TaskTestCase):
    """基类：测试环境强制 debug=True，本基类将其屏蔽，以便验证正常的已完成/记录逻辑。"""

    def setUp(self):
        patcher = patch.object(self.task, '_in_debug', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestEventTask(_DebugOffTestCase):
    task_class = EventTask
    task: EventTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'EventTask')
        self.task.clear_done('event')
        for key in ('签到', '剧情', '扫荡', '扫荡关卡', '挑战', '任务', '商店', '小游戏', '剧情模式'):
            self.task.config[key] = self.task.default_config[key]
        exit_patcher = patch.object(self.task, '_exit_to_lobby')  # 拦截收尾返回大厅步骤，避免测试触碰真实窗口。
        exit_patcher.start()
        self.addCleanup(exit_patcher.stop)
        # 默认把换地区提示特征当成「未标注」：否则每个战斗循环都要为它白等 _STORY_FIELD_CHANGED_WAIT 秒。
        # 需要覆盖该分支的用例自行 patch feature_exists/wait_feature（见换地区提示那组用例）。
        feature_patcher = patch.object(self.task, 'feature_exists', return_value=False)
        feature_patcher.start()
        self.addCleanup(feature_patcher.stop)

    def test_config_defaults(self):
        from src.tasks.event._const import _LEGACY_DONE_KEY
        self.assertEqual('活动', self.task.name)
        self.assertIn('活动', self.task.description)
        # done_keys 只是「本任务有完成状态」的声明锚：真实完成键按活动身份动态生成（event_<身份>[_<流程>]）。
        self.assertEqual({_LEGACY_DONE_KEY: 'day'}, EventTask.done_keys)
        self.assertTrue(self.task.default_config['签到'])
        self.assertFalse(self.task.default_config['剧情'])
        self.assertTrue(self.task.default_config['扫荡'])
        self.assertEqual('1-11', self.task.default_config['扫荡关卡'])
        self.assertTrue(self.task.default_config['挑战'])
        self.assertTrue(self.task.default_config['任务'])
        self.assertFalse(self.task.default_config['商店'])
        self.assertTrue(self.task.default_config['小游戏'])  # 小游戏默认开启（未接入的活动按注册表自动跳过）。
        self.assertEqual('NORMAL', self.task.default_config['剧情模式'])  # 难度选项沿用游戏内英文标签。
        for key in ('签到', '剧情', '扫荡', '扫荡关卡', '挑战', '任务', '商店', '小游戏', '剧情模式'):
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

    def test_skip_when_all_live_events_done(self):
        # 不在活动内 + 在架活动身份键均已完成：直接跳过 —— 不动游戏窗口，也不联网（判定只用本地快照）。
        from src.tasks.event._const import _LEGACY_DONE_KEY
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        self.task.mark_done(event_done_key(event_identity('key1')), 'day')
        with patch.object(event_calendar, 'load_snapshot', return_value=_snapshot([event])), \
                patch.object(event_calendar, 'refresh', side_effect=AssertionError('完成判定不应联网')), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'ensure_screen', side_effect=AssertionError('已完成不应动窗口')), \
                patch.object(self.task, '_process_event_list', side_effect=AssertionError('不应处理列表')):
            self.task.run()
        self.assertTrue(self.task.is_done(event_done_key(event_identity('key1')), 'day'))
        self.assertFalse(self.task.is_done(_LEGACY_DONE_KEY, 'day'))  # 旧聚合键不再参与判定。

    def test_run_takeover_wins_over_completed_calendar(self):
        # 顺序保证：已在活动内时先接管再判日历 —— 否则停在日历外的往期活动（档案馆）本轮什么都不做。
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        self.task.mark_done(event_done_key(event_identity('key1')), 'day')
        with patch.object(event_calendar, 'load_snapshot', return_value=_snapshot([event])), \
                patch.object(self.task, '_probe_event_context', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_takeover_event') as takeover_mock, \
                patch.object(self.task, '_todo_events', return_value=[]), \
                patch.object(self.task, 'ensure_screen', side_effect=AssertionError('接管已覆盖则不应回大厅')):
            self.task.run()
        takeover_mock.assert_called_once()  # 日历显示全部完成，但仍在活动内 → 依然接管。

    def test_run_takeover_falls_back_to_list_when_events_pending(self):
        # 接管只处理当前页（往期活动页/日历外活动页做不了 banner 定位）：仍有待处理活动时回大厅走列表。
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(event_calendar, 'load_snapshot', return_value=_snapshot([event])), \
                patch.object(self.task, '_probe_event_context', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_takeover_event') as takeover_mock, \
                patch.object(self.task, '_todo_events', return_value=[event]), \
                patch.object(self.task, 'ensure_screen', return_value=True) as lobby_mock, \
                patch.object(self.task, '_process_event_list') as list_mock:
            self.task.run()
        takeover_mock.assert_called_once()
        lobby_mock.assert_called_once_with('lobby', raise_on_fail=False)  # 回大厅按列表继续处理。
        list_mock.assert_called_once()

    def test_abort_when_lobby_not_found(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(event_calendar, 'load_snapshot', return_value=_snapshot([event])), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'ensure_screen', return_value=False), \
                patch.object(self.task, '_process_event_list', side_effect=AssertionError('不应处理列表')):
            self.task.run()
        self.assertFalse(self.task.is_done(event_done_key(event_identity('key1')), 'day'))

    def test_run_delegates_list_flow_without_marking(self):
        # run 只做门闸与编排：完成状态由 _process_event_list 按活动身份逐个落盘。
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(event_calendar, 'load_snapshot', return_value=_snapshot([event])), \
                patch.object(self.task, 'ensure_screen', return_value=True), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_process_event_list') as list_mock:
            self.task.run()
        list_mock.assert_called_once()
        self.assertFalse(self.task.is_done(event_done_key(event_identity('key1')), 'day'))  # run 自身不落盘。

    def test_run_not_marked_when_list_flow_fails(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(event_calendar, 'load_snapshot', return_value=_snapshot([event])), \
                patch.object(self.task, 'ensure_screen', return_value=True), \
                patch.object(self.task, '_probe_event_context', return_value=False), \
                patch.object(self.task, 'try_step', return_value=False):
            self.task.run()
        self.assertFalse(self.task.is_done(event_done_key(event_identity('key1')), 'day'))

    def test_run_takeover_branch_when_already_in_event(self):
        # 用户手动进入活动（主页/子页面）时直接接管：接管已覆盖全部待处理活动时不再走大厅闸门与列表遍历。
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(event_calendar, 'load_snapshot', return_value=_snapshot([event])), \
                patch.object(self.task, 'ensure_screen', side_effect=AssertionError('接管分支不应回大厅')), \
                patch.object(self.task, '_probe_event_context', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_takeover_event') as takeover_mock, \
                patch.object(self.task, '_todo_events', return_value=[]), \
                patch.object(self.task, '_process_event_list', side_effect=AssertionError('接管已覆盖不应遍历列表')):
            self.task.run()
        takeover_mock.assert_called_once()

    # ---- 完成状态：按活动身份分键 ----

    def test_event_identity_strips_prefix_and_sanitizes(self):
        self.assertEqual('COINRUSHSHOWDOWN', event_identity('EVENT_BANNER_COINRUSHSHOWDOWN'))  # 去 banner 前缀。
        self.assertEqual('ABC_1_2', event_identity('EVENT_BANNER_ABC-1.2'))  # 非法字符归一为下划线。
        self.assertEqual('A_B', event_identity('__A..B__'))  # 首尾下划线去掉。
        self.assertEqual(event_identity('EVENT_BANNER_X'), event_identity('EVENT_BANNER_X'))  # 同键稳定。

    def test_event_identity_truncates_and_hashes_dirty_key(self):
        from src.tasks.event._const import _EVENT_KEY_MAX
        self.assertEqual(_EVENT_KEY_MAX, len(event_identity('K' * (_EVENT_KEY_MAX + 20))))  # 超长截断。
        dirty = event_identity('....')  # 归一后为空：回落 md5 短哈希。
        self.assertEqual(8, len(dirty))
        self.assertEqual(dirty, event_identity('....'))  # 脏键身份仍稳定。
        self.assertNotEqual(event_identity('....'), event_identity('----'))  # 不同脏键身份不同。

    def test_event_done_key_shape(self):
        self.assertEqual('event_ABC', event_done_key('ABC'))  # 聚合键。
        self.assertEqual('event_ABC_shop', event_done_key('ABC', 'shop'))  # 子流程键。
        with self.assertRaises(ValueError):
            event_done_key(None)  # 身份缺失显式报错，避免写出 event_None 这类脏键。

    def test_todo_events_filters_done_identities(self):
        done_event = _fake_event('done', '活动A', 'https://cdn/a.png')
        todo_event = _fake_event('todo', '活动B', 'https://cdn/b.png')
        self.task.mark_done(event_done_key(event_identity('done')), 'day')
        with patch.object(self.task, '_pending_events', return_value=[done_event, todo_event]):
            remaining = self.task._todo_events()
        self.assertEqual(['todo'], [event.key for event in remaining])  # A 已完成不挡 B。

    def test_process_event_list_marks_processed_event_done(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        with patch.object(self.task, '_pending_events', return_value=[event]), \
                patch.object(self.task, '_reposition_list', return_value=True), \
                patch.object(self.task, '_find_event_row', side_effect=[row, None]), \
                patch.object(self.task, '_enter_and_probe', return_value=True) as probe_mock, \
                patch.object(self.task, '_recover_to_lobby', return_value=True):
            self.task._process_event_list()
        probe_mock.assert_called_once_with(row)
        self.assertTrue(self.task.is_done(event_done_key(event_identity('key1')), 'day'))  # 处理完落身份键。

    def test_process_event_list_marks_unmatched_event_done(self):
        # 全部位置都没匹配到卡片（保底包过期/活动未上架）：告警 + 按本日已处理落盘，避免每次运行空扫列表。
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(self.task, '_pending_events', return_value=[event]), \
                patch.object(self.task, '_reposition_list', side_effect=[True, False]), \
                patch.object(self.task, '_find_event_row', return_value=None), \
                patch.object(self.task, '_enter_and_probe', side_effect=AssertionError('未匹配不应进入')), \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._process_event_list()
        warn_mock.assert_called_once()  # 只告警一次（汇总）。
        self.assertIn('key1', warn_mock.call_args.args[0])
        self.assertTrue(self.task.is_done(event_done_key(event_identity('key1')), 'day'))

    def test_process_event_list_skips_done_event_in_same_day(self):
        # 同日在架两个活动：A 已完成时只处理 B（旧聚合键会把 B 一起挡掉）。
        done_event = _fake_event('done', '活动A', 'https://cdn/a.png')
        todo_event = _fake_event('todo', '活动B', 'https://cdn/b.png')
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        self.task.mark_done(event_done_key(event_identity('done')), 'day')
        with patch.object(self.task, '_pending_events', return_value=[done_event, todo_event]), \
                patch.object(self.task, '_reposition_list', return_value=True), \
                patch.object(self.task, '_find_event_row', side_effect=[row, None]) as find_mock, \
                patch.object(self.task, '_enter_and_probe', return_value=True) as probe_mock, \
                patch.object(self.task, '_recover_to_lobby', return_value=True):
            self.task._process_event_list()
        probe_mock.assert_called_once_with(row)
        self.assertEqual(todo_event, find_mock.call_args.args[0])  # 只在 B 上做 banner 匹配。
        self.assertTrue(self.task.is_done(event_done_key(event_identity('todo')), 'day'))

    def test_process_event_list_exposes_authoritative_identity_to_subflows(self):
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        seen = {}

        def probe(box):
            seen['identity'] = self.task._event_identity  # 处理期间子流程应拿到当前活动身份。
            seen['authoritative'] = self.task._identity_authoritative
            return True

        with patch.object(self.task, '_pending_events', return_value=[event]), \
                patch.object(self.task, '_reposition_list', return_value=True), \
                patch.object(self.task, '_find_event_row', side_effect=[row, None]), \
                patch.object(self.task, '_enter_and_probe', side_effect=probe), \
                patch.object(self.task, '_recover_to_lobby', return_value=True):
            self.task._process_event_list()
        self.assertEqual(event_identity('key1'), seen['identity'])  # 列表路径身份来自日历 key。
        self.assertTrue(seen['authoritative'])  # 权威身份：允许落盘。
        self.assertIsNone(self.task._event_identity)  # 处理后复位。
        self.assertFalse(self.task._identity_authoritative)

    def test_prune_identity_keys_drops_rotated_events(self):
        live = _fake_event('live', '新活动', 'https://cdn/live.png')
        self.task.mark_done(event_done_key(event_identity('live')), 'day')  # 在架活动：保留。
        self.task.mark_done(event_done_key(event_identity('live'), 'shop'), 'day')  # 在架活动的子流程键：保留。
        self.task.mark_done(event_done_key(event_identity('old')), 'day')  # 已轮换：清掉。
        self.task.mark_done(event_done_key(event_identity('old'), 'checkin'), 'day')  # 已轮换的子流程键：清掉。
        self.task.mark_done('event', 'day')  # 旧版聚合键：顺手清掉。
        with patch.object(self.task, '_pending_events', return_value=[live]):
            self.task._prune_identity_keys()
        states = self.task.config['_execution_states']
        self.assertIn(event_done_key(event_identity('live')), states)
        self.assertIn(event_done_key(event_identity('live'), 'shop'), states)
        self.assertNotIn(event_done_key(event_identity('old')), states)
        self.assertNotIn(event_done_key(event_identity('old'), 'checkin'), states)
        self.assertNotIn('event', states)

    def test_prune_identity_keys_noop_without_local_events(self):
        self.task.mark_done(event_done_key(event_identity('old')), 'day')
        with patch.object(self.task, '_pending_events', return_value=[]):
            self.task._prune_identity_keys()
        self.assertIn(event_done_key(event_identity('old')), self.task.config['_execution_states'])  # 无清单时不动配置。

    def test_clear_done_all_clears_identity_key_family(self):
        self.task.mark_done(event_done_key(event_identity('live')), 'day')
        self.task.mark_done(event_done_key(event_identity('live'), 'shop'), 'day')
        self.task.mark_done('event', 'day')
        self.task.clear_done_all()
        states = self.task.config['_execution_states']
        self.assertFalse([key for key in states if key.startswith('event_') or key == 'event'])  # 整族清空。

    def test_resolve_takeover_identity_uses_form_to_pick_candidate(self):
        big = _fake_event('big', '大活动', 'https://cdn/big.png', event_type='FieldHubEvent')
        small = _fake_event('small', '小活动', 'https://cdn/small.png')
        with patch.object(self.task, '_pending_events', return_value=[big, small]), \
                patch.object(self.task, '_probe_event_form', return_value=(True, False)):
            self.assertEqual(event_identity('big'), self.task._resolve_takeover_identity())  # 大活动形态。
        with patch.object(self.task, '_pending_events', return_value=[big, small]), \
                patch.object(self.task, '_probe_event_form', return_value=(False, True)):
            self.assertEqual(event_identity('small'), self.task._resolve_takeover_identity())  # 小活动形态。
        with patch.object(self.task, '_pending_events', return_value=[big, small]), \
                patch.object(self.task, '_probe_event_form', return_value=(True, True)):
            self.assertIsNone(self.task._resolve_takeover_identity())  # 形态同真：判不出。
        with patch.object(self.task, '_pending_events', return_value=[]):
            self.assertIsNone(self.task._resolve_takeover_identity())  # 无本地清单：身份未知。

    def test_resolve_takeover_identity_requires_unique_candidate(self):
        first = _fake_event('a', '小活动A', 'https://cdn/a.png')
        second = _fake_event('b', '小活动B', 'https://cdn/b.png')
        with patch.object(self.task, '_pending_events', return_value=[first, second]), \
                patch.object(self.task, '_probe_event_form', return_value=(False, True)):
            self.assertIsNone(self.task._resolve_takeover_identity())  # 两个同形态候选：不猜。

    def test_probe_event_form_uses_signin_and_bonus_entries(self):
        from src.tasks.event._const import _STORY_SUB_PATTERN
        with patch.object(self.task, '_probe_entry', return_value=True) as probe_mock, \
                patch.object(self.task, '_entry_box',
                             return_value=Box(1, 1, 1, 1, confidence=1, name='加成奖励妮姬')) as entry_mock:
            self.assertEqual((True, True), self.task._probe_event_form())
        probe_mock.assert_called_once_with('签到')  # 大活动形态判据是签到印章入口。
        self.assertEqual([_STORY_SUB_PATTERN], entry_mock.call_args.kwargs['patterns'])  # 小活动形态判据是「加成」入口。

    def test_takeover_event_runs_subflows_even_when_identity_already_done(self):
        # 接管不做整体短路：身份撞上「本日已完成的候选」时仍要跑子流程，否则日历外的往期活动（档案馆）连剧情都不会推。
        # 非幂等流程靠各自的 _subflow_completed 读身份键跳过（见 test_do_checkin_skips_when_identity_key_done）。
        self.task.mark_done(event_done_key(event_identity('key1')), 'day')
        with patch.object(self.task, '_ensure_event_menu') as menu_mock, \
                patch.object(self.task, '_resolve_takeover_identity', return_value=event_identity('key1')), \
                patch.object(self.task, '_run_event_subflows') as subflows_mock:
            self.task._takeover_event()
        menu_mock.assert_called_once()
        subflows_mock.assert_called_once()  # 子流程照跑。
        self.assertIsNone(self.task._event_identity)  # 身份上下文复位。

    def test_takeover_event_does_not_record_inferred_identity(self):
        # 接管身份是推断出来的（非权威）：流程照跑但不落任何身份键（写错会误标到别的活动头上）。
        with patch.object(self.task, '_ensure_event_menu'), \
                patch.object(self.task, '_resolve_takeover_identity', return_value=event_identity('key1')), \
                patch.object(self.task, '_run_event_subflows') as subflows_mock:
            self.task._takeover_event()
        subflows_mock.assert_called_once()
        self.assertFalse(self.task.is_done(event_done_key(event_identity('key1')), 'day'))
        self.assertIsNone(self.task._event_identity)
        self.assertFalse(self.task._identity_authoritative)

    def test_takeover_event_runs_without_identity(self):
        with patch.object(self.task, '_ensure_event_menu'), \
                patch.object(self.task, '_resolve_takeover_identity', return_value=None), \
                patch.object(self.task, '_run_event_subflows') as subflows_mock:
            self.task._takeover_event()
        subflows_mock.assert_called_once()  # 身份未知按现状执行。
        self.assertIsNone(self.task._event_identity)

    def test_takeover_event_tolerates_menu_navigation_failure(self):
        # 往期活动/档案馆页面退不回活动菜单页时按当前页面继续（子流程各自探测入口），不让整条接管失败。
        with patch.object(self.task, '_ensure_event_menu', side_effect=WaitFailedException('退不回菜单页')), \
                patch.object(self.task, '_resolve_takeover_identity', return_value=None), \
                patch.object(self.task, '_run_event_subflows') as subflows_mock, \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._takeover_event()
        subflows_mock.assert_called_once()  # 仍要跑子流程（剧情入口可能就在当前页上）。
        warn_mock.assert_called_once()

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
        assert_called_once_semantic(transition_mock, 'event_main', click=self.task._click_back_to_menu)

    def test_click_back_to_menu_uses_base_back_lookup(self):
        # 活动子页返回键样式逐期变（common_back 模板在签到页实测仅 0.41），走基类三层兜底定位。
        back = Box(26, 1342, 37, 35, confidence=1, name='common_back')
        with patch.object(self.task, '_find_back_button', return_value=back) as find_mock, \
                patch.object(self.task, 'click_box') as click_mock:
            self.task._click_back_to_menu()
        find_mock.assert_called_once()
        assert_called_once_semantic(click_mock, back)

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
        assert_last_call_semantic(transition_mock, 'event_main', click=self.task._click_back_to_menu)

    def test_ensure_event_menu_leaves_story_sub_page_on_takeover(self):
        # 接管时人在剧情子页面上：先退一级回地图页，落地后确认菜单可见即停（不再多点一次返回键）。
        with patch.object(self.task, '_probe_event_main', return_value=True), \
                patch.object(self.task, '_detail_page_open', return_value=False), \
                patch.object(self.task, '_probe_story_sub_page', side_effect=[True, False]), \
                patch.object(self.task, 'transition') as transition_mock:
            self.task._ensure_event_menu()
        assert_called_once_semantic(transition_mock, 'event_main', click=self.task._click_back_to_menu)

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
            self.assertTrue(self.task._enter_and_probe(row))  # 确认为活动：返回 True。
        assert_called_once_semantic(click_mock, row)  # 10s 覆盖过场动画 + 菜单稳定。
        menu_ready_mock.assert_called_once()  # 进入确认后先等菜单栏就绪再探测入口。
        subflows_mock.assert_called_once()

    def test_enter_and_probe_non_event_card_returns_to_lobby(self):
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=False), \
                patch.object(self.task, '_recover_to_lobby') as recover_mock, \
                patch.object(self.task, '_run_event_subflows', side_effect=AssertionError('非活动不应执行子流程')):
            self.assertFalse(self.task._enter_and_probe(row))  # 非活动条目：返回 False。
        recover_mock.assert_called_once()

    def test_enter_event_returns_true_and_waits_menu(self):
        row = Box(10, 10, 20, 20, confidence=1, name='row')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=True), \
                patch.object(self.task, '_wait_menu_ready') as menu_ready_mock, \
                patch.object(self.task, '_run_event_subflows', side_effect=AssertionError('_enter_event 不应执行子流程')):
            self.assertTrue(self.task._enter_event(row))
        assert_called_once_semantic(click_mock, row)  # 点击卡片进入。
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

    def test_entry_locked_skip_detects_locked_entry(self):
        entry = Box(60, 10, 30, 10, confidence=1, name='挑战')
        with patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, '_entry_locked', return_value=True):
            self.assertTrue(self.task._entry_locked_skip('挑战'))  # 文字可读但整行灰暗 = 点击无效。
        with patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, '_entry_locked', return_value=False):
            self.assertFalse(self.task._entry_locked_skip('挑战'))  # 非锁定态不跳过。
        with patch.object(self.task, '_entry_box', return_value=None), \
                patch.object(self.task, '_entry_locked', side_effect=AssertionError('定位不到不应判态')):
            self.assertFalse(self.task._entry_locked_skip('挑战'))  # 定位不到（与 _probe_entry 不一致）保守按可用。

    def test_do_checkin_skips_locked_entry(self):
        self.task.config['签到'] = True
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, '_entry_locked_skip', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('锁定入口不应执行')):
            self.task._do_checkin()

    def test_do_challenge_skips_locked_entry(self):
        self.task.config['挑战'] = True
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, '_entry_locked_skip', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('锁定入口不应执行')):
            self.task._do_challenge()

    def test_do_mission_skips_locked_entry(self):
        self.task.config['任务'] = True
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, '_entry_locked_skip', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('锁定入口不应执行')):
            self.task._do_mission()

    def test_do_shop_skips_locked_entry(self):
        self.task.config['商店'] = True
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, '_entry_locked_skip', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('锁定入口不应执行')):
            self.task._do_shop()

    # ---- 子流程的身份化完成状态（签到/商店按活动各记一次） ----

    def _authoritative_identity(self, key):
        """把任务置于「列表路径处理中」状态：当前活动身份权威（允许落盘）。"""
        self.task._event_identity = event_identity(key)
        self.task._identity_authoritative = True

    def test_do_checkin_skips_when_identity_key_done(self):
        self.task.config['签到'] = True
        self._authoritative_identity('key1')
        self.task.mark_done(event_done_key(event_identity('key1'), 'checkin'), 'day')
        with patch.object(self.task, '_probe_entry', side_effect=AssertionError('已完成不应探测')), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('已完成不应执行')):
            self.task._do_checkin()

    def test_do_checkin_marks_identity_key_after_success(self):
        self.task.config['签到'] = True
        self._authoritative_identity('key1')
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, 'try_step', return_value=True):
            self.task._do_checkin()
        self.assertTrue(self.task.is_done(event_done_key(event_identity('key1'), 'checkin'), 'day'))

    def test_do_checkin_does_not_mark_when_flow_fails(self):
        self.task.config['签到'] = True
        self._authoritative_identity('key1')
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, 'try_step', return_value=False):
            self.task._do_checkin()
        self.assertFalse(self.task.is_done(event_done_key(event_identity('key1'), 'checkin'), 'day'))  # 失败不落盘，下次可重试。

    def test_do_shop_skips_when_identity_key_done(self):
        self.task.config['商店'] = True
        self._authoritative_identity('key1')
        self.task.mark_done(event_done_key(event_identity('key1'), 'shop'), 'day')
        with patch.object(self.task, '_probe_entry', side_effect=AssertionError('已完成不应探测')), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('已完成不应执行')):
            self.task._do_shop()

    def test_do_shop_marks_identity_key_after_success(self):
        self.task.config['商店'] = True
        self._authoritative_identity('key1')
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, 'try_step', return_value=True):
            self.task._do_shop()
        self.assertTrue(self.task.is_done(event_done_key(event_identity('key1'), 'shop'), 'day'))

    def test_subflow_keys_isolated_per_event(self):
        # 身份键按活动隔离：A 的签到完成不影响 B 的判定（旧聚合键会串台）。
        self._authoritative_identity('a')
        self.task._mark_subflow_done('签到')
        self.assertTrue(self.task._subflow_completed('签到'))
        self.task._event_identity = event_identity('b')
        self.assertFalse(self.task._subflow_completed('签到'))

    def test_subflow_completed_false_without_identity(self):
        self.task.mark_done(event_done_key(event_identity('key1'), 'checkin'), 'day')
        self.task._event_identity = None
        self.assertFalse(self.task._subflow_completed('签到'))  # 身份未知：按未完成处理（不读键）。

    def test_subflow_mark_skipped_for_inferred_identity(self):
        # 接管路径身份只读：签到跑完也不落盘，避免把推断出来的身份误标成已完成。
        self.task.config['签到'] = True
        self.task._event_identity = event_identity('key1')
        self.task._identity_authoritative = False
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, 'try_step', return_value=True):
            self.task._do_checkin()
        self.assertFalse(self.task.is_done(event_done_key(event_identity('key1'), 'checkin'), 'day'))

    def test_subflow_key_none_when_flow_not_identity_scoped(self):
        self._authoritative_identity('key1')
        self.assertIsNone(self.task._subflow_key('挑战'))  # 幂等流程不按身份记。
        self.assertEqual(event_done_key(event_identity('key1'), 'shop'), self.task._subflow_key('商店'))

    # ---- 签到印章流程（仅大活动；面板判据走 OCR 文字，同登录奖励） ----

    def _claim_all_box(self):
        return Box(1150, 1250, 260, 60, confidence=1, name='全部领取')

    def test_find_claim_all_scans_panel_region(self):
        hit = self._claim_all_box()
        with patch.object(self.task, 'box_of_screen', return_value=Box(0, 0, 10, 10, confidence=1, name='area')), \
                patch.object(self.task, 'ocr', return_value=[hit]) as ocr_mock:
            found = self.task._find_claim_all()
        self.assertEqual(hit, found)
        ocr_mock.assert_called_once()
        from src.tasks.event._const import _CLAIM_ALL_TEXT
        self.assertEqual([_CLAIM_ALL_TEXT], ocr_mock.call_args.kwargs['match'])  # 用固定文案判据。

    def test_find_claim_all_returns_none_without_hit(self):
        with patch.object(self.task, 'box_of_screen', return_value=Box(0, 0, 10, 10, confidence=1, name='area')), \
                patch.object(self.task, 'ocr', return_value=[]):
            self.assertIsNone(self.task._find_claim_all())

    def test_claim_button_box_pads_text_box(self):
        from src.tasks.event._const import _CLAIM_ALL_PAD
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
        assert_any_call_semantic(click_mock, entry)  # 点签到入口。
        assert_any_call_semantic(click_mock, claim)  # 点全部领取。
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
        from src.tasks.event._const import _SD_ARRIVE_TIMEOUT
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
        from src.tasks.event._const import _MISSION_SUBTITLE_BOX, _MISSION_SUBTITLE_TEXT
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
        assert_any_call_semantic(click_mock, entry)  # 点任务入口弹出弹窗。
        from src.tasks.event._const import _MISSION_READY_TIMEOUT
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
        from src.tasks.event._const import _MISSION_ICON_BOX
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
        from src.tasks.event._const import _MISSION_TABS
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
        from src.tasks.event._const import _MISSION_DAILY_SUBTITLE_BOX
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
        assert_called_once_semantic(click_mock, tab)  # 点栏目标签。
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
                patch.object(self.task, 'wait_until', side_effect=AssertionError('灰白不应推进领取节奏')):
            self.task._claim_mission_rewards()

    def test_claim_mission_rewards_stops_when_claim_text_missing(self):
        with patch.object(self.task, '_find_claim_all', return_value=None), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('未识别到按钮不应点击')), \
                patch.object(self.task, 'wait_until', side_effect=AssertionError('未识别到按钮不应推进领取节奏')), \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._claim_mission_rewards()
        warn_mock.assert_called_once()

    def test_claim_mission_rewards_paces_on_second_stage_ready(self):
        # 每日任务栏目是两段式（第一段领积分不弹遮罩）：点完按「重新可领」推进，不要求必须出遮罩。
        claim = self._claim_all_box()
        with patch.object(self.task, '_find_claim_all', return_value=claim), \
                patch.object(self.task, 'is_feature_enabled', side_effect=[True, False]), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=True) as wait_mock:
            self.task._claim_mission_rewards()
        self.assertEqual(1, click_mock.call_count)  # 第一轮点击；第二轮按钮灰白退出。
        wait_mock.assert_called_once()  # 每轮点完等第二段重新可领。
        args, kwargs = wait_mock.call_args
        self.assertEqual('_claim_all_claimable', args[0].__func__.__name__)  # 判据是「重新可领」，而非遮罩必须出现。
        from src.tasks.event._const import _MISSION_CLAIM_SETTLE, _MISSION_CLAIM_SETTLE_TIMEOUT
        self.assertEqual(_MISSION_CLAIM_SETTLE_TIMEOUT, kwargs['time_out'])  # 给第二段渲染留出窗口。
        self.assertEqual(_MISSION_CLAIM_SETTLE, kwargs['settle_time'])  # 可领后稳定确认，吸收按钮入场动画。
        self.assertFalse(kwargs['raise_if_not_found'])  # 超时静默，不抛异常，由下一轮灰白判态兜底。
        self.assertTrue(callable(kwargs['pre_action']))  # 等待期间仍清掉可能弹出的奖励遮罩。

    def test_claim_mission_rewards_continues_when_second_stage_late(self):
        # 第二段晚到（wait_until 未确认到「重新可领」）不提前停止：静默进入下一轮，由灰白判态兜底收尾。
        claim = self._claim_all_box()
        with patch.object(self.task, '_find_claim_all', return_value=claim), \
                patch.object(self.task, 'is_feature_enabled', side_effect=[True, False]), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=False) as wait_mock:
            self.task._claim_mission_rewards()
        self.assertEqual(1, click_mock.call_count)  # 第一轮点击；下一轮灰白退出。
        wait_mock.assert_called_once()  # 点击后仍等待第二段就绪，超时不立即停止。

    def test_claim_mission_rewards_hits_click_limit(self):
        from src.tasks.event._const import _MISSION_CLAIM_MAX_CLICKS
        claim = self._claim_all_box()
        with patch.object(self.task, '_find_claim_all', return_value=claim), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=True) as wait_mock, \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._claim_mission_rewards()
        self.assertEqual(_MISSION_CLAIM_MAX_CLICKS, click_mock.call_count)  # 每轮都点，到上限为止。
        self.assertEqual(_MISSION_CLAIM_MAX_CLICKS, wait_mock.call_count)  # 每轮点完都等第二段就绪。
        warn_mock.assert_called_once()  # 上限耗尽告警（防死循环）。

    def test_close_claim_overlay_tolerates_missing_mask(self):
        # 领奖遮罩非必现：没弹遮罩不算失败，否则一次没领到就把整条子流程判成失败（实机事故根因）。
        with patch.object(self.task, 'close_overlay') as overlay_mock:
            self.task._close_claim_overlay()
        kwargs = overlay_mock.call_args.kwargs
        self.assertIs(False, kwargs['require_click'])  # 关掉基类「必须点到遮罩」的必现语义。
        patterns = kwargs['keywords']
        self.assertTrue(any(p.search('点击领取奖励') for p in patterns))  # 覆盖领奖遮罩。

    def test_other_claim_all_panel_present_follows_mission_popup(self):
        # 活动任务弹窗也带「全部领取」：弹窗在即声明「不是登录奖励面板」，避免被基类当登录奖励误点。
        with patch.object(self.task, '_mission_popup_ready', return_value=True) as ready_mock:
            self.assertTrue(self.task._other_claim_all_panel_present())
        ready_mock.assert_called_once()  # 判据完全复用弹窗就位判定。
        with patch.object(self.task, '_mission_popup_ready', return_value=False):
            self.assertFalse(self.task._other_claim_all_panel_present())  # 弹窗不在时不干扰登录奖励面板清理。

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
        assert_called_once_semantic(transition_mock, 'event_challenge_page', box=entry)  # 守卫式进入（补点不中断小人行为）。
        back_mock.assert_called_once()  # 收尾点返回回菜单页。

    def test_flow_challenge_raises_when_page_not_reached(self):
        # transition 确认挑战页失败，且落点不是活动菜单页（异常落点）：抛异常由 try_step 恢复。
        entry = self._challenge_entry()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'transition', side_effect=WaitFailedException('进入挑战页失败')), \
                patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_ensure_event_menu', side_effect=AssertionError('未进入不应收尾')):
            self.assertRaises(WaitFailedException, self.task._flow_challenge)

    def test_flow_challenge_skips_inert_entry_without_retry(self):
        # 往期活动/未开放入口：文字可读但点击无响应（仍停在活动菜单页）→ 直接跳过，
        # 不再抛异常让 try_step 把补点重来三遍（每次白等一分多钟）。
        entry = self._challenge_entry()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'transition', side_effect=WaitFailedException('点不动')), \
                patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, '_wait_challenge_nodes', side_effect=AssertionError('无效入口不应继续选关')), \
                patch.object(self.task, '_ensure_event_menu', side_effect=AssertionError('已在菜单页无需收尾')):
            self.task._flow_challenge()  # 正常返回（跳过）。

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
        assert_any_call_semantic(click_mock, click)  # 点左移后的关卡点击框进详情页。
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
        assert_any_call_semantic(click_mock, battle)  # 点「战斗」进战斗界面。
        skip_mock.assert_called_once()  # 进战斗可能先播剧情，尝试跳过。
        battle_wait.assert_called_once()  # 等战斗结束。
        assert_any_call_semantic(click_mock, confirm)  # 点结算返回键。
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
        assert_any_call_semantic(click_mock, click)  # 仍点了左移后的关卡点击框进详情页。
        close_mock.assert_called_once_with(to_screen='event_challenge_page')  # 关详情页回挑战页。
        back_mock.assert_called_once()  # 回菜单。

    def test_flow_challenge_retries_stage_click_then_enters_detail(self):
        # 首次点击没打开详情页（点空）：补点一次，第二次进入详情页后照常走战斗分支。
        from src.tasks.event._const import _CHALLENGE_CLICK_ATTEMPTS
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
        from src.tasks.event._const import _CHALLENGE_CLICK_ATTEMPTS
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
        from src.tasks.event._const import _CHALLENGE_CLICK_X_OFFSET
        stage = self._challenge_stage()
        with patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=2560), \
                patch('src.tasks.event._challenge.random.randint', return_value=250) as randint_mock:
            click = self.task._challenge_click_box(stage)
        self.assertEqual((int(2560 * _CHALLENGE_CLICK_X_OFFSET[0]), int(2560 * _CHALLENGE_CLICK_X_OFFSET[1])),
                         randint_mock.call_args.args)  # 左移量在区间内随机取（占屏宽比例换算成像素）。
        self.assertEqual(Box(stage.x - 250, stage.y, stage.width, stage.height, confidence=1,
                             name='event_challenge_stage'), click)

    def test_challenge_click_box_offset_degrades_when_screen_too_narrow(self):
        # 分辨率极小时区间换算成同一像素：退化为定值，不抛异常。
        stage = self._challenge_stage()
        with patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=8), \
                patch('src.tasks.event._challenge.random.randint', side_effect=AssertionError('区间退化不应取随机')):
            click = self.task._challenge_click_box(stage)
        self.assertEqual(Box(stage.x, stage.y, stage.width, stage.height, confidence=1,
                             name='event_challenge_stage'), click)  # 左移量为 0。

    def test_wait_challenge_nodes_polls_until_rendered(self):
        # 过场动画吸收：等关卡节点渲染出来再多等一会才继续（区域 + 特征名 + 到达窗口 + 停稳窗口都传给轮询）。
        from src.tasks.event._const import _CHALLENGE_PAGE_SETTLE, _CHALLENGE_STAGE_FEATURE, _SD_ARRIVE_TIMEOUT
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
        from src.tasks.event._const import _SWEEP_PAGE_FEATURE, _SWEEP_START_BOX
        quick = self._challenge_quick_box()
        max_btn = Box(1424, 991, 75, 44, confidence=1, name='custom_quick_battle_max')
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature') as wait_mock, \
                patch.object(self.task, 'find_one', return_value=max_btn), \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)):
            result = self.task._run_quick_battle(quick, label='挑战')
        self.assertEqual('success', result)
        assert_any_call_semantic(click_mock, quick)  # 点快速战斗。
        assert_any_call_semantic(click_mock, max_btn)  # 拉满次数。
        assert_any_call_semantic(click_mock, _SWEEP_START_BOX)  # 点开始。
        assert_any_call_semantic(click_mock, confirm)  # 点结算确认。
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
        assert_called_once_semantic(click_mock, 'stage_detail_close', raise_if_not_found=True)
        assert_called_once_semantic(assert_mock, 'event_challenge_page')

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
        from src.tasks.event._const import _MENU_BAND_BOXES
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
        # 菜单带首区命中任一入口关键词即视为就绪：只 OCR 一次即短路返回。
        menu = Box(0, 0, 100, 50, confidence=1, name='menu')
        hit = Box(10, 10, 30, 10, confidence=1, name='加成')
        with patch.object(self.task, 'wait_until', side_effect=lambda condition, **kwargs: condition()), \
                patch.object(self.task, '_menu_boxes', return_value=[menu]), \
                patch.object(self.task, 'ocr', return_value=[hit]) as ocr_mock:
            self.task._wait_menu_ready()
        self.assertEqual(1, ocr_mock.call_count)  # 首区命中即短路，不查其余菜单带。
        self.assertIs(menu, ocr_mock.call_args.kwargs['box'])  # OCR 限定在菜单区域内。

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

    def test_list_area_box_reads_banner_area(self):
        # 活动列表滚动区：取 coco 标注 box_event_banner_area；特征缺失返回 None（不可滚动）。
        box = Box(950, 342, 729, 867, confidence=1, name='box_event_banner_area')
        with patch.object(self.task, 'get_box_by_name', return_value=box) as get_mock:
            self.assertEqual(box, self.task._list_area_box())
        get_mock.assert_called_once_with(event_calendar.SEARCH_BOX)
        with patch.object(self.task, 'get_box_by_name', side_effect=ValueError('missing')):
            self.assertIsNone(self.task._list_area_box())

    # ---- 剧情关卡页：OCR 接线与行锚点切片（方案 §5/§11 ③） ----

    def test_ocr_region_maps_framework_boxes(self):
        # 唯一的 OCR 缝：裁剪 → 引擎 OCR → 解析层 Block（分块/去重/切片都在 event_stage，见 TestEventStage）。
        frame = np.zeros((960, 960, 3), dtype=np.uint8)
        listed = Box(100, 200, 30, 40, confidence=0.93, name='1-06')
        with patch.object(type(self.task), 'frame', new_callable=PropertyMock, return_value=frame), \
                patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=2560), \
                patch.object(type(self.task), 'height', new_callable=PropertyMock, return_value=1440), \
                patch.object(self.task, 'ocr', return_value=[listed]) as ocr_mock:
            blocks = self.task._ocr_region(Box(0, 0, 960, 960, confidence=1, name='list'))
        self.assertEqual(1, len(blocks))  # 引擎 Box -> 解析层 Block。
        self.assertEqual('1-06', blocks[0].text)
        self.assertEqual(0.93, blocks[0].score)
        self.assertEqual((100, 200, 130, 240), (blocks[0].x1, blocks[0].y1, blocks[0].x2, blocks[0].y2))
        self.assertEqual((960, 960, 3), ocr_mock.call_args.kwargs['frame'].shape)  # 标定分辨率：原尺寸送引擎。

    def test_ocr_region_upscales_small_region_and_maps_back(self):
        # 低于标定分辨率时先按 ocr_upscale 放大再送引擎，结果框再除以倍数映射回整图。
        frame = np.zeros((400, 400, 3), dtype=np.uint8)
        local = Box(20, 40, 10, 20, confidence=0.9, name='1-06')  # 预放大后的裁剪图坐标。
        with patch.object(type(self.task), 'frame', new_callable=PropertyMock, return_value=frame), \
                patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=1600), \
                patch.object(type(self.task), 'height', new_callable=PropertyMock, return_value=900), \
                patch.object(self.task, 'ocr', return_value=[local]) as ocr_mock:
            blocks = self.task._ocr_region(Box(100, 200, 200, 200, confidence=1, name='tile'))
        self.assertEqual(event_stage.OCR_UPSCALE_MAX, event_stage.ocr_upscale(Box(100, 200, 200, 200), 0.625))
        self.assertEqual((400, 400, 3), ocr_mock.call_args.kwargs['frame'].shape)  # 200x200 × 2 倍。
        self.assertEqual((110, 220, 115, 230), (blocks[0].x1, blocks[0].y1, blocks[0].x2, blocks[0].y2))

    def test_ocr_region_drops_empty_text_and_without_frame(self):
        empty = Box(1, 1, 2, 2, confidence=0.9, name='')
        frame = np.zeros((960, 960, 3), dtype=np.uint8)
        with patch.object(type(self.task), 'frame', new_callable=PropertyMock, return_value=frame), \
                patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=2560), \
                patch.object(type(self.task), 'height', new_callable=PropertyMock, return_value=1440), \
                patch.object(self.task, 'ocr', return_value=[empty]):
            self.assertEqual([], self.task._ocr_region(Box(0, 0, 960, 960, confidence=1, name='list')))
        with patch.object(type(self.task), 'frame', new_callable=PropertyMock, return_value=None), \
                patch.object(self.task, 'ocr', side_effect=AssertionError('无帧不应调引擎')):
            self.assertEqual([], self.task._ocr_region(Box(0, 0, 960, 960, confidence=1, name='list')))

    def test_stage_list_box_missing_returns_none(self):
        with patch.object(self.task, 'get_box_by_name', side_effect=ValueError('missing')):
            self.assertIsNone(self.task._stage_list_box())

    def test_stage_list_box_expands_to_full_height(self):
        # 列表区标注只在某一期活动标定：横向稳定、纵向逐期不同，故纵向拉满整屏，避免别的活动列表更高/更靠上被切掉行。
        annotated = Box(950, 342, 729, 867, confidence=1, name='box_event_stage_list')
        with patch.object(self.task, 'get_box_by_name', return_value=annotated), \
                patch.object(type(self.task), 'height', new_callable=PropertyMock, return_value=1440):
            box = self.task._stage_list_box()
        self.assertEqual((950, 0, 729, 1440), (box.x, box.y, box.width, box.height))

    def test_stage_list_box_keeps_annotation_without_height(self):
        # 无有效屏高（无帧/单测）：保守用标注框，不臆造整屏高度。
        annotated = Box(950, 342, 729, 867, confidence=1, name='box_event_stage_list')
        with patch.object(self.task, 'get_box_by_name', return_value=annotated), \
                patch.object(type(self.task), 'height', new_callable=PropertyMock, return_value=0):
            box = self.task._stage_list_box()
        self.assertEqual((950, 342, 729, 867), (box.x, box.y, box.width, box.height))

    # 行窄带切片（band_* / anchor_bands / uniform_bands / _stage_blocks）与流水线已归 event_stage，
    # 对应用例见 tests/TestEventStage.py 的 TestEventStageLayout / TestEventStagePipeline。

    def test_stage_rows_parses_list_region(self):
        # 关卡行由 event_stage 的读取流水线筛出：这里验证接线（取列表区 → 读块 → 出编号行）。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        blocks = [event_stage.Block(text='1-06', score=0.9, x1=1200, y1=400, x2=1260, y2=440),
                  event_stage.Block(text='CLEAR', score=0.9, x1=1200, y1=483, x2=1280, y2=513),  # 状态文案块：解析层不看。
                  event_stage.Block(text='1-07', score=0.9, x1=1200, y1=520, x2=1260, y2=560)]
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(self.task, '_ocr_region', return_value=blocks) as ocr_mock:
            rows = self.task._stage_rows()
        self.assertEqual(['1-06', '1-07'], [row.stage_id for row in rows])  # 只留编号行，状态不在这里判。
        self.assertEqual(list_box, ocr_mock.call_args_list[0].args[0])  # 首次调用拿到的就是列表区矩形。

    def test_stage_rows_returns_empty_without_region(self):
        with patch.object(self.task, '_stage_list_box', return_value=None), \
                patch.object(self.task, 'ocr', side_effect=AssertionError('区域缺失不应 OCR')):
            self.assertEqual([], self.task._stage_rows())

    def test_stage_rows_passes_frame_height_and_scale(self):
        # 兜底行距与窄带夹紧依赖分辨率：调用层把帧高与缩放比一起透传给 event_stage.read_rows。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(type(self.task), 'width', new_callable=PropertyMock, return_value=1920), \
                patch.object(type(self.task), 'height', new_callable=PropertyMock, return_value=1080), \
                patch.object(event_stage, 'read_rows', return_value=([], [])) as read_mock:
            self.task._stage_rows()
        args = read_mock.call_args.args
        self.assertEqual(list_box, args[1])  # 列表区。
        self.assertEqual(1080, args[2])  # frame_height（窄带夹紧与跨层去重容差）。
        self.assertAlmostEqual(0.75, args[3])  # scale（兜底行距按它缩放）。

    def test_stage_rows_logs_strategy_notes(self):
        # 策略轨迹在下层产生、在任务侧按自己的日志级别呈现（流水线搬走后降级原因仍可见）。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        note = '编号块 0 个且无行锚点，按标定行距均匀切片补扫 7 条'
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(event_stage, 'read_rows', return_value=([], [note])), \
                patch.object(self.task, 'log_info') as log_mock:
            self.task._stage_rows()
        self.assertIn(note, [call.args[0] for call in log_mock.call_args_list])

    def test_swipe_list_up_uses_list_start_ratio(self):
        # 活动列表的滚动手势：起点在区域内垂直 0.8 处、终点 0.55 处（自下往上滑）。
        from src.tasks.event._const import _SWIPE_START_RATIO
        box = Box(950, 342, 729, 867, confidence=1, name='list')
        with patch.object(self.task, 'swipe') as swipe_mock:
            self.task._swipe_list_up(box)
        x1, y1, x2, y2 = swipe_mock.call_args.args
        self.assertEqual(box.x + box.width // 2, x1)
        self.assertEqual(int(box.y + box.height * _SWIPE_START_RATIO), int(y1))  # 起点 = 区域内垂直 0.8。
        self.assertLess(y2, y1)  # 自下往上滑。

    # ---- 剧情入口定位与执行链（方案 §8 ④：点行 → 剧情跳过 → 连续战斗 → 回关卡页） ----

    def _story_row(self, stage_id='1-05'):
        """构造一行解析结果（剧情推图链测试用）。"""
        return event_stage.StageRef(stage_id=stage_id, box=(950, 400, 1679, 520),
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

    def test_entry_box_normalizes_roman_numerals(self):
        # 实机 OCR 把菜单栏美术字的「STORY II」读成 "STORYⅡI"（U+2161）/ "STORYⅢ"（U+2162）：
        # 归一成 ASCII 后仍按关键词顺序命中 STORY II，不再静默回落到 STORY I。
        menu = Box(0, 0, 100, 50, confidence=1, name='band')
        hits = [Box(10, 10, 30, 10, confidence=1, name='STORYI'),
                Box(60, 10, 30, 10, confidence=1, name='STORY\u2161I')]
        with patch.object(self.task, '_menu_boxes', return_value=[menu]), \
                patch.object(self.task, 'ocr', return_value=hits):
            found = self.task._entry_box('剧情')
        self.assertIs(hits[1], found)  # STORY II 命中框优先于 STORY I（原命中框对象直接复用）。
        self.assertEqual('STORYIII', found.name)  # 命中框文本已归一为 ASCII。
        self.assertTrue(self.task._is_story_main_entry(found))  # 归一后仍是「菜单页 STORY 入口」。
        with patch.object(self.task, '_menu_boxes', return_value=[menu]), \
                patch.object(self.task, 'ocr',
                             return_value=[Box(60, 10, 30, 10, confidence=1, name='STORY\u2162')]):
            self.assertEqual('STORYIII', self.task._entry_box('剧情').name)  # 同一行的另一种误读（U+2162）。

    def test_entry_box_returns_none_without_menu_band(self):
        with patch.object(self.task, '_menu_boxes', return_value=[]), \
                patch.object(self.task, 'ocr', side_effect=AssertionError('无菜单带不应 OCR')):
            self.assertIsNone(self.task._entry_box('剧情'))

    def test_entry_box_shifts_small_event_story_click_up(self):
        # 小活动剧情入口「加成奖励妮姬」：命中文字在按钮下缘，点击框沿 Y 轴上移 0.08 屏高落到上方 ENTER。
        menu = Box(0, 0, 100, 50, confidence=1, name='band')
        hit = Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')
        with patch.object(self.task, '_menu_boxes', return_value=[menu]), \
                patch.object(self.task, 'ocr', return_value=[hit]), \
                _fixed_height(self.task, 1000):
            found = self.task._entry_box('剧情')
        self.assertEqual(700 - 80, found.y)  # 上移 0.08 × 1000 = 80px。
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
        self.task.config['剧情'] = True  # 推图默认关闭，本用例验证推图链。
        story = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        sub_entry = Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')
        with patch.object(self.task, '_nav_to_event_main') as nav_mock, \
                patch.object(self.task, '_entry_box', side_effect=[story, sub_entry]) as entry_mock, \
                patch.object(self.task, '_enter_story_sub_page') as sub_page_mock, \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, '_push_stages', return_value=True) as push_mock, \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_story()
        nav_mock.assert_called_once()  # 子流程闸门：就位活动主页（恢复回大厅后由此重入）。
        sub_page_mock.assert_called_once()  # 先在菜单页内逐个尝试 STORY 入口并等剧情子页面就位。
        self.assertEqual(2, entry_mock.call_count)  # 子页面内重新定位剧情入口。
        self.assertEqual(['event_stage_page'],
                         [call.args[0] for call in transition_mock.call_args_list])  # 从剧情子页面入口进关卡页。
        self.assertEqual(sub_entry, transition_mock.call_args_list[0].kwargs['box'])  # 用子页面入口命中框点击。
        push_mock.assert_called_once_with()  # 进关卡页后推图（可推性由 _push_stages 自己后验）。
        back_mock.assert_called_once()  # 收尾回活动菜单页（大活动由它多退一级）。

    def test_flow_story_small_event_enters_stage_page_directly(self):
        # 小活动：主页「加成」入口就是关卡页入口，不进剧情子页面。
        self.task.config['剧情'] = True  # 推图默认关闭，本用例验证推图链。
        entry = Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry) as entry_mock, \
                patch.object(self.task, '_enter_story_sub_page', side_effect=AssertionError('小活动不应进子页面')), \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, '_push_stages') as push_mock, \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_story()
        entry_mock.assert_called_once()  # 只定位一次入口。
        self.assertEqual(entry, transition_mock.call_args_list[0].kwargs['box'])  # 直接用该入口进关卡页。
        push_mock.assert_called_once_with()  # 推图（本轮收工）。
        back_mock.assert_called_once()  # 收尾回活动菜单页。

    def test_flow_story_without_pushable_stage_only_returns_to_event_main(self):
        # 无可推关卡（_push_stages 收工返回 True）→ 结束推图、不扫荡，仍要回活动菜单页。
        self.task.config['剧情'] = True  # 打开推图才走「找可推关卡」这条路。
        self.task.config['扫荡'] = False  # 只验证收尾导航这一条路径。
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')), \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, '_push_stages', return_value=True) as push_mock, \
                patch.object(self.task, '_ensure_event_menu') as back_mock:
            self.task._flow_story()
        self.assertEqual(['event_stage_page'],
                         [call.args[0] for call in transition_mock.call_args_list])  # 仍要走关卡页。
        push_mock.assert_called_once_with()  # 可推性在 _push_stages 内部后验。
        back_mock.assert_called_once()  # 无目标也要回菜单页。

    def test_flow_story_tolerates_menu_navigation_failure(self):
        # 往期活动/档案馆页面退不回活动菜单页：剧情已推进完 → 记告警继续，不把整条剧情判失败。
        self.task.config['扫荡'] = False  # 只验证收尾导航这一条路径。
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')), \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_push_stages', return_value=True), \
                patch.object(self.task, '_ensure_event_menu', side_effect=WaitFailedException('退不回菜单页')), \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._flow_story()  # 不抛异常。
        self.assertTrue(any('剧情收尾' in call.args[0] for call in warn_mock.call_args_list))  # 记录降级原因。

    def test_try_enter_story_sub_page_clicks_and_waits_for_entry(self):
        # 剧情子页面无独有界面判据 → 点 STORY 入口后轮询等「加成」类入口出现（反向判就位）。
        from src.tasks.event._const import _SD_ARRIVE_TIMEOUT
        story = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_until', return_value=True) as wait_mock:
            ready = self.task._try_enter_story_sub_page(story)
        self.assertTrue(ready)  # 子页面就位即成功。
        assert_called_once_semantic(click_mock, story)  # 只点一次（切页不需补点）。
        self.assertEqual(_SD_ARRIVE_TIMEOUT, wait_mock.call_args.kwargs['time_out'])  # 用子页面到达窗口。

    def test_try_enter_story_sub_page_returns_false_when_not_ready(self):
        # 未开放的章节点开不切页：只返回 False（不抛异常），由调用方回落下一个入口。
        story = Box(60, 10, 30, 10, confidence=1, name='STORY II')
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, 'wait_until', return_value=False):
            self.assertFalse(self.task._try_enter_story_sub_page(story))

    def test_story_entry_boxes_orders_story_ii_before_story_i(self):
        # 候选顺序 = _STORY_MENU_PATTERNS 顺序（STORY II 优先），且逐个关键词单独定位；未出现的入口不进候选。
        from src.tasks.event._const import _STORY_MENU_PATTERNS
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
        from src.tasks.event._const import _STORY_MENU_PATTERNS
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
        from src.tasks.event._const import _STORY_MENU_PATTERNS
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

    # ---- 可推关卡定位（界面后验：自下而上点开候选行，看详情页「战斗」是否可用） ----

    def test_open_pushable_stage_uses_current_screen(self):
        # 进关卡页游戏会自动定位到当前进度关：只看当前屏，不滚动也不跨屏扫描。
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        rows = [self._story_row('1-04'), self._story_row('1-05')]
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=rows) as stage_rows_mock, \
                patch.object(self.task, '_open_first_pushable', return_value=True) as open_mock, \
                patch.object(self.task, '_scroll_list_to_top', side_effect=AssertionError('推图不应滚动')), \
                patch.object(self.task, '_scroll_list_down', side_effect=AssertionError('推图不应滚动')):
            self.assertTrue(self.task._open_pushable_stage())
        self.assertEqual(box, stage_rows_mock.call_args.args[0])  # 只解析当前屏。
        self.assertEqual(rows, open_mock.call_args.args[0])  # 当前屏候选行交给点开流程。

    def test_open_pushable_stage_returns_false_when_no_row_pushable(self):
        # 当前屏有候选行但都点不出可推的关（已全通或未开放）= 本地区推完了。
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=[self._story_row('1-04')]), \
                patch.object(self.task, '_open_first_pushable', return_value=False), \
                patch.object(self.task, '_scroll_list_down', side_effect=AssertionError('推图不应滚动')):
            self.assertFalse(self.task._open_pushable_stage())

    def test_open_pushable_stage_warns_when_current_screen_empty(self):
        # 当前屏一行都没解析出（OCR 漏检/页面未就绪）：不滚动找，但按告警记（与「有行但都不可推」分开）。
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=[]), \
                patch.object(self.task, '_scroll_list_to_top', side_effect=AssertionError('推图不应滚动')), \
                patch.object(self.task, '_scroll_list_down', side_effect=AssertionError('推图不应滚动')), \
                patch.object(self.task, 'log_warning') as warn_mock, \
                patch.object(self.task, 'log_info', side_effect=AssertionError('空结果不应按「已全通」记 info')):
            self.assertFalse(self.task._open_pushable_stage())
        self.assertTrue(any('未解析出任何关卡行' in call.args[0] for call in warn_mock.call_args_list))

    def test_open_pushable_stage_returns_false_without_region(self):
        with patch.object(self.task, '_stage_list_box', return_value=None), \
                patch.object(self.task, '_stage_rows', side_effect=AssertionError('区域缺失不应解析')):
            self.assertFalse(self.task._open_pushable_stage())

    def test_open_first_pushable_tries_bottom_up(self):
        # 列表顺序 = 解锁顺序：最下面的候选行最接近当前进度关，从它开始往上试，命中即停。
        rows = [self._story_row('1-04'), self._story_row('1-05'), self._story_row('1-06')]
        with patch.object(self.task, '_open_row_for_push', side_effect=[False, True]) as open_mock:
            self.assertTrue(self.task._open_first_pushable(rows))
        self.assertEqual(['1-06', '1-05'], [call.args[0].stage_id for call in open_mock.call_args_list])

    def test_open_first_pushable_skips_rows_without_id(self):
        # 编号补不出来的行点不中（行框是围绕编号块切的），直接跳过。
        rows = [event_stage.StageRef(stage_id=None, box=(950, 400, 1679, 520), source='number'),
                self._story_row('1-05')]
        with patch.object(self.task, '_open_row_for_push', return_value=True) as open_mock:
            self.assertTrue(self.task._open_first_pushable(rows))
        self.assertEqual(['1-05'], [call.args[0].stage_id for call in open_mock.call_args_list])

    def test_open_first_pushable_returns_false_when_all_rows_fail(self):
        with patch.object(self.task, '_open_row_for_push', return_value=False):
            self.assertFalse(self.task._open_first_pushable([self._story_row('1-04')]))

    def test_open_first_pushable_stops_when_row_cannot_be_judged(self):
        # 判不了可推性（详情页区域特征缺失）：每行都会卡在同一处，不再把整屏关卡点一遍。
        rows = [self._story_row('1-04'), self._story_row('1-05')]
        with patch.object(self.task, '_open_row_for_push', return_value=None) as open_mock:
            self.assertFalse(self.task._open_first_pushable(rows))
        open_mock.assert_called_once()  # 只试了最下面那一行。

    def test_open_row_for_push_returns_true_when_story_starts(self):
        # 点开后直接进剧情/战斗（首次进关没有详情页）：这一关就是当前进度关，交给战斗链。
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_landing', return_value='flow'), \
                patch.object(self.task, '_detail_page_open', return_value=False), \
                patch.object(self.task, '_optional_box', side_effect=AssertionError('没有详情页不应判「战斗」')):
            self.assertTrue(self.task._open_row_for_push(self._story_row('1-05')))
        self.assertEqual('event_stage_1-05', click_mock.call_args.args[0].name)  # 点了候选行。

    def test_open_row_for_push_returns_false_when_row_keeps_list(self):
        # 已通关不可重复挑战/未解锁的行：点开只弹提示、仍停在列表 → 试上一行。
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, '_stage_landing', return_value='list'), \
                patch.object(self.task, '_close_stage_detail', side_effect=AssertionError('没进详情页不应关页')):
            self.assertFalse(self.task._open_row_for_push(self._story_row('1-05')))

    def test_open_row_for_push_closes_detail_page_when_battle_disabled(self):
        # 详情页「战斗」灰白 = 该关不可推（门票耗尽/已通关不可重复挑战）→ 关页回列表，接着试上一行。
        battle_box = Box(1340, 1283, 80, 106, confidence=1, name='box_stage_detail_battle')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_landing', return_value='detail'), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_optional_box', return_value=battle_box) as optional_mock, \
                patch.object(self.task, 'is_feature_enabled', return_value=False) as enabled_mock, \
                patch.object(self.task, '_close_stage_detail') as close_mock:
            self.assertFalse(self.task._open_row_for_push(self._story_row('1-05')))
        self.assertEqual(1, click_mock.call_count)  # 只点了关卡行，未点「战斗」。
        optional_mock.assert_called_once_with('box_stage_detail_battle')
        enabled_mock.assert_called_once_with(battle_box)
        close_mock.assert_called_once()  # 关详情页回列表。

    def test_open_row_for_push_clicks_battle_when_available(self):
        battle_box = Box(1340, 1283, 80, 106, confidence=1, name='box_stage_detail_battle')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_landing', return_value='detail'), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_optional_box', return_value=battle_box), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, '_close_stage_detail', side_effect=AssertionError('可推不应关页')):
            self.assertTrue(self.task._open_row_for_push(self._story_row('1-05')))
        self.assertEqual(['event_stage_1-05', 'box_stage_detail_battle'],
                         [call.args[0].name for call in click_mock.call_args_list])  # 点行 → 点「战斗」。

    def test_open_row_for_push_missing_battle_region_closes_detail(self):
        # 详情页「战斗」区域解析不出（coco 缺失/加载失败）：告警 + 关页，且不在特征缺失时把整屏关卡点一遍。
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, '_stage_landing', return_value='detail'), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'is_feature_enabled', side_effect=AssertionError('区域缺失不应判态')), \
                patch.object(self.task, '_close_stage_detail') as close_mock, \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.assertIsNone(self.task._open_row_for_push(self._story_row('1-05')))  # 判不了可推性。
        close_mock.assert_called_once()  # 关详情页回列表。
        self.assertTrue(any('box_stage_detail_battle' in call.args[0] for call in warn_mock.call_args_list))

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
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        next_box = Box(200, 200, 20, 10, confidence=1, name='next')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_open_pushable_stage', return_value=True), \
                patch.object(self.task, '_skip_story_if_present') as skip_mock, \
                patch.object(self.task, '_field_changed_stop', return_value=False), \
                patch.object(self.task, 'wait_battle_finish',
                             side_effect=[('success', confirm), ('success', confirm)]) as battle_mock, \
                patch.object(self.task, '_optional_box', return_value=next_box), \
                patch.object(self.task, 'is_feature_enabled', side_effect=[True, False]) as enabled_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._push_stages()
        self.assertEqual(2, battle_mock.call_count)  # 第一场后点「下一关」续战，第二场后结束。
        clicked = [call.args[0] for call in click_mock.call_args_list]
        self.assertEqual(['next', 'confirm'], [box.name for box in clicked])  # 续战 → 结算返回。
        self.assertEqual(3, skip_mock.call_count)  # 进关卡、进下一关、结算返回各判一次剧情。
        self.assertEqual(2, enabled_mock.call_count)  # 两场结算都判「下一关」可用性。
        assert_called_once_semantic(assert_mock, 'event_stage_page')

    def test_push_stages_stops_on_failed_battle(self):
        back = Box(300, 300, 20, 10, confidence=1, name='failed_back')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_open_pushable_stage', return_value=True), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, '_field_changed_stop', return_value=False), \
                patch.object(self.task, 'wait_battle_finish', return_value=('failed', back)), \
                patch.object(self.task, '_optional_box', side_effect=AssertionError('失败不应判下一关')), \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._push_stages()
        self.assertEqual('failed_back', click_mock.call_args_list[-1].args[0].name)  # 点失败返回按钮结束。
        assert_called_once_semantic(assert_mock, 'event_stage_page')

    def test_push_stages_timeout_raises(self):
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, '_open_pushable_stage', return_value=True), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, '_field_changed_stop', return_value=False), \
                patch.object(self.task, 'wait_battle_finish', return_value=(None, None)), \
                patch.object(self.task, 'assert_screen', side_effect=AssertionError('超时不应继续')):
            self.assertRaises(WaitFailedException, self.task._push_stages)

    def test_push_stages_returns_true_when_no_row_is_pushable(self):
        # 候选行都点不出可推的关（已通关不可重复挑战/未解锁/门票耗尽）：不进战斗等待，直接收工返回。
        with patch.object(self.task, '_open_pushable_stage', return_value=False), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('无可推关卡不应点击')), \
                patch.object(self.task, 'wait_battle_finish', side_effect=AssertionError('未进关卡不应等战斗')), \
                patch.object(self.task, 'assert_screen', side_effect=AssertionError('仍在列表页不应断言')):
            self.assertTrue(self.task._push_stages())

    def test_push_stages_opens_stage_and_chains(self):
        # 完整一次推图：点候选行 → 详情页「战斗」可用 → 点「战斗」进战斗链 → 结算确认后收尾。
        from src.tasks.event._const import _STAGE_LIST_BOX
        list_box = Box(950, 342, 729, 867, confidence=1, name=_STAGE_LIST_BOX)
        battle_box = Box(1340, 1283, 80, 106, confidence=1, name='box_stage_detail_battle')
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(self.task, '_stage_rows', return_value=[self._story_row('1-05')]), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_landing', return_value='detail'), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_optional_box', side_effect=[battle_box, None]), \
                patch.object(self.task, 'is_feature_enabled', return_value=True) as enabled_mock, \
                patch.object(self.task, '_skip_story_if_present') as skip_mock, \
                patch.object(self.task, '_field_changed_stop', return_value=False), \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)) as battle_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.assertTrue(self.task._push_stages())
        clicked = [call.args[0] for call in click_mock.call_args_list]
        self.assertEqual(['event_stage_1-05', 'box_stage_detail_battle', 'confirm'],
                         [box.name for box in clicked])  # 点行 → 详情页点「战斗」→ 结算确认结束。
        enabled_mock.assert_called_once_with(battle_box)  # 结算「下一关」缺失不判态。
        self.assertEqual(1, battle_mock.call_count)
        self.assertEqual(2, skip_mock.call_count)  # 进战斗、结算返回各判一次剧情。
        assert_called_once_semantic(assert_mock, 'event_stage_page')

    def test_push_stages_closes_detail_page_and_stops_when_battle_disabled(self):
        # 详情页「战斗」灰白（门票耗尽/已通关不可重复挑战）：逐行往上试，全不可推就收工（不进战斗等待）。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        battle_box = Box(1340, 1283, 80, 106, confidence=1, name='box_stage_detail_battle')
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(self.task, '_stage_rows',
                             return_value=[self._story_row('1-04'), self._story_row('1-05')]), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_landing', return_value='detail'), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_optional_box', return_value=battle_box), \
                patch.object(self.task, 'is_feature_enabled', return_value=False), \
                patch.object(self.task, '_close_stage_detail') as close_mock, \
                patch.object(self.task, 'wait_battle_finish', side_effect=AssertionError('不可推不应等战斗')), \
                patch.object(self.task, 'assert_screen', side_effect=AssertionError('仍在列表页不应断言')):
            self.assertTrue(self.task._push_stages())
        self.assertEqual(['event_stage_1-05', 'event_stage_1-04'],
                         [call.args[0].name for call in click_mock.call_args_list])  # 自下而上逐行试。
        self.assertEqual(2, close_mock.call_count)  # 每行判态后都关页回列表。

    def test_push_stages_stops_when_battle_region_missing(self):
        # 详情页「战斗」区域解析不出（coco 缺失）：告警 + 关页，不再把整屏关卡点一遍。
        list_box = Box(950, 342, 729, 867, confidence=1, name='list')
        with patch.object(self.task, '_stage_list_box', return_value=list_box), \
                patch.object(self.task, '_stage_rows', return_value=[self._story_row('1-05')]), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_stage_landing', return_value='detail'), \
                patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, '_close_stage_detail') as close_mock, \
                patch.object(self.task, 'log_warning') as warn_mock, \
                patch.object(self.task, 'wait_battle_finish', side_effect=AssertionError('无区域不应等战斗')):
            self.assertTrue(self.task._push_stages())
        self.assertEqual(1, click_mock.call_count)  # 只点了关卡行。
        close_mock.assert_called_once()  # 关详情页回列表。
        self.assertTrue(any('box_stage_detail_battle' in call.args[0] for call in warn_mock.call_args_list))

    def test_push_stages_stops_at_battle_cap(self):
        # 安全上限：结算按钮持续判可用时不得死循环，达到上限即停止推图。
        from src.tasks.event._const import _STORY_MAX_BATTLES
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        next_box = Box(200, 200, 20, 10, confidence=1, name='next')
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, '_open_pushable_stage', return_value=True), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, '_field_changed_stop', return_value=False), \
                patch.object(self.task, 'wait_battle_finish',
                             return_value=('success', confirm)) as battle_mock, \
                patch.object(self.task, '_optional_box', return_value=next_box), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._push_stages()
        self.assertEqual(_STORY_MAX_BATTLES, battle_mock.call_count)  # 循环次数封顶。
        assert_called_once_semantic(assert_mock, 'event_stage_page')

    # ---- 大活动换地区（event_story_field_changed + 已回活动地区页两个信号） ----

    def test_field_changed_stop_clicks_button_and_returns_true(self):
        # 信号①：按钮在画面上 → 点掉它，判定为换地区（零等待：当前帧就命中）。
        from src.tasks.event._const import _STORY_FIELD_CHANGED_FEATURE
        hit = Box(1200, 700, 200, 60, confidence=1, name=_STORY_FIELD_CHANGED_FEATURE)
        with patch.object(self.task, 'feature_exists', return_value=True), \
                patch.object(self.task, 'find_one', return_value=hit), \
                patch.object(self.task, 'wait_feature', side_effect=AssertionError('帧上已命中不应再等')), \
                patch.object(self.task, 'click_box') as click_mock:
            self.assertTrue(self.task._field_changed_stop())
        click_mock.assert_called_once()  # 命中即点击（点完回到活动地区页）。
        self.assertEqual(hit, click_mock.call_args.args[0])

    def test_field_changed_stop_detects_event_area_page_without_button(self):
        # 信号②（实机补充）：按钮没渲染出来、或被跳过剧情的清理顺手点掉时，只要人已回到活动地区页就算换地区。
        with patch.object(self.task, 'feature_exists', return_value=True), \
                patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, '_in_battle_page', return_value=True), \
                patch.object(self.task, 'wait_feature', side_effect=AssertionError('战斗中不应等提示')), \
                patch.object(self.task, '_probe_event_main', return_value=True), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('没有按钮不应点击')):
            self.assertTrue(self.task._field_changed_stop())  # 已在活动地区页：按换地区收尾。

    def test_field_changed_stop_false_when_still_in_stage_flow(self):
        # 仍在关卡流程（关卡页/对话/战斗且不在活动地区页）：不是换地区，正常推图不被打断。
        with patch.object(self.task, 'feature_exists', return_value=True), \
                patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, '_in_battle_page', return_value=True), \
                patch.object(self.task, '_probe_event_main', return_value=False):
            self.assertFalse(self.task._field_changed_stop())

    def test_wait_field_changed_hit_waits_only_outside_battle(self):
        # 容错窗口只在「战斗已结束/未开始」时付：战斗界面内提示不可能在场，直接返回不空等。
        from src.tasks.event._const import _STORY_FIELD_CHANGED_FEATURE, _STORY_FIELD_CHANGED_WAIT
        hit = Box(1200, 700, 200, 60, confidence=1, name=_STORY_FIELD_CHANGED_FEATURE)
        with patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, '_in_battle_page', return_value=False), \
                patch.object(self.task, 'wait_feature', return_value=hit) as wait_mock:
            self.assertEqual(hit, self.task._wait_field_changed_hit(_STORY_FIELD_CHANGED_WAIT))
        self.assertEqual(_STORY_FIELD_CHANGED_FEATURE, wait_mock.call_args.args[0])
        self.assertEqual(_STORY_FIELD_CHANGED_WAIT, wait_mock.call_args.kwargs['time_out'])
        self.assertEqual(0, wait_mock.call_args.kwargs['settle_time'])  # 命中即返回，不等稳定窗口。
        self.assertEqual(self.task._story_poll_throttle, wait_mock.call_args.kwargs['post_action'])  # 等待循环节流。
        with patch.object(self.task, 'find_one', return_value=None), \
                patch.object(self.task, '_in_battle_page', return_value=True), \
                patch.object(self.task, 'wait_feature', side_effect=AssertionError('战斗中不应空等')):
            self.assertIsNone(self.task._wait_field_changed_hit(_STORY_FIELD_CHANGED_WAIT))  # 战斗中：只做即时判定。

    def test_field_changed_stop_state_only_when_feature_unannotated(self):
        # coco 未标注：只认状态信号，不匹配特征（旧包/未标定也能跑）。
        with patch.object(self.task, 'feature_exists', return_value=False), \
                patch.object(self.task, 'find_one', side_effect=AssertionError('未标注不应匹配')), \
                patch.object(self.task, '_probe_event_main', return_value=True):
            self.assertTrue(self.task._field_changed_stop())  # 已在活动地区页。
        with patch.object(self.task, 'feature_exists', return_value=False), \
                patch.object(self.task, '_probe_event_main', return_value=False):
            self.assertFalse(self.task._field_changed_stop())  # 仍在关卡流程。

    def test_push_stages_returns_false_when_field_changed(self):
        # 跳过剧情后已换地区：点掉按钮/或已在活动地区页 → 本轮返回 False，不再等战斗、不断言关卡页。
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, '_open_pushable_stage', return_value=True), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, '_field_changed_stop', return_value=True) as changed_mock, \
                patch.object(self.task, 'wait_battle_finish', side_effect=AssertionError('换地区后不应再等战斗')), \
                patch.object(self.task, 'assert_screen', side_effect=AssertionError('换地区后不在关卡页')):
            self.assertFalse(self.task._push_stages())
        changed_mock.assert_called_once()

    def test_push_stages_returns_false_when_field_changed_right_after_next_stage(self):
        # 实机补充：点「下一关」之后就直接切地区（不经过剧情/战斗）→ 紧跟的这次判定必须拦住，不能等满 240s。
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        next_box = Box(200, 200, 20, 10, confidence=1, name='next')
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, '_open_pushable_stage', return_value=True), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, '_field_changed_stop', side_effect=[False, True]) as changed_mock, \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)), \
                patch.object(self.task, '_optional_box', return_value=next_box), \
                patch.object(self.task, 'is_feature_enabled', return_value=True), \
                patch.object(self.task, 'assert_screen', side_effect=AssertionError('换地区后不在关卡页')):
            self.assertFalse(self.task._push_stages())
        self.assertEqual(2, changed_mock.call_count)  # 循环头一次 + 点「下一关」后一次。
        self.assertNotIn('confirm', [box.name for box in [call.args[0] for call in click_mock.call_args_list]])  # 没点结算返回。

    def test_push_stages_returns_true_on_normal_end(self):
        confirm = Box(100, 100, 20, 10, confidence=1, name='confirm')
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, '_open_pushable_stage', return_value=True), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, '_field_changed_stop', return_value=False), \
                patch.object(self.task, 'wait_battle_finish', return_value=('success', confirm)), \
                patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.assertTrue(self.task._push_stages())  # 门票耗尽：本轮收工。
        assert_called_once_semantic(assert_mock, 'event_stage_page')

    def test_push_stages_returns_false_when_field_changed_after_battle_timeout(self):
        # 兜底：换地区提示比预想晚出现（战斗没开起来）→ 战斗等待超时后再判一次，别白等满超时又判失败。
        with patch.object(self.task, 'click_box'), \
                patch.object(self.task, '_open_pushable_stage', return_value=True), \
                patch.object(self.task, '_skip_story_if_present'), \
                patch.object(self.task, '_field_changed_stop', side_effect=[False, True]), \
                patch.object(self.task, 'wait_battle_finish', return_value=(None, None)), \
                patch.object(self.task, 'assert_screen', side_effect=AssertionError('换地区后不在关卡页')):
            self.assertFalse(self.task._push_stages())  # 不抛超时异常，交调用方重推一轮。

    def test_flow_story_repushes_after_field_changed(self):
        # 换地区后：重新识别菜单页的剧情入口进关卡页，再推一轮，直到某轮收工。
        self.task.config['剧情'] = True
        self.task.config['扫荡'] = False  # 只验证推图轮次。
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')), \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_enter_stage_page') as enter_mock, \
                patch.object(self.task, '_push_stages', side_effect=[False, True]) as push_mock:
            self.task._flow_story()
        self.assertEqual(2, push_mock.call_count)  # 换地区后重推一轮。
        self.assertEqual(2, enter_mock.call_count)  # 第 1 轮由 _flow_story 开头进入，第 2 轮换地区后重新进入。

    def test_flow_story_stops_at_push_round_cap(self):
        # 安全上限：换地区提示持续误判时不得死循环。
        from src.tasks.event._const import _STORY_MAX_PUSH_ROUNDS
        self.task.config['剧情'] = True
        self.task.config['扫荡'] = False
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=Box(60, 700, 30, 20, confidence=1, name='加成奖励妮姬')), \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_push_stages', return_value=False) as push_mock, \
                patch.object(self.task, 'log_warning') as warn_mock:
            self.task._flow_story()
        self.assertEqual(_STORY_MAX_PUSH_ROUNDS, push_mock.call_count)  # 轮次封顶。
        self.assertTrue(any('轮次上限' in call.args[0] for call in warn_mock.call_args_list))  # 记异常日志。

    # ---- 剧情对话跳过（复用全局 conversation 界面与 conversation_skip 特征） ----

    def test_skip_story_clicks_skip_then_clears_popups(self):
        from src.tasks.event._const import _STORY_DIALOG_WAIT
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
        assert_called_once_semantic(click_feature_mock, 'conversation_skip', box=icon_box,
                                    raise_if_not_found=True)
        assert_called_once_semantic(dismiss_mock, wait_for_popup=False)  # 跳过后清奖励/好感遮罩。

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

    def test_story_poll_throttle_sleeps_interval(self):
        # 节流挂点：只睡 _STORY_POLL_INTERVAL，窗口与判据不变。
        from src.tasks.event._const import _STORY_POLL_INTERVAL
        with patch.object(self.task, 'sleep') as sleep_mock:
            self.task._story_poll_throttle()
        sleep_mock.assert_called_once_with(_STORY_POLL_INTERVAL)

    def test_story_waits_pass_poll_throttle(self):
        # ok 的等待循环体内没有 sleep（实测约 54 fps 抓帧+匹配），两个等待点都挂上节流挂点。
        with patch.object(self.task, 'wait_until', return_value=False) as wait_mock:
            self.assertFalse(self.task._skip_story_if_present())
        self.assertEqual(self.task._story_poll_throttle, wait_mock.call_args.kwargs['post_action'])
        with patch.object(self.task, 'wait_until', return_value='detail') as wait_mock:
            self.assertEqual('detail', self.task._stage_landing())
        self.assertEqual(self.task._story_poll_throttle, wait_mock.call_args.kwargs['post_action'])

    def test_stage_landing_classifies_detail_flow_list_and_unknown(self):
        # 落点分类都用界面特征判：详情页 / 剧情或战斗 / 仍停在列表 / 都不是（None）。
        cases = [({'detail': True}, 'detail'), ({'flow': True}, 'flow'), ({'list': True}, 'list'), ({}, None)]
        for flags, expected in cases:
            with self.subTest(expected=expected), \
                    patch.object(self.task, '_detail_page_open', return_value=flags.get('detail', False)), \
                    patch.object(self.task, '_in_stage_flow', return_value=flags.get('flow', False)), \
                    patch.object(self.task, 'is_screen', return_value=flags.get('list', False)), \
                    patch.object(self.task, 'wait_until', side_effect=lambda cond, **kwargs: cond()) as wait_mock:
                self.assertEqual(expected, self.task._stage_landing())
            self.assertEqual(self.task._story_poll_throttle, wait_mock.call_args.kwargs['post_action'])
            self.assertTrue(callable(wait_mock.call_args.kwargs['pre_action']))  # 未命中那轮顺手清提示框。

    def test_stage_landing_checks_detail_before_flow(self):
        # 详情页判定优先：详情页上也可能同时命中战斗界面特征，先按详情页走（由调用方判按钮态）。
        with patch.object(self.task, '_detail_page_open', return_value=True), \
                patch.object(self.task, '_in_stage_flow', return_value=True), \
                patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, 'wait_until', side_effect=lambda cond, **kwargs: cond()):
            self.assertEqual('detail', self.task._stage_landing())

    def test_in_stage_flow_covers_conversation_and_battle(self):
        # 进关卡的两种落点：剧情对话（conversation）或战斗界面。
        with patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, '_in_battle_page', return_value=False):
            self.assertTrue(self.task._in_stage_flow())
        with patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_in_battle_page', return_value=True):
            self.assertTrue(self.task._in_stage_flow())
        with patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_in_battle_page', return_value=False):
            self.assertFalse(self.task._in_stage_flow())

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
        self.task.config['剧情'] = True
        self.task.config['扫荡'] = True
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=Box(10, 10, 20, 20, confidence=1, name='加成奖励妮姬')), \
                patch.object(self.task, 'transition'), \
                patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, '_probe_story_sub_page', return_value=False), \
                patch.object(self.task, '_push_stages', side_effect=lambda: calls.append('push') or True), \
                patch.object(self.task, '_sweep_stage', side_effect=lambda stage: calls.append(f'sweep:{stage}')):
            self.task._flow_story()
        self.assertEqual(['push', 'sweep:1-11'], calls)  # 先推图后扫荡，扫荡用默认关卡（推图返回 True = 本轮收工）。

    def test_flow_story_sweeps_configured_stage_without_push(self):
        self.task.config['剧情'] = False
        self.task.config['扫荡'] = True
        self.task.config['扫荡关卡'] = '1-09'
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=Box(10, 10, 20, 20, confidence=1, name='加成奖励妮姬')), \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, '_probe_event_main', return_value=False), \
                patch.object(self.task, '_probe_story_sub_page', return_value=False), \
                patch.object(self.task, '_push_stages', side_effect=AssertionError('剧情关闭不应推图')), \
                patch.object(self.task, '_sweep_stage') as sweep_mock:
            self.task._flow_story()
        sweep_mock.assert_called_once_with('1-09')  # 用配置的扫荡关卡。
        self.assertEqual(['event_stage_page', 'event_main'],
                         [call.args[0] for call in transition_mock.call_args_list])  # 仍进关卡页并回菜单页。

    def test_locate_stage_row_uses_current_screen_without_scrolling(self):
        # 进关卡页时列表停在当前进度关：当前屏能命中就先用它，不动列表。
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=[self._story_row('1-11')]), \
                patch.object(self.task, '_scroll_list_to_top', side_effect=AssertionError('当前屏命中不应滚动')), \
                patch.object(self.task, '_scroll_list_down', side_effect=AssertionError('当前屏命中不应滚动')):
            row = self.task._locate_stage_row('1-11')
        self.assertEqual('1-11', row.stage_id)

    def test_locate_stage_row_scrolls_when_absent_from_current_screen(self):
        # 当前屏没有该编号（扫荡目标多是已通关关卡，在当前进度关上方）：归一到列表顶部后逐屏下滚查找。
        from src.tasks.event._const import _STAGE_SWIPE_START_RATIO
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        screens = [[self._story_row('1-06')], [self._story_row('1-06')], [self._story_row('1-07')]]
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', side_effect=screens), \
                patch.object(self.task, '_scroll_list_to_top') as top_mock, \
                patch.object(self.task, '_scroll_list_down', return_value=True) as down_mock:
            row = self.task._locate_stage_row('1-07')
        self.assertEqual('1-07', row.stage_id)
        top_mock.assert_called_once_with(box, _STAGE_SWIPE_START_RATIO)  # 归一到顶部（关卡列表的手势起点比例）。
        down_mock.assert_called_once_with(1, box, _STAGE_SWIPE_START_RATIO)  # 下滚一屏后在第二屏命中。

    def test_locate_stage_row_returns_none_after_full_scan(self):
        # 整份列表都没有该编号（尚未通关/未开放）：下滚到底（返回 False）即结束，不空转。
        box = Box(950, 342, 729, 867, confidence=1, name='stage_list')
        with patch.object(self.task, '_stage_list_box', return_value=box), \
                patch.object(self.task, '_stage_rows', return_value=[self._story_row('1-01')]), \
                patch.object(self.task, '_scroll_list_to_top'), \
                patch.object(self.task, '_scroll_list_down', return_value=False) as down_mock:
            self.assertIsNone(self.task._locate_stage_row('1-11'))
        self.assertEqual(1, down_mock.call_count)  # 第一次下滚就到底，不再继续。

    def test_locate_stage_row_returns_none_without_region(self):
        with patch.object(self.task, '_stage_list_box', return_value=None):
            self.assertIsNone(self.task._locate_stage_row('1-11'))

    def _sweep_quick_box(self):
        return Box(1343, 1223, 34, 30, confidence=1, name='box_stage_detail_quick_battle')

    def test_sweep_stage_sweeps_then_stops_when_unavailable(self):
        # 第一轮实际扫荡（拉满次数），第二轮进详情页发现「快速战斗」灰白即结束。
        from src.tasks.event._const import _SWEEP_START_BOX
        row = self._story_row('1-11')
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
        assert_any_call_semantic(click_mock, quick_box)  # 点详情页「快速战斗」。
        assert_any_call_semantic(click_mock, max_btn)  # 次数拉满。
        assert_any_call_semantic(click_mock, _SWEEP_START_BOX)  # 点开始快速战斗。
        assert_any_call_semantic(click_mock, confirm)  # 结算确认。
        self.assertEqual(1, battle_mock.call_count)  # 只扫荡一轮就耗尽。
        self.assertEqual([quick_box, quick_box], [call.args[0] for call in enabled_mock.call_args_list])  # 两轮都判「快速战斗」可用性。
        # 特征等待顺序：第一轮详情页就位 → 次数弹窗就位；第二轮只等详情页就位（随即判灰白结束）。
        self.assertEqual(['stage_detail_close', 'custom_quick_battle_page', 'stage_detail_close'],
                         [call.args[0] for call in wait_feature_mock.call_args_list])
        assert_any_call_semantic(close_mock, 'stage_detail_close', raise_if_not_found=True)  # 关详情页动作。
        self.assertEqual(2, close_mock.call_count)  # 结算落回详情页关一次；第二轮灰白耗尽再关一次。
        self.assertEqual(3, assert_mock.call_count)  # 两次关页 + 首轮收尾各确认一次回到关卡列表。

    def test_sweep_stage_missing_row_skips(self):
        with patch.object(self.task, '_locate_stage_row', return_value=None), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('未定位到关卡不应点击')):
            self.task._sweep_stage('1-07')

    def test_sweep_stage_skips_when_detail_page_missing(self):
        # 已通关但不可重复挑战的行：点开只弹提示、不进详情页 → 软判定跳过，且不做关页动作（仍在列表页）。
        row = self._story_row('1-11')
        with patch.object(self.task, '_locate_stage_row', return_value=row), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature', return_value=False), \
                patch.object(self.task, '_optional_box', side_effect=AssertionError('未进详情页不应判快速战斗')), \
                patch.object(self.task, 'wait_click_feature', side_effect=AssertionError('仍在列表页不应关详情页')):
            self.task._sweep_stage('1-11')
        self.assertEqual('event_stage_1-11', click_mock.call_args.args[0].name)  # 只点了关卡行。

    def test_sweep_stage_missing_quick_region_skips(self):
        # 区域特征解析不出来（coco 缺失）与「按钮灰白」是两种问题：前者要单独告警，不能误报成耗尽。
        row = self._story_row('1-11')
        with patch.object(self.task, '_locate_stage_row', return_value=row), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature'), \
                patch.object(self.task, '_optional_box', return_value=None), \
                patch.object(self.task, 'is_feature_enabled', side_effect=AssertionError('区域缺失不应判态')), \
                patch.object(self.task, 'wait_click_feature') as close_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._sweep_stage('1-11')
        self.assertEqual('event_stage_1-11', click_mock.call_args.args[0].name)  # 只点了关卡行。
        assert_called_once_semantic(close_mock, 'stage_detail_close', raise_if_not_found=True)
        assert_called_once_semantic(assert_mock, 'event_stage_page')

    def test_sweep_stage_requires_count_popup_and_closes_detail_after_settlement(self):
        # 实机口径：点「快速战斗」必弹次数选择窗（缺失抛异常）；扫荡直接跳结算不进战斗界面；
        # 结算确认后落回关卡详情页，需先关详情页退回列表再进入下一轮。
        from src.tasks.event._const import _SWEEP_PAGE_FEATURE, _SWEEP_START_BOX
        row = self._story_row('1-11')
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
                patch.object(self.task, 'assert_screen'):
            self.task._sweep_stage('1-11')
        self.assertEqual(_SWEEP_PAGE_FEATURE, wait_feature_mock.call_args_list[1].args[0])  # 第一轮等次数弹窗。
        self.assertTrue(wait_feature_mock.call_args_list[1].kwargs['raise_if_not_found'])  # 弹窗必现语义。
        clicked = [call.args[0] for call in click_mock.call_args_list]
        self.assertIn(_SWEEP_START_BOX, clicked)  # 弹窗里点「开始」（按区域特征名点击）。
        assert_any_call_semantic(click_mock, confirm)  # 点结算确认。
        self.assertEqual(2, close_mock.call_count)  # 结算后关详情页 + 第二轮灰白再关一次。

    def test_sweep_stage_ignores_row_status(self):
        # 行状态不作门槛：已通关标记可能漏检（实机 1-11 已通关却读成 available），
        # 能否扫荡一律进详情页由「快速战斗」判态决定。
        row = self._story_row('1-11')
        with patch.object(self.task, '_locate_stage_row', return_value=row), \
                patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'wait_feature'), \
                patch.object(self.task, '_optional_box', return_value=self._sweep_quick_box()), \
                patch.object(self.task, 'is_feature_enabled', return_value=False), \
                patch.object(self.task, 'wait_click_feature') as close_mock, \
                patch.object(self.task, 'assert_screen') as assert_mock:
            self.task._sweep_stage('1-11')
        self.assertEqual('event_stage_1-11', click_mock.call_args.args[0].name)  # 仍然点开了关卡详情页。
        assert_called_once_semantic(close_mock, 'stage_detail_close', raise_if_not_found=True)  # 灰白后关页收尾。
        assert_called_once_semantic(assert_mock, 'event_stage_page')

    def test_sweep_stage_timeout_raises(self):
        row = self._story_row('1-11')
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
        from src.tasks.event._const import _SWEEP_MAX_ROUNDS
        row = self._story_row('1-11')
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
        # 完成口径 = 在架活动是否已全部按身份完成；无本地活动数据不谎报完成。
        event = _fake_event('key1', '活动A', 'https://cdn/x.png')
        with patch.object(event_calendar, 'load_snapshot', return_value=None):
            self.assertFalse(self.task.is_completed())  # 无快照：不算完成。
        with patch.object(event_calendar, 'load_snapshot', return_value=_snapshot([event])):
            self.assertFalse(self.task.is_completed())
            self.task.mark_done(event_done_key(event_identity('key1')), 'day')
            self.assertTrue(self.task.is_completed())

    # ---- 小游戏 ----

    def _minigame_entry(self):
        return Box(60, 10, 30, 10, confidence=1, name='小游戏')

    def _minigame_boxes(self):
        """小游戏流程按名字解析的三处 coco 区域（分数区 / 暂停钮 / 全部领取），其余以字符串直传被 mock。"""
        return {
            'box_event_minigame_score': Box(1120, 29, 324, 72, confidence=1, name='score'),
            'event_minigame_pause': Box(1596, 42, 46, 43, confidence=1, name='pause'),
            'box_event_minigame_mission_claim': Box(1170, 1250, 35, 33, confidence=1, name='全部领取'),
        }

    def test_do_minigame_skipped_when_disabled(self):
        self.task.config['小游戏'] = False
        with patch.object(self.task, '_probe_entry', side_effect=AssertionError('关闭时不应探测')), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('关闭时不应执行')):
            self.task._do_minigame()

    def test_do_minigame_skipped_when_identity_unknown(self):
        # 接管路径判不出活动身份：不知道走哪个活动的小游戏流程，跳过（不拿注册表里的唯一项去猜）。
        self.task.config['小游戏'] = True
        self.task._event_identity = None
        with patch.object(self.task, '_probe_entry', side_effect=AssertionError('身份未知不应探测')), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('身份未知不应执行')):
            self.task._do_minigame()

    def test_do_minigame_skipped_when_event_not_registered(self):
        self.task.config['小游戏'] = True
        self.task._event_identity = 'SOMEOTHEREVENT'
        with patch.object(self.task, '_probe_entry', side_effect=AssertionError('未接入不应探测')), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('未接入不应执行')):
            self.task._do_minigame()

    def test_do_minigame_skipped_when_probe_missing(self):
        self.task.config['小游戏'] = True
        self.task._event_identity = 'COINRUSHSHOWDOWN'
        with patch.object(self.task, '_probe_entry', return_value=False), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('探测不到不应执行')):
            self.task._do_minigame()

    def test_do_minigame_skips_locked_entry(self):
        self.task.config['小游戏'] = True
        self.task._event_identity = 'COINRUSHSHOWDOWN'
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, '_entry_locked_skip', return_value=True), \
                patch.object(self.task, 'try_step', side_effect=AssertionError('锁定入口不应执行')):
            self.task._do_minigame()

    def test_do_minigame_runs_registered_flow(self):
        # 注册表命中：开关开启 + 探测到入口 + 非锁定态 → 走该活动身份登记的流程方法。
        self.task.config['小游戏'] = True
        self.task._event_identity = 'COINRUSHSHOWDOWN'
        with patch.object(self.task, '_probe_entry', return_value=True), \
                patch.object(self.task, '_entry_locked_skip', return_value=False), \
                patch.object(self.task, 'try_step', side_effect=lambda fn, **kw: fn() or True), \
                patch.object(self.task, '_flow_minigame') as flow_mock:
            self.task._do_minigame()
        flow_mock.assert_called_once()

    def test_flow_minigame_entry_click_ineffective_stops(self):
        # 入口点击无效（补点耗尽后仍在活动菜单页 = 往期活动/未开放入口）：直接结束，不再让 try_step 重跑补点。
        entry = self._minigame_entry()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'transition', side_effect=WaitFailedException('未进入小游戏')), \
                patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, '_start_minigame_run', side_effect=AssertionError('不应开局')):
            self.task._flow_minigame()  # 不抛异常 = 已按「入口点不动」跳过。

    def test_flow_minigame_entry_failed_on_other_screen_raises(self):
        # 补点耗尽后落在别的界面：按失败抛异常交 try_step 恢复（不看错误页继续猜）。
        entry = self._minigame_entry()
        with patch.object(self.task, '_nav_to_event_main'), \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'transition', side_effect=WaitFailedException('未进入小游戏')), \
                patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, '_start_minigame_run', side_effect=AssertionError('不应开局')):
            self.assertRaises(WaitFailedException, self.task._flow_minigame)

    def test_flow_minigame_reaches_target_then_quick_finishes_and_claims(self):
        # 主链路：进主界面 → START → 选择妮姬页 START → 关卡内点中央 → 分数达标 → 暂停 → 快速完成 →
        # 结算页 → 返回 → 任务弹窗 → 全部领取（第二轮回灰白）→ 关弹窗 → 退出确认 → 回活动菜单页。
        from src.tasks.event import _minigame as minigame  # 覆盖分数采样间隔：单测不必真等 2.5 秒。

        entry = self._minigame_entry()
        boxes = self._minigame_boxes()
        back = Box(30, 1345, 40, 40, confidence=1, name='返回')
        state = {'screen': 'event_minigame_main'}  # 用可变状态模拟界面切换。
        clicks = []  # click_box 的目标（框或 coco 名字）。
        features = []  # wait_click_feature 等到的特征名。

        def is_screen(name):
            return name == state['screen']  # 当前界面唯一命中。

        def click_box(box, **kwargs):
            clicks.append(box)
            name = box if isinstance(box, str) else box.name
            if name == 'box_event_minigame_enter':  # 主界面 START → 选择妮姬页。
                state['screen'] = 'event_minigame_select'
            elif name == 'event_minigame_start':  # 选择妮姬页 START → 关卡。
                state['screen'] = 'event_minigame_play'
            elif name == 'pause':  # 点暂停钮 → 暂停弹窗。
                state['screen'] = 'event_minigame_pause_dialog'
            elif name == 'box_event_minigame_quick_finish':  # 快速完成 → 结算页。
                state['screen'] = 'event_minigame_result'
            elif name == 'box_event_minigame_result_back':  # 结算页返回 → 主界面。
                state['screen'] = 'event_minigame_main'
            elif name == '返回':  # 主界面返回键 → 退出确认框。
                state['screen'] = 'event_minigame_exit_confirm'

        def wait_click_feature(feature, **kwargs):
            features.append(feature)
            if feature == 'event_minigame_mission':  # 点任务入口 → 任务弹窗。
                state['screen'] = 'event_minigame_mission_popup'
            elif feature == 'event_minigame_mission_close':  # 关任务弹窗 → 主界面。
                state['screen'] = 'event_minigame_main'
            elif feature == 'event_minigame_exit_confirm':  # 确认退出 → 活动菜单页。
                state['screen'] = 'event_main'

        def wait_until(condition, **kwargs):
            return condition()  # 单测驱动：逐次实算条件。

        with patch.object(minigame, '_MINIGAME_SCORE_INTERVAL', 0.0), \
                patch.object(self.task, '_nav_to_event_main') as nav_mock, \
                patch.object(self.task, '_entry_box', return_value=entry), \
                patch.object(self.task, 'transition') as transition_mock, \
                patch.object(self.task, 'is_screen', side_effect=is_screen), \
                patch.object(self.task, 'click_box', side_effect=click_box), \
                patch.object(self.task, 'click_relative') as tap_mock, \
                patch.object(self.task, 'next_frame'), \
                patch.object(self.task, '_optional_box', side_effect=lambda name: boxes.get(name)), \
                patch.object(self.task, 'ocr', return_value=[Box(0, 0, 9, 9, confidence=1, name='7,500')]) as ocr_mock, \
                patch.object(self.task, 'wait_until', side_effect=wait_until), \
                patch.object(self.task, 'wait_click_feature', side_effect=wait_click_feature), \
                patch.object(self.task, 'is_box_highlighted', side_effect=[True, False]) as highlighted_mock, \
                patch.object(self.task, '_close_claim_overlay') as overlay_mock, \
                patch.object(self.task, '_find_back_button', return_value=back):
            self.task._flow_minigame()

        nav_mock.assert_called_once()  # 进流程先就位活动主页。
        assert_called_once_semantic(transition_mock, 'event_minigame_main', box=entry)  # 点入口并确认进主界面。
        self.assertEqual(['box_event_minigame_enter', 'event_minigame_start', 'pause',
                          'box_event_minigame_quick_finish', 'box_event_minigame_result_back', '全部领取', '返回'],
                         [box if isinstance(box, str) else box.name for box in clicks])  # 点击顺序即流程顺序。
        self.assertEqual(['event_minigame_mission', 'event_minigame_mission_close', 'event_minigame_exit_confirm'],
                         features)  # 任务入口 → 关弹窗 → 退出确认。
        tap_mock.assert_called_once()  # 首次采样即达标：关卡内只点了一次中央。
        ocr_mock.assert_called_once()  # 达标后不再读分。
        self.assertEqual(2, highlighted_mock.call_count)  # 全部领取色相判态两轮：第一轮亮黄可领、第二轮暗棕收手。
        self.assertEqual(2, overlay_mock.call_count)  # 领奖遮罩两处清理（结算返回后 + 每轮领取后）。

    def test_play_minigame_run_stops_when_leaving_stage(self):
        # 关卡判据不成立（本局自然结束）立即停手：不再盲点中央，避免落点进结算页/弹窗。
        with patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, 'click_relative', side_effect=AssertionError('已离开关卡不应再点')):
            self.assertFalse(self.task._play_minigame_run())  # False = 无需快速完成。

    def test_play_minigame_run_returns_true_on_target_score(self):
        from src.tasks.event import _minigame as minigame  # 覆盖分数采样间隔：首次循环就采样。
        with patch.object(minigame, '_MINIGAME_SCORE_INTERVAL', 0.0), \
                patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, 'click_relative') as tap_mock, \
                patch.object(self.task, 'next_frame'), \
                patch.object(self.task, '_minigame_score', return_value=4000):
            self.assertTrue(self.task._play_minigame_run())  # 达标：返回 True 走快速完成。
        tap_mock.assert_called_once()  # 达标即返回，不再继续点。

    def test_play_minigame_run_returns_true_on_timeout(self):
        # 游玩上限到点仍未达标：也返回 True（按当前分数快速完成，不留半局给恢复流程打断）。
        from src.tasks.event import _minigame as minigame
        with patch.object(minigame, '_MINIGAME_PLAY_TIMEOUT', 0.0), \
                patch.object(self.task, 'is_screen', return_value=True), \
                patch.object(self.task, 'click_relative', side_effect=AssertionError('超时后不应再点')):
            self.assertTrue(self.task._play_minigame_run())

    def test_minigame_score_parses_thousands_separator(self):
        boxes = self._minigame_boxes()
        with patch.object(self.task, '_optional_box', side_effect=lambda name: boxes.get(name)), \
                patch.object(self.task, 'ocr', return_value=[Box(0, 0, 9, 9, confidence=1, name='7,500')]):
            self.assertEqual(7500, self.task._minigame_score())  # 千分位分隔符去掉后转整数。
        with patch.object(self.task, '_optional_box', side_effect=lambda name: boxes.get(name)), \
                patch.object(self.task, 'ocr', return_value=[Box(0, 0, 9, 9, confidence=1, name='BEAT')]):
            self.assertIsNone(self.task._minigame_score())  # 区域里没有数字：判不出来。
        with patch.object(self.task, '_optional_box', return_value=None):
            self.assertIsNone(self.task._minigame_score())  # 区域未标注：不读分。

    def test_claim_minigame_mission_rewards_stops_when_popup_closed(self):
        # 弹窗被误点关掉后不再按固定区域点「全部领取」（否则就是盲点主界面）。
        boxes = self._minigame_boxes()
        with patch.object(self.task, '_optional_box', side_effect=lambda name: boxes.get(name)), \
                patch.object(self.task, 'is_screen', return_value=False) as screen_mock, \
                patch.object(self.task, 'is_box_highlighted', side_effect=AssertionError('弹窗不在不应判态')), \
                patch.object(self.task, 'click_box', side_effect=AssertionError('弹窗不在不应点击')):
            self.task._claim_minigame_mission_rewards()
        screen_mock.assert_called_once_with('event_minigame_mission_popup')  # 只做弹窗在不在的判据。

    def test_back_to_minigame_main_retries_when_click_swallowed(self):
        # 结算动画期间点「返回」会被吃掉：第一次点完没回主界面就补点一次（第二次成功即返回）。
        checks = []  # 主界面判据的调用次数：第 1 轮不命中，第 2 轮命中。

        def is_screen(name):
            if name != 'event_minigame_main':
                return False
            checks.append(1)
            return len(checks) > 1

        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'is_screen', side_effect=is_screen), \
                patch.object(self.task, 'wait_until', side_effect=lambda condition, **kwargs: condition()):
            self.task._back_to_minigame_main()
        self.assertEqual(2, click_mock.call_count)  # 补点一次。
        self.assertEqual('box_event_minigame_result_back', click_mock.call_args_list[1].args[0])  # 补点的还是结算页「返回」。

    def test_back_to_minigame_main_gives_up_after_attempts(self):
        # 补点次数用尽仍未回主界面：抛等待失败交 try_step 恢复（不在结算页上硬撑）。
        from src.tasks.event._const import _MINIGAME_BACK_ATTEMPTS
        with patch.object(self.task, 'click_box') as click_mock, \
                patch.object(self.task, 'is_screen', return_value=False), \
                patch.object(self.task, 'wait_until', side_effect=lambda condition, **kwargs: condition()):
            self.assertRaises(WaitFailedException, self.task._back_to_minigame_main)
        self.assertEqual(_MINIGAME_BACK_ATTEMPTS, click_mock.call_count)  # 尝试次数封顶。

    @unittest.skipUnless(os.path.exists('ok_templates/event_minigame_tcr_07.png'),
                         '缺少实机截图（ok_templates 子模块未检出）')
    def test_minigame_main_screen_on_real_screenshot(self):
        # 实机标定回归：主界面左上标题栏读到「小游戏」即判为小游戏主界面（OCR 文字判据，不吃逐期美术模板）；
        # 关卡内页没有标题栏文字，同判据不得命中。
        # 负例另取活动主页：它的菜单带里也有「小游戏」入口文字，判据必须限定在标题栏区域内才不会误命中。
        self.set_image('ok_templates/event_minigame_tcr_07.png')
        self.assertTrue(self.task.is_screen('event_minigame_main'))
        self.set_image('ok_templates/event_minigame_tcr_03.png')
        self.assertFalse(self.task.is_screen('event_minigame_main'))
        self.set_image('ok_templates/event_big_main_01.png')
        self.assertFalse(self.task.is_screen('event_minigame_main'))

    def test_is_box_highlighted_splits_yellow_and_brown(self):
        # 「全部领取」两态是换色不是换形：色相带判据在合成帧上分得开（可领 ≈52° 亮黄 / 不可领 ≈20° 暗棕）。
        frame = np.zeros((80, 200, 3), dtype=np.uint8)  # 合成帧：左半亮黄、右半暗棕。
        frame[:, :100] = (0, 220, 255)  # BGR 亮黄：色相 ≈52°，落在 32~80 度带内、饱和度足够。
        frame[:, 100:] = (0, 67, 200)  # BGR 暗棕：色相 ≈20°，落在带外。
        with patch.object(type(self.task), 'frame', new_callable=PropertyMock, return_value=frame):
            self.assertTrue(self.task.is_box_highlighted(Box(0, 0, 100, 80)))  # 亮黄侧 = 仍可领。
            self.assertFalse(self.task.is_box_highlighted(Box(100, 0, 100, 80)))  # 暗棕侧 = 已领完。
        with patch.object(type(self.task), 'frame', new_callable=PropertyMock, return_value=None):
            self.assertFalse(self.task.is_box_highlighted(Box(0, 0, 10, 10)))  # 无帧：保守判非高亮。


if __name__ == '__main__':
    unittest.main()
