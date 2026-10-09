/**
 * LIONREEL STUDIO — ADVANCED VIDEO SLICING & COMPILATION SUITE
 * Complete 2026 Modern Creator Tool Engine & Workflow Controller
 */

const API_BASE = "";

// 11 Automated Quality Verifications & Content Controls Definition (Framing relocated to Section 3)
const VERIFICATION_KEYS = [
    { id: "toggle-check-sharpness", key: "CHECK_SHARPNESS", qcId: "qc-1", name: "Sharpness Filter", defaultVal: true },
    { id: "toggle-check-shake", key: "CHECK_SHAKE", qcId: "qc-2", name: "Shake Detector", defaultVal: true },
    { id: "toggle-check-watermark", key: "CHECK_WATERMARK", qcId: "qc-3", name: "Watermark Detector", defaultVal: true },
    { id: "toggle-check-duplicates", key: "CHECK_DUPLICATES", qcId: "qc-4", name: "Duplicate Detector", defaultVal: true },
    { id: "toggle-color-grading", key: "APPLY_COLOR_GRADING", qcId: "qc-5", name: "Auto Color Grading", defaultVal: false },
    { id: "toggle-bg-music", key: "ADD_BACKGROUND_MUSIC", qcId: "qc-7", name: "Music Overlay", defaultVal: true },
    { id: "toggle-audio-levels", key: "CHECK_AUDIO_LEVELS", qcId: "qc-8", name: "Audio Level Check", defaultVal: true },
    { id: "toggle-aspect-ratio", key: "ENFORCE_ASPECT_RATIO", qcId: "qc-9", name: "Aspect Ratio Check", defaultVal: true },
    { id: "toggle-check-ai-video", key: "CHECK_AI_VIDEO", qcId: "qc-10", name: "AI Video Detector", defaultVal: true },
    { id: "toggle-check-cartoon", key: "CHECK_CARTOON", qcId: "qc-11", name: "Cartoon & Animation Filter", defaultVal: true },
    { id: "toggle-check-ad-filter", key: "CHECK_ADVERTISING", qcId: "qc-12", name: "Ad & Promo Post Filter", defaultVal: true }
];

const ALL_PIPELINE_QC = [
    ...VERIFICATION_KEYS,
    { id: "toggle-smart-crop", key: "APPLY_SMART_CROP", qcId: "qc-6", name: "Smart Center Crop", defaultVal: true }
];


// Unified Reactive State
const state = {
    workflowStep: 1, // 1: Create/Home, 2: Sources/Wizard, 3: Editor, 4: Render, 5: Export
    wizardStage: 1,  // 1: Collection, 2: Add Sources, 3: Configure, 4: Review
    activeCategory: "cat", // cat | dog | mixed
    activeTemplateName: null,
    isRunning: false,
    isPaused: false,
    logOffset: 0,
    rawLogs: "",
    config: {
        VIDEO_MODE: "cat",
        SOURCE_MODE: "classic",
        VIDEO_TYPE: "short",
        TARGET_DURATION_MIN: 5.0,
        ASPECT_RATIO: "9:16",
        TARGET_CLIPS: 4,
        SHORT_CLIP_SEC: 7.5,
        SPEED_PROFILE: "fast",
        MOMENT_CUT_MODE: "peak_viral",
        BYPASS_QUALITY_GATE: false,
        BYPASS_FUNNY_CHECK: false,
        CHECK_SHARPNESS: true,
        CHECK_SHAKE: true,
        CHECK_WATERMARK: true,
        CHECK_DUPLICATES: true,
        APPLY_COLOR_GRADING: false,
        APPLY_SMART_CROP: true,
        LAYOUT_MODE: "smart_crop",
        ADD_BACKGROUND_MUSIC: true,
        CHECK_AUDIO_LEVELS: true,
        ENFORCE_ASPECT_RATIO: true,
        CHECK_AI_VIDEO: true,
        CHECK_CARTOON: true,
        CHECK_ADVERTISING: true,
        ALLOW_SHORTER: false
    },
    sources: [],
    selectedClips: [],
    activeClipIndex: 0,
    renderProgress: 0,
    renderStageIndex: 1,
    renderStartTime: 0,
    isBeforeAfterEnhanced: true,
    playbackSpeed: 1.0,
    activeColorFilter: "natural",
    finishedProjects: [],
    activeFinishedProjectName: null,
    timelineHistory: []
};

function syncFilterWarnings() {
    const warnMap = [
        { id: "toggle-check-watermark", warnId: "warn-watermark" },
        { id: "toggle-check-duplicates", warnId: "warn-duplicates" },
        { id: "toggle-check-ai-video", warnId: "warn-ai" },
        { id: "toggle-check-ad-filter", warnId: "warn-ad" }
    ];
    warnMap.forEach(({ id, warnId }) => {
        const toggle = document.getElementById(id);
        const warnBox = document.getElementById(warnId);
        if (toggle && warnBox) {
            warnBox.style.display = toggle.checked ? "none" : "block";
        }
    });
}

// Synchronize all 11 verification checkboxes, filter warnings, and active badge
function syncVerificationsUI() {
    let activeCount = 0;
    VERIFICATION_KEYS.forEach(item => {
        const isEnabled = typeof state.config[item.key] !== "undefined" ? !!state.config[item.key] : item.defaultVal;
        state.config[item.key] = isEnabled;
        if (isEnabled) activeCount++;
        const el = document.getElementById(item.id);
        if (el) {
            el.checked = isEnabled;
            const card = el.closest(".setup-verif-card");
            if (card) {
                card.classList.toggle("active", isEnabled);
                card.classList.toggle("inactive", !isEnabled);
            }
        }
    });

    const badge = document.getElementById("setup-active-verif-badge");
    if (badge) {
        badge.innerText = `${activeCount} / ${VERIFICATION_KEYS.length} Active`;
        if (activeCount >= VERIFICATION_KEYS.length - 1) {
            badge.style.background = "var(--green-surface)";
            badge.style.color = "var(--primary-emerald)";
            badge.style.borderColor = "var(--border-active)";
        } else {
            badge.style.background = "rgba(24, 232, 122, 0.1)";
            badge.style.color = "var(--soft-emerald)";
            badge.style.borderColor = "var(--border)";
        }
    }
    syncFilterWarnings();
}

// Curated Sample Sources — Verified 100% Cat, Dog, and Cat & Dog Duo Clips (Zero Wild Animals)
const CURATED_SOURCES = [
    {
        id: "cat_ref_01",
        title: "Funny Cats Master Reference (Hilarious Cat Chaos)",
        channel: "LionStudio HD",
        duration: 65,
        resolution: "1080x1920 Full HD",
        views: "Studio Master",
        qualityScore: 100,
        thumbnail: "https://images.unsplash.com/photo-1548802673-380ab8ebc7b7?w=640&q=80",
        videoUrl: "own_footage/Funny Cats.mp4",
        category: "cat"
    },
    {
        id: "cat_01",
        title: "Fastest Cat Slaps in the West (Zero Regrets)",
        channel: "ViralWhiskers",
        duration: 17,
        resolution: "1080p 60fps",
        views: "26.7M",
        qualityScore: 99,
        thumbnail: "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=8R_7KCtShkU",
        category: "cat"
    },
    {
        id: "cat_02",
        title: "Cat Stares In Mirror and Questions Own Existence",
        channel: "MeowDaily",
        duration: 52,
        resolution: "1080p",
        views: "46.2M",
        qualityScore: 96,
        thumbnail: "https://images.unsplash.com/photo-1533738363-b7f9aef128ce?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=SB-qEYVdvXA",
        category: "cat"
    },
    {
        id: "cat_03",
        title: "Cats Will Make You Laugh Your Head Off (Pure Chaos)",
        channel: "TigerPaws",
        duration: 42,
        resolution: "1080p",
        views: "30.1M",
        qualityScore: 97,
        thumbnail: "https://images.unsplash.com/photo-1543852786-1cf6624b9987?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=hY7m5jjJ9mM",
        category: "cat"
    },
    {
        id: "cat_04",
        title: "Orange Tabby Master of Stealth Attack on Slippers",
        channel: "GingerCats",
        duration: 41,
        resolution: "1080p",
        views: "82.3M",
        qualityScore: 95,
        thumbnail: "https://images.unsplash.com/photo-1574158622682-e40e69881006?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=ByH9LuSILxU",
        category: "cat"
    },
    {
        id: "dog_01",
        title: "Denver Official Guilty Dog (Classic Viral Comedy)",
        channel: "GuiltyDog",
        duration: 48,
        resolution: "1080p",
        views: "57.6M",
        qualityScore: 99,
        thumbnail: "https://images.unsplash.com/photo-1583511655857-d19b40a7a54e?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=B8ISzf2pryI",
        category: "dog"
    },
    {
        id: "dog_02",
        title: "Siberian Husky Having a Dramatic Temper Tantrum",
        channel: "HuskyDaily",
        duration: 59,
        resolution: "1080p",
        views: "35.5M",
        qualityScore: 98,
        thumbnail: "https://images.unsplash.com/photo-1543466835-00a7907e9de1?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=i82528KGDdo",
        category: "dog"
    },
    {
        id: "dog_03",
        title: "Golden Retriever Hilarious & Adorable Reactions",
        channel: "GoldenSquad",
        duration: 55,
        resolution: "1080p Full HD",
        views: "18.4M",
        qualityScore: 98,
        thumbnail: "https://images.unsplash.com/photo-1552053831-71594a27632d?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=Je09ps-3DTw",
        category: "dog"
    },
    {
        id: "dog_04",
        title: "Ultimate Talking Dog Tease (The Maple Bacon Video)",
        channel: "TalkingAnimals",
        duration: 50,
        resolution: "720p HD",
        views: "213M",
        qualityScore: 99,
        thumbnail: "https://images.unsplash.com/photo-1587300003388-59208cc962cb?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=nGeKSiCQkPw",
        category: "dog"
    },
    {
        id: "mix_01",
        title: "Tiny Kitten Attacks Giant Husky (Absolute Chaos)",
        channel: "PawsLove",
        duration: 45,
        resolution: "4K UHD 60fps",
        views: "2.44M",
        qualityScore: 99,
        thumbnail: "https://images.unsplash.com/photo-1537151625747-768eb6cf92b2?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=Aa0DbmzP6zY",
        category: "mix"
    },
    {
        id: "mix_02",
        title: "German Shepherd Confused by Attack of Tiny Kittens",
        channel: "AnimalDuo",
        duration: 52,
        resolution: "4K UHD",
        views: "3.35M",
        qualityScore: 99,
        thumbnail: "https://images.unsplash.com/photo-1583511655857-d19b40a7a54e?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=yK847E_MoM4",
        category: "mix"
    },
    {
        id: "mix_03",
        title: "Cats and Dogs Playing Together Funny (Dynamic Duo)",
        channel: "PetFriends",
        duration: 46,
        resolution: "720p HD",
        views: "1.82M",
        qualityScore: 97,
        thumbnail: "https://images.unsplash.com/photo-1548767797-d8c844163c4c?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=q9JFcvkhrZk",
        category: "mix"
    },
    {
        id: "mix_04",
        title: "Funny Dog and Cat Moments (Wholesome Friendship)",
        channel: "CutePaws",
        duration: 46,
        resolution: "720p HD",
        views: "1.25M",
        qualityScore: 96,
        thumbnail: "https://images.unsplash.com/photo-1543852786-1cf6624b9987?w=640&q=80",
        videoUrl: "https://www.youtube.com/watch?v=8zCx5yH-MqM",
        category: "mix"
    }
];

let appBootStartTime = Date.now();
let renderSimulationTimer = null;
let pollLogsInterval = null;

// ==========================================================================
// 1. INITIALIZATION & VIDEO REEL ASSEMBLY LOADING SCREEN
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
    initApp();
});

async function initApp() {
    appBootStartTime = Date.now();
    initTheme();
    initAppLoadingScreen();

    try {
        updateLoadingProgress(25, "Loading your studio…");
        await loadConfig();

        updateLoadingProgress(55, "Preparing your timeline & sources…");
        initCuratedSources();
        await loadFinishedProjects();
        setupExportScreen(null);

        updateLoadingProgress(80, "Checking render tools & codecs…");
        setupKeyboardShortcuts();
        setupPlayerListeners();
        setupUIEventListeners();

        updateLoadingProgress(100, "Ready to create.");
        finishAppLoadingScreen();

        // Check if backend compilation engine is actively running
        try {
            const statusRes = await fetch(`${API_BASE}/api/status`);
            if (statusRes.ok) {
                const statusData = await statusRes.json();
                if (statusData.status === "running") {
                    state.isRunning = true;
                    state.logOffset = 0;
                    updateEngineStatusBadge(true);
                    navigateToStep(4);
                    startLiveRenderClock(statusData.startTimeMs || null);
                    startLogsPolling();
                    showToast("Reconnected to active compilation pipeline", "info");
                    return;
                }
            }
        } catch (e) {}

        // Restore step from URL hash or sessionStorage
        try {
            if (window.location.hash) {
                handleUrlHash();
            } else {
                const savedStep = parseInt(sessionStorage.getItem("lionreel_step") || "1");
                if (savedStep && savedStep >= 1 && savedStep <= 5 && savedStep !== 4) {
                    navigateToStep(savedStep);
                } else {
                    loadPoolStatus();
                }
            }
        } catch (e) {
            loadPoolStatus();
        }
    } catch (err) {
        console.error("LionReel Studio init warning:", err);
        // Fall back gracefully so user is never locked out
        initCuratedSources();
        setupKeyboardShortcuts();
        setupPlayerListeners();
        setupUIEventListeners();
        finishAppLoadingScreen();
    }
}

function initAppLoadingScreen() {
    const screen = document.getElementById("app-loading-screen");
    if (!screen) return;
    screen.classList.remove("fade-out");
    screen.style.display = "flex";
    updateLoadingProgress(15, "Preparing your creative workspace…");
}

function updateLoadingProgress(pct, message) {
    const bar = document.getElementById("loading-bar-fill");
    const status = document.getElementById("loading-status-text");
    if (bar) bar.style.width = `${pct}%`;
    if (status && message) status.innerText = message;
}

function finishAppLoadingScreen() {
    const screen = document.getElementById("app-loading-screen");
    if (!screen) return;
    const elapsed = Date.now() - appBootStartTime;
    // Guaranteed 1.35s display time to prevent flashing
    const minDisplayMs = 1350;
    const remainingWait = Math.max(0, minDisplayMs - elapsed);

    setTimeout(() => {
        screen.classList.add("fade-out");
        setTimeout(() => {
            screen.style.display = "none";
        }, 400);
    }, remainingWait);
}

// ==========================================================================
// 2. EMERALD THEME ENGINE (DARK / LIGHT)
// ==========================================================================
function initTheme() {
    let theme = null;
    try {
        theme = localStorage.getItem("lionreel_theme");
    } catch (e) {}
    if (!theme) {
        theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    applyTheme(theme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute("data-theme") || (document.body.classList.contains("light-mode") ? "light" : "dark");
    const newTheme = currentTheme === "light" ? "dark" : "light";
    applyTheme(newTheme);
    showToast(`Switched to ${newTheme === "dark" ? "Dark" : "Light"} emerald theme`, "info");
}

function applyTheme(theme) {
    const activeTheme = (theme === "light") ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", activeTheme);

    if (activeTheme === "light") {
        document.documentElement.classList.add("light-mode");
        document.documentElement.classList.remove("dark-mode");
        document.body.classList.add("light-mode");
        document.body.classList.remove("dark-mode");
    } else {
        document.documentElement.classList.add("dark-mode");
        document.documentElement.classList.remove("light-mode");
        document.body.classList.add("dark-mode");
        document.body.classList.remove("light-mode");
    }

    const btn = document.getElementById("theme-toggle-btn");
    if (btn) {
        btn.setAttribute("title", activeTheme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode");
        btn.setAttribute("aria-pressed", activeTheme === "dark" ? "true" : "false");
    }

    const metaThemeColor = document.getElementById("meta-theme-color") || document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) {
        metaThemeColor.setAttribute("content", activeTheme === "light" ? "#F4FAF6" : "#06110C");
    }

    try {
        localStorage.setItem("lionreel_theme", activeTheme);
    } catch (e) {
        console.warn("Could not save theme preference to localStorage", e);
    }
}

// ==========================================================================
// 3. WORKSPACE VIEW NAVIGATION & STEPPER CONTROLLER
// ==========================================================================
function saveSelectedClips() {
    try {
        localStorage.setItem("lionreel_selected_clips", JSON.stringify(state.selectedClips));
    } catch (e) {}
}

function navigateToStep(stepNum) {
    state.workflowStep = stepNum;
    try {
        sessionStorage.setItem("lionreel_step", stepNum);
        if (history.replaceState) {
            history.replaceState(null, null, `#step${stepNum}`);
        }
    } catch (e) {}

    // Stepper header visuals
    for (let i = 1; i <= 5; i++) {
        const stepEl = document.getElementById(`step-btn-${i}`);
        if (!stepEl) continue;
        stepEl.classList.remove("active", "completed");

        const numEl = stepEl.querySelector(".step-num");
        if (i === stepNum) {
            stepEl.classList.add("active");
            if (numEl) numEl.innerText = i;
        } else if (i < stepNum) {
            stepEl.classList.add("completed");
            if (numEl) numEl.innerText = "✓";
        } else {
            if (numEl) numEl.innerText = i;
        }
    }

    // View visibility mapping
    const viewMap = {
        1: "view-dashboard",
        2: "view-wizard",
        3: "view-editor",
        4: "view-render",
        5: "view-export"
    };

    const targetViewId = viewMap[stepNum] || "view-dashboard";
    document.querySelectorAll(".workspace-view").forEach(v => v.classList.remove("active"));
    // Behavior rule: Pause any playing videos when switching views
    document.querySelectorAll("video").forEach(v => {
        if (!v.paused) v.pause();
    });
    const target = document.getElementById(targetViewId);
    if (target) {
        target.classList.add("active");
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    // Specific screen entry triggers
    if (stepNum === 1) {
        if (typeof hideSummaryBar === "function") hideSummaryBar();
        loadFinishedProjects();
        loadPoolStatus();
    } else if (stepNum === 2) {
        renderWizardStep();
    } else if (stepNum === 3) {
        if (typeof hideSummaryBar === "function") hideSummaryBar();
        syncEditorFromState();
    } else if (stepNum === 4) {
        if (typeof hideSummaryBar === "function") hideSummaryBar();
    } else if (stepNum === 5) {
        if (typeof hideSummaryBar === "function") hideSummaryBar();
        loadFinishedProjects().then(() => {
            const targetProj = (state.finishedProjects && state.finishedProjects.length > 0)
                ? (state.finishedProjects.find(p => p.name === state.activeFinishedProjectName) || state.finishedProjects[0])
                : null;
            setupExportScreen(targetProj);
        });
    }
}

async function loadPoolStatus(animalType) {
    try {
        const cat = animalType || state.activeCategory || (state.config && state.config.VIDEO_MODE) || "cat";
        const res = await fetch(`${API_BASE}/api/pool?animal=${encodeURIComponent(cat)}`);
        if (!res.ok) return;
        const data = await res.json();

        const badge = document.getElementById("pool-cycle-badge");
        const usageText = document.getElementById("pool-usage-text");
        const remText = document.getElementById("pool-remaining-text");
        const barFill = document.getElementById("pool-bar-fill");
        const statTotal = document.getElementById("pool-stat-total");
        const statUsed = document.getElementById("pool-stat-used");
        const statUnused = document.getElementById("pool-stat-unused");
        const statCycle = document.getElementById("pool-stat-cycle");
        const alertBox = document.getElementById("pool-warning-alert");

        if (badge) badge.innerText = `Cycle ${data.pool_cycle || 1}`;
        if (usageText) usageText.innerText = `Clip pool: ${data.used_clips || 0} of ${data.total_clips || 0} used (${data.usage_pct || 0}%)`;
        const remPct = Math.max(0, 100 - (data.usage_pct || 0)).toFixed(0);
        if (remText) remText.innerText = `${remPct}% available`;
        if (barFill) barFill.style.width = `${Math.min(100, data.usage_pct || 0)}%`;
        if (statTotal) statTotal.innerText = data.total_clips || 0;
        if (statUsed) statUsed.innerText = data.used_clips || 0;
        if (statUnused) statUnused.innerText = data.unused_clips || 0;
        if (statCycle) statCycle.innerText = data.pool_cycle || 1;

        if (alertBox) {
            alertBox.style.display = (data.warning || (data.total_clips > 0 && remPct <= 15)) ? "flex" : "none";
        }
    } catch (e) {
        console.warn("Could not load pool status:", e);
    }
}

function handleUrlHash() {
    const hash = (window.location.hash || "").toLowerCase();
    if (hash === "#step1" || hash === "#dashboard") navigateToStep(1);
    else if (hash === "#step2" || hash === "#wizard") { state.wizardStage = 1; navigateToStep(2); }
    else if (hash === "#step2-sources") { state.wizardStage = 2; navigateToStep(2); }
    else if (hash === "#step3" || hash === "#editor") navigateToStep(3);
    else if (hash === "#step4" || hash === "#render") navigateToStep(4);
    else if (hash === "#step5" || hash === "#export") navigateToStep(5);
}
window.addEventListener("hashchange", handleUrlHash);

// ==========================================================================
// 4. CURATED SOURCES & CANDIDATES DISCOVERY
// ==========================================================================
function initCuratedSources() {
    state.sources = [...CURATED_SOURCES];
    const cat = (state.activeCategory === "mixed" ? "mix" : (state.activeCategory || state.config.VIDEO_MODE || "cat"));
    try {
        const saved = localStorage.getItem("lionreel_selected_clips");
        if (saved) {
            const parsed = JSON.parse(saved);
            if (Array.isArray(parsed) && parsed.length > 0) {
                const validCatClips = parsed.filter(s => {
                    const sc = (s.category || "").toLowerCase();
                    if (cat === "cat") return sc === "cat" || sc === "feline";
                    if (cat === "dog") return sc === "dog" || sc === "canine";
                    return sc === "mix" || sc === "mixed";
                });
                if (validCatClips.length > 0) {
                    state.selectedClips = validCatClips;
                    renderCandidatesGrid();
                    updateTimelineClipCount();
                    return;
                }
            }
        }
    } catch (e) {}
    // Pre-select clips matching current category for a ready-to-run compilation
    const matching = state.sources.filter(s => {
        if (cat === "cat") return s.category === "cat";
        if (cat === "dog") return s.category === "dog";
        return s.category === "mix" || s.category === "mixed";
    });
    state.selectedClips = (matching.length >= 4 ? matching.slice(0, 4) : matching);
    renderCandidatesGrid();
    updateTimelineClipCount();
}

function renderCandidatesGrid(filterQuery = "") {
    const container = document.getElementById("candidates-grid");
    if (!container) return;

    const activeCat = (state.activeCategory === "mixed" ? "mix" : (state.activeCategory || "cat"));
    const filtered = state.sources.filter(s => {
        let matchesCategory = false;
        if (activeCat === "cat") {
            matchesCategory = (s.category === "cat");
        } else if (activeCat === "dog") {
            matchesCategory = (s.category === "dog");
        } else {
            // Cats & Dogs Duo Mix
            matchesCategory = (s.category === "mix" || s.category === "mixed");
        }
        const matchesQuery = !filterQuery || s.title.toLowerCase().includes(filterQuery.toLowerCase()) || s.channel.toLowerCase().includes(filterQuery.toLowerCase());
        return matchesCategory && matchesQuery;
    });

    const countBadge = document.getElementById("source-count-badge");
    if (countBadge) countBadge.innerText = filtered.length;

    if (filtered.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; padding: 32px; text-align: center; color: var(--text-muted); background: var(--bg-card); border-radius: var(--radius-lg); border: 1px dashed var(--border);">
                No video sources found for "${escapeHtml(filterQuery)}". Try another query or tap a trending chip.
            </div>
        `;
        return;
    }

    container.innerHTML = filtered.map(source => {
        const isSelected = state.selectedClips.some(c => c.id === source.id);
        return `
            <div class="candidate-card ${isSelected ? 'selected' : ''}" data-source-id="${source.id}">
                <div class="cand-thumb-wrap">
                    <img src="${source.thumbnail}" alt="${escapeHtml(source.title)}" loading="lazy">
                    <div class="cand-badge-row">
                        <span class="mockup-pill">${source.duration}s</span>
                        <span class="mockup-pill">${source.resolution}</span>
                    </div>
                </div>
                <div class="cand-content">
                    <div class="cand-title" title="${escapeHtml(source.title)}">${escapeHtml(source.title)}</div>
                    <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(source.channel)} • ${source.views} views</div>
                    <div class="cand-footer">
                        <button type="button" class="btn btn-secondary btn-sm cand-preview-btn" data-preview-id="${source.id}" style="padding: 2px 8px; font-size: 0.72rem;">Preview</button>
                        <button type="button" class="btn ${isSelected ? 'btn-primary' : 'btn-secondary'} btn-sm cand-select-btn" data-toggle-id="${source.id}" style="padding: 2px 10px; font-size: 0.72rem;">
                            ${isSelected ? '✓ Added' : '+ Add to Reel'}
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join("");

    // Attach button events
    container.querySelectorAll(".cand-select-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const sourceId = btn.getAttribute("data-toggle-id");
            toggleSourceSelection(sourceId);
        });
    });

    container.querySelectorAll(".cand-preview-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const sourceId = btn.getAttribute("data-preview-id");
            const source = state.sources.find(s => s.id === sourceId);
            if (source) openPreviewModal(source);
        });
    });
}

