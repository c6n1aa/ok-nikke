from ok import og

from src.tasks.HarvestTask import HarvestTask  # 导入收获子任务。
from src.tasks.MyBaseTask import MyBaseTask  # 导入项目基类，所有任务统一继承它。
from src.tasks.OutpostDefenseTask import OutpostDefenseTask  # 导入歼灭子任务。
from src.tasks.ShopTask import ShopTask  # 导入商店子任务。


class DailyTask(MyBaseTask):  # 定义清日常总编排的父任务类。

    DAILY_SETTINGS_BUTTON_KEY = "点击前往日常任务设置"  # 任务列表卡片里跳转日常设置 tab 的按钮配置键。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "日常"  # 任务显示名称。
        self.description = "按日常任务设置进行自动化操作。"  # 任务说明。
        self.default_config.update({  # 父任务配置：为每个子流程放一个常驻开关。
            "收获": True,  # 收获子流程的开关。
            "歼灭": True,  # 歼灭子流程的开关。
            "商店": True,  # 商店子流程的开关。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "收获": "是否执行收获（友情点、邮箱）。",
            "歼灭": "是否执行前哨基地歼灭。",
            "商店": "是否执行商店购买（普通/竞技场/废铁）。",
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
        if not self.wait_until_lobby_after_start():  # 启动后等待进入游戏大厅（处理公告弹窗与 TOUCH TO CONTINUE），失败则中止后续任务。
            self.log_error("未能进入游戏大厅，中止日常任务。")  # 记录失败原因。
            return  # 结束本次执行，不执行子流程。
        if self.config.get("收获"):  # 只有开关开启时才执行收获。
            self.run_task_by_class(HarvestTask)  # 运行收获子任务，子任务读取自己的配置。
        if self.config.get("歼灭"):  # 只有开关开启时才执行歼灭。
            self.run_task_by_class(OutpostDefenseTask)  # 运行歼灭子任务，子任务读取自己的配置。
        if self.config.get("商店"):  # 只有开关开启时才执行商店。
            self.run_task_by_class(ShopTask)  # 运行商店子任务，子任务读取自己的配置。
        # 后续新增子流程时，在此追加相同的开关判断和 run_task_by_class 调用即可。
        self.log_info("日常完成。")  # 记录父任务执行完成。
