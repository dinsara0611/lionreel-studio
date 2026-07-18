// API Base URL (Local relative routing)
const API_BASE = "";

let isRunning = null;
let logOffset = 0;
let rawLogsHistory = "";
let logInterval = null;
let statusInterval = null;

// Single source of truth for pipeline UI state
let appState = {
    isRunning: false,
    progress: 0,
    phase: "Preparing"
};
let progressAnimInterval = null;

// Source description map
const SOURCE_DESCS = {
    "classic": "Searches YouTube for viral clips, downloads previews to verify, then fetches and merges high-quality formats.",
    "youtube_cc": "Searches for Creative Commons long videos, slices multiple moments, and burns credit watermarks to comply with licenses.",
    "own_footage": "Loads your own local long video (e.g., from own_footage folder) and splits it into multiple high-retention moments."
};

document.addEventListener("DOMContentLoaded", () => {
    initApp();
});

function initApp() {
    // Load config from server
    loadConfig();

    // Load finished file library
    loadFinishedFiles();

    // Polling status on load
    checkStatus();
    statusInterval = setInterval(checkStatus, 3000);

    // Event listeners
    document.getElementById("source-mode-select").addEventListener("change", (e) => {
        const val = e.target.value;
        document.getElementById("source-desc").innerText = SOURCE_DESCS[val] || "";
    });

    document.getElementById("btn-start").addEventListener("click", startGeneration);
    document.getElementById("btn-stop").addEventListener("click", stopGeneration);
    document.getElementById("btn-clear-logs").addEventListener("click", clearLogs);
    
    // Delete & Clear Buttons
    const btnClearFinished = document.getElementById("btn-clear-finished");
    if (btnClearFinished) btnClearFinished.addEventListener("click", clearFinishedFiles);
    
    const btnClearRaw = document.getElementById("btn-clear-raw");
    if (btnClearRaw) btnClearRaw.addEventListener("click", clearRawCache);
    
    // Create Desktop Shortcut Button
    const btnShortcut = document.getElementById("btn-create-shortcut");
    if (btnShortcut) {
        btnShortcut.addEventListener("click", createDesktopShortcut);
    }
    const hotkeyInput = document.getElementById("shortcut-hotkey");
    if (hotkeyInput) {
        hotkeyInput.addEventListener("input", (e) => {
            e.target.value = e.target.value.toUpperCase();
        });
    }

    // Close metadata modal on clicking outside the card
    const metaModal = document.getElementById("metadata-modal");
    if (metaModal) {
        metaModal.addEventListener("click", (e) => {
            if (e.target === e.currentTarget) {
                closeMetadataModal();
            }
        });
    }

    // Theme Toggle
    initTheme();
}

// ==========================================================================
// CONFIGURATION MANAGEMENT
// ==========================================================================
async function loadConfig() {
    try {
        const response = await fetch(`${API_BASE}/api/config`);
        const config = await response.json();
        
        // Select matching radio for VIDEO_MODE
        const modeRadio = document.querySelector(`input[name="VIDEO_MODE"][value="${config.VIDEO_MODE}"]`);
        if (modeRadio) modeRadio.checked = true;

        // Select matching SOURCE_MODE
        const sourceSelect = document.getElementById("source-mode-select");
        if (sourceSelect) {
            sourceSelect.value = config.SOURCE_MODE;
            document.getElementById("source-desc").innerText = SOURCE_DESCS[config.SOURCE_MODE] || "";
        }

        // Switches
        document.getElementById("bypass-quality").checked = !!config.BYPASS_QUALITY_GATE;
        document.getElementById("bypass-funny").checked = !!config.BYPASS_FUNNY_CHECK;

        // Number inputs
        document.getElementById("target-clips").value = config.TARGET_CLIPS;
        document.getElementById("clip-duration").value = config.SHORT_CLIP_SEC;

    } catch (e) {
        showToast("Error loading configuration settings.");
    }
}

function getFormConfig() {
    const modeRadio = document.querySelector('input[name="VIDEO_MODE"]:checked');
    const sourceSelect = document.getElementById("source-mode-select");
    
    return {
        "VIDEO_MODE": modeRadio ? modeRadio.value : "mix",
        "SOURCE_MODE": sourceSelect ? sourceSelect.value : "classic",
        "BYPASS_QUALITY_GATE": document.getElementById("bypass-quality").checked,
        "BYPASS_FUNNY_CHECK": document.getElementById("bypass-funny").checked,
        "TARGET_CLIPS": document.getElementById("target-clips").value,
        "SHORT_CLIP_SEC": document.getElementById("clip-duration").value
    };
}

