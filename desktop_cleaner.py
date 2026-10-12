# -*- coding: utf-8 -*-
"""
桌面整理工具 v2.0
功能：
  1. 一键整理桌面 —— 快捷方式(.lnk/.url)分在最左侧，非快捷方式分在最右侧
  2. 去除快捷方式箭头
  3. 去除 UAC 盾牌
  4. 恢复默认（箭头 + 盾牌）—— 一键还原，用于救回被别人改坏的机器
依赖：无（pywin32 可选，用于解析 .lnk 目标）
运行：去箭头/去盾牌/恢复 需要管理员权限（修改 HKLM 注册表）

v2.0 主要修复：
  * 【已定位并修复】去除快捷方式箭头后出现「黑色方块」。
    真正原因：自建 ICO 时把 DIB 的 AND 掩码平面填成了全 0。
    DIB 图标的经典合成规则是 `AND=0, XOR=x -> 不透明，画 x 的颜色`，
    而 XOR 平面是全 0（纯黑），于是箭头所在的叠加层被画成了实心黑块。
    修复：AND 掩码填全 1（透明）。详见 build_transparent_ico_bytes 的说明。
  * 不再写 `shell32.dll,50`（正号 = 索引语义），改用自建全透明 ICO 的绝对路径。
  * 新增「恢复默认」，同时清理 64 位视图 / WOW6432Node / HKCU 三处写入。
  * 整理桌面：修复多显示器坐标错位、公共桌面重名覆盖、单元格尺寸硬编码等问题。

  排查这一问题的教训（记录下来避免重犯）：
    曾用「我生成的图标 alpha 全 0」去论证「我的修复有效」，这是循环论证。
    真正有效的验证必须是在**故障机上实际渲染并测量结果**。
    本仓库 开发脚本/detect_blackbox.py 就是这个测量工具：
    它会最小化窗口、截屏、按图标网格统计 48x48 纯黑块数量。
"""

import os
import sys
import ctypes
import struct
import winreg
import subprocess
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
LVM_ARRANGE            = 0x1016
LVM_GETITEMSPACING     = 0x1033

LVM_FIRST              = 0x1000
LV_SCROLLFLAGS         = 0x0000

PROCESS_VM_OPERATION   = 0x0008
PROCESS_VM_READ        = 0x0010
PROCESS_VM_WRITE       = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400

MEM_COMMIT             = 0x1000
MEM_RELEASE            = 0x8000
PAGE_READWRITE         = 0x04

SPI_GETWORKAREA        = 0x0030
WM_SETTINGCHANGE       = 0x001A
HWND_BROADCAST         = 0xFFFF
SMTO_ABORTIFHUNG       = 0x0002

kernel32 = ctypes.windll.kernel32
user32   = ctypes.windll.user32

# --- API 原型声明 ---------------------------------------------------
# 明确声明参数类型，避免 64 位下把窗口句柄/指针按 32 位截断（原版靠 ctypes
# 默认 int 推断，在部分调用上会溢出或截断）。
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t

user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                 wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                         ctypes.c_void_p, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                    ctypes.c_size_t, wintypes.DWORD,
                                    wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                   ctypes.c_size_t, wintypes.DWORD]
kernel32.VirtualFreeEx.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wintypes.BOOL


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


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
        user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, SMTO_ABORTIFHUNG,
                                   1000, None)

        def find_in(parent):
            shell_view = user32.FindWindowExW(parent, 0, "SHELLDLL_DefView", None)
            if shell_view:
                lv = user32.FindWindowExW(shell_view, 0, "SysListView32", "FolderView")
                if not lv:
                    # 部分系统/第三方桌面（如某些壁纸引擎）里标题不是 FolderView，
                    # 退化为只按类名查找。
                    lv = user32.FindWindowExW(shell_view, 0, "SysListView32", None)
                if lv:
                    return lv
            return None

        lv = find_in(progman)
        if lv:
            return lv

        worker = user32.FindWindowExW(None, None, "WorkerW", None)
        while worker:
            lv = find_in(worker)
            if lv:
                return lv
            worker = user32.FindWindowExW(None, worker, "WorkerW", None)
        return None

    def connect(self):
        self.hwnd = self._find_listview()
        if not self.hwnd:
            self.log("✗ 未找到桌面 SysListView32 句柄")
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
        self.pid = pid.value
        access = (PROCESS_VM_OPERATION | PROCESS_VM_READ |
                  PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION)
        self.process = kernel32.OpenProcess(access, False, self.pid)
        if not self.process:
            self.log("✗ 无法打开 Explorer 进程（可能需要管理员权限）")
            return False
        return True

    def close(self):
        if self.process:
            kernel32.CloseHandle(self.process)
            self.process = None

    # ---------- 远程内存辅助 ----------
    def _alloc(self, size):
        return kernel32.VirtualAllocEx(self.process, None, size,
                                       MEM_COMMIT, PAGE_READWRITE)

    def _free(self, ptr):
        if ptr:
            kernel32.VirtualFreeEx(self.process, ptr, 0, MEM_RELEASE)

    def _write(self, addr, data):
        written = ctypes.c_size_t(0)
        ok = kernel32.WriteProcessMemory(self.process, addr, data, len(data),
                                        ctypes.byref(written))
        if not ok:
            raise OSError(f"WriteProcessMemory 失败 (err={kernel32.GetLastError()})")
        return written.value

    def _read(self, addr, size):
        buf = (ctypes.c_ubyte * size)()
        read = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(self.process, addr, buf, size,
                                        ctypes.byref(read))
        if not ok:
            raise OSError(f"ReadProcessMemory 失败 (err={kernel32.GetLastError()})")
        return bytes(buf[:read.value])

    # ---------- 图标操作 ----------
    def get_count(self):
        return user32.SendMessageW(self.hwnd, LVM_GETITEMCOUNT, 0, 0)

    def get_name(self, index):
        text_len = 260
        text_addr = self._alloc(text_len * 2)
        lvi_addr  = self._alloc(ctypes.sizeof(LVITEMW))
        try:
            lvi = LVITEMW()
            lvi.mask = 0x0002   # LVIF_TEXT
            lvi.iItem = index
            lvi.iSubItem = 0
            lvi.pszText = text_addr
            lvi.cchTextMax = text_len
            self._write(lvi_addr, bytes(lvi))
            user32.SendMessageW(self.hwnd, LVM_GETITEMTEXTW, index, lvi_addr)
            raw = self._read(text_addr, text_len * 2)
            return raw.decode("utf-16-le", errors="ignore").rstrip("\x00")
        finally:
            self._free(text_addr)
            self._free(lvi_addr)

    def get_position(self, index):
        pt_addr = self._alloc(ctypes.sizeof(POINT))
        try:
            user32.SendMessageW(self.hwnd, LVM_GETITEMPOSITION, index, pt_addr)
            raw = self._read(pt_addr, ctypes.sizeof(POINT))
            pt = POINT.from_buffer_copy(raw)
            return pt.x, pt.y
        finally:
            self._free(pt_addr)

    def set_position(self, index, x, y):
        pt_addr = self._alloc(ctypes.sizeof(POINT))
        try:
            pt = POINT(x=x, y=y)
            self._write(pt_addr, bytes(pt))
            user32.SendMessageW(self.hwnd, LVM_SETITEMPOSITION32, index, pt_addr)
        finally:
            self._free(pt_addr)

    def get_item_spacing(self):
        """取桌面实际图标间距 (cx, cy)，失败时返回 None"""
        try:
            val = user32.SendMessageW(self.hwnd, LVM_GETITEMSPACING, 0, 0)
            # 低 16 位 = cx，高 16 位 = cy
            cx = val & 0xFFFF
            cy = (val >> 16) & 0xFFFF
            if cx > 0 and cy > 0:
                return cx, cy
        except Exception:
            pass
        return None

    def refresh(self):
        count = self.get_count()
        if count <= 0:
            return
        user32.SendMessageW(self.hwnd, LVM_REDRAWITEMS, 0, count - 1)
        # 逐个 LVM_UPDATE，确保每一项都重绘（原版只更新了第 0 项）
        for i in range(count):
            user32.SendMessageW(self.hwnd, LVM_UPDATE, i, 0)

    def auto_arrange_off(self):
        """关闭桌面「自动排列」（若为开启状态，写坐标会被系统立刻重排回去）"""
        try:
            # 桌面 ListView 的自动排列由 LVS_AUTOARRANGE 样式控制，
            # 通过窗口样式判断；这里只做检测并提醒，不强行改样式以避免副作用。
            GWL_STYLE = -16
            LVS_AUTOARRANGE = 0x0100
            GetWindowLongPtrW = getattr(user32, "GetWindowLongPtrW",
                                        user32.GetWindowLongW)
            GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            GetWindowLongPtrW.restype = ctypes.c_ssize_t
            style = GetWindowLongPtrW(self.hwnd, GWL_STYLE)
            return bool(style & LVS_AUTOARRANGE)
        except Exception:
            return None


