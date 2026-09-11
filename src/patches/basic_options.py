import os

from ok import Logger
import ok.util.GlobalConfig as _global_config_module

logger = Logger.get_logger(__name__)

# 基础设置中新增的启动器相关选项
LAUNCHER_PATH_KEY = '启动器路径'

# 后台触发任务轮询间隔(毫秒)，调高可降低系统资源占用
TRIGGER_INTERVAL_KEY = 'Trigger Interval'
TRIGGER_INTERVAL_MS = 100

# 与本项目无关、需要从基础设置中移除的选项
_BASIC_OPTIONS_REMOVE_KEYS = [
    'Mute Game while in Background',
    'Auto Resize Game Window',
    'Use DirectML',
    _global_config_module.KILL_LAUNCHER_AFTER_START,
    'Launch with DX11',
]

_basic_options_extra_default = {
    LAUNCHER_PATH_KEY: '',
}
_basic_options_extra_type = {
    LAUNCHER_PATH_KEY: {
        'type': 'file_selector',
        'selector_type': 'file',
        'dialog_title': '选择 NIKKE 启动器文件',
        'filter': '所有文件 (*)',
        'initial_directory': 'desktop',
    },
}
_basic_options_extra_description = {
    LAUNCHER_PATH_KEY: 'NIKKE 启动器文件路径 \n例如：D:/NIKKE/Launcher/nikke_launcher.exe',
    TRIGGER_INTERVAL_KEY: '后台触发任务每轮检测之间的额外延时(毫秒)。调大可降低系统资源占用，但会让后台响应变慢。',
}


def _launcher_path_first(conf_dict):
    # 让启动器路径选项排在基础设置最上面
    new = {}
    if LAUNCHER_PATH_KEY in conf_dict:
        new[LAUNCHER_PATH_KEY] = conf_dict[LAUNCHER_PATH_KEY]
    for key, value in conf_dict.items():
        if key != LAUNCHER_PATH_KEY:
            new[key] = value
    return new


def _get_desktop_path():
    # 获取当前用户的桌面目录(CSIDL_DESKTOPDIRECTORY = 0x10)
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
        if buf.value and os.path.isdir(buf.value):
            return buf.value
    except Exception as e:
        logger.error(f'get desktop path error', e)
    return None


def _patch_file_selector_initial_directory():
    # 让启动器路径选择框默认打开到桌面目录，方便直接看到桌面快捷方式
    from ok.ui.qt.tasks.LabelAndFileSelector import LabelAndFileSelector

    original = LabelAndFileSelector._initial_directory

    def _initial_directory(self, current_value):
        initial = self.config_type.get('initial_directory')
        if initial == 'desktop':
            desktop = _get_desktop_path()
            if desktop:
                return desktop
        return original(self, current_value)

    LabelAndFileSelector._initial_directory = _initial_directory


def _patch_create_basic_options():
    # 把启动器相关选项注入 create_basic_options 返回的默认配置中。
    # 这样 Config 从磁盘加载时会把这些键当作已知默认项，已保存的启动器路径
    # 才不会被 Config.verify_config 当作未知键丢弃。
    original = _global_config_module.create_basic_options

    def _create_basic_options(enable_blur=False):
        options = original(enable_blur=enable_blur)
        # 调高后台触发任务轮询间隔的默认值，避免过快地空转占用系统资源
        options.default_config[TRIGGER_INTERVAL_KEY] = TRIGGER_INTERVAL_MS
        # 移除与本项目无关的设置项
        for key in _BASIC_OPTIONS_REMOVE_KEYS:
            options.default_config.pop(key, None)
            options.config_description.pop(key, None)
            if options.config_type:
                options.config_type.pop(key, None)
        for key, value in _basic_options_extra_default.items():
            options.default_config.setdefault(key, value)
        options.config_description.update(_basic_options_extra_description)
        if options.config_type is None:
            options.config_type = {}
        options.config_type.update(_basic_options_extra_type)
        options.default_config = _launcher_path_first(options.default_config)
        return options

    _global_config_module.create_basic_options = _create_basic_options


def apply():
    # 通过包装 create_basic_options 注入自定义基础设置项（在 Config 加载磁盘配置之前生效）
    _patch_create_basic_options()
    # 启动器路径选择框默认打开桌面目录
    _patch_file_selector_initial_directory()