// ==========================================================================
// GENERATION CONTROL
// ==========================================================================
async function startGeneration() {
    if (isRunning) {
        stopGeneration();
        return;
    }
    const config = getFormConfig();

    // 1. Save config first
    try {
        const saveRes = await fetch(`${API_BASE}/api/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(config)
        });
        const saveJson = await saveRes.json();
        if (!saveJson.success) {
            showToast("Failed to write config overrides.");
            return;
        }
    } catch (e) {
        showToast("Error saving configuration overrides.");
        return;
    }

    // 2. Launch python automation script
    try {
        const startRes = await fetch(`${API_BASE}/api/start`, { method: "POST" });
        const startJson = await startRes.json();
        
        if (startJson.success) {
            showToast("LionReel Automation started.");
            setUIState(true);
            clearLogs();
            logOffset = 0;
            
            // Poll logs rapidly
            if (logInterval) clearInterval(logInterval);
            logInterval = setInterval(pollLogs, 1500);
        } else {
            showToast(`Failed to start: ${startJson.message}`);
        }
    } catch (e) {
        showToast("Error triggering script process.");
    }
}

async function stopGeneration() {
    try {
        const stopRes = await fetch(`${API_BASE}/api/stop`, { method: "POST" });
        const stopJson = await stopRes.json();
        if (stopJson.success) {
            showToast("Generation process stopped.");
            setUIState(false);
            if (logInterval) clearInterval(logInterval);
            pollLogs(); // Final log fetch
            loadFinishedFiles(); // Reload list
        }
    } catch (e) {
        showToast("Error stopping script process.");
    }
}

// ==========================================================================
// LOGS & TERMINAL STREAMING
// ==========================================================================
async function pollLogs() {
    try {
        const res = await fetch(`${API_BASE}/api/logs?offset=${logOffset}`);
        const data = await res.json();
        
        if (data.logs && data.logs.trim() !== "") {
            appendLogs(data.logs);
            logOffset = data.offset;
            
            // Live quality checks status updates
            const logBody = document.getElementById("log-body");
            if (logBody) {
                updatePipelineWidget(rawLogsHistory);
                updateCompilationDashboard(rawLogsHistory);
                
                // Active video upload metadata parser
                const meta = parseMetadataFromLogs(rawLogsHistory);
                if (meta) {
                    showMetadataDashboard(meta);
                }
            }
        }
    } catch (e) {
        console.error("Log fetch error:", e);
    }
}

function appendLogs(text) {
    const logBody = document.getElementById("log-body");
    rawLogsHistory += text;
    
    const filteredText = filterProgressLogs(rawLogsHistory);
    
    // Highlight syntax keywords
    let html = filteredText
        .replace(/SUCCESS/g, '<span class="log-success">SUCCESS</span>')
        .replace(/ACCEPTED/g, '<span class="log-success">ACCEPTED</span>')
        .replace(/STABLE ✅/g, '<span class="log-success">STABLE ✅</span>')
        .replace(/SHARP ✅/g, '<span class="log-success">SHARP ✅</span>')
        .replace(/NATURAL ✅/g, '<span class="log-success">NATURAL ✅</span>')
        .replace(/CLEAN ✅/g, '<span class="log-success">CLEAN ✅</span>')
        .replace(/REAL ✅/g, '<span class="log-success">REAL ✅</span>')
        .replace(/ANIMAL ✅/g, '<span class="log-success">ANIMAL ✅</span>')
        
        .replace(/REJECTED/g, '<span class="log-error">REJECTED</span>')
        .replace(/SHAKY ❌/g, '<span class="log-error">SHAKY ❌</span>')
        .replace(/BLURRY ❌/g, '<span class="log-error">BLURRY ❌</span>')
        .replace(/WATERMARK ❌/g, '<span class="log-error">WATERMARK ❌</span>')
        .replace(/CGI ❌/g, '<span class="log-error">CGI ❌</span>')
        .replace(/FAKE ❌/g, '<span class="log-error">FAKE ❌</span>')
        
        .replace(/── V94 Quality Report ──/g, '<span class="log-header">── V94 Quality Report ──</span>')
        .replace(/ALL DONE/g, '<span class="log-header">ALL DONE</span>')
        .replace(/Title:/gi, '<span class="log-title">Title:</span>')
        .replace(/YouTube:/gi, '<span class="log-title">YouTube:</span>')
        .replace(/Social:/gi, '<span class="log-title">Social:</span>')
        
        .replace(/Check \d+/g, (m) => `<span class="log-check">${m}</span>`);

    logBody.innerHTML = html;
    
    // Auto Scroll bottom
    const container = document.querySelector(".terminal-container");
    container.scrollTop = container.scrollHeight;
}

function clearLogs() {
    rawLogsHistory = "";
    document.getElementById("log-body").innerHTML = "Console cleared. Awaiting new runs...";
    logOffset = 0;
    resetPipelineWidget();
}

// ==========================================================================
// STATUS & BACKGROUND RECOVERY
// ==========================================================================
async function checkStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/status`);
        const data = await res.json();
        
        const currentlyRunning = data.status === "running";
        
        if (currentlyRunning !== isRunning) {
            setUIState(currentlyRunning);
            if (currentlyRunning) {
                // Recover log polling
                if (logInterval) clearInterval(logInterval);
                logOffset = 0;
                const logBody = document.getElementById("log-body");
                if (logBody) logBody.innerHTML = "Recovering active generation console...";
                logInterval = setInterval(pollLogs, 1500);
            } else {
                // Generation finished
                if (logInterval) clearInterval(logInterval);
                pollLogs(); // fetch final remaining logs
                loadFinishedFiles(); // refresh list
                showToast("Job completed successfully.");
            }
        }
    } catch (e) {
        console.error("Status check failed:", e);
    }
}

