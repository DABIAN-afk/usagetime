import os

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt

from autostart import is_autostart_enabled, toggle_autostart


def _create_tray_icon():
    """加载自定义图标，裁剪为圆形，不存在则用默认绘制。"""
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "图标.png")
    if os.path.exists(icon_path):
        src = QPixmap(icon_path)
        if not src.isNull():
            size = 64
            px = QPixmap(size, size)
            px.fill(QColor(0, 0, 0, 0))
            p = QPainter(px)
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            # 圆形裁剪
            p.setBrush(QColor(255, 255, 255))
            p.setPen(Qt.NoPen)
            p.drawEllipse(0, 0, size, size)
            p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            scaled = src.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (scaled.width() - size) // 2
            y = (scaled.height() - size) // 2
            p.drawPixmap(0, 0, scaled, x, y, size, size)
            p.end()
            return QIcon(px)
    # fallback: 自绘
    px = QPixmap(64, 64)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(10, 132, 255))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 60, 60)
    p.setPen(QColor(255, 255, 255))
    p.drawLine(32, 16, 32, 32)
    p.drawLine(32, 32, 46, 38)
    p.setBrush(QColor(255, 255, 255))
    p.drawEllipse(29, 29, 6, 6)
    p.end()
    return QIcon(px)


class TrayApp(QSystemTrayIcon):
    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.dashboard = None

        self.setIcon(_create_tray_icon())
        self.setToolTip("屏幕时间统计")

        menu = QMenu()

        act_show = menu.addAction("查看统计")
        act_show.triggered.connect(self._show_dashboard)

        self.act_pause = menu.addAction("暂停统计")
        self.act_pause.triggered.connect(self._toggle_pause)

        self.act_autostart = menu.addAction("开机自启")
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(is_autostart_enabled())
        self.act_autostart.triggered.connect(self._toggle_autostart)

        menu.addSeparator()

        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self._quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _show_dashboard(self):
        if self.dashboard is None:
            from dashboard import Dashboard
            self.dashboard = Dashboard(self.monitor)
        self.dashboard._refresh()
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    def _toggle_pause(self):
        if self.monitor.is_paused:
            self.monitor.resume()
            self.act_pause.setText("暂停统计")
        else:
            self.monitor.pause()
            self.act_pause.setText("继续统计")

    def _toggle_autostart(self):
        enabled = toggle_autostart()
        self.act_autostart.setChecked(enabled)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._show_dashboard()

    def _quit(self):
        if self.dashboard:
            self.dashboard.close()
        self.monitor.stop()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
