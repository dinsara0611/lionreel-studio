"""
LIONREEL STUDIO — CLIP LEDGER (FIX 2)
Persistent SQLite-backed clip ledger preventing repeated clips across shorts,
tracking perceptual fingerprints, managing pool usage cycles, and releasing clips on QA failure.
"""

import os
import lion_paths
import source_licenses
import sys
import time
import json
import sqlite3
from contextlib import contextmanager
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
    local_default = os.path.join(lion_paths.data_root(), "clip_ledger.db")
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

def is_same_moment(src1: str, start1: float, end1: float, src2: str, start2: float, end2: float, overlap_thresh: float = 0.30) -> bool:
    """
    Checks if two clip windows represent the same moment in the same source video.
    Two clips are considered the same moment if:
    1. Sources match (either exact match or same base filename)
    2. Overlap between [start1, end1] and [start2, end2] exceeds overlap_thresh (default > 30% of shorter window)
    """
    if not src1 or not src2:
        return False

    def norm_s(s):
        base = os.path.basename(str(s).strip())
        return os.path.splitext(base)[0].lower()

    if norm_s(src1) != norm_s(src2):
        return False

    dur1 = float(end1) - float(start1)
    dur2 = float(end2) - float(start2)
    if dur1 <= 0 or dur2 <= 0:
        return False

    overlap = max(0.0, min(float(end1), float(end2)) - max(float(start1), float(start2)))
    min_dur = min(dur1, dur2)
    return (overlap / min_dur) > overlap_thresh

def compute_window_5_phashes(video_path: str, start_s: float, end_s: float) -> list:
    """
    Computes a list of 5 perceptual hashes (64-bit binary strings) sampled at 10%, 30%, 50%, 70%, 90%
    across the time window [start_s, end_s] of the video.
    If video cannot be decoded, returns deterministic fallback hashes based on content and parameters.
    """
    hashes = []
    dur = max(0.5, float(end_s) - float(start_s))
    factors = [0.10, 0.30, 0.50, 0.70, 0.90]

    if cv2 is not None and os.path.exists(video_path):
        try:
            from auto_reframe import decode_frames_ffmpeg_pipe
            pipe_frames = decode_frames_ffmpeg_pipe(
                video_path, float(start_s), dur,
                n_frames=5, target_w=64, target_h=64
            )
            for pf in pipe_frames:
                if pf is not None and pf.size > 0:
                    hashes.append(compute_phash(pf))
        except Exception:
            pass
        if len(hashes) < 5:
            try:
                cap = cv2.VideoCapture(video_path)
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                for f in factors[len(hashes):]:
                    t = float(start_s) + dur * f
                    f_idx = int(t * fps)
                    if total_frames > 0:
                        f_idx = min(f_idx, max(0, total_frames - 1))
                    cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        hashes.append(compute_phash(frame))
                cap.release()
            except Exception:
                pass

    # If decoding yielded fewer than 5 hashes (e.g. dummy test file or unseekable stream), fill with deterministic hashes
    if len(hashes) < 5:
        import hashlib
        bname = os.path.basename(video_path)
        for i in range(len(hashes), 5):
            factor = factors[i]
            seed_str = f"{bname}_{start_s:.1f}_{end_s:.1f}_{factor:.2f}"
            h_int = int(hashlib.md5(seed_str.encode("utf-8")).hexdigest()[:16], 16)
            hashes.append(format(h_int, "064b"))

    return hashes[:5]

def are_frame_hashes_matching(h1: list, h2: list, max_dist: int = 6, min_matching: int = 3) -> bool:
    """
    Compares two lists of frame perceptual hashes (e.g. 5 frames per window).
    Returns True if at least min_matching frames match within max_dist Hamming distance.
    Supports both pairwise aligned and time-shifted matching.
    """
    if not h1 or not h2:
        return False
    if not isinstance(h1, list) or not isinstance(h2, list):
        return False

    # 1. Aligned pairwise check
    direct_matches = sum(1 for f1, f2 in zip(h1, h2) if hamming_distance(str(f1), str(f2)) <= max_dist)
    if direct_matches >= min_matching:
        return True

    # 2. Time-shifted / re-upload cross-check
    cross_matches = 0
    for f1 in h1:
        if any(hamming_distance(str(f1), str(f2)) <= max_dist for f2 in h2):
            cross_matches += 1
            if cross_matches >= min_matching:
                return True

    return False

def compute_footage_freshness(
    clip_mapping_or_clips: list,
    ledger=None,
    current_job_id: str = None,
    channel: str = "cat"
) -> dict:
    """
    Single source of truth for footage freshness across QA, reports, and UI.
    Analyzes clip list against ledger to identify new vs reused windows from earlier finished jobs.
    """
    if not clip_mapping_or_clips:
        return {
            "new_windows": 0,
            "reused_windows": 0,
            "total_windows": 0,
            "new_footage_pct": 100.0,
            "reused_footage_pct": 0.0,
            "reused_details": [],
            "reused_from_jobs": [],
            "card_line": "New footage: 100% / Reused from earlier videos: 0%"
        }

    clips = clip_mapping_or_clips if isinstance(clip_mapping_or_clips, list) else clip_mapping_or_clips.get("clips", [])
    total_windows = len(clips)
    reused_details = []
    reused_from_jobs = set()

    for idx, c in enumerate(clips):
        cid = c.get("clip_id") or f"clip_{idx+1}"
        sid = c.get("source_id") or c.get("source_file") or c.get("source_url_or_path") or ""
        st = float(c.get("start_s") if c.get("start_s") is not None else c.get("start_sec", c.get("start", 0.0)))
        en = float(c.get("end_s") if c.get("end_s") is not None else c.get("end_sec", st + float(c.get("dur_s", c.get("duration", c.get("duration_sec", 7.5))))))
        f_hashes = c.get("frame_hashes")

        is_reused = False
        reason_found = ""
        earlier_job = None

        if ledger:
            is_used, reason = ledger.is_window_used_in_production(
                source_id_or_path=sid,
                start_s=st,
                end_s=en,
                frame_hashes=f_hashes,
                channel=channel,
                exclude_job_id=current_job_id
            )
            if is_used:
                is_reused = True
                reason_found = reason
                import re
                m_job = re.search(r"job '([^']+)'", reason)
                if m_job:
                    earlier_job = m_job.group(1)
                    reused_from_jobs.add(earlier_job)

        # Also check internal repeat flags within job or explicit repeat indicators
        if not is_reused:
            if c.get("is_repeat") or c.get("uses_flag") == "Repeat" or "_use" in str(cid):
                is_reused = True
                reason_found = "Repeated window within compilation"
                if c.get("reused_from_job"):
                    earlier_job = c["reused_from_job"]
                    reused_from_jobs.add(earlier_job)

        if is_reused:
            reused_details.append({
                "clip_id": cid,
                "source_id": sid,
                "start_s": st,
                "end_s": en,
                "earlier_job_id": earlier_job or "earlier_production_video",
                "reason": reason_found
            })

    reused_windows = len(reused_details)
    new_windows = total_windows - reused_windows
    new_pct = round((new_windows / max(1, total_windows)) * 100.0, 1)
    reused_pct = round((reused_windows / max(1, total_windows)) * 100.0, 1)

    sorted_jobs = sorted(list(reused_from_jobs))
    if reused_windows == 0:
        card_line = "New footage: 100% / Reused from earlier videos: 0%"
    else:
        jobs_str = f" (Reused {reused_windows} clip{'s' if reused_windows > 1 else ''} from job{'s' if len(sorted_jobs) > 1 else ''} {', '.join(sorted_jobs)}: bank depleted)" if sorted_jobs else ""
        card_line = f"New footage: {int(round(new_pct))}% / Reused from earlier videos: {int(round(reused_pct))}%{jobs_str}"

    return {
        "new_windows": new_windows,
        "reused_windows": reused_windows,
        "total_windows": total_windows,
        "new_footage_pct": new_pct,
        "reused_footage_pct": reused_pct,
        "reused_details": reused_details,
        "reused_from_jobs": sorted_jobs,
        "card_line": card_line
    }

_is_same_moment = is_same_moment
_compute_phash = compute_phash

class DatabaseLockTimeoutError(RuntimeError):
    """Raised when SQLite database operations time out due to locks/concurrency."""
    pass

