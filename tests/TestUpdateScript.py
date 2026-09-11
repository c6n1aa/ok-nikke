# -*- coding: utf-8 -*-
"""update.py（应用内更新 bootstrap）的纯函数单测。

只测无副作用的部分：配置解析、更新源解析、依赖指纹、pip 命令、tag 排序/过滤、版本号读写。
端到端 git 流程见 dev_tools/poc_update_flow.py（用真实 tag + 临时目录）。
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import update  # noqa: E402  被测模块（零第三方依赖）


class TestUpdateConfig(unittest.TestCase):

    def test_missing_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            config = update.load_update_config(folder)
        self.assertEqual(config, update.DEFAULT_UPDATE_CONFIG)

    def test_broken_or_invalid_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, 'configs'))
            path = os.path.join(folder, update.UPDATE_CONFIG_REL)
            with open(path, 'w', encoding='utf-8') as f:
                f.write('{not json')
            self.assertEqual(update.load_update_config(folder)['channel'], 'auto')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'channel': 123, 'pip_index': None, 'custom_git_url': '  '}, f)
            config = update.load_update_config(folder)
        self.assertEqual(config['channel'], 'auto')
        self.assertEqual(config['pip_index'], '')
        self.assertEqual(config['custom_git_url'], '')

    def test_valid_config_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, 'configs'))
            with open(os.path.join(folder, update.UPDATE_CONFIG_REL), 'w', encoding='utf-8') as f:
                json.dump({'channel': 'cnb', 'pip_index': ' https://pypi.tuna.tsinghua.edu.cn/simple '}, f)
            config = update.load_update_config(folder)
        self.assertEqual(config['channel'], 'cnb')
        self.assertEqual(update.resolve_pip_index(config), 'https://pypi.tuna.tsinghua.edu.cn/simple')


class TestResolveGitUrl(unittest.TestCase):

    def test_explicit_channels(self):
        self.assertEqual(update.resolve_git_url({'channel': 'github'}), update.GITHUB_GIT_URL)
        self.assertEqual(update.resolve_git_url({'channel': 'CNB'}), update.CNB_GIT_URL)

    def test_custom_channel_falls_back_when_empty(self):
        custom = 'https://example.com/some/repo.git'
        self.assertEqual(update.resolve_git_url({'channel': 'custom', 'custom_git_url': custom}), custom)
        self.assertEqual(update.resolve_git_url({'channel': 'custom', 'custom_git_url': ''}),
                         update.GITHUB_GIT_URL)

    def test_auto_follows_system_language(self):
        self.assertEqual(update.resolve_git_url({'channel': 'auto'}, language_id=0x04), update.CNB_GIT_URL)
        self.assertEqual(update.resolve_git_url({'channel': 'auto'}, language_id=0x09), update.GITHUB_GIT_URL)


class TestRequirementsFingerprint(unittest.TestCase):

    BASE = 'pyside6-essentials==6.11.1\nopencv-python==5.0.0.93\n'

    def test_comments_and_order_do_not_trigger(self):
        shuffled = ('# via ok-script\nopencv-python==5.0.0.93\n\npyside6-essentials==6.11.1\n'
                    '    # indented comment\n')
        self.assertEqual(update.requirements_fingerprint(self.BASE),
                         update.requirements_fingerprint(shuffled))

    def test_version_change_triggers(self):
        self.assertNotEqual(update.requirements_fingerprint(self.BASE),
                            update.requirements_fingerprint('pyside6-essentials==6.12.0\n'
                                                            'opencv-python==5.0.0.93\n'))

    def test_empty_or_comment_only_returns_none(self):
        self.assertIsNone(update.requirements_fingerprint(''))
        self.assertIsNone(update.requirements_fingerprint('# nothing\n\n'))

    def test_pip_flags_are_ignored(self):
        self.assertIsNone(update.requirements_fingerprint('-r other.txt\n'))


class TestPipCommand(unittest.TestCase):

    def test_no_deps_is_mandatory(self):
        command = update.build_pip_command('python.exe', 'req.txt')
        self.assertIn('--no-deps', command)
        self.assertIn('-r', command)
        self.assertIn('req.txt', command)

    def test_no_cache_dir_keeps_writes_inside_package(self):
        """零系统写入：不加 --no-cache-dir 时 pip 会写 %LOCALAPPDATA%\\pip\\cache。"""
        self.assertIn('--no-cache-dir', update.build_pip_command('python.exe', 'req.txt'))

    def test_index_only_added_when_set(self):
        self.assertNotIn('-i', update.build_pip_command('python.exe', 'req.txt'))
        self.assertNotIn('-i', update.build_pip_command('python.exe', 'req.txt', ''))
        with_index = update.build_pip_command('python.exe', 'req.txt', 'https://mirror/simple')
        self.assertEqual(with_index[with_index.index('-i') + 1], 'https://mirror/simple')


class TestVersionKey(unittest.TestCase):

    def test_numeric_ordering(self):
        tags = ['v0.1.2', 'v0.1.10', 'v0.1.9', 'v0.2.0', 'v1.0.0']
        self.assertEqual(sorted(tags, key=update.version_key),
                         ['v0.1.2', 'v0.1.9', 'v0.1.10', 'v0.2.0', 'v1.0.0'])

    def test_release_is_greater_than_prerelease(self):
        self.assertGreater(update.version_key('v0.2.0'), update.version_key('v0.2.0-beta.1'))

    def test_prerelease_number_ordering(self):
        self.assertGreater(update.version_key('v0.2.0-beta.10'), update.version_key('v0.2.0-beta.2'))

    def test_non_numeric_sorts_lowest(self):
        self.assertLess(update.version_key('dev'), update.version_key('v0.1.0'))


class TestParseRemoteTags(unittest.TestCase):

    OUTPUT = (
        'aaa\trefs/tags/v0.1.2\n'
        'bbb\trefs/tags/v0.1.2^{}\n'
        'ccc\trefs/tags/v0.1.10\n'
        'ddd\trefs/tags/v0.1.0\n'
        'eee\theads/main\n'
        'fff\trefs/tags/v0.1.0^{}\n'
        'garbage line\n'
    )

    def test_filters_annotated_tags_and_sorts_desc(self):
        self.assertEqual(update.parse_remote_tags(self.OUTPUT), ['v0.1.10', 'v0.1.2', 'v0.1.0'])

    def test_empty_output(self):
        self.assertEqual(update.parse_remote_tags(''), [])
        self.assertEqual(update.parse_remote_tags(None), [])


class TestVersionFile(unittest.TestCase):

    def test_read_strips_utf8_bom(self):
        """CI 用 PowerShell Set-Content -Encoding utf8 写 version.txt 会带 BOM。"""
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, update.VERSION_FILE), 'w', encoding='utf-8-sig') as f:
                f.write('v0.2.0\n')
            self.assertEqual(update.read_version(folder), 'v0.2.0')

    def test_read_write_roundtrip_with_previous(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(update.read_version(folder), '')
            update.write_version(folder, 'v0.2.0', previous='v0.1.2')
            self.assertEqual(update.read_version(folder), 'v0.2.0')
            with open(os.path.join(folder, update.PREV_VERSION_FILE), encoding='utf-8') as f:
                self.assertEqual(f.read().strip(), 'v0.1.2')
            update.write_version(folder, 'v0.2.1')
            self.assertEqual(update.read_version(folder), 'v0.2.1')


class TestFindGitExe(unittest.TestCase):

    def test_prefers_bundled_portable_git(self):
        with tempfile.TemporaryDirectory() as folder:
            bundled = os.path.join(folder, 'git', 'cmd', 'git.exe')
            os.makedirs(os.path.dirname(bundled))
            with open(bundled, 'w', encoding='utf-8') as f:
                f.write('fake')
            self.assertEqual(update.find_git_exe(folder), bundled)

    def test_explicit_path_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            explicit = os.path.join(folder, 'my-git.exe')
            with open(explicit, 'w', encoding='utf-8') as f:
                f.write('fake')
            self.assertEqual(update.find_git_exe(folder, explicit), explicit)


class TestWaitForProcessExit(unittest.TestCase):

    def test_zero_pid_returns_immediately(self):
        self.assertTrue(update.wait_for_process_exit(0))

    def test_dead_pid_counts_as_exited(self):
        self.assertTrue(update.wait_for_process_exit(0xFFFFFFF0, timeout=0.5))


class TestGuardrails(unittest.TestCase):
    """把文档里的红线变成可执行断言。"""

    def test_only_stdlib_imports(self):
        with open(os.path.join(ROOT, 'update.py'), encoding='utf-8') as f:
            tree = ast.parse(f.read())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split('.')[0])
        third_party = sorted(name for name in modules
                             if name != '__future__' and name not in sys.stdlib_module_names)
        self.assertEqual(third_party, [], f'update.py 只能使用标准库，发现第三方依赖: {third_party}')

    def test_version_files_are_gitignored(self):
        with open(os.path.join(ROOT, '.gitignore'), encoding='utf-8') as f:
            lines = {line.strip() for line in f}
        for name in (update.VERSION_FILE, update.PREV_VERSION_FILE, 'git/'):
            self.assertIn(name, lines, f'{name} 必须加入 .gitignore')

    def test_launcher_sources_are_tracked(self):
        """入口 shim 的源码必须真的被 git 跟踪。

        踩过的坑：`.gitignore` 里给 PyInstaller 用的 `*.manifest` 把 launcher/launcher.manifest
        一并忽略，git add 静默跳过 → CI 上构建入口 exe 直接 FileNotFoundError。
        """
        if not shutil.which('git') or not os.path.isdir(os.path.join(ROOT, '.git')):
            self.skipTest('不是 git 工作区')
        required = ['launcher/launcher.c', 'launcher/launcher.manifest', 'launcher/launcher.rc',
                    'launcher/build.py']
        tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', *required],
                                 cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(tracked.returncode, 0, f'未被 git 跟踪：{tracked.stderr.strip()}')
        ignored = subprocess.run(['git', 'check-ignore', '--quiet', *required], cwd=ROOT)
        self.assertNotEqual(ignored.returncode, 0, 'launcher 源码不能命中 .gitignore')


class TestFailureRecordAndConsole(unittest.TestCase):
    """更新过程对用户可见：进度落日志、失败记录落盘、控制台输出不依赖第三方。"""

    def test_progress_is_written_to_log(self):
        with tempfile.TemporaryDirectory() as folder:
            update.progress(folder, 3, '安装依赖…')
            with open(os.path.join(folder, update.LOG_REL), encoding='utf-8') as f:
                text = f.read()
        self.assertIn(f'[3/{update.TOTAL_STEPS}]', text)
        self.assertIn('安装依赖', text)

    def test_failure_record_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            update.record_failure(folder, 'v9.9.9', '下载失败：网络不可达')
            with open(os.path.join(folder, update.FAILED_REL), encoding='utf-8') as f:
                data = json.load(f)
            self.assertEqual('v9.9.9', data['target'])
            self.assertEqual('下载失败：网络不可达', data['reason'])
            update.clear_failure(folder)
            self.assertFalse(os.path.exists(os.path.join(folder, update.FAILED_REL)))
            update.clear_failure(folder)  # 没有记录时也不能抛

    def test_console_helpers_do_not_raise_without_console(self):
        with tempfile.TemporaryDirectory() as folder:
            update.set_console_title('ok-nikke test')  # 无控制台时静默失败
            update.pause_before_exit(folder, seconds=0)  # 给 0 秒，测试不等待


if __name__ == '__main__':
    unittest.main()
