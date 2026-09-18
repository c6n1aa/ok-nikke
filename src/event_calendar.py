"""官方活动日历 + 活动图缓存，以及活动列表的行匹配模板（纯 stdlib + cv2，不依赖 ok 框架）。

几何标定（2560x1440 实测，回归见 tests/TestEventCalendar.py）：
- 游戏内把官方活动图等比渲染成列表一行：行宽 749（屏宽 29.26%）、行高 250、长宽比 3:1；
- 模板取 SUBJECT = banner 的 x[0.60,0.95] × y[0,0.70]：避开左下日期浮层与最右行边框，
  列表最后一行只有 175/250 = 70% 可见，模板更高即装不下（y=0.92 时该行掉到 0.29）；
- 匹配限定在 SEARCH_BOX 内：三行 0.89~0.96，其它行 ≤0.61，阈值 0.8。

取图顺序：cache/event_banner/ -> assets/event_banner/（随包保底图，由 scripts/build_event_assets.py 生成）
-> 联网下载。匹配路径不联网，联网只在 refresh()。

收录范围：version_event 且 type∈{StoryEvent, FieldHubEvent}（FieldHub 为含 STORY/FIELD HUB 子页的新大活动）。
状态信息覆盖 STATUS_CATEGORIES（版本活动 /
协同作战+单人突袭 / 竞技场），与活动图由同一次 refresh() 落到 cache/event_banner/calendar.json。
"""

from __future__ import annotations

import hashlib  # 缓存文件名取 URL 的 md5。
import json  # 解析日历接口返回、读写状态快照。
import logging  # 4xx 等不可重试的失败需要留痕。
import os  # 缓存目录与路径拼接。
import re  # 缓存文件名形态判定（清理只认 md5 十六进制 + .png）。
import time  # 重试间隔、快照时间、过期判定。
import urllib.error  # 捕获 HTTPError 以区分 4xx/5xx。
import urllib.request  # 拉取日历与活动图（纯标准库，不新增依赖）。
from dataclasses import asdict, dataclass  # 活动条目/快照结构与其 JSON 化。

import cv2  # 图像裁剪与缩放。

logger = logging.getLogger(__name__)  # 不引入 ok 框架，日志走 stdlib。

# ---- 几何标定（2560x1440 实测） ----
REF_WIDTH = 2560  # 标定截图宽度。
REF_HEIGHT = 1440  # 标定截图高度。
ROW_WIDTH_AT_REF = 749  # 列表单行宽度（像素）；行高 250。
SUBJECT = (0.60, 0.00, 0.95, 0.70)  # 模板在 banner 内的子区域（左、上、右、下，相对比例）。
SEARCH_BOX = 'box_event_banner_area'  # 列表面板的 coco 框特征名（1440p 下 881,286,799x1038）。
FALLBACK_SCALES = (0.97, 0.98, 0.99, 1.01, 1.02, 1.03)  # 基准尺度未命中时的备选档位。

# ---- 官方活动日历接口（免登录） ----
CALENDAR_URL = "https://api.blablalink.com/api/ugc/direct/standalonesite/Dynamics/GetCalendarDetail"
CDN_BASE = "https://sg-tools-cdn.blablalink.com"
USER_AGENT = "ok-nikke/1.0"
EVENT_CATEGORY = "version_event"  # 剧情活动所在分类。
EVENT_TYPES = ("StoryEvent", "FieldHubEvent")  # 剧情大活动的 type（登录活动是 LoginEvent；FieldHubEvent 是含 STORY/FIELD HUB 子页的新版大活动）。
STATUS_CATEGORIES = ("version_event", "raid", "arena")  # 状态信息收录：版本活动 / 协同作战+单人突袭 / 竞技场。
SNAPSHOT_NAME = "calendar.json"  # 状态快照文件名。
EXPIRE_NOTIFY_SECONDS = 24 * 3600  # 「即将结束」判定的提前量：结束时间在未来 24 小时内。
BANNER_KEY_PREFIX = "EVENT_BANNER_"  # 展示名从 banner 键推导时去掉的前缀。
ATTEMPTS = 3  # 网络请求默认尝试次数（含首次）。
RETRY_DELAY = 0.8  # 重试间隔（秒）。
BUNDLED_DIR = os.path.join("assets", "event_banner")  # 随包保底图目录。
CACHE_DIR = os.path.join("cache", "event_banner")  # 运行期缓存目录（cache/ 不入仓）。
LARGE_PRIMES = (224737, 1000639, 2654435761, 2654435769, 1000621, 4294967291)  # CDN 路径混淆用素数表（复刻官网前端，改一位即 404）。


