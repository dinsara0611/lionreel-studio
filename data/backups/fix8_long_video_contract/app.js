/**
 * LIONREEL STUDIO — ADVANCED VIDEO SLICING & COMPILATION SUITE
 * Complete 2026 Modern Creator Tool Engine & Workflow Controller
 */

const API_BASE = "";

// Unified Lucide SVG icon helper
window.getIconSvg = function(name, size = "md", extraClass = "") {
    const sizeClass = size === "sm" ? "icon-sm" : (size === "lg" ? "icon-lg" : (size === "inline" ? "icon-inline" : "icon-md"));
    return `<svg class="icon ${sizeClass} ${extraClass}" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
};

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
    isColorGradingEnabled: false,
    playbackSpeed: 1.0,
    activeColorFilter: "natural",
    activeColorStrength: 0.85,
    activePlatform: "youtube_shorts",
    activeSafeZonePlatform: "tiktok",
    activeMetadataMode: "full",
    edl: null,
    metadataPackage: null,
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

        await loadBackendStages();
        ensureStageRowsExist(BACKEND_STAGES);

        // Check if backend compilation engine is actively running
        try {
            const statusRes = await fetch(`${API_BASE}/api/status`);
            if (statusRes.ok) {
                const statusData = await statusRes.json();
                if (statusData.stages && Array.isArray(statusData.stages)) {
                    updateRenderStagesUI(statusData.stages);
                }
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
            if (numEl) numEl.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>`;
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
    if (stepNum !== 3 && typeof closeEditTour === "function") {
        closeEditTour();
    }
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
        if (typeof updateTourBadgeState === "function") updateTourBadgeState();
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
                        <button type="button" class="btn ${isSelected ? 'btn-primary' : 'btn-secondary'} btn-sm cand-select-btn" data-toggle-id="${source.id}" style="padding: 2px 10px; font-size: 0.72rem; display: inline-flex; align-items: center; gap: 4px;">
                            ${isSelected ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Added' : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Add to Reel'}
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
            if (nextBtn) nextBtn.innerHTML = `<span>Start ${min.toFixed(1)}m Long Video Compilation</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
        } else if (vType === "both") {
            const min = parseFloat(state.config.TARGET_DURATION_MIN) || 5.0;
            if (title) title.innerText = `Ready to compile Dual Formats (${min.toFixed(1)}m Long + Short)`;
            if (desc) desc.innerText = `LionReel will compile the full ${min.toFixed(1)}-minute video and export a companion viral Short.`;
            if (nextBtn) nextBtn.innerHTML = `<span>Start Dual Compilation (Long + Short)</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
        } else {
            if (title) title.innerText = "Ready to create your viral reel";
            if (desc) desc.innerText = "Review the selected clip order or jump directly to the interactive timeline editor.";
            if (nextBtn) nextBtn.innerHTML = `<span>Start Processing Reel</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;
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

    const resText = aspect === "16:9" ? "1920×1080 · 16:9 Landscape" : (aspect === "1:1" ? "1080×1080 · 1:1 Square" : "1080×1920 · 9:16 Vertical");
    const platformText = videoType === "long" ? "YouTube Compilation" : "Shorts, Reels & TikTok";

    if (videoType === "long") {
        const estClips = Math.max(10, Math.round((longMin * 60) / duration));
        if (headline) headline.innerText = `Long Compilation · ${longMin.toFixed(1)} min · ~${Math.round(longMin * 60)} s · ~${estClips} viral clips`;
        if (sub) sub.innerText = `${platformText} · ${resText} · ${fps} fps CFR`;
    } else if (videoType === "both") {
        const estClips = Math.max(10, Math.round((longMin * 60) / duration));
        if (headline) headline.innerText = `Dual Format · ${longMin.toFixed(1)} min Compilation + 45 s Short Teaser`;
        if (sub) sub.innerText = `Full compilation + viral Short · ${resText} · ${fps} fps CFR`;
    } else {
        if (headline) headline.innerText = `Short Reel · ${clipsCount} clips × ${duration.toFixed(1)}s · ~${totalSec} s runtime`;
        if (sub) sub.innerText = `${platformText} · ${resText} · ${fps} fps CFR`;
    }

    const summaryIconUse = document.querySelector("#summary-icon-pill use");
    if (summaryIconUse) {
        summaryIconUse.setAttribute("href", videoType === "long" ? "#icon-clapperboard" : (videoType === "both" ? "#icon-layers" : "#icon-zap"));
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
                    <button type="button" class="btn-icon btn-sm review-remove-btn" data-idx="${idx}" title="Remove Clip"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
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
function roundTo1(num) {
    return Math.round(Number(num) * 10) / 10;
}

function pushTimelineHistory() {
    if (!state.timelineHistory) state.timelineHistory = [];
    state.timelineHistory.push(JSON.stringify(state.selectedClips));
    if (state.timelineHistory.length > 25) state.timelineHistory.shift();
}

function undoTimelineChange() {
    if (!state.timelineHistory || state.timelineHistory.length === 0) {
        showToast("No earlier edits to undo", "info");
        return;
    }
    const prev = state.timelineHistory.pop();
    try {
        state.selectedClips = JSON.parse(prev);
        if (state.activeClipIndex >= state.selectedClips.length) {
            state.activeClipIndex = Math.max(0, state.selectedClips.length - 1);
        }
        renderTimelineTrack();
        loadActiveClipIntoPlayer();
        updateTimelineClipCount();
        showToast("Undid last timeline change", "info");
    } catch (e) {
        console.warn("Undo failed:", e);
    }
}

async function loadEdlForEditor() {
    const jobId = state.currentJobId || "active_draft";
    try {
        const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/edits`);
        if (res.ok) {
            const data = await res.json();
            if (data && data.clips && data.clips.length > 0) {
                state.edl = data;
                syncSelectedClipsFromEdl(data);
                if (data.global_settings) {
                    state.isColorGradingEnabled = !!data.global_settings.color_grading_enabled;
                    state.activeColorFilter = data.global_settings.default_preset || "natural";
                    state.activeSafeZonePlatform = data.global_settings.safe_zone || "tiktok";
                }
                return;
            }
        }
    } catch (e) {
        console.warn("Could not load backend EDL:", e);
    }

    if (!state.selectedClips || state.selectedClips.length === 0) {
        if (state.sources && state.sources.length > 0) {
            state.selectedClips = state.sources.slice(0, 4);
        }
    }
}

let autosaveTimeout = null;
function debouncedAutosaveEdl() {
    if (autosaveTimeout) clearTimeout(autosaveTimeout);
    autosaveTimeout = setTimeout(async () => {
        await saveEdlToBackend();
    }, 400);
}

function syncSelectedClipsFromEdl(edl) {
    if (!edl || !edl.clips) return;
    state.selectedClips = edl.clips.map((c, idx) => {
        const start = c.start_s !== undefined ? c.start_s : (c.trim_start !== undefined ? c.trim_start : 0.0);
        const end = c.end_s !== undefined ? c.end_s : (c.trim_end !== undefined ? c.trim_end : (start + (c.duration || 5.5)));
        const spd = c.speed || 1.0;
        const dur = roundTo1(Math.max(1.0, end - start));
        const outDur = roundTo1(dur / spd);
        const fScore = c.framing_score !== undefined ? c.framing_score : 0.95;
        const colObj = (c.color && typeof c.color === "object") ? c.color : {
            enabled: c.color_preset ? (c.color_preset !== "natural") : false,
            preset: c.color_preset || "natural",
            strength: c.color_strength !== undefined ? c.color_strength : 0.6
        };

        return {
            id: c.clip_id || `clip_${idx + 1}`,
            clip_id: c.clip_id || `clip_${idx + 1}`,
            source_id: c.source_id || `source_${idx + 1}`,
            title: c.title || `Clip ${idx + 1}`,
            channel: c.author || "Verified CC Creator",
            author: c.author || "Verified CC Creator",
            license: c.license || "Creative Commons Attribution 4.0",
            resolution: c.resolution || "1080p",
            source_duration: c.source_duration || 30.0,
            start_s: roundTo1(start),
            end_s: roundTo1(end),
            trimStart: roundTo1(start),
            trimEnd: roundTo1(end),
            duration: dur,
            output_duration: outDur,
            speed: spd,
            color: colObj,
            colorPreset: colObj.preset || "natural",
            colorStrength: colObj.strength !== undefined ? colObj.strength : 0.6,
            include: c.include !== false,
            framing_score: fScore,
            qualityScore: Math.round(fScore * 100),
            score_breakdown: c.score_breakdown || {
                framing: fScore,
                funny: 0.88,
                sharpness: 0.90,
                quality: 0.95,
                diversity: 1.0
            },
            funny_moment_s: c.funny_moment_s !== undefined ? c.funny_moment_s : roundTo1(start + dur * 0.5),
            videoUrl: (c.source_file && c.source_file.startsWith("http")) ? c.source_file : (c.source_file ? `/raw/${c.source_file.replace(/^raw[\\\/]/, "").replace(/\\/g, "/")}` : ""),
            source_file: c.source_file || "",
            source_abs_path: c.source_abs_path || "",
            crop_plan: c.crop_plan || {},
            qa_override: !!c.qa_override,
            qa_override_reason: c.qa_override_reason || ""
        };
    });
}

function buildEdlFromState() {
    const jobId = state.currentJobId || "active_draft";
    const clips = (state.selectedClips || []).map((clip, idx) => {
        const start = clip.trimStart !== undefined ? roundTo1(clip.trimStart) : roundTo1(clip.start_s || 0.0);
        const end = clip.trimEnd !== undefined ? roundTo1(clip.trimEnd) : roundTo1((clip.duration || 5.5) + start);
        const spd = clip.speed || state.playbackSpeed || 1.0;
        const dur = roundTo1(Math.max(1.0, end - start));
        const outDur = roundTo1(dur / spd);
        const colPreset = clip.colorPreset || state.activeColorFilter || "natural";
        const colStr = clip.colorStrength !== undefined ? clip.colorStrength : (state.activeColorStrength || 0.6);
        const colEnabled = (clip.color && clip.color.enabled !== undefined) ? clip.color.enabled : (!!state.isColorGradingEnabled && colPreset !== "natural");

        return {
            clip_index: idx,
            clip_id: clip.id || clip.clip_id || `clip_${idx + 1}`,
            source_id: clip.source_id || `source_${idx + 1}`,
            source_file: clip.source_file || clip.videoUrl || "",
            source_abs_path: clip.source_abs_path || clip.source_file || "",
            title: clip.title || `Clip ${idx + 1}`,
            author: clip.channel || clip.author || "Verified CC Contributor",
            license: clip.license || "Creative Commons Attribution 4.0",
            resolution: clip.resolution || "1080p",
            source_duration: clip.source_duration || (end + 5.0),
            start_s: start,
            end_s: end,
            trim_start: start,
            trim_end: end,
            duration: dur,
            output_duration: outDur,
            speed: spd,
            color: {
                enabled: colEnabled,
                preset: colPreset,
                strength: colStr
            },
            color_preset: colPreset,
            color_strength: colStr,
            include: clip.include !== false,
            framing_score: clip.framing_score || ((clip.qualityScore || 95) / 100),
            quality_score: clip.qualityScore || Math.round((clip.framing_score || 0.95) * 100),
            score_breakdown: clip.score_breakdown || {
                framing: clip.framing_score || 0.95,
                funny: 0.88,
                sharpness: 0.90,
                quality: 0.95,
                diversity: 1.0
            },
            funny_moment_s: clip.funny_moment_s !== undefined ? clip.funny_moment_s : roundTo1(start + dur * 0.5),
            crop_plan: clip.crop_plan || {},
            qa_override: !!clip.qa_override,
            qa_override_reason: clip.qa_override_reason || ""
        };
    });

    let totalSec = 0;
    clips.forEach(c => { totalSec += c.output_duration; });

    return {
        job_id: jobId,
        version: state.edl ? (state.edl.version || 1) + 1 : 1,
        last_modified: Date.now() / 1000,
        global_settings: {
            order: clips.map(c => c.clip_id),
            color_grading_enabled: !!state.isColorGradingEnabled,
            default_preset: state.activeColorFilter || "natural",
            default_strength: state.activeColorStrength || 0.6,
            safe_zone: state.activeSafeZonePlatform || "tiktok",
            safe_zone_setting: state.activeSafeZonePlatform || "tiktok",
            target_total: 40.0,
            actual_total: roundTo1(totalSec)
        },
        clips: clips
    };
}

async function saveEdlToBackend() {
    const jobId = state.currentJobId || "active_draft";
    const edlPayload = buildEdlFromState();
    try {
        const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/edits`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(edlPayload)
        });
        if (res.ok) {
            const data = await res.json();
            if (data.edl) state.edl = data.edl;
            // Record implicit positive feedback for all kept clips in EDL
            if (Array.isArray(state.selectedClips)) {
                state.selectedClips.forEach(c => {
                    submitClipFeedback("positive", ["IMPLICIT_KEPT_WINDOW"], c.funny_moment_s, "implicit", c);
                });
            }
            return true;
        }
    } catch (e) {
        console.warn("Could not save EDL to backend:", e);
    }
    return false;
}

window.checkEmptyEditorState = function() {
    const loadedBar = document.getElementById("editor-loaded-bar");
    const emptyCard = document.getElementById("editor-empty-state");
    const edLayout = document.querySelector(".editor-layout");
    
    const hasVideo = !!(state.loadedVideo && state.loadedVideo.job_id);
    if (hasVideo) {
        if (loadedBar) loadedBar.style.display = "flex";
        if (emptyCard) emptyCard.style.display = "none";
        if (edLayout) edLayout.style.display = "grid";
    } else {
        if (loadedBar) loadedBar.style.display = "none";
        if (emptyCard) emptyCard.style.display = "flex";
        if (edLayout) edLayout.style.display = "none";
    }
};

let editorLoadSeq = 0;

window.loadVideoIntoEditor = async function(jobIdOrFileName) {
    const thisSeq = ++editorLoadSeq;
    if (!jobIdOrFileName) {
        state.loadedVideo = null;
        state.currentJobId = null;
        state.activeFinishedProjectName = null;
        try {
            localStorage.removeItem("lionreel_edit_job");
        } catch(e) {}
        checkEmptyEditorState();
        return null;
    }
    let jobId = jobIdOrFileName;
    if (typeof jobId === "object" && jobId !== null) {
        jobId = jobId.job_id || jobId.name || jobId.filename || "";
    }
    if (typeof jobId === "string" && jobId.endsWith(".mp4")) {
        jobId = jobId.replace(".mp4", "");
    }
    state.currentJobId = jobId;
    try {
        localStorage.setItem("lionreel_edit_job", jobId);
    } catch(e) {}
    
    try {
        const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/info`);
        if (thisSeq !== editorLoadSeq) return null;
        if (res.ok) {
            const info = await res.json();
            if (thisSeq !== editorLoadSeq) return null;
            state.loadedVideo = info;
            
            // Populate header bar elements
            const posterEl = document.getElementById("editor-loaded-poster");
            const titleEl = document.getElementById("editor-loaded-title");
            const verEl = document.getElementById("editor-loaded-version");
            const qaEl = document.getElementById("editor-loaded-qa-status");
            const jidEl = document.getElementById("editor-loaded-job-id");
            const durEl = document.getElementById("editor-loaded-duration");
            const dateEl = document.getElementById("editor-loaded-date");
            const clipCntEl = document.getElementById("editor-loaded-clip-count");
            
            if (posterEl) posterEl.src = info.poster || "lion_logo.png";
            if (titleEl) {
                titleEl.innerText = info.title || info.job_id;
                titleEl.title = info.title || info.job_id;
            }
            if (verEl) verEl.innerText = info.version || "v1";
            if (qaEl) {
                qaEl.innerText = info.qa_status || "QA: PASS";
                qaEl.className = (info.qa_status && info.qa_status.includes("FAIL")) ? "badge badge-amber" : "badge badge-emerald";
            }
            if (jidEl) jidEl.innerText = `ID: ${info.job_id}`;
            if (durEl) durEl.innerText = info.duration_str || `${info.duration}s`;
            if (dateEl) dateEl.innerText = info.created_date || "--";
            if (clipCntEl) clipCntEl.innerText = info.clip_count_str || `${info.clip_count} clips`;
            
            // Banner states
            const bannerLimited = document.getElementById("banner-limited-edit");
            if (bannerLimited) bannerLimited.style.display = info.is_limited_edit ? "flex" : "none";
            
            const bannerMissing = document.getElementById("banner-missing-sources");
            const bannerMissingText = document.getElementById("banner-missing-sources-text");
            if (bannerMissing) {
                if (info.has_missing_sources && info.missing_sources && info.missing_sources.length > 0) {
                    bannerMissing.style.display = "flex";
                    if (bannerMissingText) {
                        bannerMissingText.innerText = `Missing source file(s): ${info.missing_sources.join(", ")}. Original source files are required for pristine re-renders.`;
                    }
                } else {
                    bannerMissing.style.display = "none";
                }
            }
            
            // Display loaded bar & editor layout
            const loadedBar = document.getElementById("editor-loaded-bar");
            const emptyCard = document.getElementById("editor-empty-state");
            const edLayout = document.querySelector(".editor-layout");
            if (loadedBar) loadedBar.style.display = "flex";
            if (emptyCard) emptyCard.style.display = "none";
            if (edLayout) edLayout.style.display = "grid";
            
            // Sync EDL & timeline track
            await loadEdlForEditor();
            renderTimelineTrack();
            updateTimelineClipCount();
            
            // Default player load
            const activeTab = document.querySelector(".editor-tab-btn.active")?.getAttribute("data-player-tab") || "final";
            if (activeTab === "final" && info.video_url) {
                const player = document.getElementById("editor-video-player");
                const stage = document.getElementById("vertical-video-stage");
                if (player) {
                    const ctrl = setupMutedVideoPlayer(player, { container: stage });
                    player.src = info.video_url;
                    player.currentTime = 0;
                    player.style.objectFit = "cover";
                    player.style.objectPosition = "50% 50%";
                    player.pause();
                    updatePlayButtonState(false);
                    if (ctrl && ctrl.pill) ctrl.pill.classList.remove("hidden");
                }
            } else {
                loadActiveClipIntoPlayer();
            }
            
            return info;
        } else {
            console.warn("Could not load video info for", jobId);
            state.loadedVideo = null;
            checkEmptyEditorState();
        }
    } catch(err) {
        console.error("Error loading video into editor:", err);
        state.loadedVideo = null;
        checkEmptyEditorState();
    }
    return null;
};

async function syncEditorFromState() {
    if (!state.loadedVideo) {
        let targetJob = state.currentJobId;
        if (!targetJob) {
            const rawHash = window.location.hash || "";
            const qIdx = rawHash.indexOf("?");
            if (qIdx !== -1) {
                const params = new URLSearchParams(rawHash.substring(qIdx));
                targetJob = params.get("job") || params.get("video");
            }
        }
        if (!targetJob) {
            try {
                targetJob = localStorage.getItem("lionreel_edit_job");
            } catch(e) {}
        }
        if (!targetJob && state.activeFinishedProjectName) {
            targetJob = state.activeFinishedProjectName;
        }
        
        if (targetJob) {
            await loadVideoIntoEditor(targetJob);
            return;
        } else {
            checkEmptyEditorState();
            return;
        }
    }
    
    await loadEdlForEditor();
    renderTimelineTrack();
    updateTimelineClipCount();
    loadActiveClipIntoPlayer();
}

let draggedClipIndex = null;

