"""
LIONREEL STUDIO — CLIP LEDGER (FIX 2)
Persistent SQLite-backed clip ledger preventing repeated clips across shorts,
tracking perceptual fingerprints, managing pool usage cycles, and releasing clips on QA failure.
"""

import os
import json
import sqlite3
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

def get_ledger_db_path() -> str:
    # 1. Environment variable override
    env_path = os.environ.get("LIONREEL_DATA_DIR")
    if env_path:
        return os.path.join(env_path, "clip_ledger.db")

    # 2. Check config.json for LOCAL_DATA_DIR
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base_dir, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if cfg.get("LOCAL_DATA_DIR"):
                    p = os.path.join(cfg["LOCAL_DATA_DIR"], "clip_ledger.db")
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    return p
        except Exception:
            pass

    # 3. Default to fast local SSD (C:\LionReel\data\clip_ledger.db) on Windows
    local_default = os.path.join("C:\\", "LionReel", "data", "clip_ledger.db")
    try:
        os.makedirs(os.path.dirname(local_default), exist_ok=True)
        return local_default
    except Exception:
        pass

    # 4. Fallback to repository data/ directory
    fallback = os.path.join(base_dir, "data", "clip_ledger.db")
    os.makedirs(os.path.dirname(fallback), exist_ok=True)
    return fallback

LEDGER_DB_PATH = get_ledger_db_path()
BLOCKED_SOURCES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "blocked_sources.json")

def hamming_distance(s1: str, s2: str) -> int:
    return sum(c1 != c2 for c1, c2 in zip(s1, s2))

def compute_phash(frame) -> str:
    """Computes a 64-bit DCT perceptual hash on a frame."""
    if frame is None or frame.size == 0:
        return "0" * 64
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
    resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(resized))
    dct_low = dct[:8, :8]
    med = np.median(dct_low[1:, 1:])
    bits = (dct_low > med).flatten()
    return "".join("1" if b else "0" for b in bits)

_compute_phash = compute_phash
_hamming_distance = hamming_distance

