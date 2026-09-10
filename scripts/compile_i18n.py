# -*- coding: utf-8 -*-
"""把 i18n 下的 .po 编译成运行时使用的 .mo。

用法：
    .\\.venv\\Scripts\\python.exe scripts\\compile_i18n.py            # 编译全部词条
    .\\.venv\\Scripts\\python.exe scripts\\compile_i18n.py --i18n i18n

约定：
- 目录结构 i18n/<locale>/LC_MESSAGES/{ok,ocr}.po，locale 与「设置 → 语言」里的
  选项一一对应（zh_CN / zh_TW / en_US / ja_JP，见 src/patches/language.py）；
- `ok` 域翻译应用自己的 UI，`ocr` 域翻译游戏画面上 OCR 出来的文字；
- 基准语种是简体中文：源码直接写中文，zh_CN 词条里通常不需要条目；
- 英文词条额外补一份「去掉空格」的 msgid（OCR 结果常丢空格，框架会再查一次
  无空格形式，见 ok.task.task.BaseTask 里的 no_space 处理）；
- 同一个 .po 里出现重复 msgid 直接报错退出，避免后写覆盖先写。

只依赖 polib（随 ok-script 一起安装）。改完 .po 必须重新编译，否则改动不生效。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import polib


def iter_po_files(root):
    """按目录顺序列出全部 .po，保证输出稳定。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name.endswith('.po'):
                yield os.path.join(dirpath, name)


def find_duplicate_msgids(po):
    ids = [entry.msgid for entry in po if entry.msgid]
    return sorted(msgid for msgid, count in Counter(ids).items() if count > 1)


def add_space_stripped_entries(po):
    """给英文词条补一份无空格 msgid，返回新增条数。"""
    existing = {entry.msgid for entry in po}
    added = []
    for entry in po:
        if not entry.msgid or ' ' not in entry.msgid or not entry.msgstr:
            continue
        stripped = entry.msgid.replace(' ', '')
        if stripped in existing:
            continue
        existing.add(stripped)
        added.append(polib.POEntry(msgid=stripped, msgstr=entry.msgstr))
    po.extend(added)
    return len(added)


def compile_po(path):
    po = polib.pofile(path)
    duplicates = find_duplicate_msgids(po)
    if duplicates:
        raise ValueError(f'{path} 存在重复 msgid: {duplicates}')
    # 只有英文需要无空格变体：中文/日文里没有词间空格
    added = add_space_stripped_entries(po) if os.sep + 'en_US' + os.sep in path or '/en_US/' in path else 0
    mo_path = os.path.splitext(path)[0] + '.mo'
    po.save_as_mofile(mo_path)
    return mo_path, len(po), added


def main():
    parser = argparse.ArgumentParser(description='编译 i18n 词条 (.po -> .mo)')
    parser.add_argument('--i18n', default='i18n', help='词条根目录，默认 i18n')
    args = parser.parse_args()

    root = args.i18n
    if not os.path.isdir(root):
        print(f'词条目录不存在: {root}')
        return 1

    failed = False
    for po_path in iter_po_files(root):
        try:
            mo_path, entries, added = compile_po(po_path)
        except Exception as error:
            failed = True
            print(f'[失败] {po_path}: {error}')
            continue
        extra = f'，含 {added} 条无空格变体' if added else ''
        print(f'[已编译] {po_path} -> {mo_path}（{entries} 条{extra}）')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
