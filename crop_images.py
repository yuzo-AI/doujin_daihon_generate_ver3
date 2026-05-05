#!/usr/bin/env python3
"""
crop_images.py
台本.txt の【画像指示：P{n} - 「セリフ」のコマ】を元に
テキストブロック中心の細いスライスでガターを検出して1コマだけ切り出す。

Usage: python crop_images.py Output/YYYYMMDD/NN
"""

import json
import re
import sys
from pathlib import Path
import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).parent
IMAGE_DIR    = PROJECT_ROOT / "Input" / "Image"

# --- チューニングパラメータ ---
MATCH_THRESHOLD = 0.35   # セリフ文字一致率の閾値
BRIGHT_THRESHOLD = 210   # 「明るい（白い）ピクセル」の輝度閾値
GUTTER_RATIO     = 0.90  # ガター判定: スライス内の何割が明るければガターとみなすか
MIN_GUTTER_PX    = 8     # ガター判定に必要な連続px数（字間の2-5pxを除外）
SLICE_HALF       = 40    # 中心スライスの半幅(px): この幅でガターを探す
FALLBACK_PAD     = 100   # ガター未検出時の固定パディング(px)
MIN_PANEL_PX     = 80    # 検出結果がこれ以下 → フォールバック
MAX_PANEL_RATIO  = 0.60  # 検出面積が全画像のこれ以上 → フォールバック
MAX_SINGLE_DIM   = 600   # 幅または高さがこれ以上 → フォールバック（コマとみなさない）


def normalize(text):
    return re.sub(r'[\s。、・…．「」『』！？!?〜ー～\-]', '', text)


def char_overlap_score(serif, block_lines):
    serif_clean = normalize(serif)
    block_clean = normalize(''.join(block_lines))
    if not serif_clean:
        return 0.0
    return sum(1 for c in serif_clean if c in block_clean) / len(serif_clean)


def find_best_block(serif, blocks):
    best_score, best_block = 0.0, None
    for block in blocks:
        score = char_overlap_score(serif, block['lines'])
        if score > best_score:
            best_score, best_block = score, block
    return best_block, best_score


def scan_for_gutter_edge(bright_1d, start, direction):
    """
    start から direction(-1:上/左, +1:下/右) 方向に走査して
    MIN_GUTTER_PX 以上連続した明るい帯のコマ側エッジを返す。
    見つからない場合は配列端(0 or len)を返す。
    """
    n = len(bright_1d)
    run = 0
    run_start = None
    indices = range(start, -1, -1) if direction == -1 else range(start, n)
    for i in indices:
        if bright_1d[i] >= GUTTER_RATIO:
            if run == 0:
                run_start = i
            run += 1
            if run >= MIN_GUTTER_PX:
                return run_start
        else:
            run = 0
            run_start = None
    return 0 if direction == -1 else n


