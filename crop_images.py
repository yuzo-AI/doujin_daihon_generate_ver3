#!/usr/bin/env python3
"""
crop_images.py
台本.txt の【画像指示：P{n} - 「セリフ」のコマ】を元に
mokuro の座標を使ってコマを自動切り出しし、連番 PNG で保存する。

Usage: python crop_images.py Output/YYYYMMDD/NN
"""

import json
import re
import sys
from pathlib import Path
from PIL import Image

PROJECT_ROOT = Path(__file__).parent
IMAGE_DIR = PROJECT_ROOT / "Input" / "Image"
PADDING = 200  # コマ周囲の余白 (px)
MATCH_THRESHOLD = 0.35  # OCRノイズを考慮して低めに設定


def normalize(text):
    """マッチング用: 記号・空白を除去"""
    return re.sub(r'[\s。、・…．「」『』！？!?〜ー～\-]', '', text)


def char_overlap_score(serif, block_lines):
    """セリフとブロックテキストの文字重複率を返す（OCRエラーに強い）"""
    serif_clean = normalize(serif)
    block_clean = normalize(''.join(block_lines))
    if not serif_clean:
        return 0.0
    matching = sum(1 for c in serif_clean if c in block_clean)
    return matching / len(serif_clean)


def find_best_block(serif, blocks):
    best_score = 0.0
    best_block = None
    for block in blocks:
        score = char_overlap_score(serif, block['lines'])
        if score > best_score:
            best_score = score
            best_block = block
    return best_block, best_score


def crop_with_padding(img, box, padding=PADDING):
    w, h = img.size
    x1 = max(0, int(box[0]) - padding)
    y1 = max(0, int(box[1]) - padding)
    x2 = min(w, int(box[2]) + padding)
    y2 = min(h, int(box[3]) + padding)
    return img.crop((x1, y1, x2, y2))


def main():
    if len(sys.argv) < 2:
        print("Usage: python crop_images.py Output/YYYYMMDD/NN")
        sys.exit(1)

    output_dir = PROJECT_ROOT / sys.argv[1]
    mokuro_path = output_dir / "_ocr" / "Image.mokuro"
    daihon_path = output_dir / "台本.txt"
    crop_dir = output_dir / "切り出し"

    for p, label in [(mokuro_path, "Image.mokuro"), (daihon_path, "台本.txt")]:
        if not p.exists():
            print(f"ERROR: {label} が見つかりません: {p}")
            sys.exit(1)

    crop_dir.mkdir(exist_ok=True)

    with open(mokuro_path, encoding='utf-8') as f:
        mokuro = json.load(f)
    pages = mokuro['pages']

    daihon = daihon_path.read_text(encoding='utf-8')
    # 【画像指示：P{n} - {content}】 にマッチ（最後の誘導用画像はPがないのでスキップされる）
    instructions = re.findall(r'【画像指示：P(\d+)\s*[-–]\s*(.+?)】', daihon)

    if not instructions:
        print("ERROR: 台本.txt に【画像指示：P{n} - ...】が見つかりません")
        sys.exit(1)

    print(f"\n切り出し開始: {len(instructions)}カット → {crop_dir}\n")
    skipped = 0

    for i, (page_num_str, content) in enumerate(instructions, 1):
        page_idx = int(page_num_str) - 1

        if page_idx >= len(pages):
            print(f"  {i:02d}.png  SKIP: P{page_num_str} はページ数({len(pages)})を超えています")
            skipped += 1
            continue

        page = pages[page_idx]
        img_file = IMAGE_DIR / page['img_path']

        if not img_file.exists():
            print(f"  {i:02d}.png  SKIP: 画像ファイルが見つかりません: {img_file.name}")
            skipped += 1
            continue

        img = Image.open(img_file)
        out_path = crop_dir / f"{i:02d}.png"

        serif_match = re.search(r'「(.+?)」', content)
        if serif_match:
            serif = serif_match.group(1)
            best_block, score = find_best_block(serif, page['blocks'])
            if best_block and score >= MATCH_THRESHOLD:
                cropped = crop_with_padding(img, best_block['box'])
                method = f"コマ切り出し (score={score:.2f})"
            else:
                cropped = img
                method = f"全ページ (マッチ不可 score={score:.2f})"
        else:
            # 「表紙」など → 全ページ
            cropped = img
            method = "全ページ"

        cropped.save(out_path)
        label = content[:25] + ("…" if len(content) > 25 else "")
        print(f"  {i:02d}.png  P{page_num_str} {label}  [{method}]")

    ok = len(instructions) - skipped
    print(f"\n完了: {ok}枚保存 / {skipped}枚スキップ")
    print(f"保存先: {crop_dir}")


if __name__ == '__main__':
    main()
