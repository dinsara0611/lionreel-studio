"""The progress card reports a footage search from the job log, not a guessed stage."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import web_server as ws

LOG = """[SEQ:19] [10:00:04] [INFO] Bank deficit detected (4 usable < 6 needed). Running real harvest for 2 clips...
[SEQ:21] [10:04:40] [INFO] STARTING REAL HARVEST | Target Needed: 7 | Mode: cat | Queries: 7
[SEQ:25] [10:04:54] [INFO] Downloading legal CC source: tsjBGPbkwPk...
[SEQ:26] [10:09:00] [INFO] Downloaded successfully: cache_tsjBGPbkwPk.mp4 (61.0 MB)
[SEQ:31] [10:09:34] [INFO] Window c_cache_tsjBGPbkwPk_536_611 VERIFIED! (Sharpness: 171.7, Pet: 100%)
[SEQ:31] [10:09:34] [INFO] Window c_cache_tsjBGPbkwPk_536_611 VERIFIED! (Sharpness: 171.7, Pet: 100%)
[SEQ:33] [10:09:43] [INFO] Window c_cache_tsjBGPbkwPk_779_854 VERIFIED! (Sharpness: 276.0, Pet: 100%)
[SEQ:42] [10:10:27] [INFO] Downloading legal CC source: vVVE7Dezg5U...""".splitlines()


def test_search_in_progress_is_counted_from_the_log():
    hp = ws.harvest_progress(LOG)
    assert hp == {"active": True, "found": 2, "target": 7, "sources_downloaded": 1, "downloading": "vVVE7Dezg5U"}


def test_finished_search_is_not_active():
    hp = ws.harvest_progress(LOG + ["[SEQ:90] [10:30:00] [INFO] HARVEST FINISHED | Time: 1.0s"])
    assert hp["active"] is False


def test_no_search_returns_none():
    assert ws.harvest_progress(["[SEQ:1] [10:00:00] [INFO] Starting production"]) is None


def test_pet_percentage_is_not_read_as_render_progress():
    src = open(os.path.join(os.path.dirname(__file__), "..", "gui", "app.js"), encoding="utf-8").read()
    m = re.search(r"const tqdmMatch = line\.match\(/(.+?)/\);", src)
    rx = re.compile(m.group(1))
    assert not rx.search("Window c_x VERIFIED! (Sharpness: 171.7, Pet: 100%)")
    assert rx.search("t:  45%|####      | 120/270")
