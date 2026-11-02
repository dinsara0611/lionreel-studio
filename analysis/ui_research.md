# UI Architecture & Design Research: Film-Editing Room Polish

Grounded in official standards (W3C WCAG 2.2, MDN Web Docs, web.dev, Apple Human Interface Guidelines, and Material Design Motion Guidance).

---

## 12 Foundational Decisions & Source Citations

### 1. Native Control Theming via `color-scheme`
- **Source**: [MDN Web Docs - color-scheme](https://developer.mozilla.org/en-US/docs/Web/CSS/color-scheme)
- **Official Rule**: Declaring `color-scheme: dark light;` (or switching between `color-scheme: dark;` and `color-scheme: light;` on `:root`) instructs the browser to automatically adapt default UI elements—including native scrollbars, form controls, inputs, and system popups—to the active theme.
- **Application**: Applied on `:root` and toggled synchronously with the app's `theme-dark` / `theme-light` class, guaranteeing native scrollbars and text inputs match custom tokens without third-party skinning.

### 2. Zero-Flash Theme Initialization via Early Execution
- **Source**: [web.dev - Building a theme switch component](https://web.dev/patterns/color-scheme/)
- **Official Rule**: To prevent Flash of Unstyled Theme (FOUT), read user preference (`localStorage`) or system preference (`window.matchMedia('(prefers-color-scheme: dark)')`) synchronously in the `<head>` before the DOM is painted, applying the root theme attribute/class immediately.
- **Application**: Inline synchronous `<script>` at the very top of `<head>` in `gui/index.html` resolves the active theme before CSS render-tree construction.

### 3. Contrast Ratios & Non-Text Element Legibility (WCAG 2.2 Level AA)
- **Source**: [W3C WCAG 2.2 - Success Criterion 1.4.3 Contrast (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) & [1.4.11 Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)
- **Official Rule**: Standard text requires at least a 4.5:1 luminance contrast ratio against its background (3:1 for text $\ge 18$pt or bold $\ge 14$pt). User interface components (borders, active button states, icons) require at least 3:1 contrast against adjacent background colors.
- **Application**: Color tokens strictly meet or exceed 4.5:1 for body copy and 3.0:1 for structural lines, badges, and focus rings in both dark and light palettes.

### 4. Apple HIG Layered Dark Elevation vs. Pure Black
- **Source**: [Apple Human Interface Guidelines - Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)
- **Official Rule**: Avoid pure `#000000` backgrounds behind high-contrast text to mitigate visual halation and eye fatigue. Layer surfaces using progressive lightness increments (e.g., base background, elevated card, floating modal) rather than heavy drop shadows or bright neon borders.
- **Application**: Dark theme uses a muted green-slate near-black base (`#0c100f`), secondary card surface (`#141918`), and tertiary elevated layer (`#1c2220`) with clean 1px hairline borders (`rgba(255,255,255,0.08)`).

### 5. Touch Target Minimum Size (Apple HIG & WCAG 2.2 SC 2.5.8)
- **Source**: [Apple Human Interface Guidelines - Target sizes](https://developer.apple.com/design/human-interface-guidelines/layout#Target-sizes) & [WCAG 2.2 Target Size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- **Official Rule**: Interactive controls on mobile or touch-enabled viewports must maintain an accessible hit area of at least 44×44 CSS pixels.
- **Application**: All buttons, inputs, segmented options, and icon controls expand padding or bounding box to meet $\ge 44$px on $\le 768$px viewports.

### 6. Tabular Numerals for Monospace Metrics
- **Source**: [MDN Web Docs - font-variant-numeric](https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric)
- **Official Rule**: Setting `font-variant-numeric: tabular-nums` forces numbers to share equal glyph widths, eliminating horizontal jitter and misalignment in timecodes, durations, byte sizes, and countdown meters.
- **Application**: Timecodes, durations (`0:30`, `19:52`), bitrates, file sizes, and countdown numbers explicitly declare `font-variant-numeric: tabular-nums` with monospace font fallbacks.

### 7. Flex and Grid Overflow Prevention via `min-width: 0`
- **Source**: [MDN Web Docs - CSS Grid Layout: minmax](https://developer.mozilla.org/en-US/docs/Web/CSS/minmax) & [CSS Flexible Box Layout](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_flexible_box_layout/Controlling_ratios_of_flex_items)
- **Official Rule**: Flex and grid items default to `min-width: auto`, which prevents children from shrinking below their content's intrinsic width, causing uncontained card overflows. Using `minmax(0, 1fr)` in grid definitions and `min-width: 0` on flex items restores shrink boundaries.
- **Application**: Applied to all `.job-card`, `.card-meta`, `.action-buttons`, and export summary items to guarantee no card button or metadata string ever overflows its bounding box.

### 8. Container Queries for Context-Aware Component Layout
- **Source**: [MDN Web Docs - CSS Container Queries](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_containment/Container_queries)
- **Official Rule**: Using `container-type: inline-size` allows components to adapt typography, metadata wrapping, and button collapse states based on their parent card width rather than global viewport width.
- **Application**: Job cards define `@container (max-width: 380px)` and `@container (max-width: 280px)` to dynamically collapse secondary buttons into icon-tooltips or a compact menu row without layout distortion.

### 9. High-Performance Transform & Opacity Animations
- **Source**: [web.dev - Animations guide](https://web.dev/articles/animations-guide)
- **Official Rule**: To achieve smooth 60fps/120fps motion without layout thrashing, restrict animations and transitions exclusively to compositor properties (`transform` and `opacity`). Never animate `width`, `height`, `margin`, `padding`, or `top/left`.
- **Application**: Transitions for buttons (scale 0.98), dialogs (fade and translate 8px), and loading meters exclusively manipulate `transform` and `opacity`.

### 10. Material Motion Duration and Easing Standards
- **Source**: [Material Design 3 - Motion: Duration and Easing](https://m3.material.io/styles/motion/easing-and-duration/tokens-specs)
- **Official Rule**: Micro-interactions (hover, focus, button press) should complete within 100–200ms. Medium structural transitions (tabs, menus, drawers) should complete within 200–300ms using asymmetric easing curves (`cubic-bezier(0.2, 0, 0, 1)` ease-out for entering, `cubic-bezier(0.3, 0, 1, 1)` ease-in for exiting).
- **Application**: All UI transitions use calibrated tokens (`--motion-duration-fast: 150ms`, `--motion-duration-normal: 250ms`) with clean acceleration curves and zero bouncing.

### 11. Accessible Motion Reduction (`prefers-reduced-motion`)
- **Source**: [MDN Web Docs - prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion)
- **Official Rule**: When users select reduced motion in system accessibility preferences, all non-essential movement, transitions, and loops should be replaced with instant or subtle opacity-only shifts.
- **Application**: `@media (prefers-reduced-motion: reduce)` zeroes duration or confines animation strictly to instant opacity transitions; the film leader animation replaces spinning with a clear, static progress indicator.

### 12. Accessible Progress Semantics & Non-Intrusive Live Regions
- **Source**: [W3C WAI-ARIA 1.2 - progressbar role](https://www.w3.org/TR/wai-aria-1.2/#progressbar) & [aria-live](https://www.w3.org/TR/wai-aria-1.2/#aria-live)
- **Official Rule**: Dynamic progress meters must expose `role="progressbar"`, `aria-valuenow`, `aria-valuemin="0"`, and `aria-valuemax="100"`. Stage updates must stream through an `aria-live="polite"` region to inform screen readers without interrupting ongoing speech.
- **Application**: The film leader loading modal incorporates semantic progressbar attributes and a dedicated live region broadcasting stage milestones.
