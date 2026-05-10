import ctypes
import ctypes.wintypes as wintypes
import struct
import win32gui
import win32ui
from PIL import Image, ImageDraw, ImageFont
import os
import glob as globmod

# ── Windows API ───────────────────────────────────────────────
SHGFI_ICON = 0x00000100
SHGFI_SYSICONINDEX = 0x00004000
SHIL_EXTRALARGE = 0x2
SHIL_LARGE = 0x0

shell32 = ctypes.windll.shell32
comctl32 = ctypes.windll.comctl32

_IID_IImageList = struct.pack('16s', bytes.fromhex(
    '46EB5926582E4017AF9E428BACE4B2A8'))


class SHFILEINFO(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", ctypes.c_uint),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]

# ── Cache ─────────────────────────────────────────────────────
_cache = {}
_exe_path_cache = {}
_shortcut_cache = None  # {exe_name_lower: {display_name, icon_path, icon_index}}


def _scan_shortcuts():
    """扫描桌面和开始菜单的快捷方式，建立 exe → 名称/图标映射。"""
    global _shortcut_cache
    if _shortcut_cache is not None:
        return _shortcut_cache

    _shortcut_cache = {}
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
    except Exception:
        return _shortcut_cache

    # 扫描目录
    dirs_to_scan = []
    for env_var in ("USERPROFILE", "PUBLIC", "APPDATA", "PROGRAMDATA"):
        base = os.environ.get(env_var)
        if not base:
            continue
        if env_var == "USERPROFILE":
            dirs_to_scan.append(os.path.join(base, "Desktop"))
        elif env_var == "PUBLIC":
            dirs_to_scan.append(os.path.join(base, "Desktop"))
        elif env_var == "APPDATA":
            dirs_to_scan.append(os.path.join(base, r"Microsoft\Windows\Start Menu\Programs"))
        elif env_var == "PROGRAMDATA":
            dirs_to_scan.append(os.path.join(base, r"Microsoft\Windows\Start Menu\Programs"))

    lnk_files = []
    for d in dirs_to_scan:
        if os.path.isdir(d):
            for root, _dirs, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(".lnk"):
                        lnk_files.append(os.path.join(root, f))

    for lnk_path in lnk_files:
        try:
            sc = shell.CreateShortCut(lnk_path)
            target = sc.TargetPath
            if not target:
                continue
            exe_name = os.path.basename(target).lower()
            # 显示名 = 快捷方式文件名（去掉 .lnk）
            display_name = os.path.splitext(os.path.basename(lnk_path))[0]
            icon_path = sc.IconLocation
            icon_idx = 0
            if icon_path:
                parts = icon_path.rsplit(",", 1)
                if len(parts) == 2:
                    icon_path = parts[0].strip()
                    try:
                        icon_idx = int(parts[1].strip())
                    except ValueError:
                        icon_idx = 0

            entry = {
                "display_name": display_name,
                "icon_path": icon_path if icon_path and os.path.exists(icon_path) else target,
                "icon_index": icon_idx,
            }
            # 不覆盖已有的（优先桌面 > 开始菜单）
            if exe_name not in _shortcut_cache:
                _shortcut_cache[exe_name] = entry
        except Exception:
            continue

    return _shortcut_cache


def get_shortcut_info(exe_name):
    """根据 exe 名称获取快捷方式中的显示名和图标路径。"""
    shortcuts = _scan_shortcuts()
    return shortcuts.get(exe_name.lower())

_FALLBACK_COLORS = {
    "Chrome": "#4285F4", "Edge": "#0078D7", "Firefox": "#FF7139",
    "微信": "#07C160", "QQ": "#12B7F5", "钉钉": "#0089FF",
    "Slack": "#4A154B", "Telegram": "#0088CC", "飞书": "#3370FF",
    "VS Code": "#007ACC", "Python": "#3776AB", "终端": "#0C0C0C",
    "Spotify": "#1DB954", "Steam": "#1B2838", "UU远程": "#FF6600",
    "文件资源管理器": "#FFB900", "记事本": "#6B5B95",
}


def _extract_icon_iimagelist(exe_path, size=32):
    """Extract icon via IImageList for high quality."""
    sfi = SHFILEINFO()
    flags = SHGFI_SYSICONINDEX | SHGFI_ICON
    shell32.SHGetFileInfoW(exe_path, 0, ctypes.byref(sfi),
                           ctypes.sizeof(sfi), flags)

    if not sfi.iIcon:
        return None

    try:
        pml = ctypes.POINTER(ctypes.c_void_p)()
        hr = shell32.SHGetImageList(
            SHIL_EXTRALARGE, _IID_IImageList, ctypes.byref(pml))
        if hr != 0 or not pml:
            return None

        hicon = comctl32.ImageList_GetIcon(pml, sfi.iIcon, 0x0001)
        if not hicon:
            return None

        hdc = win32gui.GetDC(0)
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(win32ui.CreateDCFromHandle(hdc), size, size)

        dc_mem = win32ui.CreateDCFromHandle(win32gui.CreateCompatibleDC(hdc))
        dc_mem.SelectObject(hbmp)

        # 黑色背景填充（处理 alpha 通道）
        dc_mem.FillSolidRect(0, 0, size, size, 0x000000)

        win32gui.DrawIconEx(dc_mem.GetSafeHdc(), 0, 0, hicon,
                            size, size, 0, None, 0x0003)

        bits = hbmp.GetBitmapBits(True)
        if len(bits) < size * size * 4:
            return None

        # BGRA → RGBA，用 alpha 通道保留透明度
        raw = bits
        pixels = bytearray(size * size * 4)
        for i in range(size * size):
            idx = i * 4
            b, g, r = raw[idx], raw[idx + 1], raw[idx + 2]
            pixels[idx] = r
            pixels[idx + 1] = g
            pixels[idx + 2] = b
            # 如果像素不是纯黑（填充色），说明有内容
            if r or g or b:
                pixels[idx + 3] = 255
            else:
                pixels[idx + 3] = 0

        img = Image.frombuffer('RGBA', (size, size), bytes(pixels),
                               'raw', 'RGBA', 0, 1)

        dc_mem.DeleteDC()
        win32gui.ReleaseDC(0, hdc)
        win32gui.DestroyIcon(hicon)
        return img

    except Exception:
        return None


def _extract_icon_legacy(exe_path, size=28):
    """Fallback: extract icon via SHGetFileInfo + DrawIconEx."""
    sfi = SHFILEINFO()
    shell32.SHGetFileInfoW(exe_path, 0, ctypes.byref(sfi),
                           ctypes.sizeof(sfi), SHGFI_ICON)
    if not sfi.hIcon:
        return None

    try:
        hdc = win32gui.GetDC(0)
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(win32ui.CreateDCFromHandle(hdc), size, size)

        dc_mem = win32ui.CreateDCFromHandle(win32gui.CreateCompatibleDC(hdc))
        dc_mem.SelectObject(hbmp)

        win32gui.DrawIconEx(dc_mem.GetSafeHdc(), 0, 0, sfi.hIcon,
                            size, size, 0, None, 0x0003)

        bits = hbmp.GetBitmapBits(True)
        if len(bits) < size * size * 4:
            return None

        raw = bits
        pixels = bytearray(size * size * 4)
        for i in range(size * size):
            idx = i * 4
            pixels[idx] = raw[idx + 2]
            pixels[idx + 1] = raw[idx + 1]
            pixels[idx + 2] = raw[idx]
            pixels[idx + 3] = 255

        img = Image.frombuffer('RGBA', (size, size), bytes(pixels),
                               'raw', 'RGBA', 0, 1)

        dc_mem.DeleteDC()
        win32gui.ReleaseDC(0, hdc)
        return img

    except Exception:
        return None
    finally:
        win32gui.DestroyIcon(sfi.hIcon)


def _extract_icon(exe_path, size=28):
    """Extract icon: try IImageList first (high-res), fallback to legacy."""
    img = _extract_icon_iimagelist(exe_path, size)
    if img:
        return img
    return _extract_icon_legacy(exe_path, size)


def _find_exe_path(app_name):
    """Find exe path from running processes, including aliased names. Cached."""
    app_lower = app_name.lower()
    if app_lower in _exe_path_cache:
        cached_path = _exe_path_cache[app_lower]
        if cached_path and os.path.exists(cached_path):
            return cached_path
        del _exe_path_cache[app_lower]

    import psutil
    from storage import get_app_rules

    rules = get_app_rules()

    # 收集所有同类进程名
    aliases = {app_lower}
    for child, parent in rules.items():
        if parent == app_lower:
            aliases.add(child)

    result = None
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            if proc.info['name'] and proc.info['name'].lower() in aliases:
                result = proc.info['exe']
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    _exe_path_cache[app_lower] = result
    return result


def _make_fallback_icon(display_name, size=28):
    """Create a colored circle with first letter as fallback."""
    color = "#64748B"
    for key, c in _FALLBACK_COLORS.items():
        if key in display_name:
            color = c
            break

    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 2
    draw.ellipse([pad, pad, size - pad, size - pad], fill=color)

    letter = (display_name[0] if display_name else "?").upper()
    try:
        for font_name in ["msyh.ttc", "msyhbd.ttc", "arial.ttf", "segoeui.ttf"]:
            try:
                font = ImageFont.truetype(font_name, size // 2)
                break
            except (IOError, OSError):
                continue
        else:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), letter, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (size - tw) // 2
        y = (size - th) // 2 - 1
        draw.text((x, y), letter, fill="white", font=font)
    except Exception:
        pass

    return img


def get_icon(app_name, display_name="", size=28):
    """Get app icon as PIL Image. Cached. Prioritizes shortcut icons."""
    cache_key = f"{app_name}_{size}"
    if cache_key in _cache:
        return _cache[cache_key]

    # Try shortcut icon first
    sc_info = get_shortcut_info(app_name)
    if sc_info:
        icon_path = sc_info["icon_path"]
        if icon_path and os.path.exists(icon_path):
            img = _extract_icon(icon_path, size)
            if img:
                _cache[cache_key] = img
                return img

    # Try running process
    exe_path = _find_exe_path(app_name)
    if exe_path:
        img = _extract_icon(exe_path, size)
        if img:
            _cache[cache_key] = img
            return img

    # Try system path directly
    sys_paths = [
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), app_name),
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", app_name),
    ]
    for path in sys_paths:
        if os.path.exists(path):
            img = _extract_icon(path, size)
            if img:
                _cache[cache_key] = img
                return img

    # Fallback
    img = _make_fallback_icon(display_name or app_name, size)
    _cache[cache_key] = img
    return img
