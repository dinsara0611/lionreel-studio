import os, sys, sqlite3
sys.path.insert(0, r"g:\My Drive\Cat make")
from clip_ledger import ClipLedger
from lion_automate_v97 import LionReelV97Pipeline

pipeline = LionReelV97Pipeline()
sources = pipeline.harvest_source_clips("cat")
print(f"Discovered {len(sources)} sources: {[os.path.basename(s) for s in sources]}")

# Populate ledger if needed
pipeline.populate_ledger_from_sources(sources, "cat")

# Check ledger pool status
pool = pipeline.ledger.get_pool_status("cat")
print("Cat Pool Status:", pool)

# Inspect clips in DB
conn = sqlite3.connect(r"g:\My Drive\Cat make\data\clip_ledger.db")
c = conn.cursor()
c.execute("SELECT count(*), count(DISTINCT source_url_or_path) FROM clips WHERE animal_type='cat' AND times_used=0 AND pending_short_id IS NULL")
print("Available clips & sources:", c.fetchall())
conn.close()
