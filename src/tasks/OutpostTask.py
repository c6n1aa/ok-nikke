import cv2  # OpenCV 模块，咨询次数 OCR 前对裁剪图做固定倍率放大。
import os  # 路径拼接模块，定位 assets/db/advise.db 咨询数据库。
import random  # 随机模块，答案匹配无法决策时随机二选一。
import re  # 正则模块，OCR 关键词部分匹配与答案文本规范化。
import sqlite3  # SQLite 模块，只读查询咨询答案库。
import time  # 时间模块，对话推进循环的超时控制。

from ok.task.exceptions import WaitFailedException  # 框架等待失败异常，断言失败时抛出由 try_step 捕获恢复。

from src.tasks.NikkeBaseTask import NikkeBaseTask  # 项目基类，所有任务统一继承它。

# 派遣公告栏窗口标题匹配模式：OCR 部分匹配（框架对 re.Pattern 走 re.search，兼容尾随标点）。
_DISPATCH_BOARD_TITLE_PATTERN = re.compile("派遣公告栏")
# 咨询剩余次数计数匹配模式：提取 "X/10" 的分子。分子与分母的 0 均容忍 OCR 误识为 O/o，
# 匹配后分子统一归一（O/o→0）再判 0（实测 OCR 会把分子的 0 识成 O 导致漏判用尽）。
_ADVISE_COUNT_PATTERN = re.compile(r"([0-9Oo]+)\s*/\s*1[0Oo]")
# 咨询对话推进的最大等待秒数：超时说明对话未按预期推进到作答时机，抛异常由 try_step 恢复。
_CONVERSATION_MAX_WAIT = 120
# 单个选项框判定为推进选项前需持续在场的秒数：作答双框可能先后渲染，防止把先出现的框误当推进选项点掉。
_SINGLE_OPTION_CONFIRM = 1.0
# 点击单个推进选项时传给 click_box 的框内相对 X（乘角标宽度）：角标贴在框体左缘不可点，
# 取 10 即点角标右侧的框体，且随模板缩放自适应分辨率。
_SINGLE_OPTION_CLICK_X = 10
# 点击 advise_next 后角色名称未变更的最大重试次数：超限视为无法切换，优雅结束咨询流程。
_ADVISE_NEXT_MAX_RETRY = 5
# 咨询流程切换角色的上限：超过后强行结束，防止异常界面状态下无限循环。
_ADVISE_MAX_SWITCH = 30
# 咨询对话点击空白的相对坐标（屏幕右下中部空白区，不与选项框/图标重叠）。
_CONVERSATION_BLANK_X = 0.7
_CONVERSATION_BLANK_Y = 0.85

# 咨询答案库路径（运行时以仓库根/程序目录为工作目录）。
_ADVISE_DB_PATH = os.path.join("assets", "db", "advise.db")


def _normalize_answer_text(text):  # 答案文本规范化：去除全部标点符号与空白，避免 OCR 噪声导致漏匹配。
    return re.sub(r"[\W_]+", "", text or "")  # \W 为非文字字符（含标点/空白），下划线单独去除。


def _normalize_query_name(name):  # OCR 角色名称转 SQL LIKE 模式：标点符号替换为通配符 %。
    return re.sub(r"\W+", "%", (name or "").strip()).strip("%")  # 连续非文字字符折叠为单个通配符。


