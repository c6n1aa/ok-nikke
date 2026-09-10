# -*- coding: utf-8 -*-
"""src/update_config.py 与「关于/更新」页补丁的单元测试。

不联网、不创建窗口：只测配置读写、命令拼装、tag 解析、版本比较、补丁接线与版本变更消费。
真实「检查更新」链路（子进程 + 随包 git）见 dev_tools/smoke_update_card.py。
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import update_config  # noqa: E402
from src.patches import about_update  # noqa: E402


class TestUpdateConfigIO(unittest.TestCase):

    def test_missing_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            config = update_config.load(folder)
        self.assertEqual(config, update_config.DEFAULT_UPDATE_CONFIG)
        self.assertEqual(config['channel'], 'auto')

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            config = dict(update_config.DEFAULT_UPDATE_CONFIG)
            config.update({'channel': 'custom', 'custom_git_url': ' https://example.com/a.git ',
                           'pip_index': 'https://mirror/simple'})
            self.assertTrue(update_config.save(config, folder))
            loaded = update_config.load(folder)
        self.assertEqual(loaded['channel'], 'custom')
        self.assertEqual(loaded['custom_git_url'], 'https://example.com/a.git')
        self.assertEqual(loaded['pip_index'], 'https://mirror/simple')

    def test_invalid_channel_is_normalized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, update_config.UPDATE_CONFIG_REL)
            os.makedirs(os.path.dirname(path))
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'channel': 'not-a-channel'}, f)
            self.assertEqual(update_config.load(folder)['channel'], 'auto')
            self.assertTrue(update_config.save({'channel': 'bogus'}, folder))
            self.assertEqual(update_config.load(folder)['channel'], 'auto')

    def test_broken_json_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, update_config.UPDATE_CONFIG_REL)
            os.makedirs(os.path.dirname(path))
            with open(path, 'w', encoding='utf-8') as f:
                f.write('{not json')
            self.assertEqual(update_config.load(folder), update_config.DEFAULT_UPDATE_CONFIG)

    def test_config_keys_match_update_script(self):
        """UI 与 update.py 必须共用同一份字段名，否则设置项会被静默忽略。"""
        import update
        self.assertEqual(set(update_config.DEFAULT_UPDATE_CONFIG), set(update.DEFAULT_UPDATE_CONFIG))
        self.assertEqual(update_config.UPDATE_CONFIG_REL, update.UPDATE_CONFIG_REL)


class TestCommandsAndParsing(unittest.TestCase):

    def test_list_tags_command(self):
        command = update_config.build_list_tags_command('X:\\pkg')
        self.assertIn('--list-tags', command)
        self.assertIn('--root', command)
        self.assertIn('X:\\pkg', command)
        self.assertTrue(command[1].endswith('update.py'), command[1])

    def test_update_command_carries_target_and_wait_pid(self):
        command = update_config.build_update_command('v1.2.3', 'X:\\pkg', wait_pid=4321)
        self.assertEqual(command[command.index('--target') + 1], 'v1.2.3')
        self.assertEqual(command[command.index('--wait-pid') + 1], '4321')
        self.assertEqual(command[command.index('--root') + 1], 'X:\\pkg')

    def test_parse_tags_tolerates_garbage(self):
        self.assertEqual(update_config.parse_tags('["v0.2.0", "v0.1.0"]'), ['v0.2.0', 'v0.1.0'])
        self.assertEqual(update_config.parse_tags(''), [])
        self.assertEqual(update_config.parse_tags('not json'), [])
        self.assertEqual(update_config.parse_tags('{"a": 1}'), [])
        self.assertEqual(update_config.parse_tags('[]'), [])

    def test_parse_tags_limits_and_stringifies(self):
        tags = update_config.parse_tags(json.dumps(list(range(100))))
        self.assertEqual(len(tags), update_config.MAX_TAGS)
        self.assertTrue(all(isinstance(tag, str) for tag in tags))


class TestVersionCompare(unittest.TestCase):

    def test_compare_and_ordering(self):
        self.assertEqual(update_config.compare('v0.2.0', 'v0.1.2'), 1)
        self.assertEqual(update_config.compare('v0.1.2', 'v0.2.0'), -1)
        self.assertEqual(update_config.compare('v0.1.2', 'v0.1.2'), 0)
        self.assertEqual(update_config.compare('v0.1.10', 'v0.1.9'), 1)

    def test_read_versions_strips_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, 'version.txt'), 'w', encoding='utf-8-sig') as f:
                f.write('v0.2.0\n')
            with open(os.path.join(folder, 'version.txt.prev'), 'w', encoding='utf-8') as f:
                f.write('v0.1.2\n')
            self.assertEqual(update_config.read_versions(folder), ('v0.2.0', 'v0.1.2'))
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(update_config.read_versions(folder), ('', ''))


class TestPrereleasePolicy(unittest.TestCase):
    """只对正式版提示：预发布 tag 不亮导航徽标、不进版本下拉。"""

    def test_is_prerelease(self):
        for tag in ('v0.2.0-beta.1', 'v0.2.0-alpha', 'v0.2.0-rc.2', '0.2.0-beta', 'dev', 'nightly'):
            self.assertTrue(update_config.is_prerelease(tag), tag)
        for tag in ('v0.2.0', 'v0.1.10', '1.0.0', 'v1'):
            self.assertFalse(update_config.is_prerelease(tag), tag)

    def test_stable_tags_keeps_order(self):
        tags = ['v0.2.1-beta.1', 'v0.2.0', 'v0.1.9', 'v0.2.0-alpha']
        self.assertEqual(update_config.stable_tags(tags), ['v0.2.0', 'v0.1.9'])
        self.assertEqual(update_config.stable_tags([]), [])

    def test_newest_stable_update_ignores_prerelease(self):
        # 只有预发布比当前新 → 不提示
        self.assertIsNone(update_config.newest_stable_update(['v0.2.0-beta.1', 'v0.1.0'], 'v0.1.0'))
        # 预发布号段更高，也不能顶替正式版作为提示目标
        self.assertEqual(update_config.newest_stable_update(['v0.3.0-alpha', 'v0.2.0'], 'v0.1.0'), 'v0.2.0')
        # 与当前相同或更旧 → 不提示
        self.assertIsNone(update_config.newest_stable_update(['v0.1.0', 'v0.0.9'], 'v0.1.0'))

    def test_newest_prerelease_update_is_hint_only(self):
        tags = ['v0.2.0-beta.2', 'v0.2.0-beta.1', 'v0.1.0']
        self.assertEqual(update_config.newest_prerelease_update(tags, 'v0.1.0'), 'v0.2.0-beta.2')
        self.assertIsNone(update_config.newest_prerelease_update(['v0.2.0', 'v0.1.0'], 'v0.1.0'))


class TestVersionOptions(unittest.TestCase):
    """版本下拉候选：只列正式版、去掉当前版本、最多 MAX_VERSION_OPTIONS 个。"""

    def test_caps_to_recent_stable_versions(self):
        tags = [f'v0.1.{n}' for n in range(20, 0, -1)]  # v0.1.20 … v0.1.1（新→旧）
        options = update_config.selectable_versions(tags, 'v0.1.1')
        self.assertEqual(options, ['v0.1.20', 'v0.1.19', 'v0.1.18', 'v0.1.17', 'v0.1.16'])
        self.assertEqual(len(options), update_config.MAX_VERSION_OPTIONS)

    def test_excludes_current_version_before_capping(self):
        tags = ['v0.2.3', 'v0.2.2', 'v0.2.1', 'v0.2.0', 'v0.1.9', 'v0.1.8', 'v0.1.7']
        self.assertEqual(update_config.selectable_versions(tags, 'v0.2.1'),
                         ['v0.2.3', 'v0.2.2', 'v0.2.0', 'v0.1.9', 'v0.1.8'])

    def test_prerelease_never_listed(self):
        tags = ['v0.2.0-beta.1', 'v0.1.9', 'v0.1.8-alpha']
        self.assertEqual(update_config.selectable_versions(tags, 'v0.1.0'), ['v0.1.9'])

    def test_keeps_current_when_it_is_the_only_stable(self):
        # 只有当前版本这一个正式 tag 时不能清空下拉，否则用户看不到任何版本
        self.assertEqual(update_config.selectable_versions(['v0.1.0'], 'v0.1.0'), ['v0.1.0'])

    def test_empty_inputs(self):
        self.assertEqual(update_config.selectable_versions([], 'v0.1.0'), [])
        self.assertEqual(update_config.selectable_versions(None, 'v0.1.0'), [])
        self.assertEqual(update_config.selectable_versions(['v0.2.0'], 'v0.1.0', limit=0), [])


class TestUpdateFailureRecord(unittest.TestCase):
    """上次更新失败的记录（update.py 落盘 → 「关于」页回显）。"""

    def test_missing_broken_or_reasonless_record_returns_none(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(update_config.read_update_failure(folder))
            path = os.path.join(folder, update_config.UPDATE_FAILED_REL)
            os.makedirs(os.path.dirname(path))
            with open(path, 'w', encoding='utf-8') as f:
                f.write('{not json')
            self.assertIsNone(update_config.read_update_failure(folder))
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'target': 'v1.0.0'}, f)  # 缺 reason，视为无记录
            self.assertIsNone(update_config.read_update_failure(folder))

    def test_reads_target_and_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, update_config.UPDATE_FAILED_REL)
            os.makedirs(os.path.dirname(path))
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'target': 'v1.2.3', 'reason': '下载 v1.2.3 失败：网络不可达'}, f)
            self.assertEqual(
                update_config.read_update_failure(folder),
                {'target': 'v1.2.3', 'reason': '下载 v1.2.3 失败：网络不可达'})


class TestStartUpdate(unittest.TestCase):

    def test_start_update_opens_a_console(self):
        """更新子进程必须带 CREATE_NEW_CONSOLE，否则用户看不到任何进度（只有应用消失）。"""
        from unittest.mock import patch
        with patch('src.update_config.subprocess.Popen') as popen:
            update_config.start_update('v9.9.9', root=ROOT, wait_pid=1234)
        command = popen.call_args.args[0]
        self.assertEqual('v9.9.9', command[command.index('--target') + 1])
        self.assertEqual('1234', command[command.index('--wait-pid') + 1])
        self.assertEqual(update_config.CREATE_NEW_CONSOLE, popen.call_args.kwargs['creationflags'])
        self.assertEqual(ROOT, popen.call_args.kwargs['cwd'])


class TestAboutUpdatePatch(unittest.TestCase):

    def test_apply_swaps_framework_update_ui(self):
        import ok.ui.qt.MainWindow as main_window_module
        import ok.ui.qt.about.AboutTab as about_tab_module
        from ok.ui.qt.about.UpdateCard import ChangeLogView
        from src.ui.UpdateCard import NikkeUpdateCard

        original_changelog = ChangeLogView
        about_update.apply()

        self.assertIs(about_tab_module.UpdateCard, NikkeUpdateCard)
        self.assertIs(main_window_module.get_startup_version_change,
                      about_update._get_startup_version_change)
        self.assertIs(about_tab_module.get_startup_version_change,
                      about_update._get_startup_version_change)
        # MainWindow 依赖的三个成员必须同名提供，否则导航徽标/自动检查会失效
        for attribute in ('update_available_changed', 'check_started', 'check_for_updates'):
            self.assertTrue(hasattr(NikkeUpdateCard, attribute), attribute)
        # 启动自检延迟被缩短（框架默认 30 秒），否则用户要等半分钟才看到更新提示
        self.assertEqual(about_update.STARTUP_UPDATE_CHECK_DELAY_MS,
                         main_window_module.update_check_delay_ms())
        # 不显示更新内容：空正文的「更新成功」卡片不应留白（ChangeLogView 被换成「空则隐藏」子类）
        self.assertIsNot(about_tab_module.ChangeLogView, original_changelog)
        self.assertTrue(issubclass(about_tab_module.ChangeLogView, original_changelog))
        # 发现新版本只弹窗口内 InfoBar，不发系统托盘气泡（配「关于」页红点）
        self.assertFalse(NikkeUpdateCard.NOTIFY_TRAY_BALLOON)

    def test_pending_version_change_consumed_once(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, 'version.txt'), 'w', encoding='utf-8') as f:
                f.write('v0.2.0\n')
            with open(os.path.join(folder, 'version.txt.prev'), 'w', encoding='utf-8') as f:
                f.write('v0.1.2\n')
            original = about_update._PENDING_CONSUMED
            about_update._PENDING_CONSUMED = False
            try:
                change = about_update.pending_version_change(folder)
                self.assertEqual(change,
                                 {'action': 'update', 'from_version': 'v0.1.2', 'to_version': 'v0.2.0'})
                # 消费后 prev 文件被删，避免每次启动重复提示
                self.assertFalse(os.path.exists(os.path.join(folder, 'version.txt.prev')))
                self.assertEqual(about_update.pending_version_change(folder), change)
            finally:
                about_update._PENDING_CONSUMED = original

    def test_pending_version_change_reports_downgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, 'version.txt'), 'w', encoding='utf-8') as f:
                f.write('v0.1.0\n')
            with open(os.path.join(folder, 'version.txt.prev'), 'w', encoding='utf-8') as f:
                f.write('v0.2.0\n')
            original = about_update._PENDING_CONSUMED
            about_update._PENDING_CONSUMED = False
            try:
                change = about_update.pending_version_change(folder)
                self.assertEqual(change['action'], 'downgrade')
            finally:
                about_update._PENDING_CONSUMED = original

    def test_pending_version_change_none_when_same(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, 'version.txt'), 'w', encoding='utf-8') as f:
                f.write('v0.1.2\n')
            with open(os.path.join(folder, 'version.txt.prev'), 'w', encoding='utf-8') as f:
                f.write('v0.1.2\n')
            original = about_update._PENDING_CONSUMED
            about_update._PENDING_CONSUMED = False
            try:
                self.assertIsNone(about_update.pending_version_change(folder))
            finally:
                about_update._PENDING_CONSUMED = original


if __name__ == '__main__':
    unittest.main()
