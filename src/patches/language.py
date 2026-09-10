from ok import Logger

logger = Logger.get_logger(__name__)

# 语言补丁：裁剪设置页语言下拉 + 解析「实际生效语言」+ 限制词条生成语言。
#
# 背景：框架 SettingTab 的下拉写死了 7 项语言，但本项目只提供 zh_CN/zh_TW/en_US/
# ja_JP 四套 gettext 词条（i18n/），任务字符串本身是简体中文（基准语种）。用户选
# 西语/韩语时会出现「框架外壳西/韩语 + 项目内容中文」的割裂界面；更隐蔽的是语言
# 默认值 AUTO 跟随系统，系统语言为西/韩的用户不选也会命中。故暂时隐藏这两项。
#
# 三处补丁互相配合：
# 1. SettingTab 构造后把隐藏语言从下拉里删掉。框架的 texts 与 Language 枚举是
#    按位置对齐的，不能直接改 texts，否则剩余项的语言映射会串位。
# 2. init_app_config 里把配置语言解析成实际生效语言：显式选中被隐藏语言、或
#    AUTO 命中不了保留语言时统一按英语兜底。
# 3. debug 模式「生成翻译文件」只给支持的语言写 ok.po，避免 i18n/ 里多出空目录。


def _kept_languages():
    """下拉里保留的语言（含 AUTO）。"""
    from ok.ui.qt.common.config import Language
    return (
        Language.CHINESE_SIMPLIFIED,
        Language.CHINESE_TRADITIONAL,
        Language.ENGLISH,
        Language.JAPANESE,
        Language.AUTO,
    )


def _hidden_languages():
    """从下拉里隐藏的语言（西语/韩语）。"""
    from ok.ui.qt.common.config import Language
    kept = set(_kept_languages())
    return tuple(language for language in Language if language not in kept)


def supported_locales():
    """实际提供词条的语言目录名（i18n/<locale>/LC_MESSAGES/），AUTO 不算。"""
    from ok.ui.qt.common.config import Language
    return {language.value.name() for language in _kept_languages() if language is not Language.AUTO}


def _resolve_auto_language(system_locale):
    """AUTO：系统语言命中保留语言就跟随，否则兜底英语。"""
    from PySide6.QtCore import QLocale
    from ok.ui.qt.common.config import Language
    for language in _kept_languages():
        if language is Language.AUTO:
            continue
        target = language.value
        if target.language() != system_locale.language():
            continue
        # 中文需区分简/繁书写系统，否则繁体系统会被误判成简体
        if system_locale.language() == QLocale.Chinese and target.script() != system_locale.script():
            continue
        return language
    return Language.ENGLISH


def _effective_language():
    """把配置里的语言解析成实际生效语言。"""
    from PySide6.QtCore import QLocale
    from ok.ui.qt.common.config import cfg, Language
    configured = cfg.get(cfg.language)
    if configured == Language.AUTO:
        return _resolve_auto_language(QLocale())
    if configured in _hidden_languages():
        # 存量配置落在已隐藏语言：按英语兜底
        return Language.ENGLISH
    return configured


def _patch_init_app_config():
    # init_app_config 用 cfg.language 解出 locale 并加载 Qt/Fluent 翻译，返回的
    # locale 又被 OK 用作 gettext 的 locale。这里在它运行前临时把语言换成解析
    # 结果，让框架与项目两层都按「实际生效语言」走，随后还原用户的原始选择。
    # 直接给 ConfigItem.value 赋值不落盘、也不会触发「重启后生效」提示。
    from ok.ui.qt.util import app as app_util

    original = app_util.init_app_config

    def _init_app_config():
        from ok.ui.qt.common.config import cfg
        configured = cfg.language.value
        effective = _effective_language()
        if effective == configured:
            return original()
        cfg.language.value = effective
        try:
            return original()
        finally:
            cfg.language.value = configured

    app_util.init_app_config = _init_app_config
    logger.info('patched init_app_config to fall back unsupported/AUTO language to English')


def _patch_setting_tab_language_options():
    from ok.ui.qt.common.config import cfg
    from ok.ui.qt.settings.SettingTab import SettingTab

    original_init = SettingTab.__init__

    def _init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        card = self.languageCard
        combo = card.comboBox
        hidden = _hidden_languages()
        # 框架按完整语言列表构造下拉（texts 与 Language 枚举按位置对齐），
        # 构造后再删除待隐藏项，剩余项的 userData 映射才不会被破坏。
        combo.blockSignals(True)
        for index in reversed(range(combo.count())):
            if combo.itemData(index) in hidden:
                combo.removeItem(index)
        combo.blockSignals(False)
        for language in hidden:
            card.optionToText.pop(language, None)
        if cfg.language.value in hidden:
            # 存量配置命中已隐藏语言：内存中改回兜底语言并刷新下拉显示
            cfg.language.value = _effective_language()

    SettingTab.__init__ = _init
    logger.info('patched SettingTab to hide unsupported languages from dropdown')


def _patch_update_po_file():
    # debug 模式「开发工具 → 生成翻译文件」按框架 Language 枚举给全部 7 种语言各写一份
    # ok.po，未支持的语言只会留下空目录（还会被打进便携包）。这里只放行 supported_locales()，
    # 保证 i18n/ 下的目录与支持的语言始终一致；返回值仅用于打开目录，给回 i18n 根目录即可。
    from ok.core import translation as translation_module
    from ok.util.file import get_path_relative_to_exe

    original = translation_module.update_po_file
    supported = supported_locales()

    def _update_po_file(strings, language_code):
        if language_code not in supported:
            logger.debug(f'skip generating po file for unsupported language {language_code}')
            return get_path_relative_to_exe('i18n')
        return original(strings, language_code)

    translation_module.update_po_file = _update_po_file
    logger.info(f'patched update_po_file to only generate {sorted(supported)}')


def apply():
    # 语言解析兜底与下拉裁剪，都必须在 ok.OK(config) 构造前应用
    _patch_init_app_config()
    _patch_setting_tab_language_options()
    _patch_update_po_file()
