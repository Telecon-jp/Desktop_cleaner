# -*- coding: utf-8 -*-
"""将上传的 PNG 转换为 ICO"""
from PIL import Image
import os

PNG_SRC = r"c:\Users\Telecon\.trae-cn\attachments\6a82c0f4d2657931e5f08f61\4cf4f45f-1996-4d0f-8524-5890c93789bd_08d0cec3-be8d-4040-a0f7-461d801f1196_app_icon.png"
FOLDER = r"C:\Users\Telecon\Desktop\ai coding成果"
ICO_PATH = os.path.join(FOLDER, "app_icon.ico")

img = Image.open(PNG_SRC).convert("RGBA")
img.save(ICO_PATH, format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(f"ICO saved: {ICO_PATH}")
