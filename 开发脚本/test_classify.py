# -*- coding: utf-8 -*-
"""测试：分类并显示每个图标会放到哪里"""
import ctypes
import sys
sys.path.insert(0, r"C:\Users\Telecon\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a82c0f4d2657931e5f08f5e")

# 启用 DPI 感知
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

from desktop_cleaner import DesktopIconManager, get_desktop_items, is_shortcut, SYSTEM_ICONS

# 获取工作区
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
work_area = RECT()
ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0)
print(f"WorkArea: left={work_area.left}, top={work_area.top}, right={work_area.right}, bottom={work_area.bottom}")
print(f"Size: {work_area.right - work_area.left} x {work_area.bottom - work_area.top}")
print()

mgr = DesktopIconManager()
if not mgr.connect():
    print("connect failed")
    sys.exit(1)

count = mgr.get_count()
desktop_files = get_desktop_items()
print(f"Desktop files: {desktop_files}")
print()

shortcuts = []
others = []

for i in range(count):
    name = mgr.get_name(i)
    if not name:
        name = f"item_{i}"
    
    is_lnk = False
    if name in SYSTEM_ICONS:
        is_lnk = False
    elif name in desktop_files:
        is_lnk = is_shortcut(name)
    else:
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        is_lnk = (ext == "lnk")
    
    if is_lnk:
        shortcuts.append((i, name))
    else:
        others.append((i, name))

print(f"=== 快捷方式 ({len(shortcuts)} 个) → 放左边 ===")
for i, name in shortcuts:
    print(f"  [{i}] {name}")

print(f"\n=== 非快捷方式 ({len(others)} 个) → 放右边 ===")
for i, name in others:
    print(f"  [{i}] {name}")

mgr.close()
