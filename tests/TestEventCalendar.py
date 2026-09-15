"""活动列表行识别：模板生成（纯函数/解析）+ 真实截图匹配回归。

期望坐标来自 2560x1440 实机截图（tests/images/event_list.png）与官方活动图
（tests/images/event_banner_great_villain_union.png）的离线标定，测量脚本见 dev_tools/check_banner_match*.py。
"""
import hashlib
import os
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

import cv2
import numpy as np

from ok.test.TaskTestCase import TaskTestCase
from scripts import build_event_assets
from src import event_calendar
from src import globals as app_globals
from src.config import config
from src.tasks.HarvestTask import HarvestTask

EVENT_LIST = 'tests/images/event_list.png'  # 2560x1440 活动列表截图（GREAT VILLAIN UNION 在列表第 3 行）。
BANNER = 'tests/images/event_banner_great_villain_union.png'  # 官方活动图，1110x370。
NOT_IN_LIST = 'tests/images/tribe_tower.png'  # 列表里不存在的画面，用作负样本。
ROW_AT_1440 = (1355, 879)  # 期望命中位置（模板左上角），2560x1440 实测。
ROW_AT_720 = (677, 440)  # 同一截图降采样到 1280x720 后应落在约一半坐标。
PANEL_AT_1440 = (881, 286, 799, 1038)  # box_event_banner_area：XAL 源点 y=286.14 按四舍五入落到 coco 的值。
TOLERANCE = 2  # 坐标容差（像素）。


