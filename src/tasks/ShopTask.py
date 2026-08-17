import os  # 路径拼接模块，拼装 assets/template/ 下代码模板的路径。

import numpy as np  # 数值计算模块，SOLD OUT 横幅带的像素统计使用。

from ok.feature.Box import Box  # 框类型，构造网格每格的匹配区域。
from ok.task.exceptions import WaitFailedException  # 框架等待失败异常，子流程断言失败时抛出由 try_step 捕获。

from src.tasks.MyBaseTask import MyBaseTask  # 项目基类，所有任务统一继承它。

# 竞技场代码模板（第一列 1-3 格随机出现，用模板匹配识别），名称 -> 模板路径。
_CODE_TEMPLATES = {
    "燃烧代码": os.path.join("assets", "template", "fire_code.png"),  # 燃烧代码模板，源自 2560x1440 截图。
    "风压代码": os.path.join("assets", "template", "wind_code.png"),  # 风压代码模板，源自 2560x1440 截图。
    "铁甲代码": os.path.join("assets", "template", "iron_code.png"),  # 铁甲代码模板，源自 2560x1440 截图。
    "电击代码": os.path.join("assets", "template", "electric_code.png"),  # 电击代码模板，源自 2560x1440 截图。
    "水冷代码": os.path.join("assets", "template", "water_code.png"),  # 水冷代码模板，源自 2560x1440 截图。
}

# 竞技场第一列固定格位（列号从 1 开始），商品名 -> 列号。
_ARENA_FIXED_SLOT = {
    "代码手册选择宝箱": 4,  # 第一列第 4 格。
    "简介个性化礼包": 5,  # 第一列第 5 格。
    "公司武器熔炉": 6,  # 第一列第 6 格。
}

# 废铁骨架优先购买列（第一列前 3 格固定商品），商品名 -> 列号。
_SCRAP_BONE_SLOT = {
    "优秀团队合作宝箱": 1,  # 第一列第 1 格。
    "保养工具箱II": 2,  # 第一列第 2 格。
    "企业精选武装": 3,  # 第一列第 3 格。
}

# 破碎核心货币购买列（row, col 从 1 开始），商品名 -> 所在格位列表（部分商品跨多格）。
_BROKEN_CORE_SLOT = {
    "珠宝": [(1, 4)],  # 第一列第 4 格。
    "指挥官自由使用卷": [(1, 5)],  # 第一列第 5 格。
    "极乐净土VIP餐券": [(1, 6)],  # 第一列第 6 格。
    "米西利斯VIP卡": [(1, 7)],  # 第一列第 7 格。
    "泰特拉VIP护理券": [(1, 8)],  # 第一列第 8 格。
    "朝圣者补给套组交换券": [(1, 9)],  # 第一列第 9 格。
    "反常年券": [(1, 10)],  # 第一列第 10 格。
    "信用点盒": [(1, 11), (2, 3)],  # 第一列第 11 格与第二列第 3 格。
    "战斗数据辑盒": [(2, 1), (2, 4)],  # 第二列第 1 格与第 4 格。
    "芯尘盒": [(2, 2), (2, 5)],  # 第二列第 2 格与第 5 格。
    "信用点": [(2, 6)],  # 第二列第 6 格。
}


