import re

from qfluentwidgets import FluentIcon

from ok import og
from src.tasks.NikkeBaseTask import NikkeBaseTask


class MyOneTimeTask(NikkeBaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 源码里的 UI 字符串一律写简体中文（基准语种），其它语言由 i18n/<locale>/LC_MESSAGES/ok.po 翻译。
        self.name = "配置演示任务"
        self.description = "演示各配置控件从简体中文翻译到其它语言的效果。"
        self.icon = FluentIcon.SYNC
        self.default_config.update({
            "下拉框配置": "下拉框值 1",
            "布尔配置": True,
            "整数配置": 1,
            "浮点数配置": 1.1,
            "字符串配置": "字符串值",
            "多行文本配置": "多行文本值",
            "文件夹选择配置": "",
            "文件选择配置": "",
            "列表配置": ["列表值 1", "列表值 2"],
            "下拉框选项配置": ["可用下拉框值 1"],
            "多选配置": ["多选值 1", "多选值 2"],
            "子布尔配置": False,
            "子字符串配置": "子字符串值",
            "子浮点数配置": 2.2,
        })
        self.config_description.update({
            "下拉框配置": "带已翻译选项值的下拉框配置。",
            "字符串配置": "带已翻译值的单行字符串配置。",
            "多行文本配置": "带已翻译值的多行文本配置。",
            "文件夹选择配置": "保存所选文件夹路径的文件夹选择配置。",
            "文件选择配置": "带可选文件过滤器的文件选择配置。",
            "下拉框选项配置": "仅可从已翻译可用值中选择的下拉框选项配置。",
            "按钮配置": "显示全部当前配置值的按钮配置。",
            "按钮选项配置": "带多个操作按钮的按钮配置。",
        })
        self.config_type.update({
            "下拉框配置": {
                "type": "drop_down",
                "options": ["下拉框值 1", "下拉框值 2"],
                "sub_configs": {
                    "下拉框值 1": ["子布尔配置"],
                    "下拉框值 2": ["子字符串配置", "子浮点数配置"],
                },
            },
            "多行文本配置": {"type": "text_edit"},
            "文件夹选择配置": {
                "type": "file_selector",
                "selector_type": "folder",
                "dialog_title": "选择演示文件夹",
            },
            "文件选择配置": {
                "type": "file_selector",
                "selector_type": "file",
                "dialog_title": "选择演示文件",
                "filter": "Python 文件 (*.py);;所有文件 (*)",
            },
            "下拉框选项配置": {
                "type": "drop_down",
                "allow_duplication": True,
                "options_available": [
                    "可用下拉框值 1",
                    "可用下拉框值 2",
                    "可用下拉框值 3",
                ],
            },
            "多选配置": {
                "type": "multi_selection",
                "options": [
                    "多选值 1",
                    "多选值 2",
                    "多选值 3",
                ],
            },
            "按钮配置": {
                "type": "button",
                "text": "按钮值",
                "callback": self.show_config_values,
            },
            "按钮选项配置": {
                "type": "button",
                "buttons": [
                    {
                        "text": "显示配置值",
                        "callback": self.show_config_values,
                    },
                    {
                        "text": "显示通知",
                        "callback": self.show_notification,
                    },
                ],
            },
        })

    def run(self):
        self.show_config_values()
        self.log_info("已显示全部配置值。", notify=True)

    def validate_config(self, key, value):
        if key == "下拉框配置" and value not in self.config_type[key]["options"]:
            return "请从可用下拉框值中选择。"
        if key == "多选配置":
            options = self.config_type[key]["options"]
            if any(item not in options for item in value):
                return "请仅选择可用的多选值。"
        if key == "下拉框选项配置":
            options = self.config_type[key]["options_available"]
            if any(item not in options for item in value):
                return "请仅选择可用的下拉框选项值。"

    def show_config_values(self):
        for key, value in self.config.items():
            self.info_set(key, self.translate_config_value(value))

    def show_notification(self):
        self.log_info("已显示按钮通知。", notify=True)

    def translate_config_value(self, value):
        # 布尔值走 str(value)，msgid 固定为 "True"/"False"，各语言词条里单独给译文。
        if isinstance(value, bool):
            return og.app.tr(str(value))
        if isinstance(value, str):
            return og.app.tr(value)
        if isinstance(value, list):
            return [og.app.tr(item) for item in value]
        return value

    def find_some_text_on_bottom_right(self):
        return self.ocr(box="bottom_right",match="方舟", log=True) #指定box以提高ocr速度

    def find_some_text_with_relative_box(self):
        return self.ocr(0.5, 0.5, 1, 1, match=re.compile("招"), log=True) #指定box以提高ocr速度

    def test_find_one_feature(self):
        return self.find_one('ark')

    def test_find_feature_list(self):
        return self.find_feature('ark')
