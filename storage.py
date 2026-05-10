import sqlite3
import os
import sys
from datetime import date, timedelta, datetime
from threading import Lock


def _get_db_path():
    if getattr(sys, 'frozen', False):
        appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
        db_dir = os.path.join(appdata, 'UsageTracker')
        os.makedirs(db_dir, exist_ok=True)
        return os.path.join(db_dir, 'usage.db')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage.db")


DB_PATH = _get_db_path()
_lock = Lock()

# 内置默认中文名（用户自定义规则优先级更高）
_APP_NAMES = {
    "chrome.exe": "Chrome 浏览器",
    "msedge.exe": "Edge 浏览器",
    "firefox.exe": "Firefox 浏览器",
    "code.exe": "VS Code",
    "code - insiders.exe": "VS Code",
    "explorer.exe": "文件资源管理器",
    "wechat.exe": "微信",
    "wechatappex.exe": "微信",
    "qq.exe": "QQ",
    "dingtalk.exe": "钉钉",
    "feishu.exe": "飞书",
    "slack.exe": "Slack",
    "spotify.exe": "Spotify",
    "telegram.exe": "Telegram",
    "notepad.exe": "记事本",
    "notepad++.exe": "Notepad++",
    "photos.exe": "照片",
    "snippingtool.exe": "截图工具",
    "python.exe": "Python",
    "pythonw.exe": "Python",
    "cmd.exe": "命令提示符",
    "windowsterminal.exe": "终端",
    "pwsh.exe": "PowerShell",
    "7zg.exe": "7-Zip",
    "winrar.exe": "WinRAR",
    "gameviewer.exe": "UU远程",
    "anydesk.exe": "AnyDesk",
    "teamviewer.exe": "TeamViewer",
    "steam.exe": "Steam",
    "wegame.exe": "WeGame",
    "tyty.exe": "Tyty",
    "shellexperiencehost.exe": "开始菜单",
    "openwith.exe": "打开方式",
    "searchui.exe": "搜索",
    "textinputhost.exe": "输入法",
    "leagueclientux.exe": "英雄联盟",
}

_APP_NAMES_LOWER = {k.lower(): v for k, v in _APP_NAMES.items()}

# 默认合并规则（会被 DB 中的 app_rules 覆盖）
_DEFAULT_APP_GROUPS = {
    "leagueclientux.exe":     "leagueclientux.exe",
    "league of legends.exe":  "leagueclientux.exe",
    "riotclientux.exe":       "leagueclientux.exe",
    "riotclientservices.exe": "leagueclientux.exe",
    "wechatappex.exe":        "wechat.exe",
    "code - insiders.exe":    "code.exe",
}

# 运行时缓存
_app_groups_cache = None


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    global _app_groups_cache
    _app_groups_cache = None
    with _lock, _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_fragments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                app_name TEXT NOT NULL,
                window_title TEXT,
                exe_path TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                is_idle INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_frag_date_app
            ON usage_fragments(date, app_name)
        """)
        # 检查 app_usage 表是否有正确的列
        need_recreate = False
        try:
            cols = conn.execute("PRAGMA table_info(app_usage)").fetchall()
            col_names = {c[1] for c in cols}
            if "total_seconds" not in col_names or "session_count" not in col_names:
                need_recreate = True
        except Exception:
            pass

        if need_recreate:
            conn.execute("DROP TABLE IF EXISTS app_usage")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                app_name TEXT NOT NULL,
                total_seconds REAL NOT NULL DEFAULT 0,
                session_count INTEGER NOT NULL DEFAULT 1,
                UNIQUE(date, app_name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ignored_apps (
                app_name TEXT PRIMARY KEY
            )
        """)
        # 应用合并/重命名规则表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_rules (
                child_name TEXT PRIMARY KEY,
                parent_name TEXT NOT NULL,
                display_name TEXT
            )
        """)
        # 设置表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # 初始化默认设置
        defaults = {
            "save_window_title": "0",
            "idle_threshold": "300",
            "first_run_done": "0",
            "autostart": "0",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (k, v),
            )
        # 将默认规则写入 DB（仅在表为空时）
        count = conn.execute("SELECT COUNT(*) as c FROM app_rules").fetchone()["c"]
        if count == 0:
            for child, parent in _DEFAULT_APP_GROUPS.items():
                display = _APP_NAMES_LOWER.get(child) if child != parent else None
                conn.execute(
                    "INSERT OR IGNORE INTO app_rules (child_name, parent_name, display_name) VALUES (?, ?, ?)",
                    (child, parent, display),
                )


# ── 设置 ──────────────────────────────────────────────────────

def get_setting(key, default=None):
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    if row:
        return row["value"]
    return default


def set_setting(key, value):
    with _lock, _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )


def get_all_settings():
    with _get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def is_first_run():
    return get_setting("first_run_done", "0") != "1"


def mark_first_run_done():
    set_setting("first_run_done", "1")


# ── 应用规则 ──────────────────────────────────────────────────

def get_app_rules():
    """返回 {child: parent} 字典，合并内置默认 + DB 自定义。"""
    global _app_groups_cache
    if _app_groups_cache is not None:
        return _app_groups_cache
    rules = dict(_DEFAULT_APP_GROUPS)
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT child_name, parent_name FROM app_rules"
        ).fetchall()
    for r in rows:
        rules[r["child_name"].lower()] = r["parent_name"].lower()
    _app_groups_cache = rules
    return rules


def get_app_rules_with_display():
    """返回 [(child, parent, display_name), ...] 用于 UI 展示。"""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT child_name, parent_name, display_name FROM app_rules ORDER BY parent_name"
        ).fetchall()
    return [(r["child_name"], r["parent_name"], r["display_name"]) for r in rows]


def add_app_rule(child_name, parent_name, display_name=None):
    global _app_groups_cache
    _app_groups_cache = None
    with _lock, _get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO app_rules (child_name, parent_name, display_name)
               VALUES (?, ?, ?)""",
            (child_name.lower(), parent_name.lower(), display_name),
        )


