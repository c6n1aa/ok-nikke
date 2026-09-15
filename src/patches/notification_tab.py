from ok import Logger

logger = Logger.get_logger(__name__)

# 通知配置仅保留「系统通知」一项，其余渠道(Discord/Telegram/企业微信/QQ等)隐藏。
# 隐藏走框架 config_type 的 hidden 参数（ConfigContentMixin 跳过渲染），保留配置键与默认值；
# NotificationManager 各渠道按 config.get() 判断，默认 False 即禁用，与缺键等价。
#
# 此外注入本项目自定义项：启动刷新活动日历后「活动即将结束」应用内提示的开关。

# 活动日历「即将结束」应用内提示开关（通知配置卡片里的自定义项）
EXPIRE_NOTIFY_ENABLED_KEY = '活动结束提醒'

_EXPIRE_NOTIFY_DESCRIPTION = '应用启动刷新活动日历后，若发现 24 小时内结束的活动，在应用内弹出提示'


def _patch_notification_tab():
    # 通知全局配置默认 show_at_tab=True, 框架会为它单独创建底部铃铛 tab。
    # 包装工厂函数把它改为 False: MainWindow 不再建独立 tab, SettingTab 会把
    # 非 show_at_tab 的全局配置作为可展开卡片收进「软件设置」页。
    # 必须在 ok.OK(config) 构造前应用(apply_all 已保证),
    # 因为注册发生在 OK.__init__ 里且每次调用工厂都新建选项。
    import ok.util.GlobalConfig as _global_config_module
    keep_keys = {_global_config_module.SYSTEM_NOTIFICATION_ENABLED}

    original = _global_config_module.create_notification_options

    def _create_notification_options():
        options = original()
        options.show_at_tab = False
        if options.config_type is None:
            options.config_type = {}
        for key in options.default_config:
            if key not in keep_keys:
                options.config_type.setdefault(key, {})['hidden'] = True
        # 自定义项在隐藏循环之后注入，保证不会被上面的 hidden 逻辑误隐藏。
        options.default_config[EXPIRE_NOTIFY_ENABLED_KEY] = True
        options.config_description[EXPIRE_NOTIFY_ENABLED_KEY] = _EXPIRE_NOTIFY_DESCRIPTION
        options.description = '任务结束/出错的通知渠道与「活动即将结束」启动提醒开关'
        return options

    _global_config_module.create_notification_options = _create_notification_options
    logger.info('patched create_notification_options to merge notification into settings tab')


def apply():
    _patch_notification_tab()