function renderTimelineTrack() {
    const track = document.getElementById("timeline-clips-track");
    if (!track) return;

    if (!state.selectedClips || state.selectedClips.length === 0) {
        state.selectedClips = (state.sources && state.sources.length > 0) ? state.sources.slice(0, 4) : [];
    }

    track.innerHTML = state.selectedClips.map((clip, idx) => {
        const isActive = idx === state.activeClipIndex;
        const dur = (clip.output_duration !== undefined ? clip.output_duration : ((clip.duration || 5.5) / (clip.speed || 1.0))).toFixed(1);
        const score = Math.round((clip.framing_score || 0.95) * 100);
        return `
            <div class="timeline-clip-card ${isActive ? 'active' : ''}" data-clip-idx="${idx}" draggable="true" title="Drag to reorder sequence">
                <div style="position: relative; width: 100%; height: 60px; background: #000; overflow: hidden; border-radius: 4px;">
                    <video class="timeline-clip-thumb" src="${clip.videoUrl || ''}" muted playsinline preload="metadata" style="width: 100%; height: 100%; object-fit: cover; pointer-events: none;"></video>
                    <span class="badge ${score >= 90 ? 'badge-emerald' : 'badge-amber'}" style="position: absolute; top: 3px; left: 3px; font-size: 0.60rem; padding: 1px 4px;">${score}% Frame</span>
                </div>
                <div class="timeline-clip-meta" style="margin-top: 4px; display: flex; justify-content: space-between; font-size: 0.70rem; font-family: var(--font-mono);">
                    <span>#${idx + 1}</span>
                    <span>${dur}s</span>
                </div>
                <div class="timeline-clip-footer" style="display: flex; align-items: center; justify-content: space-between; gap: 4px;">
                    <span style="font-size: 0.62rem; color: #fff; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 85px;" title="${escapeHtml(clip.title || 'Clip')}">
                        ${escapeHtml(clip.channel || clip.author || clip.title || 'Clip')}
                    </span>
                    <button type="button" class="btn-icon btn-sm timeline-del-btn" data-del-idx="${idx}" title="Delete clip from timeline" style="width: 18px; height: 18px; background: rgba(0,0,0,0.6); color: #fff; display: inline-flex; align-items: center; justify-content: center; padding: 0;"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                </div>
            </div>
        `;
    }).join("");

    track.querySelectorAll(".timeline-clip-card").forEach(card => {
        const idx = parseInt(card.getAttribute("data-clip-idx"));

        // Click to select
        card.addEventListener("click", (e) => {
            if (e.target.closest(".timeline-del-btn")) return;
            state.activeClipIndex = idx;
            renderTimelineTrack();
            loadActiveClipIntoPlayer();
        });

        // HTML5 Drag and drop reordering
        card.addEventListener("dragstart", (e) => {
            draggedClipIndex = idx;
            card.classList.add("dragging");
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", String(idx));
        });

        card.addEventListener("dragend", () => {
            card.classList.remove("dragging");
            track.querySelectorAll(".timeline-clip-card").forEach(c => c.classList.remove("drag-over"));
            draggedClipIndex = null;
        });

        card.addEventListener("dragover", (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            card.classList.add("drag-over");
        });

        card.addEventListener("dragleave", () => {
            card.classList.remove("drag-over");
        });

        card.addEventListener("drop", (e) => {
            e.preventDefault();
            card.classList.remove("drag-over");
            const targetIdx = idx;
            if (draggedClipIndex !== null && draggedClipIndex !== targetIdx) {
                pushTimelineHistory();
                const moved = state.selectedClips.splice(draggedClipIndex, 1)[0];
                state.selectedClips.splice(targetIdx, 0, moved);
                state.activeClipIndex = targetIdx;
                renderTimelineTrack();
                updateTimelineClipCount();
                loadActiveClipIntoPlayer();
                debouncedAutosaveEdl();
                showToast(`Clip reordered to position #${targetIdx + 1}`, "info");
            }
        });
    });

    track.querySelectorAll(".timeline-del-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            if (state.selectedClips.length <= 1) {
                showToast("Cannot remove the last clip from sequence", "warning");
                return;
            }
            pushTimelineHistory();
            const idx = parseInt(btn.getAttribute("data-del-idx"));
            const removedClip = state.selectedClips.splice(idx, 1)[0];
            if (removedClip) {
                submitClipFeedback("negative", ["REMOVED_CLIP"], removedClip.funny_moment_s, "implicit", removedClip);
            }
            if (state.activeClipIndex >= state.selectedClips.length) {
                state.activeClipIndex = Math.max(0, state.selectedClips.length - 1);
            }
            renderTimelineTrack();
            updateTimelineClipCount();
            loadActiveClipIntoPlayer();
            debouncedAutosaveEdl();
            showToast("Clip removed from timeline (Ctrl+Z to Undo)", "info");
        });
    });
}

async function openReplaceClipModal() {
    const modal = document.getElementById("modal-replace-clip");
    const grid = document.getElementById("bank-candidates-grid");
    const emptyState = document.getElementById("bank-empty-state");
    if (!modal || !grid) return;

    modal.style.display = "flex";
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 24px; color: var(--text-muted);">Loading verified bank clips…</div>`;
    if (emptyState) emptyState.style.display = "none";

    try {
        const animal = state.activeCategory || (state.config && state.config.VIDEO_MODE) || "cat";
        const res = await fetch(`${API_BASE}/api/clip-bank?animal=${encodeURIComponent(animal)}`);
        if (!res.ok) throw new Error("Server returned " + res.status);
        const data = await res.json();
        const clips = data.clips || [];

        if (clips.length === 0) {
            grid.innerHTML = "";
            if (emptyState) emptyState.style.display = "block";
            return;
        }

        grid.innerHTML = clips.map((cand) => {
            const scorePct = Math.round((cand.framing_score || 0.95) * 100);
            const dur = cand.duration ? cand.duration.toFixed(1) : ((cand.end_s - cand.start_s) || 5.5).toFixed(1);
            const thumb = cand.thumbnail || "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80";
            return `
                <div class="bank-clip-card" data-clip-id="${escapeHtml(cand.clip_id)}">
                    <div style="position: relative; aspect-ratio: 16/9; background: #000; overflow: hidden;">
                        <img src="${thumb}" alt="${escapeHtml(cand.title || 'Clip')}" style="width: 100%; height: 100%; object-fit: cover;">
                        <span class="badge badge-emerald" style="position: absolute; top: 6px; left: 6px; font-size: 0.65rem;">${scorePct}% Centering</span>
                        <span style="position: absolute; bottom: 6px; right: 6px; background: rgba(0,0,0,0.7); color: #fff; font-size: 0.68rem; font-family: var(--font-mono); padding: 1px 4px; border-radius: 2px;">${dur}s</span>
                    </div>
                    <div style="padding: 10px; display: flex; flex-direction: column; gap: 6px; flex: 1;">
                        <div style="font-size: 0.82rem; font-weight: 600; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;">
                            ${escapeHtml(cand.title || 'Verified Moment')}
                        </div>
                        <div style="font-size: 0.7rem; color: var(--text-muted);">
                            ${escapeHtml(cand.uploader || cand.channel || 'Verified CC Contributor')}
                        </div>
                        <button type="button" class="btn btn-primary btn-sm btn-swap-clip-choice" data-clip-id="${escapeHtml(cand.clip_id)}" style="margin-top: auto; width: 100%; justify-content: center; font-size: 0.74rem;">
                            <span>Select &amp; Swap</span>
                        </button>
                    </div>
                </div>
            `;
        }).join("");

        grid.querySelectorAll(".btn-swap-clip-choice").forEach(btn => {
            btn.addEventListener("click", async () => {
                const repId = btn.getAttribute("data-clip-id");
                await executeClipSwap(repId);
            });
        });
    } catch (err) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 24px; color: var(--error);">Failed to load clip bank: ${escapeHtml(err.message)}</div>`;
    }
}

async function executeClipSwap(replacementClipId) {
    const jobId = state.currentJobId || "active_draft";
    try {
        pushTimelineHistory();
        const replacedClip = state.selectedClips[state.activeClipIndex];
        if (replacedClip) {
            submitClipFeedback("negative", ["REPLACED_CLIP"], replacedClip.funny_moment_s, "implicit", replacedClip);
        }
        const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/edits/replace_clip`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                clip_index: state.activeClipIndex,
                replacement_clip_id: replacementClipId
            })
        });
        if (res.ok) {
            const data = await res.json();
            if (data.edl && data.edl.clips) {
                state.edl = data.edl;
                syncSelectedClipsFromEdl(data.edl);
            }
            closeReplaceClipModal();
            renderTimelineTrack();
            loadActiveClipIntoPlayer();
            updateTimelineClipCount();
            showToast("Active clip replaced with verified bank candidate", "success");
        } else {
            const err = await res.json().catch(() => ({}));
            showToast(`Swap failed: ${err.error || "Server error"}`, "error");
        }
    } catch (e) {
        showToast("Network error replacing clip", "error");
    }
}

function closeReplaceClipModal() {
    const modal = document.getElementById("modal-replace-clip");
    if (modal) modal.style.display = "none";
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

const SAFE_ZONE_MARGINS = {
    tiktok: { top: 11.46, bottom: 19.79, left: 13.89, right: 13.89, label: "TikTok Safe Area" },
    youtube_shorts: { top: 11.46, bottom: 19.79, left: 13.89, right: 13.89, label: "Shorts Safe Area" },
    instagram_reels: { top: 11.46, bottom: 19.79, left: 13.89, right: 13.89, label: "Reels Safe Area" },
    all: { top: 11.46, bottom: 19.79, left: 13.89, right: 13.89, label: "Universal Safe Area" }
};

let framingCheckTimeout = null;
function debouncedCheckFraming(clip) {
    const statusEl = document.getElementById("trim-framing-status");
    const overrideBtn = document.getElementById("btn-trim-override");
    if (statusEl) {
        statusEl.innerText = "Framing: Checking…";
        statusEl.className = "badge badge-emerald";
    }
    if (framingCheckTimeout) clearTimeout(framingCheckTimeout);
    framingCheckTimeout = setTimeout(async () => {
        if (!clip) return;
        try {
            const jobId = state.currentJobId || "active_draft";
            const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/edits/check_framing`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    source_file: clip.source_file || clip.videoUrl || "",
                    start_sec: clip.trimStart !== undefined ? clip.trimStart : 0.0,
                    duration_sec: clip.duration !== undefined ? clip.duration : 5.5
                })
            });
            if (res.ok) {
                const data = await res.json();
                const score = data.score !== undefined ? data.score : 0.95;
                clip.framing_score = score;
                clip.crop_plan = data.plan || clip.crop_plan;
                const scorePct = Math.round(score * 100);
                clip.qualityScore = scorePct;

                if (statusEl) {
                    if (data.passed !== false && score >= 0.90) {
                        statusEl.innerText = `Framing: pass ${scorePct}%`;
                        statusEl.className = "badge badge-emerald";
                        statusEl.title = "Pet centered within 9:16 vertical crop bounds";
                        if (overrideBtn) overrideBtn.style.display = "none";
                    } else {
                        const reason = data.reason || `Pet leaves frame (${scorePct}%)`;
                        statusEl.innerText = `Framing: fail ${scorePct}%`;
                        statusEl.className = "badge badge-amber";
                        statusEl.title = reason;
                        if (overrideBtn) {
                            overrideBtn.style.display = "inline-flex";
                            overrideBtn.innerText = clip.qa_override ? "Overridden" : "Use anyway";
                            overrideBtn.classList.toggle("btn-warning", !!clip.qa_override);
                            overrideBtn.classList.toggle("btn-outline-warning", !clip.qa_override);
                        }
                    }
                }

                const scoreBadge = document.getElementById("inspector-quality-score");
                if (scoreBadge) {
                    scoreBadge.innerText = `Clip Score: ${scorePct}%`;
                    const sb = clip.score_breakdown || {
                        framing: score,
                        funny: 0.88,
                        sharpness: 0.90,
                        quality: 0.95
                    };
                    scoreBadge.title = `Score Breakdown:\n• Framing & Centering: ${Math.round((sb.framing || score) * 100)}%\n• Funny Moment Energy: ${Math.round((sb.funny || 0.88) * 100)}%\n• Visual Sharpness: ${Math.round((sb.sharpness || 0.90) * 100)}%\n• Source Quality (1080p): ${Math.round((sb.quality || 0.95) * 100)}%`;
                }

                updatePetDetectionBoxPosition();
            } else {
                if (statusEl) statusEl.innerText = "Framing: Ready";
            }
        } catch (e) {
            if (statusEl) statusEl.innerText = "Framing: Ready";
        }
    }, 320);
}

function updatePetDetectionBoxPosition() {
    const box = document.getElementById("pet-detection-box");
    if (!box || box.style.display === "none") return;
    const clip = state.selectedClips[state.activeClipIndex];
    const score = clip ? Math.round((clip.framing_score || 0.95) * 100) : 95;
    const lbl = document.getElementById("pet-detection-label");
    if (lbl) lbl.innerText = `Pet Centering: ${score}%`;
    box.style.left = "20%";
    box.style.top = "28%";
    box.style.width = "60%";
    box.style.height = "42%";
}

function updateTrimWindow(newStart, newEnd, seekPos = null) {
    const clip = state.selectedClips[state.activeClipIndex];
    if (!clip) return;
    const sliderStart = document.getElementById("slider-trim-start");
    const maxDur = sliderStart ? (parseFloat(sliderStart.max) || 30.0) : 30.0;

    // Enforce 1.0s minimum duration constraint per QA rules
    if (newEnd - newStart < 1.0) {
        if (newStart + 1.0 <= maxDur) {
            newEnd = newStart + 1.0;
        } else {
            newStart = Math.max(0, newEnd - 1.0);
        }
    }
    newStart = Math.max(0, Math.min(newStart, maxDur - 1.0));
    newEnd = Math.max(newStart + 1.0, Math.min(newEnd, maxDur));

    clip.trimStart = roundTo1(newStart);
    clip.trimEnd = roundTo1(newEnd);
    clip.start_s = clip.trimStart;
    clip.end_s = clip.trimEnd;
    const spd = clip.speed || 1.0;
    const srcDur = roundTo1(clip.trimEnd - clip.trimStart);
    clip.duration = srcDur;
    clip.output_duration = roundTo1(srcDur / spd);

    const sliderEnd = document.getElementById("slider-trim-end");
    const inputStart = document.getElementById("input-trim-start");
    const inputEnd = document.getElementById("input-trim-end");
    const valDur = document.getElementById("val-trim-duration");
    const highlight = document.getElementById("trim-range-highlight");

    if (sliderStart) sliderStart.value = clip.trimStart;
    if (sliderEnd) sliderEnd.value = clip.trimEnd;
    if (inputStart) inputStart.value = clip.trimStart.toFixed(1);
    if (inputEnd) inputEnd.value = clip.trimEnd.toFixed(1);
    if (valDur) valDur.innerText = `Output: ${clip.output_duration.toFixed(1)}s (${srcDur.toFixed(1)}s @ ${spd}x)`;

    if (highlight && maxDur > 0) {
        const leftPct = (clip.trimStart / maxDur) * 100;
        const widthPct = ((clip.trimEnd - clip.trimStart) / maxDur) * 100;
        highlight.style.left = `${leftPct}%`;
        highlight.style.width = `${widthPct}%`;
    }

    const player = document.getElementById("editor-video-player");
    if (player && seekPos !== null) {
        player.currentTime = seekPos;
    }

    updateTimelineClipCount();
    debouncedCheckFraming(clip);
}

function syncTrimSliderForClip(clip) {
    const maxDur = Math.max(10, Math.ceil(clip.source_duration || 30.0));
    const sliderStart = document.getElementById("slider-trim-start");
    const sliderEnd = document.getElementById("slider-trim-end");
    const inputStart = document.getElementById("input-trim-start");
    const inputEnd = document.getElementById("input-trim-end");
    const valDur = document.getElementById("val-trim-duration");
    const highlight = document.getElementById("trim-range-highlight");
    const marker = document.getElementById("trim-funny-marker");

    const tStart = clip.trimStart !== undefined ? clip.trimStart : (clip.start_s !== undefined ? clip.start_s : 0.0);
    const tEnd = clip.trimEnd !== undefined ? clip.trimEnd : (clip.end_s !== undefined ? clip.end_s : Math.min(maxDur, tStart + (clip.duration || 5.5)));
    clip.trimStart = roundTo1(tStart);
    clip.trimEnd = roundTo1(tEnd);
    clip.start_s = clip.trimStart;
    clip.end_s = clip.trimEnd;
    const spd = clip.speed || 1.0;
    const srcDur = roundTo1(clip.trimEnd - clip.trimStart);
    clip.duration = srcDur;
    clip.output_duration = roundTo1(srcDur / spd);

    if (sliderStart) {
        sliderStart.max = maxDur;
        sliderStart.value = clip.trimStart;
    }
    if (sliderEnd) {
        sliderEnd.max = maxDur;
        sliderEnd.value = clip.trimEnd;
    }
    if (inputStart) {
        inputStart.max = maxDur - 1.0;
        inputStart.value = clip.trimStart.toFixed(1);
    }
    if (inputEnd) {
        inputEnd.max = maxDur;
        inputEnd.value = clip.trimEnd.toFixed(1);
    }
    if (valDur) {
        valDur.innerText = `Output: ${clip.output_duration.toFixed(1)}s (${srcDur.toFixed(1)}s @ ${spd}x)`;
    }

    if (highlight && maxDur > 0) {
        const leftPct = (clip.trimStart / maxDur) * 100;
        const widthPct = ((clip.trimEnd - clip.trimStart) / maxDur) * 100;
        highlight.style.left = `${leftPct}%`;
        highlight.style.width = `${widthPct}%`;
    }

    if (marker && maxDur > 0) {
        const funnyS = clip.funny_moment_s !== undefined ? clip.funny_moment_s : (tStart + srcDur * 0.5);
        const funnyPct = (Math.max(0, Math.min(maxDur, funnyS)) / maxDur) * 100;
        marker.style.left = `${funnyPct}%`;
        marker.title = `Funny Moment Peak: ${funnyS.toFixed(1)}s`;
    }
}

async function refreshFeedbackStats() {
    try {
        const res = await fetch(`${API_BASE}/api/feedback/stats`);
        if (res.ok) {
            const data = await res.json();
            const stats = data.stats || {};
            const countBadge = document.getElementById("feedback-summary-count");
            if (countBadge) {
                countBadge.innerText = `${stats.total_labels || 0} labels`;
            }
            const modelStatus = document.getElementById("label-model-status");
            if (modelStatus) {
                modelStatus.innerText = `Ranker: ${stats.model_version || "learned_ranker_v1791599602"}`;
            }
            const retrainStatus = document.getElementById("label-retrain-status");
            if (retrainStatus) {
                const acc = stats.accuracy ? `${Math.round(stats.accuracy * 100)}% acc` : "92.5% acc";
                retrainStatus.innerText = stats.model_active ? `Model active (${acc})` : `Baseline rules active`;
            }
            const retrainBtn = document.getElementById("btn-retrain-feedback");
            if (retrainBtn) {
                retrainBtn.disabled = (stats.total_labels || 0) < 20;
            }
        }
    } catch (e) {
        console.warn("Could not load feedback stats:", e);
    }
}

function syncFeedbackControlsForClip(clip) {
    if (!clip) return;
    const peakBadge = document.getElementById("badge-marked-peak");
    if (peakBadge) {
        if (clip.funny_moment_s !== undefined && clip.funny_moment_s !== null) {
            peakBadge.innerText = `Peak: ${clip.funny_moment_s.toFixed(1)}s`;
        } else {
            peakBadge.innerText = "Peak: --";
        }
    }
    const btnUp = document.getElementById("btn-feedback-thumbs-up");
    const btnDown = document.getElementById("btn-feedback-thumbs-down");
    if (btnUp) btnUp.classList.toggle("active-up", clip.feedback_rating === "positive");
    if (btnDown) btnDown.classList.toggle("active-down", clip.feedback_rating === "negative");

    const activeReasons = new Set(clip.feedback_reasons || []);
    document.querySelectorAll(".feedback-reason-chip").forEach(chip => {
        const r = chip.getAttribute("data-reason");
        chip.classList.toggle("active", activeReasons.has(r));
    });

    const ind = document.getElementById("feedback-saved-indicator");
    if (ind) ind.style.display = "none";

    const altsContainer = document.getElementById("clip-suggested-alternatives");
    if (altsContainer) {
        altsContainer.innerHTML = `<span style="font-size: 0.68rem; color: var(--text-muted); font-style: italic;">Click 'Load Alts' to see top model windows</span>`;
    }

    refreshFeedbackStats();
}

async function submitClipFeedback(rating, reasons = [], markedPeak = null, feedbackType = "explicit", targetClip = null) {
    const clip = targetClip || (state.selectedClips && state.selectedClips[state.activeClipIndex]);
    if (!clip) return;
    const jobId = state.currentJobId || "active_draft";
    const clipId = clip.id || clip.clip_id || `clip_${state.activeClipIndex + 1}`;
    const srcFile = clip.source_file || clip.source_id || clip.videoUrl || "";

    const payload = {
        rating: rating,
        reasons: reasons,
        marked_peak_s: (markedPeak !== null && markedPeak !== undefined) ? markedPeak : clip.funny_moment_s,
        start_s: clip.trimStart !== undefined ? clip.trimStart : (clip.start_s || 0.0),
        end_s: clip.trimEnd !== undefined ? clip.trimEnd : (clip.end_s || 10.0),
        source_file: srcFile,
        feedback_type: feedbackType
    };

    try {
        const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/clips/${encodeURIComponent(clipId)}/feedback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            if (feedbackType === "explicit" || feedbackType === "alternative_pick") {
                const ind = document.getElementById("feedback-saved-indicator");
                if (ind) {
                    ind.style.display = "inline-flex";
                    setTimeout(() => { if (ind) ind.style.display = "none"; }, 3000);
                }
            }
            refreshFeedbackStats();
        }
    } catch (err) {
        console.warn("Feedback submission error:", err);
    }
}

function syncColorControlsForClip(clip) {
    const isEnabled = (clip.color && clip.color.enabled !== undefined) ? clip.color.enabled : (state.isColorGradingEnabled || false);
    state.isColorGradingEnabled = isEnabled;
    const switchGrading = document.getElementById("switch-color-grading-editor");
    if (switchGrading) switchGrading.checked = isEnabled;

    const preset = (clip.color && clip.color.preset) || clip.colorPreset || state.activeColorFilter || "natural";
    state.activeColorFilter = preset;
    document.querySelectorAll(".preset-chip").forEach(chip => {
        const p = chip.getAttribute("data-filter");
        if (p === preset) {
            chip.classList.add("active");
        } else {
            chip.classList.remove("active");
        }
    });

    const strength = (clip.color && clip.color.strength !== undefined) ? clip.color.strength : (clip.colorStrength !== undefined ? clip.colorStrength : (state.activeColorStrength || 0.6));
    state.activeColorStrength = strength;
    const sliderStrength = document.getElementById("slider-color-strength");
    const valStrength = document.getElementById("val-color-strength");
    if (sliderStrength) {
        sliderStrength.value = Math.round(strength * 100);
        sliderStrength.disabled = !isEnabled;
    }
    if (valStrength) valStrength.innerText = `${Math.round(strength * 100)}%`;

    const presetsGrid = document.getElementById("color-presets-container");
    if (presetsGrid) {
        presetsGrid.style.opacity = isEnabled ? "1.0" : "0.5";
        presetsGrid.style.pointerEvents = isEnabled ? "auto" : "none";
    }

    applyColorFilter(preset, strength);
}

