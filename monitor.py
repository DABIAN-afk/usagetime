import time
import threading
import ctypes
import ctypes.wintypes as wintypes
from datetime import datetime

import win32gui
import win32process
import psutil

from storage import (
    record_fragments_batch, get_ignored_apps, get_app_rules, get_setting,
)


# ── Idle 检测 ─────────────────────────────────────────────────

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),
    ]


def _get_idle_seconds():
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    tick = ctypes.windll.kernel32.GetTickCount()
    return (tick - lii.dwTime) / 1000.0


# ── 忽略的系统进程 ────────────────────────────────────────────

_IGNORED = {
    "searchui.exe", "shellexperiencehost.exe", "openwith.exe",
    "textinputhost.exe", "lockapp.exe", "applicationframehost.exe",
    "systemsettings.exe", "searchapp.exe", "startmenuexperiencehost.exe",
    "runtimebroker.exe", "sihost.exe", "fontdrvhost.exe",
    "dwm.exe", "csrss.exe",
}


# ── 监控主类 ──────────────────────────────────────────────────

class WindowMonitor:
    def __init__(self, poll_interval=1.0):
        self.poll_interval = poll_interval
        self._running = False
        self._paused = False
        self._thread = None

        self._last_hwnd = None
        self._last_app = None
        self._last_title = None
        self._last_exe = None
        self._last_start = None

        self._was_idle = False

        # 内存缓冲区，定期 flush 到 DB
        self._buffer = []
        self._buffer_lock = threading.Lock()
        self._flush_interval = 10.0  # 每 10 秒 flush 一次
        self._last_flush = time.time()

    @property
    def is_paused(self):
        return self._paused

    @property
    def idle_threshold(self):
        try:
            return int(get_setting("idle_threshold", "300"))
        except (ValueError, TypeError):
            return 300

    def start(self):
        self._running = True
        self._last_start = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._flush_current()
        self._flush_to_db()
        if self._thread:
            self._thread.join(timeout=5)

    def pause(self):
        if not self._paused:
            self._flush_current()
            self._paused = True

    def resume(self):
        if self._paused:
            self._paused = False
            self._last_start = time.time()

    # ── 前台窗口检测（GetForegroundWindow） ─────────────────────

    def _get_active_window_info(self):
        """用 GetForegroundWindow 获取前台窗口信息。"""
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindowVisible(hwnd):
            return None, None, None, None

        title = win32gui.GetWindowText(hwnd)
        if not title or len(title) < 2:
            return None, None, None, None

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            name = proc.name().lower()
            exe = proc.exe() or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            return None, None, None, None

        if name in _IGNORED:
            return None, None, None, None

        # 应用合并规则
        rules = get_app_rules()
        name = rules.get(name, name)

        return hwnd, name, title, exe

    # ── 缓冲区操作 ─────────────────────────────────────────────

    def _add_to_buffer(self, fragment):
        with self._buffer_lock:
            self._buffer.append(fragment)

    def _flush_to_db(self):
        """将缓冲区中的片段写入数据库。"""
        with self._buffer_lock:
            if not self._buffer:
                return
            batch = self._buffer[:]
            self._buffer.clear()
        record_fragments_batch(batch)

    # ── Flush ─────────────────────────────────────────────────

    def _flush_current(self):
        """将当前正在计时的片段 flush 到缓冲区。"""
        if self._last_app and self._last_start:
            now = time.time()
            duration = now - self._last_start
            if duration >= 0.5:
                start_iso = datetime.fromtimestamp(self._last_start).isoformat()
                end_iso = datetime.fromtimestamp(now).isoformat()
                ignored = get_ignored_apps()
                if self._last_app.lower() not in ignored:
                    self._add_to_buffer({
                        "app_name": self._last_app,
                        "window_title": self._last_title,
                        "exe_path": self._last_exe,
                        "start_time": start_iso,
                        "end_time": end_iso,
                        "duration": duration,
                        "is_idle": False,
                    })

    def _flush_idle(self, idle_start, idle_end):
        duration = idle_end - idle_start
        if duration >= 0.5:
            start_iso = datetime.fromtimestamp(idle_start).isoformat()
            end_iso = datetime.fromtimestamp(idle_end).isoformat()
            self._add_to_buffer({
                "app_name": self._last_app or "idle",
                "window_title": "idle",
                "exe_path": "",
                "start_time": start_iso,
                "end_time": end_iso,
                "duration": duration,
                "is_idle": True,
            })

    # ── 主循环 ────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            if self._paused:
                time.sleep(self.poll_interval)
                continue

            idle_secs = _get_idle_seconds()
            is_idle = idle_secs > self.idle_threshold

            if is_idle and not self._was_idle:
                # 刚进入 idle
                self._flush_current()
                self._idle_start = time.time() - idle_secs
                self._was_idle = True

            elif not is_idle and self._was_idle:
                # 从 idle 恢复
                idle_end = time.time()
                self._flush_idle(self._idle_start, idle_end)
                self._was_idle = False
                self._last_start = time.time()
                self._last_hwnd = None  # 强制重新检测窗口

            elif not is_idle:
                # 正常计时
                hwnd, app_name, title, exe = self._get_active_window_info()
                if hwnd and hwnd != self._last_hwnd:
                    self._flush_current()
                    self._last_hwnd = hwnd
                    self._last_app = app_name
                    self._last_title = title
                    self._last_exe = exe
                    self._last_start = time.time()

            # 定期 flush 缓冲区到 DB
            now = time.time()
            if now - self._last_flush >= self._flush_interval:
                self._flush_current()
                self._flush_to_db()
                self._last_start = time.time()
                self._last_flush = now

            time.sleep(self.poll_interval)
