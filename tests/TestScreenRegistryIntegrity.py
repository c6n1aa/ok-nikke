"""coco 标注完整性静态校验：注册表引用的特征必须存在于 coco annotations。

纯 unittest 静态比对，不触碰游戏帧、不需要 TaskTestCase。
把「注册表引用了 coco 中不存在的特征」从运行时 warning（NikkeBaseTask
的界面特征缺失告警）前移到测试期/CI 失败。
"""
import json
import os
import unittest

from src.screens import SCREENS

_COCO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "assets", "coco_annotations.json")


class TestScreenRegistryIntegrity(unittest.TestCase):
    def _load_coco_names(self):
        with open(_COCO_PATH, encoding="utf-8") as f:
            coco = json.load(f)
        return {category["name"] for category in coco.get("categories", [])}

    def test_registry_references_exist_in_coco(self):
        # 收集全部界面的 features/any_features 元素与字符串形式 ocr_box/feature_box（coco 区域特征名）。
        references = {}  # 界面名 -> 该界面引用的特征名集合。
        for name, spec in SCREENS.items():
            refs = set(spec.get("features") or []) | set(spec.get("any_features") or [])
            for key in ("ocr_box", "feature_box"):  # 字符串形式的区域特征名同样视为 coco 引用。
                box = spec.get(key)
                if isinstance(box, str):
                    refs.add(box)
            if refs:
                references[name] = refs
        self.assertTrue(references, "SCREENS 里没有任何特征引用，校验形同虚设")

        coco_names = self._load_coco_names()
        missing = {name: sorted(refs - coco_names) for name, refs in references.items()
                   if refs - coco_names}
        if missing:  # 按界面分组打印缺失清单，提供可读 diff。
            lines = ["注册表引用了 coco 中不存在的特征:"]
            for name, absent in missing.items():
                lines.append(f"  {name}: {', '.join(absent)}")
            self.fail("\n".join(lines))

    def test_no_empty_spec(self):
        # 二次断言：每个界面至少配置 features/keywords/any_features 之一，防止误注册空 spec。
        empty = [name for name, spec in SCREENS.items()
                 if not spec.get("features") and not spec.get("keywords")
                 and not spec.get("any_features")]
        self.assertEqual([], empty, f"以下界面没有任何判定条件: {empty}")


if __name__ == '__main__':
    unittest.main()
