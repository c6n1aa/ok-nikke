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


def _patch_tasks_tab_sync_config_on_show():
    # 任务列表切回本 tab 时把卡片控件同步为 task.config 当前值。
    # 「日常设置」tab 直接写共享的 task.config 字典，任务列表卡片不会自动感知，
    # 因此在显示时对每张卡片调用 update_config()（逐个 update_value + 刷新子配置可见性），
    # 与 DailyTab._refresh_ui 的同步策略保持一致。
    from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab

    original_show_event = OneTimeTaskTab.showEvent

    def _show_event(self, event):
        original_show_event(self, event)  # 先走基类事件处理（QWidget.showEvent）。
        for card in getattr(self, 'card_widgets', []):  # 遍历本 tab 的所有任务卡片。
            update_config = getattr(card, 'update_config', None)  # 卡片都提供 update_config。
            if update_config is not None:  # 从共享 task.config 重新读取并同步控件值。
                update_config()

    OneTimeTaskTab.showEvent = _show_event
    logger.info('patched OneTimeTaskTab.showEvent to sync task card config from task.config')


def _patch_tasks_tab_reset_done_button():
    # 任务列表里收获/歼灭/商店卡片展开后的 Operation 行、Reset Config 前注入
    # 「重置完成状态」按钮，便于用户改完配置后一键清除完成状态并重跑。
    # 仅对有 done_keys 的 MyBaseTask 子任务显示；纯编排的 DailyTask 无 done_keys 不显示。
    from PySide6.QtWidgets import QHBoxLayout
    from qfluentwidgets import FluentIcon, InfoBar, PushButton

    from ok.gui.tasks.ConfigCard import ConfigContentMixin
    from src.tasks.MyBaseTask import MyBaseTask

    original_add_buttons = ConfigContentMixin.add_buttons

    def _add_buttons(self):
        original_add_buttons(self)  # 先走原逻辑创建 Operation 行与 Reset Config。
        if not self._has_done_state():  # 无完成状态的任务不加按钮。
            return
        buttons_layout = self._operation_buttons_layout()  # 定位 Operation 行的按钮布局。
        if buttons_layout is None or self.reset_config is None:  # 找不到锚点则跳过。
            return
        reset_done = PushButton(FluentIcon.SYNC, "重置完成状态")  # 按钮固定文字。
        buttons_layout.insertWidget(buttons_layout.indexOf(self.reset_config), reset_done)  # 插到 Reset Config 前。
        reset_done.clicked.connect(self._reset_done_clicked)  # 连接重置回调。

    def _has_done_state(self):
        # 只有带完成状态（done_keys 非空）的 MyBaseTask 子任务才需要该按钮。
        return isinstance(self.task, MyBaseTask) and bool(getattr(self.task, "done_keys", None))

    def _operation_buttons_layout(self):
        # Operation 行是 viewLayout 最后一个 LabelAndWidget；其主布局里嵌套的
        # QHBoxLayout 承载 Reset Config 等按钮。从 reset_config 父控件定位该按钮布局。
        if self.reset_config is None:  # 没有 Reset Config 按钮则无处插入。
            return None
        row = self.reset_config.parentWidget()  # 按钮的父控件即 Operation 行。
        main_layout = getattr(row, "layout", None)  # Operation 行的主布局。
        if main_layout is None:  # 主布局缺失则无法定位。
            return None
        for i in range(main_layout.count()):  # 遍历主布局中的子布局。
            sub = main_layout.itemAt(i).layout()  # 取出子布局。
            if isinstance(sub, QHBoxLayout):  # 按钮所在的 QHBoxLayout。
                return sub
        return None

    def _reset_done_clicked(self):
        self.task.clear_done_all()  # 清除任务所有完成状态并落盘。
        InfoBar.success(  # 提示用户重置成功。
            title="已重置完成状态",
            content=f"{self.task.name} 的完成状态已清除，可重新执行。",
            parent=self.window(),
        )

    ConfigContentMixin.add_buttons = _add_buttons
    ConfigContentMixin._has_done_state = _has_done_state
    ConfigContentMixin._operation_buttons_layout = _operation_buttons_layout
    ConfigContentMixin._reset_done_clicked = _reset_done_clicked
    logger.info('patched ConfigContentMixin.add_buttons to add reset-done-state button')


def apply():
    # 任务列表：日常任务卡片置顶并插分割线，展开后只显示跳转日常设置按钮
    _patch_tasks_tab_daily_pin()
    _patch_tasks_tab_daily_card()
    _patch_tasks_tab_sync_config_on_show()
    _patch_tasks_tab_reset_done_button()