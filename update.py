#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ok-nikke 应用内更新 bootstrap（零第三方依赖：只使用标准库）。

设计见 docs/portable-refactor.md §5.4。要点：
- 所有路径都相对 --root（默认本文件所在目录），不写解压目录之外的任何位置；git 配置只写本地 .git/config。
- 首次更新会在本地 git init + seed commit（把「包里的旧代码」变成 tracked 基线），
  否则 checkout 会因「未跟踪文件将被覆盖」失败，且新版本里被删除的文件永远清不掉。
- pip 在 checkout 之前、基于目标 tag 的 requirements.txt 安装，失败时工作区未被改动，无需回滚。
- git / pip 任一步失败都以旧版本拉起应用，绝不留下起不来的包。

用法:
    python update.py --target v0.2.0 [--wait-pid <旧进程PID>]
    python update.py --list-tags          # 检查更新：输出远端 tag（JSON）供 UI 使用
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

GITHUB_GIT_URL = 'https://github.com/c6n1aa/ok-nikke.git'
CNB_GIT_URL = 'https://cnb.cool/c6n1aa/ok-nikke'

DEFAULT_UPDATE_CONFIG = {
    'channel': 'auto',  # auto | github | cnb | custom
    'custom_git_url': '',
    'pip_index': '',
    'update_method': 'manual',  # manual | auto（预留启动自检）
}

UPDATE_CONFIG_REL = os.path.join('configs', 'update.json')
VERSION_FILE = 'version.txt'
PREV_VERSION_FILE = 'version.txt.prev'
MARKER_REL = os.path.join('configs', '.updating')
RUNNER_REL = os.path.join('configs', '.update_runner.py')
LOG_REL = os.path.join('logs', 'update.log')
TARGET_REQUIREMENTS_REL = os.path.join('configs', '.requirements.target.txt')
REQUIREMENTS_FILE = 'requirements.txt'
MAIN_SCRIPT = 'main.py'

# 只写包内 .git/info/exclude，避免 seed commit 把运行期产物/内联目录/独立解释器提交进本地基线
EXCLUDE_PATTERNS = [
    VERSION_FILE,
    PREV_VERSION_FILE,
    'python/',
    'ok/',
    'pyappify/',
    'git/',
    'configs/',
    'logs/',
    'screenshots/',
    'cache/',
    '__pycache__/',
    '*.pyc',
]

CREATE_NO_WINDOW = 0x08000000
GIT_TIMEOUT = 900
PIP_TIMEOUT = 3600
PIP_ATTEMPTS = 3
PIP_RETRY_DELAY = 5
WAIT_PARENT_TIMEOUT = 60


# ---------------------------------------------------------------- 小工具


def log(root: str, message: str) -> None:
    """写 logs/update.log；pythonw 无 stdout 时也能留痕。"""
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {message}'
    try:
        path = os.path.join(root, LOG_REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass
    try:
        if sys.stderr is not None:
            sys.stderr.write(line + '\n')
            sys.stderr.flush()
    except Exception:
        pass


def read_json(path: str):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def write_json(path: str, data) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def file_sha256(path: str):
    """返回文件 sha256；文件不存在返回 None。"""
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _system_language_id() -> int:
    """Windows 主语言 ID（低 10 位），zh = 0x04。取不到返回 0。"""
    try:
        return int(ctypes.windll.kernel32.GetUserDefaultUILanguage()) & 0x3FF
    except Exception:
        return 0


def package_root() -> str:
    """包根目录。runner 备份在 configs/ 下运行时，取上一层。"""
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here).lower() == 'configs':
        return os.path.dirname(here)
    return here


# ---------------------------------------------------------------- 纯函数（可单测）


def load_update_config(root: str) -> dict:
    """读 configs/update.json，缺失/损坏/字段非法时回落到硬编码默认值。"""
    config = dict(DEFAULT_UPDATE_CONFIG)
    data = read_json(os.path.join(root, UPDATE_CONFIG_REL))
    if isinstance(data, dict):
        for key in DEFAULT_UPDATE_CONFIG:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                config[key] = value.strip()
    return config


def resolve_git_url(config: dict, language_id: int | None = None) -> str:
    """channel + custom_git_url → 实际 git 地址（单一事实来源，避免双份状态不一致）。"""
    channel = str(config.get('channel') or 'auto').strip().lower()
    if channel == 'github':
        return GITHUB_GIT_URL
    if channel == 'cnb':
        return CNB_GIT_URL
    if channel == 'custom':
        custom = str(config.get('custom_git_url') or '').strip()
        return custom or GITHUB_GIT_URL
    # auto：按系统语言选择，国内默认走 CNB 镜像
    lang = _system_language_id() if language_id is None else language_id
    return CNB_GIT_URL if lang == 0x04 else GITHUB_GIT_URL


