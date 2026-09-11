from ok import Logger

logger = Logger.get_logger(__name__)


def _patch_start_tab_hide_debug_overlay():
    # 正式版（非 debug 启动）隐藏「截图方式」tab（框架 StartTab）底部的
    # 「调试悬浮窗」卡片：该卡片只有标记框/悬浮窗日志两个调试开关，
    # 面向最终用户没有意义；debug 模式（main_debug.py 启动）下保留便于调试。
    from ok.ui.qt.start.StartTab import StartTab

    original_init = StartTab.__init__

    def _init(self, config, exit_event):
        overlay_card = None
        original_add_card = self.add_card  # 先捕获绑定方法，实例属性赋值后再还原。

        def _add_card(title, widget, *args, **kwargs):
            container = original_add_card(title, widget, *args, **kwargs)
            if widget is getattr(self, 'overlay_widget', None):  # 「调试悬浮窗」卡片。
                nonlocal overlay_card
                overlay_card = container
            return container

        self.add_card = _add_card
        try:
            original_init(self, config, exit_event)
        finally:
            del self.add_card
        if overlay_card is not None and not bool(config.get('debug')):
            self.vBoxLayout.removeWidget(overlay_card)
            overlay_card.deleteLater()
            logger.info('release build: removed Debug Overlay card from StartTab')

    StartTab.__init__ = _init
    logger.info('patched StartTab to hide Debug Overlay card outside debug mode')


def apply():
    # 截图方式 tab：正式版隐藏「调试悬浮窗」卡片
    _patch_start_tab_hide_debug_overlay()