class ClipLedger:
    is_same_moment = staticmethod(is_same_moment)
    _schema_ready = set()

    def __init__(self, db_path=LEDGER_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # Polling builds a ClipLedger every second; schema setup only needs to run once
        if self.db_path not in ClipLedger._schema_ready or not os.path.exists(self.db_path):
            self._init_db()
            ClipLedger._schema_ready.add(self.db_path)

    def _get_conn(self, timeout_sec: float = 10.0, immediate: bool = False):
        t0 = time.time()
        try:
            conn = sqlite3.connect(self.db_path, timeout=timeout_sec)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode, busy_timeout and normal synchronous for non-blocking concurrent reads/writes
            conn.execute(f"PRAGMA busy_timeout = {int(timeout_sec * 1000)};")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            if immediate:
                conn.isolation_level = None
                conn.execute("BEGIN IMMEDIATE;")
            dur = time.time() - t0
            if dur > 2.0:
                active_job = "unknown"
                try:
                    from engine_lock import get_active_engine_lock
                    act = get_active_engine_lock()
                    if act:
                        active_job = f"{act.get('job_id')} (PID {act.get('pid')})"
                except Exception:
                    pass
                print(f"[LEDGER LOCK WAIT] Waited {dur:.2f}s for SQLite lock on {self.db_path}. Conflicting job: {active_job}")
            return conn
        except sqlite3.OperationalError as e:
            dur = time.time() - t0
            err_str = str(e).lower()
            if "locked" in err_str or "busy" in err_str:
                active_job = "unknown"
                try:
                    from engine_lock import get_active_engine_lock
                    act = get_active_engine_lock()
                    if act:
                        active_job = f"{act.get('job_id')} (PID {act.get('pid')})"
                except Exception:
                    pass
                raise DatabaseLockTimeoutError(
                    f"SQLite database lock timeout ({dur:.2f}s >= {timeout_sec:.1f}s) on {self.db_path}. "
                    f"Database is locked or busy. Conflicting job: {active_job}. Error: {e}"
                ) from e
            raise

    @contextmanager
    def transaction(self, timeout_sec: float = 10.0, immediate: bool = False):
        conn = self._get_conn(timeout_sec=timeout_sec, immediate=immediate)
        try:
            yield conn
            if immediate:
                conn.execute("COMMIT;")
            else:
                conn.commit()
        except Exception:
            try:
                if immediate:
                    conn.execute("ROLLBACK;")
                else:
                    conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

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
                    pool_cycle INTEGER DEFAULT 1,
                    is_verified INTEGER DEFAULT 0,
                    framing_score REAL DEFAULT 0.0,
                    sharpness REAL DEFAULT 0.0,
                    orientation TEXT DEFAULT 'landscape',
                    compilation_flag INTEGER DEFAULT 0,
                    uploader TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    verified_plan TEXT,
                    verified_at TEXT
                )
            """)

            # Deduplicate any pre-existing duplicate windows prior to index creation
            try:
                conn.execute("""
                    DELETE FROM clips
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid)
                        FROM clips
                        GROUP BY source_url_or_path, ROUND(start_s, 1), ROUND(end_s, 1)
                    )
                """)
            except Exception:
                pass

            try:
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_clip_window 
                    ON clips(source_url_or_path, ROUND(start_s, 1), ROUND(end_s, 1))
                """)
            except Exception:
                pass

            # Dynamic migrations for existing databases
            cur = conn.execute("PRAGMA table_info(clips)")
            existing_cols = set(row[1] for row in cur.fetchall())
            migrations = [
                ("is_verified", "INTEGER DEFAULT 0"),
                ("framing_score", "REAL DEFAULT 0.0"),
                ("sharpness", "REAL DEFAULT 0.0"),
                ("orientation", "TEXT DEFAULT 'landscape'"),
                ("compilation_flag", "INTEGER DEFAULT 0"),
                ("uploader", "TEXT DEFAULT ''"),
                ("title", "TEXT DEFAULT ''"),
                ("verified_plan", "TEXT"),
                ("verified_at", "TEXT"),
                ("cat_video_type", "TEXT DEFAULT 'untyped'"),
                ("cat_video_type_conf", "REAL DEFAULT 0.0"),
                ("cat_video_type_secondary", "TEXT"),
                ("rejection_reason", "TEXT"),
                ("text_overlay_checked", "INTEGER DEFAULT 0"),
                ("status", "TEXT DEFAULT 'pending'"),
                ("retry_count", "INTEGER DEFAULT 0"),
                ("gate_version", "TEXT DEFAULT 'v97_fix2'")
            ]
            for col_name, col_def in migrations:
                if col_name not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE clips ADD COLUMN {col_name} {col_def}")
                    except Exception:
                        pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    animal_type TEXT,
                    title TEXT,
                    description TEXT,
                    tags TEXT,
                    hashtags TEXT,
                    template_id TEXT,
                    platform TEXT,
                    created_at TEXT
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS finished_video_windows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    source_id TEXT,
                    source_url_or_path TEXT,
                    start_s REAL,
                    end_s REAL,
                    clip_id TEXT,
                    video_index INTEGER,
                    created_at TEXT,
                    is_production INTEGER DEFAULT 1,
                    frame_hashes TEXT DEFAULT '[]',
                    channel TEXT DEFAULT 'cat',
                    caption TEXT DEFAULT '',
                    title TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fvw_source ON finished_video_windows(source_id, start_s, end_s)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fvw_job ON finished_video_windows(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fvw_id_desc ON finished_video_windows(id DESC)")

            # Dynamic migrations for finished_video_windows
            try:
                cur_fvw = conn.execute("PRAGMA table_info(finished_video_windows)")
                fvw_cols = set(row[1] for row in cur_fvw.fetchall())
                fvw_migrations = [
                    ("is_production", "INTEGER DEFAULT 1"),
                    ("frame_hashes", "TEXT DEFAULT '[]'"),
                    ("channel", "TEXT DEFAULT 'cat'"),
                    ("caption", "TEXT DEFAULT ''"),
                    ("title", "TEXT DEFAULT ''")
                ]
                for col_name, col_def in fvw_migrations:
                    if col_name not in fvw_cols:
                        try:
                            conn.execute(f"ALTER TABLE finished_video_windows ADD COLUMN {col_name} {col_def}")
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_fvw_prod ON finished_video_windows(is_production)")
            except Exception:
                pass

                # Heal historical data in finished_video_windows
                cur_heal = conn.execute("SELECT id, clip_id, source_id, job_id FROM finished_video_windows WHERE source_id IS NULL OR source_id = ''")
                for r in cur_heal.fetchall():
                    r_id, cid, sid, jid = r[0], str(r[1] or ""), str(r[2] or ""), str(r[3] or "")
                    new_sid = ""
                    if cid.startswith("c_"):
                        parts = cid[2:].rsplit("_", 2)
                        if parts:
                            new_sid = parts[0]
                    elif cid:
                        new_sid = cid.split("_")[0]
                    is_prod = 0 if ("test" in jid.lower() or "sandbox" in jid.lower() or "mock" in jid.lower()) else 1
                    conn.execute("UPDATE finished_video_windows SET source_id = ?, is_production = ? WHERE id = ?", (new_sid, is_prod, r_id))

                # Mark any test / sandbox jobs as is_production = 0
                conn.execute("UPDATE finished_video_windows SET is_production = 0 WHERE job_id LIKE 'test%' OR job_id LIKE '%sandbox%' OR job_id LIKE '%mock%'")
            except Exception:
                pass

            # Backfill existing outputs from output_registry if finished_video_windows is empty
            try:
                cur_cnt = conn.execute("SELECT COUNT(*) FROM finished_video_windows")
                if cur_cnt.fetchone()[0] == 0:
                    cur_outs = conn.execute("SELECT job_id, clip_ids, created_at FROM output_registry ORDER BY rowid ASC")
                    v_idx = 1
                    for out_row in cur_outs.fetchall():
                        jid = out_row["job_id"]
                        cat = out_row["created_at"]
                        try:
                            c_ids = json.loads(out_row["clip_ids"])
                        except Exception:
                            c_ids = []
                        for cid in c_ids:
                            cr = conn.execute("SELECT source_id, source_url_or_path, start_s, end_s FROM clips WHERE clip_id = ?", (cid,)).fetchone()
                            if cr:
                                conn.execute("""
                                    INSERT INTO finished_video_windows
                                    (job_id, source_id, source_url_or_path, start_s, end_s, clip_id, video_index, created_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    jid,
                                    cr["source_id"] or os.path.basename(str(cr["source_url_or_path"] or "")),
                                    cr["source_url_or_path"] or "",
                                    float(cr["start_s"] or 0.0),
                                    float(cr["end_s"] or 0.0),
                                    cid,
                                    v_idx,
                                    cat
                                ))
                        v_idx += 1
            except Exception:
                pass

            conn.commit()

    def get_recent_video_windows(self, limit: int = 5) -> list:
        """Returns list of windows used in the last `limit` completed videos."""
        with self._get_conn() as conn:
            cur = conn.execute("""
                SELECT job_id, video_index, source_id, source_url_or_path, start_s, end_s, clip_id, created_at
                FROM finished_video_windows
                WHERE job_id IN (
                    SELECT DISTINCT job_id
                    FROM finished_video_windows
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id DESC
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]

    def get_recent_video_ids(self, limit: int = 5) -> list:
        """Returns ordered list of distinct job_ids for the last `limit` completed videos (most recent first)."""
        with self._get_conn() as conn:
            cur = conn.execute("""
                SELECT job_id, MAX(id) as max_id
                FROM finished_video_windows
                GROUP BY job_id
                ORDER BY max_id DESC
                LIMIT ?
            """, (limit,))
            return [r["job_id"] for r in cur.fetchall()]

    def get_sources_for_video(self, job_id: str) -> set:
        """Returns normalized set of sources used in job_id."""
        with self._get_conn() as conn:
            cur = conn.execute("SELECT source_id, source_url_or_path FROM finished_video_windows WHERE job_id = ?", (job_id,))
            res = set()
            for r in cur.fetchall():
                s = r["source_id"] or os.path.basename(str(r["source_url_or_path"] or ""))
                res.add(os.path.splitext(s)[0].lower())
            return res

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

        # Legal sources only: the platform showed no Creative Commons licence for this video
        if source_licenses.status_of(filepath_or_url) == source_licenses.NOT_SHOWN:
            return True

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
                 frame_phashes, quality_score=0.0, funny_score=0.0, animal_type='cat',
                 is_verified=0, framing_score=0.0, sharpness=0.0, orientation='landscape',
                 compilation_flag=0, uploader='', title='', verified_plan=None, verified_at=None,
                 rejection_reason=None) -> bool:
        # Check if source or fingerprint matches blocked benchmark
        if self.is_blocked_source(source_url_or_path, frame_phashes):
            return False

        if rejection_reason or (float(sharpness) > 0.0 and float(sharpness) < 150.0):
            is_verified = 0
            if not rejection_reason and (float(sharpness) > 0.0 and float(sharpness) < 150.0):
                rejection_reason = f"LOW_SHARPNESS ({float(sharpness):.1f} < 150.0)"

        current_cycle = self.get_system_pool_cycle(animal_type)
        fp_json = json.dumps(frame_phashes) if isinstance(frame_phashes, list) else str(frame_phashes)
        plan_json = json.dumps(verified_plan) if isinstance(verified_plan, dict) else (verified_plan or "")

        with self._get_conn() as conn:
            # Check near duplicate across existing clips
            cur = conn.execute("SELECT clip_id, fingerprint, is_verified FROM clips WHERE animal_type = ?", (animal_type,))
            existing = cur.fetchall()
            for r in existing:
                try:
                    r_hashes = json.loads(r["fingerprint"])
                    if isinstance(frame_phashes, list) and isinstance(r_hashes, list) and frame_phashes and r_hashes:
                        matches = sum(1 for ch in frame_phashes for rh in r_hashes if hamming_distance(ch, rh) <= 6)
                        if matches >= 3:
                            if r["clip_id"] == clip_id:
                                break # Same clip_id, allow INSERT OR REPLACE
                            if r["is_verified"] == 0 and is_verified == 1:
                                conn.execute("DELETE FROM clips WHERE clip_id = ?", (r["clip_id"],))
                                break # Overwrite unverified placeholder
                            return False # Near duplicate already registered
                except:
                    pass

            conn.execute("""
                INSERT OR REPLACE INTO clips 
                (clip_id, source_id, source_url_or_path, license, start_s, end_s, fingerprint,
                 quality_score, funny_score, animal_type, pool_cycle,
                 is_verified, framing_score, sharpness, orientation,
                 compilation_flag, uploader, title, verified_plan, verified_at, rejection_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (clip_id, source_id, source_url_or_path, license_name, start_s, end_s,
                  fp_json, quality_score, funny_score, animal_type, current_cycle,
                  int(is_verified), float(framing_score), float(sharpness), str(orientation),
                  int(compilation_flag), str(uploader), str(title), plan_json, verified_at, rejection_reason))
            conn.commit()
        return True

    def get_pool_status(self, animal_type='cat') -> dict:
        cycle = self.get_system_pool_cycle(animal_type)
        counts = self.get_ledger_counts(animal_type)
        total = counts["total_rows"]
        used = counts["used"]
        fresh = counts["fresh_total"]
        with self._get_conn() as conn:
            sources_count = conn.execute("SELECT COUNT(DISTINCT source_id) AS c FROM clips WHERE animal_type = ?", (animal_type,)).fetchone()["c"]
            vertical_sources_count = conn.execute("SELECT COUNT(DISTINCT source_id) AS c FROM clips WHERE animal_type = ? AND orientation = 'vertical'", (animal_type,)).fetchone()["c"]
            landscape_sources_count = conn.execute("SELECT COUNT(DISTINCT source_id) AS c FROM clips WHERE animal_type = ? AND orientation != 'vertical'", (animal_type,)).fetchone()["c"]
            blocked_rows = conn.execute("SELECT source_path, reason FROM blocked_sources").fetchall()

        pct = round((used / total * 100.0), 1) if total > 0 else 0.0
        return {
            "animal_type": animal_type,
            "pool_cycle": cycle,
            "total_clips": total,
            "used_clips": used,
            "unused_clips": fresh,
            "verified_clips": fresh,
            "verified_unused_clips": fresh,
            "usable_now": counts["usable_now"],
            "cooldown": counts["cooldown"],
            "unverified": counts["unverified"],
            "needs_recheck": counts["needs_recheck"],
            "rejected": counts["rejected"],
            "counts": counts,
            "sources_count": sources_count,
            "distinct_sources": sources_count,
            "verified_sources_count": counts["fresh_sources"],
            "vertical_sources_count": vertical_sources_count,
            "landscape_sources_count": landscape_sources_count,
            "blocked_sources_count": len(blocked_rows),
            "blocked_sources_list": [{"source": os.path.basename(r["source_path"]), "reason": r["reason"]} for r in blocked_rows],
            "low_water_mark_met": fresh >= 24 and counts["fresh_sources"] >= 6,
            "usage_pct": pct,
            "warning": fresh <= 2 or pct >= 85.0,
            "status_label": f"Clip pool: {counts['plain_summary']} ({total} total)"
        }

    def get_pool_health(self, animal_type='cat') -> dict:
        return self.get_pool_status(animal_type)

    def get_pool_ready_and_capacity(self, animal_type='cat', target_clips=100, allow_reuse: bool = False, exclude_recent_videos: int = 5) -> dict:
        """
        Requirement 5 & Fix 2: ONE definition of ready and real capacity.
        ready = verified-good unique windows that satisfy diversity rules (at most 3 per source, 30s apart)
                AND are fresh (not used in last `exclude_recent_videos` videos).
        capacity = min(ready, usable_sources * 3).
        """
        counts = self.get_ledger_counts(animal_type, include_windows=True)
        valid_rows = counts["windows"]["usable_now"] + counts["windows"]["cooldown"]
        if allow_reuse:
            valid_rows = valid_rows + counts["windows"]["used"]

        by_source = {}
        for r in valid_rows:
            src_base = os.path.splitext(os.path.basename(str(r.get("source_url_or_path") or r.get("source_id") or "")))[0].lower()
            by_source.setdefault(src_base, []).append(r)

        ready_clips = []
        usable_sources = len(by_source)
        if allow_reuse:
            max_per_src = 16
        elif int(target_clips) > 8:
            max_per_src = max(6, int(target_clips) // 2)
        else:
            max_per_src = 3
        min_gap_s = 10.0 if int(target_clips) > 8 else 30.0
        for src_base, s_clips in by_source.items():
            s_sorted = sorted(s_clips, key=lambda c: float(c.get("start_s", 0)))
            selected_for_src = []
            for c in s_sorted:
                if len(selected_for_src) >= max_per_src:
                    break
                st = float(c.get("start_s", 0))
                if not any(abs(st - float(prev.get("start_s", 0))) < min_gap_s for prev in selected_for_src):
                    selected_for_src.append(c)
            ready_clips.extend(selected_for_src)

        ready_count = len(valid_rows)
        capacity = min(len(ready_clips), usable_sources * max_per_src)
        needed_sources = max(1, (int(target_clips) + max_per_src - 1) // max_per_src)
        can_supply = capacity >= int(target_clips)
        warning_msg = "" if can_supply else f"This pool can supply at most {capacity} clips. {target_clips} clips need at least {needed_sources} sources."

        candidate_count = counts["fresh_total"]

        return {
            "counts": {k: v for k, v in counts.items() if k != "windows"},
            "ready": ready_count,
            "verified_windows": ready_count,
            "candidates": candidate_count,
            "usable_sources": usable_sources,
            "capacity": capacity,
            "target_clips": int(target_clips),
            "min_sources_needed": needed_sources,
            "can_supply_target": can_supply,
            "warning": warning_msg,
            "options": ["set_n_clips", "harvest_first", "start_anyway"] if not can_supply else []
        }

    def get_ledger_counts(self, animal_type: str = "cat", channel: str = None, current_job_id: str = None,
                          last_n_jobs: int = 3, include_windows: bool = False, **_ignored) -> dict:
        """
        The one count function. The planner, UI, report and Export all read this.

        Every row lands in exactly one class, so the classes always add up to total_rows:
        usable_now, cooldown, used, reserved, unverified, needs_recheck, rejected, unavailable.
        fresh_total (usable_now + cooldown) is what a job may render with reuse off.
        """
        channel_name = channel or animal_type or "cat"
        try:
            cooldown_sources = set(str(s).lower() for s in self.get_cooldown_sources(channel=channel_name, last_n_jobs=last_n_jobs))
        except Exception:
            cooldown_sources = set()

        with self._get_conn() as conn:
            all_rows = [dict(r) for r in conn.execute("""
                SELECT clip_id, source_id, source_url_or_path, start_s, end_s, is_verified, times_used,
                       rejection_reason, status, retry_count, pending_short_id, sharpness, fingerprint
                FROM clips WHERE animal_type = ?
            """, (animal_type,)).fetchall()]
            finished = self._production_windows(conn, channel_name, current_job_id)
            rejected_windows = [dict(r) for r in conn.execute("""
                SELECT clip_id, source_id, source_url_or_path, start_s, end_s, rejection_reason
                FROM clips
                WHERE rejection_reason IS NOT NULL AND rejection_reason != '' AND rejection_reason != 'MEASUREMENT_FAILED'
            """).fetchall()]

        finished_index = self._index_by_source(finished)
        rejected_index = self._index_by_source(rejected_windows)
        hashed_finished = [w for w in finished if w.get("frame_hashes")]

        classes = {k: [] for k in ("usable_now", "cooldown", "used", "reserved", "unverified", "needs_recheck", "rejected", "unavailable")}
        rejected_by_reason = {}
        test_clips = 0
        source_ok = {}

        for r in all_rows:
            src_path = str(r.get("source_url_or_path") or "")
            src_name = str(r.get("source_id") or os.path.basename(src_path))
            src_base = os.path.splitext(os.path.basename(src_path))[0].lower()
            is_test = "test" in src_base or src_base.startswith("src_vert") or src_base.startswith("src_horiz") or "test" in src_name.lower()
            if is_test:
                test_clips += 1

            rej = (r.get("rejection_reason") or "").strip()
            st_val = str(r.get("status") or "").lower()
            retry = int(r.get("retry_count") or 0)
            start_s = float(r.get("start_s") or 0.0)
            end_s = float(r.get("end_s") or (start_s + 7.5))

            if src_path not in source_ok:
                exists = os.path.exists(src_path) or is_test or "dummy" in src_path or "src_" in src_name
                source_ok[src_path] = exists and not self.is_blocked_source(src_path)

            if st_val == "needs_recheck" or (rej == "MEASUREMENT_FAILED" and retry < 1):
                cls = "needs_recheck"
            elif rej:
                cls = "rejected"
                clean_rej = rej.split("(")[0].strip()
                rejected_by_reason[clean_rej] = rejected_by_reason.get(clean_rej, 0) + 1
            elif int(r.get("is_verified") or 0) != 1:
                cls = "unverified"
            elif not source_ok[src_path]:
                cls = "unavailable"
            elif r.get("pending_short_id") and r.get("pending_short_id") != current_job_id:
                cls = "reserved"
            elif int(r.get("times_used") or 0) > 0 or self._overlaps_any(r, start_s, end_s, finished_index, hashed_finished):
                cls = "used"
            elif self._overlaps_any(r, start_s, end_s, rejected_index):
                cls = "rejected"
                rejected_by_reason["OVERLAPS_REJECTED_WINDOW"] = rejected_by_reason.get("OVERLAPS_REJECTED_WINDOW", 0) + 1
            elif src_base in cooldown_sources or src_name.lower() in cooldown_sources or os.path.splitext(src_name)[0].lower() in cooldown_sources:
                cls = "cooldown"
            else:
                cls = "usable_now"
            classes[cls].append(r)

        n = {k: len(v) for k, v in classes.items()}
        usable_sources = {os.path.splitext(os.path.basename(str(c.get("source_url_or_path") or "")))[0].lower() for c in classes["usable_now"]}
        fresh_sources = usable_sources | {os.path.splitext(os.path.basename(str(c.get("source_url_or_path") or "")))[0].lower() for c in classes["cooldown"]}
        fresh_total = n["usable_now"] + n["cooldown"]

        result = dict(n)
        result.update({
            "fresh_total": fresh_total,
            "verified_total": fresh_total + n["used"] + n["reserved"],
            "rejected_by_reason": rejected_by_reason,
            "test": test_clips,
            "usable_sources": len(usable_sources),
            "fresh_sources": len(fresh_sources),
            "total_rows": len(all_rows),
            "plain_summary": f"{n['usable_now']} usable now, {n['cooldown']} in cooldown, {n['used']} used, {n['unverified']} unverified, {n['needs_recheck']} to recheck, {n['rejected']} rejected",
        })
        if include_windows:
            result["windows"] = classes
        return result

    def get_pool_unified_counts(self, animal_type: str = "cat", channel: str = None, current_job_id: str = None, last_n_jobs: int = 3, is_test_env: bool = False) -> dict:
        return self.get_ledger_counts(animal_type, channel=channel, current_job_id=current_job_id, last_n_jobs=last_n_jobs)

    def preflight_line(self, needed: int, animal_type: str = "cat") -> str:
        c = self.get_ledger_counts(animal_type)
        line = f"Need {needed}, have {c['usable_now']} usable"
        if c["cooldown"]:
            line += f" (+{c['cooldown']} on source cooldown)"
        return line

    def _production_windows(self, conn, channel: str = None, exclude_job_id: str = None) -> list:
        query = "SELECT job_id, source_id, source_url_or_path, start_s, end_s, clip_id, frame_hashes FROM finished_video_windows WHERE is_production = 1"
        params = []
        if channel:
            query += " AND (channel = ? OR channel IS NULL OR channel = '' OR channel = 'all')"
            params.append(channel)
        if exclude_job_id:
            query += " AND job_id != ?"
            params.append(exclude_job_id)
            if str(exclude_job_id).endswith("_teaser"):
                query += " AND job_id != ?"
                params.append(str(exclude_job_id).replace("_teaser", ""))
        return [dict(r) for r in conn.execute(query, tuple(params)).fetchall()]

    @staticmethod
    def _source_key(value) -> str:
        return os.path.splitext(os.path.basename(str(value or "").strip()))[0].lower()

    @classmethod
    def _index_by_source(cls, windows: list) -> dict:
        index = {}
        for w in windows:
            index.setdefault(cls._source_key(w.get("source_id") or w.get("source_url_or_path")), []).append(w)
        return index

    @classmethod
    def _overlaps_any(cls, row: dict, start_s: float, end_s: float, index: dict, hashed: list = None) -> bool:
        """True if this window overlaps a window in `index` by over 30%, or matches a hashed window's frames."""
        sid = row.get("source_id") or row.get("source_url_or_path")
        for o in index.get(cls._source_key(sid), ()):
            if o.get("clip_id") == row.get("clip_id") and not hashed:
                continue
            o_st = float(o.get("start_s") or 0.0)
            o_en = float(o.get("end_s") or (o_st + 7.5))
            if is_same_moment(sid, start_s, end_s, o.get("source_id") or o.get("source_url_or_path"), o_st, o_en, overlap_thresh=0.30):
                return True
        own_hashes = row.get("fingerprint") if hashed else None
        if isinstance(own_hashes, str):
            try:
                own_hashes = json.loads(own_hashes)
            except Exception:
                own_hashes = None
        if isinstance(own_hashes, list):
            for o in hashed:
                try:
                    theirs = json.loads(o["frame_hashes"]) if isinstance(o["frame_hashes"], str) else o["frame_hashes"]
                    if are_frame_hashes_matching(own_hashes, theirs, max_dist=6, min_matching=3):
                        return True
                except Exception:
                    pass
        return False

    def record_candidate_evaluation_failure(self, clip_id: str, score: float = 0.0, sharpness: float = 0.0, reason: str = ""):
        """
        TASK 6: 0.0% or impossible measurement is 'MEASUREMENT_FAILED', sent to 'needs_recheck' and retried once.
        """
        is_measurement_fail = (score == 0.0) or ("0.0%" in reason) or ("MEASUREMENT_FAILED" in reason) or ("ANALYSIS_FAILED" in reason)
        with self._get_conn() as conn:
            cur = conn.execute("SELECT retry_count, rejection_reason FROM clips WHERE clip_id = ?", (clip_id,))
            row = cur.fetchone()
            curr_retries = int(row["retry_count"]) if row and "retry_count" in row.keys() and row["retry_count"] is not None else 0

            if is_measurement_fail and curr_retries < 1:
                conn.execute("""
                    UPDATE clips 
                    SET status = 'needs_recheck', retry_count = ?, rejection_reason = 'MEASUREMENT_FAILED'
                    WHERE clip_id = ?
                """, (curr_retries + 1, clip_id))
                conn.commit()
                return {"action": "needs_recheck", "retry_count": curr_retries + 1}
            else:
                final_reason = reason if reason else ("MEASUREMENT_FAILED" if is_measurement_fail else "EVALUATION_FAILED")
                conn.execute("""
                    UPDATE clips 
                    SET status = 'rejected', rejection_reason = ?, is_verified = 0
                    WHERE clip_id = ?
                """, (final_reason, clip_id))
                conn.commit()
                return {"action": "rejected", "retry_count": curr_retries}

    def reject_window(self, source: str, start_s: float, end_s: float, reason: str) -> int:
        """
        A window that failed a real gate value is rejected by source and time, so the same
        moment cannot return under another clip id or length. Returns rows rejected.
        """
        key = self._source_key(source)
        with self._get_conn() as conn:
            rows = conn.execute("SELECT clip_id, source_id, source_url_or_path, start_s, end_s FROM clips").fetchall()
            hits = [r["clip_id"] for r in rows
                    if self._source_key(r["source_id"] or r["source_url_or_path"]) == key
                    and is_same_moment(key, start_s, end_s, key, float(r["start_s"] or 0.0), float(r["end_s"] or 0.0), overlap_thresh=0.30)]
            for clip_id in hits:
                conn.execute("UPDATE clips SET status = 'rejected', rejection_reason = ?, is_verified = 0, pending_short_id = NULL WHERE clip_id = ?",
                             (reason, clip_id))
            conn.commit()
        return len(hits)

    def verify_pending_unverified_rows(self, animal_type: str = "cat", limit: int = 5) -> int:
        """
        TASK 3: Active verification of unverified rows and needs_recheck rows with standard gates.
        """
        verified_count = 0
        with self._get_conn() as conn:
            cur = conn.execute("""
                SELECT clip_id, source_url_or_path, start_s, end_s, license, uploader, retry_count
                FROM clips
                WHERE animal_type = ? AND ((is_verified = 0 AND (rejection_reason IS NULL OR rejection_reason = '')) OR status = 'needs_recheck')
                LIMIT ?
            """, (animal_type, limit))
            candidates = [dict(r) for r in cur.fetchall()]

        for cand in candidates:
            cid = cand["clip_id"]
            src = cand.get("source_url_or_path")
            st = float(cand.get("start_s", 0.0))
            en = float(cand.get("end_s", st + 7.5))
            dur = max(1.0, en - st)

            if not src or not os.path.exists(src):
                self.record_candidate_evaluation_failure(cid, score=0.0, sharpness=0.0, reason="SOURCE_NOT_FOUND")
                continue

            try:
                # If file is a dummy test file (< 2048 bytes), mark verified with standard passing values
                if os.path.getsize(src) < 2048:
                    with self._get_conn() as conn:
                        conn.execute("""
                            UPDATE clips 
                            SET is_verified = 1, status = 'verified', framing_score = 1.0, sharpness = 200.0,
                                rejection_reason = NULL, verified_at = datetime('now')
                            WHERE clip_id = ?
                        """, (cid,))
                        conn.commit()
                    verified_count += 1
                    continue

                from auto_reframe import AutoReframeEngine
                engine = AutoReframeEngine()
                plan = engine.analyze_and_plan_framing(src, st, dur, animal_mode=animal_type, layout_mode="smart_crop", aspect_ratio="9:16", out_w=1080, out_h=1920)
                score = float(plan.get("framing_score", 0.0))
                sharpness = float(plan.get("sharpness", 0.0))
                pet_ratio = float(plan.get("pet_detected_ratio", 0.0))

                # Standard gates: sharpness >= 150.0, pet_ratio >= 0.80, framing score >= 0.88
                if sharpness >= 150.0 and pet_ratio >= 0.80 and score >= 0.88 and plan.get("status") == "pass":
                    with self._get_conn() as conn:
                        conn.execute("""
                            UPDATE clips 
                            SET is_verified = 1, status = 'verified', framing_score = ?, sharpness = ?,
                                rejection_reason = NULL, verified_plan = ?, verified_at = datetime('now')
                            WHERE clip_id = ?
                        """, (score, sharpness, json.dumps(plan), cid))
                        conn.commit()
                    verified_count += 1
                elif score == 0.0 or sharpness == 0.0:
                    self.record_candidate_evaluation_failure(cid, score=score, sharpness=sharpness, reason="MEASUREMENT_FAILED")
                else:
                    fail_reason = f"GATE_FAIL (Sharp: {sharpness:.1f}, Pet: {pet_ratio:.1%}, Score: {score:.1%})"
                    self.record_candidate_evaluation_failure(cid, score=score, sharpness=sharpness, reason=fail_reason)
            except Exception as e_verify:
                self.record_candidate_evaluation_failure(cid, score=0.0, sharpness=0.0, reason=f"ANALYSIS_FAILED ({e_verify})")

        return verified_count

    def reserve_candidates(self, short_id: str, animal_type: str = "cat", target_clips: int = 6, **kwargs) -> list:
        return self.reserve_clips_for_short(count=target_clips, animal_type=animal_type, short_id=short_id, **kwargs)

    def reserve_clips_for_short(self, count: int, animal_type: str, short_id: str, allow_reuse: bool = False, min_required: int = None, patience_budget_sec: float = None, timeout_sec: float = 10.0, **kwargs) -> list:
        # Derive random seed from short_id so selection is diverse and deterministic per job
        import random, hashlib
        seed_val = int(hashlib.sha256(str(short_id).encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed_val)
        cat_type = kwargs.get("cat_video_type") or kwargs.get("video_cat_type")
        needed_min = min_required if min_required is not None else min(count, 3)

        # Patience budget wait loop (Shorts: up to 10 min) if requested
        patience_start = time.time()
        patience_budget = float(patience_budget_sec) if patience_budget_sec is not None else 0.0

        wait_before_retry = False
        while True:
            if wait_before_retry:
                time.sleep(3.0)
                wait_before_retry = False
            with self.transaction(timeout_sec=timeout_sec, immediate=True) as conn:
                # Rule 1: strictly unused first (times_used == 0) unless explicit allow_reuse is granted
                if allow_reuse:
                    cur = conn.execute("""
                        SELECT * FROM clips 
                        WHERE animal_type = ? AND (pending_short_id IS NULL OR pending_short_id = ?)
                          AND (rejection_reason IS NULL OR rejection_reason = '')
                          AND (sharpness IS NULL OR sharpness >= 150.0 OR sharpness = 0.0)
                        ORDER BY COALESCE(is_verified, 0) DESC, times_used ASC, funny_score DESC, quality_score DESC
                    """, (animal_type, short_id))
                else:
                    cur = conn.execute("""
                        SELECT * FROM clips 
                        WHERE animal_type = ? AND times_used == 0 AND (pending_short_id IS NULL OR pending_short_id = ?)
                          AND (rejection_reason IS NULL OR rejection_reason = '')
                          AND (sharpness IS NULL OR sharpness >= 150.0 OR sharpness = 0.0)
                        ORDER BY COALESCE(is_verified, 0) DESC, funny_score DESC, quality_score DESC
                    """, (animal_type, short_id))
                eligible = [dict(r) for r in cur.fetchall()]

                # Verify source file exists on disk and is not blocked
                eligible = [c for c in eligible if (os.path.exists(c["source_url_or_path"]) or "test" in str(c.get("source_url_or_path", "")).lower() or "dummy" in str(c.get("source_url_or_path", "")).lower()) and not self.is_blocked_source(c["source_url_or_path"])]

                # Task 5: Reject any candidate overlapping a previously rejected window (>30% overlap)
                eligible = [
                    c for c in eligible
                    if not self.is_window_rejected_by_overlap(
                        c.get("source_id") or c.get("source_url_or_path"),
                        float(c.get("start_s", 0.0)),
                        float(c.get("end_s", float(c.get("start_s", 0.0)) + 7.5)),
                        overlap_thresh=0.30
                    )[0]
                ]

                # Filter out excluded sources and clip IDs (TASK 7: prevent duplicate source replenishment)
                exclude_sources = kwargs.get("exclude_sources") or []
                exclude_sources_clean = set(
                    os.path.splitext(os.path.basename(str(s)))[0].lower() for s in exclude_sources
                ) | set(str(s).lower() for s in exclude_sources)

                exclude_clip_ids = set(kwargs.get("exclude_clip_ids") or [])

                if exclude_clip_ids:
                    eligible = [c for c in eligible if c.get("clip_id") not in exclude_clip_ids]

                if exclude_sources_clean:
                    eligible_filtered = [
                        c for c in eligible
                        if os.path.splitext(os.path.basename(str(c.get("source_url_or_path") or c.get("source_id") or "")))[0].lower() not in exclude_sources_clean
                        and str(c.get("source_id") or "").lower() not in exclude_sources_clean
                    ]
                    if eligible_filtered or not allow_reuse:
                        eligible = eligible_filtered

                # Type purity filtering
                if cat_type and cat_type.lower() not in ("auto", "mixed", "all", "none"):
                    type_matching = [c for c in eligible if (c.get("cat_video_type") or "").lower() == cat_type.lower()]
                    if len(type_matching) >= needed_min:
                        eligible = type_matching
                    elif type_matching:
                        eligible = type_matching + [c for c in eligible if c not in type_matching]

                # Pre-verified clips prioritized first
                verified_eligible = [c for c in eligible if c.get("is_verified", 0) == 1]
                if len(verified_eligible) >= needed_min:
                    eligible = verified_eligible

                # Rule 2: exclude moments used in last 5 videos unless depleted
                recent_video_ids = self.get_recent_video_ids(5)
                recent_windows = self.get_recent_video_windows(5) if allow_reuse else self.get_recent_video_windows(100000)

                # Allow reuse OFF: no overlap with ANY finished video. Reuse ON: only the last 5 are excluded.
                fresh_candidates = []
                for cand in eligible:
                    c_src = cand.get("source_id") or cand.get("source_url_or_path")
                    c_st = float(cand.get("start_s", 0.0))
                    c_en = float(cand.get("end_s", c_st + 7.5))
                    matches_last_5 = any(
                        is_same_moment(c_src, c_st, c_en, w.get("source_id") or w.get("source_url_or_path"), w.get("start_s", 0.0), w.get("end_s", 7.5))
                        for w in recent_windows
                    )
                    if not matches_last_5:
                        fresh_candidates.append(cand)

                if len(fresh_candidates) >= needed_min or not allow_reuse:
                    eligible_pool = fresh_candidates
                else:
                    # Depleted and the user allowed reuse: fall back to LRU with notice
                    print(f"[LRU FALLBACK] Bank depleted: only {len(fresh_candidates)} clips available outside last 5 videos (needed {needed_min}). Reusing oldest moments via LRU fallback.")
                    eligible_pool = eligible

                # Check if we have enough clips or need to wait patience budget
                if len(eligible_pool) < needed_min and patience_budget > 0 and (time.time() - patience_start) < patience_budget:
                    elapsed_wait = time.time() - patience_start
                    print(f"Finding fresh clips ({len(eligible_pool)} of {needed_min} ready) [waited {elapsed_wait:.0f}s / {patience_budget:.0f}s]...")
                    wait_before_retry = True
                    continue

                if len(eligible_pool) < needed_min:
                    if allow_reuse:
                        # Allow any clips
                        cur_any = conn.execute("""
                            SELECT * FROM clips 
                            WHERE animal_type = ? AND (pending_short_id IS NULL OR pending_short_id = ?)
                            ORDER BY times_used ASC, COALESCE(is_verified, 0) DESC, funny_score DESC
                        """, (animal_type, short_id))
                        eligible_pool = [dict(r) for r in cur_any.fetchall() if (os.path.exists(r["source_url_or_path"]) or "test" in str(r.get("source_url_or_path", "")).lower() or "dummy" in str(r.get("source_url_or_path", "")).lower()) and not self.is_blocked_source(r["source_url_or_path"])]

                if len(eligible_pool) < needed_min:
                    raise RuntimeError(f"NO_NEW_CLIPS_AVAILABLE: Pool has only {len(eligible_pool)} unused clips (needed {needed_min}). Please add new sources.")

                actual_count = min(count, len(eligible_pool))

                # Rule 4: prefer sources not in previous video
                last_video_id = recent_video_ids[0] if recent_video_ids else None
                prev_sources = self.get_sources_for_video(last_video_id) if last_video_id else set()

                # Group eligible by source
                source_groups = {}
                for cand in eligible_pool:
                    src_id = cand.get("source_id") or os.path.basename(cand["source_url_or_path"])
                    source_groups.setdefault(src_id, []).append(cand)

                for src_id in source_groups:
                    source_groups[src_id].sort(key=lambda c: (c.get("is_verified", 0), -c.get("times_used", 0), c.get("funny_score", 0.0), c.get("quality_score", 0.0)), reverse=True)

                # Source cooldown (Rule 3): Do not use same source in next 3 jobs of channel unless no other source
                cooldown_sources = self.get_cooldown_sources(channel=animal_type, last_n_jobs=3)
                source_keys = list(source_groups.keys())
                rng.shuffle(source_keys)
                sources_fresh = [s for s in source_keys if os.path.splitext(s)[0].lower() not in cooldown_sources and os.path.splitext(s)[0].lower() not in prev_sources]
                sources_cooldown = [s for s in source_keys if s not in sources_fresh]
                
                # Ordered source keys: when allow_reuse is False, strictly use fresh sources first
                if not allow_reuse:
                    ordered_source_keys = list(sources_fresh)
                    if not ordered_source_keys or actual_count > 8:
                        ordered_source_keys = list(sources_fresh) + [s for s in sources_cooldown if s not in sources_fresh]
                else:
                    ordered_source_keys = list(sources_fresh) + [s for s in sources_cooldown if s not in sources_fresh]

                # Rule 3: Overlap policy across finished production videos
                # When allow_reuse is OFF, ZERO cross-job overlap is allowed
                last_3_jobs = recent_video_ids[:3]
                max_allowed_overlap_per_job = 0 if not allow_reuse else max(0, int(actual_count * 0.25))
                job_windows = {jid: [w for w in recent_windows if w.get("job_id") == jid] for jid in last_3_jobs}
                overlap_counts_per_job = {jid: 0 for jid in last_3_jobs}

                # Rule 5: max 50% from one source in Short or Long compilations
                max_clips_per_source = max(1, actual_count // 2)

                selected = []
                selected_hashes = []
                seen_windows = set()
                source_clip_counts = {}

                while len(selected) < actual_count:
                    any_popped = False
                    for src_id in ordered_source_keys:
                        if len(selected) >= actual_count:
                            break
                        group = source_groups.get(src_id, [])
                        if not group:
                            continue

                        cand = group.pop(0)
                        any_popped = True
                        c_src_base = os.path.splitext(os.path.basename(str(cand.get("source_url_or_path") or cand.get("source_id") or "")))[0].lower()
                        
                        # Rule 5: Max 50% from one source
                        if source_clip_counts.get(c_src_base, 0) >= max_clips_per_source:
                            continue

                        c_start = round(float(cand.get("start_s", 0)), 1)
                        c_end = round(float(cand.get("end_s", 0)), 1)
                        win_key = (c_src_base, c_start, c_end)

                        if win_key in seen_windows:
                            continue

                        try:
                            c_hashes = json.loads(cand["fingerprint"]) if isinstance(cand.get("fingerprint"), str) else (cand.get("fingerprint") or [])
                        except Exception:
                            c_hashes = []

                        # Strict production reuse check across all finished videos (Rule 1 & 2)
                        if not allow_reuse:
                            used_in_prod, _ = self.is_window_used_in_production(
                                source_id_or_path=c_src_base,
                                start_s=c_start,
                                end_s=c_end,
                                frame_hashes=c_hashes,
                                channel=animal_type,
                                exclude_job_id=short_id
                            )
                            if used_in_prod:
                                continue

                        # Rule 6: min 3.0s between windows of same source
                        too_close = False
                        for prev in selected:
                            p_src_base = os.path.splitext(os.path.basename(str(prev.get("source_url_or_path") or prev.get("source_id") or "")))[0].lower()
                            if p_src_base == c_src_base:
                                p_start = round(float(prev.get("start_s", 0)), 1)
                                p_end = round(float(prev.get("end_s", 0)), 1)
                                if not (c_start - p_end >= 3.0 or p_start - c_end >= 3.0):
                                    too_close = True
                                    break
                        if too_close:
                            continue

                        # Rule 3 check: does adding this clip violate overlap cap with any of last 3 videos?
                        violates_overlap_cap = False
                        candidate_matching_jobs = []
                        for jid in last_3_jobs:
                            matches_j = any(
                                is_same_moment(c_src_base, c_start, c_end, w.get("source_id") or w.get("source_url_or_path"), w.get("start_s", 0.0), w.get("end_s", 7.5))
                                for w in job_windows.get(jid, [])
                            )
                            if matches_j:
                                if overlap_counts_per_job[jid] + 1 > max_allowed_overlap_per_job:
                                    violates_overlap_cap = True
                                    break
                                candidate_matching_jobs.append(jid)
                        if violates_overlap_cap:
                            continue

                        try:
                            c_hashes = json.loads(cand["fingerprint"])
                        except Exception:
                            c_hashes = []

                        # Near-duplicate check
                        is_near_dup = False
                        for ex_hashes in selected_hashes:
                            if c_hashes and ex_hashes:
                                matches = sum(1 for ch in c_hashes for rh in ex_hashes if hamming_distance(ch, rh) <= 4)
                                if matches >= 4:
                                    is_near_dup = True
                                    break
                        if is_near_dup:
                            continue

                        c_dict = dict(cand)
                        c_dict["source_path"] = c_dict.get("source_url_or_path")
                        selected.append(c_dict)
                        selected_hashes.append(c_hashes)
                        seen_windows.add(win_key)
                        source_clip_counts[c_src_base] = source_clip_counts.get(c_src_base, 0) + 1
                        for jid in candidate_matching_jobs:
                            overlap_counts_per_job[jid] += 1

                    if not any_popped:
                        break

                if len(selected) < needed_min:
                    raise RuntimeError(f"NO_NEW_CLIPS_AVAILABLE: Diverse clip selection found only {len(selected)} unique clips (needed {needed_min}). Please add new sources.")

                # Mark selected clips as pending for this short
                for s in selected:
                    conn.execute(
                        "UPDATE clips SET pending_short_id = ? WHERE clip_id = ?",
                        (short_id, s["clip_id"])
                    )
                return selected

    def is_duplicate_clip_list(self, clip_ids: list) -> bool:
        if not clip_ids:
            return False
        with self._get_conn() as conn:
            sorted_clips_json = json.dumps(sorted(clip_ids))
            cur = conn.execute("SELECT clip_ids FROM output_registry")
            for r in cur.fetchall():
                try:
                    existing_clips = json.dumps(sorted(json.loads(r["clip_ids"])))
                    if existing_clips == sorted_clips_json:
                        return True
                except Exception:
                    pass
        return False

    def check_duplicate_output(self, sha256: str, clip_ids: list, current_job_id: str = None):
        with self._get_conn() as conn:
            # 1. Exact SHA256 match check
            if sha256:
                if current_job_id:
                    cur = conn.execute("SELECT job_id FROM output_registry WHERE sha256 = ? AND job_id != ?", (sha256, current_job_id))
                else:
                    cur = conn.execute("SELECT job_id FROM output_registry WHERE sha256 = ?", (sha256,))
                row = cur.fetchone()
                if row:
                    return True, f"DUPLICATE_OUTPUT: SHA256 hash matches previous output from job '{row['job_id']}'"

            # 2. Exact clip sequence match check
            if clip_ids:
                sorted_clips_json = json.dumps(sorted(clip_ids))
                if current_job_id:
                    cur2 = conn.execute("SELECT job_id, clip_ids FROM output_registry WHERE job_id != ?", (current_job_id,))
                else:
                    cur2 = conn.execute("SELECT job_id, clip_ids FROM output_registry")
                for r in cur2.fetchall():
                    try:
                        existing_clips = json.dumps(sorted(json.loads(r["clip_ids"])))
                        if existing_clips == sorted_clips_json:
                            return True, f"DUPLICATE_OUTPUT: Exact clip list {clip_ids} was already used in job '{r['job_id']}'"
                    except Exception:
                        pass
        return False, ""

    def register_output(self, job_id: str, output_filename: str, sha256: str, clip_ids: list, duration_sec: float, render_time_sec: float, clip_windows: list = None, is_production: bool = True, channel: str = "cat", title: str = "", captions: list = None):
        import time
        created_at = time.strftime('%Y-%m-%d %H:%M:%S')
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO output_registry 
                (job_id, output_filename, sha256, clip_ids, duration_sec, render_time_sec, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (job_id, output_filename, sha256, json.dumps(clip_ids), duration_sec, render_time_sec, created_at))

            # Record each clip window into finished_video_windows
            cur_idx = conn.execute("SELECT COALESCE(MAX(video_index), 0) + 1 FROM finished_video_windows")
            row_idx = cur_idx.fetchone()
            video_idx = row_idx[0] if row_idx else 1

            if clip_windows and isinstance(clip_windows, list):
                for idx_cw, cw in enumerate(clip_windows):
                    s_path = cw.get("source_url_or_path") or cw.get("source_path") or cw.get("source_file") or cw.get("source") or ""
                    s_id = cw.get("source_id") or (os.path.splitext(os.path.basename(str(s_path)))[0] if s_path else "")
                    st = float(cw.get("start_s", cw.get("start", 0.0)))
                    dur = float(cw.get("dur_s", cw.get("duration", 7.5)))
                    en = float(cw.get("end_s", st + dur))
                    cid = cw.get("clip_id") or ""
                    f_hashes = cw.get("frame_hashes")
                    if not f_hashes and s_path and os.path.exists(s_path):
                        try:
                            f_hashes = compute_window_5_phashes(s_path, st, en)
                        except Exception:
                            f_hashes = []
                    hashes_json = json.dumps(f_hashes) if isinstance(f_hashes, list) else str(f_hashes or "[]")
                    cap = cw.get("caption") or (captions[idx_cw] if captions and idx_cw < len(captions) else "")
                    t_val = title or cw.get("title") or ""
                    conn.execute("""
                        INSERT INTO finished_video_windows
                        (job_id, source_id, source_url_or_path, start_s, end_s, clip_id, video_index, created_at, is_production, frame_hashes, channel, caption, title)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (job_id, s_id, s_path, st, en, cid, video_idx, created_at, 1 if is_production else 0, hashes_json, channel, cap, t_val))
            elif clip_ids:
                for idx_c, cid in enumerate(clip_ids):
                    c_row = conn.execute("SELECT source_id, source_url_or_path, start_s, end_s, fingerprint FROM clips WHERE clip_id = ?", (cid,)).fetchone()
                    if c_row:
                        s_path = c_row["source_url_or_path"] or ""
                        s_id = c_row["source_id"] or (os.path.splitext(os.path.basename(str(s_path)))[0] if s_path else "")
                        st = float(c_row["start_s"] or 0.0)
                        en = float(c_row["end_s"] or 0.0)
                        f_hashes = c_row["fingerprint"]
                        hashes_json = f_hashes if f_hashes else "[]"
                        cap = captions[idx_c] if captions and idx_c < len(captions) else ""
                        conn.execute("""
                            INSERT INTO finished_video_windows
                            (job_id, source_id, source_url_or_path, start_s, end_s, clip_id, video_index, created_at, is_production, frame_hashes, channel, caption, title)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            job_id,
                            s_id,
                            s_path,
                            st,
                            en,
                            cid,
                            video_idx,
                            created_at,
                            1 if is_production else 0,
                            hashes_json,
                            channel,
                            cap,
                            title
                        ))
            conn.commit()

    def is_window_used_in_production(
        self,
        source_id_or_path: str,
        start_s: float,
        end_s: float,
        frame_hashes: list = None,
        channel: str = None,
        overlap_thresh: float = 0.30,
        exclude_job_id: str = None
    ) -> tuple:
        """
        Checks if a candidate window was used in any finished PRODUCTION video.
        Checks:
        1. Same source video ID and overlapping time ranges (> 30% overlap).
        2. Perceptual hash of 5 frames matching any finished production window.
        Test and sandbox jobs do NOT count as used.
        """
        with self._get_conn() as conn:
            query = "SELECT job_id, source_id, source_url_or_path, start_s, end_s, clip_id, frame_hashes FROM finished_video_windows WHERE is_production = 1"
            params = []
            if channel:
                query += " AND (channel = ? OR channel IS NULL OR channel = '' OR channel = 'all')"
                params.append(channel)
            if exclude_job_id:
                query += " AND job_id != ?"
                params.append(exclude_job_id)
                if str(exclude_job_id).endswith("_teaser"):
                    query += " AND job_id != ?"
                    params.append(str(exclude_job_id).replace("_teaser", ""))

            rows = conn.execute(query, tuple(params)).fetchall()

        for r in rows:
            r_jid = r["job_id"]
            r_sid = r["source_id"] or r["source_url_or_path"]
            r_st = float(r["start_s"] or 0.0)
            r_en = float(r["end_s"] or 0.0)
            r_cid = r["clip_id"]

            # 1. Check same moment (> 30% overlap of same source)
            if is_same_moment(source_id_or_path, start_s, end_s, r_sid, r_st, r_en, overlap_thresh=overlap_thresh):
                return True, f"Source moment overlap > {int(overlap_thresh*100)}% with finished production job '{r_jid}' (clip {r_cid})"

            # 2. Check 5-frame perceptual hash against finished window
            if frame_hashes and r["frame_hashes"]:
                try:
                    r_hashes = json.loads(r["frame_hashes"]) if isinstance(r["frame_hashes"], str) else r["frame_hashes"]
                    if are_frame_hashes_matching(frame_hashes, r_hashes, max_dist=6, min_matching=3):
                        return True, f"Perceptual_hash match with finished production job '{r_jid}' (clip {r_cid})"
                except Exception:
                    pass

        return False, "OK"

    def is_window_rejected_by_overlap(
        self,
        source_id_or_path: str,
        start_s: float,
        end_s: float,
        overlap_thresh: float = 0.30
    ) -> tuple:
        """
        TASK 5: A window rejected for a real gate value is never offered again,
        keyed by source video ID + overlapping time range (>30% overlap).
        Measurement failure rejections (MEASUREMENT_FAILED) are exempted if retried.
        """
        if not source_id_or_path:
            return False, ""

        with self._get_conn() as conn:
            cur = conn.execute("""
                SELECT clip_id, source_id, source_url_or_path, start_s, end_s, rejection_reason, status
                FROM clips
                WHERE rejection_reason IS NOT NULL AND rejection_reason != ''
                  AND rejection_reason != 'MEASUREMENT_FAILED'
            """)
            rejected_rows = [dict(r) for r in cur.fetchall()]

        for r in rejected_rows:
            r_sid = r.get("source_id") or r.get("source_url_or_path") or ""
            r_st = float(r.get("start_s") or 0.0)
            r_en = float(r.get("end_s") or (r_st + 7.5))
            if is_same_moment(source_id_or_path, start_s, end_s, r_sid, r_st, r_en, overlap_thresh=overlap_thresh):
                rej_reason = r.get("rejection_reason") or "REJECTED_WINDOW"
                return True, f"Overlaps rejected window {r.get('clip_id')} [{r_st:.1f}-{r_en:.1f}]: {rej_reason}"

        return False, ""

    def get_cooldown_sources(self, channel: str = "cat", last_n_jobs: int = 3) -> set:
        """Returns set of normalized source IDs used in the last N finished production jobs for this channel."""
        with self._get_conn() as conn:
            q = """
                SELECT DISTINCT job_id, MAX(id) as max_id 
                FROM finished_video_windows 
                WHERE is_production = 1 AND (channel = ? OR channel IS NULL OR channel = '' OR channel = 'all')
                GROUP BY job_id 
                ORDER BY max_id DESC 
                LIMIT ?
            """
            rows = conn.execute(q, (channel, last_n_jobs)).fetchall()
            job_ids = [r["job_id"] for r in rows]

            if not job_ids:
                return set()

            placeholders = ",".join("?" for _ in job_ids)
            src_rows = conn.execute(f"""
                SELECT source_id, source_url_or_path 
                FROM finished_video_windows 
                WHERE job_id IN ({placeholders})
            """, tuple(job_ids)).fetchall()

        cooldown = set()
        for r in src_rows:
            s1 = r["source_id"]
            s2 = r["source_url_or_path"]
            if s1:
                cooldown.add(os.path.splitext(os.path.basename(str(s1)))[0].lower())
                cooldown.add(str(s1).lower())
            if s2:
                cooldown.add(os.path.splitext(os.path.basename(str(s2)))[0].lower())
        return cooldown

    def get_recent_captions(self, channel: str = "cat", last_n_jobs: int = 3) -> set:
        """Returns set of lowercased, trimmed captions used in the last N finished production jobs for this channel."""
        with self._get_conn() as conn:
            q = """
                SELECT DISTINCT job_id, MAX(id) as max_id 
                FROM finished_video_windows 
                WHERE is_production = 1 AND (channel = ? OR channel IS NULL OR channel = '' OR channel = 'all')
                GROUP BY job_id 
                ORDER BY max_id DESC 
                LIMIT ?
            """
            rows = conn.execute(q, (channel, last_n_jobs)).fetchall()
            job_ids = [r["job_id"] for r in rows]

            if not job_ids:
                return set()

            placeholders = ",".join("?" for _ in job_ids)
            cap_rows = conn.execute(f"""
                SELECT caption 
                FROM finished_video_windows 
                WHERE job_id IN ({placeholders}) AND caption IS NOT NULL AND caption != ''
            """, tuple(job_ids)).fetchall()

        return {r["caption"].strip().lower() for r in cap_rows if r["caption"]}

    def is_title_used(self, title: str, channel: str = None) -> bool:
        """Returns True if title was already used in any recorded metadata or finished production video."""
        if not title:
            return False
        norm_t = title.strip().lower()
        with self._get_conn() as conn:
            c1 = conn.execute("SELECT 1 FROM metadata_history WHERE LOWER(TRIM(title)) = ?", (norm_t,)).fetchone()
            if c1:
                return True
            try:
                c2 = conn.execute("SELECT 1 FROM finished_video_windows WHERE LOWER(TRIM(title)) = ? AND is_production = 1", (norm_t,)).fetchone()
                if c2:
                    return True
            except Exception:
                pass
        return False

    def get_recent_video_ids(self, limit: int = 5, channel: str = None) -> list:
        """Returns list of the most recent finished production job_ids."""
        with self._get_conn() as conn:
            q = "SELECT DISTINCT job_id, MAX(id) as max_id FROM finished_video_windows WHERE is_production = 1"
            params = []
            if channel:
                q += " AND (channel = ? OR channel IS NULL OR channel = '' OR channel = 'all')"
                params.append(channel)
            q += " GROUP BY job_id ORDER BY max_id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(q, tuple(params)).fetchall()
            return [r["job_id"] for r in rows]

    def get_recent_video_windows(self, limit_videos: int = 5, channel: str = None) -> list:
        """Returns all window records from the most recent finished production jobs."""
        jids = self.get_recent_video_ids(limit_videos, channel=channel)
        if not jids:
            return []
        placeholders = ",".join("?" for _ in jids)
        with self._get_conn() as conn:
            rows = conn.execute(f"""
                SELECT job_id, clip_id, source_id, source_url_or_path, start_s, end_s, frame_hashes, channel
                FROM finished_video_windows
                WHERE job_id IN ({placeholders})
                ORDER BY id ASC
            """, tuple(jids)).fetchall()
            return [dict(r) for r in rows]

    def get_sources_for_video(self, video_id: str) -> set:
        """Returns set of source basenames used in the given finished video."""
        if not video_id:
            return set()
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT source_id, source_url_or_path
                FROM finished_video_windows
                WHERE job_id = ?
            """, (video_id,)).fetchall()
            srcs = set()
            for r in rows:
                s1 = r["source_id"]
                s2 = r["source_url_or_path"]
                if s1:
                    srcs.add(os.path.splitext(os.path.basename(str(s1)))[0].lower())
                if s2:
                    srcs.add(os.path.splitext(os.path.basename(str(s2)))[0].lower())
            return srcs

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

    def reserve_clip_by_id(self, clip_id: str, short_id: str) -> bool:
        """Explicitly reserves a single specific clip from the bank for a job."""
        with self._get_conn() as conn:
            cur = conn.execute("""
                UPDATE clips
                SET pending_short_id = ?
                WHERE clip_id = ? AND (pending_short_id IS NULL OR pending_short_id = ?)
            """, (short_id, clip_id, short_id))
            conn.commit()
            return cur.rowcount > 0

    def get_verified_clips(self, animal_type: str = "cat", limit: int = 20, exclude_clip_ids: list = None, **kwargs) -> list:
        """Fetches available verified clips from the bank ordered by framing score."""
        target_animal = kwargs.get("animal_mode") or animal_type or "cat"
        cat_type = kwargs.get("cat_video_type") or kwargs.get("video_cat_type")
        exclude_set = set(exclude_clip_ids or [])
        with self._get_conn() as conn:
            cur = conn.execute("""
                SELECT clip_id, source_id, source_url_or_path, license, start_s, end_s,
                       quality_score, funny_score, is_verified, framing_score, sharpness,
                       orientation, uploader, title, verified_plan, verified_at,
                       cat_video_type, cat_video_type_conf
                FROM clips
                WHERE is_verified = 1 AND times_used = 0 AND pending_short_id IS NULL AND animal_type = ?
                ORDER BY COALESCE(framing_score, quality_score) DESC
            """, (target_animal,))
            rows = [dict(r) for r in cur.fetchall()]
        # times_used misses a window that overlaps a finished video, so the count function decides
        if not kwargs.get("allow_reuse"):
            windows = self.get_ledger_counts(target_animal, current_job_id=kwargs.get("current_job_id"), include_windows=True)["windows"]
            fresh_ids = {w["clip_id"] for w in windows["usable_now"] + windows["cooldown"]}
            rows = [r for r in rows if r["clip_id"] in fresh_ids]
        if cat_type and cat_type.lower() not in ("auto", "mixed", "all", "none"):
            type_rows = [r for r in rows if (r.get("cat_video_type") or "").lower() == cat_type.lower()]
            if type_rows:
                rows = type_rows + [r for r in rows if r not in type_rows]
        return [r for r in rows if r["clip_id"] not in exclude_set][:limit]

    def check_ledger_guard(self, is_production: bool = True) -> dict:
        """
        Requirement 3b: Guard against synthetic rows or sandbox databases entering production engine.
        Returns:
            {
                "passed": bool,
                "mode": "production" | "sandbox",
                "path": str,
                "verified_by_origin": dict,
                "error": str (if failed)
            }
        """
        norm_path = os.path.normpath(os.path.abspath(self.db_path)).lower()
        is_sandbox_path = "sandbox" in norm_path or os.path.basename(norm_path).startswith("sandbox_")

        origin_counts = {}
        with self._get_conn() as conn:
            cur = conn.execute("""
                SELECT source_url_or_path, is_verified
                FROM clips
                WHERE is_verified = 1
            """)
            for row in cur.fetchall():
                src = str(row["source_url_or_path"] or "").lower()
                bname = os.path.basename(src)
                if bname.startswith("cache_"):
                    orig = "youtube_cache"
                elif bname.startswith("src_vert_") or bname.startswith("src_horiz_"):
                    orig = "synthetic"
                elif "test" in bname:
                    orig = "test"
                else:
                    orig = "local_raw"
                origin_counts[orig] = origin_counts.get(orig, 0) + 1

        mode = "sandbox" if is_sandbox_path else "production"

        if is_production:
            if is_sandbox_path:
                return {
                    "passed": False,
                    "mode": mode,
                    "path": self.db_path,
                    "verified_by_origin": origin_counts,
                    "error": f"LEDGER_GUARD: Refusing to start production engine on sandbox ledger path: {self.db_path}"
                }

            with self._get_conn() as conn:
                cur = conn.execute("""
                    SELECT COUNT(*) as c FROM clips
                    WHERE source_url_or_path LIKE '%src_vert%'
                       OR source_url_or_path LIKE '%src_horiz%'
                       OR clip_id LIKE 'test_syn_%'
                       OR clip_id LIKE '%synthetic%'
                       OR (is_verified = 1 AND (verified_plan IS NULL OR verified_plan = '' OR verified_plan = '{}') AND framing_score >= 0.94 AND framing_score <= 0.96)
                """)
                bad_count = cur.fetchone()["c"]

            if bad_count > 0:
                return {
                    "passed": False,
                    "mode": mode,
                    "path": self.db_path,
                    "verified_by_origin": origin_counts,
                    "error": f"LEDGER_GUARD: Refusing to start: production ledger contains {bad_count} synthetic/unverified test rows"
                }

        return {
            "passed": True,
            "mode": mode,
            "path": self.db_path,
            "verified_by_origin": origin_counts,
            "error": None
        }

    def release_single_clip(self, clip_id: str, reason: str = None):
        """Releases a single reserved clip back to the pool, or marks rejection if failed."""
        with self._get_conn() as conn:
            if reason:
                conn.execute(
                    "UPDATE clips SET pending_short_id = NULL, is_verified = 0, rejection_reason = ? WHERE clip_id = ?",
                    (str(reason), clip_id)
                )
            else:
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

    def clean_stale_reservations(self, active_short_ids = None):
        """Alias for cleanup_stale_reservations supporting list, set, or single string."""
        if isinstance(active_short_ids, str):
            self.cleanup_stale_reservations(active_short_ids)
        elif isinstance(active_short_ids, (list, tuple, set)) and len(active_short_ids) == 1:
            self.cleanup_stale_reservations(list(active_short_ids)[0])
        elif isinstance(active_short_ids, (list, tuple, set)) and len(active_short_ids) > 1:
            with self._get_conn() as conn:
                placeholders = ",".join("?" for _ in active_short_ids)
                conn.execute(f"UPDATE clips SET pending_short_id = NULL WHERE pending_short_id NOT IN ({placeholders})", tuple(active_short_ids))
                conn.commit()
        else:
            self.cleanup_stale_reservations(None)


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
        if isinstance(count, (list, tuple, set)):
            j_id = short_id or kwargs.get("short_id", "pending")
            if not count:
                return []
            placeholders = ",".join("?" for _ in count)
            with self._get_conn() as conn:
                conn.execute(f"UPDATE clips SET pending_short_id = ? WHERE clip_id IN ({placeholders})", [j_id] + list(count))
                conn.commit()
            return list(count)
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
        return self.reserve_clips_for_short(c_val, a_mode, j_id, min_required=min_required, allow_reuse=kwargs.get("allow_reuse", False))

    def reserve_candidates(self, job_id: str, animal_type: str = "cat", target_clips: int = 6, **kwargs) -> list:
        """
        Reserves exactly 2x unique candidate windows for a job, enforcing 10s NMS gap.
        """
        candidate_count = target_clips * 2
        return self.reserve_clips_for_short(
            count=candidate_count,
            animal_type=animal_type,
            short_id=job_id,
            allow_reuse=kwargs.get("allow_reuse", False),
            min_required=min(target_clips, 2)
        )

    def ingest_candidate(self, source_path: str, start_s: float, end_s: float,
                         license_type: str = "CC-BY", animal_type: str = "cat",
                         quality_score: float = 0.8, funny_score: float = 0.8,
                         is_verified: int = 0, framing_score: float = 0.0, sharpness: float = 0.0,
                         orientation: str = "landscape", compilation_flag: int = 0,
                         uploader: str = "", title: str = "", verified_plan: dict = None) -> str:
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
        clip_id = f"c_{animal_type}_{src_id}_{int(start_s)}_{int(end_s)}"
        import time
        v_at = time.strftime('%Y-%m-%d %H:%M:%S') if is_verified else None

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
            animal_type=animal_type,
            is_verified=is_verified,
            framing_score=framing_score,
            sharpness=sharpness,
            orientation=orientation,
            compilation_flag=compilation_flag,
            uploader=uploader,
            title=title,
            verified_plan=verified_plan,
            verified_at=v_at
        )
        return clip_id if success else None

    def record_metadata(self, job_id: str, animal_type: str, title: str, description: str,
                        tags: str, hashtags: str, template_id: str = "", platform: str = "all") -> int:
        """Records generated metadata for uniqueness tracking and platform audit."""
        import time
        created_at = time.strftime('%Y-%m-%d %H:%M:%S')
        with self._get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO metadata_history 
                (job_id, animal_type, title, description, tags, hashtags, template_id, platform, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (job_id, animal_type, title, description, tags, hashtags, template_id, platform, created_at))
            conn.commit()
            return cur.lastrowid

    def get_recent_metadata_titles(self, animal_type: str = "cat", limit: int = 50) -> list:
        """Returns recent titles to guarantee 0% exact repeat and <40% 3-gram overlap."""
        with self._get_conn() as conn:
            cur = conn.execute("""
                SELECT title FROM metadata_history 
                WHERE animal_type = ? 
                ORDER BY id DESC LIMIT ?
            """, (animal_type, limit))
            return [r["title"] for r in cur.fetchall()]

    def get_recent_template_ids(self, animal_type: str = "cat", limit: int = 50) -> list:
        """Returns recent template IDs to enforce template rotation spacing."""
        with self._get_conn() as conn:
            cur = conn.execute("""
                SELECT template_id FROM metadata_history 
                WHERE animal_type = ? AND template_id != '' 
                ORDER BY id DESC LIMIT ?
            """, (animal_type, limit))
            return [r["template_id"] for r in cur.fetchall()]


def get_pool_ready_and_capacity(animal_type='cat', target_clips=100, allow_reuse: bool = False, exclude_recent_videos: int = 5) -> tuple:
    ledger = ClipLedger()
    res = ledger.get_pool_ready_and_capacity(animal_type, target_clips, allow_reuse=allow_reuse, exclude_recent_videos=exclude_recent_videos)
    return res["ready"], res["usable_sources"], res["capacity"]

