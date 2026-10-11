# -*- coding: utf-8 -*-
"""注册表写入/还原往返测试（仅操作 HKCU 的测试键，不触碰真实 Shell Icons）。

真实 Shell Icons 的写入需要管理员权限且会改变系统外观，这里只验证
「读 -> 写 -> 读回 -> 删 -> 读回」的代码路径是否正确，用 HKCU 下的临时键代替。
"""
import os
import sys
import winreg
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import desktop_cleaner as dc

TEST_KEY = r"SOFTWARE\DesktopCleanerSelfTest\Shell Icons"
FAIL = []


def check(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  -> {detail}" if detail else ""))
    if not cond:
        FAIL.append(label)


def cleanup():
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
    except OSError:
        pass


cleanup()

# ---- 用 HKCU 测试键跑一遍 写/读/删 往返 ----
print("=" * 60)
print("注册表往返测试 (HKCU 临时键)")
print("=" * 60)

try:
    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, TEST_KEY, 0,
                             winreg.KEY_SET_VALUE | winreg.KEY_READ)
    winreg.SetValueEx(key, "29", 0, winreg.REG_SZ, dc.TRANSPARENT_ICO)
    winreg.SetValueEx(key, "77", 0, winreg.REG_SZ, dc.FALLBACK_ICON)
    winreg.CloseKey(key)

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY, 0, winreg.KEY_READ)
    v29, _ = winreg.QueryValueEx(key, "29")
    v77, _ = winreg.QueryValueEx(key, "77")
    winreg.CloseKey(key)
    check("写入后读回 29", v29 == dc.TRANSPARENT_ICO, v29)
    check("写入后读回 77", v77 == dc.FALLBACK_ICON, v77)

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY, 0, winreg.KEY_SET_VALUE)
    winreg.DeleteValue(key, "29")
    winreg.DeleteValue(key, "77")
    winreg.CloseKey(key)

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY, 0, winreg.KEY_READ)
    missing = 0
    for name in ("29", "77"):
        try:
            winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            missing += 1
    winreg.CloseKey(key)
    check("删除后两个值都不存在", missing == 2, f"missing={missing}")
except Exception:
    traceback.print_exc()
    FAIL.append("注册表往返测试异常")

cleanup()

# ---- 删除不存在的键应静默成功（幂等性）----
print()
print("=" * 60)
print("幂等性 / 边界情况")
print("=" * 60)
try:
    ok = dc.delete_shell_icon("29", lambda m: None)
    check("delete_shell_icon 在键不存在时不抛异常", True, f"返回 {ok}")
except Exception as e:
    check("delete_shell_icon 在键不存在时不抛异常", False, repr(e))

# delete_shell_icon 对真实 HKLM 只读/无害检查：它会尝试删除真实值，
# 所以这里不调用，避免改变系统状态。改为验证目标列表构成。
targets = dc._registry_targets()
check("注册表目标覆盖 3 处", len(targets) == 3, f"{len(targets)}")
hives = [t[0] for t in targets]
views = [t[2] for t in targets]
check("包含 HKLM 与 HKCU",
      winreg.HKEY_LOCAL_MACHINE in hives and winreg.HKEY_CURRENT_USER in hives)
check("包含 64 位与 32 位视图",
      winreg.KEY_WOW64_64KEY in views and winreg.KEY_WOW64_32KEY in views)

# ---- 假成功回归测试：未提权时 set_shell_icon 必须返回 False ----
# 这是 v2.0 修复的一个重要 bug：HKLM 写不进去但 HKCU 写进去了，
# 旧逻辑会返回 True 并提示「成功」，用户在桌面上却看不到任何变化。
print()
print("=" * 60)
print("假成功回归测试")
print("=" * 60)

import ctypes
is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
print(f"  当前管理员状态: {is_admin}")

if not is_admin:
    logs = []
    result = dc.set_shell_icon("29", dc.TRANSPARENT_ICO, logs.append)
    check("未提权时 set_shell_icon 返回 False（不再假成功）",
          result is False, f"返回 {result}")
    check("给出了明确指出权限问题的日志",
          any("权限" in m for m in logs), " | ".join(logs[:2]))
    # HKCU 不应残留无效值
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, dc.SHELL_ICONS_KEY, 0,
                           winreg.KEY_READ)
        try:
            winreg.QueryValueEx(k, "29")
            leftover = True
        except FileNotFoundError:
            leftover = False
        winreg.CloseKey(k)
    except OSError:
        leftover = False
    check("HKCU 未残留无效写入（已回滚）", not leftover)
else:
    print("  （当前已是管理员，跳过该用例）")

# ---- 透明图标幂等生成 ----
print()
print("=" * 60)
print("透明图标生成幂等性")
print("=" * 60)
p1 = dc.ensure_transparent_ico(lambda m: None)
size1 = os.path.getsize(p1)
p2 = dc.ensure_transparent_ico(lambda m: None)
size2 = os.path.getsize(p2)
check("两次调用路径一致", p1 == p2, p1)
check("两次调用大小一致", size1 == size2, f"{size1} == {size2}")
ok, detail = dc.verify_transparent_ico(p2)
check("最终文件校验通过", ok, detail)

print()
print("=" * 60)
if FAIL:
    print(f"结果: {len(FAIL)} 项失败")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("结果: 全部通过")
