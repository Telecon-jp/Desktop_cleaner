# -*- coding: utf-8 -*-
"""
测试：读取桌面所有图标的名称和当前位置
"""
import ctypes
from ctypes import wintypes
import sys
sys.path.insert(0, r"C:\Users\Telecon\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a82c0f4d2657931e5f08f5e")
from desktop_cleaner import DesktopIconManager

mgr = DesktopIconManager()
if not mgr.connect():
    print("connect failed")
    sys.exit(1)

count = mgr.get_count()
print(f"Total icons: {count}")
print()

for i in range(count):
    name = mgr.get_name(i)
    x, y = mgr.get_position(i)
    print(f"  [{i:2d}] {name:30s}  pos=({x:5d}, {y:5d})")

mgr.close()
