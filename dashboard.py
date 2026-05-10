from datetime import date, timedelta, datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QFrame, QMessageBox, QDialog, QCheckBox,
    QComboBox, QLineEdit, QStackedWidget, QSlider, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QPixmap, QImage, QFontDatabase

from PIL import Image

from storage import (
    get_stats, get_daily_total, get_available_dates,
    get_week_stats, get_week_app_stats,
    get_hourly_stats,
    format_duration_short, format_time_short,
    clear_all_data, get_ignored_apps,
    add_ignored_app, remove_ignored_app,
    get_setting, set_setting, get_display_name,
)
from icons import get_icon

# ── Font ──────────────────────────────────────────────────────
def _detect_font():
    available = set(QFontDatabase.families())
    candidates = [
        "PingFang SC", "PingFang HK", "PingFang TC",
        "Microsoft YaHei", "微软雅黑",
        "Noto Sans SC", "Noto Sans CJK SC",
        "Source Han Sans SC", "思源黑体",
        "SimHei", "黑体",
        "WenQuanYi Micro Hei",
        "Hiragino Sans GB",
    ]
    for name in candidates:
        if name in available:
            return name
    return ""


_FONT_FAMILY = _detect_font()


def _font(size, bold=False):
    if _FONT_FAMILY:
        f = QFont(_FONT_FAMILY, size)
    else:
        f = QFont()
        f.setPixelSize(int(size * 1.2))
    f.setBold(bold)
    return f


# ── Theme (White) ─────────────────────────────────────────────
BG       = "#FFFFFF"
CARD     = "#F2F2F7"
HOVER    = "#E5E5EA"
BORDER   = "#E5E5EA"
ACCENT   = "#007AFF"
BLUE_LT  = "#409CFF"
TEXT     = "#1C1C1E"
GRAY     = "#8E8E93"
MUTED    = "#AEAEB2"
CHART_BG = "#E5E5EA"
GREEN    = "#34C759"
RED      = "#FF3B30"

APP_COLORS = [
    "#007AFF", "#34C759", "#FF9500", "#FF3B30", "#AF52DE",
    "#FF2D55", "#5AC8FA", "#FF6723", "#30B0C7", "#5856D6",
    "#A2845E", "#FF6482", "#0A84FF", "#BF5AF2", "#64D2FF",
]

DAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_CN_DAY = {0: "周一", 1: "周二", 2: "周三", 3: "周四",
           4: "周五", 5: "周六", 6: "周日"}

APP_TITLE = "屏幕时间统计"


def _pil_to_pixmap(pil_img, size=24):
    pil_img = pil_img.resize((size, size), Image.LANCZOS)
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, size, size, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


class _Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{CARD};border:none;border-radius:12px;}}"
        )


