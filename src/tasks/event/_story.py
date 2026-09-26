"""活动剧情流程：进关卡页 → 连续推图（跨换地区重新进页）→ 扫荡 → 返回活动菜单页。

推图的可用性一律界面后验（点开候选行看详情页「战斗」是否可用），解析层只给候选行；
大活动要先经 STORY I/II 剧情子页面才到关卡页，未开放的章节按亮度判据回落下一个入口。
"""

from ok.task.exceptions import WaitFailedException  # 入口缺失等流程断言抛出的等待失败异常。

from src.tasks.event._const import (
    _BATTLE_AFTER_SLEEP,
    _SD_ARRIVE_TIMEOUT,
    _STAGE_DETAIL_BATTLE_BOX,
    _STAGE_ENTER_TIMEOUT,
    _STORY_BATTLE_TIMEOUT,
    _STORY_FIELD_CHANGED_FEATURE,
    _STORY_FIELD_CHANGED_WAIT,
    _STORY_MAX_BATTLES,
    _STORY_MAX_PUSH_ROUNDS,
    _STORY_MENU_PATTERNS,
    _STORY_MODES,
    _SWEEP_CLOSE_FEATURE,
    _SWEEP_MAX_ROUNDS,
    _SWEEP_QUICK_BOX,
    _SWEEP_STAGE_DEFAULT,
)


