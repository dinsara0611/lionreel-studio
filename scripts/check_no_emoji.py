#!/usr/bin/env python3
"""
scripts/check_no_emoji.py

Scans HTML, CSS, JS, templates, and UI strings for emojis, variation selectors,
and emoji-like symbols (check marks, crosses, stars, dingbats, arrows, etc.).
Fails with exit code 1 and prints file, line number, character, and snippet.

Allowlist:
Only user-generated content fields (such as pipeline-generated video titles, captions, credits text)
are allowed to contain emojis. Interface chrome must have zero emojis.
"""

import sys
import os
import re
from pathlib import Path

# Regex patterns for emoji & emoji-like characters
# 1. Unicode emoji blocks:
EMOJI_PATTERN = re.compile(
    r"["
    r"\U0001F600-\U0001F64F"  # Emoticons
    r"\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
    r"\U0001F680-\U0001F6FF"  # Transport and Map
    r"\U0001F700-\U0001F77F"  # Alchemical Symbols
    r"\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    r"\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    r"\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    r"\U0001FA00-\U0001FA6F"  # Chess Symbols
    r"\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    r"\U00002600-\U000026FF"  # Miscellaneous Symbols (warning, gears, sun, moon, umbrella, etc.)
    r"\U00002700-\U000027BF"  # Dingbats (checkmarks, crosses, scissors, stars, etc.)
    r"\U0000231A-\U0000231B"  # Watch, Hourglass
    r"\U000023E9-\U000023F3"  # Media control buttons
    r"\U000023F8-\U000023FA"  # Media pause/stop/record
    r"\U00002B50-\U00002B55"  # Stars, circles
    r"\U0000FE0E-\U0000FE0F"  # Variation selectors
    r"\U000025A0-\U000025FF"  # Geometric shapes if rendered as symbols (like ⬛, ⬜, ⬢, ⬥)
    r"\u2705\u274C\u274E\u2728\u270C\u270F\u2714\u2716\u2712"
    r"✓✔✗✘✕✖★☆⭐⚡⚙⚠✂✨"
    r"]",
    re.UNICODE
)

# HTML entity check for emoji
HTML_ENTITY_PATTERN = re.compile(r"&#(?:x(?:1F[0-9A-Fa-f]{3}|26[0-9A-Fa-f]{2}|27[0-9A-Fa-f]{2})|[0-9]{4,6});")

# Escaped unicode in strings (e.g. \uD83C\uDF00 or \u2705 or \1F300)
ESCAPED_EMOJI_PATTERN = re.compile(
    r"(?:\\u[dD][89a-bA-B][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}"
    r"|\\u2[67][0-9a-fA-F]{2}"
    r"|\\[0-9a-fA-F]{4,6})"
)

# Allowlist: Lines matching these patterns or markers are exempt because they represent user-generated pipeline content
ALLOWLIST_PATTERNS = [
    # Allow comments explicitly referencing emoji policy or test assertions
    re.compile(r"check_no_emoji|test_no_emoji|NO_EMOJI|emoji allowlist", re.IGNORECASE),
    # Pipeline generated title/captions in mock data or credits data
    re.compile(r"(?:mock_video_title|generated_title|pipeline_caption|credits_text|sample_title)"),
]

def scan_file(filepath: Path):
    violations = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return [f"Could not read {filepath}: {e}"]

    for idx, line in enumerate(lines, start=1):
        # Check allowlist
        if any(pat.search(line) for pat in ALLOWLIST_PATTERNS):
            continue

        # Don't flag SVG path d="..." data which might contain coordinate numbers or letters
        # Check for literal emojis
        matches = list(EMOJI_PATTERN.finditer(line))
        if matches:
            for m in matches:
                char = m.group(0)
                codepoint = f"U+{ord(char):04X}"
                snippet = line.strip()[:80]
                violations.append((filepath, idx, codepoint, char, snippet))

        # Check for HTML entities
        ent_matches = list(HTML_ENTITY_PATTERN.finditer(line))
        if ent_matches:
            for m in ent_matches:
                entity = m.group(0)
                snippet = line.strip()[:80]
                violations.append((filepath, idx, entity, entity, snippet))

    return violations


def main():
    repo_root = Path(__file__).resolve().parent.parent
    target_dirs = [
        repo_root / "gui",
    ]
    
    # Also scan any html/css/js templates
    file_extensions = {".html", ".css", ".js", ".svg"}
    
    all_violations = []

    for target_dir in target_dirs:
        if not target_dir.exists():
            continue
        for root, dirs, files in os.walk(target_dir):
            for file in files:
                p = Path(root) / file
                if p.suffix.lower() in file_extensions:
                    violations = scan_file(p)
                    all_violations.extend(violations)

    print(f"=== LionReel Studio No-Emoji Audit ===")
    if not all_violations:
        print("[PASS] Zero emoji violations found in interface chrome!")
        sys.exit(0)
    else:
        print(f"[FAIL] Found {len(all_violations)} emoji/symbol violations:")
        print("-" * 80)
        for v in all_violations:
            if isinstance(v, str):
                print(v)
            else:
                fpath, line, codepoint, char, snippet = v
                rel_path = fpath.relative_to(repo_root) if fpath.is_relative_to(repo_root) else fpath
                print(f"  {rel_path}:{line} [{codepoint}] '{char}' -> {snippet}")
        print("-" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
