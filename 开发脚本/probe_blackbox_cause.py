# -*- coding: utf-8 -*-
"""黑块复现条件探测器。

严格按步骤做受控实验，每步后测量黑块数，定位「什么时候开始变黑」。

用法: python probe_blackbox_cause.py
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


def measure(label):
    """测量当前桌面的黑块数"""
    cells, spacing = expected_cells()
    saved = minimize_all_windows()
    time.sleep(1.5)
    try:
        im = grab_desktop()
        boxes = find_black_boxes(im)
        hit = 0
        if cells and boxes:
            for b in boxes:
                for (cx, cy) in cells:
                    if abs(b[0] - cx) <= 30 and abs(b[1] - cy) <= 30:
                        hit += 1
                        break
        else:
            hit = len(boxes)
    finally:
        restore_windows(saved)
    print(f"  [{label}] 黑块数 = {hit}")
    return hit


def kill_explorer():
    subprocess.run("taskkill /f /im explorer.exe", shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)


def start_explorer():
    subprocess.run("start explorer.exe", shell=True)
    time.sleep(6)


def ico_state():
    p = dc.TRANSPARENT_ICO
    if not os.path.exists(p):
        return "缺失"
    ok, detail = dc.verify_transparent_ico(p)
    return f"{'正常' if ok else '异常'} ({detail})"


def main():
    print("=" * 64)
    print("黑块复现条件探测")
    print("=" * 64)
    print()
    print(f"ICO 文件: {ico_state()}")
    print(f"注册表 29: {dc.get_shell_icon_value('29')}")
    print(f"注册表 77: {dc.get_shell_icon_value('77')}")
    print()

    results = {}

    print("步骤 1: 当前状态（不做任何操作）")
    results["初始"] = measure("初始")

    print()
    print("步骤 2: 只重启 explorer（不清缓存）")
    kill_explorer()
    start_explorer()
    results["只重启explorer"] = measure("只重启explorer")

    print()
    print("步骤 3: 清缓存 + 重启 explorer")
    kill_explorer()
    dc.clear_icon_cache(lambda m: None)
    start_explorer()
    results["清缓存+重启"] = measure("清缓存+重启")

    print()
    print("步骤 4: 再次只重启 explorer（不清缓存）")
    kill_explorer()
    start_explorer()
    results["再只重启"] = measure("再只重启")

    print()
    print("=" * 64)
    print("结果汇总")
    print("=" * 64)
    for k, v in results.items():
        print(f"  {k:20s}: {v}")

    print()
    if results.get("清缓存+重启", 0) == 0 and results.get("再只重启", 0) > 0:
        print("结论: 清缓存后正常，但【下一次 explorer 启动】又会变黑")
        print("      => explorer 每次启动都会重新产生坏缓存")
        print("      => 坏缓存不是历史遗留，而是持续性问题")
    elif results.get("清缓存+重启", 0) == 0 and results.get("再只重启", 0) == 0:
        print("结论: 清缓存后能保持正常")
    else:
        print("结论: 清缓存后仍不正常，问题不在缓存")

    return 0


if __name__ == "__main__":
    out = os.path.join(HERE, "_probe_out.txt")
    buf = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = buf

    class Tee:
        def write(self, s):
            buf.write(s)
    try:
        rc = main()
    finally:
        sys.stdout = real_stdout
        with open(out, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
                # 同时打印
        print(buf.getvalue())
    sys.exit(rc)
