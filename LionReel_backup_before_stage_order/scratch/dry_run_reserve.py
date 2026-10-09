import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger

ledger = ClipLedger()
clips = ledger.reserve_clips_for_short(count=20, animal_type="cat", short_id="test_dry_run_check")
print(f"Reserved clips count: {len(clips)}")
for c in clips:
    print(f"  {c['clip_id']}: {c['source_id']} [{c['start_s']}s - {c['end_s']}s]")

ledger.release_reservation("test_dry_run_check")
