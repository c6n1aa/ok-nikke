"""`src/event_stage.py` 的离线解析测试。

fixtures 是真实活动关卡页截图跑项目同款 onnxocr 的产物（tests/fixtures/event_stage/*.json 的
`full` = 全屏 OCR、`list` = box_event_stage_list 裁剪后的 OCR），测试只跑解析不跑模型，完全确定性。
截图本体留在 dev_tools/event/（不入仓），fixtures 的 bbox 已换算回整图坐标。
"""

import json
import os
import unittest

from src import event_stage as es

FIXTURES = os.path.join('tests', 'fixtures', 'event_stage')


def _parse(name, level):
    """读 fixtures 并解析某一层 OCR 结果。"""
    with open(os.path.join(FIXTURES, f'{name}.json'), encoding='utf-8') as fh:
        data = json.load(fh)
    return es.parse(data[level], list_box=data['list_box']), data


def _block(text, x=1000, y=400, width=200, height=40, score=0.95):
    """构造一个 OCR 文本块（bbox 按左上角 + 尺寸给出）。"""
    return es.Block(text=text, score=score, x1=x, y1=y, x2=x + width, y2=y + height)


class TestEventStageFixtures(unittest.TestCase):
    """真实截图 OCR 产物上的解析：直排列（编号 + CLEAR / 锁定族）与蛇形排列（REPEAT）。"""

    def test_direct_layout_cleared_rows_and_last_available(self):
        # NORMAL 全通页：前面都是 CLEAR，最后一关还没打（可打）。
        rows, data = _parse('event_smol_02_full', 'list')
        self.assertEqual([row.stage_id for row in rows], [f'1-{i:02d}' for i in range(6, 13)])
        self.assertEqual([row.status for row in rows], ['clear'] * 6 + ['available'])
        self.assertEqual('1-12', es.progress_target(rows).stage_id)
        list_box = data['list_box']
        for row in rows:  # 行框收在列表区内、纵向按行距切分；横向取编号块范围（直排/蛇形都点得中）。
            self.assertGreaterEqual(row.box[0], list_box[0])
            self.assertLessEqual(row.box[2], list_box[0] + list_box[2])

    def test_direct_layout_locked_rows_have_no_id(self):
        # 锁定页：只有首关有编号，其余行是 ACCESS/DENIED（编号位被锁定文案占据）。
        rows, _ = _parse('event_smol_02', 'list')
        self.assertEqual('1-01', rows[0].stage_id)
        self.assertEqual(es.STATUS_AVAILABLE, rows[0].status)
        locked = [row for row in rows if row.status == es.STATUS_LOCKED]
        self.assertEqual(6, len(locked))
        for row in locked:  # 锁定行没有编号，来源为 lock。
            self.assertIsNone(row.stage_id)
            self.assertEqual(es.SOURCE_LOCK, row.source)
        self.assertEqual('1-01', es.progress_target(rows).stage_id)

    def test_locked_only_page_full_layer_reads_arrow_prefixed_number(self):
        # 全屏层（EventTask 不采用，仅作对照输入）：锁定行占位读不到编号，但首关带装饰箭头的编号
        # （`》1-01`，旧的文案白名单因 `》` 把整块丢弃）现在按结构判据能读出来。
        rows, data = _parse('event_smol_02', 'full')
        self.assertEqual(1, es.count_numbers(data['full']))
        self.assertEqual('1-01', rows[0].stage_id)
        self.assertEqual([es.STATUS_LOCKED] * 6, [row.status for row in rows[1:]])

    def test_direct_layout_misread_numbers_normalize(self):
        # HARD 全通页：7 行编号全是形近抖动（√ 读成 V 再叠 O↔0、=↔-，如 V1O6 / V1-O8 / V 1=1O），必须全部归一化。
        rows, _ = _parse('event_smol_02_full_hard', 'list')
        self.assertEqual([f'1-{i:02d}' for i in range(6, 13)], [row.stage_id for row in rows])
        self.assertEqual([es.STATUS_CLEAR] * 7, [row.status for row in rows])  # 每行都带勾选 √ = 已通关。
        self.assertIsNone(es.progress_target(rows))

    def test_low_contrast_page_needs_fallback_level(self):
        # HARD 全通页：全屏 0 检出（低对比小字），必须靠列表区裁剪/切片降级；裁剪层只能读到 1-12。
        rows, data = _parse('event_smol_02_full_hard_1', 'full')
        self.assertEqual(0, es.count_numbers(data['full']))
        rows, data = _parse('event_smol_02_full_hard_1', 'list')
        self.assertEqual(['1-12'], [row.stage_id for row in rows])
        # 降级判据：裁剪层只读到 1 个编号，但锚点片段（eni/vent）有 3 个 → 编号数 < 锚点数 = 走行锚点切片。
        blocks = [es.Block.from_dict(block) for block in data['list']]
        anchors = [block for block in blocks
                   if es.is_anchor(block.text) and not es.stage_id_candidates(block.text)]
        self.assertLess(es.count_numbers(data['list']), len(anchors))

    def test_snake_layout_repeat_row(self):
        # 蛇形排列（另一期活动）：可重复挑战的行带 `REPEAT >>`，状态必须是 repeat（扫荡目标行）。
        rows, _ = _parse('img', 'list')
        self.assertEqual('1-01', rows[0].stage_id)
        self.assertEqual(es.STATUS_REPEAT, rows[0].status)
        self.assertEqual('1-02', rows[1].stage_id)
        self.assertEqual(es.STATUS_AVAILABLE, rows[1].status)
        self.assertTrue(any(row.status == es.STATUS_LOCKED for row in rows))  # 同行列表里还有锁定行。

    def test_handwritten_page_stays_within_candidate_set(self):
        # 手写体全锁页：编号可能误读，解析结果只允许落在受限候选表内（或 None），且不抛异常。
        rows, _ = _parse('img_1', 'full')
        for row in rows:
            self.assertIn(row.stage_id, es.ALLOWED_IDS + (None,))

    def test_handwritten_snake_page_parses_number_row(self):
        # 手写体 + 蛇形（`img_1.png`，1507x878）：编号是纯数字 `04`，锚点读成 `&vent`，锁定文案抖动成
        # `Aces Denied`/`AccessDeniced`。首关可打（用户确认），紧贴编号下方的 `Access Denied` 属于下一行，
        # 不能被归到编号行——否则唯一可打行会被误判 locked → 推图跳过。
        rows, data = _parse('img_1', 'full')
        numbered = [row for row in rows if row.stage_id]
        self.assertEqual(['1-04'], [row.stage_id for row in numbered])
        self.assertEqual(es.STATUS_AVAILABLE, numbered[0].status)
        self.assertEqual(4, len([row for row in rows if not row.stage_id]))
        self.assertEqual('1-04', es.progress_target(rows).stage_id)
        self.assertEqual(1, es.count_numbers(data['full']))
        # 蛇形：编号在左列（x≈662），行框不能横跨整列表宽（否则中心落在两列之间）。
        self.assertLess(numbered[0].box[2], 988)  # 列表区右边界。

    def test_find_stage_locates_sweep_target(self):
        # 扫荡目标定位：按编号找到行（供点该行 → 关卡详情页快速战斗）；表外编号直接判空。
        rows, _ = _parse('event_smol_02_full', 'list')
        self.assertEqual('1-08', es.find_stage(rows, '1-08').stage_id)
        self.assertIsNone(es.find_stage(rows, '2-01'))
        self.assertIsNone(es.find_stage(rows, '1-01'))