@dataclass(frozen=True)
class CalendarEvent:
    """日历里的一条活动。"""

    key: str  # banner 资源键。
    name: str  # 接口原文活动名（落盘保留原样；接口 name 可能指向错误的活动，展示用 display_name）。
    category: str  # 来源分类（version_event；保底包补齐的为 bundled）。
    event_type: str  # 接口 type 字段，决定 CDN 子路径。
    start_time: int  # 开始时间（unix 秒，0 = 接口未给出）。
    end_time: int  # 结束时间（unix 秒，0 = 接口未给出）。
    url: str  # 活动图 CDN 地址。

    @property
    def display_name(self):
        """展示名：banner 键去掉 EVENT_BANNER_ 前缀（不采用接口 name，见 parse_events）。"""
        return strip_banner_prefix(self.key)


@dataclass(frozen=True)
class CalendarSnapshot:
    """一次日历拉取的快照。fetched_at 为 0 表示没拿到线上数据（events 为保底包内容）。"""

    fetched_at: int  # 拉取时间（unix 秒）。
    events: tuple  # tuple[CalendarEvent]。
    status: dict  # 分类 -> [条目状态 dict]。

    def is_fresh(self, ttl_seconds):
        """距上次成功拉取是否在 ttl 秒内。"""
        return bool(self.fetched_at) and (time.time() - self.fetched_at) < ttl_seconds

    def status_of(self, category):
        """某分类的状态条目（不存在时为空列表）。"""
        return list(self.status.get(category) or [])

    def pick_events(self, count=1, now=None):
        """按开始时间倒序取前 count 个未过期活动（最新在前；时间缺失记 0 的排最后，同时间保持接口顺序）。

        两个 EventTask 并行时各认一个：最新取 [0]、次新取 [1]。count=None 返回全部（仍按时间倒序）。
        end_time 已过期的活动直接剔除（接口偶发含过期条目时不再空扫）；end_time=0 视为时间未知，保留。
        now 参数供测试注入当前时间（unix 秒），缺省取真实时间。
        """
        ordered = sorted(self.events, key=lambda event: -event.start_time)
        cutoff = time.time() if now is None else now  # 过期判定用当前时间。
        ordered = [event for event in ordered if not event.end_time or event.end_time > cutoff]
        return ordered if count is None else ordered[:max(0, count)]


def screen_scale(screen_width, screen_height, ref_width=REF_WIDTH, ref_height=REF_HEIGHT):
    """当前分辨率相对标定分辨率的缩放比（取 min，与框架 find_scaled_template 一致）。"""
    if not screen_width or not screen_height:  # 无帧（测试环境）。
        return 0.0
    return min(screen_width / ref_width, screen_height / ref_height)


def row_width(screen_width, screen_height, ref_width=REF_WIDTH, ref_height=REF_HEIGHT):
    """当前分辨率下列表单行的宽度（像素）。"""
    return ROW_WIDTH_AT_REF * screen_scale(screen_width, screen_height, ref_width, ref_height)