class ShopTask(MyBaseTask):  # 商店自动兑换任务，继承项目基类。

    done_keys = {  # 完成状态：普通/竞技场商店（日常刷新），废铁商店（周常刷新）。
        "shop_general": "day",  # 普通商店日常完成状态。
        "shop_arena": "day",  # 竞技场商店日常完成状态。
        "shop_scrap": "week",  # 废铁商店周常完成状态。
    }

    def is_completed(self):  # 覆盖父类：只统计用户开启的子商店，开启的均已完成才算完成。
        checks = []  # 收集各开启子商店的完成状态。
        if self.config.get("普通商店"):  # 开启普通商店才纳入判断。
            checks.append(self.is_done("shop_general", "day"))  # 普通商店日常完成状态。
        if self.config.get("竞技场商店"):  # 开启竞技场商店才纳入判断。
            checks.append(self.is_done("shop_arena", "day"))  # 竞技场商店日常完成状态。
        if self.config.get("废铁商店"):  # 开启废铁商店才纳入判断。
            checks.append(self.is_done("shop_scrap", "week"))  # 废铁商店周常完成状态。
        return bool(checks) and all(checks)  # 至少开启一个且开启的全部完成才算完成。

    # 统一网格参数（源 2560x1440，运行时按当前分辨率等比缩放），取自联盟商店标定。
    GRID_ORIGIN = (155, 711)  # 第一格左上角 x, y（像素）。
    GRID_DX = 216  # 水平格子间距（像素）。
    GRID_CARD_W = 204  # 卡片宽度（像素）。
    GRID_CARD_H = 327  # 卡片高度（像素）。
    GRID_ROW_Y = (711, 1056)  # 每行左上角 y（像素），第一行 711、第二行 1056。
    SOLD_OUT_Y_RATIO = (0.36, 0.55)  # SOLD OUT 横幅带在卡片纵向的占比范围。
    SOLD_OUT_DARK_THR = 0.7  # 横幅带深色像素占比阈值。
    SOLD_OUT_STD_THR = 30.0  # 横幅带亮度标准差阈值。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "商店"  # 任务显示名称。
        self.description = "自动购买普通/竞技场/废铁商店商品。"  # 任务说明。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "普通商店": True,  # 是否执行普通商店（每日免费刷新）。
            "竞技场商店": False,  # 是否执行竞技场商店（每日刷新），默认关闭。
            "优先购买列": [""],  # 竞技场商店优先购买的商品列表。
            "废铁商店": False,  # 是否执行废铁商店（每周刷新、商品固定），默认关闭。
            "废铁骨架优先购买列": [""],  # 废铁商店骨架优先购买的商品列表。
            "破碎核心货币购买列": ["珠宝"],  # 废铁商店货币购买的商品列表。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "普通商店": "是否购买普通商店（每日免费刷新）。",
            "竞技场商店": "是否购买竞技场商店。",
            "优先购买列": "竞技场商店要购买的商品，按配置顺序购买。",
            "废铁商店": "是否购买废铁商店。",
            "废铁骨架优先购买列": "废铁商店要用骨头购买的商品，按配置顺序购买。",
            "破碎核心货币购买列": "废铁商店要用核心购买的商品，按配置顺序购买。",
        })
        self.config_type.update({  # 配置类型与显隐控制。
            "竞技场商店": {  # 布尔开关，启用时才展开竞技场配置。
                "sub_configs": {  # 开关联动子配置显隐。
                    True: ["优先购买列"],  # 启用时显示优先购买列。
                    False: [],  # 关闭时收起配置。
                },
            },
            "优先购买列": {  # 列表配置，从固定选项中添加并排序。
                "type": "drop_down",  # 下拉选项列表类型。
                "options_available": list(_CODE_TEMPLATES) + list(_ARENA_FIXED_SLOT),  # 5 个代码 + 3 个固定商品。
            },
            "废铁商店": {  # 布尔开关，启用时才展开废铁配置。
                "sub_configs": {  # 开关联动子配置显隐。
                    True: ["废铁骨架优先购买列", "破碎核心货币购买列"],  # 启用时显示两个购买列。
                    False: [],  # 关闭时收起配置。
                },
            },
            "废铁骨架优先购买列": {  # 列表配置，从固定选项中添加并排序。
                "type": "drop_down",  # 下拉选项列表类型。
                "options_available": list(_SCRAP_BONE_SLOT),  # 3 个骨架商品。
            },
            "破碎核心货币购买列": {  # 列表配置，从固定选项中添加并排序。
                "type": "drop_down",  # 下拉选项列表类型。
                "options_available": list(_BROKEN_CORE_SLOT),  # 11 个货币商品。
            },
        })

    # ---- 网格工具 ----

    def _grid_scale(self):  # 计算源 2560x1440 到当前游戏分辨率的等比缩放比例。
        return min(self.width / 2560, self.height / 1440)  # 取宽高缩放的较小值，避免超出画面。

    def _cell_box(self, row, col):  # 返回 (row, col) 格缩放后的 Box，row/col 从 1 开始。
        s = self._grid_scale()  # 当前缩放比例。
        x = int((self.GRID_ORIGIN[0] + (col - 1) * self.GRID_DX) * s)  # 格子左上角 x。
        y = int(self.GRID_ROW_Y[row - 1] * s)  # 格子左上角 y。
        w = int(self.GRID_CARD_W * s)  # 格子宽度。
        h = int(self.GRID_CARD_H * s)  # 格子高度。
        return Box(x, y, w, h, name=f"cell_{row}_{col}")  # 构造并返回格子区域框。

    def _cell_center(self, row, col):  # 返回 (row, col) 格中心坐标。
        box = self._cell_box(row, col)  # 获取格子区域框。
        return box.x + box.width // 2, box.y + box.height // 2  # 返回中心点坐标。

    def _is_sold_out(self, row, col):  # 检测 (row, col) 格是否 SOLD OUT：横幅带深色占比>阈值 且 亮度标准差<阈值。
        box = self._cell_box(row, col)  # 获取格子区域框。
        frame = self.frame  # 当前帧（BGR），每次访问取最新帧。
        if frame is None:  # 无可用帧时视为非售罄。
            return False  # 返回非售罄。
        if box.x + box.width > frame.shape[1] or box.y + box.height > frame.shape[0]:  # 越界检查。
            return False  # 越界视为非售罄。
        y0 = int(box.y + box.height * self.SOLD_OUT_Y_RATIO[0])  # 横幅带上沿 y。
        y1 = int(box.y + box.height * self.SOLD_OUT_Y_RATIO[1])  # 横幅带下沿 y。
        region = frame[y0:y1, box.x:box.x + box.width].astype(np.float32)  # 裁剪横幅带区域并转浮点。
        b_ch, g_ch, r_ch = region[:, :, 0], region[:, :, 1], region[:, :, 2]  # 拆分 BGR 三通道。
        lum = 0.299 * r_ch + 0.587 * g_ch + 0.114 * b_ch  # 按标准系数计算亮度（等价于 RGB 顺序）。
        dark = float((lum < 100).mean())  # 深色像素（亮度<100）占比。
        std = float(lum.std())  # 亮度标准差。
        return dark > self.SOLD_OUT_DARK_THR and std < self.SOLD_OUT_STD_THR  # 同时满足两个条件判定为售罄。

    # ---- 购买流程 ----

    def _buy_cell(self, row, col, confirm_feature):  # 点击格子并完成购买确认，返回 True 成功 / False 货币不足。
        cx, cy = self._cell_center(row, col)  # 计算格子中心坐标。
        self.click(cx, cy, after_sleep=1)  # 点击格子弹出购买确认框并等待界面刷新。
        self.wait_click_feature(confirm_feature, time_out=10, raise_if_not_found=True, after_sleep=1)  # 等待并点击确认按钮。
        if self.wait_feature("shop_no_currency", time_out=2, raise_if_not_found=False) is not None:  # 检测是否弹出货币不足提示。
            self.log_warning("货币不足，停止当前商店购买。")  # 记录货币不足。
            self.wait_until(lambda: self.find_one("shop_no_currency") is None, time_out=5, raise_if_not_found=False)  # 等待货币不足弹窗自动消失，避免拦截后续点击。
            return False  # 返回失败，调用方据此停止当前商店。
        self.dismiss_all_popups(wait_for_popup=True, time_out=10)  # 清理购买成功后的遮罩弹窗。
        return True  # 返回购买成功。

    # ---- 三家商店购买逻辑 ----

    def _do_general_shop(self):  # 普通商店：买第一列第 1 格 + 免费刷新。
        if self.wait_feature("general_shop_free_item", time_out=3, raise_if_not_found=False) is None:  # 判断是否有可购买的免费商品。
            self.log_info("普通商店无可购买免费商品，跳过。")  # 记录跳过原因。
            return  # 无免费商品直接结束。
        self._buy_cell(1, 1, "general_shop_buy_confirm")  # 购买第一列第 1 格免费商品。
        if self.wait_feature("shop_general_free", time_out=3, raise_if_not_found=False) is not None:  # 判断是否仍有免费刷新机会。
            self.wait_click_feature("shop_general_refresh", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击免费刷新按钮。
            if self.wait_feature("general_shop_refresh_zero", time_out=5, raise_if_not_found=False) is not None:  # 判断刷新确认弹窗是否零消耗。
                self.wait_click_feature("general_shop_refresh_confirm", time_out=10, raise_if_not_found=True, after_sleep=1)  # 确认刷新。
                self.next_frame()  # 刷新一帧，确保读取刷新后的画面。
                if not self._is_sold_out(1, 1):  # 刷新后第 1 格可购买（非售罄）则再买一次。
                    self._buy_cell(1, 1, "general_shop_buy_confirm")  # 再次购买第一列第 1 格。
            else:  # 刷新弹窗非零消耗（需花费货币）。
                self.wait_click_feature("general_shop_refresh_cancel", time_out=10, raise_if_not_found=True, after_sleep=1)  # 取消刷新。

    def _do_arena_shop(self):  # 竞技场商店：代码模板匹配前 3 格 + 固定列 4/5/6。
        for item in self.config.get("优先购买列", []):  # 按用户配置的优先顺序遍历。
            if item in _CODE_TEMPLATES:  # 代码类商品，需在前 3 格模板匹配。
                template_path = _CODE_TEMPLATES[item]  # 取对应模板路径。
                for col in range(1, 4):  # 依次扫描第一列第 1-3 格。
                    if self._is_sold_out(1, col):  # 已售罄则跳过该格。
                        continue  # 检查下一格。
                    if self.find_scaled_template(item, template_path, box=self._cell_box(1, col)) is not None:  # 在该格区域命中模板。
                        if not self._buy_cell(1, col, "shop_buy_confirm"):  # 购买，货币不足则停止。
                            return  # 货币不足，结束竞技场购买。
                        break  # 已买到该商品，跳出列扫描处理下一个配置项。
            else:  # 固定列位商品（代码手册/简介礼包/公司武器熔炉）。
                col = _ARENA_FIXED_SLOT.get(item)  # 取固定列号。
                if col is None:  # 未知商品名则跳过。
                    continue  # 处理下一个配置项。
                if not self._is_sold_out(1, col):  # 该格未售罄才购买。
                    if not self._buy_cell(1, col, "shop_buy_confirm"):  # 购买，货币不足则停止。
                        return  # 货币不足，结束竞技场购买。

    def _do_scrap_shop(self):  # 废铁商店：按固定列位购买骨架商品与货币商品，两种货币独立判断。
        # 货币分界：第一列第 1-3 格使用废铁骨架，其余格子使用破碎核心。
        # 两种货币互相独立：骨架不足只停骨架轮次，核心商品仍继续购买；反之亦然。
        for item in self.config.get("废铁骨架优先购买列", []):  # 遍历骨架优先购买列表。
            col = _SCRAP_BONE_SLOT.get(item)  # 取固定列号。
            if col is None:  # 未知商品名则跳过。
                continue  # 处理下一个。
            if not self._is_sold_out(1, col):  # 该格未售罄才购买。
                if not self._buy_cell(1, col, "shop_buy_confirm"):  # 骨架货币不足则停止本轮。
                    self.log_warning("废铁骨架不足，停止骨架商品购买，继续购买破碎核心商品。")  # 记录原因。
                    break  # 只跳出骨架轮次，核心商品继续购买。
        for item in self.config.get("破碎核心货币购买列", []):  # 遍历货币购买列表。
            for row, col in _BROKEN_CORE_SLOT.get(item, []):  # 部分商品跨多格，逐格处理。
                if not self._is_sold_out(row, col):  # 该格未售罄才购买。
                    if not self._buy_cell(row, col, "shop_buy_confirm"):  # 核心货币不足则停止本轮。
                        self.log_warning("破碎核心不足，停止核心商品购买。")  # 记录原因。
                        break  # 核心是最后一轮，跳出后函数自然结束。

    # ---- 入口 / 切换 / 退出 ----

    def _assert_shop_title(self, keyword):  # 在 shop_title 区域 OCR 确认当前商店名称。
        try:  # coco 特征可能缺失。
            title_box = self.get_box_by_name("shop_title")  # 获取商店标题标注区域（已按当前分辨率缩放）。
        except ValueError:  # 特征缺失时抛等待失败异常。
            raise WaitFailedException("shop_title 特征缺失")  # 由 try_step 捕获恢复。
        if self.wait_ocr(box=title_box, match=keyword, time_out=10, raise_if_not_found=False) is None:  # OCR 未匹配到关键词。
            raise WaitFailedException(f"未确认进入商店：{keyword}")  # 抛异常由 try_step 捕获恢复。

    def _enter_general_shop(self):  # 从大厅进入普通商店。
        self.wait_click_feature("shop", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击大厅商店入口。
        self._assert_shop_title("普通商店")  # OCR 确认已进入普通商店。

    def _switch_to_arena(self):  # 从普通商店切换到竞技场商店。
        self.wait_click_feature("shop_arena", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击竞技场商店标签。
        self._assert_shop_title("竞技场商店")  # OCR 确认已进入竞技场商店。

    def _switch_to_scrap(self):  # 从普通商店切换到废铁商店。
        self.wait_click_feature("shop_recyling", time_out=10, raise_if_not_found=True, after_sleep=1)  # 点击废铁商店标签。
        self._assert_shop_title("废铁商店")  # OCR 确认已进入废铁商店。

    def _exit_to_lobby(self):  # 退出商店返回大厅。
        home = self.find_one("common_home")  # 查找大厅按钮。
        if home is not None:  # 找到则点击返回大厅。
            self.click_box(home, after_sleep=1)  # 点击大厅按钮并等待。
        self.wait_for_lobby(time_out=10, raise_if_not_found=False)  # 等待确认回到大厅，超时不报错由上层处理。

    # ---- 合并子流程（re-entrant，由 try_step 包裹）----

    def _has_pending_shops(self):  # 是否存在开启且未完成的商店。
        return any(  # 任一开启且未完成即返回 True。
            self.config.get(name) and not self.is_done(key, period)  # 开关开启且本周期未完成。
            for name, key, period in (  # 三家商店的 (配置键, 完成状态键, 周期)。
                ("普通商店", "shop_general", "day"),  # 普通商店每日刷新。
                ("竞技场商店", "shop_arena", "day"),  # 竞技场商店每日刷新。
                ("废铁商店", "shop_scrap", "week"),  # 废铁商店每周刷新。
            )
        )

    def _combined_shop_step(self):  # 合并子流程：一次进店，按 普通→竞技场→废铁 顺序连续处理开启的商店后统一退出。
        self._enter_general_shop()  # 进入普通商店。
        if self.config.get("普通商店") and not self.is_done("shop_general", "day"):  # 普通商店开启且本日未完成。
            try:  # 单家失败不中断整体流程。
                self._do_general_shop()  # 执行普通商店购买。
                self.mark_done("shop_general", "day")  # 成功才标记本日已完成。
            except WaitFailedException as e:  # 普通商店购买失败。
                self.log_warning(f"普通商店失败，跳过：{e}")  # 记录失败并继续后续商店。
        if self.config.get("竞技场商店") and not self.is_done("shop_arena", "day"):  # 竞技场商店开启且本日未完成。
            try:  # 单家失败不中断整体流程。
                self._switch_to_arena()  # 切换到竞技场商店。
                self._do_arena_shop()  # 执行竞技场购买。
                self.mark_done("shop_arena", "day")  # 成功才标记本日已完成。
            except WaitFailedException as e:  # 竞技场购买失败。
                self.log_warning(f"竞技场商店失败，跳过：{e}")  # 记录失败并继续后续商店。
        if self.config.get("废铁商店") and not self.is_done("shop_scrap", "week"):  # 废铁商店开启且本周未完成。
            try:  # 单家失败不中断整体流程。
                self._switch_to_scrap()  # 切换到废铁商店。
                self._do_scrap_shop()  # 执行废铁购买。
                self.mark_done("shop_scrap", "week")  # 成功才标记本周已完成。
            except WaitFailedException as e:  # 废铁购买失败。
                self.log_warning(f"废铁商店失败，跳过：{e}")  # 记录失败并继续后续商店。
        self._exit_to_lobby()  # 统一退出回大厅。

    # ---- run 入口 ----

    def run(self):  # 任务执行入口，一次进店连续处理开启的商店。
        self.log_info("商店任务开始。")  # 记录任务开始。
        if not self.wait_until_lobby_after_start():  # 启动后等待进入游戏大厅，失败则中止。
            self.log_error("未能进入游戏大厅，中止商店任务。")  # 记录失败原因。
            return  # 结束本次执行。
        if not self._has_pending_shops():  # 没有开启且未完成的商店。
            self.log_info("开启的商店均已完成，跳过。")  # 记录跳过。
            return  # 结束本次执行。
        self.try_step(self._combined_shop_step, name="商店", raise_on_fail=False)  # 合并子流程：进店→连续切换→统一退出，失败不中断。
        self.log_info("商店任务完成。")  # 记录任务完成。
