# -*- coding: utf-8 -*-
"""黑块检测器：截取桌面图标区域，统计 48x48 纯黑块数量。

用法: python detect_blackbox.py [输出png]

判定依据（由实测得出）：
  - 黑块是恰好 48x48、填充率 1.000 的纯黑连通域
  - 按桌面图标网格排列（间距 = 系统图标间距）
壁纸本身的黑色区域不会形成这么大的纯黑实心矩形，因此误报率低。
"""
import sys
import os
import time
import ctypes
from ctypes import wintypes
from collections import deque

from PIL import Image, ImageGrab

user32 = ctypes.windll.user32
user32.SetProcessDpiAwareness = getattr(user32, "SetProcessDPIAware", None)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

BLACK_THR = 20
MIN_SIZE = 40          # 小于此边长的黑块不算（图标本体 48）
MAX_SIZE = 56


def grab_desktop():
    """截取主显示器全屏。

    注意：ImageGrab 抓的是屏幕合成结果，会把挡在桌面上的窗口一起抓进来。
    因此调用方必须先最小化所有窗口，或依赖下面的 analyze_icon_cells 只统计
    图标网格所在位置。
    """
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    return ImageGrab.grab(bbox=(0, 0, w, h)).convert("RGB")


def minimize_all_windows():
    """最小化所有可见顶层窗口，返回原状态以便恢复。

    比模拟 Win+D 可靠：Win+D 在有全屏/独占窗口时可能无效。
    """
    SW_MINIMIZE = 6
    SW_RESTORE = 9
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080

    saved = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, 4):        # GW_OWNER != 0 -> 跳过子/从属窗口
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        # 跳过工具窗口
        GetWindowLongPtrW = getattr(user32, "GetWindowLongPtrW",
                                    user32.GetWindowLongW)
        ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW:
            return True
        if user32.IsIconic(hwnd):
            return True                      # 本来就最小化，不动
        saved.append(hwnd)
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        return True

    user32.EnumWindows(enum_proc, 0)
    return saved


def restore_windows(handles):
    """恢复之前最小化的窗口。"""
    SW_RESTORE = 9
    for h in handles:
        try:
            user32.ShowWindow(h, SW_RESTORE)
        except Exception:
            pass


def find_black_boxes(im):
    """返回所有接近 48x48 的纯黑矩形"""
    px = im.load()
    W, H = im.size

    def is_black(x, y):
        r, g, b = px[x, y]
        return r < BLACK_THR and g < BLACK_THR and b < BLACK_THR

    visited = bytearray(W * H)
    boxes = []
    for y in range(H):
        base = y * W
        for x in range(W):
            if visited[base + x] or not is_black(x, y):
                continue
            q = deque([(y, x)])
            visited[base + x] = 1
            miny = maxy = y
            minx = maxx = x
            n = 0
            while q:
                cy, cx = q.popleft()
                n += 1
                if cy < miny: miny = cy
                if cy > maxy: maxy = cy
                if cx < minx: minx = cx
                if cx > maxx: maxx = cx
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < H and 0 <= nx < W:
                        idx = ny * W + nx
                        if not visited[idx] and is_black(nx, ny):
                            visited[idx] = 1
                            q.append((ny, nx))
            w = maxx - minx + 1
            h = maxy - miny + 1
            fill = n / (w * h)
            if MIN_SIZE <= w <= MAX_SIZE and MIN_SIZE <= h <= MAX_SIZE and fill > 0.98:
                boxes.append((minx, miny, w, h, fill))
    return boxes


def expected_cells():
    """返回桌面上预期的图标单元左上角坐标集合（基于 ListView 实际坐标）。"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import desktop_cleaner as dc
    mgr = dc.DesktopIconManager(lambda m: None)
    if not mgr.connect():
        return None, None
    try:
        n = mgr.get_count()
        pts = []
        for i in range(n):
            x, y = mgr.get_position(i)
            pts.append((x, y))
        spacing = mgr.get_item_spacing()
        return pts, spacing
    finally:
        mgr.close()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else None
    no_min = "--no-minimize" in sys.argv

    cells, spacing = expected_cells()
    print(f"ListView 图标数: {len(cells) if cells else '?'}, 间距: {spacing}")

    if not no_min:
        saved = minimize_all_windows()
        print(f"已最小化 {len(saved)} 个窗口（稍后恢复）")
        time.sleep(2.0)
    else:
        saved = []

    try:
        im = grab_desktop()
        if out:
            im.save(out)
            print(f"截图已保存: {out}  {im.size}")

        boxes = find_black_boxes(im)
        print(f"整屏检测到 {len(boxes)} 个 48x48 纯黑块")

        # 只保留落在图标单元位置上的黑块（排除壁纸/窗口里的黑色矩形）
        if cells and boxes:
            matched = []
            tol = 30
            for b in boxes:
                bx, by = b[0], b[1]
                for (cx, cy) in cells:
                    if abs(bx - cx) <= tol and abs(by - cy) <= tol:
                        matched.append(b)
                        break
            print(f"其中落在图标位置上的: {len(matched)}")
            hit = len(matched)
        else:
            hit = len(boxes)
    finally:
        if saved:
            restore_windows(saved)
            print("已恢复窗口")

    if hit:
        print("  结论: 存在黑块")
        return 1
    print("  结论: 无黑块")
    return 0


if __name__ == "__main__":
    sys.exit(main())