class _BarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__()
        self.setMinimumHeight(130)
        self._data = []
        self._hovered = -1
        self._bar_rects = []  # [(x, y_top, bar_w, bar_h, val), ...]
        self.setMouseTracking(True)

    def set_data(self, week_stats, today_str):
        self._data = week_stats
        self._today = today_str
        self._hovered = -1
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        found = -1
        for i, (rx, ry, rw, rh, _) in enumerate(self._bar_rects):
            if rx <= pos.x() <= rx + rw and ry <= pos.y() <= ry + rh:
                found = i
                break
        if found != self._hovered:
            self._hovered = found
            self.update()

    def leaveEvent(self, event):
        if self._hovered != -1:
            self._hovered = -1
            self.update()

    def paintEvent(self, event):
        if not self._data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        max_val = max((d["total_seconds"] for d in self._data), default=1) or 1

        # 左侧留 55px 给时间刻度
        margin_left = 55
        n = len(self._data)
        gap = 20
        avail = w - margin_left - 20
        bar_w = max(14, (avail - gap * (n - 1)) // n)
        total_w = bar_w * n + gap * (n - 1)
        sx = margin_left + (avail - total_w) // 2

        chart_b = h - 20
        chart_t = 8
        chart_h = chart_b - chart_t

        self._bar_rects = []

        # 左侧时间刻度（按 1 小时分档）
        p.setFont(_font(9))
        p.setPen(QColor(GRAY))
        max_hours = max(1, int((max_val + 3599) // 3600))  # 向上取整到小时
        for h in range(0, max_hours + 1):
            t = h * 3600
            ty = chart_b - int(t / max_val * chart_h) if max_val > 0 else chart_b
            label = f"{h}h"
            p.drawText(0, ty - 7, margin_left - 6, 14,
                       Qt.AlignRight | Qt.AlignVCenter, label)
            # 刻度线
            p.setPen(QColor(BORDER))
            p.drawLine(margin_left - 2, ty, margin_left, ty)
            p.setPen(QColor(GRAY))

        for i, day in enumerate(self._data):
            x = sx + i * (bar_w + gap)
            val = day["total_seconds"]
            d = date.fromisoformat(day["date"])
            day_name = DAY_LABELS[d.weekday()]
            is_today = day["date"] == self._today

            if val > 0:
                bar_h = max(4, int(val / max_val * chart_h))
            else:
                bar_h = 0
            y_top = chart_b - bar_h if bar_h > 0 else chart_b

            self._bar_rects.append((x, y_top, bar_w, bar_h, val))

            # 柱子
            color = QColor(ACCENT if is_today else CHART_BG)
            if val > 0:
                p.setBrush(color)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(x, y_top, bar_w, bar_h, 4, 4)

            # 悬停高亮
            if i == self._hovered and val > 0:
                hl = QColor(ACCENT)
                hl.setAlpha(40)
                p.setBrush(hl)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(x - 2, y_top - 2, bar_w + 4, bar_h + 4, 6, 6)
                p.setBrush(color)
                p.drawRoundedRect(x, y_top, bar_w, bar_h, 4, 4)

            # 日名
            p.setFont(_font(9, is_today))
            p.setPen(QColor(ACCENT if is_today else GRAY))
            p.drawText(x, chart_b + 2, bar_w, 16,
                       Qt.AlignCenter, day_name)

        # 悬停时显示时间（柱子居中位置）
        if 0 <= self._hovered < len(self._data):
            day = self._data[self._hovered]
            val = day["total_seconds"]
            if val > 0:
                rx, ry, rw, rh, _ = self._bar_rects[self._hovered]
                label = format_duration_short(val)

                p.setFont(_font(9, True))
                fm = p.fontMetrics()
                tw = fm.horizontalAdvance(label) + 14
                th = 22
                lx = rx + (rw - tw) // 2
                ly = ry + (rh - th) // 2

                p.setBrush(QColor(0, 0, 0, 180))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(lx, ly, tw, th, 4, 4)

                p.setPen(QColor("white"))
                p.drawText(lx, ly, tw, th, Qt.AlignCenter, label)

        p.end()


class _HourlyChart(QWidget):
    """24 小时柱状图，每根柱子代表 1 小时。"""

    def __init__(self, fixed_labels=False, parent=None):
        super().__init__()
        self.setMinimumHeight(120)
        self._hourly = [0.0] * 24
        self._hovered = -1
        self._bar_rects = []
        self._fixed_labels = fixed_labels
        self.setMouseTracking(True)

    def set_data(self, hourly):
        self._hourly = hourly
        self._hovered = -1
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        found = -1
        for i, (rx, ry, rw, rh) in enumerate(self._bar_rects):
            if rx <= pos.x() <= rx + rw and ry <= pos.y() <= ry + rh:
                found = i
                break
        if found != self._hovered:
            self._hovered = found
            self.update()

    def leaveEvent(self, event):
        if self._hovered != -1:
            self._hovered = -1
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        max_val = max(self._hourly) if max(self._hourly) > 0 else 3600

        margin_left = 40
        margin_bottom = 20
        margin_top = 6
        gap = 2
        avail = w - margin_left - 10
        n = 24
        bar_w = max(4, (avail - gap * (n - 1)) // n)
        total_w = bar_w * n + gap * (n - 1)
        sx = margin_left + (avail - total_w) // 2

        chart_b = h - margin_bottom
        chart_h = chart_b - margin_top

        self._bar_rects = []

        # 左侧刻度
        p.setFont(_font(8))
        p.setPen(QColor(GRAY))
        if self._fixed_labels:
            ticks = [(0, "0"), (0.5, "30m"), (1, "60m")]
        else:
            ticks = [(0, "0"), (0.25, format_duration_short(max_val * 0.25)),
                     (0.5, format_duration_short(max_val * 0.5)),
                     (0.75, format_duration_short(max_val * 0.75)),
                     (1, format_duration_short(max_val))]
        for frac, label in ticks:
            ty = chart_b - int(frac * chart_h)
            p.drawText(0, ty - 6, margin_left - 4, 12,
                       Qt.AlignRight | Qt.AlignVCenter, label)

        for i in range(24):
            x = sx + i * (bar_w + gap)
            val = self._hourly[i]
            pct = val / max_val if max_val > 0 else 0
            bar_h = max(0, int(pct * chart_h))
            y_top = chart_b - bar_h

            self._bar_rects.append((x, y_top, bar_w, bar_h))

            # 柱子
            is_now = i == datetime.now().hour
            if val > 0:
                color = QColor(ACCENT if is_now else CHART_BG)
                p.setBrush(color)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(x, y_top, bar_w, bar_h, 2, 2)

            # 悬停高亮
            if i == self._hovered and val > 0:
                hl = QColor(ACCENT)
                hl.setAlpha(40)
                p.setBrush(hl)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(x - 1, y_top - 1, bar_w + 2, bar_h + 2, 3, 3)
                color = QColor(ACCENT if is_now else CHART_BG)
                p.setBrush(color)
                p.drawRoundedRect(x, y_top, bar_w, bar_h, 2, 2)

            # 整点标签
            if i % 3 == 0:
                p.setFont(_font(7))
                p.setPen(QColor(GRAY if not is_now else ACCENT))
                p.drawText(x, chart_b + 2, bar_w, 14,
                           Qt.AlignCenter, f"{i}")

        # 悬停提示
        if 0 <= self._hovered < 24:
            val = self._hourly[self._hovered]
            if val > 0:
                rx, ry, rw, rh = self._bar_rects[self._hovered]
                label = format_duration_short(val)
                hour_label = f"{self._hovered}:00-{self._hovered + 1}:00 {label}"

                p.setFont(_font(9, True))
                fm = p.fontMetrics()
                tw = fm.horizontalAdvance(hour_label) + 14
                th = 22
                lx = rx + (rw - tw) // 2
                ly = ry - th - 4
                if ly < 0:
                    ly = ry + rh + 4

                p.setBrush(QColor(0, 0, 0, 180))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(lx, ly, tw, th, 4, 4)

                p.setPen(QColor("white"))
                p.drawText(lx, ly, tw, th, Qt.AlignCenter, hour_label)

        p.end()


class _TimelineView(QWidget):
    """时间线视图：显示一天中应用切换的时间线。"""

    def __init__(self, parent=None):
        super().__init__()
        self._fragments = []

    def set_data(self, fragments):
        self._fragments = fragments
        self.update()

    def paintEvent(self, event):
        if not self._fragments:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QColor(MUTED))
            p.setFont(_font(12))
            p.drawText(self.rect(), Qt.AlignCenter, "暂无时间线数据")
            p.end()
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 55
        margin_right = 12
        row_h = 28
        bar_h = 18
        label_w = w - margin_left - margin_right

        try:
            first = datetime.fromisoformat(self._fragments[0]["start_time"])
            last = datetime.fromisoformat(self._fragments[-1]["end_time"])
        except Exception:
            p.end()
            return

        total_secs = (last - first).total_seconds()
        if total_secs <= 0:
            total_secs = 1

        segments = []
        for f in self._fragments:
            if segments and segments[-1]["app_name"] == f["app_name"]:
                segments[-1]["end_time"] = f["end_time"]
                segments[-1]["duration"] += f["duration_seconds"]
            else:
                segments.append({
                    "app_name": f["app_name"],
                    "display_name": get_display_name(f["app_name"]),
                    "start_time": f["start_time"],
                    "end_time": f["end_time"],
                    "duration": f["duration_seconds"],
                })

        y = 8
        for i, seg in enumerate(segments):
            if y + row_h > h:
                break
            try:
                s_dt = datetime.fromisoformat(seg["start_time"])
                e_dt = datetime.fromisoformat(seg["end_time"])
            except Exception:
                continue

            s_offset = (s_dt - first).total_seconds() / total_secs
            e_offset = (e_dt - first).total_seconds() / total_secs
            seg_w = max(4, int((e_offset - s_offset) * label_w))
            x = margin_left + int(s_offset * label_w)

            color = QColor(APP_COLORS[i % len(APP_COLORS)])
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(x, y, seg_w, bar_h, 4, 4)

            p.setPen(QColor(GRAY))
            p.setFont(_font(8))
            p.drawText(2, y, margin_left - 6, bar_h,
                       Qt.AlignRight | Qt.AlignVCenter,
                       format_time_short(seg["start_time"]))

            if seg_w > 40:
                p.setPen(QColor(255, 255, 255))
                p.setFont(_font(8))
                display = seg["display_name"]
                if len(display) > seg_w // 6:
                    display = display[:seg_w // 6] + "…"
                p.drawText(x + 4, y, seg_w - 8, bar_h,
                           Qt.AlignLeft | Qt.AlignVCenter, display)

            y += row_h

        if segments and y <= h:
            p.setPen(QColor(GRAY))
            p.setFont(_font(8))
            last_seg = segments[-1]
            p.drawText(2, y - row_h + bar_h, margin_left - 6, bar_h,
                       Qt.AlignRight | Qt.AlignVCenter,
                       format_time_short(last_seg["end_time"]))

        p.end()


class _FirstRunWizard(QDialog):
    """首次运行引导。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_TITLE)
        self.setMinimumWidth(420)
        self.setStyleSheet(
            f"QDialog{{background:{BG};}}"
            f"QLabel{{color:{TEXT};font-size:13px;}}"
            f"QComboBox{{background:white;color:{TEXT};border:1px solid {BORDER};"
            f"border-radius:8px;padding:6px 10px;font-size:13px;}}"
            f"QSlider::handle:horizontal{{background:{ACCENT};width:16px;height:16px;"
            f"border-radius:8px;margin:-5px 0;}}"
            f"QSlider::groove:horizontal{{background:{BORDER};height:4px;border-radius:2px;}}"
        )
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(16)
        lay.setContentsMargins(28, 24, 28, 24)

        title = QLabel(APP_TITLE)
        title.setFont(_font(22, True))
        title.setStyleSheet(f"color:{TEXT};")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            "只在本地统计应用使用时间\n"
            "不会记录键盘输入 | 不会截图 | 不会上传数据"
        )
        desc.setFont(_font(12))
        desc.setStyleSheet(f"color:{GRAY};")
        desc.setAlignment(Qt.AlignCenter)
        lay.addWidget(desc)

        lay.addSpacing(8)

        idle_lbl = QLabel("无操作判定时间：")
        idle_lbl.setFont(_font(13))
        lay.addWidget(idle_lbl)

        self.idle_combo = QComboBox()
        self.idle_combo.addItems(["3 分钟", "5 分钟", "10 分钟"])
        self.idle_combo.setCurrentIndex(1)
        lay.addWidget(self.idle_combo)

        self.chk_autostart = QCheckBox("开机自动启动")
        self.chk_autostart.setStyleSheet(f"color:{TEXT};font-size:13px;spacing:8px;")
        lay.addWidget(self.chk_autostart)

        self.chk_save_title = QCheckBox("保存窗口标题（更详细的使用记录）")
        self.chk_save_title.setStyleSheet(f"color:{TEXT};font-size:13px;spacing:8px;")
        lay.addWidget(self.chk_save_title)

        lay.addSpacing(8)

        btn = QPushButton("开始使用")
        btn.setFixedHeight(40)
        btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:white;border:none;"
            f"border-radius:10px;font-size:15px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{BLUE_LT};}}"
        )
        btn.clicked.connect(self._on_start)
        lay.addWidget(btn)

    def _on_start(self):
        idle_map = {0: 180, 1: 300, 2: 600}
        idle_val = idle_map.get(self.idle_combo.currentIndex(), 300)
        set_setting("idle_threshold", str(idle_val))
        set_setting("autostart", "1" if self.chk_autostart.isChecked() else "0")
        set_setting("save_window_title", "1" if self.chk_save_title.isChecked() else "0")
        set_setting("first_run_done", "1")

        if self.chk_autostart.isChecked():
            try:
                from autostart import enable_autostart
                enable_autostart()
            except Exception:
                pass

        self.accept()


class Dashboard(QWidget):
    def __init__(self, monitor=None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.monitor = monitor
        self._current_tab = "daily"
        self._icon_cache = {}
        self._view_date = date.today()
        self._drag_pos = None
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(520, 600)
        self.resize(600, 750)

        # 外层容器（圆角 + 阴影效果通过样式实现）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        # 内容容器
        content = QFrame()
        content.setStyleSheet(
            f"QFrame{{background:{BG};border-radius:16px;}}"
        )
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(20, 0, 20, 16)
        content_lay.setSpacing(10)

        # ── 自定义标题栏 ──
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(0, 8, 0, 4)
        title_bar.setSpacing(8)

        lbl_title = QLabel(APP_TITLE)
        lbl_title.setFont(_font(13, True))
        lbl_title.setStyleSheet(f"color:{TEXT};")
        title_bar.addWidget(lbl_title)

        self.lbl_clock = QLabel()
        self.lbl_clock.setFont(_font(11))
        self.lbl_clock.setStyleSheet(f"color:{GRAY};")
        self.lbl_clock.setAlignment(Qt.AlignCenter)
        title_bar.addWidget(self.lbl_clock)
        self._update_clock()
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)

        title_bar.addStretch()

        self.btn_min = QPushButton("─")
        self.btn_min.setFixedSize(28, 28)
        self.btn_min.setStyleSheet(
            f"QPushButton{{background:transparent;color:{GRAY};border:none;"
            f"border-radius:14px;font-size:14px;}}"
            f"QPushButton:hover{{background:{HOVER};color:{TEXT};}}"
        )
        self.btn_min.clicked.connect(self.showMinimized)

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setStyleSheet(
            f"QPushButton{{background:transparent;color:{GRAY};border:none;"
            f"border-radius:14px;font-size:13px;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
        )
        self.btn_close.clicked.connect(self.hide)

        title_bar.addWidget(self.btn_min)
        title_bar.addWidget(self.btn_close)
        content_lay.addLayout(title_bar)

        # ── Tab toggle ──
        toggle_bar = QHBoxLayout()
        toggle_bar.setAlignment(Qt.AlignCenter)
        toggle_bar.setSpacing(4)
        self.btn_daily = QPushButton("今日")
        self.btn_weekly = QPushButton("本周")
        self.btn_settings = QPushButton("设置")
        for btn in (self.btn_daily, self.btn_weekly, self.btn_settings):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(32)
            btn.setMinimumWidth(64)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{GRAY};border:none;"
                f"border-radius:8px;padding:0 16px;font-size:13px;}}"
                f"QPushButton:hover{{background:{HOVER};}}"
            )
        self.btn_daily.clicked.connect(lambda: self._switch_tab("daily"))
        self.btn_weekly.clicked.connect(lambda: self._switch_tab("weekly"))
        self.btn_settings.clicked.connect(lambda: self._switch_tab("settings"))
        toggle_bar.addWidget(self.btn_daily)
        toggle_bar.addWidget(self.btn_weekly)
        toggle_bar.addWidget(self.btn_settings)
        content_lay.addLayout(toggle_bar)

        # ── Stats container (hero + actions + charts + list) ──
        self.stats_container = QWidget()
        stats_lay = QVBoxLayout(self.stats_container)
        stats_lay.setContentsMargins(0, 0, 0, 0)
        stats_lay.setSpacing(10)

        # ── Hero card ──
        self.hero_card = _Card()
        hero_lay = QVBoxLayout(self.hero_card)
        hero_lay.setContentsMargins(20, 16, 20, 16)
        hero_lay.setSpacing(2)

        top_row = QHBoxLayout()
        self.lbl_title = QLabel("屏幕使用时间")
        self.lbl_title.setFont(_font(12, True))
        self.lbl_title.setStyleSheet(f"color:{GRAY};")
        top_row.addWidget(self.lbl_title)
        top_row.addStretch()
        self.lbl_apps = QLabel()
        self.lbl_apps.setFont(_font(12))
        self.lbl_apps.setStyleSheet(f"color:{GRAY};")
        self.lbl_apps.setAlignment(Qt.AlignRight)
        top_row.addWidget(self.lbl_apps)
        hero_lay.addLayout(top_row)

        mid_row = QHBoxLayout()

        # 左箭头
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(36, 36)
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.setStyleSheet(
            f"QPushButton{{background:{CARD};color:{ACCENT};border:1px solid {BORDER};"
            f"border-radius:18px;font-size:15px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{ACCENT};color:white;border-color:{ACCENT};}}"
        )
        self.btn_prev.clicked.connect(self._prev_period)
        mid_row.addWidget(self.btn_prev)

        # 日期显示
        left_col = QVBoxLayout()
        left_col.setAlignment(Qt.AlignCenter)
        self.lbl_day = QLabel()
        self.lbl_day.setFont(_font(18, True))
        self.lbl_day.setStyleSheet(f"color:{TEXT};")
        self.lbl_day.setAlignment(Qt.AlignCenter)
        self.lbl_date = QLabel()
        self.lbl_date.setFont(_font(12))
        self.lbl_date.setStyleSheet(f"color:{GRAY};")
        self.lbl_date.setAlignment(Qt.AlignCenter)
        left_col.addWidget(self.lbl_day)
        left_col.addWidget(self.lbl_date)
        mid_row.addLayout(left_col)

        # 右箭头
        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(36, 36)
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.setStyleSheet(
            f"QPushButton{{background:{CARD};color:{ACCENT};border:1px solid {BORDER};"
            f"border-radius:18px;font-size:15px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{ACCENT};color:white;border-color:{ACCENT};}}"
        )
        self.btn_next.clicked.connect(self._next_period)
        mid_row.addWidget(self.btn_next)

        mid_row.addStretch()
        self.lbl_total = QLabel()
        self.lbl_total.setFont(_font(28, True))
        self.lbl_total.setStyleSheet(f"color:{ACCENT};")
        self.lbl_total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        mid_row.addWidget(self.lbl_total)
        hero_lay.addLayout(mid_row)

        stats_lay.addWidget(self.hero_card)

        # ── Action bar ──
        act_bar = QHBoxLayout()
        act_bar.setSpacing(8)
        self.btn_pause = QPushButton("暂停统计")
        self.btn_clear = QPushButton("清空数据")
        self.btn_ignore = QPushButton("忽略列表")
        for btn in (self.btn_pause, self.btn_clear, self.btn_ignore):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                f"QPushButton{{background:{CARD};color:{GRAY};border:none;"
                f"border-radius:8px;padding:0 14px;font-size:12px;}}"
                f"QPushButton:hover{{color:{TEXT};}}"
            )
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_clear.clicked.connect(self._clear_data)
        self.btn_ignore.clicked.connect(self._show_ignore_dialog)
        act_bar.addWidget(self.btn_pause)
        act_bar.addWidget(self.btn_clear)
        act_bar.addWidget(self.btn_ignore)
        act_bar.addStretch()
        stats_lay.addLayout(act_bar)

        # ── Bar chart (weekly) ──
        self.chart_card = _Card()
        chart_lay = QVBoxLayout(self.chart_card)
        chart_lay.setContentsMargins(14, 10, 14, 10)
        lbl_chart = QLabel("每日使用")
        lbl_chart.setFont(_font(11, True))
        lbl_chart.setStyleSheet(f"color:{GRAY};")
        chart_lay.addWidget(lbl_chart)
        self.bar_chart = _BarChart()
        chart_lay.addWidget(self.bar_chart)
        self.chart_card.hide()
        stats_lay.addWidget(self.chart_card)

        # ── Hourly chart (daily) ──
        self.hourly_card = _Card()
        hourly_lay = QVBoxLayout(self.hourly_card)
        hourly_lay.setContentsMargins(14, 10, 14, 10)
        lbl_hourly = QLabel("每小时使用")
        lbl_hourly.setFont(_font(11, True))
        lbl_hourly.setStyleSheet(f"color:{GRAY};")
        hourly_lay.addWidget(lbl_hourly)
        self.hourly_chart = _HourlyChart(fixed_labels=True)
        hourly_lay.addWidget(self.hourly_chart)
        self.hourly_card.hide()
        stats_lay.addWidget(self.hourly_card)

        # ── App list card ──
        list_card = _Card()
        list_lay = QVBoxLayout(list_card)
        list_lay.setContentsMargins(0, 10, 0, 10)
        list_lay.setSpacing(0)

        self.lbl_list_title = QLabel("  应用使用排行")
        self.lbl_list_title.setFont(_font(11, True))
        self.lbl_list_title.setStyleSheet(f"color:{GRAY};padding:0 14px;")
        list_lay.addWidget(self.lbl_list_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:transparent;}}"
            f"QScrollBar:vertical{{background:transparent;width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;min-height:20px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(1)
        self.list_layout.addStretch()
        scroll.setWidget(self.list_container)
        list_lay.addWidget(scroll)

        stats_lay.addWidget(list_card, 1)

        # Add stats container to content
        content_lay.addWidget(self.stats_container)

        # ── Settings page ──
        self.settings_widget = self._build_settings_page()
        self.settings_widget.hide()
        content_lay.addWidget(self.settings_widget)

        outer.addWidget(content)
        self._switch_tab("daily")

    # ── 窗口拖动 ──────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _build_settings_page(self):
        widget = QWidget()
        lay = QVBoxLayout(widget)
        lay.setSpacing(14)

        # ── 隐私说明 ──
        priv_card = _Card()
        priv_lay = QVBoxLayout(priv_card)
        priv_lay.setContentsMargins(20, 18, 20, 18)
        priv_lay.setSpacing(10)

        priv_title = QLabel("  隐私与安全")
        priv_title.setFont(_font(13, True))
        priv_title.setStyleSheet(f"color:{TEXT};")
        priv_lay.addWidget(priv_title)

        items = [
            ("✓", "所有数据仅存储在本地，不上传至任何服务器"),
            ("✓", "不收集任何个人信息、键盘输入或屏幕截图"),
            ("✓", "不联网，无任何网络请求"),
            ("✓", "关闭软件后不会在后台运行任何数据采集"),
        ]
        for icon, text in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            icon_lbl = QLabel(icon)
            icon_lbl.setFont(_font(12))
            icon_lbl.setStyleSheet(f"color:{GREEN};")
            icon_lbl.setFixedWidth(16)
            text_lbl = QLabel(text)
            text_lbl.setFont(_font(11))
            text_lbl.setStyleSheet(f"color:{GRAY};")
            text_lbl.setWordWrap(True)
            row.addWidget(icon_lbl)
            row.addWidget(text_lbl, 1)
            priv_lay.addLayout(row)

        lay.addWidget(priv_card)

        # ── 无操作休眠 ──
        idle_card = _Card()
        idle_lay = QVBoxLayout(idle_card)
        idle_lay.setContentsMargins(20, 18, 20, 18)
        idle_lay.setSpacing(12)

        idle_title = QLabel("  无操作休眠")
        idle_title.setFont(_font(13, True))
        idle_title.setStyleSheet(f"color:{TEXT};")
        idle_lay.addWidget(idle_title)

        idle_desc = QLabel("当鼠标和键盘无操作超过设定时间，自动暂停计时")
        idle_desc.setFont(_font(11))
        idle_desc.setStyleSheet(f"color:{GRAY};")
        idle_lay.addWidget(idle_desc)

        current_idle = int(get_setting("idle_threshold", "300"))

        # 快捷按钮行
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        self._idle_presets = []
        for label, secs in [("1 分钟", 60), ("3 分钟", 180), ("5 分钟", 300), ("10 分钟", 600)]:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("idle_secs", secs)
            btn.clicked.connect(lambda checked, b=btn: self._on_idle_preset(b))
            self._idle_presets.append(btn)
            preset_row.addWidget(btn)
        self._update_idle_preset_style(current_idle)
        idle_lay.addLayout(preset_row)

        # 滑块
        slider_row = QHBoxLayout()
        slider_row.setSpacing(12)
        self.idle_slider = QSlider(Qt.Horizontal)
        self.idle_slider.setMinimum(60)
        self.idle_slider.setMaximum(600)
        self.idle_slider.setSingleStep(60)
        self.idle_slider.setTickInterval(60)
        self.idle_slider.setValue(current_idle)
        self.idle_slider.valueChanged.connect(self._on_idle_changed)
        self.lbl_idle_val = QLabel(f"{current_idle // 60} 分钟")
        self.lbl_idle_val.setFont(_font(12, True))
        self.lbl_idle_val.setStyleSheet(f"color:{ACCENT};min-width:48px;")
        self.lbl_idle_val.setAlignment(Qt.AlignCenter)
        slider_row.addWidget(self.idle_slider)
        slider_row.addWidget(self.lbl_idle_val)
        idle_lay.addLayout(slider_row)

        lay.addWidget(idle_card)

        # ── 开机自启 ──
        auto_card = _Card()
        auto_lay = QVBoxLayout(auto_card)
        auto_lay.setContentsMargins(20, 18, 20, 18)
        auto_lay.setSpacing(8)

        auto_title = QLabel("  开机自启")
        auto_title.setFont(_font(13, True))
        auto_title.setStyleSheet(f"color:{TEXT};")
        auto_lay.addWidget(auto_title)

        self.chk_autostart = QCheckBox("开机时自动启动并最小化到系统托盘")
        self.chk_autostart.setFont(_font(11))
        self.chk_autostart.setStyleSheet(
            f"QCheckBox{{color:{TEXT};spacing:8px;}}"
            f"QCheckBox::indicator{{width:16px;height:16px;border-radius:8px;"
            f"border:2px solid {BORDER};background:white;}}"
            f"QCheckBox::indicator:checked{{background:{ACCENT};border-color:{ACCENT};}}"
        )
        try:
            from autostart import is_autostart_enabled
            self.chk_autostart.setChecked(is_autostart_enabled())
        except Exception:
            self.chk_autostart.setChecked(False)
        self.chk_autostart.toggled.connect(self._on_autostart_toggled)
        auto_lay.addWidget(self.chk_autostart)

        lay.addWidget(auto_card)

        lay.addStretch()
        return widget

    def _update_idle_preset_style(self, current_secs):
        for btn in self._idle_presets:
            secs = btn.property("idle_secs")
            if secs == current_secs:
                btn.setStyleSheet(
                    f"QPushButton{{background:{ACCENT};color:white;border:none;"
                    f"border-radius:8px;padding:0 14px;font-size:11px;}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background:{CARD};color:{GRAY};border:none;"
                    f"border-radius:8px;padding:0 14px;font-size:11px;}}"
                    f"QPushButton:hover{{background:{HOVER};color:{TEXT};}}"
                )

    def _on_idle_preset(self, btn):
        secs = btn.property("idle_secs")
        self.idle_slider.setValue(secs)

    def _update_clock(self):
        now = datetime.now()
        self.lbl_clock.setText(now.strftime("%H:%M:%S"))

    def _on_idle_changed(self, val):
        rounded = max(60, (val // 60) * 60)
        self.lbl_idle_val.setText(f"{rounded // 60} 分钟")
        self._update_idle_preset_style(rounded)
        set_setting("idle_threshold", str(rounded))

    def _on_autostart_toggled(self, checked):
        try:
            from autostart import enable_autostart, disable_autostart
            if checked:
                enable_autostart()
            else:
                disable_autostart()
            set_setting("autostart", "1" if checked else "0")
        except Exception:
            pass

    # ── Tab switch ────────────────────────────────────────────

    def _switch_tab(self, tab):
        self._current_tab = tab
        self._view_date = date.today()
        active_style = (
            f"QPushButton{{background:{ACCENT};color:white;border:none;"
            f"border-radius:8px;padding:0 16px;font-size:13px;font-weight:bold;}}"
        )
        inactive_style = (
            f"QPushButton{{background:transparent;color:{GRAY};border:none;"
            f"border-radius:8px;padding:0 16px;font-size:13px;}}"
            f"QPushButton:hover{{background:{HOVER};}}"
        )

        for btn in (self.btn_daily, self.btn_weekly, self.btn_settings):
            btn.setStyleSheet(inactive_style)

        tab_map = {
            "daily": self.btn_daily,
            "weekly": self.btn_weekly,
            "settings": self.btn_settings,
        }
        tab_map[tab].setStyleSheet(active_style)

        show_stats = tab in ("daily", "weekly")
        self.stats_container.setVisible(show_stats)
        self.chart_card.setVisible(tab == "weekly")
        self.hourly_card.setVisible(tab == "daily")
        self.settings_widget.setVisible(tab == "settings")

        if show_stats:
            self._refresh()
        self._update_pause_button()

    # ── 导航 ──────────────────────────────────────────────────

    def _prev_period(self):
        if self._current_tab == "daily":
            self._view_date -= timedelta(days=1)
        elif self._current_tab == "weekly":
            self._view_date -= timedelta(days=7)
        self._refresh()

    def _next_period(self):
        today = date.today()
        if self._current_tab == "daily":
            new_date = self._view_date + timedelta(days=1)
            if new_date <= today:
                self._view_date = new_date
        elif self._current_tab == "weekly":
            new_date = self._view_date + timedelta(days=7)
            if new_date <= today:
                self._view_date = new_date
        self._refresh()

    def _update_arrow_state(self):
        today = date.today()
        is_today = self._view_date >= today
        if self._current_tab == "weekly":
            is_today = self._view_date + timedelta(days=6) >= today
        self.btn_next.setEnabled(not is_today)
        if is_today:
            self.btn_next.setStyleSheet(
                f"QPushButton{{background:{CARD};color:{MUTED};border:1px solid {BORDER};"
                f"border-radius:18px;font-size:15px;font-weight:bold;}}"
            )
        else:
            self.btn_next.setStyleSheet(
                f"QPushButton{{background:{CARD};color:{ACCENT};border:1px solid {BORDER};"
                f"border-radius:18px;font-size:15px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{ACCENT};color:white;border-color:{ACCENT};}}"
            )

    # ── Refresh ───────────────────────────────────────────────

    def _refresh(self):
        if self._current_tab == "daily":
            self._refresh_daily()
        elif self._current_tab == "weekly":
            self._refresh_weekly()
        self._update_pause_button()

    def _refresh_daily(self):
        target = self._view_date.isoformat()
        stats = get_stats(target)
        total = get_daily_total(target)
        hourly = get_hourly_stats(target)

        d = self._view_date
        is_today = d == date.today()
        self.lbl_day.setText("今日" if is_today else _CN_DAY.get(d.weekday(), ""))
        self.lbl_date.setText(f"{d.year}年{d.month}月{d.day}日")

        self.lbl_total.setText(format_duration_short(total))
        self.lbl_apps.setText(f"{len(stats)} 个应用")
        self._populate_list(stats, total)
        self.hourly_chart.set_data(hourly)
        self._update_arrow_state()

    def _refresh_weekly(self):
        d = self._view_date
        week_end = d
        week_start = d - timedelta(days=6)
        week_stats = get_week_stats(week_end.isoformat())
        app_stats = get_week_app_stats(week_end.isoformat())
        week_total = sum(d["total_seconds"] for d in week_stats)

        is_this_week = week_end >= date.today()
        self.lbl_day.setText("本周" if is_this_week else "本周")
        self.lbl_date.setText(f"{week_start.month}月{week_start.day}日 - {week_end.month}月{week_end.day}日")
        self.lbl_total.setText(format_duration_short(week_total))
        self.lbl_apps.setText(f"{len(app_stats)} 个应用")

        self.bar_chart.set_data(week_stats, week_end.isoformat())
        self._populate_list(app_stats, week_total)
        self._update_arrow_state()

    def _populate_list(self, stats, total):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not stats:
            lbl = QLabel("暂无使用数据")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFont(_font(13))
            lbl.setStyleSheet(f"color:{MUTED};padding:40px;")
            self.list_layout.insertWidget(0, lbl)
            return

        for i, s in enumerate(stats):
            color = APP_COLORS[i % len(APP_COLORS)]
            pct = (s["total_seconds"] / total * 100) if total > 0 else 0
            row = self._make_row(
                s["app_name"], s["display_name"],
                s["total_seconds"], pct, color)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

    def _make_row(self, app_name, display_name, seconds, pct, color):
        row = QFrame()
        row.setStyleSheet(
            f"QFrame{{background:transparent;border:none;border-radius:8px;}}"
            f"QFrame:hover{{background:{HOVER};}}"
        )
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(6)

        # Icon
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(20, 20)
        pil_img = get_icon(app_name, display_name, size=20)
        px = _pil_to_pixmap(pil_img, 20)
        icon_lbl.setPixmap(px)
        lay.addWidget(icon_lbl)

        # Name + bar
        mid = QVBoxLayout()
        mid.setSpacing(2)
        name_lbl = QLabel(display_name)
        name_lbl.setFont(_font(11))
        name_lbl.setStyleSheet(f"color:{TEXT};")
        mid.addWidget(name_lbl)

        bar_bg = QFrame()
        bar_bg.setFixedHeight(3)
        bar_bg.setStyleSheet(f"background:{CHART_BG};border-radius:1px;")
        bar_fg = QFrame(bar_bg)
        bar_fg.setFixedHeight(3)
        frac = max(0.005, pct / 100)
        bar_fg.setFixedWidth(max(2, int(bar_bg.width() * frac)))
        bar_fg.setStyleSheet(f"background:{color};border-radius:1px;")
        bar_fg.resize(max(2, int(300 * frac)), 3)
        mid.addWidget(bar_bg)

        lay.addLayout(mid, 1)

        # Time + pct
        right = QVBoxLayout()
        right.setSpacing(2)
        time_lbl = QLabel(format_duration_short(seconds))
        time_lbl.setFont(_font(11, True))
        time_lbl.setStyleSheet(f"color:{TEXT};")
        time_lbl.setAlignment(Qt.AlignRight)
        pct_lbl = QLabel(f"{pct:.1f}%")
        pct_lbl.setFont(_font(9))
        pct_lbl.setStyleSheet(f"color:{MUTED};")
        pct_lbl.setAlignment(Qt.AlignRight)
        right.addWidget(time_lbl)
        right.addWidget(pct_lbl)
        lay.addLayout(right)

        return row

    # ── Actions ───────────────────────────────────────────────

    def _toggle_pause(self):
        if self.monitor is None:
            return
        if self.monitor.is_paused:
            self.monitor.resume()
        else:
            self.monitor.pause()
        self._update_pause_button()

    def _update_pause_button(self):
        if self.monitor and self.monitor.is_paused:
            self.btn_pause.setText("继续统计")
            self.btn_pause.setStyleSheet(
                f"QPushButton{{background:{ACCENT};color:white;border:none;"
                f"border-radius:8px;padding:0 14px;font-size:12px;}}")
        else:
            self.btn_pause.setText("暂停统计")
            self.btn_pause.setStyleSheet(
                f"QPushButton{{background:{CARD};color:{GRAY};border:none;"
                f"border-radius:8px;padding:0 14px;font-size:12px;}}"
                f"QPushButton:hover{{color:{TEXT};}}")

    def _clear_data(self):
        ret = QMessageBox.question(
            self, "确认清空", "确定要清空所有统计数据吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            clear_all_data()
            self._refresh()

    def _show_ignore_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("忽略列表")
        dlg.setMinimumWidth(320)
        dlg.setStyleSheet(
            f"QDialog{{background:{BG};}}"
            f"QLabel{{color:{TEXT};font-size:13px;}}"
        )

        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)

        lbl = QLabel("勾选的应用将不计入统计：")
        lbl.setFont(_font(13))
        lay.addWidget(lbl)

        all_stats = get_stats()
        ignored = get_ignored_apps()
        for s in all_stats:
            cb = QLabel(s["display_name"])
            cb.setFont(_font(13))
            cb_name = s["app_name"]
            is_ignored = cb_name.lower() in ignored
            toggle_btn = QPushButton("已忽略" if is_ignored else "忽略")
            toggle_btn.setFixedHeight(28)
            toggle_btn.setStyleSheet(
                f"QPushButton{{background:{RED if is_ignored else CARD};"
                f"color:white;border:none;border-radius:6px;"
                f"padding:0 12px;font-size:12px;}}")
            row = QHBoxLayout()
            row.addWidget(cb)
            row.addStretch()
            row.addWidget(toggle_btn)

            def make_toggle(name, btn, is_ign):
                def toggle():
                    if is_ign:
                        remove_ignored_app(name)
                        btn.setText("忽略")
                        btn.setStyleSheet(
                            f"QPushButton{{background:{CARD};color:{TEXT};"
                            f"border:none;border-radius:6px;"
                            f"padding:0 12px;font-size:12px;}}")
                    else:
                        add_ignored_app(name)
                        btn.setText("已忽略")
                        btn.setStyleSheet(
                            f"QPushButton{{background:{RED};color:white;"
                            f"border:none;border-radius:6px;"
                            f"padding:0 12px;font-size:12px;}}")
                return toggle

            toggle_btn.clicked.connect(make_toggle(cb_name, toggle_btn, is_ignored))
            lay.addLayout(row)

        btn_box = QPushButton("关闭")
        btn_box.setStyleSheet(
            f"QPushButton{{background:{CARD};color:{GRAY};border:none;"
            f"border-radius:8px;padding:8px 24px;font-size:12px;}}"
            f"QPushButton:hover{{color:{TEXT};}}")
        btn_box.clicked.connect(dlg.close)
        lay.addWidget(btn_box, alignment=Qt.AlignCenter)

        dlg.exec()
