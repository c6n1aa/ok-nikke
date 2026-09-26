"""活动关卡页（STAGE LIST）的读取策略：文本判据 + 几何切片 + 行解析 + OCR 流水线。

职责边界按「是否碰帧、是否发动作」划：本模块不碰帧、不发动作，OCR 由调用方以回调注入
（`read_rows(ocr_region, ...)`）；点击、滚动、等待与界面判态都在调用方（`EventTask`）。
行状态（已通关 / 可重复挑战 / 未解锁）不在这里判定：那是页面文案语义（逐期美术都会换，还会漏检、
把锁孔读成编号），由调用方点开候选行、看关卡详情页按钮状态后验判定。

分三层：

- 文本判据：`stage_id_candidates` / `is_stage_anchor` / `count_numbers`（编号与行锚点的提取，纯 stdlib）；
- 几何策略：`list_strip` / `anchor_pitch` / `band_box` / `anchor_bands` / `uniform_bands` / `ocr_tiles`
  （列表竖条、行距、窄带切片、OCR 切块；矩形用 `ok.feature.Box`）；
- 解析与流水线：`parse`（一层块 → 可选关卡行）与 `read_rows`（注入 OCR：分层 → 切片降级 → 缺口补扫）。

流水线（`parse`）：编号块 → 同列重复识别去重 → 序列共识定编号。筛选规则全部来自页面结构，与美术、
字号、颜色无关：

- 编号提取只看「块里唯一的一段数字 + 分隔符」（见 `stage_id_candidates`），其余字符一律当行首装饰；
- 同一行位置上只留一关：两层 OCR 对同一行读出**不同**编号时（实机 `16` 与 `EVENT 1-6`）两个读数都留下，
  按与相邻行的序列几何裁决（读数相同的重复识别在这一步之前就并掉了）；
- 编号由序列共识定：逐行按 y 取递增编号，取「字面编号行最多 → 位置偏差最小 → 保留行最多 → 编号偏差
  最小」的解释。真实行的编号总能按字面读出来；噪声（顶栏计数器、背景装饰文字）要么与真实行撞号，
  要么落不到序列几何上任何缺行的位置——两种解释都输给「丢弃这一行」。行距以页面自身量到的编号间距
  为准（地图页的点间距可以是标定值的两倍），量出来了才拿几何去卡编号间隔。

`read_rows` 的分层与降级：整条区域与按行距切的分块两层都跑（两者对页面的取舍相反：整条看整体、
分块经预放大后看小字），按类别 + 邻近 y 去重合并；编号读不全时按行锚点（或标定行距）切窄带补扫；
最后按编号序列缺口 + 列表末尾补扫一轮（末尾是序列共识的盲区，而最下面那行正是当前进度关）。
策略轨迹以 `notes` 返回，由调用方记日志。
"""

from __future__ import annotations

import logging  # 调试日志走 stdlib（与 event_calendar 风格一致）。
import math  # 窄带高度按固定档位向上取整（OCR 输入尺寸归一到有限集合）。
import re  # 编号体提取用正则（纯 stdlib）。
from dataclasses import dataclass  # 行条目与文本块的不可变结构。

from ok.feature.Box import Box  # 几何策略的矩形类型（纯数据类，无 IO）。

logger = logging.getLogger(__name__)  # 日志走 stdlib。

# 受限候选表：编号只可能是这些值，误读一律收敛到最近合法值（方案 §7）。
ALLOWED_IDS = tuple(f"1-{i:02d}" for i in range(1, 17))  # 1-01 ~ 1-16（特殊活动最多 16 关；HARD 与 NORMAL 共用同一套）。

MIN_SCORE = 0.6  # 置信度下限（实测 0.612 的编号块可用，只剔除极低分噪声）。
ROW_PITCH_AT_REF = 120  # 行距兜底标定值（2560x1440 实测直排约 115~120px），按分辨率缩放比缩放。
PITCH_CLUSTER_RATIO = 0.4  # 同带判定（相对兜底行距），用于把编号聚成一行线估行距。
PITCH_GAP_RATIO = 1.5  # 行线间距超过最小间距该倍数 = 漏行造成的成倍间距，估行距时剔除。
DUP_ROW_RATIO = 0.4  # 「同一行」的纵向容差（相对行距）：跨层去重与同列去重共用这一个来源。
GRID_GAP_TOLERANCE = 1.0  # 编号间隔与实测几何间隔允许相差的行数（两侧各留一行余量，见 _select_sequence）。
# 行锚点文案（`EVENT` 与编号同带的两行式）：只用来定位「哪里是行」（列表区切片补扫用），不是行状态。
STAGE_ANCHOR_KEYWORDS = ("event",)
STAGE_MAX_KEYWORD_DISTANCE = 2  # 锚点关键词模糊匹配的最大编辑距离（美术字 OCR 抖动）。
# OCR 区域切块：onnxocr 检测器的 det_limit_side_len 默认 960（limit_type=max），超过就按最长边等比压缩
# 再送模型——整屏竖条 729x1440 会被压到 480x960，关卡编号这种小字直接读不出（实机 08.png 整条只读到
# 1-06 一个编号）。故调用方把超限区域切成 ≤ 上限的小块（见 ocr_tiles）。
OCR_TILE_LIMIT = 960  # 单块最长边（像素），与检测器上限同值。
OCR_TILE_OVERLAP_RATIO = 1.0  # 相邻块重叠量 = 该比例 × 兜底行距（行文字不会被切在块边界上）。
OCR_TILE_ROWS = 6  # 分块高度 = 行距 × 该行数：块要够矮，预放大才作用在小字上（见 ocr_tiles）。
OCR_UPSCALE_MAX = 2.0  # 喂给引擎前的预放大上限（检测器不放大，低分辨率下靠它补像素，见 ocr_upscale）。

# 行窄带切片（见 list_strip / band_box / anchor_bands / uniform_bands）。
# 无行锚点时的兜底切片条数上限：必须 ≥ 支持分辨率下按兜底行距切出的行数（1440/120 = 900/75 = 12），
# 否则列表末段切不到；上限本身只用于防病态参数（异常 scale）把 OCR 调用刷爆。
UNIFORM_MAX_BANDS = 16
# 行窄带高度量化档位（像素）：把 OCR 输入高度收进有限档位（行距/缺口高度逐屏漂移，直接拿来切片会让尺寸
# 每次都不重样；OpenVINO CPU 后端按尺寸永久占内存，量化后即使切回它也不会涨）。
BAND_HEIGHT_STEP = 32

SOURCE_NUMBER = "number"  # 行由编号块建立（字面编号就用它）。
SOURCE_SEQUENCE = "sequence"  # 编号块误读、由序列共识按位置补回的编号（扫荡定位仍可用，仅供参考）。

# 形近字符归一化：O/o/I/l/| → 0/1；= . _ → -；B → 8（8 的常见误读，实机 `EVENT V1-OB` = 1-08）。
_CONFUSABLE = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "=": "-", ".": "-", "_": "-",
                             "B": "8"})
