import unittest
from unittest.mock import patch

from src.config import config
from src.tasks.OutpostTask import OutpostTask, _normalize_character_name
from ok.test.TaskTestCase import TaskTestCase


class TestOutpostAdviseName(TaskTestCase):
    """咨询角色名读取与答案库查询：用实机截图锁定「名字框标注 → OCR → 查询」链路。"""

    task_class = OutpostTask

    config = config

    def test_read_name_and_query_from_real_screenshot(self):
        # 2560x1440 咨询详情页实机截图（tests/images/advise.png）：名字条位于 box_advise_nikke_name
        # 内且只有名字一个文本块，OCR 结果须能查到答案库条目。
        self.set_image('tests/images/advise.png')
        name = self.task._read_advise_name()
        self.assertTrue(name.strip())  # 名字框 OCR 出非空名称。
        with patch.object(self.task, "_advise_locale", return_value="zh_CN"):
            self.assertTrue(self.task._query_advise_rows(name))  # 回归：E.H. 曾因尾随点恒查不到。

    def test_read_sp_name_full_from_real_screenshot(self):
        # zh_CN 带 SP 后缀的长名角色截图（银华：战术升级）：名字框须读全名——库里同时存在前缀角色
        # 「银华」，读成前缀会静默取回原角色的答案（答案集完全不同，必然答错）。
        self.set_image('tests/images/advise-yh.png')
        name = self.task._read_advise_name()
        self.assertEqual("银华战术升级", _normalize_character_name(name))  # SP 后缀未被截断。
        with patch.object(self.task, "_advise_locale", return_value="zh_CN"):
            rows = self.task._query_advise_rows(name)  # SP 角色自身条目。
            base_rows = self.task._query_advise_rows("银华")  # 前缀原角色条目。
        self.assertTrue(rows)
        self.assertNotEqual(base_rows, rows)  # 串到原角色会取回完全不同的答案。


if __name__ == '__main__':
    unittest.main()
