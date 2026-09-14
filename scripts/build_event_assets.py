r"""生成 assets/event_banner 保底活动图包（随包分发，供直连不稳时匹配活动列表行）。

取当前日历里的剧情大活动（复用 event_calendar.parse_events，与运行时同一套过滤），
下载原图 -> 降采样 0.5 倍 -> 写入 assets/event_banner/<banner key>.png。

为什么 0.5 倍（2560x1440 实测）：整图 641KB 命中 0.9534，0.5 倍 179KB 命中 0.9485。
运行时仍会把图缩放到行宽（1440p 下 749px）再裁子区域，与在线图走同一条代码路径。

本脚本只写 assets/，不碰 cache/（运行期缓存由 src/event_calendar.py 自己维护）。

用法（相对路径按仓库根解析）：
    python scripts/build_event_assets.py              # 刷新，并删除不在收录范围内的旧图
    python scripts/build_event_assets.py --no-prune   # 只增不删
    python scripts/build_event_assets.py --dry-run    # 只打印计划，不落盘
    python scripts/build_event_assets.py --scale 1.0  # 不降采样
    python scripts/build_event_assets.py --attempts 5 # 网络尝试次数（默认同 event_calendar.ATTEMPTS）
"""
import argparse
import os
import sys
import tempfile

import cv2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)  # 仓库根目录。
sys.path.insert(0, ROOT)  # 保证任意 cwd 下都能 import src.*。

from src import event_calendar  # noqa: E402

OUT_DIR = os.path.join(ROOT, 'assets', 'event_banner')
DEFAULT_SCALE = 0.5


def display_path(path):
    """相对仓库根显示（跨盘符时 relpath 抛 ValueError，退回绝对路径）。"""
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='生成 assets/event_banner 保底活动图包')
    parser.add_argument('--scale', type=float, default=DEFAULT_SCALE, help='活动图降采样比例（默认 0.5）')
    parser.add_argument('--timeout', type=float, default=20.0, help='单张活动图下载超时秒数（默认 20）')
    parser.add_argument('--attempts', type=int, default=event_calendar.ATTEMPTS,
                        help=f'拉接口/下载的尝试次数（默认 {event_calendar.ATTEMPTS}）')
    parser.add_argument('--no-prune', action='store_true', help='保留不在收录范围内的旧图（默认删除）')
    parser.add_argument('--dry-run', action='store_true', help='只打印计划，不写盘、不删文件')
    return parser.parse_args(argv)


def build_one(event, scale, out_dir=OUT_DIR, timeout=20.0, attempts=event_calendar.ATTEMPTS, dry_run=False):
    """下载 -> 缩放 -> 写入 <out_dir>/<key>.png；返回写入路径，失败返回 None。"""
    out_path = os.path.join(out_dir, event.key + '.png')
    if dry_run:
        print(f'  [dry-run] {event.key} -> {display_path(out_path)}')
        return None
    with tempfile.TemporaryDirectory(prefix='event_banner_') as work_dir:  # 原图只作中转。
        temp_path = os.path.join(work_dir, event.key + '.png')
        try:
            if not event_calendar.download_banner(event.url, temp_path, timeout=timeout, attempts=attempts):
                print(f'  跳过 {event.key}：下载失败或返回内容不是 PNG')
                return None
        except Exception as error:  # noqa: BLE001 - 单张失败不影响其它活动。
            print(f'  跳过 {event.key}：下载异常 {error}')
            return None
        image = cv2.imread(temp_path)
    if image is None:
        print(f'  跳过 {event.key}：PNG 无法解码')
        return None
    scaled = image
    if scale != 1:
        width = max(8, int(round(image.shape[1] * scale)))
        height = max(8, int(round(image.shape[0] * scale)))  # 等比，避免变形。
        scaled = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    os.makedirs(out_dir, exist_ok=True)
    cv2.imwrite(out_path, scaled, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    print(f'  {event.key} -> {scaled.shape[1]}x{scaled.shape[0]}  {os.path.getsize(out_path) / 1024:.0f} KB')
    return out_path


def prune(keys, dry_run, out_dir=OUT_DIR):
    """删除 <out_dir> 里不在 keys 中的 .png。"""
    if not os.path.isdir(out_dir):
        return []
    stale = [name for name in sorted(os.listdir(out_dir))
             if name.lower().endswith('.png') and name[:-4] not in keys]
    for name in stale:
        print(f'  {"[dry-run] 删除" if dry_run else "删除"} {name}')
        if not dry_run:
            os.remove(os.path.join(out_dir, name))
    return stale


def main(argv=None):
    args = parse_args(argv)
    try:
        calendar = event_calendar.fetch_calendar(timeout=args.timeout, attempts=args.attempts)
    except Exception as error:  # noqa: BLE001 - 拉不到就不动保底包。
        print(f'拉取活动日历失败（已尝试 {args.attempts} 次），保底包保持不变：{error}')
        return 1
    events = event_calendar.parse_events(calendar)
    if not events:
        print('当前日历没有剧情大活动（StoryEvent），保底包保持不变')
        return 1
    print(f'收录 {len(events)} 个剧情活动，输出目录 {display_path(OUT_DIR)}')
    built = []
    for event in events:
        path = build_one(event, args.scale, OUT_DIR, timeout=args.timeout,
                         attempts=args.attempts, dry_run=args.dry_run)
        if path:
            built.append(path)
    if not args.no_prune:
        prune([event.key for event in events], args.dry_run, OUT_DIR)
    print(f'完成：写入 {len(built)}/{len(events)} 张{"（dry-run 未落盘）" if args.dry_run else ""}')
    return 0 if built or args.dry_run else 1


if __name__ == '__main__':
    sys.exit(main())
