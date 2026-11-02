import os
from clip_ledger import ClipLedger, LEDGER_DB_PATH

l = ClipLedger()
print("LEDGER_DB_PATH:", LEDGER_DB_PATH)
print("l.db_path:", l.db_path)
import glob
dirs = [r'g:\My Drive\Cat make\raw', r'g:\My Drive\Cat make\reference', r'C:\LionReel\cache']
cd_sources = l.get_cooldown_sources('cat', last_n_jobs=3)
print("Cooldown sources:", cd_sources)

for d in dirs:
    if os.path.exists(d):
        mp4s = glob.glob(os.path.join(d, "*.mp4"))
        print(f"\nDirectory: {d} ({len(mp4s)} mp4s)")
        for p in mp4s:
            b = os.path.basename(p)
            stem = os.path.splitext(b)[0].lower()
            sz = os.path.getsize(p) / (1024 * 1024)
            is_cd = stem in cd_sources
            print(f"  {b}: {sz:.1f} MB | cooldown={is_cd}")
