from ok import Logger

logger = Logger.get_logger(__name__)


def _disable_overlay_boxes():
    # 正式版没有开启悬浮窗的入口，历史配置里 use_overlay 为 True 的用户要显式关掉：
    # 框架 initialize_overlay 在 UI 构建之后才执行，只看持久化配置，不清就会自己冒出标记框悬浮窗且无法关闭。
    try:
        from ok import og
        if og.app.overlay_state().get('boxes'):
            og.app.set_overlay_setting('boxes', False)
            logger.info('release build: disabled persisted overlay boxes setting')
    except Exception as e:
        logger.error('disable overlay boxes error', e)


def _patch_start_tab_hide_overlay_switch():
    # 正式版保留 StartTab 底部的「Debug」卡片（导出日志/打开安装目录、截图目录、日志目录/查看日志/OCR 等排障入口），
    # 只去掉卡片里的「调试悬浮窗」开关（Enable/Disable Boxes，ok-script 2.0.6 起并入该卡片）；debug 模式保留。
    from ok.ui.qt.start.StartTab import StartTab

    original_init = StartTab.__init__

    def _init(self, config, exit_event):
        original_init(self, config, exit_event)
        if bool(config.get('debug')):
            return
        overlay_switch = getattr(self, 'overlay_switch', None)
        if overlay_switch is not None:
            overlay_switch.setVisible(False)  # 只隐藏不销毁，框架后续仍会读写这个开关的状态。
            logger.info('release build: hid the overlay boxes switch in the StartTab Debug card')
        _disable_overlay_boxes()

    StartTab.__init__ = _init
    logger.info('patched StartTab to keep the Debug card and hide the overlay switch outside debug mode')


def apply():
    # 截图方式 tab：正式版保留 Debug 排障卡片，只隐藏调试悬浮窗开关
    _patch_start_tab_hide_overlay_switch()
