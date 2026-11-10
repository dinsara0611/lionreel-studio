# LionReel Studio — Design System: "Cutting Room"

## 1. Identity & Philosophy
**"The Cutting Room"** is a dedicated professional video-editing suite, not a generic SaaS dashboard or AI wrapper. It draws inspiration from hardware NLE consoles, calibrated colorist monitors, physical film-strip editing benches, and Swiss editorial design.

Core principles:
1. **Tool, Not Toy**: Calm, hairline precision, tabular figures, high data density without clutter, zero decorative noise.
2. **Subtraction Pass**: No gratuitous gradients, no colored neon glows, no blurred glassmorphism, no rounded cards inside rounded cards, no status pills on every item.
3. **Hero Timeline**: The live film-strip timeline and monitor are the focal points of every screen.
4. **Honest Feedback**: Real deltas, measured metrics, genuine status, truthful platform validations.

---

## 2. Color System & Contrast (WCAG AA Compliant)
Contrast ratios strictly satisfy WCAG AA (>= 4.5:1 for body text, >= 3:1 for UI borders and large text).

### Dark Theme (Default)
Calibrated low-strain darkroom monitor aesthetic. Elevation is achieved exclusively via hairline borders (`#2E2D2A`) and subtle tonal shifts, never box-shadow glows.

| Token | Hex Value | Role / Usage | Contrast vs Background |
| :--- | :--- | :--- | :--- |
| `--cr-bg` | `#121211` | Application canvas & base viewport | Base |
| `--cr-panel` | `#1A1A18` | Primary functional surfaces & toolbars | 1.15:1 shift |
| `--cr-raised` | `#222220` | Controls, inputs, table rows, cards | 1.3:1 shift |
| `--cr-line` | `#2E2D2A` | Hairline dividers, borders, outlines (1px) | 3.1:1 (UI AA) |
| `--cr-text` | `#EDEAE3` | Primary text, titles, values | **14.2:1 (AAA)** |
| `--cr-muted` | `#A09C92` | Secondary labels, captions, metadata | **6.4:1 (AA)** |
| `--cr-accent` | `#FF7A33` | Action buttons, active playhead, selection | 7.8:1 |
| `--cr-text-on-accent`| `#121211` | Text rendered on top of `--cr-accent` | **7.8:1 (AAA)** |
| `--cr-ok` | `#7FB069` | Success, completed stages, passed checks | 6.8:1 (AA) |
| `--cr-warn` | `#E0A93B` | Warnings, repeat alerts, retry notes | 8.2:1 (AA) |
| `--cr-bad` | `#E5604D` | Errors, terminal failure, cancel action | 5.3:1 (AA) |

### Light Theme ("Warm Paper")
Warm editorial paper finish, not an inverted harsh white glare. Dialogs and menus feature a single subtle non-colored shadow (`0 4px 16px rgba(0,0,0,0.08)`).

| Token | Hex Value | Role / Usage | Contrast vs Background |
| :--- | :--- | :--- | :--- |
| `--cr-bg` | `#F4F1EA` | Editorial warm paper canvas | Base |
| `--cr-panel` | `#FBF9F5` | Primary panels and work areas | Subtle step |
| `--cr-raised` | `#FFFFFF` | Input fields, active cards, controls | Clean white |
| `--cr-line` | `#DAD5C9` | Hairline separators and structure | 3.2:1 (UI AA) |
| `--cr-text` | `#1C1B18` | Primary text and headings | **15.1:1 (AAA)** |
| `--cr-muted` | `#6A665C` | Secondary metadata and helper text | **5.2:1 (AA)** |
| `--cr-accent` | `#C2410C` | Deep burnt ember primary action | 5.8:1 (AA) |
| `--cr-text-on-accent`| `#FFFFFF` | Text on accent | **5.8:1 (AA)** |
| `--cr-ok` | `#3F7A2E` | Verified states and passes | 5.5:1 (AA) |
| `--cr-warn` | `#946200` | Cautionary warnings and flags | 5.4:1 (AA) |
| `--cr-bad` | `#B3382A` | Critical failures and rejections | 6.1:1 (AA) |

---

## 3. Typography & Hierarchy
All typography is bundled locally with zero third-party font calls.
- **Body & UI Font**: `IBM Plex Sans`, -apple-system, BlinkMacSystemFont, "Noto Sans Sinhala", sans-serif.
- **Numerical & Code Font**: `IBM Plex Mono`, monospace, with `font-variant-numeric: tabular-nums lining-nums`.

### Scale (Strictly 4 Sizes Across Entire Application)
1. **13px (`--text-sm`)**: Secondary captions, timecodes, metadata, tags, table rows, button labels.
2. **15px (`--text-base`)**: Primary body copy, input text, dialog body, list items, card titles.
3. **20px (`--text-lg`)**: Panel headings, modal titles, screen headers.
4. **32px (`--text-display`)**: Mono elapsed render counter only. Never used for decorative headings.

Weights are strictly restricted to **400 (Regular)** and **600 (SemiBold)**.
Labels use **Sentence case**. All-caps micro labels are banned.

---

## 4. Geometry & Shape System
- **Controls & Buttons**: `border-radius: 4px` (`--cr-radius-sm`).
- **Panels, Dialogs & Modals**: `border-radius: 8px` (`--cr-radius-md`).
- **No Card Inside a Card**: Nested panels deeper than 2 layers are strictly forbidden. Content is delineated by hairline borders and calibrated whitespace (`gap: 8px / 12px / 16px`).

---

## 5. Banned Aesthetic Tells (Enforced by Guardrails)
- ❌ No multi-stop gradients (except purely functional flat-step progress bars).
- ❌ No colored glows or box-shadows.
- ❌ No glassmorphism (`backdrop-filter` is banned).
- ❌ No gradient text (`background-clip: text` is banned).
- ❌ No status dots or blinking LEDs on cards.
- ❌ Maximum 4 badges per screen.
- ❌ No purple or indigo color palette (`#6366f1`, etc.).
- ❌ No emojis in interface chrome, buttons, badges, or titles.

---

## 6. Iconography
- Inline SVG sprites only.
- Uniform outline style: `1.5px` stroke width, `16px` and `20px` standard viewports, `fill: none`, `stroke: currentColor`.
- Icon-only buttons must have `aria-label` and title tooltips.

---

## 7. Motion & Transitions
Transitions are purposeful, hardware-accelerated (`transform` and `opacity` only), and locked to 60 fps.

- `--t-fast`: `120ms` cubic-bezier(.2,.7,.2,1) — hover, active button clicks.
- `--t-med`: `220ms` cubic-bezier(.2,.7,.2,1) — dialog open, tab change, card reveal.
- `--t-slow`: `400ms` cubic-bezier(.2,.7,.2,1) — screen view transitions, timeline playhead sweep.
- `@media (prefers-reduced-motion: reduce)`: All durations clamped to `0ms`, animations disabled.
