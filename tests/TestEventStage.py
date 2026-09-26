# pyright: reportOptionalMemberAccess=false, reportOptionalSubscript=false
# 仅本测试文件：mock 出来的 find_one/load_snapshot 返回值已知非空，直接取属性；src/ 仍由这两条规则把关。
"""`src/event_stage.py` 的离线解析测试。

fixtures 是真实活动关卡页截图跑项目同款 onnxocr 的产物（tests/fixtures/event_stage/*.json，由
dev_tools/event_stage/_make_fixtures.py 生成），测试只跑解析不跑模型，完全确定性。截图本体是开发期的
实机素材，不入仓；fixtures 的 bbox 已换算回整图坐标。

每个 fixture 存同一帧的两层 OCR：`full` = 整图一次 OCR；`list` = 关卡列表区的两级 OCR
流水线产物（横向取 coco 标注、纵向拉满整屏，「整条 + 原生分块」两层去重，编号读不全时再按锚点/标定
行距切片补扫，最后按编号序列缺口补扫一轮），与 `event_stage.read_rows` 同口径（该流水线现由本模块提供）。

本模块只筛「可选择的关卡行」：这里的期望值一律是编号与行框，不含任何行状态（状态与可用性判定
在 EventTask 侧，见 tests/TestEventTask.py）。
"""

import json
import os
import unittest
from unittest.mock import patch

from ok.feature.Box import Box

from src import event_stage as es

FIXTURES = os.path.join('tests', 'fixtures', 'event_stage')


def _parse(name, level):
    """读 fixtures 并解析某一层 OCR 结果：scale 按 fixture 自身分辨率算（与 EventTask 调用口径一致）。"""
    with open(os.path.join(FIXTURES, f'{name}.json'), encoding='utf-8') as fh:
        data = json.load(fh)
    scale = min(data['size'][0] / 2560, data['size'][1] / 1440)  # 分辨率缩放比（标定基准 2560x1440）。
    return es.parse(data[level], list_box=data['list_box'], scale=scale), data


def _block(text, x=1000, y=400, width=200, height=40, score=0.95):
    """构造一个 OCR 文本块（bbox 按左上角 + 尺寸给出）。"""
    return es.Block(text=text, score=score, x1=x, y1=y, x2=x + width, y2=y + height)


class TestEventStageFixtures(unittest.TestCase):
    """真实截图 OCR 产物上的解析：列表区两级流水线筛出的可选关卡行，以及整屏层对特殊页面的表现。"""

    # 各截图列表区应筛出的可选关卡编号（与 dev_tools/event_stage/_probe.py 的期望表一致，实机核对过）。
    LIST_EXPECTED = {
        '01': [f'1-{index:02d}' for index in range(8, 13)],  # 全通页：1-08 ~ 1-12。
        '02': [f'1-{index:02d}' for index in range(5, 13)],  # 全通页：1-05 ~ 1-12（浅色低对比小字）。
        '03': [f'1-{index:02d}' for index in range(6, 13)],  # 全通页：1-06 ~ 1-12。
        '04': ['1-01'],  # 聊天页（非关卡页）：分享文本里的编号也会被当成关卡行（页面语义由界面闸门挡）。
        '05': ['1-01', '1-02'],  # 地图页：锁定行没有编号。
        '06': ['1-01', '1-02', '1-03'],
        '07': ['1-01'],  # 锁定页：编号位被 ACCESS/DENIED 占据，只有首关带装饰箭头的编号。
        '08': [f'1-{index:02d}' for index in range(5, 10)],  # 1-05 ~ 1-09（1-09 是当前进度关）。
        '09': [f'1-{index:02d}' for index in range(3, 7)],  # 实机 0.78 截图：1-03 ~ 1-06（蛇形左右两列）。
    }

    def test_list_layer_yields_selectable_rows(self):
        for name, expected in self.LIST_EXPECTED.items():
            with self.subTest(fixture=name):
                rows, data = _parse(name, 'list')
                self.assertEqual(expected, [row.stage_id for row in rows])
                list_box = data['list_box']
                for row in rows:  # 行框横向收在列表区内，点击不会落空。
                    self.assertGreaterEqual(row.box[0], list_box[0])
                    self.assertLessEqual(row.box[2], list_box[0] + list_box[2])

    def test_rows_stay_within_allowed_candidate_set(self):
        # 解析结果只允许落在受限候选表内（表外一律判空）：全屏层噪声再多也不越界。
        for name in self.LIST_EXPECTED:
            with self.subTest(fixture=name):
                rows, _ = _parse(name, 'full')
                for row in rows:
                    self.assertIn(row.stage_id, es.ALLOWED_IDS + (None,))

    def test_full_layer_reads_chat_share_text(self):
        # 整屏层同样把聊天分享文本 `Event stage 1-1` 读成编号：解析层不看页面语义。
        rows, _ = _parse('04', 'full')
        self.assertEqual(['1-01'], [row.stage_id for row in rows])

    def test_locked_page_needs_list_pipeline_for_arrow_prefixed_number(self):
        # 锁定页整屏层读不到编号（编号位是 ACCESS/DENIED），列表区锚点切片补扫才读出首关的 `》1-01`。
        rows, _ = _parse('07', 'full')
        self.assertEqual([], [row.stage_id for row in rows])
        rows, _ = _parse('07', 'list')
        self.assertEqual(['1-01'], [row.stage_id for row in rows])

    def test_low_contrast_rows_only_readable_from_list_pipeline(self):
        # 浅色低对比小字：整屏一次 OCR 一个编号都读不出，列表区两级流水线必须把 8 行全救回。
        rows, _ = _parse('02', 'full')
        self.assertEqual([], [row.stage_id for row in rows])
        rows, _ = _parse('02', 'list')
        self.assertEqual(self.LIST_EXPECTED['02'], [row.stage_id for row in rows])

    def test_truncated_number_is_recovered_by_sequence_geometry(self):
        # 深色描边大字页把 1-07 整块读成 `1-`（只剩前缀）：读数落不到任何候选值上，几何是唯一凭据，
        # 按序列几何补回 1-07。整屏层与列表区两级流水线都能把 5 关读全（此前整屏层会白丢这一行）。
        for level in ('full', 'list'):
            with self.subTest(level=level):
                rows, _ = _parse('08', level)
                self.assertEqual(self.LIST_EXPECTED['08'], [row.stage_id for row in rows])

    def test_snake_layout_rows_stay_in_their_columns(self):
        # 蛇形两列：行框取各自编号块范围而不是整列表宽，否则点击会落在两列之间。
        rows, data = _parse('09', 'list')
        self.assertEqual(self.LIST_EXPECTED['09'], [row.stage_id for row in rows])
        for row in rows:
            self.assertLess(row.box[2] - row.box[0], data['list_box'][2] / 2)

    def test_find_stage_locates_sweep_target(self):
        # 扫荡目标定位：按编号找到行（供点该行 → 关卡详情页快速战斗）；表外编号直接判空。
        rows, _ = _parse('01', 'list')
        self.assertEqual('1-10', es.find_stage(rows, '1-10').stage_id)
        self.assertIsNone(es.find_stage(rows, '2-01'))
        self.assertIsNone(es.find_stage(rows, '1-01'))


