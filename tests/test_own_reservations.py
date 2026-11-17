"""A job's own planned clips are its footage: the preflight must not see them as missing and harvest."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clip_ledger import ClipLedger


def ledger_with_reserved(tmp_path, job_id, n_reserved=6, n_free=3):
    ledger = ClipLedger(db_path=str(tmp_path / "ledger.db"))
    with sqlite3.connect(ledger.db_path) as conn:
        for i in range(n_reserved + n_free):
            src = tmp_path / f"cache_src{i}.mp4"
            src.write_bytes(b"x")
            conn.execute("INSERT INTO clips (clip_id, source_id, source_url_or_path, start_s, end_s, is_verified, times_used, animal_type, pending_short_id) "
                         "VALUES (?, ?, ?, 10, 17.5, 1, 0, 'cat', ?)",
                         (f"c{i}", f"cache_src{i}", str(src), job_id if i < n_reserved else None))
        conn.commit()
    return ledger


def test_own_reservations_count_as_ready(tmp_path):
    # Seen in a real job: planner reserved 6 of 6, preflight counted 3 usable and harvested for 20+ minutes
    ledger = ledger_with_reserved(tmp_path, "job_me")
    assert ledger.get_pool_ready_and_capacity("cat", target_clips=6, current_job_id="job_me")["ready"] == 9
    assert "have 9 usable" in ledger.preflight_line(6, "cat", current_job_id="job_me")


def test_another_jobs_reservations_are_not_ready(tmp_path):
    ledger = ledger_with_reserved(tmp_path, "job_other")
    assert ledger.get_pool_ready_and_capacity("cat", target_clips=6, current_job_id="job_me")["ready"] == 3
    assert ledger.get_pool_ready_and_capacity("cat", target_clips=6)["ready"] == 3