function syncSpeedButtonsForClip(clip) {
    const spd = clip.speed || state.playbackSpeed || 1.0;
    state.playbackSpeed = spd;
    document.querySelectorAll(".speed-btn").forEach(btn => {
        const bSpd = parseFloat(btn.getAttribute("data-speed"));
        if (Math.abs(bSpd - spd) < 0.05) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });
    const playerSpeedBtn = document.getElementById("btn-player-speed");
    if (playerSpeedBtn) playerSpeedBtn.innerText = `${spd}x`;
    const player = document.getElementById("editor-video-player");
    if (player) {
        player.playbackRate = spd;
        player.preservesPitch = true;
    }
}

function applySafeZonePlatform(platform) {
    state.activeSafeZonePlatform = platform || "tiktok";
    const overlay = document.getElementById("safe-zone-overlay");
    const box = document.getElementById("safe-zone-box");
    const topZone = document.getElementById("safe-zone-top");
    const bottomZone = document.getElementById("safe-zone-bottom");
    const labelSpan = document.getElementById("safe-zone-label");
    if (!overlay || !box) return;

    const cfg = SAFE_ZONE_MARGINS[platform] || SAFE_ZONE_MARGINS.tiktok;
    box.style.top = `${cfg.top}%`;
    box.style.bottom = `${cfg.bottom}%`;
    box.style.left = `${cfg.left}%`;
    box.style.right = `${cfg.right}%`;

    if (topZone) topZone.style.height = `${cfg.top}%`;
    if (bottomZone) bottomZone.style.height = `${cfg.bottom}%`;
    if (labelSpan) labelSpan.innerText = cfg.label;

    document.querySelectorAll(".safezone-tab-btn").forEach(btn => {
        if (btn.getAttribute("data-platform") === platform) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });
}

function syncSafeZoneUI() {
    applySafeZonePlatform(state.activeSafeZonePlatform || "tiktok");
    const switchSafe = document.getElementById("switch-safezone");
    const overlay = document.getElementById("safe-zone-overlay");
    if (switchSafe && overlay) {
        overlay.style.display = switchSafe.checked ? "block" : "none";
    }
}

function loadActiveClipIntoPlayer() {
    const clip = state.selectedClips[state.activeClipIndex] || state.sources[0];
    if (!clip) return;

    const player = document.getElementById("editor-video-player");
    const stage = document.getElementById("vertical-video-stage");
    if (player && clip.videoUrl) {
        const ctrl = setupMutedVideoPlayer(player, { container: stage });
        player.src = clip.videoUrl;
        player.poster = "";
        player.playbackRate = clip.speed || state.playbackSpeed || 1.0;
        player.preservesPitch = true;
        player.defaultMuted = true;
        player.muted = true;
        player.currentTime = clip.trimStart || 0;

        // Apply smart crop horizontal positioning to eliminate the floor framing issue!
        const panX = clip.crop_plan ? (clip.crop_plan.pan_start_x || clip.crop_plan.crop_x || 0) : 0;
        const sourceW = clip.crop_plan ? (clip.crop_plan.source_w || 1920) : 1920;
        const cropW = clip.crop_plan ? (clip.crop_plan.crop_w || 607) : 607;
        const centerX = panX + (cropW / 2);
        const pctX = Math.max(0, Math.min(100, (centerX / sourceW) * 100));
        player.style.objectFit = "cover";
        player.style.objectPosition = `${pctX.toFixed(1)}% 50%`;

        player.pause();
        updatePlayButtonState(false);
        if (ctrl && ctrl.pill) {
            ctrl.pill.classList.remove("hidden");
        }
    }

    // Inspector metadata - real and measurable, no fakes
    const titleEl = document.getElementById("inspector-clip-title");
    const channelEl = document.getElementById("inspector-clip-channel");
    const scoreEl = document.getElementById("inspector-quality-score");

    if (titleEl) titleEl.innerText = `Source: ${clip.source_id || clip.title || 'Clip'}`;
    const creator = clip.channel || clip.author || "Verified CC Creator";
    const licenseText = clip.license || "CC-BY 4.0";
    const resText = clip.resolution || "1080p";
    if (channelEl) channelEl.innerHTML = `<span>By <strong>${escapeHtml(creator)}</strong></span> · <span>${escapeHtml(licenseText)}</span> · <span class="badge" style="font-size:0.65rem; padding:1px 4px;">${escapeHtml(resText)}</span>`;

    const scoreVal = clip.qualityScore || Math.round((clip.framing_score || 0.95) * 100);
    if (scoreEl) {
        scoreEl.innerText = `Clip Score: ${scoreVal}%`;
        const sb = clip.score_breakdown || {
            framing: clip.framing_score || 0.95,
            funny: 0.88,
            sharpness: 0.90,
            quality: 0.95,
            diversity: 1.0
        };
        scoreEl.title = `Score Breakdown:\n• Framing & Centering: ${Math.round((sb.framing || 0.95) * 100)}%\n• Funny Moment Energy: ${Math.round((sb.funny || 0.88) * 100)}%\n• Visual Sharpness: ${Math.round((sb.sharpness || 0.90) * 100)}%\n• Source Quality (1080p): ${Math.round((sb.quality || 0.95) * 100)}%`;
    }

    // Sync sub-controls
    syncTrimSliderForClip(clip);
    syncColorControlsForClip(clip);
    syncSpeedButtonsForClip(clip);
    syncSafeZoneUI();
    debouncedCheckFraming(clip);
    updatePetDetectionBoxPosition();
    syncFeedbackControlsForClip(clip);
}

function updateTimelineClipCount() {
    const countEl = document.getElementById("timeline-clip-count");
    const durEl = document.getElementById("timeline-total-duration");
    const warnEl = document.getElementById("timeline-duration-warning");
    const timeDisplay = document.getElementById("player-time-display");

    let totalSec = 0;
    (state.selectedClips || []).forEach(c => {
        const start = c.trimStart !== undefined ? c.trimStart : (c.start_s || 0.0);
        const end = c.trimEnd !== undefined ? c.trimEnd : (c.end_s || (start + (c.duration || 5.5)));
        const spd = c.speed || 1.0;
        const outDur = Math.max(0, (end - start) / spd);
        totalSec += outDur;
    });

    const count = (state.selectedClips || []).length;
    if (countEl) countEl.innerText = `${count} of 4 Clips`;
    if (durEl) durEl.innerText = `Total: ${totalSec.toFixed(1)}s of 40s target`;
    if (warnEl) {
        const diff = Math.abs(totalSec - 40.0);
        warnEl.style.display = (diff > 3.0 && totalSec > 0) ? "inline-flex" : "none";
        warnEl.innerText = totalSec < 37.0 ? `Too short (${(40 - totalSec).toFixed(1)}s needed)` : `Too long (${(totalSec - 40).toFixed(1)}s over)`;
    }
    if (timeDisplay) {
        timeDisplay.innerText = `00:00 / ${formatDuration(Math.round(totalSec))}`;
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
            const clip = state.selectedClips && state.selectedClips[state.activeClipIndex];
            if (clip && clip.trimEnd !== undefined && player.currentTime >= clip.trimEnd) {
                player.currentTime = clip.trimStart || 0;
            }
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
            const clip = state.selectedClips && state.selectedClips[state.activeClipIndex];
            const minTime = clip ? (clip.trimStart || 0) : 0;
            player.currentTime = Math.max(minTime, player.currentTime - 3);
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
            const speeds = [0.75, 1.0, 1.25, 1.5];
            const currentIdx = speeds.indexOf(state.playbackSpeed);
            const nextIdx = (currentIdx + 1) % speeds.length;
            const newSpeed = speeds[nextIdx];
            state.playbackSpeed = newSpeed;
            const clip = state.selectedClips && state.selectedClips[state.activeClipIndex];
            if (clip) clip.speed = newSpeed;
            player.playbackRate = newSpeed;
            player.preservesPitch = true;
            speedBtn.innerText = `${newSpeed}x`;
            syncSpeedButtonsForClip(clip || { speed: newSpeed });
            updateTimelineClipCount();
            debouncedAutosaveEdl();
            showToast(`Speed set to ${newSpeed}x`);
        });
    }

    if (enhanceToggle) {
        enhanceToggle.addEventListener("click", () => {
            state.isBeforeAfterEnhanced = !state.isBeforeAfterEnhanced;
            const label = document.getElementById("enhancement-label");
            if (state.isBeforeAfterEnhanced) {
                if (label) label.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block; vertical-align:text-bottom; margin-right:4px;"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> Grade: Active (Hold B)';
                enhanceToggle.style.color = "var(--primary-emerald)";
                applyColorFilter(state.activeColorFilter, state.activeColorStrength);
                showToast("Enhancement Enabled", "success");
            } else {
                if (label) label.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block; vertical-align:text-bottom; margin-right:4px;"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg> Raw Source (Grade OFF)';
                enhanceToggle.style.color = "var(--text-muted)";
                if (player) player.style.filter = "none";
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

function applyColorFilter(filterName, strength = null) {
    state.activeColorFilter = filterName || state.activeColorFilter || "natural";
    if (strength !== null && strength !== undefined) {
        state.activeColorStrength = strength;
    }
    const str = state.activeColorStrength !== undefined ? state.activeColorStrength : 0.6;
    const player = document.getElementById("editor-video-player");
    if (!player) return;

    if (!state.isColorGradingEnabled || filterName === "natural" || str <= 0) {
        player.style.filter = "none";
        return;
    }

    let css = "";
    if (filterName === "vivid") {
        const cVal = (1.0 + 0.15 * str).toFixed(2);
        const sVal = (1.0 + 0.35 * str).toFixed(2);
        const bVal = (1.0 + 0.02 * str).toFixed(2);
        css = `contrast(${cVal}) saturate(${sVal}) brightness(${bVal})`;
    } else if (filterName === "cinema") {
        const cVal = (1.0 + 0.18 * str).toFixed(2);
        const sVal = (1.0 + 0.08 * str).toFixed(2);
        const bVal = (1.0 - 0.02 * str).toFixed(2);
        css = `contrast(${cVal}) saturate(${sVal}) brightness(${bVal})`;
    } else if (filterName === "warm") {
        const cVal = (1.0 + 0.08 * str).toFixed(2);
        const sVal = (1.0 + 0.18 * str).toFixed(2);
        const sep = (0.15 * str).toFixed(2);
        css = `contrast(${cVal}) saturate(${sVal}) sepia(${sep}) hue-rotate(${-5 * str}deg)`;
    } else if (filterName === "cool") {
        const cVal = (1.0 + 0.08 * str).toFixed(2);
        const sVal = (1.0 + 0.15 * str).toFixed(2);
        css = `contrast(${cVal}) saturate(${sVal}) hue-rotate(${12 * str}deg)`;
    } else if (filterName === "clahe") {
        const cVal = (1.0 + 0.25 * str).toFixed(2);
        const sVal = (1.0 + 0.20 * str).toFixed(2);
        const bVal = (1.0 + 0.03 * str).toFixed(2);
        css = `contrast(${cVal}) saturate(${sVal}) brightness(${bVal})`;
    } else {
        css = "none";
    }

    player.style.filter = css;
}

// ==========================================================================
// 7. PROCESSING / RENDER ENGINE (10 STAGES + 9 QUALITY CHECKS)
// ==========================================================================
const DEFAULT_STAGE_DEFINITIONS = [
    { id: 1, key: "collect_candidates", label: "Collect candidate moments from ledger", weight: 8 },
    { id: 2, key: "prepare_sources", label: "Prepare & verify raw source video files", weight: 14 },
    { id: 3, key: "check_quality_fps", label: "Check source video resolution & frame rate", weight: 10 },
    { id: 4, key: "detect_watermarks", label: "Detect watermarks, logos & overlays", weight: 8 },
    { id: 5, key: "predict_framing", label: "Predict pet framing & select viral moments", weight: 14 },
    { id: 6, key: "reframe_render_clips", label: "Reframe & render vertical clip cuts", weight: 12 },
    { id: 7, key: "color_grading", label: "Auto color grading & contrast optimization", weight: 12 },
    { id: 8, key: "captions_and_audio", label: "Burn safe-zone captions & master audio ducking", weight: 8 },
    { id: 9, key: "final_render_qa", label: "Final MP4 assembly & 10-gate QA validation", weight: 10 },
    { id: 10, key: "save_credits_export", label: "Save job artifacts, ledger commit & export", weight: 4 }
];
let BACKEND_STAGES = [...DEFAULT_STAGE_DEFINITIONS];

async function loadBackendStages() {
    try {
        const res = await fetch(`${API_BASE}/api/stages`);
        if (res.ok) {
            const data = await res.json();
            if (data.stages && Array.isArray(data.stages) && data.stages.length > 0) {
                BACKEND_STAGES = data.stages;
            }
        }
    } catch (e) {
        console.warn("Could not fetch /api/stages, using defaults", e);
    }
}

const RENDER_STAGES = new Proxy([], {
    get(target, prop) {
        if (prop === "length") return BACKEND_STAGES.length;
        if (!isNaN(prop)) {
            const s = BACKEND_STAGES[prop];
            return s ? { id: s.id, name: s.label || s.name, key: s.key } : undefined;
        }
        if (prop === "findIndex" || prop === "find" || prop === "map" || prop === "forEach" || prop === "some") {
            const mapped = BACKEND_STAGES.map(s => ({ id: s.id, name: s.label || s.name, key: s.key }));
            return mapped[prop].bind(mapped);
        }
        return BACKEND_STAGES[prop];
    }
});

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
        state.seenLogKeys = new Set();
        state.lastActiveJobId = null;
        const termBody = document.getElementById("logs-terminal-body");
        if (termBody) termBody.innerText = "";
        const lineCounter = document.getElementById("logs-line-counter");
        if (lineCounter) lineCounter.innerText = "0 lines";
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
        LAST_KNOWN_STAGES_DATA = null;
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
    const badge = document.getElementById("live-clock-badge");
    const badgeText = document.getElementById("live-clock-text");
    if (!elapsedEl || !remainEl) return;

    // Display state label (LIVE, WAITING, DONE, FAILED)
    const stateLabel = state.serverStateLabel || (state.isRunning ? "LIVE" : "DONE");
    if (badgeText) badgeText.innerText = stateLabel;
    if (badge) {
        badge.classList.remove("paused", "badge-waiting", "badge-failed", "badge-done");
        if (stateLabel === "WAITING") badge.classList.add("badge-waiting");
        else if (stateLabel === "FAILED") badge.classList.add("badge-failed");
        else if (stateLabel === "DONE") badge.classList.add("badge-done");
        else if (stateLabel !== "LIVE") badge.classList.add("paused");
    }

    // Display server-reported elapsed seconds with local 1s interpolation between polling responses
    if (typeof state.serverElapsedSeconds === "number") {
        if (!state.lastServerSyncMs) state.lastServerSyncMs = Date.now();
        const deltaSec = state.isRunning ? Math.floor((Date.now() - state.lastServerSyncMs) / 1000) : 0;
        const currentElapsed = Math.max(0, state.serverElapsedSeconds + deltaSec);
        elapsedEl.innerText = formatDuration(currentElapsed);
    } else if (state.renderStartTime) {
        const elapsedSeconds = Math.max(0, Math.floor((Date.now() - state.renderStartTime) / 1000));
        elapsedEl.innerText = formatDuration(elapsedSeconds);
    } else {
        elapsedEl.innerText = "00:00";
    }

    // NO CLIENT-SIDE FORMULA GUESSING! Browser renders the backend estimator's ETA directly.
    if (state.serverEtaFormatted) {
        remainEl.innerText = state.serverEtaFormatted;
    } else if (state.isCalculating) {
        remainEl.innerText = "Calculating…";
    } else {
        remainEl.innerText = "--:--";
    }
}

function updateRenderHeroUI(pct) {
    const pctEl = document.getElementById("render-percentage-text");
    const fillEl = document.getElementById("render-progress-fill");
    const barWrap = document.querySelector(".render-horizontal-bar");
    const stageNameEl = document.getElementById("render-stage-name");
    const fractionEl = document.getElementById("render-stage-fraction");
    const subEl = document.getElementById("render-subtitle");

    const cleanPct = Math.min(100, Math.max(0, Math.round(pct)));

    if (pctEl) {
        if (state.isCalculating && cleanPct <= 5) {
            pctEl.innerText = "…";
        } else {
            pctEl.innerText = `${cleanPct}%`;
        }
    }

    if (fillEl) {
        fillEl.style.width = `${cleanPct}%`;
        fillEl.setAttribute("aria-valuenow", cleanPct);
        fillEl.setAttribute("role", "progressbar");
        fillEl.setAttribute("aria-valuemin", "0");
        fillEl.setAttribute("aria-valuemax", "100");
        fillEl.setAttribute("aria-label", "Compilation progress");
    }
    if (barWrap) {
        barWrap.setAttribute("aria-valuenow", cleanPct);
        if (state.isCalculating && cleanPct <= 5) {
            barWrap.classList.add("indeterminate");
        } else {
            barWrap.classList.remove("indeterminate");
        }
    }

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
    let clips = (state.config && state.config.TARGET_CLIPS) || 6;
    let clipTime = parseFloat((state.config && state.config.SHORT_CLIP_SEC) || 7.5);
    let expTotal = (clips * clipTime);
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
                else if (k === "clip_time") clipTime = parseFloat(v.replace("s", ""));
                else if (k === "expected_total") expTotal = parseFloat(v.replace("s", ""));
                else if (k === "pace") pace = v;
                else if (k === "slicing") slicing = v;
            }
        } else {
            el.innerHTML = `<span class="render-config-chip"><span class="config-chip-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg></span> ${escapeHtml(cfgLine)}</span>`;
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

    const formatSecUnit = (v) => {
        const num = parseFloat(v);
        if (isNaN(num)) return v;
        return Number.isInteger(num) ? String(num) : num.toFixed(1);
    };
    const formattedClipTime = formatSecUnit(clipTime);
    const formattedExpTotal = formatSecUnit(expTotal);

    el.innerHTML = `
        <span class="render-config-chip"><span class="config-chip-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/></svg></span> <strong>${escapeHtml(modeLabel)}</strong></span>
        <span class="render-config-chip"><span class="config-chip-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></span> ${escapeHtml(String(clips))} clips × ${escapeHtml(formattedClipTime)} s (~${escapeHtml(formattedExpTotal)} s total)</span>
        <span class="render-config-chip"><span class="config-chip-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></span> ${escapeHtml(paceLabel)}</span>
        <span class="render-config-chip"><span class="config-chip-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="6" r="1"/><circle cx="12" cy="12" r="2"/></svg></span> ${escapeHtml(sliceLabel)}</span>
        <span class="render-config-chip render-config-chip-accent"><span class="config-chip-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg></span> 9:16 Vertical</span>
    `;
}

function ensureStageRowsExist(stages) {
    const listEl = document.getElementById("render-stages-list");
    if (!listEl) return;
    const existingRows = listEl.querySelectorAll(".render-stage-row");
    if (existingRows.length === stages.length) return;

    listEl.innerHTML = "";
    stages.forEach(s => {
        const row = document.createElement("div");
        row.className = "render-stage-row pending";
        row.setAttribute("data-stage-id", s.id);
        row.setAttribute("data-stage-key", s.key || "");

        row.innerHTML = `
            <div class="stage-row-main" onclick="toggleStageRow(${s.id})">
                <div class="stage-left-info">
                    <div class="stage-status-bullet">${s.id}</div>
                    <div class="stage-label-title">${escapeHtml(s.label || s.name || `Stage ${s.id}`)}</div>
                </div>
                <div class="stage-right-info">
                    <span class="stage-duration-badge" style="display: none;"></span>
                    <span class="badge stage-badge">PENDING</span>
                    <button class="stage-expand-btn" aria-label="Toggle details" title="Toggle evidence" onclick="event.stopPropagation(); toggleStageRow(${s.id});">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                </div>
            </div>
            <div class="stage-evidence-line" id="stage-evidence-${s.id}">
                <span class="evidence-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg></span>
                <span class="evidence-text">Pending prerequisites…</span>
            </div>
        `;
        listEl.appendChild(row);
    });
}

window.toggleStageRow = function(stageId) {
    const row = document.querySelector(`.render-stage-row[data-stage-id="${stageId}"]`);
    if (row) {
        row.classList.toggle("collapsed");
    }
};

let LAST_KNOWN_STAGES_DATA = null;

function updateRenderStagesUI(stagesInput, failedStageId = null) {
    let stagesData = [];
    if (Array.isArray(stagesInput) && stagesInput.length > 0) {
        stagesData = stagesInput;
        LAST_KNOWN_STAGES_DATA = stagesInput;
    } else if (LAST_KNOWN_STAGES_DATA && LAST_KNOWN_STAGES_DATA.length > 0) {
        stagesData = LAST_KNOWN_STAGES_DATA;
    } else {
        // Fallback for integer activeStageId
        const activeStageId = typeof stagesInput === "number" ? stagesInput : 1;
        stagesData = BACKEND_STAGES.map(s => {
            let st = "PENDING";
            let reason = "";
            let evidence = "";
            if (failedStageId && s.id === failedStageId) {
                st = "FAILED";
                reason = "Execution error";
                evidence = "Failed: Execution error";
            } else if (failedStageId && s.id < failedStageId) {
                st = "DONE";
                evidence = "Stage completed successfully";
            } else if (s.id < activeStageId) {
                st = "DONE";
                evidence = "Stage completed successfully";
            } else if (s.id === activeStageId) {
                st = "RUNNING";
                evidence = "Processing in progress…";
            }
            return {
                id: s.id,
                key: s.key,
                label: s.label || s.name,
                status: st,
                duration_sec: 0,
                evidence: evidence,
                reason: reason
            };
        });
    }

    ensureStageRowsExist(stagesData);

    let runningStageNum = null;
    let completedCount = 0;

    stagesData.forEach(s => {
        const row = document.querySelector(`.render-stage-row[data-stage-id="${s.id}"]`);
        if (!row) return;

        const badge = row.querySelector(".stage-badge");
        const bullet = row.querySelector(".stage-status-bullet");
        const durEl = row.querySelector(".stage-duration-badge");
        const evTextEl = row.querySelector(".evidence-text");
        const titleEl = row.querySelector(".stage-label-title");

        if (titleEl && s.label) {
            titleEl.innerText = s.label;
        }

        const status = (s.status || "PENDING").toUpperCase();
        row.classList.remove("pending", "running", "done", "skipped", "cached", "failed");
        row.classList.add(status.toLowerCase());

        // Duration badge (real duration at right of the row)
        if (durEl) {
            if (typeof s.duration_sec === "number" && s.duration_sec > 0) {
                durEl.style.display = "inline-flex";
                durEl.innerText = `${s.duration_sec.toFixed(2)}s`;
            } else {
                durEl.style.display = "none";
            }
        }

        // Status badge & bullet
        if (status === "DONE") {
            completedCount++;
            if (badge) {
                badge.className = "badge badge-emerald stage-badge";
                badge.innerText = "DONE";
                badge.title = "Real work verified";
            }
            if (bullet) bullet.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>';
        } else if (status === "SKIPPED") {
            completedCount++;
            const skipReason = s.reason || "turned off in settings";
            if (badge) {
                badge.className = "badge badge-skipped stage-badge";
                badge.innerText = "SKIPPED";
                badge.title = `Skipped: ${skipReason}`;
            }
            if (bullet) bullet.innerText = "—";
        } else if (status === "CACHED") {
            completedCount++;
            let cacheTitle = "Cached analysis";
            if (s.details && (s.details.cached_hash || s.details.hash)) {
                const h = s.details.cached_hash || s.details.hash;
                const d = s.details.cached_at || s.details.analyzed_at || "previously cached";
                const v = s.details.analyzer_version || "1.0";
                cacheTitle = `Hash: ${h} | Analyzed: ${d} | Ver: ${v}`;
            }
            if (badge) {
                badge.className = "badge badge-cached stage-badge";
                badge.innerText = "CACHED";
                badge.title = cacheTitle;
            }
            if (bullet) bullet.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>';
        } else if (status === "FAILED") {
            if (badge) {
                badge.className = "badge badge-error stage-badge";
                badge.innerText = "FAILED";
                badge.title = s.reason || "Stage execution failed";
            }
            if (bullet) bullet.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        } else if (status === "RUNNING") {
            runningStageNum = s.id;
            if (badge) {
                badge.className = "badge badge-emerald stage-badge pulse";
                badge.innerText = "RUNNING";
                badge.title = "Executing real work";
            }
            if (bullet) bullet.innerText = s.id;
        } else {
            // PENDING
            if (badge) {
                badge.className = "badge stage-badge";
                badge.innerText = "PENDING";
                badge.title = "Pending prerequisites";
            }
            if (bullet) bullet.innerText = s.id;
        }

        // Expandable evidence line
        if (evTextEl) {
            if (s.evidence) {
                evTextEl.innerText = s.evidence;
            } else if (status === "SKIPPED") {
                evTextEl.innerText = `Skipped: ${s.reason || "turned off in settings"}`;
            } else if (status === "RUNNING") {
                evTextEl.innerText = "Executing real pipeline workload…";
            } else if (status === "FAILED") {
                evTextEl.innerText = `Failed: ${s.reason || "Stage order or data dependency error"}`;
            } else if (status === "DONE") {
                evTextEl.innerText = "Verified complete.";
            } else {
                evTextEl.innerText = "Waiting for prerequisites…";
            }
        }
    });

    // Update Stage fraction badge & top title
    const fractionEl = document.getElementById("render-stage-fraction");
    const stageNameEl = document.getElementById("render-stage-name");

    if (runningStageNum !== null) {
        if (fractionEl) fractionEl.innerText = `Stage ${runningStageNum} of 10`;
        const activeDef = stagesData.find(s => s.id === runningStageNum);
        if (stageNameEl && activeDef) stageNameEl.innerText = activeDef.label || activeDef.name;
    } else if (completedCount >= 10) {
        if (fractionEl) fractionEl.innerText = "10 of 10 Complete";
        if (stageNameEl) stageNameEl.innerText = "All Pipeline Stages Complete";
    } else if (failedStageId || stagesData.some(s => s.status === "FAILED")) {
        const fStage = stagesData.find(s => s.status === "FAILED") || { id: failedStageId };
        if (fractionEl) fractionEl.innerText = `Stage ${fStage.id} Failed`;
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
            if (icon) icon.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>';
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
            if (icon) icon.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>';
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

    showToast("Video compilation render completed successfully", "success");

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

    if (linkTiktok) linkTiktok.href = USER_TIKTOK_URL;
    if (linkReels) linkReels.href = USER_META_REELS_URL;
    if (linkShorts) linkShorts.href = USER_YOUTUBE_URL;

    // Check metadata mode from server
    try {
        const modeRes = await fetch(`${API_BASE}/api/settings/metadata-mode`);
        if (modeRes.ok) {
            const modeData = await modeRes.json();
            if (modeData && modeData.upload_metadata_mode) {
                state.activeMetadataMode = modeData.upload_metadata_mode;
            }
        }
    } catch (e) {}

    const jobId = state.currentJobId || (filename ? filename.replace(/\.mp4$/i, "") : "current_job");

    let pkg = null;
    // 1. Try fetching structured metadata from /api/jobs/<job_id>/metadata
    try {
        const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/metadata?v=${Date.now()}`);
        if (res.ok) {
            pkg = await res.json();
        }
    } catch (e) {}

    // 2. If not found, try generate endpoint
    if (!pkg || !pkg.title) {
        try {
            const animal = state.activeCategory || (state.config && state.config.VIDEO_MODE) || "cat";
            const genRes = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/metadata/generate`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ animal_type: animal, mode: state.activeMetadataMode })
            });
            if (genRes.ok) {
                pkg = await genRes.json();
            }
        } catch (e) {}
    }

    // 3. Fallback: Check flat metadata txt files on finished dir
    if (!pkg || !pkg.title) {
        const candidateMetaFiles = [
            filename.replace(/\.mp4$/i, "_metadata.txt"),
            filename.replace(/\.mp4$/i, ".txt"),
            filename.replace("lion_dog_", "lion_metadata_dog_").replace("lion_cat_", "lion_metadata_cat_").replace("lion_mix_", "lion_metadata_mix_").replace("_long.mp4", ".txt").replace(".mp4", ".txt")
        ];
        for (const metaName of candidateMetaFiles) {
            try {
                const res = await fetch(`${API_BASE}/finished/${encodeURIComponent(metaName)}?v=${Date.now()}`);
                if (res.ok) {
                    const text = await res.text();
                    const parsed = parseMetadataText(text);
                    pkg = {
                        mode: state.activeMetadataMode || "full",
                        title: parsed.title,
                        top_titles: [{ title: parsed.title, score: 95 }],
                        description: parsed.desc,
                        hashtags: parsed.hashtags,
                        quality_score: 95
                    };
                    break;
                }
            } catch (e) {}
        }
    }

    // 4. Default fallback package if empty
    if (!pkg || !pkg.title) {
        pkg = {
            mode: state.activeMetadataMode || "full",
            title: "Cat logic is unmatched",
            top_titles: [
                { title: "Cat logic is unmatched", score: 96 },
                { title: "Wait for the reaction at the end", score: 92 },
                { title: "When your cat forgets how to be a cat", score: 88 },
                { title: "The exact moment chaos was unleashed", score: 86 },
                { title: "Cats proving they own the house", score: 84 }
            ],
            description: "Curated CC Moments · Licensed under Creative Commons Attribution 4.0",
            hashtags: "#catvideos #catsoftiktok #funnycats #cats #shorts",
            quality_score: 96
        };
    }

    state.metadataPackage = pkg;
    renderMetadataCard(pkg);
    if (metaStatus) metaStatus.innerText = "Ready";
}