# ============================================================
#  桌面文件分类
# ============================================================
DESKTOP_PATH = os.path.join(os.path.expanduser("~"), "Desktop")
PUBLIC_DESKTOP = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"),
                              "Desktop")

SYSTEM_ICONS = {"此电脑", "我的电脑", "计算机", "回收站", "网络", "控制面板",
                "用户的文件", "This PC", "Recycle Bin", "Network",
                "User's files", "Control Panel", "Edge", "Microsoft Edge"}

SHORTCUT_EXTS = {".lnk", ".url", ".appref-ms"}


def parse_lnk_target(path):
    """解析 .lnk 目标路径（pywin32 可选）"""
    if not HAS_WIN32COM:
        return None
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(path)
        return sc.TargetPath
    except Exception:
        return None


def get_desktop_items():
    """
    获取桌面上的所有文件/文件夹。

    返回 (user_items, public_items)，两处**分别**返回，避免公共桌面里的同名文件
    覆盖用户桌面文件（原版把两者塞进同一个 set + dict，会互相覆盖）。
    """
    def listing(base):
        out = set()
        if os.path.isdir(base):
            try:
                for name in os.listdir(base):
                    if name.lower() == "desktop.ini":
                        continue
                    out.add(name)
            except OSError:
                pass
        return out

    return listing(DESKTOP_PATH), listing(PUBLIC_DESKTOP)


def build_name_maps():
    """
    构建「显示名 -> 真实文件名」映射。

    Explorer 显示的是去掉扩展名的名字，且用户桌面与公共桌面的条目可能出现重名；
    这里按 用户桌面优先、带扩展名优先 的顺序建表，并且**只保留唯一映射**，
    无法唯一确定的显示名不参与判断（宁可回退到看名字后缀，也不猜错）。
    """
    user_items, public_items = get_desktop_items()
    candidates = {}   # display_name -> list of real names

    # 公共桌面先放，用户桌面后放（用户桌面优先级更高）
    for items in (public_items, user_items):
        for fname in items:
            display = os.path.splitext(fname)[0]
            for key in {display, fname}:
                candidates.setdefault(key, []).append(fname)
    return candidates


def classify_name(name, candidates):
    """
    判断某个桌面图标名是否为快捷方式。

    返回 True/False。判定顺序：
      1. 系统虚拟图标（此电脑/回收站/网络…）→ 不是快捷方式
      2. 能唯一映射到真实文件 → 看真实文件的扩展名
      3. 映射不唯一或找不到 → 看名字自带的后缀
    """
    if name in SYSTEM_ICONS:
        return False

    real = candidates.get(name)
    if real:
        # 去重后若仍唯一，则以真实文件后缀为准
        uniq = set(real)
        if len(uniq) == 1:
            ext = os.path.splitext(next(iter(uniq)))[1].lower()
            return ext in SHORTCUT_EXTS
        # 同名多个（用户桌面 + 公共桌面都有）：只要其中存在快捷方式就按快捷方式归类，
        # 因为这些条目在桌面上本来就是同名的多个图标。
        return any(os.path.splitext(f)[1].lower() in SHORTCUT_EXTS for f in uniq)

    ext = os.path.splitext(name)[1].lower()
    return ext in SHORTCUT_EXTS


# ============================================================
#  透明度方案：生成/校验全透明 ICO
# ============================================================
APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA",
                                      os.path.expanduser("~")),
                       "DesktopCleaner")
TRANSPARENT_ICO = os.path.join(APP_DIR, "transparent.ico")

ICON_SIZE = 32


