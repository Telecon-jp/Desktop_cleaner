# -*- coding: utf-8 -*-
"""验证当前 transparent.ico 是否有效"""
import os
import struct

tmp_dir = os.environ.get("TEMP", os.path.expanduser("~"))
ico_path = os.path.join(tmp_dir, "transparent.ico")

if os.path.exists(ico_path):
    with open(ico_path, "rb") as f:
        data = f.read()
    print(f"File size: {len(data)} bytes")
    print(f"Hex: {data.hex()}")
    
    # ICO header: first 6 bytes
    if len(data) >= 6:
        reserved, img_type, count = struct.unpack("<HHH", data[0:6])
        print(f"ICO header: reserved={reserved}, type={img_type}, count={count}")
    
    # Directory entry: next 16 bytes per entry
    if len(data) >= 22 and count and count > 0:
        entry = data[6:22]
        w = entry[0] or 256
        h = entry[1] or 256
        colors = entry[2]
        planes = struct.unpack("<H", entry[4:6])[0]
        bpp = struct.unpack("<H", entry[6:8])[0]
        img_size = struct.unpack("<I", entry[8:12])[0]
        offset = struct.unpack("<I", entry[12:16])[0]
        print(f"Dir entry: w={w}, h={h}, colors={colors}, planes={planes}, bpp={bpp}, size={img_size}, offset={offset}")
        print(f"Actual data after offset: {len(data) - offset} bytes")
        print(f"Size match: {img_size == len(data) - offset}")
else:
    print(f"File not found: {ico_path}")

# Also check what imageres.dll resources are available
print("\n--- System icon resources ---")
import ctypes
windir = os.environ.get("WINDIR", r"C:\Windows")
print(f"WINDIR: {windir}")
print(f"shell32.dll exists: {os.path.exists(os.path.join(windir, 'System32', 'shell32.dll'))}")
print(f"imageres.dll exists: {os.path.exists(os.path.join(windir, 'System32', 'imageres.dll'))}")