class TestEventCalendarPureFunctions(unittest.TestCase):
    """纯几何与接口解析：不依赖 ok 框架、不触网。"""

    @staticmethod
    def _banner():
        image = cv2.imread(BANNER)
        assert image is not None, f'banner fixture missing: {BANNER}'
        return image

    def test_row_width_scales_with_resolution(self):
        self.assertAlmostEqual(749.0, event_calendar.row_width(2560, 1440), places=3)  # 1440p 实测。
        self.assertAlmostEqual(374.5, event_calendar.row_width(1280, 720), places=3)  # 720p 减半。

    def test_row_width_is_zero_without_resolution(self):
        self.assertEqual(0, event_calendar.screen_scale(0, 0))  # 无帧环境由调用方判定为不可用。
        self.assertEqual(0, event_calendar.screen_scale(None, None))

    def test_build_row_template_size_and_linear_scaling(self):
        banner = self._banner()
        template = event_calendar.build_row_template(banner, 749)
        self.assertEqual((175, 262), template.shape[:2])  # (高, 宽)：行高的 70% x 行宽的 35%。
        doubled = event_calendar.build_row_template(banner, 1498)
        self.assertEqual((349, 525), doubled.shape[:2])  # 行宽翻倍 -> 模板尺寸翻倍（等比缩放正确）。

    def test_subject_height_fits_last_row_visible_part(self):
        # 列表最后一行只有 70% 可见（面板底边裁切）：SUBJECT 下界必须不超过 0.70，否则该行永远匹配不到。
        self.assertLessEqual(event_calendar.SUBJECT[3], 0.70)

    def test_build_row_template_keeps_bgr_channels(self):
        self.assertEqual(3, event_calendar.build_row_template(self._banner(), 749).shape[2])

    def test_build_row_template_rejects_invalid_input(self):
        # 空模板会让匹配静默失败，这里要求显式报错。
        with self.assertRaises(ValueError):
            event_calendar.build_row_template(None, 749)
        with self.assertRaises(ValueError):
            event_calendar.build_row_template(np.zeros((10, 10), dtype=np.uint8), 749)

    def test_parse_events_keeps_only_version_event_story_event(self):
        calendar = {'data': {
            'version_event': {'items': [
                {'banner': 'EVENT_BANNER_STORY', 'name': '剧情活动', 'type': 'StoryEvent',
                 'start_time': '1690000000', 'end_time': '1700000000'},
                {'banner': 'EVENT_BANNER_LOGIN', 'name': '登录活动', 'type': 'LoginEvent'},  # 子类型不符。
                {'banner': 'EVENT_BANNER_STORY', 'name': '重复的同图条目', 'type': 'StoryEvent'},  # 同图去重。
                {'name': '没有活动图的条目', 'type': 'StoryEvent'},  # 无图无法匹配。
            ]},
            'character_gacha': {'items': [
                {'banner': 'EVENT_BANNER_GACHA', 'name': '招募', 'type': 'PickupGachaEvent'},  # 分类不符。
            ]},
        }}
        events = event_calendar.parse_events(calendar)
        self.assertEqual(['EVENT_BANNER_STORY'], [e.key for e in events])  # 只留剧情大活动且按图去重。
        self.assertEqual('version_event', events[0].category)
        self.assertEqual('StoryEvent', events[0].event_type)
        self.assertEqual(1690000000, events[0].start_time)
        self.assertEqual(1700000000, events[0].end_time)
        self.assertEqual('剧情活动', events[0].name)  # name 保留接口原文（落盘不加工）。
        self.assertEqual('STORY', events[0].display_name)  # 展示名从 banner 键去前缀推导。

    def test_parse_events_tolerates_empty_payload(self):
        self.assertEqual([], event_calendar.parse_events(None))
        self.assertEqual([], event_calendar.parse_events({}))
        self.assertEqual([], event_calendar.parse_events({'data': {'version_event': None}}))
        self.assertEqual([], event_calendar.parse_events({'data': {'version_event': {'items': []}}}))

    def test_strip_banner_prefix(self):
        self.assertEqual('GREATVILLAINUNION', event_calendar.strip_banner_prefix('EVENT_BANNER_GREATVILLAINUNION'))
        self.assertEqual('greatvillainunion', event_calendar.strip_banner_prefix('event_banner_greatvillainunion'))  # 前缀大小写无关，剩余部分保留原样。
        self.assertEqual('', event_calendar.strip_banner_prefix('EVENT_BANNER_'))  # 前缀整个就是键：去完为空。
        self.assertEqual('EVENT_BANNER', event_calendar.strip_banner_prefix('EVENT_BANNER'))  # 差下划线不构成前缀：原样返回。
        self.assertEqual('OTHER_KEY', event_calendar.strip_banner_prefix('OTHER_KEY'))  # 无前缀原样返回。
        self.assertEqual('', event_calendar.strip_banner_prefix(''))  # 空键安全。

    def test_fetch_calendar_does_not_retry_on_4xx(self):
        error = urllib.error.HTTPError(event_calendar.CALENDAR_URL, 403, 'Forbidden', None, None)
        with patch.object(event_calendar.urllib.request, 'urlopen', side_effect=error) as opener, \
                patch.object(event_calendar, 'RETRY_DELAY', 0):
            with self.assertRaises(urllib.error.HTTPError):
                event_calendar.fetch_calendar(attempts=3)
        self.assertEqual(1, opener.call_count)  # 4xx 是请求本身无效，不重试。

    def test_fetch_calendar_retries_on_5xx(self):
        error = urllib.error.HTTPError(event_calendar.CALENDAR_URL, 502, 'Bad Gateway', None, None)
        with patch.object(event_calendar.urllib.request, 'urlopen', side_effect=error) as opener, \
                patch.object(event_calendar, 'RETRY_DELAY', 0):
            with self.assertRaises(urllib.error.HTTPError):
                event_calendar.fetch_calendar(attempts=3)
        self.assertEqual(3, opener.call_count)  # 5xx 属于服务端抖动，按 attempts 重试。

    def test_fetch_calendar_retries_then_raises(self):
        with patch.object(event_calendar.urllib.request, 'urlopen', side_effect=OSError('模拟断网')) as opener, \
                patch.object(event_calendar, 'RETRY_DELAY', 0):
            with self.assertRaises(OSError):
                event_calendar.fetch_calendar(attempts=3)
        self.assertEqual(3, opener.call_count)  # 三次都失败才放弃（不再重试）。

    def test_download_banner_does_not_retry_on_4xx(self):
        url = 'https://sg-tools-cdn.invalid/a.png'
        error = urllib.error.HTTPError(url, 404, 'Not Found', None, None)
        with patch.object(event_calendar.urllib.request, 'urlopen', side_effect=error) as opener, \
                patch.object(event_calendar, 'RETRY_DELAY', 0):
            with tempfile.TemporaryDirectory() as tmp:
                result = event_calendar.download_banner(url, os.path.join(tmp, 'a.png'), attempts=3)
        self.assertFalse(result)
        self.assertEqual(1, opener.call_count)  # 4xx 是请求本身无效，不重试。

    def test_download_banner_retries_on_5xx(self):
        url = 'https://sg-tools-cdn.invalid/a.png'
        error = urllib.error.HTTPError(url, 503, 'Service Unavailable', None, None)
        with patch.object(event_calendar.urllib.request, 'urlopen', side_effect=error) as opener, \
                patch.object(event_calendar, 'RETRY_DELAY', 0):
            with tempfile.TemporaryDirectory() as tmp:
                result = event_calendar.download_banner(url, os.path.join(tmp, 'a.png'), attempts=3)
        self.assertFalse(result)
        self.assertEqual(3, opener.call_count)  # 5xx 属于服务端抖动，按 attempts 重试。

    def test_download_banner_retries_then_fails(self):
        with patch.object(event_calendar.urllib.request, 'urlopen', side_effect=OSError('模拟断网')) as opener, \
                patch.object(event_calendar, 'RETRY_DELAY', 0):
            with tempfile.TemporaryDirectory() as tmp:
                result = event_calendar.download_banner('https://example.invalid/a.png',
                                                      os.path.join(tmp, 'a.png'), attempts=3)
        self.assertFalse(result)  # 重试后仍失败 -> 返回 False，不抛异常。
        self.assertEqual(3, opener.call_count)

    def test_banner_url_is_deterministic_and_path_shaped(self):
        base = len(event_calendar.CDN_BASE) + 1
        url = event_calendar.banner_url('EVENT_BANNER_X')
        self.assertTrue(url.startswith(event_calendar.CDN_BASE + '/'))
        self.assertTrue(url.endswith('.png'))
        self.assertEqual(url, event_calendar.banner_url('EVENT_BANNER_X'))  # 同输入同地址（可作缓存键）。
        self.assertNotEqual(url, event_calendar.banner_url('EVENT_BANNER_Y'))
        self.assertEqual(3, len(url[base:].split('/')))  # schedule/banner/<key> -> 3 段。
        pass_url = event_calendar.banner_url('EVENT_BANNER_X', 'SeasonPass')
        self.assertEqual(4, len(pass_url[base:].split('/')))  # icon/Logo/pass/<key> -> 4 段。

    def test_ensure_cached_returns_existing_file_without_download(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            url = 'https://example.invalid/event.png'
            path = os.path.join(cache_dir, hashlib.md5(url.encode()).hexdigest() + '.png')
            with open(path, 'wb') as file:
                file.write(b'cached')
            with patch.object(event_calendar, 'download_banner') as download:
                self.assertEqual(path, event_calendar.ensure_cached(url, cache_dir=cache_dir))
            download.assert_not_called()  # 命中缓存不应触发网络请求。

    def test_ensure_cached_accepts_calendar_event(self):
        event = event_calendar.CalendarEvent(key='K', name='N', category='version_event', event_type='',
                                           start_time=0, end_time=0, url='https://example.invalid/k.png')
        with tempfile.TemporaryDirectory() as cache_dir:
            with patch.object(event_calendar, 'download_banner', return_value=False) as download:
                self.assertIsNone(event_calendar.ensure_cached(event, cache_dir=cache_dir))
            download.assert_called_once()  # 未缓存 -> 尝试下载一次。

    def test_ensure_cached_discards_partial_file_on_failure(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            def fake_download(url, path, timeout=0, attempts=1):
                with open(path, 'wb') as file:  # 模拟下载失败留下的半截文件。
                    file.write(b'partial')
                return False

            with patch.object(event_calendar, 'download_banner', side_effect=fake_download):
                self.assertIsNone(event_calendar.ensure_cached('https://example.invalid/x.png', cache_dir=cache_dir))
            self.assertEqual([], os.listdir(cache_dir))  # 半截文件必须清掉，否则下次会误判为已缓存。

    def test_ensure_cached_returns_path_after_successful_download(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            def fake_download(url, path, timeout=0, attempts=1):
                with open(path, 'wb') as file:
                    file.write(b'\x89PNG\r\n\x1a\n')
                return True

            with patch.object(event_calendar, 'download_banner', side_effect=fake_download) as download:
                path = event_calendar.ensure_cached('https://example.invalid/y.png', cache_dir=cache_dir)
            download.assert_called_once()
            self.assertTrue(os.path.exists(path))


class TestEventCalendarOfflineFallback(unittest.TestCase):
    """断网保底：assets/event_calendar 保底包与 prepare() 的降级行为（全程不触网）。"""

    @staticmethod
    def _touch(path):
        with open(path, 'wb') as file:
            file.write(b'x')
        return path

    @staticmethod
    def _event(key='EVENT_BANNER_X'):
        return event_calendar.CalendarEvent(key=key, name=key, category='version_event', event_type='',
                                          start_time=0, end_time=0,
                                          url=f'https://example.invalid/{key}.png')

    def test_local_banner_path_prefers_cache_over_bundled(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, 'cache')
            bundled_dir = os.path.join(tmp, 'bundled')
            os.makedirs(cache_dir)
            os.makedirs(bundled_dir)
            url = 'https://example.invalid/event.png'
            cached = self._touch(os.path.join(cache_dir, hashlib.md5(url.encode()).hexdigest() + '.png'))
            bundled = self._touch(os.path.join(bundled_dir, 'EVENT_BANNER_X.png'))
            self.assertEqual(cached, event_calendar.local_banner_path('EVENT_BANNER_X', url, cache_dir, bundled_dir))
            os.remove(cached)  # 缓存被清掉后落到保底包。
            self.assertEqual(bundled, event_calendar.local_banner_path('EVENT_BANNER_X', url, cache_dir, bundled_dir))
            self.assertIsNone(event_calendar.local_banner_path('', url, cache_dir, bundled_dir))  # 只有 URL 不查保底包。

    def test_bundled_keys_lists_png_stems_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], event_calendar.bundled_keys(tmp))
            self.assertEqual([], event_calendar.bundled_keys(os.path.join(tmp, 'nope')))
            for name in ('B.png', 'a.png', 'note.txt'):
                self._touch(os.path.join(tmp, name))
            self.assertEqual(['B', 'a'], event_calendar.bundled_keys(tmp))

    def test_ensure_cached_uses_bundled_pack_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled_dir = os.path.join(tmp, 'bundled')
            os.makedirs(bundled_dir)
            bundled = self._touch(os.path.join(bundled_dir, 'EVENT_BANNER_X.png'))
            with patch.object(event_calendar, 'download_banner') as download:
                path = event_calendar.ensure_cached(self._event(), cache_dir=os.path.join(tmp, 'cache'),
                                                  bundled_dir=bundled_dir)
            self.assertEqual(bundled, path)
            download.assert_not_called()  # 保底包命中就不应联网。

    def test_prepare_falls_back_to_bundled_pack_when_calendar_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled_dir = os.path.join(tmp, 'bundled')
            os.makedirs(bundled_dir)
            for key in ('EVENT_BANNER_X', 'EVENT_BANNER_Y'):
                self._touch(os.path.join(bundled_dir, key + '.png'))
            with patch.object(event_calendar, 'fetch_calendar', side_effect=OSError('模拟接口不可达')):
                events = event_calendar.prepare(cache_dir=os.path.join(tmp, 'cache'), bundled_dir=bundled_dir,
                                              attempts=1)  # 单次尝试，避免用例里真等重试间隔。
        self.assertEqual(['EVENT_BANNER_X', 'EVENT_BANNER_Y'], [e.key for e in events])  # 不抛异常，用保底包顶上。
        self.assertTrue(all(e.category == 'bundled' for e in events))  # 无接口元数据时名字用键顶替。

    def test_prepare_keeps_online_metadata_and_dedupes_bundled(self):
        calendar = {'data': {'version_event': {'items': [
            {'banner': 'EVENT_BANNER_X', 'name': '线上活动名', 'type': 'StoryEvent'}]}}}
        with tempfile.TemporaryDirectory() as tmp:
            bundled_dir = os.path.join(tmp, 'bundled')
            os.makedirs(bundled_dir)
            for key in ('EVENT_BANNER_X', 'EVENT_BANNER_Y'):
                self._touch(os.path.join(bundled_dir, key + '.png'))
            with patch.object(event_calendar, 'fetch_calendar', return_value=calendar):
                events = event_calendar.prepare(cache_dir=os.path.join(tmp, 'cache'), bundled_dir=bundled_dir)
        self.assertEqual(['EVENT_BANNER_X', 'EVENT_BANNER_Y'], [e.key for e in events])  # 同键不重复。
        self.assertEqual('线上活动名', events[0].name)  # 线上条目 name 保留接口原文。
        self.assertEqual('X', events[0].display_name)  # 展示名从键去前缀推导。
        self.assertEqual('version_event', events[0].category)
        self.assertEqual('bundled', events[1].category)  # 只在保底包里的活动排后面。

    def test_prepare_drops_events_whose_image_is_unavailable(self):
        calendar = {'data': {'version_event': {'items': [
            {'banner': 'EVENT_BANNER_MISSING', 'name': 'M', 'type': 'StoryEvent'}]}}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(event_calendar, 'fetch_calendar', return_value=calendar), \
                    patch.object(event_calendar, 'download_banner', return_value=False):
                events = event_calendar.prepare(cache_dir=os.path.join(tmp, 'cache'),
                                              bundled_dir=os.path.join(tmp, 'bundled'), attempts=1)
        self.assertEqual([], events)  # 图拿不到的活动不进清单，避免后续匹配必然落空。

    def test_prepare_ignores_non_story_events(self):
        # 登录/招募等不进清单：它们的图既不下载也不匹配（运行期只做剧情大活动）。
        calendar = {'data': {
            'version_event': {'items': [{'banner': 'EVENT_BANNER_LOGIN', 'name': '登录', 'type': 'LoginEvent'}]},
            'character_gacha': {'items': [{'banner': 'EVENT_BANNER_GACHA', 'name': '招募'}]},
        }}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(event_calendar, 'fetch_calendar', return_value=calendar), \
                    patch.object(event_calendar, 'download_banner') as download:
                events = event_calendar.prepare(cache_dir=os.path.join(tmp, 'cache'),
                                              bundled_dir=os.path.join(tmp, 'bundled'), attempts=1)
        self.assertEqual([], events)
        download.assert_not_called()  # 范围外的活动连下载都不该尝试。


class TestEventCalendarSnapshot(unittest.TestCase):
    """活动日历状态快照：解析、落盘/读回、refresh 的降级行为（全程不触网）。"""

    @staticmethod
    def _calendar():
        return {'data': {
            'version_event': {'items': [
                {'banner': 'EVENT_BANNER_STORY', 'name': 'No Caller ID', 'type': 'StoryEvent',
                 'start_time': '1788404400', 'end_time': '1789588799', 'rewards': [{'name': 'x'}]},
                {'banner': 'EVENT_BANNER_DAILY_LOGIN_52', 'name': 'Daily Login Event', 'type': 'LoginEvent'},
            ]},
            'raid': {'items': [{'name': 'Coordinated Operation', 'type': 'CooperationEvent',
                                'start_time': '1789095600', 'end_time': '1789311599'}]},
            'arena': {'items': [{'name': 'Champion Arena', 'type': 'ArenaChampionSeason',
                                 'start_time': '1789005600', 'end_time': '1789743599',
                                 'next_start_time': '1790215200', 'next_end_time': '1790953199'}]},
        }}

    @staticmethod
    def _fake_download(size=(100, 300)):
        def fake(url, path, timeout=0, attempts=1):
            cv2.imwrite(path, np.zeros((size[0], size[1], 3), np.uint8))
            return True
        return fake

    @staticmethod
    def _event(key='EVENT_BANNER_STORY', start_time=0, end_time=0):
        return event_calendar.CalendarEvent(key=key, name=key, category='version_event',
                                            event_type='StoryEvent', start_time=start_time, end_time=end_time,
                                            url=f'https://example.invalid/{key}.png')

    def test_parse_status_keeps_scalars_and_drops_rewards(self):
        status = event_calendar.parse_status(self._calendar())
        self.assertEqual(['version_event', 'raid', 'arena'], list(status.keys()))
        story = status['version_event'][0]
        self.assertEqual('No Caller ID', story['name'])
        self.assertEqual('StoryEvent', story['type'])
        self.assertNotIn('rewards', story)  # 大数组不进缓存。
        self.assertEqual(2, len(status['version_event']))  # 同分类下的登录活动也照收（状态不分类型）。
        self.assertEqual('1790215200', status['arena'][0]['next_start_time'])  # 竞技场的下期时间保留。

    def test_parse_status_skips_missing_categories(self):
        self.assertEqual({}, event_calendar.parse_status(None))
        self.assertEqual({}, event_calendar.parse_status({'data': {'raid': None}}))
        self.assertEqual({'raid': [{'name': 'Coop'}]},
                         event_calendar.parse_status({'data': {'raid': {'items': [{'name': 'Coop'}]}}}))

    def test_snapshot_roundtrip_and_helpers(self):
        event = self._event('EVENT_BANNER_STORY')
        snapshot = event_calendar.CalendarSnapshot(fetched_at=int(time.time()),
                                                 events=(event,),
                                                 status={'raid': [{'name': 'Coop'}]})
        with tempfile.TemporaryDirectory() as cache_dir:
            path = event_calendar.save_snapshot(snapshot, cache_dir)
            self.assertEqual(event_calendar.snapshot_path(cache_dir), path)
            loaded = event_calendar.load_snapshot(cache_dir)
        self.assertEqual(snapshot.events, loaded.events)  # CalendarEvent 是 frozen dataclass，可直接比较。
        self.assertEqual(snapshot.status, loaded.status)
        self.assertTrue(loaded.is_fresh(60))  # 刚拉的在 ttl 内。
        self.assertFalse(loaded.is_fresh(0))  # ttl=0 视为已过期。
        self.assertEqual([{'name': 'Coop'}], loaded.status_of('raid'))
        self.assertEqual([], loaded.status_of('arena'))  # 不存在的分类返回空列表。

    def test_load_snapshot_returns_none_when_missing_or_broken(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            self.assertIsNone(event_calendar.load_snapshot(cache_dir))  # 没有缓存。
            with open(event_calendar.snapshot_path(cache_dir), 'w', encoding='utf-8') as file:
                file.write('{ 这不是 JSON')
            self.assertIsNone(event_calendar.load_snapshot(cache_dir))  # 损坏的缓存按没有处理。
            self.assertIsNone(event_calendar.snapshot_from_dict(['不是 dict']))  # 结构不对也不抛异常。

    def test_refresh_writes_snapshot_and_caches_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, 'cache')
            bundled_dir = os.path.join(tmp, 'bundled')
            with patch.object(event_calendar, 'fetch_calendar', return_value=self._calendar()), \
                    patch.object(event_calendar, 'download_banner', side_effect=self._fake_download()):
                snapshot = event_calendar.refresh(cache_dir=cache_dir, bundled_dir=bundled_dir)
            self.assertEqual(['EVENT_BANNER_STORY'], [event.key for event in snapshot.events])  # 只留剧情活动。
            self.assertTrue(snapshot.is_fresh(60))
            self.assertTrue(os.path.exists(event_calendar.cache_path(snapshot.events[0].url, cache_dir)))  # 图落 cache。
            self.assertEqual('No Caller ID', snapshot.events[0].name)  # 落盘保留接口原文，不做加工。
            self.assertEqual('STORY', snapshot.events[0].display_name)  # 展示名读取时从键推导。
            loaded = event_calendar.load_snapshot(cache_dir)  # JSON 也能读回。
        self.assertEqual(['EVENT_BANNER_STORY'], [event.key for event in loaded.events])
        self.assertEqual('Champion Arena', loaded.status_of('arena')[0]['name'])
        self.assertEqual('Coordinated Operation', loaded.status_of('raid')[0]['name'])

    def test_refresh_degrades_silently_and_keeps_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, 'cache')
            os.makedirs(cache_dir)
            previous = event_calendar.CalendarSnapshot(fetched_at=1700000000, events=(), status={'raid': [{'name': 'old'}]})
            event_calendar.save_snapshot(previous, cache_dir)
            before = open(event_calendar.snapshot_path(cache_dir), encoding='utf-8').read()
            with patch.object(event_calendar, 'fetch_calendar', side_effect=OSError('模拟断网')), \
                    patch.object(event_calendar, 'download_banner'):
                snapshot = event_calendar.refresh(cache_dir=cache_dir, bundled_dir=os.path.join(tmp, 'bundled'),
                                                attempts=1)
            after = open(event_calendar.snapshot_path(cache_dir), encoding='utf-8').read()
        self.assertEqual(0, snapshot.fetched_at)  # 没拉到线上数据。
        self.assertEqual((), snapshot.events)  # 无保底包时清单为空，但不抛异常。
        self.assertEqual(before, after)  # 旧快照不被空数据覆盖。

    def test_pick_events_orders_newest_first(self):
        # 接口顺序不等于时间序：这里故意乱序给，验证按 start_time 倒序取。
        events = tuple(self._event(key, start) for key, start in (('A', 100), ('B', 300), ('C', 200)))
        snapshot = event_calendar.CalendarSnapshot(fetched_at=1, events=events, status={})
        self.assertEqual(['B'], [event.key for event in snapshot.pick_events()])  # 默认 1 个 = 最新。
        self.assertEqual(['B', 'C'], [event.key for event in snapshot.pick_events(2)])  # 两个并行任务各认一个。
        self.assertEqual(['B', 'C', 'A'], [event.key for event in snapshot.pick_events(None)])  # None = 全部。
        self.assertEqual([], snapshot.pick_events(0))
        self.assertEqual(['B', 'C', 'A'], [event.key for event in snapshot.pick_events(9)])  # 不足 count 时给现有的。

    def test_pick_events_keeps_api_order_on_ties_and_puts_missing_time_last(self):
        events = (self._event('BUNDLED', 0),  # 保底包独有：没有起止时间。
                  self._event('FIRST', 500),
                  self._event('SECOND', 500))  # 与 FIRST 同时间。
        snapshot = event_calendar.CalendarSnapshot(fetched_at=1, events=events, status={})
        self.assertEqual(['FIRST', 'SECOND'], [event.key for event in snapshot.pick_events(2)])  # 同时间保持接口顺序。
        self.assertEqual('BUNDLED', snapshot.pick_events(None)[-1].key)  # 无时间的排最后。

    def test_pick_events_filters_expired_and_keeps_unknown(self):
        now = 1000
        events = tuple(self._event(key, start, end) for key, start, end in (
            ('NEW', 900, 2000),  # 未过期。
            ('OLD', 300, 500),  # end_time 已过 → 剔除。
            ('UNKNOWN', 0, 0),  # end_time=0 视为时间未知 → 保留。
        ))
        snapshot = event_calendar.CalendarSnapshot(fetched_at=1, events=events, status={})
        self.assertEqual(['NEW'], [event.key for event in snapshot.pick_events(1, now=now)])
        self.assertEqual(['NEW', 'UNKNOWN'], [event.key for event in snapshot.pick_events(None, now=now)])

    def test_expiring_events_picks_ending_within_window(self):
        now = 100000
        within = event_calendar.EXPIRE_NOTIFY_SECONDS  # 24 小时窗口。
        events = tuple(self._event(key, 0, end) for key, end in (
            ('SOON', now + 3600),  # 1 小时后结束 → 命中。
            ('EDGE', now + within),  # 恰好压线 → 命中。
            ('LATER', now + within + 1),  # 窗口外 → 不命中。
            ('GONE', now - 1),  # 已过期 → 不命中（refresh 已剔除，这里防御）。
            ('UNKNOWN', 0),  # end_time=0 视为时间未知 → 不提示。
        ))
        self.assertEqual(['SOON', 'EDGE'],
                         [event.key for event in event_calendar.expiring_events(events, now=now)])
        self.assertEqual([], event_calendar.expiring_events([], now=now))
        self.assertEqual([], event_calendar.expiring_events(events, within_seconds=0, now=now))  # 窗口为 0。

    def test_expiring_events_keeps_input_order(self):
        now = 100000
        events = (self._event('B', 0, now + 60), self._event('A', 0, now + 30))  # 故意乱序给。
        self.assertEqual(['B', 'A'],
                         [event.key for event in event_calendar.expiring_events(events, now=now)])  # 保持传入顺序。

    def test_prune_cache_never_touches_non_banner_files(self):
        # 只删本项目缓存命名形态（md5 十六进制 + .png）：陌生 .png、非 png 文件、同名目录一律不动。
        with tempfile.TemporaryDirectory() as cache_dir:
            keep_name = os.path.basename(event_calendar.cache_path('https://example.invalid/keep.png', cache_dir))
            kept_paths = []  # 必须原样保留的条目。
            for name in (keep_name, 'manual_copy.png', 'banner.jpg', 'notes.txt', 'calendar.json'):
                path = os.path.join(cache_dir, name)
                with open(path, 'w', encoding='utf-8') as file:
                    file.write('x')
                kept_paths.append(path)
            dir_name = hashlib.md5(b'https://example.invalid/dir.png').hexdigest() + '.png'  # 形态正确但是目录。
            dir_path = os.path.join(cache_dir, dir_name)
            os.makedirs(dir_path)
            kept_paths.append(dir_path)
            removed = event_calendar.prune_cache(['https://example.invalid/keep.png'], cache_dir)
            self.assertEqual([], removed)  # 没有本项目形态的过期缓存文件 → 什么都不删。
            for path in kept_paths:  # 陌生文件与同名目录都不在删除范围内。
                self.assertTrue(os.path.exists(path))

    def test_prune_cache_survives_failed_removal(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            name = os.path.basename(event_calendar.cache_path('https://example.invalid/keep.png', cache_dir))
            with open(os.path.join(cache_dir, name), 'w', encoding='utf-8') as file:
                file.write('x')
            with patch.object(os, 'remove', side_effect=OSError('删除失败不应抛')):  # 底层删除失败被吞掉。
                removed = event_calendar.prune_cache([], cache_dir)  # keep_urls 为空：全部判为过期。
            self.assertEqual([name], removed)  # 删除异常不阻塞主流程。

    def test_prune_cache_keeps_only_given_urls(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            keep_name = os.path.basename(event_calendar.cache_path('https://example.invalid/keep.png', cache_dir))
            stale_names = sorted(
                os.path.basename(event_calendar.cache_path(f'https://example.invalid/stale{i}.png', cache_dir))
                for i in (1, 2))  # 往期遗留也用本项目缓存命名形态，才是真实可删对象。
            for name in (keep_name, *stale_names, 'calendar.json'):
                with open(os.path.join(cache_dir, name), 'w', encoding='utf-8') as file:
                    file.write('x')
            removed = event_calendar.prune_cache(['https://example.invalid/keep.png'], cache_dir)
            self.assertEqual(stale_names, removed)  # 只删非当前的缓存形态文件。
            self.assertEqual(sorted([keep_name, 'calendar.json']), sorted(os.listdir(cache_dir)))

    def test_prune_cache_on_missing_dir_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], event_calendar.prune_cache([], os.path.join(tmp, 'nope')))

    def test_refresh_prunes_previous_events_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, 'cache')
            os.makedirs(cache_dir)
            stale = event_calendar.cache_path('https://example.invalid/stale.png', cache_dir)  # 往期活动残留的图。
            with open(stale, 'w', encoding='utf-8') as file:
                file.write('x')
            with patch.object(event_calendar, 'fetch_calendar', return_value=self._calendar()), \
                    patch.object(event_calendar, 'download_banner', side_effect=self._fake_download()):
                snapshot = event_calendar.refresh(cache_dir=cache_dir, bundled_dir=os.path.join(tmp, 'bundled'))
            self.assertFalse(os.path.exists(stale))  # 刷新成功后清掉非当期的图。
            self.assertTrue(os.path.exists(event_calendar.cache_path(snapshot.events[0].url, cache_dir)))
            self.assertTrue(os.path.exists(event_calendar.snapshot_path(cache_dir)))

    def test_refresh_prunes_expired_cache_when_calendar_ok(self):
        # 过期活动不下载、不进快照，且其 cache 图在成功拉取后被清掉（与往期/下架图同一条清理路径）。
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, 'cache')
            os.makedirs(cache_dir)
            stale = event_calendar.cache_path('https://example.invalid/expired.png', cache_dir)  # 过期活动的图。
            with open(stale, 'w', encoding='utf-8') as file:
                file.write('x')
            calendar = {'data': {'version_event': {'items': [
                {'banner': 'EVENT_BANNER_STORY', 'name': 'No Caller ID', 'type': 'StoryEvent',
                 'start_time': '1788404400', 'end_time': '1789588799', 'rewards': [{'name': 'x'}]},
                {'banner': 'EVENT_BANNER_EXPIRED', 'name': 'Expired Story', 'type': 'StoryEvent',
                 'start_time': '1788404400', 'end_time': '1', 'rewards': [{'name': 'x'}]},
            ]}}}
            with patch.object(event_calendar, 'fetch_calendar', return_value=calendar), \
                    patch.object(event_calendar, 'download_banner', side_effect=self._fake_download()) as dl_mock, \
                    patch.object(event_calendar.time, 'time', return_value=2000):  # 当前时间在 1 之后。
                snapshot = event_calendar.refresh(cache_dir=cache_dir, bundled_dir=os.path.join(tmp, 'bundled'))
            self.assertEqual(['EVENT_BANNER_STORY'], [event.key for event in snapshot.events])  # 过期活动不在快照。
            self.assertFalse(os.path.exists(stale))  # 过期活动图被清掉。
            for call in dl_mock.call_args_list:  # 过期活动不在下载名单。
                self.assertNotIn('EVENT_BANNER_EXPIRED', str(call.args))

    def test_refresh_keeps_cache_when_calendar_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, 'cache')
            os.makedirs(cache_dir)
            old = os.path.join(cache_dir, 'deadbeef.png')  # 上次成功下载的图。
            with open(old, 'w', encoding='utf-8') as file:
                file.write('x')
            with patch.object(event_calendar, 'fetch_calendar', side_effect=OSError('模拟断网')), \
                    patch.object(event_calendar, 'download_banner'), \
                    patch.object(event_calendar, 'RETRY_DELAY', 0):
                event_calendar.refresh(cache_dir=cache_dir, bundled_dir=os.path.join(tmp, 'bundled'), attempts=1)
            self.assertTrue(os.path.exists(old))  # 拉不到日历就不动缓存。

    def test_prepare_returns_refresh_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, 'cache')
            with patch.object(event_calendar, 'fetch_calendar', return_value=self._calendar()), \
                    patch.object(event_calendar, 'download_banner', side_effect=self._fake_download()):
                events = event_calendar.prepare(cache_dir=cache_dir, bundled_dir=os.path.join(tmp, 'bundled'))
        self.assertEqual(['EVENT_BANNER_STORY'], [event.key for event in events])  # 轻量入口与 refresh 同源。