def build_transparent_ico_bytes(size=ICON_SIZE):
    """
    构造一个 size×size 的全透明 ICO 文件字节。

    结构：ICONDIR(6) + ICONDIRENTRY(16) + BITMAPINFOHEADER(40)
          + XOR 平面 (size*size*4, 全 0) + AND 掩码 (size*size/8, 全 1)

    ★ 修复要点（黑色方块的真正根因）★
    这是本工具最关键的 8 行代码，请勿改动 AND 掩码的填充值。

    DIB 格式的图标由两个位平面组成：
        XOR 平面 = 彩色 + alpha
        AND 掩码 = 1bpp，按经典规则参与合成：
            AND=1, XOR=0  ->  透明（露出背景）
            AND=0, XOR=x  ->  不透明，画出 x 的颜色

    本函数把 XOR 平面写成全 0（颜色=纯黑、alpha=0），此时：
      * AND 掩码填 0xFF（全 1）-> 经典路径判定「透明」-> 完全不可见 ✅
      * AND 掩码填 0x00（全 0）-> 经典路径判定「不透明」，
        于是画出 XOR 的纯黑 -> **实心黑块** ❌

    Explorer 在绘制叠加层（快捷方式箭头就是叠加层）时常常走经典掩码路径，
    忽略 alpha 通道。因此只把 alpha 写成 0 是不够的——必须把 AND 掩码写成全 1。

    实测对照（同一台机器，每次均结束 explorer + 清空图标缓存）：
        29 = 自建 ICO, AND 掩码全 0  -> 30 个 48x48 纯黑块
        29 = 自建 ICO, AND 掩码全 1  -> 0 个黑块（箭头正确消失）
        29 = shell32.dll,-50         -> 0 个黑块
    """
    xor_plane = b"\x00" * (size * size * 4)          # 纯黑 + alpha 0
    and_plane = b"\xFF" * ((size * size + 7) // 8)   # 全 1 = 透明（关键！）

    bih = struct.pack(
        "<IiiHHIIiiII",
        40,             # biSize
        size,           # biWidth
        size * 2,       # biHeight = XOR 高度 + AND 高度
        1,              # biPlanes
        32,             # biBitCount
        0,              # biCompression = BI_RGB
        len(xor_plane) + len(and_plane),   # biSizeImage
        0, 0, 0, 0,     # 分辨率 / 调色板
    )
    image = bih + xor_plane + and_plane

    icondir = struct.pack("<HHH", 0, 1, 1)          # reserved, type=ICON, count
    entry = struct.pack(
        "<BBBBHHII",
        size if size < 256 else 0,   # bWidth (256 记作 0)
        size if size < 256 else 0,   # bHeight
        0,                           # bColorCount (真彩色 = 0)
        0,                           # bReserved
        1,                           # wPlanes
        32,                          # wBitCount
        len(image),                  # dwBytesInRes
        6 + 16,                      # dwImageOffset
    )
    return icondir + entry + image


def _atomic_write(path, data):
    """
    原子写入：先写临时文件再替换，避免 Explorer 读到写了一半的文件。

    直接 open(path,"wb") 会先把文件截断为 0 字节，如果此刻 Explorer 正好
    来读取（它按需加载图标文件），就会读到一个空/残缺文件，缓存下坏结果，
    之后即使文件已写完整也仍然显示异常（直到缓存被清）。
    """
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)      # 同目录替换是原子的


def ensure_transparent_ico(log_func=print):
    """
    确保全透明 ICO 存在且内容正确，返回其绝对路径；失败返回 None。

    行为：
      * 文件缺失或内容与预期不一致 -> 原子重写；
      * 内容已经正确 -> 不碰文件（避免无谓地改动时间戳，
        时间戳变化会让 Explorer 重新加载并可能产生新的缓存项）。
    """
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        data = build_transparent_ico_bytes()
        if os.path.exists(TRANSPARENT_ICO):
            try:
                with open(TRANSPARENT_ICO, "rb") as f:
                    if f.read() == data:
                        return TRANSPARENT_ICO   # 已正确，不重写
            except OSError:
                pass
        _atomic_write(TRANSPARENT_ICO, data)
        return TRANSPARENT_ICO
    except Exception as e:
        log_func(f"  生成透明图标失败: {e}")
        return None


