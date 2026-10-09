const { chromium } = require("C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test");
const fs = require("fs");
const path = require("path");

async function run() {
    const outDir = path.resolve(__dirname, "../analysis/change1");
    if (!fs.existsSync(outDir)) {
        fs.mkdirSync(outDir, { recursive: true });
    }

    console.log("=== Testing CHANGE 1: Summary Bar ===");
    const browser = await chromium.launch({
        channel: "chrome",
        headless: true
    });

    // 1. Desktop context
    const context = await browser.newContext({
        viewport: { width: 1440, height: 900 }
    });
    const page = await context.newPage();

    await page.goto("http://localhost:8000/#step2", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(500);

    // Make sure we are in Dark theme first
    await page.evaluate(() => {
        document.documentElement.setAttribute("data-theme", "dark");
        localStorage.setItem("lionreel_theme", "dark");
    });

    console.log("-> Transitioning to wizard-step-3 (Sources compilation parameters)...");
    // Switch to wizard stage 3
    await page.evaluate(() => {
        state.wizardStage = 3;
        renderWizardStep();
    });

    // Capture Entrance Frames: 0ms, 150ms, 350ms
    console.log("-> Capturing entrance animation frames...");
    // Immediate frame (0ms)
    await page.screenshot({ path: path.join(outDir, "entrance_0ms.png") });

    // 150ms into animation
    await page.waitForTimeout(150);
    await page.screenshot({ path: path.join(outDir, "entrance_150ms.png") });

    // 350ms into animation (completed dock)
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(outDir, "entrance_350ms.png") });

    const entranceBoxStyle = await page.evaluate(() => {
        const el = document.getElementById("wizard-dynamic-summary");
        if (!el) return null;
        const comp = window.getComputedStyle(el);
        return {
            opacity: comp.opacity,
            transform: comp.transform,
            position: comp.position,
            bottom: comp.bottom,
            hasDockedClass: el.classList.contains("summary-docked-in")
        };
    });
    console.log("Entrance Box Style @ 350ms:", entranceBoxStyle);

    // 2. Docked mid-scroll
    console.log("-> Testing docked mid-scroll...");
    await page.evaluate(() => window.scrollTo(0, 600));
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(outDir, "docked_mid_scroll.png") });

    const midScrollBox = await page.evaluate(() => {
        const el = document.getElementById("wizard-dynamic-summary");
        const rect = el.getBoundingClientRect();
        return {
            top: rect.top,
            bottom: rect.bottom,
            height: rect.height,
            viewportHeight: window.innerHeight,
            distFromBottom: window.innerHeight - rect.bottom
        };
    });
    console.log("Mid-scroll position:", midScrollBox);

    // 3. End of page natural resting position
    console.log("-> Testing end of page natural resting position...");
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(outDir, "end_of_page_natural.png") });

    const endScrollBox = await page.evaluate(() => {
        const el = document.getElementById("wizard-dynamic-summary");
        const nextBtn = document.getElementById("btn-wizard-next");
        const rect = el.getBoundingClientRect();
        const nextRect = nextBtn ? nextBtn.getBoundingClientRect() : null;
        return {
            summaryRect: { top: rect.top, bottom: rect.bottom },
            nextBtnRect: nextRect ? { top: nextRect.top, bottom: nextRect.bottom } : null,
            nextBtnVisible: nextRect ? (nextRect.top >= rect.bottom - 10) : false
        };
    });
    console.log("End-of-page layout:", endScrollBox);

    // 4. Live Data Updates Check
    console.log("-> Testing live data updates across modes, sliders, and framing...");
    // Short video with 4 clips x 10.0s = 40.0s
    await page.evaluate(() => {
        const durSlider = document.getElementById("slider-clip-duration");
        if (durSlider) {
            durSlider.value = "10.0";
            durSlider.dispatchEvent(new Event("input"));
        }
    });
    await page.waitForTimeout(200);
    const shortText = await page.evaluate(() => {
        return {
            headline: document.getElementById("summary-headline").innerText,
            sub: document.getElementById("summary-sub").innerText,
            badge: document.getElementById("badge-format-summary").innerText
        };
    });
    console.log("Short Mode Live Text (4 x 10s):", shortText);

    // Change to Long Mode via button click
    await page.evaluate(() => {
        document.getElementById("btn-type-long").click();
    });
    await page.waitForTimeout(200);
    const longText = await page.evaluate(() => {
        return {
            headline: document.getElementById("summary-headline").innerText,
            sub: document.getElementById("summary-sub").innerText
        };
    });
    console.log("Long Mode Live Text:", longText);

    // Change to Dual Format (Both) via button click
    await page.evaluate(() => {
        document.getElementById("btn-type-both").click();
    });
    await page.waitForTimeout(200);
    const bothText = await page.evaluate(() => {
        return {
            headline: document.getElementById("summary-headline").innerText,
            sub: document.getElementById("summary-sub").innerText
        };
    });
    console.log("Dual Mode Live Text:", bothText);

    // Change framing to blur_fit
    await page.evaluate(() => {
        const sel = document.getElementById("select-layout-mode");
        if (sel) {
            sel.value = "blur_fit";
            sel.dispatchEvent(new Event("change"));
        }
    });
    await page.waitForTimeout(200);
    const blurFitText = await page.evaluate(() => document.getElementById("summary-sub").innerText);
    console.log("Framing Live Subtext:", blurFitText);

    // Revert to Short Mode with 4 clips x 7.5s = 30s
    await page.evaluate(() => {
        document.getElementById("btn-type-short").click();
        const durSlider = document.getElementById("slider-clip-duration");
        if (durSlider) {
            durSlider.value = "7.5";
            durSlider.dispatchEvent(new Event("input"));
        }
        document.getElementById("btn-format-916").click();
    });
    await page.waitForTimeout(200);

    // 5. Theme switch: Dark and Light screenshots @ 1440x900
    console.log("-> Capturing Dark and Light screenshots @ 1440x900...");
    await page.evaluate(() => {
        document.documentElement.setAttribute("data-theme", "dark");
        localStorage.setItem("lionreel_theme", "dark");
        window.scrollTo(0, 400);
    });
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(outDir, "dark_1440.png") });

    await page.evaluate(() => {
        document.documentElement.setAttribute("data-theme", "light");
        localStorage.setItem("lionreel_theme", "light");
    });
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(outDir, "light_1440.png") });

    // 6. Keyboard Tab Focus
    console.log("-> Testing Keyboard Tab focus...");
    await page.evaluate(() => {
        const badge = document.getElementById("badge-format-summary");
        if (badge) badge.focus();
    });
    await page.waitForTimeout(150);
    await page.screenshot({ path: path.join(outDir, "keyboard_tab_focus.png") });

    // 7. Step removal / isolation check
    console.log("-> Testing Step removal / isolation...");
    await page.evaluate(() => {
        state.wizardStage = 1;
        renderWizardStep();
    });
    await page.waitForTimeout(100);
    const stage1Hidden = await page.evaluate(() => {
        const el = document.getElementById("wizard-dynamic-summary");
        return el ? (el.style.display === "none" || !el.classList.contains("summary-docked-in")) : true;
    });
    console.log("Summary bar cleanly removed on stage 1:", stage1Hidden);

    await page.evaluate(() => {
        navigateToStep(1); // Go to Step 1 Dashboard
    });
    await page.waitForTimeout(100);
    const step1Hidden = await page.evaluate(() => {
        const el = document.getElementById("wizard-dynamic-summary");
        return el ? (el.style.display === "none") : true;
    });
    console.log("Summary bar cleanly removed on Step 1 (Dashboard):", step1Hidden);

    // 8. Mobile 390px Viewport (Dark & Light)
    console.log("-> Testing Mobile 390px Viewport...");
    const mobileContext = await browser.newContext({
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 3,
        isMobile: true,
        hasTouch: true
    });
    const mobilePage = await mobileContext.newPage();
    await mobilePage.goto("http://localhost:8000/#step2", { waitUntil: "domcontentloaded" });
    await mobilePage.waitForTimeout(300);

    // Enter wizard stage 3
    await mobilePage.evaluate(() => {
        document.documentElement.setAttribute("data-theme", "dark");
        state.wizardStage = 3;
        renderWizardStep();
        window.scrollTo(0, 300);
    });
    await mobilePage.waitForTimeout(400);
    await mobilePage.screenshot({ path: path.join(outDir, "dark_390.png") });

    await mobilePage.evaluate(() => {
        document.documentElement.setAttribute("data-theme", "light");
    });
    await mobilePage.waitForTimeout(300);
    await mobilePage.screenshot({ path: path.join(outDir, "light_390.png") });

    // 9. Reduced Motion Test
    console.log("-> Testing prefers-reduced-motion...");
    const reducedMotionContext = await browser.newContext({
        viewport: { width: 1440, height: 900 },
        reducedMotion: "reduce"
    });
    const rmPage = await reducedMotionContext.newPage();
    await rmPage.goto("http://localhost:8000/#step2", { waitUntil: "domcontentloaded" });
    await rmPage.evaluate(() => {
        state.wizardStage = 3;
        renderWizardStep();
    });
    // Immediately at 20ms:
    await rmPage.waitForTimeout(20);
    const rmBoxState = await rmPage.evaluate(() => {
        const el = document.getElementById("wizard-dynamic-summary");
        const comp = window.getComputedStyle(el);
        return {
            opacity: comp.opacity,
            hasDockedClass: el.classList.contains("summary-docked-in")
        };
    });
    console.log("Reduced motion immediate state (<50ms):", rmBoxState);
    await rmPage.screenshot({ path: path.join(outDir, "reduced_motion.png") });

    await browser.close();
    console.log("=== CHANGE 1 Testing Complete! All screenshots saved in analysis/change1/ ===");
}

run().catch(err => {
    console.error("Test failed:", err);
    process.exit(1);
});
