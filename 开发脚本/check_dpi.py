# -*- coding: utf-8 -*-
"""获取物理分辨率（DPI-unaware 坐标）"""
import ctypes

# 方法1: 通过 GetDeviceCaps 获取物理分辨率
hdc = ctypes.windll.user32.GetDC(0)
LOGPIXELSX = 88
HORZRES = 8
VERTRES = 10
DESKTOPHORZRES = 118
DESKTOPVERTRES = 117

horzres = ctypes.windll.gdi32.GetDeviceCaps(hdc, HORZRES)
vertres = ctypes.windll.gdi32.GetDeviceCaps(hdc, VERTRES)
desktop_horz = ctypes.windll.gdi32.GetDeviceCaps(hdc, DESKTOPHORZRES)
desktop_vert = ctypes.windll.gdi32.GetDeviceCaps(hdc, DESKTOPVERTRES)
dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
ctypes.windll.user32.ReleaseDC(0, hdc)

print(f"GetDeviceCaps HORZRES={horzres}, VERTRES={vertres}")
print(f"GetDeviceCaps DESKTOPHORZRES={desktop_horz}, DESKTOPVERTRES={desktop_vert}")
print(f"DPI (LOGPIXELSX)={dpi}")

# 方法2: GetSystemMetricsForDpi
try:
    sm_w = ctypes.windll.user32.GetSystemMetrics(0)
    sm_h = ctypes.windll.user32.GetSystemMetrics(1)
    print(f"GetSystemMetrics: {sm_w} x {sm_h}")
except:
    pass

# 尝试 SetProcessDPIAware 后再获取
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

sm_w2 = ctypes.windll.user32.GetSystemMetrics(0)
sm_h2 = ctypes.windll.user32.GetSystemMetrics(1)
print(f"After DPI Aware - GetSystemMetrics: {sm_w2} x {sm_h2}")
