# -*- coding: utf-8 -*-
"""
处理图片：去除背景，保留角色，生成 ICO 图标
改进版：用容差 flood fill 从边缘扩散，保护头发
"""
from PIL import Image, ImageFilter
import numpy as np
from collections import deque

SRC = r"c:\Users\Telecon\.trae-cn\attachments\6a82c0f4d2657931e5f08f61\803d4ba4-62f7-4ec5-b43c-ef590936b10a_438dbb97-c5c7-4e6f-a469-d0797ff4be53_30447196c2fb1a5a6d6f0b7206537ffe_4343884620260224746.jpg"
OUT_PNG = r"C:\Users\Telecon\Desktop\app_icon.png"
OUT_ICO = r"C:\Users\Telecon\Desktop\app_icon.ico"

def remove_background():
    img = Image.open(SRC).convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]
    r, g, b = arr[:,:,0].astype(int), arr[:,:,1].astype(int), arr[:,:,2].astype(int)

    # 绝对保护的角色区域
    is_skin    = (r > 165) & (g > 135) & (b > 135) & (r >= g)
    is_orange  = (r > 140) & (g > 50) & (g < 170) & (b < 130)
    is_white   = (r > 190) & (g > 190) & (b > 190)
    is_eye_blue= (b > 80) & (b < 200) & (r < 120) & (g < 120) & (b > r + 10)
    is_eye_purple = (b > 80) & (r > 60) & (r < 160) & (b > r) & (g < 110)
    protected = is_skin | is_orange | is_white | is_eye_blue | is_eye_purple

    # 用容差 flood fill 从边缘扩散背景
    # 计算亮度，背景普遍很暗
    brightness = (r + g + b) // 3

    visited = np.zeros((h, w), dtype=bool)
    is_bg = np.zeros((h, w), dtype=bool)
    queue = deque()

    # 从边缘暗色像素开始
    edge_thresh = 100
    for x in range(w):
        for y in [0, h-1]:
            if brightness[y, x] < edge_thresh and not protected[y, x]:
                queue.append((y, x)); visited[y, x] = True; is_bg[y, x] = True
    for y in range(h):
        for x in [0, w-1]:
            if brightness[y, x] < edge_thresh and not protected[y, x]:
                queue.append((y, x)); visited[y, x] = True; is_bg[y, x] = True

    # 容差扩散：与已标记背景颜色相近且未被保护的像素也标记为背景
    tol = 45
    while queue:
        cy, cx = queue.popleft()
        cr, cg, cb = r[cy, cx], g[cy, cx], b[cy, cx]
        for dy, dx in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
            ny, nx = cy+dy, cx+dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and not protected[ny, nx]:
                nr, ng, nb = r[ny, nx], g[ny, nx], b[ny, nx]
                if abs(nr-cr) <= tol and abs(ng-cg) <= tol and abs(nb-cb) <= tol:
                    visited[ny, nx] = True
                    is_bg[ny, nx] = True
                    queue.append((ny, nx))

    # 设置 alpha
    alpha = arr[:,:,3].copy()
    alpha[is_bg] = 0

    # 羽化边缘
    alpha_img = Image.fromarray(alpha, mode='L')
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=1.5))
    alpha = np.array(alpha_img)
    arr[:,:,3] = alpha

    # 边缘颜色净化（去除紫边）
    edge_mask = (alpha > 10) & (alpha < 245)
    for c in range(3):
        ch = arr[:,:,c].astype(float)
        ch[edge_mask & (ch < 80)] = 255 * 0.7
        arr[:,:,c] = ch.astype(np.uint8)
    arr[:,:,3] = alpha

    result = Image.fromarray(arr, mode='RGBA')

    # 裁剪到内容区域，但留一点边距
    bbox = result.getbbox()
    if bbox:
        pad = 10
        bbox = (max(0, bbox[0]-pad), max(0, bbox[1]-pad),
                min(w, bbox[2]+pad), min(h, bbox[3]+pad))
        result = result.crop(bbox)

    # 缩放到 256x256 居中
    target = 256
    max_dim = max(result.size)
    ratio = target / max_dim
    new_size = (int(result.size[0] * ratio), int(result.size[1] * ratio))
    result = result.resize(new_size, Image.LANCZOS)

    square = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    offset = ((target - new_size[0]) // 2, (target - new_size[1]) // 2)
    square.paste(result, offset, result)

    square.save(OUT_PNG)
    print(f"PNG saved: {OUT_PNG}")
    square.save(OUT_ICO, format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    print(f"ICO saved: {OUT_ICO}")
    print("Done!")

if __name__ == "__main__":
    remove_background()
