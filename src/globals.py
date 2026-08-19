from PySide6.QtCore import QObject

from ok import Logger

logger = Logger.get_logger(__name__)


class Globals(QObject):

    def __init__(self, exit_event):
        super().__init__()
        # 在 og.global_config 就绪、设置 UI 枚举配置分区之前，用框架官方扩展点
        # 注册独立的「NIKKE 启动器」配置分区（取代对 create_basic_options 的猴子补丁注入）。
        from src.patches.basic_options import register_launcher_config
        register_launcher_config()

