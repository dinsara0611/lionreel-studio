/**
 * LionReel Studio — Edit Step Guided Tour Strings & Step Definitions (i18n-ready)
 * English strings dictionary for Step 3 editor guided tour.
 * Zero emojis — strictly inline SVG icons.
 */

window.LIONREEL_TOUR_STRINGS = {
    locale: "en",
    ui: {
        instructionsButton: "Instructions",
        stepCounter: "Step {current} of {total}",
        back: "Back",
        next: "Next",
        skip: "Skip",
        done: "Done",
        newBadge: "New"
    },
    steps: [
        {
            id: "video-preview",
            selector: "#vertical-video-stage",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/></svg>`,
            title: "Your Video",
            description: "Review your loaded video here. Switch between Final rendered output, live Edit preview, and Before / after comparison. Player is muted by default with a quick unmute pill."
        },
        {
            id: "timeline-clips",
            selector: "#timeline-panel",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,
            title: "Clips",
            description: "Click any clip in the strip to inspect or edit it. Drag clips horizontally to reorder the sequence, remove unwanted clips, or swap them from your bank. Total length updates against your target."
        },
        {
            id: "trim-window",
            selector: "#trim-slider-wrap",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>`,
            title: "Trim Window",
            description: "Drag the start and end handles or enter exact seconds to adjust timing. Switch between Slide and Resize modes, snap straight to the funniest moment, or reset to auto-detected bounds."
        },
        {
            id: "funny-moment",
            selector: "#inspector-feedback-section",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>`,
            title: "Funny Moment",
            description: "Mark the exact peak funny moment with one click. Give a thumbs up or down and pick issue reasons to train the model on what makes great comedy."
        },
        {
            id: "framing-check",
            selector: "#trim-framing-status",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>`,
            title: "Framing Check",
            description: "See live pass/fail centering validation for your current trim window. If a favorite moment fails auto-centering, click 'Use anyway' to bypass the gate intentionally."
        },
        {
            id: "color-grade",
            selector: "#color-presets-container",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.563-2.512 5.563-5.562C22 6.5 17.5 2 12 2z"/></svg>`,
            title: "Color Enhancement",
            description: "Toggle the color enhancement master switch, select presets like Vivid Pop or Cinema, and dial in the filter strength. Hold the B key on your keyboard to instantly compare before and after."
        },
        {
            id: "speed-multiplier",
            selector: ".speed-btn.active, .speed-btn",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>`,
            title: "Speed Multiplier",
            description: "Change clip playback speed from 0.75x to 1.5x. Use 'Apply to All' for sequence consistency; timeline duration automatically recalibrates to reflect your playback speed."
        },
        {
            id: "safe-zone",
            selector: "#switch-safezone",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>`,
            title: "Safe Zone Guide",
            description: "Toggle platform UI overlay guides for TikTok, YouTube Shorts, and Instagram Reels. Guides are visible only during editing and never rendered into your exported video."
        },
        {
            id: "shortcuts",
            selector: "#btn-player-toggle",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2" ry="2"/><line x1="6" y1="8" x2="6" y2="8"/><line x1="10" y1="8" x2="10" y2="8"/><line x1="14" y1="8" x2="14" y2="8"/><line x1="18" y1="8" x2="18" y2="8"/><line x1="6" y1="12" x2="6" y2="12"/><line x1="10" y1="12" x2="10" y2="12"/><line x1="14" y1="12" x2="14" y2="12"/><line x1="18" y1="12" x2="18" y2="12"/><line x1="7" y1="16" x2="17" y2="16"/></svg>`,
            title: "Keyboard Shortcuts",
            description: "Use Space for play/pause, [ and ] to set in/out points, Left/Right arrows to nudge 0.1s (hold Shift for 1s), Ctrl+Z / Ctrl+Y for undo/redo, and hold B for before/after comparison."
        },
        {
            id: "rerender",
            selector: "#btn-launch-render",
            icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>`,
            title: "Re-render as New Version",
            description: "Re-rendering compiles a pristine new version (v2) from original source pixels while preserving your untouched original compilation in the library with updated attribution credits."
        }
    ]
};
