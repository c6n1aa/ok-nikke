from PySide6.QtWidgets import QApplication
from qfluentwidgets import ExpandSettingCard, FluentIcon, SwitchButton

from ok import Logger, og
from ok.gui.tasks.ConfigItemFactory import config_widget
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.widget.ExpandCardLayout import ExpandCardLayout
from ok.gui.widget.Tab import Tab

from src.tasks.DailyTask import DailyTask
from src.tasks.HarvestTask import HarvestTask
from src.tasks.OutpostDefenseTask import OutpostDefenseTask


class SubTaskCard(ExpandSettingCard):
    """带开关的可展开卡片，覆盖高度逻辑，避免展开后收起残留空白。

    基类用滚动条动画缩放高度，动画被打断时高度复原不完整；这里改为直接设置
    收起=头部高度、展开=头部+内容高度，与任务列表 ConfigCard 的修复方式一致。
    """

    def setExpand(self, isExpand: bool):
        if self.isExpand == isExpand:
            return
        header_height = self.viewportMargins().top()
        content_height = self._visible_content_height()
        target_height = header_height + content_height if isExpand else header_height
        parent = self.parentWidget()
        parent_updates_enabled = parent is not None and parent.updatesEnabled()
        if parent_updates_enabled:
            parent.setUpdatesEnabled(False)
        self.expandAni.stop()
        try:
            self.spaceWidget.hide()
            self.verticalScrollBar().setValue(0)
            self.isExpand = isExpand
            self.setProperty('isExpand', isExpand)
            self.setStyle(QApplication.style())
            self.card.expandButton.setExpand(isExpand)
            self.setFixedHeight(target_height)
            parent_layout = parent.layout() if parent is not None else None
            if parent_layout is not None:
                parent_layout.invalidate()
                parent_layout.activate()
        finally:
            if parent_updates_enabled:
                parent.setUpdatesEnabled(True)
                parent.update()

    def _adjustViewSize(self):
        self.spaceWidget.hide()
        if self.isExpand:
            self.setFixedHeight(self.viewportMargins().top() + self._visible_content_height())

    def _visible_content_height(self):
        margins = self.viewLayout.contentsMargins()
        self.viewLayout.activate()
        bottom = margins.top()
        for index in range(self.viewLayout.count()):
            item = self.viewLayout.itemAt(index)
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            bottom = max(bottom, item.geometry().bottom() + 1)
        return bottom + margins.bottom()


class DailyTab(CustomTab):

    SUB_TASKS = [
        (HarvestTask, "收获"),
        (OutpostDefenseTask, "歼灭"),
    ]

    def __init__(self):
        # CustomTab.__init__ 不接受 layout_class，改用 ExpandCardLayout 让展开/收起带位移动画
        Tab.__init__(self, layout_class=ExpandCardLayout)
        self.logger = Logger.get_logger(self.__class__.__name__)
        self.executor = None
        self.logger.info(f'DailyTab init {self.__class__.__name__}')
        self.icon = FluentIcon.CALENDAR
        self.daily_task = self._get_task(DailyTask)
        self._build_ui()

    @property
    def name(self):
        return "日常设置"

    def _get_task(self, cls):
        # custom tab 构造时 self.executor 尚未注入，任务列表已就绪，直接走 og.executor
        if og.executor:
            return og.executor.get_task_by_class(cls)
        return None

    def _build_sub_task_card(self, task, daily_key):
        card = SubTaskCard(task.icon or FluentIcon.INFO, task.name, task.description, self)
        switch = SwitchButton(parent=card)
        switch.setOnText("启用")
        switch.setOffText("关闭")
        switch.setChecked(bool(self.daily_task.config.get(daily_key, False)))
        switch.checkedChanged.connect(lambda checked, k=daily_key: self._set_daily_switch(k, checked))
        card.addWidget(switch)
        card.viewLayout.setContentsMargins(6, 4, 6, 8)
        card.viewLayout.setSpacing(0)
        for key in task.default_config:
            if key.startswith('_'):
                continue
            row = config_widget(task.config_type, task.config_description, task.config,
                                key, task.config.get(key), task)
            card.viewLayout.addWidget(row)
        return card

    def _set_daily_switch(self, key, checked):
        self.daily_task.config[key] = checked

    def _build_ui(self):
        if self.daily_task is None:
            self.logger.warning('DailyTask not found, DailyTab skipped')
            return
        for task_cls, daily_key in self.SUB_TASKS:
            task = self._get_task(task_cls)
            if task is None:
                continue
            if daily_key not in self.daily_task.default_config:
                self.logger.warning(f'daily config key missing: {daily_key}')
                continue
            self.add_widget(self._build_sub_task_card(task, daily_key))