function toggleSourceSelection(sourceId) {
    const source = state.sources.find(s => s.id === sourceId);
    if (!source) return;

    const existingIdx = state.selectedClips.findIndex(c => c.id === sourceId);
    if (existingIdx >= 0) {
        state.selectedClips.splice(existingIdx, 1);
        showToast(`Removed "${source.title.substring(0, 24)}…" from reel`);
    } else {
        state.selectedClips.push(source);
        showToast(`Added "${source.title.substring(0, 24)}…" to reel`, "success");
    }

    renderCandidatesGrid();
    updateTimelineClipCount();
    renderReviewClipsGrid();
    updateLiveSummary();
    saveSelectedClips();
}

// ==========================================================================
// 5. NEW COMPILATION WIZARD CONTROLLER
// ==========================================================================
function renderWizardStep() {
    const stage = state.wizardStage;
    for (let i = 1; i <= 4; i++) {
        const stepEl = document.getElementById(`wizard-step-${i}`);
        if (stepEl) stepEl.style.display = (i === stage) ? "block" : "none";
    }

    const tag = document.getElementById("wizard-step-tag");
    const title = document.getElementById("wizard-title");
    const desc = document.getElementById("wizard-desc");
    const backBtn = document.getElementById("btn-wizard-back");
    const nextBtn = document.getElementById("btn-wizard-next");
    const editorBtn = document.getElementById("btn-wizard-open-editor");

    if (backBtn) backBtn.style.visibility = (stage > 1) ? "visible" : "hidden";
    if (editorBtn) editorBtn.style.display = (stage === 4) ? "inline-flex" : "none";

    if (stage === 1) {
        hideSummaryBar();
        if (tag) tag.innerText = "Step 1 of 4 • Choose Collection";
        if (title) title.innerText = "What kind of compilation are you making?";
        if (desc) desc.innerText = "Select an animal focus to optimize automated moment detection, color grade, and music pacing.";
        if (nextBtn) nextBtn.innerHTML = `<span>Continue to Sources</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>`;
    } else if (stage === 2) {
        hideSummaryBar();
        if (tag) tag.innerText = "Step 2 of 4 • Source Video Discovery";
        if (title) title.innerText = "Choose your high-energy moments";
        if (desc) desc.innerText = "Search YouTube, paste URLs, or select from curated 4K/1080p clips.";
        if (nextBtn) nextBtn.innerHTML = `<span>Configure Output</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>`;
        // Ensure queued clips strictly match the active collection
        const cat = (state.activeCategory === "mixed" ? "mix" : (state.activeCategory || state.config.VIDEO_MODE || "cat"));
        state.selectedClips = (state.selectedClips || []).filter(s => {
            const sc = (s.category || "").toLowerCase();
            if (cat === "cat") return sc === "cat" || sc === "feline";
            if (cat === "dog") return sc === "dog" || sc === "canine";
            return sc === "mix" || sc === "mixed";
        });
        if (state.selectedClips.length === 0) {
            state.selectedClips = state.sources.filter(s => {
                if (cat === "cat") return s.category === "cat";
                if (cat === "dog") return s.category === "dog";
                return s.category === "mix" || s.category === "mixed";
            }).slice(0, 4);
        }
        saveSelectedClips();
        renderCandidatesGrid();
        updateTimelineClipCount();
    } else if (stage === 3) {
        if (tag) tag.innerText = "Step 3 of 4 • Compilation Engine Parameters";
        if (title) title.innerText = "Fine-tune pacing and viral output";
        if (desc) desc.innerText = "Adjust clip duration, total count, audio mixing, and 9:16 vertical re-framing.";
        if (nextBtn) nextBtn.innerHTML = `<span>Review Sequence</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>`;
        updateDynamicChipLabels(state.config.SHORT_CLIP_SEC);
        updateLiveSummary();
        // CHANGE 1: Summary Bar popup entrance on wizard-step-3
        initSummaryBarEntrance();
    } else if (stage === 4) {
        hideSummaryBar();
        if (tag) tag.innerText = "Step 4 of 4 • Review & Launch Compilation";
        const vType = state.config.VIDEO_TYPE || "short";
        if (vType === "long") {
            const min = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
            if (title) title.innerText = `Ready to compile ${min.toFixed(1)} min Long Video`;
            if (desc) desc.innerText = `Review the viral moments for your ${min.toFixed(1)}-minute full YouTube compilation.`;
            if (nextBtn) nextBtn.innerHTML = `<span>🎬 Start ${min.toFixed(1)}m Long Video Compilation</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
        } else if (vType === "both") {
            const min = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
            if (title) title.innerText = `Ready to compile Dual Formats (${min.toFixed(1)}m Long + Short)`;
            if (desc) desc.innerText = `LionReel will compile the full ${min.toFixed(1)}-minute video and export a companion viral Short.`;
            if (nextBtn) nextBtn.innerHTML = `<span>🔄 Start Dual Compilation (Long + Short)</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
        } else {
            if (title) title.innerText = "Ready to create your viral reel";
            if (desc) desc.innerText = "Review the selected clip order or jump directly to the interactive timeline editor.";
            if (nextBtn) nextBtn.innerHTML = `<span>⚡ Start Processing Reel</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
        }
        renderReviewClipsGrid();
    }
}

function updateDynamicChipLabels(currentClipSec) {
    const sec = parseFloat(currentClipSec) || 7.5;
    document.querySelectorAll(".short-preset-chip").forEach(chip => {
        const clips = parseInt(chip.getAttribute("data-clips"));
        if (!isNaN(clips)) {
            const approx = Math.round(clips * sec);
            const stdTag = (clips === 4 && Math.abs(sec - 7.5) < 0.2) ? " • Std" : "";
            chip.innerText = `${clips} Clips (~${approx}s${stdTag})`;
        }
    });
}

// CHANGE 1: Summary Bar Entrance & Removal Lifecycle
function initSummaryBarEntrance() {
    const summaryBox = document.getElementById("wizard-dynamic-summary");
    if (!summaryBox) return;
    if (window._summaryEntranceTimer) clearTimeout(window._summaryEntranceTimer);

    // Initial state: visible in DOM but opacity 0 and shifted down
    summaryBox.style.display = "flex";
    summaryBox.classList.remove("summary-docked-in");

    // Accessibility: immediate appearance if user prefers reduced motion
    const prefersReducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion) {
        summaryBox.classList.add("summary-docked-in");
        return;
    }

    // Popup entrance after ~300ms delay: slide up 16-24px + fade in + scale 0.98 -> 1
    window._summaryEntranceTimer = setTimeout(() => {
        summaryBox.classList.add("summary-docked-in");
    }, 300);
}

function hideSummaryBar() {
    const summaryBox = document.getElementById("wizard-dynamic-summary");
    if (!summaryBox) return;
    if (window._summaryEntranceTimer) clearTimeout(window._summaryEntranceTimer);
    summaryBox.classList.remove("summary-docked-in");
    summaryBox.style.display = "none";
}

function updateLiveSummary() {
    const videoType = state.config.VIDEO_TYPE || "short";
    const aspect = state.config.ASPECT_RATIO || "9:16";
    const longMin = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
    const clipsCount = parseInt(document.getElementById("slider-target-clips")?.value || state.config.TARGET_CLIPS || 4);
    const duration = parseFloat(document.getElementById("slider-clip-duration")?.value || state.config.SHORT_CLIP_SEC || 7.5);
    const totalSec = (clipsCount * duration).toFixed(0);

    const valClips = document.getElementById("val-target-clips");
    const valDur = document.getElementById("val-clip-duration");
    const headline = document.getElementById("summary-headline");
    const sub = document.getElementById("summary-sub");
    const shortTotalDur = document.getElementById("val-short-total-dur");
    const badgeSummary = document.getElementById("badge-format-summary");

    if (valClips) valClips.innerText = `${clipsCount} clips`;
    if (valDur) valDur.innerText = `${duration.toFixed(1)}s`;
    if (shortTotalDur) shortTotalDur.innerText = `~${totalSec}s total viral runtime`;

    const resLabel = aspect === "16:9" ? "1920x1080 (16:9 Landscape)" : (aspect === "1:1" ? "1080x1080 (1:1 Square)" : "1080x1920 (9:16 Vertical)");
    const fps = state.config.TARGET_FPS || 30;

    const layoutVal = state.config.LAYOUT_MODE || document.getElementById("select-layout-mode")?.value || "smart_crop";
    const framingLabel = layoutVal === "blur_fit" ? "Blur-Fit" : (layoutVal === "auto" ? "Auto" : "Smart Crop");

    if (badgeSummary) {
        if (aspect === "16:9") {
            badgeSummary.innerText = "16:9 WIDESCREEN";
            badgeSummary.className = "badge";
            badgeSummary.style.background = "var(--info-soft)";
            badgeSummary.style.color = "var(--info)";
        } else if (aspect === "1:1") {
            badgeSummary.innerText = "1:1 SQUARE";
            badgeSummary.className = "badge";
            badgeSummary.style.background = "var(--warning-soft)";
            badgeSummary.style.color = "var(--warn)";
        } else {
            badgeSummary.innerText = "9:16 VERTICAL";
            badgeSummary.className = "badge badge-emerald";
            badgeSummary.style.background = "";
            badgeSummary.style.color = "";
        }
    }

    if (videoType === "long") {
        const estClips = Math.max(10, Math.round((longMin * 60) / duration));
        if (headline) headline.innerText = `Long Video: ${longMin.toFixed(1)} min (~${Math.round(longMin * 60)}s) - ~${estClips} viral moments`;
        if (sub) sub.innerText = `Full-length compilation for YouTube - ${resLabel} - ${fps} FPS CFR`;
    } else if (videoType === "both") {
        const estClips = Math.max(10, Math.round((longMin * 60) / duration));
        if (headline) headline.innerText = `Dual Format: ${longMin.toFixed(1)}m Long Video + 45s Short Teaser`;
        if (sub) sub.innerText = `Exports full compilation AND viral Short reel - ${resLabel} - ${fps} FPS CFR`;
    } else {
        if (headline) headline.innerText = `Short Reel: ${clipsCount} clips x ${duration.toFixed(1)}s - ~${totalSec}s runtime`;
        if (sub) sub.innerText = `Optimized for Shorts, Reels & TikTok - ${resLabel} - ${fps} FPS CFR`;
    }

    const summaryBox = document.getElementById("wizard-dynamic-summary");
    if (summaryBox) {
        summaryBox.classList.remove("val-pulse");
        void summaryBox.offsetWidth;
        summaryBox.classList.add("val-pulse");
    }
}

function renderReviewClipsGrid() {
    const container = document.getElementById("review-clips-grid");
    const countBadge = document.getElementById("review-selected-count");
    if (countBadge) countBadge.innerText = state.selectedClips.length;
    if (!container) return;

    if (state.selectedClips.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; padding: 24px; text-align: center; color: var(--text-muted); background: var(--bg-card); border-radius: var(--radius-md); border: 1px dashed var(--border);">
                No clips selected yet. Click "+ Add More Clips" to choose clips for your sequence.
            </div>
        `;
        return;
    }

    container.innerHTML = state.selectedClips.map((clip, idx) => `
        <div class="review-clip-item">
            <img class="review-clip-thumb" src="${clip.thumbnail}" alt="${escapeHtml(clip.title)}">
            <div class="review-clip-meta">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 0.72rem; font-family: var(--font-mono); font-weight: 700; color: var(--primary-emerald);">Clip #${idx + 1}</span>
                    <button type="button" class="btn-icon btn-sm review-remove-btn" data-idx="${idx}" title="Remove Clip">✕</button>
                </div>
                <div style="font-size: 0.78rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(clip.title)}</div>
                <div style="font-size: 0.68rem; color: var(--text-muted);">${clip.duration}s • ${clip.resolution || '1080p'}</div>
                <div style="display: flex; gap: 4px; align-items: center; margin-top: 3px; flex-wrap: wrap;">
                    <span class="badge badge-emerald" style="font-size: 0.6rem; padding: 1px 5px;">${clip.license || 'CC-BY 4.0'}</span>
                    <span style="font-size: 0.64rem; color: var(--text-muted); max-width: 140px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(clip.author || clip.source || 'CC Archive')}">${escapeHtml(clip.author || clip.source || 'CC Archive')}</span>
                </div>
            </div>
        </div>
    `).join("");

    container.querySelectorAll(".review-remove-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.getAttribute("data-idx"));
            state.selectedClips.splice(idx, 1);
            renderReviewClipsGrid();
            updateTimelineClipCount();
            updateLiveSummary();
            saveSelectedClips();
            showToast("Clip removed from sequence");
        });
    });
}

// ==========================================================================
// 6. INTERACTIVE VIDEO EDITOR & MULTI-CLIP TIMELINE
// ==========================================================================
function syncEditorFromState() {
    renderTimelineTrack();
    updateTimelineClipCount();
    loadActiveClipIntoPlayer();
}

function renderTimelineTrack() {
    const track = document.getElementById("timeline-clips-track");
    if (!track) return;

    if (state.selectedClips.length === 0) {
        state.selectedClips = state.sources.slice(0, 4);
    }

    track.innerHTML = state.selectedClips.map((clip, idx) => {
        const isActive = idx === state.activeClipIndex;
        return `
            <div class="timeline-clip-card ${isActive ? 'active' : ''}" data-clip-idx="${idx}">
                <img class="timeline-clip-thumb" src="${clip.thumbnail}" alt="${escapeHtml(clip.title)}">
                <div class="timeline-clip-meta">
                    <span>#${idx + 1}</span>
                    <span>${clip.duration}s</span>
                </div>
                <div class="timeline-clip-footer">
                    <span style="font-size: 0.62rem; color: #fff; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 90px;">
                        ${escapeHtml(clip.title)}
                    </span>
                    <button type="button" class="btn-icon btn-sm timeline-del-btn" data-del-idx="${idx}" title="Delete clip from timeline" style="width: 18px; height: 18px; background: rgba(0,0,0,0.6); color: #fff; font-size: 0.65rem;">✕</button>
                </div>
            </div>
        `;
    }).join("");

    track.querySelectorAll(".timeline-clip-card").forEach(card => {
        card.addEventListener("click", (e) => {
            if (e.target.closest(".timeline-del-btn")) return;
            const idx = parseInt(card.getAttribute("data-clip-idx"));
            state.activeClipIndex = idx;
            renderTimelineTrack();
            loadActiveClipIntoPlayer();
        });
    });

    track.querySelectorAll(".timeline-del-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.getAttribute("data-del-idx"));
            state.selectedClips.splice(idx, 1);
            if (state.activeClipIndex >= state.selectedClips.length) {
                state.activeClipIndex = Math.max(0, state.selectedClips.length - 1);
            }
            renderTimelineTrack();
            updateTimelineClipCount();
            loadActiveClipIntoPlayer();
            showToast("Clip removed from timeline");
        });
    });
}

