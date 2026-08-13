from src.tasks.MyBaseTask import MyBaseTask  # 导入项目基类，子任务统一继承它。


class SweepDungeonTask(MyBaseTask):  # 定义副本清扫子任务类。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "清扫副本"  # 任务显示名称。
        self.description = "清扫指定关卡并执行设定次数。"  # 任务说明。
        self.default_config.update({  # 子任务专属设置，独立持久化到 configs/。
            "关卡": "困难5-1",  # 要清扫的关卡。
            "次数": 10,  # 清扫次数。
            "自动战斗": True,  # 是否开启自动战斗。
        })
        self.config_description.update({  # 每个配置项的帮助文本。
            "关卡": "要清扫的关卡。",
            "次数": "清扫次数。",
            "自动战斗": "清扫时是否开启自动战斗。",
        })

    def run(self):  # 子任务执行入口。
        stage = self.config.get("关卡")  # 读取关卡配置。
        times = self.config.get("次数")  # 读取清扫次数。
        auto = self.config.get("自动战斗")  # 读取自动战斗开关。
        self.log_info(f"开始清扫 {stage}，共 {times} 次，自动战斗：{auto}")  # 记录本次清扫参数。
        # TODO: 在此接入清扫副本的实际自动化逻辑，用 wait_ocr / wait_click_feature 驱动界面状态流转。
        self.log_info("清扫副本完成。")  # 记录子流程完成。