function setUIState(running) {
    isRunning = running;
    appState.isRunning = running;
    
    if (!running) {
        appState.progress = 0;
        appState.phase = "Preparing";
        if (progressAnimInterval) {
            clearInterval(progressAnimInterval);
            progressAnimInterval = null;
        }
    }
    syncUIFromState();
}

function syncUIFromState() {
    const startBtn = document.getElementById("btn-start");
    const stopBtn = document.getElementById("btn-stop");
    const glow = document.getElementById("status-glow");
    const label = document.getElementById("status-label");
    const dashboard = document.getElementById("compilation-dashboard");
    const circle = document.getElementById("progress-ring-circle");
    const percentEl = document.getElementById("ring-percent");
    const phaseEl = document.getElementById("ring-phase");
    
    if (appState.isRunning) {
        if (startBtn) {
            startBtn.innerText = "Stop Process";
            startBtn.className = "btn btn-secondary";
            startBtn.style.color = "var(--clr-danger)";
            startBtn.style.borderColor = "rgba(239, 68, 68, 0.4)";
            startBtn.style.background = "rgba(239, 68, 68, 0.03)";
            startBtn.style.display = "block";
            startBtn.disabled = false;
        }
        if (stopBtn) {
            stopBtn.style.display = "none";
        }
        if (glow) {
            glow.className = "status-indicator running";
        }
        if (label) {
            label.innerText = "SYSTEM ACTIVE";
        }
        if (dashboard) {
            dashboard.style.display = "block";
        }
    } else {
        if (startBtn) {
            startBtn.innerText = "Run Generator";
            startBtn.className = "btn btn-primary";
            startBtn.style.color = "";
            startBtn.style.borderColor = "";
            startBtn.style.background = "";
            startBtn.style.display = "block";
            startBtn.disabled = false;
        }
        if (stopBtn) {
            stopBtn.style.display = "none";
        }
        if (glow) {
            glow.className = "status-indicator idle";
        }
        if (label) {
            label.innerText = "SYSTEM IDLE";
        }
        
        // Hide dashboard if manually stopped or if no successful run finished yet
        if (dashboard && !rawLogsHistory.includes("ALL DONE") && !rawLogsHistory.includes("Job completed")) {
            dashboard.style.display = "none";
        }
    }

    if (circle && percentEl) {
        const radius = circle.r.baseVal.value;
        const circumference = 2 * Math.PI * radius;
        const offset = circumference - (appState.progress / 100) * circumference;
        circle.style.strokeDashoffset = offset;
        percentEl.innerText = `${Math.floor(appState.progress)}%`;
    }
    if (phaseEl) {
        phaseEl.innerText = appState.phase;
    }

    const clearRawBtn = document.getElementById("btn-clear-raw");
    if (clearRawBtn) {
        clearRawBtn.disabled = appState.isRunning;
    }
}

function animateProgressTo(targetVal, phaseText) {
    appState.phase = phaseText || appState.phase;
    
    if (progressAnimInterval) clearInterval(progressAnimInterval);
    
    progressAnimInterval = setInterval(() => {
        if (!appState.isRunning) {
            appState.progress = 0;
            syncUIFromState();
            clearInterval(progressAnimInterval);
            progressAnimInterval = null;
            return;
        }
        
        if (appState.progress < targetVal) {
            const diff = targetVal - appState.progress;
            const step = diff > 10 ? 1 : 0.5;
            appState.progress += step;
            if (appState.progress > targetVal) appState.progress = targetVal;
            syncUIFromState();
        } else if (appState.progress > targetVal) {
            appState.progress -= 1.0;
            if (appState.progress < targetVal) appState.progress = targetVal;
            syncUIFromState();
        } else {
            clearInterval(progressAnimInterval);
            progressAnimInterval = null;
        }
    }, 30);
}