def remove_app_rule(child_name):
    global _app_groups_cache
    _app_groups_cache = None
    with _lock, _get_conn() as conn:
        conn.execute(
            "DELETE FROM app_rules WHERE child_name = ?",
            (child_name.lower(),),
        )


# ── 崩溃恢复 ──────────────────────────────────────────────────

def get_last_unfinished_fragment():
    """获取最后一次未正常结束的片段（end_time 晚于当前时间前 10 分钟的不算）。
    实际上我们检查最近一条 fragment，如果它的 end_time 距现在超过 poll_interval*2，
    说明程序可能异常退出时丢失了中间片段。返回 (app_name, end_time) 或 None。"""
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT app_name, end_time FROM usage_fragments
               WHERE is_idle = 0
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    if row:
        return {"app_name": row["app_name"], "end_time": row["end_time"]}
    return None


# ── 记录 ──────────────────────────────────────────────────────

def record_fragment(app_name, window_title, exe_path, start_iso, end_iso,
                    duration, is_idle=False):
    if duration < 0.5:
        return
    save_title = get_setting("save_window_title", "0") == "1"
    title_to_save = window_title if save_title else None
    today = date.today().isoformat()
    with _lock, _get_conn() as conn:
        conn.execute(
            """INSERT INTO usage_fragments
               (date, app_name, window_title, exe_path,
                start_time, end_time, duration_seconds, is_idle)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (today, app_name, title_to_save, exe_path,
             start_iso, end_iso, round(duration, 2), 1 if is_idle else 0),
        )
        if not is_idle:
            conn.execute(
                """INSERT INTO app_usage (date, app_name, total_seconds, session_count)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(date, app_name)
                   DO UPDATE SET total_seconds = total_seconds + ?,
                                 session_count = session_count + 1""",
                (today, app_name, duration, duration),
            )


def record_fragments_batch(fragments):
    """批量写入片段。fragments 是 list of dict。"""
    if not fragments:
        return
    save_title = get_setting("save_window_title", "0") == "1"
    today = date.today().isoformat()
    with _lock, _get_conn() as conn:
        for f in fragments:
            if f["duration"] < 0.5:
                continue
            title = f.get("window_title") if save_title else None
            conn.execute(
                """INSERT INTO usage_fragments
                   (date, app_name, window_title, exe_path,
                    start_time, end_time, duration_seconds, is_idle)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (today, f["app_name"], title, f.get("exe_path", ""),
                 f["start_time"], f["end_time"],
                 round(f["duration"], 2), 1 if f.get("is_idle") else 0),
            )
            if not f.get("is_idle"):
                conn.execute(
                    """INSERT INTO app_usage (date, app_name, total_seconds, session_count)
                       VALUES (?, ?, ?, 1)
                       ON CONFLICT(date, app_name)
                       DO UPDATE SET total_seconds = total_seconds + ?,
                                     session_count = session_count + 1""",
                    (today, f["app_name"], f["duration"], f["duration"]),
                )


