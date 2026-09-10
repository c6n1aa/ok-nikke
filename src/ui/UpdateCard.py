# -*- coding: utf-8 -*-
"""ok-nikke 自己的「关于 → 应用更新」卡片。

替换框架基于 pyappify 启动器的 UpdateCard（无 launcher 时它只会报「不支持」）。
对外接口保持与框架卡片一致，这样 MainWindow 的「启动 30 秒自动检查 + 导航徽标」逻辑
无需改动即可复用：`update_available_changed` / `check_started` / `check_for_updates()`。

所有 git/pip 逻辑都在根目录 update.py 里（唯一实现），本文件只负责界面与线程调度。
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, FluentIcon, LineEdit, MessageBox, PrimaryPushButton, \
    PushButton

from ok.core.events import communicate
from ok.ui.qt.common.design_system import DesignToken, control_width
from ok.util.logger import Logger

from src import update_config

logger = Logger.get_logger(__name__)

# 更新期间留给应用优雅退出的时间；超时则硬退（update.py 会等本进程真正消失）
GRACEFUL_EXIT_MS = 3000

# 发现新版本时的通知范围：只弹窗口内 InfoBar（配「关于」页红点），不发系统托盘气泡。
# 框架的 MainWindow.show_notification 由这个 tray 参数决定是否调 notify_system()。
NOTIFY_TRAY_BALLOON = False


class NikkeUpdateCard(QWidget):
    """版本选择 + 更新源切换 + 执行更新。"""

    update_available_changed = Signal(bool)
    check_started = Signal()
    _tags_loaded = Signal(object)

    def __init__(self, current_version, pyappify_module=None, parent=None, exit_event=None,
                 download_url=None):
        super().__init__(parent)
        self.current_version = str(current_version or '')
        self.exit_event = exit_event
        self.download_url = download_url
        self.tags = []
        self._busy = False
        self._notified_version = None  # 已弹过通知的版本，避免自动检查与手动检查重复提示
        self.config = update_config.load()

        self.channel_combo = ComboBox(self)
        self.channel_combo.addItems([label for _, label in update_config.CHANNEL_OPTIONS])
        self.channel_combo.setFixedWidth(control_width())
        self.channel_combo.setCurrentIndex(update_config.CHANNEL_VALUES.index(self.config['channel']))
        self.channel_combo.currentIndexChanged.connect(self._channel_changed)

        self.custom_url_edit = LineEdit(self)
        self.custom_url_edit.setPlaceholderText('https://github.com/<owner>/<repo>.git')
        self.custom_url_edit.setText(self.config.get('custom_git_url') or '')
        self.custom_url_edit.setMinimumWidth(control_width(220))
        self.custom_url_edit.editingFinished.connect(self._custom_url_changed)
        self._sync_custom_url_visibility()

        self.version_combo = ComboBox(self)
        self.version_combo.setFixedWidth(control_width())
        self.version_combo.currentIndexChanged.connect(self._selection_changed)

        self.check_button = PushButton(FluentIcon.SYNC, '检查更新', self)
        self.check_button.clicked.connect(self.check_for_updates)
        self.update_button = PrimaryPushButton(FluentIcon.UPDATE, '更新', self)
        self.update_button.clicked.connect(self.update_to_selected_version)
        self.update_button.setEnabled(False)
        self.release_button = PushButton(FluentIcon.DOWNLOAD, '手动下载', self)
        self.release_button.clicked.connect(self._open_download_url)
        self.release_button.setVisible(bool(self.download_url))

        self.current_label = BodyLabel(f'当前版本 {self.current_version or "未知"}', self)
        self.status_label = BodyLabel('点击「检查更新」获取可用版本', self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.notes_label = BodyLabel('', self)
        self.notes_label.setWordWrap(True)
        self.notes_label.setTextFormat(Qt.TextFormat.PlainText)
        self.notes_label.setVisible(False)
        # 上次更新失败过（update.py 落盘的记录）：直接显示原因，别让用户「还是旧版本但不知道为什么」
        failure = update_config.read_update_failure()
        if failure:
            self.status_label.setText(
                f'上次更新到 {failure["target"] or "目标版本"} 失败：{failure["reason"]}'
                f'（详见 logs/update.log；可重新点「检查更新」再试）')

        source_row = QHBoxLayout()
        source_row.setSpacing(DesignToken.ROW_SPACING)
        source_row.addWidget(BodyLabel('更新源', self))
        source_row.addWidget(self.channel_combo)
        source_row.addWidget(self.custom_url_edit)
        source_row.addStretch(1)

        version_row = QHBoxLayout()
        version_row.setSpacing(DesignToken.ROW_SPACING)
        version_row.addWidget(BodyLabel('版本', self))
        version_row.addWidget(self.version_combo)
        version_row.addWidget(self.status_label, 1)
        version_row.addWidget(self.release_button)
        version_row.addWidget(self.check_button)
        version_row.addWidget(self.update_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(DesignToken.SECTION_SPACING)
        layout.addWidget(self.current_label)
        layout.addLayout(source_row)
        layout.addLayout(version_row)
        layout.addWidget(self.notes_label)

        self._tags_loaded.connect(self._apply_tags)
        self._set_version_controls_visible(False)
        logger.info(f'nikke update card ready, current_version={self.current_version!r}, '
                    f'channel={self.config["channel"]!r}')

    # ------------------------------------------------------------ 对外接口（框架依赖）

    def check_for_updates(self):
        if self._busy:
            return
        self.check_started.emit()
        self._set_busy(True)
        self._set_status('正在检查更新…')
        url = update_config.resolve_git_url(self.config)
        logger.info(f'check updates from {url or "未配置"}')

        def run():
            tags, error = update_config.list_remote_tags()
            self._tags_loaded.emit((tags, error))

        threading.Thread(target=run, daemon=True, name='ok-nikke-update-check').start()

    def update_to_selected_version(self):
        if self._busy or self.version_combo.currentIndex() < 0:
            return
        target = self.version_combo.currentText()
        if not target:
            return
        direction = update_config.compare(target, self.current_version)
        action = '更新' if direction > 0 else '降级'
        confirm = MessageBox('确认' + action,
                             f'将把 ok-nikke 从 {self.current_version or "未知"} 切换到 {target}。\n\n'
                             f'{action}过程会联网拉取代码，必要时重装依赖；完成后应用会自动重启。'
                             f'\n期间请不要关闭电源或手动结束进程。',
                             self.window())
        if not confirm.exec():
            return
        try:
            update_config.start_update(target, wait_pid=os.getpid())
        except Exception as error:
            logger.error(f'start update failed: {error}')
            self._set_status(f'启动更新失败：{error}')
            return
        logger.info(f'update to {target} started, quitting app')
        self._set_status(f'正在{action}到 {target}，应用即将自动重启…')
        # 先请求优雅退出（保存配置/收尾线程），超时再硬退；update.py 会等本进程真正退出
        communicate.quit.emit()
        QTimer.singleShot(GRACEFUL_EXIT_MS, lambda: os._exit(0))

    # ------------------------------------------------------------ 内部

    def _apply_tags(self, result):
        tags, error = result
        self._set_busy(False)
        if error:
            self.tags = []
            self.version_combo.clear()
            self._set_version_controls_visible(False)
            self.update_available_changed.emit(False)
            self._set_status(f'检查更新失败：{error}')
            return
        # 只把正式版纳入可更新列表：预发布（v0.2.0-beta.1）不亮徽标、不进版本下拉，
        # 需要试的用户到 Release 页手动下载；这样「发布语义」与「更新语义」才对得上。
        stable = update_config.stable_tags(tags)
        self.tags = [tag for tag in stable if tag != self.current_version] or list(stable)
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.addItems(self.tags)
        self.version_combo.blockSignals(False)
        newest_newer = update_config.newest_stable_update(tags, self.current_version)
        self.update_available_changed.emit(newest_newer is not None)
        # 发现新版本时主动通知（框架的 communicate.notification → 窗口内 InfoBar），只提示一次；
        # 「关于」页的红点徽标是常驻提示，托盘气泡按 NOTIFY_TRAY_BALLOON 关闭。
        if newest_newer is not None and newest_newer != self._notified_version:
            self._notified_version = newest_newer
            communicate.notification.emit(
                f'发现新版本 {newest_newer}，可在「关于 → 应用更新」一键升级。',
                'ok-nikke 更新', False, NOTIFY_TRAY_BALLOON, None, None, None)
        if not self.tags:
            self._set_version_controls_visible(False)
            self._set_status('未获取到任何正式版本')
            return
        self._set_version_controls_visible(True)
        if newest_newer is not None:
            index = self.tags.index(newest_newer) if newest_newer in self.tags else 0
            self.version_combo.setCurrentIndex(index)
            self._set_status(f'发现新版本 {newest_newer}')
        else:
            self.version_combo.setCurrentIndex(0)
            prerelease_newer = update_config.newest_prerelease_update(tags, self.current_version)
            if prerelease_newer:
                self._set_status(f'已是最新正式版；预发布 {prerelease_newer} 不参与提示，'
                                 f'需要请到 Release 页手动下载')
            else:
                self._set_status('已是最新版本')
        self._selection_changed()

    def _selection_changed(self, _index=None):
        target = self.version_combo.currentText()
        if not target:
            self.update_button.setEnabled(False)
            self._set_notes('')
            return
        direction = update_config.compare(target, self.current_version)
        self.update_button.setText({1: '更新', -1: '降级'}.get(direction, '当前版本'))
        self.update_button.setEnabled(direction != 0 and not self._busy)
        if direction == 0:
            self._set_notes(f'当前已是 {target}。')
        else:
            action = '更新' if direction > 0 else '降级'
            self._set_notes(f'{action}后：{self.current_version or "未知"} → {target}'
                            f'（会重启应用；更新日志见 Release 页面）')

    def _channel_changed(self, index):
        if index < 0 or index >= len(update_config.CHANNEL_OPTIONS):
            return
        self.config['channel'] = update_config.CHANNEL_OPTIONS[index][0]
        self._sync_custom_url_visibility()
        self._save_config(f'更新源已切换为「{update_config.channel_label(self.config["channel"])}」，'
                          f'请重新检查更新')

    def _custom_url_changed(self):
        self.config['custom_git_url'] = self.custom_url_edit.text().strip()
        self._save_config('自定义更新源已保存，请重新检查更新')

    def _save_config(self, status: str):
        if update_config.save(self.config):
            self._set_status(status)
        else:
            self._set_status('更新源配置写入失败（configs/update.json）')

    def _sync_custom_url_visibility(self):
        self.custom_url_edit.setVisible(self.config.get('channel') == 'custom')

    def _open_download_url(self):
        if self.download_url:
            QDesktopServices.openUrl(QUrl(self.download_url))

    def _set_version_controls_visible(self, visible):
        self.version_combo.setVisible(visible)

    def _set_busy(self, busy):
        self._busy = busy
        self.check_button.setEnabled(not busy)
        self.channel_combo.setEnabled(not busy)
        self.custom_url_edit.setEnabled(not busy)
        self.version_combo.setEnabled(not busy)
        if busy:
            self.update_button.setEnabled(False)

    def _set_status(self, message: str):
        self.status_label.setText(message)

    def _set_notes(self, text: str):
        self.notes_label.setText(text)
        self.notes_label.setVisible(bool(text))
