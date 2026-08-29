from ok import Logger

logger = Logger.get_logger(__name__)

# 通知配置仅保留「系统通知」一项，其余渠道(Discord/Telegram/企业微信/QQ等)移除。
# NotificationManager 读取这些键都是 config.get()，缺键即视为禁用，裁剪安全。


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
        for key in list(options.default_config):
            if key not in keep_keys:
                options.default_config.pop(key, None)
                options.config_description.pop(key, None)
                if options.config_type:
                    options.config_type.pop(key, None)
        options.description = '任务结束或出错时弹出 Windows 系统通知'
        return options

    _global_config_module.create_notification_options = _create_notification_options
    logger.info('patched create_notification_options to merge notification into settings tab')


def apply():
    _patch_notification_tab()
