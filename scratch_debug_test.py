import os
import sys
import tempfile
import json
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger, are_frame_hashes_matching

def make_hash(s):
    return format(int(hashlib.md5(str(s).encode("utf-8")).hexdigest(), 16), "064b")

temp_dir = tempfile.TemporaryDirectory()
db_path = os.path.join(temp_dir.name, "debug_ledger.db")
ledger = ClipLedger(db_path=db_path)

print("Creating sources...")
sources = []
for i in range(12):
    sp = os.path.join(temp_dir.name, f"source_{i:02d}.mp4")
    with open(sp, "wb") as f:
        f.write(b"RIFF" + b"\x00" * 200000)
    sources.append(sp)

print("Seeding clips...")
with ledger._get_conn() as conn:
    for s_idx, sp in enumerate(sources):
        sid = os.path.splitext(os.path.basename(sp))[0]
        for w_idx in range(2):
            cid = f"clip_{sid}_w{w_idx}"
            st = float(w_idx * 15.0 + 2.0)
            en = st + 7.5
            hashes = [make_hash(f"src_{s_idx}_w_{w_idx}_frame_{k}") for k in range(5)]
            conn.execute("""
                INSERT INTO clips (
                    clip_id, source_id, source_url_or_path, animal_type,
                    start_s, end_s, is_verified, times_used,
                    quality_score, funny_score, sharpness, framing_score, orientation,
                    fingerprint
                ) VALUES (?, ?, ?, 'cat', ?, ?, 1, 0, 95.0, 90.0, 200.0, 95.0, 'vertical', ?)
            """, (cid, sid, sp, st, en, json.dumps(hashes)))
    conn.commit()

print("Registering Job 1 output...")
job1_id = "lionreel_cat_prod_job_1"
clip_mapping_1 = []
for idx in range(4):
    clip_mapping_1.append({
        "clip_id": f"clip_source_{idx:02d}_w0",
        "source_id": f"source_{idx:02d}",
        "source_url_or_path": sources[idx],
        "source_file": sources[idx],
        "start_s": 2.0,
        "end_s": 9.5,
        "duration": 7.5,
        "frame_hashes": [make_hash(f"src_{idx}_w_0_frame_{k}") for k in range(5)]
    })

ledger.register_output(
    job_id=job1_id,
    output_filename=f"{job1_id}.mp4",
    sha256="dummy_sha256_1",
    clip_ids=[c["clip_id"] for c in clip_mapping_1],
    duration_sec=30.0,
    render_time_sec=12.0,
    clip_windows=clip_mapping_1,
    is_production=True
)
print("Job 1 registered.")

print("Calling reserve_clips_for_short for Job 2...")
res = ledger.reserve_clips_for_short(
    count=4,
    animal_type="cat",
    short_id="lionreel_cat_prod_job_2",
    allow_reuse=False,
    min_required=2,
    patience_budget_sec=0.0
)
print(f"reserve_clips_for_short returned {len(res)} clips:")
for c in res:
    print(f"  Reserved: {c['clip_id']} ({c['source_id']})")
print("SUCCESS!")
