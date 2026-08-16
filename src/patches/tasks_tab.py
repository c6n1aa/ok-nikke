from ok import Logger

logger = Logger.get_logger(__name__)


def _patch_tasks_tab_daily_card():
    # 任务列表里日常任务卡片展开后只保留标准按钮配置行（日常开关已迁移到
    # 「日常设置」tab），按钮点击跳转到日常设置 tab。按钮行由 DailyTask 的
    # config_type 按钮配置渲染，样式与其他任务的设置行保持一致。
    from ok.gui.tasks.TaskCard import TaskCard

    original_init = TaskCard.__init__

    def _init(self, task, onetime):
        original_init(self, task, onetime)
        from src.tasks.DailyTask import DailyTask
        if isinstance(task, DailyTask):
            self._replace_content_with_daily_navigation()

    def _replace_content_with_daily_navigation(self):
        from src.tasks.DailyTask import DailyTask
        button_key = DailyTask.DAILY_SETTINGS_BUTTON_KEY
        button_widget = self.config_widget_by_key.get(button_key)
        if button_widget is None:
            return
        # 从布局中移除开关行和 Operation 行（含 Reset Config 按钮），只留按钮行
        for index in range(self.viewLayout.count() - 1, -1, -1):
            widget = self.viewLayout.itemAt(index).widget()
            if widget is not None and widget is not button_widget:
                self.viewLayout.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()
        self.config_widgets = [button_widget]
        self.config_widget_by_key = {button_key: button_widget}
        self.config_keys = [button_key]
        self._adjust_config_content_size()

    TaskCard.__init__ = _init
    TaskCard._replace_content_with_daily_navigation = _replace_content_with_daily_navigation
    logger.info('patched TaskCard to keep only the daily settings navigation button')


def _patch_tasks_tab_daily_pin():
    # 任务列表把日常任务卡片置顶，并在其下方插入一条分割线。
    # 刷新(任务列表变化)时会先移除旧分割线再重建，避免累积重复。
    from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
    from ok.gui.widget.ExpandCardLayout import ExpandCardLayout
    from PySide6.QtWidgets import QWidgetItem
    from qfluentwidgets import HorizontalSeparator

    # ExpandCardLayout 增加按索引插入，用于在卡片之间插分割线
    if not hasattr(ExpandCardLayout, 'insertWidget'):
        def _insert_widget(self, index, widget):
            if self.indexOf(widget) >= 0:
                return
            parent = self.parentWidget()
            if parent is not None and widget.parentWidget() is not parent:
                widget.setParent(parent)
            widgets = self._ExpandLayout__widgets
            items = self._ExpandLayout__items
            widgets.insert(index, widget)
            widget.installEventFilter(self)
            items.insert(index, QWidgetItem(widget))
        ExpandCardLayout.insertWidget = _insert_widget

    original_refresh_ui = OneTimeTaskTab.refresh_ui

    def _refresh_ui(self):
        original_refresh_ui(self)
        from src.tasks.DailyTask import DailyTask
        layout = self.taskCardLayout

        # 清理上一次刷新留下的分割线
        separator = getattr(self, '_daily_separator', None)
        if separator is not None:
            layout.removeWidget(separator)
            separator.deleteLater()
            self._daily_separator = None

        daily_card = next(
            (card for card in self.card_widgets
             if isinstance(getattr(card, 'task', None), DailyTask)),
            None)
        if daily_card is None:
            return

        # 置顶位置：排在任务信息容器之后、其他任务卡片之前
        insert_index = 0
        info_container = getattr(self, 'task_info_container', None)
        if info_container is not None:
            info_index = layout.indexOf(info_container)
            if info_index >= 0:
                insert_index = info_index + 1

        if layout.indexOf(daily_card) != insert_index:
            layout.removeWidget(daily_card)
            layout.insertWidget(insert_index, daily_card)

        separator = HorizontalSeparator()
        layout.insertWidget(insert_index + 1, separator)
        self._daily_separator = separator
        layout.invalidate()
        layout.activate()

    OneTimeTaskTab.refresh_ui = _refresh_ui
    logger.info('patched OneTimeTaskTab.refresh_ui to pin DailyTask card on top with a divider')


def apply():
    # 任务列表：日常任务卡片置顶并插分割线，展开后只显示跳转日常设置按钮
    _patch_tasks_tab_daily_pin()
    _patch_tasks_tab_daily_card()