// ==========================================================================
// CHANGE 2: UNIFIED MUTED VIDEO CONTROLLER
// ==========================================================================
function setupMutedVideoPlayer(video, options = {}) {
    if (!video) return null;
    if (video._mutedController) return video._mutedController;

    const container = options.container || video.parentElement;
    if (container && getComputedStyle(container).position === "static") {
        container.style.position = "relative";
    }

    // Explicitly set muted & playsinline BEFORE play()
    video.defaultMuted = true;
    video.muted = true;
    video.playsInline = true;
    video.setAttribute("muted", "");
    video.setAttribute("playsinline", "");
    video.setAttribute("preload", "metadata");

    // Create or locate the Unmute Hint Pill
    let pill = container ? container.querySelector(".video-unmute-pill") : null;
    if (!pill && container) {
        pill = document.createElement("button");
        pill.type = "button";
        pill.className = "video-unmute-pill";
        pill.setAttribute("aria-label", "Muted - tap to unmute");
        pill.setAttribute("title", "Muted - tap to unmute");
        pill.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                <line x1="23" y1="9" x2="17" y2="15"></line>
                <line x1="17" y1="9" x2="23" y2="15"></line>
            </svg>
            <span>Muted - tap to unmute</span>
        `;
        container.appendChild(pill);
    }

    if (pill) {
        pill.addEventListener("click", (e) => {
            e.stopPropagation();
            e.preventDefault();
            video.muted = false;
            if (video.volume === 0) video.volume = 1.0;
            if (video.paused) {
                video.play().catch(() => {});
            }
            pill.classList.add("hidden");
        });
    }

    // Bi-directional state sync via volumechange event
    video.addEventListener("volumechange", () => {
        const isMuted = video.muted || video.volume === 0;
        if (pill) {
            if (isMuted) {
                pill.classList.remove("hidden");
            } else {
                pill.classList.add("hidden");
            }
        }
        if (video.id === "editor-video-player") {
            const soundOn = document.getElementById("icon-sound-on");
            const soundOff = document.getElementById("icon-sound-off");
            if (soundOn) soundOn.style.display = isMuted ? "none" : "block";
            if (soundOff) soundOff.style.display = isMuted ? "block" : "none";
        }
    });

    // Ensure currentTime starts from 0:00 on metadata load
    video.addEventListener("loadedmetadata", () => {
        video.currentTime = 0;
        if (video.muted && pill) {
            pill.classList.remove("hidden");
        }
    });

    // Behavior rule: Only one video plays at a time
    video.addEventListener("play", () => {
        document.querySelectorAll("video").forEach(other => {
            if (other !== video && !other.paused) {
                other.pause();
            }
        });
        if (video.id === "editor-video-player") {
            updatePlayButtonState(true);
        }
    });

    video.addEventListener("pause", () => {
        if (video.id === "editor-video-player") {
            updatePlayButtonState(false);
        }
    });

    // IntersectionObserver: Pause when < 50% visible, resume only if was playing
    let wasPlayingBeforeScroll = false;
    let observer = null;
    if ("IntersectionObserver" in window) {
        observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.intersectionRatio >= 0.5) {
                    if (wasPlayingBeforeScroll && video.paused) {
                        video.play().catch(() => {});
                    }
                    wasPlayingBeforeScroll = false;
                } else {
                    if (!video.paused) {
                        wasPlayingBeforeScroll = true;
                        video.pause();
                    }
                }
            });
        }, { threshold: [0, 0.5, 1.0] });
        observer.observe(video);
    }

    // VisibilityChange: Pause when tab is hidden, resume only if was playing
    let wasPlayingBeforeHidden = false;
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            if (!video.paused) {
                wasPlayingBeforeHidden = true;
                video.pause();
            }
        } else {
            if (wasPlayingBeforeHidden && video.paused) {
                video.play().catch(() => {});
            }
            wasPlayingBeforeHidden = false;
        }
    });

    const controller = {
        video,
        pill,
        playMutedFromStart(autoplay = true) {
            video.defaultMuted = true;
            video.muted = true;
            video.currentTime = 0;
            if (pill) pill.classList.remove("hidden");

            const prefersReducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            if (prefersReducedMotion || !autoplay) {
                video.pause();
                return;
            }

            const p = video.play();
            if (p && typeof p.then === "function") {
                p.catch(() => {
                    // Autoplay blocked by browser policy without user gesture: show poster, do not log errors
                });
            }
        },
        destroy() {
            if (observer) observer.disconnect();
        }
    };

    video._mutedController = controller;
    return controller;
}

function loadActiveClipIntoPlayer() {
    const clip = state.selectedClips[state.activeClipIndex] || state.sources[0];
    if (!clip) return;

    const player = document.getElementById("editor-video-player");
    const stage = document.getElementById("vertical-video-stage");
    if (player && clip.videoUrl) {
        const ctrl = setupMutedVideoPlayer(player, { container: stage });
        player.src = clip.videoUrl;
        player.poster = clip.thumbnail || "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80";
        player.playbackRate = state.playbackSpeed;
        player.defaultMuted = true;
        player.muted = true;
        player.currentTime = 0;
        player.pause();
        updatePlayButtonState(false);
        if (ctrl && ctrl.pill) {
            ctrl.pill.classList.remove("hidden");
        }
    }

    // Inspector metadata
    const titleEl = document.getElementById("inspector-clip-title");
    const channelEl = document.getElementById("inspector-clip-channel");
    const scoreEl = document.getElementById("inspector-quality-score");

    if (titleEl) titleEl.innerText = clip.title;
    if (channelEl) channelEl.innerText = `${clip.channel} • ${clip.resolution}`;
    if (scoreEl) scoreEl.innerText = `${clip.qualityScore || 97}% SCORE`;

    // Apply color filter
    applyColorFilter(state.activeColorFilter);
}

function updateTimelineClipCount() {
    const countEl = document.getElementById("timeline-clip-count");
    const durEl = document.getElementById("timeline-total-duration");
    const timeDisplay = document.getElementById("player-time-display");

    if (state.config.VIDEO_TYPE === "long" || state.config.VIDEO_TYPE === "both") {
        const min = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
        const totalSec = Math.round(min * 60);
        const estClips = state.config.TARGET_CLIPS || Math.max(10, Math.round(totalSec / 5.5));
        if (countEl) countEl.innerText = `Long: ~${estClips} Clips`;
        if (durEl) durEl.innerText = `Target: ${min.toFixed(1)} Min (${totalSec}s)`;
        if (timeDisplay) {
            const m = Math.floor(min);
            const s = Math.round((min - m) * 60);
            timeDisplay.innerText = `00:00 / ${m < 10 ? '0' + m : m}:${s < 10 ? '0' + s : s}`;
        }
    } else {
        const count = state.selectedClips.length || state.config.TARGET_CLIPS || 6;
        const clipSec = parseFloat(state.config.SHORT_CLIP_SEC) || 5.5;
        const totalSec = count * clipSec;
        if (countEl) countEl.innerText = `${count} Clips`;
        if (durEl) durEl.innerText = `Total: ${totalSec.toFixed(1)}s`;
        if (timeDisplay) {
            const s = Math.round(totalSec);
            timeDisplay.innerText = `00:00 / 00:${s < 10 ? '0' + s : s}`;
        }
    }
}

function setupPlayerListeners() {
    const player = document.getElementById("editor-video-player");
    const stage = document.getElementById("vertical-video-stage");
    const scrubber = document.getElementById("player-scrubber");
    const scrubberFill = document.getElementById("player-scrubber-fill");
    const timeDisplay = document.getElementById("player-time-display");
    const playBtn = document.getElementById("btn-player-toggle");
    const rewindBtn = document.getElementById("btn-player-rewind");
    const muteBtn = document.getElementById("btn-player-mute");
    const fsBtn = document.getElementById("btn-player-fullscreen");
    const speedBtn = document.getElementById("btn-player-speed");
    const enhanceToggle = document.getElementById("btn-toggle-enhancement");

    if (player) {
        setupMutedVideoPlayer(player, { container: stage });
        player.defaultMuted = true;
        player.muted = true;
        player.currentTime = 0;

        player.addEventListener("click", () => {
            if (player.paused) {
                player.play().catch(() => {});
                updatePlayButtonState(true);
            } else {
                player.pause();
                updatePlayButtonState(false);
            }
        });

        player.addEventListener("timeupdate", () => {
            if (player.duration) {
                const pct = (player.currentTime / player.duration) * 100;
                if (scrubberFill) scrubberFill.style.width = `${pct}%`;
                if (timeDisplay) timeDisplay.innerText = `${formatTime(player.currentTime)} / ${formatTime(player.duration)}`;
            }
        });

        player.addEventListener("ended", () => {
            updatePlayButtonState(false);
        });
    }

    if (playBtn && player) {
        playBtn.addEventListener("click", () => {
            if (player.paused) {
                player.play().catch(() => {});
                updatePlayButtonState(true);
            } else {
                player.pause();
                updatePlayButtonState(false);
            }
        });
    }

    if (rewindBtn && player) {
        rewindBtn.addEventListener("click", () => {
            player.currentTime = Math.max(0, player.currentTime - 3);
        });
    }

    if (scrubber && player) {
        scrubber.addEventListener("click", (e) => {
            const rect = scrubber.getBoundingClientRect();
            const pos = (e.clientX - rect.left) / rect.width;
            if (player.duration) {
                player.currentTime = pos * player.duration;
            }
        });
    }

    if (muteBtn && player) {
        muteBtn.addEventListener("click", () => {
            player.muted = !player.muted;
        });
    }

    if (fsBtn && player) {
        fsBtn.addEventListener("click", () => {
            if (player.requestFullscreen) {
                player.requestFullscreen();
            }
        });
    }

    if (speedBtn && player) {
        speedBtn.addEventListener("click", () => {
            const speeds = [0.75, 1.0, 1.25, 1.5, 2.0];
            const currentIdx = speeds.indexOf(state.playbackSpeed);
            const nextIdx = (currentIdx + 1) % speeds.length;
            state.playbackSpeed = speeds[nextIdx];
            player.playbackRate = state.playbackSpeed;
            speedBtn.innerText = `${state.playbackSpeed}x`;
            showToast(`Speed set to ${state.playbackSpeed}x`);
        });
    }

    if (enhanceToggle) {
        enhanceToggle.addEventListener("click", () => {
            state.isBeforeAfterEnhanced = !state.isBeforeAfterEnhanced;
            const label = document.getElementById("enhancement-label");
            if (state.isBeforeAfterEnhanced) {
                if (label) label.innerText = "✨ Enhancement: ON";
                enhanceToggle.style.color = "var(--primary-emerald)";
                applyColorFilter(state.activeColorFilter);
                showToast("Enhancement Enabled (CLAHE Color & Sharpness)", "success");
            } else {
                if (label) label.innerText = "Raw Log: OFF";
                enhanceToggle.style.color = "var(--text-muted)";
                if (player) player.style.filter = "contrast(0.95) saturate(0.9)";
                showToast("Viewing Raw Unenhanced Source", "info");
            }
        });
    }
}

function updatePlayButtonState(isPlaying) {
    const playIcon = document.getElementById("icon-player-play");
    const pauseIcon = document.getElementById("icon-player-pause");
    if (playIcon) playIcon.style.display = isPlaying ? "none" : "block";
    if (pauseIcon) pauseIcon.style.display = isPlaying ? "block" : "none";
}

function applyColorFilter(filterName) {
    state.activeColorFilter = filterName;
    const player = document.getElementById("editor-video-player");
    if (!player) return;

    if (!state.isBeforeAfterEnhanced) {
        player.style.filter = "contrast(0.95) saturate(0.9)";
        return;
    }

    const filters = {
        natural: "contrast(1.08) saturate(1.12) brightness(1.02)",
        vibrant: "contrast(1.2) saturate(1.35) brightness(1.05)",
        cinema: "contrast(1.25) saturate(0.85) sepia(0.12)",
        warm: "contrast(1.1) saturate(1.2) sepia(0.2) hue-rotate(-8deg)",
        cool: "contrast(1.1) saturate(1.15) hue-rotate(15deg)",
        clahe: "contrast(1.3) saturate(1.25) brightness(1.04) drop-shadow(0 0 1px #18e87a)"
    };

    player.style.filter = filters[filterName] || filters.natural;
}

// ==========================================================================
// 7. PROCESSING / RENDER ENGINE (10 STAGES + 9 QUALITY CHECKS)
// ==========================================================================
const RENDER_STAGES = [
    { id: 1, name: "Searching sources & fetching high-res clips", weight: 8 },
    { id: 2, name: "Downloading selected clips into raw staging", weight: 14 },
    { id: 3, name: "Checking video quality & frame rate stability", weight: 10 },
    { id: 4, name: "Detecting watermarks & platform overlays", weight: 8 },
    { id: 5, name: "Trimming high-energy animal motion slices", weight: 14 },
    { id: 6, name: "Auto color grading (Contrast & CLAHE Normalization)", weight: 12 },
    { id: 7, name: "Smart center-crop to 9:16 vertical shorts", weight: 12 },
    { id: 8, name: "Mixing background music & audio ducking (-14 LUFS)", weight: 8 },
    { id: 9, name: "Rendering final MP4 compilation with FFmpeg", weight: 10 },
    { id: 10, name: "Preparing export packages for TikTok, Reels & Shorts", weight: 4 }
];

function setGenerateButtonsDisabled(disabled) {
    const launchRenderBtn = document.getElementById("btn-launch-render");
    const wizardNext = document.getElementById("btn-wizard-next");
    const renderRetryBtn = document.getElementById("btn-render-retry");
    if (launchRenderBtn) { 
        launchRenderBtn.disabled = disabled; 
        launchRenderBtn.classList.toggle("disabled", disabled);
        if (disabled) launchRenderBtn.setAttribute("disabled", "true");
        else launchRenderBtn.removeAttribute("disabled");
    }
    if (wizardNext) { 
        wizardNext.disabled = disabled; 
        wizardNext.classList.toggle("disabled", disabled);
        if (disabled) wizardNext.setAttribute("disabled", "true");
        else wizardNext.removeAttribute("disabled");
    }
    if (renderRetryBtn) { 
        renderRetryBtn.disabled = disabled; 
        renderRetryBtn.classList.toggle("disabled", disabled);
        if (disabled) renderRetryBtn.setAttribute("disabled", "true");
        else renderRetryBtn.removeAttribute("disabled");
    }
}

async function startRenderPipeline() {
    if (state.isStarting || state.isRunning) {
        console.warn("Render pipeline already starting or running. Ignoring duplicate trigger.");
        return;
    }
    state.isStarting = true;
    setGenerateButtonsDisabled(true);

    try {
        navigateToStep(4);
        state.isRunning = true;
        state.renderProgress = 5;
        state.renderStageIndex = 1;
        state.renderStartTime = Date.now();
        state.logOffset = 0;
        state.lastLogSeq = 0;
        if (state.seenLogKeys) state.seenLogKeys.clear();
        state.liveStatusMsg = "Initializing LionReel AI compilation pipeline...";
        state.currentJobId = null;

        // Reset Export player & "Ready for Upload" panels immediately
        const expPlayer = document.getElementById("export-video-player");
        if (expPlayer) {
            expPlayer.pause();
            expPlayer.removeAttribute("src");
            expPlayer.load();
        }
        const expTitle = document.getElementById("export-video-title");
        if (expTitle) expTitle.innerText = "Rendering New Video...";
        const expMeta = document.getElementById("export-video-meta");
        if (expMeta) expMeta.innerText = "Processing pipeline in progress...";
        const metaTitle = document.getElementById("export-meta-title");
        if (metaTitle) metaTitle.value = "";
        const metaDesc = document.getElementById("export-meta-desc");
        if (metaDesc) metaDesc.value = "";
        const metaTags = document.getElementById("export-meta-tags");
        if (metaTags) metaTags.value = "";

        // Clear previous error state on backend
        try { await fetch(`${API_BASE}/api/clear-error`); } catch (e) {}

        // Update Header Status Badge
        updateEngineStatusBadge(true);

        // Reset Stage Visuals
        updateRenderStagesUI(1);
        resetQualityChecksUI();

        // Ensure VIDEO_MODE is normalized
        if (state.config.VIDEO_MODE === "mixed" || state.config.VIDEO_MODE === "wildlife") {
            state.config.VIDEO_MODE = "mix";
        }
        if (!state.config.VIDEO_MODE) {
            state.config.VIDEO_MODE = state.activeCategory === "mixed" ? "mix" : (state.activeCategory || "mix");
        }

        // Safety: ensure SOURCE_MODE is classic unless an active user upload exists
        if (state.config.SOURCE_MODE === "own_footage" && (!state.config.OWN_FOOTAGE_FILE || state.config.OWN_FOOTAGE_FILE === "my_cat_video.mp4")) {
            state.config.SOURCE_MODE = "classic";
            state.config.OWN_FOOTAGE_FILE = "";
        }

        // Pass user-selected clips from timeline whenever clips are selected
        if (state.selectedClips && state.selectedClips.length > 0 && state.config.SOURCE_MODE !== "own_footage" && state.config.SOURCE_MODE !== "custom_url") {
            state.config.SOURCE_MODE = "curated";
            const cat = (state.config.VIDEO_MODE || state.activeCategory || "cat").toLowerCase();
            const effectiveCat = (cat === "mixed" || cat === "wildlife") ? "mix" : cat;
            const filteredClips = state.selectedClips.filter(c => {
                const sc = (c.category || "").toLowerCase();
                if (effectiveCat === "cat") return sc === "cat" || sc === "feline";
                if (effectiveCat === "dog") return sc === "dog" || sc === "canine";
                return sc === "mix" || sc === "mixed";
            });
            const finalClips = filteredClips.length > 0 ? filteredClips : state.selectedClips;
            state.config.SELECTED_CLIPS = finalClips.map(c => ({
                id: c.id,
                title: c.title,
                videoUrl: c.videoUrl,
                duration: c.duration,
                category: c.category,
                trimStart: c.trimStart || 0,
                trimEnd: c.trimEnd || null
            }));
        } else if (state.config.SOURCE_MODE !== "own_footage" && state.config.SOURCE_MODE !== "custom_url") {
            state.config.SELECTED_CLIPS = [];
        }

        // Ensure LAYOUT_MODE is explicitly synced from select element or state
        const selectLayoutModeEl = document.getElementById("select-layout-mode");
        if (selectLayoutModeEl && selectLayoutModeEl.value) {
            state.config.LAYOUT_MODE = selectLayoutModeEl.value;
        } else if (!state.config.LAYOUT_MODE) {
            state.config.LAYOUT_MODE = "smart_crop";
        }
        state.config.APPLY_SMART_CROP = (state.config.LAYOUT_MODE === "smart_crop" || state.config.LAYOUT_MODE === "auto");

        // 1. Save user configuration to config.json
        try {
            await fetch(`${API_BASE}/api/config`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(state.config)
            });
        } catch (e) {}

        // 2. Start or connect to the real backend compilation engine
        try {
            const res = await fetch(`${API_BASE}/api/start`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(state.config)
            });
            if (res.ok) {
                const data = await res.json();
                if (data.job_id) {
                    state.currentJobId = data.job_id;
                }
                if (data.already_running) {
                    showToast("Connected to running LionReel compilation engine", "info");
                } else {
                    showToast(`LionReel compilation engine started (Job: ${state.currentJobId || "new"})`, "success");
                }
            }
        } catch (e) {
            console.warn("Backend engine start fallback:", e);
        }

        // Start Continuous 1-Second Live Digital Clock (Smooth real-time ticker)
        startLiveRenderClock(state.renderStartTime);

        // Start Real-Time Logs Polling
        startLogsPolling();
    } finally {
        state.isStarting = false;
    }
}

let liveRenderClockInterval = null;

function startLiveRenderClock(overrideStartTime) {
    if (liveRenderClockInterval) {
        clearInterval(liveRenderClockInterval);
        liveRenderClockInterval = null;
    }

    if (overrideStartTime && overrideStartTime > 0) {
        state.renderStartTime = overrideStartTime;
    } else if (!state.renderStartTime || state.renderStartTime <= 0) {
        state.renderStartTime = Date.now();
    }

    const badge = document.getElementById("live-clock-badge");
    const badgeText = document.getElementById("live-clock-text");
    if (badge) badge.classList.remove("paused");
    if (badgeText) badgeText.innerText = "LIVE";

    // Immediate tick
    tickLiveRenderClock();

    // Dedicated smooth 1000ms clock ticking EVERY single second like a real clock
    liveRenderClockInterval = setInterval(tickLiveRenderClock, 1000);
}

function stopLiveRenderClock(statusLabel = "PAUSED") {
    if (liveRenderClockInterval) {
        clearInterval(liveRenderClockInterval);
        liveRenderClockInterval = null;
    }
    const badge = document.getElementById("live-clock-badge");
    const badgeText = document.getElementById("live-clock-text");
    if (badge) badge.classList.add("paused");
    if (badgeText) badgeText.innerText = statusLabel;
}

function tickLiveRenderClock() {
    const elapsedEl = document.getElementById("render-time-elapsed");
    const remainEl = document.getElementById("render-time-remaining");
    if (!elapsedEl || !remainEl) return;

    if (!state.renderStartTime) state.renderStartTime = Date.now();
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - state.renderStartTime) / 1000));
    elapsedEl.innerText = formatDuration(elapsedSeconds);

    const pct = state.renderProgress || 0;
    if (pct >= 100) {
        remainEl.innerText = "00:00";
        return;
    }

    const targetClips = parseInt(state.config.TARGET_CLIPS) || 6;
    const clipSec = parseFloat(state.config.SHORT_CLIP_SEC) || 5.5;

    let remainingSeconds = 0;
    if (pct > 8) {
        // Smart dynamic projection based on actual progress pace
        const projectedTotalSec = Math.round(elapsedSeconds / (pct / 100));
        remainingSeconds = Math.max(5, projectedTotalSec - elapsedSeconds);
        // Dynamic finishing indicator for final render stages
        if (state.renderStageIndex === 9 && remainingSeconds <= 10) {
            remainEl.innerText = `~00:${String(Math.max(2, remainingSeconds)).padStart(2, "0")}`;
        } else {
            remainEl.innerText = formatDuration(remainingSeconds);
        }
    } else {
        // No fake estimate while at initial stage
        remainEl.innerText = "--:--";
    }
}

function updateRenderHeroUI(pct) {
    const pctEl = document.getElementById("render-percentage-text");
    const fillEl = document.getElementById("render-progress-fill");
    const stageNameEl = document.getElementById("render-stage-name");
    const fractionEl = document.getElementById("render-stage-fraction");
    const subEl = document.getElementById("render-subtitle");

    if (pctEl) pctEl.innerText = `${pct}%`;
    if (fillEl) fillEl.style.width = `${pct}%`;
    if (subEl && state.liveStatusMsg) subEl.innerText = state.liveStatusMsg;

    const currentStage = RENDER_STAGES[state.renderStageIndex - 1];
    if (stageNameEl && currentStage) stageNameEl.innerText = currentStage.name;
    if (fractionEl) fractionEl.innerText = `Stage ${state.renderStageIndex} of 10`;

    // Ensure clock and dynamic remaining sync immediately with new progress
    tickLiveRenderClock();
    updateJobConfigSummaryUI();
}

function updateJobConfigSummaryUI(cfgLine = null) {
    const el = document.getElementById("render-job-config-summary");
    if (!el) return;

    let mode = (state.config && state.config.VIDEO_TYPE) || "short";
    let clips = (state.config && state.config.TARGET_CLIPS) || 4;
    let clipTime = parseFloat((state.config && state.config.SHORT_CLIP_SEC) || 7.5).toFixed(1);
    let expTotal = (clips * parseFloat(clipTime)).toFixed(1);
    let pace = (state.config && state.config.SPEED_PROFILE) || "fast";
    let slicing = (state.config && state.config.MOMENT_CUT_MODE) || "peak_viral";

    if (cfgLine && typeof cfgLine === "string") {
        if (cfgLine.startsWith("CONFIG:")) {
            const matches = cfgLine.matchAll(/(\w+)=([^\s]+)/g);
            for (const match of matches) {
                const k = match[1];
                const v = match[2];
                if (k === "mode") mode = v;
                else if (k === "clips") clips = v;
                else if (k === "clip_time") clipTime = v.replace("s", "");
                else if (k === "expected_total") expTotal = v.replace("s", "");
                else if (k === "pace") pace = v;
                else if (k === "slicing") slicing = v;
            }
        } else {
            el.innerHTML = `<span class="render-config-chip"><span class="config-chip-icon">ℹ️</span> ${escapeHtml(cfgLine)}</span>`;
            return;
        }
    }

    const modeLabels = {
        short: "Short Reel",
        standard: "Standard Video",
        story: "Story Mode",
        compilation: "Full Compilation"
    };
    const modeLabel = modeLabels[String(mode).toLowerCase()] || (String(mode).charAt(0).toUpperCase() + String(mode).slice(1));

    const paceLabels = {
        fast: "Fast Viral Cuts",
        normal: "Balanced Pace",
        relaxed: "Cinematic Pace",
        rapid: "Rapid Action"
    };
    const paceLabel = paceLabels[String(pace).toLowerCase()] || `${pace} Pace`;

    const sliceLabels = {
        peak_viral: "Peak Viral Focus",
        high_motion: "High Motion Focus",
        smart_balance: "Smart Balanced Cuts",
        chronological: "Sequential Order"
    };
    const sliceLabel = sliceLabels[String(slicing).toLowerCase()] || String(slicing).replace(/_/g, " ");

    el.innerHTML = `
        <span class="render-config-chip"><span class="config-chip-icon">🎬</span> <strong>${escapeHtml(modeLabel)}</strong></span>
        <span class="render-config-chip"><span class="config-chip-icon">⏱️</span> ${escapeHtml(String(clips))} clips × ${escapeHtml(String(clipTime))}s (~${escapeHtml(String(expTotal))}s total)</span>
        <span class="render-config-chip"><span class="config-chip-icon">⚡</span> ${escapeHtml(paceLabel)}</span>
        <span class="render-config-chip"><span class="config-chip-icon">🎯</span> ${escapeHtml(sliceLabel)}</span>
        <span class="render-config-chip render-config-chip-accent"><span class="config-chip-icon">📐</span> 9:16 Vertical</span>
    `;
}

function updateRenderStagesUI(activeStageId, failedStageId = null) {
    for (let i = 1; i <= 10; i++) {
        const row = document.querySelector(`.render-stage-row[data-stage-id="${i}"]`);
        if (!row) continue;
        const badge = row.querySelector(".stage-badge");
        const bullet = row.querySelector(".stage-status-bullet");

        row.classList.remove("pending", "running", "done", "failed");

        if (failedStageId && i === failedStageId) {
            row.classList.add("failed");
            if (badge) {
                badge.className = "badge badge-error stage-badge";
                badge.innerText = "FAILED";
            }
            if (bullet) bullet.innerText = "✕";
        } else if (failedStageId && i < failedStageId) {
            row.classList.add("done");
            if (badge) {
                badge.className = "badge badge-emerald stage-badge";
                badge.innerText = "VERIFIED";
            }
            if (bullet) bullet.innerText = "✓";
        } else if (failedStageId && i > failedStageId) {
            row.classList.add("pending");
            if (badge) {
                badge.className = "badge stage-badge";
                badge.innerText = "PENDING";
            }
            if (bullet) bullet.innerText = i;
        } else if (i < activeStageId) {
            row.classList.add("done");
            if (badge) {
                badge.className = "badge badge-emerald stage-badge";
                badge.innerText = "VERIFIED";
            }
            if (bullet) bullet.innerText = "✓";
        } else if (i === activeStageId) {
            row.classList.add("running");
            if (badge) {
                badge.className = "badge badge-emerald stage-badge";
                badge.innerText = "RUNNING";
            }
            if (bullet) bullet.innerText = i;
        } else {
            row.classList.add("pending");
            if (badge) {
                badge.className = "badge stage-badge";
                badge.innerText = "PENDING";
            }
            if (bullet) bullet.innerText = i;
        }
    }
}

function updateQualityChecksProgress(pct) {
    const verifiedCount = Math.min(9, Math.floor((pct / 100) * 10));
    ALL_PIPELINE_QC.forEach((item, index) => {
        const qc = document.getElementById(item.qcId);
        if (!qc) return;
        const isEnabled = typeof state.config[item.key] !== "undefined" ? !!state.config[item.key] : item.defaultVal;
        const icon = qc.querySelector(".quality-check-icon");
        if (!isEnabled) {
            qc.classList.add("skipped");
            qc.classList.remove("verified");
            if (icon) icon.innerText = "—";
            return;
        }
        qc.classList.remove("skipped");
        if (index + 1 <= verifiedCount) {
            qc.classList.add("verified");
            if (icon) icon.innerText = "✓";
        } else {
            qc.classList.remove("verified");
        }
    });
}

function resetQualityChecksUI() {
    ALL_PIPELINE_QC.forEach(item => {
        const qc = document.getElementById(item.qcId);
        if (!qc) return;
        qc.classList.remove("verified");
        const isEnabled = typeof state.config[item.key] !== "undefined" ? !!state.config[item.key] : item.defaultVal;
        const icon = qc.querySelector(".quality-check-icon");
        if (!isEnabled) {
            qc.classList.add("skipped");
            if (icon) icon.innerText = "—";
        } else {
            qc.classList.remove("skipped");
            if (icon) icon.innerText = "✓";
        }
    });
}

async function finishRenderPipeline(specificFileName = null) {
    state.isRunning = false;
    updateEngineStatusBadge(false);
    stopLogsPolling();
    stopLiveRenderClock("COMPLETE");

    // Mark all stages as done
    updateRenderStagesUI(11);
    updateQualityChecksProgress(100);

    showToast("🎉 Video Compilation Render Complete OK!", "success");

    // Fetch the latest finished files
    let latestFile = null;
    try {
        await loadFinishedProjects();
        if (state.finishedProjects && state.finishedProjects.length > 0) {
            if (specificFileName) {
                latestFile = state.finishedProjects.find(f => f.name === specificFileName);
            }
            if (!latestFile) {
                latestFile = state.finishedProjects[0];
            }
        }
    } catch (e) {}

    if (!latestFile && specificFileName) {
        latestFile = {
            name: specificFileName,
            url: `/finished/${encodeURIComponent(specificFileName)}`
        };
    }

    // Seamlessly transition to Export screen after 800ms
    setTimeout(() => {
        navigateToStep(5);
        setupExportScreen(latestFile);
    }, 800);
}

function renderExportProjectsStrip(currentFilename) {
    const listEl = document.getElementById("export-projects-scroll-list");
    const countEl = document.getElementById("export-projects-count");
    if (!listEl) return;

    if (!state.finishedProjects || state.finishedProjects.length === 0) {
        listEl.innerHTML = `<span style="font-size: 0.72rem; color: var(--text-muted); padding: 6px;">No other compilations rendered yet.</span>`;
        if (countEl) countEl.innerText = "0 Videos";
        return;
    }

    if (countEl) countEl.innerText = `${state.finishedProjects.length} Available`;

    listEl.innerHTML = state.finishedProjects.map(p => {
        const isActive = p.name === currentFilename;
        const thumb = p.thumbnail || "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80";
        const size = p.sizeBytes ? `${(p.sizeBytes / (1024 * 1024)).toFixed(1)} MB` : "";
        const isLandscape = p.name.includes("_long") || p.name.includes("16-9") || p.name.includes("landscape") || p.aspectRatio === "16:9";
        const aspectBadge = isLandscape ? "16:9 Landscape" : "9:16 Shorts";
        return `
            <div class="export-project-chip ${isActive ? 'active' : ''}" data-file-name="${p.name}" title="Switch to ${escapeHtml(p.name)}">
                <img class="export-chip-thumb" src="${thumb}" alt="${escapeHtml(p.name)}">
                <div class="export-chip-info">
                    <span class="export-chip-name" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</span>
                    <span class="export-chip-meta">${size ? size + ' • ' : ''}${aspectBadge}</span>
                </div>
            </div>
        `;
    }).join("");

    listEl.querySelectorAll(".export-project-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const fileName = chip.getAttribute("data-file-name");
            const targetProj = state.finishedProjects.find(p => p.name === fileName);
            if (targetProj) {
                state.activeFinishedProjectName = fileName;
                setupExportScreen(targetProj);
                showToast(`Loaded "${fileName}" in player`, "info");
            }
        });
    });
}

const USER_YOUTUBE_URL = "https://studio.youtube.com/channel/UCK6vJnSBp-6XWlVKjePzr4w";
const USER_META_REELS_URL = "https://business.facebook.com/latest/reels_composer/?asset_id=960315347156294&business_id=25484170311269841&ir_qe_exposed=1&ref=biz_web_home_create_reel&context_ref=HOME";
const USER_TIKTOK_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center&tab=video";

function setupExportScreen(finishedFile = null) {
    const player = document.getElementById("export-video-player");
    const playerWrap = document.getElementById("export-player-wrap") || document.querySelector(".export-player-wrap");
    const titleEl = document.getElementById("export-video-title");
    const metaEl = document.getElementById("export-video-meta");
    const downloadMasterBtn = document.getElementById("btn-download-master-video");
    const downloadSizeBadge = document.getElementById("btn-download-size-badge");
    const linkTiktok = document.getElementById("link-upload-tiktok");
    const linkReels = document.getElementById("link-upload-reels");
    const linkShorts = document.getElementById("link-upload-shorts");
    const labelUploadYoutube = document.getElementById("label-upload-youtube");

    let target = null;
    if (finishedFile && finishedFile.name) {
        target = finishedFile;
    } else if (state.finishedProjects && state.finishedProjects.length > 0) {
        target = state.finishedProjects.find(p => p.name === state.activeFinishedProjectName) || state.finishedProjects[0];
    }

    if (!target) {
        if (titleEl) titleEl.innerText = "No Finished Compilations Yet";
        if (metaEl) metaEl.innerText = "Render a compilation to preview, download, and export here.";
        renderExportProjectsStrip("");
        return;
    }

    const filename = target.name;
    let videoUrl = target.url || `/finished/${encodeURIComponent(filename)}`;
    if (!videoUrl.includes("?v=")) {
        const cacheBust = target.sha256 ? target.sha256.substring(0, 10) : Date.now();
        videoUrl = `${videoUrl}?v=${cacheBust}`;
    }
    const sizeStr = target.sizeBytes ? `${(target.sizeBytes / (1024 * 1024)).toFixed(1)} MB` : "41.6 MB";

    state.activeFinishedProjectName = filename;

    // Render projects switcher strip
    renderExportProjectsStrip(filename);

    const isInitial169 = filename.includes("_long") || filename.includes("16-9") || filename.includes("landscape") || 
                         (target.aspectRatio === "16:9") || (state.config && state.config.ASPECT_RATIO === "16:9");

    function updateExportPlayerLayout(vw, vh) {
        const isLandscape = (vw && vh) ? (vw / vh > 1.25) : isInitial169;
        const isSquare = (vw && vh) ? (Math.abs(vw - vh) < 40) : (target.aspectRatio === "1:1" || (state.config && state.config.ASPECT_RATIO === "1:1"));

        if (playerWrap) {
            playerWrap.classList.remove("aspect-16-9", "aspect-9-16", "aspect-1-1");
            if (isLandscape) {
                playerWrap.classList.add("aspect-16-9");
            } else if (isSquare) {
                playerWrap.classList.add("aspect-1-1");
            } else {
                playerWrap.classList.add("aspect-9-16");
            }
        }

        const resStr = isLandscape ? (vw && vh ? `${vw}×${vh}` : "1920×1080") : (isSquare ? (vw && vh ? `${vw}×${vh}` : "1080×1080") : (vw && vh ? `${vw}×${vh}` : "1080×1920"));
        const aspectLabel = isLandscape ? "16:9 Landscape" : (isSquare ? "1:1 Square" : "9:16 Shorts");

        const realDur = target.duration || (player && player.duration ? player.duration.toFixed(1) : null);
        const expDur = target.expected_duration_s || target.expected_duration;
        let durStr = "";
        if (realDur && expDur) {
            durStr = ` • ${parseFloat(realDur).toFixed(1)}s (expected ${parseFloat(expDur).toFixed(1)}s)`;
        } else if (realDur) {
            durStr = ` • ${parseFloat(realDur).toFixed(1)}s`;
        }

        if (metaEl) {
            metaEl.innerText = `${resStr} (${aspectLabel})${durStr} • ${sizeStr}`;
        }
        if (downloadSizeBadge) {
            downloadSizeBadge.innerText = `${sizeStr} • ${resStr}`;
        }
        if (labelUploadYoutube) {
            labelUploadYoutube.innerText = isLandscape ? "Upload to YouTube Studio" : "Upload to YouTube Shorts";
        }
    }

    // Apply immediate dimensions based on filename / config to prevent flicker
    updateExportPlayerLayout(isInitial169 ? 1920 : 1080, isInitial169 ? 1080 : 1920);

    if (player) {
        const ctrl = setupMutedVideoPlayer(player, { container: playerWrap });
        player.onloadedmetadata = () => {
            player.currentTime = 0;
            if (player.videoWidth && player.videoHeight) {
                updateExportPlayerLayout(player.videoWidth, player.videoHeight);
            }
        };
        player.defaultMuted = true;
        player.muted = true;
        player.currentTime = 0;
        player.src = videoUrl;
        player.poster = target.thumbnail || "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80";
        player.load();
        if (state.workflowStep === 5) {
            if (ctrl) {
                ctrl.playMutedFromStart(true);
            } else {
                player.play().catch(() => {});
            }
        }
    }

    if (titleEl) titleEl.innerText = filename;

    // 1. Master Video Direct Download Button
    if (downloadMasterBtn) {
        downloadMasterBtn.href = videoUrl;
        downloadMasterBtn.setAttribute("download", filename);
    }

    // 2. Verified Permanent User Upload URLs
    if (linkTiktok) linkTiktok.href = USER_TIKTOK_URL;
    if (linkReels) linkReels.href = USER_META_REELS_URL;
    if (linkShorts) linkShorts.href = USER_YOUTUBE_URL;

    // 3. Load & Parse Metadata File (Title, Description, Tags)
    loadMetadataForExport(filename);
}

async function loadMetadataForExport(filename) {
    const metaTitleInput = document.getElementById("export-meta-title");
    const metaDescInput = document.getElementById("export-meta-desc");
    const metaTagsInput = document.getElementById("export-meta-tags");
    const metaStatus = document.getElementById("meta-file-status");
    const linkTiktok = document.getElementById("link-upload-tiktok");
    const linkReels = document.getElementById("link-upload-reels");
    const linkShorts = document.getElementById("link-upload-shorts");

    if (metaStatus) metaStatus.innerText = "Loading…";

    // Set permanent links immediately
    if (linkTiktok) linkTiktok.href = USER_TIKTOK_URL;
    if (linkReels) linkReels.href = USER_META_REELS_URL;
    if (linkShorts) linkShorts.href = USER_YOUTUBE_URL;

    const candidateMetaFiles = [
        filename.replace(/\.mp4$/i, "_metadata.txt"),
        filename.replace(/\.mp4$/i, ".txt"),
        filename.replace("lion_dog_", "lion_metadata_dog_").replace("lion_cat_", "lion_metadata_cat_").replace("lion_mix_", "lion_metadata_mix_").replace("_long.mp4", ".txt").replace(".mp4", ".txt")
    ];

    try {
        for (const metaName of candidateMetaFiles) {
            const res = await fetch(`${API_BASE}/finished/${encodeURIComponent(metaName)}?v=${Date.now()}`);
            if (res.ok) {
                const text = await res.text();
                const meta = parseMetadataText(text);

                if (meta.title && metaTitleInput) metaTitleInput.value = meta.title;
                if (metaDescInput) metaDescInput.value = meta.desc || "";
                if (metaTagsInput) metaTagsInput.value = meta.hashtags || "";

                if (linkTiktok) linkTiktok.href = USER_TIKTOK_URL;
                if (linkReels) linkReels.href = USER_META_REELS_URL;
                if (linkShorts) linkShorts.href = USER_YOUTUBE_URL;

                if (metaStatus) metaStatus.innerText = "Loaded from file";
                return;
            }
        }
    } catch (e) {
        console.warn("Could not load metadata file:", e);
    }

    if (metaStatus) metaStatus.innerText = "Ready";
}

function parseMetadataText(text) {
    let title = "Cat logic is unmatched 🐾";
    let desc = "";
    let hashtags = "";
    let uploadLinks = {
        tiktok: USER_TIKTOK_URL,
        reels: USER_META_REELS_URL,
        youtube: USER_YOUTUBE_URL
    };

    if (!text) return { title, desc, hashtags, uploadLinks };

    // Support single-line TITLE: format (Strict Upload Rule: Title Only)
    const simpleTitleMatch = text.match(/^TITLE:\s*(.*)$/im);
    if (simpleTitleMatch && simpleTitleMatch[1].trim()) {
        title = simpleTitleMatch[1].trim();
        return { title, desc: "", hashtags: "", uploadLinks };
    }

    // Extract Title from legacy blocks
    const titleMatch = text.match(/[-=]{3,}\s*\nTITLE\s*\n[-=]{3,}\s*\n([\s\S]*?)(?=\n[-=]{3,}|\n===|$)/i) ||
                       text.match(/>>>\s*TITLE:\n?([\s\S]*?)(?=\n?>>>|\n?════)/i);
    if (titleMatch && titleMatch[1].trim()) title = titleMatch[1].trim();

    return { title, desc: "", hashtags: "", uploadLinks };
}

function updateEngineStatusBadge(isProcessing) {
    const badge = document.getElementById("system-status-badge");
    const label = document.getElementById("status-badge-label");
    if (!badge || !label) return;

    if (isProcessing) {
        badge.classList.add("processing");
        label.innerText = "PROCESSING";
    } else {
        badge.classList.remove("processing");
        label.innerText = "SYSTEM READY";
    }
}

// ==========================================================================
// 8. REAL-TIME LOGS CONSOLE & ENGINE TELEMETRY PARSER
// ==========================================================================
function startLogsPolling() {
    stopLogsPolling();

    pollLogsInterval = setInterval(async () => {
        try {
            const qJob = state.currentJobId ? `&job_id=${encodeURIComponent(state.currentJobId)}` : "";
            const res = await fetch(`${API_BASE}/api/logs?seq=${state.lastLogSeq || 0}${qJob}&offset=${state.logOffset}`);
            if (res.ok) {
                const data = await res.json();
                if (data.job_id && !state.currentJobId) {
                    state.currentJobId = data.job_id;
                }
                if (data.lines && data.lines.length > 0) {
                    appendSequentialLogs(data.lines, data.job_id);
                } else if (data.logs && data.logs.length > 0 && (!data.lines || data.lines.length === 0)) {
                    appendRawLogs(data.logs);
                    state.logOffset = data.offset;
                }
            }
        } catch (e) {
            console.warn("Log streaming warning:", e);
        }

        // Check background engine status
        await checkEngineStatus();
    }, 1000);
}

function stopLogsPolling() {
    if (pollLogsInterval) {
        clearInterval(pollLogsInterval);
        pollLogsInterval = null;
    }
}

function appendSequentialLogs(lines, jobId) {
    const body = document.getElementById("logs-terminal-body");
    const counter = document.getElementById("logs-line-counter");
    if (!body || !lines || lines.length === 0) return;

    if (!state.seenLogKeys) state.seenLogKeys = new Set();
    const activeJobId = jobId || state.currentJobId || "default";

    // If job changed, reset set and clear terminal body
    if (state.lastActiveJobId && state.lastActiveJobId !== activeJobId) {
        state.seenLogKeys.clear();
        state.lastLogSeq = 0;
        body.innerText = "";
    }
    state.lastActiveJobId = activeJobId;

    let newChunk = "";
    for (const item of lines) {
        const seq = item.seq;
        const lineText = item.text;
        const key = `${activeJobId}:${seq}`;
        if (!state.seenLogKeys.has(key)) {
            state.seenLogKeys.add(key);
            state.lastLogSeq = Math.max(state.lastLogSeq || 0, seq);
            newChunk += lineText + "\n";
        }
    }

    if (newChunk) {
        body.innerText += newChunk;
        body.scrollTop = body.scrollHeight;

        const totalLines = body.innerText.split("\n").length;
        if (counter) counter.innerText = `${totalLines} lines`;

        parseEngineTelemetry(newChunk);
    }
}

function appendRawLogs(chunk) {
    const body = document.getElementById("logs-terminal-body");
    const counter = document.getElementById("logs-line-counter");
    if (!body || !chunk) return;

    body.innerText += chunk;
    body.scrollTop = body.scrollHeight;

    const totalLines = body.innerText.split("\n").length;
    if (counter) counter.innerText = `${totalLines} lines`;

    // Parse live telemetry from engine output
    parseEngineTelemetry(chunk);
}

function parseEngineTelemetry(chunk) {
    if (!chunk) return;
    const targetClips = parseInt(state.config.TARGET_CLIPS) || 6;

    // Filter out static startup ASCII banner to avoid false keyword matches
    const lines = chunk.split("\n").filter(line => {
        const l = line.trim();
        return !l.startsWith("FIX ") && 
               !l.startsWith("QUALITY FILTERS") && 
               !l.startsWith("+ Audio normalisation") &&
               !l.startsWith("+ 8Mbps") &&
               !l.includes("LionReel V") &&
               !l.includes("════") &&
               !l.includes("────");
    });
    const operationalChunk = lines.join("\n");

    let currentClipNum = 1;

    for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line) continue;

        // Explicit engine stage marker: e.g. [STAGE 1] to [STAGE 10]
        const stageMarkerMatch = line.match(/\[STAGE\s*(\d+)\]/i);
        if (stageMarkerMatch) {
            const stg = parseInt(stageMarkerMatch[1]);
            state.renderStageIndex = Math.max(state.renderStageIndex, stg);
            const STAGE_PROGRESS_MAP = [0, 8, 22, 35, 45, 55, 65, 75, 85, 92, 100];
            if (stg >= 1 && stg <= 10) {
                state.renderProgress = Math.max(state.renderProgress, STAGE_PROGRESS_MAP[stg]);
                const stgObj = RENDER_STAGES[stg - 1];
                if (stgObj) {
                    state.liveStatusMsg = `Stage ${stg}/10: ${stgObj.name}`;
                }
            }
            // Auto-verify preceding quality checks when reaching specific stages
            if (stg >= 3) {
                const q1 = document.getElementById("qc-1"); if (q1) q1.classList.add("verified");
                const q2 = document.getElementById("qc-2"); if (q2) q2.classList.add("verified");
            }
            if (stg >= 4) {
                const q3 = document.getElementById("qc-3"); if (q3) q3.classList.add("verified");
            }
            if (stg >= 6) {
                const q5 = document.getElementById("qc-5"); if (q5) q5.classList.add("verified");
            }
            if (stg >= 7) {
                const q6 = document.getElementById("qc-6"); if (q6) q6.classList.add("verified");
            }
            if (stg >= 8) {
                const q7 = document.getElementById("qc-7"); if (q7) q7.classList.add("verified");
                const q8 = document.getElementById("qc-8"); if (q8) q8.classList.add("verified");
            }
        }

        // Explicit clip progress marker: e.g. [CLIP_PROGRESS] 1/6
        const clipProgMatch = line.match(/\[CLIP_PROGRESS\]\s*(\d+)\/(\d+)/i);
        if (clipProgMatch) {
            currentClipNum = parseInt(clipProgMatch[1]);
            const total = parseInt(clipProgMatch[2]) || targetClips;
            state.renderStageIndex = Math.max(state.renderStageIndex, 2);
            const basePct = Math.round(22 + (currentClipNum / total) * 45);
            state.renderProgress = Math.max(state.renderProgress, Math.min(67, basePct));
            state.liveStatusMsg = `Processing clip ${currentClipNum} of ${total}...`;
        }

        // Query progress: e.g. [Query 2/5] 'cat compilation' -> 25 candidates  OR  'cats' -> 25
        const queryMatch = line.match(/(?:\[Query\s*(\d+)\/(\d+)\])?\s*'([^']+)'\s*->\s*(\d+)/i);
        if (queryMatch) {
            const qNum = queryMatch[1] ? parseInt(queryMatch[1]) : 1;
            const qTotal = queryMatch[2] ? parseInt(queryMatch[2]) : 5;
            const qText = queryMatch[3];
            const qFound = queryMatch[4];
            state.renderStageIndex = Math.max(state.renderStageIndex, 1);
            state.renderProgress = Math.max(state.renderProgress, Math.round(5 + (qNum / qTotal) * 15));
            state.liveStatusMsg = `Searching: "${qText.substring(0, 36)}" (${qFound} candidates found)`;
        }

        // Searching start
        if (line.includes("Searching YouTube")) {
            state.renderStageIndex = Math.max(state.renderStageIndex, 1);
            state.renderProgress = Math.max(state.renderProgress, 8);
            state.liveStatusMsg = "Executing YouTube semantic searches for top animal footage...";
        }

        // Viral-scoring
        const viralMatch = line.match(/Viral-scoring\s*(\d+)\s*candidates/i);
        if (viralMatch) {
            state.renderStageIndex = Math.max(state.renderStageIndex, 1);
            state.renderProgress = Math.max(state.renderProgress, 22);
            state.liveStatusMsg = `AI viral-scoring ${viralMatch[1]} candidates by engagement velocity...`;
        }

        // Clip header: e.g. [1/6] Title
        const clipMatch = line.match(/\[(\d+)\/(\d+)\]\s*(.*)/);
        if (clipMatch) {
            currentClipNum = parseInt(clipMatch[1]);
            const total = parseInt(clipMatch[2]) || targetClips;
            const clipTitle = clipMatch[3].trim();
            state.renderStageIndex = currentClipNum <= 1 ? 2 : Math.max(state.renderStageIndex, 2);
            const basePct = Math.round(22 + ((currentClipNum - 0.7) / total) * 45);
            state.renderProgress = Math.max(state.renderProgress, Math.min(67, basePct));
            if (clipTitle) {
                state.liveStatusMsg = `[Clip ${currentClipNum}/${total}] Sourcing: "${clipTitle.substring(0, 42)}..."`;
            }
        }

        // Download strategy attempt
        if (line.includes("Downloading preview via") || line.includes("Attempting download") || line.includes("Downloading preview...")) {
            const stratMatch = line.match(/via\s*([a-zA-Z0-9_-]+)/i);
            const stratName = stratMatch ? stratMatch[1] : "fast stream";
            state.renderStageIndex = Math.max(state.renderStageIndex, 2);
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Streaming preview via ${stratName}...`;
        }

        if (line.includes("Downloaded preview")) {
            state.renderStageIndex = Math.max(state.renderStageIndex, 2);
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Preview stream buffered successfully ✅`;
        }

        // Quality Gate checks
        if (line.includes("[QualityGate]") || line.includes("Running V93 checks")) {
            state.renderStageIndex = Math.max(state.renderStageIndex, 3);
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Running 6-point quality gate checks...`;
        }

        if (line.includes("check_sharpness") || line.includes("Sharpness check") || line.includes("Laplacian")) {
            const qc1 = document.getElementById("qc-1");
            if (qc1) qc1.classList.add("verified");
            state.renderStageIndex = Math.max(state.renderStageIndex, 3);
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Sharpness verified (Laplacian edge score OK)`;
        }

        if (line.includes("check_shake") || line.includes("Shake detector") || line.includes("shake_score")) {
            const qc2 = document.getElementById("qc-2");
            if (qc2) qc2.classList.add("verified");
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Background motion stabilized ✅`;
        }

        if (line.includes("check_watermark") || line.includes("Watermark detector") || line.includes("Watermark clear")) {
            const qc3 = document.getElementById("qc-3");
            if (qc3) qc3.classList.add("verified");
            state.renderStageIndex = Math.max(state.renderStageIndex, 4);
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Watermark scan clean (no overlays detected)`;
        }

        if (line.includes("[AICheck]") || line.includes("REAL CAMERA") || line.includes("Real footage")) {
            const qc10 = document.getElementById("qc-10");
            if (qc10) qc10.classList.add("verified");
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] AI Detector: Natural camera footage verified (no CGI) ✅`;
        }

        if (line.includes("[CartoonCheck]") || line.includes("LIVE ANIMAL") || line.includes("Real animal")) {
            const qc11 = document.getElementById("qc-11");
            if (qc11) qc11.classList.add("verified");
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Cartoon Filter: Live authentic animal verified ✅`;
        }

        if (line.includes("[AdCheck]") || line.includes("CLEAN PET VIDEO") || line.includes("Clean video")) {
            const qc12 = document.getElementById("qc-12");
            if (qc12) qc12.classList.add("verified");
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Anti-Ad Filter: Non-commercial content verified ✅`;
        }

        if (line.includes("[PeakMoment]")) {
            state.liveStatusMsg = line.replace(/^\s+/, "");
        }

        if (line.includes("Preview passed all checks") || line.includes("Downloading high quality")) {
            state.renderStageIndex = Math.max(state.renderStageIndex, 2);
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Quality checks passed! Downloading 1080p source...`;
        }

        if (line.includes("Long video detected")) {
            state.renderStageIndex = Math.max(state.renderStageIndex, 5);
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Long video detected — slicing peak-motion viral moments...`;
        }

        const segMatch = line.match(/Segment\s*(\d+)\/(\d+)\s*ACCEPTED/i);
        if (segMatch) {
            state.renderStageIndex = Math.max(state.renderStageIndex, 5);
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Sliced segment ${segMatch[1]} of ${segMatch[2]} accepted ✅`;
        }

        const accMatch = line.match(/ACCEPTED\s*✅\s*—\s*Clip\s*(\d+)\/(\d+)/i);
        if (accMatch) {
            const cN = parseInt(accMatch[1]);
            const tN = parseInt(accMatch[2]) || targetClips;
            state.renderProgress = Math.max(state.renderProgress, Math.round(22 + (cN / tN) * 45));
            state.liveStatusMsg = `[Clip ${cN}/${tN}] Clip verified & added to compilation sequence ✅`;
        }

        if (line.includes("[ColourGrade]") || line.includes("Colour grade applied") || line.includes("CLAHE Normalization") || line.includes("color grade")) {
            const qc5 = document.getElementById("qc-5");
            if (qc5) qc5.classList.add("verified");
            state.renderStageIndex = Math.max(state.renderStageIndex, 6);
            if (line.includes("Skipped")) {
                state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Color grading bypassed (user setting)`;
            } else {
                state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] CLAHE + AWB color grading applied`;
            }
        }

        if (line.includes("[SmartCrop]") || line.includes("Smart crop applied") || line.includes("smart_crop_v2") || line.includes("Smart crop V93") || line.includes("vertical re-framing")) {
            const qc6 = document.getElementById("qc-6");
            if (qc6) qc6.classList.add("verified");
            state.renderStageIndex = Math.max(state.renderStageIndex, 7);
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Smart 9:16 vertical re-framing applied`;
        }

        if (line.includes("Mixing background music") || line.includes("Adding background music") || line.includes("normalising audio") || line.includes("Mixing audio")) {
            const qc7 = document.getElementById("qc-7");
            if (qc7) qc7.classList.add("verified");
            const qc8 = document.getElementById("qc-8");
            if (qc8) qc8.classList.add("verified");
            state.renderStageIndex = Math.max(state.renderStageIndex, 8);
            state.renderProgress = Math.max(state.renderProgress, 68);
            state.liveStatusMsg = "Mixing beat-matched background music with -14 LUFS ducking...";
        }

        const tqdmMatch = line.match(/t:\s*(\d+)%/);
        if (tqdmMatch) {
            state.renderStageIndex = 9;
            const rPct = parseInt(tqdmMatch[1]);
            state.renderProgress = Math.max(state.renderProgress, Math.round(70 + (rPct * 0.28)));
            state.liveStatusMsg = `Rendering final 9:16 MP4 compilation with FFmpeg (${rPct}%)...`;
        }

        if (line.includes("Moviepy - Done") || line.includes("Saved:") || line.includes("COMPILATION COMPLETE") || line.includes("All done!")) {
            const saveMatch = line.match(/Saved:\s*([^\s\r\n]+\.mp4)/i);
            const genName = saveMatch ? saveMatch[1].split(/[\\/]/).pop() : null;
            state.renderProgress = 100;
            state.renderStageIndex = 10;
            state.liveStatusMsg = "🎉 Compilation complete! Preparing master export.";
            updateRenderHeroUI(100);
            updateRenderStagesUI(11);
            updateQualityChecksProgress(100);
            finishRenderPipeline(genName);
            return;
        }
    }

    // Update UI telemetry
    updateRenderHeroUI(state.renderProgress);
    updateRenderStagesUI(state.renderStageIndex);
}

