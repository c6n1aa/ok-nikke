import unittest

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.DebugTask import DebugTask


class _FakeFeatureSet:
    """替身特征集：只暴露 debug_find_feature 用到的 process_data / feature_dict / empty。"""

    def __init__(self, names):
        self.feature_dict = {name: object() for name in names}

    def process_data(self, feature_name=None):
        pass

    def empty(self):
        return not self.feature_dict


class TestDebugFindFeature(TaskTestCase):
    task_class = DebugTask
    config = config

    def setUp(self):
        self.task.next_frame = lambda: None  # 静态帧即可，跳过真实抓帧。
        logs = []
        self.task.log_info = lambda msg: logs.append(msg)  # 收集日志避免测试噪音。
        self.logs = logs

    def _install(self, names, hits=(), errors=None):
        """替换 executor.feature_set 与 find_one：hits 命中、errors 抛异常，其余未命中。"""
        errors = errors or {}
        self.task.executor.feature_set = _FakeFeatureSet(names)

        def fake_find_one(name, *args, **kwargs):
            if name in errors:
                raise ValueError(errors[name])
            return object() if name in hits else None

        self.task.find_one = fake_find_one

    def test_scans_all_features_and_reports_hits(self):
        # 全量扫描替身特征集：命中与未命中都来自同一份名字清单，验证总数与命中列表。
        self._install(['ark', 'lobby', 'tribe_tower_mark'], hits={'ark', 'lobby'})
        result = self.task.debug_find_feature()
        self.assertIn('扫描特征(3)', result)
        self.assertIn('命中(2): ark, lobby', result)
        self.assertNotIn('异常', result)

    def test_excludes_box_region_entries(self):
        # box_* 只是 OCR 区域范围标记，不进入模板扫描清单（即使能匹配也不出现在结果里）。
        self._install(['ark', 'box_sub_pages_title'], hits={'ark', 'box_sub_pages_title'})
        result = self.task.debug_find_feature()
        self.assertIn('扫描特征(1)', result)
        self.assertIn('命中(1): ark', result)
        self.assertNotIn('box_', result)

    def test_reports_per_feature_errors_instead_of_silence(self):
        # 单个特征匹配抛异常时必须在结果中可见，不允许静默吞掉（否则误判为未命中）。
        self._install(['ark', 'lobby'], hits={'ark'}, errors={'lobby': 'not in featureDict'})
        result = self.task.debug_find_feature()
        self.assertIn('扫描特征(2)', result)
        self.assertIn('命中(1): ark', result)
        self.assertIn('异常(1): lobby(not in featureDict)', result)

    def test_empty_feature_set_reports_zero(self):
        # 空特征集（如 coco 加载失败）应返回零扫描而不是崩溃。
        self._install([])
        result = self.task.debug_find_feature()
        self.assertIn('扫描特征(0)', result)
        self.assertIn('命中(0): 无', result)


if __name__ == '__main__':
    unittest.main()