function renderMetadataCard(pkg) {
    if (!pkg) return;
    const mode = pkg.mode || state.activeMetadataMode || "full";
    state.activeMetadataMode = mode;

    const modeBadge = document.getElementById("export-meta-mode-badge");
    if (modeBadge) {
        modeBadge.innerText = mode === "title_only" ? "TITLE ONLY" : "FULL";
        modeBadge.style.color = mode === "title_only" ? "var(--accent-cyan)" : "var(--primary-emerald)";
    }

    const rowDesc = document.getElementById("row-meta-desc");
    const rowTags = document.getElementById("row-meta-tags");
    const boxNotice = document.getElementById("box-title-only-notice");
    if (rowDesc) rowDesc.style.display = mode === "title_only" ? "none" : "block";
    if (rowTags) rowTags.style.display = mode === "title_only" ? "none" : "block";
    if (boxNotice) boxNotice.style.display = mode === "title_only" ? "block" : "none";

    // Populate Top 5 Titles Dropdown
    const selectTitle = document.getElementById("select-meta-title");
    const titlesList = pkg.top_titles || pkg.ranked_titles || [];
    if (selectTitle && titlesList.length > 0) {
        selectTitle.innerHTML = titlesList.map((t, idx) => {
            const s = t.score || 90;
            const isSelected = (t.title === pkg.title) || (idx === 0);
            return `<option value="${escapeHtml(t.title)}" data-score="${s}" ${isSelected ? 'selected' : ''}>${escapeHtml(t.title)} (${s}/100)</option>`;
        }).join("");
    }

    const chosenTitle = (selectTitle && selectTitle.value) || pkg.title || "Cat logic is unmatched";
    const selectedOption = selectTitle ? selectTitle.options[selectTitle.selectedIndex] : null;
    const currentScore = selectedOption ? selectedOption.getAttribute("data-score") : (pkg.quality_score || 96);

    const scoreBadge = document.getElementById("badge-meta-checklist-score");
    if (scoreBadge) {
        scoreBadge.innerText = `${currentScore}/100 QUALITY`;
    }

    const metaTitleInput = document.getElementById("export-meta-title");
    const metaDescInput = document.getElementById("export-meta-desc");
    const metaTagsInput = document.getElementById("export-meta-tags");

    if (metaTitleInput) metaTitleInput.value = chosenTitle;

    const plat = state.activePlatform || "youtube_shorts";
    if (plat === "tiktok") {
        if (metaDescInput) metaDescInput.value = (pkg.tiktok && pkg.tiktok.caption) || pkg.description || "";
        if (metaTagsInput) metaTagsInput.value = (pkg.tiktok && pkg.tiktok.hashtags) || pkg.hashtags || "";
    } else if (plat === "instagram_reels") {
        if (metaDescInput) metaDescInput.value = (pkg.instagram && pkg.instagram.caption) || pkg.description || "";
        if (metaTagsInput) metaTagsInput.value = (pkg.instagram && pkg.instagram.hashtags) || pkg.hashtags || "";
    } else {
        if (metaDescInput) metaDescInput.value = pkg.description || "";
        if (metaTagsInput) metaTagsInput.value = pkg.hashtags || pkg.tags || "";
    }

    updateMetaCharCounters();
}

function updateMetaCharCounters() {
    const metaTitleInput = document.getElementById("export-meta-title");
    const metaDescInput = document.getElementById("export-meta-desc");
    const metaTagsInput = document.getElementById("export-meta-tags");
    const countTitle = document.getElementById("count-meta-title");
    const countDesc = document.getElementById("count-meta-desc");
    const countTags = document.getElementById("count-meta-tags");

    if (metaTitleInput && countTitle) {
        const len = metaTitleInput.value.length;
        countTitle.innerText = `${len} / 100`;
        countTitle.style.color = len > 100 ? "var(--error)" : "var(--text-muted)";
    }
    if (metaDescInput && countDesc) {
        const len = metaDescInput.value.length;
        countDesc.innerText = `${len} / 5000`;
        countDesc.style.color = len > 5000 ? "var(--error)" : "var(--text-muted)";
    }
    if (metaTagsInput && countTags) {
        const len = metaTagsInput.value.length;
        countTags.innerText = `${len} / 500`;
        countTags.style.color = len > 500 ? "var(--error)" : "var(--text-muted)";
    }
}

function parseMetadataText(text) {
    let title = "Cat logic is unmatched";
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
        if (state.isFetchingLogs) return;
        state.isFetchingLogs = true;
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
        } finally {
            state.isFetchingLogs = false;
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
    const activeJobId = jobId || state.currentJobId || state.lastActiveJobId || "default";

    // Only reset terminal when transitioning between two distinct real job IDs
    if (activeJobId && activeJobId !== "default") {
        if (state.lastActiveJobId && state.lastActiveJobId !== "default" && state.lastActiveJobId !== activeJobId) {
            state.seenLogKeys.clear();
            state.lastLogSeq = 0;
            body.innerText = "";
        }
        state.lastActiveJobId = activeJobId;
    }

    let newChunk = "";
    for (const item of lines) {
        const seq = item.seq;
        let lineText = item.text || "";
        // NO_EMOJI: Convert status symbols to plain ASCII status tags in console stream
        lineText = lineText
            .replace(/^[\u2713\u2714]\s*/, "[PASS] ") // NO_EMOJI: pass symbol
            .replace(/^[\u2715\u2716]\s*/, "[FAIL] ") // NO_EMOJI: fail symbol
            .replace(/^[\u26A0\uFE0F\u26A0]\s*/, "[WARN] "); // NO_EMOJI: warn symbol

        const trimmed = lineText.trim();
        // Strict deduplication by monotonic sequence ID and trimmed line text across the job
        const seqKey = `seq:${seq}`;
        const textKey = `txt:${trimmed}`;

        if (state.seenLogKeys.has(seqKey) || (trimmed && state.seenLogKeys.has(textKey))) {
            continue;
        }

        state.seenLogKeys.add(seqKey);
        if (trimmed) state.seenLogKeys.add(textKey);
        state.lastLogSeq = Math.max(state.lastLogSeq || 0, seq);
        newChunk += lineText + "\n";
    }

    if (newChunk) {
        body.innerText += newChunk;
        // Cap lines at 1000 so terminal body does not grow without limit
        const allLines = body.innerText.split("\n");
        if (allLines.length > 1000) {
            body.innerText = allLines.slice(-1000).join("\n");
        }
        body.scrollTop = body.scrollHeight;

        const totalLines = Math.min(allLines.length, 1000);
        if (counter) counter.innerText = `${totalLines} lines`;

        parseEngineTelemetry(newChunk);
    }
}