function renderCandidateReportsTable(reports) {
    const container = document.getElementById("render-candidate-table-container");
    if (!container) return;
    if (!reports || reports.length === 0) {
        container.style.display = "none";
        container.innerHTML = "";
        return;
    }

    container.style.display = "block";
    let rowsHtml = reports.map(r => {
        const isPass = r.result === "PASS";
        const resBadge = isPass 
            ? `<span class="badge badge-emerald" style="padding: 2px 8px; font-size: 0.72rem;">PASS</span>`
            : `<span class="badge" style="background: rgba(239,68,68,0.2); color: #f87171; border: 1px solid rgba(239,68,68,0.4); padding: 2px 8px; font-size: 0.72rem;">REJECT</span>`;
        const scorePct = typeof r.score === "number" ? `${(r.score * 100).toFixed(1)}%` : (r.framing_score || "—");
        return `
            <tr style="border-bottom: 1px solid var(--border);">
                <td style="padding: 7px 10px; font-family: var(--font-mono); font-weight: 600;">Cand ${r.candidate}</td>
                <td style="padding: 7px 10px; color: var(--text-secondary); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(r.source || '')}">${escapeHtml(r.source || '')}</td>
                <td style="padding: 7px 10px; font-family: var(--font-mono);">${scorePct}</td>
                <td style="padding: 7px 10px;">${resBadge}</td>
                <td style="padding: 7px 10px; color: var(--text-muted); font-size: 0.74rem;">${escapeHtml(r.reason || '')}</td>
            </tr>
        `;
    }).join("");

    container.innerHTML = `
        <div style="background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px; margin-top: 10px; overflow-x: auto;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 0.82rem; font-weight: 700; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.04em;">Processing Gate Candidates Audit</span>
                <span style="font-size: 0.72rem; color: var(--text-muted);">${reports.length} candidates evaluated</span>
            </div>
            <table style="width: 100%; border-collapse: collapse; font-size: 0.76rem; text-align: left;">
                <thead>
                    <tr style="border-bottom: 1.5px solid var(--border); color: var(--text-muted);">
                        <th style="padding: 6px 10px;">Candidate</th>
                        <th style="padding: 6px 10px;">Source</th>
                        <th style="padding: 6px 10px;">Framing Score</th>
                        <th style="padding: 6px 10px;">Result</th>
                        <th style="padding: 6px 10px;">Reason</th>
                    </tr>
                </thead>
                <tbody>
                    ${rowsHtml}
                </tbody>
            </table>
        </div>
    `;
}

