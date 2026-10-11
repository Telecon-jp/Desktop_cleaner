# -*- coding: utf-8 -*-
"""
桌面整理工具 v1.0
功能：
  1. 一键整理桌面 —— 快捷方式(.lnk)分在最左侧，非快捷方式分在最右侧
  2. 一键去除桌面快捷方式上的箭头图标
  3. 一键去除桌面上应用图标上的蓝黄盾牌(UAC)
依赖：pywin32 (用于解析 .lnk 快捷方式目标)
运行：需要管理员权限（修改 HKLM 注册表时）
"""

import os
import sys
import ctypes
import winreg
import tkinter as tk
from tkinter import ttk, messagebox
from ctypes import wintypes
from threading import Thread

# 启用 DPI 感知，使程序使用物理像素坐标（与 Explorer 一致）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ============================================================
#  依赖检测
# ============================================================
try:
    import win32com.client
    HAS_WIN32COM = True
except ImportError:
    HAS_WIN32COM = False


# ============================================================
#  Windows API 常量 & 类型
# ============================================================
LVM_GETITEMCOUNT       = 0x1004
LVM_GETITEMPOSITION    = 0x1010      # 返回 POINT
LVM_SETITEMPOSITION32  = 0x1031      # 传入 POINT 指针
LVM_GETITEMTEXTW       = 0x1073
LVM_REDRAWITEMS        = 0x1015
LVM_UPDATE             = 0x1014

WM_KEYDOWN             = 0x0100
VK_F5                  = 0x74

PROCESS_VM_OPERATION   = 0x0008
PROCESS_VM_READ        = 0x0010
PROCESS_VM_WRITE       = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400

MEM_COMMIT             = 0x1000
MEM_RELEASE            = 0x8000
PAGE_READWRITE         = 0x04

kernel32 = ctypes.windll.kernel32
user32   = ctypes.windll.user32


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# 64 位 LVITEMW
class LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask",        wintypes.UINT),
        ("iItem",       ctypes.c_int),
        ("iSubItem",    ctypes.c_int),
        ("state",       wintypes.UINT),
        ("stateMask",   wintypes.UINT),
        ("pszText",     ctypes.c_void_p),   # 远程指针
        ("cchTextMax",  ctypes.c_int),
        ("iImage",      ctypes.c_int),
        ("lParam",      ctypes.c_longlong),
        ("iIndent",     ctypes.c_int),
        ("iGroupId",    ctypes.c_int),
        ("cColumns",    wintypes.UINT),
        ("puColumns",   ctypes.c_void_p),
        ("piColFmt",    ctypes.c_void_p),
        ("iGroup",      ctypes.c_int),
    ]


