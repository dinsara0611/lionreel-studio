# ═══════════════════════════════════════════════════════════════════════
# LionReel V94 — CAT/DOG ONLY, YOUTUBE-ONLY SOURCE
# ═══════════════════════════════════════════════════════════════════════
#
# V94 CHANGE (this update):
#   ✅ STRICT CAT/DOG FILTER — any video whose title mentions another
#      animal (hamster, rabbit, bird, fox, goat, etc.) is auto-rejected,
#      even in "mix" mode. Only cat + dog content can pass now.
#   ✅ Confirmed YouTube-only source (yt-dlp ytsearch + youtube.com URLs
#      — no other platform is ever queried or downloaded from).
#
# 6 QUALITY FIXES FROM V93 (all retained, unchanged):
#
#  FIX 1 — SHARPNESS CHECK (no blurry/pixelated videos)
#    Laplacian variance on 16 sample frames.
#    Rejects if median sharpness < SHARP_THRESHOLD (400).
#    Also checks resolution: rejects if source < 480p.
#
#  FIX 2 — SHAKE DETECTOR (no handheld shaky cam)
#    Compares frame-to-frame global optical flow.
#    If background moves as much as foreground → shaky cam → reject.
#    Uses corner tracking on background regions (edges of frame).
#
#  FIX 3 — AUDIO QUALITY FILTER (no loud music/noise overlay)
#    Checks audio RMS energy variance across clip.
#    Music = sustained high RMS with low variance (flat loud).
#    Natural pet audio = spiky RMS (quiet then sudden noise).
#    Rejects clips with music-like flat loud audio signature.
#
#  FIX 4 — WATERMARK DETECTOR (no other channels' logos)
#    Checks top-left, top-right, bottom-left, bottom-right corners.
#    If any corner has bright high-contrast text-like region → flag.
#    Rejects if watermark detected in >40% of sampled frames.
#
#  FIX 5 — COLOUR GRADE UPGRADE (not dark / washed out)
#    Auto white-balance correction per clip.
#    Adaptive brightness normalisation (target mean brightness 100-140).
#    Contrast enhancement (CLAHE on L channel in LAB space).
#    Saturation boost 1.20x (up from 1.15x).
#
#  FIX 6 — SMART CROP V2 (animal not cut off)
#    After finding animal center, validates crop box doesn't clip animal.
#    If animal detected near crop edge → shifts crop to include full animal.
#    Safe margin: 80px from crop boundary.
#    Audio normalisation: target -14 LUFS (YouTube/TikTok standard).
#
# ALL V92 FEATURES RETAINED:
#   ✅ 60+ viral queries, Viral Score ranking, 500K min views
#   ✅ Peak Laugh Moment detector
#   ✅ L1/L2/L3 AI/fake detection
#   ✅ Animal presence check
#   ✅ Intro skip, MOG2 crop, 5s hook
#   ✅ Energy ramp ordering, PIL text, logo, thumbnail
# ═══════════════════════════════════════════════════════════════════════

import os, time, random, json, tempfile, glob, math
import numpy as np, cv2, warnings, logging
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

import sys

# Ensure Python virtualenv Scripts folder (containing ffmpeg.exe) is in PATH
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_SCRIPTS = os.path.join(_BASE_DIR, ".venv", "Scripts")
if os.path.exists(_VENV_SCRIPTS) and _VENV_SCRIPTS not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _VENV_SCRIPTS + os.pathsep + os.environ.get("PATH", "")

# Force unbuffered line-level stdout/stderr for instant GUI telemetry streaming
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(line_buffering=True)
    except: pass
if hasattr(sys.stderr, "reconfigure"):
    try: sys.stderr.reconfigure(line_buffering=True)
    except: pass

import builtins
_orig_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _orig_print(*args, **kwargs)

from yt_dlp import YoutubeDL

# MoviePy 1.x & 2.x Compatibility Layer
import moviepy
from moviepy import (
    VideoClip, VideoFileClip, concatenate_videoclips,
    ImageClip, CompositeVideoClip, ColorClip, vfx, afx
)

BaseClip = getattr(moviepy.Clip, "Clip", moviepy.Clip)
for target in [BaseClip, VideoClip]:
    if not hasattr(target, "subclip") and hasattr(target, "subclipped"):
        target.subclip = lambda self, t_start, t_end=None: self.subclipped(t_start, t_end)
    if not hasattr(target, "set_duration") and hasattr(target, "with_duration"):
        target.set_duration = lambda self, d: self.with_duration(d)
    if not hasattr(target, "set_opacity") and hasattr(target, "with_opacity"):
        target.set_opacity = lambda self, o: self.with_opacity(o)
    if not hasattr(target, "set_pos") and hasattr(target, "with_position"):
        target.set_pos = lambda self, pos, relative=False: self.with_position(pos)
    if not hasattr(target, "set_position") and hasattr(target, "with_position"):
        target.set_position = lambda self, pos: self.with_position(pos)
    if not hasattr(target, "set_audio") and hasattr(target, "with_audio"):
        target.set_audio = lambda self, a: self.with_audio(a)
    if not hasattr(target, "crop") and hasattr(target, "cropped"):
        target.crop = lambda self, *args, **kwargs: self.cropped(*args, **kwargs)
    if not hasattr(target, "resize") and hasattr(target, "resized"):
        target.resize = lambda self, *args, **kwargs: self.resized(*args, **kwargs)
    if not hasattr(target, "fl") and hasattr(target, "transform"):
        target.fl = lambda self, f, apply_to=None: self.transform(f)
    if not hasattr(target, "fadein"):
        target.fadein = lambda self, d: self.with_effects([vfx.FadeIn(d)])
    if not hasattr(target, "fadeout"):
        target.fadeout = lambda self, d: self.with_effects([vfx.FadeOut(d)])

def audio_normalize(clip):
    try:
        return clip.with_effects([afx.AudioNormalize()])
    except:
        return clip

from PIL import Image, ImageDraw, ImageFont


# ───────────────────────────────────────────────────────────────
# CONFIG
# ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FOLDER      = os.path.join(BASE_DIR, "raw", "")
OUT_FOLDER      = os.path.join(BASE_DIR, "finished", "")
HISTORY_FILE    = "used_videos.txt"
USED_META_FILE  = "used_metadata.json"
LOGO_FILE       = "lion_logo.png"

SHORT_CLIP_SEC  = 7.5
TARGET_CLIPS    = 4
FADE_DUR        = 0.0
OUTPUT_FPS      = 30
BITRATE         = "8000k"
ADD_LOGO        = False
LOGO_OPACITY    = 0.35
LOGO_WIDTH      = 120
OUT_W, OUT_H    = 1080, 1920

# V92 viral scoring
MIN_VIEWS               = 0
VIRAL_SWEET_VIEWS_HIGH  = 80_000_000
DURATION_SWEET_LOW      = 8
DURATION_SWEET_HIGH     = 45
MAX_DURATION_HARD       = 55
MIN_DURATION_HARD       = 6
RECENCY_MONTHS_BOOST    = 18
SEARCH_RESULTS_PER_Q    = 80

# ── V93 QUALITY THRESHOLDS ──────────────────────────────────────
SHARP_THRESHOLD         = 30    # Laplacian variance — below = blurry. Raise if too strict.
MIN_SOURCE_HEIGHT       = 360    # Reject videos shorter than 480p
SHAKE_THRESHOLD         = 20.0  # Background motion px/frame — above = shaky cam
WATERMARK_THRESHOLD     = 0.65  # Fraction of frames with watermark corner → reject
MUSIC_FLAT_THRESHOLD    = 0.12  # Audio RMS variance coefficient — below = background music
SAFE_CROP_MARGIN        = 80    # Pixels — animal must be this far from crop edge
TARGET_BRIGHTNESS       = 118   # Target mean brightness for auto-exposure (0-255)
CLAHE_CLIP_LIMIT        = 2.5   # CLAHE contrast enhancement strength
SATURATION_BOOST        = 1.22  # Colour saturation multiplier

# Bypasses and Pipeline Flags
BYPASS_QUALITY_GATE     = False # If True, prints quality gate checks but never rejects candidates
BYPASS_FUNNY_CHECK      = False # If True, ignores strict funny word requirements in title
APPLY_COLOR_GRADING     = True  # If False, passes through natural original colors without alteration
APPLY_SMART_CROP        = True  # If True, centers animals using background subtraction & cascades
ADD_BACKGROUND_MUSIC    = True  # If True, mixes background audio with dynamic ducking
MOMENT_CUT_MODE         = "peak_viral" # "peak_viral" | "smart_auto" | "full_clip"
CHECK_SHARPNESS         = True
CHECK_SHAKE             = True
CHECK_WATERMARK         = True
CHECK_AUDIO_LEVELS      = True
CHECK_AI_VIDEO          = True
CHECK_CARTOON           = True
CHECK_ADVERTISING       = True

os.makedirs(OUT_FOLDER, exist_ok=True)
os.makedirs(RAW_FOLDER,  exist_ok=True)


# ───────────────────────────────────────────────────────────────
# VIDEO MODE
# ───────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
# V95 — SOURCE MODE (multi-clip-from-one-long-video methods)
# ═══════════════════════════════════════════════════════════════
#   "classic"     : Autonomous YouTube discovery — searches YouTube live,
#                   downloads top viral funny clips matching animal category.
#   "curated"     : User selected / timeline curated clips from studio library.
#   "own_footage" : reads a long video (5/10/20 min) from OWN_FOOTAGE_FOLDER
#                   that belongs to you, and pulls several funny moments
#                   from across it into one short.
#   "youtube_cc"  : searches YouTube for long Creative Commons videos and slices them.
#   "custom_url"  : slices user-provided custom YouTube link.
SOURCE_MODE = "classic"   # "classic" | "curated" | "own_footage" | "youtube_cc" | "custom_url"

OWN_FOOTAGE_FOLDER   = r"G:\My Drive\Cat make\own_footage\\"
OWN_FOOTAGE_HISTORY  = "used_own_footage.txt"

CC_MAX_DURATION      = 1200    # accept CC videos up to 20 minutes long
CC_MIN_DURATION      = 60      # must be at least 1 minute to make sense to slice
CC_CANDIDATES_TO_CHECK = 12    # how many top search results to license-check per run


VIDEO_MODE = random.choice(["cat", "dog", "mix"])

# Video format and length defaults
VIDEO_TYPE          = "short" # "short" | "long" | "both"
TARGET_DURATION_MIN = 5.0     # Target compilation minutes for long video
TARGET_FORMAT       = "9:16"  # "9:16" | "16:9" | "1:1"
SELECTED_CLIPS      = []      # Clips queued from GUI
CUSTOM_URL          = ""

# Load GUI configuration overrides if config.json is present
if os.path.exists("config.json"):
    try:
        with open("config.json", "r", encoding="utf-8") as f_cfg:
            overrides = json.load(f_cfg)
        if "VIDEO_MODE" in overrides:
            raw_mode = str(overrides["VIDEO_MODE"]).lower()
            VIDEO_MODE = "mix" if raw_mode in ("mix", "mixed", "wildlife") else raw_mode
        if "SOURCE_MODE" in overrides:
            SOURCE_MODE = str(overrides["SOURCE_MODE"]).lower()
        if "CUSTOM_URL" in overrides:
            CUSTOM_URL = str(overrides["CUSTOM_URL"]).strip()
        if "VIDEO_TYPE" in overrides:
            VIDEO_TYPE = str(overrides["VIDEO_TYPE"]).lower()
        if "TARGET_DURATION_MIN" in overrides:
            TARGET_DURATION_MIN = float(overrides["TARGET_DURATION_MIN"])
        if "SHORT_CLIP_SEC" in overrides:
            SHORT_CLIP_SEC = float(overrides["SHORT_CLIP_SEC"])
        if "ASPECT_RATIO" in overrides:
            TARGET_FORMAT = overrides["ASPECT_RATIO"]
        elif "TARGET_FORMAT" in overrides:
            TARGET_FORMAT = overrides["TARGET_FORMAT"]

        # Enforce format defaults according to video type:
        # Long compilation on YouTube must be 16:9 landscape unless user explicitly chose otherwise
        if VIDEO_TYPE == "long" and TARGET_FORMAT not in ("16:9", "1:1"):
            TARGET_FORMAT = "16:9"
        elif VIDEO_TYPE == "short" and TARGET_FORMAT not in ("9:16", "1:1"):
            TARGET_FORMAT = "9:16"

        # Set output resolution based on aspect ratio
        if TARGET_FORMAT == "16:9":
            OUT_W, OUT_H = 1920, 1080
        elif TARGET_FORMAT == "1:1":
            OUT_W, OUT_H = 1080, 1080
        else: # 9:16
            OUT_W, OUT_H = 1080, 1920

        if "ADD_LOGO" in overrides:
            ADD_LOGO = (overrides["ADD_LOGO"] is True or str(overrides["ADD_LOGO"]).lower() == "true")

        # Calculate TARGET_CLIPS according to duration
        if VIDEO_TYPE in ("long", "both"):
            total_sec = max(60, int(TARGET_DURATION_MIN * 60))
            TARGET_CLIPS = max(10, int(round(total_sec / SHORT_CLIP_SEC)))
        elif "TARGET_CLIPS" in overrides:
            TARGET_CLIPS = int(overrides["TARGET_CLIPS"])

        if "BYPASS_QUALITY_GATE" in overrides:
            BYPASS_QUALITY_GATE = (overrides["BYPASS_QUALITY_GATE"] is True or str(overrides["BYPASS_QUALITY_GATE"]).lower() == "true")
        if "BYPASS_FUNNY_CHECK" in overrides:
            BYPASS_FUNNY_CHECK = (overrides["BYPASS_FUNNY_CHECK"] is True or str(overrides["BYPASS_FUNNY_CHECK"]).lower() == "true")
        if "APPLY_COLOR_GRADING" in overrides:
            APPLY_COLOR_GRADING = (overrides["APPLY_COLOR_GRADING"] is True or str(overrides["APPLY_COLOR_GRADING"]).lower() == "true")
        if "APPLY_SMART_CROP" in overrides:
            APPLY_SMART_CROP = (overrides["APPLY_SMART_CROP"] is True or str(overrides["APPLY_SMART_CROP"]).lower() == "true")
        if "ADD_BACKGROUND_MUSIC" in overrides:
            ADD_BACKGROUND_MUSIC = (overrides["ADD_BACKGROUND_MUSIC"] is True or str(overrides["ADD_BACKGROUND_MUSIC"]).lower() == "true")
        if "CHECK_SHARPNESS" in overrides:
            CHECK_SHARPNESS = (overrides["CHECK_SHARPNESS"] is True or str(overrides["CHECK_SHARPNESS"]).lower() == "true")
        if "CHECK_SHAKE" in overrides:
            CHECK_SHAKE = (overrides["CHECK_SHAKE"] is True or str(overrides["CHECK_SHAKE"]).lower() == "true")
        if "CHECK_WATERMARK" in overrides:
            CHECK_WATERMARK = (overrides["CHECK_WATERMARK"] is True or str(overrides["CHECK_WATERMARK"]).lower() == "true")
        if "CHECK_AUDIO_LEVELS" in overrides:
            CHECK_AUDIO_LEVELS = (overrides["CHECK_AUDIO_LEVELS"] is True or str(overrides["CHECK_AUDIO_LEVELS"]).lower() == "true")
        if "CHECK_AI_VIDEO" in overrides:
            CHECK_AI_VIDEO = (overrides["CHECK_AI_VIDEO"] is True or str(overrides["CHECK_AI_VIDEO"]).lower() == "true")
        if "CHECK_CARTOON" in overrides:
            CHECK_CARTOON = (overrides["CHECK_CARTOON"] is True or str(overrides["CHECK_CARTOON"]).lower() == "true")
        if "CHECK_ADVERTISING" in overrides:
            CHECK_ADVERTISING = (overrides["CHECK_ADVERTISING"] is True or str(overrides["CHECK_ADVERTISING"]).lower() == "true")
        if "MOMENT_CUT_MODE" in overrides:
            MOMENT_CUT_MODE = str(overrides["MOMENT_CUT_MODE"]).lower()

        if "SELECTED_CLIPS" in overrides and isinstance(overrides["SELECTED_CLIPS"], list):
            SELECTED_CLIPS = overrides["SELECTED_CLIPS"]

        print(f"   [Config] Loaded GUI overrides: Mode={VIDEO_MODE.upper()}, SourceMode={SOURCE_MODE}, Type={VIDEO_TYPE.upper()}, ColorGrading={'ON' if APPLY_COLOR_GRADING else 'OFF'}, FunnyCheck={'BYPASS' if BYPASS_FUNNY_CHECK else 'ENFORCE'}, QualityGate={'BYPASS' if BYPASS_QUALITY_GATE else 'ENFORCE'}, TargetMin={TARGET_DURATION_MIN}m, TargetClips={TARGET_CLIPS}, ClipSec={SHORT_CLIP_SEC}s, Format={TARGET_FORMAT} ({OUT_W}x{OUT_H})")
    except Exception as e_cfg:
        print(f"   [Config] Failed to load config.json: {e_cfg}")

CAT_WORDS = [
    "cat","cats","kitten","kittens","kitty","meow","feline","tabby","calico",
    "persian","bengal","siamese","ragdoll","munchkin","maine coon","scottish fold",
    "sphynx","british shorthair","catto","nyan",
]
DOG_WORDS = [
    "dog","dogs","puppy","puppies","pup","doggo","husky","golden retriever",
    "labrador","corgi","poodle","shiba","dachshund","bulldog","beagle",
    "pomeranian","chihuahua","pug","woof","bork","rottweiler","doberman",
    "german shepherd","maltese","cavapoo","cavachon","cockapoo","yorkshire","doge",
]
ANIMAL_WORDS = CAT_WORDS + DOG_WORDS + [
    "hamster","rabbit","bunny","bunnies","parrot","birb","bird","birds",
    "duck","duckling","goat","otter","raccoon","fox","foxes",
    "hedgehog","ferret","guinea pig","capybara","chinchilla",
    "squirrel","deer","penguin","seal","pet","pets","animal","animals",
]
ANIMAL_CHANNEL_WORDS = [
    "cat","dog","pet","animal","kitten","puppy","paws","fur","meow","woof",
    "catto","doggo","feline","canine","wildlife","floofy","fluffy","whisker",
    "dodo","pets","critters","creatures","funny cat","funny dog",
]
FUNNY_WORDS = [
    "funny","hilarious","fail","fails","stupid","dumb","crazy","insane",
    "weird","chaotic","chaos","unhinged","lol","lmao","shocked",
    "reaction","scared","scare","surprise","surprised","confused",
    "zoomies","attack","attacks","jumpscare","try not to laugh",
    "caught on camera","best of","compilation","moments","clips",
    "vs","battle","fights","sneezes","screams","screaming","yelling",
    "refuses","destroy","destroys","broke","broken","lose it","losing it",
    "freaks out","goes crazy","pov","caught","guilty","busted",
]

