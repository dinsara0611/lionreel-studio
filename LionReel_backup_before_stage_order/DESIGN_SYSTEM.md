# LionReel Studio — Design System Specification

## Overview
LionReel Studio is an advanced video slicing and compilation suite for short-form creators. This design system establishes a consistent, professional, and accessible user experience across all 5 workflow stages.

---

## 1. Design Tokens

### 1.1 Color Tokens
The palette preserves LionReel's signature dark-green studio aesthetic while delivering an accessible light theme with contrast ratios meeting or exceeding WCAG AA standards (≥ 4.5:1 normal text, ≥ 3.0:1 UI controls and large text).

| Token | Dark Theme (Default) | Light Theme | Description |
| :--- | :--- | :--- | :--- |
| `--bg` | `#07130C` | `#F4F8F5` | Main application background |
| `--surface` | `#0C1F14` | `#FFFFFF` | Primary surface (cards, panels) |
| `--surface-2` | `#112A1B` | `#E8F1EC` | Secondary surface (inputs, tracks) |
| `--surface-3` | `#163523` | `#DCE9E1` | Elevated surface (hover, active) |
| `--border` | `#143823` | `#C8DCD0` | Subtle component borders |
| `--border-strong` | `#1D4F31` | `#9DBFA9` | High-contrast structural dividers |
| `--text` | `#E6F4EC` | `#0E2417` | High-emphasis body and headings |
| `--text-muted` | `#84A993` | `#355C44` | Secondary text, sub-labels (≥ 4.5:1) |
| `--text-faint` | `#587D67` | `#4F735D` | Tertiary indicators, captions |
| `--accent` | `#18E87A` | `#0A8F47` | Primary emerald brand accent |
| `--accent-hover` | `#23F586` | `#087A3C` | Hover state for accent buttons |
| `--accent-contrast` | `#041A0E` | `#FFFFFF` | High-contrast text on accent surfaces |
| `--info` | `#60A5FA` | `#2563EB` | Informational chips and highlights |
| `--warn` | `#FACC15` | `#B45309` | Cautionary filter bypass warnings |
| `--danger` | `#F87171` | `#DC2626` | Destructive actions, failure states |
| `--success` | `#34D399` | `#059669` | Success badges, verified stages |
| `--focus` | `#18E87A` | `#0A8F47` | Visible keyboard focus ring |

### 1.2 Spacing Grid (8px Base)
All margins, paddings, and layout gaps adhere strictly to the 8px spatial grid:
- `--space-1`: `4px` (half-unit)
- `--space-2`: `8px` (1 unit)
- `--space-3`: `12px` (1.5 units)
- `--space-4`: `16px` (2 units)
- `--space-6`: `24px` (3 units)
- `--space-8`: `32px` (4 units)
- `--space-12`: `48px` (6 units)

### 1.3 Border Radius Scale
- `--radius-sm`: `6px` (badges, small inputs)
- `--radius-md`: `8px` (standard buttons, chips, menu items)
- `--radius-lg`: `12px` (content cards, form sections)
- `--radius-xl`: `16px` (hero panels, modals)
- `--radius-full`: `9999px` (pills, badges, toggle sliders)

### 1.4 Elevation Scale (Soft Shadows)
- Level 1 (`--shadow-sm`): `0 2px 4px rgba(0, 0, 0, 0.2)`
- Level 2 (`--shadow-md`): `0 4px 12px rgba(0, 0, 0, 0.28)`
- Level 3 (`--shadow-lg`): `0 12px 32px rgba(0, 0, 0, 0.4)`
- Light theme shadows are softened (`rgba(10, 40, 20, 0.08)`) with zero dirty or radioactive glow.

### 1.5 Typography Scale
Font families: Inter / System UI for headings and body; JetBrains Mono / SF Mono for telemetry, numbers, and code.
- `32px` (`2.0rem`, line-height `1.2`, weight `800`): Hero titles
- `24px` (`1.5rem`, line-height `1.3`, weight `700`): Section titles
- `20px` (`1.25rem`, line-height `1.35`, weight `700`): Card headings
- `16px` (`1.0rem`, line-height `1.45`, weight `600`): Component titles, large buttons
- `14px` (`0.88rem`, line-height `1.5`, weight `500`): Standard body, form labels (minimum 14px for labels)
- `13px` (`0.81rem`, line-height `1.4`, weight `500`): Sub-descriptions, chip text
- `12px` (`0.75rem`, line-height `1.35`, weight `600`): Badges, telemetry tags (minimum 12px for any text)

### 1.6 Motion Tokens
Transitions animate only GPU-accelerated properties (`transform` and `opacity`):
- `--transition-fast`: `120ms cubic-bezier(0.2, 0.8, 0.2, 1)`
- `--transition-normal`: `200ms cubic-bezier(0.2, 0.8, 0.2, 1)`
- `--transition-slow`: `300ms cubic-bezier(0.2, 0.8, 0.2, 1)`
- Honored by `@media (prefers-reduced-motion: reduce)` which sets duration to `0.01ms`.

### 1.7 Page Container
- `--page-max-width: 1200px` centered via `margin: 0 auto; width: 100%;`.
- Shared uniformly by the sticky header (`.app-header`), main viewport (`.app-viewport`), wizard stages, and the bottom docked summary bar (`.live-summary-box`). All components align perfectly flush to the 1200px outer boundaries.

---

## 2. Vendored SVG Icon Set (Lucide)