class TestGlobalsStartupRefresh(unittest.TestCase):
    """应用启动钩子：测试运行器下不启动；正常启动（含 debug）时起后台线程调 refresh（被 mock，不触网）。"""

    def _run_hook(self, exit_event, is_test=True):
        with patch.object(event_calendar, 'refresh') as refresh_mock, \
                patch.object(event_calendar, 'load_snapshot', return_value=None), \
                patch.object(app_globals, '_is_test_runner', return_value=is_test):
            app_globals._start_event_refresh(exit_event)
            for _ in range(50):  # 等后台线程跑起来（最多约 0.5s）。
                if refresh_mock.called or is_test:
                    break
                time.sleep(0.01)
        return refresh_mock

    def test_is_test_runner_detected_in_test_process(self):
        self.assertTrue(app_globals._is_test_runner())  # 本文件加载了 ok.test，刷新线程因此被跳过。

    def test_skips_in_test_runner(self):
        self._run_hook(threading.Event(), is_test=True).assert_not_called()  # 测试不触网。

    def test_starts_background_refresh(self):
        self._run_hook(threading.Event(), is_test=False).assert_called_once()  # debug 启动也会刷新。

    def test_skips_when_app_is_exiting(self):
        exit_event = threading.Event()
        exit_event.set()
        self._run_hook(exit_event, is_test=False).assert_not_called()  # 已开始退出则不发起请求。


