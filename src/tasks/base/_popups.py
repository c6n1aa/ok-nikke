import os  # 操作系统路径模块，处理公告/登录奖励等模板文件的绝对路径。
import re  # 正则模块，用于弹窗提示文字的部分匹配。
import time  # 时间模块，处理弹窗清理等待与超时。

from ok.feature.Box import Box  # 检测框对象，用于构造关闭按钮/领取按钮的搜索区域。
from ok.task.exceptions import TaskDisabledException, WaitFailedException  # 任务被停止与等待失败异常。


class PopupsMixin:
    """弹窗/遮罩统一清理：公告横幅、卢比限时特卖、登录奖励面板与各类领奖遮罩。

    统一入口 `dismiss_all_popups` 循环调用 `_try_close_one_popup`；新增弹窗只挂
    后者（`_close_xxx_popup` 每次只走一步，多段由外层逐轮推进）。
    """

    _NOTICE_BELL_TEMPLATES = (  # 公告弹窗铃铛模板列表：公告(notice_bell1)与活动(notice_bell2)弹窗图标样式略有差异，依次尝试任一命中即可。
        os.path.join('assets', 'template', 'common', 'notice_bell1.png'),  # 活动弹窗铃铛模板，来自 2560x1440 截图。
        os.path.join('assets', 'template', 'common', 'notice_bell2.png'),  # 公告弹窗铃铛模板，来自 2560x1440 截图。
    )
    _COMMON_CLOSE_TEMPLATE = os.path.join('assets', 'template', 'common', 'common_close.png')  # 通用关闭按钮模板，来自 2560x1440 截图。
    # 登录奖励（DAILY LOGIN）弹窗判据：七天制小型登录奖励每期面板皮肤不同，判据一律取
    # 不受皮肤影响的部分——「全部领取」认文字（OCR），关闭按钮认 X 图形（模板只留图形本身）。
    _DAILY_LOGIN_CLAIM_ALL_TEXT = re.compile("全部领取")  # 「全部领取」按钮文字，OCR 部分匹配（兼容拆框/噪声）。
    _DAILY_LOGIN_CLAIM_PAD = (0.2, 0.36)  # 文字框外扩比例（宽, 高）：OCR 只框到白字，外扩取到按钮底色才能判断可领与否；用比例而非固定像素，保证各分辨率下都不超出按钮本体。
    _DAILY_LOGIN_CLOSE_TEMPLATES = (  # 面板右上角关闭 X 模板列表；出现新皮肤样式时追加即可，依次尝试任一命中。
        os.path.join('assets', 'template', 'daily_login', 'daily_login_close.png'),  # 来自 2560x1440 截图。
    )

    # 遮罩提示文字 OCR 关键词：框架对字符串是全等匹配，OCR 常把提示拆成多个文本框
    # （如实测「点击进行下一步」被拆成「点击进行下一」+「步」），一律用正则走部分匹配。
    _MASK_CLAIM_PATTERN = re.compile("点击领取奖励")  # 领奖遮罩提示。
    _MASK_ANYWHERE_PATTERN = re.compile("点击任意处")  # 点击任意处关闭遮罩提示。
    _CLICK_TO_PROCEED_PATTERN = re.compile("点击进行")  # 「点击进行下一步」好感度提升等遮罩提示。

    def _close_notice_popup(self):
        """在屏幕中上部依次尝试多个公告铃铛模板，命中后向右延伸查找通用关闭按钮并点击，返回是否成功点击。"""
        bell = None  # 初始化铃铛匹配结果。
        for template_path in self._NOTICE_BELL_TEMPLATES:  # 依次尝试每个铃铛模板。
            bell = self.find_scaled_template(  # 在屏幕中上部查找当前铃铛模板。
                "notice_bell", template_path,  # 使用模板并命名匹配结果。
                threshold=0.75,  # 铃铛图标在不同弹窗间样式有差异，阈值放宽到 0.75 提高命中率。
                box=self.box_of_screen(0.258, 0.05, 0.75, 0.5),  # 限定 x 约25.8%-75%（2560x1440 下约 660-1920 像素）、y 5%-50% 的屏幕中上部区域。
            )
            if bell is not None:  # 当前模板命中铃铛。
                break  # 停止尝试后续模板。
        if bell is None:  # 所有模板均未命中，当前帧无公告横幅。
            return False  # 返回未命中，让上层继续后续流程。
        close_region = Box(  # 从公告横幅右侧延伸到屏幕右边缘作为关闭按钮搜索区域。
            bell.x + bell.width,  # 从铃铛右边缘开始。
            max(0, bell.y - bell.height),  # 上扩一个铃铛高度，允许垂直方向轻微误差。
            self.width - (bell.x + bell.width),  # 水平方向延伸到屏幕右边缘。
            bell.height * 3,  # 垂直范围取铃铛高度的三倍，覆盖同高度附近的关闭按钮。
            name="notice_close_region",  # 搜索区域名称，用于日志/调试。
        )
        close = self.find_scaled_template(  # 在公告横幅右侧查找通用关闭按钮。
            "common_close", self._COMMON_CLOSE_TEMPLATE, box=close_region,  # 仅在右侧区域搜索。
        )
        if close is None:  # 找不到关闭按钮（可能不是公告弹窗）。
            return False  # 返回未命中，跳过本轮关闭。
        self.click_box(close, after_sleep=1)  # 点击关闭按钮并等待弹窗关闭动画完成。
        self.log_info("已关闭公告/活动弹窗。")  # 记录关闭动作。
        return True  # 返回成功，供上层继续检测大厅。

    def _close_rupee_flash_sale_popup(self):
        """处理卢比限时特卖（Rupee Flash Sale）弹窗：优先点关闭确认，否则点入口横幅，返回是否已处理。

        该弹窗为两段式：先出现入口横幅 rupee_flash_sale，点击后弹出详情弹窗，
        需再识别 rupee_flash_sale_close_confirm 点击关闭。每次只处理一步，
        由 dismiss_all_popups 逐轮调用完成整段流程。
        """
        confirm = self.find_one("rupee_flash_sale_close_confirm")  # 优先识别详情弹窗的关闭确认按钮。
        if confirm is not None:  # 详情弹窗已打开。
            self.click_box(confirm, after_sleep=1)  # 点击关闭确认按钮关闭详情弹窗。
            self.log_info("已关闭卢比限时特卖弹窗。")  # 记录关闭动作。
            return True  # 返回已处理。
        banner = self.find_one("rupee_flash_sale")  # 识别限时特卖入口横幅。
        if banner is not None:  # 入口横幅存在。
            self.click_box(banner, after_sleep=1)  # 点击横幅打开详情弹窗，下一轮再关闭。
            self.log_info("已点击卢比限时特卖入口。")  # 记录点击动作。
            return True  # 返回已处理。
        return False  # 当前帧无卢比限时特卖相关界面。

    def _find_daily_login_claim_all(self):
        """在屏幕底部区域 OCR 识别登录奖励弹窗的「全部领取」按钮文字，返回匹配框或 None。

        走 OCR 而非模板：七天制登录奖励每期皮肤不同，按钮配色/尺寸随之变化，
        但「全部领取」这行文字固定不变。
        """
        boxes = self.ocr(box=self.box_of_screen(1 / 3, 0.85, 0.7, 1.0),  # 按钮恒在面板底部。
                         match=[self._DAILY_LOGIN_CLAIM_ALL_TEXT])  # 正则部分匹配。
        return boxes[0] if boxes else None  # 文字长在按钮上，命中即按钮存在。

    def _daily_login_button_box(self, text_box):
        """把 OCR 得到的「全部领取」文字框按 _DAILY_LOGIN_CLAIM_PAD 比例外扩到按钮底色区域。

        OCR 只框到白色文字，彩色可领与灰白已领完两种状态下文字都是白的，无法据此区分；
        外扩取到按钮底色后才能用 is_feature_enabled 判定。外扩用比例而非固定像素，
        保证在 1600x900 等小分辨率下也不会撑出按钮本体而混进背景色。
        """
        pad_w = text_box.width * self._DAILY_LOGIN_CLAIM_PAD[0]  # 水平外扩量。
        pad_h = text_box.height * self._DAILY_LOGIN_CLAIM_PAD[1]  # 垂直外扩量。
        return Box(text_box.x - pad_w, text_box.y - pad_h,  # 左上各外扩一份。
                   text_box.width + pad_w * 2, text_box.height + pad_h * 2,  # 尺寸两端各加一份。
                   name="daily_login_claim_button")  # 命名便于日志/调试识别。

    def _find_daily_login_close(self):
        """在屏幕右上区域依次尝试各期关闭按钮模板，返回第一个命中的框或 None。

        七天制登录奖励每期面板皮肤不同，关闭 X 的背景纹理/描边随之变化，故模板只保留
        X 图形本身（不含周边背景）以应对该变化；出现新样式时把裁剪好的小图路径追加到
        _DAILY_LOGIN_CLOSE_TEMPLATES 即可，无需改动本方法。
        """
        for template_path in self._DAILY_LOGIN_CLOSE_TEMPLATES:  # 依次尝试每个关闭按钮模板。
            found = self.find_scaled_template(  # 关闭 X 恒在面板右上角约 x 0.62、y 0.095。
                "daily_login_close", template_path,
                box=self.box_of_screen(0.5, 0.03, 0.8, 0.2),
            )
            if found is not None:  # 当前模板命中。
                return found  # 停止尝试后续模板。
        return None  # 所有模板均未命中，当前帧无该弹窗（或遇到未收录的新皮肤）。

    def _close_daily_login_popup(self):
        """处理登录奖励（DAILY LOGIN）弹窗：有可领奖励先点「全部领取」，无可领则点右上角关闭按钮。

        「全部领取」一次性领取多档登录奖励，点击后会弹出奖励遮罩盖住面板；本方法在
        点击领取后立即等待并关闭该遮罩，再交由 dismiss_all_popups 的下一轮判定按钮
        是否变灰、进而关闭面板。遮罩的关闭提示与其它领奖遮罩共用（点击领取奖励/
        点击任意处/点击进行下一步），故复用 close_overlay 统一清理。
        """
        # 任务弹窗（mission）底部也有「全部领取」按钮，文字与登录奖励弹窗相同、且都在屏幕下半区，
        # 单看 OCR 无法区分：用任务弹窗标题特征消歧，任务弹窗在前时这里是任务页按钮，不是登录奖励弹窗，跳过以免误点。
        if self.find_one("mission_page") is not None:  # 命中任务弹窗标题 = 当前在任务页而非登录奖励弹窗。
            return False  # 跳过，避免误点任务页的「全部领取」。
        claim = self._find_daily_login_claim_all()  # 查找「全部领取」文字。
        if claim is not None and self.is_feature_enabled(self._daily_login_button_box(claim)):  # 底色彩色 = 仍有可领奖励。
            self.click_box(claim, after_sleep=1)  # 点击领取。
            self.log_info("已点击登录奖励全部领取。")  # 记录动作。
            # 领取后弹出奖励遮罩（盖住面板）：等待并关闭，避免遮罩残留或下一轮误点面板的关闭按钮。
            self.close_overlay(
                keywords=(self._MASK_CLAIM_PATTERN, self._MASK_ANYWHERE_PATTERN, self._CLICK_TO_PROCEED_PATTERN),
                time_out=5  # 遮罩并非必现（可能无奖励动画），超时未出现不报错。
            )
            return True  # 返回已处理。
        close = self._find_daily_login_close()  # 无可领（按钮灰白/缺失）时直接关闭弹窗。
        if close is not None:  # 关闭按钮存在。
            self.click_box(close, after_sleep=1)  # 点击关闭按钮关闭整个弹窗。
            self.log_info("已关闭登录奖励弹窗。")  # 记录动作。
            return True  # 返回已处理。
        return False  # 当前帧无登录奖励弹窗。

    def close_overlay(self, keywords=None, time_out=5, after_sleep=1, max_clicks=3,
                      require_click=True):
        """点击遮罩窗按钮关闭弹窗，避免后续点击被遮罩拦截。

        在屏幕中下部区域（x 1/3-2/3，y 0.6-1）做 OCR："点击领取奖励"文字
        位于屏幕中央偏下（约 rel_y 0.64），因此 OCR 区域从 y=0.6 开始覆盖，
        每次只点第一个匹配框（同一弹窗的文字阴影会重复命中，不能连点），
        点完继续检测，弹窗连续出现时逐个关闭。遮罩未出现时会一直等到
        time_out 超时，方便处理点击后延迟弹出的遮罩。

        Args:
            keywords: OCR 匹配关键词（支持正则），缺省为领奖遮罩提示（正则部分匹配）。
            time_out: 等待遮罩出现/关闭的最长时间（秒）。
            after_sleep: 点击后的固定等待时间（秒）。
            max_clicks: 最多连续点击次数，防止异常时死循环。
            require_click: True 时若超时仍未点到任何遮罩则抛 WaitFailedException；
                恢复流程等容错场景应传 False，超时未出现则跳过不报错。
        Returns:
            True 表示至少点击过一次；require_click=False 且未点到时返回 False。
        """
        if keywords is None:  # 未指定关键词。
            keywords = (self._MASK_CLAIM_PATTERN,)  # 默认领奖遮罩提示（正则部分匹配，兼容 OCR 拆框/噪声）。
        start = time.time()  # 记录开始时间，用于超时控制。
        clicked = False  # 标记是否至少成功点击过一次。
        clicks = 0  # 统计连续点击次数。
        while time.time() - start < time_out:  # 循环直到超时。
            boxes = self.ocr(x=1 / 3, y=0.6, to_x=2 / 3, to_y=1, match=list(keywords))  # 在中下部区域 OCR 匹配关键词，覆盖位于 rel_y≈0.64 的“点击领取奖励”。
            if boxes:  # 当前仍有遮罩按钮。
                if clicks >= max_clicks:  # 超过最大连续点击次数。
                    self.log_warning(f"遮罩点击 {max_clicks} 次仍存在，停止。")  # 记录异常并停止，避免死循环。
                    break  # 退出循环。
                self.click_box(boxes[0], after_sleep=after_sleep)  # 点击第一个匹配框并等待弹窗响应。
                self.log_info(f"点击遮罩按钮: {keywords}")  # 记录本次点击。
                clicked = True  # 标记已点击过。
                clicks += 1  # 点击次数加一。
                continue  # 继续检测下一个弹窗或确认已关闭。
            if clicked:  # 点过且当前无遮罩，说明弹窗已关闭。
                self.log_info("遮罩已全部关闭。")  # 记录全部关闭完成。
                return True  # 关闭成功，立即返回。
            self.sleep(1)  # 遮罩尚未出现，等待 1 秒后重试直到超时。
        if not clicked:  # 全程未出现遮罩。
            if require_click:  # 明确要求至少关闭一次但未点到。
                raise WaitFailedException(f"未找到遮罩按钮 {keywords}，未能关闭弹窗。")  # 抛出等待失败异常，便于上层 try_step 捕获重试。
            self.log_info("未出现遮罩，跳过。")  # 记录超时未出现。
        return clicked  # 超时或点满次数后返回当前状态。

    def _try_close_one_popup(self, after_sleep=1):
        """尝试关闭当前帧上的一个弹窗：卢比限时特卖 → 公告/活动横幅 → 领取奖励/点击任意处遮罩 → 登录奖励弹窗。返回是否成功关掉一个。

        顺序按遮挡层级从上到下：遮罩压在登录奖励面板之上，故面板排在遮罩之后——
        否则「点完全部领取弹出的奖励遮罩」会被面板的关闭按钮抢先跳过后者的点击。
        每次只关一个，由 dismiss_all_popups 循环调用，避免一次点击后界面动画未完成导致误判。
        """
        if self._close_rupee_flash_sale_popup():  # 卢比限时特卖（两段式：入口横幅点击后弹详情，再点关闭确认）。
            return True  # 已处理卢比限时特卖。
        if self._close_notice_popup():  # 公告/活动横幅（右上角铃铛+关闭按钮）。
            return True  # 已关闭横幅弹窗。
        try:  # 遮罩 OCR 异常不应中断统一清理。
            boxes = self.ocr(x=1 / 3, y=0.6, to_x=2 / 3, to_y=1,
                             match=[self._MASK_CLAIM_PATTERN, self._MASK_ANYWHERE_PATTERN,
                                    self._CLICK_TO_PROCEED_PATTERN])  # 中下部区域查找领奖/任意处/进行下一步遮罩提示（正则部分匹配）。
        except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
            raise  # 重新抛出，交由执行器结束任务。
        except Exception as e:  # 其它 OCR 失败。
            self.log_warning(f"遮罩 OCR 失败: {e}")  # 记录失败原因。
            return False  # 本帧无遮罩可关。
        if boxes:  # 存在遮罩按钮。
            self.click_box(boxes[0], after_sleep=after_sleep)  # 点击关闭遮罩。
            self.log_info("点击遮罩按钮关闭弹窗。")  # 记录关闭动作。
            return True  # 已关闭一个遮罩。
        try:  # 登录奖励面板含 OCR 与模板匹配，异常同样不应中断统一清理。
            if self._close_daily_login_popup():  # 位于遮罩之下，故排在遮罩之后处理。
                return True  # 已处理登录奖励弹窗。
        except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
            raise  # 重新抛出，交由执行器结束任务。
        except Exception as e:  # OCR/模板匹配失败。
            self.log_warning(f"登录奖励弹窗清理失败: {e}")  # 记录失败原因。
            return False  # 本帧视为无可关闭的弹窗。
        return False  # 本帧没有可关闭的弹窗。

    def dismiss_all_popups(self, clear_condition=None, time_out=10, after_sleep=1, max_passes=6,
                           wait_for_popup=True):
        """统一弹窗清理入口：循环关闭卢比限时特卖、公告/活动横幅与领取奖励/点击任意处遮罩等弹窗。

        语义与 close_overlay 一致：点击后弹窗可能延迟出现，因此当前帧无弹窗时
        默认不会立即返回，而是继续等待（wait_for_popup=True，适用于"点击领取后"等
        必出弹窗的场景）；纯入口清理等"可能有弹窗也可能没有"的场景应传
        wait_for_popup=False，无弹窗时立即返回。也可传 clear_condition 等待目标界面。

        Args:
            clear_condition: 可选完成条件（返回 True 表示清理完成/已回到目标界面）；
                每轮先尝试关弹窗，仅当本轮未关到任何弹窗时才检查该条件——遮罩压暗下
                目标界面特征可能仍命中，若先查条件会误报清理完成而留下未关弹窗。
            time_out: 清理的总超时（秒）。
            after_sleep: 每次点击后的固定等待（秒）。
            max_passes: 最大清理轮数上限，防止异常画面下死循环。
            wait_for_popup: True 时无弹窗也继续等待直到超时（处理延迟弹窗）；
                False 时当前帧无弹窗且未关过任何弹窗则立即返回 True。
        Returns:
            True 清理完成；False 超时且仍有弹窗未能关闭。
        """
        start = time.time()  # 记录开始时间。
        passes = 0  # 统计清理轮数。
        closed_any = False  # 是否至少关闭过一个弹窗。
        while time.time() - start < time_out:  # 循环直到超时。
            passes += 1  # 轮数加一。
            if passes > max_passes:  # 超过轮次上限。
                self.log_warning(f"清理弹窗达到轮次上限（{max_passes}），停止。")  # 记录异常并停止。
                return False  # 返回失败。
            if self._try_close_one_popup(after_sleep=after_sleep):  # 关掉了一个弹窗。
                closed_any = True  # 标记已关闭过弹窗。
                try:  # 刷新帧后再继续，避免基于旧帧重复匹配。
                    self.next_frame()  # 获取最新屏幕帧。
                except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
                    raise  # 重新抛出，交由执行器结束任务。
                except Exception:  # 无可用帧时忽略。
                    pass  # 继续下一轮。
                continue  # 继续清理剩余弹窗。
            if clear_condition is not None and clear_condition():  # 本轮已无弹窗可关且完成条件满足。
                return True  # 清理完成。
            if clear_condition is not None:  # 有完成条件但尚未满足。
                self.sleep(1)  # 等待界面变化后重试。
                continue  # 继续等待。
            if closed_any:  # 关闭过弹窗且当前无弹窗可关。
                return True  # 清理完成。
            if not wait_for_popup:  # 快速清理场景：从未出现过弹窗。
                return True  # 无需清理，立即返回。
            self.sleep(1)  # 弹窗可能尚未出现（点击后延迟），等待出现。
        if closed_any:  # 超时但关闭过弹窗，仍有弹窗残留。
            self.log_warning(f"清理弹窗超时（{time_out}秒）。")  # 记录超时。
            return False  # 返回失败。
        self.log_info("未发现弹窗，无需清理。")  # 超时未出现任何弹窗。
        return True  # 视为清理完成。