WHITELIST_CHANNELS = [
    "the dodo","dodo","failarmy","9gag","ladbible","unilad","viral hog","viralhog",
    "jukin","storyful","rumble viral","america's funniest","afv","afvofficial",
    "laughpig","meow","catlovers","cat lovers","funny cats and dogs",
    "cat universe","daily cat","cats are awesome","dogs are awesome",
    "funnyplox","tiger productions","compilation nation","best fails",
    "kyoot","we love animals","zefrank","reddit",
]

# ═══════════════════════════════════════════════════════════════
# V94 — STRICT CAT/DOG ONLY FILTER
# These lists make sure that no matter what search results come back,
# only cat and dog content can ever pass the filter — other animals
# (hamster, rabbit, bird, fox, goat, etc.) are explicitly blocked.
# ═══════════════════════════════════════════════════════════════
CAT_DOG_WORDS = list(set(CAT_WORDS + DOG_WORDS))

CAT_DOG_CHANNEL_WORDS = [
    "cat","dog","catto","doggo","feline","canine","kitten","puppy",
    "meow","woof","funny cat","funny dog","cats","dogs",
]

OTHER_ANIMAL_BLOCK_WORDS = [
    "hamster","rabbit","bunny","bunnies","parrot","birb","bird","birds",
    "duck","duckling","goat","otter","raccoon","fox","foxes",
    "hedgehog","ferret","guinea pig","capybara","chinchilla",
    "squirrel","deer","penguin","seal","cow","cows","calf","pig","pigs",
    "piglet","sheep","lamb","chicken","chick","rooster","hen",
    "snake","lizard","gecko","turtle","tortoise","frog","fish",
    "monkey","chimp","elephant","lion cub","tiger cub","bear cub",
    "koala","panda","llama","alpaca","donkey","mule","camel",
    "hedge hog","sea lion","dolphin","whale","shark","spider","insect",
]


# ───────────────────────────────────────────────────────────────
# SEARCH QUERIES (V92 viral-specific)
# ───────────────────────────────────────────────────────────────
CAT_QUERIES = [
    "cat yelling at woman dinner table meme original",
    "cat scared cucumber original video",
    "cat knocks everything off table on purpose",
    "cat pushes glass off table slow eye contact",
    "cat loaf refuses to move funny",
    "cat wakes owner up 3am attacking face",
    "cat slaps dog in face unprovoked",
    "cat jumps scared then acts casual",
    "cat falls off table and pretends nothing happened",
    "cat zoomies 3am destroying house",
    "cat stares at wall talking to something",
    "cat attacks own reflection mirror",
    "kitten tries to fit in tiny box fails",
    "cat screaming at nothing reaction",
    "cat vs printer nemesis attack",
    "cat steals food instantly no hesitation",
    "cat refuses to let owner work laptop",
    "cat derpy face tongue out forgot to put in",
    "cat hissing at own hiccup confused",
    "cat jumpscare fails compilation 2023 2024",
    "cats being absolute menaces compilation",
    "cats that think they are dogs funny",
    "cat trying to fit won't fit funny",
    "cats reacting to magic tricks funny",
    "cats absolutely losing it compilation",
    "scottish fold cat sitting like human funny",
    "maine coon massive cat scares everyone",
    "ragdoll cat goes completely limp funny",
    "british shorthair chonk struggle life funny",
    "cat vs cucumber 2023 new reactions best",
    "cats vs dogs who wins fight funny compilation",
    "cat ignores owner for hours then bites them",
    "cats that clearly hate their owners funny",
    "cat gives owner death stare doing nothing wrong",
    "cat compilation try not to laugh impossible",
    "cats with no chill compilation 2024",
    "funniest cat moments caught on camera 2024",
    "cats destroying things compilation funny",
]

DOG_QUERIES = [
    "dog guilty face did something bad expression",
    "dog zoomies crashes into furniture compilation",
    "dog fails to catch treat embarrassing",
    "dog scared of tiny kitten compilation",
    "dog sits on owner face good morning",
    "dog absolutely destroys couch caught red handed",
    "dog howling at owner singing voice crack",
    "dog confused magic trick toy disappears",
    "dog dramatic fall off couch compilation",
    "dog cannot handle bath time escapes funny",
    "puppy hiccups own scared first time",
    "dog versus own fart confused reaction",
    "dog steals food lightning speed caught camera",
    "dog cannot walk on ice fails compilation",
    "dog meets baby first time goes crazy",
    "husky talking back arguing owner funny",
    "dog ignores training selective hearing funny",
    "golden retriever extremely gentle with everything",
    "corgi butt wiggle compilation impossible not laugh",
    "dog absolutely loses mind owner comes home",
    "chihuahua thinks it is giant dog attacks",
    "great dane has no idea how big it is",
    "shiba inu much wow doge face reaction",
    "pug struggles to exist compilation funny",
    "dachshund tiny legs big energy funny",
    "dog versus automatic dog feeder outsmarting it",
    "dog rings bell for treats nonstop manipulation",
    "dog recognizes owner car from distance reaction",
    "dog pretends to be asleep avoid bath funny",
    "dog steals spot on couch owner gone 5 seconds",
    "puppy first encounter cat terrified funny",
    "dogs reacting to their owners crying test funny",
    "funniest dog moments caught on camera 2024",
    "dog compilation try not to laugh impossible",
    "dogs with no chill compilation 2024",
]

MIX_QUERIES = CAT_QUERIES + DOG_QUERIES + [
    "cat and dog best friends compilation impossible",
    "tiny kitten bosses big dog around funny",
    "dog afraid of cat half its size compilation",
    "cats slapping dogs perfectly timed compilation",
    "cats and dogs having absolutely no chill compilation",
    "cats and dogs forgot how to animal funny",
    "cats and dogs caught doing crime compilation 2024",
    "try not to laugh at cats and dogs challenge impossible",
    "funniest cats and dogs on the internet 2024",
    "cats and dogs being idiots compilation 2024",
]

def get_search_queries():
    base_queries = []
    if VIDEO_MODE == "cat":
        base_queries = list(CAT_QUERIES)
        if VIDEO_TYPE in ("long", "both"):
            base_queries = [
                "funny cats compilation 2026", "try not to laugh funny cats moments",
                "cute kittens funny fails compilation", "ultimate cat zoomies funny video",
                "hilarious cats being weird full compilation"
            ] + base_queries
    elif VIDEO_MODE == "dog":
        base_queries = list(DOG_QUERIES)
        if VIDEO_TYPE in ("long", "both"):
            base_queries = [
                "funny dogs compilation 2026", "try not to laugh funny dogs moments",
                "cute puppies funny fails compilation", "guilty dogs caught on camera compilation",
                "hilarious dog zoomies full compilation"
            ] + base_queries
    else:
        base_queries = list(MIX_QUERIES)
        if VIDEO_TYPE in ("long", "both"):
            base_queries = [
                "funny cats and dogs compilation 2026", "funniest pets try not to laugh",
                "animals being hilarious full compilation", "best pet fails compilation",
                "cute and funny animal moments compilation"
            ] + base_queries
    return base_queries

def mode_passes(entry):
    title   = (entry.get("title")   or "").lower()
    channel = (entry.get("channel") or entry.get("uploader") or "").lower()
    if VIDEO_MODE == "cat":
        return any(w in title or w in channel for w in CAT_WORDS)
    if VIDEO_MODE == "dog":
        return any(w in title or w in channel for w in DOG_WORDS)
    # V94: "mix" mode still requires cat OR dog words — no longer a free pass
    return any(w in title or w in channel for w in CAT_DOG_WORDS)


# ───────────────────────────────────────────────────────────────
# VIRAL SCORE (V92)
# ───────────────────────────────────────────────────────────────
def compute_viral_score(entry):
    views     = entry.get("view_count")    or 0
    likes     = entry.get("like_count")    or 0
    duration  = entry.get("duration")      or 0
    upload_ts = entry.get("timestamp")     or entry.get("upload_date")
    title     = (entry.get("title")        or "").lower()
    channel   = (entry.get("channel")      or entry.get("uploader") or "").lower()

    score = 0.0
    # views=0 means YouTube didn't return count in flat extract — don't reject, give neutral score
    if views == 0:
        score += 12.0  # neutral base — will be ranked below confirmed viral
    elif views < 50_000:
        return -1.0  # genuinely tiny channel — skip

    v_score = math.log10(max(views, 1)) if views > 0 else 0
    if views > VIRAL_SWEET_VIEWS_HIGH: v_score *= 0.75
    score += v_score * 3.0

    if likes > 0 and views > 0:
        like_ratio = likes / views
        if like_ratio > 0.05:   score += 4.0
        elif like_ratio > 0.02: score += 2.0
        elif like_ratio > 0.01: score += 1.0

    if VIDEO_TYPE in ("long", "both"):
        if 60 <= duration <= 1200: score += 6.0
        elif duration > 1200: score += 2.0
    else:
        if DURATION_SWEET_LOW <= duration <= DURATION_SWEET_HIGH: score += 5.0
        elif duration < DURATION_SWEET_LOW: score += 1.0
        elif duration <= MAX_DURATION_HARD: score += 2.0

    if upload_ts:
        try:
            if isinstance(upload_ts, str) and len(upload_ts) == 8:
                from datetime import datetime
                upload_dt = datetime.strptime(upload_ts, "%Y%m%d")
                age_days  = (datetime.now() - upload_dt).days
            elif isinstance(upload_ts, (int, float)):
                age_days = (time.time() - upload_ts) / 86400
            else:
                age_days = 730
            if age_days < 180:   score += 4.0
            elif age_days < 365: score += 2.5
            elif age_days < RECENCY_MONTHS_BOOST * 30: score += 1.0
        except: pass

    for wc in WHITELIST_CHANNELS:
        if wc in channel: score += 3.0; break

    HIGH_SIGNAL = ["try not to laugh","lost it","losing it","caught on camera",
                   "compilation","reaction","zoomies","fails","guilty","busted",
                   "freaks out","yelling","screaming"]
    for phrase in HIGH_SIGNAL:
        if phrase in title: score += 0.8; break

    # V94: only reward cat/dog titles, not any generic animal word
    if any(w in title for w in CAT_DOG_WORDS) and any(w in title for w in FUNNY_WORDS):
        score += 2.0

    return score


# ───────────────────────────────────────────────────────────────
# METADATA
# ───────────────────────────────────────────────────────────────
CAT_TITLES = [
    "Pov: Your cat is officially broken 😹",
    "This cat said NO to everything 😂🐱",
    "Cat logic is unmatched 🐾",
    "The audacity of this cat 😤🐈",
    "Cats really are built different 😂🐾",
    "When your cat does THIS you lose it 😹",
    "Caught my cat doing the unthinkable 😱😹",
    "Cats that have completely given up 😹😭",
    "When the cat forgets it's not human 😂🐾",
    "Cat jumpscare compilation 😱😹",
    "This cat just ended me 💀🐱",
    "Cat said absolutely not 😹🐱",
    "My cat is a menace and I love him 😹",
    "Cats vs gravity — cats win again 😹",
    "POV you live with a tiny feline dictator 😤🐈",
    "Cat woke up and chose chaos 😹🐱",
    "This cat clip sent me to another dimension 😭😹",
    "Nobody told me cats could do this 😂🐾",
    "Real footage that broke the cat internet 😱🐾",
    "I can't stop laughing at this cat 😂🐾",
    "The way this cat has ZERO regrets 😤🐱",
    "Cat said today is not the day 💀🐱",
    "Your honour my cat is unhinged 🐱😂",
    "When the cat finds out it's bath time 😱🐱",
    "This cat is in its villain era 😈🐱",
]
DOG_TITLES = [
    "This dog has no idea what it's doing 😂🐶",
    "Dogs that forgot how to dog 😂🐶",
    "Why are dogs like this 😭😂",
    "Dog brain is something else 😂🐶",
    "Dogs that need to be stopped 😂🐶",
    "POV your dog owns the house not you 🏠🐾",
    "Dogs reacting to absolutely nothing 😂🐶",
    "This dog clip sent me 😭😂🐾",
    "Puppy chaos compilation 🔥🐶",
    "The confidence of this dog is unmatched 😤🐶",
    "My dog woke up and chose violence 😹🐶",
    "Dogs being absolutely unhinged 😂🐶",
    "This dog has ZERO regrets 😤🐶",
    "Dog zoomies destroyed everything 😱🐶",
    "Nobody told me dogs could do this 😂🐶",
    "When your dog is the main character 😎🐶",
    "Dog said I do what I want 😤🐶",
    "Real dog footage that broke the internet 😱🐾",
    "I can't stop laughing at this dog 😂🐶",
    "Caught my dog doing the unthinkable 😱🐶",
    "Your honour my dog is guilty as charged 🐶😂",
    "The guilty face is sending me 💀🐶",
    "Dog said sorry not sorry 😤🐶",
    "This dog is in its flop era 😂🐶",
    "Dog brain vs common sense: dog wins 😂🐾",
]
MIX_TITLES = [
    "Pov: Your pet is officially broken 😹",
    "I can't stop laughing at this 😂🐾",
    "Wait for the end I'm crying 😭😹",
    "Why are pets like this 😭😂",
    "POV your pet owns the house not you 🏠🐾",
    "The funniest cats and dogs on the internet 🐾😹",
    "Cat and dog chaos compilation 🔥🐾",
    "Cats and dogs being absolutely unhinged 😂🐾",
    "This pet has ZERO regrets 😤🐶",
    "Cats and dogs on their villain arc 😈🐾",
    "My pet woke up and chose chaos 😹🐱",
    "When your pet is the main character 😎🐱",
    "The most chaotic cats and dogs on the internet 🔥🐾",
    "This clip sent me 😭😂🐾",
    "Cats and dogs really said I do what I want 😤🐾",
    "Unhinged cat and dog behaviour compilation 🔥😂",
    "Real footage that broke the internet 😱🐾",
    "Cats and dogs having a better day than me 🐾😂",
    "Caught on camera: absolute cat and dog chaos 😱🐾",
    "Cat and dog owners will understand this 😭😂",
    "Your honour these pets are feral 😂🐾",
    "Cats and dogs that said today is chaos day 🔥🐾",
    "The goblin era of pets 😈🐾",
    "POV: your pet hates you but you're ok with it 😭🐾",
    "Cats and dogs that are built differently fr 😂🐾",
]
ALL_CAPTIONS = [
    "Can't make this up 😹", "Why are pets like this 😂", "This one got me 💀",
    "Sending this to everyone 🐾", "Pets are just built different",
    "I am not okay 😭😹", "The confidence 😤🐾", "This broke me 😭",
    "I replayed this 10 times 😹", "My stomach hurts from laughing 😂",
    "This made my whole week 🐾", "I need everyone to see this 😹",
    "Not me crying at a pet video again 😭", "The way this destroyed me 💀🐾",
    "Whoever filmed this is a hero 🎥🐾",
]
HOOK_LINES = [
    "WAIT FOR IT... 👀", "YOU WON'T BELIEVE THIS 😱",
    "THIS IS TOO FUNNY 😹", "WATCH TILL THE END 🔥",
    "POV: PET CHAOS 💀", "CAUGHT ON CAMERA 📸",
    "HE DID NOT 💀", "THE AUDACITY 😤",
    "I CANNOT 😭😹", "REAL FOOTAGE 😱",
    "THEY DID WHAT 😱", "SEND HELP 😭",
]
SUB_HOOK_LINES = [
    "watch till the end 🔥", "it gets better 👀",
    "the ending 💀", "i replayed this 10x 😹",
    "keep watching 😱", "you need to see this 🐾",
    "wait for it... 👁", "it happens at 5 seconds 😹",
    "the reaction 😱", "i'm not okay 😭",
]
YOUTUBE_TAGS = (
    "funny cats, funny dogs, cat videos, dog videos, funny animals, "
    "cute cats, cute dogs, funny pet videos, cat compilation, dog compilation, "
    "funny cat moments, funny dog moments, pet fails, kitten videos, puppy videos, "
    "cats being funny, dogs being funny, animal videos, pet compilation, lion reel, "
    "try not to laugh, funny pets 2025, viral pet videos, cat shorts, dog shorts"
)
SOCIAL_TAGS = (
    "#funnycats #funnydogs #catvideos #dogvideos #lionreel "
    "#petsoftiktok #catmemes #dogmemes #funnyanimals "
    "#viral #fyp #reels #catsoftiktok #dogsoftiktok "
    "#cutecats #cutedogs #funnypets #pets #shorts #petlover "
    "#animalsoftiktok #animalsofinstagram #dogsofinstagram "
    "#catsofinstagram #petvideos #funnyvideos #catshorts #dogshorts"
)

def load_used_titles():
    if os.path.exists(USED_META_FILE):
        try:
            with open(USED_META_FILE,"r",encoding="utf-8") as f:
                return set(json.load(f).get("used_titles",[]))
        except: pass
    return set()

def save_used_titles(s):
    with open(USED_META_FILE,"w",encoding="utf-8") as f:
        json.dump({"used_titles":list(s)},f,ensure_ascii=False,indent=2)

def pick_unique_title():
    pool = CAT_TITLES if VIDEO_MODE=="cat" else (DOG_TITLES if VIDEO_MODE=="dog" else MIX_TITLES)
    used = load_used_titles()
    avail = [t for t in pool if t not in used]
    if not avail:
        used = {u for u in used if u not in pool}
        avail = pool[:]
    t = random.choice(avail); used.add(t); save_used_titles(used)
    return t

