# -*- coding: utf-8 -*-
"""`.github/scripts/release_notes.py`（Release 正文生成）的单元测试。

不联网、不发版：解析/分节/渲染用纯函数覆盖；再用一个真实临时 git 仓库验证
「上一个 tag 查找、区间日志、launcher 变更检测、build_body 手写覆盖」几条 git 路径。
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / '.github' / 'scripts' / 'release_notes.py'

spec = importlib.util.spec_from_file_location('release_notes', SCRIPT)
release_notes = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_notes  # dataclasses 解析字符串注解时要求模块已注册
spec.loader.exec_module(release_notes)


def commit(subject, body=''):
    return release_notes.parse_commit(subject, body)


class TestParseCommit(unittest.TestCase):

    def test_conventional_with_scope(self):
        parsed = commit('feat(outpost): open the wipe-out dialog in one place')
        self.assertEqual(parsed.type, 'feat')
        self.assertEqual(parsed.scope, 'outpost')
        self.assertEqual(parsed.desc, 'open the wipe-out dialog in one place')
        self.assertFalse(parsed.breaking)

    def test_bang_marks_breaking(self):
        self.assertTrue(commit('refactor(update)!: drop the custom URL channel').breaking)

    def test_body_breaking_change_marks_breaking(self):
        parsed = commit('feat(api): rework config', 'BREAKING CHANGE: configs moved')
        self.assertTrue(parsed.breaking)

    def test_non_conventional_keeps_raw_subject(self):
        parsed = commit('Trim README to title, ok-script credit')
        self.assertEqual(parsed.type, '')
        self.assertEqual(parsed.desc, 'Trim README to title, ok-script credit')


class TestRenderBody(unittest.TestCase):

    def render(self, commits, **kwargs):
        options = dict(tag='v0.3.0', prev_tag='v0.2.0', repo='o/r')
        options.update(kwargs)
        return release_notes.render_body(commits, **options)

    def test_sections_are_ordered_and_noise_filtered(self):
        body = self.render([
            commit('fix(outpost): stop the advise timer from resetting'),
            commit('docs: refresh the guides'),
            commit('feat(i18n): add Japanese locale'),
            commit('perf(ocr): cache the model'),
            commit('refactor(demo): rewrite the config strings'),
        ])
        self.assertLess(body.index('#### 新功能'), body.index('#### 问题修复'))
        self.assertLess(body.index('#### 问题修复'), body.index('#### 性能优化'))
        self.assertIn('- **i18n**: add Japanese locale', body)
        self.assertIn('#### 其他改动', body)
        self.assertIn('- **demo**: rewrite the config strings', body)
        self.assertNotIn('refresh the guides', body)

    def test_noise_only_falls_back_to_other_section(self):
        body = self.render([commit('docs: refresh the guides'), commit('chore: bump the submodule')])
        self.assertIn('#### 其他改动', body)
        self.assertIn('- refresh the guides', body)

    def test_breaking_entries_are_hoisted(self):
        body = self.render([
            commit('refactor(update)!: drop the custom URL channel'),
            commit('feat(i18n): add Japanese locale'),
        ])
        self.assertIn('#### 不兼容变更', body)
        self.assertLess(body.index('#### 不兼容变更'), body.index('#### 新功能'))
        self.assertEqual(body.count('drop the custom URL channel'), 1)

    def test_empty_range_says_no_changes(self):
        body = self.render([])
        self.assertIn('本次发布没有需要列出的变更。', body)

    def test_first_release_has_no_compare_link(self):
        body = self.render([], prev_tag=None)
        self.assertIn('首个版本发布。', body)
        self.assertNotIn('完整变更记录', body)

    def test_prerelease_gets_a_notice(self):
        self.assertIn('预发布', self.render([], tag='v0.3.0-beta.1'))

    def test_launcher_change_adds_a_reinstall_hint(self):
        self.assertIn('请重新下载完整便携包', self.render([], launcher_changed=True))

    def test_handwritten_body_wins_and_skips_the_hint(self):
        body = self.render([commit('feat(i18n): add Japanese locale')], handwritten='- 手写条目', launcher_changed=True)
        self.assertIn('- 手写条目', body)
        self.assertNotIn('add Japanese locale', body)
        self.assertNotIn('请重新下载完整便携包', body)

    def test_download_and_compare_links(self):
        body = self.render([])
        self.assertIn('https://github.com/o/r/releases/download/v0.3.0/ok-nikke-win32-portable.zip', body)
        self.assertIn('[v0.2.0...v0.3.0](https://github.com/o/r/compare/v0.2.0...v0.3.0)', body)


class TestGitBacked(unittest.TestCase):

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.git('-c', 'init.defaultBranch=main', 'init', '-q')

    def git(self, *args):
        subprocess.run(
            ['git', '-c', 'user.name=test', '-c', 'user.email=test@example.com',
             '-c', 'commit.gpgsign=false', '-C', str(self.root), *args],
            check=True, capture_output=True, text=True,
        )

    def commit_all(self, subject):
        self.git('commit', '-q', '--allow-empty', '-m', subject)

    def test_prev_tag_range_and_launcher_detection(self):
        self.commit_all('feat(a): first')
        self.git('tag', '-a', 'v0.1.0', '-m', 'v0.1.0')
        (self.root / 'launcher').mkdir()
        (self.root / 'launcher' / 'launcher.c').write_text('int main(void) { return 0; }\n', encoding='utf-8')
        self.git('add', 'launcher/launcher.c')
        self.commit_all('fix(b): second')
        self.git('tag', '-a', 'v0.2.0', '-m', 'v0.2.0')

        self.assertIsNone(release_notes.find_prev_tag(self.root, 'v0.1.0'))
        self.assertEqual(release_notes.find_prev_tag(self.root, 'v0.2.0'), 'v0.1.0')

        commits = release_notes.read_commits(self.root, 'v0.1.0', 'v0.2.0')
        self.assertEqual([c.desc for c in commits], ['second'])

        self.assertFalse(release_notes.launcher_changed(self.root, None, 'v0.1.0'))
        self.assertTrue(release_notes.launcher_changed(self.root, 'v0.1.0', 'v0.2.0'))

        body = release_notes.build_body(self.root, 'v0.2.0', 'o/r')
        self.assertIn('- **b**: second', body)
        self.assertIn('请重新下载完整便携包', body)
        self.assertIn('**完整变更记录**', body)

    def test_handwritten_file_overrides_git_log(self):
        self.commit_all('feat(a): first')
        self.git('tag', '-a', 'v0.1.0', '-m', 'v0.1.0')
        changelog = self.root / 'changelog'
        changelog.mkdir()
        (changelog / 'v0.1.0.md').write_text('- 面向用户的手写说明\n', encoding='utf-8')

        body = release_notes.build_body(self.root, 'v0.1.0', 'o/r')
        self.assertIn('- 面向用户的手写说明', body)
        self.assertNotIn('first', body)


if __name__ == '__main__':
    unittest.main()
