from src.tasks.HarvestTask import HarvestTask  # 导入收获子任务。
from src.tasks.MyBaseTask import MyBaseTask  # 导入项目基类，所有任务统一继承它。
from src.tasks.OutpostDefenseTask import OutpostDefenseTask  # 导入歼灭子任务。


class DailyTask(MyBaseTask):  # 定义清日常总编排的父任务类。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "日常"  # 任务显示名称。
        self.description = "按顺序执行勾选好的日常子流程。"  # 任务说明。
        self.default_config.update({  # 父任务配置：为每个子流程放一个常驻开关。
            "收获": True,  # 收获子流程的开关。
            "歼灭": True,  # 歼灭子流程的开关。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "收获": "是否执行收获（友情点、邮箱）。",
            "歼灭": "是否执行前哨基地歼灭。",
        })

    def run(self):  # 父任务执行入口，按顺序编排子流程。
        self.log_info("日常开始。")  # 记录父任务开始。
        if self.config.get("收获"):  # 只有开关开启时才执行收获。
            self.run_task_by_class(HarvestTask)  # 运行收获子任务，子任务读取自己的配置。
        if self.config.get("歼灭"):  # 只有开关开启时才执行歼灭。
            self.run_task_by_class(OutpostDefenseTask)  # 运行歼灭子任务，子任务读取自己的配置。
        # 后续新增子流程时，在此追加相同的开关判断和 run_task_by_class 调用即可。
        self.log_info("日常完成。")  # 记录父任务执行完成。