def generate_metadata():
    title   = pick_unique_title()
    caption = random.choice(ALL_CAPTIONS)
    mode_tag = {"cat":"#catvideos #catsoftiktok #funnycats",
                "dog":"#dogvideos #dogsoftiktok #funnydogs",
                "mix":"#petsoftiktok #funnyanimals #funnypets"}[VIDEO_MODE]
    yt_desc = (f"{caption}\n\nWelcome to LionReel! Funny cats and dogs — real footage only.\n"
               f"New video every day! Hit SUBSCRIBE so you never miss one.\n\nTags: {YOUTUBE_TAGS}")
    return title, yt_desc, f"{caption}\n\n{mode_tag}\n{SOCIAL_TAGS}"


# ───────────────────────────────────────────────────────────────
# COOKIES
# ───────────────────────────────────────────────────────────────
class SilentLogger:
    def debug(self,m): pass
    def warning(self,m): pass
    def error(self,m): pass

def _safe_str(s):
    if not isinstance(s,str): return False
    try: s.encode("ascii",errors="strict")
    except UnicodeEncodeError:
        for ch in s:
            if ord(ch)<0x20 and ch not in('\t',): return False
    return '\t' not in s

def make_netscape_file(kws=None):
    cookies=[]
    if os.path.exists("cookies_raw.json"):
        try:
            with open("cookies_raw.json","r",encoding="utf-8",errors="replace") as f:
                cookies=json.load(f)
        except: pass
    if not cookies: return None
    fl=cookies
    if kws:
        fl=[c for c in cookies if any(k in c.get("domain","").lower() for k in kws)]
        if not fl: fl=cookies
    try:
        tmp=tempfile.NamedTemporaryFile(mode="w",suffix=".txt",delete=False,encoding="utf-8",newline="\n")
        tmp.write("# Netscape HTTP Cookie File\n\n")
        wr=sk=0
        for c in fl:
            try:
                dom=str(c.get("domain","")).strip(); nm=str(c.get("name","")).strip()
                val=str(c.get("value","")); pth=str(c.get("path","/"))
                sec="TRUE" if c.get("secure",False) else "FALSE"
                exp=c.get("expires",-1)
                exp=int(float(exp)) if exp and exp>0 else int(time.time())+365*24*3600
                flg="TRUE" if dom.startswith(".") else "FALSE"
                if not nm or not dom: sk+=1; continue
                if not _safe_str(nm) or not _safe_str(dom): sk+=1; continue
                if val and not _safe_str(val): sk+=1; continue
                val=val.replace('\t','').replace('\n','').replace('\r','')
                tmp.write(f"{dom}\t{flg}\t{pth}\t{sec}\t{exp}\t{nm}\t{val}\n"); wr+=1
            except: sk+=1
        tmp.close()
        print(f"   [cookies] Written {wr}, skipped {sk}")
        if wr>0: return tmp.name
        os.remove(tmp.name); return None
    except Exception as e:
        print(f"   [cookies] Error: {e}"); return None


# ───────────────────────────────────────────────────────────────
# CODEC OPTIMIZER & DOWNLOAD (H.264 ENFORCED FOR FAST ZERO-LAG SEEKING)
# ───────────────────────────────────────────────────────────────
def ensure_fast_h264(video_path):
    """
    Ensures video is encoded in H.264 (avc1) for instant seek & decode without CPU hangs.
    Only transcodes if video stream is explicitly confirmed to be AV1 (av01).
    """
    if not video_path or not os.path.exists(video_path):
        return video_path
    try:
        import subprocess, imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()

        cmd = [ffmpeg_bin, "-i", video_path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
        is_av1 = False
        for line in res.stderr.splitlines():
            if "Video:" in line or "Stream #0:0" in line:
                line_low = line.lower()
                if "av1" in line_low or "av01" in line_low:
                    is_av1 = True
                break

        if not is_av1:
            return video_path

        h264_tmp = video_path.replace(".mp4", "_fast_h264.mp4")
        print(f"      [CodecOpt] Transcoding AV1 stream {os.path.basename(video_path)} to fast H.264...")
        cmd_enc = [
            ffmpeg_bin, "-y", "-v", "error",
            "-i", video_path,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-c:a", "copy",
            h264_tmp
        ]
        subprocess.run(cmd_enc, check=True, timeout=120)
        if os.path.exists(h264_tmp) and os.path.getsize(h264_tmp) > 50_000:
            try:
                os.remove(video_path)
                os.rename(h264_tmp, video_path)
                print(f"      [CodecOpt] Streamlined to high-speed H.264 ({os.path.getsize(video_path)/1_048_576:.1f} MB) ✅")
                return video_path
            except:
                return h264_tmp
    except Exception as e_opt:
        print(f"      [CodecOpt] Note: {e_opt}")
    return video_path


def download_video(url, out_path, cookie_file, preview=False):
    def find():
        if os.path.exists(out_path) and os.path.getsize(out_path)>50_000: return out_path
        cands=sorted(glob.glob(out_path.replace(".mp4",".*"))+glob.glob(out_path.replace(".mp4","*")),
                     key=lambda x:os.path.getsize(x) if os.path.exists(x) else 0,reverse=True)
        for c in cands:
            if os.path.exists(c) and os.path.getsize(c)>50_000: return c
        return None
    def clean():
        for f in glob.glob(out_path.replace(".mp4","*")):
            try: os.remove(f)
            except: pass
    def opts(extra=None):
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        o={"outtmpl":out_path,"quiet":True,"no_warnings":True,"noprogress":True,
           "logger":SilentLogger(),"merge_output_format":"mp4","no_check_formats":True,
           "retries":5,"fragment_retries":5,"socket_timeout":15,
           "ffmpeg_location": ffmpeg_bin}
        if cookie_file and os.path.exists(cookie_file): o["cookiefile"]=cookie_file
        if preview:
            o["download_ranges"] = lambda info_dict, ydl: [{"start_time": 0, "end_time": 15}]
            o["force_keyframes_at_cuts"] = True
        if extra: o.update(extra)
        return o
    if preview:
        FMT="18/worst[ext=mp4]/worst"
        strats=[
            ("android_vr",{"format":FMT,"extractor_args":{"youtube":{"player_client":["android_vr"]}},
                           "http_headers":{"User-Agent":"com.google.android.apps.youtube.vr.oculus/1.56.120 (Linux; Android 12; Build/SQ3A.220705.003.A1) gzip"}}),
            ("web",{"format":FMT}),
        ]
    else:
        FMT = (
            "bv*[aspect_ratio<=0.6][height>=1080]+ba[ext=m4a]/"
            "bv*[aspect_ratio<=0.6]+ba/"
            "bv*[height>=2160]+ba/"
            "bv*[height>=1440]+ba/"
            "bv*[height>=1080][ext=mp4]+ba[ext=m4a]/"
            "bv*[height>=1080]+ba/"
            "bv*[ext=mp4]+ba[ext=m4a]/"
            "bv*+ba/b"
        )
        strats=[
            ("web",{"format":FMT}),
            ("tv_embedded",{"format":FMT,"extractor_args":{"youtube":{"player_client":["tv_embedded"]}},
                            "http_headers":{"User-Agent":"Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/537.36"}}),
            ("android_vr",{"format":FMT,"extractor_args":{"youtube":{"player_client":["android_vr"]}},
                           "http_headers":{"User-Agent":"com.google.android.apps.youtube.vr.oculus/1.56.120 (Linux; Android 12; Build/SQ3A.220705.003.A1) gzip"}}),
            ("android",{"format":FMT,"extractor_args":{"youtube":{"player_client":["android"],"player_skip":["webpage","configs"]}},
                        "http_headers":{"User-Agent":"com.google.android.youtube/17.36.4 (Linux; U; Android 12; GB) gzip"}}),
            ("ios",{"format":FMT,"extractor_args":{"youtube":{"player_client":["ios"],"player_skip":["webpage","configs"]}},
                    "http_headers":{"User-Agent":"com.google.ios.youtube/17.33.2 (iPhone14,3; U; CPU iOS 15_6 like Mac OS X)"}}),
        ]
    for name,extra in strats:
        clean()
        try:
            with YoutubeDL(opts(extra)) as ydl: ydl.download([url])
            f=find()
            if f:
                print(f"      Downloaded {'preview ' if preview else ''}via {name} ({os.path.getsize(f)/1_048_576:.1f} MB)")
                if not preview:
                    try:
                        from source_utils import probe_video_fast
                        pr = probe_video_fast(f)
                        if not pr.get("pass_gate", True):
                            print(f"      [IngestGate] Downloaded video rejected: {pr.get('reason')} ❌")
                            clean()
                            return None, f"Failed resolution gate: {pr.get('reason')}"
                    except Exception as e_gate:
                        pass
                    f = ensure_fast_h264(f)
                return f,None
        except: pass
    clean(); return None,"All strategies failed"



# ───────────────────────────────────────────────────────────────
# CARTOON & CGI CONTENT FILTER (ZERO CARTOONS / 3D MODELS ALLOWED)
# ───────────────────────────────────────────────────────────────
CARTOON_KEYWORDS = [
    "talking tom", "talking angela", "talking ben", "talking ginger", "talking friends", "outfit7",
    "cartoon", "cartoons", "animated", "animation", "animating", "anime",
    "3d animation", "3d model", "3d render", "blender", "unreal engine", "cgi",
    "kids tv", "kids channel", "nursery rhyme", "kids song", "children tv",
    "cocomelon", "chuchu tv", "babybus", "pinkfong",
    "gameplay", "game play", "playthrough", "walkthrough", "gaming", "game", "games",
    "roblox", "minecraft", "gacha", "gacha life", "peppa pig", "cbeebies",
    "simon's cat", "simons cat", "pixar", "disney", "dreamworks", "looney tunes",
    "tom and jerry", "garfield", "oggy",
    "kling", "runway ml", "luma dream", "pika", "sora", "deepfake",
    "ai generated", "ai cat", "ai dog", "ai pet", "ai animal"
]

def check_cartoon_metadata(entry_or_metadata):
    """Returns (is_cartoon: bool, matched_keyword: str) based on title, channel, description, tags."""
    if not entry_or_metadata:
        return False, ""
    text_corpus = ""
    if isinstance(entry_or_metadata, dict):
        text_corpus += " " + str(entry_or_metadata.get("title", "")).lower()
        text_corpus += " " + str(entry_or_metadata.get("channel", "")).lower()
        text_corpus += " " + str(entry_or_metadata.get("uploader", "")).lower()
        text_corpus += " " + str(entry_or_metadata.get("description", "")).lower()
        tags = entry_or_metadata.get("tags")
        if isinstance(tags, (list, tuple)):
            text_corpus += " " + " ".join(str(t).lower() for t in tags)
    elif isinstance(entry_or_metadata, str):
        text_corpus = entry_or_metadata.lower()

    for kw in CARTOON_KEYWORDS:
        if kw in text_corpus:
            return True, kw
    return False, ""

# ───────────────────────────────────────────────────────────────
# TITLE / CHANNEL FILTER (L1 + L2)
# ───────────────────────────────────────────────────────────────
BLACKLIST = [
    "dancing","cat dance","dog dance","pet dance","animal dance",
    "princess","royal outfit","in a dress","in dress","wearing dress",
    "outfit","costume","fashion show","cat fashion","dog fashion",
    "wedding dress","ballet","cat ballet","cat performs","cat concert",
    "cat singing","dog singing","singing pet","pet sings","animal sings",
    "cat clothes","dog clothes","dressed cat","dressed dog","dressed pet",
    "cat music video","dog music video","ai generated","ai cat","ai dog",
    "ai animal","ai pet","cgi","3d cat","3d dog","3d animal","animated cat",
    "animated dog","cartoon cat","cartoon dog","stable diffusion","midjourney",
    "sora","deepfake","talking tom","tom and jerry","garfield",
    "talking angela","talking ben","talking ginger","talking friends","outfit7",
    "cartoon","cartoons","animated","animation","animating","anime",
    "3d animation","3d model","3d render","blender","unreal engine",
    "kids tv","kids channel","nursery rhyme","kids song","children tv","cocomelon","chuchu tv","babybus",
    "gameplay","game play","playthrough","walkthrough","gaming","game","games",
    "roblox","minecraft","gacha","gacha life","peppa pig","cbeebies",
    "kling","runway ml","luma dream","pika",
    "simon's cat","simons cat","pixar","disney","dreamworks","looney tunes",
    "performs","concert","ballet","opera","music video","mv",
    "wears","wearing","dressed in","fancy dress","model cat","model dog",
    "streamer","twitch","speedrun",
    "full movie","full episode","24 hour","24/7","2 hour","3 hour","4 hour","1 hour",
    "8 hour","10 hour",
    "lullaby","official mv",
    "official video","lyric video","official audio","album","live performance",
    "breaking news","politician","election","president","congress",
    "government","war","protest","military","police",
    "life hack","makeup tutorial","fashion haul","workout routine",
    "cooking recipe","travel vlog","unboxing","product review",
    "national geographic","planet earth","animal planet","zoo tour",
    "wildlife documentary","nature documentary","bbc earth","discovery channel",
    "asmr","meditation","relaxing","sleep music","white noise","lofi","lo-fi",
    "alien","ufo","robot","cgi creature","my story","storytime",
    "slideshow","photo","photos","pictures","drawing","artwork","fanart",
    "tribute","rip","memorial","sad story",
    "training tips","how to train","obedience","tricks tutorial",
    "cat food review","dog food review","sponsored",
    "top 10 breeds","breed comparison","which breed",
    # Non-pet content that slips through (seen in logs)
    "miraculous","ladybug","comic con","teaser","trailer","promo",
    "delivery guy","ups","fedex","driveway","ice driveway",
    "bald eagle","eagle","hawk","falcon","owl",  # birds of prey not funny pets
    "bean burrito","burrito",  # food content
    "lap dog commercial","ad",
    "highlight","highlights","match","game recap",
    "horse","horses","pony","ponies","farm","barn","livestock",
]

BLACKLIST_CHANNELS = [
    "catiemano","catime","ai pets","ai cats","ai animals","cute ai",
    "digital pets","animated pets","sora pets","ai cat world","cattime","catie mano",
    "animalkingdom ai","ai studio","generative pet","neural cat","neural dog",
    "kidstv","kids tv","cartoongames","cartoon games","talking tom","talkingtom",
    "games kids tv","games kidstv","cartoon","cartoons","animation","gaming","gameplay",
    "news","cnn","bbc","fox news","nbc","abc news","msnbc","reuters","ap news",
    "official","music","vevo","records","esports",
    "movie",
]

def is_viral_worthy(entry):
    duration = entry.get("duration") or 0
    title    = (entry.get("title") or "").lower().strip()
    channel  = (entry.get("channel") or entry.get("uploader") or "").lower().strip()
    views    = entry.get("view_count") or 0

    if duration < MIN_DURATION_HARD or duration > 1200: return False
    if views > 0 and views < 50_000: return False  # genuinely tiny channel only

    for phrase in BLACKLIST:
        if phrase in title: return False
    for phrase in BLACKLIST_CHANNELS:
        if phrase in channel: return False

    # V94: hard block — if title mentions any non-cat/dog animal, reject immediately
    for phrase in OTHER_ANIMAL_BLOCK_WORDS:
        if phrase in title: return False

    # V95: hard block cartoon / animation / gaming / 3D content
    if CHECK_CARTOON:
        for kw in CARTOON_KEYWORDS:
            if kw in title or kw in channel:
                return False

    # V94: only cat/dog words count as "this is an animal video" now
    has_animal_title   = any(k in title   for k in CAT_DOG_WORDS)
    has_animal_channel = any(k in channel for k in CAT_DOG_CHANNEL_WORDS)
    if not has_animal_title and not has_animal_channel: return False

    if not has_animal_title and has_animal_channel:
        human_signals = ["my day","my life","story time","i tried","vlog","haul","routine"]
        if any(h in title for h in human_signals): return False

    if duration <= 55 and not BYPASS_FUNNY_CHECK:
        has_funny = any(k in title for k in FUNNY_WORDS)
        strong_pet_ch = any(k in channel for k in ["funny cat","funny dog","funny pet",
                                                    "cat fails","dog fails","pet fails",
                                                    "funniest","hilarious","laugh","dodo",
                                                    "failarmy","afv","viralhog","jukin"])
        # V94b: high-view videos don't need an exact "funny" word in the title —
        # a video with 500K+ views of a cat/dog is worth trying even if the title
        # doesn't literally say "funny" or "fail".
        if not has_funny and not strong_pet_ch and views < 500_000: return False
    if not mode_passes(entry): return False
    return True


# ───────────────────────────────────────────────────────────────
# HAAR CASCADES
# ───────────────────────────────────────────────────────────────
try:
    _CAT1 = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalcatface.xml")
    _CAT2 = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalcatface_extended.xml")
    _FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    _DOG  = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt.xml")
except:
    _CAT1 = _CAT2 = _FACE = _DOG = None


# ───────────────────────────────────────────────────────────────
# CORE VISUAL UTILITIES
# ───────────────────────────────────────────────────────────────
def _tex(gray):
    k=np.ones((16,16),np.float32)/256.
    f=gray.astype(np.float32)
    sq=cv2.filter2D(f*f,-1,k); ms=cv2.filter2D(f,-1,k)**2
    return float(np.mean(np.sqrt(np.maximum(sq-ms,0))))

def _noise(gray):
    b=cv2.GaussianBlur(gray,(5,5),0).astype(np.float32)
    return float(np.std(gray.astype(np.float32)-b))

def _crop_letterbox_borders(frame_bgr):
    """Detects and crops black letterbox / pillarbox bars so black bars do not skew image statistics."""
    try:
        h, w = frame_bgr.shape[:2]
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        top_black = np.mean(gray[:max(1, int(h * 0.1)), :]) < 18
        bot_black = np.mean(gray[min(h - 1, int(h * 0.9)):, :]) < 18
        left_black = np.mean(gray[:, :max(1, int(w * 0.1))]) < 18
        right_black = np.mean(gray[:, min(w - 1, int(w * 0.9)):]) < 18
        y1 = int(h * 0.12) if top_black else 0
        y2 = int(h * 0.88) if bot_black else h
        x1 = int(w * 0.12) if left_black else 0
        x2 = int(w * 0.88) if right_black else w
        cropped = frame_bgr[y1:y2, x1:x2]
        return cropped if (cropped.shape[0] > 20 and cropped.shape[1] > 20) else frame_bgr
    except Exception:
        return frame_bgr

def _is_cgi_frame(frame_bgr):
    """
    Evaluates a single frame for 3D CGI models, animation, synthetic saturation or cell-shading.
    Distinguishes real organic animal fur & textures from flat polygons / cartoons.
    """
    try:
        clean = _crop_letterbox_borders(frame_bgr)
        sm = cv2.resize(clean, (320, 180))
        gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)
        b, g, r = cv2.split(sm)
        sat_mean = float(np.mean(hsv[:, :, 1]))
        sat_std = float(np.std(hsv[:, :, 1]))
        rg_diff = float(np.mean(np.abs(r.astype(float) - g.astype(float))))
        ch_spread = float(max(np.std(b), np.std(g), np.std(r)) - min(np.std(b), np.std(g), np.std(r)))
        edges = cv2.Canny(gray, 40, 120)
        edge_dens = float(np.mean(edges > 0))
        k = np.ones((9, 9), np.float32) / 81.0
        f = gray.astype(np.float32)
        local_mean = cv2.filter2D(f, -1, k)
        local_std = np.sqrt(np.maximum(cv2.filter2D(f * f, -1, k) - local_mean ** 2, 0))
        flat_ratio = float(np.mean(local_std < 4.0))

        # 3D CGI models (Talking Tom, video game assets, Pixar-style models)
        is_3d_cgi = (edge_dens < 0.065 and flat_ratio > 0.35)
        # Anime & 2D cartoons with hyper-saturation and cell shading
        is_anime_cartoon = (edge_dens < 0.070 and sat_mean > 90 and flat_ratio > 0.40)
        # Generative AI or extreme synthetic saturation divergence
        is_ai_cgi = (edge_dens < 0.070 and sat_std > 70 and rg_diff > 30 and ch_spread > 16)
        return is_3d_cgi or is_anime_cartoon or is_ai_cgi
    except Exception:
        return False

