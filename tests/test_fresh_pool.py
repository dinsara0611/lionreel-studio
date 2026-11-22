"""Short videos use fresh sources only, at most 2 clips per source, and overlapping windows count once."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clip_ledger import ClipLedger


def make_ledger(tmp_path, windows, finished=()):
    """windows: (clip_id, source, start). finished: (job_id, source, start) already in a finished video."""
    ledger = ClipLedger(db_path=str(tmp_path / "ledger.db"))
    with sqlite3.connect(ledger.db_path) as conn:
        for cid, src, st in windows:
            p = tmp_path / f"cache_{src}.mp4"
            p.write_bytes(b"x")
            conn.execute("INSERT INTO clips (clip_id, source_id, source_url_or_path, start_s, end_s, is_verified, times_used, animal_type, status) "
                         "VALUES (?, ?, ?, ?, ?, 1, 0, 'cat', 'verified')", (cid, f"cache_{src}", str(p), st, st + 7.5))
        for jid, src, st in finished:
            conn.execute("INSERT INTO finished_video_windows (job_id, source_id, source_url_or_path, start_s, end_s, clip_id, is_production, channel) "
                         "VALUES (?, ?, ?, ?, ?, ?, 1, 'cat')", (jid, src, str(tmp_path / f"cache_{src}.mp4"), st, st + 7.5, f"{jid}_{src}_{st}"))
        conn.commit()
    return ledger


def test_overlapping_windows_count_once(tmp_path):
    # Seen in a real job: '6 fresh clips available, needed 6' and the job still failed
    ledger = make_ledger(tmp_path, [("a1", "A", 10), ("a2", "A", 12), ("b1", "B", 10), ("c1", "C", 10)])
    assert ledger.get_pool_ready_and_capacity("cat", target_clips=6)["ready"] == 3


def test_resting_sources_are_not_ready(tmp_path):
    ledger = make_ledger(tmp_path, [("a1", "A", 100), ("b1", "B", 10)], finished=[("job1", "A", 10)])
    assert ledger.get_pool_ready_and_capacity("cat", target_clips=6)["ready"] == 1
    assert ledger.get_pool_ready_and_capacity("cat", target_clips=6, allow_reuse=True)["ready"] == 2


def test_short_video_never_takes_a_resting_source(tmp_path):
    ledger = make_ledger(tmp_path, [("a1", "A", 100), ("a2", "A", 200), ("b1", "B", 10)], finished=[("job1", "A", 10)])
    got = ledger.reserve_clips_for_short(count=3, animal_type="cat", short_id="job2", allow_reuse=False,
                                         min_required=1, patience_budget_sec=0)
    assert [c["clip_id"] for c in got] == ["b1"]


def test_at_most_two_clips_of_one_source(tmp_path):
    ledger = make_ledger(tmp_path, [(f"a{i}", "A", 20 + i * 40) for i in range(5)] + [("b1", "B", 10), ("c1", "C", 10)])
    got = ledger.reserve_clips_for_short(count=6, animal_type="cat", short_id="job2", allow_reuse=False,
                                         min_required=1, patience_budget_sec=0)
    from_a = [c for c in got if "A" in str(c.get("source_id"))]
    assert len(from_a) <= 2 and len(got) == 4