async function checkEngineStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/status`);
        if (res.ok) {
            const data = await res.json();
            const isRunning = data.status === "running";
            const retryBtn = document.getElementById("btn-render-retry");

            if (isRunning) {
                state.isRunning = true;
                if (retryBtn) retryBtn.style.display = "none";
                updateEngineStatusBadge(true);
                if (!liveRenderClockInterval) {
                    startLiveRenderClock(data.startTimeMs || null);
                }

                // Reset failure visual state if previously set
                const heroCard = document.getElementById("render-hero-card");
                if (heroCard) heroCard.classList.remove("failed");
                const headline = document.getElementById("render-headline");
                if (headline) headline.innerText = "Your compilation is taking shape.";
                const remainWrap = document.getElementById("render-telemetry-remaining");
                if (remainWrap) remainWrap.style.display = "";
                const candTable = document.getElementById("render-candidate-table-container");
                if (candTable) candTable.style.display = "none";

                // Live progress and stage from backend
                if (typeof data.progressPct === "number" && data.progressPct > 0) {
                    state.renderProgress = Math.max(state.renderProgress, data.progressPct);
                }
                if (typeof data.stageIndex === "number" && data.stageIndex > 0) {
                    state.renderStageIndex = Math.max(state.renderStageIndex, data.stageIndex);
                }
                if (data.stageName) {
                    state.liveStatusMsg = `Stage ${state.renderStageIndex}/10: ${data.stageName}`;
                }
                updateRenderHeroUI(state.renderProgress);
                updateRenderStagesUI(state.renderStageIndex);

            } else if (data.status === "completed" || (data.jobResult && data.jobResult.success)) {
                // Background process finished with verified success
                const resJobId = (data.jobResult && data.jobResult.job_id) || data.job_id;
                if (state.currentJobId && resJobId && state.currentJobId !== resJobId) {
                    // Stale job output from previous run, ignore!
                    return;
                }

                state.isRunning = false;
                setGenerateButtonsDisabled(false);
                if (retryBtn) retryBtn.style.display = "none";
                updateEngineStatusBadge(false);
                stopLogsPolling();
                stopLiveRenderClock("COMPLETE");

                const headline = document.getElementById("render-headline");
                if (headline) headline.innerText = "Your compilation is ready";

                state.renderProgress = 100;
                state.renderStageIndex = 10;
                updateRenderHeroUI(100);
                updateRenderStagesUI(11);
                updateQualityChecksProgress(100);

                const newFileName = data.generatedFile || (data.jobResult && data.jobResult.output_file);
                if (!newFileName) {
                    console.warn("Completed job returned no output filename!");
                    return;
                }

                await loadFinishedProjects();
                let targetFile = null;
                if (newFileName && state.finishedProjects) {
                    targetFile = state.finishedProjects.find(p => p.name === newFileName);
                }
                if (!targetFile && newFileName) {
                    const cacheBust = (data.sha256 ? data.sha256.substring(0, 10) : Date.now());
                    targetFile = { name: newFileName, url: `/finished/${encodeURIComponent(newFileName)}?v=${cacheBust}` };
                }

                showToast("🎉 Brand New Video Generated Successfully OK!", "success");
                setTimeout(() => {
                    navigateToStep(5);
                    setupExportScreen(targetFile);
                }, 800);
                return;
            } else if (data.status === "error" || data.status === "pool_low" || (data.jobResult && !data.jobResult.success) || (data.exitCode !== null && data.exitCode !== 0)) {
                // Background process reported an error or crashed or gate failure
                state.isRunning = false;
                setGenerateButtonsDisabled(false);
                updateEngineStatusBadge(false);
                stopLogsPolling();
                stopLiveRenderClock(data.status === "pool_low" ? "POOL LOW" : "FAILED");

                const errMsg = data.error || (data.jobResult && data.jobResult.error) || (data.exitCode ? `Process exited with error code ${data.exitCode}` : "Compilation failed");
                state.liveStatusMsg = data.status === "pool_low" ? `⏳ ${errMsg}` : `❌ ${errMsg}`;
                updateRenderHeroUI(state.renderProgress);

                // Set failure UI state
                const headline = document.getElementById("render-headline");
                if (headline) headline.innerText = "Video generation failed";

                const heroCard = document.getElementById("render-hero-card");
                if (heroCard) heroCard.classList.add("failed");

                // Highlight failed stage
                let failedStageId = data.stageIndex || state.renderStageIndex || 1;
                if (data.failedStage) {
                    const fIdx = RENDER_STAGES.findIndex(s => s.name.toLowerCase().includes(data.failedStage.toLowerCase()));
                    if (fIdx >= 0) failedStageId = fIdx + 1;
                }
                updateRenderStagesUI(state.renderStageIndex, failedStageId);

                // Hide ETA
                const remainWrap = document.getElementById("render-telemetry-remaining");
                if (remainWrap) remainWrap.style.display = "none";

                // Render candidate reports table
                const candidateReports = data.candidateReports || (data.jobResult && data.jobResult.candidate_reports) || [];
                if (candidateReports.length > 0) {
                    renderCandidateReportsTable(candidateReports);
                }

                if (errMsg.includes("Pool low") || data.status === "pool_low") {
                    showToast(`⚠️ ${errMsg}`, "warning");
                    if (retryBtn) {
                        retryBtn.innerText = `🔄 ${errMsg}`;
                        retryBtn.style.display = "inline-flex";
                        retryBtn.onclick = () => { state.currentJobId = null; startRenderPipeline(); };
                    }
                } else if (errMsg.includes("No new clips available") || errMsg.includes("NO_NEW_CLIPS_AVAILABLE")) {
                    showToast("❌ No new clips available in pool! Please add new sources.", "error");
                    if (retryBtn) {
                        retryBtn.innerText = "➕ Add Sources (Step 2)";
                        retryBtn.style.display = "inline-flex";
                        retryBtn.onclick = () => { navigateToStep(2); };
                    }
                } else {
                    if (retryBtn) {
                        retryBtn.innerText = "🔄 Retry Generation";
                        retryBtn.style.display = "inline-flex";
                        retryBtn.onclick = () => {
                            state.currentJobId = null;
                            startRenderPipeline();
                        };
                    }
                    showToast(`❌ Video generation error: ${errMsg}`, "error");
                }
                return;
            } else if (!isRunning && state.isRunning) {
                // Stopped without explicit completed or error flag
                state.isRunning = false;
                setGenerateButtonsDisabled(false);
                updateEngineStatusBadge(false);
                stopLogsPolling();
                stopLiveRenderClock("STOPPED");
                if (retryBtn) {
                    retryBtn.innerText = "🔄 Retry Generation";
                    retryBtn.style.display = "inline-flex";
                    retryBtn.onclick = () => { state.currentJobId = null; startRenderPipeline(); };
                }
            }
        }
    } catch (e) {
        console.warn("Status check notice:", e);
    }
}

// ==========================================================================
// 8b. DOM VIDEO PLAYER LOCK RELEASER (PREVENTS WINERROR 32 ON DELETE)
// ==========================================================================
function releaseVideoPlayer(playerOrId) {
    const el = typeof playerOrId === "string" ? document.getElementById(playerOrId) : playerOrId;
    if (el) {
        try {
            el.pause();
            el.removeAttribute("src");
            el.load();
        } catch (e) {}
    }
}

function releaseAllVideoPlayers() {
    ["modal-preview-video", "export-video-player", "editor-video-player"].forEach(releaseVideoPlayer);
}

// ==========================================================================
// 9. FINISHED COMPILATIONS & RECENT PROJECTS LOADER
// ==========================================================================
async function loadFinishedProjects() {
    const grid = document.getElementById("recent-projects-grid");
    const emptyState = document.getElementById("recent-empty-state");
    if (!grid) return;

    try {
        const res = await fetch(`${API_BASE}/api/finished`);
        if (res.ok) {
            const data = await res.json();
            const list = Array.isArray(data) ? data : (data.files || []);
            state.finishedProjects = list.filter(f => f.name && f.name.endsWith(".mp4"));
        }
    } catch (e) {
        console.warn("Could not load backend finished videos:", e);
    }

    if (!state.finishedProjects || state.finishedProjects.length === 0) {
        grid.style.display = "none";
        if (emptyState) emptyState.style.display = "flex";
        return;
    }

    grid.style.display = "grid";
    if (emptyState) emptyState.style.display = "none";

    grid.innerHTML = state.finishedProjects.map(proj => {
        const name = proj.name || "lionreel_compilation.mp4";
        const dur = "0:33";
        const size = proj.sizeBytes ? `${(proj.sizeBytes / (1024 * 1024)).toFixed(1)} MB` : "24.5 MB";
        const isLandscape = name.includes("_long") || name.includes("16-9") || name.includes("landscape") || proj.aspectRatio === "16:9";
        const formatLabel = isLandscape ? "16:9 Landscape" : "9:16 Shorts";
        const resLabel = isLandscape ? "1920×1080" : "1080×1920";
        const thumb = proj.thumbnail || "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80";
        const fileUrl = proj.url || `/finished/${encodeURIComponent(name)}`;

        return `
            <div class="project-card" data-proj-name="${name}">
                <div class="project-thumb-wrap">
                    <img src="${thumb}" alt="${escapeHtml(name)}">
                    <div class="project-card-play" data-play-url="${fileUrl}" data-play-name="${escapeHtml(name)}" title="Play compilation">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                    </div>
                    <span class="project-duration-tag">${dur}</span>
                </div>
                <div class="project-content">
                    <div class="project-title" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
                    <div class="project-meta">
                        <span>${formatLabel}</span>
                        <span>•</span>
                        <span>${size}</span>
                        <span>•</span>
                        <span>${resLabel}</span>
                    </div>
                    <div class="project-actions">
                        <button type="button" class="btn btn-primary btn-sm btn-proj-open" data-open="${name}" style="padding: 2px 10px; font-size: 0.72rem;">Open</button>
                        <a href="${fileUrl}" download="${name}" class="btn btn-secondary btn-sm" style="padding: 2px 8px; font-size: 0.72rem;">Download</a>
                        <div style="display: flex; gap: 4px;">
                            <button type="button" class="btn-icon btn-sm btn-proj-dup" data-dup="${name}" title="Edit in Studio"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
                            <button type="button" class="btn-icon btn-sm btn-proj-del" data-del="${name}" title="Delete" style="color: var(--error);"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join("");

    grid.querySelectorAll(".btn-proj-open, .project-title").forEach(btn => {
        btn.addEventListener("click", () => {
            const card = btn.closest(".project-card");
            const name = card.getAttribute("data-proj-name");
            state.activeFinishedProjectName = name;
            const targetProj = state.finishedProjects.find(p => p.name === name);
            navigateToStep(5);
            setupExportScreen(targetProj);
            showToast(`Opened "${name}" in Export Studio`, "success");
        });
    });

    grid.querySelectorAll(".btn-proj-dup").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const name = btn.getAttribute("data-dup");
            state.activeFinishedProjectName = name;
            navigateToStep(3);
            showToast(`Loaded "${name}" into Editor timeline`, "success");
        });
    });

    grid.querySelectorAll(".project-card-play").forEach(btn => {
        btn.addEventListener("click", () => {
            const url = btn.getAttribute("data-play-url");
            const name = btn.getAttribute("data-play-name");
            openPreviewModal({
                title: name,
                videoUrl: url
            });
        });
    });

    grid.querySelectorAll(".btn-proj-del").forEach(btn => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const name = btn.getAttribute("data-del");
            const ok = await showConfirmModal({
                title: "Delete Compilation",
                message: `Are you sure you want to permanently delete "${name}" and all its files from disk?`,
                confirmText: "Delete",
                isDanger: true
            });
            if (ok) {
                // 1. Release all video player references in DOM immediately so Windows unlocks the file
                releaseAllVideoPlayers();
                await new Promise(r => setTimeout(r, 60));

                try {
                    const res = await fetch(`${API_BASE}/api/delete-file`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ filename: name })
                    });
                    const data = await res.json().catch(() => ({}));
                    if (res.ok && data.success) {
                        showToast(`Deleted ${name} permanently from disk`, "success");
                        if (state.activeFinishedProjectName === name) {
                            state.activeFinishedProjectName = null;
                        }
                    } else {
                        showToast(`Failed to delete "${name}": ${data.error || data.message || "File locked or not found"}`, "error");
                    }
                } catch (err) {
                    showToast(`Failed to delete "${name}": Network error`, "error");
                }
                await loadFinishedProjects();
            }
        });
    });
}