_ID_BODY = re.compile(r"^(?P<body>(?:0?1-\d{1,2})|(?:1\d{2})|(?:\d{1,2}))$")  # 编号体三种形态（带分隔符的前缀可补零）。
# 编号提取的判据是「块里唯一的一段数字 + 分隔符」：行首装饰每期美术都换，不做文案白名单，
# 只用下面两条结构判据区分「编号」与「含数字的噪声（计数器 / 数据 / 页面文案）」。
_DIGIT_SEGMENT = re.compile(r"\d[\d-]*\d|\d")  # 连续「数字 + 分隔符」片段（归一化后 = . _ 都已变成 -）。
_CJK_CHAR = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")  # 汉字（紧邻编号的汉字 = 页面文案，不是装饰）。


@dataclass(frozen=True)
class Block:
    """OCR 文本块（bbox 为整图坐标 x1,y1,x2,y2）。"""

    text: str
    score: float
    x1: int
    y1: int
    x2: int
    y2: int

    @classmethod
    def from_dict(cls, data):
        """从 OCR JSON（text/score/bbox）构造。"""
        x1, y1, x2, y2 = data["bbox"]  # OCR 块按最小外接矩形给出。
        return cls(text=str(data["text"]), score=float(data.get("score", 1.0)),
                   x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2))

    @property
    def center_x(self):
        """块水平中心。"""
        return (self.x1 + self.x2) / 2

    @property
    def center_y(self):
        """块垂直中心。"""
        return (self.y1 + self.y2) / 2


@dataclass(frozen=True)
class StageRef:
    """关卡行条目：编号与来源（编号不可读时由序列共识按位置补回）、行框（可直接点击）。"""

    stage_id: str | None
    box: tuple
    source: str


@dataclass(frozen=True)
class _Row:
    """内部候选行：编号读数（可能多个：见 `stage_id_candidates` 的无分隔符两可形态）+ 行框，供序列共识收敛。"""

    candidate: str | None  # 首选读数（日志与来源用）。
    box: tuple[int, int, int, int]
    source: str
    center_y: float  # 编号块中心 y（行框即围绕它切带）。
    options: tuple = ()  # 该块的全部合法读数（序列共识在这些读数里按位置取值）。
    stage_id: str | None = None  # 序列共识定下的最终编号（None = 还没定：候选行/被淘汰）。


def stage_id_candidates(text, allowed=ALLOWED_IDS):
    """从文本块提取编号候选（按序），无法提取返回空列表。

    判据是**结构**而非文案白名单：行首装饰每期美术都换（`EVENT` / `&vent` / `Bvent` / `Y 1-03` …），
    逐个登记救不完。规则：块里只能有**一段**「数字 + 分隔符」片段，且该片段匹配编号体；其余字符
    一律当装饰。无分隔符的片段（`04` / `T2` / `105`）另加三条护栏——紧邻汉字拒（`活动剧情第1部`）、
    紧邻多字母词拒（`PART1` / `ADD 2`）、片段后紧跟字母拒（`2045F`）；多段数字（`0/5` / `107.01.8` /
    游戏右下角滚动日志）与不合编号体的形态（`015` / `515`）一律拒。护栏只管明显不像编号的形态，
    剩下的取舍交给 `parse` 的序列共识（页面上真正的关卡行能连成一段序列）。

    无分隔符的两位形态里，`1x` 本身两可（`16` 可能是 1-6 丢了分隔符，也可能是第 16 关），两种读数
    按「整段当关卡号 → 版本位 + 关卡号」的顺序都给出，由序列共识按位置定（实机 09.png 的分块层只读到
    `16` 时仍要能定出 1-06）。
    """
    normalized = text.translate(_CONFUSABLE).upper()  # 形近字符归一化（O→0、=→-、.→-）。
    segments = list(_DIGIT_SEGMENT.finditer(normalized))  # 全部「数字 + 分隔符」片段。
    if len(segments) != 1:  # 没有数字，或数字分成多段 = 计数器 / 滚动日志 / 美术噪声。
        return []
    match = segments[0]  # 唯一编号段（块的其余部分是装饰，不参与判定）。
    body = match.group()  # 编号段文本（可能含内部分隔符）。
    if "-" not in body:  # 无分隔符：护栏拦「词 + 数字」与中文文案。
        before, after = normalized[:match.start()], normalized[match.end():]  # 段前 / 段后装饰。
        if _CJK_CHAR.search(before[-1:] + after[:1]):  # 紧邻汉字 = 页面文案（`活动剧情第1部`），不是装饰。
            return []
        word = re.search(r"[A-Z]+$", before.rstrip())  # 紧邻编号的字母连续段（先去掉间隔空白，`ADD 2` 也要拦）。
        if word is not None and len(word.group()) > 1:  # `PART1` / `ADD 2` 这类「词 + 数字」不是关卡编号。
            return []
        if after[:1].isalpha():  # 编号后紧跟字母（`2045F`）= 编号以外的数字（数据 / 计数器）。
            return []
    id_match = _ID_BODY.match(body)  # 三种编号体：1-06 / 106 / 06（前缀可补零成 01-06）。
    if not id_match:  # 不符合编号体（如 `107-01-8` 这类数据噪声）。
        return []
    body = id_match.group("body")  # 编号体。
    if body.startswith("01-"):  # 补零前缀归一：01-06 → 1-06。
        body = body[1:]
    if body.startswith("1-") and len(body) > 2:  # 形态 A：1-06。
        indexes = [int(body[2:])]
    elif body.startswith("1") and len(body) == 3:  # 形态 B：106（丢分隔符）。
        indexes = [int(body[1:])]
    elif body.startswith("1") and len(body) == 2:  # 形态 B/C 两可：`16` 可能是 1-6（丢分隔符）或第 16 关。
        indexes = [int(body), int(body[1:])]  # 两种读数都给出，由序列共识按位置定（实机 09.png 的 1-6）。
    else:  # 形态 C：06 / 6（丢版本位）。
        indexes = [int(body)]
    return [f"1-{index:02d}" for index in indexes if 1 <= index <= len(allowed)]  # 收敛到受限候选表。


def count_numbers(blocks, allowed=ALLOWED_IDS):
    """块集合里能解析出编号的块数（调用方据此决定是否降级到裁剪/切片 OCR）。"""
    return sum(1 for block in _as_blocks(blocks) if stage_id_candidates(block.text, allowed))


def _as_blocks(blocks):
    """把 OCR JSON dict 或 Block 统一转成 Block 列表。"""
    return [block if isinstance(block, Block) else Block.from_dict(block) for block in blocks]


def stage_edit_distance(first, second):
    """两字符串的编辑距离（纯 stdlib，用于形近抖动的模糊匹配）。"""
    if first == second:  # 完全相同。
        return 0
    if not first or not second:  # 有一侧为空。
        return len(first) or len(second)
    previous = list(range(len(second) + 1))  # 上一行动态规划值。
    for i, char_a in enumerate(first, start=1):
        current = [i]  # 每行首列。
        for j, char_b in enumerate(second, start=1):
            cost = 0 if char_a == char_b else 1  # 替换代价。
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current  # 滚动到下一行。
    return previous[-1]