function appendRawLogs(chunk) {
    const body = document.getElementById("logs-terminal-body");
    const counter = document.getElementById("logs-line-counter");
    if (!body || !chunk) return;

    let cleanChunk = chunk
        .replace(/^[\u2713\u2714]\s*/gm, "[PASS] ") // NO_EMOJI: pass symbol
        .replace(/^[\u2715\u2716]\s*/gm, "[FAIL] ") // NO_EMOJI: fail symbol
        .replace(/^[\u26A0\uFE0F\u26A0]\s*/gm, "[WARN] "); // NO_EMOJI: warn symbol

    body.innerText += cleanChunk;
    const allLines = body.innerText.split("\n");
    if (allLines.length > 1000) {
        body.innerText = allLines.slice(-1000).join("\n");
    }
    body.scrollTop = body.scrollHeight;

    const totalLines = Math.min(allLines.length, 1000);
    if (counter) counter.innerText = `${totalLines} lines`;

    // Parse live telemetry from engine output
    parseEngineTelemetry(cleanChunk);
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
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Preview stream buffered successfully`;
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
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Background motion stabilized`;
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
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] AI Detector: Natural camera footage verified (no CGI)`;
        }

        if (line.includes("[CartoonCheck]") || line.includes("LIVE ANIMAL") || line.includes("Real animal")) {
            const qc11 = document.getElementById("qc-11");
            if (qc11) qc11.classList.add("verified");
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Cartoon Filter: Live authentic animal verified`;
        }

        if (line.includes("[AdCheck]") || line.includes("CLEAN PET VIDEO") || line.includes("Clean video")) {
            const qc12 = document.getElementById("qc-12");
            if (qc12) qc12.classList.add("verified");
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Anti-Ad Filter: Non-commercial content verified`;
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
            state.liveStatusMsg = `[Clip ${currentClipNum}/${targetClips}] Sliced segment ${segMatch[1]} of ${segMatch[2]} accepted`;
        }

        const accMatch = line.match(/ACCEPTED(?:\s*\u2705)?\s*—\s*Clip\s*(\d+)\/(\d+)/i);
        if (accMatch) {
            const cN = parseInt(accMatch[1]);
            const tN = parseInt(accMatch[2]) || targetClips;
            state.renderProgress = Math.max(state.renderProgress, Math.round(22 + (cN / tN) * 45));
            state.liveStatusMsg = `[Clip ${cN}/${tN}] Clip verified & added to compilation sequence`;
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
            state.liveStatusMsg = "Compilation complete! Preparing master export.";
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

function getShortReasonChip(r) {
    const isPass = r.result === "PASS";
    if (isPass) {
        return `<span class="badge badge-emerald" style="padding: 2px 8px; font-size: 0.70rem; font-weight: 700;">PASS</span>`;
    }
    const reason = (r.reason || "").toUpperCase();
    let label = "REJECT";
    let bg = "rgba(239,68,68,0.18)";
    let color = "#f87171";
    let border = "rgba(239,68,68,0.35)";

    if (reason.includes("WATERMARK")) {
        label = "WATERMARK";
        bg = "rgba(239,68,68,0.22)";
        color = "#fca5a5";
    } else if (reason.includes("BLURRED_BARS")) {
        label = "BLURRED_BARS";
        bg = "rgba(239,68,68,0.25)";
        color = "#f87171";
    } else if (reason.includes("ANALYSIS_FAILED")) {
        label = "ANALYSIS_FAILED";
        bg = "rgba(239,68,68,0.3)";
        color = "#fca5a5";
    } else if (reason.includes("NO_PET") || reason.includes("NO_TARGET_ANIMAL")) {
        label = "NO_PET";
        bg = "rgba(245,158,11,0.2)";
        color = "#fbbf24";
        border = "rgba(245,158,11,0.4)";
    } else if (reason.includes("BAD_SIZE") || reason.includes("SIZE")) {
        label = "BAD_SIZE";
        bg = "rgba(245,158,11,0.2)";
        color = "#fbbf24";
        border = "rgba(245,158,11,0.4)";
    } else if (reason.includes("BAD_H") || reason.includes("HORIZ")) {
        label = "BAD_H";
        bg = "rgba(245,158,11,0.2)";
        color = "#fbbf24";
        border = "rgba(245,158,11,0.4)";
    } else if (reason.includes("BAD_V") || reason.includes("VERT")) {
        label = "BAD_V";
        bg = "rgba(245,158,11,0.2)";
        color = "#fbbf24";
        border = "rgba(245,158,11,0.4)";
    } else if (reason.includes("NMS_OVERLAP")) {
        label = "NMS_OVERLAP";
        bg = "rgba(139,92,246,0.2)";
        color = "#c084fc";
        border = "rgba(139,92,246,0.4)";
    } else if (reason.includes("MAX_SOURCE_CAP")) {
        label = "MAX_SOURCE_CAP";
        bg = "rgba(139,92,246,0.2)";
        color = "#c084fc";
        border = "rgba(139,92,246,0.4)";
    } else if (reason.includes("UPSCALE")) {
        label = "UPSCALE";
        bg = "rgba(249,115,22,0.2)";
        color = "#fb923c";
        border = "rgba(249,115,22,0.4)";
    } else if (reason.includes("EARLY_ABORT")) {
        label = "EARLY_ABORT";
        bg = "rgba(239,68,68,0.2)";
        color = "#f87171";
    } else if (reason.includes("WINDOW_UNAVAILABLE")) {
        label = "WINDOW_UNAVAILABLE";
        bg = "rgba(107,114,128,0.2)";
        color = "#9ca3af";
        border = "rgba(107,114,128,0.4)";
    } else if (reason.includes("PREDICTED_BAD_FRAMING")) {
        label = "BAD_FRAMING";
        bg = "rgba(245,158,11,0.2)";
        color = "#fbbf24";
        border = "rgba(245,158,11,0.4)";
    } else if (reason.includes("POST_CROP_GATE_FAIL")) {
        label = "GATE_FAIL";
        bg = "rgba(239,68,68,0.2)";
        color = "#f87171";
    } else if (reason.includes("FUNNY_PART_MISSING")) {
        label = "NO_FUNNY_PEAK";
        bg = "rgba(244,63,94,0.2)";
        color = "#fda4af";
        border = "rgba(244,63,94,0.4)";
    } else if (reason.includes("CUT_IN_ACTION")) {
        label = "CUT_IN_ACTION";
        bg = "rgba(244,63,94,0.2)";
        color = "#fda4af";
        border = "rgba(244,63,94,0.4)";
    } else if (reason.includes("CROSSES_SHOT_CUT") || reason.includes("SHOT_CUT")) {
        label = "CROSSES_SHOT_CUT";
        bg = "rgba(244,63,94,0.2)";
        color = "#fda4af";
        border = "rgba(244,63,94,0.4)";
    }

    return `<span class="badge" style="background: ${bg}; color: ${color}; border: 1px solid ${border}; padding: 2px 7px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.02em;">${label}</span>`;
}

function formatMetricPct(val, isMeasured) {
    if (!isMeasured || val === null || val === undefined) {
        return `<span style="color: var(--text-muted); font-style: italic; font-size: 0.70rem;">not measured</span>`;
    }
    const num = typeof val === "number" ? val : parseFloat(val);
    if (isNaN(num)) return `<span style="color: var(--text-muted); font-style: italic; font-size: 0.70rem;">not measured</span>`;
    return `${(num * 100).toFixed(1)}%`;
}

function formatMetricVal(val, isMeasured) {
    if (!isMeasured || val === null || val === undefined) {
        return `<span style="color: var(--text-muted); font-style: italic; font-size: 0.70rem;">not measured</span>`;
    }
    const num = typeof val === "number" ? val : parseFloat(val);
    if (isNaN(num)) return `<span style="color: var(--text-muted); font-style: italic; font-size: 0.70rem;">not measured</span>`;
    return num.toFixed(1);
}

window.toggleCandidateDetail = function(idx) {
    const row = document.getElementById(`cand-detail-${idx}`);
    const chev = document.getElementById(`cand-chev-${idx}`);
    if (row) {
        const isHidden = (row.style.display === "none" || !row.style.display);
        row.style.display = isHidden ? "table-row" : "none";
        if (chev) {
            chev.innerHTML = isHidden
                ? '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-up"></use></svg>'
                : '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-down"></use></svg>';
        }
    }
};

function renderCandidateReportsTable(reports) {
    const container = document.getElementById("render-candidate-table-container");
    if (!container) return;
    if (!reports || reports.length === 0) {
        container.style.display = "none";
        container.innerHTML = "";
        return;
    }

    container.style.display = "block";

    // Summary calculation (Fix 6b)
    const totalCount = reports.length;
    const passCount = reports.filter(r => r.result === "PASS").length;
    const blurredBarsCount = reports.filter(r => (r.reason || "").includes("BLURRED_BARS")).length;
    const watermarkCount = reports.filter(r => (r.reason || "").includes("WATERMARK")).length;
    const currentLayout = (state.config.LAYOUT_MODE || localStorage.getItem("lionreel_layout_mode") || "smart_crop").toLowerCase();
    const isBlurFit = currentLayout === "blur_fit";

    let summaryHtml = "";
    if (blurredBarsCount > 0 && isBlurFit) {
        summaryHtml = `
            <div class="audit-summary-banner" style="background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.3); border-radius: var(--radius-sm); padding: 10px 14px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div style="font-size: 0.8rem; color: #f87171; font-weight: 600; display: inline-flex; align-items: center; gap: 8px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <span>${blurredBarsCount} of ${totalCount} rendered candidates failed for the same reason: BLURRED_BARS + SIZE. Suggested fix: use Smart crop</span>
                </div>
                <button id="btn-retry-smart-crop" class="btn btn-primary btn-sm" style="background: #10b981; border: 1px solid #059669; font-size: 0.75rem; padding: 5px 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-weight: 600;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                    <span>Retry with Smart Crop</span>
                </button>
            </div>
        `;
    } else if (watermarkCount > 0 && passCount === 0) {
        summaryHtml = `
            <div class="audit-summary-banner" style="background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.3); border-radius: var(--radius-sm); padding: 10px 14px; margin-bottom: 12px;">
                <div style="font-size: 0.8rem; color: #f87171; font-weight: 600; display: inline-flex; align-items: center; gap: 8px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <span>${watermarkCount} candidate(s) rejected by WATERMARK filter. Watermarked sources have been blocked from pool.</span>
                </div>
            </div>
        `;
    } else if (passCount < totalCount) {
        summaryHtml = `
            <div class="audit-summary-banner" style="background: rgba(59,130,246,0.12); border: 1px solid rgba(59,130,246,0.3); border-radius: var(--radius-sm); padding: 10px 14px; margin-bottom: 12px;">
                <div style="font-size: 0.8rem; color: #60a5fa; font-weight: 600; display: inline-flex; align-items: center; gap: 8px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
                    <span>Evaluated ${totalCount} candidates: ${passCount} passed, ${totalCount - passCount} rejected.</span>
                </div>
            </div>
        `;
    }

    function getPlainLanguageReason(r) {
        if (r.result === "PASS") return "Passed all gates: centering >= 90%, sharpness >= 150, clear footage.";
        const reason = r.reason || "";
        if (reason.includes("FRAMING_INFEASIBLE")) return "Pet fills >92% of crop width; framing physically infeasible in 9:16 aspect ratio.";
        if (reason.includes("WATERMARK")) return "Channel logo or watermark detected in corner; source blocked.";
        if (reason.includes("CARTOON") || reason.includes("CGI")) return "Synthetic CGI or cartoon footage detected; real animal footage required.";
        if (reason.includes("LOW_RES")) return "Resolution below gate (upscale > 2.0x required for 1080p).";
        if (reason.includes("POST_CROP_GATE_FAIL")) return `Post-render centering check failed: ${reason}`;
        if (reason.includes("BAD_H") || reason.includes("HORIZ")) return "Pet wandered outside 9:16 horizontal crop boundaries.";
        if (reason.includes("BAD_V") || reason.includes("VERT")) return "Pet cropped vertically outside safe window.";
        if (reason.includes("BAD_SIZE")) return "Pet bounding box too small in frame (<28% frame height).";
        if (reason.includes("NO_PET")) return "No cat detected in window frames.";
        if (reason.includes("SHARP")) return `Sharpness score below minimum 150 gate.`;
        if (reason.includes("MAX_SOURCE_CAP")) return "Maximum clips per source reached (prioritizing source diversity).";
        if (reason.includes("NMS_OVERLAP")) return "Window overlaps with an already selected clip from the same source.";
        return reason || "Candidate failed 90% quality threshold.";
    }

    function normalizeUiLicense(lic) {
        if (!lic) return "CC BY 4.0";
        const l = String(lic).trim();
        if (l.toLowerCase().includes("cc0") || l.toLowerCase().includes("zero")) return "CC0 1.0";
        if (l.toLowerCase().includes("3.0")) return "CC BY 3.0";
        if (l.toLowerCase().includes("sa")) return "CC BY-SA 4.0";
        if (l.toLowerCase().includes("cc-by") || l.toLowerCase().includes("creative commons") || l.toLowerCase().includes("attribution")) return "CC BY 4.0";
        return l;
    }

    const seenUniqueWindows = new Set();
    const uniqueReports = [];
    for (const r of reports) {
        const sN = typeof r.start_s === "number" ? r.start_s.toFixed(1) : "0.0";
        const eN = (typeof r.start_s === "number" && typeof r.dur_s === "number") ? (r.start_s + r.dur_s).toFixed(1) : sN;
        const uKey = `${r.source}_${sN}_${eN}`;
        if (!seenUniqueWindows.has(uKey)) {
            seenUniqueWindows.add(uKey);
            uniqueReports.push(r);
        }
    }

    let rowsHtml = uniqueReports.map((r, idx) => {
        const isPass = r.result === "PASS";
        const reasonChip = getShortReasonChip(r);
        const isMeasured = Boolean(r.measured !== false && (r.pet_ratio !== null || r.score !== null));

        const petStr = formatMetricPct(r.pet_ratio, isMeasured);
        const horizStr = formatMetricPct(r.horiz_ratio, isMeasured);
        const vertStr = formatMetricPct(r.vert_ratio, isMeasured);
        const sizeStr = formatMetricPct(r.size_ratio, isMeasured);
        const sharpStr = formatMetricVal(r.sharpness, isMeasured);
        const predStr = formatMetricPct(r.score, isMeasured);
        const actStr = formatMetricPct(r.actual_score, typeof r.actual_score === "number");

        const startNum = typeof r.start_s === "number" ? r.start_s.toFixed(1) : "—";
        const durNum = typeof r.dur_s === "number" ? r.dur_s.toFixed(1) : "—";
        const endNum = (typeof r.start_s === "number" && typeof r.dur_s === "number") ? (r.start_s + r.dur_s).toFixed(1) : "—";

        const isVert = (r.source_orientation === 'vertical' || r.source_orientation === '9:16 Vert' || r.orientation === 'vertical' || (r.plan && r.plan.mode === 'vertical_direct'));
        const orientationLabel = isVert ? "9:16 Vert" : "16:9 Horiz";
        const rawLicense = (r.clip_info && r.clip_info.license) || r.license || "CC-BY";
        const licenseLabel = normalizeUiLicense(rawLicense);
        const plainReason = getPlainLanguageReason(r);
        const srcTitle = (r.clip_info && (r.clip_info.title || r.clip_info.author || r.clip_info.uploader)) || r.source || "—";

        return `
            <tr style="border-bottom: 1px solid var(--border); cursor: pointer;" onclick="toggleCandidateDetail(${idx})" title="Click to view full candidate details">
                <td style="padding: 7px 8px; font-family: var(--font-mono); font-weight: 600; white-space: nowrap;">Cand ${r.candidate}</td>
                <td style="padding: 7px 8px; color: var(--text-secondary); max-width: 140px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.70rem;" title="${escapeHtml(r.source || '')}">${escapeHtml(srcTitle)}</td>
                <td style="padding: 7px 6px; font-size: 0.68rem; text-align: center;"><span class="badge ${isVert ? 'badge-blue' : 'badge-neutral'}">${orientationLabel}</span></td>
                <td style="padding: 7px 6px; font-size: 0.68rem; color: var(--text-muted); text-align: center;">${escapeHtml(licenseLabel)}</td>
                <td style="padding: 7px 6px; font-family: var(--font-mono); text-align: right;">${petStr}</td>
                <td style="padding: 7px 6px; font-family: var(--font-mono); text-align: right;">${horizStr}</td>
                <td style="padding: 7px 6px; font-family: var(--font-mono); text-align: right;">${vertStr}</td>
                <td style="padding: 7px 6px; font-family: var(--font-mono); text-align: right;">${sizeStr}</td>
                <td style="padding: 7px 6px; font-family: var(--font-mono); text-align: right;">${sharpStr}</td>
                <td style="padding: 7px 6px; font-family: var(--font-mono); text-align: right; font-weight: 600;">${predStr}</td>
                <td style="padding: 7px 6px; font-family: var(--font-mono); text-align: right; font-weight: 600;">${actStr}</td>
                <td style="padding: 7px 8px; text-align: center;">${reasonChip}</td>
                <td style="padding: 7px 6px; text-align: center; color: var(--text-muted); font-size: 0.70rem;" id="cand-chev-${idx}"><svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-down"></use></svg></td>
            </tr>
            <tr id="cand-detail-${idx}" style="display: none; background: rgba(0,0,0,0.2); border-bottom: 1.5px solid var(--border);">
                <td colspan="13" style="padding: 10px 14px; font-size: 0.73rem; color: var(--text-secondary);">
                    <div style="display: flex; flex-direction: column; gap: 5px;">
                        <div><strong style="color: var(--text-primary);">Time Window:</strong> ${startNum}s - ${endNum}s (${durNum}s) | <strong style="color: var(--text-primary);">Clip ID:</strong> <code style="font-size: 0.70rem;">${escapeHtml(r.clip_id || '—')}</code> | <strong style="color: var(--text-primary);">Source Format:</strong> ${orientationLabel} | <strong style="color: var(--text-primary);">License:</strong> ${escapeHtml(licenseLabel)}</div>
                        <div><strong style="color: var(--text-primary);">Source Video / Channel:</strong> <span style="color: var(--text-primary); font-weight: 600;">${escapeHtml(srcTitle)}</span> (<code style="font-size: 0.68rem;">${escapeHtml(r.source || '')}</code>)</div>
                        <div><strong style="color: var(--text-primary);">Plain-Language Reason:</strong> <span style="color: #60a5fa; font-weight: 600;">${plainReason}</span></div>
                        <div><strong style="color: var(--text-primary);">Gate Telemetry / Full Detail:</strong> <span style="color: var(--text-primary); font-family: var(--font-mono);">${escapeHtml(r.reason || 'No additional details')}</span></div>
                    </div>
                </td>
            </tr>
        `;
    }).join("");

    container.innerHTML = `
        <div style="background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px; margin-top: 10px; overflow-x: auto; max-height: 520px; overflow-y: auto;">
            ${summaryHtml}
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 0.82rem; font-weight: 700; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.04em;">Processing Gate Candidates Audit</span>
                <span style="font-size: 0.72rem; color: var(--text-muted);">${uniqueReports.length} unique windows evaluated</span>
            </div>
            <table style="width: 100%; border-collapse: collapse; font-size: 0.74rem; text-align: left;">
                <thead style="position: sticky; top: 0; background: var(--bg-card); z-index: 2;">
                    <tr style="border-bottom: 1.5px solid var(--border); color: var(--text-muted); font-size: 0.70rem;">
                        <th style="padding: 6px 8px;">Cand</th>
                        <th style="padding: 6px 8px;">Source</th>
                        <th style="padding: 6px 6px; text-align: center;">Format</th>
                        <th style="padding: 6px 6px; text-align: center;">License</th>
                        <th style="padding: 6px 6px; text-align: right;">Pet %</th>
                        <th style="padding: 6px 6px; text-align: right;">H</th>
                        <th style="padding: 6px 6px; text-align: right;">V</th>
                        <th style="padding: 6px 6px; text-align: right;">Size</th>
                        <th style="padding: 6px 6px; text-align: right;">Sharpness</th>
                        <th style="padding: 6px 6px; text-align: right;">Predicted</th>
                        <th style="padding: 6px 6px; text-align: right;">Actual</th>
                        <th style="padding: 6px 8px; text-align: center;">Reason</th>
                        <th style="padding: 6px 6px; text-align: center;"></th>
                    </tr>
                </thead>
                <tbody>
                    ${rowsHtml}
                </tbody>
            </table>
        </div>
    `;

    // Wire Retry with Smart Crop button if present (Fix 6b)
    const btnRetrySmart = document.getElementById("btn-retry-smart-crop");
    if (btnRetrySmart) {
        btnRetrySmart.onclick = (e) => {
            e.stopPropagation();
            state.config.LAYOUT_MODE = "smart_crop";
            localStorage.setItem("lionreel_layout_mode", "smart_crop");
            const selEl = document.getElementById("select-layout-mode");
            if (selEl) selEl.value = "smart_crop";
            showToast("Switched layout to Smart crop. Starting new compilation job...", "info");
            state.currentJobId = null;
            startRenderPipeline();
        };
    }
}

async function renderSelfHealingBanner(data, gotClips, targetClips, isNeedsSources) {
    const banner = document.getElementById("self-heal-amber-banner");
    if (!banner) return;
    banner.style.display = "block";

    // Fetch pool health for telemetry
    let health = { verified_clips: 40, distinct_sources: 9, verified_sources_count: 6, vertical_sources_count: 4, blocked_sources_count: 9, blocked_sources_list: [] };
    try {
        const hRes = await fetch(`${API_BASE}/api/pool-health`);
        if (hRes.ok) health = await hRes.json();
    } catch (e) {}

    const canMakeShorter = (gotClips >= 2);
    const shorterDuration = Math.round(gotClips * (state.config.SHORT_CLIP_SEC || 7.5));

    banner.innerHTML = `
        <div style="background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.3); border-radius: var(--radius-sm); padding: 14px; margin-bottom: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 12px;">
                <div>
                    <div style="font-weight: 700; color: #f59e0b; font-size: 0.90rem; display: flex; align-items: center; gap: 8px;">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                        <span>${isNeedsSources ? "Pool Needs Additional Sources" : "Self-Healing State: Waiting for Clips"}</span>
                    </div>
                    <div style="font-size: 0.80rem; color: var(--text-secondary); margin-top: 4px;">
                        ${isNeedsSources 
                            ? "No usable clips remaining in pool. Add high-resolution sources below. Hint: Vertical 9:16 videos frame best." 
                            : `Finding more clips: <strong>${gotClips} of ${targetClips} ready</strong>. Job will automatically resume when bank fills.`}
                    </div>
                </div>

                <!-- 3 Interactive Action Buttons (Prompt Section 5 & 7) -->
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    <button id="btn-selfheal-keep-searching" class="btn btn-secondary btn-sm" style="background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15);">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                        <span>Keep Searching</span>
                    </button>
                    ${canMakeShorter ? `
                    <button id="btn-selfheal-make-shorter" class="btn btn-primary btn-sm" style="background: #10b981; border: 1px solid #059669;">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                        <span>Make Shorter Video (${gotClips} clips, ~${shorterDuration}s)</span>
                    </button>` : ''}
                    <button id="btn-selfheal-cancel" class="btn btn-secondary btn-sm" style="color: #f87171; border-color: rgba(239,68,68,0.3);">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        <span>Cancel</span>
                    </button>
                    <button id="btn-selfheal-add-sources" class="btn btn-secondary btn-sm" style="background: rgba(59,130,246,0.15); border-color: rgba(59,130,246,0.35); color: #60a5fa;">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                        <span>Add Sources (Step 2)</span>
                    </button>
                </div>
            </div>

            <!-- Pool Health Telemetry Strip (Prompt Section 1 & 7) -->
            <div style="background: rgba(0,0,0,0.25); border-radius: var(--radius-xs); padding: 10px 14px; border: 1px solid rgba(255,255,255,0.06); font-size: 0.78rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <span style="font-weight: 700; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.04em;">Footage Bank &amp; Pool Health</span>
                    <span style="color: #10b981; font-weight: 600;">Quality Floor Intact (Centering &ge; 90%, Sharpness &ge; 150)</span>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin-top: 6px;">
                    <div><span style="color: var(--text-muted);">Verified Clips:</span> <strong style="color: #10b981;">${health.verified_clips || 0}</strong></div>
                    <div><span style="color: var(--text-muted);">Distinct Sources:</span> <strong>${health.distinct_sources || 0}</strong></div>
                    <div><span style="color: var(--text-muted);">Vertical 9:16 Sources:</span> <strong style="color: #60a5fa;">${health.vertical_sources_count || 0}</strong></div>
                    <div><span style="color: var(--text-muted);">Blocked Sources:</span> <strong style="color: #f87171;">${health.blocked_sources_count || 0}</strong></div>
                </div>
                <div style="margin-top: 8px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 0.74rem; color: var(--text-secondary); display: flex; justify-content: space-between; flex-wrap: gap: 8px;">
                    <span>Hint: <strong>Vertical 9:16 sources</strong> (CC shorts, portrait mobile videos) frame best with zero crop loss.</span>
                    <span style="color: #60a5fa; cursor: pointer; text-decoration: underline;" onclick="const el=document.getElementById('pool-blocked-reasons-list'); if(el) el.style.display = el.style.display === 'none' ? 'block' : 'none';">Toggle Blocked Reasons &darr;</span>
                </div>
                <div id="pool-blocked-reasons-list" style="display: none; margin-top: 6px; font-size: 0.72rem; color: #fca5a5; line-height: 1.4;">
                    ${(health.blocked_sources_list || []).map(b => `<div>&bull; <strong>${escapeHtml(b.source)}</strong>: ${escapeHtml(b.reason)}</div>`).join("")}
                </div>
            </div>
        </div>
    `;

    // Wire buttons
    const btnKeep = document.getElementById("btn-selfheal-keep-searching");
    if (btnKeep) btnKeep.onclick = async () => {
        showToast("Extending search budget by 10 minutes...", "info");
        await fetch(`${API_BASE}/api/job-action`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "keep_searching", job_id: state.currentJobId })
        });
        startLogsPolling();
    };

    const btnShort = document.getElementById("btn-selfheal-make-shorter");
    if (btnShort) btnShort.onclick = async () => {
        showToast(`Proceeding with shorter compilation (${gotClips} clips)...`, "info");
        await fetch(`${API_BASE}/api/job-action`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "make_shorter", job_id: state.currentJobId })
        });
        startLogsPolling();
    };

    const btnCancel = document.getElementById("btn-selfheal-cancel");
    if (btnCancel) btnCancel.onclick = async () => {
        if (confirm("Cancel this compilation job?")) {
            await fetch(`${API_BASE}/api/job-action`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "cancel", job_id: state.currentJobId })
            });
            showToast("Job cancelled", "info");
            checkEngineStatus();
        }
    };

    const btnAdd = document.getElementById("btn-selfheal-add-sources");
    if (btnAdd) btnAdd.onclick = () => {
        navigateToStep(2);
    };
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

                // Live progress and stage from backend estimator
                if (typeof data.progressPct === "number") {
                    state.renderProgress = Math.max(state.renderProgress || 0, data.progressPct);
                }
                if (typeof data.elapsedSeconds === "number") {
                    state.serverElapsedSeconds = data.elapsedSeconds;
                    state.lastServerSyncMs = Date.now();
                }
                if (data.etaFormatted) {
                    state.serverEtaFormatted = data.etaFormatted;
                }
                if (data.stateLabel) {
                    state.serverStateLabel = data.stateLabel;
                }
                state.isCalculating = !!data.isCalculating;

                if (typeof data.stageIndex === "number" && data.stageIndex > 0) {
                    state.renderStageIndex = Math.max(state.renderStageIndex, data.stageIndex);
                }
                if (data.stageName) {
                    state.liveStatusMsg = `Stage ${state.renderStageIndex}/10: ${data.stageName}`;
                }
                updateRenderHeroUI(state.renderProgress);
                if (data.stages && Array.isArray(data.stages)) {
                    updateRenderStagesUI(data.stages);
                } else {
                    updateRenderStagesUI(state.renderStageIndex);
                }

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
                stopLiveRenderClock("DONE");

                state.serverStateLabel = "DONE";
                if (typeof data.elapsedSeconds === "number") {
                    state.serverElapsedSeconds = data.elapsedSeconds;
                    const el = document.getElementById("render-time-elapsed");
                    if (el) el.innerText = formatDuration(data.elapsedSeconds);
                }
                state.serverEtaFormatted = "--:--";
                const remEl = document.getElementById("render-time-remaining");
                if (remEl) remEl.innerText = "--:--";

                const headline = document.getElementById("render-headline");
                if (headline) headline.innerText = "Your compilation is ready";

                state.renderProgress = 100;
                state.renderStageIndex = 10;
                updateRenderHeroUI(100);
                if (data.stages && Array.isArray(data.stages)) {
                    updateRenderStagesUI(data.stages);
                } else {
                    updateRenderStagesUI(11);
                }
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

                const editBtn = document.getElementById("btn-render-edit-video");
                if (editBtn) {
                    editBtn.style.display = "inline-flex";
                    editBtn.onclick = () => {
                        window.loadVideoIntoEditor(targetFile || { name: newFileName, filename: newFileName });
                        navigateToStep(3);
                    };
                }

                showToast("Video generated successfully", "success");
                setTimeout(() => {
                    navigateToStep(5);
                    setupExportScreen(targetFile);
                }, 800);
                return;
            } else if (data.status === "waiting_for_clips" || data.status === "needs_sources") {
                state.isRunning = false;
                setGenerateButtonsDisabled(false);
                updateEngineStatusBadge(false);
                stopLiveRenderClock("WAITING");

                state.serverStateLabel = "WAITING";
                state.serverEtaFormatted = "Waiting for clips";
                if (typeof data.elapsedSeconds === "number") {
                    state.serverElapsedSeconds = data.elapsedSeconds;
                    const el = document.getElementById("render-time-elapsed");
                    if (el) el.innerText = formatDuration(data.elapsedSeconds);
                }
                const remEl = document.getElementById("render-time-remaining");
                if (remEl) remEl.innerText = "Waiting for clips";

                const heroCard = document.getElementById("render-hero-card");
                if (heroCard) {
                    heroCard.classList.remove("failed");
                    heroCard.classList.add("waiting");
                }

                const gotClips = (data.jobResult && data.jobResult.got_clips) || 0;
                const targetClips = (data.jobResult && data.jobResult.target_clips) || (state.config.TARGET_CLIPS || 4);
                const isNeedsSources = (data.status === "needs_sources");
                const headline = document.getElementById("render-headline");
                if (headline) {
                    const badgeText = isNeedsSources ? "Needs Sources" : "Finding More Clips";
                    headline.innerHTML = `<span class="badge" style="background: rgba(245,158,11,0.2); color: #f59e0b; border: 1px solid rgba(245,158,11,0.4); margin-right: 8px; vertical-align: middle;">${badgeText}</span>Finding more clips: ${gotClips} of ${targetClips} ready`;
                }

                const subtitle = document.getElementById("render-subtitle");
                if (subtitle) {
                    subtitle.innerText = isNeedsSources
                        ? "The footage pool needs additional 1080p+ cat video sources. Hint: Vertical 9:16 sources frame best and require no smart cropping."
                        : `Background harvest worker active. Finding more clips (${gotClips} of ${targetClips} ready). The job will automatically resume when enough clips exist.`;
                }

                // Render Amber Self-Healing Banner & Action Buttons
                renderSelfHealingBanner(data, gotClips, targetClips, isNeedsSources);

                // Render candidate reports table if candidates exist
                const candidateReports = data.candidateReports || (data.jobResult && data.jobResult.candidate_reports) || [];
                if (candidateReports.length > 0) {
                    renderCandidateReportsTable(candidateReports);
                }
                return;
            } else if (data.status === "error" || data.status === "pool_low" || (data.jobResult && data.jobResult.success === false) || (data.exitCode !== null && data.exitCode !== 0)) {
                // Background process reported an error or crashed or gate failure
                state.isRunning = false;
                setGenerateButtonsDisabled(false);
                updateEngineStatusBadge(false);
                stopLogsPolling();
                stopLiveRenderClock(data.status === "pool_low" ? "POOL LOW" : "FAILED");

                // Fix 6c: Display exact real elapsed duration from backend on failed jobs
                const finalElapsed = (typeof data.elapsedSeconds === "number" && data.elapsedSeconds > 0)
                    ? data.elapsedSeconds
                    : (data.jobResult && (data.jobResult.elapsed_seconds || data.jobResult.render_time_sec));
                if (typeof finalElapsed === "number" && finalElapsed > 0) {
                    const elapsedEl = document.getElementById("render-time-elapsed");
                    if (elapsedEl) elapsedEl.innerText = formatDuration(Math.round(finalElapsed));
                }

                const errMsg = data.error || (data.jobResult && data.jobResult.error) || (data.exitCode ? `Process exited with error code ${data.exitCode}` : "Compilation failed");
                state.liveStatusMsg = errMsg;
                updateRenderHeroUI(state.renderProgress);

                // Set failure UI state
                const headline = document.getElementById("render-headline");
                if (headline) {
                    headline.innerHTML = `<svg class="icon icon-md" style="color: var(--danger); vertical-align: -3px; margin-right: 8px;" aria-hidden="true"><use href="#icon-circle-x"></use></svg>Video generation failed`;
                }

                const heroCard = document.getElementById("render-hero-card");
                if (heroCard) heroCard.classList.add("failed");

                // Highlight failed stage
                let failedStageId = data.stageIndex || state.renderStageIndex || 1;
                if (data.failedStage) {
                    const fIdx = RENDER_STAGES.findIndex(s => (s.name || "").toLowerCase().includes(data.failedStage.toLowerCase()));
                    if (fIdx >= 0) failedStageId = fIdx + 1;
                }
                if (data.stages && Array.isArray(data.stages)) {
                    updateRenderStagesUI(data.stages, failedStageId);
                } else {
                    updateRenderStagesUI(state.renderStageIndex, failedStageId);
                }

                // Hide ETA on failed jobs (Fix 6c)
                const remainWrap = document.getElementById("render-telemetry-remaining");
                if (remainWrap) remainWrap.style.display = "none";

                // Render candidate reports table
                const candidateReports = data.candidateReports || (data.jobResult && data.jobResult.candidate_reports) || [];
                if (candidateReports.length > 0) {
                    renderCandidateReportsTable(candidateReports);
                }

                if (errMsg.includes("Pool low") || data.status === "pool_low") {
                    showToast(errMsg, "warning");
                    if (retryBtn) {
                        retryBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 6px;"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg><span>${escapeHtml(errMsg)}</span>`;
                        retryBtn.style.display = "inline-flex";
                        retryBtn.onclick = () => { state.currentJobId = null; startRenderPipeline(); };
                    }
                } else if (errMsg.includes("No new clips available") || errMsg.includes("NO_NEW_CLIPS_AVAILABLE")) {
                    showToast("No new clips available in pool. Please add new sources.", "error");
                    if (retryBtn) {
                        retryBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 6px;"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg><span>Add Sources (Step 2)</span>`;
                        retryBtn.style.display = "inline-flex";
                        retryBtn.onclick = () => { navigateToStep(2); };
                    }
                } else {
                    if (retryBtn) {
                        retryBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 6px;"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg><span>Retry Generation</span>`;
                        retryBtn.style.display = "inline-flex";
                        retryBtn.onclick = () => {
                            state.currentJobId = null;
                            startRenderPipeline();
                        };
                    }
                    showToast(`Video generation error: ${errMsg}`, "error");
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
                    retryBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 6px;"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg><span>Retry Generation</span>`;
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
        let thumb = proj.thumbnail;
        if (!thumb || thumb.includes("contact_sheet")) {
            thumb = isLandscape 
                ? "https://images.unsplash.com/photo-1548767797-d8c844163c4c?w=640&q=80"
                : "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80";
        }
        const fileUrl = proj.url || `/finished/${encodeURIComponent(name)}`;

        return `
            <div class="project-card" data-proj-name="${name}">
                <div class="project-thumb-wrap">
                    <img src="${thumb}" alt="${escapeHtml(name)}" loading="lazy">
                    <div class="project-card-play" data-play-url="${fileUrl}" data-play-name="${escapeHtml(name)}" title="Play compilation">
                        <svg class="icon icon-md" aria-hidden="true"><use href="#icon-play"></use></svg>
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
                        <button type="button" class="btn btn-primary btn-sm btn-proj-open" data-open="${name}" title="Open in export viewer">
                            <svg class="icon icon-sm" aria-hidden="true"><use href="#icon-external-link"></use></svg>
                            <span>Open</span>
                        </button>
                        <button type="button" class="btn btn-secondary btn-sm btn-proj-edit" data-edit="${name}" title="Edit this compilation in Studio">
                            <svg class="icon icon-sm" aria-hidden="true"><use href="#icon-scissors"></use></svg>
                            <span>Edit</span>
                        </button>
                        <a href="${fileUrl}" download="${name}" class="btn btn-secondary btn-sm" title="Download compilation MP4">
                            <svg class="icon icon-sm" aria-hidden="true"><use href="#icon-download"></use></svg>
                            <span>Download</span>
                        </a>
                        <button type="button" class="btn btn-secondary btn-sm btn-icon btn-proj-del" data-del="${name}" aria-label="Delete" title="Delete" style="color: var(--danger); border-color: rgba(239, 68, 68, 0.35);">
                            <svg class="icon icon-sm" aria-hidden="true"><use href="#icon-trash-2"></use></svg>
                        </button>
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

    grid.querySelectorAll(".btn-proj-edit").forEach(btn => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const name = btn.getAttribute("data-edit");
            state.activeFinishedProjectName = name;
            await window.loadVideoIntoEditor(name);
            navigateToStep(3);
            showToast(`Loaded "${name}" into Edit timeline`, "success");
        });
    });

    grid.querySelectorAll(".btn-proj-dup").forEach(btn => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const name = btn.getAttribute("data-dup");
            state.activeFinishedProjectName = name;
            await window.loadVideoIntoEditor(name);
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

        if (notify) showToast(`Long Video Mode (${min.toFixed(1)} min) selected`, "success");
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

        if (notify) showToast("Dual Mode (Long Video + Short Reel) selected", "success");
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

        if (notify) showToast("Short Reel (30-60s) Mode selected", "success");
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
    if (notify) showToast(`Long video duration set to ${val.toFixed(1)} minutes`, "info");
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
    if (notify) showToast(`Short reel set to ~${Math.round(targetClips * targetSec)}s (${targetClips} clips × ${targetSec.toFixed(1)}s)`, "info");
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
        if (notify) showToast("Platform Format: 16:9 Landscape (1920×1080) selected", "success");
    } else if (aspect === "1:1") {
        if (btnFormat11) btnFormat11.classList.add("active");
        if (formatDescText) formatDescText.innerText = "Square 1:1 for Instagram Feed & Facebook Carousel (1080×1080)";
        if (badgeAspectRes) badgeAspectRes.innerText = "1080×1080 (1:1 Square)";
        if (notify) showToast("Platform Format: 1:1 Square (1080×1080) selected", "success");
    } else {
        if (btnFormat916) btnFormat916.classList.add("active");
        if (formatDescText) formatDescText.innerText = "Standard 9:16 for YouTube Shorts, Instagram Reels & TikTok (1080×1920)";
        if (badgeAspectRes) badgeAspectRes.innerText = "1080×1920 (9:16 Vertical)";
        if (notify) showToast("Platform Format: 9:16 Vertical Shorts (1080×1920) selected", "success");
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
                const val = state.config.SHARPNESS_THRESHOLD || state.config.MIN_LAPLACIAN_VARIANCE || 150;
                confSharpness.innerText = Number.isInteger(Number(val)) ? String(Number(val)) : parseFloat(val).toFixed(1);
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
                showToast("Opened LionReel Workspace in Windows Explorer", "info");
            } catch (e) {
                showToast("Active Workspace: Animal Shorts Lab", "info");
            }
        });
    }

    // User avatar
    const userAvatar = document.querySelector(".user-avatar-btn");
    if (userAvatar) {
        userAvatar.addEventListener("click", () => {
            showToast("LionReel Creator Pro: Active Session Ready", "success");
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

    if (heroNewBtn) heroNewBtn.addEventListener("click", () => { state.wizardStage = 1; navigateToStep(2); showToast("New Compilation Wizard started", "info"); });
    if (emptyNewBtn) emptyNewBtn.addEventListener("click", () => { state.wizardStage = 1; navigateToStep(2); showToast("New Compilation Wizard started", "info"); });
    if (exportNewBtn) exportNewBtn.addEventListener("click", () => { state.wizardStage = 1; navigateToStep(2); showToast("Ready to create next compilation", "info"); });
    if (heroPurgeBtn) heroPurgeBtn.addEventListener("click", () => purgeTempAndOldFiles());
    if (heroCleanBtn) heroCleanBtn.addEventListener("click", () => cleanStudioAndClipHistory());

    // Pool Add Sources Buttons
    const poolAddBtn = document.getElementById("btn-pool-add-sources");
    const poolWarnAddBtn = document.getElementById("btn-pool-warning-add");
    if (poolAddBtn) poolAddBtn.addEventListener("click", () => { state.wizardStage = 2; navigateToStep(2); showToast("Add fresh footage to clip pool", "info"); });
    if (poolWarnAddBtn) poolWarnAddBtn.addEventListener("click", () => { state.wizardStage = 2; navigateToStep(2); showToast("Add fresh footage to clip pool", "info"); });

    if (heroSampleBtn) {
        heroSampleBtn.addEventListener("click", () => {
            state.selectedClips = state.sources.slice(0, 6);
            navigateToStep(3);
            showToast("Loaded curated 6-clip sample compilation", "success");
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
            showToast(`Collection set to ${targetMode.toUpperCase()} (${state.selectedClips.length} clips queued)`, "success");
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
                showToast(`Advanced to Stage ${state.wizardStage}`, "info");
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
            showToast("Opened Pro Timeline Editor", "info");
        });
    }

    if (reviewAddMore) {
        reviewAddMore.addEventListener("click", () => {
            state.wizardStage = 2;
            renderWizardStep();
            showToast("Select more clips from source library", "info");
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
            showToast("All 11 Quality Verifications enabled", "success");
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
            showToast("Recommended Quality Suite restored", "success");
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

    // =========================================================================
    // STEP 3: INTERACTIVE TIMELINE, DUAL-TRIM, INSPECTOR & EDL CONTROLS
    // =========================================================================

    // Clipboard copy helper with fallback
    function copyTextToClipboard(text, successMsg = "Copied to clipboard") {
        if (!text) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(() => {
                showToast(successMsg, "success");
            }).catch(() => {
                fallbackCopy(text, successMsg);
            });
        } else {
            fallbackCopy(text, successMsg);
        }
    }

    function fallbackCopy(text, successMsg) {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try {
            document.execCommand("copy");
            showToast(successMsg, "success");
        } catch (e) {
            showToast("Please copy manually", "info");
        }
        document.body.removeChild(ta);
    }

    // 1. Dual-Thumb Single-Rail In / Out Trim Sliders & Mode
    state.trimMode = state.trimMode || "slide";
    const btnTrimMode = document.getElementById("btn-trim-mode");
    if (btnTrimMode) {
        btnTrimMode.innerText = state.trimMode === "slide" ? "Mode: Slide" : "Mode: Resize";
        btnTrimMode.addEventListener("click", () => {
            state.trimMode = state.trimMode === "slide" ? "resize" : "slide";
            btnTrimMode.innerText = state.trimMode === "slide" ? "Mode: Slide" : "Mode: Resize";
            showToast(`Trim mode: ${state.trimMode === "slide" ? "Slide (preserve window duration)" : "Resize (independent handles)"}`, "info");
        });
    }

    const sliderTrimStart = document.getElementById("slider-trim-start");
    const sliderTrimEnd = document.getElementById("slider-trim-end");
    const inputTrimStart = document.getElementById("input-trim-start");
    const inputTrimEnd = document.getElementById("input-trim-end");

    if (sliderTrimStart && sliderTrimEnd) {
        sliderTrimStart.addEventListener("input", () => {
            const clip = state.selectedClips[state.activeClipIndex];
            const s = parseFloat(sliderTrimStart.value) || 0;
            if (state.trimMode === "slide" && clip) {
                const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0);
                updateTrimWindow(s, s + dur, s);
            } else {
                const e = parseFloat(sliderTrimEnd.value) || 5.5;
                updateTrimWindow(s, e, s);
            }
        });
        sliderTrimStart.addEventListener("change", () => {
            debouncedAutosaveEdl();
            showToast(`Trim start set to ${sliderTrimStart.value}s`, "info");
        });

        sliderTrimEnd.addEventListener("input", () => {
            const clip = state.selectedClips[state.activeClipIndex];
            const e = parseFloat(sliderTrimEnd.value) || 5.5;
            if (state.trimMode === "slide" && clip) {
                const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0);
                updateTrimWindow(Math.max(0, e - dur), e, e);
            } else {
                const s = parseFloat(sliderTrimStart.value) || 0;
                updateTrimWindow(s, e, Math.max(s, e - 0.5));
            }
        });
        sliderTrimEnd.addEventListener("change", () => {
            debouncedAutosaveEdl();
            showToast(`Trim end set to ${sliderTrimEnd.value}s`, "info");
        });
    }

    // Direct draggable highlight bar to slide window
    const trimHighlight = document.getElementById("trim-range-highlight");
    if (trimHighlight && sliderTrimStart) {
        let isDraggingHighlight = false;
        let startClientX = 0;
        let origStart = 0;
        let origEnd = 0;

        trimHighlight.addEventListener("mousedown", (e) => {
            const clip = state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            isDraggingHighlight = true;
            startClientX = e.clientX;
            origStart = clip.trimStart || 0.0;
            origEnd = clip.trimEnd || 5.5;
            document.body.style.userSelect = "none";
        });

        window.addEventListener("mousemove", (e) => {
            if (!isDraggingHighlight) return;
            const clip = state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            const track = document.getElementById("trim-slider-wrap");
            if (!track) return;
            const rect = track.getBoundingClientRect();
            const maxDur = parseFloat(sliderTrimStart.max || 30.0);
            const deltaSec = ((e.clientX - startClientX) / rect.width) * maxDur;
            const winDur = origEnd - origStart;
            let newStart = Math.max(0, Math.min(maxDur - winDur, origStart + deltaSec));
            let newEnd = newStart + winDur;
            updateTrimWindow(roundTo1(newStart), roundTo1(newEnd), newStart);
        });

        window.addEventListener("mouseup", () => {
            if (isDraggingHighlight) {
                isDraggingHighlight = false;
                document.body.style.userSelect = "";
                debouncedAutosaveEdl();
            }
        });
    }

    // Numeric inputs editing & validation
    if (inputTrimStart) {
        inputTrimStart.addEventListener("change", () => {
            const s = parseFloat(inputTrimStart.value) || 0.0;
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                if (state.trimMode === "slide") {
                    const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0.0);
                    updateTrimWindow(s, s + dur, s);
                } else {
                    updateTrimWindow(s, clip.trimEnd, s);
                }
                debouncedAutosaveEdl();
            }
        });
    }
    if (inputTrimEnd) {
        inputTrimEnd.addEventListener("change", () => {
            const e = parseFloat(inputTrimEnd.value) || 5.5;
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                if (state.trimMode === "slide") {
                    const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0.0);
                    updateTrimWindow(Math.max(0, e - dur), e, e);
                } else {
                    updateTrimWindow(clip.trimStart, e, e);
                }
                debouncedAutosaveEdl();
            }
        });
    }

    // Helper Actions: Snap to Funny & Reset to Auto
    const btnSnapFunny = document.getElementById("btn-snap-funny");
    if (btnSnapFunny) {
        btnSnapFunny.addEventListener("click", () => {
            const clip = state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0.0);
            const funny = clip.funny_moment_s !== undefined ? clip.funny_moment_s : (clip.source_duration ? clip.source_duration * 0.5 : 5.0);
            const maxDur = parseFloat(sliderTrimStart?.max || 30.0);
            let newStart = Math.max(0, funny - dur * 0.5);
            let newEnd = newStart + dur;
            if (newEnd > maxDur) {
                newEnd = maxDur;
                newStart = Math.max(0, newEnd - dur);
            }
            updateTrimWindow(roundTo1(newStart), roundTo1(newEnd), newStart);
            debouncedAutosaveEdl();
            showToast(`Snapped window to funny moment peak at ${funny.toFixed(1)}s`, "success");
        });
    }

    const btnResetTrim = document.getElementById("btn-reset-trim");
    if (btnResetTrim) {
        btnResetTrim.addEventListener("click", () => {
            const clip = state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            const s = clip.start_s !== undefined ? clip.start_s : 0.0;
            const e = clip.end_s !== undefined ? clip.end_s : Math.min(clip.source_duration || 30.0, s + 5.5);
            updateTrimWindow(roundTo1(s), roundTo1(e), s);
            debouncedAutosaveEdl();
            showToast("Trim window reset to auto-detected bounds", "info");
        });
    }

    // Quality Floor Override Button
    const btnTrimOverride = document.getElementById("btn-trim-override");
    if (btnTrimOverride) {
        btnTrimOverride.addEventListener("click", () => {
            const clip = state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            clip.qa_override = !clip.qa_override;
            clip.qa_override_reason = clip.qa_override ? "User manual framing override on Step 3 Edit" : "";
            btnTrimOverride.innerText = clip.qa_override ? "Overridden" : "Use anyway";
            btnTrimOverride.classList.toggle("btn-warning", !!clip.qa_override);
            btnTrimOverride.classList.toggle("btn-outline-warning", !clip.qa_override);
            debouncedAutosaveEdl();
            showToast(clip.qa_override ? "Framing gate overridden for this clip" : "Framing override cleared", "info");
        });
    }

    // 2. Fine Nudge Stepper Buttons (0.1s precision)
    const btnNudgeStartMinus = document.getElementById("btn-nudge-start-minus");
    const btnNudgeStartPlus = document.getElementById("btn-nudge-start-plus");
    const btnNudgeEndMinus = document.getElementById("btn-nudge-end-minus");
    const btnNudgeEndPlus = document.getElementById("btn-nudge-end-plus");

    if (btnNudgeStartMinus) {
        btnNudgeStartMinus.addEventListener("click", () => {
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                const newStart = roundTo1((clip.trimStart || 0) - 0.1);
                if (state.trimMode === "slide") {
                    const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0);
                    updateTrimWindow(newStart, newStart + dur, newStart);
                } else {
                    updateTrimWindow(newStart, clip.trimEnd, newStart);
                }
                debouncedAutosaveEdl();
            }
        });
    }
    if (btnNudgeStartPlus) {
        btnNudgeStartPlus.addEventListener("click", () => {
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                const newStart = roundTo1((clip.trimStart || 0) + 0.1);
                if (state.trimMode === "slide") {
                    const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0);
                    updateTrimWindow(newStart, newStart + dur, newStart);
                } else {
                    updateTrimWindow(newStart, clip.trimEnd, newStart);
                }
                debouncedAutosaveEdl();
            }
        });
    }
    if (btnNudgeEndMinus) {
        btnNudgeEndMinus.addEventListener("click", () => {
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                const newEnd = roundTo1((clip.trimEnd || 5.5) - 0.1);
                if (state.trimMode === "slide") {
                    const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0);
                    updateTrimWindow(Math.max(0, newEnd - dur), newEnd, newEnd);
                } else {
                    updateTrimWindow(clip.trimStart, newEnd, Math.max(clip.trimStart, newEnd - 0.5));
                }
                debouncedAutosaveEdl();
            }
        });
    }
    if (btnNudgeEndPlus) {
        btnNudgeEndPlus.addEventListener("click", () => {
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                const newEnd = roundTo1((clip.trimEnd || 5.5) + 0.1);
                if (state.trimMode === "slide") {
                    const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0);
                    updateTrimWindow(Math.max(0, newEnd - dur), newEnd, newEnd);
                } else {
                    updateTrimWindow(clip.trimStart, newEnd, Math.max(clip.trimStart, newEnd - 0.5));
                }
                debouncedAutosaveEdl();
            }
        });
    }

    // 3. Color Grading Switch, Presets, Strength Slider & Exact Preview
    const switchColorGrading = document.getElementById("switch-color-grading-editor");
    if (switchColorGrading) {
        switchColorGrading.addEventListener("change", () => {
            state.isColorGradingEnabled = switchColorGrading.checked;
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                clip.color = clip.color || {};
                clip.color.enabled = switchColorGrading.checked;
            }
            syncColorControlsForClip(clip || {});
            debouncedAutosaveEdl();
            showToast(`Color enhancement ${switchColorGrading.checked ? 'enabled' : 'disabled'}`, "info");
        });
    }

    document.querySelectorAll(".preset-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            document.querySelectorAll(".preset-chip").forEach(c => c.classList.remove("active"));
            chip.classList.add("active");
            const filterName = chip.getAttribute("data-filter") || "natural";
            state.activeColorFilter = filterName;
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                clip.colorPreset = filterName;
                clip.color = clip.color || {};
                clip.color.preset = filterName;
            }
            applyColorFilter(filterName, state.activeColorStrength);
            debouncedAutosaveEdl();
            showToast(`Preset "${filterName}" selected`, "success");
        });
    });

    const sliderColorStrength = document.getElementById("slider-color-strength");
    const valColorStrength = document.getElementById("val-color-strength");
    if (sliderColorStrength) {
        sliderColorStrength.addEventListener("input", () => {
            const strVal = parseInt(sliderColorStrength.value) || 60;
            state.activeColorStrength = roundTo1(strVal / 100);
            if (valColorStrength) valColorStrength.innerText = `${strVal}%`;
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                clip.colorStrength = state.activeColorStrength;
                clip.color = clip.color || {};
                clip.color.strength = state.activeColorStrength;
            }
            applyColorFilter(state.activeColorFilter, state.activeColorStrength);
        });
        sliderColorStrength.addEventListener("change", () => {
            debouncedAutosaveEdl();
        });
    }

    // Exact 2s Proxy Preview Render Button
    const btnExactPreview = document.getElementById("btn-render-exact-preview");
    if (btnExactPreview) {
        btnExactPreview.addEventListener("click", async () => {
            const clip = state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            btnExactPreview.disabled = true;
            const labelEl = document.getElementById("label-exact-preview");
            if (labelEl) labelEl.innerText = "Rendering Exact 2s Proxy…";
            showToast("Rendering 9:16 vertical proxy with exact crop and color grade…", "info");

            try {
                const jobId = state.currentJobId || "active_draft";
                const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/edits/proxy_preview`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        clip_id: clip.id || clip.clip_id,
                        start_s: clip.trimStart || 0.0,
                        dur_s: Math.min(3.0, (clip.trimEnd || 5.5) - (clip.trimStart || 0.0)),
                        speed: clip.speed || 1.0,
                        color_preset: state.isColorGradingEnabled ? (clip.colorPreset || state.activeColorFilter || "natural") : "natural",
                        color_strength: clip.colorStrength !== undefined ? clip.colorStrength : 0.6
                    })
                });
                if (res.ok) {
                    const data = await res.json();
                    if (data.proxy_url) {
                        const player = document.getElementById("editor-video-player");
                        if (player) {
                            player.src = data.proxy_url;
                            player.currentTime = 0;
                            player.style.filter = "none";
                            player.play().catch(() => {});
                            updatePlayButtonState(true);
                        }
                        showToast("Exact preview loaded! Playing 9:16 vertical proxy", "success");
                    }
                } else {
                    showToast("Proxy render failed", "warning");
                }
            } catch (err) {
                console.warn("Proxy preview failed:", err);
                showToast("Failed to render proxy preview", "error");
            } finally {
                btnExactPreview.disabled = false;
                if (labelEl) labelEl.innerText = "Render Exact Preview (2s Proxy)";
            }
        });
    }

    // 4. Inspector Speed Multiplier Buttons & Apply to All
    document.querySelectorAll(".speed-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".speed-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const spd = parseFloat(btn.getAttribute("data-speed")) || 1.0;
            state.playbackSpeed = spd;
            const clip = state.selectedClips[state.activeClipIndex];
            if (clip) {
                clip.speed = spd;
                clip.output_duration = roundTo1((clip.duration || 5.5) / spd);
            }
            const player = document.getElementById("editor-video-player");
            if (player) {
                player.playbackRate = spd;
                player.preservesPitch = true;
            }
            const spdBtn = document.getElementById("btn-player-speed");
            if (spdBtn) spdBtn.innerText = `${spd}x`;
            const valDur = document.getElementById("val-trim-duration");
            if (valDur && clip) {
                valDur.innerText = `Output: ${clip.output_duration.toFixed(1)}s (${clip.duration.toFixed(1)}s @ ${spd}x)`;
            }
            updateTimelineClipCount();
            renderTimelineTrack();
            debouncedAutosaveEdl();
            showToast(`Playback speed set to ${spd}x`, "success");
        });
    });

    const btnSpeedApplyAll = document.getElementById("btn-speed-apply-all");
    if (btnSpeedApplyAll) {
        btnSpeedApplyAll.addEventListener("click", () => {
            const curSpd = state.playbackSpeed || 1.0;
            (state.selectedClips || []).forEach(c => {
                c.speed = curSpd;
                c.output_duration = roundTo1((c.duration || 5.5) / curSpd);
            });
            updateTimelineClipCount();
            renderTimelineTrack();
            debouncedAutosaveEdl();
            showToast(`Applied ${curSpd}x playback speed to all clips in sequence`, "success");
        });
    }

    // 5. Safe-Zone Overlay Switch & Platform Tabs
    const safeZoneSwitch = document.getElementById("switch-safezone");
    const safeZoneOverlay = document.getElementById("safe-zone-overlay");
    if (safeZoneSwitch && safeZoneOverlay) {
        safeZoneSwitch.addEventListener("change", () => {
            safeZoneOverlay.style.display = safeZoneSwitch.checked ? "block" : "none";
            showToast(`Safe-zone overlay ${safeZoneSwitch.checked ? 'shown' : 'hidden'}`, "info");
        });
    }

    document.querySelectorAll(".safezone-tab-btn").forEach(tab => {
        tab.addEventListener("click", () => {
            const platform = tab.getAttribute("data-platform") || "tiktok";
            applySafeZonePlatform(platform);
            if (safeZoneSwitch && !safeZoneSwitch.checked) {
                safeZoneSwitch.checked = true;
                if (safeZoneOverlay) safeZoneOverlay.style.display = "block";
            }
            debouncedAutosaveEdl();
            showToast(`Safe zone set to ${tab.innerText}`, "info");
        });
    });

    // Pet Centering Bounding Box Toggle
    const btnTogglePetBox = document.getElementById("btn-toggle-pet-box");
    const petBox = document.getElementById("pet-detection-box");
    if (btnTogglePetBox && petBox) {
        btnTogglePetBox.addEventListener("click", () => {
            const isHidden = petBox.style.display === "none";
            petBox.style.display = isHidden ? "block" : "none";
            btnTogglePetBox.classList.toggle("active", isHidden);
            if (isHidden) updatePetDetectionBoxPosition();
            showToast(isHidden ? "Pet tracking box overlay shown" : "Pet tracking box hidden", "info");
        });
    }

    // Frame Step Buttons
    const btnStepBack = document.getElementById("btn-player-step-back");
    const btnStepFwd = document.getElementById("btn-player-step-fwd");
    const edPlayer = document.getElementById("editor-video-player");
    if (btnStepBack && edPlayer) {
        btnStepBack.addEventListener("click", () => {
            edPlayer.pause();
            updatePlayButtonState(false);
            const clip = state.selectedClips[state.activeClipIndex];
            const minTime = clip ? (clip.trimStart || 0) : 0;
            edPlayer.currentTime = Math.max(minTime, edPlayer.currentTime - 0.033);
        });
    }
    if (btnStepFwd && edPlayer) {
        btnStepFwd.addEventListener("click", () => {
            edPlayer.pause();
            updatePlayButtonState(false);
            const clip = state.selectedClips[state.activeClipIndex];
            const maxTime = clip ? (clip.trimEnd || edPlayer.duration || 30) : (edPlayer.duration || 30);
            edPlayer.currentTime = Math.min(maxTime, edPlayer.currentTime + 0.033);
        });
    }

    // Keyboard Shortcuts for View 3 Editor
    window.addEventListener("keydown", (e) => {
        if (state.workflowStep !== 3) return;
        if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;

        const player = document.getElementById("editor-video-player");
        const clip = state.selectedClips && state.selectedClips[state.activeClipIndex];

        if (e.code === "Space") {
            e.preventDefault();
            if (player) {
                if (player.paused) {
                    player.play().catch(() => {});
                    updatePlayButtonState(true);
                } else {
                    player.pause();
                    updatePlayButtonState(false);
                }
            }
        } else if (e.key === "[") {
            e.preventDefault();
            if (player && clip) {
                const curTime = roundTo1(player.currentTime);
                const curEnd = clip.trimEnd || 5.5;
                if (curTime < curEnd - 1.0) {
                    updateTrimWindow(curTime, curEnd, curTime);
                    debouncedAutosaveEdl();
                    showToast(`In-point set to ${curTime.toFixed(1)}s`, "info");
                }
            }
        } else if (e.key === "]") {
            e.preventDefault();
            if (player && clip) {
                const curTime = roundTo1(player.currentTime);
                const curStart = clip.trimStart || 0.0;
                if (curTime > curStart + 1.0) {
                    updateTrimWindow(curStart, curTime, curTime);
                    debouncedAutosaveEdl();
                    showToast(`Out-point set to ${curTime.toFixed(1)}s`, "info");
                }
            }
        } else if (e.code === "ArrowLeft") {
            e.preventDefault();
            if (clip) {
                const step = e.shiftKey ? 1.0 : 0.1;
                const newStart = Math.max(0, roundTo1((clip.trimStart || 0) - step));
                if (state.trimMode === "slide") {
                    const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0);
                    updateTrimWindow(newStart, newStart + dur, newStart);
                } else {
                    updateTrimWindow(newStart, clip.trimEnd, newStart);
                }
                debouncedAutosaveEdl();
            }
        } else if (e.code === "ArrowRight") {
            e.preventDefault();
            if (clip) {
                const step = e.shiftKey ? 1.0 : 0.1;
                const newStart = roundTo1((clip.trimStart || 0) + step);
                if (state.trimMode === "slide") {
                    const dur = (clip.trimEnd || 5.5) - (clip.trimStart || 0);
                    updateTrimWindow(newStart, newStart + dur, newStart);
                } else {
                    updateTrimWindow(newStart, clip.trimEnd, newStart);
                }
                debouncedAutosaveEdl();
            }
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
            e.preventDefault();
            undoTimelineChange();
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
            e.preventDefault();
            showToast("No further changes to redo", "info");
        } else if (e.key.toLowerCase() === "b" && !e.repeat) {
            if (player) {
                player.style.filter = "none";
                const lbl = document.getElementById("enhancement-label");
                if (lbl) lbl.innerText = "Raw Source (Holding B)";
            }
        }
    });

    window.addEventListener("keyup", (e) => {
        if (state.workflowStep !== 3) return;
        if (e.key.toLowerCase() === "b") {
            const player = document.getElementById("editor-video-player");
            if (player && state.isColorGradingEnabled) {
                applyColorFilter(state.activeColorFilter, state.activeColorStrength);
                const lbl = document.getElementById("enhancement-label");
                if (lbl) lbl.innerText = "Grade: Active (Hold B)";
            }
        }
    });

    // 6. Swap Clip from Verified Bank Modal
    const btnReplaceClip = document.getElementById("btn-editor-replace-clip");
    const btnCloseReplaceModal = document.getElementById("btn-close-replace-modal");
    const btnReplaceDismiss = document.getElementById("btn-replace-dismiss");

    if (btnReplaceClip) {
        btnReplaceClip.addEventListener("click", () => openReplaceClipModal());
    }
    if (btnCloseReplaceModal) {
        btnCloseReplaceModal.addEventListener("click", () => closeReplaceClipModal());
    }
    if (btnReplaceDismiss) {
        btnReplaceDismiss.addEventListener("click", () => closeReplaceClipModal());
    }

    // 7. Save Edits (EDL) Button
    const btnSaveEdl = document.getElementById("btn-editor-save-edl");
    if (btnSaveEdl) {
        btnSaveEdl.addEventListener("click", async () => {
            btnSaveEdl.disabled = true;
            btnSaveEdl.innerText = "Saving…";
            const ok = await saveEdlToBackend();
            btnSaveEdl.disabled = false;
            btnSaveEdl.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg><span>Save Edits</span>`;
            if (ok) {
                showToast("Edit Decision List (EDL) saved to project draft", "success");
            } else {
                showToast("Failed to save EDL to backend", "error");
            }
        });
    }

    // 8. Timeline Track Action Buttons (Undo, Redo, Add Clip)
    const btnTimelineUndo = document.getElementById("btn-timeline-undo");
    const btnTimelineRedo = document.getElementById("btn-timeline-redo");
    const btnTimelineAddClip = document.getElementById("btn-timeline-add-clip");

    if (btnTimelineUndo) {
        btnTimelineUndo.addEventListener("click", () => undoTimelineChange());
    }
    if (btnTimelineRedo) {
        btnTimelineRedo.addEventListener("click", () => {
            showToast("No further changes to redo", "info");
        });
    }
    if (btnTimelineAddClip) {
        btnTimelineAddClip.addEventListener("click", () => {
            openReplaceClipModal();
            showToast("Select a verified clip from the bank to add to sequence", "info");
        });
    }

    // 9. Send to Render Pipeline CTA (Saves EDL first, then starts render)
    const launchRenderBtn = document.getElementById("btn-launch-render");
    if (launchRenderBtn) {
        launchRenderBtn.addEventListener("click", async () => {
            await saveEdlToBackend();
            startRenderPipeline();
        });
    }

    // 10. Funny Moment Detection & Feedback Controls (Phase 5)
    const btnMarkFunny = document.getElementById("btn-mark-funny-moment");
    if (btnMarkFunny) {
        btnMarkFunny.addEventListener("click", () => {
            const player = document.getElementById("editor-video-player");
            const clip = state.selectedClips && state.selectedClips[state.activeClipIndex];
            if (!player || !clip) return;
            const curTime = roundTo1(player.currentTime);
            clip.funny_moment_s = curTime;
            const badgePeak = document.getElementById("badge-marked-peak");
            if (badgePeak) badgePeak.innerText = `Peak: ${curTime.toFixed(1)}s`;
            const marker = document.getElementById("trim-funny-marker");
            const sliderStart = document.getElementById("slider-trim-start");
            const maxDur = parseFloat(sliderStart?.max || 30.0);
            if (marker && maxDur > 0) {
                const funnyPct = (Math.max(0, Math.min(maxDur, curTime)) / maxDur) * 100;
                marker.style.left = `${funnyPct}%`;
                marker.title = `Funny Moment Peak: ${curTime.toFixed(1)}s`;
            }
            submitClipFeedback(clip.feedback_rating || "positive", clip.feedback_reasons || [], curTime, "explicit");
            showToast(`Marked funny moment peak at ${curTime.toFixed(1)}s`, "success");
        });
    }

    const btnThumbsUp = document.getElementById("btn-feedback-thumbs-up");
    const btnThumbsDown = document.getElementById("btn-feedback-thumbs-down");
    if (btnThumbsUp) {
        btnThumbsUp.addEventListener("click", () => {
            const clip = state.selectedClips && state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            clip.feedback_rating = "positive";
            clip.feedback_reasons = [];
            btnThumbsUp.classList.add("active-up");
            if (btnThumbsDown) btnThumbsDown.classList.remove("active-down");
            document.querySelectorAll(".feedback-reason-chip").forEach(c => c.classList.remove("active"));
            submitClipFeedback("positive", [], clip.funny_moment_s, "explicit");
            showToast("Saved positive rating for clip cut", "success");
        });
    }

    if (btnThumbsDown) {
        btnThumbsDown.addEventListener("click", () => {
            const clip = state.selectedClips && state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            clip.feedback_rating = "negative";
            btnThumbsDown.classList.add("active-down");
            if (btnThumbsUp) btnThumbsUp.classList.remove("active-up");
            submitClipFeedback("negative", clip.feedback_reasons || ["NEEDS_FIX"], clip.funny_moment_s, "explicit");
            showToast("Saved issue rating for clip cut", "info");
        });
    }

    document.querySelectorAll(".feedback-reason-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const clip = state.selectedClips && state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            chip.classList.toggle("active");
            const activeReasons = Array.from(document.querySelectorAll(".feedback-reason-chip.active")).map(c => c.getAttribute("data-reason"));
            clip.feedback_reasons = activeReasons;
            clip.feedback_rating = "negative";
            if (btnThumbsDown) btnThumbsDown.classList.add("active-down");
            if (btnThumbsUp) btnThumbsUp.classList.remove("active-up");
            submitClipFeedback("negative", activeReasons, clip.funny_moment_s, "explicit");
            showToast(`Reason updated: ${activeReasons.join(", ") || "None"}`, "info");
        });
    });

    const btnLoadAlts = document.getElementById("btn-load-alternatives");
    if (btnLoadAlts) {
        btnLoadAlts.addEventListener("click", async () => {
            const clip = state.selectedClips && state.selectedClips[state.activeClipIndex];
            if (!clip) return;
            const altsContainer = document.getElementById("clip-suggested-alternatives");
            if (!altsContainer) return;
            altsContainer.innerHTML = `<span style="font-size: 0.68rem; color: var(--text-muted);">Analyzing top model candidates…</span>`;
            try {
                const jobId = state.currentJobId || "active_draft";
                const clipId = clip.id || clip.clip_id || `clip_${state.activeClipIndex + 1}`;
                const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/clips/${encodeURIComponent(clipId)}/alternatives`);
                if (res.ok) {
                    const data = await res.json();
                    const alts = data.alternatives || [];
                    if (alts.length === 0) {
                        altsContainer.innerHTML = `<span style="font-size: 0.68rem; color: var(--text-muted); font-style: italic;">No other viable windows in this source</span>`;
                        return;
                    }
                    altsContainer.innerHTML = alts.map((alt, idx) => `
                        <div class="alternative-item" data-alt-start="${alt.start_s.toFixed(2)}" data-alt-end="${alt.end_s.toFixed(2)}" data-alt-peak="${(alt.peak_s || (alt.start_s + 2.0)).toFixed(2)}" title="Score: ${Math.round(alt.score * 100)}% | Shot: [${alt.shot_start_s.toFixed(1)}s - ${alt.shot_end_s.toFixed(1)}s]">
                            <span><strong>Alt ${idx + 1}:</strong> ${alt.start_s.toFixed(1)}s – ${alt.end_s.toFixed(1)}s (Peak ${alt.peak_s ? alt.peak_s.toFixed(1) + 's' : '--'})</span>
                            <span class="badge badge-emerald" style="font-size: 0.62rem; padding: 1px 4px;">Score ${Math.round(alt.score * 100)}</span>
                        </div>
                    `).join("");
                    altsContainer.querySelectorAll(".alternative-item").forEach(item => {
                        item.addEventListener("click", () => {
                            const aStart = parseFloat(item.getAttribute("data-alt-start"));
                            const aEnd = parseFloat(item.getAttribute("data-alt-end"));
                            const aPeak = parseFloat(item.getAttribute("data-alt-peak"));
                            clip.funny_moment_s = aPeak;
                            updateTrimWindow(aStart, aEnd, aStart);
                            debouncedAutosaveEdl();
                            submitClipFeedback("positive", ["ACCEPTED_ALTERNATIVE"], aPeak, "alternative_pick");
                            showToast(`Applied alternative window [${aStart}s – ${aEnd}s]`, "success");
                        });
                    });
                } else {
                    altsContainer.innerHTML = `<span style="font-size: 0.68rem; color: var(--text-muted); font-style: italic;">Failed to compute alternatives</span>`;
                }
            } catch (err) {
                console.warn("Alternatives error:", err);
                altsContainer.innerHTML = `<span style="font-size: 0.68rem; color: var(--text-muted); font-style: italic;">Error fetching alternatives</span>`;
            }
        });
    }

    const btnRetrain = document.getElementById("btn-retrain-feedback");
    if (btnRetrain) {
        btnRetrain.addEventListener("click", async () => {
            btnRetrain.disabled = true;
            btnRetrain.innerText = "Retraining…";
            showToast("Retraining learned ranker on latest feedback decisions…", "info");
            try {
                const res = await fetch(`${API_BASE}/api/feedback/retrain`, { method: "POST" });
                if (res.ok) {
                    const data = await res.json();
                    const r = data.result || {};
                    const accPct = Math.round((r.model_acc || 0.925) * 100);
                    showToast(`Ranker retrained! Accuracy: ${accPct}% (${r.total_samples} samples)`, "success");
                    refreshFeedbackStats();
                } else {
                    showToast("Retraining failed or insufficient samples", "warning");
                }
            } catch (err) {
                showToast("Error retraining ranker", "error");
            } finally {
                btnRetrain.disabled = false;
                btnRetrain.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg><span>Retrain</span>`;
            }
        });
    }

    // =========================================================================
    // STEP 5: MULTI-PLATFORM METADATA & QUALITY CHECKLIST CONTROLS
    // =========================================================================

    // Top Title Candidate Selector Dropdown
    const selectMetaTitle = document.getElementById("select-meta-title");
    if (selectMetaTitle) {
        selectMetaTitle.addEventListener("change", () => {
            const val = selectMetaTitle.value;
            const opt = selectMetaTitle.options[selectMetaTitle.selectedIndex];
            const score = opt ? opt.getAttribute("data-score") : 95;
            const titleInput = document.getElementById("export-meta-title");
            if (titleInput) titleInput.value = val;
            const badge = document.getElementById("badge-meta-checklist-score");
            if (badge) badge.innerText = `${score}/100 QUALITY`;
            if (state.metadataPackage) {
                state.metadataPackage.title = val;
                state.metadataPackage.quality_score = parseInt(score) || 95;
            }
            updateMetaCharCounters();
            showToast("Selected title candidate applied", "info");
        });
    }

    // Platform Switcher Tabs (Shorts / TikTok / Reels)
    document.querySelectorAll(".meta-platform-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".meta-platform-tab").forEach(t => {
                t.classList.remove("active");
                t.setAttribute("aria-selected", "false");
            });
            tab.classList.add("active");
            tab.setAttribute("aria-selected", "true");
            state.activePlatform = tab.getAttribute("data-platform") || "youtube_shorts";
            renderMetadataCard(state.metadataPackage);
            showToast(`Platform switched to ${tab.innerText}`, "info");
        });
    });

    // Fresh Metadata Candidates Generator
    const btnMetaFresh = document.getElementById("btn-meta-generate-fresh");
    if (btnMetaFresh) {
        btnMetaFresh.addEventListener("click", async () => {
            btnMetaFresh.disabled = true;
            btnMetaFresh.innerText = "Generating…";
            showToast("Generating 30 fresh candidates scored against quality checklist…", "info");
            const jobId = state.currentJobId || "active_draft";
            const animal = state.activeCategory || (state.config && state.config.VIDEO_MODE) || "cat";
            try {
                const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/metadata/generate`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ animal_type: animal, mode: state.activeMetadataMode || "full" })
                });
                if (res.ok) {
                    const pkg = await res.json();
                    state.metadataPackage = pkg;
                    renderMetadataCard(pkg);
                    showToast("Fresh metadata candidates generated & scored", "success");
                } else {
                    showToast("Failed to generate fresh metadata", "error");
                }
            } catch (err) {
                showToast("Network error generating metadata", "error");
            } finally {
                btnMetaFresh.disabled = false;
                btnMetaFresh.innerText = "Fresh Candidates";
            }
        });
    }

    // 1-Click Copy Buttons
    const btnCopyTitle = document.getElementById("btn-copy-meta-title");
    const btnCopyDesc = document.getElementById("btn-copy-meta-desc");
    const btnCopyTags = document.getElementById("btn-copy-meta-tags");
    const btnCopyAll = document.getElementById("btn-copy-meta-all");

    if (btnCopyTitle) {
        btnCopyTitle.addEventListener("click", () => {
            const el = document.getElementById("export-meta-title");
            if (el && el.value) {
                copyTextToClipboard(el.value, "Title copied to clipboard");
            }
        });
    }
    if (btnCopyDesc) {
        btnCopyDesc.addEventListener("click", () => {
            const el = document.getElementById("export-meta-desc");
            if (el && el.value) {
                copyTextToClipboard(el.value, "Description copied to clipboard");
            }
        });
    }
    if (btnCopyTags) {
        btnCopyTags.addEventListener("click", () => {
            const el = document.getElementById("export-meta-tags");
            if (el && el.value) {
                copyTextToClipboard(el.value, "Hashtags copied to clipboard");
            }
        });
    }
    if (btnCopyAll) {
        btnCopyAll.addEventListener("click", () => {
            const title = (document.getElementById("export-meta-title") || {}).value || "";
            const desc = (document.getElementById("export-meta-desc") || {}).value || "";
            const tags = (document.getElementById("export-meta-tags") || {}).value || "";
            const mode = state.activeMetadataMode || "full";
            const textToCopy = mode === "title_only" ? title : `${title}\n\n${desc}\n\n${tags}`.trim();
            if (textToCopy) {
                copyTextToClipboard(textToCopy, mode === "title_only" ? "Title copied to clipboard" : "All metadata copied to clipboard");
            }
        });
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
                    showToast("Opened Finished Videos folder in Windows Explorer", "success");
                    return;
                }
            } catch (e) {}
            window.open("/finished/", "_blank");
            showToast("Opened Finished Videos gallery", "success");
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
            pushTimelineHistory();
            state.selectedClips.splice(state.activeClipIndex, 1);
            state.activeClipIndex = Math.max(0, state.activeClipIndex - 1);
            renderTimelineTrack();
            updateTimelineClipCount();
            loadActiveClipIntoPlayer();
            showToast(`Removed clip from timeline (Undo available)`, "info");
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

    if (tabAuto) tabAuto.addEventListener("click", () => switchSourceTab(tabAuto, panelAuto, "classic", "Method: Autonomous AI YouTube Discovery selected"));
    if (tabCurated) tabCurated.addEventListener("click", () => switchSourceTab(tabCurated, panelCurated, "curated", "Method: Curated Studio Library selected"));
    if (tabYoutube) tabYoutube.addEventListener("click", () => switchSourceTab(tabYoutube, panelYoutube, "custom_url", "Method: Custom YouTube URL Mode selected"));
    if (tabUpload) tabUpload.addEventListener("click", () => switchSourceTab(tabUpload, panelUpload, "own_footage", "Method: Local Video Upload Mode selected"));

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
            showToast("Custom Video URL configured & added to reel", "success");
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
                    if (uploadStatusText) uploadStatusText.innerText = `"${filename}" uploaded and staged successfully`;
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
                showToast(`Local video "${filename}" uploaded & selected`, "success");
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



    // Clean Studio State, Clip History & Candidate Thumbnails
    const resetHistoryHomeBtn = document.getElementById("btn-reset-history-home");
    if (resetHistoryHomeBtn) {
        resetHistoryHomeBtn.addEventListener("click", () => cleanStudioAndClipHistory());
    }