class TestExpireNotifyOption(unittest.TestCase):
    """「活动结束提醒」开关注册进通知配置：默认开启、可见、描述齐全。"""

    def test_option_registered_visible_and_default_on(self):
        from src.patches import notification_tab
        from ok.util.GlobalConfig import create_notification_options
        options = create_notification_options()
        self.assertTrue(options.default_config[notification_tab.EXPIRE_NOTIFY_ENABLED_KEY])  # 默认开启。
        self.assertFalse(
            options.config_type.get(notification_tab.EXPIRE_NOTIFY_ENABLED_KEY, {}).get('hidden'))  # 不被隐藏。
        self.assertIn(notification_tab.EXPIRE_NOTIFY_ENABLED_KEY, options.config_description)  # 有说明文案。
        self.assertFalse(options.show_at_tab)  # 整个通知配置仍并入「软件设置」页。


class TestExpiringEventNotifier(unittest.TestCase):
    """刷新成功后「即将结束活动」提示：筛选边界与窗口未就绪时的暂存/补发。"""

    @staticmethod
    def _event(key='SOON', name=None, end_time=0):
        return event_calendar.CalendarEvent(key=key, name=name or key, category='version_event',
                                            event_type='StoryEvent', start_time=0, end_time=end_time,
                                            url=f'https://example.invalid/{key}.png')

    def test_message_shapes(self):
        soon = self._event('EVENT_BANNER_SOON', name='接口原文')  # name 是接口原文，展示走键推导。
        other = self._event('EVENT_BANNER_OTHER', name='接口原文2')
        self.assertEqual('活动「SOON」即将结束（24小时内）', app_globals.expire_message([soon]))  # 单个。
        self.assertEqual('以下活动即将结束（24小时内）：SOON、OTHER',
                         app_globals.expire_message([soon, other]))  # 多个。

    def test_no_emit_when_nothing_expiring(self):
        notifier = app_globals.ExpiringEventNotifier(exit_event=threading.Event())
        with patch.object(notifier, '_emit_info') as emit:
            notifier.notify_expiring([self._event('LATER', end_time=int(time.time()) + 999999)])
            notifier.notify_expiring([self._event('UNKNOWN', end_time=0)])  # 时间未知不提示。
        emit.assert_not_called()

    def test_skips_emit_when_switch_disabled(self):
        og = app_globals.og
        og.main_window = 'window'
        try:
            notifier = app_globals.ExpiringEventNotifier(exit_event=threading.Event())
            with patch.object(app_globals, 'expire_notify_enabled', return_value=False), \
                    patch.object(notifier, '_emit_info') as emit:
                notifier.notify_expiring(
                    [self._event('SOON', end_time=int(time.time()) + 3600)], now=time.time())
            emit.assert_not_called()  # 开关关闭：即使有即将结束的活动也不提示。
            self.assertIsNone(notifier._pending)
        finally:
            og.main_window = None

    def test_expire_notify_enabled_reads_config(self):
        key = '活动结束提醒'
        with patch('src.globals.og') as og_mock:
            og_mock.global_config.get_config.return_value = {key: False}
            self.assertFalse(app_globals.expire_notify_enabled())
            og_mock.global_config.get_config.return_value = {key: True}
            self.assertTrue(app_globals.expire_notify_enabled())
            og_mock.global_config.get_config.return_value = {}
            self.assertTrue(app_globals.expire_notify_enabled())  # 旧配置缺键：按开启兜底。
            og_mock.global_config.get_config.side_effect = RuntimeError('config unavailable')
            self.assertTrue(app_globals.expire_notify_enabled())  # 配置取不到：按开启兜底，不阻断。

    def test_emit_with_window_ready(self):
        og = app_globals.og
        og.main_window = 'window'  # 只查存在性，用哨兵即可。
        try:
            notifier = app_globals.ExpiringEventNotifier(exit_event=threading.Event())
            with patch('ok.ui.qt.Communicate.communicate') as communicate:
                notifier.notify_expiring(
                    [self._event('EVENT_BANNER_SOON', name='接口原文', end_time=int(time.time()) + 3600)],
                    now=time.time())
            communicate.notification.emit.assert_called_once_with(
                '活动「SOON」即将结束（24小时内）', 'ok-nikke', False, False, None, None, None)
            self.assertIsNone(notifier._pending)
        finally:
            og.main_window = None

    def test_globals_forwards_window_hook_to_notifier(self):
        # 框架回调 og.my_app.on_show_main_window（Globals 类），必须转发到 notifier，
        # 否则刷新先于主窗口完成时 pending 提示永远补发不出去（正式版与 debug 都会命中）。
        app = app_globals.Globals(exit_event=threading.Event())
        with patch.object(app.notifier, 'on_show_main_window') as forwarded:
            app.on_show_main_window('window')
        forwarded.assert_called_once_with('window')

    def test_pending_emitted_on_window_hook(self):
        og = app_globals.og
        og.main_window = None  # 刷新先于主窗口完成。
        try:
            notifier = app_globals.ExpiringEventNotifier(exit_event=threading.Event())
            with patch('ok.ui.qt.Communicate.communicate') as communicate, \
                    patch.object(og, 'handler', create=True) as handler:
                notifier.notify_expiring(
                    [self._event('EVENT_BANNER_SOON', name='接口原文', end_time=int(time.time()) + 3600)],
                    now=time.time())
                communicate.notification.emit.assert_not_called()  # 窗口未就绪：先不发。
                self.assertIsNotNone(notifier._pending)
                og.main_window = 'window'  # 模拟 show_main_window 挂载完成。
                notifier.on_show_main_window('window')  # 框架钩子。
                communicate.notification.emit.assert_not_called()  # 延迟 2s，不立即发。
                handler.post.assert_called_once()
                task = handler.post.call_args.args[0]
                self.assertAlmostEqual(app_globals.EXPIRE_NOTIFY_DELAY_MS / 1000.0,
                                       handler.post.call_args.kwargs['delay'])
                task()  # 模拟 2s 后主线程执行投递的任务。
                communicate.notification.emit.assert_called_once_with(
                    '活动「SOON」即将结束（24小时内）', 'ok-nikke', False, False, None, None, None)
            self.assertIsNone(notifier._pending)  # 补发后清空。
            with patch('ok.ui.qt.Communicate.communicate') as communicate:
                notifier.on_show_main_window('window')  # 再触发也无 pending 可发。
                communicate.notification.emit.assert_not_called()
        finally:
            og.main_window = None

    def test_pending_emitted_immediately_without_handler(self):
        # 无 og.handler（headless/测试兜底）时退化为立即补发，不让提示卡在暂存里。
        og = app_globals.og
        og.main_window = None
        try:
            notifier = app_globals.ExpiringEventNotifier(exit_event=threading.Event())
            with patch('ok.ui.qt.Communicate.communicate') as communicate, \
                    patch.object(og, 'handler', None):
                notifier.notify_expiring(
                    [self._event('EVENT_BANNER_SOON', name='接口原文', end_time=int(time.time()) + 3600)],
                    now=time.time())
                self.assertIsNotNone(notifier._pending)
                og.main_window = 'window'
                notifier.on_show_main_window('window')
                communicate.notification.emit.assert_called_once_with(
                    '活动「SOON」即将结束（24小时内）', 'ok-nikke', False, False, None, None, None)
        finally:
            og.main_window = None

    def test_no_pending_when_app_exiting(self):
        og = app_globals.og
        og.main_window = None
        exit_event = threading.Event()
        exit_event.set()  # 应用已在退出：不提示也不暂存。
        try:
            notifier = app_globals.ExpiringEventNotifier(exit_event=exit_event)
            with patch.object(notifier, '_emit_info') as emit:
                notifier.notify_expiring(
                    [self._event('SOON', end_time=int(time.time()) + 3600)], now=time.time())
            emit.assert_not_called()
            self.assertIsNone(notifier._pending)
            notifier.on_show_main_window('window')  # 钩子同样不发。
            emit.assert_not_called()
        finally:
            og.main_window = None

    def test_refresh_notifies_expiring_on_success(self):
        exit_event = threading.Event()
        notifier = app_globals.ExpiringEventNotifier(exit_event=exit_event)
        now = int(time.time())
        snapshot = event_calendar.CalendarSnapshot(
            fetched_at=now, events=(), status={})
        with patch.object(app_globals.event_calendar, 'load_snapshot', return_value=None), \
                patch.object(app_globals.event_calendar, 'refresh', return_value=snapshot), \
                patch.object(notifier, 'notify_expiring') as notify:
            app_globals._refresh_event_calendar(exit_event, notifier)
        notify.assert_called_once_with(snapshot.events)

    def test_refresh_does_not_notify_on_failure(self):
        notifier = app_globals.ExpiringEventNotifier(exit_event=threading.Event())
        snapshot = event_calendar.CalendarSnapshot(fetched_at=0, events=(), status={})
        with patch.object(app_globals.event_calendar, 'load_snapshot', return_value=None), \
                patch.object(app_globals.event_calendar, 'refresh', return_value=snapshot), \
                patch.object(notifier, 'notify_expiring') as notify:
            app_globals._refresh_event_calendar(threading.Event(), notifier)
        notify.assert_not_called()  # 接口不可达时不提示。

    def test_refresh_skips_when_snapshot_fresh(self):
        notifier = app_globals.ExpiringEventNotifier(exit_event=threading.Event())
        snapshot = event_calendar.CalendarSnapshot(fetched_at=int(time.time()), events=(), status={})
        with patch.object(app_globals.event_calendar, 'load_snapshot', return_value=snapshot), \
                patch.object(app_globals.event_calendar, 'refresh') as refresh, \
                patch.object(notifier, 'notify_expiring') as notify:
            app_globals._refresh_event_calendar(threading.Event(), notifier)
        refresh.assert_not_called()  # ttl 内直接跳过。
        notify.assert_not_called()