# ============================================================
#  桌面图标位置管理（跨进程）
# ============================================================
class DesktopIconManager:
    """通过 Windows API 读写桌面 SysListView32 图标位置"""

    def __init__(self, log_func=print):
        self.log = log_func
        self.hwnd = None
        self.pid = None
        self.process = None

    # ---------- 句柄 ----------
    def _find_listview(self):
        """依次在 Progman / WorkerW 下查找 SysListView32"""
        progman = user32.FindWindowW("Progman", "Program Manager")
        if not progman:
            return None
        # 通知 Progman，促使其子窗口架构就绪
        user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, None)

        def find_in(parent):
            shell_view = user32.FindWindowExW(parent, 0, "SHELLDLL_DefView", None)
            if shell_view:
                lv = user32.FindWindowExW(shell_view, 0, "SysListView32", "FolderView")
                if lv:
                    return lv
            return None

        lv = find_in(progman)
        if lv:
            return lv

        worker = user32.FindWindowExW(0, 0, "WorkerW", None)
        while worker:
            lv = find_in(worker)
            if lv:
                return lv
            worker = user32.FindWindowExW(0, worker, "WorkerW", None)
        return None

    def connect(self):
        self.hwnd = self._find_listview()
        if not self.hwnd:
            self.log("✗ 未找到桌面 SysListView32 句柄")
            return False
        self.pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(self.hwnd, ctypes.byref(self.pid))
        self.pid = self.pid.value
        access = (PROCESS_VM_OPERATION | PROCESS_VM_READ |
                  PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION)
        self.process = kernel32.OpenProcess(access, False, self.pid)
        if not self.process:
            self.log("✗ 无法打开 Explorer 进程")
            return False
        return True

    def close(self):
        if self.process:
            kernel32.CloseHandle(self.process)
            self.process = None

    # ---------- 远程内存辅助 ----------
    def _alloc(self, size):
        ptr = kernel32.VirtualAllocEx(self.process, None, size, MEM_COMMIT, PAGE_READWRITE)
        return ptr

    def _free(self, ptr):
        kernel32.VirtualFreeEx(self.process, ptr, 0, MEM_RELEASE)

    def _write(self, addr, data):
        written = ctypes.c_size_t(0)
        kernel32.WriteProcessMemory(self.process, addr, data, len(data), ctypes.byref(written))

    def _read(self, addr, size):
        buf = (ctypes.c_ubyte * size)()
        read = ctypes.c_size_t(0)
        kernel32.ReadProcessMemory(self.process, addr, buf, size, ctypes.byref(read))
        return bytes(buf[:read.value])

    # ---------- 图标操作 ----------
    def get_count(self):
        return user32.SendMessageW(self.hwnd, LVM_GETITEMCOUNT, 0, 0)

    def get_name(self, index):
        text_len = 260
        text_addr = self._alloc(text_len * 2)
        lvi_addr  = self._alloc(ctypes.sizeof(LVITEMW))
        lvi = LVITEMW()
        lvi.mask = 0x0002   # LVIF_TEXT
        lvi.iItem = index
        lvi.iSubItem = 0
        lvi.pszText = text_addr
        lvi.cchTextMax = text_len
        self._write(lvi_addr, bytes(lvi))
        user32.SendMessageW(self.hwnd, LVM_GETITEMTEXTW, index, lvi_addr)
        raw = self._read(text_addr, text_len * 2)
        name = raw.decode("utf-16-le", errors="ignore").rstrip("\x00")
        self._free(text_addr)
        self._free(lvi_addr)
        return name

    def get_position(self, index):
        pt_addr = self._alloc(ctypes.sizeof(POINT))
        user32.SendMessageW(self.hwnd, LVM_GETITEMPOSITION, index, pt_addr)
        raw = self._read(pt_addr, ctypes.sizeof(POINT))
        pt = POINT.from_buffer_copy(raw)
        self._free(pt_addr)
        return pt.x, pt.y

    def set_position(self, index, x, y):
        pt_addr = self._alloc(ctypes.sizeof(POINT))
        pt = POINT(x=x, y=y)
        self._write(pt_addr, bytes(pt))
        user32.SendMessageW(self.hwnd, LVM_SETITEMPOSITION32, index, pt_addr)
        self._free(pt_addr)

    def refresh(self):
        count = self.get_count()
        user32.SendMessageW(self.hwnd, LVM_REDRAWITEMS, 0, count - 1)
        user32.SendMessageW(self.hwnd, LVM_UPDATE, 0, 0)


# ============================================================
#  桌面文件分类
# ============================================================
DESKTOP_PATH = os.path.join(os.path.expanduser("~"), "Desktop")
PUBLIC_DESKTOP = os.path.join(os.environ.get("PUBLIC", "C:\\Users\\Public"), "Desktop")

APP_EXTS = {".exe", ".bat", ".cmd", ".msi", ".ps1", ".appref-ms", ".url"}
DOC_EXTS = {
    ".txt", ".doc", ".docx", ".pdf", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".rtf", ".odt", ".ods", ".odp", ".md",
}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico", ".webp", ".svg", ".tiff"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz"}

SYSTEM_ICONS = {"此电脑", "我的电脑", "计算机", "回收站", "网络", "控制面板",
                 "用户的文件", "This PC", "Recycle Bin", "Network"}


def parse_lnk_target(path):
    """解析 .lnk 目标路径"""
    if not HAS_WIN32COM:
        return None
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(path)
        return sc.TargetPath
    except Exception:
        return None


def is_shortcut(filename):
    """判断桌面项是否为快捷方式（.lnk）"""
    ext = os.path.splitext(filename)[1].lower()
    return ext == ".lnk"


