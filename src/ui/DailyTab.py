from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from qfluentwidgets import ExpandSettingCard, FluentIcon, SwitchButton

from ok import Logger, og
from ok.gui.tasks.ConfigCard import ConfigContentMixin
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.widget.ExpandCardLayout import ExpandCardLayout
from ok.gui.widget.Tab import Tab

from src.tasks.DailyTask import DailyTask
from src.tasks.HarvestTask import HarvestTask
from src.tasks.OutpostDefenseTask import OutpostDefenseTask
from src.tasks.ShopTask import ShopTask
from src.tasks.CashShopTask import CashShopTask
from src.tasks.ArkTask import ArkTask


class SubTaskCard(ConfigContentMixin, ExpandSettingCard):
    """带开关的可展开卡片，配置区复用 ConfigContentMixin 以支持 sub_configs 联动显隐。

    覆盖高度逻辑，避免展开后收起残留空白。基类用滚动条动画缩放高度，动画被打断时
    高度复原不完整；这里改为直接设置收起=头部高度、展开=头部+内容高度，与任务列表
    ConfigCard 的修复方式一致。
    """

    def __init__(self, icon, title, content, task, config, default_config,
                 config_description, config_type, parent=None):
        super().__init__(icon, title, content, parent)
        # 复用 ConfigCard 的配置渲染：解析 sub_configs、连接开关联动、按开关值显隐子配置。
        self._init_config_content(task, config, default_config, config_description, config_type)

    def add_buttons(self):
        # 子任务卡片不显示 Reset Config / 快捷方式等操作行。
        pass

    def refresh_status_icon(self):
        """根据任务完成状态刷新头部图标：已完成用 FluentIcon.COMPLETED，未完成用回默认图标。"""
        is_completed = getattr(self.task, "is_completed", None)  # 任务是否提供完成判断。
        completed = bool(is_completed and is_completed())  # 计算当前是否已完成。
        icon = FluentIcon.COMPLETED if completed else (self.task.icon or FluentIcon.INFO)  # 选择状态图标。
        self.card.iconLabel.setIcon(icon)  # 更新头部图标。

    def showEvent(self, event):
        super().showEvent(event)
        if self.isExpand:
            # 首次显示时布局才就绪，延迟一帧重新计算高度，避免展开不完整（同 ConfigCard）。
            QTimer.singleShot(0, self._adjustViewSize)

    def _adjust_config_content_size(self):
        # 开关联动时 __sync_sub_config_order 刚移除/重插过布局行；_visible_content_height
        # 内部会临时撑开容器保证几何准确，这里同步调整高度即可，避免行重排与高度调整
        # 跨帧导致内容闪烁。
        self._adjustViewSize()

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
        # __sync_sub_config_order 移除/重插行后，若容器高度仍是旧值，QVBoxLayout 会把全部
        # 行压缩重叠（几何不可信）。先临时撑开卡片高度让行按真实尺寸布局，取完几何再恢复，
        # 保证返回的高度准确、与任务列表 ConfigCard 一致且不残留空白。
        margins = self.viewLayout.contentsMargins()
        fixed_height = self.height()
        self.setFixedHeight(fixed_height + 100000)
        self.viewLayout.activate()
        bottom = margins.top()
        for index in range(self.viewLayout.count()):
            item = self.viewLayout.itemAt(index)
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            bottom = max(bottom, item.geometry().bottom() + 1)
        result = bottom + margins.bottom()
        self.setFixedHeight(fixed_height)
        return result


class DailyTab(CustomTab):

    SUB_TASKS = [
        (HarvestTask, "收获"),
        (OutpostDefenseTask, "歼灭"),
        (ShopTask, "商店"),
        (CashShopTask, "付费商店"),
        (ArkTask, "方舟"),
    ]

    def __init__(self):
        # CustomTab.__init__ 不接受 layout_class，改用 ExpandCardLayout 让展开/收起带位移动画
        Tab.__init__(self, layout_class=ExpandCardLayout)
        self.logger = Logger.get_logger(self.__class__.__name__)
        self.executor = None
        self.logger.info(f'DailyTab init {self.__class__.__name__}')
        self.icon = FluentIcon.CALENDAR
        self.daily_task = self._get_task(DailyTask)
        # 每个子任务卡片 (父开关, 开关控件, 卡片)，供显示时刷新同步。
        self._cards = []
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
        card = SubTaskCard(task.icon or FluentIcon.INFO, task.name, task.description,
                           task, task.config, task.default_config,
                           task.config_description, task.config_type, self)
        switch = SwitchButton(parent=card)
        switch.setOnText("启用")
        switch.setOffText("关闭")
        switch.setChecked(bool(self.daily_task.config.get(daily_key, False)))
        switch.checkedChanged.connect(lambda checked, k=daily_key: self._set_daily_switch(k, checked))
        card.addWidget(switch)
        card.refresh_status_icon()  # 初始设置完成状态图标（未完成=空心圆）。
        self._cards.append((daily_key, switch, card))
        return card

    def _refresh_ui(self):
        # 切到本 tab 时把控件同步为当前 config，覆盖在任务 tab 修改后与本 tab 的差异。
        for daily_key, switch, card in self._cards:
            value = bool(self.daily_task.config.get(daily_key, False))  # 读取父任务开关当前值。
            if switch.isChecked() != value:  # 值不同才 setChecked，避免冗余信号。
                switch.setChecked(value)  # 同步父任务开关。
            card.update_config()  # 刷新子任务全部配置控件 + 应用 sub_configs 可见性。
            card.refresh_status_icon()  # 刷新完成状态图标。

    def showEvent(self, event):
        super().showEvent(event)  # 先走基类事件。
        self._refresh_ui()  # 显示时刷新一次控件状态。

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