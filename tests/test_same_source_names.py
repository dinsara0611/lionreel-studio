"""A moment used in one finished video is never used again, however its source name was written."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clip_ledger import ClipLedger, is_same_moment, source_key

PATH = r"C:\LionReel\cache\cache_sZHtchTlOKc.mp4"


def test_every_spelling_is_one_source():
    assert source_key(PATH) == source_key("cache_sZHtchTlOKc") == source_key("sZHtchTlOKc") == "szhtchtlokc"
    assert source_key("cache_other") != source_key("sZHtchTlOKc")


def test_same_moment_across_spellings():
    # The two finished videos from the bug report: 134.3-141.8 s stored as 'sZHtchTlOKc',
    # 134.69-142.19 s picked again as 'cache_sZHtchTlOKc'
    assert is_same_moment("cache_sZHtchTlOKc", 134.69, 142.19, "sZHtchTlOKc", 134.30, 141.80)
    assert not is_same_moment("cache_sZHtchTlOKc", 200.0, 207.5, "sZHtchTlOKc", 134.30, 141.80)


def test_finished_window_blocks_the_other_spelling(tmp_path):
    ledger = ClipLedger(db_path=str(tmp_path / "ledger.db"))
    with sqlite3.connect(ledger.db_path) as conn:
        conn.execute("INSERT INTO finished_video_windows (job_id, source_id, source_url_or_path, start_s, end_s, clip_id, is_production, channel) "
                     "VALUES (?, ?, ?, ?, ?, ?, 1, 'cat')",
                     ("job_a", "sZHtchTlOKc", PATH, 134.30, 141.80, "c_cat_cache_sZHtchTlOKc_134_139"))
        conn.commit()
    used, _ = ledger.is_window_used_in_production("cache_sZHtchTlOKc", 134.69, 142.19, channel="cat")
    assert used
    free, _ = ledger.is_window_used_in_production("cache_sZHtchTlOKc", 300.0, 307.5, channel="cat")
    assert not free


def test_ledger_counts_the_window_as_used(tmp_path):
    ledger = ClipLedger(db_path=str(tmp_path / "ledger.db"))
    src = tmp_path / "cache_sZHtchTlOKc.mp4"
    src.write_bytes(b"x")
    with sqlite3.connect(ledger.db_path) as conn:
        conn.execute("INSERT INTO finished_video_windows (job_id, source_id, source_url_or_path, start_s, end_s, clip_id, is_production, channel) "
                     "VALUES ('job_a', 'sZHtchTlOKc', ?, 134.30, 141.80, 'old', 1, 'cat')", (str(src),))
        conn.execute("INSERT INTO clips (clip_id, source_id, source_url_or_path, start_s, end_s, is_verified, times_used, animal_type) "
                     "VALUES ('new', 'cache_sZHtchTlOKc', ?, 134.69, 142.19, 1, 0, 'cat')", (str(src),))
        conn.commit()
    counts = ledger.get_ledger_counts("cat", include_windows=True)
    assert [r["clip_id"] for r in counts["windows"]["used"]] == ["new"]
    assert counts["usable_now"] == 0
