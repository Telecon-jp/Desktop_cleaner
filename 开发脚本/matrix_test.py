# -*- coding: utf-8 -*-
"""验证：黑块是否与「设置 29」存在因果关系，以及是否随机跳动。

设计：对同一注册表取值，连续重启 explorer N 次，每次测量黑块数。
若结果在 0 与非 0 之间跳动 => 竞态问题，与图标文件内容无关。
"""
import os
import sys
import io
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import desktop_cleaner as dc
from detect_blackbox import expected_cells, minimize_all_windows, restore_windows, \
    grab_desktop, find_black_boxes

N = 6


def measure():
    cells, _ = expected_cells()
    saved = minimize_all_windows()
    time.sleep(1.5)
    try:
        im = grab_desktop()
        boxes = find_black_boxes(im)
        hit = 0
        for b in boxes:
            for (cx, cy) in (cells or []):
                if abs(b[0] - cx) <= 30 and abs(b[1] - cy) <= 30:
                    hit += 1
                    break
        return hit
    finally:
        restore_windows(saved)


def cycle():
    subprocess.run("taskkill /f /im explorer.exe", shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    subprocess.run("start explorer.exe", shell=True)
    time.sleep(6)
    return measure()


def run_case(label):
    print(f"\n{'='*60}")
    print(f"用例: {label}")
    print(f"{'='*60}")
    vals = []
    for i in range(N):
        v = cycle()
        vals.append(v)
        print(f"  第 {i+1} 次重启 explorer -> 黑块 {v}")
    print(f"  结果序列: {vals}")
    if all(v == 0 for v in vals):
        print("  => 稳定正常")
    elif all(v > 0 for v in vals):
        print("  => 稳定黑块")
    else:
        print("  => !! 跳动（时好时坏）—— 竞态问题")
    return vals


def main():
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        results = {}

        # 用例 A: 无 29
        dc.delete_shell_icon("29", lambda m: None)
        dc.delete_shell_icon("77", lambda m: None)
        results["无29/77"] = run_case("Windows 默认（无 29/77）")

        # 用例 B: 自建 ICO
        p = dc.ensure_transparent_ico(lambda m: None)
        dc.set_shell_icon("29", p, lambda m: None)
        results["自建ICO"] = run_case(f"29 = 自建 ICO")

        # 用例 C: shell32.dll,-50
        dc.set_shell_icon("29", r"C:\Windows\System32\shell32.dll,-50", lambda m: None)
        results["dll-50"] = run_case("29 = shell32.dll,-50")

        # 用例 D: shell32.dll,50 (正号)
        dc.set_shell_icon("29", r"C:\Windows\System32\shell32.dll,50", lambda m: None)
        results["dll+50"] = run_case("29 = shell32.dll,50")

        print(f"\n{'='*60}")
        print("汇总")
        print(f"{'='*60}")
        for k, v in results.items():
            print(f"  {k:12s}: {v}")
    finally:
        sys.stdout = real
        with open(os.path.join(HERE, "_matrix_out.txt"), "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print(buf.getvalue())


if __name__ == "__main__":
    main()