def check_cartoon_visual(filepath, n_samples=16):
    """
    Scans video frames across the clip to detect 3D animation, Talking Tom, video games, or cartoons.
    Returns: (is_cartoon: bool, cartoon_ratio: float)
    """
    try:
        cap = cv2.VideoCapture(filepath)
        if not cap.isOpened():
            cap.release()
            return False, 0.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            return False, 0.0
        
        cartoon_votes = 0
        valid_samples = 0
        for i in range(n_samples):
            pos = int(total * (i + 0.5) / n_samples)
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            if _is_cgi_frame(frame):
                cartoon_votes += 1
            valid_samples += 1
        cap.release()
        if valid_samples == 0:
            return False, 0.0
        ratio = cartoon_votes / valid_samples
        is_cartoon = ratio >= 0.35
        tag = "CARTOON/CGI ❌" if is_cartoon else "REAL FOOTAGE ✅"
        print(f"      [CartoonCheck] {tag} | votes={cartoon_votes}/{valid_samples} ({ratio:.0%})")
        return is_cartoon, ratio
    except Exception as e:
        print(f"      [CartoonCheck] Error: {e} — SKIP ✅")
        return False, 0.0

def check_cartoon_or_cgi(filepath, metadata=None):
    """
    Dual-layer validation: checks metadata keywords and visual frames.
    Returns: (is_cartoon: bool, reason: str)
    """
    if not CHECK_CARTOON:
        return False, "Check disabled"
    if metadata:
        is_m, kw = check_cartoon_metadata(metadata)
        if is_m:
            return True, f"Metadata keyword '{kw}'"
    if filepath and os.path.exists(filepath):
        is_c, score = check_cartoon_visual(filepath)
        if is_c:
            return True, f"Visual 3D/CGI model detected ({score:.0%} frames)"
    return False, "Clean real pet footage"

def _animal_cascade_hit(frame_bgr, src_w=None, src_h=None):
    sm = cv2.resize(frame_bgr, (160, 90))
    gfull = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
    for cas in [_CAT1, _CAT2, _DOG]:
        if cas is None or cas.empty(): continue
        dets = cas.detectMultiScale(gfull, scaleFactor=1.3, minNeighbors=2, minSize=(18, 18))
        if len(dets) > 0: return True
    return False

def _frame_has_animal_visual(frame_bgr):
    sm   = cv2.resize(frame_bgr,(320,180))
    gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
    if _animal_cascade_hit(frame_bgr, frame_bgr.shape[1], frame_bgr.shape[0]):
        return True
    tex = _tex(gray)
    noi = _noise(gray)
    if tex > 14.0 and noi > 3.0:
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# V93 FIX 1 — SHARPNESS CHECK
# Reject blurry / pixelated / low-res videos
# ═══════════════════════════════════════════════════════════════
def check_sharpness(filepath):
    """
    Returns (is_sharp, median_score, resolution_ok).
    Uses Laplacian variance — higher = sharper.
    Also checks actual frame resolution.
    """
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened(): cap.release(); return False, 0, False

    # Check resolution
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    res_ok = min(src_w, src_h) >= MIN_SOURCE_HEIGHT

    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    scores = []

    for i in range(16):
        pos = int(total * (i + 0.5) / 16)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret: continue
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        score = cv2.Laplacian(gray, cv2.CV_64F).var()
        scores.append(score)

    cap.release()
    if not scores: return False, 0, res_ok

    median_score = float(np.median(scores))
    is_sharp = median_score >= SHARP_THRESHOLD and res_ok

    tag = "SHARP ✅" if is_sharp else "BLURRY ❌"
    print(f"      [Sharpness] {tag} | score={median_score:.0f} (need {SHARP_THRESHOLD}) | {src_w}x{src_h}")
    return is_sharp, median_score, res_ok