// ==========================================================================
// FINISHED COMPILATIONS LIBRARY
// ==========================================================================
async function loadFinishedFiles() {
    const listEl = document.getElementById("finished-files-list");
    
    try {
        const res = await fetch(`${API_BASE}/api/finished`);
        const data = await res.json();
        
        if (!data.files || data.files.length === 0) {
            listEl.innerHTML = '<li class="empty-list">No compilations rendered yet</li>';
            return;
        }

        listEl.innerHTML = "";
        data.files.forEach(file => {
            if (file.type !== "video") return; // Only show videos in list (metadata is loaded via Upload button!)
            
            const sizeMB = (file.sizeBytes / 1024 / 1024).toFixed(1);
            const typeText = "VIDEO";
            const typeClass = "badge-video";
            
            const li = document.createElement("li");
            li.className = "file-item";
            li.innerHTML = `
                <div class="file-info">
                    <span class="file-badge ${typeClass}">${typeText}</span>
                    <div class="file-details">
                        <span class="file-name" title="${file.name}">${file.name}</span>
                        <span class="file-size">${sizeMB} MB</span>
                    </div>
                </div>
                <div class="file-actions-menu">
                    <button type="button" class="btn-menu-trigger" aria-label="File Actions" onclick="toggleFileMenu(event, this)">
                        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="5" r="1.5"></circle>
                            <circle cx="12" cy="12" r="1.5"></circle>
                            <circle cx="12" cy="19" r="1.5"></circle>
                        </svg>
                    </button>
                    <div class="menu-dropdown">
                        <button type="button" class="menu-item-btn meta-btn" onclick="openMetadataPopup(event, '${file.name}')" style="color: var(--clr-primary);">
                            <svg class="menu-icon" viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                            Copy Metadata
                        </button>
                        <button type="button" class="menu-item-btn upload-btn" onclick="triggerUpload(event, '${file.name}', 'youtube')">
                            <svg class="menu-icon" viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"/><polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"/></svg>
                            Upload YouTube
                        </button>
                        <button type="button" class="menu-item-btn upload-btn" onclick="triggerUpload(event, '${file.name}', 'meta')">
                            <svg class="menu-icon" viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/></svg>
                            Upload Meta Reel
                        </button>
                        <button type="button" class="menu-item-btn upload-btn" onclick="triggerUpload(event, '${file.name}', 'tiktok')">
                            <svg class="menu-icon" viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><path d="M9 12a4 4 0 1 0 4 4V4a5 5 0 0 0 5 5"/></svg>
                            Upload TikTok
                        </button>
                        <a href="${API_BASE}/finished/${file.name}" download="${file.name}" class="menu-item-btn download-btn">
                            <svg class="menu-icon" viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
                            Download
                        </a>
                        <button type="button" class="menu-item-btn delete-btn" onclick="deleteFile('${file.name}')">
                            <svg class="menu-icon" viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                            Delete
                        </button>
                    </div>
                </div>
            `;
            listEl.appendChild(li);
        });
    } catch (e) {
        listEl.innerHTML = '<li class="empty-list error">Error loading file library</li>';
    }
}

// ==========================================================================
// TOAST NOTIFICATION
// ==========================================================================
function showToast(message) {
    const toast = document.getElementById("toast");
    toast.innerText = message;
    toast.className = "toast show";
    
    setTimeout(() => {
        toast.className = "toast";
    }, 3500);
}

// ==========================================================================
// FILE DELETE & CACHE CLEANING
// ==========================================================================
window.deleteFile = (filename) => {
    showConfirmModal(`Are you sure you want to delete ${filename}?`, async () => {
        try {
            const res = await fetch(`${API_BASE}/api/delete-file`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename })
            });
            const data = await res.json();
            if (data.success) {
                showToast("File deleted successfully.");
                loadFinishedFiles();
            }
        } catch (e) {
            showToast("Error deleting file.");
        }
    });
};

async function clearFinishedFiles() {
    showConfirmModal("Are you sure you want to delete ALL finished compilations? This cannot be undone.", async () => {
        try {
            const res = await fetch(`${API_BASE}/api/clear-finished`, { method: "POST" });
            const data = await res.json();
            if (data.success) {
                showToast("All finished files deleted.");
                loadFinishedFiles();
            }
        } catch (e) {
            showToast("Error clearing library.");
        }
    });
}

async function clearRawCache() {
    showConfirmModal("Are you sure you want to clear the raw download cache? (This will delete temporary video streams to free up space)", async () => {
        try {
            const res = await fetch(`${API_BASE}/api/clear-raw`, { method: "POST" });
            const data = await res.json();
            if (data.success) {
                showToast("Raw download cache cleared.");
            }
        } catch (e) {
            showToast("Error clearing raw cache.");
        }
    });
}

