"""活动关卡页（STAGE LIST）的 OCR 文本解析：纯逻辑，不 import ok 框架（同 `event_calendar.py` 风格）。

设计依据（交接口径）见 `dev_tools/handoff.md` §4「关卡页解析层」：判据只用文本块位置 + 语义 + 序列校验，
不使用美术特征（模板 / 颜色）；每期美术不同，OCR 会有形近抖动（O↔0、=↔-、丢分隔符）。

输入是一层 OCR 文本块（text/score/bbox），输出行条目 StageRef：
- 编号行：编号块 + 状态块（`CLEAR` / `REPEAT >>` / 锁定族）配对；编号块里紧邻编号的勾选符号 √
  （已通关的行内标记，实测被 OCR 读成 `V`）使该行默认 clear，其余默认 available；
- 锁定行：编号位被锁定文案占据（`ACCESS DENIED` 等），没有编号，stage_id 为 None。

配对规则按实测：状态文案画在所属编号行的编号块**下方**（约 0.6 倍行距处），
且两行式布局里 `EVENT` 锚点块与编号块同带 → 状态块归给「上方最近且在行距内的编号行」，
超出容差即视为独立锁定行（见 tests/TestEventStage.py 的 fixtures 断言）。

兜底行距（`ROW_PITCH_AT_REF`）不写死像素：`parse(scale=...)` 传当前分辨率相对标定截图的
缩放比，按比例缩放（状态归行容差、行框高度、状态块聚类阈值同源联动）。

三级 OCR 降级（全屏 → 列表区裁剪 → 行锚点切片）由调用方负责：本模块提供
`count_numbers` 供调用方判断是否需要降级（锚点过滤由调用方按 `is_anchor` 内联），解析本身与 OCR 层级无关。
"""

from __future__ import annotations

import logging  # 调试日志走 stdlib，不引入 ok 框架（同 event_calendar 风格）。
import re  # 编号体提取用正则（纯 stdlib）。
from dataclasses import dataclass  # 行条目与文本块的不可变结构。

logger = logging.getLogger(__name__)  # 不引入 ok 框架，日志走 stdlib。

# 受限候选表：编号只可能是这些值，误读一律收敛到最近合法值（方案 §7）。
ALLOWED_IDS = tuple(f"1-{i:02d}" for i in range(1, 17))  # 1-01 ~ 1-16（特殊活动最多 16 关；HARD 与 NORMAL 共用同一套）。

MIN_SCORE = 0.6  # 置信度下限：实测 0.612 的锁定行不可丢，阈值只用来剔除极低分噪声。
MAX_DISTANCE = 2  # 关键词模糊匹配的最大编辑距离。
ROW_PITCH_AT_REF = 120  # 行距兜底标定值（2560x1440 实测直排列约 115~120px），按分辨率缩放比缩放后使用。
STATUS_ATTACH_RATIO = 0.9  # 状态块归行容差 = 行距 × 该比例，超出即判为独立锁定行。
STATUS_ATTACH_MIN_RATIO = 0.5  # 状态必须落在编号行**下半区**（> 行距 × 该比例）才算本行状态；更近的那条是下一锁定行的文案槽。
DUP_ROW_RATIO = 0.4  # 同列编号块判「同一行的重复识别」的纵向容差（相对行距）：取小值的比例，避免并掉真实相邻行。

CLEAR_KEYWORDS = ("clear", "complete", "completed")  # 已通关文案。
CLEAR_MARK_CHARS = ("V", "✓", "√")  # 行内勾选符号（√，实测被 OCR 读成 V；normalize 后统一大写）。
REPEAT_KEYWORDS = ("repeat",)  # 可重复挑战文案（扫荡目标行）。
LOCKED_KEYWORDS = ("access", "denied", "locked")  # 锁定族文案。
ANCHOR_KEYWORDS = ("event",)  # 行锚点文案（`EVENT` 与编号同带的两行式）。

STATUS_CLEAR = "clear"  # 已通关。
STATUS_REPEAT = "repeat"  # 已通关且可重复挑战。
STATUS_LOCKED = "locked"  # 未解锁（当前进度之后）。
STATUS_AVAILABLE = "available"  # 可打（未通关且未锁）。