class TestEventStageBlocks(unittest.TestCase):
    """纯函数与合成变体：编号变体、噪声拒绝、蛇形去重、序列共识。"""

    def test_stage_id_variants(self):
        cases = {
            'EVENT V1-06': ['1-06'],
            'EVENT V1O6': ['1-06'],  # O 读成 0。
            'EVENT V1-O8': ['1-08'],  # 多一个分隔符。
            'EVENT V 1=1O': ['1-10'],  # = 当分隔符 + 尾位 O。
            'EVENT 1-1': ['1-01'],
            'EVENT T2': ['1-02'],
            'X-1-6 EVENT': ['1-06'],  # 编号在前。
            '1-11': ['1-11'],  # 独立编号块。
            'H1-06': ['1-06'],  # HARD 前缀只作装饰字母剔除，编号与 NORMAL 同一套。
            '01-06': ['1-06'],  # 前缀补零。
            'EVENT V1-16': ['1-16'],  # 特殊活动最多 16 关。
            'EVENT V1-OB': ['1-08'],  # 尾位 8 读成 B（实机日志：EVENT V1-OB 整行曾因 B 被丢弃）。
            '&VENT 1-1': ['1-01'],  # 锚点形近误读（实机小活动日志：整块 `&vent 1-1` 曾因残留 &/E/N 被丢弃）。
            '&VENT1-1': ['1-01'],  # 同上，锚点与编号无空格粘连。
            'Y1-03': ['1-03'],  # 勾选 √ 被读成 Y（实机日志 `Y1-03`/`Y 1-10`，旧白名单不认识 Y 会整行丢弃）。
            'Y 1-10': ['1-10'],  # 同上（Y 与编号之间有空格）。
            '》1-01': ['1-01'],  # 装饰箭头前缀（旧白名单因 `》` 丢弃整块）。
            '-07': ['1-07'],  # 丢前缀的独立编号块。
            '04': ['1-04'],  # 丢版本位的两位形态。
            '16': ['1-16', '1-06'],  # 无分隔符两位且首位是 1：两可（第 16 关 / 1-6 丢分隔符），按序都给。
            '11': ['1-11', '1-01'],  # 同上：版本位与关卡位都合法。
            'EVENT Y': [],  # 只有锚点 + 装饰字母：不是编号块。
            '116': ['1-16'],  # 丢分隔符 + 两位数关卡号。
            '1-17': [],  # 超出候选上限。
        }
        for text, expected in cases.items():
            self.assertEqual(expected, es.stage_id_candidates(text), text)

    def test_small_event_list_keeps_first_stage_when_anchor_misread(self):
        # 实机小活动日志（17:11）：整块 `&vent 1-1` 被丢弃 → 只剩锁定行 → 推图判「无可打的剧情关卡」。
        # 块文本与列表区坐标照抄日志，锁定行框取日志里的三行（y 454/572/690）。
        blocks = [
            _block('tage List', y=250, height=20),  # 表头（噪声）。
            _block('Q、加成奖励妮姬', y=280, height=30),  # 页面标题。
            _block('&vent 1-1', y=330, height=30),  # 锚点形近误读 + 编号同块。
            _block('+ + Access Denied ++', y=505, height=20),
            _block('++Access Denied + +', y=623, height=20),
            _block('+ +  Alccess Denied ++', y=741, height=20),
        ]
        rows = es.parse(blocks, list_box=(681, 245, 522, 621))
        self.assertEqual(['1-01'], [row.stage_id for row in rows])  # 首关必须能被选中去推图。

    def test_sequence_gaps_detects_missing_row(self):
        # 1-08 漏检：靠两侧已识别编号（1-07 → 1-09）推断中间有行，缺口区取两行中心之间。
        rows = es.parse([_block('1-06', y=400), _block('1-07', y=520), _block('1-09', y=760)])
        gaps = es.sequence_gaps(rows)
        self.assertEqual(1, len(gaps))
        self.assertAlmostEqual(660, gaps[0][0], delta=1)  # 中心 = 1-07 中心(540) 与 1-09 中心(780) 的中点。
        self.assertAlmostEqual(240, gaps[0][1], delta=1)  # 高度 = 两行间距（覆盖整个区间，蛇形同带也扫得到）。

    def test_sequence_gaps_handles_multiple_missing_rows(self):
        # 跨度 3（1-06 → 1-09）→ 单个缺口区一次扫掉中间两行。
        rows = es.parse([_block('1-06', y=400), _block('1-09', y=880)])
        gaps = es.sequence_gaps(rows)
        self.assertEqual(1, len(gaps))
        self.assertAlmostEqual(660, gaps[0][0], delta=1)
        self.assertAlmostEqual(480, gaps[0][1], delta=1)

    def test_sequence_gaps_empty_when_continuous(self):
        rows = es.parse([_block('1-06', y=400), _block('1-07', y=520), _block('1-08', y=640)])
        self.assertEqual([], es.sequence_gaps(rows))

    def test_candidate_set_covers_sixteen_stages(self):
        # 候选表 1-01 ~ 1-16（特殊活动最多 16 关），不再有 HARD 专属的 H1 候选。
        self.assertEqual(16, len(es.ALLOWED_IDS))
        self.assertEqual('1-16', es.ALLOWED_IDS[-1])
        self.assertEqual(['1-16'], es.stage_id_candidates('H1-16'))  # HARD 编号归一化到同一套。

    def test_snake_number_rows_narrow_to_own_column(self):
        # 蛇形：相邻编号分居左右两列（同一 y、不同 x），行框取各自编号块 x，互不重叠、不横跨整列表宽。
        rows = es.parse([_block('1-03', x=1000, y=400), _block('1-04', x=1400, y=400)])
        left, right = rows[0], rows[1]
        self.assertEqual('1-03', left.stage_id)
        self.assertEqual('1-04', right.stage_id)
        self.assertLess(left.box[2], right.box[0])  # 左列行框在右列左侧。
        self.assertGreater(left.box[0], 1000 - 50)  # 仍是编号块邻域，不是整屏宽。

    def test_conflicting_readings_of_one_row_keep_the_sequence_id(self):
        # 实机 09.png（0.78 蛇形）：两层 OCR 把 1-6 那行读成 `16`（→1-16）与 `EVENT 1-6`（→1-06），
        # 落在同一行位置上。读数不同 = 不是重复识别，两个都留，由序列几何裁决（上一行是 1-05 → 该位置是 1-06）。
        for fragment_y in (545, 575):  # 碎片读数在上/在下两种顺序都要裁决成 1-06。
            blocks = [_block('EVENT 1-3', x=1010, y=238, width=161, height=40),
                      _block('EVENT1-4', x=848, y=338, width=160, height=40),
                      _block('EVENT1-5', x=1016, y=438, width=152, height=40),
                      _block('16', x=1010, y=fragment_y, width=60, height=40),
                      _block('EVENT 1-6', x=846, y=545, width=172, height=40)]
            rows = es.parse(blocks, list_box=(741, 0, 569, 1122), scale=0.779)
            self.assertEqual(['1-03', '1-04', '1-05', '1-06'], [row.stage_id for row in rows],
                             f'碎片 y={fragment_y}')

    def test_ambiguous_two_digit_reading_resolves_by_position(self):
        # 整条层把 1-6 那行读成 `16`（分块层也没读全时只剩这一个读数）：`16` 是「第 16 关」还是
        # 「1-6 丢分隔符」两可，按位置定——上一行是 1-05 → 该位置就是 1-06。
        rows = es.parse([_block('EVENT 1-3', x=1010, y=238, width=161, height=40),
                         _block('EVENT1-4', x=848, y=338, width=160, height=40),
                         _block('EVENT1-5', x=1016, y=438, width=152, height=40),
                         _block('16', x=846, y=545, width=172, height=40)],
                        list_box=(741, 0, 569, 1122), scale=0.779)
        self.assertEqual(['1-03', '1-04', '1-05', '1-06'], [row.stage_id for row in rows])

    def test_stacked_readings_leave_one_row_per_list_position(self):
        # 同一行位置上两个读数都接得上序列（相邻编号）时，也只能留一关：按与上一行的序列几何最吻合的那个。
        rows = es.parse([_block('1-04', y=400), _block('1-05', x=1000, y=520), _block('1-06', x=1400, y=520)])
        self.assertEqual(['1-04', '1-05', '1-06'], [row.stage_id for row in rows])  # 左右两列（x 不重叠）= 两关，都留。
        rows = es.parse([_block('1-04', y=400), _block('1-05', y=520), _block('1-06', x=1010, y=522)])
        self.assertEqual(['1-04', '1-05'], [row.stage_id for row in rows])  # 同一列同一点 = 一关。

    def test_duplicate_number_blocks_merge_into_one_row(self):
        # 同一行的重复识别（`1-05` 与带装饰箭头的 `》1-05`）不能收敛成两行：否则会凭空多出一关。
        rows = es.parse([_block('1-04', y=280), _block('1-05', y=400), _block('》1-05', x=1010, y=402)])
        self.assertEqual(['1-04', '1-05'], [row.stage_id for row in rows])

    def test_snake_layout_columns_are_not_merged(self):
        # 蛇形布局：同一 y 上左右两列是两关（x 不重叠）→ 不能被去重并掉。
        rows = es.parse([_block('1-04', x=1000, y=400), _block('1-05', x=1400, y=400)])
        self.assertEqual(['1-04', '1-05'], [row.stage_id for row in rows])

    def test_anchor_block_alone_is_not_a_row(self):
        # 两行式布局：`EVENT` 锚点块 + 编号块同带 = 一行；锚点块自身不产出条目（锚点由调用方判，见 EventTask）。
        rows = es.parse([_block('EVENT', y=400), _block('1-08', y=436)])
        self.assertEqual(['1-08'], [row.stage_id for row in rows])

    def test_noise_texts_are_not_stage_ids(self):
        # 美术噪声/计数器/滚动日志不能当编号：否则会凭空造出关卡行（0/5 曾被当成 1-05）。
        for text in ('PART1', '活动剧情第1部', '0/5', '107.01.8', '-/-', 'REPEAT >>', 'STAGE LIST', '加成奖励妮姬',
                     'ADD 2', '5/5', '015', '515', '0:', '2045F', '-Rt 003krz-2.0s', '2937628F. RtD2Dkr2-22s',
                     'Updated Path data', 'Active System Log', 'CAUTION : Sign', 'PROTOCOL.ux', 'EVENI'):
            self.assertEqual([], es.stage_id_candidates(text), text)
        self.assertEqual(0, es.count_numbers([_block(text) for text in ('PART1', '0/5', 'ADD 2')]))

    def test_noise_blocks_are_not_rows(self):
        # 实机 05 场景的噪声块：挂锁钥匙孔读成 `7`（落在锁定行带里）、顶栏加成奖励计数器读成 `-7-`、
        # 背景终端装饰文字读成 `PI`（与真实行撞号）。三条都靠序列共识淘汰，不用字号/颜色那类判据。
        blocks = [
            _block('-7-', x=1553, y=269, width=65, height=33, score=0.63),  # 顶栏计数器（实机整条 OCR 读数）→ 1-07。
            _block('PI', x=1660, y=227, width=18, height=21, score=0.83),  # 背景装饰文字 → 1-01，与真实首关撞号。
            _block('EVENT 1-1', x=1332, y=344, width=123, height=39, score=0.98),  # 真实 1-01。
            _block('REPEAT》', x=1250, y=386, width=90, height=24, score=0.91),  # 1-01 的重复挑战标记（不是编号）。
            _block('EVENT 1-2', x=1124, y=469, width=129, height=43, score=0.93),  # 真实 1-02（当前进度关）。
            _block('7', x=1292, y=613, width=26, height=18, score=0.64),  # 挂锁钥匙孔 → 1-07。
            _block('Access', x=1140, y=610, width=116, height=30, score=0.96),  # 锁定行文案（钥匙孔就在这一行带里）。
            _block('Denied', x=1300, y=608, width=120, height=32, score=1.0),
        ]
        rows = es.parse(blocks, list_box=(950, 0, 729, 1440))
        self.assertEqual(['1-01', '1-02'], [row.stage_id for row in rows])

    def test_sequence_snaps_misread_to_expected_next(self):
        # 序列单调：`1-6, 1.2, 1-8` 里的误读 1.2 收敛为 1-07（受限候选 + 顺序约束）。
        blocks = [_block('1-6', y=400), _block('1.2', y=520), _block('1-8', y=640)]
        rows = es.parse(blocks)
        self.assertEqual(['1-06', '1-07', '1-08'], [row.stage_id for row in rows])
        self.assertEqual(es.SOURCE_SEQUENCE, rows[1].source)

    def test_leading_noise_cannot_shift_the_sequence(self):
        # 顶栏计数器落在真实首关上方时，不能把真实行整体顶偏：改编号只在上面已经有行时才可信。
        blocks = [_block('-1-', x=1553, y=269, width=65, height=33, score=0.81),  # 计数器 → 1-01（真实 1-01 之上）。
                  _block('1-05', y=420), _block('1-06', y=540), _block('1-07', y=660)]
        rows = es.parse(blocks)
        self.assertEqual(['1-05', '1-06', '1-07'], [row.stage_id for row in rows])

    def test_row_pitch_follows_resolution_scale(self):
        # 兜底行距不是固定像素：按分辨率缩放比缩放；缩放比无效（无帧/测试环境）时用标定值。
        self.assertEqual(es.ROW_PITCH_AT_REF, es.row_pitch_fallback(1.0))
        self.assertAlmostEqual(es.ROW_PITCH_AT_REF * 0.75, es.row_pitch_fallback(0.75))  # 1080p = 1440p 的 0.75。
        self.assertEqual(es.ROW_PITCH_AT_REF, es.row_pitch_fallback(0.0))

    def test_row_pitch_measures_number_line_gaps(self):
        # 行距取编号行线间距的中位数（行框高度按它切）；只有一个编号时退回兜底值。
        blocks = [_block('1-04', y=400), _block('1-05', y=580), _block('1-06', y=760)]
        self.assertAlmostEqual(180, es.row_pitch(blocks), delta=1)
        self.assertAlmostEqual(es.ROW_PITCH_AT_REF, es.row_pitch([_block('1-04', y=400)]))
        self.assertAlmostEqual(es.ROW_PITCH_AT_REF * 0.5, es.row_pitch([_block('1-04', y=400)], scale=0.5))