def get_desktop_items():
    """获取桌面上的所有文件/文件夹名称"""
    items = set()
    for base in (DESKTOP_PATH, PUBLIC_DESKTOP):
        if os.path.isdir(base):
            for name in os.listdir(base):
                if name.lower() == "desktop.ini":
                    continue
                items.add(name)
    return list(items)


# ============================================================
#  注册表操作：去箭头 / 去盾牌
# ============================================================
SHELL_ICONS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons"
LNKFILE_KEY = r"lnkfile"

ICON_ARROW = "29"
ICON_SHIELD = "77"

# Windows 系统内置透明图标资源，所有 Windows 系统上都存在，不会丢失
TRANSPARENT_ICON = "%windir%\\System32\\shell32.dll,-50"


def set_shell_icon(icon_id, icon_value, log_func=print):
    """在 Shell Icons 注册表中设置指定图标 ID 的替换值"""
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, SHELL_ICONS_KEY, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)
        winreg.SetValueEx(key, icon_id, 0, winreg.REG_SZ, icon_value)
        winreg.CloseKey(key)
        return True
    except PermissionError:
        log_func("✗ 权限不足，请以管理员身份运行本程序")
        return False
    except Exception as e:
        log_func(f"✗ 注册表写入失败: {e}")
        return False


def delete_shell_icon(icon_id, log_func=print):
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SHELL_ICONS_KEY, 0,
                             winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)
        winreg.DeleteValue(key, icon_id)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return True
    except Exception as e:
        log_func(f"✗ 删除注册表值失败: {e}")
        return False


def restart_explorer(log_func=print):
    log_func("正在清理图标缓存...")
    # 删除图标缓存文件，确保新设置生效
    local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    iconcache = os.path.join(local_appdata, "IconCache.db")
    if os.path.exists(iconcache):
        try:
            os.remove(iconcache)
            log_func("✓ 已清理 IconCache.db")
        except Exception as e:
            log_func(f"  清理 IconCache.db 失败: {e}")
    explorer_cache_dir = os.path.join(local_appdata, "Microsoft", "Windows", "Explorer")
    if os.path.isdir(explorer_cache_dir):
        for f in os.listdir(explorer_cache_dir):
            if f.lower().startswith("iconcache") and f.lower().endswith(".db"):
                try:
                    os.remove(os.path.join(explorer_cache_dir, f))
                    log_func(f"✓ 已清理 {f}")
                except Exception:
                    pass
    log_func("正在重启资源管理器以应用更改...")
    os.system("taskkill /f /im explorer.exe >nul 2>&1")
    os.system("start explorer.exe")
    log_func("✓ 资源管理器已重启")

def remove_shortcut_arrow(log_func=print):
    """去除快捷方式小箭头"""
    log_func("【去箭头】开始处理...")
    log_func(f"  使用系统透明图标: {TRANSPARENT_ICON}")
    if set_shell_icon(ICON_ARROW, TRANSPARENT_ICON, log_func):
        log_func("✓ 已设置透明图标替换箭头")
        restart_explorer(log_func)
        log_func("✓ 快捷方式小箭头已去除")
    else:
        log_func("✗ 去箭头失败")

def remove_uac_shield(log_func=print):
    """去除 UAC 蓝黄盾牌"""
    log_func("【去盾牌】开始处理...")
    log_func(f"  使用系统透明图标: {TRANSPARENT_ICON}")
    if set_shell_icon(ICON_SHIELD, TRANSPARENT_ICON, log_func):
        log_func("✓ 已设置透明图标替换盾牌")
        restart_explorer(log_func)
        log_func("✓ UAC 盾牌图标已去除")
    else:
        log_func("✗ 去盾牌失败")


def restore_arrows(log_func=print):
    """恢复小箭头和盾牌"""
    log_func("【恢复】正在恢复默认图标...")
    delete_shell_icon(ICON_ARROW, log_func)
    delete_shell_icon(ICON_SHIELD, log_func)
    restart_explorer(log_func)
    log_func("✓ 已恢复默认快捷方式箭头和盾牌")


