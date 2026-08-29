"""从咨询 JSON 生成 SQLite 数据库 assets/advise.db（全量覆盖，不做增量）。

源数据（人工维护的唯一真源）是 dev_tools/advise_data/nikke_advises_i18n.json，
结构为 5 种语言共享同一组条目：character[].advises[] 的每个元素同时持有
prompt/good/bad 的五种语言文本，因此各语言的条目数天然一致。

流程：
    读 JSON -> 校验 -> 角色名为空则跳过 -> 写临时库 -> VACUUM -> 原子替换

导入规则：
    1. 角色名（character[].name[locale]）为空字符串 -> 该角色在该语言下整条不入库。
       不做回退填充，即"有就有，没有就没有"；各语言条目数不强求对齐
       （当前 zh_TW 为 160 个角色，ja/ko 为 0，zh_CN 与 en 为 162）。
    2. 不做任何文本加工，JSON 里是什么就存什么。文本规范化（统一省略号为「……」、
       去掉换行符等）一律在 JSON 层面完成，本脚本只负责搬运。
    3. 全量覆盖：db 是派生产物，随时可从 JSON 重建，不保留任何 JSON 之外的信息。

校验（阻断式，一次收集全部错误后统一报出；失败时不生成/不改动任何文件，退出码 1）：
    1. 每个 name / prompt / good / bad 必须含全部 5 个语言键（缺键会被静默当成"未翻译"）
    2. 每个角色的条目数必须与其他角色一致
    3. 角色名为空但该语言已有译文 -> 报错（否则这些译文会被静默丢弃）
    4. zh_CN 角色名必须唯一（报错定位用）

用法（必须在仓库根目录运行，使相对路径生效）：
    .\\.venv\\Scripts\\python.exe scripts\\build_advise_db.py
    .\\.venv\\Scripts\\python.exe scripts\\build_advise_db.py --source <json> --target <db>
"""

import argparse
import json
import os
import sqlite3
import sys

LOCALES = ('zh_CN', 'zh_TW', 'en', 'ja', 'ko')  # 支持的语言，顺序即处理顺序。
TEXT_FIELDS = ('prompt', 'good', 'bad')  # 每条咨询的三个文本字段。

DEFAULT_SOURCE = os.path.join('dev_tools', 'advise_data', 'nikke_advises_i18n.json')
DEFAULT_TARGET = os.path.join('assets', 'db', 'advise.db')

# 表结构：主键前缀 (locale, character_name) 即运行时的固定查询条件，因此无需二级索引；
# 第三列 advise_index 使同一角色的条目物理连续且有序，查询时不必再加 ORDER BY。
DDL = """
CREATE TABLE advise (
    locale         TEXT    NOT NULL,
    character_name TEXT    NOT NULL,
    advise_index   INTEGER NOT NULL,
    prompt         TEXT    NOT NULL,
    good           TEXT    NOT NULL,
    bad            TEXT    NOT NULL,
    PRIMARY KEY (locale, character_name, advise_index)
) WITHOUT ROWID;
"""

def validate(chars):
    """返回全部错误描述；空列表表示通过。一次收集所有问题，便于维护者一次修完。"""
    errors = []

    # 校验 2 的基准条目数：取第一个角色的条目数，后续逐一比对。
    base_count = len(chars[0]['advises']) if chars else 0

    # 校验 4：zh_CN 角色名需唯一，否则报错信息无法定位到具体角色。
    seen = {}
    for c in chars:
        key = c['name'].get('zh_CN', '')
        if key in seen:
            errors.append('zh_CN 角色名重复: %r（第 %d、%d 个角色）'
                          % (key, seen[key], len(seen)))
        seen.setdefault(key, len(seen))

    for c in chars:
        key = c['name'].get('zh_CN', '')
        label = '角色「%s」' % key

        # 校验 1：缺语言键会被 .get(lang, '') 静默吞掉，与"未翻译"无法区分。
        missing = [l for l in LOCALES if l not in c['name']]
        if missing:
            errors.append('%s 的 name 缺少语言键: %s' % (label, missing))
        for i, it in enumerate(c['advises']):
            for f in TEXT_FIELDS:
                if f not in it:
                    errors.append('%s 第 %d 条缺少字段 %s' % (label, i, f))
                    continue
                miss = [l for l in LOCALES if l not in it[f]]
                if miss:
                    errors.append('%s 第 %d 条 %s 缺少语言键: %s' % (label, i, f, miss))

        # 校验 2：条目数不一致会导致后续定位混乱。
        if len(c['advises']) != base_count:
            errors.append('%s 条目数 %d，与基准 %d 不符'
                          % (label, len(c['advises']), base_count))

        # 校验 3：名字为空但该语言已有译文 -> 这些译文会因跳过规则被静默丢弃。
        for lang in LOCALES:
            if c['name'].get(lang, ''):
                continue
            filled = sum(1 for it in c['advises'] for f in TEXT_FIELDS
                         if it.get(f, {}).get(lang))
            if filled:
                errors.append('[%s] %s 未填 %s 角色名，但已有 %d 处译文 -> 这些译文将被丢弃'
                              % (lang, label, lang, filled))
    return errors