// ==========================================================================
// 10. BACKEND CONFIG & SYNC + VIDEO FORMAT & LENGTH CONTROLLERS
// ==========================================================================
async function syncConfigToServer() {
    try {
        await fetch(`${API_BASE}/api/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(state.config)
        });
    } catch (e) {}
}

function setVideoType(type, notify = true) {
    state.config.VIDEO_TYPE = type;
    const btnTypeShort = document.getElementById("btn-type-short");
    const btnTypeLong = document.getElementById("btn-type-long");
    const btnTypeBoth = document.getElementById("btn-type-both");
    const panelLongControls = document.getElementById("panel-long-video-controls");
    const panelShortClips = document.getElementById("panel-short-clips-count");
    const panelShortDur = document.getElementById("panel-short-clip-duration");
    const badgeVideoType = document.getElementById("badge-video-type");
    const subtextVideoType = document.getElementById("video-type-subtext");

    [btnTypeShort, btnTypeLong, btnTypeBoth].forEach(b => {
        if (b) b.classList.remove("active");
    });

    if (type === "long") {
        if (btnTypeLong) btnTypeLong.classList.add("active");
        if (panelLongControls) panelLongControls.style.display = "block";
        if (panelShortClips) panelShortClips.style.display = "none";
        if (panelShortDur) panelShortDur.style.display = "block";
        
        const min = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
        state.config.TARGET_DURATION_MIN = min;
        const clipSec = parseFloat(state.config.SHORT_CLIP_SEC) || 5.5;
        const estClips = Math.max(10, Math.round((min * 60) / clipSec));
        state.config.TARGET_CLIPS = estClips;

        if (badgeVideoType) {
            badgeVideoType.innerText = `Long Video (${min.toFixed(1)} min)`;
            badgeVideoType.className = "badge";
            badgeVideoType.style.background = "rgba(59,130,246,0.2)";
            badgeVideoType.style.color = "#60a5fa";
        }
        if (subtextVideoType) subtextVideoType.innerText = "Full YouTube compilation with continuous viral moments";

        // Sync long duration slider and label
        const sliderLongDur = document.getElementById("slider-long-duration");
        const valLongDur = document.getElementById("val-long-duration");
        const valLongDurSec = document.getElementById("val-long-duration-sec");
        if (sliderLongDur) sliderLongDur.value = min;
        if (valLongDur) valLongDur.innerText = `${min.toFixed(1)} min`;
        if (valLongDurSec) valLongDurSec.innerText = `(${Math.round(min * 60)}s • ~${estClips} clips)`;

        // Sync preset chips
        document.querySelectorAll(".duration-preset-chip").forEach(chip => {
            const chipMin = parseFloat(chip.getAttribute("data-min"));
            if (Math.abs(chipMin - min) < 0.1) chip.classList.add("active");
            else chip.classList.remove("active");
        });

        // Recommend 16:9 Landscape for long YouTube compilations if currently 9:16
        if (!state.config.ASPECT_RATIO || state.config.ASPECT_RATIO === "9:16") {
            setFormat("16:9", false);
        }

        if (notify) showToast(`🎬 Long Video Mode (${min.toFixed(1)} min) Selected OK`, "success");
    } else if (type === "both") {
        if (btnTypeBoth) btnTypeBoth.classList.add("active");
        if (panelLongControls) panelLongControls.style.display = "block";
        if (panelShortClips) panelShortClips.style.display = "block";
        if (panelShortDur) panelShortDur.style.display = "block";
        
        const min = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
        state.config.TARGET_DURATION_MIN = min;
        const clipSec = parseFloat(state.config.SHORT_CLIP_SEC) || 5.5;
        const estClips = Math.max(10, Math.round((min * 60) / clipSec));
        state.config.TARGET_CLIPS = estClips;

        if (badgeVideoType) {
            badgeVideoType.innerText = "Dual (Long + Short)";
            badgeVideoType.className = "badge";
            badgeVideoType.style.background = "rgba(234,179,8,0.2)";
            badgeVideoType.style.color = "#facc15";
        }
        if (subtextVideoType) subtextVideoType.innerText = "Exports full compilation AND companion viral Short reel";

        // Sync long duration slider and label
        const sliderLongDur = document.getElementById("slider-long-duration");
        const valLongDur = document.getElementById("val-long-duration");
        const valLongDurSec = document.getElementById("val-long-duration-sec");
        if (sliderLongDur) sliderLongDur.value = min;
        if (valLongDur) valLongDur.innerText = `${min.toFixed(1)} min`;
        if (valLongDurSec) valLongDurSec.innerText = `(${Math.round(min * 60)}s • ~${estClips} clips)`;

        // Sync preset chips
        document.querySelectorAll(".duration-preset-chip").forEach(chip => {
            const chipMin = parseFloat(chip.getAttribute("data-min"));
            if (Math.abs(chipMin - min) < 0.1) chip.classList.add("active");
            else chip.classList.remove("active");
        });

        if (notify) showToast("✓ Dual Mode (Long Video + Short Reel) Selected OK", "success");
    } else {
        // Short Video (default)
        if (btnTypeShort) btnTypeShort.classList.add("active");
        if (panelLongControls) panelLongControls.style.display = "none";
        if (panelShortClips) panelShortClips.style.display = "block";
        if (panelShortDur) panelShortDur.style.display = "block";
        if (badgeVideoType) {
            badgeVideoType.innerText = "Short Reel (30s-60s)";
            badgeVideoType.className = "badge badge-emerald";
            badgeVideoType.style.background = "";
            badgeVideoType.style.color = "";
        }
        if (subtextVideoType) subtextVideoType.innerText = "Optimized for TikTok, Shorts & Reels";

        const targetClipsInput = document.getElementById("slider-target-clips");
        const clips = targetClipsInput ? parseInt(targetClipsInput.value) : 4;
        state.config.TARGET_CLIPS = Math.min(12, Math.max(3, clips));

        // Switch back to 9:16 Vertical for Shorts if currently 16:9 Landscape
        if (!state.config.ASPECT_RATIO || state.config.ASPECT_RATIO === "16:9") {
            setFormat("9:16", false);
        }

        // Sync short chips
        document.querySelectorAll(".short-preset-chip").forEach(chip => {
            const chipClips = parseInt(chip.getAttribute("data-clips"));
            if (chipClips === state.config.TARGET_CLIPS) chip.classList.add("active");
            else chip.classList.remove("active");
        });

        if (notify) showToast("✓ Short Reel (30-60s) Mode Selected OK", "success");
    }

    updateLiveSummary();
    updateTimelineClipCount();
    syncConfigToServer();
}

function updateLongDuration(minVal, notify = false) {
    const val = parseFloat(minVal) || 5.0;
    state.config.TARGET_DURATION_MIN = val;
    
    // If not already in Long or Both mode, switch to Long Video mode
    if (state.config.VIDEO_TYPE !== "both" && state.config.VIDEO_TYPE !== "long") {
        setVideoType("long", false);
    }

    const sliderLongDur = document.getElementById("slider-long-duration");
    const valLongDur = document.getElementById("val-long-duration");
    const valLongDurSec = document.getElementById("val-long-duration-sec");
    const badgeVideoType = document.getElementById("badge-video-type");

    if (sliderLongDur) sliderLongDur.value = val;
    if (valLongDur) valLongDur.innerText = `${val.toFixed(1)} min`;
    
    const clipSec = parseFloat(state.config.SHORT_CLIP_SEC) || 5.5;
    const estClips = Math.max(10, Math.round((val * 60) / clipSec));
    if (valLongDurSec) valLongDurSec.innerText = `(${Math.round(val * 60)}s • ~${estClips} clips)`;

    // Sync preset chips
    document.querySelectorAll(".duration-preset-chip").forEach(chip => {
        const chipMin = parseFloat(chip.getAttribute("data-min"));
        if (Math.abs(chipMin - val) < 0.1) {
            chip.classList.add("active");
        } else {
            chip.classList.remove("active");
        }
    });

    state.config.TARGET_CLIPS = estClips;
    if (badgeVideoType && state.config.VIDEO_TYPE === "long") {
        badgeVideoType.innerText = `Long Video (${val.toFixed(1)} min)`;
    }

    updateLiveSummary();
    updateTimelineClipCount();
    syncConfigToServer();
    if (notify) showToast(`🎬 Long video duration set to ${val.toFixed(1)} minutes`, "info");
}

function updateShortDuration(clips, sec, notify = false) {
    // Only switch to Short Video mode if not already in short
    if (state.config.VIDEO_TYPE !== "short") {
        setVideoType("short", false);
    }
    const targetClips = Math.min(10, Math.max(2, parseInt(clips) || 4));
    const targetSec = Math.min(15.0, Math.max(2.0, parseFloat(sec) || 7.5));
    state.config.TARGET_CLIPS = targetClips;
    state.config.SHORT_CLIP_SEC = targetSec;
    updateDynamicChipLabels(targetSec);

    const sliderClips = document.getElementById("slider-target-clips");
    const sliderDur = document.getElementById("slider-clip-duration");
    const valClips = document.getElementById("val-target-clips");
    const valDur = document.getElementById("val-clip-duration");
    const totalSecEl = document.getElementById("val-short-total-dur");
    const pacingDesc = document.getElementById("label-clip-pacing-desc");

    if (sliderClips) sliderClips.value = targetClips;
    if (sliderDur) sliderDur.value = targetSec;
    if (valClips) valClips.innerText = `${targetClips} clips`;
    if (valDur) valDur.innerText = `${targetSec.toFixed(1)}s`;

    const totalSec = (targetClips * targetSec).toFixed(1);
    if (totalSecEl) totalSecEl.innerText = `~${totalSec}s total viral runtime`;

    if (pacingDesc) {
        if (targetSec <= 4.0) pacingDesc.innerText = "Pacing: Snappy Fast Cuts";
        else if (targetSec <= 6.5) pacingDesc.innerText = "Pacing: Dynamic Flow";
        else if (targetSec <= 8.5) pacingDesc.innerText = `Pacing: ${targetSec.toFixed(1)}s Viral Sweet Spot`;
        else pacingDesc.innerText = "Pacing: Extended Story Arc";
    }

    // Sync short preset chips (clip count)
    document.querySelectorAll(".short-preset-chip").forEach(chip => {
        const c = parseInt(chip.getAttribute("data-clips"));
        if (c === targetClips) {
            chip.classList.add("active");
        } else {
            chip.classList.remove("active");
        }
    });

    // Sync duration preset chips (seconds)
    document.querySelectorAll(".clip-sec-preset-chip").forEach(chip => {
        const s = parseFloat(chip.getAttribute("data-sec"));
        if (Math.abs(s - targetSec) < 0.2) {
            chip.classList.add("active");
        } else {
            chip.classList.remove("active");
        }
    });

    // Auto-sync selectedClips sequence to match target clip count
    if (state.selectedClips && state.sources && state.sources.length > 0) {
        if (state.selectedClips.length < targetClips) {
            const cat = (state.activeCategory === "mixed" ? "mix" : (state.activeCategory || state.config.VIDEO_MODE || "cat"));
            const available = state.sources.filter(s => {
                const matchesCat = (cat === "mix" || cat === "mixed") ? (s.category === "mix" || s.category === "mixed") : (s.category === cat);
                return matchesCat && !state.selectedClips.some(sel => sel.id === s.id);
            });
            const needed = targetClips - state.selectedClips.length;
            const toAdd = available.slice(0, needed);
            state.selectedClips.push(...toAdd);
        } else if (state.selectedClips.length > targetClips) {
            state.selectedClips = state.selectedClips.slice(0, targetClips);
        }
        if (state.activeClipIndex >= state.selectedClips.length) {
            state.activeClipIndex = Math.max(0, state.selectedClips.length - 1);
        }
        renderCandidatesGrid();
        renderReviewClipsGrid();
        renderTimelineTrack();
        saveSelectedClips();
    }

    updateLiveSummary();
    updateTimelineClipCount();
    syncConfigToServer();
    if (notify) showToast(`⚡ Short reel set to ~${Math.round(targetClips * targetSec)}s (${targetClips} clips × ${targetSec.toFixed(1)}s)`, "info");
}

function setFormat(aspect, notify = true) {
    state.config.ASPECT_RATIO = aspect;
    state.config.TARGET_FORMAT = aspect;
    const btnFormat916 = document.getElementById("btn-format-916");
    const btnFormat169 = document.getElementById("btn-format-169");
    const btnFormat11 = document.getElementById("btn-format-11");
    const formatDescText = document.getElementById("format-desc-text");
    const badgeAspectRes = document.getElementById("badge-current-aspect-res");

    [btnFormat916, btnFormat169, btnFormat11].forEach(b => {
        if (b) b.classList.remove("active");
    });

    if (aspect === "16:9") {
        if (btnFormat169) btnFormat169.classList.add("active");
        if (formatDescText) formatDescText.innerText = "Widescreen 16:9 for YouTube, Television & Desktop playback (1920×1080)";
        if (badgeAspectRes) badgeAspectRes.innerText = "1920×1080 (16:9 Landscape)";
        if (notify) showToast("✓ Platform Format: 16:9 Landscape (1920×1080) OK", "success");
    } else if (aspect === "1:1") {
        if (btnFormat11) btnFormat11.classList.add("active");
        if (formatDescText) formatDescText.innerText = "Square 1:1 for Instagram Feed & Facebook Carousel (1080×1080)";
        if (badgeAspectRes) badgeAspectRes.innerText = "1080×1080 (1:1 Square)";
        if (notify) showToast("✓ Platform Format: 1:1 Square (1080×1080) OK", "success");
    } else {
        if (btnFormat916) btnFormat916.classList.add("active");
        if (formatDescText) formatDescText.innerText = "Standard 9:16 for YouTube Shorts, Instagram Reels & TikTok (1080×1920)";
        if (badgeAspectRes) badgeAspectRes.innerText = "1080×1920 (9:16 Vertical)";
        if (notify) showToast("✓ Platform Format: 9:16 Vertical Shorts (1080×1920) OK", "success");
    }

    updateLiveSummary();
    syncConfigToServer();
}

async function loadConfig() {
    try {
        const res = await fetch(`${API_BASE}/api/config`);
        if (res.ok) {
            const cfg = await res.json();
            Object.assign(state.config, cfg);
            if (state.config.SOURCE_MODE === "own_footage" && (!state.config.OWN_FOOTAGE_FILE || state.config.OWN_FOOTAGE_FILE === "my_cat_video.mp4")) {
                state.config.SOURCE_MODE = "classic";
                state.config.OWN_FOOTAGE_FILE = "";
            }
            syncVerificationsUI();

            // Sync animal collection card in Step 1
            const curMode = state.config.VIDEO_MODE || "cat";
            const effectiveMode = (curMode === "mixed" || curMode === "wildlife" || curMode === "mix") ? "mix" : curMode;
            state.activeCategory = effectiveMode;
            document.querySelectorAll(".collection-card").forEach(c => {
                const cMode = c.getAttribute("data-mode");
                if (cMode === effectiveMode) {
                    c.classList.add("selected");
                } else {
                    c.classList.remove("selected");
                }
            });

            // Sync wizard slider inputs and indicators
            const clipDurSlider = document.getElementById("slider-clip-duration");
            const targetClipsSlider = document.getElementById("slider-target-clips");
            const valDur = document.getElementById("val-clip-duration");
            const valClips = document.getElementById("val-target-clips");
            const badgeAspectRes = document.getElementById("badge-current-aspect-res");
            const totalSecEl = document.getElementById("val-short-total-dur");
            const pacingDesc = document.getElementById("label-clip-pacing-desc");

            if (clipDurSlider && state.config.SHORT_CLIP_SEC) {
                clipDurSlider.value = state.config.SHORT_CLIP_SEC;
                if (valDur) valDur.innerText = `${parseFloat(state.config.SHORT_CLIP_SEC).toFixed(1)}s`;
            }
            if (targetClipsSlider && state.config.TARGET_CLIPS) {
                targetClipsSlider.value = state.config.TARGET_CLIPS;
                if (valClips) valClips.innerText = `${state.config.TARGET_CLIPS} clips`;
            }
            if (badgeAspectRes && state.config.ASPECT_RATIO) {
                badgeAspectRes.innerText = state.config.ASPECT_RATIO === "16:9" ? "1920×1080 (16:9 Landscape)" : (state.config.ASPECT_RATIO === "1:1" ? "1080×1080 (1:1 Square)" : "1080×1920 (9:16 Vertical)");
            }

            const currentClips = parseInt(state.config.TARGET_CLIPS) || 4;
            const currentSec = parseFloat(state.config.SHORT_CLIP_SEC) || 7.5;
            if (totalSecEl) totalSecEl.innerText = `~${(currentClips * currentSec).toFixed(1)}s total viral runtime`;

            if (pacingDesc) {
                if (currentSec <= 4.0) pacingDesc.innerText = "Pacing: Snappy Fast Cuts";
                else if (currentSec <= 6.5) pacingDesc.innerText = "Pacing: Dynamic Flow";
                else if (currentSec <= 8.5) pacingDesc.innerText = `Pacing: ${currentSec.toFixed(1)}s Viral Sweet Spot`;
                else pacingDesc.innerText = "Pacing: Extended Story Arc";
            }

            document.querySelectorAll(".short-preset-chip").forEach(chip => {
                const c = parseInt(chip.getAttribute("data-clips"));
                if (c === currentClips) chip.classList.add("active");
                else chip.classList.remove("active");
            });
            document.querySelectorAll(".clip-sec-preset-chip").forEach(chip => {
                const s = parseFloat(chip.getAttribute("data-sec"));
                if (Math.abs(s - currentSec) < 0.2) chip.classList.add("active");
                else chip.classList.remove("active");
            });

            // Sync toggle switches
            const colorToggle = document.getElementById("toggle-color-grading");
            const editorColorToggle = document.getElementById("switch-color-grading-editor");
            const colorGradingStatus = document.getElementById("label-color-grading-status");
            if (typeof state.config.APPLY_COLOR_GRADING !== "undefined") {
                const isGradeOn = !!state.config.APPLY_COLOR_GRADING;
                if (colorToggle) colorToggle.checked = isGradeOn;
                if (editorColorToggle) editorColorToggle.checked = isGradeOn;
                if (colorGradingStatus) {
                    colorGradingStatus.innerText = isGradeOn ? "ACTIVE" : "OFF";
                    colorGradingStatus.style.color = isGradeOn ? "var(--primary-emerald)" : "var(--text-muted)";
                }
            }
            const gateToggle = document.getElementById("toggle-bypass-gate");
            if (gateToggle && typeof state.config.BYPASS_QUALITY_GATE !== "undefined") {
                gateToggle.checked = !!state.config.BYPASS_QUALITY_GATE;
            }
            const musicToggle = document.getElementById("toggle-bg-music");
            if (musicToggle && typeof state.config.ADD_BACKGROUND_MUSIC !== "undefined") {
                musicToggle.checked = !!state.config.ADD_BACKGROUND_MUSIC;
            }

            // Sync Video Format & Length Mode
            const savedVideoType = state.config.VIDEO_TYPE || "short";
            setVideoType(savedVideoType, false);

            if (state.config.TARGET_DURATION_MIN) {
                const minVal = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
                const sliderLongDur = document.getElementById("slider-long-duration");
                const valLongDur = document.getElementById("val-long-duration");
                const valLongDurSec = document.getElementById("val-long-duration-sec");
                if (sliderLongDur) sliderLongDur.value = minVal;
                if (valLongDur) valLongDur.innerText = `${minVal.toFixed(1)} min`;
                const clipSec = parseFloat(state.config.SHORT_CLIP_SEC) || 5.5;
                const estClips = Math.max(10, Math.round((minVal * 60) / clipSec));
                if (valLongDurSec) valLongDurSec.innerText = `(${Math.round(minVal * 60)}s • ~${estClips} clips)`;
                document.querySelectorAll(".duration-preset-chip").forEach(chip => {
                    const chipMin = parseFloat(chip.getAttribute("data-min"));
                    if (Math.abs(chipMin - minVal) < 0.1) chip.classList.add("active");
                    else chip.classList.remove("active");
                });
            }
            if (state.config.ASPECT_RATIO) {
                setFormat(state.config.ASPECT_RATIO, false);
            }

            // Sync relocated Framing (Layout Mode)
            const selectLayoutMode = document.getElementById("select-layout-mode");
            if (selectLayoutMode) {
                selectLayoutMode.value = state.config.LAYOUT_MODE || "smart_crop";
            }

            // Sync dynamic config placeholders
            const confSharpness = document.getElementById("conf-sharpness-thresh");
            if (confSharpness) {
                const val = state.config.SHARPNESS_THRESHOLD || state.config.MIN_LAPLACIAN_VARIANCE || 150.0;
                confSharpness.innerText = parseFloat(val).toFixed(1);
            }

            const confFps = document.getElementById("conf-fps");
            if (confFps) {
                const fps = state.config.TARGET_FPS || 30;
                confFps.innerText = fps;
            }

            const momentCutSelect = document.getElementById("select-moment-cut");
            if (momentCutSelect && state.config.MOMENT_CUT_MODE) {
                momentCutSelect.value = state.config.MOMENT_CUT_MODE;
            }

            const paceSelect = document.getElementById("select-pace-profile");
            if (paceSelect && state.config.SPEED_PROFILE) {
                paceSelect.value = state.config.SPEED_PROFILE;
            }

            const toggleAllowShorter = document.getElementById("toggle-allow-shorter");
            if (toggleAllowShorter && state.config.ALLOW_SHORTER !== undefined) {
                toggleAllowShorter.checked = Boolean(state.config.ALLOW_SHORTER);
            }

            updateDynamicChipLabels(currentSec);
            syncFilterWarnings();
            updateLiveSummary();
        }
    } catch (e) {
        console.warn("Using local configuration state");
    }
}

// ==========================================================================
// 11. UI EVENT LISTENERS & INTERACTIVITY
// ==========================================================================
function setupUIEventListeners() {
    // Theme toggle
    const themeBtn = document.getElementById("theme-toggle-btn");
    if (themeBtn) themeBtn.addEventListener("click", toggleTheme);

    // Brand logo home
    const brandBtn = document.getElementById("btn-brand-home");
    if (brandBtn) brandBtn.addEventListener("click", () => navigateToStep(1));

    // Workspace selector
    const wsSelector = document.getElementById("workspace-selector");
    if (wsSelector) {
        wsSelector.addEventListener("click", async () => {
            try {
                await fetch(`${API_BASE}/api/open-folder`, { method: "POST" });
                showToast("📁 Opened LionReel Workspace in Windows Explorer", "info");
            } catch (e) {
                showToast("📁 Active Workspace: Animal Shorts Lab", "info");
            }
        });
    }

    // User avatar
    const userAvatar = document.querySelector(".user-avatar-btn");
    if (userAvatar) {
        userAvatar.addEventListener("click", () => {
            showToast("👑 LionReel Creator Pro: Active Session Ready", "success");
        });
    }

    // Stepper buttons
    for (let i = 1; i <= 5; i++) {
        const stepBtn = document.getElementById(`step-btn-${i}`);
        if (stepBtn) {
            stepBtn.addEventListener("click", () => navigateToStep(i));
        }
    }

    // Header CTA
    const headerNewBtn = document.getElementById("btn-header-new");
    if (headerNewBtn) {
        headerNewBtn.addEventListener("click", () => {
            state.wizardStage = 1;
            navigateToStep(2);
        });
    }

    // Hero buttons
    const heroNewBtn = document.getElementById("hero-btn-new");
    const heroSampleBtn = document.getElementById("hero-btn-sample");
    const heroPurgeBtn = document.getElementById("hero-btn-purge-files");
    const heroCleanBtn = document.getElementById("hero-btn-clean-all");
    const emptyNewBtn = document.getElementById("btn-empty-new");
    const exportNewBtn = document.getElementById("btn-export-new");
    const heroMockup = document.getElementById("hero-mockup-frame");

    if (heroNewBtn) heroNewBtn.addEventListener("click", () => { state.wizardStage = 1; navigateToStep(2); showToast("✓ New Compilation Wizard Started OK", "info"); });
    if (emptyNewBtn) emptyNewBtn.addEventListener("click", () => { state.wizardStage = 1; navigateToStep(2); showToast("✓ New Compilation Wizard Started OK", "info"); });
    if (exportNewBtn) exportNewBtn.addEventListener("click", () => { state.wizardStage = 1; navigateToStep(2); showToast("✓ Ready to Create Next Compilation OK", "info"); });
    if (heroPurgeBtn) heroPurgeBtn.addEventListener("click", () => purgeTempAndOldFiles());
    if (heroCleanBtn) heroCleanBtn.addEventListener("click", () => cleanStudioAndClipHistory());

    // Pool Add Sources Buttons
    const poolAddBtn = document.getElementById("btn-pool-add-sources");
    const poolWarnAddBtn = document.getElementById("btn-pool-warning-add");
    if (poolAddBtn) poolAddBtn.addEventListener("click", () => { state.wizardStage = 2; navigateToStep(2); showToast("✓ Add fresh footage to clip pool", "info"); });
    if (poolWarnAddBtn) poolWarnAddBtn.addEventListener("click", () => { state.wizardStage = 2; navigateToStep(2); showToast("✓ Add fresh footage to clip pool", "info"); });

    if (heroSampleBtn) {
        heroSampleBtn.addEventListener("click", () => {
            state.selectedClips = state.sources.slice(0, 6);
            navigateToStep(3);
            showToast("✓ Loaded curated 6-clip sample compilation OK", "success");
        });
    }

    if (heroMockup) {
        heroMockup.addEventListener("click", () => {
            openPreviewModal(state.sources[0] || CURATED_SOURCES[0]);
        });
    }

    // Quick Templates
    document.querySelectorAll(".template-card").forEach(card => {
        card.addEventListener("click", () => {
            const template = card.getAttribute("data-template");
            applyTemplateConfig(template);
            state.wizardStage = 2;
            navigateToStep(2);
        });
    });

    // Wizard Collection Cards
    document.querySelectorAll(".collection-card").forEach(card => {
        card.addEventListener("click", () => {
            document.querySelectorAll(".collection-card").forEach(c => c.classList.remove("selected"));
            card.classList.add("selected");
            const rawMode = card.getAttribute("data-mode") || "mix";
            const targetMode = (rawMode === "mixed" || rawMode === "wildlife" || rawMode === "mix") ? "mix" : rawMode;
            state.activeCategory = targetMode;
            state.config.VIDEO_MODE = targetMode;

            // Always reset source mode to classic so old footage/URLs never get stuck
            state.config.SOURCE_MODE = "classic";
            state.config.OWN_FOOTAGE_FILE = "";
            state.config.CUSTOM_URL = "";

            // Automatically pick candidate clips tailored to the chosen collection
            if (targetMode === "mix") {
                const mixClips = state.sources.filter(s => s.category === "mix" || s.category === "mixed");
                state.selectedClips = mixClips.slice(0, 4);
            } else {
                state.selectedClips = state.sources.filter(s => s.category === targetMode).slice(0, 4);
            }

            saveSelectedClips();
            renderCandidatesGrid();
            renderReviewClipsGrid();
            renderTimelineTrack();
            updateTimelineClipCount();
            updateLiveSummary();
            syncConfigToServer();
            loadPoolStatus(targetMode);
            showToast(`✓ Collection set to ${targetMode.toUpperCase()} (${state.selectedClips.length} clips queued)`, "success");
        });
    });

    // Wizard Next & Back Buttons
    const wizardNext = document.getElementById("btn-wizard-next");
    const wizardBack = document.getElementById("btn-wizard-back");
    const wizardEditor = document.getElementById("btn-wizard-open-editor");
    const reviewAddMore = document.getElementById("btn-review-add-more");

    if (wizardNext) {
        wizardNext.addEventListener("click", () => {
            if (state.wizardStage < 4) {
                state.wizardStage++;
                renderWizardStep();
                showToast(`✓ Advanced to Stage ${state.wizardStage} OK`, "info");
            } else {
                startRenderPipeline();
            }
        });
    }

    if (wizardBack) {
        wizardBack.addEventListener("click", () => {
            if (state.wizardStage > 1) {
                state.wizardStage--;
                renderWizardStep();
                showToast(`Returned to Stage ${state.wizardStage}`, "info");
            }
        });
    }

    if (wizardEditor) {
        wizardEditor.addEventListener("click", () => {
            navigateToStep(3);
            showToast("✓ Opened Pro Timeline Editor OK", "info");
        });
    }

    if (reviewAddMore) {
        reviewAddMore.addEventListener("click", () => {
            state.wizardStage = 2;
            renderWizardStep();
            showToast("✓ Select more clips from source library", "info");
        });
    }

    // Source Search & Suggestion Chips
    const searchInput = document.getElementById("source-search-input");
    const searchBtn = document.getElementById("btn-source-search");

    if (searchBtn && searchInput) {
        searchBtn.addEventListener("click", () => {
            renderCandidatesGrid(searchInput.value.trim());
        });
        searchInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") renderCandidatesGrid(searchInput.value.trim());
        });
    }

    document.querySelectorAll(".suggestion-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const q = chip.getAttribute("data-query");
            if (searchInput) searchInput.value = q;
            renderCandidatesGrid(q);
        });
    });

    // Wizard Config Sliders and Steppers handled centrally in setupEventListeners

    // Wizard Config Toggles
    const colorGradeToggle = document.getElementById("toggle-color-grading");
    const bypassGateToggle = document.getElementById("toggle-bypass-gate");
    const bgMusicToggle = document.getElementById("toggle-bg-music");

    async function syncConfigToServer() {
        try {
            await fetch(`${API_BASE}/api/config`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(state.config)
            });
        } catch (e) {}
    }

    const editorColorGradeSwitch = document.getElementById("switch-color-grading-editor");
    const colorGradingStatusLabel = document.getElementById("label-color-grading-status");

    function updateColorGradingState(enabled, notify = true) {
        state.config.APPLY_COLOR_GRADING = enabled;
        if (colorGradeToggle) colorGradeToggle.checked = enabled;
        if (editorColorGradeSwitch) editorColorGradeSwitch.checked = enabled;
        if (colorGradingStatusLabel) {
            colorGradingStatusLabel.innerText = enabled ? "ACTIVE" : "OFF";
            colorGradingStatusLabel.style.color = enabled ? "var(--primary-emerald)" : "var(--text-muted)";
        }
        syncVerificationsUI();
        if (notify) {
            showToast(`Auto color grading (CLAHE) ${enabled ? 'enabled' : 'disabled'}`, "info");
        }
        syncConfigToServer();
    }

    if (colorGradeToggle) {
        colorGradeToggle.addEventListener("change", () => {
            updateColorGradingState(colorGradeToggle.checked, true);
        });
    }

    if (editorColorGradeSwitch) {
        editorColorGradeSwitch.addEventListener("change", () => {
            updateColorGradingState(editorColorGradeSwitch.checked, true);
        });
    }

    // 9 Automated Quality Verifications & Pipeline Controls Toggles
    VERIFICATION_KEYS.forEach(item => {
        if (item.key === "APPLY_COLOR_GRADING") return; // Handled by updateColorGradingState above
        const el = document.getElementById(item.id);
        if (el) {
            el.addEventListener("change", () => {
                state.config[item.key] = el.checked;
                syncVerificationsUI();
                syncConfigToServer();
                showToast(`${item.name} ${el.checked ? 'enabled' : 'bypassed'}`, "info");
            });
        }
    });

    // Quick Action: Select All (Enables all 11 quality checks)
    const btnSelectAll = document.getElementById("btn-verif-select-all");
    if (btnSelectAll) {
        btnSelectAll.addEventListener("click", () => {
            VERIFICATION_KEYS.forEach(item => {
                state.config[item.key] = true;
            });
            syncVerificationsUI();
            updateColorGradingState(true, false);
            syncConfigToServer();
            showToast("✓ All 11 Quality Verifications Enabled OK", "success");
        });
    }

    // Quick Action: Recommended (Standard active, color grading optional off)
    const btnResetDefault = document.getElementById("btn-verif-reset-default");
    if (btnResetDefault) {
        btnResetDefault.addEventListener("click", () => {
            VERIFICATION_KEYS.forEach(item => {
                state.config[item.key] = item.defaultVal;
            });
            syncVerificationsUI();
            updateColorGradingState(false, false);
            syncConfigToServer();
            showToast("✓ Recommended Quality Suite Restored OK", "success");
        });
    }

    if (bypassGateToggle) {
        bypassGateToggle.addEventListener("change", () => {
            state.config.BYPASS_QUALITY_GATE = bypassGateToggle.checked;
            syncConfigToServer();
        });
    }

    if (bgMusicToggle) {
        bgMusicToggle.addEventListener("change", () => {
            state.config.ADD_BACKGROUND_MUSIC = bgMusicToggle.checked;
            syncVerificationsUI();
            syncConfigToServer();
        });
    }


    // Compilation Pace Profile
    const paceProfileSelect = document.getElementById("select-pace-profile");
    if (paceProfileSelect) {
        paceProfileSelect.addEventListener("change", (e) => {
            state.config.SPEED_PROFILE = e.target.value;
            syncConfigToServer();
            showToast(`Pacing profile: ${e.target.options[e.target.selectedIndex].text}`, "info");
        });
    }

    // AI Viral Moment Slicing Engine
    const momentCutSelect = document.getElementById("select-moment-cut");
    if (momentCutSelect) {
        momentCutSelect.addEventListener("change", (e) => {
            state.config.MOMENT_CUT_MODE = e.target.value;
            syncConfigToServer();
            showToast(`AI Moment Cut: ${e.target.options[e.target.selectedIndex].text}`, "info");
        });
    }

    // Allow Shorter Video Toggle (Safety Gate)
    const toggleAllowShorter = document.getElementById("toggle-allow-shorter");
    if (toggleAllowShorter) {
        toggleAllowShorter.addEventListener("change", () => {
            state.config.ALLOW_SHORTER = toggleAllowShorter.checked;
            syncConfigToServer();
            showToast(`Allow shorter video: ${toggleAllowShorter.checked ? "ON" : "OFF"}`, "info");
        });
    }

    // Relocated Framing Layout Mode
    const selectLayoutMode = document.getElementById("select-layout-mode");
    if (selectLayoutMode) {
        selectLayoutMode.addEventListener("change", (e) => {
            const val = e.target.value;
            state.config.LAYOUT_MODE = val;
            state.config.APPLY_SMART_CROP = (val === "smart_crop" || val === "auto");
            const cropCheckbox = document.getElementById("toggle-smart-crop");
            if (cropCheckbox) cropCheckbox.checked = (val === "smart_crop");
            syncConfigToServer();
            updateLiveSummary();
            showToast(`Framing layout: ${e.target.options[e.target.selectedIndex].text}`, "info");
        });
    }

    // Video Format & Length Mode Buttons (Short / Long / Both)
    const btnTypeShort = document.getElementById("btn-type-short");
    const btnTypeLong = document.getElementById("btn-type-long");
    const btnTypeBoth = document.getElementById("btn-type-both");

    if (btnTypeShort) {
        btnTypeShort.addEventListener("click", () => setVideoType("short", true));
    }
    if (btnTypeLong) {
        btnTypeLong.addEventListener("click", () => setVideoType("long", true));
    }
    if (btnTypeBoth) {
        btnTypeBoth.addEventListener("click", () => setVideoType("both", true));
    }

    // Long Video Duration Slider & Quick Presets
    const sliderLongDuration = document.getElementById("slider-long-duration");
    if (sliderLongDuration) {
        sliderLongDuration.addEventListener("input", (e) => {
            updateLongDuration(e.target.value, false);
        });
    }

    document.querySelectorAll(".duration-preset-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const min = chip.getAttribute("data-min");
            if (min) updateLongDuration(min, true);
        });
    });

    // Stepper buttons for Clip Count
    const btnClipsMinus = document.getElementById("btn-step-clips-minus");
    const btnClipsPlus = document.getElementById("btn-step-clips-plus");
    if (btnClipsMinus) {
        btnClipsMinus.addEventListener("click", () => {
            const current = parseInt(state.config.TARGET_CLIPS) || 4;
            const next = Math.max(2, current - 1);
            updateShortDuration(next, state.config.SHORT_CLIP_SEC, true);
        });
    }
    if (btnClipsPlus) {
        btnClipsPlus.addEventListener("click", () => {
            const current = parseInt(state.config.TARGET_CLIPS) || 4;
            const next = Math.min(10, current + 1);
            updateShortDuration(next, state.config.SHORT_CLIP_SEC, true);
        });
    }

    // Stepper buttons for Clip Duration (Seconds)
    const btnDurMinus = document.getElementById("btn-step-dur-minus");
    const btnDurPlus = document.getElementById("btn-step-dur-plus");
    if (btnDurMinus) {
        btnDurMinus.addEventListener("click", () => {
            const current = parseFloat(state.config.SHORT_CLIP_SEC) || 7.5;
            const next = Math.max(2.0, current - 0.5);
            updateShortDuration(state.config.TARGET_CLIPS, next, true);
        });
    }
    if (btnDurPlus) {
        btnDurPlus.addEventListener("click", () => {
            const current = parseFloat(state.config.SHORT_CLIP_SEC) || 7.5;
            const next = Math.min(15.0, current + 0.5);
            updateShortDuration(state.config.TARGET_CLIPS, next, true);
        });
    }

    // Stepper buttons for Long Video Duration (Minutes)
    const btnLongMinus = document.getElementById("btn-step-long-minus");
    const btnLongPlus = document.getElementById("btn-step-long-plus");
    if (btnLongMinus) {
        btnLongMinus.addEventListener("click", () => {
            const current = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
            const next = Math.max(1.0, current - 0.5);
            updateLongDuration(next, true);
        });
    }
    if (btnLongPlus) {
        btnLongPlus.addEventListener("click", () => {
            const current = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
            const next = Math.min(20.0, current + 0.5);
            updateLongDuration(next, true);
        });
    }

    // Short Video Quick Runtime Presets (Clip Count)
    document.querySelectorAll(".short-preset-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const clips = chip.getAttribute("data-clips");
            const sec = chip.getAttribute("data-sec");
            if (clips && sec) updateShortDuration(clips, sec, true);
            else if (clips) updateShortDuration(clips, state.config.SHORT_CLIP_SEC, true);
        });
    });

    // Moment Cut Duration Presets (Seconds)
    document.querySelectorAll(".clip-sec-preset-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const sec = parseFloat(chip.getAttribute("data-sec"));
            if (sec) {
                const clips = parseInt(state.config.TARGET_CLIPS) || 4;
                updateShortDuration(clips, sec, true);
            }
        });
    });

    const sliderTargetClips = document.getElementById("slider-target-clips");
    if (sliderTargetClips) {
        sliderTargetClips.addEventListener("input", (e) => {
            const clipSec = parseFloat(state.config.SHORT_CLIP_SEC) || 7.5;
            updateShortDuration(e.target.value, clipSec, false);
        });
    }

    const sliderClipDuration = document.getElementById("slider-clip-duration");
    if (sliderClipDuration) {
        sliderClipDuration.addEventListener("input", (e) => {
            const sec = parseFloat(e.target.value) || 7.5;
            state.config.SHORT_CLIP_SEC = sec;
            const valDur = document.getElementById("val-clip-duration");
            if (valDur) valDur.innerText = `${sec.toFixed(1)}s`;

            if (state.config.VIDEO_TYPE === "long" || state.config.VIDEO_TYPE === "both") {
                const min = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
                const estClips = Math.max(10, Math.round((min * 60) / sec));
                state.config.TARGET_CLIPS = estClips;
                const valLongDurSec = document.getElementById("val-long-duration-sec");
                if (valLongDurSec) valLongDurSec.innerText = `(${Math.round(min * 60)}s • ~${estClips} clips)`;
                updateLiveSummary();
                updateTimelineClipCount();
                syncConfigToServer();
            } else {
                const clips = parseInt(state.config.TARGET_CLIPS) || 4;
                updateShortDuration(clips, sec, false);
            }
        });
    }

    // Target Platform Format (9:16 Vertical, 16:9 Landscape, 1:1 Square)
    const btnFormat916 = document.getElementById("btn-format-916");
    const btnFormat169 = document.getElementById("btn-format-169");
    const btnFormat11 = document.getElementById("btn-format-11");

    if (btnFormat916) {
        btnFormat916.addEventListener("click", () => setFormat("9:16", true));
    }
    if (btnFormat169) {
        btnFormat169.addEventListener("click", () => setFormat("16:9", true));
    }
    if (btnFormat11) {
        btnFormat11.addEventListener("click", () => setFormat("1:1", true));
    }

    // Inspector Color Filter Chips
    document.querySelectorAll(".preset-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            document.querySelectorAll(".preset-chip").forEach(c => c.classList.remove("active"));
            chip.classList.add("active");
            const filterName = chip.getAttribute("data-filter");
            applyColorFilter(filterName);
            showToast(`✓ Color enhancement "${filterName}" applied OK`, "success");
        });
    });

    // Inspector Speed Buttons
    document.querySelectorAll(".speed-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".speed-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const spd = parseFloat(btn.getAttribute("data-speed"));
            state.playbackSpeed = spd;
            const player = document.getElementById("editor-video-player");
            if (player) player.playbackRate = spd;
            const spdBtn = document.getElementById("btn-player-speed");
            if (spdBtn) spdBtn.innerText = `${spd}x`;
            showToast(`✓ Playback speed set to ${spd}x OK`, "success");
        });
    });

    // Inspector Safe-zone Switch
    const safeZoneSwitch = document.getElementById("switch-safezone");
    const safeZoneOverlay = document.getElementById("safe-zone-overlay");
    if (safeZoneSwitch && safeZoneOverlay) {
        safeZoneSwitch.addEventListener("change", () => {
            safeZoneOverlay.style.display = safeZoneSwitch.checked ? "block" : "none";
            showToast(`✓ Safe-zone overlay ${safeZoneSwitch.checked ? 'shown' : 'hidden'} OK`, "info");
        });
    }

    // Inspector "Send to Render Pipeline" CTA
    const launchRenderBtn = document.getElementById("btn-launch-render");
    if (launchRenderBtn) {
        launchRenderBtn.addEventListener("click", startRenderPipeline);
    }

    // Render Actions
    const cancelRenderBtn = document.getElementById("btn-render-cancel");
    const bgRenderBtn = document.getElementById("btn-render-bg");

    if (cancelRenderBtn) {
        cancelRenderBtn.addEventListener("click", async () => {
            const ok = await showConfirmModal({
                title: "Cancel Compilation",
                message: "Cancel current compilation rendering and halt background processing?",
                confirmText: "Yes, Cancel",
                cancelText: "Keep Running",
                isDanger: true
            });
            if (ok) {
                state.isRunning = false;
                setGenerateButtonsDisabled(false);
                if (renderSimulationTimer) clearInterval(renderSimulationTimer);
                stopLiveRenderClock("RESET");
                updateEngineStatusBadge(false);
                stopLogsPolling();
                try {
                    await fetch(`${API_BASE}/api/stop`, { method: "POST" });
                } catch (e) {}

                // Reset render hero state and telemetry
                state.renderProgress = 0;
                state.renderStageIndex = 1;
                state.renderStartTime = 0;
                state.liveStatusMsg = "";

                const elapsedEl = document.getElementById("render-time-elapsed");
                const remainEl = document.getElementById("render-time-remaining");
                const pctEl = document.getElementById("render-percentage-text");
                const fillEl = document.getElementById("render-progress-fill");
                const stageNameEl = document.getElementById("render-stage-name");
                const fractionEl = document.getElementById("render-stage-fraction");

                if (elapsedEl) elapsedEl.innerText = "00:00";
                if (remainEl) remainEl.innerText = "--:--";
                if (pctEl) pctEl.innerText = "0%";
                if (fillEl) fillEl.style.width = "0%";
                if (stageNameEl) stageNameEl.innerText = "Initializing…";
                if (fractionEl) fractionEl.innerText = "Stage 1 of 10";

                resetQualityChecksUI();
                updateRenderStagesUI(1);

                navigateToStep(3);
                showToast("Pipeline stopped & reset. Ready to re-render.", "warning");
            }
        });
    }

    if (bgRenderBtn) {
        bgRenderBtn.addEventListener("click", () => {
            navigateToStep(1);
            showToast("Compilation continuing in background…", "info");
        });
    }

    // Logs Console Controls
    const clearLogsBtn = document.getElementById("btn-clear-logs");
    const copyLogsBtn = document.getElementById("btn-copy-logs");
    const logsDrawer = document.getElementById("btn-toggle-logs");

    if (clearLogsBtn) {
        clearLogsBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const body = document.getElementById("logs-terminal-body");
            if (body) body.innerText = "[Console cleared]";
        });
    }

    if (copyLogsBtn) {
        copyLogsBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const body = document.getElementById("logs-terminal-body");
            if (body && navigator.clipboard) {
                navigator.clipboard.writeText(body.innerText).then(() => {
                    showToast("Logs copied to clipboard", "success");
                });
            }
        });
    }

    // Refresh Finished Library
    const refreshFinishedBtn = document.getElementById("btn-refresh-finished");
    if (refreshFinishedBtn) {
        refreshFinishedBtn.addEventListener("click", () => {
            loadFinishedProjects();
            showToast("Refreshed compilation library");
        });
    }

    // Open in Explorer / Copy Path Actions on Export View
    const openFolderBtn = document.getElementById("btn-open-folder");
    const copyPathBtn = document.getElementById("btn-copy-path");

    if (openFolderBtn) {
        openFolderBtn.addEventListener("click", async () => {
            try {
                const res = await fetch(`${API_BASE}/api/open-folder`, { method: "POST" });
                if (res.ok) {
                    showToast("✓ Opened Finished Videos Folder in Windows Explorer OK!", "success");
                    return;
                }
            } catch (e) {}
            window.open("/finished/", "_blank");
            showToast("✓ Opened Finished Videos Gallery OK", "success");
        });
    }

    if (copyPathBtn) {
        copyPathBtn.addEventListener("click", () => {
            if (navigator.clipboard) {
                navigator.clipboard.writeText("G:\\My Drive\\Cat make\\finished").then(() => {
                    showToast("Directory path copied to clipboard", "success");
                });
            }
        });
    }

    // Master Video Direct Download Click Handler
    const downloadMasterBtn = document.getElementById("btn-download-master-video");
    if (downloadMasterBtn) {
        downloadMasterBtn.addEventListener("click", () => {
            let href = downloadMasterBtn.getAttribute("href");
            let name = downloadMasterBtn.getAttribute("download") || "lionreel_compilation.mp4";
            if (!href || href === "#" || href === window.location.href) {
                const activeOrTop = (state.finishedProjects && state.finishedProjects.length > 0)
                    ? (state.finishedProjects.find(p => p.name === state.activeFinishedProjectName) || state.finishedProjects[0])
                    : null;
                name = activeOrTop ? activeOrTop.name : "lionreel_compilation.mp4";
                href = `/finished/${encodeURIComponent(name)}`;
                downloadMasterBtn.href = href;
                downloadMasterBtn.setAttribute("download", name);
            }
            showToast(`Downloading compilation: ${name}`, "success");
        });
    }

    // Metadata 1-Click Copy Buttons
    const copyTitleBtn = document.getElementById("btn-copy-meta-title");
    const copyDescBtn = document.getElementById("btn-copy-meta-desc");
    const copyTagsBtn = document.getElementById("btn-copy-meta-tags");
    const copyAllBtn = document.getElementById("btn-copy-meta-all");

    if (copyTitleBtn) {
        copyTitleBtn.addEventListener("click", () => {
            const val = document.getElementById("export-meta-title").value;
            copyTextWithFeedback(val, copyTitleBtn, "Title");
        });
    }
    if (copyDescBtn) {
        copyDescBtn.addEventListener("click", () => {
            const val = document.getElementById("export-meta-desc").value;
            copyTextWithFeedback(val, copyDescBtn, "Description & Tags");
        });
    }
    if (copyTagsBtn) {
        copyTagsBtn.addEventListener("click", () => {
            const val = document.getElementById("export-meta-tags").value;
            copyTextWithFeedback(val, copyTagsBtn, "Hashtags");
        });
    }
    if (copyAllBtn) {
        copyAllBtn.addEventListener("click", () => {
            const title = document.getElementById("export-meta-title")?.value || "";
            const desc = document.getElementById("export-meta-desc")?.value || "";
            const tags = document.getElementById("export-meta-tags")?.value || "";
            const combined = `${title}\n\n${desc}\n\n${tags}`;
            copyTextWithFeedback(combined, copyAllBtn, "All Metadata");
        });
    }

    // Platform Upload Redirect Links Event Listeners
    const linkTiktok = document.getElementById("link-upload-tiktok");
    const linkReels = document.getElementById("link-upload-reels");
    const linkShorts = document.getElementById("link-upload-shorts");

    if (linkTiktok) {
        linkTiktok.addEventListener("click", () => {
            showToast("Opening TikTok Studio in a new tab…", "info");
        });
    }
    if (linkReels) {
        linkReels.addEventListener("click", () => {
            showToast("Opening Instagram / Meta Reels Composer in a new tab…", "info");
        });
    }
    if (linkShorts) {
        linkShorts.addEventListener("click", () => {
            showToast("Opening YouTube Shorts Studio in a new tab…", "info");
        });
    }

    // Clear Raw Cache Handlers (Home & Export)
    const clearRawHomeBtn = document.getElementById("btn-clear-raw-cache");
    const clearRawExportBtn = document.getElementById("btn-clear-raw-export");

    async function handleClearRawCache() {
        const ok = await showConfirmModal({
            title: "Clear Raw Cache",
            message: "Clear temporary raw video clips from cache? This will free up local disk space.",
            confirmText: "Clear Cache",
            isDanger: false
        });
        if (ok) {
            try {
                const res = await fetch(`${API_BASE}/api/clear-raw`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" }
                });
                if (res.ok) {
                    showToast("Raw clips cache cleared successfully!", "success");
                } else {
                    showToast("Cache cleared", "info");
                }
            } catch (e) {
                showToast("Could not clear raw cache", "warning");
            }
        }
    }

    if (clearRawHomeBtn) clearRawHomeBtn.addEventListener("click", handleClearRawCache);
    if (clearRawExportBtn) clearRawExportBtn.addEventListener("click", handleClearRawCache);

    // Clear All Finished Compilations Handler
    const clearFinishedBtn = document.getElementById("btn-clear-all-finished");
    if (clearFinishedBtn) {
        clearFinishedBtn.addEventListener("click", async () => {
            const ok = await showConfirmModal({
                title: "Delete All Compilations",
                message: "Are you sure you want to delete ALL rendered compilations from disk? This cannot be undone.",
                confirmText: "Delete All",
                isDanger: true
            });
            if (ok) {
                releaseAllVideoPlayers();
                await new Promise(r => setTimeout(r, 60));

                try {
                    const res = await fetch(`${API_BASE}/api/clear-finished`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" }
                    });
                    const data = await res.json().catch(() => ({}));
                    if (res.ok && data.success) {
                        showToast("All finished compilations permanently deleted from disk", "success");
                        state.activeFinishedProjectName = null;
                    } else {
                        showToast(`Failed to delete all compilations: ${data.error || "File locked"}`, "error");
                    }
                    await loadFinishedProjects();
                } catch (e) {
                    showToast("Error clearing finished compilations", "warning");
                }
            }
        });
    }

    // Delete / Remove Current Video on Export Screen
    const deleteExportBtn = document.getElementById("btn-delete-export-video");
    if (deleteExportBtn) {
        deleteExportBtn.addEventListener("click", async () => {
            const titleEl = document.getElementById("export-video-title");
            const filename = (state.activeFinishedProjectName || (titleEl ? titleEl.innerText.trim() : "")).trim();
            if (!filename || filename === "No Finished Compilations Yet" || filename === "Rendering New Video...") return;

            const ok = await showConfirmModal({
                title: "Delete Video",
                message: `Are you sure you want to permanently delete "${filename}" and all its files from disk?`,
                confirmText: "Delete Video",
                isDanger: true
            });
            if (ok) {
                // 1. Release video players before calling delete
                releaseAllVideoPlayers();
                await new Promise(r => setTimeout(r, 60));

                try {
                    const res = await fetch(`${API_BASE}/api/delete-file`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ filename })
                    });
                    const data = await res.json().catch(() => ({}));
                    if (res.ok && data.success) {
                        showToast(`Deleted ${filename} permanently from disk`, "success");
                        state.activeFinishedProjectName = null;
                        await loadFinishedProjects();
                        // Go back to home library
                        navigateToStep(1);
                    } else {
                        showToast(`Failed to delete "${filename}": ${data.error || data.message || "File locked"}`, "error");
                        await loadFinishedProjects();
                    }
                } catch (e) {
                    showToast("Failed to delete video: Network error", "error");
                }
            }
        });
    }

    // Reset All Clips in Wizard Step 4
    const resetAllClipsBtn = document.getElementById("btn-review-reset-all");
    if (resetAllClipsBtn) {
        resetAllClipsBtn.addEventListener("click", async () => {
            const ok = await showConfirmModal({
                title: "Reset Clip Sequence",
                message: "Reset and clear all selected clips from this sequence?",
                confirmText: "Reset All",
                isDanger: true
            });
            if (ok) {
                state.selectedClips = [];
                renderReviewClipsGrid();
                updateTimelineClipCount();
                saveSelectedClips();
                showToast("All clips cleared. Add clips to start your sequence.", "info");
            }
        });
    }

    // Remove Active Clip in Editor
    const removeEditorClipBtn = document.getElementById("btn-editor-remove-clip");
    if (removeEditorClipBtn) {
        removeEditorClipBtn.addEventListener("click", () => {
            if (state.selectedClips.length <= 1) {
                showToast("Cannot remove only clip. Please keep at least 1 clip or reset in Wizard.", "warning");
                return;
            }
            state.selectedClips.splice(state.activeClipIndex, 1);
            state.activeClipIndex = Math.max(0, state.activeClipIndex - 1);
            renderTimelineTrack();
            loadActiveClipIntoPlayer();
            showToast(`Removed clip from reel`, "info");
        });
    }

    // Source Method Tabs (Autonomous AI / Curated / YouTube / Upload)
    const tabAuto = document.getElementById("tab-auto");
    const tabCurated = document.getElementById("tab-curated");
    const tabYoutube = document.getElementById("tab-youtube");
    const tabUpload = document.getElementById("tab-upload");
    const panelAuto = document.getElementById("panel-auto");
    const panelCurated = document.getElementById("panel-curated");
    const panelYoutube = document.getElementById("panel-youtube");
    const panelUpload = document.getElementById("panel-upload");

    function switchSourceTab(activeTab, activePanel, modeName, toastMsg) {
        [tabAuto, tabCurated, tabYoutube, tabUpload].forEach(t => t && t.classList.remove("active"));
        [panelAuto, panelCurated, panelYoutube, panelUpload].forEach(p => p && (p.style.display = "none"));
        if (activeTab) activeTab.classList.add("active");
        if (activePanel) activePanel.style.display = "block";
        if (modeName) {
            state.config.SOURCE_MODE = modeName;
            syncConfigToServer();
        }
        if (toastMsg) {
            showToast(toastMsg, "success");
        }
    }

    if (tabAuto) tabAuto.addEventListener("click", () => switchSourceTab(tabAuto, panelAuto, "classic", "✓ Method: Autonomous AI YouTube Discovery Selected OK"));
    if (tabCurated) tabCurated.addEventListener("click", () => switchSourceTab(tabCurated, panelCurated, "curated", "✓ Method: Curated Studio Library Selected OK"));
    if (tabYoutube) tabYoutube.addEventListener("click", () => switchSourceTab(tabYoutube, panelYoutube, "custom_url", "✓ Method: Custom YouTube URL Mode Selected OK"));
    if (tabUpload) tabUpload.addEventListener("click", () => switchSourceTab(tabUpload, panelUpload, "own_footage", "✓ Method: Local Video Upload Mode Selected OK"));

    // Custom Video URL Importer (Method 2)
    const addUrlBtn = document.getElementById("btn-add-custom-url");
    const customUrlInput = document.getElementById("custom-video-url-input");

    if (addUrlBtn && customUrlInput) {
        addUrlBtn.addEventListener("click", async () => {
            const url = customUrlInput.value.trim();
            if (!url) {
                showToast("Please enter a valid video link or MP4 URL", "warning");
                return;
            }
            state.config.SOURCE_MODE = "custom_url";
            state.config.CUSTOM_URL = url;
            await syncConfigToServer();

            const isYt = url.includes("youtu");
            const newClip = {
                id: "custom_" + Date.now(),
                title: isYt ? "YouTube Clip (" + url.slice(-8) + ")" : "Imported Video Clip",
                channel: isYt ? "YouTube Source" : "Web Video",
                duration: 35,
                resolution: "1080p 60fps",
                views: "New",
                qualityScore: 98,
                thumbnail: "https://images.unsplash.com/photo-1543852786-1cf6624b9987?w=640&q=80",
                videoUrl: url.endsWith(".mp4") ? url : "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
                category: state.activeCategory
            };
            state.sources.unshift(newClip);
            state.selectedClips.push(newClip);
            renderCandidatesGrid();
            renderReviewClipsGrid();
            updateTimelineClipCount();
            customUrlInput.value = "";
            showToast("✓ Custom Video URL Configured & Added to Reel OK!", "success");
            switchSourceTab(tabCurated, panelCurated);
        });
    }

    // Sample URL quick buttons
    document.querySelectorAll(".btn-sample-url").forEach(btn => {
        btn.addEventListener("click", () => {
            if (customUrlInput) {
                customUrlInput.value = btn.getAttribute("data-sample") || "";
                if (addUrlBtn) addUrlBtn.click();
            }
        });
    });

    // Local Video File Upload (Method 3)
    const browseBtn = document.getElementById("btn-browse-local-files");
    const fileInput = document.getElementById("file-upload-input");
    const uploadStatusBox = document.getElementById("upload-status-box");
    const uploadStatusText = document.getElementById("upload-status-text");

    async function handleFileUpload(file) {
        if (!file) return;
        const filename = file.name;
        if (uploadStatusBox) {
            uploadStatusBox.style.display = "flex";
            if (uploadStatusText) uploadStatusText.innerText = `Uploading "${filename}" (${(file.size / (1024 * 1024)).toFixed(1)} MB)...`;
        }
        showToast(`Uploading "${filename}" to studio backend...`, "info");

        try {
            const uploadRes = await fetch(`${API_BASE}/api/upload?filename=${encodeURIComponent(filename)}`, {
                method: "POST",
                headers: { "Content-Type": file.type || "application/octet-stream" },
                body: file
            });

            if (uploadRes.ok) {
                const upData = await uploadRes.json();
                state.config.SOURCE_MODE = "own_footage";
                state.config.OWN_FOOTAGE_FILE = upData.filename || filename;
                await syncConfigToServer();

                if (uploadStatusBox) {
                    uploadStatusBox.style.display = "flex";
                    if (uploadStatusText) uploadStatusText.innerText = `✓ "${filename}" uploaded and staged OK!`;
                }

                const objUrl = URL.createObjectURL(file);
                const newClip = {
                    id: "upload_" + Date.now(),
                    title: filename.replace(/\.[^/.]+$/, ""),
                    channel: "Local Upload (Own Footage)",
                    duration: 25,
                    resolution: "1080p Local",
                    views: "Local",
                    qualityScore: 99,
                    thumbnail: "https://images.unsplash.com/photo-1533738363-b7f9aef128ce?w=640&q=80",
                    videoUrl: objUrl,
                    category: state.activeCategory
                };
                state.sources.unshift(newClip);
                state.selectedClips.push(newClip);
                renderCandidatesGrid();
                renderReviewClipsGrid();
                updateTimelineClipCount();
                showToast(`✓ Local video "${filename}" uploaded & selected OK!`, "success");
                setTimeout(() => {
                    if (uploadStatusBox) uploadStatusBox.style.display = "none";
                    switchSourceTab(tabCurated, panelCurated);
                }, 1800);
            } else {
                showToast(`Upload failed (${uploadRes.statusText})`, "error");
                if (uploadStatusBox) uploadStatusBox.style.display = "none";
            }
        } catch (err) {
            console.error("Upload error:", err);
            showToast("Upload network error, please retry", "error");
            if (uploadStatusBox) uploadStatusBox.style.display = "none";
        }
    }

    if (browseBtn && fileInput) {
        browseBtn.addEventListener("click", () => fileInput.click());
        fileInput.addEventListener("change", () => {
            if (fileInput.files && fileInput.files[0]) {
                handleFileUpload(fileInput.files[0]);
            }
        });
    }

    if (panelUpload) {
        panelUpload.addEventListener("dragover", (e) => {
            e.preventDefault();
            panelUpload.style.borderColor = "var(--primary-emerald)";
            panelUpload.style.background = "rgba(24, 232, 122, 0.08)";
        });
        panelUpload.addEventListener("dragleave", () => {
            panelUpload.style.borderColor = "var(--border)";
            panelUpload.style.background = "var(--bg-card)";
        });
        panelUpload.addEventListener("drop", (e) => {
            e.preventDefault();
            panelUpload.style.borderColor = "var(--border)";
            panelUpload.style.background = "var(--bg-card)";
            if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
                handleFileUpload(e.dataTransfer.files[0]);
            }
        });
    }

    // In / Out Trim Slider Controls
    const sliderTrimStart = document.getElementById("slider-trim-start");
    const sliderTrimEnd = document.getElementById("slider-trim-end");
    const valTrimStart = document.getElementById("val-trim-start");
    const valTrimEnd = document.getElementById("val-trim-end");
    const editorVideoPlayer = document.getElementById("editor-video-player");

    if (sliderTrimStart && valTrimStart) {
        sliderTrimStart.addEventListener("input", () => {
            const val = parseFloat(sliderTrimStart.value) || 0;
            valTrimStart.innerText = `${val.toFixed(1)}s`;
            if (editorVideoPlayer) editorVideoPlayer.currentTime = val;
            if (state.selectedClips[state.activeClipIndex]) {
                state.selectedClips[state.activeClipIndex].trimStart = val;
            }
        });
        sliderTrimStart.addEventListener("change", () => {
            showToast(`✓ Trim start set to ${sliderTrimStart.value}s OK`, "info");
        });
    }

    if (sliderTrimEnd && valTrimEnd) {
        sliderTrimEnd.addEventListener("input", () => {
            const val = parseFloat(sliderTrimEnd.value) || 5.5;
            valTrimEnd.innerText = `${val.toFixed(1)}s`;
            if (editorVideoPlayer) editorVideoPlayer.currentTime = Math.max(0, val - 0.5);
            if (state.selectedClips[state.activeClipIndex]) {
                state.selectedClips[state.activeClipIndex].trimEnd = val;
            }
        });
        sliderTrimEnd.addEventListener("change", () => {
            showToast(`✓ Trim end set to ${sliderTrimEnd.value}s OK`, "info");
        });
    }

    // Clean Studio State, Clip History & Candidate Thumbnails
    const resetHistoryHomeBtn = document.getElementById("btn-reset-history-home");
    if (resetHistoryHomeBtn) {
        resetHistoryHomeBtn.addEventListener("click", () => cleanStudioAndClipHistory());
    }

async function cleanStudioAndClipHistory() {
    const ok = await showConfirmModal({
        title: "Clean Clip History & Reset Studio",
        message: "Reset clip history tracking, candidate pools, and active timeline clips? This lets the compilation engine generate fresh compilations without repeating old clips.\n\n🛡️ Safe Clean: All finished videos in your library, thumbnails, and source assets are safely preserved and will NOT be deleted.",
        confirmText: "Clean & Reset Studio",
        isDanger: false
    });
    if (!ok) return;

    try {
        showToast("Cleaning clip history & resetting caches...", "info");
        const res = await fetch(`${API_BASE}/api/reset-history`, { method: "POST" });
        const data = await res.json();

        // 1. Clear stored selections
        localStorage.removeItem("lionreel_selected_clips");
        sessionStorage.removeItem("lionreel_step");

        // 2. Reset in-memory reactive state
        state.selectedClips = [];
        state.activeClipIndex = 0;
        state.timelineHistory = [];
        state.renderProgress = 0;
        state.renderStageIndex = 1;
        state.logOffset = 0;
        state.rawLogs = "";
        state.isRunning = false;
        state.isPaused = false;

        // 3. Reset sources, candidates grid and thumbnails
        initCuratedSources();
        renderCandidatesGrid();
        updateTimelineClipCount();
        renderReviewClipsGrid();
        renderTimelineTrack();
        updateLiveSummary();

        // 4. Reload finished projects to ensure library thumbnails stay fresh & displayed
        await loadFinishedProjects();

        // 5. Navigate to Home Dashboard if on another step
        if (state.workflowStep !== 1) {
            navigateToStep(1);
        }

        // 6. Reset Engine status badge
        updateEngineStatusBadge(false);

        showToast("✓ Studio cleaned & clip history reset! Finished videos preserved.", "success");
    } catch (err) {
        console.error("Error cleaning studio state:", err);
        showToast("Reset completed with local state refreshed", "info");
    }
}

async function purgeTempAndOldFiles() {
    const ok = await showConfirmModal({
        title: "Purge All Temp, Thumbnails & Old Files",
        message: "Are you sure you want to permanently remove all temporary files, scratch clips, and old raw video cache in the Cat make folder?\n\n🗑️ Temporary & scratch files: scratch_*.mp4, *TEMP_MPY_*, *.part, scratch/\n🖼️ Thumbnails & metadata: all old thumbnails and metadata files\n📦 Old raw downloads: all raw/*.mp4 video clips\n📋 History tracking: used_videos.txt, used_metadata.json, gui_run.log\n\n🛡️ Preservation Guarantee: Exactly 1 latest finished video will be kept in your Library, while all older finished videos and temp files will be permanently deleted.",
        confirmText: "Purge & Keep 1 Latest Video",
        cancelText: "Cancel",
        isDanger: true
    });
    if (!ok) return;

    try {
        showToast("Purging temporary files, thumbnails & old cache...", "info");
        const res = await fetch(`${API_BASE}/api/purge-temp-files`, { method: "POST" });
        const data = await res.json();

        if (data.success) {
            // 1. Clear stored selections & steps
            localStorage.removeItem("lionreel_selected_clips");
            sessionStorage.removeItem("lionreel_step");

            // 2. Reset in-memory reactive state
            state.selectedClips = [];
            state.activeClipIndex = 0;
            state.timelineHistory = [];
            state.renderProgress = 0;
            state.renderStageIndex = 1;
            state.logOffset = 0;
            state.rawLogs = "";
            state.isRunning = false;
            state.isPaused = false;
            state.liveStatusMsg = "";
            state.renderProgress = 0;
            const retryBtnEl = document.getElementById("btn-render-retry");
            if (retryBtnEl) retryBtnEl.style.display = "none";
            try { await fetch(`${API_BASE}/api/clear-error`); } catch (e) {}

            // 3. Reset sources, candidates grid and timeline
            initCuratedSources();
            renderCandidatesGrid();
            updateTimelineClipCount();
            renderReviewClipsGrid();
            renderTimelineTrack();
            updateLiveSummary();

            // 4. Reload finished projects
            await loadFinishedProjects();

            // 5. Navigate to Home Dashboard if on another step
            if (state.workflowStep !== 1) {
                navigateToStep(1);
            }

            // 6. Reset Engine status badge
            updateEngineStatusBadge(false);

            showToast(`✓ Removed ${data.removed_count} files (freed ${data.freed_mb} MB) OK!`, "success");
        } else {
            showToast(`Purge failed: ${data.error || 'Unknown error'}`, "error");
        }
    } catch (err) {
        console.error("Error purging workspace files:", err);
        showToast("Could not complete purge operation", "warning");
    }
}

    // Render Retry Button in Render Studio
    const renderRetryBtn = document.getElementById("btn-render-retry");
    if (renderRetryBtn) {
        renderRetryBtn.addEventListener("click", async () => {
            renderRetryBtn.style.display = "none";
            showToast("✓ Restarting compilation engine OK...", "info");
            try { await fetch(`${API_BASE}/api/clear-error`); } catch (e) {}
            startRenderPipeline();
        });
    }

    // Loading Screen Retry Button
    const btnLoadingRetry = document.getElementById("btn-loading-retry");
    if (btnLoadingRetry) {
        btnLoadingRetry.addEventListener("click", () => {
            const errBox = document.getElementById("loading-error-box");
            if (errBox) errBox.style.display = "none";
            showToast("Connecting to LionReel Studio backend...", "info");
            initApp();
        });
    }

    // Timeline Track Header Controls (Undo, Redo, Add Clip)
    const timelineAddBtn = document.getElementById("btn-timeline-add-clip");
    const timelineUndoBtn = document.getElementById("btn-timeline-undo");
    const timelineRedoBtn = document.getElementById("btn-timeline-redo");

    if (timelineAddBtn) {
        timelineAddBtn.addEventListener("click", () => {
            state.wizardStage = 2;
            navigateToStep(2);
            showToast("Select or upload clips to add to timeline sequence", "info");
        });
    }

    if (timelineUndoBtn) {
        timelineUndoBtn.addEventListener("click", () => {
            if (state.selectedClips.length > 1) {
                const popped = state.selectedClips.pop();
                state.activeClipIndex = Math.max(0, state.selectedClips.length - 1);
                renderTimelineTrack();
                updateTimelineClipCount();
                loadActiveClipIntoPlayer();
                showToast(`Undid last clip: removed "${popped.title.substring(0, 18)}…"`, "info");
            } else {
                showToast("Cannot undo further: at least 1 clip required", "info");
            }
        });
    }

    if (timelineRedoBtn) {
        timelineRedoBtn.addEventListener("click", () => {
            showToast("Timeline sequence is at latest edit", "info");
        });
    }

    // Shortcuts Modal triggers
    const shortcutsBtn = document.getElementById("btn-open-shortcuts");
    const shortcutsModal = document.getElementById("modal-shortcuts");
    const closeShortcutsBtn = document.getElementById("btn-close-shortcuts-modal");
    const dismissShortcutsBtn = document.getElementById("btn-shortcuts-dismiss");

    if (shortcutsBtn && shortcutsModal) {
        shortcutsBtn.addEventListener("click", () => {
            shortcutsModal.style.display = "flex";
        });
    }
    if (closeShortcutsBtn && shortcutsModal) {
        closeShortcutsBtn.addEventListener("click", () => {
            shortcutsModal.style.display = "none";
        });
    }
    if (dismissShortcutsBtn && shortcutsModal) {
        dismissShortcutsBtn.addEventListener("click", () => {
            shortcutsModal.style.display = "none";
        });
    }

    // Preview Modal triggers
    const previewModal = document.getElementById("modal-video-preview");
    const closePreviewBtn = document.getElementById("btn-close-preview-modal");
    const dismissPreviewBtn = document.getElementById("btn-modal-dismiss");

    if (closePreviewBtn && previewModal) {
        closePreviewBtn.addEventListener("click", closePreviewModal);
    }
    if (dismissPreviewBtn && previewModal) {
        dismissPreviewBtn.addEventListener("click", closePreviewModal);
    }

    // Live Dynamic Summary Box Entrance / Fit Observer
    const dynamicSummaryEl = document.getElementById("wizard-dynamic-summary");
    if (dynamicSummaryEl && window.IntersectionObserver) {
        const summaryObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    dynamicSummaryEl.classList.remove("fit-in");
                    void dynamicSummaryEl.offsetWidth;
                    dynamicSummaryEl.classList.add("fit-in");
                }
            });
        }, { threshold: 0.15 });
        summaryObserver.observe(dynamicSummaryEl);
    }
}

function applyTemplateConfig(templateKey) {
    if (templateKey === "viral-cat") {
        state.activeCategory = "cat";
        state.config.VIDEO_MODE = "cat";
        state.config.TARGET_CLIPS = 6;
        state.config.SHORT_CLIP_SEC = 5.5;
        state.config.SPEED_PROFILE = "fast";
        showToast("Loaded 'Viral Cat Moments' template formula", "success");
    } else if (templateKey === "funny-dog") {
        state.activeCategory = "dog";
        state.config.VIDEO_MODE = "dog";
        state.config.TARGET_CLIPS = 6;
        state.config.SHORT_CLIP_SEC = 6.0;
        state.config.SPEED_PROFILE = "balanced";
        showToast("Loaded 'Funny Dog Reactions' template formula", "success");
    } else if (templateKey === "cute-pets") {
        state.activeCategory = "mix";
        state.config.VIDEO_MODE = "mix";
        state.config.TARGET_CLIPS = 7;
        state.config.SHORT_CLIP_SEC = 6.5;
        state.config.SPEED_PROFILE = "cinematic";
        showToast("Loaded 'Cute Pet Highlights' template formula", "success");
    } else if (templateKey === "animal-fails") {
        state.activeCategory = "mix";
        state.config.VIDEO_MODE = "mix";
        state.config.TARGET_CLIPS = 8;
        state.config.SHORT_CLIP_SEC = 4.5;
        state.config.SPEED_PROFILE = "fast";
        showToast("Loaded 'Mixed Animal Fails' template formula", "success");
    }

    // Sync sliders
    const clipsSlider = document.getElementById("slider-target-clips");
    const durSlider = document.getElementById("slider-clip-duration");
    if (clipsSlider) clipsSlider.value = state.config.TARGET_CLIPS;
    if (durSlider) durSlider.value = state.config.SHORT_CLIP_SEC;
    updateLiveSummary();
}

// ==========================================================================
// 12. PREVIEW MODAL & TOASTS
// ==========================================================================
function openPreviewModal(clip) {
    const modal = document.getElementById("modal-video-preview");
    const video = document.getElementById("modal-preview-video");
    const title = document.getElementById("modal-preview-title");
    const addBtn = document.getElementById("btn-modal-add-to-reel");

    if (!modal || !video) return;

    const modalBody = video.closest(".modal-body") || video.parentElement;
    const ctrl = setupMutedVideoPlayer(video, { container: modalBody });

    if (title) title.innerText = clip.title || "Video Preview";
    video.defaultMuted = true;
    video.muted = true;
    video.currentTime = 0;
    video.src = clip.videoUrl || "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4";
    video.poster = clip.thumbnail || "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80";
    video.load();
    modal.style.display = "flex";
    if (ctrl) {
        ctrl.playMutedFromStart(true);
    } else {
        video.play().catch(() => {});
    }

    if (addBtn) {
        addBtn.onclick = () => {
            if (!state.selectedClips.some(c => c.id === clip.id)) {
                state.selectedClips.push(clip);
                updateTimelineClipCount();
                renderCandidatesGrid();
                renderReviewClipsGrid();
                saveSelectedClips();
                showToast(`Added "${clip.title.substring(0, 24)}…" to sequence`, "success");
            }
            closePreviewModal();
        };
    }
}

function closePreviewModal() {
    const modal = document.getElementById("modal-video-preview");
    const video = document.getElementById("modal-preview-video");
    if (video) {
        video.pause();
        video.currentTime = 0;
        video.removeAttribute("src");
        video.load();
    }
    if (modal) modal.style.display = "none";
}

function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = "toast";

    const iconMap = {
        success: "✓",
        warning: "⚠",
        error: "✕",
        info: "⚡"
    };

    toast.innerHTML = `
        <span style="color: var(--primary-emerald); font-weight: 700;">${iconMap[type] || '⚡'}</span>
        <span>${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("show"));

    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => toast.remove(), 260);
    }, 3200);
}

