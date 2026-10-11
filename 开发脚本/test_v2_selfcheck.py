# -*- coding: utf-8 -*-
"""v2.0 自检：验证透明 ICO 字节结构、分类逻辑、注册表读取（只读）。

不修改系统，可安全反复运行。
"""
import os
import sys
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import desktop_cleaner as dc

FAIL = []


def check(label, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {label}" + (f"  -> {detail}" if detail else ""))
    if not cond:
        FAIL.append(label)


print("=" * 60)
print("1) 透明 ICO 字节结构")
print("=" * 60)

data = dc.build_transparent_ico_bytes(32)
check("总长度 = 22 + 40 + 4096 + 128 = 4286", len(data) == 4286, f"实际 {len(data)}")

reserved, img_type, count = struct.unpack("<HHH", data[:6])
check("ICONDIR", (reserved, img_type, count) == (0, 1, 1),
      f"reserved={reserved} type={img_type} count={count}")

w, h, colors, rsvd, planes, bpp, nbytes, offset = struct.unpack("<BBBBHHII", data[6:22])
check("宽高 32x32", (w, h) == (32, 32), f"{w}x{h}")
check("planes=1 bpp=32", (planes, bpp) == (1, 32), f"planes={planes} bpp={bpp}")
check("bytesInRes=4264", nbytes == 4264, f"{nbytes}")
check("offset=22", offset == 22, f"{offset}")
check("offset+nbytes == filesize", offset + nbytes == len(data))

bi_size, bi_w, bi_h = struct.unpack("<Iii", data[offset:offset + 12])
check("BI: size=40 w=32 h=64(两倍)", (bi_size, bi_w, bi_h) == (40, 32, 64),
      f"size={bi_size} w={bi_w} h={bi_h}")

body = data[offset + 40:]
xor_plane = body[:4096]
and_plane = body[4096:]
check("XOR 平面 4096 字节全 0 (颜色黑 + alpha 0)", not any(xor_plane),
      f"非零字节 {sum(1 for b in xor_plane if b)}")
# ★ 关键回归测试：AND 掩码必须全 1（0xFF）。
# 全 0 会让 Explorer 把叠加层画成实心黑色方块（已实测复现 30 个黑块）。
check("AND 掩码 128 字节全 1 (0xFF = 透明，防黑块)", all(b == 0xFF for b in and_plane),
      f"非 0xFF 字节 {sum(1 for b in and_plane if b != 0xFF)}")

# 逐像素校验 alpha
alphas = [xor_plane[i * 4 + 3] for i in range(32 * 32)]
check("1024 个像素 alpha 全部为 0", all(a == 0 for a in alphas),
      f"最大 alpha={max(alphas)}")

print()
print("=" * 60)
print("2) 多尺寸生成")
print("=" * 60)
for size in (16, 24, 32, 48, 64, 256):
    d = dc.build_transparent_ico_bytes(size)
    expected = 22 + 40 + size * size * 4 + (size * size + 7) // 8
    ok = len(d) == expected
    check(f"{size}x{size} 尺寸字节数正确", ok, f"{len(d)} vs {expected}")

print()
print("=" * 60)
print("3) 落盘 + 结构复校验")
print("=" * 60)
path = dc.ensure_transparent_ico(print)
check("透明 ICO 已生成", bool(path and os.path.exists(path)), str(path))
if path and os.path.exists(path):
    ok, detail = dc.verify_transparent_ico(path)
    check("verify_transparent_ico 通过", ok, detail)

print()
print("=" * 60)
print("4) 分类逻辑")
print("=" * 60)
cands = dc.build_name_maps()
check("build_name_maps 返回 dict", isinstance(cands, dict), f"{len(cands)} 项")

cases = [
    ("此电脑", False, "系统虚拟图标"),
    ("回收站", False, "系统虚拟图标"),
    ("This PC", False, "系统虚拟图标"),
    ("某个不存在的东西", False, "既无映射也无 .lnk 后缀"),
    ("某个不存在的东西.lnk", True, "名字自带 .lnk 后缀"),
    ("某网址.url", True, "名字自带 .url 后缀"),
    ("普通文档.txt", False, "普通文档后缀"),
]
for name, expect, why in cases:
    got = dc.classify_name(name, cands)
    check(f"classify({name!r}) == {expect}", got == expect, why)

print()
print("=" * 60)
print("5) 注册表只读状态")
print("=" * 60)
state = dc.read_shell_icons()
print(f"  当前 Shell Icons 条目: {state if state else '（无）'}")
check("read_shell_icons 可调用", isinstance(state, dict))

print()
print("=" * 60)
print("6) 常量/语义校验")
print("=" * 60)
check("FALLBACK_ICON 带负号（资源 ID 语义）",
      dc.FALLBACK_ICON.endswith(",-50"), dc.FALLBACK_ICON)
check("SHELL32 是绝对路径", os.path.isabs(dc.SHELL32), dc.SHELL32)
check("TRANSPARENT_ICO 在 LOCALAPPDATA 下",
      dc.TRANSPARENT_ICO.lower().startswith(
          os.environ.get("LOCALAPPDATA", "~").lower()), dc.TRANSPARENT_ICO)
# 注意：源码注释里会「提到」坏的写法用于说明原因，所以只检查**代码行**，
# 忽略注释与文档字符串。
import tokenize
import io as _io

src_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "desktop_cleaner.py")
with open(src_path, encoding="utf-8") as f:
    src_text = f.read()

code_only = []
try:
    for tok in tokenize.generate_tokens(_io.StringIO(src_text).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            code_only.append(tok.string)
except tokenize.TokenError:
    pass
code_blob = " ".join(code_only)

check("代码中未出现正号 shell32.dll,50 写法",
      "shell32.dll,50" not in code_blob)
check("回退值确实以负号结尾（资源 ID 语义）",
      dc.FALLBACK_ICON.endswith("shell32.dll,-50"), dc.FALLBACK_ICON)

print()
print("=" * 60)
if FAIL:
    print(f"结果: {len(FAIL)} 项失败")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("结果: 全部通过")
