from ok import Logger

logger = Logger.get_logger(__name__)


def _patch_start_tab_hide_debug_card():
    # 正式版隐藏 StartTab 底部的「Debug」卡片（ok-script 2.0.6 起「调试悬浮窗」并入其中），debug 模式保留。
    from ok.ui.qt.start.StartTab import StartTab

    original_init = StartTab.__init__

    def _init(self, config, exit_event):
        debug_card = None
        original_add_card = self.add_card

        def _add_card(title, widget, *args, **kwargs):
            container = original_add_card(title, widget, *args, **kwargs)
            if widget is getattr(self, 'debug_widget', None):
                nonlocal debug_card
                debug_card = container
            return container

        self.add_card = _add_card
        try:
            original_init(self, config, exit_event)
        finally:
            del self.add_card
        if debug_card is not None and not bool(config.get('debug')):
            self.vBoxLayout.removeWidget(debug_card)
            debug_card.deleteLater()
            logger.info('release build: removed Debug card from StartTab')

    StartTab.__init__ = _init
    logger.info('patched StartTab to hide Debug card outside debug mode')


def apply():
    # 截图方式 tab：正式版隐藏「Debug」卡片
    _patch_start_tab_hide_debug_card()