# ── 查询 ──────────────────────────────────────────────────────

def get_display_name(app_name):
    # 优先查 DB 自定义规则的 display_name
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT display_name FROM app_rules WHERE child_name = ? AND display_name IS NOT NULL",
            (app_name.lower(),),
        ).fetchone()
        if row and row["display_name"]:
            return row["display_name"]
        # 查是否被合并到某个 parent
        row2 = conn.execute(
            "SELECT parent_name FROM app_rules WHERE child_name = ?",
            (app_name.lower(),),
        ).fetchone()
        if row2 and row2["parent_name"] != app_name.lower():
            prow = conn.execute(
                "SELECT display_name FROM app_rules WHERE child_name = ? AND display_name IS NOT NULL",
                (row2["parent_name"],),
            ).fetchone()
            if prow and prow["display_name"]:
                return prow["display_name"]

    # 快捷方式名称
    try:
        from icons import get_shortcut_info
        sc = get_shortcut_info(app_name)
        if sc and sc["display_name"]:
            return sc["display_name"]
    except Exception:
        pass

    desc = _extract_display_name(app_name)
    if desc:
        return desc
    name = _APP_NAMES_LOWER.get(app_name.lower())
    if name:
        return name
    if app_name.lower().endswith(".exe"):
        return app_name[:-4]
    return app_name


_name_cache = {}


def _extract_display_name(app_name):
    if app_name in _name_cache:
        return _name_cache[app_name]
    try:
        import psutil
        import win32api
        rules = get_app_rules()
        aliases = {app_name.lower()}
        for child, parent in rules.items():
            if parent == app_name.lower():
                aliases.add(child)
        for proc in psutil.process_iter(['name', 'exe']):
            try:
                if (proc.info['name'] and
                        proc.info['name'].lower() in aliases and
                        proc.info['exe']):
                    info = win32api.GetFileVersionInfo(
                        proc.info['exe'], "\\VarFileInfo\\Translation")
                    if info:
                        lang, cp = info[0]
                        key = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription"
                        desc = win32api.GetFileVersionInfo(proc.info['exe'], key)
                        desc = desc.strip() if desc else ""
                        bad = {"release", "main", "app", "application",
                               "loader", "launcher", "setup", "install"}
                        if desc and len(desc) > 1 and desc.lower() not in bad:
                            _name_cache[app_name] = desc
                            return desc
            except Exception:
                continue
    except Exception:
        pass
    return None


def _merge_rows(rows):
    rules = get_app_rules()
    merged = {}
    for r in rows:
        d = dict(r)
        app = d["app_name"].lower()
        key = rules.get(app, app)
        if key in merged:
            merged[key]["total_seconds"] += d["total_seconds"]
            if "session_count" in d:
                merged[key]["session_count"] += d["session_count"]
            if "days_used" in d:
                merged[key]["days_used"] = max(merged[key]["days_used"], d["days_used"])
        else:
            merged[key] = {
                "app_name": key,
                "total_seconds": d["total_seconds"],
                "display_name": get_display_name(key),
            }
            if "session_count" in d:
                merged[key]["session_count"] = d["session_count"]
            if "days_used" in d:
                merged[key]["days_used"] = d["days_used"]
    return sorted(merged.values(), key=lambda x: x["total_seconds"], reverse=True)


def get_stats(target_date=None):
    if target_date is None:
        target_date = date.today().isoformat()
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT LOWER(app_name) as app_name,
                      SUM(total_seconds) as total_seconds,
                      SUM(session_count) as session_count
               FROM app_usage
               WHERE date = ?
               GROUP BY LOWER(app_name)
               ORDER BY total_seconds DESC""",
            (target_date,),
        ).fetchall()
    return _merge_rows(rows)


def get_daily_total(target_date=None):
    if target_date is None:
        target_date = date.today().isoformat()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(total_seconds), 0) as t FROM app_usage WHERE date = ?",
            (target_date,),
        ).fetchone()
    return row["t"]


def get_available_dates():
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM app_usage ORDER BY date DESC"
        ).fetchall()
    return [r["date"] for r in rows]


def get_week_stats(start_date=None):
    if start_date is None:
        start_date = date.today().isoformat()
    d = date.fromisoformat(start_date)
    week_start = d - timedelta(days=6)
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT date, SUM(total_seconds) as total_seconds
               FROM app_usage
               WHERE date >= ? AND date <= ?
               GROUP BY date
               ORDER BY date""",
            (week_start.isoformat(), start_date),
        ).fetchall()
    result = {r["date"]: r["total_seconds"] for r in rows}
    days = []
    for i in range(7):
        dd = week_start + timedelta(days=i)
        ds = dd.isoformat()
        days.append({"date": ds, "total_seconds": result.get(ds, 0)})
    return days