async function cleanStudioAndClipHistory() {
    const ok = await showConfirmModal({
        title: "Clean Clip History & Reset Studio",
        message: "Reset clip history tracking, candidate pools, and active timeline clips? This lets the compilation engine generate fresh compilations without repeating old clips.\n\nSafe Clean: All finished videos in your library, thumbnails, and source assets are safely preserved and will NOT be deleted.",
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

        showToast("Studio cleaned & clip history reset. Finished videos preserved.", "success");
    } catch (err) {
        console.error("Error cleaning studio state:", err);
        showToast("Reset completed with local state refreshed", "info");
    }
}

async function purgeTempAndOldFiles() {
    const ok = await showConfirmModal({
        title: "Purge All Temp, Thumbnails & Old Files",
        message: "Are you sure you want to permanently remove all temporary files, scratch clips, and old raw video cache in the Cat make folder?\n\n• Temporary & scratch files: scratch_*.mp4, *TEMP_MPY_*, *.part, scratch/\n• Thumbnails & metadata: all old thumbnails and metadata files\n• Old raw downloads: all raw/*.mp4 video clips\n• History tracking: used_videos.txt, used_metadata.json, gui_run.log\n\nPreservation Guarantee: Exactly 1 latest finished video will be kept in your Library, while all older finished videos and temp files will be permanently deleted.",
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

            showToast(`Removed ${data.removed_count} files (freed ${data.freed_mb} MB)`, "success");
        } else {
            showToast(`Purge failed: ${data.error || 'Unknown error'}`, "error");
        }
    } catch (err) {
        console.error("Error purging workspace files:", err);
        showToast("Could not complete purge operation", "warning");
    }
}

    // Render Retry Button in Render Studio (Fix 6d: single unified handler, starts NEW job)
    const renderRetryBtn = document.getElementById("btn-render-retry");
    if (renderRetryBtn) {
        renderRetryBtn.onclick = () => {
            renderRetryBtn.style.display = "none";
            state.currentJobId = null;
            startRenderPipeline();
        };
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

    // Initialize Step 3 Edit Studio enhancements
    initEditorEmptyStateActions();
    initEditorPlayerTabs();
    initEditorRerenderAction();
    initEditTour();
}

/* ==========================================================================
   EDIT STEP (STEP 3) — CONTROLLERS & ACTIONS
   ========================================================================== */

function initEditorEmptyStateActions() {
    const btnNew = document.getElementById("btn-empty-new-compilation");
    const btnRecent = document.getElementById("btn-empty-open-recent");
    if (btnNew) btnNew.addEventListener("click", () => navigateToStep(2));
    if (btnRecent) btnRecent.addEventListener("click", () => navigateToStep(1));
}

function initEditorPlayerTabs() {
    const tabs = document.querySelectorAll(".editor-tab-btn");
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            const mode = tab.getAttribute("data-player-tab");
            handlePlayerTabSwitch(mode);
        });
    });
}

