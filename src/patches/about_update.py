# -*- coding: utf-8 -*-
"""「关于/更新」页补丁：去掉框架基于 pyappify 启动器的更新 UI，换成 ok-nikke 自己的实现。

为什么必须补：
`AboutTab` 只判断 `pyappify.get_version_list` 是否可调用就创建框架 UpdateCard，而该函数
恒存在 → 卡片一定会建；`MainWindow` 首次显示后 30 秒必定调一次检查 → 无 launcher 时
`get_version_list()` 抛 `RuntimeError("...pyappify_version: None")`，用户每次启动都会在
卡片里看到一次红字报错（不崩，但体验很差）。

补法（都只换模块级名字，不改 ok 源码）：
1. `ok.ui.qt.about.AboutTab.UpdateCard` → `src.ui.UpdateCard.NikkeUpdateCard`。
   我们的卡片同名提供 `update_available_changed` / `check_started` / `check_for_updates()`，
   因此 MainWindow 的「30 秒自动检查 + 导航徽标」逻辑原样可用，无需再补 MainWindow。
2. `get_startup_version_change` → 基于 `version.txt` / `version.txt.prev` 的实现，
   让「已更新 vX → vY」提示在去掉 pyappify 环境变量后继续可用（首次调用即消费掉 prev 文件，
   避免每次启动都弹）。正文不显示更新内容，空正文由 `_patch_empty_changelog` 收起，避免留白。
"""

from __future__ import annotations

import os

from ok.util.logger import Logger

from src import update_config

logger = Logger.get_logger(__name__)

_PENDING_CHANGE = None
_PENDING_CONSUMED = False


def pending_version_change(root: str = None):
    """返回 {action, from_version, to_version} 或 None；只消费一次（删除 .prev 文件）。"""
    global _PENDING_CHANGE, _PENDING_CONSUMED
    if _PENDING_CONSUMED:
        return _PENDING_CHANGE
    _PENDING_CONSUMED = True
    current, previous = update_config.read_versions(root)
    if not current or not previous or current == previous:
        _PENDING_CHANGE = None
        return None
    action = 'update' if update_config.compare(current, previous) > 0 else 'downgrade'
    _PENDING_CHANGE = {'action': action, 'from_version': previous, 'to_version': current}
    # 消费掉：否则每次启动都会提示同一次更新
    try:
        os.remove(os.path.join(root or update_config.package_root(), 'version.txt.prev'))
    except OSError:
        pass
    logger.info(f'pending version change: {_PENDING_CHANGE}')
    return _PENDING_CHANGE


def _get_startup_version_change(pyappify_module=None):
    """替换 ok 的 pyappify 版本变更检测（读 version.txt 而不是环境变量）。"""
    from ok.ui.qt.util.pyappify_startup import StartupVersionChange

    change = pending_version_change()
    if not change:
        return None
    return StartupVersionChange(
        title=f'{change["action"].capitalize()} success '
              f'{change["from_version"]} -> {change["to_version"]}',
        content='',  # 不显示更新内容：卡片只留标题，空正文由 _patch_empty_changelog 收起
        action=change['action'],
        from_version=change['from_version'],
        to_version=change['to_version'],
    )


def _patch_update_card():
    import ok.ui.qt.about.AboutTab as about_tab_module
    from src.ui.UpdateCard import NikkeUpdateCard

    about_tab_module.UpdateCard = NikkeUpdateCard
    logger.info('patched AboutTab.UpdateCard with NikkeUpdateCard')


def _patch_startup_version_change():
    # MainWindow 与 AboutTab 都在导入时绑定了这个名字，两处都要换
    import ok.ui.qt.MainWindow as main_window_module
    import ok.ui.qt.about.AboutTab as about_tab_module

    main_window_module.get_startup_version_change = _get_startup_version_change
    about_tab_module.get_startup_version_change = _get_startup_version_change
    logger.info('patched get_startup_version_change to read version.txt')


def _patch_empty_changelog():
    """「更新成功 / 降级成功」卡片正文为空时，把整张卡片收掉。

    我们不显示更新内容（pyappify 时代由启动器的 update_note 提供），但**只隐藏正文 label
    是不够的**：AboutTab 用 add_card 把正文包进一张 Card，隐藏 label 后界面里仍会留一个空框
    （已实测）。所以这里两件事一起做：换掉 ChangeLogView（空文本时自身隐藏）+ 包装
    AboutTab.add_card（正文为空则把外层 Card 一并隐藏）。只影响「关于」页，不动 ok 源码。
    """
    import ok.ui.qt.about.AboutTab as about_tab_module

    original_changelog = about_tab_module.ChangeLogView

    class _CollapsedWhenEmpty(original_changelog):
        def __init__(self, text='', parent=None):
            super().__init__(text, parent)
            if not str(text or '').strip():
                self.setVisible(False)

    about_tab_module.ChangeLogView = _CollapsedWhenEmpty

    original_add_card = about_tab_module.AboutTab.add_card

    def add_card(self, title, widget, stretch=0, parent=None):
        container = original_add_card(self, title, widget, stretch=stretch, parent=parent)
        if isinstance(widget, _CollapsedWhenEmpty) and not str(widget.text() or '').strip():
            container.setVisible(False)  # 空正文：连外层卡片一起收掉，不留空框
        return container

    about_tab_module.AboutTab.add_card = add_card
    logger.info('patched AboutTab.add_card + ChangeLogView to collapse empty changelog cards')


STARTUP_UPDATE_CHECK_DELAY_MS = 3000  # 启动自检延迟（框架默认 30 秒，用户等得太久）


def _patch_update_check_delay():
    """把启动自检延迟从 30 秒缩短到 3 秒。

    MainWindow._schedule_update_check 在调用时按模块名查找 update_check_delay_ms，
    所以替换模块属性即可生效，不需要改 ok 源码（也不动 MainWindow）。
    """
    import ok.ui.qt.MainWindow as main_window_module

    def update_check_delay_ms():
        return STARTUP_UPDATE_CHECK_DELAY_MS

    main_window_module.update_check_delay_ms = update_check_delay_ms
    logger.info(f'patched update_check_delay_ms to {STARTUP_UPDATE_CHECK_DELAY_MS}ms')


def apply():
    # 先消费一次版本变更（apply_all 在 ok.OK(config) 构造前调用，早于任何 UI 构建）
    pending_version_change()
    _patch_update_card()
    _patch_startup_version_change()
    _patch_update_check_delay()
    _patch_empty_changelog()