def get_week_app_stats(start_date=None):
    if start_date is None:
        start_date = date.today().isoformat()
    d = date.fromisoformat(start_date)
    week_start = d - timedelta(days=6)
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT LOWER(app_name) as app_name,
                      SUM(total_seconds) as total_seconds,
                      COUNT(DISTINCT date) as days_used
               FROM app_usage
               WHERE date >= ? AND date <= ?
               GROUP BY LOWER(app_name)
               ORDER BY total_seconds DESC""",
            (week_start.isoformat(), start_date),
        ).fetchall()
    return _merge_rows(rows)


# ── 时间线 ────────────────────────────────────────────────────

def get_fragments_for_date(target_date=None, include_idle=False):
    """获取某天的所有片段，按时间排序，用于时间线视图。"""
    if target_date is None:
        target_date = date.today().isoformat()
    query = """SELECT app_name, window_title, exe_path,
                      start_time, end_time, duration_seconds, is_idle
               FROM usage_fragments
               WHERE date = ?"""
    params = [target_date]
    if not include_idle:
        query += " AND is_idle = 0"
    query += " ORDER BY start_time"
    with _get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ── 忽略列表 ──────────────────────────────────────────────────

def get_ignored_apps():
    with _get_conn() as conn:
        rows = conn.execute("SELECT app_name FROM ignored_apps").fetchall()
    return {r["app_name"].lower() for r in rows}


def add_ignored_app(app_name):
    with _lock, _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO ignored_apps (app_name) VALUES (?)",
            (app_name.lower(),),
        )


def remove_ignored_app(app_name):
    with _lock, _get_conn() as conn:
        conn.execute(
            "DELETE FROM ignored_apps WHERE app_name = ?",
            (app_name.lower(),),
        )


# ── 清空数据 ──────────────────────────────────────────────────

def clear_all_data():
    with _lock, _get_conn() as conn:
        conn.execute("DELETE FROM usage_fragments")
        conn.execute("DELETE FROM app_usage")


# ── 格式化 ────────────────────────────────────────────────────

def format_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}秒"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}小时{minutes}分钟"
    return f"{minutes}分钟"


def format_duration_short(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}秒"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}小时{minutes}分钟"
    return f"{minutes}分钟"


def get_hourly_stats(target_date=None):
    """获取某天 24 小时的使用统计，返回 [秒数] * 24，每小时上限 3600 秒。"""
    if target_date is None:
        target_date = date.today().isoformat()
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT start_time, end_time, duration_seconds, is_idle
               FROM usage_fragments
               WHERE date = ? AND is_idle = 0
               ORDER BY start_time""",
            (target_date,),
        ).fetchall()

    hourly = [0.0] * 24
    for r in rows:
        try:
            s = datetime.fromisoformat(r["start_time"])
            e = datetime.fromisoformat(r["end_time"])
        except Exception:
            continue
        # 限制在合理范围内
        if (e - s).total_seconds() > 86400:
            continue
        cur = s
        while cur < e:
            h = cur.hour
            next_hour = cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            seg_end = min(e, next_hour)
            seg_dur = (seg_end - cur).total_seconds()
            if 0 <= h < 24:
                hourly[h] = min(3600, hourly[h] + seg_dur)
            cur = seg_end

    return hourly


def get_week_hourly_stats(end_date=None):
    """获取一周 24 小时的累计使用统计，返回 [秒数] * 24。"""
    if end_date is None:
        end_date = date.today().isoformat()
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=6)
    result = [0.0] * 24
    cur = start
    while cur <= end:
        hourly = get_hourly_stats(cur.isoformat())
        for h in range(24):
            result[h] += hourly[h]
        cur += timedelta(days=1)
    return result


def format_time_short(iso_str):
    """ISO 时间字符串 → HH:MM"""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M")
    except Exception:
        return iso_str