def resolve_pip_index(config: dict) -> str:
    """pip 镜像源；空则返回空串（调用方不要拼 -i）。"""
    return str(config.get('pip_index') or '').strip()


def _parse_requirements_lines(text: str):
    """requirements.txt → 有效条目（去注释/空行/行尾续行）。"""
    entries = []
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or line.startswith('-'):
            continue
        entries.append(line)
    return entries


def requirements_fingerprint(text: str):
    """依赖指纹：对解析后的条目做 sha256；无有效条目返回 None。

    比直接哈希文件更稳：注释/空行/行序无关的变化不应触发 pip。
    """
    entries = _parse_requirements_lines(text)
    if not entries:
        return None
    normalized = '\n'.join(sorted(entries))
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def build_pip_command(python_exe: str, requirements_path: str, pip_index: str = ''):
    """更新时安装依赖的命令：必须 --no-deps（与 CI/AGENTS.md 一致）。

    不加 --no-deps 会拉 pyside6 元包/addons，包体积会暴涨。
    """
    command = [
        python_exe, '-m', 'pip', 'install',
        '--no-deps',
        '--no-cache-dir',  # 零系统写入：默认缓存会落到 %LOCALAPPDATA%\pip\cache
        '--disable-pip-version-check',
        '--no-warn-script-location',
        '-r', requirements_path,
    ]
    if pip_index:
        command += ['-i', pip_index]
    return command


def _pre_key(prerelease: str):
    parts = []
    for token in re.split(r'[.\-_+]', prerelease or ''):
        if not token:
            continue
        parts.append((0, int(token), '') if token.isdigit() else (1, 0, token))
    return tuple(parts)


def version_key(tag: str):
    """tag → 可比较排序键（正式版 > 预发布版）。"""
    text = str(tag or '').strip()
    match = re.match(r'^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$', text)
    if not match:
        return (0, 0, 0, 0, ((1, 0, text),))
    major, minor, patch, rest = match.groups()
    prerelease = rest.lstrip('-.+') if rest else ''
    return (int(major), int(minor or 0), int(patch or 0), 1 if not prerelease else 0, _pre_key(prerelease))


def parse_remote_tags(output: str):
    """解析 git ls-remote --tags 输出：过滤注释 tag 的 ^{} 行，按版本倒序返回。"""
    tags = set()
    for line in (output or '').splitlines():
        if '\t' not in line:
            continue
        _, ref = line.split('\t', 1)
        ref = ref.strip()
        if not ref.startswith('refs/tags/') or ref.endswith('^{}'):
            continue
        name = ref[len('refs/tags/'):]
        if name:
            tags.add(name)
    return sorted(tags, key=version_key, reverse=True)


def read_version(root: str) -> str:
    try:
        with open(os.path.join(root, VERSION_FILE), 'r', encoding='utf-8') as f:
            # lstrip BOM：CI 里 PowerShell Set-Content -Encoding utf8 会写 BOM，
            # 不清理会让版本号带 \ufeff 前缀，"已更新 vX → vY" 提示与比较全部失真
            return f.read().lstrip('\ufeff').strip()
    except Exception:
        return ''


def write_version(root: str, version: str, previous: str = None) -> None:
    with open(os.path.join(root, VERSION_FILE), 'w', encoding='utf-8') as f:
        f.write(f'{version}\n')
    if previous is not None:
        with open(os.path.join(root, PREV_VERSION_FILE), 'w', encoding='utf-8') as f:
            f.write(f'{previous}\n')


def wait_for_process_exit(pid: int, timeout: float = WAIT_PARENT_TIMEOUT) -> bool:
    """等旧进程真正退出（Windows 文件锁）；无 ctypes/失败时退化为轮询 os.kill(pid, 0)。"""
    if not pid or pid <= 0:
        return True
    deadline = time.monotonic() + timeout
    if sys.platform == 'win32':
        try:
            synchronize = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, int(pid))
            if handle:
                try:
                    while time.monotonic() < deadline:
                        result = ctypes.windll.kernel32.WaitForSingleObject(handle, 100)
                        if result == 0:
                            return True
                        if result == 0xFFFFFFFF:
                            return False
                    return False
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            pass
    while time.monotonic() < deadline:
        try:
            os.kill(int(pid), 0)
            time.sleep(0.2)
        except OSError:
            return True
    return False


# ---------------------------------------------------------------- git 操作