class TestEventStageBlocks(unittest.TestCase):
    """纯函数与合成变体：编号变体、噪声拒绝、两行配对、序列收敛。"""

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
            'EVENT Y': [],  # 只有锚点 + 装饰字母：不是编号块（仍按锚点用）。
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
            _block('+ +  Alccess Denied + +', y=741, height=20),
        ]
        rows = es.parse(blocks, list_box=(681, 245, 522, 621))
        self.assertEqual(['1-01', None, None, None], [row.stage_id for row in rows])
        self.assertEqual([es.STATUS_AVAILABLE, es.STATUS_LOCKED, es.STATUS_LOCKED, es.STATUS_LOCKED],
                         [row.status for row in rows])
        self.assertEqual('1-01', es.progress_target(rows).stage_id)  # 首关要能被选中去推图。

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

    def test_status_attachment_requires_lower_half_of_row(self):
        # 状态文字落在编号行下半区（>0.5 行距）才归行；紧贴编号（上半区）的是下一锁定行的文案槽 → 独立行。
        rows = es.parse([_block('1-05', y=400),  # ctr 420。
                         _block('ACCESS DENIED', y=400 + 48),  # ctr 468，Δ48 = 0.2 行距 → 独立锁定行。
                         _block('1-06', y=400 + 240),  # ctr 660。
                         _block('CLEAR', y=400 + 240 + 150)])  # ctr 830，Δ170 = 0.71 行距 → 归给 1-06。
        self.assertEqual(['1-05', None, '1-06'], [row.stage_id for row in rows])
        self.assertEqual([es.STATUS_AVAILABLE, es.STATUS_LOCKED, es.STATUS_CLEAR], [row.status for row in rows])
        self.assertEqual('1-05', es.progress_target(rows).stage_id)  # 唯一可打行不被误判 locked。

    def test_snake_number_rows_narrow_to_own_column(self):
        # 蛇形：相邻编号分居左右两列（同一 y、不同 x），行框取各自编号块 x，互不重叠、不横跨整列表宽。
        rows = es.parse([_block('1-03', x=1000, y=400), _block('1-04', x=1400, y=400)])
        left, right = rows[0], rows[1]
        self.assertEqual('1-03', left.stage_id)
        self.assertEqual('1-04', right.stage_id)
        self.assertLess(left.box[2], right.box[0])  # 左列行框在右列左侧。
        self.assertGreater(left.box[0], 1000 - 50)  # 仍是编号块邻域，不是整屏宽。

    def test_duplicate_number_blocks_merge_into_one_row(self):
        # 同一行的重复识别（`1-05` 与带装饰箭头的 `》1-05`）不能收敛成两行：否则会凭空多出一关。
        rows = es.parse([_block('1-04', y=280), _block('1-05', y=400), _block('》1-05', x=1010, y=402)])
        self.assertEqual(['1-04', '1-05'], [row.stage_id for row in rows])

    def test_snake_layout_columns_are_not_merged(self):
        # 蛇形布局：同一 y 上左右两列是两关（x 不重叠）→ 不能被去重并掉。
        rows = es.parse([_block('1-04', x=1000, y=400), _block('1-05', x=1400, y=400)])
        self.assertEqual(['1-04', '1-05'], [row.stage_id for row in rows])

    def test_clear_mark_detection(self):
        # 行内勾选符号 √（已通关标记）实测被 OCR 读成 V：紧邻编号才算，孤立字母不算。
        for text in ('EVENT V1-06', 'EVENT V 1=10', 'V06', 'EVENT √1-06'):
            self.assertTrue(es.has_clear_mark(text), text)
        for text in ('EVENT 1-06', 'EVENT', 'V CLEAR', 'STAGE LIST'):
            self.assertFalse(es.has_clear_mark(text), text)

    def test_checkmark_row_is_cleared(self):
        # 带勾选的行默认 clear（CLEAR 文字缺失时兜底）；状态文案优先于勾选（REPEAT >> 仍判 repeat）。
        rows = es.parse([_block('EVENT V1-06', y=400), _block('EVENT 1-07', y=520)])
        self.assertEqual([es.STATUS_CLEAR, es.STATUS_AVAILABLE], [row.status for row in rows])
        self.assertEqual('1-07', es.progress_target(rows).stage_id)
        rows = es.parse([_block('EVENT V1-01', y=400), _block('REPEAT >>', y=470)])
        self.assertEqual([es.STATUS_REPEAT], [row.status for row in rows])

    def test_progress_target_is_row_above_lock_band(self):
        # 门票机制下一页常是「一半已通关 + 一半锁定」：目标取锁定段上方那关（列表最下面的可打行）。
        # 1-04 已通关但状态漏检（CLEAR 与勾选都没读到）→ 会被解析成 available，不能选它。
        blocks = [_block('1-03', y=280), _block('CLEAR', y=350),  # 已通关（状态正常读到）。
                  _block('1-04', y=400),  # 已通关但状态漏检 → 解析成 available。
                  _block('1-05', y=520),  # 真正的可打关（锁定段上方那行）。
                  _block('ACCESS DENIED', y=640)]  # 其后开始锁定。
        rows = es.parse(blocks)
        self.assertEqual(['1-04', '1-05'], [row.stage_id for row in rows if row.status == es.STATUS_AVAILABLE])
        self.assertEqual('1-05', es.progress_target(rows).stage_id)
        self.assertIsNone(es.progress_target(es.parse([_block('1-01', y=400), _block('CLEAR', y=470)])))

    def test_noise_texts_are_not_stage_ids(self):
        # 美术噪声/计数器/滚动日志不能当编号：否则会凭空造出关卡行（0/5 曾被当成 1-05）。
        for text in ('PART1', '活动剧情第1部', '0/5', '107.01.8', '-/-', 'REPEAT >>', 'STAGE LIST', '加成奖励妮姬',
                     'ADD 2', '5/5', '015', '515', '0:', '2045F', '-Rt 003krz-2.0s', '2937628F. RtD2Dkr2-22s',
                     'Updated Path data', 'Active System Log', 'CAUTION : Sign', 'PROTOCOL.ux', 'EVENI'):
            self.assertEqual([], es.stage_id_candidates(text), text)
        self.assertEqual(0, es.count_numbers([_block(text) for text in ('PART1', '0/5', 'ADD 2')]))

    def test_anchor_fragments_are_recognized(self):
        # 低对比页把 `EVENT` 读残成 `eni` / `vent`，仍要算行锚点（降级判据依赖锚点数）；其它文案不误判。
        for text in ('EVENT', 'event', 'eni', 'vent', 'EVENT T2'):
            self.assertTrue(es.is_anchor(text), text)
        for text in ('CLEAR', 'STAGE LIST', '加成奖励妮姬', '1-12', 'ACTIVE'):
            self.assertFalse(es.is_anchor(text), text)

    def test_two_line_anchor_pairs_one_row(self):
        # 两行式布局：`EVENT` 锚点块 + 编号块同带 = 一行；锚点块自身不产生行。
        blocks = [_block('EVENT', y=400), _block('1-08', y=436)]
        rows = es.parse(blocks)
        self.assertEqual(['1-08'], [row.stage_id for row in rows])
        self.assertEqual(1, len([block for block in blocks
                                 if es.is_anchor(block.text) and not es.stage_id_candidates(block.text)]))

    def test_sequence_snaps_misread_to_expected_next(self):
        # 序列单调：`1-6, 1.2, 1-8` 里的误读 1.2 收敛为 1-07（受限候选 + 顺序约束）。
        blocks = [_block('1-6', y=400), _block('1.2', y=520), _block('1-8', y=640)]
        rows = es.parse(blocks)
        self.assertEqual(['1-06', '1-07', '1-08'], [row.stage_id for row in rows])
        self.assertEqual(es.SOURCE_SEQUENCE, rows[1].source)

    def test_status_attaches_only_within_row_pitch(self):
        # 状态文案画在所属编号行下方约 0.6 倍行距处；超出一个行距即视为独立锁定行。
        near = [_block('1-01', y=400), _block('1-02', y=520), _block('CLEAR', y=470)]
        rows = es.parse(near)
        self.assertEqual(es.STATUS_CLEAR, rows[0].status)
        self.assertEqual(es.STATUS_AVAILABLE, rows[1].status)
        far = [_block('1-01', y=400), _block('1-02', y=520), _block('DENIED', y=700)]
        rows = es.parse(far)
        self.assertEqual(3, len(rows))  # 多出一行锁定行。
        self.assertEqual(es.SOURCE_LOCK, rows[2].source)

    def test_fallback_row_pitch_scales_with_resolution(self):
        # 兜底行距不是固定像素：按分辨率缩放比缩放；缩放比无效（无帧/测试环境）时用标定值。
        self.assertEqual(es.ROW_PITCH_AT_REF, es.row_pitch_fallback(1.0))
        self.assertAlmostEqual(es.ROW_PITCH_AT_REF * 0.75, es.row_pitch_fallback(0.75))  # 1080p = 1440p 的 0.75。
        self.assertEqual(es.ROW_PITCH_AT_REF, es.row_pitch_fallback(0.0))

    def test_status_attach_tolerance_follows_scale(self):
        # 只有一个编号块（测不出行距）时归行容差走兜底行距：低分辨率下容差缩小，超界状态块成为独立行。
        blocks = [_block('1-01', y=400), _block('CLEAR', y=480)]  # 编号中心 420、状态中心 500，间距 80。
        self.assertEqual([es.STATUS_CLEAR], [row.status for row in es.parse(blocks)])  # 1440p：80 ≤ 120 × 0.9。
        rows = es.parse(blocks, scale=0.5)  # 720p：容差缩到 60 × 0.9 = 54 < 80。
        self.assertEqual(2, len(rows))
        self.assertEqual(es.SOURCE_LOCK, rows[1].source)


if __name__ == '__main__':
    unittest.main()