def _stage_fuzzy_contains(text, keyword, max_distance=STAGE_MAX_KEYWORD_DISTANCE):
    """文本是否含关键词（容忍形近抖动）：先判完整子串，再逐等长窗口比编辑距离。"""
    text = text.lower()  # 统一小写比较。
    keyword = keyword.lower()
    if keyword in text:  # 完整子串命中。
        return True
    window = len(keyword)  # 滑动窗口长度。
    for start in range(len(text) - window + 1):  # 逐窗口比较，容忍字母级抖动。
        if stage_edit_distance(text[start:start + window], keyword) <= max_distance:
            return True
    return False


def is_stage_anchor(text, min_fragment=3):
    """是否行锚点块：`EVENT` 或其被截断的片段（低对比页读成 `eni` / `vent`）。

    编号可能被拆到同带的另一个块，锚点只用来定位「哪里是行」（列表区切片补扫用）。
    与行状态无关：行能不能打一律走界面后验（点开看详情页按钮），这里只解决 OCR 漏读编号时行在哪。
    """
    keyword = STAGE_ANCHOR_KEYWORDS[0]  # `event`。
    if _stage_fuzzy_contains(text, keyword, max_distance=1):  # 完整或近完整命中。
        return True
    fragment = text.strip().lower()  # 待判定的片段。
    if len(fragment) < min_fragment or len(fragment) >= len(keyword):  # 太短易误判，不短于关键词的已在上面判过。
        return False
    return any(stage_edit_distance(fragment, keyword[start:start + len(fragment)]) <= 1  # 与关键词等长窗口比编辑距离。
               for start in range(len(keyword) - len(fragment) + 1))


def row_pitch_fallback(scale=1.0):
    """兜底行距（像素）：标定值按分辨率缩放比缩放；缩放比无效（无帧/测试环境）时用标定值。"""
    return ROW_PITCH_AT_REF * (scale if scale and scale > 0 else 1.0)


def ocr_tile_overlap(scale=1.0):
    """相邻 OCR 分块的重叠量（像素）= OCR_TILE_OVERLAP_RATIO × 兜底行距（按分辨率缩放）。"""
    return int(row_pitch_fallback(scale) * OCR_TILE_OVERLAP_RATIO)


def ocr_upscale(box, scale=1.0):
    """把该区域喂给 OCR 引擎前的预放大倍数（1.0 = 不放大）。

    检测器只压缩超限的最长边、**不放大**小于上限的图（onnxocr det_limit_side_len=960 / limit_type=max），
    所以低于标定分辨率时得调用方自己补像素：按「把最长边填到 `OCR_TILE_LIMIT` 所需的比例」放大，上限
    `OCR_UPSCALE_MAX` 兜住成本（整屏竖条最长边是屏高，几乎放不动；按行距切的行块最长边是竖条宽，能放到
    上限——小字的等效像素数因此在各分辨率下接近）。

    标定分辨率（`scale ≥ 1`，2560x1440）下**不放大**：那时小字本来就够大，插值放大只会糊掉笔画、让
    检测器多认出噪声（实机 03.png 在 1.32 倍下多出 `1-04`/`1-05` 两个假行）。
    """
    if scale >= 1.0:  # 标定分辨率及以上：按原生尺寸送，与标定口径一致。
        return 1.0
    longest = max(int(box.width), int(box.height), 1)  # 最长边（决定检测器的缩放比例）。
    return min(OCR_UPSCALE_MAX, max(1.0, OCR_TILE_LIMIT / longest))  # 填满检测器上限，但不超上限。


def ocr_tiles(x, y, width, height, overlap, scale=1.0, rows=OCR_TILE_ROWS, limit=OCR_TILE_LIMIT):
    """OCR 区域 -> 子区域矩形列表 [(x, y, w, h)]：每块按行距取 rows 行高（封顶 limit），相邻块重叠 overlap。

    **分块不是为了绕开检测器上限**（整条也塞得进），而是为了让预放大起作用：检测器不放大输入，块的最长边
    落在**宽度**上时按上限预放大的倍数才最大（1440p 的 729 宽竖条：整条 1440 高只能 1.0 倍；切到 6 行
    720 高 → 1.32 倍；1600x900 的 456 宽竖条切 6 行 450 高 → 2.0 倍）。实机 1600x900 浅色小字页
    （02.png）整条只读出 5/8 关，切 6 行 + 2 倍预放大后 8/8。未超限且不高于目标块高时返回原矩形。
    """
    tile = min(limit, max(1, round(row_pitch_fallback(scale) * rows)))  # 目标块高（按页面行距）。
    starts = _axis_starts(y, height, tile, overlap)  # 纵向切块（列表竖条主要就是这一维超限）。
    if width <= limit:  # 宽度在限内：只按纵向切。
        return [(x, start, width, min(tile, y + height - start)) for start in starts]
    columns = _axis_starts(x, width, limit, overlap)  # 宽度也超限：两个方向都切。
    return [(column, start, min(limit, x + width - column), min(tile, y + height - start))
            for start in starts for column in columns]