# ============================================================
#  桌面整理核心
# ============================================================
def organize_desktop(log_func=print):
    """一键整理桌面：快捷方式在最左，非快捷方式在最右"""
    log_func("【整理桌面】开始处理...")

    mgr = DesktopIconManager(log_func=log_func)
    if not mgr.connect():
        return

    count = mgr.get_count()
    log_func(f"桌面共有 {count} 个图标")

    if count == 0:
        log_func("桌面上没有图标可整理")
        mgr.close()
        return

    # 收集图标名称并分类：快捷方式 vs 非快捷方式
    # 构建桌面文件映射：显示名（无扩展名）→ 实际文件名（含扩展名）
    desktop_files = get_desktop_items()
    name_to_file = {}
    for fname in desktop_files:
        # 去掉扩展名得到 Explorer 中显示的名称
        display_name = os.path.splitext(fname)[0]
        name_to_file[display_name] = fname
    # 也保留原始文件名映射
    for fname in desktop_files:
        name_to_file[fname] = fname

    shortcut_indices = []
    other_indices = []

    for i in range(count):
        name = mgr.get_name(i)
        if not name:
            name = f"item_{i}"

        # 判断是否为快捷方式
        is_lnk = False
        if name in SYSTEM_ICONS:
            is_lnk = False
        else:
            # 先检查显示名是否对应一个 .lnk 或 .url 文件
            actual_file = name_to_file.get(name)
            if actual_file:
                ext = os.path.splitext(actual_file)[1].lower()
                is_lnk = (ext == ".lnk" or ext == ".url")
            else:
                # 不在桌面文件列表中，直接看名称扩展名
                ext = os.path.splitext(name)[1].lower()
                is_lnk = (ext == ".lnk" or ext == ".url")

        if is_lnk:
            shortcut_indices.append((i, name))
        else:
            other_indices.append((i, name))

    log_func(f"快捷方式: {len(shortcut_indices)} 个, 非快捷方式: {len(other_indices)} 个")

    # 获取桌面工作区域（排除任务栏），启用 DPI 感知后返回物理像素
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    work_area = RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0)  # SPI_GETWORKAREA
    work_w = work_area.right - work_area.left
    work_h = work_area.bottom - work_area.top
    work_left = work_area.left
    work_top = work_area.top

    log_func(f"桌面工作区: {work_w} x {work_h} (左={work_left}, 上={work_top}, 右={work_area.right}, 下={work_area.bottom})")

    # 高分辨率下图标间距更大
    icon_w, icon_h = 120, 135
    start_y = work_top + 10
    rows_per_col = max(1, (work_h - 20) // icon_h)

    # 快捷方式排列在最左侧（从工作区左边缘开始向右）
    left_x = work_left
    for idx, (i, name) in enumerate(shortcut_indices):
        col = idx // rows_per_col
        row = idx % rows_per_col
        x = left_x + col * icon_w
        y = start_y + row * icon_h
        mgr.set_position(i, x, y)
        log_func(f"  快捷方式 [{name}] -> ({x}, {y})")

    # 非快捷方式排列在最右侧（从工作区右边缘向左）
    right_x = work_area.right - icon_w
    for idx, (i, name) in enumerate(other_indices):
        col = idx // rows_per_col
        row = idx % rows_per_col
        x = right_x - col * icon_w
        y = start_y + row * icon_h
        mgr.set_position(i, x, y)
        log_func(f"  其他 [{name}] -> ({x}, {y})")

    mgr.refresh()
    mgr.close()
    log_func("✓ 桌面整理完成！快捷方式在最左，非快捷方式在最右")


# ============================================================
#  管理员权限
# ============================================================
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def relaunch_as_admin():
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{os.path.abspath(__file__)}"', None, 1)


# ============================================================
#  GUI 界面（深色主题）
# ============================================================
class DesktopCleanerApp:
    # 深色系配色
    BG          = "#1e1e2e"
    CARD_BG     = "#2a2a3c"
    CARD_HOVER  = "#333346"
    ACCENT      = "#7c3aed"
    ACCENT_HOVER= "#6d28d9"
    ACCENT2     = "#0ea5e9"
    TEXT_MAIN   = "#e2e8f0"
    TEXT_SUB    = "#94a3b8"
    DANGER      = "#ef4444"
    SUCCESS     = "#22c55e"
    LOG_BG      = "#16161f"
    BORDER      = "#3a3a4e"

    def __init__(self, root):
        self.root = root
        self._setup_window()
        self._setup_style()
        self._build_ui()

    def _setup_window(self):
        self.root.title("桌面整理工具  v1.0")
        self.root.geometry("640x620")
        self.root.minsize(580, 560)
        self.root.configure(bg=self.BG)
        # 居中显示
        self.root.update_idletasks()
        w, h = 640, 620
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background=self.BG)
        style.configure("Card.TFrame", background=self.CARD_BG)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT_MAIN, font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background=self.BG, foreground=self.TEXT_MAIN,
                        font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Sub.TLabel", background=self.BG, foreground=self.TEXT_SUB,
                        font=("Microsoft YaHei UI", 9))
        style.configure("CardTitle.TLabel", background=self.CARD_BG, foreground=self.TEXT_MAIN,
                        font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("CardDesc.TLabel", background=self.CARD_BG, foreground=self.TEXT_SUB,
                        font=("Microsoft YaHei UI", 9))

        style.configure("Log.TFrame", background=self.LOG_BG)
        style.configure("Log.TLabel", background=self.LOG_BG, foreground=self.SUCCESS,
                        font=("Consolas", 9))

    def _make_card(self, parent, title, desc, button_text, command, accent_color):
        """创建功能卡片"""
        card = tk.Frame(parent, bg=self.CARD_BG, highlightbackground=self.BORDER,
                        highlightthickness=1, bd=0)
        card.pack(fill="x", padx=24, pady=6)

        inner = tk.Frame(card, bg=self.CARD_BG)
        inner.pack(fill="x", padx=16, pady=12)

        # 左侧色条
        bar = tk.Frame(inner, bg=accent_color, width=4)
        bar.pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(inner, bg=self.CARD_BG)
        info.pack(side="left", fill="x", expand=True)

        tk.Label(info, text=title, bg=self.CARD_BG, fg=self.TEXT_MAIN,
                 font=("Microsoft YaHei UI", 13, "bold"), anchor="w").pack(fill="x")
        tk.Label(info, text=desc, bg=self.CARD_BG, fg=self.TEXT_SUB,
                 font=("Microsoft YaHei UI", 9), anchor="w", wraplength=380, justify="left").pack(fill="x", pady=(2, 0))

        btn = tk.Button(inner, text=button_text, command=command,
                        bg=accent_color, fg="white", activebackground=self.ACCENT_HOVER,
                        activeforeground="white", bd=0, relief="flat",
                        font=("Microsoft YaHei UI", 10, "bold"),
                        cursor="hand2", padx=18, pady=8)
        btn.pack(side="right", padx=(12, 0))

        # 悬停效果
        def on_enter(e):
            card.configure(highlightbackground=accent_color)
        def on_leave(e):
            card.configure(highlightbackground=self.BORDER)
        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)
        return card

    def _build_ui(self):
        # 顶部标题区
        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill="x", padx=24, pady=(20, 5))

        tk.Label(header, text="桌面整理工具", bg=self.BG, fg=self.TEXT_MAIN,
                 font=("Microsoft YaHei UI", 22, "bold")).pack(side="left")

        # 管理员状态
        admin_text = "管理员" if is_admin() else "非管理员"
        admin_color = self.SUCCESS if is_admin() else self.DANGER
        tk.Label(header, text=f"● {admin_text}", bg=self.BG, fg=admin_color,
                 font=("Microsoft YaHei UI", 9)).pack(side="right", pady=(8, 0))

        tk.Label(self.root, text="一键整理桌面 · 去除快捷方式箭头 · 去除UAC盾牌",
                 bg=self.BG, fg=self.TEXT_SUB,
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=24)

        # 分割线
        tk.Frame(self.root, bg=self.BORDER, height=1).pack(fill="x", padx=24, pady=(10, 6))

        # 功能卡片区
        cards_frame = tk.Frame(self.root, bg=self.BG)
        cards_frame.pack(fill="x")

        self._make_card(
            cards_frame,
            "一键整理桌面",
            "将桌面图标按类型分区：所有快捷方式(.lnk)排列在桌面最左侧，非快捷方式（文件夹、文档、图片等）排列在桌面最右侧。",
            "开始整理",
            self.on_organize,
            self.ACCENT2
        )

        self._make_card(
            cards_frame,
            "去除快捷方式箭头",
            "去除桌面及系统中 .lnk 快捷方式图标上的小箭头，需要管理员权限，完成后自动重启资源管理器。",
            "去除箭头",
            self.on_remove_arrow,
            self.ACCENT
        )

        self._make_card(
            cards_frame,
            "去除UAC盾牌图标",
            "去除应用图标右下角的蓝黄盾牌（UAC 提权标记），需要管理员权限，完成后自动重启资源管理器。",
            "去除盾牌",
            self.on_remove_shield,
            self.DANGER
        )

        # 底部恢复按钮
        bottom = tk.Frame(self.root, bg=self.BG)
        bottom.pack(fill="x", padx=24, pady=(8, 4))
        tk.Button(bottom, text="恢复默认（箭头+盾牌）", command=self.on_restore,
                  bg=self.CARD_BG, fg=self.TEXT_SUB, activebackground=self.CARD_HOVER,
                  activeforeground=self.TEXT_MAIN, bd=0, relief="flat",
                  font=("Microsoft YaHei UI", 9),
                  cursor="hand2", padx=12, pady=4).pack(side="left")

        if not HAS_WIN32COM:
            tk.Label(bottom, text="⚠ 未安装 pywin32，快捷方式目标解析将受限",
                     bg=self.BG, fg="#f59e0b",
                     font=("Microsoft YaHei UI", 8)).pack(side="left", padx=10)

        # 日志区
        log_header = tk.Frame(self.root, bg=self.BG)
        log_header.pack(fill="x", padx=24, pady=(8, 2))
        tk.Label(log_header, text="运行日志", bg=self.BG, fg=self.TEXT_SUB,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")

        log_frame = tk.Frame(self.root, bg=self.LOG_BG, highlightbackground=self.BORDER,
                             highlightthickness=1)
        log_frame.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        self.log_text = tk.Text(log_frame, bg=self.LOG_BG, fg=self.TEXT_MAIN,
                                font=("Consolas", 9), bd=0, relief="flat",
                                wrap="word", state="disabled")
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

        self.log("欢迎使用桌面整理工具")
        self.log(f"管理员权限: {'是' if is_admin() else '否（去箭头/盾牌功能将不可用）'}")
        if not HAS_WIN32COM:
            self.log("提示: 安装 pywin32 可提升分类准确度  →  pip install pywin32")

    # ---------- 日志 ----------
    def log(self, msg):
        def append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, append)

    # ---------- 按钮回调 ----------
    def _run_in_thread(self, func):
        def wrapper():
            Thread(target=func, daemon=True).start()
        return wrapper

    def on_organize(self):
        self.log("=" * 50)
        self.log("开始整理桌面...")
        Thread(target=organize_desktop, args=(self.log,), daemon=True).start()

    def on_remove_arrow(self):
        if not is_admin():
            self._need_admin()
            return
        self.log("=" * 50)
        self.log("开始去除快捷方式箭头...")
        Thread(target=remove_shortcut_arrow, args=(self.log,), daemon=True).start()

    def on_remove_shield(self):
        if not is_admin():
            self._need_admin()
            return
        self.log("=" * 50)
        self.log("开始去除UAC盾牌...")
        Thread(target=remove_uac_shield, args=(self.log,), daemon=True).start()

    def on_restore(self):
        if not is_admin():
            self._need_admin()
            return
        self.log("=" * 50)
        self.log("开始恢复默认图标...")
        Thread(target=restore_arrows, args=(self.log,), daemon=True).start()

    def _need_admin(self):
        result = messagebox.askyesno(
            "需要管理员权限",
            "此功能需要管理员权限才能修改系统注册表。\n\n是否以管理员身份重新启动程序？\n（当前整理记录会丢失）"
        )
        if result:
            relaunch_as_admin()
            self.root.destroy()


# ============================================================
#  入口
# ============================================================
def main():
    root = tk.Tk()
    app = DesktopCleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
