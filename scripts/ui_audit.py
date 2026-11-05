"""
Measures every page in both themes at each width, using the installed Chrome.

    python scripts/ui_audit.py --base http://127.0.0.1:8200 --out analysis/screenshots/after [--shots-at 1440,390]

Writes audit.json next to the screenshots. The audit only reads the page.
"""
import argparse
import json
import os
import sys

from playwright.sync_api import sync_playwright

PAGES = {"library": 1, "create": 2, "sources_edit": 3, "render": 4, "export": 5}
MODALS = {"cleanup": "openSafeCleanupModal"}
WIDTHS = {1920: 1080, 1440: 900, 1280: 800, 768: 1024, 390: 844}

MEASURE = r"""
() => {
  const vw = document.documentElement.clientWidth;
  const visible = el => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const inScroller = el => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if ((o === 'auto' || o === 'scroll') && p !== document.body && p !== document.documentElement) return true;
      if (o === 'hidden' && p !== document.body && p !== document.documentElement) return true;
    }
    return false;
  };
  const label = el => {
    const id = el.id ? '#' + el.id : '';
    const cls = (typeof el.className === 'string' && el.className) ? '.' + el.className.trim().split(/\s+/)[0] : '';
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 28);
    return `${el.tagName.toLowerCase()}${id}${cls} "${text}"`;
  };
  const toRgb = c => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).map(Number);
    return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1};
  };
  const lum = c => {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const bgOf = el => {
    for (let p = el; p; p = p.parentElement) {
      const c = toRgb(getComputedStyle(p).backgroundColor);
      if (c && c.a >= 0.99) return c;
      if (getComputedStyle(p).backgroundImage !== 'none') return null;
    }
    return {r: 255, g: 255, b: 255, a: 1};
  };
  const out = {hscroll: document.documentElement.scrollWidth > vw + 1, scrollWidth: document.documentElement.scrollWidth, vw,
               overflow: [], small_text: [], small_touch: [], clipped: [], low_contrast: [], no_label: []};
  const root = document.querySelector('.modal-overlay.active, .modal-overlay[style*="flex"]') || document.querySelector('.workspace-view.active') || document.body;
  const scope = [...root.querySelectorAll('*'), ...document.querySelectorAll('header *, .top-bar *')];
  const seen = new Set();
  for (const el of scope) {
    if (seen.has(el) || !visible(el) || el.closest('svg')) continue;
    seen.add(el);
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (r.right > vw + 1 && !inScroller(el)) out.overflow.push(label(el));
    const ownText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (ownText) {
      if (parseFloat(s.fontSize) < 13) out.small_text.push(`${label(el)} ${s.fontSize}`);
      const bg = bgOf(el), fg = toRgb(s.color);
      if (bg && fg && fg.a >= 0.99) {
        const a = lum(fg), b = lum(bg);
        const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        const large = parseFloat(s.fontSize) >= 18.66 || (parseFloat(s.fontSize) >= 14 && +s.fontWeight >= 700);
        if (ratio < (large ? 3 : 4.5)) out.low_contrast.push(`${label(el)} ${ratio.toFixed(2)}`);
      }
      if ((s.overflow === 'hidden' || s.overflowX === 'hidden') && s.whiteSpace !== 'normal' && el.scrollWidth > el.clientWidth + 1 && s.textOverflow !== 'ellipsis') out.clipped.push(label(el));
    }
    if (el.matches('button, a[href], input:not([type=hidden]), select, textarea, [role=button]')) {
      if (r.height < 44 || r.width < 44) out.small_touch.push(`${label(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
      if (el.matches('button, [role=button]') && !(el.innerText || '').trim() && !el.getAttribute('aria-label') && !el.title) out.no_label.push(label(el));
    }
  }
  for (const k of Object.keys(out)) if (Array.isArray(out[k])) out[k] = [...new Set(out[k])];
  return out;
}
"""


def focus_ring(page):
    return page.evaluate("""() => {
      const b = document.querySelector('.workspace-view.active button:not([disabled]), header button');
      if (!b) return null;
      b.focus({focusVisible: true});
      const s = getComputedStyle(b);
      const ok = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 1;
      b.blur();
      return ok;
    }""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8200")
    ap.add_argument("--out", required=True)
    ap.add_argument("--shots-at", default="1440,390")
    args = ap.parse_args()
    shots = {int(w) for w in args.shots_at.split(",") if w}
    os.makedirs(args.out, exist_ok=True)
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for width, height in WIDTHS.items():
            for theme in ("dark", "light"):
                ctx = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)[:200]))
                page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
                page.goto(args.base, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1200)
                page.evaluate("t => applyTheme(t)", theme)
                assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == theme
                for name, step in PAGES.items():
                    page.evaluate("n => navigateToStep(n)", step)
                    page.wait_for_timeout(450)
                    key = f"{name}/{theme}/{width}"
                    report[key] = page.evaluate(MEASURE)
                    report[key]["focus_ring"] = focus_ring(page)
                    if width in shots:
                        page.screenshot(path=os.path.join(args.out, f"{name}_{theme}_{width}.png"), full_page=False)
                for name, fn in MODALS.items():
                    page.evaluate("n => navigateToStep(n)", 1)
                    try:
                        page.evaluate(f"() => {fn}()")
                        page.wait_for_timeout(900)
                        key = f"{name}/{theme}/{width}"
                        report[key] = page.evaluate(MEASURE)
                        if width in shots:
                            page.screenshot(path=os.path.join(args.out, f"{name}_{theme}_{width}.png"))
                    except Exception as e:
                        report[f"{name}/{theme}/{width}"] = {"error": str(e)[:200]}
                report[f"console/{theme}/{width}"] = {"errors": sorted(set(errors))[:12]}
                ctx.close()
        browser.close()
    with open(os.path.join(args.out, "audit.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    totals = {k: 0 for k in ("overflow", "small_text", "small_touch", "clipped", "low_contrast", "no_label")}
    hscroll = 0
    for v in report.values():
        hscroll += 1 if v.get("hscroll") else 0
        for k in totals:
            totals[k] += len(v.get(k, []))
    print("hscroll pages:", hscroll, "totals:", totals, "pages measured:", len(report))


if __name__ == "__main__":
    sys.exit(main())
