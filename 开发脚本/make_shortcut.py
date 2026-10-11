# -*- coding: utf-8 -*-
"""
将上传的 PNG 转换为 ICO 并创建带自定义图标的快捷方式
"""
from PIL import Image
import os
import win32com.client

PNG_SRC = r"c:\Users\Telecon\.trae-cn\attachments\6a82c0f4d2657931e5f08f61\4cf4f45f-1996-4d0f-8524-5890c93789bd_08d0cec3-be8d-4040-a0f7-461d801f1196_app_icon.png"
FOLDER = r"C:\Users\Telecon\Desktop\ai coding成果"
ICO_PATH = os.path.join(FOLDER, "app_icon.ico")
PY_FILE = os.path.join(FOLDER, "desktop_cleaner.py")
LNK_PATH = os.path.join(FOLDER, "桌面整理工具.lnk")
PYTHON_EXE = r"C:\Users\Telecon\PyCharmMiscProject\.venv\Scripts\python.exe"

def main():
    # 1. PNG -> ICO
    img = Image.open(PNG_SRC).convert("RGBA")
    img.save(ICO_PATH, format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    print(f"ICO saved: {ICO_PATH}")

    # 2. 创建快捷方式
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(LNK_PATH)
    shortcut.TargetPath = PYTHON_EXE
    shortcut.Arguments = f'"{PY_FILE}"'
    shortcut.WorkingDirectory = FOLDER
    shortcut.IconLocation = ICO_PATH
    shortcut.Description = "桌面整理工具 v1.0"
    shortcut.Save()
    print(f"Shortcut created: {LNK_PATH}")
    print("Done!")

if __name__ == "__main__":
    main()
