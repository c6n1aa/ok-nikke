# -*- coding: utf-8 -*-
"""生成 GitHub Release 正文（构建流程用，纯标准库）。

由 .github/workflows/build.yml 的 Release 步骤调用；也可本地预览：

    .\\.venv\\Scripts\\python.exe .github/scripts/release_notes.py --tag v0.3.0 --out release_notes.md

生成规则：
- 手写覆盖优先：`changelog/<tag>.md` 存在时用它的正文作为「更新日志」内容（该文件需随 tag 提交）。
- 否则解析 `<上一个 tag>..<tag>` 的非 merge 提交（Conventional Commits）分节：
  `feat` 新功能 / `fix` 问题修复 / `perf` 性能优化 / `revert`、`refactor` 等 其他改动；
  `docs`/`chore`/`ci`/`test`/`build`/`style` 不单列（全部被过滤时兜底为「其他改动」，保证日志非空）；
  标题带 `!` 或正文含 `BREAKING CHANGE` 的条目提升到「不兼容变更」节。
- 区间内 `launcher/` 有改动时附加提示：入口 exe 无法通过应用内 git 更新交付，需重新下载完整包。
- 下载说明与「完整变更记录」链接固定生成；预发布（tag 含 `-`）附加一行说明。
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT = 'ok-nikke'
PACKAGE = 'ok-nikke-win32-portable.zip'
TAG_PATTERN = 'v*'  # 版本 tag 前缀，与 deploy 技能一致
HANDWRITTEN_DIR = 'changelog'
LAUNCHER_PATHS = ('launcher',)

SECTION_ORDER = ('breaking', 'feat', 'fix', 'perf', 'other')
SECTION_TITLES = {
    'breaking': '不兼容变更',
    'feat': '新功能',
    'fix': '问题修复',
    'perf': '性能优化',
    'other': '其他改动',
}
# Conventional Commits 类型 -> 分节；未列出的（含无 type 的历史提交）进「其他改动」
TYPE_SECTIONS = {
    'feat': 'feat',
    'fix': 'fix',
    'perf': 'perf',
    'revert': 'other',
    'refactor': 'other',
}
# 纯工程噪音：不单列，仅在所有条目都被过滤时兜底展示
NOISE_TYPES = frozenset({'docs', 'chore', 'ci', 'test', 'build', 'style'})

CONVENTIONAL_RE = re.compile(
    r'^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^()]+)\))?(?P<breaking>!)?: (?P<desc>.+)$'
)
BREAKING_BODY_RE = re.compile(r'^BREAKING[ -]CHANGE:', re.MULTILINE)


@dataclasses.dataclass(frozen=True)
class Commit:
    """一条提交解析后的 Conventional Commits 字段（解析不出 type 时 desc=原始标题）。"""

    subject: str
    desc: str
    type: str = ''
    scope: str = ''
    breaking: bool = False


def parse_commit(subject: str, body: str = '') -> Commit:
    subject = subject.strip()
    breaking = bool(BREAKING_BODY_RE.search(body))
    match = CONVENTIONAL_RE.match(subject)
    if not match:
        return Commit(subject=subject, desc=subject, breaking=breaking)
    return Commit(
        subject=subject,
        desc=match.group('desc'),
        type=match.group('type').lower(),
        scope=match.group('scope') or '',
        breaking=breaking or bool(match.group('breaking')),
    )


def select_sections(commits: list[Commit]) -> dict[str, list[Commit]]:
    """按分节归类提交；噪音提交只在没有任何可展示条目时兜底进「其他改动」。"""
    sections: dict[str, list[Commit]] = {key: [] for key in SECTION_ORDER}
    noise: list[Commit] = []
    for commit in commits:
        if commit.breaking:
            sections['breaking'].append(commit)
            continue
        section = TYPE_SECTIONS.get(commit.type)
        if section:
            sections[section].append(commit)
        elif commit.type in NOISE_TYPES:
            noise.append(commit)
        else:
            sections['other'].append(commit)
    if not any(sections.values()):
        sections['other'] = noise
    return sections


def render_entry(commit: Commit) -> str:
    prefix = f'**{commit.scope}**: ' if commit.scope else ''
    return f'- {prefix}{commit.desc}'


def render_body(
    commits: list[Commit],
    *,
    tag: str,
    prev_tag: str | None,
    repo: str,
    handwritten: str | None = None,
    launcher_changed: bool = False,
) -> str:
    """拼装完整 Release 正文；handwritten 非空时用它作为「更新日志」内容。"""
    blocks: list[str] = []

    if '-' in tag:
        blocks.append('> 本版本为预发布版：不参与应用内更新提示，仅供手动下载。')

    if handwritten is not None:
        changelog = handwritten.strip()
    elif prev_tag is None:
        changelog = '首个版本发布。'
    else:
        sections = select_sections(commits)
        section_blocks = []
        for key in SECTION_ORDER:
            entries = sections[key]
            if entries:
                lines = [f'#### {SECTION_TITLES[key]}', '']
                lines.extend(render_entry(commit) for commit in entries)
                section_blocks.append('\n'.join(lines))
        changelog = '\n\n'.join(section_blocks) if section_blocks else '本次发布没有需要列出的变更。'
    blocks.append(f'### 更新日志\n\n{changelog}')

    if launcher_changed and handwritten is None:
        blocks.append('> 本次更新包含入口程序变更，应用内更新无法覆盖，请重新下载完整便携包。')

    blocks.append(
        '### 下载说明\n\n'
        f'* [{PACKAGE}](https://github.com/{repo}/releases/download/{tag}/{PACKAGE}) '
        '完整便携包: 解压到任意目录运行 ok-nikke.exe (需管理员权限)。\n'
        '* 无需下载 Source code, 仅供存档用。'
    )

    if prev_tag is not None:
        blocks.append(
            f'**完整变更记录**: [{prev_tag}...{tag}]'
            f'(https://github.com/{repo}/compare/{prev_tag}...{tag})'
        )

    return '\n\n'.join(blocks) + '\n'


def run_git(root: str | Path, *args: str) -> str:
    result = subprocess.run(
        ['git', '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def find_prev_tag(root: str | Path, tag: str) -> str | None:
    """`<tag>` 之前最近的版本 tag；没有（首个版本）时返回 None。"""
    try:
        return run_git(root, 'describe', '--tags', '--abbrev=0', '--match', TAG_PATTERN, f'{tag}^').strip() or None
    except RuntimeError:
        return None


def read_commits(root: str | Path, prev_tag: str, tag: str) -> list[Commit]:
    """读取 `prev_tag..tag` 的非 merge 提交（字段用 \\x1f、记录用 \\x1e 分隔，避免正文干扰）。"""
    raw = run_git(root, 'log', '--no-merges', '--format=%s%x1f%b%x1e', f'{prev_tag}..{tag}')
    commits = []
    for chunk in raw.split('\x1e'):
        chunk = chunk.strip('\n')
        if not chunk:
            continue
        subject, _, body = chunk.partition('\x1f')
        commits.append(parse_commit(subject, body))
    return commits


def launcher_changed(root: str | Path, prev_tag: str | None, tag: str) -> bool:
    """入口 exe（launcher/）是否在区间内变更：它无法通过应用内 git 更新交付。"""
    if prev_tag is None:
        return False
    return bool(run_git(root, 'diff', '--name-only', prev_tag, tag, '--', *LAUNCHER_PATHS).strip())


def build_body(root: str | Path, tag: str, repo: str) -> str:
    handwritten_path = Path(root) / HANDWRITTEN_DIR / f'{tag}.md'
    handwritten = handwritten_path.read_text(encoding='utf-8') if handwritten_path.is_file() else None
    prev_tag = find_prev_tag(root, tag)
    commits = read_commits(root, prev_tag, tag) if prev_tag else []
    return render_body(
        commits,
        tag=tag,
        prev_tag=prev_tag,
        repo=repo,
        handwritten=handwritten,
        launcher_changed=launcher_changed(root, prev_tag, tag),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='生成 GitHub Release 正文（自动生成 + changelog/<tag>.md 手写覆盖）')
    parser.add_argument('--tag', required=True, help='本次发布的 tag，如 v0.3.0')
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', f'c6n1aa/{PROJECT}'),
                        help='owner/repo，用于下载与 compare 链接')
    parser.add_argument('--root', default='.', help='仓库根目录')
    parser.add_argument('--out', default='release_notes.md', help='输出文件（UTF-8，LF）')
    args = parser.parse_args(argv)

    body = build_body(args.root, args.tag, args.repo)
    Path(args.out).write_text(body, encoding='utf-8', newline='\n')
    print(f'release notes for {args.tag} written to {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
