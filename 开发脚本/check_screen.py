# -*- coding: utf-8 -*-
import ctypes

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

r = RECT()
ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
print(f"WorkArea: left={r.left}, top={r.top}, right={r.right}, bottom={r.bottom}")
print(f"WorkArea size: w={r.right - r.left}, h={r.bottom - r.top}")
print(f"Screen: w={ctypes.windll.user32.GetSystemMetrics(0)}, h={ctypes.windll.user32.GetSystemMetrics(1)}")

# 检查 DPI
dpi = ctypes.windll.user32.GetDpiForSystem()
print(f"DPI: {dpi}")
print(f"DPI scale: {dpi / 96 * 100}%")
