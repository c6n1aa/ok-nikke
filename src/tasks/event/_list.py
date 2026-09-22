"""活动列表页处理：大厅 → 活动列表 → 逐位置滚动 → 用官方活动图 banner 匹配定位待处理活动。

进入活动主页后的子流程执行在 EventEntryMixin（_run_event_subflows），本模块只管「找到并进去」。
"""

from ok.task.exceptions import WaitFailedException  # 活动处理结束未回大厅等流程断言抛出的等待失败异常。

from src import event_calendar  # 本地日历快照与活动图（纯本地读取，快照过期才联网刷新）。

from src.tasks.event._const import _EVENT_ICON, _MAX_CARDS, event_identity, event_done_key


class EventListMixin:
    """活动列表页的遍历与进入。

    按日历的待处理活动逐个用 banner 匹配定位卡片行，进入并确认是活动后交给子流程；
    列表用带上限的滚动位置遍历，到底即停；卡片定位到即视为本日已处理，未匹配到的也落盘（未上架口径）。
    """

    def _process_event_list(self):  # 活动列表处理主循环：大厅→列表页→逐位置滚动→banner 定位待处理活动并进入处理，最后返回大厅。
        events = self._todo_events()  # 待处理活动：在架活动里本日尚未完成身份键的那些。
        if not events:  # 无日历数据或本日已全部处理完时不必进列表页。
            self.log_info("无待处理剧情活动（日历无数据或今日均已完成），结束列表处理")  # 记录结束原因。
            return  # 结束列表处理（由 run 统一收尾）。
        processed = set()  # 本运行内已处理的活动 key（双活动去重，不落持久状态）。
        unmatched = {event.key for event in events}  # 本运行尚未匹配到卡片的活动（遍历结束仍在 = 列表里没有）。
        for step in range(_MAX_CARDS):  # 带上限的滚动位置遍历。
            if not self._reposition_list(step):  # 进入列表页并滚动到第 step 位；到底返回 False 退出。
                self.log_info("列表已滚动到底，退出遍历")  # 记录到底。
                break  # 退出循环。
            for event in events:  # 扫描全部待处理活动（find_event_row 按 banner 匹配，未命中 = 该位置无此活动）。
                if event.key in processed:  # 已处理过则跳过。
                    continue  # 下一个活动。
                row = self._find_event_row(event)  # banner 匹配定位该活动所在行。
                if row is None:  # 当前滚动位置没有该活动。
                    continue  # 下一个活动。
                identity = event_identity(event.key)  # 列表路径拿到日历 key：身份权威，允许读写身份键。
                self._current_event = event  # 记录当前活动，供子流程失败恢复回大厅后重入时 banner 定位。
                self._event_identity = identity  # 子流程按它落身份化完成状态。
                self._identity_authoritative = True  # 权威身份：允许落盘。
                self._enter_and_probe(row)  # 点击进入并确认是活动，命中则执行子流程。
                self._current_event = None  # 处理结束清除上下文，避免下次重入定位到错误活动。
                self._event_identity = None  # 同步清除身份，避免后续流程误用别的活动的身份。
                self._identity_authoritative = False  # 身份权限同步复位。
                processed.add(event.key)  # 记录已处理。
                unmatched.discard(event.key)  # 已定位到卡片，不再算未匹配。
                # 卡片定位到即视为本日已处理（含命中卡片但未确认进入活动的误命中）：与旧版聚合键的落盘口径一致，
                # 避免下一次运行为了同一个活动再扫一遍列表。
                self.mark_done(event_done_key(identity), "day")  # 记录该活动本日已完成。
                self.log_info(f"活动 {identity} 本日完成状态已记录")  # 记录落盘键，便于排查串台。
                if not self._recover_to_lobby():  # 活动页返回键直接回大厅，此处确认已回大厅。
                    raise WaitFailedException("活动处理结束未回到大厅")  # 抛异常由 try_step 恢复。
                if not unmatched:  # 剩余待处理活动都已定位处理，没有第二张卡要扫，无需再进列表点 event_icon。
                    break  # 退出内层；外层随后依据 unmatched 为空提前结束。
                if not self._reposition_list(step):  # 返回大厅后重进列表并滚回本位置，继续扫描同位置剩余活动。
                    self.log_info("列表已滚动到底，退出遍历")  # 记录到底。
                    break  # 退出内层扫描。
            if not unmatched:  # 全部待处理活动均已定位处理，无需再往下滚动找卡片。
                break  # 提前结束遍历。
        for key in unmatched:  # 全部位置扫完仍未匹配到卡片：活动未上架/已下架，或保底包已过期。
            self.log_warning(f"活动 {key} 在列表页未匹配到卡片（未上架/已下架，或保底包已过期），本日不再重试")  # 记录便于排查。
            # 未匹配也按「本日已处理」落盘：否则此后每次运行都会为了这张不存在的卡片把列表重新扫一遍。
            self.mark_done(event_done_key(event_identity(key)), "day")  # 记录该活动本日已完成（未上架/已下架口径）。
        self._exit_to_lobby()  # 收尾返回大厅（run 里还会再幂等确认一次）。

    def _reposition_list(self, step):  # 进入列表页并滚动到第 step 个位置，返回是否定位成功（到底返回 False）。
        self._enter_event_list()  # 从大厅进入活动列表页。
        self._scroll_list_to_top()  # 先向上滚到底归一化到顶部。
        return step == 0 or self._scroll_list_down(step)  # 顶部位置无需下滚；下滚到底返回 False。

    def _enter_event_list(self):  # 大厅 -> 活动列表页（大厅右侧「活动」图标入口）。
        if self.is_screen("event_list_page"):  # 已在列表页（跨屏扫描连调 _reposition_list 时）则跳过：event_icon 是大厅图标，列表页上不存在，再点必超时。
            return  # 幂等：不重复点入口。
        self.transition("event_list_page", click_feature=_EVENT_ICON, wait_confirm=10, after_sleep=5)  # 点击入口并确认进入列表页。

    def _pending_events(self, refresh=True):  # 待处理剧情活动快照：本地读快照；快照缺失/过期时按 refresh 决定是否联网刷新。
        snapshot = event_calendar.load_snapshot()  # 应用启动已在后台静默刷新，纯本地读。
        if refresh and (snapshot is None or not snapshot.is_fresh(600)):  # 无快照或快照超过 600s TTL，且允许联网。
            snapshot = event_calendar.refresh()  # 刷新（内部含保底包兜底，不抛异常）。
        if snapshot is None:  # 不联网且没有本地快照（首次运行且离线）。
            return []  # 无本地数据即无待处理活动。
        return list(snapshot.pick_events(2))  # 按 start_time 倒序取最新 2 个未过期剧情活动（end_time=0 视为未知保留）。

    def _find_event_row(self, event):  # 用官方活动图在列表内 banner 匹配定位该活动所在行，返回行 Box 或 None。
        path = event_calendar.local_banner_path(event.key, event.url)  # 本地活动图路径（cache -> 保底包，纯本地）。
        if path is None:  # 无本地活动图（断网且不在保底包）。
            self.log_warning(f"活动「{event.display_name}」无本地活动图，无法定位")  # 记录跳过原因。
            return None  # 视为该活动当前不可定位。
        return self.find_event_row(event.display_name, path)  # 在 box_event_banner_area 内匹配该活动行。

    def _enter_event(self, row_box):  # 点击卡片进入活动主页并等菜单就绪；返回是否确认为活动（超时判非活动条目）。
        self.click_box(row_box, after_sleep=10)  # 点击卡片（10 秒覆盖过场动画与菜单稳定）。
        # 入场动画容忍 + 遮罩清理：特殊活动页面可能有入场动画或「点击任意处/跳过」遮罩，
        # 轮询期间每轮顺手清理遮罩（dismiss_all_popups 无遮罩立即返回），超时前不得判「非活动」。
        entered = self.wait_until(  # 轮询判定已进入活动主页（每轮取新帧）。
            lambda: self.is_screen("event_main"),  # event_main 判定（剩余时间关键词 OCR）。
            time_out=12,  # 动画容忍窗口 8~12s。
            pre_action=lambda: self.dismiss_all_popups(wait_for_popup=False, time_out=2),  # 期间清理入场遮罩。
        )
        if not entered:  # 超时未确认到活动主页 = 抽卡/登录奖励等非活动条目。
            self.log_info("未进入活动（抽卡/登录奖励等非活动条目）")  # 记录未确认原因。
            return False  # 由调用方决定退回大厅或抛异常。
        self.log_info("已进入活动主页，等待菜单栏就绪")  # 记录进入确认与后续等待。
        self._wait_menu_ready()  # 等菜单栏渲染并停稳再探测（标题先于菜单出现，过早探测会误判子流程全跳过）。
        return True  # 已确认为活动主页。

    def _enter_and_probe(self, row_box):  # 进入活动并执行子流程（列表处理路径）；返回是否确认为活动。
        if self._enter_event(row_box):  # 确认为活动主页（含菜单就绪等待）。
            self._run_event_subflows()  # 进入后按 _ENTRIES 探测各功能入口并执行。
            return True  # 已确认为活动并处理完子流程。
        self._recover_to_lobby()  # 退回大厅（活动页返回键直接回大厅，此处用恢复协议兜底）。
        return False  # 抽卡/登录奖励等非活动条目。

    def _locate_event_row(self, event):  # 在活动列表页内自上而下滚动定位指定活动的卡片行，返回行 Box；未找到返回 None。
        self._scroll_list_to_top()  # 归一到顶部再逐位下滚（进入列表页时可能停在任意滚动位置）。
        for _ in range(_MAX_CARDS):  # 带上限防死循环。
            row = self._find_event_row(event)  # banner 匹配定位该活动所在行。
            if row is not None:  # 当前滚动位置命中该活动。
                return row  # 返回可点击的行 Box。
            if not self._scroll_list_down(1):  # 下滚一位；到底返回 False。
                break  # 到底仍未命中。
        return None  # 遍历上限内未找到。