SOURCE_NUMBER = "number"  # 行由编号块建立。
SOURCE_LOCK = "lock"  # 行由锁定文案建立（无编号）。
SOURCE_SEQUENCE = "sequence"  # 编号块误读、按序列收敛到预期下一关。

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
    """关卡行条目：编号（不可读为 None）、行框（可直接点击）、状态与来源。"""

    stage_id: str | None
    box: tuple
    status: str
    source: str


@dataclass(frozen=True)
class _Row:
    """内部行：保留候选编号（无编号行为 None），供序列校验收敛。"""

    candidate: str | None
    box: tuple[int, int, int, int]
    status: str
    source: str
    anchor_center: float  # 归属判定用的行锚点 y（编号行取编号块中心，锁定行取文案块中心）。


def edit_distance(a, b):
    """两字符串的编辑距离（纯 stdlib 实现，用于形近抖动的模糊匹配）。"""
    if a == b:  # 完全相同。
        return 0
    if not a or not b:  # 有一侧为空。
        return len(a) or len(b)
    previous = list(range(len(b) + 1))  # 上一行动态规划值。
    for i, ca in enumerate(a, start=1):
        current = [i]  # 每行首列。
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1  # 替换代价。
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current  # 滚动到下一行。
    return previous[-1]


def fuzzy_contains(text, keyword, max_distance=MAX_DISTANCE):
    """文本是否含关键词：先子串命中，再按等长窗口容忍编辑距离（形近抖动）。"""
    text = text.lower()  # 统一小写比较。
    keyword = keyword.lower()
    if keyword in text:  # 完整子串命中。
        return True
    window = len(keyword)  # 滑动窗口长度。
    for start in range(0, len(text) - window + 1):  # 逐窗口比较，容忍字母级抖动。
        if edit_distance(text[start:start + window], keyword) <= max_distance:
            return True
    return False


def match_status(text):
    """状态文案块归类：clear / repeat / locked，都不是返回 None。"""
    if any(fuzzy_contains(text, word) for word in LOCKED_KEYWORDS):  # 锁定族优先（`ACCESS DENIED` 含两个词）。
        return STATUS_LOCKED
    if any(fuzzy_contains(text, word) for word in REPEAT_KEYWORDS):  # `REPEAT >>`。
        return STATUS_REPEAT
    if any(fuzzy_contains(text, word) for word in CLEAR_KEYWORDS):  # `CLEAR` / `COMPLETE`。
        return STATUS_CLEAR
    return None  # 非状态文案。


def has_clear_mark(text):
    """文本里是否有紧邻编号的行内勾选符号（√ = 已通关标记，实测被 OCR 读成 `V`）。"""
    normalized = text.translate(_CONFUSABLE).upper()  # 形近字符归一化，统一大小写。
    return any(char in CLEAR_MARK_CHARS and normalized[index + 1:].lstrip()[:1].isdigit()  # 勾选符号后紧跟编号。
               for index, char in enumerate(normalized))


def is_anchor(text, min_fragment=3):
    """是否行锚点块：`EVENT` 或其被截断的片段（实测低对比页会读成 `eni` / `vent`）。

    编号可能被拆到同带的另一个块，锚点只用来判断是否降级到行切片（见方案 §5）。
    """
    keyword = ANCHOR_KEYWORDS[0]  # `event`。
    if fuzzy_contains(text, keyword, max_distance=1):  # 完整或近完整命中。
        return True
    fragment = text.strip().lower()  # 待判定的片段。
    if len(fragment) < min_fragment or len(fragment) >= len(keyword):  # 太短易误判，不短于关键词的已在上面判过。
        return False
    return any(edit_distance(fragment, keyword[start:start + len(fragment)]) <= 1  # 与关键词等长窗口比编辑距离。
               for start in range(len(keyword) - len(fragment) + 1))


