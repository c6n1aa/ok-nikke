import re  # 正则模块，用于 OCR 文字的部分匹配。

from ok.task.exceptions import WaitFailedException  # 框架等待失败异常，子流程断言失败时抛出由 try_step 捕获。

from src.tasks.NikkeBaseTask import NikkeBaseTask  # 项目基类，所有任务统一继承它。


class CashShopTask(NikkeBaseTask):  # 付费商店免费礼包领取任务，继承项目基类。

    done_keys = {  # 完成状态：STEP UP/每日免费礼包（日常刷新），每周（周常刷新），每月（月度刷新）。
        "cash_shop_stepup": "day",  # STEP UP 免费礼包日常完成状态。
        "cash_shop_daily": "day",  # 每日免费礼包日常完成状态。
        "cash_shop_weekly": "week",  # 每周免费礼包周常完成状态。
        "cash_shop_monthly": "month",  # 每月免费礼包月度完成状态。
    }

    # 普通礼包页签的 (OCR关键词, 完成状态键, 周期)，按 每日→每周→每月 顺序遍历。
    _ORDINARY_TABS = (  # 三个免费礼包页签的处理顺序。
        ("每日", "cash_shop_daily", "day"),  # 每日免费礼包。
        ("每周", "cash_shop_weekly", "week"),  # 每周免费礼包。
        ("每月", "cash_shop_monthly", "month"),  # 每月免费礼包。
    )

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "付费商店"  # 任务显示名称。
        self.description = "自动领取付费商店中STEP UP/每日/每周/每月的免费礼包。"  # 任务说明。

    def _get_box(self, name):  # 获取标注区域框，特征缺失时抛等待失败异常。
        try:  # coco 特征可能缺失。
            box = self.get_box_by_name(name)  # 获取指定标注区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失时置空。
            box = None  # 由下方统一判断。
        if box is None:  # 区域不可用。
            raise WaitFailedException(f"特征区域缺失: {name}")  # 抛异常由 try_step 捕获恢复。
        return box  # 返回区域框。

    def _enter_cash_shop(self):  # 从大厅进入付费商店。
        self.wait_click_feature("cash_shop", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击大厅付费商店入口。
        self.assert_screen("付费商店", time_out=10)  # 复用屏幕注册表确认已进入付费商店。

    def _switch_nav(self, feature_name):  # 在 box_cash_shop_nav_bar 区域内点击左侧导航项。
        nav_box = self._get_box("box_cash_shop_nav_bar")  # 获取导航栏标注区域。
        self.wait_click_feature(feature_name, box=nav_box, time_out=10, raise_if_not_found=True, after_sleep=1)  # 在导航栏内查找并点击目标导航项。

    def _do_stepup_pack(self):  # STEP UP 免费礼包：限时礼包页 → STEP UP 页签 → 免费按钮。
        self._switch_nav("cash_shop_nav_limited_time_package")  # 切换到限时礼包导航项。
        self.wait_feature("cash_shop_limited_time_package", time_out=10, raise_if_not_found=True)  # 确认已进入限时礼包页面。
        tab_bar = self._get_box("box_cash_shop_tab_bars")  # 获取页签栏标注区域。
        self.wait_click_ocr(box=tab_bar, match=re.compile("STEP UP"), time_out=10, raise_if_not_found=True, after_sleep=1)  # OCR 识别并点击 STEP UP 页签。
        free_box = self.wait_ocr(box=self._get_box("box_cash_shop_free_stepup"), match=re.compile("免费"), time_out=3, raise_if_not_found=False)  # 等待在免费购买按钮区域 OCR 识别“免费”。
        if free_box:  # 识别到免费按钮。
            self.click_box(free_box[0], after_sleep=1)  # 点击免费按钮购买礼包。
            self.dismiss_all_popups(time_out=10)  # 处理购买后出现的遮罩层（默认等待弹窗出现）。
            self.log_info("已领取 STEP UP 免费礼包。")  # 记录领取成功。
        else:  # 未识别到免费按钮（已领取或不可用）。
            self.log_info("STEP UP 免费礼包已领取，跳过。")  # 记录跳过原因。
        self.mark_done("cash_shop_stepup", "day")  # 标记 STEP UP 本日已完成。

    def _do_ordinary_packs(self):  # 每日/每周/每月免费礼包：普通礼包页 → 逐页签领取。
        self._switch_nav("cash_shop_nav_ordinary_package")  # 切换到普通礼包导航项。
        self.wait_feature("cash_shop_ordinary_package", time_out=10, raise_if_not_found=True)  # 确认已进入普通礼包页面。
        tab_bar = self._get_box("box_cash_shop_tab_bars")  # 获取页签栏标注区域。
        for keyword, done_key, period in self._ORDINARY_TABS:  # 依次处理每日/每周/每月页签。
            if self.is_done(done_key, period):  # 本周期已完成则跳过。
                continue  # 处理下一个页签。
            tab = self.wait_click_ocr(box=tab_bar, match=re.compile(keyword), time_out=10, raise_if_not_found=False, after_sleep=1)  # OCR 识别并点击当前页签。
            if tab is None:  # 当前页签不存在。
                self.log_warning(f"未找到{keyword}页签，跳过。")  # 记录跳过原因。
                continue  # 处理下一个页签。
            sold_out = self.wait_feature("cash_shop_free_package_sold_out", time_out=5, raise_if_not_found=False)  # 判断免费礼包是否售罄。
            if sold_out is None:  # 未售罄，可购买。
                buy_box = self._get_box("cash_shop_free_package_sold_out")  # 获取售罄标签标注区域作为购买按钮位置。
                self.click_box(buy_box, after_sleep=1)  # 点击购买免费礼包。
                self.dismiss_all_popups(time_out=10)  # 处理购买后出现的遮罩层（默认等待弹窗出现）。
                self.log_info(f"已领取{keyword}免费礼包。")  # 记录领取成功。
            else:  # 已售罄。
                self.log_info(f"{keyword}免费礼包已售罄，跳过。")  # 记录跳过原因。
            self.mark_done(done_key, period)  # 标记当前页签本周期已完成。

    def _exit_to_lobby(self):  # 退出付费商店返回大厅。
        home = self.find_one("common_home")  # 查找大厅按钮。
        if home is not None:  # 找到则点击返回大厅。
            self.click_box(home, after_sleep=1)  # 点击大厅按钮并等待。
        self.wait_for_lobby(time_out=10, raise_if_not_found=False)  # 等待确认回到大厅，超时不报错由上层处理。

    # ---- 合并子流程（re-entrant，由 try_step 包裹）----

    def _has_pending_packs(self):  # 是否存在本周期尚未领取的免费礼包。
        return any(  # 任一礼包未完成即返回 True。
            not self.is_done(key, period)  # 该礼包本周期未完成。
            for key, period in self.done_keys.items()  # 遍历全部完成状态项。
        )

    def _combined_step(self):  # 合并子流程：一次进店，先 STEP UP 再普通礼包，结束后统一退出。
        self._enter_cash_shop()  # 进入付费商店。
        if not self.is_done("cash_shop_stepup", "day"):  # STEP UP 本日未完成才处理。
            try:  # 单流程失败不中断整体。
                self._do_stepup_pack()  # 领取 STEP UP 免费礼包。
            except WaitFailedException as e:  # STEP UP 领取失败。
                self.log_warning(f"STEP UP 免费礼包领取失败，跳过：{e}")  # 记录失败并继续后续礼包。
        try:  # 普通礼包失败不中断整体。
            self._do_ordinary_packs()  # 领取每日/每周/每月免费礼包。
        except WaitFailedException as e:  # 普通礼包领取失败。
            self.log_warning(f"每日/每周/每月免费礼包领取失败，跳过：{e}")  # 记录失败并继续。
        self._exit_to_lobby()  # 统一退出回大厅。

    # ---- run 入口 ----

    def run(self):  # 任务执行入口，一次进店连续领取全部免费礼包。
        self.log_info("付费商店任务开始。")  # 记录任务开始。
        if not self.wait_until_lobby_after_start():  # 启动后等待进入游戏大厅，失败则中止。
            self.log_error("未能进入游戏大厅，中止付费商店任务。")  # 记录失败原因。
            return  # 结束本次执行。
        if not self._has_pending_packs():  # 全部免费礼包本周期已完成。
            self.log_info("付费商店免费礼包均已完成，跳过。")  # 记录跳过。
            return  # 结束本次执行。
        self.try_step(self._combined_step, name="付费商店", raise_on_fail=False)  # 合并子流程：进店→STEP UP→普通礼包→统一退出，失败不中断。
        self.log_info("付费商店任务完成。")  # 记录任务完成。
