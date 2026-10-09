import os
import sys
import json
import sqlite3
import shutil

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from watermark_detector import WatermarkDetector
from clip_ledger import ClipLedger, BLOCKED_SOURCES_FILE
from lion_automate_v97 import remove_source_from_pool

def test_fix4():
    print("=== TESTING FIX 4: BLOCK BAD SOURCES ONCE ===")
    
    # 1. Test clean source verification
    clean_src = r"C:\LionReel\cache\cache_ByH9LuSILxU.mp4"
    detector = WatermarkDetector()
    print(f"Testing 6-window watermark verification on clean source: {os.path.basename(clean_src)}...")
    is_blocked, hit_count, details = detector.verify_source_watermark(clean_src, n_windows=6, window_dur=4.0)
    print(f"Result on clean source: is_blocked={is_blocked}, hit_count={hit_count}, details={details}")
    assert is_blocked is False, "Clean source should not be blocked!"
    assert hit_count == 0, f"Clean source had unexpected hits: {hit_count}"

    # 2. Test ledger source blocking & clip deletion
    ledger = ClipLedger()
    mock_bad_source = os.path.join(PROJECT_ROOT, "raw", "mock_watermarked_source.mp4")
    mock_bname = os.path.basename(mock_bad_source)

    # Ingest a mock candidate clip
    with ledger._get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used)
            VALUES ('mock_clip_01', 'mock_src', ?, 'CC', 10.0, 20.0, 'cat', 0)
        """, (mock_bad_source,))
        conn.commit()

    # Verify clip exists in table
    with ledger._get_conn() as conn:
        c = conn.execute("SELECT COUNT(*) FROM clips WHERE clip_id = 'mock_clip_01'").fetchone()[0]
        assert c == 1, "Mock clip was not ingested"

    # Mark source blocked
    reason_str = "BLOCKED_WATERMARK (WOA Network in 2/6 windows)"
    print(f"\nMarking mock source blocked: {mock_bname}...")
    ledger.mark_source_blocked(mock_bad_source, reason=reason_str)

    # Verify is_blocked_source returns True
    assert ledger.is_blocked_source(mock_bad_source) is True, "Source should be recognized as blocked in ledger"
    assert ledger.is_blocked_source(mock_bname) is True, "Basename should be recognized as blocked"

    # Verify clip was deleted from clips table
    with ledger._get_conn() as conn:
        c_after = conn.execute("SELECT COUNT(*) FROM clips WHERE clip_id = 'mock_clip_01'").fetchone()[0]
        assert c_after == 0, f"Clips from blocked source should have been deleted, found {c_after}"

    # Verify blocked_sources table has the reason
    with ledger._get_conn() as conn:
        row = conn.execute("SELECT reason FROM blocked_sources WHERE source_name = ?", (mock_bname,)).fetchone()
        assert row is not None, "Source not found in SQLite blocked_sources table"
        assert "BLOCKED_WATERMARK" in row["reason"], f"Unexpected reason: {row['reason']}"

    # 3. Test remove_source_from_pool and credits_registry.csv
    print("\nTesting remove_source_from_pool & credits_registry.csv...")
    remove_source_from_pool(mock_bad_source, reason=reason_str)

    registry_path = os.path.join(PROJECT_ROOT, "credits_registry.csv")
    assert os.path.exists(registry_path), "credits_registry.csv was not created!"
    with open(registry_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert mock_bname in content, f"Source {mock_bname} not found in credits_registry.csv"
    assert "BLOCKED" in content, "Status BLOCKED not recorded in credits_registry.csv"

    # Cleanup mock entries
    with ledger._get_conn() as conn:
        conn.execute("DELETE FROM blocked_sources WHERE source_name = ?", (mock_bname,))
        conn.commit()

    print("\nALL FIX 4 TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_fix4()