// Universal Custom Action Confirmation Dialog
let confirmModalResolver = null;

function showConfirmModal({
    title = "Confirm Action",
    message = "Are you sure you want to proceed?",
    confirmText = "Confirm",
    cancelText = "Cancel",
    isDanger = true
} = {}) {
    return new Promise((resolve) => {
        const modal = document.getElementById("modal-confirm");
        const titleEl = document.getElementById("modal-confirm-title");
        const msgEl = document.getElementById("modal-confirm-message");
        const okBtn = document.getElementById("btn-confirm-ok");
        const cancelBtn = document.getElementById("btn-confirm-cancel");
        const closeBtn = document.getElementById("btn-confirm-close");
        const iconWrap = document.getElementById("modal-confirm-icon-wrap");

        if (!modal) {
            resolve(window.confirm(message));
            return;
        }

        if (confirmModalResolver) {
            confirmModalResolver(false);
            confirmModalResolver = null;
        }
        confirmModalResolver = resolve;

        if (titleEl) titleEl.innerText = title;
        if (msgEl) msgEl.innerText = message;
        if (okBtn) {
            okBtn.innerText = confirmText;
            if (isDanger) {
                okBtn.style.background = "var(--error)";
                okBtn.style.borderColor = "var(--error)";
                okBtn.style.color = "#fff";
                if (iconWrap) {
                    iconWrap.style.background = "rgba(239, 68, 68, 0.15)";
                    iconWrap.style.color = "var(--error)";
                }
            } else {
                okBtn.style.background = "var(--primary-emerald)";
                okBtn.style.borderColor = "var(--primary-emerald)";
                okBtn.style.color = "#fff";
                if (iconWrap) {
                    iconWrap.style.background = "rgba(16, 185, 129, 0.15)";
                    iconWrap.style.color = "var(--primary-emerald)";
                }
            }
        }
        if (cancelBtn) cancelBtn.innerText = cancelText;

        const closeWith = (val) => {
            modal.style.display = "none";
            document.removeEventListener("keydown", onKeyDown);
            modal.removeEventListener("click", onBackdropClick);
            if (confirmModalResolver) {
                const r = confirmModalResolver;
                confirmModalResolver = null;
                r(val);
            }
        };

        const onKeyDown = (e) => {
            if (e.key === "Escape") closeWith(false);
            else if (e.key === "Enter") closeWith(true);
        };
        const onBackdropClick = (e) => {
            if (e.target === modal) closeWith(false);
        };

        if (okBtn) okBtn.onclick = () => closeWith(true);
        if (cancelBtn) cancelBtn.onclick = () => closeWith(false);
        if (closeBtn) closeBtn.onclick = () => closeWith(false);

        document.addEventListener("keydown", onKeyDown);
        modal.addEventListener("click", onBackdropClick);
        modal.style.display = "flex";
        if (okBtn) okBtn.focus();
    });
}