class TestEventStageLayout(unittest.TestCase):
    """列表竖条、行距与窄带切片的纯几何（原 TestEventTask 的对应用例迁入）。"""

    LIST_BOX = Box(950, 342, 729, 867, confidence=1, name='list')

    def test_list_strip_expands_to_full_height(self):
        # 标注框纵向逐期不同：解析与滚动都用整屏竖条，横向沿用标注范围。
        box = es.list_strip(self.LIST_BOX, 1440)
        self.assertEqual((950, 0, 729, 1440), (box.x, box.y, box.width, box.height))
        self.assertEqual(self.LIST_BOX.name, box.name)

    def test_list_strip_keeps_annotation_without_height(self):
        # 无有效屏高（无帧/单测）：保守用标注框，不臆造整屏高度。
        self.assertEqual(self.LIST_BOX, es.list_strip(self.LIST_BOX, 0))

    def test_band_height_quantizes_to_fixed_steps(self):
        # 窄带高度按 BAND_HEIGHT_STEP 向上取整：实测行距/缺口高度的漂移不再产生新的 OCR 输入尺寸。
        self.assertEqual(32, es.BAND_HEIGHT_STEP)
        self.assertEqual(32, es.band_height(1))  # 非正/极小值兜底一个档位。
        self.assertEqual(64, es.band_height(33))
        self.assertEqual(64, es.band_height(64))  # 正好落在档位上不额外加一档。
        self.assertEqual(96, es.band_height(88))  # 实测行距 88 → 96。
        self.assertEqual(es.band_height(89), es.band_height(88))  # 相邻行距落到同一档位。
        self.assertEqual(0, es.band_height(200) % es.BAND_HEIGHT_STEP)

    def test_band_box_clamps_into_frame(self):
        # 顶部/底部越界的窄带夹回帧内：负 y 会让框架的 numpy 切片反向取到画面末尾的内容。
        list_box = Box(950, 0, 729, 1124, confidence=1, name='list')
        top = es.band_box(list_box, 10, 88, 1000)  # 中心贴近帧顶。
        bottom = es.band_box(list_box, 990, 88, 1000)  # 中心贴近帧底。
        self.assertEqual(0, top.y)
        self.assertEqual(96, top.height)
        self.assertEqual(96, bottom.height)
        self.assertEqual(1000 - 96, bottom.y)  # 贴帧底，不越过下边界。
        self.assertEqual((list_box.x, list_box.width), (top.x, top.width))

    def test_anchor_bands_extrapolate_missing_row(self):
        # 相邻锚点间隔约两倍行距：中间那行漏检，按中点外推补一条窄带。
        anchors = [es.Block(text='eni', score=0.9, x1=1200, y1=400, x2=1230, y2=420),
                   es.Block(text='eni', score=0.9, x1=1200, y1=520, x2=1230, y2=540),
                   es.Block(text='vent', score=0.9, x1=1200, y1=760, x2=1240, y2=780)]
        bands = es.anchor_bands(anchors, self.LIST_BOX, 1440, 1.0)
        centers = [band.y + band.height / 2 for band in bands]
        self.assertEqual(4, len(bands))  # 3 个锚点 + 外推 1 行。
        self.assertIn(650, centers)  # 410/530 之间的行距为 120；530 与 770 之间按中点 650 外推。

    def test_uniform_bands_covers_full_strip_within_cap(self):
        # 无锚点兜底：覆盖整屏竖条（1440 / 120 = 12 行 × 兜底行距），条数在 UNIFORM_MAX_BANDS 之内。
        bands = es.uniform_bands(es.list_strip(self.LIST_BOX, 1440), 1440, 1.0)
        self.assertEqual(12, len(bands))  # 末段必须切到（上限只防病态参数，见 UNIFORM_MAX_BANDS）。
        self.assertEqual(es.band_height(es.ROW_PITCH_AT_REF), bands[0].height)

    def test_anchor_pitch_falls_back_without_gaps(self):
        # 锚点不足两个时量不出间距，退回按分辨率缩放的标定行距。
        self.assertAlmostEqual(es.ROW_PITCH_AT_REF, es.anchor_pitch([], 1.0))
        single = es.Block(text='EVENT', score=0.9, x1=1200, y1=400, x2=1300, y2=430)
        self.assertAlmostEqual(es.ROW_PITCH_AT_REF * 0.5, es.anchor_pitch([single], 0.5))

    def test_anchor_fragments_are_recognized(self):
        # 低对比页把 `EVENT` 读残成 `eni` / `vent`，仍要算行锚点（切片降级依赖锚点数）；其它文案不误判。
        for text in ('EVENT', 'event', 'eni', 'vent', 'EVENT T2'):
            self.assertTrue(es.is_stage_anchor(text), text)
        for text in ('CLEAR', 'STAGE LIST', '加成奖励妮姬', '1-12', 'ACTIVE'):
            self.assertFalse(es.is_stage_anchor(text), text)


