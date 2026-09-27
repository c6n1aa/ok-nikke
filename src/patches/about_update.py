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
   避免每次启动都弹）。卡片正文是本次更新的**更新说明**：读包内 `changelog/<tag>.md`
   （随 tag 提交，CNB 镜像由 CI 补写，纯本地读取、不联网）；没有该文件时正文留空，
   由 `_patch_empty_changelog` 把整张卡片收起，避免留白。
3. `AboutTab.__init__` → 构建完成后把「其他项目」卡片裁剪到只剩 `KEEP_PROJECT_URLS`
   里的两项（ok-script 与 ok-script 模板项目），其余 ok-script 系列应用不再展示。
"""

from __future__ import annotations

import os

from ok.util.logger import Logger

from src import update_config

logger = Logger.get_logger(__name__)

_PENDING_CHANGE = None
_PENDING_CONSUMED = False


def pending_version_change(root: str | None = None):
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
    notes = update_config.read_release_notes(change['to_version'])
    if not notes:
        logger.info(f'no local release notes for {change["to_version"]} (changelog/<tag>.md)')
    return StartupVersionChange(
        title=f'{change["action"].capitalize()} success '
              f'{change["from_version"]} -> {change["to_version"]}',
        content=notes,  # 空正文由 _patch_empty_changelog 把整张卡片收起
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
    import ok.ui.qt.about.AboutTab as about_tab_module
    import ok.ui.qt.MainWindow as main_window_module

    main_window_module.get_startup_version_change = _get_startup_version_change
    about_tab_module.get_startup_version_change = _get_startup_version_change
    logger.info('patched get_startup_version_change to read version.txt')


def _patch_empty_changelog():
    """「更新成功 / 降级成功」卡片正文为空时，把整张卡片收掉。

    正文是本次更新的更新说明（本地 `changelog/<tag>.md`），没有该文件时为空；**只隐藏正文
    label 是不够的**：AboutTab 用 add_card 把正文包进一张 Card，隐藏 label 后界面里仍会留一个
    空框（已实测），所以外层 Card 要一起隐藏。只影响「关于」页，不动 ok 源码。
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


# 「关于」页「其他项目」卡片只留这两项：ok-script 本体与 ok-script 模板项目。
KEEP_PROJECT_URLS = (
    'https://github.com/ok-oldking/ok-script',
    'https://github.com/ok-oldking/ok-script-app',
)


def _normalize_project_url(url):
    return str(url or '').strip().rstrip('/').lower()


def _keep_project(url):
    return _normalize_project_url(url) in KEEP_PROJECT_URLS


def _prune_project_cards(tab):
    """把「其他项目」卡片裁剪到只剩 KEEP_PROJECT_URLS 里的两项。

    框架把项目清单硬编码在 `AboutTab.__init__` 里，这里在构建完成后摘掉其余卡片：
    只 `setVisible(False)` 仍会占着网格单元格（留出空行空列），所以要从布局里
    `removeWidget` 再 `deleteLater`，最后把保留的卡片按两列重新排布——框架会过滤掉与
    当前应用 GitHub 链接相同的项目，重排能补上空出来的位置。只影响「关于」页，不动 ok 源码。
    """
    group = getattr(tab, 'group', None)
    if group is None:  # 框架没建这张卡片（项目清单为空）时无事可做。
        return
    from ok.ui.qt.about.ProjectCard import ProjectCard
    from PySide6.QtWidgets import QGridLayout

    grid = group.findChild(QGridLayout)
    if grid is None:  # 框架换了卡片结构：不猜布局，直接跳过。
        return
    kept = []
    for card in group.findChildren(ProjectCard):
        grid.removeWidget(card)
        if _keep_project(card.url):
            kept.append(card)
        else:
            card.setParent(None)
            card.deleteLater()
    for index, card in enumerate(kept):
        grid.addWidget(card, index // 2, index % 2)


def _patch_about_projects():
    import ok.ui.qt.about.AboutTab as about_tab_module

    original_init = about_tab_module.AboutTab.__init__

    def __init__(self, config, pyappify_module=None, exit_event=None):
        original_init(self, config, pyappify_module, exit_event)
        _prune_project_cards(self)

    about_tab_module.AboutTab.__init__ = __init__
    logger.info('patched AboutTab.__init__ to keep only the ok-script projects')


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
    _patch_about_projects()