def find_panel_bounds(img, text_box):
    """
    テキストブロック中心(cx, cy)の「細いスライス」でガターを検出してコマ境界を返す。

    - 上下端検出: cx ± SLICE_HALF の縦スライスで「ほぼ真っ白な行」を探す
    - 左右端検出: cy ± SLICE_HALF の横スライスで「ほぼ真っ白な列」を探す

    隣ページ・隣コマの暗い領域が混入しないよう、スライスを細く限定することで
    誤判定を防ぐ。
    """
    arr = np.array(img.convert('L'))
    ih, iw = arr.shape

    bx1, by1, bx2, by2 = int(text_box[0]), int(text_box[1]), int(text_box[2]), int(text_box[3])
    cx = max(0, min((bx1 + bx2) // 2, iw - 1))
    cy = max(0, min((by1 + by2) // 2, ih - 1))

    # ── 上下端検出: cx中心の縦スライス ──
    # このスライスで「ほぼ真っ白な行」= コマとコマの間の水平ガター
    sx1 = max(0,  cx - SLICE_HALF)
    sx2 = min(iw, cx + SLICE_HALF)
    row_bright = (arr[:, sx1:sx2] > BRIGHT_THRESHOLD).mean(axis=1)  # (ih,)

    # ── 左右端検出: cy中心の横スライス ──
    # このスライスで「ほぼ真っ白な列」= コマとコマの間の垂直ガター
    sy1 = max(0,  cy - SLICE_HALF)
    sy2 = min(ih, cy + SLICE_HALF)
    col_bright = (arr[sy1:sy2, :] > BRIGHT_THRESHOLD).mean(axis=0)  # (iw,)

    y1 = scan_for_gutter_edge(row_bright, cy, -1)
    y2 = scan_for_gutter_edge(row_bright, cy, +1)
    x1 = scan_for_gutter_edge(col_bright, cx, -1)
    x2 = scan_for_gutter_edge(col_bright, cx, +1)

    pw, ph = x2 - x1, y2 - y1

    # サイズ異常チェック → フォールバック
    if (pw < MIN_PANEL_PX or ph < MIN_PANEL_PX
            or pw > MAX_SINGLE_DIM or ph > MAX_SINGLE_DIM
            or pw * ph > iw * ih * MAX_PANEL_RATIO):
        x1 = max(0,  bx1 - FALLBACK_PAD)
        y1 = max(0,  by1 - FALLBACK_PAD)
        x2 = min(iw, bx2 + FALLBACK_PAD)
        y2 = min(ih, by2 + FALLBACK_PAD)
        return (x1, y1, x2, y2), f"固定PAD{FALLBACK_PAD}px"

    return (x1, y1, x2, y2), "ガター検出OK"


def main():
    if len(sys.argv) < 2:
        print("Usage: python crop_images.py Output/YYYYMMDD/NN")
        sys.exit(1)

    output_dir  = PROJECT_ROOT / sys.argv[1]
    mokuro_path = output_dir / "_ocr" / "Image.mokuro"
    daihon_path = output_dir / "台本.txt"
    crop_dir    = output_dir / "切り出し"

    for p, label in [(mokuro_path, "Image.mokuro"), (daihon_path, "台本.txt")]:
        if not p.exists():
            print(f"ERROR: {label} が見つかりません: {p}")
            sys.exit(1)

    crop_dir.mkdir(exist_ok=True)

    with open(mokuro_path, encoding='utf-8') as f:
        mokuro = json.load(f)
    pages = mokuro['pages']

    daihon = daihon_path.read_text(encoding='utf-8')
    instructions = re.findall(r'【画像指示：P(\d+)\s*[-–]\s*(.+?)】', daihon)

    if not instructions:
        print("ERROR: 台本.txt に【画像指示：P{n} - ...】が見つかりません")
        sys.exit(1)

    print(f"\n切り出し開始: {len(instructions)}カット → {crop_dir}\n")
    skipped = 0

    for i, (page_num_str, content) in enumerate(instructions, 1):
        page_idx = int(page_num_str) - 1
        if page_idx >= len(pages):
            print(f"  {i:02d}.png  SKIP: P{page_num_str} はページ数を超えています")
            skipped += 1
            continue

        page     = pages[page_idx]
        img_file = IMAGE_DIR / page['img_path']
        if not img_file.exists():
            print(f"  {i:02d}.png  SKIP: {img_file.name} が見つかりません")
            skipped += 1
            continue

        img      = Image.open(img_file)
        out_path = crop_dir / f"{i:02d}.png"

        serif_match = re.search(r'「(.+?)」', content)
        if serif_match:
            serif = serif_match.group(1)
            best_block, score = find_best_block(serif, page['blocks'])
            if best_block and score >= MATCH_THRESHOLD:
                box, method = find_panel_bounds(img, best_block['box'])
                cropped = img.crop(box)
                detail  = f"{method}, score={score:.2f}"
            else:
                cropped = img
                detail  = f"全ページ(マッチ不可 score={score:.2f})"
        else:
            cropped = img
            detail  = "全ページ"

        cropped.save(out_path)
        label_text = content[:25] + ("…" if len(content) > 25 else "")
        print(f"  {i:02d}.png  P{page_num_str} {label_text}  [{detail}]")

    ok = len(instructions) - skipped
    print(f"\n完了: {ok}枚保存 / {skipped}枚スキップ")
    print(f"保存先: {crop_dir}")


if __name__ == '__main__':
    main()