class EventStoryMixin:
    """活动剧情推图链与扫荡链。

    推图自下而上找第一个能推的关卡点开，结算「下一关」可用则续战，直到门票耗尽；
    大活动清完一个地区会换地区（关卡流程结束、回到活动地区页），此时重新识别菜单页的剧情入口再推一轮。
    扫荡对配置的可重复关卡反复走快速战斗，直到详情页「快速战斗」灰白。
    """

    def _flow_story(self):  # 剧情流程（自足重入）：进关卡页 → 推图（剧情开关）→ 扫荡（扫荡开关）→ 返回活动菜单页。
        # 闸门：本流程从活动主页出发；失败恢复回大厅后由 _nav_to_event_main 用当前活动上下文
        # （大厅→列表→banner→活动主页）重新进入，不递归触发子流程（只进活动，不探测入口）。
        self._nav_to_event_main()  # 就位活动主页（正常已就位；恢复回大厅后由此重入）。
        mode = self.config.get("剧情模式", _STORY_MODES[0])  # 剧情关卡难度（配置项已隐藏，实现前保持默认）。
        if mode != _STORY_MODES[0]:  # 非默认值（历史配置残留或手改）：难度选择未实现。
            self.log_info(f"剧情模式 {mode} 暂未支持，按页面当前难度继续")  # TODO 实机标定 box_event_stage_mode 的选中态与点击。
        self._enter_stage_page()  # 活动菜单页 → 关卡页（大活动要经 STORY I/II 剧情子页面绕一级）。
        if self.config.get("剧情"):  # 推图开关（与扫荡独立，任一开启都进关卡页）。
            for round_index in range(1, _STORY_MAX_PUSH_ROUNDS + 1):  # 换地区后要重新进关卡页再来一轮（带上限防死循环）。
                if round_index > 1:  # 第 2 轮起：上一轮以换地区收尾，当前在活动地区页，需重新识别菜单页的剧情入口。
                    self.log_info(f"第 {round_index} 轮推图：重新识别菜单页并进入关卡页")  # 记录轮次与重新进入的原因。
                    self._enter_stage_page()  # 活动地区页 → 关卡页（入口与 STORY 章节重新定位，新地区可能解锁了下一章）。
                if self._push_stages():  # 本轮推图收工（无可推关卡/门票耗尽/战斗失败）。
                    break  # 结束推图。
                # False = 出现换地区提示并已点掉：当前在活动地区页，进入下一轮（重新进关卡页）。
            else:  # 轮次用尽仍在换地区 = 异常状态。
                self.log_warning(f"推图达到轮次上限 {_STORY_MAX_PUSH_ROUNDS} 轮，停止推图")  # 记录异常，交由后续界面断言兜底。
                return  # 当前是活动地区页（不是关卡页）：直接结束子流程，免得在错误页面上做扫荡/导航。
        if self.config.get("扫荡"):  # 扫荡开关：对配置的可重复关卡快速战斗。
            self._sweep_stage(self.config.get("扫荡关卡", _SWEEP_STAGE_DEFAULT))  # 点行 → 详情页快速战斗（次数拉满）→ 扫到不可用。
        try:  # 点返回回活动菜单页，供后续子流程接续（大活动剧情子页面多退一级）。
            self._ensure_event_menu()
        except WaitFailedException:  # 往期活动/档案馆页面退不回活动菜单页：剧情已经推进完，不该把整条剧情判失败。
            self.log_warning("剧情收尾未能退回活动菜单页（可能是往期活动/档案馆页面），按当前页面继续")  # 记录降级原因。

    def _enter_stage_page(self):  # 活动菜单页 → 关卡页：小活动直接用「加成」入口进，大活动先经 STORY I/II 剧情子页面。
        entry = self._entry_box("剧情")  # 剧情入口命中框（大活动菜单页 STORY II → STORY I，小活动主页「加成」）。
        if entry is None:  # 入口缺失（页面结构变化或菜单未渲染）。
            raise WaitFailedException("未找到剧情入口")  # 抛异常由 try_step 恢复。
        if self._is_story_main_entry(entry):  # 大活动菜单页：STORY I/II 打开的是剧情子页面而非关卡页。
            self._enter_story_sub_page()  # 逐个尝试 STORY 入口（STORY II 优先，未开放的章节回落下一个入口）。
            entry = self._entry_box("剧情")  # 子页面内重新定位剧情入口（与小活动同款）。
            if entry is None:  # 子页面内没有剧情入口（未渲染完或该期页面结构不同）。
                raise WaitFailedException("剧情子页面内未找到剧情入口")  # 抛异常由 try_step 恢复。
        self.transition("event_stage_page", box=entry, wait_confirm=10, after_sleep=1)  # 点击剧情入口并确认进入关卡页。

    def _push_stages(self):  # 连续推图链：自下而上找第一个能推的关卡并点开 → 逐场战斗（结算「下一关」可用则续战，跳到门票耗尽）→ 回关卡页。
        """返回本轮推图是否收工：True = 正常结束（无可推关卡/门票耗尽/战斗失败）；False = 出现换地区提示并已点掉。

        False 时当前界面是「活动地区」页（关卡页已消失），调用方需重新识别菜单页的剧情入口、
        重新进关卡页再推一轮（见 _flow_story 的轮次循环）。
        """
        if not self._open_pushable_stage():  # 自下而上找可推关卡并点开（没有就说明本地区推完了）。
            return True  # 结束推图（仍在关卡列表页，无需收尾动作）。
        for _ in range(_STORY_MAX_BATTLES):  # 连续战斗安全上限（正常由门票耗尽自然结束）。
            self._skip_story_if_present()  # 进关卡/进下一关可能先播剧情：识别并点跳过。
            if self._field_changed_stop():  # 跳过剧情后可能已换地区：本轮到此为止，交调用方重推一轮。
                return False  # 已回到活动地区页：交调用方重新进关卡页再推一轮。
            result, confirm_box = self.wait_battle_finish(time_out=_STORY_BATTLE_TIMEOUT)  # 节流等待战斗结束，只检测不点击。
            if result is None:  # 等待战斗结束超时。
                if self._field_changed_stop():  # 兜底：换地区比预想晚（战斗根本没开起来）时，别白等满超时再判失败。
                    return False  # 已回到活动地区页：交调用方重新进关卡页再推一轮。
                raise WaitFailedException("等待活动关卡战斗结束超时")  # 抛异常由 try_step 恢复。
            if result == "failed":  # 战斗失败（门票已消耗，不再续战）。
                self.log_warning("活动关卡战斗失败")  # 记录失败供排查。
                self.click_box(confirm_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 点击失败返回按钮。
                self._skip_story_if_present()  # 返回时也可能先播剧情。
                if self._field_changed_stop():  # 失败返回后同样可能换地区。
                    return False  # 已回到活动地区页。
                break  # 结束推图。
            next_box = self._optional_box("box_battle_finish_next_stage")  # 结算界面右下角「下一关」区域（缺失按不可用）。
            if next_box is not None and self.is_feature_enabled(next_box):  # 彩色高亮 = 还有门票可续战。
                self.log_info("结算界面「下一关」可用，继续推进")  # 记录续战。
                self.click_box(next_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 点击下一关，回到循环头部等待下一场。
                # 实机：点「下一关」后也可能直接切地区（不经过剧情/战斗）——这里紧跟一次判定，别等满 240s 超时。
                if self._field_changed_stop():
                    return False  # 已回到活动地区页：交调用方重新进关卡页再推一轮。
                continue  # 续战。
            self.click_box(confirm_box, after_sleep=_BATTLE_AFTER_SLEEP)  # 「下一关」不可用 = 门票耗尽，点击结算返回按钮。
            self._skip_story_if_present()  # 返回时也可能先播剧情。
            if self._field_changed_stop():  # 结算返回后同样可能换地区。
                return False  # 已回到活动地区页。
            break  # 推图结束。
        else:  # 循环用尽仍未自然结束 = 异常状态。
            self.log_warning(f"连续战斗达到上限 {_STORY_MAX_BATTLES} 场，停止推图")  # 提示异常，交界面断言兜底。
        self.assert_screen("event_stage_page", time_out=15)  # 确认已回到活动关卡界面（剧情跳过后的落点）。
        return True  # 本轮推图收工。

    def _field_changed_stop(self, time_out=_STORY_FIELD_CHANGED_WAIT):  # 是否发生换地区：True = 需重新进关卡页再推一轮。
        """大活动（FieldHub）清完一个地区后切到新地区，两个信号任一成立即算（都不依赖时间假设）：

        ① 提示按钮 `event_story_field_changed` 在画面上 → 点掉它（点完回到活动地区页）；
        ② 人已经回到「活动地区」页 → 关卡流程已结束——按钮可能没渲染出来，也可能刚被跳过剧情的
           弹窗清理顺手点掉，所以不能只认按钮（实机：按钮会出现在「战斗结束 → 点击下一关」之后）。
        按钮只可能在「战斗已结束/未开始」时出现，故在战斗界面内不等待（不拖慢正常推图）。
        """
        if not self.feature_exists(_STORY_FIELD_CHANGED_FEATURE):  # coco 未标注：只认状态信号（旧包/未标定也能跑）。
            return self._stop_on_event_area_page()  # 只看是否已回到活动地区页。
        hit = self._wait_field_changed_hit(time_out)  # 取提示按钮：当前帧命中即返回，必要时给一小段出现窗口。
        if hit is not None:  # 提示在画面上：点掉它（点完自动回活动地区页），需要重推一轮。
            self.log_info("识别到活动地区切换提示，点击返回活动地区页")  # 记录动作，便于核对换地区时机。
            self.click_box(hit, after_sleep=_BATTLE_AFTER_SLEEP)  # 点击提示按钮（等待覆盖切页动画）。
            return True  # 需要重推一轮。
        return self._stop_on_event_area_page()  # 按钮没看到：再看是否已经回到活动地区页。

    def _stop_on_event_area_page(self):  # 是否已回到「活动地区」页 = 关卡流程已结束（换地区，或异常退出）。
        if not self._probe_event_main():  # 仍在关卡页/战斗/对话等：没有换地区。
            return False  # 不处理。
        self.log_info("已回到活动地区页（关卡流程结束），按换地区收尾，重新进关卡页再推一轮")  # 记录判据来源便于实机核对。
        return True  # 需要重推一轮。

    def _wait_field_changed_hit(self, time_out):  # 取换地区提示按钮：当前帧命中即返回；不在战斗界面才等一小段。
        try:  # 特征名在配置里但模板加载失败时按不出现处理。
            hit = self.find_one(_STORY_FIELD_CHANGED_FEATURE)  # 即时：帧上就有，零额外等待。
            if hit is not None or self._in_battle_page():  # 已命中，或正在战斗（提示不可能在场）：不进等待。
                return hit  # 返回当前结果（None = 没命中）。
            return self.wait_feature(_STORY_FIELD_CHANGED_FEATURE, time_out=time_out, settle_time=0,  # 命中即返回，不等稳定窗口。
                                     raise_if_not_found=False,  # 不在战斗：提示可能正在渲染，给一小段出现窗口。
                                     post_action=self._story_poll_throttle)  # 轮询节流（见 _STORY_POLL_INTERVAL）。
        except ValueError:  # 特征缺失/模板加载失败。
            return None  # 按不出现处理。

    def _open_pushable_stage(self):  # 自下而上找第一个能推的关卡并点开：进到关卡流程（剧情/战斗）返回 True，全不可推返回 False。
        """可用性一律走界面后验：候选行上的 CLEAR / REPEAT / 锁图标既不参与解析也不作门槛
        （实机会漏检，锁孔还会被读成编号），逐个点开看详情页「战斗」是否可用。

        只看当前屏：点剧情入口进关卡页后列表停在当前进度关，能推的关就在这一屏里，故不滚动、不跨屏扫描。
        当前屏有候选行但都点不出可推的关 = 本地区推完了。扫荡目标不同（已通关的关卡可能在当前屏外），
        故 `_locate_stage_row` 会滚动查找。
        """
        box = self._stage_list_box()  # 列表区。
        rows = self._stage_rows(box) if box is not None else []  # 当前屏候选行（行框即当前屏坐标）。
        if self._open_first_pushable(rows):  # 自下而上找（最下面的候选行最接近当前进度关）。
            return True  # 已进入关卡流程。
        if not rows:  # 一行都没解析出：多半是 OCR 漏检/页面没就绪，而不是真的没得推。
            self.log_warning("当前屏未解析出任何关卡行（OCR 漏检或页面未就绪），推图结束")  # 与「有行但都不可推」分开记，便于实机排查。
            return False  # 本地区按推完收工（列表停在当前进度关，不滑动查找）。
        self.log_info("当前屏没有可推的关卡（已全通或未开放），推图结束")  # 记录结束原因。
        return False  # 本地区推完（列表停在当前进度关，不滑动查找）。

    def _open_first_pushable(self, rows):  # 自下而上逐个点开候选行，命中可推关卡返回 True；都不可推返回 False。
        for row in reversed(rows):  # 最下面的候选行最接近当前进度关（列表顺序 = 解锁顺序）。
            if row.stage_id is None:  # 没有编号的行点不中（编号漏检时序列共识会补号，补不出来就不试）。
                continue
            opened = self._open_row_for_push(row)  # 点开并判态。
            if opened:  # 已在关卡流程里（或「战斗」已点）。
                return True  # 命中可推关卡。
            if opened is None:  # 可推性判不了（详情页区域特征缺失）：每行都会卡在同一处，不再往下试。
                return False  # 结束本轮找关卡。
        return False  # 这一屏没有可推的关。

    def _open_row_for_push(self, row):  # 点开候选行判可推性：可推/已开战返回 True、不可推返回 False、判不了返回 None。
        self.click_box(self._row_box(row), after_sleep=2)  # 点击关卡行进入关卡（可能先播剧情）。
        landing = self._stage_landing()  # 等落点分类（离开列表不等于进了关卡流程，见 _stage_landing）。
        if landing == "list":  # 仍停在关卡列表 = 该关不可推（已通关不可重复挑战/未解锁，只弹提示）。
            self.log_info(f"{row.stage_id} 点开后仍停在关卡列表（已通关不可重复挑战或未解锁），试上一行")  # 记录跳过原因。
            return False  # 列表没动，继续试上一行。
        if landing == "flow":  # 直接进了剧情/战斗 = 这一关就是当前进度关（首次进关先播剧情）。
            self.log_info(f"{row.stage_id} 点开后直接进入关卡流程（剧情/战斗），按当前进度关推进")  # 记录选中原因。
            return True  # 已在流程里，交给战斗链。
        if landing is None:  # 落点没认出来（过场卡住/未知页面）：判不了可推性。
            self.log_warning(f"{row.stage_id} 点开后未识别到关卡流程落点（详情页/剧情/战斗/列表），停止找关卡")  # 记录跳过原因。
            return None  # 交调用方停止找关卡（每行都会卡在同一处）。
        battle_box = self._optional_box(_STAGE_DETAIL_BATTLE_BOX)  # 详情页「战斗」区域（缺失按不可点）。
        if battle_box is None:  # 区域特征解析不出来（coco 缺失/加载失败）。
            self.log_warning(f"缺少区域特征 {_STAGE_DETAIL_BATTLE_BOX}，推图结束")  # 记录跳过原因。
            self._close_stage_detail()  # 关详情页回关卡列表。
            return None  # 判不了可推性：交调用方停止找关卡。
        if not self.is_feature_enabled(battle_box):  # 灰白禁用：该关不可推（门票耗尽/已通关不可重复挑战）。
            self.log_info(f"{row.stage_id} 详情页「战斗」为灰白禁用态（门票耗尽等），试上一行")  # 记录结束原因。
            self._close_stage_detail()  # 关详情页回关卡列表（下一行还要在列表上点）。
            return False  # 继续试上一行。
        self.log_info(f"{row.stage_id} 详情页「战斗」可用，点击进入战斗")  # 记录推进（可能先播剧情）。
        self.click_box(battle_box, after_sleep=2)  # 点「战斗」进入战斗链。
        return True  # 已开战。

    def _sweep_stage(self, stage_id):  # 扫荡：点配置关卡行 → 详情页「快速战斗」（次数拉满）→ 结算回列表，循环到不可用（耗尽）。
        for round_index in range(1, _SWEEP_MAX_ROUNDS + 1):  # 带上限防死循环（次数拉满后正常一轮即耗尽）。
            row = self._locate_stage_row(stage_id)  # 定位配置关卡（当前屏没有会滚动查找；行框对应当前屏幕，可直接点击）。
            if row is None:  # 整份列表都没有该关 = 该关尚未通关/未开放（不是识别失败），不做任何降级替代。
                self.log_warning(f"列表中没有可扫荡关卡 {stage_id}（尚未通关/未开放），跳过扫荡")  # 记录跳过原因。
                return  # 结束扫荡。
            # 行上的已通关标记（√ / CLEAR / REPEAT）一律不看、也不解析：能否扫荡以关卡详情页的
            # 「快速战斗」判态为准（门票用光时详情页仍可打开）。
            self.click_box(self._row_box(row), after_sleep=2)  # 点关卡行进入关卡详情页。
            if not self.wait_feature(_SWEEP_CLOSE_FEATURE, time_out=_STAGE_ENTER_TIMEOUT, raise_if_not_found=False):  # 等详情页就位（右上关闭按钮特征）。
                self.log_info(f"{stage_id} 点开后未进入关卡详情页（已通关但不可重复挑战会弹提示、停在列表），跳过扫荡")  # 记录跳过原因。
                return  # 仍在关卡列表页：无需关页，直接结束扫荡（交由调用方回菜单页）。
            quick_box = self._optional_box(_SWEEP_QUICK_BOX)  # 「快速战斗」区域。
            if quick_box is None:  # 区域特征解析不出来（coco 缺失/加载失败）——与「按钮不可用」是两种问题，分开记日志。
                self.log_warning(f"缺少区域特征 {_SWEEP_QUICK_BOX}，跳过扫荡")  # 记录跳过原因。
                self._close_stage_detail()  # 关闭详情页回列表。
                return  # 结束扫荡。
            enabled = self.is_feature_enabled(quick_box)  # 色彩判态：彩色=可用，灰白=禁用。
            self.log_debug(f"{stage_id}「快速战斗」区域 {quick_box}，色彩判态 {enabled}")  # 判态明细便于实机校准。
            if not enabled:  # 灰白禁用：门票已被推图耗尽，或该关当前不可重复挑战。
                self.log_info(f"{stage_id}「快速战斗」为灰白禁用态（与剧情共用门票，可能已被推图耗尽；或该关不可重复挑战），扫荡结束")  # 记录结束原因。
                self._close_stage_detail()  # 关闭详情页回列表。
                return  # 结束扫荡。
            self._run_quick_battle(quick_box, label=f"扫荡 {stage_id} 第 {round_index} 轮")  # 快速战斗链（拉满 → 开始 → 等结算 → 点确认）。
            if self._detail_page_open():  # 结算关闭后落回关卡详情页（扫荡页面的默认落点）。
                self._close_stage_detail()  # 先关详情页退回活动关卡列表，下一轮重新定位关卡行。
            self.assert_screen("event_stage_page", time_out=15)  # 确认已回到活动关卡列表界面。
        self.log_warning(f"扫荡达到轮次上限 {_SWEEP_MAX_ROUNDS} 轮，结束")  # 上限兜底（异常状态）。

    def _story_entry_boxes(self):  # 菜单页各 STORY 入口命中框（按 _STORY_MENU_PATTERNS 优先级：STORY II → STORY I）；未出现的跳过。
        entries = []  # 候选入口命中框。
        for pattern in _STORY_MENU_PATTERNS:  # 优先级即列表顺序。
            box = self._entry_box("剧情", patterns=[pattern])  # 只按该关键词定位（STORY I/II 同时出现时是两个独立入口）。
            if box is not None:  # 该入口出现在菜单栏（未开放的章节也会被 OCR 读到文字）。
                entries.append(box)  # 收集候选。
        return entries  # 至多两个。

    def _enter_story_sub_page(self):  # 点开 STORY 入口进入剧情子页面：STORY II 优先，点不开的章节回落下一个入口。
        # STORY I/II 会同时出现在菜单栏，未开放的章节只多了锁图标、文字仍是灰字（OCR 照常读到），
        # 点它不会切页；只认第一个命中框会让「锁一个入口」拖垮整条剧情链（含 STORY I 的推图与扫荡）。
        for entry_box in self._story_entry_boxes():  # 候选按优先级：STORY II → STORY I。
            if self._entry_locked(entry_box):  # 亮度前置判断：整行灰暗 = 锁定入口，跳过省掉一次 _SD_ARRIVE_TIMEOUT 空等。
                self.log_info(f"{entry_box.name} 亮度判据为锁定态（整行灰暗），跳过并尝试下一个剧情入口")  # 记录跳过原因。
                continue  # 下一个候选。
            if self._try_enter_story_sub_page(entry_box):  # 点开并等剧情子页面就位。
                return  # 已进入剧情子页面。
            if not self.is_screen("event_main"):  # 点开后不在活动菜单页（锁定提示等落点）：先退回菜单页再试下一个候选。
                self._ensure_event_menu()  # 逐级退回菜单页。
        raise WaitFailedException("STORY 入口均不可用（章节未开放或页面结构变化）")  # 抛异常由 try_step 恢复。

    def _try_enter_story_sub_page(self, entry_box):  # 点 STORY 入口并等剧情子页面就位，返回是否成功。
        # 子页面左上标题同为「剧情活动」（event_main 判定命中）、没有活动菜单，没有可用于 wait_screen 的独有判据，
        # 故反向判就位：小活动同款剧情入口（「加成」）出现即子页面可操作（同签到页反向判切页）。
        self.click_box(entry_box, after_sleep=2)  # 点击 STORY 入口切页。
        ready = self.wait_until(lambda: self._story_sub_entry_ready(),  # 轮询等剧情入口出现（每轮取新帧）。
                                time_out=_SD_ARRIVE_TIMEOUT, settle_time=1.5)  # 命中后再稳定 1.5s，吸收切页动画里按钮仍位移的过渡期。
        if not ready:  # 窗口内未出现剧情子页面入口 = 该章节未开放/不可用。
            self.log_warning(f"{entry_box.name} 点开后未进入剧情子页面（章节未开放/不可用）")  # 记录回落原因。
        return ready  # 交由调用方决定回落下一个入口。

    def _story_sub_entry_ready(self):  # 剧情子页面就位判据：出现小活动同款剧情入口（STORY I/II 入口只在大活动菜单页）。
        entry = self._entry_box("剧情")  # 当前页面的剧情入口。
        return entry is not None and not self._is_story_main_entry(entry)  # 命中「加成」类入口即子页面已可操作。
