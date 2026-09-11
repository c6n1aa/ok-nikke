#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编译 ok-nikke 入口 shim（launcher/launcher.c → ok-nikke.exe）。

自动探测工具链，优先 MinGW（windres + gcc），其次 MSVC（rc + cl，需在 vcvars 环境下）。
两种工具链的 manifest 嵌入方式不同，见 launcher.rc 顶部注释；构建结束后会**校验成品**
确实带 UAC 提权且没有混入 asInvoker 的默认 manifest —— 提权是这个 shim 存在的理由，
不能静默产出不提权的 exe。

用法：
    .venv\\Scripts\\python.exe launcher\\build.py
    python launcher/build.py --no-manifest --out dev_tools/shim-test.exe

--no-manifest 只用于本地验证 spawn 行为：带 requireAdministrator 的 exe 每次运行都会弹 UAC，
自动化验证不方便；发布必须不带这个开关（否则没有图标、也不提权）。
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SOURCE = os.path.join(HERE, 'launcher.c')
RESOURCE_SCRIPT = os.path.join(HERE, 'launcher.rc')
MANIFEST_FILE = os.path.join(HERE, 'launcher.manifest')
STAMP_DIR = os.path.join(HERE, 'build-stamp')


def which(*names):
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def run(command, cwd=HERE):
    print('$ ' + ' '.join(f'"{part}"' if ' ' in part else part for part in command))
    return subprocess.run(command, cwd=cwd).returncode


def compile_resource(toolchain, rc_text, out_name):
    """把 rc 文本写成临时脚本并编译为资源文件，返回产物路径。

    临时 rc 必须放在 launcher/ 下（而不是 build-stamp/），否则 rc 里的
    "../icons/icon.ico"、"../launcher.manifest" 这类相对路径会指错地方。
    """
    os.makedirs(STAMP_DIR, exist_ok=True)
    rc_path = os.path.join(HERE, f'_build_{os.path.splitext(out_name)[0]}.rc')
    with open(rc_path, 'w', encoding='utf-8') as f:
        f.write(rc_text)
    out_path = os.path.join(STAMP_DIR, out_name)
    try:
        if toolchain == 'mingw':
            tool = which('windres')
            if not tool:
                raise SystemExit('未找到 windres：MinGW 工具链不完整')
            command = [tool, os.path.basename(rc_path), '-O', 'coff', '-o', out_path]
        else:
            tool = which('rc.exe', 'rc')
            if not tool:
                raise SystemExit('未找到 rc.exe：请在 VS 开发者命令行（vcvars）下运行')
            command = [tool, '/nologo', '/fo', out_path, os.path.basename(rc_path)]
        if run(command) != 0:
            raise SystemExit('资源编译失败')
    finally:
        try:
            os.remove(rc_path)
        except OSError:
            pass
    return out_path


def prepare_resources(toolchain):
    """返回 (需要链接的资源对象列表, 额外的编译参数)。"""
    with open(RESOURCE_SCRIPT, encoding='utf-8') as f:
        base_rc = f.read()
    with open(MANIFEST_FILE, encoding='utf-8') as f:
        f.read()

    if toolchain == 'msvc':
        # MSVC 直接把自己的 manifest 写进资源（link.exe 不会自动加），资源 ID 1 = EXE 的 manifest
        rc_text = base_rc + '\n1 24 "launcher.manifest"\n'
        return [compile_resource(toolchain, rc_text, 'launcher.res')], []

    # MinGW：gcc 的 *endfile spec 会自动链接 <lib>/default-manifest.o（asInvoker）。
    # 我们在 build-stamp 里放一份同名的「我们的 manifest」对象，并用 -B 让它被优先找到，
    # 这样最终 exe 里只有唯一一份 manifest（requireAdministrator）。
    # 生成的 rc 与 launcher.manifest 同目录（launcher/），所以直接写文件名
    manifest_obj = compile_resource(toolchain, '1 24 "launcher.manifest"\n', 'default-manifest.o')
    resource = compile_resource(toolchain, base_rc, 'launcher.res')
    return [resource], ['-B', os.path.dirname(manifest_obj) + os.sep]


def verify_manifest(exe_path):
    """校验成品带提权 manifest，且没有混入 asInvoker 的默认 manifest。"""
    with open(exe_path, 'rb') as f:
        blob = f.read()
    has_admin = b'requireAdministrator' in blob
    has_as_invoker = b'asInvoker' in blob
    if not has_admin:
        raise SystemExit('构建产物缺少 requireAdministrator manifest：UAC 不会提权，产物不可用')
    if has_as_invoker:
        raise SystemExit('构建产物同时含 asInvoker 默认 manifest（MinGW 常见冲突）：'
                         '提权行为不确定，请检查 launcher.rc 与 build-stamp/default-manifest.o')


def main(argv=None):
    parser = argparse.ArgumentParser(description='编译 ok-nikke 入口 shim')
    parser.add_argument('--out', default=os.path.join(REPO, 'ok-nikke.exe'),
                        help='输出路径（默认 <仓库根>/ok-nikke.exe）')
    parser.add_argument('--no-manifest', action='store_true',
                        help='不编译资源：无图标、UAC 不提权，仅用于验证 spawn 行为')
    parser.add_argument('--debug', action='store_true', help='带调试信息、不 strip')
    options = parser.parse_args(argv)

    out_file = os.path.abspath(options.out)
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    if not os.path.isfile(SOURCE):
        raise SystemExit(f'找不到源码 {SOURCE}')

    gcc = which('gcc')
    cl = which('cl.exe', 'cl')
    toolchain = 'mingw' if gcc else ('msvc' if cl else None)
    if toolchain is None:
        raise SystemExit('未找到 gcc 或 cl.exe：请安装 MinGW-w64，或使用 VS 开发者命令行')

    resources, extra_flags = [], []
    if options.no_manifest:
        print('已跳过资源编译（--no-manifest）：exe 无图标、不提权，仅用于验证 spawn 行为')
    else:
        resources, extra_flags = prepare_resources(toolchain)

    started = time.time()
    if toolchain == 'mingw':
        command = [gcc, '-O2', '-Wall', '-municode', '-mwindows', '-s' if not options.debug else '-g']
        command += extra_flags + [SOURCE] + resources + ['-o', out_file]
    else:
        command = [cl, '/nologo', '/W3', '/DUNICODE', '/D_UNICODE']
        command += ['/Od', '/Zi'] if options.debug else ['/O2']
        command += [SOURCE, f'/Fe:{out_file}', '/link', '/SUBSYSTEM:WINDOWS'] + resources
    if run(command) != 0:
        raise SystemExit('编译失败')

    size_kb = os.path.getsize(out_file) / 1024
    print(f'构建完成：{out_file}  {size_kb:.0f} KB  用时 {time.time() - started:.1f}s')
    if options.no_manifest:
        print('注意：这是验证用 exe，不要用于发布。')
    else:
        verify_manifest(out_file)
        print('已校验：带 requireAdministrator 提权 manifest，且无 asInvoker 冲突')
    return 0


if __name__ == '__main__':
    sys.exit(main())
