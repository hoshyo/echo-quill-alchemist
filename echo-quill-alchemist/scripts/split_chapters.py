"""按章节标题把整本小说拆成多份 markdown 文件。

输出：
  <output-dir>/chapter-001.md, chapter-002.md, ...
  stdout: JSON 摘要 {chapter_count, char_counts, pattern_used, warnings}

用法：
  python split_chapters.py --input "novel.txt" --output-dir "out_dir"
  python split_chapters.py --input "novel.txt" --output-dir "out_dir" --pattern "^第[一二三四五六七八九十百千〇零\\d]+[章回卷篇]"
"""

import argparse
import json
import os
import re
import sys


PRESET_PATTERNS = [
    # 中文：第N章/回/卷/篇
    r"^[\s　]*第[一二三四五六七八九十百千零〇\d]+[章回卷篇](?:[\s　].*)?$",
    # 英文：Chapter 1 / Chapter 1: Title / Chapter I
    r"^Chapter\s+(?:\d+|[IVXLCM]+)\b.*$",
    # 数字编号：1. 标题  /  1 标题
    r"^\d{1,4}[\.\s　][^\n]{0,80}$",
]


def detect_pattern(text: str):
    """选择匹配数最多的预设 pattern。要求至少匹配 3 个章节标题。"""
    best = None
    best_count = 0
    for pat in PRESET_PATTERNS:
        regex = re.compile(pat, flags=re.MULTILINE)
        count = len(regex.findall(text))
        if count > best_count:
            best_count = count
            best = pat
    if best_count < 3:
        return None, best_count
    return best, best_count


def split_text(text: str, pattern: str):
    """按章节标题切分。返回 [(title_line, body_text), ...]"""
    regex = re.compile(pattern, flags=re.MULTILINE)
    matches = list(regex.finditer(text))
    if not matches:
        return []

    chapters = []
    for i, m in enumerate(matches):
        title_line = m.group(0).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip("\r\n").strip()
        chapters.append((title_line, body))
    return chapters


def write_chapters(chapters, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    char_counts = []
    for idx, (title, body) in enumerate(chapters, start=1):
        filename = f"chapter-{idx:03d}.md"
        path = os.path.join(output_dir, filename)
        content = f"# {title}\n\n{body}\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        char_counts.append({"index": idx, "title": title, "chars": len(body), "file": filename})
    return char_counts


def read_input(path: str) -> str:
    encodings = ["utf-8", "utf-8-sig", "gb18030", "gbk", "big5"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(
        "tried", b"", 0, 1,
        f"failed to decode {path} with any of {encodings}",
    )


def main():
    parser = argparse.ArgumentParser(description="Split a novel into chapter files.")
    parser.add_argument("--input", required=True, help="path to the full novel file")
    parser.add_argument("--output-dir", required=True, help="directory to write chapter-NNN.md")
    parser.add_argument("--pattern", default=None, help="custom regex (multiline) for chapter titles")
    parser.add_argument("--min-chapters", type=int, default=3, help="abort if detected chapters < this (default 3)")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(json.dumps({"error": f"input file not found: {args.input}"}, ensure_ascii=False))
        sys.exit(2)

    text = read_input(args.input)

    if args.pattern:
        pattern = args.pattern
        regex = re.compile(pattern, flags=re.MULTILINE)
        match_count = len(regex.findall(text))
        if match_count == 0:
            print(json.dumps({"error": "custom pattern matched 0 lines", "pattern": pattern}, ensure_ascii=False))
            sys.exit(3)
    else:
        pattern, match_count = detect_pattern(text)
        if pattern is None:
            print(json.dumps({
                "error": "no preset pattern matched at least 3 chapter titles",
                "best_match_count": match_count,
                "hint": "pass --pattern '<regex>' to specify a custom chapter title regex",
            }, ensure_ascii=False))
            sys.exit(4)

    chapters = split_text(text, pattern)

    if len(chapters) < args.min_chapters:
        print(json.dumps({
            "error": f"split produced {len(chapters)} chapters, below min-chapters={args.min_chapters}",
            "pattern_used": pattern,
        }, ensure_ascii=False))
        sys.exit(5)

    char_counts = write_chapters(chapters, args.output_dir)

    warnings = []
    short_chapters = [c for c in char_counts if c["chars"] < 200]
    if short_chapters:
        warnings.append(f"{len(short_chapters)} chapter(s) are unusually short (< 200 chars); possible mis-split")

    summary = {
        "chapter_count": len(chapters),
        "pattern_used": pattern,
        "output_dir": os.path.abspath(args.output_dir),
        "chapters": char_counts,
        "warnings": warnings,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