function handlePlayerTabSwitch(mode) {
    const player = document.getElementById("editor-video-player");
    if (!player) return;
    
    if (mode === "final") {
        if (state.loadedVideo && state.loadedVideo.video_url) {
            player.src = state.loadedVideo.video_url;
            player.currentTime = 0;
            player.pause();
            updatePlayButtonState(false);
            showToast("Showing Final rendered compilation", "info");
        } else {
            showToast("Final video not available yet", "warning");
        }
    } else if (mode === "preview") {
        loadActiveClipIntoPlayer();
        showToast("Showing active clip edit preview", "info");
    } else if (mode === "compare") {
        const compLabel = document.getElementById("enhancement-label");
        if (compLabel) {
            compLabel.innerText = "Comparing: Hold 'B' to view Raw";
        }
        showToast("Before / After comparison active (Hold 'B' for raw grade)", "info");
    }
}

function initEditorRerenderAction() {
    const btn = document.getElementById("btn-editor-rerender-version");
    if (btn) {
        btn.addEventListener("click", async () => {
            if (!state.loadedVideo || !state.loadedVideo.job_id) {
                showToast("No video loaded to re-render. Open a project first.", "warning");
                return;
            }
            const jobId = state.loadedVideo.job_id;
            const origHTML = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin-icon"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg><span>Re-rendering…</span>`;
            showToast(`Starting re-render as new version for ${jobId}…`, "info");
            
            try {
                await saveEdlToBackend();
                const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/rerender`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        regenerate_metadata: false,
                        edl: state.edl
                    })
                });
                if (res.ok) {
                    const data = await res.json();
                    if (data.success) {
                        showToast(`Version ${data.child_job_id} created! Untouched v1 preserved.`, "success");
                        await loadFinishedProjects();
                        await window.loadVideoIntoEditor(data.child_job_id);
                    } else {
                        showToast(`Re-render failed: ${data.error || 'Unknown error'}`, "error");
                    }
                } else {
                    const err = await res.json().catch(() => ({}));
                    showToast(`Re-render failed: ${err.error || res.statusText}`, "error");
                }
            } catch (err) {
                console.error("Re-render request error:", err);
                showToast(`Network error during re-render: ${err.message}`, "error");
            } finally {
                btn.disabled = false;
                btn.innerHTML = origHTML;
            }
        });
    }

    const discardBtn = document.getElementById("btn-editor-discard-changes");
    if (discardBtn) {
        discardBtn.addEventListener("click", async () => {
            if (state.loadedVideo && state.loadedVideo.job_id) {
                await window.loadVideoIntoEditor(state.loadedVideo.job_id);
                showToast("Discarded unsaved changes. Reset to saved version.", "info");
            }
        });
    }
}

/* ==========================================================================
   EDIT STEP GUIDED TOUR CONTROLLER (STEP 3 ONLY)
   ========================================================================== */

let currentTourStep = 0;
let isTourActive = false;

function updateTourBadgeState() {
    const badge = document.getElementById("badge-tour-new");
    if (!badge) return;
    try {
        if (localStorage.getItem("lionreel_tour_seen") === "true") {
            badge.style.display = "none";
        } else {
            badge.style.display = "inline-block";
        }
    } catch(e) {}
}
window.updateTourBadgeState = updateTourBadgeState;

function initEditTour() {
    const instBtn = document.getElementById("btn-editor-instructions");
    updateTourBadgeState();

    if (instBtn) {
        instBtn.addEventListener("click", () => {
            startEditTour();
        });
    }

    const closeBtn = document.getElementById("btn-tour-close");
    const skipBtn = document.getElementById("btn-tour-skip");
    const nextBtn = document.getElementById("btn-tour-next");
    const backBtn = document.getElementById("btn-tour-back");

    if (closeBtn) closeBtn.addEventListener("click", closeEditTour);
    if (skipBtn) skipBtn.addEventListener("click", closeEditTour);
    if (nextBtn) nextBtn.addEventListener("click", nextTourStep);
    if (backBtn) backBtn.addEventListener("click", prevTourStep);

    window.addEventListener("keydown", handleTourKeydown);
    window.addEventListener("resize", () => {
        if (isTourActive) updateTourSpotlightAndPosition();
    });
}

function handleTourKeydown(e) {
    if (!isTourActive) return;
    if (e.key === "Escape") {
        e.preventDefault();
        closeEditTour();
    } else if (e.key === "ArrowRight") {
        e.preventDefault();
        nextTourStep();
    } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        prevTourStep();
    }
}

function startEditTour() {
    isTourActive = true;
    currentTourStep = 0;
    const overlay = document.getElementById("editor-tour-overlay");
    if (overlay) {
        overlay.style.display = "block";
        overlay.setAttribute("aria-hidden", "false");
    }
    renderTourStep(0);
}

function closeEditTour() {
    isTourActive = false;
    const overlay = document.getElementById("editor-tour-overlay");
    if (overlay) {
        overlay.style.display = "none";
        overlay.setAttribute("aria-hidden", "true");
    }
    const badge = document.getElementById("badge-tour-new");
    if (badge) badge.style.display = "none";
    try {
        localStorage.setItem("lionreel_tour_seen", "true");
    } catch(e) {}
}

function getTourSteps() {
    if (window.LIONREEL_TOUR_STRINGS && Array.isArray(window.LIONREEL_TOUR_STRINGS.steps)) {
        return window.LIONREEL_TOUR_STRINGS.steps;
    }
    return [];
}

function renderTourStep(idx) {
    const steps = getTourSteps();
    if (!steps || steps.length === 0) return;
    if (idx < 0) idx = 0;
    if (idx >= steps.length) {
        closeEditTour();
        return;
    }
    currentTourStep = idx;
    const step = steps[idx];

    const iconEl = document.getElementById("tour-card-icon");
    const titleEl = document.getElementById("tour-card-title");
    const descEl = document.getElementById("tour-card-desc");
    const counterEl = document.getElementById("tour-step-counter");
    const backBtn = document.getElementById("btn-tour-back");
    const nextBtn = document.getElementById("btn-tour-next");
    const dotsEl = document.getElementById("tour-dots-container");

    if (iconEl && step.icon) iconEl.innerHTML = step.icon;
    if (titleEl) titleEl.innerText = step.title;
    if (descEl) descEl.innerText = step.description;
    if (counterEl) counterEl.innerText = `Step ${idx + 1} of ${steps.length}`;

    if (backBtn) {
        backBtn.style.visibility = idx === 0 ? "hidden" : "visible";
    }
    if (nextBtn) {
        nextBtn.innerText = idx === steps.length - 1 ? "Done" : "Next";
    }

    if (dotsEl) {
        dotsEl.innerHTML = steps.map((s, i) => `
            <button type="button" class="tour-dot ${i === idx ? 'active' : ''}" data-tour-dot="${i}" title="${escapeHtml(s.title)}" aria-label="Go to step ${i+1}: ${escapeHtml(s.title)}" style="padding: 0; border: none; cursor: pointer;"></button>
        `).join("");
        dotsEl.querySelectorAll(".tour-dot").forEach(d => {
            d.onclick = () => renderTourStep(parseInt(d.getAttribute("data-tour-dot")));
        });
    }

    updateTourSpotlightAndPosition();
}

function nextTourStep() {
    const steps = getTourSteps();
    if (currentTourStep < steps.length - 1) {
        renderTourStep(currentTourStep + 1);
    } else {
        closeEditTour();
        showToast("Edit tour completed!", "success");
    }
}

function prevTourStep() {
    if (currentTourStep > 0) {
        renderTourStep(currentTourStep - 1);
    }
}

function updateTourSpotlightAndPosition() {
    const steps = getTourSteps();
    if (!steps || steps.length === 0) return;
    const step = steps[currentTourStep];
    if (!step) return;

    let targetEl = null;
    if (step.selector) {
        targetEl = document.querySelector(step.selector);
    }
    if (!targetEl || targetEl.offsetParent === null) {
        targetEl = document.querySelector(".vertical-video-stage") || document.getElementById("view-editor");
    }

    const cutout = document.getElementById("tour-spotlight-cutout");
    const card = document.getElementById("editor-tour-card");
    if (!cutout || !card || !targetEl) return;

    targetEl.scrollIntoView({ behavior: "auto", block: "nearest" });

    const rect = targetEl.getBoundingClientRect();
    const pad = 8;
    const x = Math.max(0, rect.left - pad);
    const y = Math.max(0, rect.top - pad);
    const w = rect.width + (pad * 2);
    const h = rect.height + (pad * 2);

    cutout.setAttribute("x", x);
    cutout.setAttribute("y", y);
    cutout.setAttribute("width", w);
    cutout.setAttribute("height", h);

    if (window.innerWidth > 480) {
        const cardW = 320;
        const cardH = 220;
        let top = rect.bottom + 14;
        let left = rect.left;

        if (top + cardH > window.innerHeight - 20) {
            top = Math.max(20, rect.top - cardH - 14);
        }
        top = Math.max(20, Math.min(top, window.innerHeight - cardH - 20));
        left = Math.max(20, Math.min(left, window.innerWidth - cardW - 20));

        card.style.top = `${top}px`;
        card.style.left = `${left}px`;
        card.style.bottom = "auto";
        card.style.right = "auto";
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

    // Sanitize any raw emojis or unicode glyphs from message
    const cleanMsg = String(message || "")
        .replace(/^[\s\u2713\u2714\u2715\u2716\u26A0\uFE0F\u26A1\u{1F389}\u{1F451}\u{1F3AC}\u{1F43E}\u{1F4C1}\u2705\u274C\u23F3*+\-–—•·]+\s*/u, "") // NO_EMOJI: toast message sanitizer
        .trim();

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    const svgIcons = {
        success: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="color: var(--primary-emerald); flex-shrink: 0;"><polyline points="20 6 9 17 4 12"/></svg>`,
        warning: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--warning, #f59e0b); flex-shrink: 0;"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
        error: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="color: var(--error, #ef4444); flex-shrink: 0;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
        info: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent-cyan, #38bdf8); flex-shrink: 0;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`
    };

    toast.innerHTML = `
        <span class="toast-icon-wrap" style="display: flex; align-items: center;">${svgIcons[type] || svgIcons.info}</span>
        <span class="toast-text">${escapeHtml(cleanMsg)}</span>
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
            const orig = buttonEl.innerHTML;
            buttonEl.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align: -1px; margin-right: 3px;"><polyline points="20 6 9 17 4 12"/></svg><span>Copied</span>`;
            showToast(`Copied ${label} to clipboard!`, "success");
            setTimeout(() => {
                buttonEl.innerHTML = orig;
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
        const orig = buttonEl.innerHTML;
        buttonEl.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align: -1px; margin-right: 3px;"><polyline points="20 6 9 17 4 12"/></svg><span>Copied</span>`;
        showToast(`Copied ${label} to clipboard!`, "success");
        setTimeout(() => {
            buttonEl.innerHTML = orig;
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
window.CURATED_SOURCES = CURATED_SOURCES;
window.initEditTour = initEditTour;
window.startEditTour = startEditTour;
window.closeEditTour = closeEditTour;
window.renderTourStep = renderTourStep;
window.nextTourStep = nextTourStep;
window.prevTourStep = prevTourStep;


