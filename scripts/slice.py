#!/usr/bin/env python3
"""把 3x3 表情包大图切成单张 webp，并生成 mdocs 用的 meme.json。

用法:
    python3 scripts/slice.py

约定:
    sheets/<stem>.png   一张 3x3 大图（内容大体均分九宫格）
    captions.json       { "<stem>": [ { "id", "desc" }, ... 9 条，行优先 ] }
    memes/<id>.webp     切出来的单张（去白边、清掉邻格残边、最长边 360）
    meme.json           { "version": 1, "memes": [{ "id", "desc", "meme_name" }] }

做法:
    1. 横竖都不是严格三等分（相邻贴纸会溢出格线），所以按「每行的空白列」找切口；
    2. 切口仍会带进邻居的一点边角，用连通块过滤：贴着格子边缘又很小的碎块直接丢掉；
    3. 剩下的按外接框裁紧，四周留 PAD。
"""
import json
import os
import sys
from collections import deque

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHEETS = os.path.join(ROOT, "sheets")
OUT = os.path.join(ROOT, "memes")
CAPTIONS = os.path.join(ROOT, "captions.json")
MAX_SIDE = 360
PAD = 10
WHITE = 248
# 贴边碎块小于这个比例就当邻格残留丢掉
SLIVER_RATIO = 0.03


def valleys(profile, expect, window=80):
    """在预期切口附近找最空的那一列/行。"""
    picks = []
    for e in expect:
        lo, hi = max(1, e - window), min(len(profile) - 1, e + window)
        seg = profile[lo:hi]
        picks.append(lo + int(min(range(len(seg)), key=lambda i: seg[i])))
    return picks


def drop_edge_slivers(mask, width, height):
    """把贴着格子边缘、又明显偏小的连通块抹掉（邻格残留）。"""
    seen = bytearray(width * height)
    keep = bytearray(width * height)
    limit = SLIVER_RATIO * width * height
    for start in range(width * height):
        if not mask[start] or seen[start]:
            continue
        seen[start] = 1
        queue = deque([start])
        comp = []
        touches = False
        while queue:
            idx = queue.popleft()
            comp.append(idx)
            x, y = idx % width, idx // width
            if x == 0 or y == 0 or x == width - 1 or y == height - 1:
                touches = True
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    n = ny * width + nx
                    if mask[n] and not seen[n]:
                        seen[n] = 1
                        queue.append(n)
        if touches and len(comp) < limit:
            continue
        for idx in comp:
            keep[idx] = 1
    return keep


def make_transparent(im):
    """把与外框连通的白色背景抠掉（内部白点，如高光，不受影响）。"""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    bg = bytearray(w * h)
    queue = deque()
    def near_white(x, y):
        r, g, b, _ = px[x, y]
        return r >= 240 and g >= 240 and b >= 240
    for x in range(w):
        for y in (0, h - 1):
            if near_white(x, y) and not bg[y * w + x]:
                bg[y * w + x] = 1
                queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if near_white(x, y) and not bg[y * w + x]:
                bg[y * w + x] = 1
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not bg[ny * w + nx] and near_white(nx, ny):
                bg[ny * w + nx] = 1
                queue.append((nx, ny))
    for y in range(h):
        for x in range(w):
            if bg[y * w + x]:
                r, g, b, _ = px[x, y]
                px[x, y] = (r, g, b, 0)
    return im


def cut_cells(sheet):
    """按内容留白切九宫格，返回 9 张 RGB 图（行优先）。"""
    gray = sheet.convert("L")
    width, height = gray.size
    px = gray.load()
    col = [0] * width
    row = [0] * height
    for y in range(height):
        for x in range(width):
            if px[x, y] < WHITE:
                col[x] += 1
                row[y] += 1
    xs = [0] + valleys(col, [width // 3, (width * 2) // 3]) + [width]
    ys = [0] + valleys(row, [height // 3, (height * 2) // 3]) + [height]

    cells = []
    for r in range(3):
        for c in range(3):
            boxes = (xs[c], ys[r], xs[c + 1], ys[r + 1])
            cell = sheet.crop(boxes)
            cw, ch = cell.size
            g = cell.convert("L")
            gp = g.load()
            mask = bytearray(cw * ch)
            for y in range(ch):
                base = y * cw
                for x in range(cw):
                    if gp[x, y] < WHITE:
                        mask[base + x] = 1
            keep = drop_edge_slivers(mask, cw, ch)
            left, top, right, bottom = cw, ch, -1, -1
            for y in range(ch):
                base = y * cw
                for x in range(cw):
                    if keep[base + x]:
                        if x < left:
                            left = x
                        if x > right:
                            right = x
                        if y < top:
                            top = y
                        if y > bottom:
                            bottom = y
            if right < 0:
                cells.append(cell)
                continue
            trimmed = cell.crop(
                (
                    max(0, left - PAD),
                    max(0, top - PAD),
                    min(cw, right + 1 + PAD),
                    min(ch, bottom + 1 + PAD),
                )
            )
            cells.append(make_transparent(trimmed))
    return cells


def main() -> int:
    if not os.path.isdir(SHEETS):
        print("缺少 sheets/ 目录", file=sys.stderr)
        return 1
    with open(CAPTIONS, encoding="utf-8") as fh:
        captions = json.load(fh)

    os.makedirs(OUT, exist_ok=True)
    memes = []
    seen = set()

    for name in sorted(os.listdir(SHEETS)):
        if not name.lower().endswith(".png"):
            continue
        stem = os.path.splitext(name)[0]
        entries = captions.get(stem)
        if not entries or len(entries) != 9:
            print(f"跳过 {name}: captions.json 里缺 {stem} 或不是 9 条", file=sys.stderr)
            continue

        sheet = Image.open(os.path.join(SHEETS, name)).convert("RGB")
        cells = cut_cells(sheet)
        for cell, entry in zip(cells, entries):
            meme_id = str(entry["id"]).strip()
            desc = str(entry.get("desc", "")).strip()
            if not meme_id or meme_id in seen:
                print(f"id 非法或重复: {meme_id}", file=sys.stderr)
                return 1
            if not desc:
                print(f"{meme_id} 缺 desc", file=sys.stderr)
                return 1
            seen.add(meme_id)
            if max(cell.size) > MAX_SIDE:
                cell = cell.copy()
                cell.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            file_name = f"{meme_id}.webp"
            cell.save(os.path.join(OUT, file_name), "WEBP", quality=88, method=6)
            memes.append({"id": meme_id, "desc": desc, "meme_name": file_name})
        print(f"{name} → 9 张")

    with open(os.path.join(ROOT, "meme.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "memes": memes}, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    total = sum(os.path.getsize(os.path.join(OUT, m["meme_name"])) for m in memes)
    print(f"完成: {len(memes)} 张 → memes/，共 {total / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
