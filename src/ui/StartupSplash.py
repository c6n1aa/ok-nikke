# -*- coding: utf-8 -*-
"""启动画面：主窗口构建完成前给用户「正在启动」的反馈。

框架启动链路里，QApplication 建好之后要花约 4 秒构造 MainWindow 与各 tab（开发机实测
双击到出窗口约 5 秒），这段时间屏幕没有任何反馈。这里复用框架窗口基类 BaseWindow
（无边框 + 主题背景，与主窗口同一套配色），由 src/patches/startup_splash.py 在
App.do_show_main 前后显示/关闭，并按 tab 推进进度条。
"""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout
from qfluentwidgets import BodyLabel, ProgressBar, SubtitleLabel

from ok.ui.qt.common.design_system import DesignToken
from ok.ui.qt.widget.BaseWindow import BaseWindow
from ok.util.logger import Logger

logger = Logger.get_logger(__name__)

SPLASH_SIZE = (420, 150)
ICON_SIZE = 40


class StartupSplash(BaseWindow):
    """无标题栏、置顶、不可缩放的启动画面。"""

    def __init__(self, title, icon=None):
        super().__init__()
        self.titleBar.hide()  # 启动画面不需要标题栏与窗口按钮
        self.setResizeEnabled(False)
        # 置顶只能等基类构造之后再设（构造里已经建好原生句柄），而 setWindowFlags 会重建原生窗口：
        # DWM 的亚克力/失焦模糊、窗口动画、阴影都是按句柄挂的，重建后就留在旧句柄上了。
        # 所以改完 flags 必须再走一次框架的 updateFrameless()，把这些效果挂到当前句柄，
        # 并把 flags 归一成框架要的那一组（AcrylicWindow.updateFrameless 是整体赋值，不是按位或）。
        # 不用框架的 setStayOnTop(True)：它末尾会自己 show()，会在尺寸/位置还没定好时先冒一下窗口。
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.updateFrameless()
        self.setWindowTitle(str(title))
        self._apply_size()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DesignToken.CARD_PADDING, DesignToken.CARD_PADDING,
                                  DesignToken.CARD_PADDING, DesignToken.CARD_PADDING)
        layout.setSpacing(DesignToken.PAGE_SPACING)

        head = QHBoxLayout()
        head.setSpacing(DesignToken.PAGE_SPACING)
        icon_label = QLabel(self)
        icon_label.setFixedSize(ICON_SIZE, ICON_SIZE)
        if icon is not None:
            icon_label.setPixmap(icon.pixmap(ICON_SIZE, ICON_SIZE))
        head.addWidget(icon_label)
        head.addWidget(SubtitleLabel(str(title), self))
        head.addStretch(1)
        layout.addLayout(head)
        layout.addStretch(1)

        self.stage_label = BodyLabel('', self)
        layout.addWidget(self.stage_label)
        # useAni=False：进度条默认用 QPropertyAnimation 补间，启动期没有事件循环在跑，
        # 动画推不动，填充部分会一直停在 0。
        self.progress_bar = ProgressBar(self, useAni=False)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

    def show_centered(self):
        """居中显示并立刻画出一帧（启动期没有事件循环，不冲刷就只是一块空窗口）。"""
        self._apply_size()
        self._center_on_screen()
        self.show()
        self.raise_()
        self._flush()
        # 改过 window flags 的窗口在首次事件处理时会把几何恢复成改 flags 之前的值
        # （也就是基类构造里的 500x500，setFixedSize 拦不住），所以 show 之后再定一次尺寸
        # 并重新居中，否则文案与进度条会落在窗口外面。
        self._apply_size()
        self._center_on_screen()
        self._flush()

    def _apply_size(self):
        self.setFixedSize(*SPLASH_SIZE)
        self.resize(*SPLASH_SIZE)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())

    def set_stage(self, text, percent):
        self.stage_label.setText(text)
        self.progress_bar.setValue(int(percent))
        self._flush()

    def finish(self):
        self.close()
        self._flush()

    @staticmethod
    def _flush():
        # 启动期主线程被 MainWindow 构造占住，没有事件循环在跑，必须手动派发一次绘制事件。
        # 排除用户输入事件：启动途中点击/按键不派发到还没建完的界面上。
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