def build_row_template(banner, row_width_px, scale=1.0):
    """活动图 -> 行匹配模板：等比缩放到 row_width_px，再裁出 SUBJECT。

    Args:
        banner: 活动图 BGR ndarray。
        row_width_px: 目标行宽（由 row_width() 算得）。
        scale: 额外缩放系数（FALLBACK_SCALES 档位）。

    Returns:
        裁剪后的 BGR ndarray。
    """
    if banner is None or getattr(banner, 'size', 0) == 0 or banner.ndim != 3:  # 空图或非 BGR。
        raise ValueError('event banner image is empty or not a BGR image')
    height, width = banner.shape[:2]
    target_w = max(8, int(round(row_width_px * scale)))
    target_h = max(8, int(round(target_w * height / width)))
    factor = target_w / width
    interpolation = cv2.INTER_AREA if factor < 1 else cv2.INTER_LINEAR  # 缩小用 AREA，放大用 LINEAR。
    resized = cv2.resize(banner, (target_w, target_h), interpolation=interpolation)
    x1, y1, x2, y2 = SUBJECT
    return resized[int(target_h * y1):int(target_h * y2), int(target_w * x1):int(target_w * x2)]


def _djb2_signed(text, seed):
    """有符号 djb2 哈希（官网前端实现）。"""
    value = seed
    for char in text:
        value = (value * 33 + ord(char)) & 0xFFFFFFFF
    if value >= 0x80000000:  # 转有符号 32 位。
        value -= 0x100000000
    return value


