# Project Proposal & Comprehensive Project Brief
## LionReel Studio: Autonomous Video Slicing, Computer Vision Curation & Short-Form Compilation Suite

---

### 1. Project Title & Identity
* **Project Title:** LionReel Studio — Autonomous Multi-Modal Video Slicing & Quality-Gated Viral Compilation Engine
* **Project Type:** Final Year Capstone Project / Software Engineering & Applied Artificial Intelligence Project
* **Domain:** Computer Vision, Digital Video Processing, Automation Systems, Creator Economy & Content Engineering
* **Author / Developer:** [Student Name / ID]
* **Supervising Faculty / Department:** Department of Computer Science & Software Engineering

---

### 2. Executive Summary & Abstract
In the modern digital media landscape, short-form video platforms such as YouTube Shorts, TikTok, and Instagram Reels have become the predominant medium for global digital engagement. However, manual curation, quality checking, cropping, editing, and compiling viral long-form videos into high-retention 9:16 vertical shorts is labor-intensive and technically challenging.

**LionReel Studio** is an end-to-end autonomous video production and curation system that replaces hours of manual video editing with automated computer vision, audio frequency analysis, and intelligent timeline compilation. The system autonomously queries video sources, enforces a **12-stage automated quality gate** (filtering out blurry, shaky, watermark-contaminated, AI-synthetic, cartoon, or promotional content), detects the peak viral climax moments using optical burst motion and audio energy, centers subjects using background subtraction (MOG2) and Haar cascades, and composes a fully produced, color-graded, captioned short video with background music and branding. The solution is accompanied by an interactive, modern web-based studio dashboard for real-time monitoring, configuration, and previewing.

---

### 3. Problem Statement & Motivation
#### The Problem
1. **High Latency in Content Repurposing:** Finding entertaining moments inside lengthy video repositories requires human editors to watch hours of footage, note timestamps, slice clips, and arrange transitions.
2. **Quality Inconsistency in Sourced Media:** Sourced web clips often suffer from poor focus, severe handheld camera shake, competing watermark overlays, poor lighting, or synthetic AI artifacts.
3. **Aspect Ratio Framing Bottlenecks:** Naive cropping of standard 16:9 horizontal videos to 9:16 vertical shorts cuts off subjects, leading to low retention and viewer dissatisfaction.
4. **Creator Burnout & Scalability Limits:** Solo creators and digital media agencies face severe scaling bottlenecks trying to output consistent daily content across multiple channels.

#### The Solution
LionReel Studio provides a fully autonomous, algorithmically driven pipeline that treats video curation as a multi-criteria computer vision problem, validating footage sharpness, camera stability, audio dynamics, subject presence, and aesthetic pacing before assembling an optimized reel.

---

### 4. Programming Languages & Technology Stack

| Layer | Language / Technology | Purpose & Architectural Role |
| :--- | :--- | :--- |
| **Core Processing Engine** | **Python (v3.10+)** | High-performance video processing, mathematical array transformations, algorithmic scoring, and pipeline orchestration. |
| **Computer Vision** | **OpenCV (`cv2`), NumPy** | Frame analysis, Laplacian variance blur detection, optical flow shake tracking, MOG2 background subtraction, Haar cascades, Canny edge detection, and LAB color space CLAHE. |
| **Media Engineering** | **MoviePy, FFmpeg, FFprobe** | Frame slicing, multi-clip composition, audio extraction, LUFS loudness normalization, transition fades, and H.264 rendering. |
| **Asset Generation** | **Pillow (PIL)** | Dynamic typographic rendering, stroke/shadow hook captions, watermark compositing, and automated thumbnail creation. |
| **Media Ingestion** | **yt-dlp** | Content extraction, query resolution, metadata filtering, view velocity calculation, and cookie-authenticated stream retrieval. |
| **Backend & REST API** | **Python `http.server` & `subprocess`** | Lightweight, dependency-free local web server handling asynchronous process execution, configuration persistence, and log streaming. |
| **Frontend UI (Dashboard)** | **JavaScript (ES6+ Vanilla)** | Reactive studio state management, asynchronous polling, log parsing, custom video playback controls, and dynamic 5-step wizard routing. |
| **Styling & Presentation** | **Modern CSS3 (Vanilla)** | Custom dark/light mode engine, glassmorphic design system, CSS grid/flexbox layouts, and fluid micro-animations. |
| **Markup** | **HTML5** | Semantic structure, accessible interactive components, and video canvas elements. |
| **DevOps & Packaging** | **Batch (`.bat`), Docker, DevContainers** | One-click local launch scripts, reproducible container environments, and cross-platform setup. |

---

