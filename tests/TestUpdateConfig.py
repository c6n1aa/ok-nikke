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


class TestAboutUpdatePatch(unittest.TestCase):

    def test_apply_swaps_framework_update_ui(self):
        import ok.ui.qt.MainWindow as main_window_module
        import ok.ui.qt.about.AboutTab as about_tab_module
        from src.ui.UpdateCard import NikkeUpdateCard

        about_update.apply()

        self.assertIs(about_tab_module.UpdateCard, NikkeUpdateCard)
        self.assertIs(main_window_module.get_startup_version_change,
                      about_update._get_startup_version_change)
        self.assertIs(about_tab_module.get_startup_version_change,
                      about_update._get_startup_version_change)
        # MainWindow 依赖的三个成员必须同名提供，否则导航徽标/自动检查会失效
        for attribute in ('update_available_changed', 'check_started', 'check_for_updates'):
            self.assertTrue(hasattr(NikkeUpdateCard, attribute), attribute)

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