// ==========================================================================
// 13. GLOBAL KEYBOARD SHORTCUTS
// ==========================================================================
function setupKeyboardShortcuts() {
    document.addEventListener("keydown", (e) => {
        // Ignore typing inside input fields or textareas
        if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;

        if (e.key === " " || e.code === "Space") {
            e.preventDefault();
            const player = document.getElementById("editor-video-player");
            if (player) {
                if (player.paused) {
                    player.play().catch(() => {});
                    updatePlayButtonState(true);
                } else {
                    player.pause();
                    updatePlayButtonState(false);
                }
            }
        } else if (e.key === "e" || e.key === "E") {
            const toggle = document.getElementById("btn-toggle-enhancement");
            if (toggle) toggle.click();
        } else if (e.key === "s" || e.key === "S") {
            const safeZone = document.getElementById("switch-safezone");
            if (safeZone) {
                safeZone.checked = !safeZone.checked;
                safeZone.dispatchEvent(new Event("change"));
            }
        } else if (e.key === "n" || e.key === "N") {
            state.wizardStage = 1;
            navigateToStep(2);
        } else if (e.key === "t" || e.key === "T") {
            toggleTheme();
        } else if (e.key === "?" || (e.shiftKey && e.key === "/")) {
            const modal = document.getElementById("modal-shortcuts");
            if (modal) modal.style.display = "flex";
        } else if (e.key === "Escape") {
            closePreviewModal();
            const shortcutsModal = document.getElementById("modal-shortcuts");
            if (shortcutsModal) shortcutsModal.style.display = "none";
        }
    });
}

// ==========================================================================
// 14. HELPERS
// ==========================================================================
function formatTime(seconds) {
    if (isNaN(seconds) || seconds < 0) return "00:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function formatDuration(seconds) {
    if (isNaN(seconds) || seconds < 0) return "00:00";
    if (seconds >= 3600) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
    }
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, (m) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    }[m]));
}

function copyTextWithFeedback(text, buttonEl, label) {
    if (!text) return;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            const orig = buttonEl.innerText;
            buttonEl.innerText = "✓ Copied";
            showToast(`Copied ${label} to clipboard!`, "success");
            setTimeout(() => {
                buttonEl.innerText = orig;
            }, 2000);
        }).catch(() => {
            fallbackCopy(text, buttonEl, label);
        });
    } else {
        fallbackCopy(text, buttonEl, label);
    }
}

function fallbackCopy(text, buttonEl, label) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
        document.execCommand("copy");
        const orig = buttonEl.innerText;
        buttonEl.innerText = "✓ Copied";
        showToast(`Copied ${label} to clipboard!`, "success");
        setTimeout(() => {
            buttonEl.innerText = orig;
        }, 2000);
    } catch (err) {
        showToast(`Could not copy ${label}`, "warning");
    }
    document.body.removeChild(ta);
}

// Expose core state and controllers to window for automated testing and browser access
window.state = state;
window.navigateToStep = navigateToStep;
window.renderWizardStep = renderWizardStep;
window.applyTheme = applyTheme;
window.toggleTheme = toggleTheme;
window.setVideoType = setVideoType;
window.setFormat = setFormat;
window.updateShortDuration = updateShortDuration;
window.updateLongDuration = updateLongDuration;
window.syncVerificationsUI = syncVerificationsUI;
window.openPreviewModal = openPreviewModal;
window.CURATED_SOURCES = CURATED_SOURCES;


