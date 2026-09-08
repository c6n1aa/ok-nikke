import os
import unittest
from unittest.mock import patch

from ok.feature.Box import Box
from ok.task.exceptions import WaitFailedException
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.RecruitTask import RecruitTask

_TEST_CONFIG_DIR = os.path.join('dev_tools', 'test_configs')


def _isolate_task_config(task, name):
    """把任务配置重定向到 dev_tools/test_configs 下的临时文件，避免污染真实 configs/。"""
    os.makedirs(_TEST_CONFIG_DIR, exist_ok=True)
    task.config.config_file = os.path.join(_TEST_CONFIG_DIR, f'{name}.json')
    task.config['_execution_states'] = {}


def _execute_step(step_fn, **kw):
    """try_step 桩：直通执行步骤并返回 True（真实 try_step 成功即返回 True，忽略步骤返回值）。"""
    step_fn()
    return True


class _DebugOffTestCase(TaskTestCase):
    """基类：测试环境强制 debug=True，本基类将其屏蔽，以便验证正常的已完成/记录逻辑。"""

    def setUp(self):
        patcher = patch.object(self.task, '_in_debug', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestRecruitTask(_DebugOffTestCase):
    task_class = RecruitTask

    config = config

    def setUp(self):
        super().setUp()
        _isolate_task_config(self.task, 'RecruitTask')
        # 配置写穿透到共享临时文件：其他测试留下的开关/完成状态会泄漏进来，必须显式钉死。
        self.task.config["友情点招募"] = self.task.default_config["友情点招募"]
        self.task.config["折扣普通招募"] = self.task.default_config["折扣普通招募"]
        self.task.clear_done_all()
        self.set_image('tests/images/main.png')  # 提供真实帧，保证 get_box_by_name 可解析标注区域。

    def test_config_defaults(self):
        self.assertEqual("招募", self.task.name)
        self.assertEqual("活动免费招募/友情点招募/普通招募", self.task.description)
        self.assertNotIn("招募", self.task.default_config)  # 总开关由日常编排的「招募」键承担，任务自身不重复。
        self.assertTrue(self.task.default_config["友情点招募"])
        self.assertFalse(self.task.default_config["折扣普通招募"])
        self.assertNotIn("免费活动单抽", self.task.default_config)  # 暂缺截图特征，配置已屏蔽（补充知识2）。
        self.assertNotIn("招募", self.task.config_type)  # 无主开关即无 sub_configs 联动。
        self.assertEqual({"recruit": "day"}, RecruitTask.done_keys)

    def test_run_skips_when_already_done(self):
        self.task.mark_done("recruit", "day")  # 标记本周期已完成。
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "transition", side_effect=AssertionError("已完成时不应进入招募界面")):
            self.task.run()
        self.assertTrue(self.task.is_done("recruit", "day"))

    def test_run_aborts_when_lobby_not_reachable(self):
        with patch.object(self.task, "ensure_screen", return_value=False), \
                patch.object(self.task, "transition", side_effect=AssertionError("未就位大厅时不应进入招募界面")):
            self.task.run()
        self.assertFalse(self.task.is_done("recruit", "day"))

    def test_run_skips_when_flow_fails(self):
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "try_step", return_value=False), \
                patch.object(self.task, "_do_recruit", side_effect=AssertionError("try_step 返回 False 时不应执行流程")):
            self.task.run()
        self.assertFalse(self.task.is_done("recruit", "day"))

    def test_full_success_flow(self):
        # 友情点招募成功路径：进界面→点单抽→跳过动画→点确定→返回大厅。
        entry = Box(500, 500, 50, 30, confidence=1, name="recruit_social_point_single")
        confirm = Box(1000, 900, 60, 30, confidence=1, name="确定")
        result_box = Box(200, 700, 500, 200, confidence=1, name="box_recruit_result")

        def fake_find_one(name, *args, **kwargs):
            return entry if name == "recruit_social_point_single" else None

        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "try_step", side_effect=_execute_step), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "wait_for_lobby", return_value=True), \
                patch.object(self.task, "find_one", side_effect=fake_find_one), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "get_box_by_name", return_value=result_box), \
                patch.object(self.task, "ocr", return_value=[confirm]), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "sleep"):
            self.task.run()
        self.assertTrue(self.task.is_done("recruit", "day"))
        clicked_features = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual(["gacha", "recruit_skip", "lobby"], clicked_features)  # 进入→跳过动画→返回大厅。
        clicked_boxes = [c.args[0] for c in click_box_mock.call_args_list]
        self.assertIs(entry, clicked_boxes[0])  # 点击友情点单抽入口。
        self.assertIs(confirm, clicked_boxes[1])  # 点击结果确定按钮。

    def test_sub_configs_skipped_when_disabled(self):
        # 两个子招募均关闭：只进出招募界面，不执行任何招募动作。
        self.task.config["友情点招募"] = False
        self.task.config["折扣普通招募"] = False
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "try_step", side_effect=_execute_step), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "wait_for_lobby", return_value=True), \
                patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "get_box_by_name", return_value=Box(200, 700, 500, 200, name="box_recruit_result")), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "sleep"):
            self.task.run()
        clicked_features = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual(["gacha", "lobby"], clicked_features)  # 两个子招募均关闭：只进出不招募。
        self.assertTrue(self.task.is_done("recruit", "day"))  # 无招募内容时流程仍完整走完并标记完成。

    def test_ordinary_recruit_clicks_confirm(self):
        # 折扣普通招募：首屏未找到入口→翻页→点入口→点确认→跳过动画→点确定。
        self.task.config["友情点招募"] = False
        self.task.config["折扣普通招募"] = True
        entry = Box(500, 500, 50, 30, confidence=1, name="recruit_ordinary_150")
        confirm = Box(1000, 900, 60, 30, confidence=1, name="确定")
        result_box = Box(200, 700, 500, 200, confidence=1, name="box_recruit_result")
        with patch.object(self.task, "ensure_screen", return_value=True), \
                patch.object(self.task, "try_step", side_effect=_execute_step), \
                patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", return_value=True), \
                patch.object(self.task, "wait_for_lobby", return_value=True), \
                patch.object(self.task, "find_one", side_effect=[None, entry]), \
                patch.object(self.task, "click_box") as click_box_mock, \
                patch.object(self.task, "get_box_by_name", return_value=result_box), \
                patch.object(self.task, "ocr", return_value=[confirm]), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "sleep"):
            self.task.run()
        clicked_features = [c.args[0] for c in click_mock.call_args_list]
        self.assertIn("recruit_next_page", clicked_features)  # 首屏未找到时翻页。
        self.assertIn("recruit_ordinary_confirm", clicked_features)  # 折扣招募先点确认。
        self.assertIn("recruit_skip", clicked_features)
        self.assertIn("lobby", clicked_features)
        self.assertIs(entry, click_box_mock.call_args_list[0].args[0])  # 入口框来自翻页后的匹配结果。
        self.assertTrue(self.task.is_done("recruit", "day"))

    def test_find_entry_exhausts_pages_returns_none(self):
        with patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "wait_click_feature", return_value=True), \
                patch.object(self.task, "sleep"):
            self.assertIsNone(self.task._find_recruit_entry("recruit_social_point_single"))

    def test_find_entry_stops_when_next_page_missing(self):
        # 翻到最后一页（无下一页按钮）仍找不到入口：结束查找并返回 None。
        with patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "wait_click_feature", return_value=False), \
                patch.object(self.task, "sleep"):
            self.assertIsNone(self.task._find_recruit_entry("recruit_social_point_single"))

    def test_social_point_recruit_raises_when_entry_missing(self):
        with patch.object(self.task, "_find_recruit_entry", return_value=None):
            with self.assertRaises(WaitFailedException):
                self.task._do_social_point_recruit()

    def test_click_recruit_result_retries_after_result_click(self):
        # 出金/new 时结果区识别不到「确定」：点击结果区一次后再识别（补充知识3）。
        confirm = Box(1000, 900, 60, 30, confidence=1, name="确定")
        result_box = Box(200, 700, 500, 200, confidence=1, name="box_recruit_result")
        with patch.object(self.task, "get_box_by_name", return_value=result_box), \
                patch.object(self.task, "ocr", side_effect=[[], [confirm]]), \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"):
            self.task._click_recruit_result()
        clicked = [c.args[0] for c in click_mock.call_args_list]
        self.assertEqual([result_box, confirm], clicked)  # 先点击结果区重试，再点击确定按钮。

    def test_click_recruit_result_raises_when_box_missing(self):
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")):
            with self.assertRaises(WaitFailedException):
                self.task._click_recruit_result()

    def test_click_recruit_result_raises_on_timeout(self):
        # 结果区始终识别不到「确定」：超时抛等待失败，由 try_step 恢复。
        result_box = Box(200, 700, 500, 200, confidence=1, name="box_recruit_result")
        with patch.object(self.task, "get_box_by_name", return_value=result_box), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "sleep"), \
                patch.object(self.task, "next_frame"):
            with self.assertRaises(WaitFailedException):
                self.task._click_recruit_result(time_out=0.01)

    def test_recruit_screen_registered(self):
        self.assertIn("recruit_page", self.task.screens)  # 招募界面已注册。
        self.assertEqual(["招募队员"], self.task.screens["recruit_page"]["keywords"])  # OCR 关键词判定。
        self.assertEqual("box_sub_pages_title", self.task.screens["recruit_page"]["ocr_box"])  # 限定标题区域。


if __name__ == '__main__':
    unittest.main()