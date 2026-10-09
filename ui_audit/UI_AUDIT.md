# LionReel Studio — UI Visual & Architectural Audit

**Document Version**: Phase 1 Baseline Audit  
**Date**: October 9, 2026  
**Environment**: Antigravity Dev Server (`http://localhost:8000`)  
**Target Viewports**: Desktop 1440×900, Mobile 390×844 (Dark and Light themes)

---

## 1. Visual Capture Baseline Summary

Complete screenshot sets captured using headless Chrome (`channel: "chrome"`) at both viewports (1440×900 and 390×844) across Dark and Light modes:

| Screen / Component | Dark 1440px | Dark 390px | Light 1440px | Light 390px |
|---|:---:|:---:|:---:|:---:|
| **Header & Theme Toggle** | `ui_audit/dark/header_theme_1440.png` | `ui_audit/dark/header_theme_390.png` | `ui_audit/light/header_theme_1440.png` | `ui_audit/light/header_theme_390.png` |
| **Create (Step 1 Animal Cards)** | `ui_audit/dark/step1_create_animal_cards_1440.png` | `ui_audit/dark/step1_create_animal_cards_390.png` | `ui_audit/light/step1_create_animal_cards_1440.png` | `ui_audit/light/step1_create_animal_cards_390.png` |
| **Sources (Step 2 Pool & Discovery)** | `ui_audit/dark/step2_sources_1440.png` | `ui_audit/dark/step2_sources_390.png` | `ui_audit/light/step2_sources_1440.png` | `ui_audit/light/step2_sources_390.png` |
| **Edit (Step 3 Config & Sliders)** | `ui_audit/dark/step3_edit_config_1440.png` | `ui_audit/dark/step3_edit_config_390.png` | `ui_audit/light/step3_edit_config_1440.png` | `ui_audit/light/step3_edit_config_390.png` |
| **Summary Bar (Step 3 Docked)** | `ui_audit/dark/step3_summary_bar_1440.png` | `ui_audit/dark/step3_summary_bar_390.png` | `ui_audit/light/step3_summary_bar_1440.png` | `ui_audit/light/step3_summary_bar_390.png` |
| **Render (Step 4 Progress Card)** | `ui_audit/dark/step4_render_progress_1440.png` | `ui_audit/dark/step4_render_progress_390.png` | `ui_audit/light/step4_render_progress_1440.png` | `ui_audit/light/step4_render_progress_390.png` |
| **Render (Step 4 Audit & Failed State)** | `ui_audit/dark/step4_render_failed_audit_1440.png` | `ui_audit/dark/step4_render_failed_audit_390.png` | `ui_audit/light/step4_render_failed_audit_1440.png` | `ui_audit/light/step4_render_failed_audit_390.png` |
| **Export (Step 5 Details & Gallery)** | `ui_audit/dark/step5_export_1440.png` | `ui_audit/dark/step5_export_390.png` | `ui_audit/light/step5_export_1440.png` | `ui_audit/light/step5_export_390.png` |
| **Modals (Confirm Dialog)** | `ui_audit/dark/modal_confirm_1440.png` | `ui_audit/dark/modal_confirm_390.png` | `ui_audit/light/modal_confirm_1440.png` | `ui_audit/light/modal_confirm_390.png` |
| **Modals (Keyboard Shortcuts)** | `ui_audit/dark/modal_shortcuts_1440.png` | `ui_audit/dark/modal_shortcuts_390.png` | `ui_audit/light/modal_shortcuts_1440.png` | `ui_audit/light/modal_shortcuts_390.png` |
| **Modals (Video Preview Player)** | `ui_audit/dark/modal_preview_1440.png` | `ui_audit/dark/modal_preview_390.png` | `ui_audit/light/modal_preview_1440.png` | `ui_audit/light/modal_preview_390.png` |
| **Toasts & Live Notifications** | `ui_audit/dark/toast_notification_1440.png` | `ui_audit/dark/toast_notification_390.png` | `ui_audit/light/toast_notification_1440.png` | `ui_audit/light/toast_notification_390.png` |

---

## 2. Design System Inventory (Current State)

### 2.1 Typography & Fonts
- **Heading Font**: `'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
- **Body / Sans Font**: `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
- **Monospace Font**: `'Fira Code', monospace`
- **Font Sizes In Use** (41 separate font-size declarations):
  - Micro: `0.58rem` (8.7px), `0.62rem` (9.3px), `0.65rem` (9.75px), `0.68rem` (10.2px), `0.70rem` (10.5px), `0.72rem` (10.8px), `0.75rem` (11.25px). *Issue: violates minimum 12px requirement.*
  - Body: `0.80rem` (12px), `0.85rem` (12.75px), `0.88rem` (13.2px), `0.92rem` (13.8px), `1rem` (15px).
  - Headings: `1.1rem` (16.5px), `1.25rem` (18.75px), `1.4rem` (21px), `1.6rem` (24px), `2.2rem` (33px).
  - *Standardization Target*: 12, 13, 14, 16, 20, 24, 32px scale with consistent line-heights and minimum 12px for body, 14px for form labels.

