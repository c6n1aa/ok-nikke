import unittest
from unittest.mock import patch

from ok.feature.Box import Box
from ok.task.exceptions import WaitFailedException
from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.screens import LOGIN_PAGE_PATTERN, SCREENS
from src.tasks.HarvestTask import HarvestTask


class TestScreenRecovery(TaskTestCase):
    task_class = HarvestTask

    config = config

    def setUp(self):
        self.set_image('tests/images/main.png')
        # 每个用例从干净的界面注册表开始，避免共享实例上残留其它用例注册的界面。
        self.task.screens = {}
        self.task.register_screen("lobby", features=["ark"])

    def test_global_screens_registry_matches_migrated_specs(self):
        # 集中式注册表收录全部 24 个界面：9 个迁移自任务 __init__、3 个竞技场界面、商店与方舟排名子页面、
        # 4 个拦截战界面、5 个前哨基地界面，外加冷启动正向锚点 login_page。
        # 顺序即 SCREENS 注册顺序（login_page 紧随 lobby）。
        expected = {
            "lobby": {"features": ["ark", "lobby"]},
            "login_page": {"keywords": [LOGIN_PAGE_PATTERN], "ocr_box": "box_enter_game"},
            "ark": {"features": ["ark_tribe_tower", "ark_simulation_room"]},
            "tribe_tower": {"features": ["tribe_tower_mark"]},
            "simulation_room": {"features": ["simulation_mark"]},
            "shop": {"keywords": ["百货商店"], "ocr_box": "box_sub_pages_title"},
            "cash_shop": {"keywords": ["付费商店"], "ocr_box": "box_sub_pages_title"},
            "coop_page": {"features": ["coop_page"]},
            "coop_nikke_select_page": {"features": ["coop_nikke_select_page"]},
            "solo_raid_page": {"features": ["solo_raid_page"]},
            "solo_raid_battle_team_select_page": {"features": ["solo_raid_battle_team_select_page"]},
            "arena": {"features": ["arena_page"]},
            "rookie_arena": {"features": ["rookie_arena_page"]},
            "special_arena": {"features": ["special_arena_page"]},
            "ark_ranking": {"features": ["ark_ranking_page"]},
            "interception_page": {"features": ["common_interception_active"],
                                  "keywords": ["拦截战"], "ocr_box": "box_sub_pages_title"},
            "anomaly_interception_page": {"features": ["anomaly_interception_page", "anomaly_interception_active"]},
            "common_interception_page": {"features": ["common_interception_page"]},
            "anomaly_interception_team_select_page": {"features": ["anomaly_interception_team_select_page"]},
            "outpost": {"features": ["command_center"], "keywords": ["前哨基地"], "ocr_box": "box_sub_pages_title"},
            "command_center": {"keywords": ["指挥中心"], "ocr_box": "box_sub_pages_title"},
            "advise": {"features": ["advise_page_icon"], "keywords": ["咨询"], "ocr_box": "box_sub_pages_title"},
            "advise_nikke": {"features": ["advise_detail_page", "advise_gift"]},
            "conversation": {"any_features": ["conversation_cancel", "conversation_log", "conversation_skip"],
                             "feature_box": "box_conversation_icon"},
        }
        self.assertEqual(list(expected), list(SCREENS))  # 顺序敏感：current_screen 按插入顺序首命中。
        self.assertEqual(expected, SCREENS)

    def test_register_screen_overrides_existing_entry(self):
        # 同名注册覆盖先前条目：任务私有注册以同样的方式覆盖基类加载的全局条目（后写者胜）。
        self.task.register_screen("lobby", features=["custom"])  # setUp 刚注册过 lobby，同名覆盖。
        self.assertEqual(["custom"], self.task.screens["lobby"]["features"])

    def test_is_screen_lobby_when_ark_present(self):
        self.assertTrue(self.task.is_screen("lobby"))

    def test_current_screen_returns_lobby(self):
        self.assertEqual("lobby", self.task.current_screen())

    def test_current_screen_none_when_no_screen_matches(self):
        # 只注册一个当前帧上不存在的界面，验证未命中时返回 None。
        self.task.screens = {}
        self.task.register_screen("好友页", features=["simulation_mark"])
        self.assertIsNone(self.task.current_screen())

    def test_register_screen_features_negative(self):
        self.task.register_screen("好友页", features=["simulation_mark"])
        self.assertFalse(self.task.is_screen("好友页"))

    def test_unregistered_screen_warns_and_returns_false(self):
        with patch.object(self.task, "log_warning") as warn_mock:
            self.assertFalse(self.task.is_screen("不存在"))
        warn_mock.assert_called_once()

    def test_wait_screen_raises_for_unregistered(self):
        with self.assertRaises(ValueError):
            self.task.wait_screen("未注册", time_out=1)

    def test_screen_ocr_keywords_with_region(self):
        self.task.register_screen("大厅ocr", keywords=["方舟"], ocr_box=[0.5, 0.5, 1, 1])
        self.assertTrue(self.task.is_screen("大厅ocr"))

    def test_screen_ocr_keywords_with_named_box(self):
        # ocr_box 传 coco 区域特征名时，按当前分辨率解析后以 box= 传入 ocr；
        # 缓存路径下 ocr 不再带 match（区域结果同帧共享），关键词由判定层等价过滤。
        fake_box = Box(100, 100, 50, 50, confidence=1, name="cash_shop_title")
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "ocr", return_value=[Box(100, 100, 50, 50, confidence=1, name="付费商店")]) as ocr_mock:
            self.task.register_screen("cash_shop", keywords=["付费商店"], ocr_box="cash_shop_title")
            self.assertTrue(self.task.is_screen("cash_shop"))
        ocr_mock.assert_called_once_with(box=fake_box)

    def test_screen_ocr_keywords_with_missing_named_box_falls_back_fullscreen(self):
        # 区域特征缺失时退化为全屏 OCR，不抛异常。
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")), \
                patch.object(self.task, "ocr", return_value=[Box(1, 1, 5, 5, name="付费商店")]) as ocr_mock:
            self.task.register_screen("cash_shop", keywords=["付费商店"], ocr_box="cash_shop_title")
            self.assertTrue(self.task.is_screen("cash_shop"))
        ocr_mock.assert_called_once_with()

    def test_screen_match_features_and_keywords_and(self):
        # features 与 keywords 同时配置时取「与」：特征命中且关键词命中才判定为该界面。
        fake_box = Box(100, 100, 50, 50, confidence=1, name="box_sub_pages_title")
        with patch.object(self.task, "find_one", return_value=Box(1, 1, 5, 5, name="ark_ranking")), \
                patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "ocr", return_value=[Box(100, 100, 50, 50, confidence=1, name="方舟")]) as ocr_mock:
            self.task.register_screen("方舟", features=["ark_ranking"], keywords=["方舟"], ocr_box="box_sub_pages_title")
            self.assertTrue(self.task.is_screen("方舟"))
        ocr_mock.assert_called_once_with(box=fake_box)

    def test_screen_match_features_and_keywords_fails_when_keyword_missing(self):
        # 特征命中但关键词未命中时判定不在该界面。
        fake_box = Box(100, 100, 50, 50, confidence=1, name="box_sub_pages_title")
        with patch.object(self.task, "find_one", return_value=Box(1, 1, 5, 5, name="ark_ranking")), \
                patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "ocr", return_value=[]):
            self.task.register_screen("方舟", features=["ark_ranking"], keywords=["方舟"], ocr_box="box_sub_pages_title")
            self.assertFalse(self.task.is_screen("方舟"))

    def _hit(self, name):
        return Box(1, 1, 5, 5, confidence=1, name=name)

    def test_absent_feature_blocks_match(self):
        # absent 消歧：消歧特征命中时判定失败；未命中时正常命中路径。
        self.task.register_screen("子集页", features=["simulation_mark"], absent=["ark"])
        with patch.object(self.task, "find_one", side_effect=lambda name: self._hit(name)):
            self.assertFalse(self.task.is_screen("子集页"))  # ark 命中 → 判负。
        self.set_image('tests/images/main.png')  # 换帧：两个场景相互独立（同帧内消歧命中会被缓存，属预期语义）。
        with patch.object(self.task, "find_one",
                          side_effect=lambda name: self._hit(name) if name == "simulation_mark" else None):
            self.assertTrue(self.task.is_screen("子集页"))  # 消歧特征未命中 → 正常判定。

    def test_any_features_any_hit_matches(self):
        # any_features 任一命中：任一特征命中即判定为该界面（与 features 的「全部命中」相对）；
        # feature_box 限定匹配区域（区域存在时走 find_one 直查路径，不经帧级特征缓存）。
        fake_box = Box(100, 100, 50, 50, confidence=1, name="box_conversation_icon")
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "find_one",
                             side_effect=lambda name, **kw: self._hit(name) if name == "conversation_log" else None):
            self.task.register_screen(
                "谈话", any_features=["conversation_cancel", "conversation_log", "conversation_skip"],
                feature_box="box_conversation_icon")
            self.assertTrue(self.task.is_screen("谈话"))  # 第二个特征命中即通过。
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "find_one", return_value=None):
            self.assertFalse(self.task.is_screen("谈话"))  # 全部未命中判负。

    def test_any_features_with_missing_feature_box_falls_back_fullscreen(self):
        # feature_box 缺失时退化为全屏匹配，不抛异常。
        with patch.object(self.task, "get_box_by_name", side_effect=ValueError("missing")), \
                patch.object(self.task, "find_one", side_effect=lambda name, **kw: self._hit(name)) as find_mock:
            self.task.register_screen("谈话", any_features=["conversation_cancel"], feature_box="box_conversation_icon")
            self.assertTrue(self.task.is_screen("谈话"))
        find_mock.assert_called_once_with("conversation_cancel")  # 区域缺失退化为无 box 的全屏查找。

    def test_any_features_with_keywords_and(self):
        # any_features 与 keywords 同配时取「与」：任一特征命中且关键词命中才判定为该界面。
        # 传 feature_box 走 find_one 直查路径（不经帧级特征缓存），两个场景才互不污染。
        fake_box = Box(100, 100, 50, 50, confidence=1, name="box_icon")
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "find_one",
                             side_effect=lambda name, **kw: self._hit(name) if name == "a_icon" else None), \
                patch.object(self.task, "ocr", return_value=[Box(0, 0, 5, 5, confidence=1, name="聊天")]):
            self.task.register_screen("联判", any_features=["a_icon", "b_icon"], keywords=["聊天"],
                                      ocr_box="box_icon", feature_box="box_icon")
            self.assertTrue(self.task.is_screen("联判"))
        with patch.object(self.task, "get_box_by_name", return_value=fake_box), \
                patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "ocr", return_value=[Box(0, 0, 5, 5, confidence=1, name="聊天")]):
            self.assertFalse(self.task.is_screen("联判"))  # 特征全部未命中，关键词命中也不算。

    def test_current_screen_respects_priority(self):
        # priority 仅影响 current_screen 遍历顺序：高优先级先返回；同优先级保持注册序。
        self.task.screens = {}
        self.task.register_screen("甲", features=["不存在A"])
        self.task.register_screen("乙", features=["不存在B"], priority=5)
        with patch.object(self.task, "find_one", return_value=Box(1, 1, 5, 5, confidence=1, name="hit")):
            self.assertEqual("乙", self.task.current_screen())  # 高优先级胜出。
            self.assertEqual(5, self.task.screens["乙"]["priority"])  # 扩展字段原样保留。

    def test_current_screen_same_priority_keeps_registration_order(self):
        self.task.screens = {}
        self.task.register_screen("先注册", features=["特征X"])
        self.task.register_screen("后注册", features=["特征Y"])
        with patch.object(self.task, "find_one", return_value=Box(1, 1, 5, 5, confidence=1, name="hit")):
            self.assertEqual("先注册", self.task.current_screen())  # 同为默认 0，注册序在前者返回。

    def test_wait_screen_min_frames_requires_consecutive_hits(self):
        # min_frames=2：单次 True 不算进入，需连续两轮 True 才返回。
        self.task.register_screen("抖动页", features=["特征Z"], min_frames=2)
        evals = []

        def fake_match(spec):
            evals.append(1)
            return [False, True, True, True][min(len(evals) - 1, 3)]

        with patch.object(self.task, "_screen_match", side_effect=fake_match), \
                patch.object(self.task, "sleep"):
            self.assertTrue(self.task.wait_screen("抖动页", time_out=30))
        self.assertGreaterEqual(len(evals), 3)  # 至少经历 False→True→True 三轮才通过。

    def test_transition_reclicks_when_swallowed(self):
        # 吞点击：第一次确认未命中时原地补点，第二次确认命中 → 不抛异常且点击了两次。
        attempts = {"n": 0}

        def fake_wait_screen(name, time_out=10, **kw):
            attempts["n"] += 1
            return attempts["n"] >= 2  # 第一次 False（动画吞点击），第二次 True。

        with patch.object(self.task, "wait_click_feature") as click_mock, \
                patch.object(self.task, "wait_screen", side_effect=fake_wait_screen):
            self.assertTrue(self.task.transition("目标页", click_feature="入口特征", retry_click=2))
        self.assertEqual(2, click_mock.call_count)  # 首次点击 + 一次原地补点。

    def test_transition_raises_with_context_after_exhausted(self):
        # 重试耗尽：每次确认都不命中 → 补满 retry_click 次后抛 WaitFailedException，消息含目标界面与当前识别结果，且保存失败截图。
        with patch.object(self.task, "wait_click_feature"), \
                patch.object(self.task, "wait_screen", return_value=False), \
                patch.object(self.task, "current_screen", return_value="别的界面") as cur_mock, \
                patch.object(self.task, "save_failure_screenshot") as shot_mock:
            with self.assertRaises(WaitFailedException) as ctx:
                self.task.transition("目标页", click_feature="入口特征", retry_click=2)
        self.assertIn("transition to 目标页 failed", str(ctx.exception))
        self.assertIn("current: 别的界面", str(ctx.exception))
        cur_mock.assert_called_once()  # 异常上下文里的当前界面识别只做一次。
        shot_mock.assert_called_once_with("目标页")

    def test_screen_match_features_and_keywords_fails_when_feature_missing(self):
        # 特征缺失时不进入 OCR 判定，直接判定不在该界面。
        with patch.object(self.task, "find_one", return_value=None), \
                patch.object(self.task, "ocr", side_effect=AssertionError("特征未命中不应 OCR")):
            self.task.register_screen("方舟", features=["ark_ranking"], keywords=["方舟"], ocr_box="box_sub_pages_title")
            self.assertFalse(self.task.is_screen("方舟"))

    def test_assert_screen_success(self):
        self.task.assert_screen("lobby", time_out=5)

    def test_assert_screen_raises_when_not_present(self):
        with patch.object(self.task, "wait_screen", return_value=None):
            with self.assertRaises(WaitFailedException):
                self.task.assert_screen("lobby", time_out=1)

    def test_try_step_success(self):
        calls = []

        def step():
            calls.append(1)

        with patch.object(self.task, "save_failure_screenshot") as shot_mock:
            result = self.task.try_step(step, name="成功步骤")
        self.assertTrue(result)
        self.assertEqual(1, len(calls))
        shot_mock.assert_not_called()

    def test_try_step_retries_then_raises(self):
        calls = []

        def step():
            calls.append(1)
            raise WaitFailedException("找不到特征")

        with patch.object(self.task, "_recover_to_lobby", return_value=True) as recover_mock, \
                patch.object(self.task, "save_failure_screenshot") as shot_mock, \
                patch.object(self.task, "sleep"):
            with self.assertRaises(WaitFailedException):
                self.task.try_step(step, name="失败步骤", retries=2)
        self.assertEqual(3, len(calls))
        self.assertEqual(2, recover_mock.call_count)
        self.assertEqual(3, shot_mock.call_count)

    def test_try_step_retries_then_success(self):
        calls = []

        def step():
            calls.append(1)
            if len(calls) < 3:
                raise WaitFailedException("暂时失败")

        with patch.object(self.task, "_recover_to_lobby", return_value=True) as recover_mock, \
                patch.object(self.task, "save_failure_screenshot"):
            result = self.task.try_step(step, name="恢复成功", retries=2)
        self.assertTrue(result)
        self.assertEqual(3, len(calls))
        self.assertEqual(2, recover_mock.call_count)

    def test_try_step_skip_on_fail(self):
        def step():
            raise WaitFailedException("失败")

        with patch.object(self.task, "_recover_to_lobby", return_value=True), \
                patch.object(self.task, "save_failure_screenshot"), \
                patch.object(self.task, "sleep"):
            result = self.task.try_step(step, name="跳过步骤", retries=1, raise_on_fail=False)
        self.assertFalse(result)

    def test_try_step_stops_when_recovery_fails(self):
        calls = []

        def step():
            calls.append(1)
            raise WaitFailedException("失败")

        with patch.object(self.task, "_recover_to_lobby", return_value=False) as recover_mock, \
                patch.object(self.task, "save_failure_screenshot"), \
                patch.object(self.task, "sleep"):
            with self.assertRaises(WaitFailedException):
                self.task.try_step(step, name="恢复失败步骤", retries=2)
        self.assertEqual(1, len(calls))
        self.assertEqual(1, recover_mock.call_count)

    def test_recover_to_lobby_clicks_home_feature(self):
        fake_home = Box(100, 100, 50, 50, confidence=1, name="common_home")
        with patch.object(self.task, "next_frame"), \
                patch.object(self.task, "dismiss_all_popups", return_value=False), \
                patch.object(self.task, "is_screen", return_value=False), \
                patch.object(self.task, "feature_exists", return_value=True), \
                patch.object(self.task, "find_one", return_value=fake_home) as find_mock, \
                patch.object(self.task, "click_box") as click_mock, \
                patch.object(self.task, "wait_for_lobby", return_value=True) as lobby_mock:
            result = self.task._recover_to_lobby()
        self.assertTrue(result)
        find_mock.assert_called_once_with("common_home")
        click_mock.assert_called_once()
        lobby_mock.assert_called_once_with(time_out=30, raise_if_not_found=False)

    def test_recover_to_lobby_skips_when_already_lobby(self):
        with patch.object(self.task, "next_frame"), \
                patch.object(self.task, "dismiss_all_popups", return_value=False), \
                patch.object(self.task, "is_screen", return_value=True), \
                patch.object(self.task, "feature_exists") as fe_mock, \
                patch.object(self.task, "wait_for_lobby") as lobby_mock:
            result = self.task._recover_to_lobby()
        self.assertTrue(result)
        fe_mock.assert_not_called()
        lobby_mock.assert_not_called()

    def test_close_overlay_require_click_raises_when_no_overlay(self):
        # 明确要求至少关闭一次遮罩，但 OCR 一直匹配不到时抛 WaitFailedException。
        with patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "sleep"):
            with self.assertRaises(WaitFailedException):
                self.task.close_overlay(time_out=0)

    def test_close_overlay_require_click_false_returns_false_when_no_overlay(self):
        # 容错模式（恢复流程）：没有遮罩可关时返回 False 而不抛异常。
        with patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "sleep"):
            result = self.task.close_overlay(time_out=0, require_click=False)
        self.assertFalse(result)

    def test_close_overlay_clicks_and_returns_true(self):
        # 找到遮罩点击一次后确认已关闭，返回 True。
        fake_box = Box(500, 700, 100, 40, confidence=1, name="overlay")
        with patch.object(self.task, "ocr", side_effect=[[fake_box], []]) as ocr_mock, \
                patch.object(self.task, "click_box") as click_mock:
            result = self.task.close_overlay(time_out=5)
        self.assertTrue(result)
        self.assertEqual(2, ocr_mock.call_count)  # 第一次命中并点击，第二次确认已关闭。
        self.assertEqual(1, click_mock.call_count)

    def test_dismiss_all_popups_no_popup_returns_true(self):
        # 没有弹窗可关且无完成条件时，等待直到超时后返回 True（与 close_overlay 语义一致）。
        with patch.object(self.task, "_try_close_one_popup", return_value=False) as close_mock:
            result = self.task.dismiss_all_popups(time_out=2)
        self.assertTrue(result)
        self.assertEqual(2, close_mock.call_count)  # 每轮检查一次，等满 time_out 秒。

    def test_dismiss_all_popups_fast_mode_returns_immediately(self):
        # wait_for_popup=False 时，当前帧无弹窗立即返回 True，不等待。
        with patch.object(self.task, "_try_close_one_popup", return_value=False) as close_mock, \
                patch.object(self.task, "sleep") as sleep_mock:
            result = self.task.dismiss_all_popups(wait_for_popup=False, time_out=5)
        self.assertTrue(result)
        close_mock.assert_called_once()  # 只检查一帧。
        sleep_mock.assert_not_called()  # 没有睡眠等待。

    def test_dismiss_all_popups_closes_until_clean(self):
        # 弹窗连续出现时逐个关闭，直到无弹窗返回 True。
        with patch.object(self.task, "_try_close_one_popup", side_effect=[True, True, False]) as close_mock, \
                patch.object(self.task, "next_frame"):
            result = self.task.dismiss_all_popups(time_out=5)
        self.assertTrue(result)
        self.assertEqual(3, close_mock.call_count)  # 关了两个后，第三次确认无弹窗。

    def test_dismiss_all_popups_max_passes(self):
        # 弹窗一直关不掉时达到轮次上限返回 False。
        with patch.object(self.task, "_try_close_one_popup", return_value=True), \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "log_warning") as warn_mock:
            result = self.task.dismiss_all_popups(time_out=5, max_passes=3)
        self.assertFalse(result)
        warn_mock.assert_called_once()  # 达轮次上限只记录一次并返回失败。

    def test_dismiss_all_popups_clear_condition_stops_early(self):
        # 指定完成条件时，无可关弹窗且条件满足即返回 True。
        with patch.object(self.task, "_try_close_one_popup", return_value=False), \
                patch.object(self.task, "sleep"):
            result = self.task.dismiss_all_popups(
                clear_condition=lambda: self.task.is_screen("lobby"), time_out=5)
        self.assertTrue(result)

    def test_dismiss_all_popups_closes_popup_before_honoring_clear_condition(self):
        # 遮罩下 lobby 特征可能仍命中：即使完成条件已满足，也必须先关完弹窗再返回。
        with patch.object(self.task, "_try_close_one_popup", side_effect=[True, False]) as close_mock, \
                patch.object(self.task, "next_frame"), \
                patch.object(self.task, "is_screen", return_value=True), \
                patch.object(self.task, "sleep"):
            result = self.task.dismiss_all_popups(
                clear_condition=lambda: self.task.is_screen("lobby"), time_out=5)
        self.assertTrue(result)
        self.assertEqual(2, close_mock.call_count)  # 第一轮先关弹窗，第二轮确认无弹窗后才认条件。


if __name__ == '__main__':
    unittest.main()