from ok import og

from src.tasks.HarvestTask import HarvestTask  # 导入收获子任务。
from src.tasks.NikkeBaseTask import NikkeBaseTask  # 导入项目基类，所有任务统一继承它。
from src.tasks.OutpostDefenseTask import OutpostDefenseTask  # 导入歼灭子任务。
from src.tasks.OutpostTask import OutpostTask  # 导入前哨基地子任务（派遣/咨询）。
from src.tasks.ShopTask import ShopTask  # 导入商店子任务。
from src.tasks.CashShopTask import CashShopTask  # 导入付费商店子任务。
from src.tasks.ArkTask import ArkTask  # 导入方舟子任务（企业塔/模拟室/拦截战/竞技场）。
from src.tasks.RaidTask import RaidTask  # 导入讨伐子任务（协同作战/个人突袭）。


class DailyTask(NikkeBaseTask):  # 定义清日常总编排的父任务类。

    DAILY_SETTINGS_BUTTON_KEY = "点击前往日常任务设置"  # 任务列表卡片里跳转日常设置 tab 的按钮配置键。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "日常"  # 任务显示名称。
        self.description = "按日常任务设置进行自动化操作。"  # 任务说明。
        self.default_config.update({  # 父任务配置：为每个子流程放一个常驻开关。
            "收获": True,  # 收获子流程的开关。
            "歼灭": True,  # 歼灭子流程的开关。
            "前哨基地": True,  # 前哨基地子流程的开关。
            "商店": True,  # 商店子流程的开关。
            "付费商店": True,  # 付费商店子流程的开关。
            "方舟": True,  # 方舟子流程的开关。
            "Raid": True,  # Raid子流程的开关。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "收获": "是否执行收获（友情点、邮箱）。",
            "歼灭": "是否执行前哨基地歼灭。",
            "前哨基地": "是否执行前哨基地（派遣/咨询）。",
            "商店": "是否执行商店购买（普通/竞技场/废铁）。",
            "付费商店": "是否执行付费商店免费礼包领取（STEP UP/每日/每周/每月）。",
            "方舟": "是否执行方舟（企业塔/模拟室/拦截战/竞技场）。",
            "Raid": "是否执行限时挑战活动（协同作战/个人突袭）。",
        })
        self.config_type.update({  # 任务列表的日常卡片展开后只显示这一个按钮行。
            self.DAILY_SETTINGS_BUTTON_KEY: {
                "type": "button",  # 复用标准按钮配置行，样式与其他任务设置保持一致。
                "text": "前往日常设置",  # 按钮文字。
                "callback": self.open_daily_settings,  # 点击后跳转到日常设置 tab。
            },
        })

    def open_daily_settings(self):  # 按钮点击回调：切换到「日常设置」tab。
        from src.ui.DailyTab import DailyTab  # 延迟导入，避免与 DailyTab 模块互相循环导入。
        mw = getattr(og, 'main_window', None)  # 主窗口在 show_main_window 后才挂到 og 上。
        if mw is None:  # 主窗口未就绪时不处理。
            return
        for index in range(mw.stackedWidget.count()):  # 遍历主窗口的页面栈。
            tab = mw.stackedWidget.widget(index)  # 逐个取出页面。
            if isinstance(tab, DailyTab):  # 找到日常设置 tab 实例。
                mw.switchTo(tab)  # 切换到该 tab。
                return

    def run(self):  # 父任务执行入口，按顺序编排子流程。
        self.log_info("日常开始。")  # 记录父任务开始。
        if not self.ensure_screen("lobby", raise_on_fail=False):  # 启动后就位游戏大厅（幂等闸门：含冷启动引导与弹窗清理），失败则中止后续任务。
            self.log_error("未能进入游戏大厅，中止日常任务。")  # 记录失败原因。
            return  # 结束本次执行，不执行子流程。
        if self.config.get("收获"):  # 只有开关开启时才执行收获。
            self.run_task_by_class(HarvestTask)  # 运行收获子任务，子任务读取自己的配置。
        if self.config.get("歼灭"):  # 只有开关开启时才执行歼灭。
            self.run_task_by_class(OutpostDefenseTask)  # 运行歼灭子任务，子任务读取自己的配置。
        if self.config.get("前哨基地"):  # 只有开关开启时才执行前哨基地。
            self.run_task_by_class(OutpostTask)  # 运行前哨基地子任务（派遣/咨询），子任务读取自己的配置。
        if self.config.get("商店"):  # 只有开关开启时才执行商店。
            self.run_task_by_class(ShopTask)  # 运行商店子任务，子任务读取自己的配置。
        if self.config.get("付费商店"):  # 只有开关开启时才执行付费商店。
            self.run_task_by_class(CashShopTask)  # 运行付费商店子任务，子任务读取自己的配置。
        if self.config.get("方舟"):  # 只有开关开启时才执行方舟。
            self.run_task_by_class(ArkTask)  # 运行方舟子任务，子任务读取自己的配置。
        if self.config.get("Raid"):  # 只有开关开启时才执行讨伐。
            self.run_task_by_class(RaidTask)  # 运行讨伐子任务，子任务读取自己的配置。
        # 后续新增子流程时，在此追加相同的开关判断和 run_task_by_class 调用即可。
        if self.config.get("方舟"):  # 只有开启方舟子流程才需要检查失败塔提醒。
            ark = self.get_task_by_class(ArkTask)  # 获取方舟子任务实例。
            if ark is not None:  # 子任务已注册。
                message = ark.failed_towers_message()  # 读取本次运行的战斗失败塔记录。
                if message:  # 存在战斗失败的塔。
                    self.log_info(message, notify=True)  # 在所有日常子任务执行完成后统一提醒。
        self.log_info("日常完成。")  # 记录父任务执行完成。