### 2.2 Color Tokens & Hex Values
- **Identified Hex Colors**: 51 distinct hex values found across CSS and inline templates:
  - Dark Theme: `#06110C` (bg), `#0B2118` (surface), `#102B20` (surface-2), `#15382A` (card hover), `#18E87A` (accent), `#020805` (terminal/media surface), `#F3FAF6` (text), `#7A9B89` (text-muted), `#A7BDB0` (text-secondary).
  - Light Theme: `#F4FAF6` (bg), `#FFFFFF` (surface), `#E8F5EE` (surface-2), `#0A8F47` (accent), `#0E2417` (text), `#385644` (text-muted), `#244432` (text-secondary).
  - Feedback: `#5EAFFF` (info dark), `#1B67AF` (info light), `#F5B942` (warn dark), `#925400` (warn light), `#FF6674` (danger dark), `#BA2032` (danger light).
  - *Standardization Target*: Clean set of tokens: `--bg`, `--surface`, `--surface-2`, `--surface-3`, `--border`, `--border-strong`, `--text`, `--text-muted`, `--text-faint`, `--accent`, `--accent-hover`, `--accent-contrast`, `--info`, `--warn`, `--danger`, `--success`, `--focus`.

### 2.3 Radii & Elevation
- **Border Radii in Use**: `1px`, `4px`, `8px`, `12px`, `18px`, `24px`, `50%`, `9999px`.
  - *Standardization Target*: Strict 8px grid scale: 8px, 12px, 16px, 24px (plus 9999px for pills/avatars).
- **Shadows in Use**: 41 distinct `box-shadow` styles, including legacy glow effects (`--shadow-glow: 0 0 24px rgba(24, 232, 122, 0.22)`).
  - *Standardization Target*: 3 soft elevation levels (`--elevation-1`, `--elevation-2`, `--elevation-3`), clean rendering in light mode with zero dirty glow.

### 2.4 Spacing & Containers
- **Spacing In Use**: Mixed rem, pixel, and CSS variables (`--space-1` to `--space-12`).
  - *Standardization Target*: Strict 8px grid: 4, 8, 12, 16, 24, 32, 48px.
- **Page Container Width**:
  - Main viewport: `max-width: 1140px; margin: 0 auto;`
  - Export grid: `max-width: 1040px;` (misaligned)
  - Summary bar: `calc(100% - 48px)` (sticks out and wider than grid)
  - *Standardization Target*: Single unified `--container-max-width: 1200px` used identically by header, content grids, and summary bar.

### 2.5 Component Variations
- **Buttons**:
  - Classes: `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.btn-danger`, `.btn-icon`, `.upload-redirect-btn`, `.btn-refresh-sources`.
  - Inconsistency: Varying padding, inconsistent border-radius (`4px` vs `8px` vs `12px`), mixed font weights.
- **Badges**:
  - Classes: `.badge`, `.status-badge`, `.cycle-badge`, `.pool-badge`, `.candidate-badge`, `.resolution-badge`, `.badge-accent`.
  - Inconsistency: Inconsistent padding (`2px 6px` vs `4px 8px` vs `1px 4px`), microscopic font sizes (`0.58rem`).
- **Cards**:
  - Classes: `.animal-card`, `.collection-card`, `.config-group-card`, `.stage-card`, `.export-details-panel`, `.recent-card`.

---

## 3. Emoji & Symbol Audit

| Location | Character / Symbol | Codepoint / Entity | Current Usage | Replacement Plan |
|---|---|---|---|---|
| `gui/app.js:2565` | `▲` | `U+25B2` | Candidate audit table collapse chevron | Lucide SVG `<svg class="icon icon-chevron-up">` |
| `gui/app.js:2565` | `▼` | `U+25BC` | Candidate audit table expand chevron | Lucide SVG `<svg class="icon icon-chevron-down">` |
| `gui/app.js:2651` | `▼` | `U+25BC` | Table row expander placeholder | Lucide SVG `<svg class="icon icon-chevron-down">` |
| `gui/app.js:4921` | `✓✔✕✖⚠⚠️⚡🎉👑🎬🐾📁✅❌⏳` | Multiple | Log line cleanup regex | Retained in regex pattern (exempt from UI chrome) |
| `gui/app.js:2397` | `\u2705` | `U+2705` | Regex matching ACCEPTED log lines | Retained in regex pattern for pipeline engine compatibility |
| `gui/index.html` Title | Clean | N/A | `LionReel Studio — Advanced Video Slicing & Compilation Suite` | Maintained (no emojis) |
| Favicon | PNG | `gui/lion_logo.png` | PNG raster image | Create and link inline/static SVG favicon |
| Console Logs | Raw symbols / checkmarks | `✓`, `✗`, `ℹ` | Terminal log status lines | Tag badges `[PASS]`, `[FAIL]`, `[WARN]`, `[INFO]` + SVG icons |

---

## 4. UI Function Regression Baseline (From UI_FUNCTION_MATRIX.md)

All 12 critical functional capabilities verified intact:

1. **Animal Mode Toggles (Cats / Dogs / Duo)**: PASS
2. **Video Type Selector (Shorts vs Compilation)**: PASS
3. **Language Toggle (English / Sinhala)**: PASS
4. **Clip Count / Duration Target Sliders**: PASS
5. **Start / Generate Action Button**: PASS
6. **Reset / Cancel Action Button**: PASS
7. **Finished Video Gallery**: PASS
8. **QA Details Modal / 8-point Audit View**: PASS
9. **Clip Ledger & Pool Panel Status**: PASS
10. **Download / Master Export Actions**: PASS
11. **Settings / Config Persistence via `/api/config`**: PASS
12. **Responsive Centered Layout at Desktop & 390px**: PASS
