# Export Page "Cockpit" UI Research & Design Decisions

**Document:** `analysis/export_research.md`  
**Date:** 2026-10-17  
**Scope:** Export / Publishing Screen (Step 5) Architecture  

---

## 1. Research Decisions & Official Guidelines

1. **Tabs vs. Single-View / Progressive Disclosure (Nielsen Norman Group)**  
   - *Guideline:* "Tabs are only appropriate when users need to alternate between distinct views without needing to see or compare their contents simultaneously. When users need to complete a sequential or holistic task (such as reviewing an export, copying metadata, and downloading assets), splitting primary content into tabs forces memory overhead, hidden errors, and unnecessary clicks."  
   - *Source:* [Nielsen Norman Group: Tabs, Used Right](https://www.nngroup.com/articles/tabs-used-right/) & [Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)  
   - *Rule Taken:* Eliminate the Publish / Files / Library tab switcher entirely. All critical tasks (Player inspection, Metadata publishing, Action rail, Finished filmstrip) remain simultaneously visible in a single viewport.

2. **Avoiding Tab Rows and Complex Nesting (GOV.UK & European Commission Design Systems)**  
   - *Guideline:* "Tabs hide content from users. Only use tabs if user research shows that users do not need to see content from multiple tabs at once. Avoid multiple rows of tabs or tabs nested within tabs."  
   - *Source:* [GOV.UK Design System: Tabs Component](https://design-system.service.gov.uk/components/tabs/) and [European Commission Design System: Navigation Components](https://ec.europa.eu/component-library/ec/components/tabs/)  
   - *Rule Taken:* Zero tabs in the DOM. Essential controls are positioned directly in their respective functional zones.

3. **Segmented Controls for Mutually Exclusive Options (Apple HIG)**  
   - *Guideline:* "Use a segmented control to offer a single choice from a small set of mutually exclusive options (typically 2 to 5). Do not use a segmented control as a tab bar that switches entire screen layouts; keep it tightly bound to the content it modifies."  
   - *Source:* [Apple Human Interface Guidelines: Segmented Controls](https://developer.apple.com/design/human-interface-guidelines/segmented-controls)  
   - *Rule Taken:* Use ONE single segmented control in Zone B for selecting the target platform (`YouTube Shorts`, `YouTube Video`, `TikTok`, `Instagram Reels`). Ineligible platforms are disabled with inline reason tooltips.

4. **Prominence & Hierarchy of Primary Actions (Material Design 3)**  
   - *Guideline:* "Every screen or view should have a single distinct primary action (Filled button). Secondary and tertiary actions (Tonal, Outlined, or Text buttons) must be visually subordinate to prevent visual competition."  
   - *Source:* [Material Design 3: Buttons Overview](https://m3.material.io/components/buttons/overview)  
   - *Rule Taken:* ONE primary action button in Zone B ("Upload to <platform>") and ONE primary action button in Zone C ("Download MP4"). Secondary tools (Report, Folder, Copy Path) use quiet outline styling.

5. **Action Rails & Vertical Tool Columns in Production NLEs (DaVinci Resolve / Premiere Pro Export Spaces)**  
   - *Guideline:* "Professional digital audio/video workstations group output delivery settings into a center inspection panel while dedicating the right-hand margin to an action rail (Render queue, Master export, Folder location, Report diagnostics)."  
   - *Source:* Blackmagic DaVinci Resolve 19 Delivery Workspace Design Pattern & Adobe Premiere Pro Export Mode.  
   - *Rule Taken:* Establish Zone C (Right 24%) as the dedicated Action Rail with full-width action buttons that never wrap or overflow.

6. **WCAG 2.2 Target Size & Non-Text Contrast (W3C)**  
   - *Guideline:* "Target Size (Minimum) (Level AA 2.5.8): Interactive targets must measure at least 24x24 CSS pixels, with 44x44 CSS pixels recommended for mobile touch targets (Level AAA 2.5.5). Non-text elements like button boundaries and status indicators must achieve 3:1 contrast against adjacent backgrounds."  
   - *Source:* [W3C WCAG 2.2 Understanding Target Size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) and [Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)  
   - *Rule Taken:* Ensure all desktop buttons maintain minimum 36px height (touch targets >= 44px on mobile 390px). Contrast ratios strictly exceed 4.5:1 (text) and 3:1 (borders/icons).

7. **Aspect Ratio Preservation Without Letterbox Contamination (MDN Web Docs)**  
   - *Guideline:* "Using CSS `aspect-ratio` on the media player container guarantees the container geometry exactly matches the media's natural aspect ratio, preventing artificial page-added black bars or pillarboxes."  
   - *Source:* [MDN: CSS aspect-ratio](https://developer.mozilla.org/en-US/docs/Web/CSS/aspect-ratio) & [web.dev: Aspect Ratio](https://web.dev/articles/aspect-ratio)  
   - *Rule Taken:* Zone A player box uses dynamic `aspect-ratio` matching video stream (9:16 for short, 16:9 for long). Object-fit is `cover`/`contain` without container-added black margins.

8. **Reduced Motion & Predictable Micro-Interactions (web.dev)**  
   - *Guideline:* "Animations should be restrained, predictable, and strictly scoped to transform and opacity with durations between 120ms and 250ms. Always respect `prefers-reduced-motion`."  
   - *Source:* [web.dev: prefers-reduced-motion](https://web.dev/articles/prefers-reduced-motion)  
   - *Rule Taken:* Zero parallax, zero blur filters, zero bouncy transitions. 150ms ease transitions on interactive states, disabled when `prefers-reduced-motion: reduce` is active.

---

## 2. Wireframe Options Evaluated

### Option 1: Stacked Card Model (Rejected)
```
+-------------------------------------------------------------+
| Header: Title + Status                                      |
+-------------------------------------------------------------+
| [ Player (Left 50%) ]   | [ Card 1: Publish Details (50%) ] |
|                         | [ Card 2: File Tools (50%)      ] |
|                         | [ Card 3: Library (50%)         ] |
+-------------------------------------------------------------+
```
*Reason for Rejection:* Stacked vertical cards on the right column force vertical scrolling at 1280x720, breaking the zero-page-scroll contract and cramping the filmstrip.

### Option 2: Cockpit 4-Zone Studio Model (Chosen)
```
+----------------------------------------------------------------------------------------+
| HEADER: Status Badge, Title, One "New compilation" Button                             |
+----------------------------------------------------------------------------------------+
| ZONE A: PLAYER (36%)   | ZONE B: PUBLISH (40%)             | ZONE C: ACTION RAIL (24%) |
| Video in real ratio    | Platform Segmented Control        | Download MP4 (Size)       |
| Monospace specs line   | Upload to <Platform> Primary      | Production Report         |
| Status chips w/ reasons| Title (2-line wrap, score badge)  | 16:9 Thumbnail (Long only)|
| (Quality, Length, Rep) | Description (3-line internal)     | Open Folder               |
| Corner mute button     | Hashtags (2-line wrap)            | Copy Path                 |
|                        | Copy buttons + Copy All + Fresh   | More Menu (Cache, Delete) |
+----------------------------------------------------------------------------------------+
| ZONE D: FILMSTRIP (Bottom full-width, max 96px high)                                  |
| [Real Frame 1] [Real Frame 2] [Real Frame 3] ... (Scrolls horizontally inside strip)  |
+----------------------------------------------------------------------------------------+
```
*Selection Reason:* Perfectly balances inspection, distribution, and file actions on a single screen with zero document scrollbars at both 1440x900 and 1280x720, placing all essential actions immediately at hand.
