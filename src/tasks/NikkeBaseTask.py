from ok import BaseTask

from src.screens import SCREENS  # 集中式界面注册表（全局界面在 __init__ 里统一加载进 self.screens）。
from src.tasks.base._battle import BattleMixin  # 战斗结束等待与中断哨兵。
from src.tasks.base._done_state import DoneStateMixin  # 完成状态与周期刷新。
from src.tasks.base._exceptions import InterruptedByDialogException  # 致命中断弹窗异常（此处重导出，兼容 `import src.tasks.NikkeBaseTask as nbt` 的外部引用）。
from src.tasks.base._foreground import ForegroundMixin  # 窗口前置。
from src.tasks.base._navigation import NavigationMixin  # 守卫式导航 + 失败恢复 + 冷启动。
from src.tasks.base._popups import PopupsMixin  # 弹窗/遮罩统一清理。
from src.tasks.base._screen import ScreenMixin  # 界面识别系统 + 帧级判定缓存。
from src.tasks.base._vision import VisionMixin  # 缩放模板匹配 / 红点 / 色彩判态。


class NikkeBaseTask(NavigationMixin, BattleMixin, PopupsMixin, ScreenMixin,
                    VisionMixin, ForegroundMixin, DoneStateMixin, BaseTask):
    """项目统一基类：组合 src/tasks/base/ 下的各职责 mixin。

    子任务一律继承本类（`from src.tasks.NikkeBaseTask import NikkeBaseTask`），
    不要直接 `import ok.BaseTask`。各职责的具体实现拆在 src/tasks/base/ 的
    mixin 里，本类只做组合与实例状态初始化。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 注册到 default_config，否则 verify_config 重载时会丢弃非 default 键，状态无法跨重启保留。
        self.default_config[self._execution_states_key] = {}
        # 按 (路径, 缩放比例) 缓存缩放后的模板，避免循环查找时反复读取/缩放。
        self._scaled_template_cache = {}
        # 界面识别注册表：界面名 -> 判定描述（features 为 coco 模板特征，keywords 为 OCR 关键词）。
        self.screens = {}
        # 从集中式注册表加载全部界面；任务仍可用 register_screen 追加私有界面，同名覆盖全局条目（后写者胜）。
        for _name, _spec in SCREENS.items():
            self.register_screen(_name, **_spec)
        # 帧级判定缓存：同一帧内重复的界面判定（模板匹配/区域 OCR）只真正执行一次。
        # 条目为 (计算时的帧对象, 结果)，读取时校验帧对象同一性——帧一换即失效，无陈旧风险。
        self._screen_cache = {}


__all__ = ["NikkeBaseTask", "InterruptedByDialogException"]  # 供外部 import 的公共对象。