# 受控的 venv ok-script 猴子补丁统一集中在这里。
# 约定：
# - 每个补丁按主题放进一个模块，模块暴露 apply() 应用自身补丁；
# - apply_all() 是唯一入口，在 src/config.py 顶部调用（早于 ok.OK(config) 构造）；
# - 项目内任何其他代码都不得自行修补 ok 包，新增补丁一律加到这里的对应模块，
#   不要手写自定义控件/到处散落补丁。
from src.patches import basic_options, runtime, start_controller, tasks_tab


def apply_all():
    basic_options.apply()   # 基础设置注入启动器路径等选项，需在 Config 加载磁盘配置前生效
    runtime.apply()         # 禁用 OpenVINO 遥测 + 任务执行期间保持游戏窗口前台
    start_controller.apply()  # 替换 StartController 为启动器自动化版本
    tasks_tab.apply()       # 任务列表：日常卡片置顶/分割线/只留跳转日常设置按钮