def collect(chars):
    """生成待入库的行：角色名为空的语言整条跳过，其余按 (语言, 角色, 序号) 展开。

    文本原样搬运，不做规范化——规范化属于 JSON 层面的工作。
    """
    rows = []
    for c in chars:
        for lang in LOCALES:
            name = c['name'].get(lang, '')
            if not name:
                continue  # 名字为空 -> 该角色在该语言下不入库，不做回退填充。
            for i, it in enumerate(c['advises']):
                rows.append((lang, name, i,
                             *[it.get(f, {}).get(lang, '') for f in TEXT_FIELDS]))
    return rows


def build_db(rows, target):
    """写入临时库后 VACUUM 再原子替换目标库；中途失败不会损坏已有的 db。"""
    tmp = target + '.tmp'
    for ext in ('', '-wal', '-shm'):  # 清掉可能残留的临时库及其 WAL 文件。
        if os.path.exists(tmp + ext):
            os.remove(tmp + ext)

    con = sqlite3.connect(tmp)
    try:
        con.executescript(DDL)
        con.executemany('INSERT INTO advise VALUES (?,?,?,?,?,?)', rows)
        con.commit()
        con.execute('VACUUM')  # 整理碎片，实测体积 1.88 MB -> 1.25 MB。
        con.commit()
    except Exception:
        con.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    con.close()

    os.replace(tmp, target)  # Windows 上为原子操作，直接覆盖目标库。


def main():
    parser = argparse.ArgumentParser(description='从咨询 JSON 生成 advise.db（全量覆盖）')
    parser.add_argument('--source', default=DEFAULT_SOURCE, help='源 JSON 路径')
    parser.add_argument('--target', default=DEFAULT_TARGET, help='输出 db 路径')
    args = parser.parse_args()

    if not os.path.exists(args.source):
        print('源文件不存在: %s' % args.source)
        return 1

    with open(args.source, encoding='utf-8') as f:
        data = json.load(f)
    chars = data['character'] if isinstance(data, dict) else data
    print('源文件: %s（%.2f MB）' % (args.source, os.path.getsize(args.source) / 1024 / 1024))

    errors = validate(chars)
    if errors:
        print('\n校验失败，共 %d 个问题：' % len(errors))
        for e in errors[:50]:  # 最多打印 50 条，避免刷屏。
            print('  ✗', e)
        if len(errors) > 50:
            print('  ... 另有 %d 条未显示' % (len(errors) - 50))
        print('\n未生成 db，现有 %s 未改动' % args.target)
        return 1
    print('校验通过')

    rows = collect(chars)
    parent = os.path.dirname(args.target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    build_db(rows, args.target)

    print('\n已生成: %s（%.2f MB）' % (args.target, os.path.getsize(args.target) / 1024 / 1024))
    print('%-8s %8s %10s' % ('语言', '角色数', '行数'))
    con = sqlite3.connect('file:%s?mode=ro&immutable=1' % args.target.replace(os.sep, '/'), uri=True)
    for lang in LOCALES:
        nch = con.execute('SELECT count(DISTINCT character_name) FROM advise WHERE locale=?',
                          (lang,)).fetchone()[0]
        nrow = con.execute('SELECT count(*) FROM advise WHERE locale=?', (lang,)).fetchone()[0]
        if nrow or nch:
            print('%-8s %8d %10d' % (lang, nch, nrow))
    con.close()
    print('%-8s %8s %10d' % ('合计', '', len(rows)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