class ClipLedger:
    def __init__(self, db_path=LEDGER_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    clip_id TEXT PRIMARY KEY,
                    source_id TEXT,
                    source_url_or_path TEXT,
                    license TEXT,
                    start_s REAL,
                    end_s REAL,
                    fingerprint TEXT, -- JSON array of frame phashes
                    quality_score REAL DEFAULT 0.0,
                    funny_score REAL DEFAULT 0.0,
                    animal_type TEXT DEFAULT 'cat',
                    times_used INTEGER DEFAULT 0,
                    last_used_short_id TEXT,
                    pending_short_id TEXT,
                    pool_cycle INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS output_registry (
                    job_id TEXT PRIMARY KEY,
                    output_filename TEXT,
                    sha256 TEXT UNIQUE,
                    clip_ids TEXT,
                    duration_sec REAL,
                    render_time_sec REAL,
                    created_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blocked_sources (
                    source_path TEXT PRIMARY KEY,
                    source_name TEXT,
                    reason TEXT,
                    blocked_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS source_analysis_cache (
                    source_hash TEXT PRIMARY KEY,
                    source_path TEXT,
                    analysis_json TEXT,
                    updated_at TEXT
                )
            """)
            conn.commit()

    def get_system_pool_cycle(self, animal_type='cat') -> int:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT value FROM system_state WHERE key = ?", (f"pool_cycle_{animal_type}",))
            row = cur.fetchone()
            if row:
                return int(row["value"])
            return 1

    def set_system_pool_cycle(self, animal_type: str, cycle: int):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO system_state (key, value) VALUES (?, ?)",
                (f"pool_cycle_{animal_type}", str(cycle))
            )
            conn.commit()

    def mark_source_blocked(self, source_path: str, reason: str = "BLOCKED_LOW_RES") -> None:
        """
        Marks a source as blocked in SQLite and blocked_sources.json,
        and deletes/releases all candidate clips from this source so they are never used or counted.
        """
        bname = os.path.basename(source_path)
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO blocked_sources (source_path, source_name, reason, blocked_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (source_path, bname, reason))
            # Delete any clips registered from this source so they never burn pool slots
            conn.execute("""
                DELETE FROM clips 
                WHERE source_url_or_path = ? OR source_id = ? OR source_url_or_path LIKE ?
            """, (source_path, os.path.splitext(bname)[0], f"%{bname}%"))
            conn.commit()

        # Update blocked_sources.json
        if os.path.exists(BLOCKED_SOURCES_FILE):
            try:
                with open(BLOCKED_SOURCES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                blocked_files = set(data.get("blocked_files", []))
                if bname not in blocked_files:
                    data.setdefault("blocked_files", []).append(bname)
                    with open(BLOCKED_SOURCES_FILE, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
            except Exception:
                pass

    def get_source_analysis(self, source_hash: str):
        try:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT analysis_json FROM source_analysis_cache WHERE source_hash = ?", (source_hash,))
                row = cur.fetchone()
                if row:
                    return json.loads(row["analysis_json"])
        except Exception:
            pass
        return None

    def save_source_analysis(self, source_hash: str, source_path: str, analysis: dict) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO source_analysis_cache (source_hash, source_path, analysis_json, updated_at)
                    VALUES (?, ?, ?, datetime('now'))
                """, (source_hash, source_path, json.dumps(analysis)))
                conn.commit()
        except Exception:
            pass

    def is_blocked_source(self, filepath_or_url: str, frame_phashes: list = None) -> bool:
        norm_target = os.path.normpath(str(filepath_or_url)).lower()
        bname = os.path.basename(filepath_or_url).lower()

        # 0. Check SQLite blocked_sources table
        try:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT 1 FROM blocked_sources WHERE LOWER(source_name) = ? OR LOWER(source_path) = ?", (bname, norm_target))
                if cur.fetchone():
                    return True
        except Exception:
            pass

        if not os.path.exists(BLOCKED_SOURCES_FILE):
            return False
        try:
            with open(BLOCKED_SOURCES_FILE, "r", encoding="utf-8") as f:
                blocked = json.load(f)
            
            # 1. Filename / path / directory match
            for b_file in blocked.get("blocked_files", []):
                if os.path.basename(b_file).lower() in norm_target:
                    return True
            for b_dir in blocked.get("reference_directories", []):
                if f"\\{b_dir.lower()}\\" in norm_target or f"/{b_dir.lower()}/" in norm_target:
                    return True

            # 2. Perceptual fingerprint comparison
            if frame_phashes:
                for entry in blocked.get("perceptual_fingerprints", []):
                    ref_hashes = entry.get("frame_phashes", [])
                    # Compare each candidate hash against reference hashes
                    match_count = 0
                    for cand_h in frame_phashes:
                        for ref_h in ref_hashes:
                            if hamming_distance(cand_h, ref_h) <= 7: # > 89% visual similarity
                                match_count += 1
                                break
                    if match_count >= 2: # 2 or more frames match reference video
                        return True
        except Exception:
            pass
        return False

    def add_clip(self, clip_id, source_id, source_url_or_path, license_name, start_s, end_s,
                 frame_phashes, quality_score=0.0, funny_score=0.0, animal_type='cat') -> bool:
        # Check if source or fingerprint matches blocked benchmark
        if self.is_blocked_source(source_url_or_path, frame_phashes):
            return False

        current_cycle = self.get_system_pool_cycle(animal_type)
        fp_json = json.dumps(frame_phashes) if isinstance(frame_phashes, list) else str(frame_phashes)

        with self._get_conn() as conn:
            # Check near duplicate across entire existing clips
            cur = conn.execute("SELECT clip_id, fingerprint FROM clips WHERE animal_type = ?", (animal_type,))
            existing = cur.fetchall()
            for r in existing:
                try:
                    r_hashes = json.loads(r["fingerprint"])
                    if isinstance(frame_phashes, list) and isinstance(r_hashes, list) and frame_phashes and r_hashes:
                        matches = sum(1 for ch in frame_phashes for rh in r_hashes if hamming_distance(ch, rh) <= 6)
                        if matches >= 3:
                            return False # Near duplicate already registered
                except:
                    pass

            conn.execute("""
                INSERT OR REPLACE INTO clips 
                (clip_id, source_id, source_url_or_path, license, start_s, end_s, fingerprint,
                 quality_score, funny_score, animal_type, pool_cycle)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (clip_id, source_id, source_url_or_path, license_name, start_s, end_s,
                  fp_json, quality_score, funny_score, animal_type, current_cycle))
            conn.commit()
        return True

    def get_pool_status(self, animal_type='cat') -> dict:
        cycle = self.get_system_pool_cycle(animal_type)
        with self._get_conn() as conn:
            cur_tot = conn.execute("SELECT COUNT(*) AS c FROM clips WHERE animal_type = ?", (animal_type,))
            total = cur_tot.fetchone()["c"]

            cur_used = conn.execute(
                "SELECT COUNT(*) AS c FROM clips WHERE animal_type = ? AND times_used > 0",
                (animal_type,)
            )
            used = cur_used.fetchone()["c"]

            cur_unused = conn.execute(
                "SELECT COUNT(*) AS c FROM clips WHERE animal_type = ? AND times_used == 0 AND pending_short_id IS NULL",
                (animal_type,)
            )
            unused = cur_unused.fetchone()["c"]
            pct = round((used / total * 100.0), 1) if total > 0 else 0.0
            warning = (unused <= 2) or (pct >= 85.0)

            return {
                "animal_type": animal_type,
                "pool_cycle": cycle,
                "total_clips": total,
                "used_clips": used,
                "unused_clips": unused,
                "usage_pct": pct,
                "warning": warning,
                "status_label": f"Clip pool: {used} of {total} used ({pct}%)"
            }

    def reserve_clips_for_short(self, count: int, animal_type: str, short_id: str, allow_reuse: bool = False, min_required: int = None) -> list:
        # Derive random seed from short_id so selection is diverse and deterministic per job
        import random, hashlib
        seed_val = int(hashlib.sha256(str(short_id).encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed_val)

        with self._get_conn() as conn:
            # Query strictly unused clips (times_used == 0) unless explicit allow_reuse is granted
            if allow_reuse:
                cur = conn.execute("""
                    SELECT * FROM clips 
                    WHERE animal_type = ? AND (pending_short_id IS NULL OR pending_short_id = ?)
                    ORDER BY times_used ASC, funny_score DESC
                """, (animal_type, short_id))
            else:
                cur = conn.execute("""
                    SELECT * FROM clips 
                    WHERE animal_type = ? AND times_used == 0 AND (pending_short_id IS NULL OR pending_short_id = ?)
                    ORDER BY funny_score DESC, quality_score DESC
                """, (animal_type, short_id))
            eligible = [dict(r) for r in cur.fetchall()]

            # Verify that source file physically exists on disk and is not blocked
            eligible = [c for c in eligible if os.path.exists(c["source_url_or_path"]) and not self.is_blocked_source(c["source_url_or_path"])]

            needed_min = min_required if min_required is not None else min(count, 3)
            if len(eligible) < needed_min:
                raise RuntimeError(f"NO_NEW_CLIPS_AVAILABLE: Pool has only {len(eligible)} unused clips (needed {needed_min}). Please add new sources.")

            actual_count = min(count, len(eligible))

            # Group eligible by source to enforce pool diversity (>= 3 distinct sources when available)
            source_groups = {}
            for cand in eligible:
                src_id = cand.get("source_id") or os.path.basename(cand["source_url_or_path"])
                source_groups.setdefault(src_id, []).append(cand)

            # Shuffle candidates within each source using seeded random
            for src_id in source_groups:
                rng.shuffle(source_groups[src_id])

            # Select diverse candidates across distinct sources round-robin
            selected = []
            selected_hashes = []
            source_keys = list(source_groups.keys())
            rng.shuffle(source_keys)

            # Pick from each source in rotation to maximize source diversity
            while len(selected) < actual_count:
                progress_made = False
                for src_id in source_keys:
                    if len(selected) >= actual_count:
                        break
                    group = source_groups[src_id]
                    if not group:
                        continue

                    cand = group.pop(0)
                    try:
                        c_hashes = json.loads(cand["fingerprint"])
                    except:
                        c_hashes = []

                    # Ensure no near-duplicates in this candidate batch (at least 4 matching frames)
                    is_near_dup = False
                    for ex_hashes in selected_hashes:
                        if c_hashes and ex_hashes:
                            matches = sum(1 for ch in c_hashes for rh in ex_hashes if hamming_distance(ch, rh) <= 4)
                            if matches >= 4:
                                is_near_dup = True
                                break
                    if is_near_dup:
                        continue

                    selected.append(cand)
                    selected_hashes.append(c_hashes)
                    progress_made = True

                if not progress_made:
                    break

            if len(selected) < needed_min:
                raise RuntimeError(f"NO_NEW_CLIPS_AVAILABLE: Diverse clip selection found only {len(selected)} unique clips (needed {needed_min}). Please add new sources.")

            # Mark selected clips as pending for this short
            for s in selected:
                conn.execute(
                    "UPDATE clips SET pending_short_id = ? WHERE clip_id = ?",
                    (short_id, s["clip_id"])
                )
            conn.commit()
            return selected

    def check_duplicate_output(self, sha256: str, clip_ids: list):
        with self._get_conn() as conn:
            # 1. Exact SHA256 match check
            cur = conn.execute("SELECT job_id FROM output_registry WHERE sha256 = ?", (sha256,))
            row = cur.fetchone()
            if row:
                return True, f"DUPLICATE_OUTPUT: SHA256 hash matches previous output from job '{row['job_id']}'"

            # 2. Exact clip sequence match check
            sorted_clips_json = json.dumps(sorted(clip_ids))
            cur2 = conn.execute("SELECT job_id, clip_ids FROM output_registry")
            for r in cur2.fetchall():
                try:
                    existing_clips = json.dumps(sorted(json.loads(r["clip_ids"])))
                    if existing_clips == sorted_clips_json:
                        return True, f"DUPLICATE_OUTPUT: Exact clip list {clip_ids} was already used in job '{r['job_id']}'"
                except Exception:
                    pass
        return False, ""

    def register_output(self, job_id: str, output_filename: str, sha256: str, clip_ids: list, duration_sec: float, render_time_sec: float):
        import time
        created_at = time.strftime('%Y-%m-%d %H:%M:%S')
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO output_registry 
                (job_id, output_filename, sha256, clip_ids, duration_sec, render_time_sec, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (job_id, output_filename, sha256, json.dumps(clip_ids), duration_sec, render_time_sec, created_at))
            conn.commit()

    def commit_short(self, short_id: str):
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE clips 
                SET times_used = times_used + 1, 
                    last_used_short_id = ?,
                    pending_short_id = NULL
                WHERE pending_short_id = ?
            """, (short_id, short_id))
            conn.commit()

    def release_short(self, short_id: str):
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE clips 
                SET pending_short_id = NULL
                WHERE pending_short_id = ?
            """, (short_id,))
            conn.commit()

    def release_single_clip(self, clip_id: str):
        """Releases a single reserved clip back to the pool if rejected during processing."""
        with self._get_conn() as conn:
            conn.execute("UPDATE clips SET pending_short_id = NULL WHERE clip_id = ?", (clip_id,))
            conn.commit()

    def release_reservation(self, short_id: str):
        return self.release_short(short_id)

    def cleanup_stale_reservations(self, current_job_id: str = None):
        """Clears pending reservations that are not the current active job."""
        with self._get_conn() as conn:
            if current_job_id:
                conn.execute("UPDATE clips SET pending_short_id = NULL WHERE pending_short_id != ?", (current_job_id,))
            else:
                conn.execute("UPDATE clips SET pending_short_id = NULL")
            conn.commit()

    def delete_output(self, identifier: str) -> bool:
        """
        Removes an output from output_registry and releases its clips back to the pool
        by decrementing times_used and clearing last_used_short_id.
        """
        if not identifier:
            return False
        stem = os.path.splitext(os.path.basename(identifier))[0]
        with self._get_conn() as conn:
            cur = conn.execute("""
                SELECT job_id, clip_ids FROM output_registry 
                WHERE job_id = ? OR job_id = ? OR output_filename = ? OR output_filename LIKE ?
            """, (identifier, stem, identifier, f"%{stem}%"))
            rows = cur.fetchall()
            for row in rows:
                j_id = row["job_id"]
                try:
                    c_ids = json.loads(row["clip_ids"]) if row["clip_ids"] else []
                    for c_id in c_ids:
                        conn.execute("""
                            UPDATE clips 
                            SET times_used = MAX(0, times_used - 1),
                                last_used_short_id = CASE WHEN last_used_short_id = ? THEN NULL ELSE last_used_short_id END,
                                pending_short_id = NULL
                            WHERE clip_id = ?
                        """, (j_id, c_id))
                except Exception:
                    pass
                conn.execute("DELETE FROM output_registry WHERE job_id = ?", (j_id,))

            conn.execute("""
                UPDATE clips 
                SET times_used = MAX(0, times_used - 1),
                    last_used_short_id = NULL
                WHERE last_used_short_id = ? OR last_used_short_id = ?
            """, (identifier, stem))
            conn.execute("""
                UPDATE clips 
                SET pending_short_id = NULL
                WHERE pending_short_id = ? OR pending_short_id = ?
            """, (identifier, stem))
            conn.commit()
        return True

    def reserve_clips(self, count: int = 3, animal_mode: str = 'cat', short_id: str = "", min_required: int = None, **kwargs) -> list:
        # Flexible argument handling
        if isinstance(count, str) and not isinstance(animal_mode, str):
            j_id = count
            c_val = kwargs.get("target_count", animal_mode)
            a_mode = short_id if short_id else "cat"
        elif isinstance(short_id, int):
            j_id = kwargs.get("short_id", "")
            c_val = kwargs.get("target_count", short_id)
            a_mode = animal_mode
        else:
            j_id = short_id or kwargs.get("short_id", "")
            c_val = kwargs.get("target_count", count)
            a_mode = animal_mode
        return self.reserve_clips_for_short(c_val, a_mode, j_id, min_required=min_required)

    def ingest_candidate(self, source_path: str, start_s: float, end_s: float,
                         license_type: str = "CC-BY", animal_type: str = "cat",
                         quality_score: float = 0.8, funny_score: float = 0.8) -> str:
        """
        Samples 5 frames across the candidate range to compute perceptual pHashes,
        generates a unique clip_id, and inserts into clip_ledger.db.
        """
        cap = cv2.VideoCapture(source_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_f = int(start_s * fps)
        end_f = int(end_s * fps)
        dur_f = max(1, end_f - start_f)

        phashes = []
        for i in range(5):
            f_idx = start_f + int(dur_f * (i + 0.5) / 5)
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if ret and frame is not None:
                phashes.append(compute_phash(frame))
        cap.release()

        src_id = os.path.splitext(os.path.basename(source_path))[0]
        clip_id = f"c_{src_id}_{int(start_s)}_{int(end_s)}"

        success = self.add_clip(
            clip_id=clip_id,
            source_id=src_id,
            source_url_or_path=source_path,
            license_name=license_type,
            start_s=start_s,
            end_s=end_s,
            frame_phashes=phashes,
            quality_score=quality_score,
            funny_score=funny_score,
            animal_type=animal_type
        )
        return clip_id if success else None