### 2.1 Specification
- **Library**: Lucide Icons (ISC License).
- **Delivery**: Inline SVG sprite `<svg id="lionreel-icon-sprite">` injected into `gui/index.html`. Zero CDN requests, zero runtime network dependencies, zero icon fonts.
- **Styling**: Every icon renders with `fill="none" stroke="currentColor"` and `stroke-width="2"` (or `1.75`), inheriting colors naturally from theme tokens.
- **Size Scale**:
  - `icon-sm`: `14px` / `16px` (chips, inline buttons)
  - `icon-md`: `18px` / `20px` (standard buttons, action rows)
  - `icon-lg`: `24px` / `28px` (collection cards, template headers)
  - `icon-inline`: `1.25em` height, vertically aligned with adjacent text.

### 2.2 Icon Mapping Reference
| Semantic Role | Lucide Symbol ID | Usage |
| :--- | :--- | :--- |
| Feline / Cat | `#icon-cat` | Feline collection, cat templates |
| Canine / Dog | `#icon-dog` | Canine collection, dog templates |
| Pet Duo / Mix | `#icon-paw-print` | Cats & Dogs Duo card, cute pet templates |
| Short Video | `#icon-zap` | Short Reel button, fast cuts, summary pill |
| Long Video | `#icon-clapperboard` | Long video format, compilation switcher |
| Both Formats | `#icon-layers` | Dual render mode |
| Clip Count | `#icon-layers` | Clips counter, sequential sequence |
| Clip Duration | `#icon-timer` | Per-moment duration stepper |
| Refresh / Sync | `#icon-refresh-cw` | Refresh library, reload |
| Reset / Clean | `#icon-rotate-ccw` | Reset history, restore defaults |
| Delete / Purge | `#icon-trash-2` | Delete video, remove clip |
| Copy / Duplicate | `#icon-copy` | Copy metadata, edit in studio |
| Download | `#icon-download` | Master MP4 download |
| Open / Link | `#icon-external-link` | Open finished compilation, studio link |
| Play | `#icon-play` | Playback trigger, preview thumbnail |
| Stop / Cancel | `#icon-square` | Cancel render pipeline |
| Success / Verified | `#icon-check`, `#icon-circle-check` | Quality checks, verified stages |
| Failure / Reject | `#icon-circle-x` | Failed state card, rejected candidate |
| Warning / Alert | `#icon-triangle-alert` | Filter bypass warning, pool low alert |
| Info | `#icon-info` | Information badges, tooltips |
| Muted Audio | `#icon-volume-x` | Unmute hint pill |
| Active Audio | `#icon-volume-2` | Audio levels check, sound profile |
| Theme Toggle | `#icon-sun`, `#icon-moon` | Light / Dark switcher |
| Settings | `#icon-settings` | Fine-tune in editor |
| Filters / Shield | `#icon-shield-check`, `#icon-shield`| 11 Quality verifications, AI shield |
| Watermark Scan | `#icon-scan-eye` | Watermark detector |
| Framing / Crop | `#icon-crop` | Smart crop, aspect ratio selector |
| Mobile 9:16 | `#icon-smartphone` | 9:16 vertical shorts badge |
| Color Grading | `#icon-palette` | CLAHE tone mapping card |
| Slicing / Cuts | `#icon-scissors` | Moment cutting engine |
| Credits / Users | `#icon-badge-check`, `#icon-users` | Credits panel, creator avatar |
| Folder / Staging | `#icon-folder` | Open local folder, studio library tab |
| Console Terminal | `#icon-terminal` | Live engine output drawer |
| Cartoon Filter | `#icon-shapes` | 2D animation filter |
| Ad / Promo Filter | `#icon-megaphone-off`, `#icon-ban` | Anti-ad post filter |

### 2.3 How to Add a New Icon
1. Locate the SVG icon definition from the official Lucide library.
2. Ensure `<svg>` attributes use `viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"`.
3. Wrap as a `<symbol id="icon-[name]" viewBox="0 0 24 24">` element.
4. Append inside `<svg id="lionreel-icon-sprite">` in `gui/index.html`.
5. Render anywhere in HTML via `<svg class="icon icon-[size]"><use href="#icon-[name]"></use></svg>` or in JS via `window.getIconSvg('[name]', '[size]')`.

---

## 3. Component Library Guidelines

- **Buttons**: Equal height (sm: 28-32px, md: 38-42px, lg: 48px), consistent padding, visible focus ring with `3px var(--green-glow)`.
- **Segmented Controls & Chips**: 8px grid spacing, equal-width grids (`minmax(88px, 1fr)`), active state using `--accent` border and soft green tint.
- **Sliders & Selects**: Native styling replaced with custom emerald thumbs and custom SVGs.
- **Summary Bar**: Centered within the 1200px container, 32px top scrim gradient to softly fade background text, 12px viewport gap, Lucide leading icon, middle dot separators (`·`), and multiplication sign (`×`).
- **Audit Table**: Sticky header, monospace aligned numerical values, badges for PASS/REJECT, expandable detail rows with Lucide chevron SVG toggles, source tooltips.
- **Console Terminal**: Bounded to 1000 lines maximum to prevent DOM memory leaks, converting status glyphs into clean ASCII tags (`[PASS]`, `[FAIL]`, `[WARN]`).
- **Responsive Behavior (390px Mobile)**: 1-column card stacking, zero horizontal overflow, minimum 44px touch targets.