def find_git_exe(root: str, explicit: str = '') -> str:
    """优先随包预置的 PortableGit，其次 PATH 上的 git（开发环境）。"""
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates += [
        os.path.join(root, 'git', 'cmd', 'git.exe'),
        os.path.join(root, 'git', 'bin', 'git.exe'),
        'git',
    ]
    for candidate in candidates:
        if candidate == 'git':
            return shutil.which('git') or ''
        if os.path.isfile(candidate):
            return candidate
    return ''


def run_command(command, cwd: str, timeout: int = GIT_TIMEOUT, dry_run: bool = False):
    """执行命令，返回 (returncode, stdout, stderr)；dry_run 只回显不执行。"""
    if dry_run:
        return 0, '', ''
    try:
        completed = subprocess.run(
            command, cwd=cwd, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
    except subprocess.TimeoutExpired:
        return 124, '', f'timeout after {timeout}s: {command}'
    except Exception as error:
        return 1, '', f'{type(error).__name__}: {error}'
    decode = lambda data: (data or b'').decode('utf-8', 'replace').strip()
    return completed.returncode, decode(completed.stdout), decode(completed.stderr)


class Git:
    """对 git 命令的薄封装：统一 cwd/超时/日志，避免在业务流程里散落 subprocess。"""

    def __init__(self, exe: str, root: str, dry_run: bool = False):
        self.exe = exe
        self.root = root
        self.dry_run = dry_run

    def run(self, *args, timeout: int = GIT_TIMEOUT, check: bool = False):
        display = ' '.join(str(a) for a in args)
        if self.dry_run:
            log(self.root, f'[dry-run] git {display}')
            return 0, '', ''
        code, out, err = run_command([self.exe, *args], self.root, timeout=timeout)
        log(self.root, f'git {display} -> {code}{f" | {err}" if code else ""}')
        if check and code != 0:
            raise RuntimeError(f'git {display} failed ({code}): {err or out}')
        return code, out, err

    def output(self, *args, timeout: int = GIT_TIMEOUT) -> str:
        code, out, _ = self.run(*args, timeout=timeout)
        return out if code == 0 else ''


def ensure_repository(git: Git, root: str, git_url: str, current_version: str) -> None:
    """init（首次）→ 本地排除项/行尾设置 → remote → seed commit（首次）。

    seed commit 的作用：把包内旧代码变成 tracked 基线，这样 checkout -f 既能覆盖未跟踪文件，
    也能正确删除「新版本已移除」的文件（否则残留文件会永久堆积，已用 v0.1.0→v0.1.2 验证）。
    """
    if not os.path.isdir(os.path.join(root, '.git')):
        git.run('-c', 'init.defaultBranch=main', 'init', check=True)
    # 只写包内 .git/config 与 .git/info/exclude，不做任何全局配置写入
    git.run('config', 'core.autocrlf', 'false')
    git.run('config', 'core.eol', 'lf')
    git.run('config', 'advice.detachedHead', 'false')
    git.run('config', 'user.name', 'ok-nikke-update')
    git.run('config', 'user.email', 'update@ok-nikke.local')
    _append_local_excludes(git, root)

    code, _, _ = git.run('remote', 'get-url', 'origin')
    if code == 0:
        git.run('remote', 'set-url', 'origin', git_url, check=True)
    else:
        git.run('remote', 'add', 'origin', git_url, check=True)

    code, _, _ = git.run('rev-parse', '--verify', 'HEAD')
    if code == 0:
        return
    log(root, f'first update: seeding local baseline (version={current_version or "unknown"})')
    git.run('add', '-A', check=True)
    code, out, err = git.run('commit', '-m', f'seed {current_version or "unknown"}', '--quiet')
    if code != 0 and 'nothing to commit' not in (out + err).lower():
        raise RuntimeError(f'seed commit failed: {err or out}')


def _append_local_excludes(git: Git, root: str) -> None:
    """把运行期产物/内联目录写进 .git/info/exclude（不动仓库里的 .gitignore）。"""
    path = os.path.join(root, '.git', 'info', 'exclude')
    if git.dry_run:
        log(root, f'[dry-run] append local excludes -> {path}')
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing = ''
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                existing = f.read()
        missing = [p for p in EXCLUDE_PATTERNS if p not in existing.split()]
        if not missing:
            return
        with open(path, 'a', encoding='utf-8') as f:
            if existing and not existing.endswith('\n'):
                f.write('\n')
            f.write('\n'.join(missing) + '\n')
    except Exception as error:
        log(root, f'append local excludes failed: {error}')


def prune_old_tags(git: Git, root: str, keep: str) -> None:
    """删除除当前 tag 外的本地 tag 并 gc：--depth=1 每次都带来完整快照，不清理 .git 会线性膨胀。"""
    code, out, _ = git.run('tag', '--list')
    if code != 0:
        return
    stale = [t for t in out.split() if t and t != keep]
    if not stale:
        return
    git.run('tag', '-d', *stale)
    git.run('gc', '--prune=now', '--quiet')


# ---------------------------------------------------------------- 主流程


def _write_marker(root: str, payload: dict) -> None:
    write_json(os.path.join(root, MARKER_REL), payload)


def _clear_marker(root: str) -> None:
    try:
        os.remove(os.path.join(root, MARKER_REL))
    except OSError:
        pass


def _backup_runner(root: str) -> None:
    """把自己备份到 configs/：checkout 可能覆盖/删除正在运行的 update.py。"""
    try:
        target = os.path.join(root, RUNNER_REL)
        if os.path.abspath(__file__) == os.path.abspath(target):
            return
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.abspath(__file__), target)
    except Exception as error:
        log(root, f'backup runner failed: {error}')


