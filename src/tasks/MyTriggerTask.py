from ok import TriggerTask

from src.tasks.MyBaseTask import MyBaseTask


class MyTriggerTask(MyBaseTask, TriggerTask):
    # 继承 MyBaseTask 以获得周期执行状态机制（is_done/mark_done/clear_done）。
    # 同时继承 TriggerTask 保持后台触发能力；MRO: MyTriggerTask → MyBaseTask → TriggerTask → BaseTask。

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "触发器会不断调用run方法"
        self.description = "一般根据frame来判断是否需要运行"
        self.trigger_count = 0

    def run(self):
        self.trigger_count += 1
        self.log_debug(f'MyTriggerTask run {self.trigger_count}')