def _two_letter(text, mod):
    """混淆段：两位小写字母。"""
    result = _djb2_signed(text, mod) % mod
    return chr(97 + (result // 26) % 26) + chr(97 + result % 26)


def _two_number(text, mod):
    """混淆段：两位数字。"""
    result = _djb2_signed(text, mod) % mod % 99
    return f"{result:02d}"


def obfuscate_path(path):
    """明文路径 -> CDN 实际路径（中间段「两位字母-两位数字」，末段 md5 + 原扩展名）。"""
    segments = [s for s in path.split('/') if s]
    out = []
    for index, segment in enumerate(segments):
        if index == len(segments) - 1:
            _, _, extension = segment.rpartition('.')
            out.append(hashlib.md5(path.encode()).hexdigest() + '.' + extension)
        else:
            out.append(f"{_two_letter(path, LARGE_PRIMES[index])}-{_two_number(path, LARGE_PRIMES[index])}")
    return '/'.join(out)


def banner_url(key, event_type='', extension='png'):
    """资源键 + 活动类型 -> CDN 地址（SeasonPass 走 icon/Logo/pass，其余走 schedule/banner）。"""
    if event_type == 'SeasonPass':
        sub_path = f"icon/Logo/pass/{key}.{extension}"
    else:
        sub_path = f"schedule/banner/{key}.{extension}"
    return f"{CDN_BASE}/{obfuscate_path(sub_path)}"


def fetch_calendar(timeout=10.0, attempts=1):
    """拉取日历 JSON；网络异常/5xx 按 attempts 重试，4xx 不重试，最后一次仍失败抛异常。"""
    last_error = None
    for attempt in range(1, max(1, int(attempts)) + 1):
        request = urllib.request.Request(
            CALENDAR_URL,
            data=b"{}",  # 免登录接口，空 JSON body。
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT,
                     "Origin": "https://www.blablalink.com"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if 400 <= error.code < 500:  # 请求本身无效（接口地址/参数变更后的 403/404）。
                logger.warning(f'日历接口返回 HTTP {error.code}，不再重试')
                raise
            last_error = error
        except Exception as error:  # noqa: BLE001 - 网络异常。
            last_error = error
        if attempt < attempts:
            time.sleep(RETRY_DELAY)
    raise last_error


def strip_banner_prefix(key):
    """banner 键的展示名：去掉 EVENT_BANNER_ 前缀（大小写无关，无前缀则原样返回）。"""
    text = str(key or '')
    return text[len(BANNER_KEY_PREFIX):] if text.upper().startswith(BANNER_KEY_PREFIX) else text


def parse_events(calendar):
    """取出 version_event 且 type∈EVENT_TYPES（剧情大活动）的项目，按 banner 键去重保序。

    name 保留接口原文（落盘不被加工）；展示名请用 event.display_name（banner 键去前缀），
    因为接口 name 可能指向错误的活动（实测 GREATVILLAINUNION 的 name 是开服活动
    "No Caller ID" 且长期未修正）。
    """
    events = []
    seen = set()
    node = ((calendar or {}).get("data") or {}).get(EVENT_CATEGORY)
    if not isinstance(node, dict):  # 分类缺失。
        return events
    for item in node.get("items") or []:
        event_type = item.get("type") or ""
        if event_type not in EVENT_TYPES:  # 其它子类型（登录活动等）。
            continue
        key = (item.get("banner") or "").strip()
        if not key or key in seen:  # 无活动图，或同图重复。
            continue
        seen.add(key)
        events.append(CalendarEvent(
            key=key,
            name=item.get("name") or key,
            category=EVENT_CATEGORY,
            event_type=event_type,
            start_time=int(item.get("start_time") or 0),
            end_time=int(item.get("end_time") or 0),
            url=banner_url(key, event_type),
        ))
    return events


def download_banner(url, path, timeout=20.0, attempts=1):
    """下载活动图到 path 并校验 PNG magic；网络异常/5xx 按 attempts 重试，4xx 不重试。"""
    for attempt in range(1, max(1, int(attempts)) + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
            if data[:8] != b"\x89PNG\r\n\x1a\n":  # 非 PNG：CDN 错误页。
                return False
            with open(path, "wb") as file:
                file.write(data)
            return True
        except urllib.error.HTTPError as error:
            if 400 <= error.code < 500:  # 请求本身无效（如路径规则变更后的 403/404）。
                logger.warning(f'CDN 返回 HTTP {error.code}，不再重试：{url}')
                return False
            if attempt < attempts:
                time.sleep(RETRY_DELAY)
        except Exception:  # noqa: BLE001 - 网络异常。
            if attempt < attempts:
                time.sleep(RETRY_DELAY)
    return False


def cache_path(url, cache_dir=CACHE_DIR):
    """活动图在下载缓存里的路径（文件名取 URL 的 md5）。"""
    return os.path.join(cache_dir, hashlib.md5(url.encode()).hexdigest() + '.png')


def local_banner_path(key='', url='', cache_dir=CACHE_DIR, bundled_dir=BUNDLED_DIR):
    """本地已有活动图的路径（缓存 -> 保底包），都没有返回 None。不联网。

    Args:
        key: banner 资源键（保底包按 <key>.png 命名）。
        url: 活动图 URL（缓存文件名取其 md5）；留空则只查保底包。
    """
    if url:
        cached = cache_path(url, cache_dir)
        if os.path.exists(cached):
            return cached
    if key:
        bundled = os.path.join(bundled_dir, key + '.png')
        if os.path.exists(bundled):
            return bundled
    return None


def bundled_keys(bundled_dir=BUNDLED_DIR):
    """保底包里的活动图键清单（文件名去扩展名；目录不存在返回空）。"""
    if not os.path.isdir(bundled_dir):
        return []
    return sorted(name[:-4] for name in os.listdir(bundled_dir) if name.lower().endswith('.png'))


def prune_expired_events(events, now=None):
    """按 end_time 剔除已过期活动（end_time=0 视为时间未知，保留）；now 供测试注入，缺省取真实时间。"""
    if now is None:
        now = time.time()
    return [event for event in events if not event.end_time or event.end_time > now]


def expiring_events(events, within_seconds=EXPIRE_NOTIFY_SECONDS, now=None):
    """结束时间在未来 within_seconds 内且尚未过期的活动（end_time=0 视为时间未知，跳过）。

    now 供测试注入（unix 秒），缺省取真实时间；返回值保持传入顺序。
    """
    if now is None:
        now = time.time()
    deadline = now + max(0, within_seconds)
    return [event for event in events
            if event.end_time and event.end_time > now and event.end_time <= deadline]


def _remove_quiet(path):
    """删文件，不存在/删除失败不抛（缓存清理只做尽力而为）。"""
    try:
        os.remove(path)
    except OSError:
        pass


_CACHE_PNG_PATTERN = re.compile(r"^[0-9a-f]{32}\.png$", re.IGNORECASE)  # cache_path() 产物的命名形态：url 的 md5 十六进制 + .png。


def _is_cache_banner(name):
    """是否本项目活动图缓存文件的命名形态（md5 十六进制 + .png）。

    删除只认这种形态：cache 目录里的陌生文件（用户手放的文件、其它组件产物）一律不动。
    """
    return bool(_CACHE_PNG_PATTERN.match(name))


def prune_cache(keep_urls, cache_dir=CACHE_DIR):
    """删除缓存目录里不属于 keep_urls 的活动图，calendar.json 不动。返回被删文件名。

    只删本项目缓存命名形态（md5 十六进制 + .png）的常规文件：cache_path() 决定"当前活动图叫什么"，
    不匹配的即为往期遗留/已过期；陌生文件与同名目录一律不动。删除失败静默。
    """
    if not os.path.isdir(cache_dir):
        return []
    keep = {os.path.basename(cache_path(url, cache_dir)) for url in keep_urls}
    removed = []
    for name in sorted(os.listdir(cache_dir)):
        if not _is_cache_banner(name) or name in keep:  # 非本项目缓存命名形态的 .png 也不动。
            continue
        path = os.path.join(cache_dir, name)
        if os.path.isfile(path):  # 同名目录不动。
            _remove_quiet(path)
            removed.append(name)
    return removed


def ensure_cached(event_or_url, cache_dir=CACHE_DIR, bundled_dir=BUNDLED_DIR, timeout=20.0, attempts=1):
    """确保活动图在本地（缓存 -> 保底包 -> 下载），返回路径；全都失败返回 None。

    Args:
        event_or_url: CalendarEvent（带 key，可查保底包）或活动图 URL 字符串。
        attempts: 下载尝试次数（含首次）。
    """
    is_event = isinstance(event_or_url, CalendarEvent)
    url = event_or_url.url if is_event else str(event_or_url)
    key = event_or_url.key if is_event else ''
    path = local_banner_path(key, url, cache_dir, bundled_dir)
    if path:
        return path
    os.makedirs(cache_dir, exist_ok=True)
    path = cache_path(url, cache_dir)
    if download_banner(url, path, timeout=timeout, attempts=attempts):
        return path
    if os.path.exists(path):  # 清掉半截文件，避免下次误判为已缓存。
        os.remove(path)
    return None


def parse_status(calendar):
    """取 STATUS_CATEGORIES 的状态条目，只保留标量字段（丢掉 rewards/characters 等数组）。"""
    status = {}
    data = (calendar or {}).get("data") or {}
    for category in STATUS_CATEGORIES:
        node = data.get(category)
        if not isinstance(node, dict):
            continue
        items = []
        for item in node.get("items") or []:
            if not isinstance(item, dict):
                continue
            items.append({key: value for key, value in item.items()
                          if value is None or isinstance(value, (str, int, float, bool))})
        if items:
            status[category] = items
    return status


def snapshot_to_dict(snapshot):
    """快照 -> 可 JSON 化的 dict。"""
    return {
        "fetched_at": snapshot.fetched_at,
        "events": [asdict(event) for event in snapshot.events],
        "status": snapshot.status,
    }


def snapshot_from_dict(data):
    """dict -> 快照；结构不对返回 None。"""
    if not isinstance(data, dict):
        return None
    events = []
    for item in data.get("events") or []:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        events.append(CalendarEvent(
            key=str(item["key"]),
            name=str(item.get("name") or item["key"]),
            category=str(item.get("category") or ""),
            event_type=str(item.get("event_type") or ""),
            start_time=int(item.get("start_time") or 0),
            end_time=int(item.get("end_time") or 0),
            url=str(item.get("url") or ""),
        ))
    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    return CalendarSnapshot(fetched_at=int(data.get("fetched_at") or 0), events=tuple(events), status=status)


def snapshot_path(cache_dir=CACHE_DIR):
    """状态快照路径（与活动图同目录）。"""
    return os.path.join(cache_dir, SNAPSHOT_NAME)


def save_snapshot(snapshot, cache_dir=CACHE_DIR):
    """写快照到缓存：先写 .tmp 再 os.replace。"""
    path = snapshot_path(cache_dir)
    os.makedirs(cache_dir, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(snapshot_to_dict(snapshot), file, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)
    return path


def load_snapshot(cache_dir=CACHE_DIR):
    """读缓存里的快照；没有或损坏返回 None。不联网。"""
    try:
        with open(snapshot_path(cache_dir), encoding="utf-8") as file:
            return snapshot_from_dict(json.load(file))
    except Exception:  # noqa: BLE001 - 不存在/改坏/无权限都按没有缓存处理。
        return None


def refresh(timeout=5.0, download_timeout=10.0, attempts=ATTEMPTS,
            cache_dir=CACHE_DIR, bundled_dir=BUNDLED_DIR):
    """拉日历并落缓存：状态写 calendar.json、剧情活动图下到 cache，返回快照。本模块唯一联网入口。

    不抛异常：接口拉不到则返回只有保底包内容的快照（fetched_at=0）且不覆盖已有快照；
    单张图下载失败则该活动回落到保底图或从清单剔除；已缓存的图与快照直接复用；
    接口可达时未被接口返回的保底包活动视为已过期/下架，不进快照。

    Returns:
        CalendarSnapshot。
    """
    try:
        calendar = fetch_calendar(timeout=timeout, attempts=attempts)
    except Exception:  # noqa: BLE001 - 重试后仍失败。
        calendar = None
    parsed = parse_events(calendar) if calendar else []
    events = prune_expired_events(parsed)  # 过期活动不进下载、快照与缓存保留名单。
    if calendar and len(events) < len(parsed):
        logger.debug(f'剔除已过期活动 {len(parsed) - len(events)} 个，不下载其活动图')
    ready = []  # 本地已有图的活动。
    for event in events:
        if ensure_cached(event, cache_dir=cache_dir, bundled_dir=bundled_dir,
                         timeout=download_timeout, attempts=attempts):
            ready.append(event)
    if not calendar:  # 保底包独有活动只在接口不可达时兜底：接口可达而不返回的键视为已过期/下架，不复活为活动。
        for key in bundled_keys(bundled_dir):  # 无接口元数据，名字用键顶替（展示名走 display_name）。
            ready.append(CalendarEvent(key=key, name=key, category='bundled', event_type='',
                                       start_time=0, end_time=0, url=''))
    snapshot = CalendarSnapshot(fetched_at=int(time.time()) if calendar else 0,
                                events=tuple(ready), status=parse_status(calendar) if calendar else {})
    if calendar:  # 只在拿到线上数据时落盘与清理，避免断网时把好数据/图删掉。
        save_snapshot(snapshot, cache_dir)
        # keep = 未过期活动的图：过期图与往期/下架活动图一并清掉（只删缓存命名形态的文件）。
        removed = prune_cache([event.url for event in events], cache_dir)
        if removed:
            logger.debug(f'清理非当期/已过期活动图 {len(removed)} 张：{", ".join(removed)}')
    return snapshot


def prepare(timeout=5.0, download_timeout=10.0, attempts=ATTEMPTS,
            cache_dir=CACHE_DIR, bundled_dir=BUNDLED_DIR):
    """可直接匹配的剧情活动清单（= refresh().events）。"""
    snapshot = refresh(timeout=timeout, download_timeout=download_timeout, attempts=attempts,
                       cache_dir=cache_dir, bundled_dir=bundled_dir)
    return list(snapshot.events)