### 5. Detailed System Architecture & Workflow Pipeline

The LionReel Studio pipeline operates as a modular, 6-phase autonomous assembly system:

```
[Phase 1: Ingestion & Query Engine]
       │
       ▼
[Phase 2: Metadata & Pre-Download Gate]
       │
       ▼
[Phase 3: 12-Stage Computer Vision Quality Gate]
       │
       ▼
[Phase 4: Algorithmic Peak Moment & Animal Framing]
       │
       ▼
[Phase 5: Post-Production (Color Grade, Captions, Music)]
       │
       ▼
[Phase 6: Energy Ramp Sequencing & Final 9:16 MP4 Export]
```

#### Phase 1: Smart Query Ingestion
* Generates dynamic queries (60+ search phrases) categorized by target subject (e.g., Cat, Dog, Mixed).
* Interfaces with `yt-dlp` using structured search parameters, minimum view thresholds (e.g., 500K+ viral sweet spot), and duration constraints (6s – 55s for shorts).

#### Phase 2: Metadata & Pre-Filtering Gate
* **Channel Blacklisting:** Filters out compilation aggregators and spam channels.
* **Semantic Filters:** Rejects titles containing unrelated animals, human vlogs ("my day", "routine"), and promotional tags ("sponsor", "discount", "merch", "giveaway").
* **Deduplication Engine:** Compares incoming video IDs against `used_videos.txt` and `used_metadata.json` to prevent content repetition.

#### Phase 3: The 12 Automated Quality Gates
Each candidate video is downloaded as a lightweight stream and subjected to rigorous sensory inspection:
1. **Sharpness & Resolution Filter:** Samples 16 frames; calculates Laplacian variance $Var(\nabla^2 I)$. Rejects frames with median sharpness $< \text{SHARP\_THRESHOLD}$ or resolution $< 480\text{p}$.
2. **Camera Shake Detector:** Analyzes outer 15% frame perimeter using consecutive frame subtraction. If background motion exceeds stability thresholds, the video is classified as shaky handheld footage and rejected.
3. **Audio Overlay & Pre-baked Music Filter:** Extracts 8kHz raw PCM audio; computes RMS energy over 0.5s segments. Slices with flat loudness (low coefficient of variation $CV < 0.12$) indicate non-diegetic background music and are discarded to preserve authentic pet audio.
4. **Watermark & Logo Scanner:** Analyzes all 4 corner bounding boxes (15% dimensions) using Canny edge detection and brightness variance. Videos with watermark signatures in $> 40\%$ of frames are rejected.
5. **AI / Synthetic Video Detector:** Evaluates high-frequency sensor noise, pixel texture standard deviation, and inter-frame morphing artifacts to reject synthetic generative models (Sora, Runway, Kling, SVD).
6. **2D Cartoon & Animation Filter:** Color histogram quantization and edge density profiling to reject illustrated, anime, or 2D animated content.
7. **Ad & Promotional Slate Filter:** Employs morphological gradient analysis across 5 vertical height bands to distinguish standard single-line subtitles (allowed) from full-screen text slates or commercial advertisements (rejected).
8. **Animal Presence Verification:** Utilizes Haar Cascades (`haarcascade_frontalcatface`, `haarcascade_frontalface`) and motion clustering to verify that a genuine pet is visible.
9. **Duplicate Detection:** Prevents reuse of previously processed assets.
10. **Aspect Ratio Enforcement:** Standardizes inputs into 9:16 vertical canvas.
11. **Color Grading Validation:** Ensures consistent chromatic balance.
12. **Background Music Synchronization:** Balances original audio with curated ambient music tracks.

#### Phase 4: Peak Viral Moment Extraction & Smart Cropping
* **Moment Cutting Algorithm:** Evaluates sliding windows across the video based on:
  $$\text{Score} = w_1 \cdot M_{\text{burst}} + w_2 \cdot M_{\text{total}} + w_3 \cdot C_{\text{center}} + w_4 \cdot A_{\text{audio}} - w_5 \cdot P_{\text{text}}$$
  Where $M_{\text{burst}}$ is acceleration of optical motion, $C_{\text{center}}$ rewards subject presence in the vertical crop corridor (22% to 78% horizontal span), $A_{\text{audio}}$ is acoustic energy, and $P_{\text{text}}$ penalizes promotional text overlays.
* **Smart Crop V2 (MOG2 + Cascade Centering):** Dynamically computes subject centroids using background subtraction and Haar bounding boxes, shifting crop windows to maintain an 80px safety margin so the animal is never truncated.