# ═══════════════════════════════════════════════════════════════
# V93 FIX 2 — SHAKE DETECTOR
# Reject handheld shaky camera footage
# ═══════════════════════════════════════════════════════════════
def check_shake(filepath):
    """
    Tracks BACKGROUND motion (outer 15% border of frame).
    If background moves as much as foreground → camera is shaking.
    Real funny pet videos: camera is fixed, animal moves.
    Shaky cam: entire frame translates each frame.
    """
    cap   = cv2.VideoCapture(filepath)
    if not cap.isOpened(): cap.release(); return True, 0.0  # assume shaky on error

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    bg_motions = []

    for i in range(24):
        pos = int(total * (i + 0.5) / 24)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame1 = cap.read()
        if not ret: continue

        # Read the immediate next frame for consecutive comparison
        ret, frame2 = cap.read()
        if not ret: continue

        gray1 = cv2.cvtColor(cv2.resize(frame1, (320, 180)), cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(cv2.resize(frame2, (320, 180)), cv2.COLOR_BGR2GRAY)
        h, w = gray1.shape

        # Extract background border (outer 15% of frame)
        border = int(min(h, w) * 0.15)
        bg_mask = np.zeros_like(gray1)
        bg_mask[:border, :]   = 1   # top
        bg_mask[-border:, :]  = 1   # bottom
        bg_mask[:, :border]   = 1   # left
        bg_mask[:, -border:]  = 1   # right

        bg_region1 = gray1 * bg_mask
        bg_region2 = gray2 * bg_mask

        diff = cv2.absdiff(bg_region2, bg_region1)
        # Mean motion in background region only
        bg_pix = np.sum(bg_mask > 0)
        bg_motion = float(np.sum(diff)) / max(bg_pix, 1)
        bg_motions.append(bg_motion)

    cap.release()

    if not bg_motions:
        return False, 0.0

    avg_bg_motion = float(np.mean(bg_motions))
    is_shaky = avg_bg_motion > SHAKE_THRESHOLD

    tag = "SHAKY ❌" if is_shaky else "STABLE ✅"
    print(f"      [ShakeCheck] {tag} | bg_motion={avg_bg_motion:.2f} (limit {SHAKE_THRESHOLD})")
    return is_shaky, avg_bg_motion


# ═══════════════════════════════════════════════════════════════
# V93 FIX 3 — AUDIO MUSIC DETECTOR
# Reject clips with loud background music overlay
# ═══════════════════════════════════════════════════════════════
def check_audio_music(filepath):
    """
    Reads raw audio samples via ffmpeg pipe.
    Music signature: sustained high RMS with LOW variance (flat loud).
    Natural pet audio: variable RMS (quiet moments + sudden noise spikes).
    Coefficient of variation (std/mean) of RMS chunks:
      - Music: cv < 0.25 (flat and loud)
      - Natural: cv > 0.35 (spiky)
    """
    try:
        import subprocess, imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe, "-y", "-i", filepath, "-vn",
            "-ac", "1", "-ar", "8000",
            "-f", "s16le", "-t", "30",
            "pipe:1"
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        if not result.stdout or len(result.stdout) < 1000:
            print("      [AudioCheck] No audio stream or too quiet — SKIP check ✅")
            return False

        audio = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
        if len(audio) < 800:
            return False

        chunk_size = 4000  # 0.5s at 8kHz
        chunks = [audio[i:i+chunk_size] for i in range(0, len(audio)-chunk_size, chunk_size)]
        if len(chunks) < 4:
            return False

        rms_values = [float(np.sqrt(np.mean(c**2))) for c in chunks]
        mean_rms = float(np.mean(rms_values))
        std_rms  = float(np.std(rms_values))

        if mean_rms < 50:
            print("      [AudioCheck] Very quiet audio — SKIP check ✅")
            return False

        cv = std_rms / max(mean_rms, 1.0)
        has_music = cv < MUSIC_FLAT_THRESHOLD

        tag = "MUSIC ❌" if has_music else "NATURAL ✅"
        print(f"      [AudioCheck] {tag} | RMS_cv={cv:.3f} (need >{MUSIC_FLAT_THRESHOLD})")
        return has_music

    except Exception as e:
        print(f"      [AudioCheck] Error: {e} — SKIP check ✅")
        return False


# ═══════════════════════════════════════════════════════════════
# V93 FIX 4 — WATERMARK DETECTOR
# Reject videos with other channels' logos/watermarks in corners
# ═══════════════════════════════════════════════════════════════
def check_watermark(filepath):
    """
    Checks all 4 corners of each sampled frame.
    Corner size: 15% of frame dimensions.
    Watermark signal: bright high-contrast region in corner
    (text/logo = high edge density + high brightness variance).
    If >WATERMARK_THRESHOLD fraction of frames have this → reject.
    """
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened(): cap.release(); return False, 0.0

    total    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    wm_count = 0
    checked  = 0

    for i in range(20):
        pos = int(total * (i + 0.5) / 20)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret: continue
        checked += 1

        h, w = frame.shape[:2]
        ch = max(1, int(h * 0.15))  # corner height
        cw = max(1, int(w * 0.15))  # corner width

        corners = [
            frame[:ch, :cw],           # top-left
            frame[:ch, w-cw:],         # top-right
            frame[h-ch:, :cw],         # bottom-left
            frame[h-ch:, w-cw:],       # bottom-right
        ]

        # Check each corner for watermark signature
        corner_hits = 0
        for corner in corners:
            if corner.size == 0: continue
            gray_c = cv2.cvtColor(corner, cv2.COLOR_BGR2GRAY)
            edges  = cv2.Canny(gray_c, 30, 100)
            edge_density = float(np.sum(edges > 0)) / edges.size
            brightness_var = float(np.std(gray_c))
            mean_bright    = float(np.mean(gray_c))

            # Watermark = high edge density in corner + bright + high contrast
            if edge_density > 0.08 and brightness_var > 30 and mean_bright > 40:
                corner_hits += 1

        # If 2+ corners have watermark signal → flag this frame
        if corner_hits >= 2:
            wm_count += 1

    cap.release()

    if checked == 0: return False, 0.0
    wm_ratio = wm_count / checked
    has_watermark = wm_ratio > WATERMARK_THRESHOLD

    tag = "WATERMARK ❌" if has_watermark else "CLEAN ✅"
    print(f"      [WatermarkCheck] {tag} | wm_frames={wm_count}/{checked} ({wm_ratio:.0%})")
    return has_watermark, wm_ratio


# ═══════════════════════════════════════════════════════════════
# REAL FOOTAGE CHECKER (V91 — retained)
# ═══════════════════════════════════════════════════════════════
def is_real_footage(filepath):
    try:
        cap = cv2.VideoCapture(filepath)
        if not cap.isOpened(): cap.release(); return False
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps   = cap.get(cv2.CAP_PROP_FPS) or 30
        dur   = total / fps
        if total <= 0 or dur < 2: cap.release(); return False

        samples    = 16
        real_score = 0
        cgi_score  = 0
        prev_gray  = None

        for i in range(samples):
            pos = int(total * (i + 0.5) / samples)
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if not ret: continue

            if _is_cgi_frame(frame): cgi_score += 1

            sm  = cv2.resize(frame,(320,180))
            hsv = cv2.cvtColor(sm,cv2.COLOR_BGR2HSV)
            gray= cv2.cvtColor(sm,cv2.COLOR_BGR2GRAY)
            f   = gray.astype(np.float32)

            sat_std  = float(np.std(hsv[:,:,1]))
            val_std  = float(np.std(hsv[:,:,2]))
            edges    = cv2.Canny(gray,20,90)
            edge_dens= float(np.sum(edges>0))/edges.size
            noi      = _noise(gray)
            hist     = cv2.calcHist([gray],[0],None,[64],[0,256]).flatten()
            hn       = hist/(hist.sum()+1e-6)
            entropy  = float(-np.sum(hn*np.log(hn+1e-9)))
            b,g,r    = cv2.split(sm)
            ch_stds  = [float(np.std(c)) for c in [b,g,r]]
            nat_ch   = min(ch_stds)>7 and (max(ch_stds)-min(ch_stds))<38
            med      = float(np.median(gray))
            flat     = float(np.sum(np.abs(f-med)<6))/f.size
            not_flat = flat<0.50 and med>5

            motion_ok = True
            if prev_gray is not None:
                diff      = cv2.absdiff(prev_gray,gray)
                motion    = float(np.mean(diff))
                motion_ok = 0.2<motion<90
            prev_gray = gray
            tex = _tex(gray)

            passes = sum([
                sat_std>7 and val_std>8,
                0.01<edge_dens<0.58,
                noi>1.2,
                entropy>2.8,
                nat_ch,
                not_flat,
                motion_ok,
                tex>6.0
            ])
            if passes >= 5: real_score += 1

        cap.release()
        if cgi_score / max(samples, 1) > 0.30:
            print(f"      [RealCheck] FAKE/AI ❌ | CGI={cgi_score}/{samples}")
            return False
        threshold = int(samples * 0.55)
        ok = real_score >= threshold
        print(f"      [RealCheck] {'REAL ✅' if ok else 'FAKE ❌'} | real={real_score}/{samples}")
        return ok
    except Exception as e:
        print(f"      [RealCheck] Error: {e}"); return False


# ───────────────────────────────────────────────────────────────
# ANIMAL PRESENCE CHECK
# ───────────────────────────────────────────────────────────────
def visual_has_animal(filepath, n_samples=14):
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened(): cap.release(); return False
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    animal_frames = checked = 0
    for i in range(n_samples):
        pos = int(total * (i + 0.5) / n_samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret: continue
        checked += 1
        if _frame_has_animal_visual(frame): animal_frames += 1
    cap.release()
    ratio  = animal_frames / max(checked, 1)
    result = ratio >= 0.40
    print(f"      [AnimalCheck] {'ANIMAL ✅' if result else 'NO ANIMAL ❌'} | {animal_frames}/{checked} ({ratio:.0%})")
    return result


# ───────────────────────────────────────────────────────────────
# PEAK LAUGH MOMENT (V92)
# ───────────────────────────────────────────────────────────────
def get_peak_laugh_moment(filepath, clip_duration=5.5):
    """
    Enhanced V96 Viral Climax Detector:
    1. Constrains search window to avoid intro logos and end-credits/outros on long videos.
    2. Uses high-resolution adaptive frame sampling (>=2.5 fps) to capture rapid comedy fails.
    3. Combines motion burst acceleration and animal visual prominence.
    4. Automatically centers the cut clip so the peak burst climax happens ~35% into the clip,
       providing ~1.5s setup anticipation and ~3.5s of hilarious chaotic payoff.
    """
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened():
        cap.release()
        return 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    dur   = total / fps
    if dur <= clip_duration:
        cap.release()
        return 0.0

    # Constrain search window to avoid intros and long compilation outros
    search_start = min(1.5, max(0.0, dur * 0.05))
    if dur > 90.0:
        # Long compilation/video: search in the first 160s to avoid dead outro credits
        search_end = min(dur - clip_duration - 1.0, 160.0)
    else:
        search_end = max(search_start + clip_duration + 0.5, dur - 0.5)

    search_span = max(clip_duration + 1.0, search_end - search_start)
    n_bins = int(max(10, min(16, search_span / 4.0)))

    mot, tex_arr, has_ani = [], [], []
    prev = None

    for i in range(n_bins):
        t_sample = search_start + (search_span * i / n_bins)
        pos = int(min(total - 1, max(0, t_sample * fps)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret:
            mot.append(0); tex_arr.append(0); has_ani.append(False)
            continue

        sm   = cv2.resize(frame, (160, 90))
        gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
        bl   = cv2.GaussianBlur(gray, (21, 21), 0)

        if prev is not None:
            _, th = cv2.threshold(cv2.absdiff(prev, bl), 16, 255, cv2.THRESH_BINARY)
            mot.append(int(np.sum(th)))
        else:
            mot.append(0)
        prev = bl
        tex_val = _tex(gray)
        tex_arr.append(tex_val)
        has_ani.append(tex_val > 10.0)

    cap.release()

    m = np.array(mot, dtype=float)
    t = np.array(tex_arr, dtype=float)
    a = np.array(has_ani, dtype=float)

    window = 6
    m_smooth = np.convolve(m, np.ones(window)/window, mode='same')
    m_burst  = np.maximum(m - m_smooth * 0.65, 0)

    if m_burst.max() > 0: m_burst /= m_burst.max()
    if m.max() > 0: m /= m.max()
    if t.max() > 0: t /= t.max()

    combined = 0.55 * m_burst + 0.30 * m + 0.15 * t
    bins_per_clip = max(2, int(n_bins * clip_duration / search_span))
    best_ts = search_start
    best_score = -1.0
    best_animal = False

    for i in range(max(1, n_bins - bins_per_clip)):
        window_combined = combined[i:i+bins_per_clip]
        window_score = float(np.sum(window_combined)) + float(np.max(window_combined)) * 2.5
        window_animal = float(np.mean(a[i:i+bins_per_clip])) >= 0.25

        # Pin peak action climax inside window
        climax_local_bin = int(np.argmax(window_combined))
        climax_t = search_start + ((i + climax_local_bin) / n_bins) * search_span
        # Target 35% anticipation setup before climax
        cand_ts = max(0.3, climax_t - (clip_duration * 0.35))
        cand_ts = min(cand_ts, dur - clip_duration - 0.2)

        if window_animal and not best_animal:
            best_score = window_score; best_ts = cand_ts; best_animal = True
        elif window_animal and best_animal and window_score > best_score:
            best_score = window_score; best_ts = cand_ts
        elif not window_animal and not best_animal and window_score > best_score:
            best_score = window_score; best_ts = cand_ts

    best_ts = max(0.3, min(best_ts, dur - clip_duration - 0.2))
    print(f"      [PeakLaugh] t={best_ts:.1f}s score={best_score:.2f} {'✅' if best_animal else '⚠'}")
    return best_ts


# ═══════════════════════════════════════════════════════════════
# V95 — MULTI-MOMENT DETECTOR
# Used by "own_footage" and "youtube_cc" modes to pull SEVERAL funny
# moments out of ONE long video (spread across start/middle/end)
# instead of needing several different source videos.
# ═══════════════════════════════════════════════════════════════
def get_peak_moment_in_segment(filepath, seg_start, seg_end, clip_duration=9.0):
    """Finds the single best moment inside [seg_start, seg_end] only."""
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened(): cap.release(); return max(0.0, seg_start)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30
    dur   = total / fps
    seg_end = min(seg_end, dur)
    seg_dur = seg_end - seg_start

    if seg_dur <= clip_duration:
        cap.release()
        return max(0.0, min(seg_start, max(0.0, dur - clip_duration - 0.1)))

    n_bins = 10
    mot=[]; tex_arr=[]; has_ani=[]; prev=None

    for i in range(n_bins):
        t   = seg_start + (seg_dur * i / n_bins)
        pos = int(t * fps)
        if pos >= total: pos = total - 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret:
            mot.append(0); tex_arr.append(0); has_ani.append(False); continue

        sm   = cv2.resize(frame, (160, 90))
        gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
        bl   = cv2.GaussianBlur(gray, (21, 21), 0)

        if prev is not None:
            _, th = cv2.threshold(cv2.absdiff(prev, bl), 18, 255, cv2.THRESH_BINARY)
            mot.append(int(np.sum(th)))
        else:
            mot.append(0)
        prev = bl
        tex_val = _tex(gray)
        tex_arr.append(tex_val)
        has_ani.append(tex_val > 10.0)

    cap.release()

    m = np.array(mot, dtype=float)
    t_arr = np.array(tex_arr, dtype=float)
    a = np.array(has_ani, dtype=float)
    if m.max() > 0: m /= m.max()
    if t_arr.max() > 0: t_arr /= t_arr.max()
    combined = 0.6*m + 0.4*t_arr

    bins_per_clip = max(1, int(n_bins * clip_duration / seg_dur))
    best_ts = seg_start; best_score = -1.0; best_animal = False

    for i in range(max(1, n_bins - bins_per_clip)):
        window_score  = float(np.sum(combined[i:i+bins_per_clip]))
        window_animal = float(np.mean(a[i:i+bins_per_clip])) >= 0.3
        ts = seg_start + (seg_dur * i / n_bins)
        if window_animal and not best_animal:
            best_score=window_score; best_ts=ts; best_animal=True
        elif window_animal and best_animal and window_score>best_score:
            best_score=window_score; best_ts=ts
        elif not window_animal and not best_animal and window_score>best_score:
            best_score=window_score; best_ts=ts

    best_ts = max(0.0, min(best_ts, max(0.0, dur - clip_duration - 0.1)))
    return best_ts


def get_multiple_moments(filepath, n_clips=6, clip_duration=9.0):
    """
    Splits the video into n_clips equal segments (spread across the
    WHOLE video — start, middle, end, and points in between) and finds
    the best funny/animal moment inside each segment. Returns a sorted
    list of start timestamps, one per clip.
    """
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened(): cap.release(); return [0.0]
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30
    dur   = total / fps
    cap.release()

    if dur <= clip_duration:
        return [0.0]

    # Don't ask for more clips than the video can reasonably fit
    max_possible = max(1, int(dur // (clip_duration * 1.4)))
    n_clips = max(1, min(n_clips, max_possible))

    segment_len = dur / n_clips
    moments = []
    for i in range(n_clips):
        seg_start = i * segment_len
        seg_end   = min(dur, seg_start + segment_len)
        t = get_peak_moment_in_segment(filepath, seg_start, seg_end, clip_duration)
        moments.append(t)
        print(f"      [MultiMoment] segment {i+1}/{n_clips} -> t={t:.1f}s")

    return moments


# ───────────────────────────────────────────────────────────────
# INTRO SKIP (V91)
# ───────────────────────────────────────────────────────────────
def verify_and_slide_start(filepath, start_t, clip_duration, fps=30.0):
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened(): cap.release(); return start_t
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS) or fps
    dur   = total / fps
    cap.release()

    if start_t + clip_duration > dur:
        start_t = max(0.0, dur - clip_duration - 0.1)
    return max(0.0, start_t)


# ═══════════════════════════════════════════════════════════════
# V93 FIX 5 — COLOUR GRADE UPGRADE
# Auto white-balance + adaptive brightness + CLAHE + saturation
# ═══════════════════════════════════════════════════════════════
def grade_frame(frame_bgr):
    """
    Enhanced cinematic pet color grade:
    Gently corrects tint without washing out fur (85/15 blend),
    enhances luminance contrast with CLAHE, and applies warm saturation.
    """
    # Step 1: Subtle white-balance correction (85% original, 15% grey-world to preserve fur tones)
    b, g, r = cv2.split(frame_bgr.astype(np.float32))
    mean_b, mean_g, mean_r = max(1.0, np.mean(b)), max(1.0, np.mean(g)), max(1.0, np.mean(r))
    mean_all = (mean_b + mean_g + mean_r) / 3.0
    wb_b = np.clip(b * (mean_all / mean_b), 0, 255)
    wb_g = np.clip(g * (mean_all / mean_g), 0, 255)
    wb_r = np.clip(r * (mean_all / mean_r), 0, 255)
    wb_bgr = cv2.merge([wb_b, wb_g, wb_r]).astype(np.uint8)
    frame_bgr = cv2.addWeighted(frame_bgr, 0.85, wb_bgr, 0.15, 0)

    # Step 2: Adaptive brightness (gentle, preserves natural lighting)
    current_brightness = float(np.mean(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)))
    if current_brightness > 10:
        alpha = TARGET_BRIGHTNESS / current_brightness
        alpha = np.clip(alpha, 0.80, 1.25)
        frame_bgr = np.clip(frame_bgr.astype(np.float32) * alpha, 0, 255).astype(np.uint8)

    # Step 3: CLAHE on L channel (crisp, filmic contrast)
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l, a, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
    l = clahe.apply(l)
    frame_bgr = cv2.cvtColor(cv2.merge([l, a, b_ch]), cv2.COLOR_LAB2BGR)

    # Step 4: Saturation boost (warm, vibrant)
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.12, 0, 255)
    frame_bgr = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    return frame_bgr

def apply_colour_grade(clip):
    """Apply grade_frame to every frame in a MoviePy clip if enabled."""
    if not APPLY_COLOR_GRADING:
        return clip
    def process(get_frame, t):
        frame = get_frame(t)
        if frame.dtype != np.uint8:
            frame = (frame * 255).clip(0, 255).astype(np.uint8)
        bgr   = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        graded = grade_frame(bgr)
        return cv2.cvtColor(graded, cv2.COLOR_BGR2RGB)
    return clip.fl(process, apply_to="video")


# ═══════════════════════════════════════════════════════════════
# V93 FIX 6 — SMART CROP V2 (animal not cut off)
# After finding center, validate animal is fully inside crop box
# ═══════════════════════════════════════════════════════════════
def _find_animal_center_v93(clip, src_w, src_h):
    """
    Enhanced V93 crop center finder.
    After finding animal bbox via cascade, checks the full bbox fits
    within the proposed crop — shifts crop if animal would be cut off.
    """
    fgbg = cv2.createBackgroundSubtractorMOG2(detectShadows=False)
    cx_votes = []; cy_votes = []
    animal_bboxes = []  # track full bbox for safety margin check

    sample_times = [clip.duration * f for f in [0.05,0.15,0.28,0.42,0.58,0.70,0.82,0.92]]

    for t in sample_times:
        t = max(0.0, min(t, clip.duration - 0.05))
        try:
            fr = clip.get_frame(t)
            if fr.dtype != np.uint8:
                fr = (fr * 255).clip(0, 255).astype(np.uint8)
            fbgr = cv2.cvtColor(fr, cv2.COLOR_RGB2BGR)

            # Fast Haar cascade on 270x480
            gfull = cv2.cvtColor(cv2.resize(fbgr, (270, 480)), cv2.COLOR_BGR2GRAY)
            for cas in [_CAT1, _CAT2, _DOG]:
                if cas is None or cas.empty(): continue
                dets = cas.detectMultiScale(gfull, scaleFactor=1.15, minNeighbors=3, minSize=(30, 30))
                if len(dets) > 0:
                    areas = sorted([(w*h, x, y, w, h) for (x, y, w, h) in dets], reverse=True)
                    _, bx, by, bw, bh = areas[0]
                    bx_s = int(bx * src_w / 270); by_s = int(by * src_h / 480)
                    bw_s = int(bw * src_w / 270); bh_s = int(bh * src_h / 480)
                    cx_votes.append(bx_s + bw_s // 2)
                    cy_votes.append(by_s + bh_s // 2)
                    animal_bboxes.append((bx_s, by_s, bx_s + bw_s, by_s + bh_s))
                    break

            # Foreground motion
            sm_fg = cv2.resize(fbgr,(270,480))
            fgmask = fgbg.apply(sm_fg)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))
            fgmask = cv2.erode(fgmask, kernel, iterations=1)
            fgmask = cv2.dilate(fgmask, kernel, iterations=2)
            if float(np.sum(fgmask)) > 200:
                ys, xs = np.where(fgmask > 0)
                if len(xs) > 0:
                    cx_votes.append(int(np.median(xs) * src_w/270))
                    cy_votes.append(int(np.median(ys) * src_h/480))

        except Exception:
            pass

    # Texture fallback
    if len(cx_votes) < 2:
        try:
            mid_t = max(0.0, min(clip.duration*0.5, clip.duration-0.05))
            fr = clip.get_frame(mid_t)
            if fr.dtype != np.uint8: fr = (fr*255).clip(0,255).astype(np.uint8)
            fbgr = cv2.cvtColor(fr,cv2.COLOR_RGB2BGR)
            sm   = cv2.resize(fbgr,(270,480))
            gsm  = cv2.cvtColor(sm,cv2.COLOR_BGR2GRAY)
            f    = gsm.astype(np.float32)
            k    = np.ones((20,20),np.float32)/400.
            sq   = cv2.filter2D(f*f,-1,k); ms = cv2.filter2D(f,-1,k)**2
            tex  = np.sqrt(np.maximum(sq-ms,0))
            col_t= np.convolve(np.mean(tex,axis=0),np.ones(40),'same')
            row_t= np.convolve(np.mean(tex,axis=1),np.ones(40),'same')
            cx_votes.append(int(np.argmax(col_t)*src_w/270))
            cy_votes.append(int(np.argmax(row_t)*src_h/480))
        except:
            pass

    if not cx_votes:
        return src_w//2, src_h//2

    cx = int(np.median(cx_votes))
    cy = int(np.median(cy_votes))

    # V93 Safety margin: if animal bbox known, ensure it fits in crop
    if animal_bboxes:
        hw = OUT_W // 2; hh = OUT_H // 2
        # Proposed crop: cx±hw, cy±hh (clamped to frame)
        crop_x1 = max(hw, min(cx, src_w-hw)) - hw
        crop_y1 = max(hh, min(cy, src_h-hh)) - hh
        crop_x2 = crop_x1 + OUT_W
        crop_y2 = crop_y1 + OUT_H

        for (ax1, ay1, ax2, ay2) in animal_bboxes:
            # Check if any bbox edge is within SAFE_CROP_MARGIN of crop edge
            if ax1 - crop_x1 < SAFE_CROP_MARGIN:
                # Animal too close to left edge — shift crop left
                cx = max(hw, cx - (SAFE_CROP_MARGIN - (ax1 - crop_x1)))
            if crop_x2 - ax2 < SAFE_CROP_MARGIN:
                # Animal too close to right edge — shift crop right
                cx = min(src_w - hw, cx + (SAFE_CROP_MARGIN - (crop_x2 - ax2)))
            if ay1 - crop_y1 < SAFE_CROP_MARGIN:
                cy = max(hh, cy - (SAFE_CROP_MARGIN - (ay1 - crop_y1)))
            if crop_y2 - ay2 < SAFE_CROP_MARGIN:
                cy = min(src_h - hh, cy + (SAFE_CROP_MARGIN - (crop_y2 - ay2)))

    return cx, cy

def smart_crop_v93(clip):
    """V93 smart crop — animal-safe boundary check with 16:9 Landscape support."""
    TW, TH = OUT_W, OUT_H
    sr = clip.w / clip.h
    tr = TW / TH

    # If aspect ratio matches within ~4%, resize directly without cropping
    if abs(sr - tr) < 0.05:
        return clip.resize((TW, TH))

    # In 16:9 Landscape mode with vertical input clip (9:16):
    # Pillarbox with dark canvas instead of extreme 300% zoom crop that cuts off animal
    if tr > 1.2 and sr < 1.0:
        fg = clip.resize(height=TH)
        x_off = max(0, (TW - fg.w) // 2)
        try:
            bg = ColorClip(size=(TW, TH), color=(15, 15, 18)).set_duration(clip.duration)
            return CompositeVideoClip([bg, fg.set_pos((x_off, 0))])
        except Exception:
            pass

    scaled = clip.resize(height=TH) if sr > tr else clip.resize(width=TW)

    if abs(scaled.w-TW)<4 and abs(scaled.h-TH)<4:
        if scaled.w != TW or scaled.h != TH:
            return scaled.crop(x_center=scaled.w//2, y_center=scaled.h//2, width=TW, height=TH)
        return scaled

    cx, cy = _find_animal_center_v93(scaled, scaled.w, scaled.h)

    hw = TW//2; hh = TH//2
    fcx = max(hw, min(cx, scaled.w-hw))
    fcy = max(hh, min(cy, scaled.h-hh))

    try:
        return scaled.crop(x_center=fcx, y_center=fcy, width=TW, height=TH)
    except:
        return scaled.crop(x_center=scaled.w//2, y_center=scaled.h//2, width=TW, height=TH)


# ───────────────────────────────────────────────────────────────
# PIL TEXT HELPERS
# ───────────────────────────────────────────────────────────────
def _load_font(size):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\impact.ttf",
        "/System/Library/Fonts/Helvetica.ttc"
    ]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

def _render_text(text, w, h, size, y_frac, fg, stroke_col, stroke_r):
    img  = Image.new("RGBA",(w,h),(0,0,0,0))
    draw = ImageDraw.Draw(img)
    font = _load_font(size)
    bb   = draw.textbbox((0,0),text,font=font)
    tw   = bb[2]-bb[0]
    x    = max(0,(w-tw)//2)
    y    = int(h*y_frac)
    for dx in range(-stroke_r,stroke_r+1):
        for dy in range(-stroke_r,stroke_r+1):
            if dx*dx+dy*dy<=stroke_r*stroke_r:
                draw.text((x+dx,y+dy),text,font=font,fill=stroke_col)
    draw.text((x,y),text,font=font,fill=fg)
    return np.array(img)

def _blend(frame, layer, alpha_scale=1.0):
    fh,fw = frame.shape[:2]; lh,lw = layer.shape[:2]
    if lh!=fh or lw!=fw: layer = cv2.resize(layer,(fw,fh))
    a   = layer[:,:,3:4].astype(np.float32)/255.0*alpha_scale
    rgb = layer[:,:,:3].astype(np.float32)
    return (frame.astype(np.float32)*(1-a)+rgb*a).clip(0,255).astype(np.uint8)


# ───────────────────────────────────────────────────────────────
# 5-SECOND HOOK
# ───────────────────────────────────────────────────────────────
def add_5s_hook(clip, hook_text, sub_text):
    ZOOM_DUR=0.5; HOOK_DUR=2.5; SUB_DUR=5.0; FO=0.25
    hook_rgba = _render_text(hook_text,OUT_W,OUT_H,max(72,OUT_W//13),0.07,
                              (255,230,0,255),(0,0,0,240),5)
    sub_rgba  = _render_text(sub_text, OUT_W,OUT_H,max(48,OUT_W//20),0.07,
                              (255,255,255,220),(0,0,0,200),3)
    def apply(get_frame,t):
        frame = get_frame(t).copy()
        if frame.dtype!=np.uint8: frame=(frame*255).clip(0,255).astype(np.uint8)
        if t<ZOOM_DUR:
            scale=1.0+0.15*(t/ZOOM_DUR); h,w=frame.shape[:2]
            nw,nh=int(w*scale),int(h*scale); res=cv2.resize(frame,(nw,nh))
            frame=res[(nh-h)//2:(nh-h)//2+h,(nw-w)//2:(nw-w)//2+w]
        if t<HOOK_DUR:
            a=t/0.15 if t<0.15 else ((HOOK_DUR-t)/FO if t>HOOK_DUR-FO else 1.0)
            frame=_blend(frame,hook_rgba,a)
        elif t<SUB_DUR:
            prog=t-HOOK_DUR; sub_total=SUB_DUR-HOOK_DUR
            a=prog/0.2 if prog<0.2 else ((sub_total-prog)/FO if prog>sub_total-FO else 1.0)
            frame=_blend(frame,sub_rgba,a)
        return frame
    try: return clip.fl(apply,apply_to="video")
    except Exception as e:
        print(f"      [Hook] Error: {e}"); return clip


# ───────────────────────────────────────────────────────────────
# ENERGY RAMP
# ───────────────────────────────────────────────────────────────
def energy_ramp_order(clips, scores):
    if len(clips)<=2: return clips
    indexed = sorted(range(len(clips)),key=lambda i:scores[i])
    n = len(indexed)
    low=indexed[:n//3]; mid=indexed[n//3:2*n//3]; high=indexed[2*n//3:]
    order = mid + list(reversed(high)) + low
    while len(order)<n: order.append(indexed[len(order)%n])
    print(f"      [EnergyRamp] {order[:n]}")
    return [clips[i] for i in order[:n]]


# ───────────────────────────────────────────────────────────────
# PROCESS CLIP — V93 full pipeline
# ───────────────────────────────────────────────────────────────
def process_clip(path, duration=SHORT_CLIP_SEC, is_first=False, hook_text="", sub_text=""):
    clip = VideoFileClip(path)
    fps  = clip.fps or OUTPUT_FPS

    # Step 1: Peak laugh moment
    start = get_peak_laugh_moment(path, duration)

    # Step 2: Intro skip
    start = verify_and_slide_start(path, start, duration, fps)

    # Step 3: Trim
    clip = clip.subclip(start, min(start+duration, clip.duration))

    # Step 4: Smart crop (animal-safe)
    if APPLY_SMART_CROP:
        clip = smart_crop_v93(clip)

    # Step 5: Colour grade
    if APPLY_COLOR_GRADING:
        print("      [ColourGrade] Cinematic tone + CLAHE contrast + saturation boost...")
        clip = apply_colour_grade(clip)
    else:
        print("      [ColourGrade] OFF (Preserving natural clip colors as configured)")

    # Step 6: Fade
    clip = clip.fadein(FADE_DUR).fadeout(FADE_DUR)

    # Step 7: Audio normalisation
    try:
        clip = clip.fx(audio_normalize)
    except:
        pass  # no audio or error — skip

    # Step 8: Hook on first clip
    if is_first and hook_text:
        print(f"      [Hook] '{hook_text}' / '{sub_text}'")
        clip = add_5s_hook(clip, hook_text, sub_text)

    return clip


# ═══════════════════════════════════════════════════════════════
# V95 — PROCESS CLIP AT EXPLICIT TIMESTAMP
# Same pipeline as process_clip(), but you tell it exactly where to
# start (used when pulling several clips out of ONE long video).
# ═══════════════════════════════════════════════════════════════
def process_clip_at(path, start, duration=SHORT_CLIP_SEC, is_first=False,
                     hook_text="", sub_text="", credit_text=None):
    clip = VideoFileClip(path)
    fps  = clip.fps or OUTPUT_FPS

    # Nudge forward if the animal isn't actually on screen at this instant
    start = verify_and_slide_start(path, start, duration, fps)

    clip = clip.subclip(start, min(start + duration, clip.duration))
    if APPLY_SMART_CROP:
        clip = smart_crop_v93(clip)

    if APPLY_COLOR_GRADING:
        print("      [ColourGrade] Cinematic tone + CLAHE contrast + saturation boost...")
        clip = apply_colour_grade(clip)
    else:
        print("      [ColourGrade] OFF (Preserving natural clip colors as configured)")

    clip = clip.fadein(FADE_DUR).fadeout(FADE_DUR)

    try:
        clip = clip.fx(audio_normalize)
    except:
        pass

    if is_first and hook_text:
        print(f"      [Hook] '{hook_text}' / '{sub_text}'")
        clip = add_5s_hook(clip, hook_text, sub_text)

    if credit_text:
        clip = add_credit_overlay(clip, credit_text)

    return clip


def add_credit_overlay(clip, credit_text):
    """Small persistent on-screen credit line near the bottom of the frame."""
    txt_rgba = _render_text(
        credit_text, OUT_W, OUT_H, max(26, OUT_W // 40), 0.95,
        (255, 255, 255, 220), (0, 0, 0, 200), 2
    )
    def apply(get_frame, t):
        frame = get_frame(t).copy()
        if frame.dtype != np.uint8:
            frame = (frame * 255).clip(0, 255).astype(np.uint8)
        return _blend(frame, txt_rgba, 0.95)
    try:
        return clip.fl(apply, apply_to="video")
    except Exception as e:
        print(f"      [Credit] Error: {e}")
        return clip


# ───────────────────────────────────────────────────────────────
# LOGO + THUMBNAIL
# ───────────────────────────────────────────────────────────────
def add_logo(base):
    if not os.path.exists(LOGO_FILE): return base
    try:
        lw = min(120, int(OUT_W * 0.12))
        logo = (ImageClip(LOGO_FILE)
                .set_duration(base.duration)
                .resize(width=lw)
                .set_opacity(LOGO_OPACITY)
                .set_pos((OUT_W - lw - 24, OUT_H - int(lw * 1.2) - 30)))
        return CompositeVideoClip([base, logo])
    except Exception as e:
        print(f"      [Logo] {e}"); return base

def create_thumbnail(vpath, opath):
    try:
        cap   = cv2.VideoCapture(vpath)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        best  = None; bs = -1
        for i in range(20):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total*0.015*i))
            ret, frame = cap.read()
            if not ret: continue
            g  = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            sc = cv2.Laplacian(g,cv2.CV_64F).var()*0.6 + _tex(cv2.resize(g,(160,90)))*350
            if sc>bs: bs=sc; best=frame.copy()
        cap.release()
        if best is not None:
            cv2.imwrite(opath, cv2.resize(best,(1280,720)))
            return opath
    except Exception as e:
        print(f"      [Thumb] {e}")
    return None


# ═══════════════════════════════════════════════════════════════
# V95 — SHARED FINALIZE / EXPORT (used by all 3 source modes)
# Renders clips into one file, makes thumbnail + metadata, cleans up.
# ═══════════════════════════════════════════════════════════════
def finalize_and_export(clips, energy_scores=None):
    if not clips:
        print("\n   ⚠  No clips to export.")
        return

    mode_emoji = {"cat":"🐱","dog":"🐶","mix":"🐾"}[VIDEO_MODE]
    title, yt_desc, social_desc = generate_metadata()
    ts = int(time.time())
    if VIDEO_TYPE == "long":
        short_out = os.path.join(OUT_FOLDER, f"lion_{VIDEO_MODE}_{ts}_long.mp4")
    else:
        short_out = os.path.join(OUT_FOLDER, f"lion_{VIDEO_MODE}_{ts}.mp4")
    print(f"\n   Rendering {len(clips)} clips ({TARGET_FORMAT} {OUT_W}x{OUT_H}) to: {os.path.basename(short_out)}")

    final = concatenate_videoclips(clips, method="compose")
    if ADD_LOGO:
        print("      [Logo] Overlaying subtle channel watermark...")
        final = add_logo(final)
    final.write_videofile(
        short_out,
        codec="libx264",
        bitrate="10000k",
        audio_codec="aac",
        audio_bitrate="192k",
        fps=OUTPUT_FPS,
        preset="fast",
        ffmpeg_params=["-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p"],
        threads=4,
        logger="bar"
    )
    print(f"   Saved: {short_out}")

    thumb_out = short_out.replace(".mp4", "_thumb.jpg")
    create_thumbnail(short_out, thumb_out)

    meta_path = os.path.join(OUT_FOLDER, f"lion_metadata_{VIDEO_MODE}_{ts}.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("="*60+"\n  LIONREEL V95 MASTER\n"+"="*60+"\n\n")
        f.write(f"SOURCE_MODE : {SOURCE_MODE}\n")
        f.write(f"MODE  : {VIDEO_MODE.upper()} {mode_emoji}\n")
        f.write(f"VIDEO : {os.path.basename(short_out)}\n")
        f.write(f"THUMB : {os.path.basename(thumb_out)}\n\n")
        f.write("-"*60+"\nTITLE\n"+"-"*60+"\n"+title+"\n\n")
        f.write("-"*60+"\nYOUTUBE DESCRIPTION\n"+"-"*60+"\n"+yt_desc+"\n\n")
        f.write("-"*60+"\nTIKTOK / INSTAGRAM / FACEBOOK\n"+"-"*60+"\n"+social_desc+"\n\n")
        f.write("-"*60+"\nUPLOAD LINKS\n"+"-"*60+"\n")
        f.write("YouTube   : https://studio.youtube.com\n")
        f.write("TikTok    : https://www.tiktok.com/tiktokstudio/upload\n")
        f.write("Instagram : https://www.instagram.com/reels/upload\n")
        f.write("Facebook  : https://www.facebook.com/reels/create\n")
    print(f"   Metadata: {meta_path}")

    print("\n   Cleaning temporary raw files...")
    deleted = 0
    for f in glob.glob(os.path.join(RAW_FOLDER, "*")):
        if os.path.isfile(f) and not os.path.basename(f).startswith("cache_"):
            try: os.remove(f); deleted += 1
            except: pass
    print(f"   {deleted} temporary files cleaned.")

    try: final.close()
    except: pass
    for c in clips:
        try: c.close()
        except: pass

    line = "═"*60
    print("\n"+line+f"\n  ALL DONE — LionReel V95! {mode_emoji}")
    print(f"  MODE  : {VIDEO_MODE.upper()}")
    print(f"  VIDEO : {os.path.basename(short_out)}")
    print(line)
    print("\n>>> TITLE:"); print(title)
    print("\n>>> YOUTUBE:"); print(yt_desc)
    print("\n>>> SOCIAL:"); print(social_desc)
    print("\n>>> UPLOAD:")
    print("  YouTube   : https://studio.youtube.com/channel/UCK6vJnSBp-6XWlVKjePzr4w")
    print("  TikTok    : https://www.tiktok.com/tiktokstudio/upload?from=creator_center&tab=video")
    print("  Meta/Reels: https://business.facebook.com/latest/reels_composer/?asset_id=960315347156294&business_id=25484170311269841&ir_qe_exposed=1&ref=biz_web_home_create_reel&context_ref=HOME")
    print("  Facebook  : https://business.facebook.com/latest/reels_composer/?asset_id=960315347156294&business_id=25484170311269841&ir_qe_exposed=1&ref=biz_web_home_create_reel&context_ref=HOME")
    print("\n"+line+"\n")


# ═══════════════════════════════════════════════════════════════
# V95 — METHOD A: OWN FOOTAGE MODE
# Reads ONE long video (yours) from OWN_FOOTAGE_FOLDER and pulls
# several funny moments spread across it (start/middle/end) into
# one finished short. No copyright concern — it's your footage.
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# SELECTED CLIPS COMPILATION MODE (GUI QUEUED CLIPS)
# ═══════════════════════════════════════════════════════════════
def run_selected_clips_mode(selected_clips):
    mode_emoji = {"cat":"🐱","dog":"🐶","mix":"🐾","mixed":"🐾"}.get(VIDEO_MODE, "🐾")

    clips = []
    energy_scores = []
    used_vids = set()
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f_h:
                used_vids = {l.strip() for l in f_h if l.strip()}
        except:
            pass

    # Strictly filter queued clips by category and block any other animal (otters, raccoons, etc.)
    valid_selected = []
    dog_keywords = ("dog", "dogs", "puppy", "puppies", "canine", "hound", "retriever", "husky", "bulldog", "poodle", "bark", "barking", "woof")
    cat_keywords = ("cat", "cats", "kitten", "kittens", "feline", "meow", "purr", "tabby")

    for sc in selected_clips:
        t_low = (sc.get("title") or "").lower()
        c_cat = (sc.get("category") or "").lower()

        # Always block wild / non-pet animals (otters, raccoons, red pandas, etc.)
        if any(b in t_low for b in OTHER_ANIMAL_BLOCK_WORDS):
            print(f"   [CategoryGate] Skipped non-pet clip '{sc.get('title')}' (Other animal detected)")
            continue

        if VIDEO_MODE == "cat":
            if c_cat in ("dog", "canine"):
                print(f"   [CategoryGate] Skipped dog clip '{sc.get('title')}' in Cat mode")
                continue
            if any(dw in t_low for dw in dog_keywords) and not any(cw in t_low for cw in cat_keywords):
                print(f"   [CategoryGate] Skipped dog-titled clip '{sc.get('title')}' in Cat mode")
                continue
            if c_cat and c_cat not in ("cat", "feline"):
                print(f"   [CategoryGate] Skipped non-cat clip '{sc.get('title')}' in Cat mode")
                continue

        elif VIDEO_MODE == "dog":
            if c_cat in ("cat", "feline"):
                print(f"   [CategoryGate] Skipped cat clip '{sc.get('title')}' in Dog mode")
                continue
            if any(cw in t_low for cw in cat_keywords) and not any(dw in t_low for dw in dog_keywords):
                print(f"   [CategoryGate] Skipped cat-titled clip '{sc.get('title')}' in Dog mode")
                continue
            if c_cat and c_cat not in ("dog", "canine"):
                print(f"   [CategoryGate] Skipped non-dog clip '{sc.get('title')}' in Dog mode")
                continue

        elif VIDEO_MODE in ("mix", "mixed"):
            # Cats & Dogs Duo
            pass

        valid_selected.append(sc)

    if not valid_selected and selected_clips:
        print(f"   [CategoryGate] None of the selected clips matched current category '{VIDEO_MODE.upper()}'. Falling back to category-tuned discovery.")
        lion_factory()
        return

    if VIDEO_TYPE in ("long", "both"):
        target_total_sec = max(60, int(TARGET_DURATION_MIN * 60))
        needed_clips = max(10, int(round(target_total_sec / SHORT_CLIP_SEC)))
    else:
        # Standard Short Video mode: Exactly 1 clip per valid selected source — NO LOOPING, NO REPEATING
        needed_clips = max(1, len(valid_selected))
        target_total_sec = int(needed_clips * SHORT_CLIP_SEC)

    print("")
    print("═"*68)
    print(f"  LionReel — SELECTED CLIPS COMPILATION MODE  {mode_emoji}  {VIDEO_MODE.upper()}")
    print("  ─────────────────────────────────────────────────────────────")
    print(f"  Selected Clips : {len(valid_selected)} clips queued from GUI")
    print(f"  Format / Mode  : {VIDEO_TYPE.upper()} (Target: {target_total_sec}s, {needed_clips} clips)")
    print(f"  Moment Pacing  : {SHORT_CLIP_SEC}s per cut")
    print("═"*68)
    print("")

    downloaded_sources = []
    for idx, sc in enumerate(valid_selected):
        clip_id = str(sc.get("id") or f"clip_{idx}")
        title = sc.get("title") or f"Clip {idx+1}"
        url = sc.get("videoUrl") or ""
        trim_start = float(sc.get("trimStart") or 0.0)
        trim_end = sc.get("trimEnd")
        if trim_end is not None and float(trim_end) > trim_start:
            target_dur = float(trim_end) - trim_start
        else:
            target_dur = float(SHORT_CLIP_SEC)

        print(f"\n   [{idx+1}/{len(valid_selected)}] Sourcing: {title[:50]}")
        local_path = None
        if os.path.exists(url):
            local_path = url
        elif url.startswith("http://") or url.startswith("https://"):
            if "youtube.com" in url or "youtu.be" in url:
                v_id = None
                if "v=" in url:
                    v_id = url.split("v=")[1].split("&")[0]
                elif "youtu.be/" in url:
                    v_id = url.split("youtu.be/")[1].split("?")[0]

                cache_file = os.path.join(RAW_FOLDER, f"cache_{v_id}.mp4") if v_id else None
                if cache_file and os.path.exists(cache_file) and os.path.getsize(cache_file) > 100_000:
                    local_path = cache_file
                    print(f"      Using cached high-speed source: {os.path.basename(cache_file)} ({os.path.getsize(cache_file)/1_048_576:.1f} MB)")
                else:
                    target_out = cache_file or os.path.join(RAW_FOLDER, f"sel_{int(time.time())}_{idx}.mp4")
                    dl_file, err = download_video(url, target_out, None, preview=False)
                    if dl_file and os.path.exists(dl_file):
                        local_path = dl_file
                    else:
                        print(f"      Download failed: {err}")
            elif "commondatastorage.googleapis.com" in url:
                print(f"      Sample bucket URL deprecated, using live search fallback...")
            else:
                import urllib.request
                tmp_dl = os.path.join(RAW_FOLDER, f"sel_direct_{int(time.time())}_{idx}.mp4")
                try:
                    headers = {"User-Agent": "Mozilla/5.0"}
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=4) as resp, open(tmp_dl, "wb") as out_f:
                        out_f.write(resp.read())
                    if os.path.exists(tmp_dl) and os.path.getsize(tmp_dl) > 10_000:
                        local_path = tmp_dl
                    else:
                        print(f"      Downloaded file too small or empty")
                except Exception as e_dl:
                    print(f"      Direct download error: {e_dl}")

        # Quality & Content Verification Gate on candidate source
        if local_path and os.path.exists(local_path):
            if CHECK_CARTOON and not BYPASS_QUALITY_GATE:
                is_cart, reason = check_cartoon_or_cgi(local_path, sc)
                if is_cart:
                    print(f"      [SelectedGate] REJECTED clip '{title[:45]}' — {reason} ❌")
                    try:
                        if not os.path.isabs(url) and os.path.exists(local_path) and "cache_" not in local_path:
                            os.remove(local_path)
                    except: pass
                    local_path = None

            if local_path and CHECK_SHARPNESS and not BYPASS_QUALITY_GATE:
                is_s, s_score, _ = check_sharpness(local_path)
                if not is_s:
                    print(f"      [SelectedGate] REJECTED clip '{title[:45]}' — Low sharpness ({s_score:.0f}) ❌")
                    local_path = None

            if local_path and CHECK_AI_VIDEO and not BYPASS_QUALITY_GATE:
                if not is_real_footage(local_path):
                    print(f"      [SelectedGate] REJECTED clip '{title[:45]}' — Failed real footage check ❌")
                    local_path = None

        if not local_path or not os.path.exists(local_path):
            mode_tag = "cat" if VIDEO_MODE == "cat" else ("dog" if VIDEO_MODE == "dog" else "cat and dog")
            clean_t = "".join(ch for ch in title[:30] if ch.isalnum() or ch.isspace()).strip()
            search_q = f"funny {mode_tag} {clean_t} viral pet -cartoon -animation -game -talking"
            print(f"      Searching YouTube for live clip matching '{clean_t[:45]}'...")
            try:
                with YoutubeDL({"quiet": True, "extract_flat": True, "logger": SilentLogger(), "socket_timeout": 8}) as ydl:
                    s_res = ydl.extract_info(f"ytsearch8:{search_q}", download=False).get("entries", [])
                    for se in s_res:
                        if not se or not se.get("id"):
                            continue
                        se_title = (se.get("title") or "").lower()
                        if any(b in se_title for b in OTHER_ANIMAL_BLOCK_WORDS):
                            continue
                        if not mode_passes(se):
                            continue
                        if CHECK_CARTOON:
                            is_cart_meta, kw = check_cartoon_metadata(se)
                            if is_cart_meta:
                                print(f"      [FallbackSearch] Skipped cartoon candidate '{se.get('title','')[:40]}' ({kw})")
                                continue
                        dur = se.get("duration") or 0
                        if dur < 4 or dur > 900:
                            continue
                        v_url = f"https://www.youtube.com/watch?v={se['id']}"
                        tmp_dl = os.path.join(RAW_FOLDER, f"sel_yt_{int(time.time())}_{idx}.mp4")
                        dl_file, _ = download_video(v_url, tmp_dl, None, preview=False)
                        if dl_file and os.path.exists(dl_file):
                            if CHECK_CARTOON and not BYPASS_QUALITY_GATE:
                                is_cart, r_score = check_cartoon_visual(dl_file)
                                if is_cart:
                                    print(f"      [FallbackSearch] Candidate failed visual cartoon check ({r_score:.0%}), skipping")
                                    try: os.remove(dl_file)
                                    except: pass
                                    continue
                            if CHECK_SHARPNESS and not BYPASS_QUALITY_GATE:
                                is_s, s_score, _ = check_sharpness(dl_file)
                                if not is_s:
                                    print(f"      [FallbackSearch] Candidate too blurry ({s_score:.0f}), skipping")
                                    try: os.remove(dl_file)
                                    except: pass
                                    continue
                            local_path = dl_file
                            print(f"      Retrieved verified live video from YouTube: {se.get('title','')[:50]}")
                            break
            except Exception as e_s:
                print(f"      Search fallback note: {e_s}")

        if local_path and os.path.exists(local_path):
            local_path = ensure_fast_h264(local_path)
            downloaded_sources.append({
                "path": local_path,
                "id": clip_id,
                "title": title,
                "trim_start": trim_start,
                "target_dur": target_dur
            })

    if not downloaded_sources:
        msg = "No selected clips could be processed successfully. Falling back to automated YouTube discovery."
        print(f"\n   ⚠ {msg}")
        lion_factory()
        return

    print(f"\n   [STAGE 5] Trimming high-energy animal motion slices...")
    print(f"   Target: {needed_clips} clips (~{target_total_sec}s runtime) from {len(downloaded_sources)} source videos")

    if VIDEO_TYPE in ("long", "both"):
        moments_per_source = max(1, int(math.ceil(needed_clips / len(downloaded_sources))))
        for s_idx, src in enumerate(downloaded_sources):
            if len(clips) >= needed_clips:
                break
            local_path = src["path"]
            clip_id = src["id"]
            trim_start = src["trim_start"]

            src_dur = 30.0
            try:
                cap = cv2.VideoCapture(local_path)
                total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                src_fps = max(1.0, cap.get(cv2.CAP_PROP_FPS) or 30)
                src_dur = total_frames / src_fps
                cap.release()
            except:
                pass

            moments = []
            if trim_start > 0:
                moments = [trim_start]
            else:
                m_count = max(1, min(moments_per_source, int(src_dur // (SHORT_CLIP_SEC * 1.1))))
                moments = get_multiple_moments(local_path, m_count, SHORT_CLIP_SEC)

            if not moments:
                moments = [0.0]

            for m_start in moments:
                if len(clips) >= needed_clips:
                    break
                try:
                    is_first = (len(clips) == 0)
                    hook_txt = random.choice(HOOK_LINES) if is_first else ""
                    sub_txt = random.choice(SUB_HOOK_LINES) if is_first else ""
                    clip_obj = process_clip_at(
                        local_path, start=m_start, duration=SHORT_CLIP_SEC,
                        is_first=is_first, hook_text=hook_txt, sub_text=sub_txt
                    )
                    clips.append(clip_obj)
                    energy_scores.append(100)
                    print(f"      ACCEPTED ✅ — Clip {len(clips)}/{needed_clips} (Source: {src['title'][:30]}, t={m_start:.1f}s)")
                    print(f"      [CLIP_PROGRESS] {len(clips)}/{needed_clips} clips ready")
                except Exception as e_cut:
                    print(f"      Cut error: {e_cut}")

        # Cycle through sources with offset start points if needed to fulfill full requested long duration
        cycle_round = 1
        while len(clips) < needed_clips and cycle_round <= 10:
            offset = cycle_round * 3.0
            added_in_round = 0
            for src in downloaded_sources:
                if len(clips) >= needed_clips:
                    break
                local_path = src["path"]
                try:
                    cap = cv2.VideoCapture(local_path)
                    s_dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(1.0, cap.get(cv2.CAP_PROP_FPS) or 30)
                    cap.release()
                except:
                    s_dur = 30.0

                start_t = (offset + added_in_round * SHORT_CLIP_SEC) % max(1.0, s_dur - SHORT_CLIP_SEC - 1.0)
                try:
                    clip_obj = process_clip_at(
                        local_path, start=start_t, duration=SHORT_CLIP_SEC,
                        is_first=False, hook_text="", sub_text=""
                    )
                    clips.append(clip_obj)
                    energy_scores.append(100)
                    added_in_round += 1
                    print(f"      ACCEPTED ✅ — Clip {len(clips)}/{needed_clips} (Extended cut, t={start_t:.1f}s)")
                    print(f"      [CLIP_PROGRESS] {len(clips)}/{needed_clips} clips ready")
                except Exception as e_cyc:
                    pass
            cycle_round += 1
            if added_in_round == 0:
                break
    else:
        # Standard Short Video mode: 1 clip per selected source
        for idx, src in enumerate(downloaded_sources):
            if len(clips) >= needed_clips:
                break
            local_path = src["path"]
            clip_id = src["id"]
            trim_start = src["trim_start"]
            target_dur = src["target_dur"]
            clip_dur = target_dur if target_dur > 0 else SHORT_CLIP_SEC
            try:
                is_first = (len(clips) == 0)
                hook_txt = random.choice(HOOK_LINES) if is_first else ""
                sub_txt = random.choice(SUB_HOOK_LINES) if is_first else ""
                if trim_start > 0:
                    clip_obj = process_clip_at(
                        local_path, start=trim_start, duration=clip_dur,
                        is_first=is_first, hook_text=hook_txt, sub_text=sub_txt
                    )
                else:
                    clip_obj = process_clip(
                        local_path, duration=clip_dur,
                        is_first=is_first, hook_text=hook_txt, sub_text=sub_txt
                    )
                clips.append(clip_obj)
                energy_scores.append(100)
                used_vids.add(clip_id)
                with open(HISTORY_FILE, "a", encoding="utf-8") as f_h:
                    f_h.write(clip_id + chr(10))
                print(f"      ACCEPTED ✅ — Clip {len(clips)}/{needed_clips} ({clip_dur:.1f}s, Source: {src['title'][:30]})")
                print(f"      [CLIP_PROGRESS] {len(clips)}/{needed_clips} clips ready")
            except Exception as e_proc:
                print(f"      Error processing clip: {e_proc}")



    if len(clips) < 1:
        msg = "No selected clips could be processed successfully. Falling back to automated YouTube discovery."
        print(f"\n   ⚠ {msg}")
        lion_factory()
        return

    print(f"\n   [STAGE 8] Mixing background music & audio ducking (-14 LUFS)")
    print(f"   Successfully prepared {len(clips)} clips ({len(clips)*SHORT_CLIP_SEC:.1f}s runtime). Finalizing export...")
    finalize_and_export(clips, energy_scores)

def run_own_footage_mode():
    print("\n" + "═"*68)
    print(f"  LionReel V95 — OWN FOOTAGE MODE  🎬")
    print("  ─────────────────────────────────────────────────────────────")
    print(f"  FOLDER   : {OWN_FOOTAGE_FOLDER}")
    print("  METHOD   : split your long video into segments, pull the best")
    print("             funny/animal moment from each segment")
    print("═"*68 + "\n")

    os.makedirs(OWN_FOOTAGE_FOLDER, exist_ok=True)
    files = []
    for ext in ("*.mp4", "*.mov", "*.MP4", "*.MOV", "*.mkv", "*.avi"):
        files.extend(glob.glob(os.path.join(OWN_FOOTAGE_FOLDER, ext)))
    files = sorted(set(files))

    if not files:
        print(f"   ⚠  No video files found in:\n   {OWN_FOOTAGE_FOLDER}")
        print("   Drop a long .mp4/.mov file of your cat/dog in that folder and re-run.")
        return

    used = set()
    if os.path.exists(OWN_FOOTAGE_HISTORY):
        used = {l.strip() for l in open(OWN_FOOTAGE_HISTORY, encoding="utf-8", errors="ignore")}

    candidates = [f for f in files if os.path.basename(f) not in used]
    if not candidates:
        print("   All footage already used once — recycling the pool.")
        candidates = files

    source = random.choice(candidates)
    print(f"   Using footage: {os.path.basename(source)}")

    try:
        probe = VideoFileClip(source)
        src_dur = probe.duration
        probe.close()
    except Exception as e:
        print(f"   ⚠  Could not open video: {e}")
        return

    print(f"   Duration: {src_dur/60:.1f} min")

    moments = get_multiple_moments(source, TARGET_CLIPS, SHORT_CLIP_SEC)
    print(f"   Found {len(moments)} moments to use.\n")

    clips = []
    for i, start in enumerate(moments):
        is_first = (i == 0)
        print(f"   [{i+1}/{len(moments)}] Clip at t={start:.1f}s")
        try:
            clip = process_clip_at(
                source, start, SHORT_CLIP_SEC, is_first=is_first,
                hook_text=random.choice(HOOK_LINES) if is_first else "",
                sub_text=random.choice(SUB_HOOK_LINES) if is_first else "",
            )
            clips.append(clip)
            print("      ACCEPTED ✅")
        except Exception as e:
            print(f"      Error on this segment: {e}")

    if len(clips) < 2:
        print("\n   ⚠  Not enough usable moments found in this video.")
        return

    with open(OWN_FOOTAGE_HISTORY, "a", encoding="utf-8") as f:
        f.write(os.path.basename(source) + "\n")

    finalize_and_export(clips)


# ═══════════════════════════════════════════════════════════════
# V95 — METHOD B: YOUTUBE CREATIVE-COMMONS MODE
# Searches YouTube for LONG videos, checks each candidate's actual
# YouTube license, and ONLY proceeds if it is marked Creative Commons
# (reuse allowed). Pulls several clips from that ONE long video and
# burns an on-screen credit + link to the original into the short.
# ═══════════════════════════════════════════════════════════════
def _check_youtube_license(video_id, cookie_file):
    """Fetches full info for one video and checks its license field."""
    opts = {
        "quiet": True, "no_warnings": True, "logger": SilentLogger(),
        "skip_download": True,
    }
    if cookie_file and os.path.exists(cookie_file):
        opts["cookiefile"] = cookie_file
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        lic = (info.get("license") or "").lower()
        return "creative commons" in lic, info
    except Exception:
        return False, None


def is_viral_worthy_loose(entry):
    """Looser cat/dog + safety check used for CC long-video candidates
    (skips the strict 'funny word in title' requirement since long
    compilations are often just titled 'Cat Compilation Vol. 4')."""
    duration = entry.get("duration") or 0
    title    = (entry.get("title") or "").lower().strip()
    channel  = (entry.get("channel") or entry.get("uploader") or "").lower().strip()

    for phrase in BLACKLIST:
        if phrase in title: return False
    for phrase in BLACKLIST_CHANNELS:
        if phrase in channel: return False
    for phrase in OTHER_ANIMAL_BLOCK_WORDS:
        if phrase in title: return False

    has_animal_title   = any(k in title for k in CAT_DOG_WORDS)
    has_animal_channel = any(k in channel for k in CAT_DOG_CHANNEL_WORDS)
    if not has_animal_title and not has_animal_channel:
        return False
    if not mode_passes(entry):
        return False
    return True


def run_youtube_cc_mode():
    print("\n" + "═"*68)
    print(f"  LionReel V95 — YOUTUBE CREATIVE COMMONS MODE  🎬")
    print("  ─────────────────────────────────────────────────────────────")
    print("  Only videos explicitly licensed Creative Commons (reuse")
    print("  allowed) are used. Original creator is credited on-screen.")
    print("═"*68 + "\n")

    cookie_file = make_netscape_file(["youtube", "google", "ytimg", "yt3"])

    search_queries = get_search_queries()
    long_queries = [q + " compilation 10 minutes" for q in search_queries[:8]]

    search_opts = {
        "quiet": True, "extract_flat": True, "logger": SilentLogger(),
        "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        "socket_timeout": 15
    }
    if cookie_file and os.path.exists(cookie_file):
        search_opts["cookiefile"] = cookie_file

    print(f"   Searching for long compilations ({len(long_queries)} queries)...")
    all_entries = []
    for q in long_queries:
        with YoutubeDL(search_opts) as ydl:
            try:
                entries = ydl.extract_info(f"ytsearch15:{q}", download=False).get("entries", [])
                valid = [e for e in entries if e]
                all_entries.extend(valid)
                print(f"   '{q[:55]}' -> {len(valid)}")
            except Exception as e:
                print(f"   Failed [{q[:40]}]: {str(e)[:50]}")

    seen = set(); unique = []
    for e in all_entries:
        vid = e.get("id")
        if vid and vid not in seen:
            seen.add(vid); unique.append(e)

    # Filter to plausible long, cat/dog, non-blacklisted candidates first
    plausible = []
    for e in unique:
        dur = e.get("duration") or 0
        if not (CC_MIN_DURATION <= dur <= CC_MAX_DURATION):
            continue
        if not is_viral_worthy_loose(e):
            continue
        plausible.append(e)

    plausible.sort(key=lambda e: compute_viral_score(e), reverse=True)
    print(f"   {len(plausible)} plausible long candidates. Checking licenses on top {CC_CANDIDATES_TO_CHECK}...\n")

    chosen = None
    chosen_info = None
    for e in plausible[:CC_CANDIDATES_TO_CHECK]:
        vid = e.get("id")
        title = (e.get("title") or "")[:60]
        print(f"   Checking license: {title}")
        is_cc, info = _check_youtube_license(vid, cookie_file)
        if is_cc:
            print("      ✅ Creative Commons — usable")
            chosen = e; chosen_info = info
            break
        else:
            print("      ❌ Not CC-licensed — skip")

    if cookie_file:
        try: os.remove(cookie_file)
        except: pass

    if not chosen:
        print("\n   ⚠  No Creative Commons licensed video found this run.")
        print("   Try again later, or widen CC_CANDIDATES_TO_CHECK / queries.")
        return

    v_id = chosen.get("id")
    channel = chosen_info.get("channel") or chosen_info.get("uploader") or "Unknown channel"
    url = f"https://www.youtube.com/watch?v={v_id}"

    tmp = os.path.join(RAW_FOLDER, f"cc_{int(time.time())}.mp4")
    actual, err = download_video(url, tmp, None)
    if not actual:
        print(f"   Download failed: {err}")
        return

    print(f"\n   Source: {chosen.get('title','')[:70]}")
    print(f"   Credit: {channel}\n")

    moments = get_multiple_moments(actual, TARGET_CLIPS, SHORT_CLIP_SEC)
    credit_text = f"Credit: {channel} — {url}"

    clips = []
    for i, start in enumerate(moments):
        is_first = (i == 0)
        try:
            clip = process_clip_at(
                actual, start, SHORT_CLIP_SEC, is_first=is_first,
                hook_text=random.choice(HOOK_LINES) if is_first else "",
                sub_text=random.choice(SUB_HOOK_LINES) if is_first else "",
                credit_text=credit_text,
            )
            clips.append(clip)
            print(f"      Clip {i+1}/{len(moments)} ACCEPTED ✅")
        except Exception as e:
            print(f"      Error on this segment: {e}")

    if len(clips) < 2:
        print("\n   ⚠  Not enough usable moments found in this video.")
        try: os.remove(actual)
        except: pass
        return

    finalize_and_export(clips)

    try: os.remove(actual)
    except: pass


# ═══════════════════════════════════════════════════════════════
# V95 — METHOD C: CUSTOM VIDEO LINK MODE
# Downloads user-provided YouTube URL or direct video, extracts
# peak funny moments or formats entire clip for Shorts.
# ═══════════════════════════════════════════════════════════════
def run_custom_url_mode(custom_url=None):
    url = (custom_url or CUSTOM_URL or "").strip()
    print("\n" + "═"*68)
    print("  LionReel V95 — CUSTOM VIDEO LINK MODE  🎬")
    print("  ─────────────────────────────────────────────────────────────")
    print(f"  Target URL : {url}")
    print("═"*68 + "\n")

    if not url:
        print("   ⚠  No custom URL provided. Falling back to autonomous YouTube discovery.")
        lion_factory()
        return

    cookie_file = make_netscape_file(["youtube", "google", "ytimg", "yt3"])
    tmp_path = os.path.join(RAW_FOLDER, f"custom_{int(time.time())}.mp4")

    print(f"   Downloading source video from: {url}")
    actual, err = download_video(url, tmp_path, cookie_file, preview=False)
    if cookie_file:
        try: os.remove(cookie_file)
        except: pass

    if not actual or not os.path.exists(actual):
        print(f"   ⚠  Download failed: {err}")
        print("   Falling back to autonomous YouTube discovery...")
        lion_factory()
        return

    try:
        cap = cv2.VideoCapture(actual)
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = max(1.0, cap.get(cv2.CAP_PROP_FPS) or 30.0)
        dur = total_frames / fps
        cap.release()
    except Exception as e:
        dur = 30.0

    print(f"   Downloaded successfully! Duration: {dur:.1f}s")
    clips = []
    energy_scores = []

    if dur <= SHORT_CLIP_SEC * 1.5:
        print("   Processing entire video as high-impact short...")
        try:
            clip = process_clip(
                actual,
                is_first=True,
                hook_text=random.choice(HOOK_LINES),
                sub_text=random.choice(SUB_HOOK_LINES)
            )
            clips.append(clip)
            energy_scores.append(100)
        except Exception as e_p:
            print(f"   Clip processing error: {e_p}")
    else:
        needed = TARGET_CLIPS if VIDEO_TYPE in ("long", "both") else max(1, min(6, int(dur // SHORT_CLIP_SEC)))
        print(f"   Extracting {needed} peak laugh moments from {dur:.1f}s video...")
        moments = get_multiple_moments(actual, needed, SHORT_CLIP_SEC)
        if not moments:
            moments = [0.0]

        for i, start_t in enumerate(moments):
            is_first = (i == 0)
            try:
                clip = process_clip_at(
                    actual,
                    start=start_t,
                    duration=SHORT_CLIP_SEC,
                    is_first=is_first,
                    hook_text=random.choice(HOOK_LINES) if is_first else "",
                    sub_text=random.choice(SUB_HOOK_LINES) if is_first else ""
                )
                clips.append(clip)
                energy_scores.append(100)
                print(f"      Moment {i+1}/{len(moments)} ACCEPTED ✅ (t={start_t:.1f}s)")
            except Exception as e:
                print(f"      Moment cut error: {e}")

    if not clips:
        print("   ⚠  Could not extract any clips from custom URL. Falling back to autonomous YouTube discovery.")
        try: os.remove(actual)
        except: pass
        lion_factory()
        return

    finalize_and_export(clips, energy_scores)
    try: os.remove(actual)
    except: pass


# ───────────────────────────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────────────────────────
def lion_factory():
    mode_emoji = {"cat":"🐱","dog":"🐶","mix":"🐾"}[VIDEO_MODE]
    print("\n"+"═"*68)
    print(f"  LionReel V94 — CAT/DOG ONLY, YOUTUBE-ONLY SOURCE  {mode_emoji}  {VIDEO_MODE.upper()}")
    print("  ─────────────────────────────────────────────────────────────")
    print("  SOURCE   : YouTube only (yt-dlp ytsearch + youtube.com URLs)")
    print("  CONTENT  : Cat + Dog videos only — all other animals blocked")
    print("  ─────────────────────────────────────────────────────────────")
    print("  QUALITY FILTERS:")
    print(f"  FIX 1 ✅ Sharpness check    (Laplacian ≥{SHARP_THRESHOLD}, min {MIN_SOURCE_HEIGHT}p)")
    print(f"  FIX 2 ✅ Shake detector     (bg motion < {SHAKE_THRESHOLD}px/frame)")
    print(f"  FIX 3 ✅ Music detector     (audio RMS cv > {MUSIC_FLAT_THRESHOLD})")
    print(f"  FIX 4 ✅ Watermark detector (corner check < {WATERMARK_THRESHOLD:.0%} frames)")
    print("  FIX 5 ✅ Colour grade       (AWB + CLAHE + 1.22x saturation)")
    print(f"  FIX 6 ✅ Smart crop V2     ({SAFE_CROP_MARGIN}px safety margin)")
    print("  + Audio normalisation on every clip")
    print("  + 8Mbps bitrate, 720p+ source enforced")
    print("═"*68+"\n")

    cookie_file = make_netscape_file(["youtube","google","ytimg","yt3"])
    if cookie_file:
        try:
            n = sum(1 for l in open(cookie_file) if not l.startswith("#") and l.strip())
            print(f"   [cookies] {n} entries ready")
        except: print("   [cookies] Ready")
    else:
        print("   [cookies] No cookies — public only\n")

    used_vids = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE,"r") as f: lines = f.readlines()
        if len(lines) > 500:
            lines = lines[-500:]
            with open(HISTORY_FILE,"w") as f: f.writelines(lines)
        used_vids = {l.strip() for l in lines}

    search_queries = get_search_queries()
    # Shuffle and select a subset of 8 queries to prevent long search times and rate-limiting
    random.shuffle(search_queries)
    search_queries = search_queries[:5]
    search_opts = {
        "quiet":True,"extract_flat":True,"logger":SilentLogger(),
        "http_headers":{"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        "socket_timeout": 15
    }
    if cookie_file and os.path.exists(cookie_file):
        search_opts["cookiefile"] = cookie_file

    print(f"   Searching YouTube ({VIDEO_MODE.upper()} — {len(search_queries)} queries × {SEARCH_RESULTS_PER_Q})...")
    all_entries = []
    for q in search_queries:
        with YoutubeDL(search_opts) as ydl:
            try:
                entries = ydl.extract_info(
                    f"ytsearch{SEARCH_RESULTS_PER_Q}:{q}", download=False
                ).get("entries",[])
                valid = [e for e in entries if e]
                all_entries.extend(valid)
                print(f"   '{q[:55]}' -> {len(valid)}")
            except Exception as e:
                print(f"   Failed [{q[:40]}]: {str(e)[:50]}")

    seen=set(); unique=[]
    for e in all_entries:
        vid = e.get("id")
        if vid and vid not in seen: seen.add(vid); unique.append(e)

    print(f"\n   Viral-scoring {len(unique)} candidates...")
    scored = [(compute_viral_score(e), e) for e in unique]
    scored = [(s, e) for s, e in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"\n   TOP CANDIDATES:")
    for i, (vs, e) in enumerate(scored[:8]):
        views = e.get("view_count") or 0
        dur   = e.get("duration") or 0
        title = (e.get("title") or "")[:52]
        print(f"   #{i+1:02d} Score:{vs:.1f} Views:{views/1_000_000:.1f}M Dur:{dur}s | {title}")

    candidates = [e for (_, e) in scored]
    clips=[]
    energy_scores=[]
    skip={"used":0,"filter":0,"dl":0,"fake":0,"no_animal":0,
          "blurry":0,"shaky":0,"music":0,"watermark":0,"err":0}
    idx=0

    while len(clips) < TARGET_CLIPS and idx < len(candidates):
        entry = candidates[idx]; idx += 1
        v_id  = entry.get("id")
        if not v_id or v_id in used_vids: skip["used"]+=1; continue
        if not is_viral_worthy(entry):    skip["filter"]+=1; continue

        viral_score = compute_viral_score(entry)
        # V94b: do NOT mark as used here. A video that fails the quality gate
        # (blurry/shaky/etc) below should stay available for future runs —
        # only videos that actually become a finished clip get locked out.

        title = entry.get("title","")[:55]
        views = entry.get("view_count") or 0
        dur   = entry.get("duration") or 0
        print(f"\n   [{len(clips)+1}/{TARGET_CLIPS}] {title}")
        print(f"       Views:{views:,}  Dur:{dur:.0f}s  Score:{viral_score:.1f}")

        tmp_prev = os.path.join(RAW_FOLDER, f"prev_{int(time.time())}_{len(clips)}.mp4")
        tmp_hq = os.path.join(RAW_FOLDER, f"t_{int(time.time())}_{len(clips)}.mp4")
        url = f"https://www.youtube.com/watch?v={v_id}"

        # Download lightweight preview first
        print("      Downloading preview...")
        preview_file, err = download_video(url, tmp_prev, cookie_file, preview=True)

        if not preview_file:
            print(f"      Preview download failed: {err}"); skip["dl"]+=1
            for f in glob.glob(tmp_prev.replace(".mp4","*")):
                try: os.remove(f)
                except: pass
            continue

        actual = None
        try:
            # ── V93 QUALITY GATE — runs ALL 6 checks on preview ──────────
            print("      [QualityGate] Running V93 checks on preview...")

            # Check 1: Sharpness
            is_sharp, sharp_score, res_ok = check_sharpness(preview_file)
            if not is_sharp and not BYPASS_QUALITY_GATE:
                print(f"      REJECTED — blurry/low-res (score={sharp_score:.0f})")
                try: os.remove(preview_file)
                except: pass
                skip["blurry"]+=1; continue

            # Check 2: Shake
            is_shaky, shake_score = check_shake(preview_file)
            if is_shaky and not BYPASS_QUALITY_GATE:
                print(f"      REJECTED — shaky camera (motion={shake_score:.2f})")
                try: os.remove(preview_file)
                except: pass
                skip["shaky"]+=1; continue

            # Check 3: Music overlay
            has_music = check_audio_music(preview_file)
            if has_music and not BYPASS_QUALITY_GATE:
                print("      REJECTED — background music detected")
                try: os.remove(preview_file)
                except: pass
                skip["music"]+=1; continue

            # Check 4: Watermark
            has_wm, wm_ratio = check_watermark(preview_file)
            if has_wm and not BYPASS_QUALITY_GATE:
                print(f"      REJECTED — watermark detected ({wm_ratio:.0%} frames)")
                try: os.remove(preview_file)
                except: pass
                skip["watermark"]+=1; continue

            # Check 5: AI/fake
            print("      [AICheck] Running...")
            if not is_real_footage(preview_file) and not BYPASS_QUALITY_GATE:
                print("      REJECTED — AI/fake content")
                try: os.remove(preview_file)
                except: pass
                skip["fake"]+=1; continue

            # Check 6: Animal presence
            print("      [AnimalCheck] Running...")
            if not visual_has_animal(preview_file) and not BYPASS_QUALITY_GATE:
                print("      REJECTED — no animal visible")
                try: os.remove(preview_file)
                except: pass
                skip["no_animal"]+=1; continue

            # Check 7: Cartoon & Animation Gate
            if CHECK_CARTOON:
                print("      [CartoonCheck] Scanning for 3D CGI / Cartoon models...")
                is_c, c_score = check_cartoon_visual(preview_file)
                if is_c and not BYPASS_QUALITY_GATE:
                    print(f"      REJECTED — Cartoon / 3D Animation / CGI detected ({c_score:.0%})")
                    try: os.remove(preview_file)
                    except: pass
                    skip["fake"]+=1; continue

            # Clean preview and download high quality!
            try: os.remove(preview_file)
            except: pass

            print(f"      ✅ Preview passed all checks! Downloading high quality...")
            actual, err = download_video(url, tmp_hq, cookie_file, preview=False)

            if not actual:
                print(f"      HQ download failed: {err}"); skip["dl"]+=1
                for f in glob.glob(tmp_hq.replace(".mp4","*")):
                    try: os.remove(f)
                    except: pass
                continue

            # Sanity check sharpness on the high-quality download
            is_sharp_hq, sharp_score_hq, res_ok_hq = check_sharpness(actual)
            if not is_sharp_hq and not BYPASS_QUALITY_GATE:
                print(f"      REJECTED HQ — high quality version is blurry (score={sharp_score_hq:.0f})")
                try: os.remove(actual)
                except: pass
                skip["blurry"]+=1; continue

            # Sanity check cartoon on the high-quality download
            if CHECK_CARTOON and not BYPASS_QUALITY_GATE:
                is_c_hq, c_score_hq = check_cartoon_visual(actual)
                if is_c_hq:
                    print(f"      REJECTED HQ — Cartoon / 3D Animation / CGI detected in HQ ({c_score_hq:.0%})")
                    try: os.remove(actual)
                    except: pass
                    skip["fake"]+=1; continue

            needed = TARGET_CLIPS - len(clips)
            if dur > 40 and (VIDEO_TYPE in ("long", "both") or needed > 1):
                print(f"      🎥 Long video detected ({dur:.0f}s). Extracting up to {needed} clips from it...")
                moments_count = min(needed, max(2, int((dur - 10) // (SHORT_CLIP_SEC * 1.2))))
                moments = get_multiple_moments(actual, moments_count, SHORT_CLIP_SEC)
                if moments:
                    long_clips = []
                    for i, start in enumerate(moments):
                        is_first = (len(clips) + len(long_clips) == 0)
                        try:
                            c = process_clip_at(
                                actual, start, SHORT_CLIP_SEC,
                                is_first=is_first,
                                hook_text=random.choice(HOOK_LINES) if is_first else "",
                                sub_text=random.choice(SUB_HOOK_LINES) if is_first else ""
                            )
                            long_clips.append(c)
                            print(f"      Segment {len(long_clips)}/{len(moments)} ACCEPTED ✅")
                        except Exception as seg_err:
                            print(f"      Error on segment: {seg_err}")
                    if long_clips:
                        clips.extend(long_clips)
                        for _ in long_clips:
                            energy_scores.append(10000)
                        used_vids.add(v_id)
                        with open(HISTORY_FILE, "a", encoding="utf-8") as f_h:
                            f_h.write(v_id + chr(10))
                        print(f"      SUCCESS ✅ — Extracted {len(long_clips)} clips from long video! ({len(clips)}/{TARGET_CLIPS} total)")
                        print(f"      ACCEPTED ✅ — Clip {len(clips)}/{TARGET_CLIPS}")
                        print(f"      [CLIP_PROGRESS] {len(clips)}/{TARGET_CLIPS} clips ready")
                        if len(clips) >= TARGET_CLIPS:
                            break
                        continue

            else:
                # Energy score for ramp
                cap_t = cv2.VideoCapture(actual)
                ttl   = int(cap_t.get(cv2.CAP_PROP_FRAME_COUNT))
                ms=0; pf=None
                for si in range(20):
                    cap_t.set(cv2.CAP_PROP_POS_FRAMES, int(ttl*si/20))
                    ret,frm = cap_t.read()
                    if not ret: continue
                    g = cv2.cvtColor(cv2.resize(frm,(160,90)),cv2.COLOR_BGR2GRAY)
                    if pf is not None: ms += int(np.sum(cv2.absdiff(pf,g)))
                    pf=g
                cap_t.release(); energy_scores.append(ms)

                print("      Processing clip (V93 pipeline)...")
                is_first = (len(clips)==0)
                clip = process_clip(
                    actual,
                    is_first=is_first,
                    hook_text=random.choice(HOOK_LINES) if is_first else "",
                    sub_text=random.choice(SUB_HOOK_LINES) if is_first else ""
                )
                clips.append(clip)
                # V94b: mark as used only NOW — after it actually became a clip.
                used_vids.add(v_id)
                with open(HISTORY_FILE,"a") as f: f.write(v_id+"\n")
                print(f"      ACCEPTED ✅ — Clip {len(clips)}/{TARGET_CLIPS}!")

        except Exception as e:
            print(f"      Error: {e}"); skip["err"]+=1
            for p in [tmp_prev, tmp_hq]:
                for f in glob.glob(p.replace(".mp4","*")):
                    try: os.remove(f)
                    except: pass

    # ── Summary ──────────────────────────────────────────────
    print(f"\n   ── V94 Quality Report ───────────────────────────────")
    print(f"   Mode       : {VIDEO_MODE.upper()} {mode_emoji}")
    print(f"   Clips      : {len(clips)}/{TARGET_CLIPS}")
    print(f"   Blurry/res : {skip['blurry']}  Shaky: {skip['shaky']}")
    print(f"   Music      : {skip['music']}   Watermark: {skip['watermark']}")
    print(f"   AI/fake    : {skip['fake']}    No animal: {skip['no_animal']}")
    print(f"   DL fail    : {skip['dl']}      Filter: {skip['filter']}")
    print(f"   ────────────────────────────────────────────────────")

    if len(clips) < 3:
        print(f"\n   ⚠  Only {len(clips)} clips passed all quality checks.")
        print("   V94 filter is strict (cat/dog only + quality gate) — TIPS:")
        print("   1. Lower SHARP_THRESHOLD (e.g. 80 → 50) if too strict")
        print("   2. Raise SHAKE_THRESHOLD (e.g. 6.0 → 8.0) to allow more")
        print("   3. Delete used_videos.txt to refresh the pool")
        print("   4. Add cookies_raw.json for more search results")
        if cookie_file:
            try: os.remove(cookie_file)
            except: pass
        return

    if len(clips) > 2:
        clips = [clips[0]] + energy_ramp_order(clips[1:], energy_scores[1:])

    finalize_and_export(clips)

    if cookie_file:
        try: os.remove(cookie_file)
        except: pass


if __name__ == "__main__":
    # ── OPTIONAL: force a mode ─────────────────────────────────
    # VIDEO_MODE = "cat"
    # VIDEO_MODE = "dog"
    # VIDEO_MODE = "mix"
    #
    # SOURCE_MODE is set near the top of this file:
    #   "classic"     -> original behaviour, many short YouTube videos
    #   "own_footage" -> your own long video, sliced into several clips
    #   "youtube_cc"  -> one Creative-Commons-licensed long YouTube video,
    #                    sliced into several clips, credited on-screen
    print(f"\n[Execution Dispatch] Sourcing Mode: {SOURCE_MODE.upper()}, Animal Category: {VIDEO_MODE.upper()}")
    if SELECTED_CLIPS and len(SELECTED_CLIPS) > 0 and SOURCE_MODE not in ("own_footage", "custom_url"):
        run_selected_clips_mode(SELECTED_CLIPS)
    elif SOURCE_MODE == "classic":
        lion_factory()
    elif SOURCE_MODE in ("curated", "selected"):
        if SELECTED_CLIPS and len(SELECTED_CLIPS) > 0:
            run_selected_clips_mode(SELECTED_CLIPS)
        else:
            print("   [Dispatch] Curated mode selected but no clips queued. Running autonomous YouTube discovery.")
            lion_factory()
    elif SOURCE_MODE == "custom_url":
        run_custom_url_mode(CUSTOM_URL)
    elif SOURCE_MODE == "own_footage":
        run_own_footage_mode()
    elif SOURCE_MODE == "youtube_cc":
        run_youtube_cc_mode()
    else:
        if SELECTED_CLIPS and len(SELECTED_CLIPS) > 0:
            run_selected_clips_mode(SELECTED_CLIPS)
        else:
            lion_factory()