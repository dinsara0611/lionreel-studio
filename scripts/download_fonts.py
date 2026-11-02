import os
import urllib.request
import re

FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "fonts")
os.makedirs(FONTS_DIR, exist_ok=True)

# URL for IBM Plex Sans & IBM Plex Mono Latin WOFF2 subsets
CSS_URL = "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,400;0,600&family=IBM+Plex+Sans:ital,wght@0,400;0,600&display=swap"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def main():
    print(f"Fetching Google Fonts manifest from {CSS_URL}...")
    req = urllib.request.Request(CSS_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        css = resp.read().decode('utf-8')

    # Parse @font-face blocks specifically for latin subset
    blocks = re.findall(r'/\* latin \*/\s*@font-face\s*\{([^}]+)\}', css, re.DOTALL)
    print(f"Found {len(blocks)} latin font-face blocks.")

    local_css_rules = []
    total_bytes = 0

    for idx, b in enumerate(blocks):
        family_m = re.search(r"font-family:\s*['\"]([^'\"]+)['\"];", b)
        weight_m = re.search(r"font-weight:\s*(\d+);", b)
        style_m = re.search(r"font-style:\s*([a-z]+);", b)
        url_m = re.search(r"src:\s*url\((https://[^\)]+\.woff2)\)", b)

        if not (family_m and weight_m and url_m):
            continue

        family = family_m.group(1)
        weight = weight_m.group(1)
        style = style_m.group(1) if style_m else "normal"
        url = url_m.group(1)

        safe_fam = family.lower().replace(" ", "-")
        filename = f"{safe_fam}-{weight}-{style}.woff2"
        filepath = os.path.join(FONTS_DIR, filename)

        print(f"Downloading {filename} from {url}...")
        f_req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(f_req, timeout=10) as f_resp:
            data = f_resp.read()
            with open(filepath, "wb") as f_out:
                f_out.write(data)
            sz = len(data)
            total_bytes += sz
            print(f"  -> Saved {filename} ({sz / 1024:.1f} KB)")

        local_css_rules.append(f"""@font-face {{
  font-family: '{family}';
  font-style: {style};
  font-weight: {weight};
  font-display: swap;
  src: url('fonts/{filename}') format('woff2');
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
}}""")

    fonts_css_path = os.path.join(FONTS_DIR, "fonts.css")
    with open(fonts_css_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(local_css_rules) + "\n")

    print(f"\nFonts bundling complete! Total downloaded: {total_bytes / 1024:.1f} KB (Budget: <= 160 KB)")
    print(f"CSS declarations written to: {fonts_css_path}")

if __name__ == "__main__":
    main()
