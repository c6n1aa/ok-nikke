import os

from ok import Logger
from ok.core.icons import Icon
from ok.util.config import Config, ConfigOption
import ok.util.GlobalConfig as _global_config_module

logger = Logger.get_logger(__name__)

# 启动器配置分区（独立配置，用框架官方扩展点注册）。
# UI 分区名与 global_config 键用中文「NIKKE 启动器」，磁盘文件名用英文 nikke_launcher.json 避免中文路径。
LAUNCHER_PATH_KEY = '启动器路径'
LAUNCHER_SECTION_NAME = 'NIKKE 启动器'   # 设置 UI 显示的分区名 + global_config 键
LAUNCHER_CONFIG_FILE = 'nikke_launcher'  # 磁盘文件名（对应 configs/nikke_launcher.json）

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

# 启动器配置分区：通过 ok.util.GlobalConfig.register_config 官方扩展点注册为独立分区，
# 取代对 create_basic_options 的猴子补丁注入。文件选择器默认打开桌面目录由
# _patch_file_selector_initial_directory 补丁支持 initial_directory='desktop'。
LAUNCHER_CONFIG_OPTION = ConfigOption(
    LAUNCHER_SECTION_NAME,
    default={LAUNCHER_PATH_KEY: ''},
    config_type={
        LAUNCHER_PATH_KEY: {
            'type': 'file_selector',
            'selector_type': 'file',
            'dialog_title': '选择 NIKKE 启动器文件',
            'filter': '所有文件 (*)',
            'initial_directory': 'desktop',
        },
    },
    config_description={
        LAUNCHER_PATH_KEY: 'NIKKE 启动器文件路径(nikke_launcher.exe)。选择桌面快捷方式(.lnk)时会自动解析其指向的执行文件。',
    },
    icon=Icon.APPLICATION,
)


# 在 apply()（ok.OK() 构造前）捕获的旧启动器路径。必须在框架加载 Basic Options 之前捕获，
# 否则框架 verify_config 会把未知键「启动器路径」剥离并落盘，旧值就丢了。
_LEGACY_LAUNCHER_PATH = None


def _capture_legacy_launcher_path():
    # 在 ok.OK() 构造前、框架加载 Basic Options 之前捕获旧「启动器路径」。
    global _LEGACY_LAUNCHER_PATH
    if _LEGACY_LAUNCHER_PATH is not None:
        return
    try:
        from ok.util.file import get_relative_path, read_json_file
        old = read_json_file(get_relative_path(Config.config_folder, 'Basic Options.json'))
    except Exception as e:
        logger.warning('capture legacy launcher path failed', e)
        return
    if isinstance(old, dict):
        value = str(old.get(LAUNCHER_PATH_KEY) or '').strip()
        if value:
            _LEGACY_LAUNCHER_PATH = value
            logger.info(f'captured legacy launcher path: {value}')


def _migrate_legacy_launcher_path(config):
    # 一次性无损迁移：把捕获到的旧「启动器路径」写入新分区 nikke_launcher.json。
    # 仅当旧值非空、且新分区仍为空时才写入；不修改旧 Basic Options.json
    #（其「启动器路径」键会被框架 verify_config 自动裁剪，无需我们处理）。
    legacy = _LEGACY_LAUNCHER_PATH
    if not legacy:
        return
    if str(config.get(LAUNCHER_PATH_KEY) or '').strip():
        return
    config[LAUNCHER_PATH_KEY] = legacy
    logger.info('migrated legacy launcher path into nikke_launcher config')


def register_launcher_config():
    # 用框架官方扩展点注册独立的「NIKKE 启动器」配置分区。
    # 文件名用 LAUNCHER_CONFIG_FILE（nikke_launcher.json），分区名/键仍用 LAUNCHER_SECTION_NAME。
    # 必须在 og.global_config 就绪、且设置 UI 枚举分区之前调用（src/globals.py Globals.__init__）。
    from ok import og
    if og.global_config is None:
        logger.warning('register_launcher_config skipped: global_config not ready')
        return
    if og.global_config.configs.get(LAUNCHER_SECTION_NAME) is not None:
        return
    # Config 第一个参数是文件名（磁盘文件名），与 UI 分区名（option.name）解耦
    config = Config(LAUNCHER_CONFIG_FILE, LAUNCHER_CONFIG_OPTION.default_config)
    _migrate_legacy_launcher_path(config)
    og.global_config.register_config(LAUNCHER_CONFIG_OPTION, config)
    logger.info('registered NIKKE launcher config section via official API')


def get_launcher_path():
    # 读取启动器路径；分区未注册时按官方 ConfigOption 自动注册并加载磁盘值。
    from ok import og
    if og.global_config is None:
        return ''
    cfg = og.global_config.get_config(LAUNCHER_CONFIG_OPTION)
    return str(cfg.get(LAUNCHER_PATH_KEY) or '').strip()


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
    # 仅保留对 Basic Options 的局部调整（无官方 API 的部分）：
    # 调高 Trigger Interval 默认值 + 移除与本项目无关的项。
    # 启动器选项已改为独立分区（见 register_launcher_config），不再注入此处。
    original = _global_config_module.create_basic_options

    def _create_basic_options(enable_blur=False):
        options = original(enable_blur=enable_blur)
        # 调高后台触发任务轮询间隔的默认值，避免过快地空转占用系统资源
        options.default_config[TRIGGER_INTERVAL_KEY] = TRIGGER_INTERVAL_MS
        # 移除与本项目无关的设置项（无官方 API，仍需此补丁）
        for key in _BASIC_OPTIONS_REMOVE_KEYS:
            options.default_config.pop(key, None)
            options.config_description.pop(key, None)
            if options.config_type:
                options.config_type.pop(key, None)
        return options

    _global_config_module.create_basic_options = _create_basic_options


def apply():
    # 在 ok.OK() 构造前捕获旧 Basic Options.json 里的「启动器路径」（框架随后会剥离该未知键）
    _capture_legacy_launcher_path()
    # 仅保留对 Basic Options 的局部调整（无官方 API 的部分）
    _patch_create_basic_options()
    # 启动器路径选择框默认打开桌面目录
    _patch_file_selector_initial_directory()