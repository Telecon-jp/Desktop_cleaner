# -*- coding: utf-8 -*-
"""验证修复后的分类逻辑"""
import ctypes
import os
import sys
sys.path.insert(0, r"C:\Users\Telecon\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a82c0f4d2657931e5f08f5e")

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

from desktop_cleaner import DesktopIconManager, get_desktop_items, SYSTEM_ICONS

DESKTOP_PATH = os.path.join(os.path.expanduser("~"), "Desktop")
PUBLIC_DESKTOP = os.path.join(os.environ.get("PUBLIC", "C:\\Users\\Public"), "Desktop")

desktop_files = get_desktop_items()
name_to_file = {}
for fname in desktop_files:
    display_name = os.path.splitext(fname)[0]
    name_to_file[display_name] = fname
for fname in desktop_files:
    name_to_file[fname] = fname

mgr = DesktopIconManager()
if not mgr.connect():
    sys.exit(1)

count = mgr.get_count()
shortcuts = []
others = []

for i in range(count):
    name = mgr.get_name(i)
    if not name:
        name = f"item_{i}"
    is_lnk = False
    if name in SYSTEM_ICONS:
        is_lnk = False
    else:
        actual_file = name_to_file.get(name)
        if actual_file:
            ext = os.path.splitext(actual_file)[1].lower()
            is_lnk = (ext == ".lnk" or ext == ".url")
        else:
            ext = os.path.splitext(name)[1].lower()
            is_lnk = (ext == ".lnk" or ext == ".url")
    if is_lnk:
        shortcuts.append((i, name))
    else:
        others.append((i, name))

print(f"=== 快捷方式 ({len(shortcuts)} 个) → 左边 ===")
for i, name in shortcuts:
    actual = name_to_file.get(name, "?")
    print(f"  [{i:2d}] {name:30s}  (file: {actual})")

print(f"\n=== 非快捷方式 ({len(others)} 个) → 右边 ===")
for i, name in others:
    actual = name_to_file.get(name, name)
    print(f"  [{i:2d}] {name:30s}  (file: {actual})")

mgr.close()
