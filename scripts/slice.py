#!/usr/bin/env python3
"""把表情包大图切成单张，并生成 / 追加 mdocs 用的 meme.json。

用法:
    python3 scripts/slice.py           # 处理 captions.json 里有的全部 sheet
    python3 scripts/slice.py 04 05     # 只处理指定 stem，结果追加进 meme.json

约定:
    sheets/<stem>.png   源图（白底贴纸，行列不要求严格等分）
    captions.json       { "<stem>": [ { "id", "desc" }, ... ] }，行优先
    memes/<id>.png      切出来的单张（去白边、归属切割、最长边 360）
    meme.json           { "version": 1, "memes": [{ "id", "desc", "meme_name" }] }

做法:
    1. 按 captions 条数推断行列（9→3x3，12→4x3），再用投影 valley 微调格线；
    2. 非白像素按「最近格心」归属（避免共享刀线导致一边切了另一边还留着）；
    3. 每格取归属像素外接框，四周留 PAD，再抠掉与外框连通的白底。
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
INDEX = os.path.join(ROOT, "meme.json")
MAX_SIDE = 360
PAD = 10
WHITE = 248
EXT = "png"


def valleys(profile, expect, window=80):
    """在预期切口附近找最空的那一列/行。"""
    picks = []
    for e in expect:
        lo, hi = max(1, e - window), min(len(profile) - 1, e + window)
        seg = profile[lo:hi]
        picks.append(lo + int(min(range(len(seg)), key=lambda i: seg[i])))
    return picks


def infer_grid(n, width, height, row_profile):
    """由条数 + 行向留白推断 (rows, cols)。"""
    candidates = []
    for rows in range(1, n + 1):
        if n % rows == 0:
            candidates.append((rows, n // rows))
    if not candidates:
        raise ValueError(f"无法为 {n} 条 captions 推断行列")

    def gap_score(rows):
        if rows <= 1:
            return 0.0
        expect = [int(height * i / rows) for i in range(1, rows)]
        cuts = valleys(row_profile, expect)
        # 切口越空越好
        return -sum(row_profile[c] for c in cuts)

    # 优先接近方阵，再用行向留白打分
    def key(rc):
        rows, cols = rc
        return (abs(rows - cols), -gap_score(rows), abs(rows * height - cols * width))

    return min(candidates, key=key)


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


def connected_components(mask, width, height):
    """4-连通块。返回 [(pixels, cx, cy), ...]。"""
    seen = bytearray(width * height)
    comps = []
    for start in range(width * height):
        if not mask[start] or seen[start]:
            continue
        seen[start] = 1
        queue = deque([start])
        pixels = []
        sx = sy = 0
        while queue:
            idx = queue.popleft()
            pixels.append(idx)
            x, y = idx % width, idx // width
            sx += x
            sy += y
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    n = ny * width + nx
                    if mask[n] and not seen[n]:
                        seen[n] = 1
                        queue.append(n)
        n = len(pixels)
        comps.append((pixels, sx / n, sy / n))
    return comps


def cut_cells(sheet, rows, cols):
    """连通块整块归最近格心；粘连块再按像素拆，最后只渲染本格像素。

    - 整块归属：邻格越界碎边跟回自己的格心，避免「一边切了另一边还留着」
    - 粘连拆分：若一块里 <85% 像素同属一格，说明两张贴纸碰到了，对该块做 Voronoi
    """
    rgb = sheet.convert("RGB")
    gray = rgb.convert("L")
    width, height = gray.size
    gpx = gray.load()
    spx = rgb.load()
    col = [0] * width
    row = [0] * height
    mask = bytearray(width * height)
    for y in range(height):
        base = y * width
        for x in range(width):
            if gpx[x, y] < WHITE:
                col[x] += 1
                row[y] += 1
                mask[base + x] = 1

    xe = [int(width * i / cols) for i in range(1, cols)]
    ye = [int(height * i / rows) for i in range(1, rows)]
    xs = [0] + (valleys(col, xe) if xe else []) + [width]
    ys = [0] + (valleys(row, ye) if ye else []) + [height]

    centers = []
    for r in range(rows):
        for c in range(cols):
            centers.append(((xs[c] + xs[c + 1]) * 0.5, (ys[r] + ys[r + 1]) * 0.5))

    owner = [-1] * (width * height)
    boxes = [[width, height, -1, -1] for _ in centers]

    def nearest(x, y):
        best_i, best_d = 0, 1e18
        for i, (gx, gy) in enumerate(centers):
            d = (x - gx) * (x - gx) + (y - gy) * (y - gy)
            if d < best_d:
                best_d = d
                best_i = i
        return best_i

    def claim(idx, cell_i):
        owner[idx] = cell_i
        x, y = idx % width, idx // width
        box = boxes[cell_i]
        if x < box[0]:
            box[0] = x
        if y < box[1]:
            box[1] = y
        if x > box[2]:
            box[2] = x
        if y > box[3]:
            box[3] = y

    for pixels, cx, cy in connected_components(mask, width, height):
        # 整块先看质心；若块内像素多数已更靠近别的格心，说明两张贴纸粘连了，再按像素拆开
        votes = {}
        for idx in pixels:
            i = nearest(idx % width, idx // width)
            votes[i] = votes.get(i, 0) + 1
        primary = max(votes, key=votes.get)
        if votes[primary] >= 0.85 * len(pixels):
            for idx in pixels:
                claim(idx, primary)
        else:
            for idx in pixels:
                claim(idx, nearest(idx % width, idx // width))

    cells = []
    for i, (left, top, right, bottom) in enumerate(boxes):
        if right < 0:
            cells.append(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
            continue
        x0 = max(0, left - PAD)
        y0 = max(0, top - PAD)
        x1 = min(width, right + 1 + PAD)
        y1 = min(height, bottom + 1 + PAD)
        cell = Image.new("RGB", (x1 - x0, y1 - y0), (255, 255, 255))
        cpx = cell.load()
        for y in range(y0, y1):
            base = y * width
            for x in range(x0, x1):
                if owner[base + x] == i:
                    cpx[x - x0, y - y0] = spx[x, y]
        cells.append(make_transparent(cell))
    return cells


def load_index():
    if not os.path.isfile(INDEX):
        return {"version": 1, "memes": []}
    with open(INDEX, encoding="utf-8") as fh:
        raw = json.load(fh)
    memes = raw.get("memes") if isinstance(raw, dict) else None
    if not isinstance(memes, list):
        memes = []
    return {"version": int(raw.get("version", 1)) if isinstance(raw, dict) else 1, "memes": memes}


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    only = set(argv) if argv else None

    if not os.path.isdir(SHEETS):
        print("缺少 sheets/ 目录", file=sys.stderr)
        return 1
    with open(CAPTIONS, encoding="utf-8") as fh:
        captions = json.load(fh)

    os.makedirs(OUT, exist_ok=True)
    index = load_index()
    by_id = {str(m.get("id")): m for m in index["memes"] if isinstance(m, dict) and m.get("id")}
    order = [str(m.get("id")) for m in index["memes"] if isinstance(m, dict) and m.get("id")]

    processed = 0
    for name in sorted(os.listdir(SHEETS)):
        if not name.lower().endswith(".png"):
            continue
        stem = os.path.splitext(name)[0]
        if only is not None and stem not in only:
            continue
        entries = captions.get(stem)
        if not entries:
            print(f"跳过 {name}: captions.json 里缺 {stem}", file=sys.stderr)
            continue

        sheet = Image.open(os.path.join(SHEETS, name)).convert("RGB")
        gray = sheet.convert("L")
        width, height = gray.size
        gpx = gray.load()
        row_profile = [0] * height
        for y in range(height):
            for x in range(width):
                if gpx[x, y] < WHITE:
                    row_profile[y] += 1
        rows, cols = infer_grid(len(entries), width, height, row_profile)
        if rows * cols != len(entries):
            print(f"{name}: 推断 {rows}x{cols} 与 captions {len(entries)} 条不匹配", file=sys.stderr)
            return 1

        cells = cut_cells(sheet, rows, cols)
        for cell, entry in zip(cells, entries):
            meme_id = str(entry["id"]).strip()
            desc = str(entry.get("desc", "")).strip()
            if not meme_id:
                print(f"id 非法: {meme_id!r}", file=sys.stderr)
                return 1
            if not desc:
                print(f"{meme_id} 缺 desc", file=sys.stderr)
                return 1
            if max(cell.size) > MAX_SIDE:
                cell = cell.copy()
                cell.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            file_name = f"{meme_id}.{EXT}"
            cell.save(os.path.join(OUT, file_name), "PNG", optimize=True)
            rec = {"id": meme_id, "desc": desc, "meme_name": file_name}
            if meme_id in by_id:
                by_id[meme_id] = rec
            else:
                by_id[meme_id] = rec
                order.append(meme_id)
        processed += len(entries)
        print(f"{name} → {rows}x{cols} = {len(entries)} 张 ({EXT})")

    index["memes"] = [by_id[i] for i in order if i in by_id]
    with open(INDEX, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    total = 0
    for m in index["memes"]:
        path = os.path.join(OUT, m["meme_name"])
        if os.path.isfile(path):
            total += os.path.getsize(path)
    print(f"完成: 本轮 {processed} 张，索引共 {len(index['memes'])} 条 → memes/，约 {total / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