def stage_id_candidates(text, allowed=ALLOWED_IDS):
    """从文本块提取编号候选（按序），无法提取返回空列表。

    判据是**结构**而非文案白名单：行首装饰每期美术都换（`EVENT` / `&vent` / `Bvent` / `Y 1-03` …），
    逐个登记救不完。规则：块里只能有**一段**「数字 + 分隔符」片段，且该片段匹配编号体；其余字符
    一律当装饰。无分隔符的片段（`04` / `T2` / `105`）另加三条护栏——紧邻汉字拒（`活动剧情第1部`）、
    紧邻多字母词拒（`PART1` / `ADD 2`）、片段后紧跟字母拒（`2045F`）；多段数字（`0/5` / `107.01.8` /
    游戏右下角滚动日志）与不合编号体的形态（`015` / `515`）一律拒。
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
        index = int(body[2:])
    elif body.startswith("1") and len(body) == 3:  # 形态 B：106（丢分隔符）。
        index = int(body[1:])
    else:  # 形态 C：06 / 6（丢版本位）。
        index = int(body)
    if not 1 <= index <= len(allowed):  # 超出受限候选范围。
        return []
    return [candidate for candidate in allowed if candidate.split("-")[-1] == f"{index:02d}"]  # 唯一编号。


def count_numbers(blocks, allowed=ALLOWED_IDS):
    """块集合里能解析出编号的块数（调用方据此决定是否降级到裁剪/切片 OCR）。"""
    return sum(1 for block in _as_blocks(blocks) if stage_id_candidates(block.text, allowed))


def _as_blocks(blocks):
    """把 OCR JSON dict 或 Block 统一转成 Block 列表。"""
    return [block if isinstance(block, Block) else Block.from_dict(block) for block in blocks]


def _median_gap(centers):
    """一组 y 中心相邻间距的中位数（剔除重叠），不足两点返回 0。"""
    centers = sorted(centers)  # 按 y 排序。
    gaps = [b - a for a, b in zip(centers, centers[1:]) if b - a > 1]  # 剔除重叠的相邻间距。
    if not gaps:  # 全部重叠。
        return 0
    gaps.sort()
    return gaps[len(gaps) // 2]  # 中位数对误读块不敏感。


def row_pitch_fallback(scale=1.0):
    """兜底行距（像素）：标定值按分辨率缩放比缩放；缩放比无效（无帧/测试环境）时用标定值。"""
    return ROW_PITCH_AT_REF * (scale if scale and scale > 0 else 1.0)


def _row_pitch(number_blocks, cluster_centers, fallback):
    """行距估计：优先用编号块间距；编号块不足两块时用状态簇间距（锁定页编号少）；仍不足用兜底值。"""
    pitch = _median_gap([block.center_y for block in number_blocks])  # 编号块间距。
    if pitch <= 0:  # 编号块少于两块/全部重叠。
        pitch = _median_gap(cluster_centers)  # 退一步用状态簇间距。
    return pitch if pitch > 0 else fallback


def _row_box(blocks, pitch, list_box, center_y):
    """行框：给了列表区就横跨列表宽度、纵向按行距切分；否则取块并集上下扩半个行距。"""
    if list_box is not None:  # 列表区已知：点击落点更稳。
        return (int(list_box[0]), int(center_y - pitch / 2),
                int(list_box[0] + list_box[2]), int(center_y + pitch / 2))
    x1 = min(block.x1 for block in blocks)  # 块并集左边界。
    x2 = max(block.x2 for block in blocks)  # 块并集右边界。
    y1 = min(block.y1 for block in blocks)  # 块并集上边界。
    y2 = max(block.y2 for block in blocks)  # 块并集下边界。
    return (int(x1), int(y1 - pitch / 2), int(x2), int(y2 + pitch / 2))


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


def _cluster_status_blocks(blocks, cluster_gap):
    """状态块聚类：`ACCESS` 与 `DENIED` 是两块，纵向邻近（≤ cluster_gap）即同簇。"""
    clusters = []  # 每簇为块列表。
    for block in sorted(blocks, key=lambda item: item.center_y):  # 按 y 顺序聚类。
        if clusters and block.center_y - clusters[-1][-1].center_y <= cluster_gap:  # 与上一簇同行。
            clusters[-1].append(block)  # 并入。
        else:
            clusters.append([block])  # 新簇。
    return clusters


def _build_rows(blocks, list_box=None, allowed=ALLOWED_IDS, scale=1.0):
    """聚类成内部行：编号行（候选编号 + 默认状态）与锁定行（无编号）。"""
    fallback_pitch = row_pitch_fallback(scale)  # 兜底行距（按分辨率缩放）。
    usable = [block for block in blocks if block.score >= MIN_SCORE and block.text.strip()]  # 过滤极低分噪声块。
    number_blocks = [block for block in usable if stage_id_candidates(block.text, allowed)]  # 编号块。
    status_blocks = [block for block in usable if not stage_id_candidates(block.text, allowed)
                     and match_status(block.text)]  # 状态块。
    clusters = _cluster_status_blocks(status_blocks, fallback_pitch / 2)  # 状态簇（`ACCESS` + `DENIED` 同簇）。
    cluster_centers = [sum(block.center_y for block in cluster) / len(cluster) for cluster in clusters]  # 簇中心。
    pitch = _row_pitch(number_blocks, cluster_centers, fallback_pitch)  # 行距估计。
    logger.debug(f"行构建：可用块 {len(usable)} / 编号块 {len(number_blocks)} / 状态块 {len(status_blocks)} / "
                 f"状态簇 {len(clusters)}；行距 {pitch:.0f}px（兜底 {fallback_pitch:.0f}px，scale {scale}）")  # 聚类概览。
    rows = []  # 内部行列表。
    placed = []  # 已建编号行的 (中心 y, x1, x2)：同列纵向邻近的重复识别要并掉（否则会收敛出多余关卡）。
    tolerance = min(pitch, fallback_pitch) * DUP_ROW_RATIO  # 重复识别容差：用较小行距的比例（真实相邻行距远大于它）。
    for block in sorted(number_blocks, key=lambda item: (item.center_y, item.x1)):  # 先建立全部编号行。
        if any(abs(block.center_y - center) <= tolerance and block.x1 < x2 and x1 < block.x2  # 同列（x 重叠）+ 纵向贴近。
               for center, x1, x2 in placed):  # = 同一行的重复识别（`1-05` 与 `》1-05` 这类）。
            logger.debug(f"编号块 {block.text!r} 与已建行同列邻近，按重复识别丢弃")  # 去重记录便于核对。
            continue
        candidates = stage_id_candidates(block.text, allowed)  # 编号候选（提取逻辑保证至多一个）。
        candidate = candidates[0] if candidates else None
        status = STATUS_CLEAR if has_clear_mark(block.text) else STATUS_AVAILABLE  # 行内勾选（√ 读成 V）= 已通关。
        logger.debug(f"编号行 {candidate}（{block.text!r} y={block.center_y:.0f}）状态 {status}")  # 逐行明细便于核对。
        rows.append(_Row(candidate=candidate, box=_number_row_box(block, pitch, list_box, block.center_y),
                         status=status, source=SOURCE_NUMBER, anchor_center=block.center_y))
        placed.append((block.center_y, block.x1, block.x2))  # 登记该行位置供后续去重。
    for cluster in clusters:  # 状态簇逐个归行。
        center_y = sum(block.center_y for block in cluster) / len(cluster)  # 簇中心。
        status = match_status(" ".join(block.text for block in cluster))  # 多块拼起来判状态。
        tolerance = pitch * STATUS_ATTACH_RATIO  # 归行容差上界。
        min_gap = pitch * STATUS_ATTACH_MIN_RATIO  # 归行容差下界：状态在本行下半区才算（更近 = 下一锁定行的文案槽）。
        target = None  # 归属的编号行下标。
        best = None  # 归属的最小纵向距离。
        for index, row in enumerate(rows):  # 只在编号行的**上方**找归属（状态文案画在编号下方）。
            delta = center_y - row.anchor_center
            if 0 <= delta and (best is None or delta < best):  # 最近且在其下方。
                target, best = index, delta
        if target is not None and best is not None and min_gap < best <= tolerance:  # 落在编号行下半区 = 该行的状态。
            logger.debug(f"状态 {status} 归给 {rows[target].candidate}（间距 {best:.0f} ≤ 容差 {tolerance:.0f}）")  # 归行判定。
            row = rows[target]
            rows[target] = _Row(candidate=row.candidate, box=row.box, status=status,
                                source=row.source, anchor_center=row.anchor_center)
        else:  # 超出容差 = 锁定行（编号位被锁定文案占据）。
            logger.debug(f"状态 {status} 判为独立行（y={center_y:.0f}，最近间距 "
                         f"{best if best is not None else -1:.0f} > 容差 {tolerance:.0f}）")  # 锁定行判定。
            rows.append(_Row(candidate=None, box=_row_box(cluster, pitch, list_box, center_y),
                             status=status, source=SOURCE_LOCK, anchor_center=center_y))
    rows.sort(key=lambda row: (row.box[1], row.box[3]))  # 统一按 y 排序。
    return rows


def _resolve_sequence(rows, allowed=ALLOWED_IDS):
    """序列单调校验：编号按 y 必递增，违规/误读取受限候选里最近的合法值。"""
    resolved = []  # 输出行。
    last_index = 0  # 上一行已确定的序号（1-01 序号为 1）。
    for row in rows:  # 逐行（已按 y 排序）。
        chosen = None  # 本行选定编号。
        source = row.source  # 行来源（误读收敛时改写）。
        if row.source != SOURCE_LOCK:  # 锁定行不参与序列。
            candidate = row.candidate
            if candidate is not None:  # 编号行（提取逻辑保证单候选）。
                index = _id_index(candidate, allowed)
                if index is not None and index > last_index:  # 满足序号单调递增。
                    chosen = candidate
                elif last_index < len(allowed):  # 违规/误读：收敛到序列预期的下一关。
                    chosen = allowed[last_index]
                    source = SOURCE_SEQUENCE
                    logger.debug(f"序号收敛：{candidate} -> {chosen}（上一行序号 {last_index}）")  # 收敛记录。
            if chosen is not None:  # 记录序号供后续比较。
                last_index = _id_index(chosen, allowed) or last_index
        resolved.append(StageRef(stage_id=chosen, box=row.box, status=row.status, source=source))
    return resolved


def _id_index(stage_id, allowed):
    """编号在受限候选表里的序号（1 起），不在表内返回 None。"""
    return allowed.index(stage_id) + 1 if stage_id in allowed else None


def parse(blocks, list_box=None, allowed=ALLOWED_IDS, scale=1.0):
    """一层 OCR 块 -> 关卡行列表（聚类 + 序列校验），blocks 可为 Block 或 OCR JSON dict。

    Args:
        scale: 当前分辨率相对 2560x1440 标定截图的缩放比（兜底行距按它缩放，无效值按标定值）。
    """
    return _resolve_sequence(_build_rows(_as_blocks(blocks), list_box=list_box, allowed=allowed, scale=scale),
                             allowed=allowed)


def _box_center_y(box):
    """行框（x1,y1,x2,y2 四元组）的纵向中心。"""
    return (box[1] + box[3]) / 2


def sequence_gaps(rows, allowed=ALLOWED_IDS):
    """已识别编号之间的缺口：返回 [(缺口区中心 y, 缺口区高度)]，供调用方补扫漏检行。

    编号序列单调递增（`_resolve_sequence` 保证），相邻两个已识别编号序号差 > 1 即说明中间漏行。
    缺口区取两侧已知行的中心之间（高度 = 两者间距），而不是只按行距切一条窄带：
    蛇形布局里漏掉的行可能与相邻行同带（y 相同），只有覆盖整个区间才一定扫到。空列表 = 编号连续。
    """
    numbered = [(row, _id_index(row.stage_id, allowed)) for row in rows if row.stage_id]  # 有编号的行。
    gaps = []  # 缺口区列表。
    for (first, first_index), (second, second_index) in zip(numbered, numbered[1:]):  # 相邻已识别行成对比较。
        if first_index is None or second_index is None or second_index - first_index <= 1:  # 不是缺口。
            continue
        first_y = _box_center_y(first.box)  # 前一行中心。
        second_y = _box_center_y(second.box)  # 后一行中心。
        gaps.append(((first_y + second_y) / 2, abs(second_y - first_y)))  # 中心与高度。
    return gaps


def progress_target(rows):
    """推图目标：列表最下面的可打行（锁定段上方那一关 = 当前进度）；没有返回 None。

    门票机制下一次只解锁一关，页面常是一半已通关、一半锁定；从下往上取可避免
    已通关行状态漏检（CLEAR 文字与勾选 √ 都没读到）时误把前面的行当成目标。
    """
    available = [row for row in rows if row.status == STATUS_AVAILABLE and row.stage_id]  # 可打行（列表顺序）。
    target = available[-1] if available else None  # rows 顺序即列表顺序，最后一条 = 最下面那行。
    logger.info(f"推图目标：{target.stage_id if target else None}（可打 {len(available)} 行）")  # 目标选择记录。
    logger.debug(f"目标选择依据：{[(row.stage_id, row.status, row.source) for row in rows]}")  # 全部行状态便于排查误选。
    return target


def find_stage(rows, stage_id, allowed=ALLOWED_IDS):
    """按编号定位关卡行（扫荡目标用）；目标不在受限候选或未找到返回 None。"""
    if stage_id not in allowed:  # 目标必须在受限候选内。
        return None
    for row in rows:  # 线性查找。
        if row.stage_id == stage_id:
            return row
    return None
