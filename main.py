import sys
import os

if getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(sys.executable))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from storage import init_db, is_first_run, get_last_unfinished_fragment
from monitor import WindowMonitor
from tray import TrayApp, _create_tray_icon


def main():
    init_db()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(_create_tray_icon())

    # 首次运行引导
    if is_first_run():
        from dashboard import _FirstRunWizard
        wizard = _FirstRunWizard()
        wizard.exec()

    # 崩溃恢复：检测上一次异常退出
    last = get_last_unfinished_fragment()
    if last:
        # 监控启动后会自动从当前时间重新开始计时
        # 上一次未结束的片段已写入 end_time，无需额外处理
        pass

    monitor = WindowMonitor(poll_interval=1.0)
    monitor.start()

    tray = TrayApp(monitor)
    tray.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
