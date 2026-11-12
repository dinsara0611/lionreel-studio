"""
Editing choices a person would make, each based on something measured in the rendered clips:
open on the clip that moves most in its first seconds, never run two clips from the same
source back to back when it can be avoided, and let a caption leave the screen after a few seconds.
"""
import cv2
import numpy as np

# A caption is a punchline, not a subtitle: it leaves after this long so the footage can breathe
CAPTION_SECONDS = 3.5
OPENING_SECONDS = 2.0

# First-clip lines. They ask the viewer something and claim nothing about what is in the footage.
HOOK_CAPTIONS = [
    "Which one is your cat?",
    "Rate these from 1 to 10",
    "Pick your favourite before the end",
    "Tag someone who needs this today",
    "Tell me which one wins",
    "One of these is your pet. Which?",
]
HOOK_CAPTIONS_SI = [
    "ඔයාගේ පූසා කවුද?",
    "ආසම එක මොකක්ද?",
]

# Lines that describe a specific event (a fall, a jump, a laser, food). A random pick cannot know the clip
# shows that event, so these are never burned onto footage they may not match.
EVENT_WORDS = (
    "gravity", "wipeout", "jump", "laser", "treat", "food", "zoomies", "parkour", "mid-air", "slide",
    "leap", "dismount", "curtain", "sofa", "catnip", "shadow", "lava", "target", "full speed", "liquid",
    "red-handed", "stealth", "secret agent", "physics", "regret", "mission failed", "keep scrolling",
    "calculated", "mistake", "plot twist", "couch", "athletic", "panic", "unfortunate", "treason",
    "accidental", "act natural", "how did i",
)


def is_event_caption(text):
    low = str(text or "").lower()
    return any(w in low for w in EVENT_WORDS)


def general_captions(pool):
    """The lines of `pool` that fit any pet clip."""
    return [c for c in pool if not is_event_caption(c)]


def opening_motion(clip_path, seconds=OPENING_SECONDS, step=3):
    """
    Mean absolute change between sampled frames in the first `seconds` of the clip (0-255 scale).
    None when the clip cannot be read: a clip that was not measured is never ranked as the best opener.
    """
    cap = cv2.VideoCapture(clip_path)
    try:
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        limit = int(round(seconds * fps))
        prev, diffs, idx = None, [], 0
        while idx < limit:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                gray = cv2.cvtColor(cv2.resize(frame, (160, 284)), cv2.COLOR_BGR2GRAY).astype(np.int16)
                if prev is not None:
                    diffs.append(float(np.mean(np.abs(gray - prev))))
                prev = gray
            idx += 1
        return round(sum(diffs) / len(diffs), 3) if diffs else None
    finally:
        cap.release()


def order_like_an_editor(items):
    """
    items: dicts with "source_id" and "motion" (None when not measured).
    Returns the same dicts in a new order:
      1. the clip with the most opening motion goes first (the hook),
      2. the next most active clip is held for the end,
      3. the rest keep their order, placed so the same source is not back to back when that is possible.
    With fewer than 3 clips, or no measured motion at all, only rule 3 applies.
    """
    items = list(items)
    if len(items) < 2:
        return items
    measured = sorted((i for i in items if i.get("motion") is not None), key=lambda i: -i["motion"])
    first = last = None
    if measured and len(items) >= 3:
        first = measured[0]
        last = next((m for m in measured[1:] if m.get("source_id") != first.get("source_id")), None)
        if last is None and len(measured) > 1:
            last = measured[1]
    middle = [i for i in items if i is not first and i is not last]

    ordered = [first] if first is not None else []
    while middle:
        prev_src = ordered[-1].get("source_id") if ordered else None
        tail_src = last.get("source_id") if (last is not None and len(middle) == 1) else None
        pick = next((m for m in middle if m.get("source_id") != prev_src and m.get("source_id") != tail_src), None)
        if pick is None:
            pick = next((m for m in middle if m.get("source_id") != prev_src), middle[0])
        ordered.append(pick)
        middle.remove(pick)
    if last is not None:
        ordered.append(last)
    return ordered