class TestEventStagePipeline(unittest.TestCase):
    """OCR 读取流水线：分层、切片降级、去重、缺口补扫与策略轨迹。OCR 以回调注入，测试不需要框架。"""

    STRIP = Box(950, 0, 729, 1440, confidence=1, name='list')  # 整屏竖条（纵向拉满）。
    ANNOTATED = Box(950, 342, 729, 867, confidence=1, name='list')  # 未超限的标注框（只跑整条一层）。

    def _recorder(self, blocks):
        """构造记录调用区域的假 OCR：每次调用返回 blocks。"""
        calls = []

        def ocr_region(box):
            calls.append(box)
            return blocks

        return ocr_region, calls

    def test_ocr_blocks_runs_whole_region_and_row_tiles(self):
        # 整条 + 按行距切的分块两层都跑（分块够矮才放大得动，见 ocr_tiles）；任一层读到的行都不丢。
        ocr_region, calls = self._recorder([])
        self.assertEqual([], es._ocr_blocks(ocr_region, self.STRIP, 1.0))
        tile = round(es.ROW_PITCH_AT_REF * es.OCR_TILE_ROWS)
        self.assertEqual(4, len(calls))  # 1 整条 + 3 块（1440 / (6 行 - 1 行重叠)）。
        self.assertEqual((950, 0, 729, 1440), (calls[0].x, calls[0].y, calls[0].width, calls[0].height))
        for box in calls[1:]:  # 分块必须落在区域里、不高于目标块高（避免检测器压缩）。
            self.assertLessEqual(box.height, tile)
            self.assertLessEqual(max(box.width, box.height), es.OCR_TILE_LIMIT)
            self.assertGreaterEqual(box.y, self.STRIP.y)
            self.assertLessEqual(box.y + box.height, self.STRIP.y + self.STRIP.height)
        self.assertEqual([0, tile - 120, 2 * (tile - 120)], [box.y for box in calls[1:]])  # 步长 = 块高 - 一个行距。
        self.assertGreater(calls[2].y, calls[1].y)  # 第二块在下。
        self.assertLess(calls[2].y, calls[1].y + calls[1].height)  # 相邻块重叠：行文字不会被切在块边界。

    def test_ocr_blocks_keeps_single_call_when_region_not_taller_than_tile(self):
        short = Box(950, 342, 729, 600, confidence=1, name='list')  # 600 < 6 行（720）：整条即唯一分块。
        ocr_region, calls = self._recorder([])
        es._ocr_blocks(ocr_region, short, 1.0)
        self.assertEqual(1, len(calls))

    def test_ocr_upscale_fills_detector_limit_below_reference_resolution(self):
        # 标定分辨率及以上按原生尺寸送（放大只会糊掉笔画）；低于它才补像素：倍数 = 上限 / 最长边，封顶。
        self.assertEqual(1.0, es.ocr_upscale(Box(0, 0, 729, 1440), 1.0))  # 标定分辨率：不放大。
        self.assertEqual(1.0, es.ocr_upscale(Box(0, 0, 456, 450), 1.25))  # 高于标定分辨率：不放大。
        self.assertEqual(es.OCR_UPSCALE_MAX, es.ocr_upscale(Box(0, 0, 456, 450), 0.625))  # 900p 的 6 行块：顶到上限。
        self.assertAlmostEqual(es.OCR_TILE_LIMIT / 729, es.ocr_upscale(Box(0, 0, 729, 720), 0.75), delta=1e-6)
        self.assertEqual(es.OCR_UPSCALE_MAX, es.ocr_upscale(Box(0, 0, 1, 1), 0.625))  # 极小区域也不超过上限。

    def test_to_block_maps_upscaled_crop_back_to_full_frame(self):
        item = Box(20, 40, 10, 20, confidence=0.9, name='1-06')  # 预放大后的裁剪图坐标。
        block = es.to_block(item, Box(100, 200, 400, 400, confidence=1, name='tile'), 2.0)
        self.assertEqual((110, 220, 115, 230), (block.x1, block.y1, block.x2, block.y2))  # 除以倍数再加左上角。

    def test_dedup_blocks_keeps_highest_score_per_row(self):
        # 同一元素被两层 OCR 各读一次：同类别且纵向邻近时只留置信度高的一块。
        blocks = [es.Block(text='1-06', score=0.70, x1=1200, y1=400, x2=1300, y2=440),
                  es.Block(text='EVENT V1O6', score=0.96, x1=1200, y1=405, x2=1300, y2=445),
                  es.Block(text='CLEAR', score=0.80, x1=1200, y1=500, x2=1300, y2=540),
                  es.Block(text='CLEAR', score=0.91, x1=1200, y1=498, x2=1300, y2=538)]
        kept = es._dedup_blocks(blocks, 1.0)
        self.assertEqual([0.96, 0.91], sorted((block.score for block in kept), reverse=True))

    def test_dedup_blocks_keeps_conflicting_readings_of_one_row(self):
        # 两层 OCR 把同一行读成不同编号（实机 09.png：`16` 与 `EVENT 1-6`）不是重复识别：两块都留，
        # 由序列共识按几何裁决；读数相同的才是重复识别（见上一个用例）。
        blocks = [es.Block(text='16', score=0.99, x1=1010, y1=548, x2=1070, y2=588),
                  es.Block(text='EVENT 1-6', score=0.94, x1=846, y1=545, x2=1018, y2=585)]
        kept = es._dedup_blocks(blocks, 1.0)
        self.assertEqual(['16', 'EVENT 1-6'], sorted(block.text for block in kept))

    def test_dedup_tolerance_follows_resolution_scale(self):
        # 容差与同列去重同源（DUP_ROW_RATIO × 兜底行距）：0.5 缩放下同一行的两块也要并掉。
        blocks = [es.Block(text='1-06', score=0.70, x1=600, y1=200, x2=650, y2=220),
                  es.Block(text='1-06', score=0.96, x1=600, y1=212, x2=650, y2=232)]
        self.assertEqual(1, len(es._dedup_blocks(blocks, 0.5)))  # 容差 0.5×120×0.4 = 24px > 12px 间距。

    def test_read_rows_skips_slice_when_numbers_sufficient(self):
        # 编号块数与锚点数齐平（7 个编号、0 个锚点）：不触发降级切片。末尾也无空间可补——最后一行行框
        # 下边缘 1200 距列表区底边 1209 不足一个量化档位，故只有列表区那一层（整条 + 2 分块）。
        numbers = [es.Block(text=f'EVENT V1-0{index + 1}', score=0.9, x1=1200, y1=400 + index * 120,
                            x2=1260, y2=440 + index * 120) for index in range(7)]
        ocr_region, calls = self._recorder(numbers)
        rows, notes = es.read_rows(ocr_region, self.ANNOTATED, 1440, 1.0)
        self.assertEqual(3, len(calls))  # 整条 + 2 块（867 高按 6 行切）。
        self.assertFalse(any('切片补扫' in note for note in notes))  # 没有走降级切片。
        self.assertEqual([f'1-{index:02d}' for index in range(1, 8)], [row.stage_id for row in rows])

    def test_stage_blocks_slices_bands_when_anchors_exceed_numbers(self):
        # 低对比页：列表区只读到 1 个编号 + 3 个锚点残片，每条窄带补扫一次，切片结果并入解析输入。
        # 列表区取 6 行高以内（单次 OCR），把「整条 + 分块」的层数与窄带区分开。
        list_box = Box(950, 342, 729, 600, confidence=1, name='list')
        listed = [es.Block(text='1-12', score=0.9, x1=1200, y1=1100, x2=1260, y2=1140),
                  es.Block(text='eni', score=0.83, x1=1200, y1=400, x2=1230, y2=420),
                  es.Block(text='eni', score=0.86, x1=1200, y1=520, x2=1230, y2=540),
                  es.Block(text='vent', score=0.93, x1=1200, y1=640, x2=1240, y2=660)]
        sliced = es.Block(text='EVENT V1-04', score=0.92, x1=1200, y1=580, x2=1260, y2=620)
        calls = []

        def ocr_region(box):
            calls.append(box)
            return listed if len(calls) == 1 else [sliced]  # 首次是列表区，其后都是窄带。

        notes = []
        blocks = es._stage_blocks(ocr_region, list_box, 1440, 1.0, notes)
        self.assertEqual(4, len(calls))  # 1 次列表区 + 3 条锚点窄带。
        for band in calls[1:]:  # 窄带必须落在列表区内。
            self.assertGreaterEqual(band.x, list_box.x)
            self.assertLessEqual(band.x + band.width, list_box.x + list_box.width)
        self.assertIn('EVENT V1-04', [block.text for block in blocks])  # 切片结果并入解析输入。
        self.assertEqual(2, len(notes))  # 解析规模 + 降级原因。
        self.assertIn('列表区 OCR 4 块', notes[0])
        self.assertIn('按行锚点切片补扫', notes[1])

    def test_stage_blocks_uniform_slice_without_anchors_or_numbers(self):
        # 无 EVENT 家族的页面 + 编号也没读到：按标定行距均匀切片兜底，切片结果并入解析输入。
        list_box = Box(950, 342, 729, 600, confidence=1, name='list')
        locked = [es.Block(text='Access Denied', score=0.9, x1=1200, y1=400, x2=1500, y2=430),
                  es.Block(text='Access Denied', score=0.9, x1=1200, y1=520, x2=1500, y2=550)]
        sliced = es.Block(text='EVENT V1-04', score=0.92, x1=1200, y1=360, x2=1260, y2=400)
        calls = []

        def ocr_region(box):
            calls.append(box)
            return locked if len(calls) == 1 else [sliced]

        expected_height = es.band_height(es.row_pitch_fallback(1.0))
        notes = []
        blocks = es._stage_blocks(ocr_region, list_box, 1440, 1.0, notes)
        self.assertGreater(len(calls), 1)  # 触发降级切片。
        for band in calls[1:]:  # 均匀窄带：整列表宽 × 量化档位高度。
            self.assertEqual(list_box.x, band.x)
            self.assertEqual(list_box.width, band.width)
            self.assertEqual(expected_height, band.height)  # 高度量化到固定档位（OCR 输入尺寸不进新形状）。
            self.assertEqual(0, band.height % es.BAND_HEIGHT_STEP)
            self.assertGreaterEqual(band.y, 0)  # 夹紧在帧内：负 y 会让框架反向切片读到画面末尾。
            self.assertLess(band.y, list_box.y + list_box.height)
        self.assertIn('EVENT V1-04', [block.text for block in blocks])  # 切片结果并入解析输入。
        self.assertIn('无行锚点', notes[-1])

    def test_tail_band_starts_below_last_recognized_row(self):
        # 末尾补扫带：上沿钉在最后一行行框的下边缘（绝不回头重读该行），向下覆盖到列表区底边。
        rows = es.parse([_block('1-06', y=400), _block('1-07', y=520)], list_box=(950, 342, 729, 867))
        band = es.tail_band(rows, (950, 342, 729, 867), 1440)
        self.assertEqual((950, 600, 729, 608), (band.x, band.y, band.width, band.height))  # 最后一行的下边缘 = 600。
        self.assertEqual(0, band.height % es.BAND_HEIGHT_STEP)  # 高度向下取整到量化档位。

    def test_tail_band_absent_when_no_room_or_last_stage(self):
        list_box = (950, 342, 729, 867)
        self.assertIsNone(es.tail_band([], list_box, 1440))  # 一行都没有：末尾无从判断。
        last = es.parse([_block('1-16', y=400)], list_box=list_box)  # 已经是候选表最后一关。
        self.assertIsNone(es.tail_band(last, list_box, 1440))
        bottom = es.parse([_block('1-06', y=1190)], list_box=list_box)  # 行框下边缘 1270 已越出底边 1209。
        self.assertIsNone(es.tail_band(bottom, list_box, 1440))

    def test_parse_rows_repairs_sequence_gap_and_tail(self):
        # 编号序列缺口（1-07 → 1-09）按推断位置补扫缺失行；列表末尾（1-09 之下）再补扫一次。
        listed = [es.Block(text='1-06', score=0.95, x1=1200, y1=400, x2=1260, y2=440),
                  es.Block(text='1-07', score=0.95, x1=1200, y1=520, x2=1260, y2=560),
                  es.Block(text='1-09', score=0.95, x1=1200, y1=760, x2=1260, y2=800)]
        repaired = es.Block(text='1-08', score=0.9, x1=1200, y1=640, x2=1260, y2=680)
        ocr_region, calls = self._recorder([repaired])
        notes = []
        rows = es._parse_rows(ocr_region, self.ANNOTATED, listed, 1440, 1.0, notes)
        self.assertEqual(['1-06', '1-07', '1-08', '1-09'], [row.stage_id for row in rows])
        self.assertEqual(2, len(calls))  # 缺口一处 + 末尾一处。
        band = calls[0]
        self.assertLess(band.y, 660)  # 第一条窄带以缺口中心 660 为中线。
        self.assertGreater(band.y + band.height, 660)
        self.assertEqual(840, calls[1].y)  # 第二条上沿 = 最下面一行（1-09）行框的下边缘。
        self.assertEqual(0, calls[1].height % es.BAND_HEIGHT_STEP)
        self.assertIn('缺失行补扫 2 处', notes[0])

    def test_parse_rows_skips_reparse_when_repair_finds_nothing(self):
        # 末尾补扫多数时候扫不到新块（下面是锁定行/空白）：补扫无新块就省掉一次去重 + 重解析。
        listed = [es.Block(text='1-06', score=0.95, x1=1200, y1=400, x2=1260, y2=440),
                  es.Block(text='1-07', score=0.95, x1=1200, y1=520, x2=1260, y2=560)]
        ocr_region, calls = self._recorder([])
        notes = []
        with patch.object(es, 'parse', wraps=es.parse) as parse_mock:
            rows = es._parse_rows(ocr_region, self.ANNOTATED, listed, 1440, 1.0, notes)
        self.assertEqual(['1-06', '1-07'], [row.stage_id for row in rows])
        self.assertEqual(1, len(calls))  # 编号连续，只有末尾一处补扫。
        self.assertIn('缺失行补扫 1 处', notes[0])
        self.assertEqual(1, parse_mock.call_count)  # 补扫没读到新块 → 不重解析。

    def test_read_rows_replays_fixture_list_layer(self):
        # 端到端（离线、无框架）：把真实截图的列表区 OCR 产物喂给 read_rows，走完整条流水线
        # （分层 → 去重 → 解析）仍筛出同一批可选关卡，守住 scale / frame_height 的接线。
        name = '09'
        with open(os.path.join(FIXTURES, f'{name}.json'), encoding='utf-8') as fh:
            data = json.load(fh)
        scale = min(data['size'][0] / 2560, data['size'][1] / 1440)  # 与调用方同口径。
        ocr_region, calls = self._recorder([es.Block.from_dict(item) for item in data['list']])
        rows, _ = es.read_rows(ocr_region, Box(*data['list_box'], confidence=1, name='list'),
                               data['size'][1], scale)
        self.assertGreaterEqual(len(calls), 1)  # 整屏竖条超限，会切块 → 至少一次区域调用。
        self.assertEqual(TestEventStageFixtures.LIST_EXPECTED[name], [row.stage_id for row in rows])


    def test_parse_returns_rows_without_status(self):
        # 分层契约：解析层只给编号 + 行框 + 来源；行状态/可用性判定在 EventTask 侧。
        rows = es.parse([_block('1-04', y=400)])
        self.assertEqual(('stage_id', 'box', 'source'), tuple(rows[0].__dataclass_fields__))
        for name in ('match_status', 'has_clear_mark', 'is_anchor', 'progress_target'):
            self.assertFalse(hasattr(es, name), name)  # 状态类接口不得留在解析模块。
        self.assertFalse(hasattr(es, 'STATUS_AVAILABLE'))

    def test_ocr_tiles_split_region_by_row_pitch_with_overlap(self):
        # 竖条 1440 = 6 行 × 2 块：按行距切（块高 = 6 行 = 720，不是检测器上限 960），
        # 相邻块重叠一个行距、完整覆盖原区域。
        rects = es.ocr_tiles(950, 0, 729, 1440, es.ocr_tile_overlap(1.0), 1.0)
        tile = es.ROW_PITCH_AT_REF * es.OCR_TILE_ROWS
        self.assertEqual([(950, 0, 729, tile), (950, tile - 120, 729, tile), (950, 2 * (tile - 120), 729, 240)], rects)
        for x, _y, width, height in rects:  # 只关心 x/宽高：y 由下面的重叠断言单独校验。
            self.assertEqual(950, x)  # 宽度在限内：不横切。
            self.assertEqual(729, width)
            self.assertLessEqual(max(width, height), es.OCR_TILE_LIMIT)
        self.assertLess(rects[1][1], rects[0][1] + rects[0][3])  # 相邻块重叠：行文字不会被切在块边界。
        self.assertEqual(1440, rects[-1][1] + rects[-1][3])  # 末块收在区域末尾。

    def test_ocr_tiles_splits_both_axes_when_wide(self):
        # 两个方向都超限时横竖都切；每块仍 ≤ 上限，且起点序列覆盖到区域末尾。
        rects = es.ocr_tiles(0, 0, 2000, 1440, es.ocr_tile_overlap(1.0), 1.0)
        self.assertEqual(9, len(rects))  # 横 3 块 × 纵 3 块。
        for x, y, width, height in rects:
            self.assertLessEqual(max(width, height), es.OCR_TILE_LIMIT)
            self.assertLessEqual(x + width, 2000)
            self.assertLessEqual(y + height, 1440)
        self.assertIn((1680, 1200, 320, 240), rects)  # 末块贴着区域右下角收尾。

    def test_ocr_tiles_keeps_region_not_taller_than_tile(self):
        # 不高于目标块高（6 行）的区域原样返回一块：调用方据此保持「只 OCR 一次」。
        self.assertEqual([(950, 342, 729, 600)], es.ocr_tiles(950, 342, 729, 600, es.ocr_tile_overlap(1.0), 1.0))

    def test_ocr_tile_overlap_follows_scale(self):
        # 重叠量 = 一个标定行距：按分辨率缩放，缩放比无效（无帧/测试环境）时用标定值，与行距兜底同源。
        self.assertEqual(es.ROW_PITCH_AT_REF, es.ocr_tile_overlap(1.0))
        self.assertEqual(int(es.ROW_PITCH_AT_REF * 0.5), es.ocr_tile_overlap(0.5))
        self.assertEqual(es.ROW_PITCH_AT_REF, es.ocr_tile_overlap(0.0))


if __name__ == '__main__':
    unittest.main()