class TestEventRowMatch(TaskTestCase):
    """真实截图回归：官方活动图应定位到活动列表里对应的那一行。"""

    task_class = HarvestTask

    config = config

    def test_matches_row_at_2560x1440(self):
        self.set_image(EVENT_LIST)
        found = self.task.find_event_row('GREAT VILLAIN UNION', BANNER)
        self.assertIsNotNone(found)
        self.assertAlmostEqual(ROW_AT_1440[0], found.x, delta=TOLERANCE)  # 命中第 3 行（列位置）。
        self.assertAlmostEqual(ROW_AT_1440[1], found.y, delta=TOLERANCE)  # 命中第 3 行（行位置）。
        self.assertGreater(found.confidence, 0.9)  # 实测 0.957，阈值 0.8 有裕度。

    def test_matches_same_row_after_downscale_to_720p(self):
        # 同一画面降采样到 1280x720：模板应自动缩到一半尺寸并命中同一行。
        original = cv2.imread(EVENT_LIST)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'event_list_720p.png')
            cv2.imwrite(path, cv2.resize(original, (1280, 720), interpolation=cv2.INTER_AREA))
            self.set_image(path)
            found = self.task.find_event_row('GREAT VILLAIN UNION', BANNER)
            self.assertIsNotNone(found)
            self.assertAlmostEqual(ROW_AT_720[0], found.x, delta=TOLERANCE)
            self.assertAlmostEqual(ROW_AT_720[1], found.y, delta=TOLERANCE)

    def test_restricts_search_to_given_box(self):
        # 传入不包含目标行的区域 -> 应判定未命中（说明 box 限定生效）。
        self.set_image(EVENT_LIST)
        from ok.feature.Box import Box
        self.assertIsNone(self.task.find_event_row('GREAT VILLAIN UNION', BANNER, box=Box(0, 0, 800, 1440)))

    def test_returns_none_when_banner_not_in_list(self):
        self.set_image(EVENT_LIST)
        self.assertIsNone(self.task.find_event_row('不在列表里的画面', NOT_IN_LIST))

    def test_raises_for_missing_banner_file(self):
        self.set_image(EVENT_LIST)
        with self.assertRaises(FileNotFoundError):
            self.task.find_event_row('missing', 'tests/images/not_exists.png')

    def test_default_search_box_is_panel_and_fits_template(self):
        # 缺省搜索区固定在 coco 框上：既不跑到面板外乱匹配，也必须装得下模板（装不下 cv2 会抛异常）。
        self.set_image(EVENT_LIST)
        panel = self.task.get_box_by_name(event_calendar.SEARCH_BOX)
        self.assertEqual(PANEL_AT_1440, (panel.x, panel.y, panel.width, panel.height))
        template = event_calendar.build_row_template(cv2.imread(BANNER), event_calendar.row_width(2560, 1440))
        self.assertLess(template.shape[1], panel.width)  # 宽方向裕度。
        self.assertLess(template.shape[0], panel.height)  # 高方向裕度。

    def test_default_search_box_scales_with_resolution(self):
        # 框由框架按分辨率等比换算：720p 下应约为一半（模板尺寸同样减半，仍装得下）。
        original = cv2.imread(EVENT_LIST)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'event_list_720p.png')
            cv2.imwrite(path, cv2.resize(original, (1280, 720), interpolation=cv2.INTER_AREA))
            self.set_image(path)
            panel = self.task.get_box_by_name(event_calendar.SEARCH_BOX)
        self.assertAlmostEqual(PANEL_AT_1440[0] / 2, panel.x, delta=2)
        self.assertAlmostEqual(PANEL_AT_1440[1] / 2, panel.y, delta=2)
        self.assertAlmostEqual(PANEL_AT_1440[3] / 2, panel.height, delta=2)

    def test_matches_with_bundled_pack_format(self):
        # 保底包是 0.5 倍降采样的整图（scripts/build_event_assets.py 的产物形态）：
        # 直接当模板用应仍命中同一行（实测 0.952）。
        original = cv2.imread(BANNER)
        packed = cv2.resize(original, (original.shape[1] // 2, original.shape[0] // 2),
                            interpolation=cv2.INTER_AREA)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'EVENT_BANNER_GREATVILLAINUNION.png')
            cv2.imwrite(path, packed)
            self.set_image(EVENT_LIST)
            found = self.task.find_event_row('GREAT VILLAIN UNION', path)
            self.assertIsNotNone(found)
            self.assertAlmostEqual(ROW_AT_1440[0], found.x, delta=TOLERANCE)
            self.assertAlmostEqual(ROW_AT_1440[1], found.y, delta=TOLERANCE)
            self.assertGreater(found.confidence, 0.9)