def _restore_runner_if_missing(root: str) -> None:
    """目标 tag 早于引入 update.py 的版本时，从 runner 备份把自己放回去。"""
    path = os.path.join(root, 'update.py')
    if os.path.exists(path):
        return
    try:
        shutil.copyfile(os.path.join(root, RUNNER_REL), path)
        log(root, 'restored update.py from runner backup')
    except Exception as error:
        log(root, f'restore update.py failed: {error}')


def relaunch_app(root: str, pythonw_exe: str) -> None:
    if not os.path.isfile(os.path.join(root, MAIN_SCRIPT)):
        log(root, f'skip relaunch: {MAIN_SCRIPT} not found')
        return
    if not os.path.isfile(pythonw_exe):
        log(root, f'skip relaunch: {pythonw_exe} not found')
        return
    try:
        subprocess.Popen([pythonw_exe, MAIN_SCRIPT], cwd=root, close_fds=True,
                         creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0)
        log(root, f'relaunched {MAIN_SCRIPT} with {pythonw_exe}')
    except Exception as error:
        log(root, f'relaunch failed: {error}')


def list_tags(git_url: str, git_exe: str, root: str) -> list:
    """检查更新用：远端 tag 列表（已过滤注释 tag 的 ^{} 行）。"""
    if not git_exe:
        log(root, 'ls-remote skipped: git not found')
        return []
    code, out, err = run_command([git_exe, 'ls-remote', '--tags', git_url], root, timeout=120)
    if code != 0:
        log(root, f'ls-remote failed ({code}): {err or out}')
        return []
    return parse_remote_tags(out)


def run_update(options) -> int:
    root = os.path.abspath(options.root or package_root())
    config = load_update_config(root)
    git_url = options.git_url or resolve_git_url(config)
    pip_index = options.pip_index if options.pip_index is not None else resolve_pip_index(config)
    git_exe = find_git_exe(root, options.git_exe)
    python_exe = options.python_exe or os.path.join(root, 'python', 'python.exe')
    pythonw_exe = options.pythonw_exe or os.path.join(root, 'python', 'pythonw.exe')
    log(root, f'update start: git_url={git_url} target={options.target} dry_run={options.dry_run}')

    if not git_exe:
        log(root, 'git not found: expected <root>/git/cmd/git.exe or git on PATH')
        return 2
    if not options.target:
        log(root, 'missing --target')
        return 2

    git = Git(git_exe, root, dry_run=options.dry_run)

    if options.wait_pid:
        if not wait_for_process_exit(options.wait_pid, options.wait_timeout):
            log(root, f'old process {options.wait_pid} did not exit in {options.wait_timeout}s, abort')
            return 2
        log(root, f'old process {options.wait_pid} exited')

    _backup_runner(root)
    _write_marker(root, {'target': options.target, 'pid': os.getpid(), 'started': time.time()})

    current_version = read_version(root)
    try:
        ensure_repository(git, root, git_url, current_version)
        old_ref = git.output('rev-parse', 'HEAD').strip()

        code, _, err = git.run('fetch', '--depth=1', 'origin', 'tag', options.target)
        if code != 0:
            log(root, f'fetch {options.target} failed: {err}, keep current code')
            _clear_marker(root)
            return 1

        # 依赖：用目标 tag 里的 requirements.txt 生成临时文件，在 checkout 之前安装；
        # 失败时工作区仍是旧版本，无需回滚。
        if not options.no_pip:
            code, new_requirements, _ = git.run('show', f'{options.target}:{REQUIREMENTS_FILE}')
            old_fingerprint = requirements_fingerprint(_read_text(os.path.join(root, REQUIREMENTS_FILE)) or '')
            new_fingerprint = requirements_fingerprint(new_requirements) if code == 0 else None
            if options.force_pip or (new_fingerprint and new_fingerprint != old_fingerprint):
                log(root, f'dependencies changed (force_pip={options.force_pip}), installing before checkout')
                if not _install_requirements(root, python_exe, new_requirements, pip_index, options.dry_run,
                                            options.pip_attempts, options.pip_retry_delay):
                    log(root, 'pip failed, keep current code')
                    _clear_marker(root)
                    return 1

        code, _, err = git.run('checkout', '-f', options.target)
        if code != 0:
            log(root, f'checkout {options.target} failed: {err}, keep current code')
            _clear_marker(root)
            return 1

        write_version(root, options.target, current_version)
        prune_old_tags(git, root, options.target)
        _clear_marker(root)
        _restore_runner_if_missing(root)
        log(root, f'update done: {current_version or "unknown"} -> {options.target} (old_ref={old_ref})')
    finally:
        if not options.no_relaunch:
            relaunch_app(root, pythonw_exe)
    return 0