#### Phase 5: Post-Production & Color Science
* **Color Grading Pipeline:** Converts frames to LAB color space, applies CLAHE (Contrast Limited Adaptive Histogram Equalization) on the Luminance (L) channel, normalizes brightness to target mean 118, and enhances color saturation by $1.22\times$.
* **Hook & Typographic Branding:** Overlays high-contrast, stroke-bordered hook captions during the initial 3–5 seconds to maximize viewer retention.
* **Audio Engineering:** Normalizes voice and ambient sound to $-14 \text{ LUFS}$ standard; mixes low-volume background viral audio.

#### Phase 6: Energy Ramp Assembly & Delivery
* Clips are sorted using an **Energy Ramp Algorithm**: the single highest-impact hook clip opens the video, followed by clips sorted in ascending order of motion energy to create an engaging crescendo.
* Final export is encoded as 1080x1920 @ 30fps H.264 MP4 alongside auto-generated high-contrast thumbnails and SEO-ready metadata tags.

---

### 6. System GUI & Dashboard Features
The application features a modern web dashboard served locally via Python:
* **Real-Time Pipeline Status & Live Log Streamer:** Displays live console output with auto-scrolling and timestamped step indicators.
* **5-Step Creation Stepper:** Guides the user through (1) Project Home, (2) Source Wizard, (3) Clip Editor, (4) Render Pipeline, and (5) Library & Export.
* **Granular Quality Gate Toggles:** Allows creators to toggle individual verification tests (e.g., bypass funny check, adjust sharpness threshold, enable/disable color grading).
* **Finished Project Library:** Built-in video player with quick preview, metadata copying, file download, and one-click deletion.
* **Multi-Mode Support:** Supports "Classic" (multiple short YouTube clips), "Own Footage" (user-uploaded long video slicing), and "YouTube CC" (Creative Commons long-form slicing).

---

### 7. Academic Significance & Project Innovation
1. **Multi-Modal Quality Gating:** Unlike naive scrapers or basic ffmpeg wrappers, LionReel Studio integrates multi-modal sensory checks (audio variance analysis, computer vision edge detection, spatial frequency analysis, and motion optical flow).
2. **Autonomous Subject Tracking without Heavy GPU Overhead:** Employs highly optimized classical computer vision (Laplacian variance, MOG2, Haar Cascades, morphological gradients) that runs efficiently on standard CPU hardware without requiring multi-gigabyte neural network models.
3. **End-to-End Autonomous Pipeline:** Bridges the gap between raw data collection and polished, platform-ready digital media outputs with zero human editing required.

---

### 8. Potential Enhancements & Future Scope (Final Year Project Extensions)
To elevate this project to an exceptional grade, several high-impact extensions can be integrated:
1. **Deep Learning Object Detection (YOLOv8 / RT-DETR):** Replace Haar cascades with lightweight YOLOv8-nano to track cats, dogs, humans, and props with pinpoint bounding box accuracy and keypoint pose tracking.
2. **AI Voiceover & Speech-to-Text Subtitles (Whisper & ElevenLabs):** Integrate OpenAI Whisper for automatic speech transcription, generating word-by-word animated karaoke subtitles (CapCut style), and ElevenLabs for humorous AI commentary.
3. **Automated Social Media Publishing (YouTube Data API v3 & TikTok API):** Add OAuth2 social media connectors to schedule and publish generated shorts directly to YouTube Shorts, TikTok, and Instagram Reels with optimized tags and descriptions.
4. **Sentiment & Humor Analysis Model:** Train a lightweight binary classifier or multimodal LLM (Gemini 1.5 Flash API) to rate clip humor and punchline delivery before slicing.
5. **Cloud Deployment (Docker + AWS/GCP):** Package the backend into a container deployed on Cloud Run or AWS ECS with Amazon S3 storage for finished videos.

---

### 9. Viva / Presentation Talking Points
When presenting this project to examiners or evaluators, emphasize:
* **The Engineering Problem Solved:** Autonomous end-to-end content pipeline replacing 3+ hours of manual Adobe Premiere / CapCut editing.
* **The Mathematics / Algorithms:**
  - *Laplacian Variance* for blur detection: $\sigma^2 = \frac{1}{N}\sum (\nabla^2 I - \mu)^2$
  - *Optical Flow Motion Differential* for camera shake detection.
  - *Audio RMS Variance Coefficient* ($CV = \sigma / \mu$) for background music detection.
  - *MOG2 Gaussian Mixture Models* for dynamic subject centering in 9:16 crops.
  - *CLAHE in LAB color space* for contrast enhancement without color distortion.
* **Architecture Design:** Decoupled backend-frontend design (REST API + Vanilla JS/CSS reactive GUI + Python multiprocessing).
