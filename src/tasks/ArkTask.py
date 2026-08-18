import re  # 正则模块，用于 OCR 关键词的部分匹配。

from ok import og  # 全局单例，读取当前执行任务以判断是否由日常编排。
from ok.task.exceptions import WaitFailedException  # 界面断言/战斗超时抛出的框架等待失败异常。

from src.tasks.MyBaseTask import MyBaseTask  # 项目基类，所有任务统一继承它。

# 塔号 -> 企业名，用于战斗失败时提醒用户。
_TOWER_NAMES = {
    1: "极乐净土",  # 1号塔。
    2: "米西利斯",  # 2号塔。
    3: "泰特拉",  # 3号塔。
    4: "朝圣者/超标准",  # 4号塔。
}

# 塔卡 OPEN 关键词：OCR 忽略大小写匹配英文 OPEN。
_OPEN_PATTERN = re.compile(r"OPEN", re.IGNORECASE)


class ArkTask(MyBaseTask):  # 方舟任务：执行企业塔/模拟室/拦截战/竞技场等子流程。

    done_keys = {"tribe_tower": "day"}  # 完成状态：企业塔（日常刷新）。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "方舟"  # 任务显示名称。
        self.description = "执行企业塔/模拟室/拦截战/竞技场相关任务。"  # 任务说明。
        self.failed_towers = []  # 本次运行中战斗失败的塔号记录，供日常编排统一提醒。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "关闭自动爬塔": False,  # 进入战斗后自动撤退，默认正常爬塔。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "关闭自动爬塔": "进入战斗后自动撤退，适合只完成日常任务而不需要爬塔的指挥官。",
        })
        # 界面注册：方舟需同时命中 coco 特征与标题 OCR；无限之塔以塔徽特征判定。
        self.register_screen("ark", features=["ark_ranking"], keywords=["方舟"], ocr_box="box_sub_pages_title")
        self.register_screen("infinite_tower", features=["tribe_tower_mark"])

    def run(self):  # 任务执行入口，目前只包含企业塔子流程。
        self.log_info("方舟任务开始。")  # 记录任务开始。
        self.failed_towers = []  # 重置本次运行的失败塔记录，避免残留上次数据。
        if self.is_done("tribe_tower", "day"):  # 本周期内已完成则直接跳过。
            self.log_info("今日企业塔已完成，跳过。")  # 记录跳过原因。
            return  # 结束本次执行。
        if not self.wait_until_lobby_after_start():  # 启动后等待进入游戏大厅，失败则中止。
            self.log_error("未能进入游戏大厅，中止方舟任务。")  # 记录失败原因。
            return  # 结束本次执行。
        self.dismiss_all_popups(wait_for_popup=False, time_out=10)  # 统一清理大厅残留弹窗，无弹窗立即返回。
        success = self.try_step(  # 企业塔整体流程从大厅出发，用恢复协议包裹。
            lambda: self._tribe_tower_flow(),  # 执行企业塔流程。
            name="企业塔",  # 步骤名用于日志与失败截图。
            raise_on_fail=False,  # 多次失败后跳过而非抛异常。
        )
        if not success:  # 流程多次失败。
            self.log_warning("企业塔流程多次失败，跳过。")  # 记录跳过原因。
            return  # 不标记完成，下次可重试。
        self.mark_done("tribe_tower", "day")  # 记录本周期已完成。
        if not self._under_daily():  # 非日常编排时由本任务直接提醒。
            self.notify_failed_towers()  # 提醒战斗失败的塔。
        self.log_info("企业塔任务完成。")  # 记录子流程完成。

    def _tribe_tower_flow(self):  # 企业塔整体流程：进入方舟→无限之塔→逐塔挑战→返回方舟。
        self._enter_ark_and_tower()  # 从大厅进入无限之塔界面。
        abandoned = False  # 自动撤退模式是否已处理并返回方舟。
        for index in range(1, 5):  # 依次处理 1-4 号塔。
            handled = self._try_tower(index)  # 处理单号塔，返回是否进入过塔。
            if handled and self.config.get("关闭自动爬塔"):  # 自动撤退模式下进入一次即结束流程。
                abandoned = True  # 标记已结束。
                break  # 停止循环。
        if not abandoned:  # 正常模式走完所有塔后统一返回方舟。
            if not self.wait_click_feature("common_back", raise_if_not_found=False, after_sleep=1):  # 点击返回方舟界面。
                self.log_warning("返回方舟界面失败，后续任务会自动恢复。")  # 记录未返回，依赖后续任务的失败恢复。

    def _tower_is_open(self, box_key):  # 在塔卡区域 OCR 识别 OPEN 关键词，判断该塔是否开放。
        try:  # 区域特征可能缺失。
            box = self.get_box_by_name(box_key)  # 获取塔卡 OPEN 标注区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失。
            return False  # 视为未开放。
        if box is None:  # 区域无效。
            return False  # 视为未开放。
        return bool(self.ocr(box=box, match=_OPEN_PATTERN))  # 区域内 OCR 命中 OPEN 才算开放。

    def _try_tower(self, index):  # 处理单号塔：OPEN 判断→进入→战斗按钮可用性→战斗，返回是否进入过塔。
        box_key = f"box_tribe_tower{index}"  # 塔卡 OPEN 标注区域特征名。
        if not self._tower_is_open(box_key):  # 该塔未开放。
            self.log_info(f"{index}号塔未开放，跳过。")  # 记录跳过。
            return False  # 未进入塔。
        self._enter_tower(box_key)  # 点击塔卡进入该塔。
        self.wait_feature("tribe_tower_stage", raise_if_not_found=True)  # 等待进入塔关卡界面。
        self.wait_click_feature("box_tower_enter", raise_if_not_found=True, after_sleep=1)  # 点击进入关卡。
        battle_box = self.get_box_by_name("box_tribe_tower_battle")  # 获取战斗按钮区域（box_ 前缀特征为纯坐标区域，无模板）。
        if battle_box is None or not self.is_feature_enabled(battle_box):  # 区域缺失或按钮为灰白禁用态说明次数用尽。
            self.log_info(f"{index}号塔通关次数用尽，跳过。")  # 记录跳过。
            self.wait_click_feature("tribe_tower_close", raise_if_not_found=True, after_sleep=1)  # 点击关闭按钮关闭弹出的开始战斗卡片。
            self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 返回无限之塔界面。
            return False  # 未进入战斗。
        if self.config.get("关闭自动爬塔"):  # 关闭自动爬塔模式。
            self._abandon_battle(battle_box)  # 进入战斗后自动撤退，结束后已返回方舟界面。
        else:  # 正常爬塔模式。
            self._climb_battle(index, battle_box)  # 正常战斗并处理结算，结束后返回无限之塔界面。
        return True  # 已进入过塔。

    def _enter_ark_and_tower(self):  # 从大厅进入无限之塔界面。
        self.wait_click_feature("ark", raise_if_not_found=True, after_sleep=1)  # 点击方舟入口进入方舟界面。
        self.assert_screen("ark")  # 确认已进入方舟界面。
        self.wait_click_feature("ark_tribe_tower", raise_if_not_found=True, after_sleep=1)  # 点击企业塔入口。
        self.assert_screen("infinite_tower")  # 确认已进入无限之塔界面。

    def _enter_tower(self, box_key):  # 点击塔卡进入该塔。
        try:  # 区域特征可能缺失。
            box = self.get_box_by_name(box_key)  # 获取塔卡 OPEN 标注区域。
        except ValueError:  # 特征缺失。
            box = None  # 置空以便统一处理。
        if box is None:  # 区域无效。
            raise WaitFailedException(f"缺少区域特征: {box_key}")  # 抛异常由 try_step 恢复。
        cx = box.x + box.width // 2  # 点击 x 取 OPEN 区域水平中心。
        cy = box.y + box.height + int(0.1 * self.height)  # 点击 y 取区域底边下移 0.1 倍屏幕高度（塔卡中部）。
        self.click(cx, cy, after_sleep=1)  # 点击塔卡进入该塔。

    def _climb_battle(self, index, battle_btn):  # 正常爬塔：进入战斗、处理结算并返回无限之塔界面。
        self.click_box(battle_btn, after_sleep=1)  # 点击开始战斗按钮进入战斗。
        result, confirm_box = self.wait_battle_finish(time_out=240, check_interval=2)  # 节流等待战斗结束，只检测不点击。
        if result == "success":  # 战斗胜利。
            next_stage = self.find_one("battile_finish_next_stage")  # 识别结算界面的下一关按钮。
            if next_stage is not None:  # 存在下一关按钮。
                self.click_box(next_stage, after_sleep=1)  # 点击继续挑战下一关。
            else:  # 无下一关。
                self.click_box(confirm_box, after_sleep=1)  # 点击结算确认按钮返回塔关卡界面。
        elif result == "failed":  # 战斗失败。
            self.failed_towers.append(index)  # 记录本次失败的塔号，供结束时提醒用户。
            self.click_box(confirm_box, after_sleep=1)  # 点击失败返回按钮。
        else:  # 等待战斗结束超时。
            raise WaitFailedException("等待企业塔战斗结束超时")  # 抛异常由 try_step 恢复重试。
        self.wait_feature("tribe_tower_stage", raise_if_not_found=True)  # 等待回到塔关卡界面。
        self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 点击返回无限之塔界面。

    def _abandon_battle(self, battle_btn):  # 关闭自动爬塔模式：进入战斗后暂停撤退，消耗一次次数后返回方舟。
        self.click_box(battle_btn, after_sleep=10)  # 点击开始战斗并等待战斗加载约 10 秒。
        pause = self.wait_feature("battle_pause", time_out=15, raise_if_not_found=True)  # 识别战斗暂停按钮。
        self.click_box(pause, after_sleep=1)  # 点击暂停按钮。
        escape = self.wait_feature("battle_escape", raise_if_not_found=True)  # 识别撤退按钮。
        self.click_box(escape, after_sleep=1)  # 点击撤退放弃本场战斗。
        failed_back = self.wait_feature("battle_finish_failed_back", time_out=15, raise_if_not_found=True)  # 识别失败结算返回按钮。
        self.click_box(failed_back, after_sleep=1)  # 点击返回。
        self.wait_feature("tribe_tower_stage", raise_if_not_found=True)  # 等待回到塔关卡界面。
        self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 点击返回无限之塔界面。
        self.wait_click_feature("common_back", raise_if_not_found=True, after_sleep=1)  # 点击返回方舟界面。

    def _under_daily(self):  # 判断当前是否由日常任务编排执行（日常里统一在全部子任务完成后提醒）。
        executor = getattr(og, "executor", None)  # 读取全局执行器。
        return executor is not None and executor.current_task is not None and executor.current_task is not self  # 当前执行者是其他编排任务时返回 True。

    def failed_towers_message(self):  # 构造战斗失败塔的提醒文本，无失败记录返回 None。
        if not self.failed_towers:  # 无失败记录。
            return None  # 无需提醒。
        unique = []  # 去重后的失败塔号列表。
        for i in self.failed_towers:  # 遍历记录（失败重试可能重复记录）。
            if i not in unique:  # 未记录过才加入。
                unique.append(i)  # 加入去重列表。
        names = "、".join(_TOWER_NAMES.get(i, f"{i}号塔") for i in unique)  # 拼接失败塔的企业名。
        return f"今日企业塔战斗失败：{names}，请手动处理。"  # 返回提醒文本。

    def notify_failed_towers(self):  # 系统通知提醒战斗失败的塔（供单独运行与日常编排共用）。
        message = self.failed_towers_message()  # 构造提醒文本。
        if message:  # 有失败记录才提醒。
            self.log_info(message, notify=True)  # 发送系统通知。