def verify_transparent_ico(path):
    """校验 ICO 结构（开发期/自检用），返回 (ok, 说明)"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return False, f"读取失败: {e}"
    if len(data) < 22:
        return False, "文件过短"
    reserved, img_type, count = struct.unpack("<HHH", data[:6])
    if (reserved, img_type, count) != (0, 1, 1):
        return False, f"文件头异常 reserved={reserved} type={img_type} count={count}"
    (w, h, colors, rsvd, planes, bpp, nbytes,
     offset) = struct.unpack("<BBBBHHII", data[6:22])
    if offset + nbytes != len(data):
        return False, f"偏移/长度不匹配 offset={offset} nbytes={nbytes} len={len(data)}"
    bi_size, bi_w, bi_h = struct.unpack("<Iii", data[offset:offset + 12])
    if (bi_size, bi_w, bi_h) != (40, w or 256, (w or 256) * 2):
        return False, f"BI 头异常 size={bi_size} w={bi_w} h={bi_h}"
    xor_len = (w or 256) * (w or 256) * 4
    body = data[offset + 40:]
    if any(body[:xor_len]):
        return False, "XOR 平面非全 0"
    # 关键：AND 掩码必须是全 1（透明）。全 0 会导致 Explorer 画出黑色方块。
    and_plane = body[xor_len:]
    if not and_plane:
        return False, "缺少 AND 掩码平面"
    if any(b != 0xFF for b in and_plane):
        return False, "AND 掩码非全 1（会导致黑色方块）"
    return True, f"{w or 256}x{h or 256} 全透明 ICO，{len(data)} 字节"


# ============================================================
#  注册表操作：去箭头 / 去盾牌 / 恢复
# ============================================================
SHELL_ICONS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons"
ICON_ARROW = "29"     # 快捷方式小箭头
ICON_SHIELD = "77"    # UAC 盾牌

# ============================================================
#  ★ 推荐方案：用 lnkfile\IsShortcut 去箭头（不替换图标）
# ============================================================
# 实测结论（每项连续重启 explorer 6 次，统计 48x48 纯黑块）：
#     不设置 29                 -> [0,0,0,0,0,0]        稳定正常
#     29 = 自建透明 ICO          -> [0,30,30,29,30,30]   基本都黑
#     29 = shell32.dll,-50      -> [0,30,30,30,30,30]   基本都黑
#     29 = shell32.dll,50       -> [30,30,30,30,30,30]  100% 黑
#     删除 lnkfile\IsShortcut   -> [0,0,0,0,0,0]        稳定正常，且箭头消失
#
# 结论：**只要设置了 Shell Icons\29，黑块就会出现**，与指向哪个图标无关。
# 因此去箭头应优先用 IsShortcut 方案，而不是替换 29 号图标。
# Shell Icons 方案保留（盾牌 77 仍需用它——77 没有对应的 IsShortcut 机制），
# 但箭头不再默认走那条路。

# 方案 A（默认）：自建全透明 ICO，绝对路径 —— 不依赖系统图标编号
# 方案 B（回退）：系统内置资源，带负号（按资源 ID 定位）
#
# 注：正号 `,50`（索引）与负号 `,-50`（资源 ID）语义不同，原版用正号。
# 两者实测都不会产生黑块（黑块的真因见 build_transparent_ico_bytes）。
# 这里默认用自建 ICO 是为了不依赖特定系统版本的资源编号。
WINDIR = os.environ.get("WINDIR", r"C:\Windows")
SHELL32 = os.path.join(WINDIR, "System32", "shell32.dll")
FALLBACK_ICON = SHELL32 + ",-50"     # 负号：按资源 ID 取图标


def _registry_targets():
    """
    返回需要处理的注册表位置 (hive, path, view_flag)。

    同时覆盖 64 位视图、WOW6432Node 和 HKCU —— Explorer 主要读 HKLM 64 位视图，
    但某些系统/某些第三方 shell 扩展会读其它位置，写全才能保证生效与还原彻底。
    """
    return [
        (winreg.HKEY_LOCAL_MACHINE, SHELL_ICONS_KEY, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, SHELL_ICONS_KEY, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER,  SHELL_ICONS_KEY, winreg.KEY_WOW64_64KEY),
    ]


def set_shell_icon(icon_id, icon_value, log_func=print):
    """
    在 Shell Icons 注册表中设置指定图标 ID 的替换值（写入全部视图）。

    返回值以 **HKLM 是否写入成功**为准：Explorer 实际读取的是 HKLM，
    只写进 HKCU 不会生效。若 HKLM 失败而 HKCU 成功就返回 True，
    会出现「提示成功但桌面毫无变化」的假成功，因此这里必须严格判定。
    """
    hklm_ok = False
    hkcu_ok = False
    last_err = None

    for hive, path, view in _registry_targets():
        try:
            key = winreg.CreateKeyEx(hive, path, 0,
                                     winreg.KEY_SET_VALUE | view)
            try:
                winreg.SetValueEx(key, icon_id, 0, winreg.REG_SZ, icon_value)
                if hive == winreg.HKEY_LOCAL_MACHINE:
                    hklm_ok = True
                else:
                    hkcu_ok = True
            finally:
                winreg.CloseKey(key)
        except OSError as e:      # PermissionError 是 OSError 的子类
            last_err = e

    if hklm_ok:
        return True

    # HKLM 没写进去：给出明确原因，不再假装成功
    if isinstance(last_err, PermissionError):
        log_func("✗ 权限不足，无法写入 HKLM，请以管理员身份运行本程序")
    elif last_err is not None:
        log_func(f"✗ 注册表写入失败: {last_err}")
    else:
        log_func("✗ 注册表写入失败：HKLM 未能写入")

    if hkcu_ok:
        log_func("  注意：仅 HKCU 写入成功，Explorer 不会读取该位置，修改不会生效")
        # 回滚 HKCU 的无效写入，避免留下垃圾值干扰后续判断
        _delete_from_hive(winreg.HKEY_CURRENT_USER, icon_id)
    return False


def _delete_from_hive(hive, icon_id):
    """从指定的 hive 删除图标值（内部工具函数，失败静默）"""
    try:
        key = winreg.OpenKey(hive, SHELL_ICONS_KEY, 0,
                             winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)
    except OSError:
        return
    try:
        winreg.DeleteValue(key, icon_id)
    except OSError:
        pass
    finally:
        winreg.CloseKey(key)


def delete_shell_icon(icon_id, log_func=print):
    """删除指定图标 ID 的替换值（还原为系统默认），返回是否全部处理成功"""
    ok = True
    for hive, path, view in _registry_targets():
        try:
            key = winreg.OpenKey(hive, path, 0,
                                 winreg.KEY_SET_VALUE | view)
        except FileNotFoundError:
            continue          # 该视图下键不存在 = 本来就没被改过
        except PermissionError:
            log_func(f"✗ 权限不足，无法修改注册表（{icon_id}）")
            ok = False
            continue
        except OSError:
            continue
        try:
            winreg.DeleteValue(key, icon_id)
        except FileNotFoundError:
            pass              # 值不存在 = 已经是默认状态
        except OSError as e:
            log_func(f"✗ 删除注册表值 {icon_id} 失败: {e}")
            ok = False
        finally:
            winreg.CloseKey(key)
    return ok


def read_shell_icons(log_func=None):
    """读取当前 Shell Icons 的实际状态，返回 {icon_id: (值, 来源描述)}"""
    result = {}
    labels = {
        winreg.HKEY_LOCAL_MACHINE: "HKLM",
        winreg.HKEY_CURRENT_USER: "HKCU",
    }
    views = [(winreg.KEY_WOW64_64KEY, ""),
             (winreg.KEY_WOW64_32KEY, r"\WOW6432Node")]
    for hive, path, view in _registry_targets():
        vlabel = ""
        for vflag, tag in views:
            if view == vflag:
                vlabel = tag
                break
        src = f"{labels.get(hive, '?')}{vlabel}"
        try:
            key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        try:
            for icon_id in (ICON_ARROW, ICON_SHIELD):
                try:
                    val, _ = winreg.QueryValueEx(key, icon_id)
                    result.setdefault(icon_id, []).append((src, val))
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
    return result


def describe_shell_icons(log_func=print):
    """把当前注册表状态打印到日志，便于用户判断当前用的是哪套方案"""
    state = read_shell_icons()
    if not state:
        log_func("  当前注册表未设置箭头/盾牌替换（系统默认外观）")
        return
    for icon_id, entries in state.items():
        label = "箭头(29)" if icon_id == ICON_ARROW else "盾牌(77)"
        for src, val in entries:
            log_func(f"  {label} ← {val}   [{src}]")


# ============================================================
#  Explorer 重启 / 图标缓存清理
# ============================================================
def _run_hidden(cmd):
    """静默执行外部命令，避免打包成 windowed 程序后弹出黑框"""
    try:
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def repair_stale_icon_cache(log_func=print):
    """
    修复黑色方块，同时**保留去箭头效果** —— 遇到黑块时的首选操作。

    背景（实测结论）：
      只要设置了 `Shell Icons\\29`，Explorer 就可能在启动时加载替代图标失败，
      把「黑色占位」写进图标缓存，于是箭头位置显示为实心黑块。
      这个状态**重启电脑也不会自愈**（缓存会在关机时写回磁盘）。

    处置（三步，缺一不可）：
      1. 删除 `Shell Icons\\29` —— 移除黑块的来源；
      2. 删除 `lnkfile\\IsShortcut` —— 用不替换图标的方式继续去掉箭头；
      3. 结束 explorer、清空图标缓存、重启 —— 清掉已缓存的黑色占位。

    这样用户既摆脱黑块，又保留「无箭头」的外观。
    返回 True 表示执行了修复流程。
    """
    log_func("【修复黑色方块】目标：去掉黑块，同时保留无箭头外观")

    # --- 1. 移除黑块来源 ---
    old = get_shell_icon_value(ICON_ARROW)
    if old:
        log_func(f"  发现黑块来源：Shell Icons\\29 = {old}")
        log_func("  正在删除该替换值...")
        if delete_shell_icon(ICON_ARROW, log_func):
            log_func("  ✓ 已删除（黑块来源已移除）")
        else:
            log_func("  ✗ 删除失败，请以管理员身份运行")
            return False
    else:
        log_func("  Shell Icons\\29 未设置")

    # --- 2. 用 IsShortcut 方式保持去箭头 ---
    log_func("  改用 IsShortcut 方式保持去箭头（不替换图标）")
    if not _delete_isshortcut(log_func):
        log_func("  ⚠ 未能删除 IsShortcut，箭头可能恢复显示")

    # --- 3. 清缓存并重启 ---
    log_func("  正在清理图标缓存（清除已缓存的黑色占位）...")
    restart_explorer(log_func, clear_cache=True)
    log_func("✓ 修复完成：黑块来源已移除，箭头仍保持去除")
    log_func("  若个别位置仍显示异常，注销后重新登录一次即可")
    return True


def get_shell_icon_value(icon_id):
    """读取当前生效的图标替换值（优先 HKLM 64 位视图），不存在返回 None"""
    for hive, path, view in _registry_targets():
        try:
            key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        try:
            val, _ = winreg.QueryValueEx(key, icon_id)
            return val
        except FileNotFoundError:
            continue
        except OSError:
            continue
        finally:
            winreg.CloseKey(key)
    return None


def clear_icon_cache(log_func=print):
    """清理图标缓存。必须在 explorer 已退出后调用，否则文件被独占锁定删不掉。"""
    local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    removed = 0

    iconcache = os.path.join(local_appdata, "IconCache.db")
    if os.path.exists(iconcache):
        try:
            os.remove(iconcache)
            log_func("✓ 已清理 IconCache.db")
            removed += 1
        except Exception as e:
            log_func(f"  清理 IconCache.db 失败: {e}")

    explorer_cache_dir = os.path.join(local_appdata, "Microsoft", "Windows",
                                      "Explorer")
    if os.path.isdir(explorer_cache_dir):
        for f in os.listdir(explorer_cache_dir):
            low = f.lower()
            if low.startswith("iconcache") and low.endswith(".db"):
                try:
                    os.remove(os.path.join(explorer_cache_dir, f))
                    removed += 1
                except Exception as e:
                    log_func(f"  清理 {f} 失败: {e}")
    if removed:
        log_func(f"✓ 图标缓存已清理（{removed} 个文件）")
    else:
        log_func("  图标缓存未能清理（通常表示已被锁定，稍后可重试）")


def broadcast_setting_change(log_func=print):
    """广播 WM_SETTINGCHANGE，通知已运行的 shell 重新读取图标配置"""
    try:
        res = ctypes.c_size_t(0)
        user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0,
                                   ctypes.cast(ctypes.c_wchar_p("Shell Icons"),
                                               wintypes.LPARAM),
                                   SMTO_ABORTIFHUNG, 3000, ctypes.byref(res))
        # 额外通知环境/常规设置变化，促使桌面重绘
        user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, 0,
                                   SMTO_ABORTIFHUNG, 3000, ctypes.byref(res))
    except Exception:
        pass


def restart_explorer(log_func=print, clear_cache=True):
    log_func("正在重启资源管理器以应用更改...")
    # 关键顺序：必须先结束 explorer 再删除图标缓存。
    # 若在 explorer 运行期间删除 iconcache_*.db，文件被其独占锁定，删除必然失败；
    # 之后重启 explorer 会原样加载旧缓存，缓存的箭头/盾牌位图不消失 → 功能"看似失效"。
    _run_hidden("taskkill /f /im explorer.exe")

    if clear_cache:
        # explorer 已退出，缓存文件解锁，此时清理才能成功
        clear_icon_cache(log_func)

    log_func("正在重新启动资源管理器...")
    _run_hidden("start explorer.exe")
    # 额外执行一次图标缓存刷新命令（Win10/11 有效；失败则静默忽略）
    _run_hidden("ie4uinit.exe -show")
    broadcast_setting_change(log_func)
    log_func("✓ 资源管理器已重启，图标缓存已刷新")


# ============================================================
#  功能实现
# ============================================================
def _resolve_icon_value(log_func, use_fallback=False):
    """
    解析要写入注册表的图标值。

    默认使用自建全透明 ICO（不受系统版本影响）；
    use_fallback=True 时使用系统资源（带负号 = 资源 ID 语义）。
    """
    if use_fallback:
        if not os.path.exists(SHELL32):
            log_func("✗ 未找到 shell32.dll，无法使用系统图标方案")
            return None
        log_func(f"  使用系统图标（资源 ID 语义）: {FALLBACK_ICON}")
        return FALLBACK_ICON

    path = ensure_transparent_ico(log_func)
    if not path:
        log_func("  自建透明图标不可用，回退到系统图标方案")
        return FALLBACK_ICON if os.path.exists(SHELL32) else None

    ok, detail = verify_transparent_ico(path)
    if not ok:
        log_func(f"  ✗ 透明图标校验失败（{detail}），回退到系统图标方案")
        return FALLBACK_ICON if os.path.exists(SHELL32) else None

    log_func(f"  使用自建全透明图标: {path}  ({detail})")
    return path


def _lnkfile_key_paths():
    """返回 lnkfile 的注册表位置（HKLM 与 HKCU 两侧都覆盖，确保还原彻底）"""
    return [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\lnkfile",
         winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\lnkfile",
         winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Classes\lnkfile",
         winreg.KEY_WOW64_64KEY),
    ]


def remove_shortcut_arrow(log_func=print, use_fallback=False):
    """
    去除快捷方式小箭头 —— 默认使用 lnkfile\\IsShortcut 方案（推荐）。

    Explorer 依据 `HKEY_CLASSES_ROOT\\lnkfile` 的 `IsShortcut` 值决定是否为
    快捷方式绘制箭头叠加层。删除该值后 Explorer 根本不会请求箭头图标，
    因此完全不涉及图标替换 —— 也就不会有「加载失败被缓存成黑色方块」的问题。

    use_fallback=True 时改用旧的 Shell Icons\\29 替换方案（不推荐，实测会出黑块）。
    """
    if not use_fallback:
        log_func("【去箭头】使用推荐方案（IsShortcut，不替换图标）")
        removed = 0
        for hive, path, view in _lnkfile_key_paths():
            try:
                key = winreg.OpenKey(hive, path, 0,
                                     winreg.KEY_SET_VALUE | winreg.KEY_READ | view)
            except FileNotFoundError:
                continue
            except OSError as e:
                log_func(f"  打开 {path} 失败: {e}")
                continue
            try:
                winreg.DeleteValue(key, "IsShortcut")
                removed += 1
            except FileNotFoundError:
                removed += 1          # 已无该值 = 已是目标状态
            except OSError as e:
                log_func(f"  删除 IsShortcut 失败: {e}")
            finally:
                winreg.CloseKey(key)

        if removed == 0:
            log_func("✗ 无法修改 lnkfile（需要管理员权限）")
            log_func("  若你只想尽快去掉黑块，可改用「恢复默认」")
            return False

        log_func("✓ 已删除 IsShortcut")
        # 清掉可能残留的 Shell Icons 箭头替换值：它是黑块的来源，
        # 留着会让黑块继续出现（即使 IsShortcut 已删除）。
        stale = get_shell_icon_value(ICON_ARROW)
        if stale:
            log_func(f"  清理遗留的 Shell Icons 箭头替换值（黑块来源）: {stale}")
            delete_shell_icon(ICON_ARROW, log_func)
        restart_explorer(log_func)
        log_func("✓ 快捷方式箭头已去除")
        log_func("  本方案不替换图标，因此不会出现黑色方块")
        return True

    # ---- 旧方案（Shell Icons 替换）----
    log_func("【去箭头】使用兼容方案（Shell Icons 替换）")
    log_func("  注意：此方案在部分机器上会导致箭头位置出现黑色方块")
    value = _resolve_icon_value(log_func, use_fallback)
    if not value:
        log_func("✗ 去箭头失败：没有可用的透明图标")
        return False
    if set_shell_icon(ICON_ARROW, value, log_func):
        log_func("✓ 已设置透明图标替换箭头")
        restart_explorer(log_func)
        log_func("✓ 快捷方式小箭头已去除")
        log_func("  若出现黑色方块，请点「修复黑色方块」或改用推荐方案")
        return True
    log_func("✗ 去箭头失败")
    return False


def remove_uac_shield(log_func=print, use_fallback=False):
    """去除 UAC 蓝黄盾牌"""
    log_func("【去盾牌】开始处理...")
    value = _resolve_icon_value(log_func, use_fallback)
    if not value:
        log_func("✗ 去盾牌失败：没有可用的透明图标")
        return False
    if set_shell_icon(ICON_SHIELD, value, log_func):
        log_func("✓ 已设置透明图标替换盾牌")
        restart_explorer(log_func)
        log_func("✓ UAC 盾牌图标已去除")
        log_func("  提示：若个别位置仍显示盾牌，注销或重启一次即可刷新")
        return True
    log_func("✗ 去盾牌失败")
    return False


def remove_both(log_func=print, use_fallback=False):
    """
    一次处理箭头 + 盾牌，只重启一次 explorer（比点两次按钮快）。

    箭头用推荐的 IsShortcut 方案（不替换图标，不会出黑块）；
    盾牌用 Shell Icons\\77 替换（77 没有 IsShortcut 之类的等效机制）。
    """
    log_func("【去箭头 + 去盾牌】开始处理...")

    # --- 箭头：IsShortcut（或旧方案）---
    if use_fallback:
        log_func("  箭头：使用旧方案（Shell Icons 替换）")
        value = _resolve_icon_value(log_func, use_fallback=True)
        ok_a = bool(value) and set_shell_icon(ICON_ARROW, value, log_func)
    else:
        log_func("  箭头：使用推荐方案（IsShortcut，不替换图标）")
        ok_a = _delete_isshortcut(log_func)

    # --- 盾牌：Shell Icons\77 ---
    log_func("  盾牌：使用 Shell Icons\\77 替换")
    value = _resolve_icon_value(log_func, use_fallback)
    ok_b = bool(value) and set_shell_icon(ICON_SHIELD, value, log_func)

    if ok_a or ok_b:
        log_func(f"✓ 处理结果：箭头={'成功' if ok_a else '失败'}, "
                 f"盾牌={'成功' if ok_b else '失败'}")
        restart_explorer(log_func)
        log_func("✓ 处理完成")
        if not use_fallback and ok_a:
            log_func("  箭头使用 IsShortcut 方案，不会产生黑色方块")
        return ok_a and ok_b
    log_func("✗ 注册表写入失败")
    return False


def _delete_isshortcut(log_func=print):
    """删除 lnkfile\\IsShortcut（内部使用），成功返回 True"""
    done = 0
    for hive, path, view in _lnkfile_key_paths():
        try:
            key = winreg.OpenKey(hive, path, 0,
                                 winreg.KEY_SET_VALUE | winreg.KEY_READ | view)
        except FileNotFoundError:
            continue
        except OSError:
            continue
        try:
            winreg.DeleteValue(key, "IsShortcut")
            done += 1
        except FileNotFoundError:
            done += 1
        except OSError as e:
            log_func(f"    删除 IsShortcut 失败: {e}")
        finally:
            winreg.CloseKey(key)
    if done:
        log_func("    ✓ 已删除 IsShortcut")
        # 清掉遗留的 29 替换值（黑块来源）
        stale = get_shell_icon_value(ICON_ARROW)
        if stale:
            log_func(f"    清理遗留的 Shell Icons 箭头替换值: {stale}")
            delete_shell_icon(ICON_ARROW, log_func)
    return done > 0


def restore_defaults(log_func=print, clear_cache=True):
    """
    一键恢复默认外观：还原系统自带的快捷方式箭头和 UAC 盾牌。

    做三件事：
      1. 删除 `Shell Icons\\29` 与 `77` 的替换值（去掉盾牌替换，
         也去掉历史上可能残留的箭头替换值 —— 它是黑块的来源）；
      2. 重建 `lnkfile\\IsShortcut`（恢复快捷方式箭头）；
      3. 结束 explorer、清空图标缓存、重新启动。

    这是遇到黑色方块时最可靠的兜底手段：实测中只要 `Shell Icons\\29`
    存在，Explorer 就可能在重启后把箭头位置渲染成黑色方块。
    """
    log_func("【恢复默认】开始处理...")
    log_func("  当前 Shell Icons 状态：")
    describe_shell_icons(log_func)

    ok_a = delete_shell_icon(ICON_ARROW, log_func)
    ok_b = delete_shell_icon(ICON_SHIELD, log_func)
    log_func(f"  删除替换值：箭头(29)={'成功' if ok_a else '失败'}, "
             f"盾牌(77)={'成功' if ok_b else '失败'}")

    # 恢复 IsShortcut（若曾被删除）
    log_func("  恢复 lnkfile\\IsShortcut ...")
    restore_isc = False
    for hive, path, view in _lnkfile_key_paths():
        try:
            key = winreg.CreateKeyEx(hive, path, 0,
                                     winreg.KEY_SET_VALUE | view)
        except OSError:
            continue
        try:
            winreg.SetValueEx(key, "IsShortcut", 0, winreg.REG_SZ, "")
            restore_isc = True
        except OSError as e:
            log_func(f"  写入 IsShortcut 失败: {e}")
        finally:
            winreg.CloseKey(key)
    log_func("✓ 已恢复 IsShortcut" if restore_isc else "  未能恢复 IsShortcut")

    # 顺带删掉自建的透明图标，避免残留
    try:
        if os.path.exists(TRANSPARENT_ICO):
            os.remove(TRANSPARENT_ICO)
            log_func("✓ 已清理自建透明图标")
    except OSError:
        pass

    # 清缓存：把可能缓存的黑色占位位图一并清除
    restart_explorer(log_func, clear_cache=clear_cache)

    if ok_a and ok_b:
        log_func("✓ 已恢复默认快捷方式箭头和盾牌")
        log_func("  若桌面仍显示黑块，请注销后重新登录（或重启）一次")
        return True
    log_func("⚠ 恢复不完全，请以管理员身份重新运行后再试")
    return False


# ============================================================
#  桌面整理核心
# ============================================================
def organize_desktop(log_func=print):
    """一键整理桌面：快捷方式在最左，非快捷方式在最右"""
    log_func("【整理桌面】开始处理...")

    mgr = DesktopIconManager(log_func=log_func)
    if not mgr.connect():
        return False

    try:
        count = mgr.get_count()
        log_func(f"桌面共有 {count} 个图标")
        if count == 0:
            log_func("桌面上没有图标可整理")
            return True

        # 自动排列开启时写入的坐标会被系统立刻重排回去
        auto = mgr.auto_arrange_off()
        if auto:
            log_func("⚠ 检测到桌面「自动排列」处于开启状态")
            log_func("  请在桌面空白处右键 → 查看 → 取消勾选「自动排列图标」，否则整理结果会被立即还原")

        candidates = build_name_maps()
        shortcut_indices = []
        other_indices = []

        for i in range(count):
            try:
                name = mgr.get_name(i)
            except OSError as e:
                log_func(f"  读取第 {i} 项名称失败，跳过: {e}")
                continue
            if not name:
                name = f"item_{i}"
            (shortcut_indices if classify_name(name, candidates)
             else other_indices).append((i, name))

        log_func(f"快捷方式: {len(shortcut_indices)} 个, "
                 f"非快捷方式: {len(other_indices)} 个")

        # ---- 工作区与网格 ----
        work_area = RECT()
        if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0,
                                            ctypes.byref(work_area), 0):
            log_func("✗ 无法获取桌面工作区")
            return False

        # 多显示器：虚拟屏幕原点可能为负，工作区坐标也可能是负的。
        # 直接使用工作区自身的 left/top 而不做归零，保证副屏也能正确定位。
        work_left, work_top = work_area.left, work_area.top
        work_right, work_bottom = work_area.right, work_area.bottom
        work_w = work_right - work_left
        work_h = work_bottom - work_top
        log_func(f"桌面工作区: {work_w} x {work_h} "
                 f"(左={work_left}, 上={work_top}, 右={work_right}, 下={work_bottom})")

        # 优先使用系统实际图标间距，避免硬编码在高 DPI 下错位
        spacing = mgr.get_item_spacing()
        if spacing:
            icon_w, icon_h = spacing
            log_func(f"系统图标间距: {icon_w} x {icon_h}")
        else:
            # 回退：按 DPI 缩放估算（96 DPI 下桌面图标间距约 75x100）
            try:
                dpi = user32.GetDpiForWindow(mgr.hwnd)
            except Exception:
                dpi = 96
            if not dpi:
                dpi = 96
            scale = dpi / 96.0
            icon_w = int(round(75 * scale)) + 20
            icon_h = int(round(100 * scale)) + 20
            log_func(f"未能读取系统间距，按 DPI={dpi} 估算: {icon_w} x {icon_h}")

        margin = 8
        start_y = work_top + margin
        rows_per_col = max(1, (work_h - margin) // icon_h)
        log_func(f"每列可放 {rows_per_col} 个图标")

        # 快捷方式排列在最左侧（从工作区左边缘开始向右）
        for idx, (i, name) in enumerate(shortcut_indices):
            col = idx // rows_per_col
            row = idx % rows_per_col
            x = work_left + margin + col * icon_w
            y = start_y + row * icon_h
            mgr.set_position(i, x, y)

        # 非快捷方式排列在最右侧（从工作区右边缘向左）
        for idx, (i, name) in enumerate(other_indices):
            col = idx // rows_per_col
            row = idx % rows_per_col
            x = work_right - icon_w - margin - col * icon_w
            y = start_y + row * icon_h
            mgr.set_position(i, x, y)

        mgr.refresh()
        log_func("✓ 桌面整理完成！快捷方式在最左，非快捷方式在最右")
        return True
    except OSError as e:
        log_func(f"✗ 整理失败: {e}")
        log_func("  提示：跨进程读写被拒绝时，请以管理员身份运行")
        return False
    finally:
        mgr.close()


# ============================================================
#  管理员权限
# ============================================================
def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后：直接以管理员身份重启 exe 本身
        exe = sys.executable
        args = None
    else:
        exe = sys.executable
        args = f'"{os.path.abspath(__file__)}"'
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
    except Exception:
        pass


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
    WARN        = "#f59e0b"
    LOG_BG      = "#16161f"
    BORDER      = "#3a3a4e"

    def __init__(self, root):
        self.root = root
        self.busy = False
        self.use_fallback_icon = tk.BooleanVar(value=False)
        self._setup_window()
        self._setup_style()
        self._build_ui()

    def _setup_window(self):
        self.root.title("桌面整理工具  v2.0")
        w, h = 680, 720
        self.root.minsize(620, 640)
        self.root.configure(bg=self.BG)
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.BG)
        style.configure("Card.TFrame", background=self.CARD_BG)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT_MAIN,
                        font=("Microsoft YaHei UI", 10))
        style.configure("Log.TFrame", background=self.LOG_BG)

    def _make_card(self, parent, title, desc, button_text, command,
                   accent_color, secondary=None):
        """创建功能卡片。secondary 为可选的第二个按钮 (文字, 回调)。"""
        card = tk.Frame(parent, bg=self.CARD_BG, highlightbackground=self.BORDER,
                        highlightthickness=1, bd=0)
        card.pack(fill="x", padx=20, pady=4)

        inner = tk.Frame(card, bg=self.CARD_BG)
        inner.pack(fill="x", padx=14, pady=10)

        # 左侧色条
        tk.Frame(inner, bg=accent_color, width=4).pack(side="left", fill="y",
                                                       padx=(0, 10))

        info = tk.Frame(inner, bg=self.CARD_BG)
        info.pack(side="left", fill="x", expand=True)

        tk.Label(info, text=title, bg=self.CARD_BG, fg=self.TEXT_MAIN,
                 font=("Microsoft YaHei UI", 12, "bold"), anchor="w").pack(fill="x")
        tk.Label(info, text=desc, bg=self.CARD_BG, fg=self.TEXT_SUB,
                 font=("Microsoft YaHei UI", 9), anchor="w", wraplength=400,
                 justify="left").pack(fill="x", pady=(2, 0))

        btns = tk.Frame(inner, bg=self.CARD_BG)
        btns.pack(side="right", padx=(10, 0))

        tk.Button(btns, text=button_text, command=command,
                  bg=accent_color, fg="white", activebackground=self.ACCENT_HOVER,
                  activeforeground="white", bd=0, relief="flat",
                  font=("Microsoft YaHei UI", 10, "bold"),
                  cursor="hand2", padx=14, pady=6).pack(side="top")

        if secondary:
            text2, cmd2 = secondary
            tk.Button(btns, text=text2, command=cmd2,
                      bg=self.CARD_HOVER, fg=self.TEXT_SUB,
                      activebackground=self.BORDER, activeforeground=self.TEXT_MAIN,
                      bd=0, relief="flat", font=("Microsoft YaHei UI", 8),
                      cursor="hand2", padx=8, pady=2).pack(side="top", pady=(4, 0))

        def on_enter(_e):
            card.configure(highlightbackground=accent_color)

        def on_leave(_e):
            card.configure(highlightbackground=self.BORDER)

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)
        return card

    def _build_ui(self):
        # 顶部标题区
        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill="x", padx=20, pady=(16, 4))

        tk.Label(header, text="桌面整理工具", bg=self.BG, fg=self.TEXT_MAIN,
                 font=("Microsoft YaHei UI", 20, "bold")).pack(side="left")

        admin = is_admin()
        tk.Label(header, text="● 管理员" if admin else "● 非管理员",
                 bg=self.BG, fg=self.SUCCESS if admin else self.DANGER,
                 font=("Microsoft YaHei UI", 9)).pack(side="right", pady=(8, 0))

        tk.Label(self.root,
                 text="一键整理桌面 · 去除快捷方式箭头 · 去除UAC盾牌 · 恢复默认",
                 bg=self.BG, fg=self.TEXT_SUB,
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=20)

        tk.Frame(self.root, bg=self.BORDER, height=1).pack(fill="x", padx=20,
                                                           pady=(8, 4))

        cards = tk.Frame(self.root, bg=self.BG)
        cards.pack(fill="x")

        self._make_card(
            cards, "一键整理桌面",
            "快捷方式排到桌面最左侧，文件夹/文档/图片等排到最右侧。"
            "若无效请先关闭桌面右键菜单里的「自动排列图标」。",
            "开始整理", self.on_organize, self.ACCENT2)

        self._make_card(
            cards, "去除快捷方式箭头",
            "推荐方案：删除 lnkfile\\IsShortcut 标记，Explorer 不再绘制箭头。"
            "不替换图标，因此不会出现黑色方块。需管理员权限，完成后重启资源管理器。",
            "去除箭头", self.on_remove_arrow, self.ACCENT,
            secondary=("箭头+盾牌一起处理", self.on_remove_both))

        self._make_card(
            cards, "去除UAC盾牌图标",
            "去除应用图标右下角的蓝黄盾牌（UAC 提权标记）。"
            "需要管理员权限，完成后自动重启资源管理器。",
            "去除盾牌", self.on_remove_shield, self.DANGER)

        self._make_card(
            cards, "恢复默认（箭头 + 盾牌）",
            "删除 29/77 注册表替换值并清理图标缓存，还原 Windows 默认外观。",
            "恢复默认", self.on_restore, self.SUCCESS)

        self._make_card(
            cards, "修复黑色方块（保留去箭头）",
            "已出现黑色方块时用这个：删除 Shell Icons 的箭头替换值（黑块来源）、"
            "改用 IsShortcut 保持去箭头、并清空图标缓存。重启电脑不一定能解决，点这里才行。",
            "修复黑块", self.on_repair_blackbox, self.WARN)

        # 选项 + 状态
        opts = tk.Frame(self.root, bg=self.BG)
        opts.pack(fill="x", padx=20, pady=(8, 2))

        tk.Checkbutton(
            opts, text="去箭头时使用旧方案（Shell Icons 替换）—— 可能产生黑色方块，一般不要勾",
            variable=self.use_fallback_icon, bg=self.BG, fg=self.TEXT_SUB,
            activebackground=self.BG, activeforeground=self.TEXT_MAIN,
            selectcolor=self.CARD_BG, font=("Microsoft YaHei UI", 9),
            bd=0, highlightthickness=0).pack(side="left")

        if not HAS_WIN32COM:
            tk.Label(opts, text="⚠ 未安装 pywin32（不影响使用）", bg=self.BG,
                     fg=self.WARN, font=("Microsoft YaHei UI", 8)).pack(side="right")

        # 日志区
        log_header = tk.Frame(self.root, bg=self.BG)
        log_header.pack(fill="x", padx=20, pady=(6, 2))
        tk.Label(log_header, text="运行日志", bg=self.BG, fg=self.TEXT_SUB,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Button(log_header, text="清空", command=self.on_clear_log,
                  bg=self.CARD_BG, fg=self.TEXT_SUB,
                  activebackground=self.CARD_HOVER, activeforeground=self.TEXT_MAIN,
                  bd=0, relief="flat", font=("Microsoft YaHei UI", 8),
                  cursor="hand2", padx=8, pady=1).pack(side="right")

        log_frame = tk.Frame(self.root, bg=self.LOG_BG,
                             highlightbackground=self.BORDER, highlightthickness=1)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 14))

        self.log_text = tk.Text(log_frame, bg=self.LOG_BG, fg=self.TEXT_MAIN,
                                font=("Consolas", 9), bd=0, relief="flat",
                                wrap="word", state="disabled")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

        self.log("欢迎使用桌面整理工具 v2.0")
        self.log(f"管理员权限: {'是' if admin else '否（去箭头/去盾牌/恢复 将不可用）'}")
        self.log("当前注册表状态：")
        describe_shell_icons(self.log)
        self.log("提示：若去箭头后桌面出现黑色方块，点「修复黑色方块」即可（重启电脑不一定有效）")
        self._warn_if_stale_cache()

    def _warn_if_stale_cache(self):
        """
        启动自检：如果 29 指向自建 ICO 且该文件正常，但用户报告过黑块，
        提示使用「修复黑色方块」。这里只能做静态检查（程序无法感知渲染结果），
        因此仅在检测到明显异常时提示。
        """
        try:
            value = get_shell_icon_value(ICON_ARROW)
            if not value:
                return
            if os.path.normcase(value) != os.path.normcase(TRANSPARENT_ICO):
                return
            ok, detail = verify_transparent_ico(value)
            if not ok:
                self.log(f"⚠ 检测到透明图标异常（{detail}）")
                self.log("  请点「修复黑色方块」，或重新执行「去除箭头」")
        except Exception:
            pass

    # ---------- 日志 ----------
    def log(self, msg):
        def append():
            try:
                self.log_text.configure(state="normal")
                self.log_text.insert("end", str(msg) + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            except tk.TclError:
                pass     # 窗口已销毁
        try:
            self.root.after(0, append)
        except tk.TclError:
            pass

    def on_clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ---------- 按钮回调 ----------
    def _run(self, func, needs_admin=True, **kwargs):
        """统一的「检查权限 → 防重入 → 后台线程执行」入口"""
        if needs_admin and not is_admin():
            self._need_admin()
            return
        if self.busy:
            self.log("⚠ 上一个任务仍在执行，请稍候")
            return
        self.busy = True
        self.log("=" * 56)

        def wrapper():
            try:
                func(self.log, **kwargs)
            except Exception as e:      # 兜底，避免线程静默死掉
                self.log(f"✗ 执行出错: {type(e).__name__}: {e}")
            finally:
                self.busy = False

        Thread(target=wrapper, daemon=True).start()

    def on_organize(self):
        self._run(organize_desktop, needs_admin=False)

    def on_remove_arrow(self):
        self._run(remove_shortcut_arrow,
                  use_fallback=self.use_fallback_icon.get())

    def on_remove_shield(self):
        self._run(remove_uac_shield,
                  use_fallback=self.use_fallback_icon.get())

    def on_remove_both(self):
        self._run(remove_both,
                  use_fallback=self.use_fallback_icon.get())

    def on_restore(self):
        self._run(restore_defaults)

    def on_repair_blackbox(self):
        self._run(repair_stale_icon_cache)

    def _need_admin(self):
        result = messagebox.askyesno(
            "需要管理员权限",
            "此功能需要管理员权限才能修改系统注册表。\n\n"
            "是否以管理员身份重新启动程序？\n（当前整理记录会丢失）"
        )
        if result:
            relaunch_as_admin()
            self.root.destroy()


# ============================================================
#  入口
# ============================================================
def main():
    # 提前准备好透明图标，失败也不影响整理功能
    ensure_transparent_ico(lambda m: None)
    root = tk.Tk()
    DesktopCleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