class TestBuildEventBannersScript(unittest.TestCase):
    """保底包生成脚本：只测不联网的部分（缩放落盘、删除策略、dry-run）。"""

    @staticmethod
    def _event(key='K'):
        return event_calendar.CalendarEvent(key=key, name=key, category='version_event', event_type='StoryEvent',
                                          start_time=0, end_time=0,
                                          url=f'https://example.invalid/{key}.png')

    @staticmethod
    def _fake_download(size=(100, 300)):
        def fake(url, path, timeout=0, attempts=1):
            cv2.imwrite(path, np.zeros((size[0], size[1], 3), np.uint8))  # 造一张假活动图。
            return True
        return fake

    def test_build_one_downloads_scales_and_writes_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, 'out')
            with patch.object(event_calendar, 'download_banner', side_effect=self._fake_download()):
                result = build_event_assets.build_one(self._event(), 0.5, out_dir, timeout=5.0)
            self.assertEqual(os.path.join(out_dir, 'K.png'), result)
            self.assertEqual((50, 150), cv2.imread(result).shape[:2])  # 0.5 倍且等比。
            self.assertEqual(['K.png'], os.listdir(out_dir))  # 只产出保底图，原图不留在仓库。

    def test_build_one_propagates_attempts_to_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(event_calendar, 'download_banner', side_effect=self._fake_download()) as download:
                build_event_assets.build_one(self._event(), 0.5, os.path.join(tmp, 'out'),
                                              timeout=5.0, attempts=5)
            self.assertEqual(5, download.call_args.kwargs['attempts'])  # 重试次数透传到下载。

    def test_build_one_skips_when_download_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, 'out')
            with patch.object(event_calendar, 'download_banner', return_value=False):
                result = build_event_assets.build_one(self._event(), 0.5, out_dir, timeout=5.0)
            self.assertIsNone(result)
            self.assertFalse(os.path.exists(out_dir))  # 失败不留空目录/半成品。

    def test_build_one_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, 'out')
            with patch.object(event_calendar, 'download_banner', side_effect=self._fake_download()) as download:
                result = build_event_assets.build_one(self._event(), 0.5, out_dir, dry_run=True)
            self.assertIsNone(result)
            download.assert_not_called()  # dry-run 连下载都不做。
            self.assertFalse(os.path.exists(out_dir))

    def test_prune_removes_only_stale_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('CURRENT.png', 'stale.png', 'note.txt'):
                with open(os.path.join(tmp, name), 'wb') as file:
                    file.write(b'x')
            removed = build_event_assets.prune(['CURRENT'], dry_run=False, out_dir=tmp)
            self.assertEqual(['stale.png'], removed)
            self.assertEqual(['CURRENT.png', 'note.txt'], sorted(os.listdir(tmp)))  # 非 PNG 不动。

    def test_prune_dry_run_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'stale.png'), 'wb') as file:
                file.write(b'x')
            self.assertEqual(['stale.png'], build_event_assets.prune(['CURRENT'], dry_run=True, out_dir=tmp))
            self.assertEqual(['stale.png'], os.listdir(tmp))  # dry-run 只报告不删。

    def test_prune_on_missing_dir_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], build_event_assets.prune(['CURRENT'], dry_run=False,
                                                           out_dir=os.path.join(tmp, 'nope')))


if __name__ == '__main__':
    unittest.main()
