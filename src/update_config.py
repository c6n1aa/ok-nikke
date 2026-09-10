# -*- coding: utf-8 -*-
"""更新源配置 + 「检查/执行更新」的薄封装（无 UI，无新依赖）。

设计要点：
- 配置读写 `configs/update.json`，与根目录 `update.py` **共用同一份文件与字段名**；
- 检查更新 / 执行更新一律通过子进程调用根目录 `update.py`，UI 里不写任何 git/pip 逻辑，
  保证「唯一实现」在 update.py（这也是为什么本模块只是薄封装）；
- `update.py` 是零第三方依赖的脚本，因此这里只 import 标准库 + 可选地 import 它复用常量。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

try:  # 根目录 update.py：tag 解析 / 更新源解析的唯一实现；缺失时降级（见下）
    import update as _update
except Exception:  # pragma: no cover - 只在包被破坏/极老版本 tag 下发生
    _update = None

UPDATE_SCRIPT = 'update.py'
# 与 update.py 指向同一份文件；update.py 可用时直接复用它的定义，避免两边漂移
UPDATE_CONFIG_REL = os.path.join('configs', 'update.json')
if _update is not None:
    UPDATE_CONFIG_REL = _update.UPDATE_CONFIG_REL

# 上次更新的失败记录（由 update.py 落盘，这里读出来在「关于」页提示用户）
UPDATE_FAILED_REL = os.path.join('configs', 'update_failed.json')
if _update is not None:
    UPDATE_FAILED_REL = _update.FAILED_REL

# 给更新子进程一个新控制台：进度与失败原因对用户可见（原来 CREATE_NO_WINDOW 是全隐身）
CREATE_NEW_CONSOLE = 0x00000010

# 与 update.py 的 DEFAULT_UPDATE_CONFIG 保持一致（若 update.py 可用则以它为准，避免漂移）
DEFAULT_UPDATE_CONFIG = {
    'channel': 'auto',
    'custom_git_url': '',
    'pip_index': '',
    'update_method': 'manual',
}
if _update is not None:
    DEFAULT_UPDATE_CONFIG = dict(_update.DEFAULT_UPDATE_CONFIG)

# 更新源下拉项：(channel 值, 显示名)
CHANNEL_OPTIONS = (
    ('auto', '自动（按系统语言）'),
    ('github', 'GitHub'),
    ('cnb', 'CNB 镜像'),
    ('custom', '自定义 URL'),
)
CHANNEL_VALUES = tuple(value for value, _ in CHANNEL_OPTIONS)

LIST_TAGS_TIMEOUT = 120
UPDATE_LAUNCH_TIMEOUT = 30
MAX_TAGS = 30


def package_root() -> str:
    """包根目录：优先 main.py 所在目录（框架路径也基于 argv[0]），退化到 cwd。"""
    try:
        script = os.path.abspath(sys.argv[0])
        if os.path.isfile(script):
            return os.path.dirname(script)
    except Exception:
        pass
    return os.getcwd()


def config_path(root: str = None) -> str:
    return os.path.join(root or package_root(), UPDATE_CONFIG_REL)


def update_script_path(root: str = None) -> str:
    return os.path.join(root or package_root(), UPDATE_SCRIPT)


def python_exe(root: str = None) -> str:
    """执行 update.py 用的解释器：优先包内独立解释器，开发环境用当前解释器。"""
    bundled = os.path.join(root or package_root(), 'python', 'python.exe')
    if os.path.isfile(bundled):
        return bundled
    return sys.executable


def load(root: str = None) -> dict:
    """读更新源配置；缺失/损坏/字段非法时回落到默认值。"""
    config = dict(DEFAULT_UPDATE_CONFIG)
    try:
        with open(config_path(root), 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return config
    if isinstance(data, dict):
        for key in DEFAULT_UPDATE_CONFIG:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                config[key] = value.strip()
    if config.get('channel') not in CHANNEL_VALUES:
        config['channel'] = DEFAULT_UPDATE_CONFIG['channel']
    return config


def save(config: dict, root: str = None) -> bool:
    """写更新源配置：只落允许的键，非法 channel 归一化，缺目录自动创建。"""
    payload = dict(DEFAULT_UPDATE_CONFIG)
    for key in payload:
        value = config.get(key)
        if isinstance(value, str):
            payload[key] = value.strip()
    if payload['channel'] not in CHANNEL_VALUES:
        payload['channel'] = DEFAULT_UPDATE_CONFIG['channel']
    path = config_path(root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def channel_label(channel: str) -> str:
    for value, label in CHANNEL_OPTIONS:
        if value == channel:
            return label
    return CHANNEL_OPTIONS[0][1]


def resolve_git_url(config: dict) -> str:
    """把 channel + custom_git_url 解析成实际 git 地址（复用 update.py 的实现）。"""
    if _update is not None:
        return _update.resolve_git_url(config)
    if config.get('channel') == 'custom':
        return str(config.get('custom_git_url') or '')
    return ''


def version_key(tag: str):
    """tag 排序键（复用 update.py，保证 UI 与更新流程判定一致）。"""
    if _update is not None:
        return _update.version_key(tag)
    return (0, 0, 0, 0, ((1, 0, str(tag)),))


def compare(left: str, right: str) -> int:
    """-1/0/1：left 相对 right 的新旧。"""
    left_key, right_key = version_key(left), version_key(right)
    if left_key > right_key:
        return 1
    if left_key < right_key:
        return -1
    return 0


def is_prerelease(tag: str) -> bool:
    """是否为预发布/非正式 tag（含 alpha/beta 等后缀，或非版本号形式）。

    判定与 update.py 的 version_key 同源（正式版 > 预发布），避免两处漂移。
    """
    if _update is not None:
        return _update.version_key(tag)[3] == 0
    return not re.match(r'^v?\d+(?:\.\d+)*$', str(tag or '').strip())


def stable_tags(tags) -> list:
    """只保留正式版 tag（保持传入顺序）。"""
    return [str(tag) for tag in (tags or []) if not is_prerelease(str(tag))]


def newest_stable_update(tags, current_version: str):
    """比当前版本新的最新正式版；没有返回 None（导航徽标与「发现新版本」的唯一判定依据）。"""
    return next((tag for tag in stable_tags(tags) if compare(tag, current_version) > 0), None)


def newest_prerelease_update(tags, current_version: str):
    """比当前版本新的最新预发布；仅用于状态文案提示，不参与徽标与版本下拉。

    按传入顺序取第一个：列表来自 parse_remote_tags，已是新→旧排序。
    """
    return next((str(tag) for tag in (tags or [])
                 if is_prerelease(str(tag)) and compare(str(tag), current_version) > 0), None)


def parse_tags(stdout: str) -> list:
    """解析 update.py --list-tags 的 JSON 输出；非法内容返回空列表。"""
    try:
        tags = json.loads(stdout or '[]')
    except Exception:
        return []
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags if str(tag).strip()][:MAX_TAGS]


def build_list_tags_command(root: str = None) -> list:
    return [python_exe(root), update_script_path(root), '--root', root or package_root(), '--list-tags']


def list_remote_tags(root: str = None, timeout: int = LIST_TAGS_TIMEOUT):
    """检查更新：返回 (tags, error)，tags 为新到旧排序，error 为空表示成功。

    走子进程调 update.py：git 由包内 `git/cmd/git.exe` 提供，不依赖用户环境。
    """
    if not os.path.isfile(update_script_path(root)):
        return [], f'未找到 {UPDATE_SCRIPT}'
    try:
        completed = subprocess.run(
            build_list_tags_command(root), cwd=root or package_root(), timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=0x08000000 if os.name == 'nt' else 0,
        )
    except subprocess.TimeoutExpired:
        return [], '检查更新超时'
    except Exception as error:
        return [], f'{type(error).__name__}: {error}'
    if completed.returncode != 0:
        detail = (completed.stderr or b'').decode('utf-8', 'replace').strip()
        return [], detail.splitlines()[-1] if detail else f'退出码 {completed.returncode}'
    return parse_tags(completed.stdout.decode('utf-8', 'replace')), ''


def build_update_command(target: str, root: str = None, wait_pid: int = 0) -> list:
    root = root or package_root()
    return [python_exe(root), update_script_path(root), '--root', root, '--target', target,
            '--wait-pid', str(int(wait_pid or 0))]


def start_update(target: str, root: str = None, wait_pid: int = 0):
    """启动 update.py（不等待）：它会等本进程退出后再 fetch/checkout/pip。

    用 CREATE_NEW_CONSOLE 开一个控制台窗口：拉代码/装依赖/失败原因都看得见，
    否则用户只看到「应用关掉、过一会儿自己回来」。进度同时写 logs/update.log。
    """
    if not target:
        raise ValueError('缺少目标版本')
    if not os.path.isfile(update_script_path(root)):
        raise FileNotFoundError(f'未找到 {UPDATE_SCRIPT}')
    return subprocess.Popen(
        build_update_command(target, root, wait_pid), cwd=root or package_root(),
        close_fds=True, creationflags=CREATE_NEW_CONSOLE if os.name == 'nt' else 0,
    )


def read_versions(root: str = None) -> tuple:
    """返回 (当前版本, 上一版本)（来自 version.txt / version.txt.prev，缺失为空串）。"""
    current, previous = '', ''
    base = root or package_root()
    for name, setter in (('version.txt', 'current'), ('version.txt.prev', 'previous')):
        try:
            with open(os.path.join(base, name), 'r', encoding='utf-8') as f:
                value = f.read().lstrip('\ufeff').strip()
        except OSError:
            value = ''
        if setter == 'current':
            current = value
        else:
            previous = value
    return current, previous


def read_update_failure(root: str = None):
    """上次更新失败的记录：{'target','reason'}；无记录或文件损坏返回 None。

    由 update.py 写在 configs/update_failed.json（成功更新时会被删掉），
    这里读出来在「关于 → 应用更新」里回显，避免用户「更新完还是旧版本但不知道为什么」。
    """
    try:
        with open(os.path.join(root or package_root(), UPDATE_FAILED_REL), 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    reason = str(data.get('reason') or '').strip()
    if not reason:
        return None
    return {'target': str(data.get('target') or '').strip(), 'reason': reason}