def _axis_starts(start, size, chunk, overlap):
    """沿一个轴的切块起点：块长 ≤ chunk、相邻块重叠，末块收在区域末尾；不超限时只切一块。"""
    if size <= chunk:  # 不超限：整块一次。
        return [start]
    step = chunk - min(overlap, chunk // 2)  # 步长 = 块长 - 重叠；重叠封顶半个块长，防病态参数把块数刷爆。
    starts = []  # 起点序列。
    position = start  # 当前块起点。
    while position < start + size:  # 直到覆盖区域末尾。
        starts.append(position)
        if position + chunk >= start + size:  # 这一块已经够到末尾。
            break
        position += step
    return starts


# ---- 列表竖条与行窄带几何（纯计算，矩形用 Box）----

def list_strip(list_box, frame_height):
    """关卡列表竖条：横向沿用标注范围，纵向拉满整屏；无有效屏高时保守返回标注框本身。

    标注框只在一期活动上标定：横向跨期稳定，纵向逐期不同（按标注 y/高裁剪会切掉别的活动的行）。
    解析与滚动都用这一个函数的结果，保证「读哪块」与「滑哪块」同源。
    """
    if not frame_height or frame_height <= 0:  # 无有效屏高（单测/无帧）：不臆造高度。
        return list_box
    return Box(list_box.x, 0, list_box.width, frame_height,  # 同横向范围的整屏竖条。
               confidence=list_box.confidence, name=list_box.name)


def _median_gap(gaps):
    """间距列表 -> 正常间距的中位数（先剔除漏行造成的成倍间距）。"""
    regular = [gap for gap in gaps if gap <= min(gaps) * PITCH_GAP_RATIO]  # 剔除漏行造成的成倍间距。
    regular.sort()
    return regular[len(regular) // 2]  # 正常行距的中位数。


def anchor_pitch(anchors, scale):
    """行距：锚点 y 中心间距的中位数（先剔除漏行造成的成倍间距）；测不出间距时用兜底值。"""
    centers = sorted(block.center_y for block in anchors)  # 锚点按 y 排序。
    gaps = [b - a for a, b in zip(centers, centers[1:], strict=False) if b - a > 1]  # 相邻间距（错位一格的自身配对，长度天然差一）。
    if not gaps:  # 单锚点/无锚点。
        fallback = row_pitch_fallback(scale)  # 兜底行距（按分辨率缩放）。
        logger.debug(f"行距兜底：锚点 {len(anchors)} 个测不出间距，用 {fallback:.0f}px")
        return fallback
    pitch = _median_gap(gaps)  # 正常行距的中位数。
    logger.debug(f"行距估计：锚点间距 {[round(gap) for gap in gaps]} -> {pitch:.0f}px")
    return pitch


def band_height(pitch):
    """窄带高度：向上对齐到 BAND_HEIGHT_STEP，把 OCR 输入尺寸收进有限档位。"""
    return max(BAND_HEIGHT_STEP,
               int(math.ceil(max(1.0, float(pitch)) / BAND_HEIGHT_STEP)) * BAND_HEIGHT_STEP)


def band_box(list_box, center_y, pitch, frame_height):
    """列表区内以 center_y 为中心的行窄带 Box（高度量化 + 夹紧到帧内）。"""
    height = band_height(pitch)  # 量化后的高度（同一中心摆放，比实测行距略高）。
    y = int(round(center_y - height / 2))  # 保持以 center_y 为中心。
    frame_height = frame_height or 0  # 无有效分辨率时为 0，此时不夹紧。
    if frame_height > 0 and y + height > frame_height:  # 越出帧底部时上移。
        y = max(0, frame_height - height)  # 贴帧底。
    if y < 0:  # 越出帧顶部：夹到 0。
        y = 0  # 负 y 会让框架的 numpy 切片反向取值，读到画面末尾的内容。
    return Box(list_box.x, y, list_box.width, height)


def anchor_bands(anchors, list_box, frame_height, scale):
    """锚点 -> 逐行切片窄带；相邻锚点间隔过大时按中点外推补一行。"""
    pitch = anchor_pitch(anchors, scale)  # 行距。
    centers = sorted(block.center_y for block in anchors)  # 锚点中心 y。
    bands = []  # 窄带列表。
    for index, center in enumerate(centers):  # 每个锚点一条窄带。
        bands.append(band_box(list_box, center, pitch, frame_height))
        if index + 1 < len(centers):  # 与下一个锚点比较间隔。
            gap = centers[index + 1] - center
            if gap > pitch * PITCH_GAP_RATIO:  # 间隔约两倍行距 = 中间那行漏检。
                bands.append(band_box(list_box, (center + centers[index + 1]) / 2, pitch, frame_height))
    logger.debug(f"锚点切片：{len(centers)} 个锚点、行距 {pitch:.0f}px -> {len(bands)} 条窄带")  # 切片概览。
    return bands  # 可能是外推补齐的行数。


def uniform_bands(list_box, frame_height, scale):
    """无行锚点的兜底切片：按标定行距（含分辨率缩放）在列表区自上而下切等距窄带。"""
    pitch = row_pitch_fallback(scale)  # 兜底行距（2560x1440 标定值按当前缩放比缩放）。
    bands = []  # 窄带列表。
    center = list_box.y + pitch / 2  # 首条带中心：列表区顶往下半个行距（行首文字通常不在区域最顶端）。
    while center < list_box.y + list_box.height and len(bands) < UNIFORM_MAX_BANDS:  # 逐行下移直到区域底部或条数上限。
        bands.append(band_box(list_box, center, pitch, frame_height))  # 整列表宽 × 一个行距的行窄带。
        center += pitch  # 下移一行。
    logger.debug(f"均匀切片：行距 {pitch:.0f}px -> {len(bands)} 条窄带（列表区高 {list_box.height}px）")
    return bands  # 条数 = 列表区高度 ÷ 行距（封顶 UNIFORM_MAX_BANDS）。


def _estimate_pitch(number_blocks, scale):
    """行距（像素）= 编号行线间距的中位数，返回 (行距, 是否量自本页)。

    跨期活动的列表行距逐期不同，地图页的关卡点间距还能到标定值的两倍（实机 06.png 是 2.15 倍），
    故**以页面自身量到的间距为准**：量到两个以上间距（至少三个编号行线）才认为本页行距已知，调用方
    据此把「编号间隔」与「实测几何间隔」对上；只量到一个间距（可能正好跨过漏检行）或一个编号都没有，
    就退回兜底值——此时几何没有参照，只能按字面用编号（缺口交给调用方补扫）。

    不设上界：按兜底值卡上界会把地图页的真实行当噪声。下界取编号块自身的行高——比文字还矮的
    「行距」只可能是同一行的错位。
    """
    fallback = row_pitch_fallback(scale)  # 兜底行距（按分辨率缩放）。
    centers = sorted(block.center_y for block in number_blocks)  # 编号行信号。
    tolerance = fallback * PITCH_CLUSTER_RATIO  # 同带容差（同行错位远小于一个行距）。
    lines = []  # 行线列表（每线为同带信号中心）。
    for center in centers:
        if lines and center - lines[-1][-1] <= tolerance:  # 与上一条行线同带。
            lines[-1].append(center)
        else:
            lines.append([center])
    line_centers = [sum(line) / len(line) for line in lines]  # 每条行线的中心。
    gaps = [b - a for a, b in zip(line_centers, line_centers[1:], strict=False) if b - a > 1]  # 相邻行线间距（错位一格的自身配对，长度天然差一）。
    if len(gaps) < 2:  # 只有一个间距（两个编号行线）：可能正好跨过漏检行，量不出本页行距。
        return fallback, False
    pitch = _median_gap(gaps)  # 正常行距的中位数。
    text_height = sorted(block.y2 - block.y1 for block in number_blocks)[len(number_blocks) // 2]  # 编号块行高。
    if pitch < text_height:  # 比文字还矮 = 只量到同一行的错位。
        logger.debug(f"行距估计：{pitch:.0f}px 比编号块行高 {text_height}px 还小，回退兜底 {fallback:.0f}px")
        return fallback, False
    logger.debug(f"行距估计：采用本页中位数 {pitch:.0f}px（间距 {[round(gap) for gap in gaps]}，兜底 {fallback:.0f}px）")
    return pitch, True


def row_pitch(blocks, scale=1.0):
    """块集合的行距（像素）：编号行线间距的中位数，量不出来时退回兜底值（按分辨率缩放）。

    供离线探测脚本（`dev_tools/event_stage`）核对行距用；生产路径的行距在 `parse` 内部估计。
    """
    number_blocks = [block for block in _as_blocks(blocks) if stage_id_candidates(block.text)]  # 编号块。
    return _estimate_pitch(number_blocks, scale)[0]


def _number_row_box(block, pitch, list_box, center_y):
    """编号行的行框：横向取**编号块自身范围**（外扩一个块高），纵向按行距切带。

    蛇形布局左右两列各点各的，横条中心落在整列表宽的中点会点到两列之间的空白；
    直排里编号块也在行按钮上，点它同样有效——所以编号行统一用编号块 x，两种布局都点得中。
    """
    pad = block.y2 - block.y1  # 水平外扩一个块高，避免点击目标过窄。
    x1, x2 = block.x1 - pad, block.x2 + pad
    if list_box is not None:  # 收在列表区内，别点到列外。
        x1 = max(list_box[0], x1)
        x2 = min(list_box[0] + list_box[2], x2)
    return (int(x1), int(center_y - pitch / 2), int(x2), int(center_y + pitch / 2))


def _build_rows(blocks, list_box=None, allowed=ALLOWED_IDS, scale=1.0):
    """OCR 块 -> (候选行, 本页行距是否已知)：编号块按同列重复识别去重后逐块建行。

    编号可不可信不在这里取舍（不按字号/美术），交给 `_select_sequence` 的序列共识。
    去重只并「读数相同」的块：两层 OCR 对同一行读出**不同**编号时不是重复识别（实机 09.png：
    整条层把 1-6 那行读成 `16`、分块层读成 `EVENT 1-6`），两个读数都留下，由序列共识按几何裁决。
    """
    fallback = row_pitch_fallback(scale)  # 兜底行距（按分辨率缩放）：重复识别容差与行距估计同源。
    usable = [block for block in blocks if block.score >= MIN_SCORE and block.text.strip()]  # 过滤极低分噪声块。
    number_blocks = [block for block in usable if stage_id_candidates(block.text, allowed)]  # 编号块。
    pitch, measured = _estimate_pitch(number_blocks, scale)  # 行距估计 + 是否量自本页。
    logger.debug(f"行构建：可用块 {len(usable)} / 编号块 {len(number_blocks)}；行距 {pitch:.0f}px（scale {scale}）")
    rows = []  # 候选行列表。
    placed = []  # 已建行的 (中心 y, x1, x2, 读数集合)，用于同列重复识别去重。
    tolerance = min(pitch, fallback) * DUP_ROW_RATIO  # 重复识别容差：用较小行距的比例。
    for block in sorted(number_blocks, key=lambda item: (item.center_y, item.x1)):  # 逐块建行。
        candidates = stage_id_candidates(block.text, allowed)  # 编号读数（无分隔符的两可形态可能给两个）。
        candidate = candidates[0] if candidates else None
        if any(abs(block.center_y - center) <= tolerance and block.x1 < x2 and x1 < block.x2  # 同列（x 重叠）+ 纵向贴近。
               and candidates == other for center, x1, x2, other in placed):  # 且读数相同 = 同一行的重复识别。
            logger.debug(f"编号块 {block.text!r} 与已建行同列邻近且读数相同，按重复识别丢弃")  # 去重记录便于核对。
            continue
        logger.debug(f"候选行 {candidates}（{block.text!r} y={block.center_y:.0f}）")  # 逐行明细。
        rows.append(_Row(candidate=candidate, box=_number_row_box(block, pitch, list_box, block.center_y),
                         source=SOURCE_NUMBER, center_y=block.center_y, options=tuple(candidates)))
        placed.append((block.center_y, block.x1, block.x2, candidates))  # 登记该行位置供后续去重。
    rows.sort(key=lambda row: (row.box[1], row.box[3]))  # 统一按 y 排序。
    return rows, measured


def _select_sequence(rows, allowed=ALLOWED_IDS, measured=False):
    """序列共识：只留能连成一段关卡序列的行，并按位置定编号（噪声行在这里淘汰）。

    逐行按 y 递增地在受限候选里取值，四层目标函数（依次比较）：

    1. **字面编号行最多**：真实行的编号总能按字面读出来，读数对不上的解释先输；
    2. **位置偏差最小**：被选中的行必须落在序列几何上它该在的位置（相邻行实测隔几行，编号就该差几）。
       噪声（顶栏计数器、背景装饰文字）的 y 对不上任何缺行 → 留着它就要把真实行整段顶偏、位置偏差
       一下子变大，于是输给「丢弃这一行」；
    3. **保留行最多**：几何上确实有空缺、而那个位置上正好有块时，它是编号被误读的真实行（实机
      低对比页把 1-07 读成 1.2），留着比丢掉好——调用方还能点中它；
    4. **编号偏差最小**：同一位置可选多个编号时，取与字面读数最接近的那个。

    两条硬约束：改编号（把误读按位置补回来）只在**上面已经有行**时才可信——顶栏噪声总在列表最上面，
    没有「上一行」可依，只能按字面用，用不上就丢弃；编号跳的关数不能超过两行之间的空档（反过来挨得
    比行距还近是正常的：中间的行可能漏检）。本页行距量出来了（`measured`）时再加一条：几何空档也不能
    比编号间隔多出两行以上——那说明这个块的位置根本不该有关卡行（实机 01.png：列表上方三个行距处的
    美术噪声读成 `07`，按字面是 1-07，几何上对不上任何缺行）。被淘汰的行不产出条目，它留下的缺口交给
    调用方补扫（`sequence_gaps`）。
    """
    pitch = max(1.0, sorted(row.box[3] - row.box[1] for row in rows)[len(rows) // 2]) if rows else 1.0  # 行距（行框高）。
    # (上一行编号序号, 上一行下标) -> (字面行数, -位置偏差, 保留行数, -编号偏差, 路径)；显式标注是因为
    # 初值里的 None 下标与空路径会让 pyright 把键/值类型推成比实际更窄的字面类型。
    paths: dict[tuple[int, int | None], tuple[int, float, int, float, tuple]] = {(0, None): (0, 0.0, 0, 0.0, ())}
    for position, row in enumerate(rows):  # 逐行（已按 y 排序）。
        options = [index for index in (_id_index(option, allowed) for option in row.options) if index]  # 本行的合法读数。
        current = dict(paths)  # 本行判为噪声（丢弃）：上一步的状态原样保留。
        for (last, last_position), score in paths.items():  # 上一个被选中的行。
            for index in range(last + 1, len(allowed) + 1):  # 本行只能取更大的编号（列表顺序 = 解锁顺序）。
                if options and index not in options and last_position is None:  # 改编号只在上面已经有行时才可信。
                    continue  # 顶部噪声（计数器/背景文字）没有「上一行」可依，只能按字面用，用不上就丢弃。
                position_error = 0.0  # 位置偏差：编号间隔与实测行距间隔的差。
                if last_position is not None:  # 与上一行比。
                    rows_gap = (row.center_y - rows[last_position].center_y) / pitch  # 实测隔了几行。
                    if index - last > rows_gap + GRID_GAP_TOLERANCE:  # 跳的关数比空档还多 = 这两行的编号对不上。
                        continue  # 反向（编号挨得比行距还近）是正常的：中间的行可能漏检了。
                    if measured and rows_gap - (index - last) > GRID_GAP_TOLERANCE:  # 空档比编号间隔多出两行以上。
                        continue  # 这个位置不该有关卡行 = 噪声块（本页行距没量出来时不判，免得把真实行当噪声）。
                    position_error = abs(index - last - rows_gap)  # 对上了，差距并进位置偏差。
                correction = min((abs(index - option) for option in options), default=0.0)  # 与本行读数的差。
                value = (score[0] + (1 if index in options else 0),  # 字面行数（读数之一命中即算）。
                         score[1] - position_error,  # 位置偏差（越小越靠前）。
                         score[2] + 1,  # 保留行数。
                         score[3] - correction,  # 编号偏差。
                         score[4] + ((position, index),))  # 赋值路径。
                if value[:4] > current.get((index, position), (-1, -1.0, -1, -1.0, ()))[:4]:  # 目标函数更优才替换。
                    current[(index, position)] = value
        paths = current
    best = max(paths.values(), key=lambda score: score[:4])  # 全局最优那套解释。
    chosen = dict(best[4])  # 行下标 -> 编号序号。
    _recover_interior_rows(rows, chosen, pitch, allowed)  # 读数被读残的真实行：几何上落在缺行位置就补回。
    selected = []  # 保留的行。
    for position, row in enumerate(rows):  # 逐行核对。
        index = chosen.get(position)  # 本行选中的编号序号。
        if index is None:  # 接不上序列 = 噪声行。
            logger.debug(f"编号块 {row.candidate}（y={row.center_y:.0f}）接不上序列共识，按噪声丢弃")
            continue
        stage_id = allowed[index - 1]  # 最终编号。
        selected.append(_Row(candidate=row.candidate, box=row.box, options=row.options,
                             source=SOURCE_NUMBER if stage_id in row.options else SOURCE_SEQUENCE,
                             center_y=row.center_y, stage_id=stage_id))
    return _drop_stacked_rows(selected, pitch, allowed)  # 同一行位置上的多个读数只留一个。


def _recover_interior_rows(rows, chosen, pitch, allowed=ALLOWED_IDS):
    """把「被淘汰但几何上正好落在缺行位置」的候选行补回 `chosen`（原地修改；只补两侧都有已识别行的位置）。

    `_select_sequence` 第 2 层的浮点位置偏差是严格比较：整块文本被读残时（实机 08.png 的 `1-`、
    1600x900 的 02.png 的 `1- EVENT`）读数落不到任何候选值上，几何是它唯一的凭据，而行距/行框中心
    零点几行的测量抖动就足以让它输给「丢弃这一行」。这里按第 3 层的本意补一道：**夹在两个已识别行
    之间**、且几何上正好落在缺口位置的候选行，就是被误读的真实行。

    列表两端不补：那里是噪声的常驻地（顶栏计数器、背景装饰文字、锁定行的钥匙孔），它们的 y 同样
    「对不上任何缺行」——但那是没有两侧夹逼的意思，不能凭几何认领一个关卡位。
    """
    if pitch <= 0:  # 病态参数（无行距）：几何无从判断。
        return
    before_positions = sorted(chosen)  # 保留下来的行下标（升序）。
    for position, row in enumerate(rows):
        if position in chosen:  # 已选中。
            continue
        previous = [item for item in before_positions if item < position]  # 左侧最近的已识别行。
        following = [item for item in before_positions if item > position]  # 右侧最近的已识别行。
        if not previous or not following:  # 列表两端：没有两侧夹逼，不补。
            continue
        last_position, next_position = previous[-1], following[0]
        index = chosen[last_position] + round((row.center_y - rows[last_position].center_y) / pitch)  # 几何推出的编号。
        if not chosen[last_position] < index < chosen[next_position]:  # 落在已知两行之间的缺行位置才算数。
            continue
        chosen[position] = index  # 补回该行（编号来源标 sequence，见调用方）。
        logger.debug(f"编号块 {row.candidate}（y={row.center_y:.0f}）读数不落在候选值上，"
                     f"但几何落在缺行位置，按序列补回 {allowed[index - 1]}")


def _same_position(first, second, tolerance):
    """两个候选行是否落在列表的同一行上：横向重叠（同列）且纵向几乎重合。

    蛇形布局同一 y 上的左右两列 x 不重叠，不受影响。
    """
    return (first.box[0] < second.box[2] and second.box[0] < first.box[2]
            and abs(first.center_y - second.center_y) <= tolerance)


def _pick_stacked_row(group, previous, following, pitch, allowed=ALLOWED_IDS):
    """同位置的一组候选行里选一行：与前后已保留行在序列几何上最吻合的那个。

    判据 = |编号间隔 − 实测行距间隔| 之和（两侧都算），即这一组所在的列表位置上该是第几关。
    """
    scored = []  # (位置偏差, 行)。
    for row in group:
        row_index = _id_index(row.stage_id, allowed)  # 本行编号序号（不在候选表内为 None）。
        error = 0.0  # 与前后行的序列几何偏差。
        for neighbour in (previous, following):
            if neighbour is None:  # 该侧没有已保留行（列表边缘）。
                continue
            neighbour_index = _id_index(neighbour.stage_id, allowed)  # 邻行编号序号。
            if row_index is None or neighbour_index is None:  # 任一侧读不出候选编号：这一侧不参与打分。
                continue
            gap = abs(row.center_y - neighbour.center_y) / pitch  # 实测隔了几行。
            error += abs(row_index - neighbour_index - gap)  # 编号该差几关。
        scored.append((error, row))
    return min(scored, key=lambda item: item[0])[1]  # 偏差最小的那个（并列取靠上的）。


def _drop_stacked_rows(rows, pitch, allowed=ALLOWED_IDS):
    """列表的同一行位置上只留一关：两层 OCR 对同一行读出不同编号时会留下两个候选行。

    它们占同一个位置（横向重叠 + 纵向几乎重合），至多一个是对的；留下与相邻行序列几何吻合的那个
    （实机 09.png：`16` → 1-16 与 `EVENT 1-6` → 1-06 落在同一行上，1-05 就在上一行 → 留 1-06）。
    """
    if len(rows) < 2:  # 单行/空表。
        return rows
    tolerance = pitch * DUP_ROW_RATIO  # 同位置容差（行框按行距切，同一行的两个读数中心几乎重合）。
    kept = []  # 已选定的行（每组只留一个）。
    index = 0  # 当前扫描下标。
    while index < len(rows):
        group = [rows[index]]  # 同位置的一组。
        while index + 1 < len(rows) and _same_position(group[-1], rows[index + 1], tolerance):
            index += 1
            group.append(rows[index])
        if len(group) == 1:  # 该位置只有一个读数。
            kept.append(group[0])
        else:  # 同位置多个读数：按前后方的序列几何裁决。
            following = rows[index + 1] if index + 1 < len(rows) else None  # 紧随其后的下一行。
            chosen = _pick_stacked_row(group, kept[-1] if kept else None, following, pitch, allowed)
            logger.debug(f"同一行位置有 {len(group)} 个读数（{[row.candidate for row in group]}），"
                         f"按序列几何留 {chosen.stage_id}")  # 裁决记录便于核对。
            kept.append(chosen)
        index += 1
    return kept


def _id_index(stage_id, allowed):
    """编号在受限候选表里的序号（1 起），不在表内返回 None。"""
    return allowed.index(stage_id) + 1 if stage_id in allowed else None


def parse(blocks, list_box=None, allowed=ALLOWED_IDS, scale=1.0):
    """一层 OCR 块 -> 可选择关卡行列表（编号 + 行框），blocks 可为 Block 或 OCR JSON dict。

    顺序：编号块建候选行（同列重复识别去重）→ 序列共识（淘汰噪声行并按位置定编号）。
    行状态不在这里判：调用方拿块集合自己读文案（`EventTask`）。

    Args:
        scale: 当前分辨率相对 2560x1440 标定截图的缩放比（兜底行距按它缩放，无效值按标定值）。
    """
    rows, measured = _build_rows(_as_blocks(blocks), list_box=list_box, allowed=allowed, scale=scale)  # 候选行 + 本页行距是否已知。
    return [StageRef(stage_id=row.stage_id, box=row.box, source=row.source)  # 共识留下的行 = 可选关卡。
            for row in _select_sequence(rows, allowed=allowed, measured=measured)]


def _box_center_y(box):
    """行框（x1,y1,x2,y2 四元组）的纵向中心。"""
    return (box[1] + box[3]) / 2


def sequence_gaps(rows, allowed=ALLOWED_IDS):
    """已识别编号之间的缺口：返回 [(缺口区中心 y, 缺口区高度)]，供调用方补扫漏检行。

    编号序列单调递增（`_select_sequence` 保证），相邻两个已识别编号序号差 > 1 即说明中间漏行。
    缺口区取两侧已知行的中心之间（高度 = 两者间距），而不是只按行距切一条窄带：
    蛇形布局里漏掉的行可能与相邻行同带（y 相同），只有覆盖整个区间才一定扫到。空列表 = 编号连续。
    """
    numbered = [(row, _id_index(row.stage_id, allowed)) for row in rows if row.stage_id]  # 有编号的行。
    gaps = []  # 缺口区列表。
    for (first, first_index), (second, second_index) in zip(numbered, numbered[1:], strict=False):  # 相邻已识别行成对比较（错位一格，长度天然差一）。
        if first_index is None or second_index is None or second_index - first_index <= 1:  # 不是缺口。
            continue
        first_y = _box_center_y(first.box)  # 前一行中心。
        second_y = _box_center_y(second.box)  # 后一行中心。
        gaps.append(((first_y + second_y) / 2, abs(second_y - first_y)))  # 中心与高度。
    return gaps


def tail_band(rows, list_box, frame_height, allowed=ALLOWED_IDS):
    """列表末尾的补扫带（Box）；无可补区返回 None。

    `sequence_gaps` 只看得见「两个已识别编号之间」的缺口，列表两端是序列共识的盲区：最下面那行没有
    「下一行」可比，漏检后不留缺口。而列表顺序 = 解锁顺序，最下面那行正是当前进度关（唯一能推的那关），
    漏了它本轮就按「本地区推完」收工——少推一关且不报错，故末尾单独补扫一次。
    上端不补：最上面一行是更早的关卡（已通关），漏检不影响「哪一关能推」。

    与 `band_box` 的「以中心摆放、高度向上取整」不同：上沿严格钉在最后一行行框的下边缘、高度向下取整到
    `BAND_HEIGHT_STEP`——上沿落进那一行里就会把它再读一遍，重复块几何略有出入会扰动序列共识（实机
    02.png 曾因此白丢一行：重复块 score 更高、抢赢去重后行框下移 2px，1-11 那一行的位置偏差从 0 变成
    0.015 行，就输给了「丢弃这一行」）。向下取整同时保证不越过列表区底边，OCR 输入尺寸仍落在有限档位上。
    """
    numbered = [row for row in rows if row.stage_id]  # 有编号的行（`parse` 保证按 y 升序）。
    if not numbered:  # 一行都没有：末尾在哪无从判断。
        return None
    last_index = _id_index(numbered[-1].stage_id, allowed)  # 最后一行的编号序号（不在候选表内为 None）。
    if last_index is None or last_index >= len(allowed):  # 读不出候选编号 / 已经是候选表里最后一关。
        return None
    top = int(numbered[-1].box[3])  # 最后一行行框的下边缘（行框高按行距切，即该行文字带的下沿）。
    limit = list_box[1] + list_box[3]  # 列表区底边。
    height = int((limit - top) // BAND_HEIGHT_STEP) * BAND_HEIGHT_STEP  # 向下取整到量化档位。
    if height < BAND_HEIGHT_STEP:  # 下面不足一个档位：没有可补的空间。
        return None
    y = top  # 上沿钉在最后一行之下，绝不回头重复读它。
    if frame_height and frame_height > 0 and y + height > frame_height:  # 越出帧底时上移（同 band_box）。
        y = max(0, frame_height - height)
    return Box(list_box[0], y, list_box[2], height)


def find_stage(rows, stage_id, allowed=ALLOWED_IDS):
    """按编号定位关卡行（扫荡目标用）；目标不在受限候选或未找到返回 None。"""
    if stage_id not in allowed:  # 目标必须在受限候选内。
        return None
    for row in rows:  # 线性查找。
        if row.stage_id == stage_id:
            return row
    return None


# ---- OCR 读取流水线（OCR 以回调注入：整条 → 分块 → 切片降级 → 缺口补扫）----

def to_block(item, box, upscale):  # 引擎结果框（预放大后的裁剪图坐标）-> 解析层 Block（整图坐标）。
    """把 OCR 引擎返回的框映射回整图坐标（除以预放大倍数、加上裁剪区左上角）。"""
    x, y = int(box.x), int(box.y)  # 裁剪区左上角。
    return Block(text=item.name, score=item.confidence,
                 x1=x + round(item.x / upscale), y1=y + round(item.y / upscale),
                 x2=x + round((item.x + item.width) / upscale),
                 y2=y + round((item.y + item.height) / upscale))


def _ocr_blocks(ocr_region, box, scale):
    """区域 OCR -> Block 列表（整图坐标）；超长区域整条与分块两层都跑。

    两层取舍相反（实机）：

    - 02.png（浅色低对比小字，行高约 20px）：整条读全 8 个编号，原生分块只读到 5 个；
    - 08.png（深色描边大字，行高约 37px）：整条只读到 1 个编号，原生分块读全 5 个。

    两层都跑、按类别 + 邻近 y 去重合并，任一层读到就不丢行（去重见 `_dedup_blocks`）。
    """
    rects = ocr_tiles(box.x, box.y, box.width, box.height,  # 每块按行距切（见 ocr_tiles 的预放大理由）。
                      ocr_tile_overlap(scale), scale)  # 重叠一个标定行距。
    regions = [box]  # 第一层：整条区域（未超限时它就是唯一的区域）。
    if len(rects) > 1:  # 超限：再补第二层原生分块（两层缩放不同，任一层读到就不丢行）。
        regions.extend(Box(x, y, width, height, name=box.name) for x, y, width, height in rects)
    blocks = []  # 两层结果合并（重叠区的重复块由调用方去重）。
    for region in regions:
        blocks.extend(ocr_region(region))  # 空文本块由调用方的适配器丢弃。
    return blocks


def _block_kind(block):
    """块类别（去重只在同类别之间进行）：编号块按读出的编号分档，其它块一类。"""
    # 读数相同的才是同一元素的重复识别（两层 OCR 各读一遍）；读数不同的两个块要都留下，
    # 由序列共识按几何裁决谁对（实机 09.png：整条层把 1-6 那行读成 `16`、分块层读成 `EVENT 1-6`）。
    candidates = stage_id_candidates(block.text)  # 编号候选。
    return f"number:{candidates[0]}" if candidates else "other"  # 编号块 / 其它块。


def _dedup_blocks(blocks, scale):
    """多层 OCR 的重复块：同类别且纵向邻近时只保留置信度最高的一块。

    容差与解析层的同列去重同源（`DUP_ROW_RATIO` × 兜底行距），跨分辨率一致；两条路径只在「并什么」
    上不同：这里并的是两层 OCR 对同一元素的重复识别，那边并的是同一层内的同列重复。
    """
    tolerance = max(1.0, row_pitch_fallback(scale) * DUP_ROW_RATIO)  # 「同一行」的纵向容差。
    kept = []  # 已保留的（块, 类别）。
    for block in sorted(blocks, key=lambda item: item.score, reverse=True):  # 高分优先保留。
        kind = _block_kind(block)  # 当前块类别。
        if all(kind != other_kind or abs(block.center_y - other.center_y) > tolerance
               for other, other_kind in kept):  # 与同类已保留块不重叠即保留。
            kept.append((block, kind))
    return [block for block, _ in kept]  # 返回去重后的块（顺序不敏感，解析层会排序）。


def _stage_blocks(ocr_region, list_box, frame_height, scale, notes):
    """列表区 OCR；编号读不全时降级切片补扫（有锚点按锚点切，无锚点按标定行距均匀切）并去重。"""
    blocks = _ocr_blocks(ocr_region, list_box, scale)  # 第一层：列表区（整屏竖条）OCR。
    anchors = [block for block in blocks if is_stage_anchor(block.text)
               and not stage_id_candidates(block.text)]  # 行锚点（含 eni/vent 残片）。
    numbers = count_numbers(blocks)  # 编号块数。
    logger.debug(f"列表区 OCR {len(blocks)} 块（编号 {numbers} 个、锚点 {len(anchors)} 个）："
                 f"{[block.text for block in blocks]}")
    notes.append(f"列表区 OCR {len(blocks)} 块（编号 {numbers} 个、锚点 {len(anchors)} 个）")  # 解析规模：空结果时靠它定位是漏检还是页面没就绪。
    if numbers and numbers >= len(anchors):  # 读到编号且不比锚点少 = 无需降级（普通页多为「有编号、无锚点」）。
        return _dedup_blocks(blocks, scale)  # 整条 + 分块两层结果在这里合并去重。
    if anchors:  # 有锚点：按锚点 y 逐行切片（低对比页里锚点是唯一可靠的行定位信号）。
        bands = anchor_bands(anchors, list_box, frame_height, scale)  # 逐行窄带（间距过大时按中点外推补条）。
        notes.append(f"编号块 {numbers} 个 < 锚点 {len(anchors)} 个，按行锚点切片补扫")  # 记录降级原因。
    else:  # 连行锚点都没有（行首文案换成了非 EVENT 家族，或整行是图形）：按标定行距均匀切片补扫。
        bands = uniform_bands(list_box, frame_height, scale)  # 均匀窄带。
        notes.append(f"编号块 {numbers} 个且无行锚点，按标定行距均匀切片补扫 {len(bands)} 条")  # 记录降级原因。
    for band in bands:  # 逐行切片 OCR（第三层）。
        blocks.extend(_ocr_blocks(ocr_region, band, scale))
    merged = _dedup_blocks(blocks, scale)  # 合并两层结果并去重。
    logger.debug(f"切片补扫去重：{len(blocks)} -> {len(merged)} 块：{[block.text for block in merged]}")
    return merged


def _parse_rows(ocr_region, box, blocks, frame_height, scale, notes):
    """解析成行条目，并按编号序列缺口 + 列表末尾补扫缺失行后重解析（只补一轮）。"""
    list_rect = (box.x, box.y, box.width, box.height)  # 解析层用的列表区矩形。
    rows = parse(blocks, list_box=list_rect, scale=scale)  # 首次解析（兜底行距按分辨率缩放）。
    bands = [band_box(box, center_y, height, frame_height)  # 已识别编号之间的缺口（中间漏行的位置估计）。
             for center_y, height in sequence_gaps(rows)]
    tail = tail_band(rows, list_rect, frame_height)  # 列表末尾：序列共识看不见的盲区，最下面那行是最可能漏的进度关。
    if tail is not None:  # 末尾有空间：一起补扫（没读到新块时会在下面提前返回，不额外重解析）。
        bands.append(tail)
    if not bands:  # 编号连续且末尾无可补区。
        return rows  # 无需补扫。
    before = len(blocks)  # 补扫前的块数（用于判断补扫是否真的读到新块）。
    notes.append(f"缺失行补扫 {len(bands)} 处")  # 记录补扫原因。
    for band in bands:  # 逐个补扫区（取整列表宽度，覆盖两侧/底边之间，蛇形同带的行也能扫到）。
        blocks.extend(_ocr_blocks(ocr_region, band, scale))
    if len(blocks) == before:  # 补扫没读到新块：解析输入没变，省掉一次去重 + 重解析（末尾补扫多数时候是这种）。
        logger.debug("缺失行补扫没有新块，跳过重解析")
        return rows
    repaired = parse(_dedup_blocks(blocks, scale), list_box=list_rect,  # 合并去重后重解析。
                     scale=scale)
    logger.debug(f"缺口补扫：{len(rows)} -> {len(repaired)} 行")  # 补扫效果便于核对。
    return repaired


def read_rows(ocr_region, list_box, frame_height, scale):
    """关卡列表区 -> (可选关卡行, 策略轨迹)：分层 OCR → 切片降级 → 去重 → 解析 → 缺口补扫。

    Args:
        ocr_region: 区域 Box -> Block 列表（调用方把框架 OCR 的返回转成 Block；空文本块自行丢弃）。
        list_box: 关卡列表区（横向已定、纵向拉满整屏，见 `list_strip`）。
        frame_height: 当前帧高（窄带夹紧与跨层去重容差按它算；0 = 无有效分辨率）。
        scale: 当前分辨率相对 2560x1440 标定截图的缩放比（兜底行距按它缩放）。

    Returns:
        (rows, notes)：`rows` 为解析出的可选关卡行；`notes` 是策略轨迹（走了哪条降级切片/补扫路径），
        由调用方记日志，也可在测试里断言策略选择。
    """
    notes = []  # 策略轨迹（在下面逐层产生，由调用方呈现）。
    blocks = _stage_blocks(ocr_region, list_box, frame_height, scale, notes)  # 两级 OCR 块 + 切片降级。
    rows = _parse_rows(ocr_region, list_box, blocks, frame_height, scale, notes)  # 解析候选行 + 序列缺口修复。
    return rows, notes