// ==========================================================================
// DESKTOP SHORTCUT CREATION
// ==========================================================================
async function createDesktopShortcut() {
    const hotkeyInput = document.getElementById("shortcut-hotkey");
    const hotkey = hotkeyInput ? hotkeyInput.value.trim() : "CTRL+ALT+L";
    
    const btn = document.getElementById("btn-create-shortcut");
    if (btn) {
        btn.disabled = true;
        btn.innerText = "Creating...";
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/create-shortcut`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hotkey })
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message || "Desktop shortcut created successfully!");
        } else {
            showToast("Failed to create shortcut: " + (data.error || "Unknown error"));
        }
    } catch (e) {
        showToast("Error creating desktop shortcut.");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = "Create Shortcut";
        }
    }
}

// ==========================================================================
// LIGHT & DARK THEME MANAGEMENT
// ==========================================================================
function initTheme() {
    const themeBtn = document.getElementById("btn-theme-toggle");
    const currentTheme = localStorage.getItem("theme") || "dark"; // Default theme is Dark (Enterprise look)
    const isDark = currentTheme === "dark";
    
    if (isDark) {
        document.body.classList.add("dark-mode");
    }
    updateThemeUI(isDark);
    
    if (themeBtn) {
        themeBtn.addEventListener("click", () => {
            document.body.classList.toggle("dark-mode");
            const isCurrentlyDark = document.body.classList.contains("dark-mode");
            localStorage.setItem("theme", isCurrentlyDark ? "dark" : "light");
            updateThemeUI(isCurrentlyDark);
            showToast(`Theme switched to ${isCurrentlyDark ? 'Dark' : 'Light'} Mode.`);
        });
    }
}

function updateThemeUI(isDark) {
    const sunIcon = document.querySelector(".sun-icon");
    const moonIcon = document.querySelector(".moon-icon");
    if (sunIcon && moonIcon) {
        if (isDark) {
            // Dark Mode active -> Show Sun (click to go Light)
            sunIcon.style.display = "block";
            moonIcon.style.display = "none";
        } else {
            // Light Mode active -> Show Moon (click to go Dark)
            sunIcon.style.display = "none";
            moonIcon.style.display = "block";
        }
    }
}

// ==========================================================================
// METADATA COPY & WIDGET MANIPULATIONS
// ==========================================================================
window.copyMetaText = (elementId) => {
    const textarea = document.getElementById(elementId);
    if (textarea) {
        textarea.select();
        textarea.setSelectionRange(0, 99999);
        
        try {
            navigator.clipboard.writeText(textarea.value);
            showToast("Copied to clipboard!");
        } catch (err) {
            document.execCommand("copy");
            showToast("Copied to clipboard!");
        }
    }
};

function resetPipelineWidget() {
    const checkKeys = ["sharpness", "shake", "music", "watermark", "colorGrade", "smartCrop"];
    checkKeys.forEach(key => {
        const el = document.getElementById(`check-${key}`);
        if (el) {
            el.className = "check-item";
            el.querySelector(".check-status").innerText = "Pending";
        }
    });
    const layerKeys = ["fetch", "quality", "effects", "audio", "render"];
    layerKeys.forEach(key => {
        const el = document.getElementById(`layer-${key}`);
        if (el) {
            el.className = "layer-item";
            el.querySelector(".layer-status").innerText = "Pending";
        }
    });
    const metaDashboard = document.getElementById("metadata-dashboard");
    if (metaDashboard) metaDashboard.style.display = "none";
}

function updatePipelineWidget(logText) {
    const items = {
        sharpness: { 
            pass: /FIX 1\s*✅|Sharpness check.*Passed/i, 
            fail: /FIX 1\s*❌|REJECTED — blurry/i, 
            active: /Checking sharpness|Check 1/i 
        },
        shake: { 
            pass: /FIX 2\s*✅|Shake detector.*Passed/i, 
            fail: /FIX 2\s*❌|REJECTED — shaky/i, 
            active: /Checking shake|Check 2/i 
        },
        music: { 
            pass: /FIX 3\s*✅|Music detector.*Passed/i, 
            fail: /FIX 3\s*❌|REJECTED — background music/i, 
            active: /Checking music|Check 3/i 
        },
        watermark: { 
            pass: /FIX 4\s*✅|Watermark detector.*Passed/i, 
            fail: /FIX 4\s*❌|REJECTED — watermark/i, 
            active: /Checking watermark|Check 4/i 
        },
        colorGrade: { 
            pass: /FIX 5\s*✅|Applying color grade.*Done/i, 
            active: /Applying color grade/i 
        },
        smartCrop: { 
            pass: /FIX 6\s*✅|Applying smart crop.*Done/i, 
            active: /Applying smart crop/i 
        }
    };
    
    const lines = logText.split("\n");
    
    for (const [key, patterns] of Object.entries(items)) {
        const el = document.getElementById(`check-${key}`);
        if (!el) continue;
        
        let status = "Pending";
        let className = "check-item";
        
        for (let i = lines.length - 1; i >= 0; i--) {
            const line = lines[i];
            if (patterns.fail && patterns.fail.test(line)) {
                status = "Failed";
                className = "check-item failed";
                break;
            } else if (patterns.pass.test(line)) {
                status = "Verified";
                className = "check-item passed";
                break;
            } else if (patterns.active.test(line)) {
                status = "Checking...";
                className = "check-item active";
                break;
            }
        }
        
        el.className = className;
        el.querySelector(".check-status").innerText = status;
    }
}

function parseMetadataFromLogs(logText) {
    if (!logText) return null;
    
    const hasMarker = />>>\s*(Title|YouTube|Social|Upload):/i.test(logText);
    if (!hasMarker) return null;
    
    try {
        const text = logText.replace(/\r\n/g, "\n");
        
        let title = "";
        let youtube = "";
        let social = "";
        let uploadLinks = {};
        
        const titleMatch = text.match(/>>>\s*TITLE:\n?([\s\S]*?)(?=\n?>>>|\n?════)/i);
        if (titleMatch) title = titleMatch[1].trim();
        
        const ytMatch = text.match(/>>>\s*(?:YOUTUBE|YT):\n?([\s\S]*?)(?=\n?>>>|\n?════)/i);
        if (ytMatch) youtube = ytMatch[1].trim();
        
        const socialMatch = text.match(/>>>\s*SOCIAL:\n?([\s\S]*?)(?=\n?>>>|\n?UPLOAD)/i);
        if (socialMatch) social = socialMatch[1].trim();
        
        const youtubeUrlMatch = text.match(/YouTube\s*:\s*(https?:\/\/[^\s]+)/i);
        const tiktokUrlMatch = text.match(/TikTok\s*:\s*(https?:\/\/[^\s]+)/i);
        const instagramUrlMatch = text.match(/Instagram\s*:\s*(https?:\/\/[^\s]+)/i);
        const facebookUrlMatch = text.match(/Facebook\s*:\s*(https?:\/\/[^\s]+)/i);
        
        if (youtubeUrlMatch) uploadLinks.youtube = youtubeUrlMatch[1].trim();
        if (tiktokUrlMatch) uploadLinks.tiktok = tiktokUrlMatch[1].trim();
        if (instagramUrlMatch) uploadLinks.instagram = instagramUrlMatch[1].trim();
        if (facebookUrlMatch) uploadLinks.facebook = facebookUrlMatch[1].trim();
        
        let videoName = "";
        const vidMatch = text.match(/VIDEO\s*:\s*([^\s]+)/i);
        if (vidMatch) videoName = vidMatch[1].trim();
        
        if (title || youtube || social || Object.keys(uploadLinks).length > 0) {
            return { videoName, title, youtube, social, uploadLinks };
        }
    } catch (e) {
        console.error("Failed to parse metadata:", e);
    }
    return null;
}

function showMetadataDashboard(meta) {
    const metaDashboard = document.getElementById("metadata-dashboard");
    if (!metaDashboard) return;
    
    document.getElementById("meta-vid-name").innerText = meta.videoName || "lion_video.mp4";
    document.getElementById("meta-title").value = meta.title || "";
    document.getElementById("meta-yt").value = meta.youtube || "";
    document.getElementById("meta-social").value = meta.social || "";

    // Extract YouTube tags (Keywords) from description
    let tags = "";
    if (meta.youtube) {
        const tagsMatch = meta.youtube.match(/Tags:\s*([\s\S]+)$/i);
        if (tagsMatch) {
            tags = tagsMatch[1].trim();
        }
    }
    document.getElementById("meta-tags").value = tags;

    // Extract hashtags from social caption
    let hashtags = "";
    if (meta.social) {
        const hashtagsMatch = meta.social.match(/(#[a-zA-Z0-9_]+\s*)+/g);
        if (hashtagsMatch) {
            hashtags = hashtagsMatch.join(" ").trim();
        }
    }
    document.getElementById("meta-hashtags").value = hashtags;
    
    const links = {
        yt: { id: "link-upload-yt", default: "https://studio.youtube.com/channel/UCK6vJnSBp-6XWlVKjePzr4w" },
        tt: { id: "link-upload-tt", default: "https://www.tiktok.com/tiktokstudio/upload?from=creator_center&tab=video" },
        meta: { id: "link-upload-meta", default: "https://business.facebook.com/latest/reels_composer/?asset_id=960315347156294&business_id=25484170311269841&ir_qe_exposed=1&ref=biz_web_home_create_reel&context_ref=HOME" }
    };
    
    document.getElementById("link-upload-yt").href = meta.uploadLinks.youtube || links.yt.default;
    document.getElementById("link-upload-tt").href = meta.uploadLinks.tiktok || links.tt.default;
    document.getElementById("link-upload-meta").href = meta.uploadLinks.facebook || meta.uploadLinks.instagram || links.meta.default;
    
    metaDashboard.style.display = "flex";
}

window.loadMetadataForVideo = async (filename) => {
    try {
        const metaName = filename
            .replace("lion_dog_", "lion_metadata_dog_")
            .replace("lion_cat_", "lion_metadata_cat_")
            .replace("lion_mix_", "lion_metadata_mix_")
            .replace(".mp4", ".txt");
            
        const res = await fetch(`${API_BASE}/finished/${metaName}`);
        if (!res.ok) {
            showToast("Metadata file not found for this video.");
            return;
        }
        const text = await res.text();
        const meta = parseMetadataFromLogs(text);
        if (meta) {
            meta.videoName = filename;
            showMetadataDashboard(meta);
            showToast("Metadata loaded into upload card.");
            
            // Scroll to the metadata dashboard
            const card = document.getElementById("metadata-dashboard");
            if (card) {
                card.scrollIntoView({ behavior: "smooth" });
            }
        } else {
            showToast("Failed to parse metadata file.");
        }
    } catch (e) {
        showToast("Error loading metadata.");
    }
};

function showConfirmModal(message, onConfirm) {
    const modal = document.getElementById("confirm-modal");
    const msgEl = document.getElementById("modal-message");
    const confirmBtn = document.getElementById("modal-btn-confirm");
    const cancelBtn = document.getElementById("modal-btn-cancel");
    
    if (modal && msgEl && confirmBtn && cancelBtn) {
        msgEl.innerText = message;
        modal.style.display = "flex";
        
        confirmBtn.onclick = () => {
            modal.style.display = "none";
            onConfirm();
        };
        
        cancelBtn.onclick = () => {
            modal.style.display = "none";
        };
    }
}

// ==========================================================================
// 3-DOT MENU TRIGGERS
// ==========================================================================
window.toggleFileMenu = (event, btn) => {
    event.stopPropagation();
    const menuContainer = btn.parentElement;
    
    // Close all other open menus
    document.querySelectorAll(".file-actions-menu.open").forEach(openMenu => {
        if (openMenu !== menuContainer) {
            openMenu.classList.remove("open");
        }
    });
    
    // Toggle current menu
    menuContainer.classList.toggle("open");
};

// Global click handler to close menus when clicking outside
document.addEventListener("click", () => {
    document.querySelectorAll(".file-actions-menu.open").forEach(openMenu => {
        openMenu.classList.remove("open");
    });
});

// Helper function to load metadata and open social media upload page
window.triggerUpload = async (event, filename, platform) => {
    if (event) event.stopPropagation();
    
    // Close all open menus
    document.querySelectorAll(".file-actions-menu.open").forEach(openMenu => {
        openMenu.classList.remove("open");
    });
    
    // 1. Open the copy metadata popup screen
    await window.openMetadataPopup(null, filename);
    
    // 2. Open the corresponding upload page in a new tab
    const uploadUrls = {
        youtube: "https://studio.youtube.com/channel/UCK6vJnSBp-6XWlVKjePzr4w",
        meta: "https://business.facebook.com/latest/reels_composer/?asset_id=960315347156294&business_id=25484170311269841&ir_qe_exposed=1&ref=biz_web_home_create_reel&context_ref=HOME",
        tiktok: "https://www.tiktok.com/tiktokstudio/upload?from=creator_center&tab=video"
    };
    
    const url = uploadUrls[platform];
    if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
    }
};

// Helper function to open metadata modal popup
window.openMetadataPopup = async (event, filename) => {
    if (event) event.stopPropagation();
    
    // Close dropdowns
    document.querySelectorAll(".file-actions-menu.open").forEach(openMenu => {
        openMenu.classList.remove("open");
    });
    
    // Clear and show loading state
    document.getElementById("popup-meta-vid-name").innerText = filename;
    document.getElementById("popup-meta-title").value = "Loading title...";
    document.getElementById("popup-meta-tags").value = "Loading tags...";
    document.getElementById("popup-meta-hashtags").value = "Loading hashtags...";
    
    // Open modal
    const modal = document.getElementById("metadata-modal");
    if (modal) modal.style.display = "flex";
    
    // Load metadata
    try {
        const metaName = filename
            .replace("lion_dog_", "lion_metadata_dog_")
            .replace("lion_cat_", "lion_metadata_cat_")
            .replace("lion_mix_", "lion_metadata_mix_")
            .replace(".mp4", ".txt");
            
        const res = await fetch(`${API_BASE}/finished/${metaName}`);
        if (!res.ok) {
            showToast("Metadata file not found.");
            closeMetadataModal();
            return;
        }
        const text = await res.text();
        const meta = parseMetadataFromLogs(text);
        if (meta) {
            document.getElementById("popup-meta-title").value = meta.title || "";
            
            // Extract tags
            let tags = "";
            if (meta.youtube) {
                const tagsMatch = meta.youtube.match(/Tags:\s*([\s\S]+)$/i);
                if (tagsMatch) tags = tagsMatch[1].trim();
            }
            document.getElementById("popup-meta-tags").value = tags;
            
            // Extract hashtags
            let hashtags = "";
            if (meta.social) {
                const hashtagsMatch = meta.social.match(/(#[a-zA-Z0-9_]+\s*)+/g);
                if (hashtagsMatch) hashtags = hashtagsMatch.join(" ").trim();
            }
            document.getElementById("popup-meta-hashtags").value = hashtags;
        } else {
            showToast("Failed to parse metadata file.");
        }
    } catch (e) {
        showToast("Error loading metadata.");
    }
};

window.closeMetadataModal = () => {
    const modal = document.getElementById("metadata-modal");
    if (modal) modal.style.display = "none";
};

// ==========================================================================
// TQDM LOG PARSING & VISUAL PROGRESS PIPELINE HELPERS
// ==========================================================================
function filterProgressLogs(logText) {
    const lines = logText.split(/\r?\n/);
    const cleanedLines = [];
    let lastTLine = null;
    let lastChunkLine = null;
    
    for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith("t:") && trimmed.includes("%|")) {
            lastTLine = line;
        } else if (trimmed.startsWith("chunk:") && trimmed.includes("%|")) {
            lastChunkLine = line;
        } else {
            cleanedLines.push(line);
        }
    }
    
    if (lastChunkLine) {
        cleanedLines.push(lastChunkLine);
    }
    if (lastTLine) {
        cleanedLines.push(lastTLine);
    }
    
    return cleanedLines.join("\n");
}

function updateCompilationDashboard(logText) {
    const dashboard = document.getElementById("compilation-dashboard");
    if (!dashboard) return;
    
    // Parse progress bar info
    const chunkMatch = logText.match(/chunk:\s*(\d+)%\s*\|.*?\|\s*(\d+)\/(\d+)\s*\[(.*?)(?:<(.*?))?,\s*([^,\]]+)/i);
    const frameMatch = logText.match(/t:\s*(\d+)%\s*\|.*?\|\s*(\d+)\/(\d+)\s*\[(.*?)(?:<(.*?))?,\s*([^,\]]+)/i);
    
    let activePercent = 0;
    let activePhase = "Preparing";
    let activeVideoName = "lion_video.mp4";
    let eta = "--:--";
    let speed = "-- it/s";
    let progressText = "0/0";
    
    // Parse video filename
    const vidMatch = logText.match(/Rendering\s+\d+\s+clips\s+to:\s*([^\s]+)/i);
    if (vidMatch) {
        activeVideoName = vidMatch[1].split(/[\\/]/).pop();
    } else {
        const activeVidMatch = logText.match(/VIDEO\s*:\s*([^\s]+)/i);
        if (activeVidMatch) activeVideoName = activeVidMatch[1].trim();
    }
    
    let isRenderingVideo = false;
    let isRenderingAudio = false;
    
    if (frameMatch) {
        activePercent = parseInt(frameMatch[1], 10);
        progressText = `${frameMatch[2]}/${frameMatch[3]}`;
        eta = frameMatch[5] || "--:--";
        speed = frameMatch[6] || "-- it/s";
        activePhase = "Rendering Video Frames";
        isRenderingVideo = true;
    } else if (chunkMatch) {
        activePercent = parseInt(chunkMatch[1], 10);
        progressText = `${chunkMatch[2]}/${chunkMatch[3]}`;
        eta = chunkMatch[5] || "--:--";
        speed = chunkMatch[6] || "-- it/s";
        activePhase = "Processing Audio Layers";
        isRenderingAudio = true;
    } else {
        // Fallback progress estimation if not rendering frames yet
        if (logText.includes("Auto white-balance")) {
            activePercent = 80;
            activePhase = "Applying Enhancements";
        } else if (logText.includes("[MultiMoment]")) {
            activePercent = 60;
            activePhase = "Extracting Clips";
        } else if (logText.includes("Running V93 checks")) {
            activePercent = 40;
            activePhase = "Quality Gate Checks";
        } else if (logText.includes("Searching YouTube")) {
            activePercent = 20;
            activePhase = "Downloading Footage";
        }
    }
    
    const vidEl = document.getElementById("compilation-active-video");
    if (vidEl) {
        vidEl.innerText = isRunning ? `Active Pipeline: ${activeVideoName}` : "Idle";
    }
    
    // Set target progress & phase dynamically (animates smoothly)
    animateProgressTo(activePercent, activePhase);
    
    const etaEl = document.getElementById("compilation-eta");
    const speedEl = document.getElementById("compilation-speed");
    const framesEl = document.getElementById("compilation-frames");
    if (etaEl) etaEl.innerText = eta;
    if (speedEl) speedEl.innerText = speed;
    if (framesEl) framesEl.innerText = progressText;
    
    // Update layers
    updateLayer("layer-fetch", 
        logText.includes("TOP CANDIDATES:") || logText.includes("Running V93 checks"), 
        logText.includes("Searching YouTube") || logText.includes("Downloading preview")
    );
    updateLayer("layer-quality", 
        logText.includes("Preview passed all checks!"), 
        logText.includes("Running V93 checks") || logText.includes("[Sharpness]")
    );
    updateLayer("layer-effects", 
        logText.includes("SUCCESS ✅ — Extracted") || logText.includes("MoviePy - Writing audio"), 
        logText.includes("[MultiMoment]") || logText.includes("[ColourGrade]")
    );
    updateLayer("layer-audio", 
        logText.includes("MoviePy - Done.") || logText.includes("Moviepy - Writing video"), 
        isRenderingAudio || logText.includes("Writing audio")
    );
    updateLayer("layer-render", 
        logText.includes("ALL DONE") || logText.includes("=== Generation Finished ===") || (!isRunning && logText.includes("finished")), 
        isRenderingVideo || logText.includes("Writing video")
    );
}

function updateLayer(id, isPassed, isActive) {
    const el = document.getElementById(id);
    if (!el) return;
    
    const statusEl = el.querySelector(".layer-status");
    if (isPassed) {
        el.className = "layer-item passed";
        statusEl.innerText = "Completed";
    } else if (isActive) {
        el.className = "layer-item active";
        statusEl.innerText = "Processing...";
    } else {
        el.className = "layer-item";
        statusEl.innerText = "Pending";
    }
}
