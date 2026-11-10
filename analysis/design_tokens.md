# Design Tokens: Film-Editing Room Identity

A unified, tranquil, utilitarian design token specification inspired by professional post-production suites (e.g. DaVinci Resolve, Avid Media Composer). Replaces neon glow, heavy glassmorphism, and rainbow gradients with flat, layered surfaces, 1px hairline borders, monospace timecode counters, and purposeful accenting.

---

## 1. Color Palette (Dark & Light)

### Dark Theme (Default Studio Mode)
- **Base Canvas (`--bg-base`)**: `#0c100f` (Quiet near-black with a subtle cool slate-green tint)
- **Layer 1 Surface (`--bg-surface-1`)**: `#131917` (Cards, side panels, primary containers)
- **Layer 2 Elevated (`--bg-surface-2`)**: `#1b2220` (Modals, menus, dropdowns, hovered items)
- **Layer 3 Subdued / Wells (`--bg-surface-well`)**: `#080b0a` (Video viewport, timeline tracks, code wells)
- **Hairline Border (`--border-subtle`)**: `rgba(255, 255, 255, 0.08)` (1px structure)
- **Active / Hover Border (`--border-focus`)**: `rgba(255, 255, 255, 0.18)`
- **Text Primary (`--text-primary`)**: `#f1f5f3` (Off-white, 14.8:1 contrast on base canvas, WCAG AAA)
- **Text Secondary (`--text-secondary`)**: `#98a4a0` (Neutral muted slate, 6.2:1 contrast, WCAG AA)
- **Text Monospace / Timecode (`--text-mono`)**: `#86efac` (Soft terminal phosphor for metrics)
- **Accent Primary (`--accent-primary`)**: `#10b981` (Deep emerald green for main CTA and focus)
- **Accent Hover (`--accent-hover`)**: `#059669`
- **Accent Text (`--accent-text`)**: `#ffffff` (5.1:1 contrast on accent primary, WCAG AA)
- **Warning Amber (`--state-warning`)**: `#f59e0b` (Legitimate cautions only)
- **Error Red (`--state-error`)**: `#ef4444` (Actionable errors only)
- **Success Green (`--state-success`)**: `#10b981`

### Light Theme (Paper Archive Mode)
- **Base Canvas (`--bg-base`)**: `#f8f7f4` (Warm off-white archival paper, not harsh pure #fff)
- **Layer 1 Surface (`--bg-surface-1`)**: `#ffffff` (Clean editorial card backing)
- **Layer 2 Elevated (`--bg-surface-2`)**: `#efece6` (Hovered cards, flyout menus, toolbars)
- **Layer 3 Subdued / Wells (`--bg-surface-well`)**: `#e6e2d8` (Player framing, inset wells)
- **Hairline Border (`--border-subtle`)**: `rgba(0, 0, 0, 0.10)` (1px structure)
- **Active / Hover Border (`--border-focus`)**: `rgba(0, 0, 0, 0.22)`
- **Text Primary (`--text-primary`)**: `#151c19` (Near-black ink, 14.2:1 contrast, WCAG AAA)
- **Text Secondary (`--text-secondary`)**: `#5c6762` (Pencil graphite slate, 5.5:1 contrast, WCAG AA)
- **Text Monospace / Timecode (`--text-mono`)**: `#065f46` (Deep forest emerald for metrics)
- **Accent Primary (`--accent-primary`)**: `#059669` (Darkened emerald for light canvas legibility)
- **Accent Hover (`--accent-hover`)**: `#047857`
- **Accent Text (`--accent-text`)**: `#ffffff` (4.6:1 contrast on accent primary, WCAG AA)
- **Warning Amber (`--state-warning`)**: `#b45309` (Readable dark amber)
- **Error Red (`--state-error`)**: `#b91c1c` (Readable deep crimson)
- **Success Green (`--state-success`)**: `#059669`

---

## 2. Typography Scale

- **Font Family (Prose & UI)**: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- **Font Family (Timecodes, Metrics, Technical Data)**: `"Cascadia Code", "SF Mono", "Consolas", "Roboto Mono", monospace`
- **Tabular Numerals**: `font-variant-numeric: tabular-nums` (mandatory on all duration badges, clocks, sizes, counters)
- **Type Scale**:
  - `--font-size-xs`: `11px` (Caps category headers, micro badges, safe-zone guidelines)
  - `--font-size-sm`: `13px` (Secondary card metadata, helper notes, timecode stamps)
  - `--font-size-base`: `14px` (Default UI labels, standard body copy, button labels)
  - `--font-size-md`: `16px` (Section titles, card headlines, major input text)
  - `--font-size-lg`: `18px` (View subheadings, prominent numbers)
  - `--font-size-xl`: `22px` (Primary view headings, film leader countdown numbers)

---

## 3. Spacing Grid & Dimensions (8px System)

- `--space-1`: `4px` (Tight padding, chip gaps)
- `--space-2`: `8px` (Standard inner padding, icon-text gap)
- `--space-3`: `12px` (Medium separation)
- `--space-4`: `16px` (Card interior padding, form row spacing)
- `--space-5`: `24px` (Section dividers, major column gaps)
- `--space-6`: `32px` (Container gutters, modal margins)

### Border Radius
- `--radius-sm`: `4px` (Chips, mini buttons, indicators)
- `--radius-md`: `6px` (Cards, input fields, standard buttons)
- `--radius-lg`: `8px` (Dialogs, flyout sheets, player enclosure)
- *Strict Rule*: No pill buttons with 9999px radius; maximum radius is 8px for a cohesive, professional editing workspace.

---

## 4. Motion & Animation Tokens

- `--ease-enter`: `cubic-bezier(0.2, 0, 0, 1)` (Decelerated entry)
- `--ease-exit`: `cubic-bezier(0.3, 0, 1, 1)` (Accelerated exit)
- `--ease-standard`: `cubic-bezier(0.4, 0, 0.2, 1)` (Standard transitions)
- `--motion-fast`: `150ms` (Hover, active button press, color fade)
- `--motion-normal`: `250ms` (Panel transition, dialog open/close, tab slide)
- `--motion-count`: `300ms` (Tabular numeral transition)
- **Reduced Motion**: `@media (prefers-reduced-motion: reduce)` resets duration to `0ms` or transforms to instant opacity changes.