def _read_text(path: str):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


def _install_requirements(root: str, python_exe: str, requirements_text: str, pip_index: str,
                          dry_run: bool, attempts: int = PIP_ATTEMPTS,
                          retry_delay: float = PIP_RETRY_DELAY) -> bool:
    """把依赖清单写到包内临时文件后 pip 安装（失败重试）。"""
    if not requirements_text.strip():
        log(root, 'target tag has empty requirements.txt, skip pip')
        return True
    target_path = os.path.join(root, TARGET_REQUIREMENTS_REL)
    if not dry_run:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(requirements_text)
    command = build_pip_command(python_exe, target_path, pip_index)
    attempts = max(1, int(attempts))
    for attempt in range(1, attempts + 1):
        if dry_run:
            log(root, f'[dry-run] {" ".join(command)}')
            return True
        code, out, err = run_command(command, root, timeout=PIP_TIMEOUT)
        if code == 0:
            log(root, f'pip install ok (attempt {attempt})')
            return True
        log(root, f'pip install failed (attempt {attempt}/{attempts}, code {code}): {err or out}')
        if attempt < attempts:
            time.sleep(max(0.0, float(retry_delay)))
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='ok-nikke update bootstrap')
    parser.add_argument('--target', help='目标 git tag，如 v0.2.0')
    parser.add_argument('--root', default='', help='包根目录（默认本文件所在目录）')
    parser.add_argument('--git-exe', default='', help='git 可执行文件（默认 <root>/git/cmd/git.exe）')
    parser.add_argument('--python-exe', default='', help='pip 用的解释器（默认 <root>/python/python.exe）')
    parser.add_argument('--pythonw-exe', default='', help='重启应用用的解释器（默认 <root>/python/pythonw.exe）')
    parser.add_argument('--git-url', default='', help='覆盖 configs/update.json 里的更新源')
    parser.add_argument('--pip-index', default=None, help='pip 镜像源（默认取配置）')
    parser.add_argument('--wait-pid', type=int, default=0, help='等待该进程退出后再更新')
    parser.add_argument('--wait-timeout', type=float, default=WAIT_PARENT_TIMEOUT)
    parser.add_argument('--list-tags', action='store_true', help='输出远端 tag 列表（JSON）')
    parser.add_argument('--no-pip', action='store_true', help='跳过依赖安装')
    parser.add_argument('--force-pip', action='store_true', help='即使依赖未变也重装依赖')
    parser.add_argument('--no-relaunch', action='store_true', help='更新完不拉起应用（调试用）')
    parser.add_argument('--pip-attempts', type=int, default=PIP_ATTEMPTS, help='pip 失败重试次数')
    parser.add_argument('--pip-retry-delay', type=float, default=PIP_RETRY_DELAY, help='pip 重试间隔秒数')
    parser.add_argument('--dry-run', action='store_true', help='只回显计划，不改动任何文件')
    return parser


def main(argv=None) -> int:
    options = build_parser().parse_args(argv)
    root = os.path.abspath(options.root or package_root())
    if options.list_tags:
        config = load_update_config(root)
        git_url = options.git_url or resolve_git_url(config)
        git_exe = find_git_exe(root, options.git_exe)
        print(json.dumps(list_tags(git_url, git_exe, root), ensure_ascii=False))
        return 0
    return run_update(options)


if __name__ == '__main__':
    sys.exit(main())