class OutpostTask(NikkeBaseTask):  # 前哨基地任务：执行派遣公告栏与咨询子流程。

    done_keys = {"bulletin_board": "day", "advise": "day"}  # 完成状态：派遣/咨询（日常刷新）。

    def is_completed(self):  # 覆盖父类：只统计用户开启的子流程，开启的均已完成才算完成。
        checks = []  # 收集各开启子流程的完成状态。
        if self.config.get("派遣"):  # 开启派遣才纳入判断。
            checks.append(self.is_done("bulletin_board", "day"))  # 派遣日常完成状态。
        if self.config.get("咨询"):  # 开启咨询才纳入判断。
            checks.append(self.is_done("advise", "day"))  # 咨询日常完成状态。
        return bool(checks) and all(checks)  # 至少开启一个且开启的全部完成才算完成。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "前哨基地"  # 任务显示名称。
        self.description = "执行派遣/咨询任务"  # 任务说明。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "派遣": True,  # 每日派遣与领取。
            "咨询": True,  # 执行每日咨询。
            "只咨询星标": True,  # 只对星标的妮姬进行咨询。
            "补齐咨询日志": False,  # 角色好感度满时，仍对咨询日志图鉴未满的角色进行咨询。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "派遣": "每日派遣与领取",
            "咨询": "执行每日咨询",
            "只咨询星标": "只对星标的妮姬进行咨询",
            "补齐咨询日志": "角色好感度满时，仍对咨询日志图鉴未满的角色进行咨询",
        })
        self.config_type.update({  # 配置类型与显隐控制：布尔开关联动子配置显隐（参考 ShopTask）。
            "咨询": {  # 布尔开关，启用时才展开咨询配置。
                "sub_configs": {  # 开关联动子配置显隐。
                    True: ["只咨询星标", "补齐咨询日志"],  # 启用时显示两个咨询选项。
                    False: [],  # 关闭时收起配置。
                },
            },
        })

    # ---- 区域工具 ----

    def _optional_box(self, name):  # 获取 box_ 区域特征，缺失时返回 None（用于可缺失的判态区域）。
        try:  # coco 特征可能缺失。
            return self.get_box_by_name(name)  # 按当前分辨率解析区域框。
        except ValueError:  # 特征缺失视为区域不可用。
            return None  # 返回 None。

    def _box_or_fail(self, name):  # 获取 box_ 区域特征，缺失时抛等待失败异常（由 try_step 捕获恢复）。
        box = self._optional_box(name)  # 解析区域框。
        if box is None:  # 特征缺失。
            raise WaitFailedException(f"缺少区域特征: {name}")  # 抛异常由 try_step 捕获恢复。
        return box  # 返回区域框。

    # ---- run 入口 ----

    def run(self):  # 任务执行入口：先就位大厅，依次执行派遣与咨询子流程。
        self.log_info("前哨基地任务开始")  # 记录任务开始。
        if not self.config.get("派遣") and not self.config.get("咨询"):  # 两个子流程均未开启。
            self.log_info("派遣与咨询均未开启，跳过")  # 记录跳过原因。
            return  # 结束任务，避免无谓拉起游戏窗口。
        if self.is_done("bulletin_board", "day") and self.is_done("advise", "day"):  # 两个子流程均已完成。
            self.log_info("今日派遣与咨询均已完成，跳过")  # 记录跳过原因。
            return  # 结束任务，避免无谓拉起游戏窗口。
        if not self.ensure_screen("lobby", raise_on_fail=False):  # 就位游戏大厅（含冷启动引导与弹窗清理）。
            self.log_error("未能进入游戏大厅，中止前哨基地任务")  # 记录失败原因。
            return  # 结束任务。
        self._do_dispatch()  # 执行派遣子流程。
        self._do_advise()  # 执行咨询子流程。
        self.log_info("前哨基地任务完成")  # 记录任务完成。

    # ---- 派遣子流程 ----

    def _do_dispatch(self):  # 派遣子流程编排：开关/完成判断 + 恢复协议包裹。
        if not self.config.get("派遣"):  # 用户未启用派遣子流程。
            self.log_info("派遣未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if self.is_done("bulletin_board", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日派遣已完成，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self.try_step(self._dispatch_flow, name="派遣", raise_on_fail=False):  # 以大厅为起点，失败恢复回大厅重试。
            self.log_warning("派遣流程多次失败，跳过")  # 记录跳过原因。
            return  # 不标记完成，下次可重试。
        self.mark_done("bulletin_board", "day")  # 记录本周期已完成。
        self.log_info("派遣任务完成")  # 记录子流程完成。

    def _dispatch_flow(self):  # 派遣整体流程：大厅→前哨基地→派遣公告栏→领取/全部派遣→关闭→回大厅。
        self.transition("outpost", click_feature="outpost", wait_confirm=10, after_sleep=1)  # 到[前哨基地]：点入口并确认进入。
        self.wait_click_feature("bulletin_board", raise_if_not_found=True, after_sleep=1)  # 点派遣公告栏入口。
        title_box = self._box_or_fail("box_bulletin_board_title")  # 公告栏标题区域。
        self.wait_ocr(box=title_box, match=_DISPATCH_BOARD_TITLE_PATTERN, time_out=10,
                      raise_if_not_found=True)  # OCR 标题确认派遣公告栏窗口已打开。
        claim_box = self._optional_box("box_bulletin_board_claim_feature")  # 领取按钮区域（缺失视为不可用）。
        if claim_box is not None and self.is_feature_enabled(claim_box):  # 领取按钮可用（有可领取的派遣奖励）。
            self.click_box(claim_box, after_sleep=1)  # 点击领取。
            self.dismiss_all_popups(time_out=10)  # 清理领取后弹出的奖励遮罩弹窗。
        send_box = self._optional_box("box_bulletin_board_send_all_feature")  # 全部派遣按钮区域（缺失视为不可用）。
        if send_box is not None and self.is_feature_enabled(send_box):  # 全部派遣按钮可用。
            self.click_box(send_box, after_sleep=1)  # 点击全部派遣。
            self.wait_click_feature("bulletin_board_send_all_confirm", raise_if_not_found=True,
                                    after_sleep=1)  # 点击派遣确认弹窗。
        self.wait_click_feature("bulletin_board_windows_close", raise_if_not_found=False,
                                after_sleep=1)  # 关闭公告栏窗口（未领取/未派遣时窗口仍开着，统一关闭）。
        self._exit_to_lobby()  # 返回大厅收尾。

    # ---- 咨询子流程 ----

    def _do_advise(self):  # 咨询子流程编排：开关/完成判断 + 恢复协议包裹。
        if not self.config.get("咨询"):  # 用户未启用咨询子流程。
            self.log_info("咨询未开启，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if self.is_done("advise", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日咨询已完成，跳过")  # 记录跳过原因。
            return  # 结束本子流程。
        if not self.try_step(self._advise_flow, name="咨询", raise_on_fail=False):  # 以大厅为起点，失败恢复回大厅重试。
            self.log_warning("咨询流程多次失败，跳过")  # 记录跳过原因。
            return  # 不标记完成，下次可重试。
        self.mark_done("advise", "day")  # 记录本周期已完成。
        self.log_info("咨询任务完成")  # 记录子流程完成。

    def _advise_flow(self):  # 咨询整体流程：大厅→前哨基地→指挥中心→咨询→逐角色咨询→回大厅。
        self.transition("outpost", click_feature="outpost", wait_confirm=10, after_sleep=1)  # 到[前哨基地]：点入口并确认进入。
        self.wait_click_feature("command_center", raise_if_not_found=True, after_sleep=1)  # 点指挥中心建筑，弹出入场确认。
        self.transition("command_center", click_feature="command_center_enter", wait_confirm=10,
                        after_sleep=1)  # 点入场并确认进入[指挥中心]界面。
        self.click_box(self._box_or_fail("box_command_center_advise_enter"), after_sleep=1)  # 点咨询入口。
        self.assert_screen("advise", time_out=10)  # 等[咨询]界面。
        count_box = self._optional_box("box_advise_count_feature")  # 咨询次数区域（缺失视为无剩余次数）。
        if count_box is None or not self.is_feature_enabled(count_box):  # 次数区域灰白禁用 = 无剩余咨询次数。
            self.log_info("无剩余咨询次数，咨询流程结束")  # 记录结束原因。
            self._exit_to_lobby()  # 返回大厅。
            return  # 由调用方标记完成。
        self.click_box(self._box_or_fail("box_advise_nikke"), after_sleep=1)  # 点第一个可咨询角色打开详情。
        switches = 0  # 切换角色计数，超限强行结束。
        while True:  # 逐角色处理循环：OCR 名称 → 星标/好感判断 → 咨询 → 切换下一个。
            self.assert_screen("advise_nikke", time_out=10)  # 等[咨询详情]界面。
            self.sleep(1)  # 等界面稳定后再 OCR，避免动画期读错角色名。
            name = self._read_advise_name()  # OCR 角色名称，作为 SQL 查询条件。
            if self.config.get("只咨询星标"):  # 只咨询星标开关开启时先判星标。
                star_box = self._optional_box("box_advise_nikke_star")  # 星标区域（缺失视为未星标）。
                if star_box is None or not self.is_feature_enabled(star_box):  # 当前角色未星标。
                    self.log_info("当前角色未星标，咨询流程结束")  # 记录结束原因。
                    self._exit_to_lobby()  # 返回大厅。
                    return  # 由调用方标记完成。
            skip = False  # 是否跳过当前角色直接切换下一个。
            if self.find_one("advise_bond_max") is not None:  # 好感度已满。
                if self.config.get("补齐咨询日志"):  # 补齐咨询日志开启时按图鉴进度决定去留。
                    progress_box = self._optional_box("box_advise_collection_progress")  # 图鉴进度区域。
                    if progress_box is not None and self.is_feature_enabled(progress_box):  # 日志图鉴已完成。
                        skip = True  # 跳过该角色，直接切换下一个。
            if not skip:  # 正常咨询判定路径。
                advise_box = self._optional_box("box_advise_feature")  # 咨询按钮区域（缺失视为不可用）。
                if advise_box is not None and self.is_feature_enabled(advise_box):  # 咨询按钮可用。
                    self._advise_once(name, advise_box)  # 执行一次咨询：确认弹窗→对话→答题→跳过→回详情。
                if self._advise_count_zero():  # 咨询次数已用尽（0/10）。
                    self._exit_to_lobby()  # 返回大厅。
                    return  # 由调用方标记完成。
            switched = self._switch_advise_nikke(name)  # 点击下一个切换角色（以名称变更为准）。
            if not switched:  # 重试用尽仍无法切换。
                self.log_warning("无法切换到下一个咨询角色，咨询流程结束")  # 记录结束原因。
                self._exit_to_lobby()  # 返回大厅。
                return  # 由调用方标记完成。
            switches += 1  # 切换计数加一。
            if switches > _ADVISE_MAX_SWITCH:  # 超过切换上限，强行结束防止异常界面无限循环。
                self.log_warning(f"切换角色超过 {_ADVISE_MAX_SWITCH} 次，强行结束咨询流程")  # 记录强行结束。
                self._exit_to_lobby()  # 返回大厅。
                return  # 由调用方标记完成。

    def _read_advise_name(self):  # OCR 咨询详情页角色名称区域，返回文本（无识别结果返回空串）。
        box = self._box_or_fail("box_advise_nikke_name")  # 详情页名字条区域（区别于列表页点击槽 box_advise_nikke）。
        texts = self.ocr(box=box)  # 区域内 OCR 获取全部文本框。
        return texts[0].name if texts else ""  # 取第一个文本框作为角色名称。

    def _switch_advise_nikke(self, name):  # 点击 advise_next 切换角色，返回是否确认切换成功（名称变更）。
        next_box = self._box_or_fail("advise_next")  # 下一个按钮区域。
        for _ in range(_ADVISE_NEXT_MAX_RETRY):  # 有限重试：弹窗遮挡或吞点击时清理后补点。
            self.click_box(next_box, after_sleep=1)  # 点击下一个角色。
            if self._read_advise_name() != name:  # 角色名称已变更，切换成功。
                return True  # 切换成功。
            self.dismiss_all_popups(wait_for_popup=False, time_out=5)  # 清理可能遮挡的弹窗后重试。
        return False  # 重试用尽仍未切换成功。

    def _advise_count_zero(self):  # OCR 咨询次数区域判断是否已用尽（出现 0/10）。
        box = self._optional_box("box_advise_count")  # 次数区域（缺失视为未用尽，交由切换上限兜底）。
        if box is None:  # 区域缺失。
            return False  # 视为未用尽。
        # 次数文本是细体小字，小图直读会把 "10" 的 1 吞掉识成 "0/0"，3 倍放大后各分辨率实测稳定。
        texts = self.ocr(box=box, frame_processor=lambda image: cv2.resize(
            image, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))  # 区域内放大后 OCR 获取计数文本。
        joined = " ".join((item.name or "") for item in texts)  # 拼接全部识别文本。
        matches = _ADVISE_COUNT_PATTERN.findall(joined)  # 提取全部 X/10 计数的分子。
        if not matches:  # OCR 未识别到任何 X/10 计数（区域错位或计数文本未渲染）。
            self.log_warning(f"咨询次数区域未识别到计数文本：raw='{joined}'")  # 打印原文以便定位。
        # 分子里的 O/o 归一为 0 后再判是否用尽（OCR 常把 0 误识为 O）。
        return any(m.replace("O", "0").replace("o", "0") == "0" for m in matches)  # 任一分子为 0 即已用尽。

    def _advise_once(self, name, advise_box):  # 执行一次完整咨询：确认弹窗→对话推进→答题→跳过→回详情。
        self.click_box(advise_box, after_sleep=1)  # 点击咨询按钮。
        self.wait_click_feature("advise_confirm", raise_if_not_found=True, after_sleep=1)  # 等咨询确认弹窗并点击。
        rows = self._query_advise_rows(name)  # 按角色名与语言区域查询咨询选项（无结果时答案走随机兜底）。
        self.assert_screen("conversation", time_out=10)  # 等[谈话]界面出现。
        self._answer_conversation(rows)  # 点击空白推进对话，出现选项框后按爱心/答案匹配点击。
        self.wait_click_feature("conversation_skip", box=self._box_or_fail("box_conversation_icon"),
                                raise_if_not_found=True, after_sleep=1)  # 在对话图标区识别并点击跳过，结束剩余对话。
        self.dismiss_all_popups(wait_for_popup=False, time_out=5)  # 好感度等级提升遮罩（点击进行下一步）会压暗详情页特征并吞掉切换点击，回详情页前先清掉。
        self.assert_screen("advise_nikke", time_out=15)  # 确认回到咨询详情界面。

    def _answer_conversation(self, rows):  # 对话推进循环：点空白直到出现正式回答选项框，再按爱心/答案匹配选择。
        mark_box = self._box_or_fail("box_advise_option_mark")  # 选项框标记区域。
        deadline = time.time() + _CONVERSATION_MAX_WAIT  # 对话推进超时时刻。
        single_since = None  # 单个选项框首次出现的时刻，持续超过确认窗口才判定为推进选项。
        while True:  # 两个选项框同时出现才是作答时机；单个选项框持续在场则是推进选项，点掉才能继续。
            option1 = self.find_one("advise_option1", box=mark_box)  # 选项框 1。
            option2 = self.find_one("advise_option2", box=mark_box)  # 选项框 2。
            now = time.time()
            if option1 is not None and option2 is not None:  # 正式回答选项已出现。
                break  # 进入作答。
            single = option1 if (option1 is not None and option2 is None) else (
                option2 if (option2 is not None and option1 is None) else None)  # 恰好一个：推进选项或双框渲染间隙。
            if single is not None and single_since is not None \
                    and now - single_since >= _SINGLE_OPTION_CONFIRM:  # 单框持续在场超确认窗口。
                self.click_box(single, relative_x=_SINGLE_OPTION_CLICK_X,
                               after_sleep=1)  # 点角标右侧的框体推进对话（角标本体不可点）。
                single_since = None  # 点击后重新观测。
                continue
            single_since = now if single is not None else None  # 单框开始计时；无框清零重新等。
            if now > deadline:  # 对话迟迟未推进到作答时机。
                raise WaitFailedException("等待咨询回答选项框超时")  # 抛异常由 try_step 恢复。
            self.click_relative(_CONVERSATION_BLANK_X, _CONVERSATION_BLANK_Y,
                                after_sleep=0.5)  # 点击屏幕右下中部空白推进对话。
        heart = self.find_one("advise_option_heart", box=mark_box)  # 好感爱心标记（直接标在正确选项上）。
        if heart is not None:  # 爱心可见时直接点击爱心所在选项。
            self.click_box(heart, after_sleep=1)  # 点击爱心。
            return  # 作答完成。
        self._click_matched_answer(rows, option1, option2)  # 无爱心时按数据库答案匹配点击。

    def _click_matched_answer(self, rows, option1, option2):  # OCR 两个选项文本并与数据库答案匹配后点击。
        answer_box = self._box_or_fail("box_advise_option")  # 选项文本 OCR 区域。
        texts = self.ocr(box=answer_box)  # OCR 获取选项文本框。
        candidates = {}  # 规范化文本 -> 文本框（去重，保留首个）。
        for item in texts:  # 逐个规范化选项文本。
            key = _normalize_answer_text(item.name)  # 去除标点符号后的文本。
            if key and key not in candidates:  # 空文本或重复文本跳过。
                candidates[key] = item  # 记录候选。
        if candidates:  # OCR 命中选项文本时按三级策略匹配。
            choice = self._match_good_answer(rows, candidates)  # 精准命中→排除→随机。
        else:  # OCR 未读到选项文本。
            choice = random.choice([option1, option2])  # 随机点一个选项框兜底，避免卡死。
        self.click_box(choice, after_sleep=1)  # 点击选中的答案。

    @staticmethod
    def _match_good_answer(rows, candidates):  # 三级答案匹配：同行精准命中 → bad 排除 → 随机兜底。
        if rows:  # 有查询结果才做匹配。
            bad_set = {_normalize_answer_text(bad) for _, _, bad in rows}  # 全部错误答案（规范化）。
            good_set = {_normalize_answer_text(good) for _, good, _ in rows}  # 全部正确答案（规范化）。
            for _, good, bad in rows:  # 逐行精准命中：同行 good/bad 同时出现在两个选项中即锁定该行。
                good_key = _normalize_answer_text(good)  # 规范化正确答案。
                bad_key = _normalize_answer_text(bad)  # 规范化错误答案。
                if good_key in candidates and bad_key in candidates:  # 两个选项恰为该行的正确/错误答案。
                    return candidates[good_key]  # 点击正确答案。
            for key, box in candidates.items():  # 排除法：选项命中任一 bad 即选另一个。
                if key in bad_set:  # 该选项是错误答案。
                    others = [item for k, item in candidates.items() if k != key]  # 其余选项。
                    if len(others) == 1:  # 恰剩一个候选。
                        return others[0]  # 点击另一个。
            for key, box in candidates.items():  # 仍未决策时正向命中 good。
                if key in good_set:  # 该选项是正确答案。
                    return box  # 点击正确答案。
        return random.choice(list(candidates.values()))  # 查询无结果/均未命中：随机二选一。

    # ---- 咨询数据库 ----

    def _query_advise_rows(self, name):  # 按语言区域与角色名称查询咨询答案；失败/无结果返回空列表。
        locale = self._advise_locale()  # 运行时语言映射为库内 locale 代码。
        pattern = _normalize_query_name(name)  # 角色名称标点替换为通配符。
        if not locale or not pattern:  # 语言不支持或名称为空时无法查询。
            return []  # 答案走随机兜底。
        if not os.path.exists(_ADVISE_DB_PATH):  # 数据库缺失（未随包分发）。
            self.log_warning(f"咨询数据库不存在: {_ADVISE_DB_PATH}")  # 记录缺失。
            return []  # 答案走随机兜底。
        try:  # 数据库异常不中断咨询流程。
            con = sqlite3.connect(f"file:{_ADVISE_DB_PATH.replace(os.sep, '/')}?mode=ro",
                                  uri=True)  # 只读连接（mode=ro 无写锁），保证速度和响应。
            try:
                return con.execute(  # 仅按 locale 与角色名称查询。
                    "SELECT prompt, good, bad FROM advise WHERE locale = ? AND character_name LIKE ?",
                    (locale, pattern)).fetchall()  # 返回该角色全部咨询条目。
            finally:
                con.close()  # 用完即关，避免占用句柄。
        except sqlite3.Error as e:  # 查询异常。
            self.log_warning(f"咨询数据库查询失败: {e}")  # 记录异常。
            return []  # 答案走随机兜底。

    def _advise_locale(self):  # 运行时语言配置映射为咨询库 locale 代码（en/ja/zh_CN/zh_TW），不支持返回空串。
        locale = getattr(self.executor, "locale", None)  # 读取执行器语言配置。
        name = locale.name() if hasattr(locale, "name") else str(locale or "")  # LocaleName 兼容。
        name = name.replace("-", "_")  # 统一分隔符。
        if name.startswith("zh"):  # 中文区：繁体变体归 zh_TW，其余归 zh_CN。
            return "zh_TW" if name.startswith(("zh_TW", "zh_HK", "zh_MO")) else "zh_CN"  # 返回映射结果。
        if name.startswith("en"):  # 英语变体归 en。
            return "en"  # 返回映射结果。
        if name.startswith("ja"):  # 日语变体归 ja。
            return "ja"  # 返回映射结果。
        return ""  # 其它语言库中无数据，答案走随机兜底。
