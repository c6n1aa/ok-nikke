# Test case
import unittest

from PySide6.QtGui import QFontMetrics

from src.config import config
from ok.ui.qt.common.design_system import control_width
from ok.test.TaskTestCase import TaskTestCase
from ok.ui.qt.tasks.ConfigItemFactory import config_widget
from ok.ui.qt.tasks.LabelAndButtons import LabelAndButtons
from ok.ui.qt.tasks.LabelAndFileSelector import LabelAndFileSelector
from ok.ui.qt.tasks.ModifyListDialog import ModifyListDialog
from ok.ui.qt.tasks.ModifyListItem import ModifyListItem
from qfluentwidgets import PushButton

from src.tasks.MyOneTimeTask import MyOneTimeTask


class TestMyOneTimeTask(TaskTestCase):
    task_class = MyOneTimeTask

    config = config

    def test_config_demo_supports_all_widget_types_and_sub_configs(self):
        defaults = self.task.default_config
        config_type = self.task.config_type

        self.assertIsInstance(defaults["布尔配置"], bool)
        self.assertIsInstance(defaults["整数配置"], int)
        self.assertIsInstance(defaults["浮点数配置"], float)
        self.assertIsInstance(defaults["字符串配置"], str)
        self.assertIsInstance(defaults["文件夹选择配置"], str)
        self.assertIsInstance(defaults["文件选择配置"], str)
        self.assertIsInstance(defaults["列表配置"], list)
        self.assertIsInstance(defaults["下拉框选项配置"], list)
        self.assertEqual("字符串值", defaults["字符串配置"])
        self.assertEqual(["列表值 1", "列表值 2"], defaults["列表配置"])
        self.assertEqual("drop_down", config_type["下拉框配置"]["type"])
        self.assertEqual("text_edit", config_type["多行文本配置"]["type"])
        self.assertEqual("file_selector", config_type["文件夹选择配置"]["type"])
        self.assertEqual("folder", config_type["文件夹选择配置"]["selector_type"])
        self.assertEqual("选择演示文件夹", config_type["文件夹选择配置"]["dialog_title"])
        self.assertEqual("file_selector", config_type["文件选择配置"]["type"])
        self.assertEqual("file", config_type["文件选择配置"]["selector_type"])
        self.assertEqual("选择演示文件", config_type["文件选择配置"]["dialog_title"])
        self.assertEqual("Python 文件 (*.py);;所有文件 (*)", config_type["文件选择配置"]["filter"])
        self.assertEqual("drop_down", config_type["下拉框选项配置"]["type"])
        self.assertEqual(
            [
                "可用下拉框值 1",
                "可用下拉框值 2",
                "可用下拉框值 3",
            ],
            config_type["下拉框选项配置"]["options_available"],
        )
        self.assertEqual("multi_selection", config_type["多选配置"]["type"])
        self.assertEqual("button", config_type["按钮配置"]["type"])
        self.assertEqual("button", config_type["按钮选项配置"]["type"])
        self.assertEqual(
            ["显示配置值", "显示通知"],
            [button["text"] for button in config_type["按钮选项配置"]["buttons"]],
        )
        self.assertEqual(
            {
                "下拉框值 1": ["子布尔配置"],
                "下拉框值 2": ["子字符串配置", "子浮点数配置"],
            },
            config_type["下拉框配置"]["sub_configs"],
        )

    def test_folder_selector_config_uses_folder_selector_widget(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "文件夹选择配置",
            self.task.config.get("文件夹选择配置"),
            self.task,
        )
        self.assertIsInstance(widget, LabelAndFileSelector)
        self.assertEqual("folder", widget.selector_type)
        self.assertFalse(hasattr(widget, "line_edit"))
        self.assertEqual(str(self.task.config.get("文件夹选择配置") or ""), widget.value_label.text())

    def test_file_selector_config_uses_file_selector_widget(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "文件选择配置",
            self.task.config.get("文件选择配置"),
            self.task,
        )
        self.assertIsInstance(widget, LabelAndFileSelector)
        self.assertEqual("file", widget.selector_type)
        self.assertEqual("Python 文件 (*.py);;所有文件 (*)", widget.config_type["filter"])
        self.assertFalse(hasattr(widget, "line_edit"))
        self.assertEqual(str(self.task.config.get("文件选择配置") or ""), widget.value_label.text())

    def test_button_options_config_uses_multiple_buttons(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "按钮选项配置",
            self.task.config.get("按钮选项配置"),
            self.task,
        )
        self.assertIsInstance(widget, LabelAndButtons)
        self.assertEqual(2, len(widget.findChildren(PushButton)))

    def test_options_available_uses_restricted_option_list_dialog(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "下拉框选项配置",
            self.task.config.get("下拉框选项配置"),
            self.task,
        )
        self.assertIsInstance(widget, ModifyListItem)
        self.assertTrue(widget.allow_duplication)

        options = self.task.config_type["下拉框选项配置"]["options_available"]
        dialog = ModifyListDialog(
            ["可用下拉框值 1"],
            widget,
            options_available=options,
            allow_duplication=widget.allow_duplication,
        )
        result = []
        dialog.list_modified.connect(result.append)

        dialog.add_available_item("可用下拉框值 2")
        dialog.add_available_item("可用下拉框值 2")
        dialog.confirm()

        self.assertEqual(
            [
                "可用下拉框值 1",
                "可用下拉框值 2",
                "可用下拉框值 2",
            ],
            result[0],
        )
        widget.list_modified(["可用下拉框值 1", "不可用值"])
        self.assertEqual(["可用下拉框值 1"], self.task.config["下拉框选项配置"])

    def test_string_config_input_uses_minimum_width_when_empty(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "字符串配置",
            self.task.config.get("字符串配置"),
            self.task,
        )

        widget.line_edit.setText("")
        self.assertEqual(widget.MIN_INPUT_WIDTH, widget.line_edit.width())
        self.assertEqual(widget.MIN_INPUT_WIDTH, widget.line_edit.minimumWidth())
        widget.line_edit.setText("a")
        self.assertEqual(widget.MIN_INPUT_WIDTH, widget.line_edit.width())
        long_text = "String Value With Enough Content"
        widget.line_edit.setText(long_text)
        expected_width = control_width(
            QFontMetrics(widget.line_edit.font()).horizontalAdvance(long_text)
            + widget.HORIZONTAL_PADDING
        )
        self.assertEqual(expected_width, widget.line_edit.width())
        self.task.config["字符串配置"] = self.task.default_config["字符串配置"]

    def test_text_edit_config_uses_minimum_width_when_empty(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "多行文本配置",
            self.task.config.get("多行文本配置"),
            self.task,
        )

        widget.text_edit.setText("")
        self.assertEqual(widget.MIN_INPUT_WIDTH, widget.text_edit.width())
        self.assertEqual(widget.MIN_INPUT_WIDTH, widget.text_edit.minimumWidth())
        widget.text_edit.setText("a")
        self.assertEqual(widget.MIN_INPUT_WIDTH, widget.text_edit.width())
        long_line = "Text Edit Value With Enough Content To Need More Width"
        widget.text_edit.setText(f"Short\n{long_line}")
        expected_width = max(
            widget.MIN_INPUT_WIDTH,
            control_width(
                QFontMetrics(widget.text_edit.font()).horizontalAdvance(long_line)
                + widget.HORIZONTAL_PADDING
            ),
        )
        self.assertEqual(expected_width, widget.text_edit.width())
        self.task.config["多行文本配置"] = self.task.default_config["多行文本配置"]

    def test_run_shows_config_values(self):
        self.task.config.reset_to_default()
        self.task.run()

        for key, value in self.task.config.items():
            self.assertEqual(self.task.translate_config_value(value), self.task.info_get(key))
        self.assertEqual("下拉框值 1", self.task.info_get("下拉框配置"))
        self.assertEqual("真", self.task.info_get("布尔配置"))
        self.assertEqual("字符串值", self.task.info_get("字符串配置"))
        self.assertEqual(["列表值 1", "列表值 2"], self.task.info_get("列表配置"))
        self.assertEqual(
            ["可用下拉框值 1"],
            self.task.info_get("下拉框选项配置"),
        )
        self.assertEqual(
            ["多选值 1", "多选值 2"],
            self.task.info_get("多选配置"),
        )

    def test_ocr1(self):
        # Create a BattleReport object
        self.set_image('tests/images/main.png')
        text = self.task.find_some_text_on_bottom_right()
        self.assertEqual(text[0].name, '方舟')

    def test_ocr2(self):
        # Create a BattleReport object
        self.set_image('tests/images/main.png')
        text = self.task.find_some_text_with_relative_box()
        self.assertEqual(text[0].name, '队员招募')

    def test_feature1(self):
        # Create a BattleReport object
        self.set_image('tests/images/main.png')
        feature = self.task.test_find_one_feature()
        self.assertIsNotNone(feature)

    def test_feature2(self):
        # Create a BattleReport object
        self.set_image('tests/images/main.png')
        features = self.task.test_find_feature_list()
        self.assertEqual(1, len(features))


if __name__ == '__main__':
    unittest.main()
