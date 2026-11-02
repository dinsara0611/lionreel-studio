"""
safe_cleanup.py — Phase 5 Safe Clean-Up Engine for LionReel Cat Make.

Implements strict protection rules so finished production videos, reports, clip mapping,
credits, QA files, the clip ledger database, verified bank clips & sources with licence/creator
data, config files, channel analytics, thumbnails of finished videos, the current job, and
resumable ("Waiting" / "Interrupted") job clips are NEVER deleted under any circumstance.

Candidate groups (each reported with size and count):
1. temp_work_folders: Temp and work folders of finished or failed jobs (keeps rendered clips of Waiting/Interrupted resumable jobs).
2. intermediate_renders: Intermediate render files (assembled_*, master_audio_*, concat_*.txt, *_cap.mp4, TEMP_MPY_*, *.part, *.tmp).
3. rejected_unreferenced_cache: Cached downloads of sources that were rejected or are not in the ledger.
4. test_sandbox_outputs: Test and sandbox outputs (is_test=True).
5. old_preview_caches: Preview and contact-sheet caches older than 14 days (excluding finished production video thumbnails/sheets).
6. old_logs: Old logs older than 30 days (always keeping at least the last 10 job logs).
7. duplicate_files: Duplicate files with the same SHA-256 hash outside protected production assets.
8. empty_folders: Empty folders in work, output, scratch, or cache directories.
9. python_cache: Python cache folders (__pycache__, .pytest_cache, *.pyc).

Supports:
- Preview first (returns groups, sizes, counts without deleting anything).
- Group selection (tick/untick groups).
- Single confirmation check requiring confirmed=True for non-dry-run execution.
- "Move to Recycle Bin instead of permanent delete" option (default ON) using Windows SHFileOperationW (FOF_ALLOWUNDO).
- Dry run mode (deletes nothing, logs previewed removal set).
- Persistent audit log (cleanup_log.json) recording every removed path, size, group, mode, and timestamp.
- Google Drive detection: notifies the user when deleted paths reside on Google Drive (where Drive's own trash also retains files).
"""

import ctypes
from ctypes import wintypes
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set, Tuple


DEFAULT_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOCAL_DATA_DIR = r"C:\LionReel" if os.path.exists(r"C:\LionReel") else DEFAULT_BASE_DIR


def format_bytes(size_bytes: int) -> str:
    """Format byte size into human-readable string (B, KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024.0:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024.0 * 1024.0):.2f} MB"
    else:
        return f"{size_bytes / (1024.0 * 1024.0 * 1024.0):.2f} GB"


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_google_drive_path(path: str) -> bool:
    """Detect whether a path resides on Google Drive for Desktop (e.g., G:\\My Drive)."""
    ap = os.path.abspath(path)
    low = ap.lower()
    if "my drive" in low or "google drive" in low or low.startswith("g:\\"):
        return True
    return False


# Windows Shell SHFileOperationW for Recycle Bin (FOF_ALLOWUNDO)
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


def send_to_recycle_bin(target_path: str) -> Tuple[bool, str]:
    """
    Move a file or folder to the Windows Recycle Bin (or Google Drive trash on Drive volumes)
    using Shell32 SHFileOperationW with FOF_ALLOWUNDO.
    Never performs permanent deletion.
    """
    abs_path = os.path.abspath(target_path)
    if not os.path.exists(abs_path):
        return False, "Path does not exist"

    # Double-null terminated wide string required by SHFileOperationW
    p_from = abs_path + "\0\0"
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = p_from
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None

    res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if res == 0 and not op.fAnyOperationsAborted and not os.path.exists(abs_path):
        return True, "Moved to Recycle Bin"

    # Fallback via PowerShell VisualBasic FileIO (still strictly RecycleOption.SendToRecycleBin)
    try:
        import subprocess
        escaped = abs_path.replace("'", "''")
        if os.path.isdir(abs_path):
            ps_cmd = (
                "Add-Type -AssemblyName Microsoft.VisualBasic; "
                f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory('{escaped}', "
                "'OnlyErrorDialogs', 'SendToRecycleBin')"
            )
        else:
            ps_cmd = (
                "Add-Type -AssemblyName Microsoft.VisualBasic; "
                f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('{escaped}', "
                "'OnlyErrorDialogs', 'SendToRecycleBin')"
            )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0 and not os.path.exists(abs_path):
            return True, "Moved to Recycle Bin (VB FileIO)"
        return False, f"Recycle Bin operation failed (code={res}, ps={proc.stderr.strip()})"
    except Exception as exc:
        return False, f"Recycle Bin error: {exc}"


def is_test_identifier(name_or_path: str) -> bool:
    """Return True if a filename, job_id, or path is a test/sandbox artifact."""
    low = os.path.basename(name_or_path).lower()
    full_low = name_or_path.replace("\\", "/").lower()
    test_tokens = (
        "sandbox",
        "smoke",
        "test_",
        "_test",
        "repro",
        "dummy",
        "mock",
        "synthetic",
        "_old_baseline",
        "rerender",
        "verify_",
        "probe_",
        "temp_mpy",
        "scratch_",
    )
    if any(tok in low for tok in test_tokens):
        return True
    if "/scratch/" in full_low or "/tests/" in full_low:
        return True
    return False


def _is_job_resumable(job_dir: str) -> bool:
    """
    Check if a job work directory belongs to a "Waiting" or "Interrupted" job that has
    rendered clips and is resumable.
    """
    if not os.path.isdir(job_dir):
        return False

    clips_dir = os.path.join(job_dir, "clips")
    clips_rendered_json = os.path.join(job_dir, "clips_rendered.json")
    has_rendered_clips = False
    if os.path.isfile(clips_rendered_json):
        has_rendered_clips = True
    elif os.path.isdir(clips_dir):
        try:
            has_rendered_clips = any(
                f.lower().endswith(".mp4") and os.path.getsize(os.path.join(clips_dir, f)) > 1024
                for f in os.listdir(clips_dir)
            )
        except Exception:
            pass

    resumable_statuses = {
        "waiting",
        "waiting_for_footage",
        "needs_sources",
        "interrupted",
        "paused",
        "running",
        "starting",
        "queued",
    }

    # Check job_result.json
    jr_path = os.path.join(job_dir, "job_result.json")
    if os.path.isfile(jr_path):
        try:
            with open(jr_path, "r", encoding="utf-8") as f:
                jr = json.load(f)
            status = str(jr.get("status") or jr.get("state") or "").lower().strip()
            if status in resumable_statuses:
                return True
            if status in ("success", "job_success", "completed", "passed"):
                return False
            # If interrupted or failed mid-way with rendered clips and explicitly marked resumable
            if jr.get("resumable") is True and has_rendered_clips:
                return True
        except Exception:
            pass

    # Check stages_state.json
    ss_path = os.path.join(job_dir, "stages_state.json")
    if os.path.isfile(ss_path):
        try:
            with open(ss_path, "r", encoding="utf-8") as f:
                ss = json.load(f)
            state = str(ss.get("state") or ss.get("status") or "").lower().strip()
            if state in resumable_statuses:
                return True
            if state in ("completed", "success", "failed", "cancelled", "stopped", "error"):
                # Even if stopped/interrupted, check if stages_state marks it waiting/interrupted
                if state == "interrupted" and has_rendered_clips:
                    return True
                return False
        except Exception:
            pass

    # If there is no terminal job_result.json yet, and it has rendered clips, treat as interrupted/resumable!
    if not os.path.isfile(jr_path) and has_rendered_clips:
        return True

    return False


def _load_ledger_protected_sources(ledger_db_path: str) -> Tuple[Set[str], Set[str]]:
    """
    Inspect clip_ledger.db to identify:
    - protected_source_ids / paths: sources that are verified, in the bank, or have valid clips/licences.
    - rejected_source_ids / paths: sources that were explicitly rejected and have 0 verified clips.
    """
    protected_tokens: Set[str] = set()
    rejected_tokens: Set[str] = set()

    if not ledger_db_path or not os.path.isfile(ledger_db_path):
        return protected_tokens, rejected_tokens

    try:
        conn = sqlite3.connect(ledger_db_path, timeout=5.0)
        cur = conn.cursor()

        # Check sources table
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}

        verified_source_ids: Set[str] = set()
        if "clip_windows" in tables:
            try:
                cur.execute("SELECT DISTINCT source_id, local_path FROM clip_windows WHERE status='verified' OR qa_passed=1")
                for sid, lpath in cur.fetchall():
                    if sid:
                        verified_source_ids.add(str(sid))
                        protected_tokens.add(str(sid).lower())
                    if lpath:
                        protected_tokens.add(os.path.basename(str(lpath)).lower())
                        protected_tokens.add(_norm(str(lpath)))
            except Exception:
                try:
                    cur.execute("SELECT DISTINCT source_id FROM clip_windows")
                    for (sid,) in cur.fetchall():
                        if sid:
                            verified_source_ids.add(str(sid))
                            protected_tokens.add(str(sid).lower())
                except Exception:
                    pass

        if "clips" in tables:
            try:
                cur.execute("PRAGMA table_info(clips)")
                ccols = {r[1] for r in cur.fetchall()}
                path_col = "source_url_or_path" if "source_url_or_path" in ccols else ("file_path" if "file_path" in ccols else "local_path")
                ver_col = "is_verified" if "is_verified" in ccols else "verified"
                cur.execute(f"SELECT source_id, {path_col}, {ver_col}, rejection_reason FROM clips")
                for sid, fpath, is_ver, rej in cur.fetchall():
                    if is_ver or not rej:
                        if sid:
                            verified_source_ids.add(str(sid))
                            protected_tokens.add(str(sid).lower())
                        if fpath:
                            protected_tokens.add(os.path.basename(str(fpath)).lower())
                            protected_tokens.add(_norm(str(fpath)))
                    else:
                        if sid and str(sid) not in verified_source_ids:
                            rejected_tokens.add(str(sid).lower())
                        if fpath and str(sid) not in verified_source_ids:
                            rejected_tokens.add(os.path.basename(str(fpath)).lower())
                            rejected_tokens.add(_norm(str(fpath)))
            except Exception:
                pass

        if "blocked_sources" in tables:
            try:
                cur.execute("SELECT source_id FROM blocked_sources")
                for (sid,) in cur.fetchall():
                    if sid and str(sid) not in verified_source_ids:
                        rejected_tokens.add(str(sid).lower())
                        rejected_tokens.add(f"cache_{str(sid).lower()}")
                        rejected_tokens.add(f"cache_{str(sid).lower()}.mp4")
            except Exception:
                pass

        if "finished_video_windows" in tables:
            try:
                cur.execute("SELECT DISTINCT source_id, source_url_or_path FROM finished_video_windows")
                for sid, fpath in cur.fetchall():
                    if sid:
                        verified_source_ids.add(str(sid))
                        protected_tokens.add(str(sid).lower())
                    if fpath:
                        protected_tokens.add(os.path.basename(str(fpath)).lower())
                        protected_tokens.add(_norm(str(fpath)))
            except Exception:
                pass

        if "used_windows" in tables:
            try:
                cur.execute("SELECT DISTINCT source_id FROM used_windows")
                for (sid,) in cur.fetchall():
                    if sid:
                        verified_source_ids.add(str(sid))
                        protected_tokens.add(str(sid).lower())
            except Exception:
                pass

        if "sources" in tables:
            try:
                cur.execute("PRAGMA table_info(sources)")
                cols = {r[1] for r in cur.fetchall()}
                select_cols = [c for c in ("source_id", "local_path", "file_path", "rejection_reason", "status", "creator", "license") if c in cols]
                if select_cols:
                    cur.execute(f"SELECT {', '.join(select_cols)} FROM sources")
                    for row in cur.fetchall():
                        row_dict = dict(zip(select_cols, row))
                        sid = str(row_dict.get("source_id") or "")
                        lpath = str(row_dict.get("local_path") or row_dict.get("file_path") or "")
                        rej = row_dict.get("rejection_reason")
                        st = str(row_dict.get("status") or "").lower()
                        if sid in verified_source_ids or (not rej and st not in ("rejected", "invalid", "banned")):
                            if sid:
                                protected_tokens.add(sid.lower())
                            if lpath:
                                protected_tokens.add(os.path.basename(lpath).lower())
                                protected_tokens.add(_norm(lpath))
                        else:
                            if sid and sid not in verified_source_ids:
                                rejected_tokens.add(sid.lower())
                            if lpath and sid not in verified_source_ids:
                                rejected_tokens.add(os.path.basename(lpath).lower())
                                rejected_tokens.add(_norm(lpath))
            except Exception:
                pass

        conn.close()
    except Exception:
        pass

    return protected_tokens, rejected_tokens


class SafeCleanupManager:
    """
    Phase 5 Safe Clean-Up Manager.
    Scans workspace and local data directories, enforces hard protection rules,
    organizes candidate files into the 9 required groups, supports dry-run and
    Recycle Bin execution, and writes cleanup_log.json.
    """

    GROUP_DEFINITIONS = [
        (
            "temp_work_folders",
            "Temp & Work Folders of Finished/Failed Jobs",
            "Temporary job work directories (keeps rendered clips of Waiting or Interrupted resumable jobs).",
        ),
        (
            "intermediate_renders",
            "Intermediate Render Files",
            "Unmerged audio stems, concat lists, temp MoviePy/FFmpeg clips, and .part/.tmp fragments.",
        ),
        (
            "rejected_unreferenced_cache",
            "Rejected or Unreferenced Source Downloads",
            "Cached source downloads that were rejected by quality gates or are not in the clip ledger.",
        ),
        (
            "test_sandbox_outputs",
            "Test & Sandbox Outputs (is_test)",
            "Videos, folders, and artifacts generated by automated sandbox, smoke, or unit tests.",
        ),
        (
            "old_preview_caches",
            "Preview & Contact-Sheet Caches (>14 Days)",
            "Preview clips and temporary contact sheets older than 14 days (excludes finished production videos).",
        ),
        (
            "old_logs",
            "Old Logs (>30 Days, Keeps Last 10)",
            "Historical log files older than 30 days (always preserves the 10 most recent job logs).",
        ),
        (
            "duplicate_files",
            "Duplicate Files (Identical SHA-256 Hash)",
            "Redundant duplicate copies with identical content hash outside protected deliverables.",
        ),
        (
            "empty_folders",
            "Empty Folders",
            "Empty directories left behind in work, output, scratch, or cache folders.",
        ),
        (
            "python_cache",
            "Python Cache Folders (__pycache__)",
            "Compiled Python bytecode caches (__pycache__, .pytest_cache, .pyc files).",
        ),
    ]

    def __init__(
        self,
        base_dir: str = DEFAULT_BASE_DIR,
        local_data_dir: Optional[str] = None,
        current_job_id: Optional[str] = None,
        log_path: Optional[str] = None,
    ):
        self.base_dir = os.path.abspath(base_dir)
        if local_data_dir is None:
            # If base_dir is inside a temp/test folder, keep local_data_dir scoped to base_dir unless C:\LionReel is explicitly wanted
            if os.path.normcase(self.base_dir) == os.path.normcase(DEFAULT_BASE_DIR):
                self.local_data_dir = DEFAULT_LOCAL_DATA_DIR
            else:
                self.local_data_dir = self.base_dir
        else:
            self.local_data_dir = os.path.abspath(local_data_dir)

        self.current_job_id = current_job_id
        self.log_path = log_path or os.path.join(self.base_dir, "cleanup_log.json")

        self.finished_dir = os.path.join(self.base_dir, "finished")
        self.output_dir = os.path.join(self.base_dir, "output")
        self.raw_dir = os.path.join(self.base_dir, "raw")
        self.config_dir = os.path.join(self.base_dir, "config")
        self.data_dir = os.path.join(self.base_dir, "data")
        self.local_work_dir = os.path.join(self.local_data_dir, "work")
        self.base_work_dir = os.path.join(self.base_dir, "work")
        self.local_cache_dir = os.path.join(self.local_data_dir, "cache")
        self.local_db_dir = os.path.join(self.local_data_dir, "data")
        self.local_logs_dir = os.path.join(self.local_data_dir, "logs")
        self.base_logs_dir = os.path.join(self.base_dir, "logs")

        self._protected_exact_paths: Set[str] = set()
        self._protected_dir_prefixes: Set[str] = set()
        self._production_job_ids: Set[str] = set()
        self._protected_source_tokens: Set[str] = set()
        self._rejected_source_tokens: Set[str] = set()
        self._build_protected_registry()

    def _find_ledger_db(self) -> Optional[str]:
        candidates = [
            os.path.join(self.local_db_dir, "clip_ledger.db"),
            os.path.join(self.data_dir, "clip_ledger.db"),
            os.path.join(self.base_dir, "clip_ledger.db"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    def _build_protected_registry(self) -> None:
        """
        Populate the strict set of protected files and directories according to Phase 5a:
        NEVER delete:
        - finished production videos and their reports/mapping/credits/qa files
        - the clip ledger database (and feedback.db)
        - the verified bank clips and sources with their licence and creator data
        - config files
        - channel analytics
        - thumbnails of finished videos
        - the current job
        - rendered clips of a job that is "Waiting" or "Interrupted" and resumable
        """
        # 1. Config files & root registries
        for d in (
            self.config_dir,
            self.data_dir,
            self.local_db_dir,
            os.path.join(self.base_dir, "gui"),
            os.path.join(self.base_dir, "reference"),
            os.path.join(self.base_dir, "models"),
            os.path.join(self.local_data_dir, "models"),
            os.path.join(self.local_data_dir, "venv"),
        ):
            if os.path.exists(d):
                self._protected_dir_prefixes.add(_norm(d))

        root_protected_files = [
            "config.json",
            "credits_registry.csv",
            "ui_freeze_manifest.json",
            "channel_analytics.json",
            "used_videos.txt",
            "used_metadata.json",
            "used_own_footage.txt",
            "clip_ledger.db",
            "feedback.db",
            "cleanup_log.json",
            "PROGRESS.md",
        ]
        for rf in root_protected_files:
            for root in (self.base_dir, self.local_data_dir, self.data_dir, self.local_db_dir):
                p = os.path.join(root, rf)
                self._protected_exact_paths.add(_norm(p))

        # Protect any file with "analytics", "ledger", "credits", "license", "licence" in config/data/root
        for root_dir in (self.base_dir, self.data_dir, self.local_db_dir, self.config_dir):
            if not os.path.isdir(root_dir):
                continue
            try:
                for fn in os.listdir(root_dir):
                    fp = os.path.join(root_dir, fn)
                    low = fn.lower()
                    if any(k in low for k in ("ledger", "analytics", "credits", "licence", "license", "config", "feedback")):
                        if os.path.isdir(fp):
                            self._protected_dir_prefixes.add(_norm(fp))
                        else:
                            self._protected_exact_paths.add(_norm(fp))
            except Exception:
                pass

        # 2. Current active job
        if self.current_job_id:
            for wd in (self.local_work_dir, self.base_work_dir, self.output_dir, self.finished_dir):
                jp = os.path.join(wd, self.current_job_id)
                self._protected_dir_prefixes.add(_norm(jp))
                self._protected_exact_paths.add(_norm(jp))

        # 3. Finished production videos in finished/ and output/
        if os.path.isdir(self.finished_dir):
            try:
                for fn in os.listdir(self.finished_dir):
                    fp = os.path.join(self.finished_dir, fn)
                    if is_test_identifier(fn):
                        continue
                    # Every non-test file in finished/ (videos, thumbnails, .txt credits/metadata, reports, mapping, qa) is protected
                    if os.path.isdir(fp):
                        self._protected_dir_prefixes.add(_norm(fp))
                    else:
                        self._protected_exact_paths.add(_norm(fp))
                        base_stem = os.path.splitext(fn)[0]
                        # Strip suffixes like _short, _long, _teaser, _thumb
                        for suf in ("_short", "_long", "_teaser", "_thumb", "_credits", "_report", "_qa"):
                            if base_stem.endswith(suf):
                                base_stem = base_stem[: -len(suf)]
                        if base_stem.startswith("lionreel_"):
                            self._production_job_ids.add(base_stem)
            except Exception:
                pass

        if os.path.isdir(self.output_dir):
            try:
                for entry in os.listdir(self.output_dir):
                    ep = os.path.join(self.output_dir, entry)
                    if is_test_identifier(entry):
                        continue
                    # Check if output/<job_id>/job_config.json marks is_test
                    jc_path = os.path.join(ep, "job_config.json") if os.path.isdir(ep) else None
                    if jc_path and os.path.isfile(jc_path):
                        try:
                            with open(jc_path, "r", encoding="utf-8") as f:
                                jc = json.load(f)
                            if jc.get("is_test") is True or jc.get("sandbox") is True:
                                continue
                        except Exception:
                            pass
                    # Protect production output deliverable folder and all reports/mapping/credits/qa/thumbnails inside it
                    if os.path.isdir(ep):
                        self._protected_dir_prefixes.add(_norm(ep))
                        self._production_job_ids.add(entry)
                    else:
                        self._protected_exact_paths.add(_norm(ep))
            except Exception:
                pass

        # 4. Resumable ("Waiting" or "Interrupted") jobs in work/ -> protect their rendered clips & state files!
        for wd in {self.local_work_dir, self.base_work_dir}:
            if not os.path.isdir(wd):
                continue
            try:
                for jname in os.listdir(wd):
                    jdir = os.path.join(wd, jname)
                    if not os.path.isdir(jdir):
                        continue
                    if self.current_job_id and jname == self.current_job_id:
                        self._protected_dir_prefixes.add(_norm(jdir))
                        continue
                    if _is_job_resumable(jdir):
                        # Protect clips/ subfolder and state/config manifests needed to resume
                        clips_sub = os.path.join(jdir, "clips")
                        if os.path.isdir(clips_sub):
                            self._protected_dir_prefixes.add(_norm(clips_sub))
                        for keep_fn in (
                            "clips_rendered.json",
                            "job_config.json",
                            "job_result.json",
                            "stages_state.json",
                            "edl.json",
                            "clip_mapping.json",
                        ):
                            kp = os.path.join(jdir, keep_fn)
                            if os.path.exists(kp):
                                self._protected_exact_paths.add(_norm(kp))
            except Exception:
                pass

        # 5. Verified bank clips and sources in raw/ and cache/
        ledger_db = self._find_ledger_db()
        prot_tokens, rej_tokens = _load_ledger_protected_sources(ledger_db)
        self._protected_source_tokens = prot_tokens
        self._rejected_source_tokens = rej_tokens

        for src_dir in {self.raw_dir, self.local_cache_dir, os.path.join(self.base_dir, "cache")}:
            if not os.path.isdir(src_dir):
                continue
            try:
                for fn in os.listdir(src_dir):
                    fp = os.path.join(src_dir, fn)
                    low = fn.lower()
                    norm_fp = _norm(fp)
                    # Always protect licence/creator metadata files in raw/ or cache/
                    if low.endswith((".json", ".csv", ".txt")) and any(
                        k in low for k in ("credit", "licen", "creator", "meta", "source", "bank", "manifest")
                    ):
                        self._protected_exact_paths.add(norm_fp)
                        continue

                    # Check if this source file is explicitly rejected
                    stem = os.path.splitext(low)[0]
                    yt_id = stem
                    for prefix in ("cache_", "raw_"):
                        if yt_id.startswith(prefix):
                            yt_id = yt_id[len(prefix) :]

                    is_rejected = (
                        norm_fp in self._rejected_source_tokens
                        or low in self._rejected_source_tokens
                        or stem in self._rejected_source_tokens
                        or yt_id in self._rejected_source_tokens
                    )
                    is_verified = (
                        norm_fp in self._protected_source_tokens
                        or low in self._protected_source_tokens
                        or stem in self._protected_source_tokens
                        or yt_id in self._protected_source_tokens
                    )

                    if is_verified:
                        self._protected_exact_paths.add(norm_fp)
                    elif not is_rejected and (low.startswith("cache_") or low.startswith("raw_")) and not self._protected_source_tokens:
                        # Rule 0: if ledger has no source rows loaded (or empty DB in unit test without explicit unreferenced cache),
                        # only protect if it has companion creator/licence metadata or is a verified bank clip
                        companion_json = os.path.splitext(fp)[0] + ".json"
                        companion_info = os.path.splitext(fp)[0] + ".info.json"
                        if os.path.isfile(companion_json) or os.path.isfile(companion_info):
                            self._protected_exact_paths.add(norm_fp)
                            self._protected_exact_paths.add(_norm(companion_json))
                            self._protected_exact_paths.add(_norm(companion_info))
            except Exception:
                pass

    def is_protected(self, path: str) -> bool:
        """
        Return True if `path` (file or folder) is protected and must NEVER be offered for deletion.
        """
        norm_p = _norm(path)
        if norm_p in self._protected_exact_paths:
            return True

        for pref in self._protected_dir_prefixes:
            if norm_p == pref or norm_p.startswith(pref + os.sep):
                return True

        # Also protect any parent directory that contains a protected exact path or protected prefix
        for exact in self._protected_exact_paths:
            if exact.startswith(norm_p + os.sep):
                return True
        for pref in self._protected_dir_prefixes:
            if pref.startswith(norm_p + os.sep):
                return True

        # Check filename-level hard protections
        bn = os.path.basename(norm_p)
        if bn in (
            "clip_ledger.db",
            "feedback.db",
            "credits_registry.csv",
            "config.json",
            "ui_freeze_manifest.json",
            "channel_analytics.json",
        ):
            return True

        return False

    def scan_candidates(self) -> Dict[str, Any]:
        """
        Scan the workspace and local data directories and return the 9 candidate groups
        with their file lists, counts, and byte sizes. Nothing is deleted.
        """
        self._build_protected_registry()
        groups_map: Dict[str, List[Dict[str, Any]]] = {gid: [] for gid, _, _ in self.GROUP_DEFINITIONS}
        seen_paths: Set[str] = set()

        def _add_candidate(group_id: str, path: str, reason: str) -> None:
            abs_p = os.path.abspath(path)
            norm_p = _norm(abs_p)
            if norm_p in seen_paths:
                return
            if not os.path.exists(abs_p):
                return
            if self.is_protected(abs_p):
                return
            try:
                if os.path.isdir(abs_p):
                    sz = self._dir_size(abs_p)
                else:
                    sz = os.path.getsize(abs_p)
            except Exception:
                sz = 0
            seen_paths.add(norm_p)
            groups_map[group_id].append(
                {
                    "path": abs_p,
                    "rel_path": self._rel_display(abs_p),
                    "size_bytes": sz,
                    "size_formatted": format_bytes(sz),
                    "is_dir": os.path.isdir(abs_p),
                    "reason": reason,
                    "on_google_drive": is_google_drive_path(abs_p),
                }
            )

        now = time.time()
        fourteen_days_sec = 14 * 86400
        thirty_days_sec = 30 * 86400

        # ------------------------------------------------------------------
        # GROUP 4: Test & Sandbox outputs (is_test) in finished/, output/, work/, scratch/
        # (Scan before temp_work_folders so test jobs are categorized under test_sandbox_outputs)
        # ------------------------------------------------------------------
        for out_root in (self.finished_dir, self.output_dir):
            if not os.path.isdir(out_root):
                continue
            try:
                for entry in os.listdir(out_root):
                    ep = os.path.join(out_root, entry)
                    is_test = is_test_identifier(entry)
                    if not is_test and os.path.isdir(ep):
                        jc_p = os.path.join(ep, "job_config.json")
                        if os.path.isfile(jc_p):
                            try:
                                with open(jc_p, "r", encoding="utf-8") as f:
                                    jc = json.load(f)
                                if jc.get("is_test") is True or jc.get("sandbox") is True:
                                    is_test = True
                            except Exception:
                                pass
                    if is_test:
                        _add_candidate("test_sandbox_outputs", ep, "Test or sandbox output (is_test=True)")
            except Exception:
                pass

        # Scratch folder test outputs
        scratch_dir = os.path.join(self.base_dir, "scratch")
        if os.path.isdir(scratch_dir):
            try:
                for entry in os.listdir(scratch_dir):
                    ep = os.path.join(scratch_dir, entry)
                    if os.path.isfile(ep) or os.path.isdir(ep):
                        _add_candidate("test_sandbox_outputs", ep, "Scratch test artifact")
            except Exception:
                pass

        # ------------------------------------------------------------------
        # GROUP 8: Empty folders (scan before temp_work_folders so truly empty folders go here)
        # ------------------------------------------------------------------
        empty_scan_roots = [
            self.local_work_dir,
            self.base_work_dir,
            self.output_dir,
            os.path.join(self.base_dir, "scratch"),
            self.local_cache_dir,
        ]
        for eroot in empty_scan_roots:
            if not os.path.isdir(eroot):
                continue
            for root, dirs, files in os.walk(eroot, topdown=False):
                if _norm(root) == _norm(eroot):
                    continue
                if self.is_protected(root):
                    continue
                try:
                    if not os.listdir(root):
                        _add_candidate("empty_folders", root, "Empty directory")
                except Exception:
                    pass

        # ------------------------------------------------------------------
        # GROUP 1: Temp and work folders of finished or failed jobs
        # (Keep rendered clips of Waiting or Interrupted resumable jobs!)
        # ------------------------------------------------------------------
        for wd in {self.local_work_dir, self.base_work_dir}:
            if not os.path.isdir(wd):
                continue
            try:
                for jname in os.listdir(wd):
                    jdir = os.path.join(wd, jname)
                    if not os.path.isdir(jdir):
                        continue
                    if self.current_job_id and jname == self.current_job_id:
                        continue
                    if is_test_identifier(jname):
                        _add_candidate("test_sandbox_outputs", jdir, "Test/sandbox job work folder")
                        continue
                    if _is_job_resumable(jdir):
                        # Job is Waiting or Interrupted and resumable -> keep clips/ and state files,
                        # only offer non-protected temp files inside jdir (if any)
                        for sub in os.listdir(jdir):
                            sub_p = os.path.join(jdir, sub)
                            if not self.is_protected(sub_p):
                                _add_candidate(
                                    "temp_work_folders",
                                    sub_p,
                                    "Temp file inside resumable job (rendered clips preserved)",
                                )
                    else:
                        _add_candidate("temp_work_folders", jdir, "Work folder of finished or failed job")
            except Exception:
                pass

        # ------------------------------------------------------------------
        # GROUP 2: Intermediate render files
        # ------------------------------------------------------------------
        intermediate_prefixes = (
            "assembled_",
            "master_audio_",
            "concat_",
            "cut_",
            "capcut_",
            "temp_mpy_",
            "cand_",
        )
        intermediate_suffixes = (".part", ".tmp", ".temp", "_cap.mp4", "_raw.mp4", "_norm.wav")
        for scan_dir in {self.base_dir, self.raw_dir, self.local_data_dir}:
            if not os.path.isdir(scan_dir):
                continue
            try:
                for fn in os.listdir(scan_dir):
                    fp = os.path.join(scan_dir, fn)
                    if not os.path.isfile(fp):
                        continue
                    low = fn.lower()
                    if low.startswith("cache_") or low.startswith("raw_"):
                        # Only if it's a .part/.tmp incomplete download
                        if low.endswith((".part", ".tmp", ".ytdl")):
                            _add_candidate("intermediate_renders", fp, "Incomplete download fragment")
                        continue
                    if (
                        any(low.startswith(p) for p in intermediate_prefixes)
                        or any(low.endswith(s) for s in intermediate_suffixes)
                        or "temp_mpy_" in low
                    ):
                        _add_candidate("intermediate_renders", fp, "Intermediate render file")
            except Exception:
                pass

        # ------------------------------------------------------------------
        # GROUP 3: Cached downloads of sources that were rejected or are not in the ledger
        # ------------------------------------------------------------------
        for cache_root in {self.local_cache_dir, self.raw_dir, os.path.join(self.base_dir, "cache")}:
            if not os.path.isdir(cache_root):
                continue
            try:
                for fn in os.listdir(cache_root):
                    fp = os.path.join(cache_root, fn)
                    if not os.path.isfile(fp):
                        continue
                    low = fn.lower()
                    if not low.endswith((".mp4", ".mkv", ".webm", ".mov", ".avi")):
                        continue
                    if self.is_protected(fp):
                        continue
                    stem = os.path.splitext(low)[0]
                    yt_id = stem
                    for prefix in ("cache_", "raw_"):
                        if yt_id.startswith(prefix):
                            yt_id = yt_id[len(prefix) :]
                    if (
                        _norm(fp) in self._rejected_source_tokens
                        or low in self._rejected_source_tokens
                        or stem in self._rejected_source_tokens
                        or yt_id in self._rejected_source_tokens
                    ):
                        _add_candidate("rejected_unreferenced_cache", fp, "Rejected source in clip ledger")
                    elif self._protected_source_tokens and (
                        _norm(fp) not in self._protected_source_tokens
                        and low not in self._protected_source_tokens
                        and stem not in self._protected_source_tokens
                        and yt_id not in self._protected_source_tokens
                    ):
                        _add_candidate("rejected_unreferenced_cache", fp, "Cached source not referenced in clip ledger")
            except Exception:
                pass

        # ------------------------------------------------------------------
        # GROUP 5: Preview and contact-sheet caches older than 14 days
        # ------------------------------------------------------------------
        preview_dirs = [
            os.path.join(self.base_dir, "previews"),
            os.path.join(self.base_dir, "contact_sheets"),
            os.path.join(self.local_data_dir, "previews"),
            os.path.join(self.local_data_dir, "contact_sheets"),
            os.path.join(self.local_cache_dir, "previews"),
        ]
        for pdir in preview_dirs:
            if not os.path.isdir(pdir):
                continue
            for root, _, files in os.walk(pdir):
                for fn in files:
                    fp = os.path.join(root, fn)
                    if self.is_protected(fp):
                        continue
                    try:
                        age = now - os.path.getmtime(fp)
                        if age > fourteen_days_sec:
                            _add_candidate("old_preview_caches", fp, f"Preview/contact-sheet cache older than 14 days ({int(age // 86400)}d old)")
                    except Exception:
                        pass

        # Also check loose contact_sheet / preview files in work or cache older than 14 days
        for scan_dir in {self.local_cache_dir, self.raw_dir}:
            if not os.path.isdir(scan_dir):
                continue
            try:
                for fn in os.listdir(scan_dir):
                    low = fn.lower()
                    if "contact_sheet" in low or "preview_" in low or low.endswith("_preview.mp4"):
                        fp = os.path.join(scan_dir, fn)
                        if self.is_protected(fp):
                            continue
                        try:
                            age = now - os.path.getmtime(fp)
                            if age > fourteen_days_sec:
                                _add_candidate("old_preview_caches", fp, f"Preview/contact sheet >14 days old ({int(age // 86400)}d)")
                        except Exception:
                            pass
            except Exception:
                pass

        # ------------------------------------------------------------------
        # GROUP 6: Old logs older than 30 days (keep the last 10 job logs)
        # ------------------------------------------------------------------
        all_log_files: List[Tuple[float, str]] = []
        for ldir in {self.local_logs_dir, self.base_logs_dir, self.base_dir}:
            if not os.path.isdir(ldir):
                continue
            try:
                for fn in os.listdir(ldir):
                    low = fn.lower()
                    if low.endswith(".log") or (low.startswith("job_") and low.endswith(".txt")):
                        # Never touch active root live log file
                        if fn in ("automate_log.txt", "server.log"):
                            continue
                        fp = os.path.join(ldir, fn)
                        if os.path.isfile(fp) and not self.is_protected(fp):
                            all_log_files.append((os.path.getmtime(fp), fp))
            except Exception:
                pass

        # Sort newest first and always keep at least the newest 10 logs
        all_log_files.sort(key=lambda x: x[0], reverse=True)
        for idx, (mtime, fp) in enumerate(all_log_files):
            if idx < 10:
                continue
            age = now - mtime
            if age > thirty_days_sec:
                _add_candidate("old_logs", fp, f"Log file older than 30 days ({int(age // 86400)}d old, beyond last 10 logs)")

        # ------------------------------------------------------------------
        # GROUP 7: Duplicate files with the same SHA-256 hash
        # ------------------------------------------------------------------
        hash_buckets: Dict[Tuple[int, str], List[str]] = {}
        dup_scan_dirs = [
            self.raw_dir,
            self.local_cache_dir,
            os.path.join(self.base_dir, "duplicates"),
            os.path.join(self.local_data_dir, "duplicates"),
        ]
        for ddir in dup_scan_dirs:
            if not os.path.isdir(ddir):
                continue
            try:
                for fn in os.listdir(ddir):
                    fp = os.path.join(ddir, fn)
                    if not os.path.isfile(fp):
                        continue
                    try:
                        sz = os.path.getsize(fp)
                        if sz == 0 or sz > 250 * 1024 * 1024:
                            continue
                        h = self._sha256_file(fp)
                        hash_buckets.setdefault((sz, h), []).append(fp)
                    except Exception:
                        pass
            except Exception:
                pass

        for (sz, h), paths in hash_buckets.items():
            if len(paths) < 2:
                continue
            # Sort so protected or canonical paths come first (kept), and duplicates come after
            paths_sorted = sorted(
                paths,
                key=lambda p: (
                    0 if self.is_protected(p) else 1,
                    0 if not ("copy" in os.path.basename(p).lower() or "dup" in os.path.basename(p).lower()) else 1,
                    len(os.path.basename(p)),
                    p,
                ),
            )
            kept_primary = paths_sorted[0]
            for dup_p in paths_sorted[1:]:
                if not self.is_protected(dup_p):
                    _add_candidate(
                        "duplicate_files",
                        dup_p,
                        f"Duplicate SHA-256 ({h[:10]}...) of {os.path.basename(kept_primary)}",
                    )

        # ------------------------------------------------------------------
        # GROUP 8: Empty folders
        # ------------------------------------------------------------------
        empty_scan_roots = [
            self.local_work_dir,
            self.base_work_dir,
            self.output_dir,
            os.path.join(self.base_dir, "scratch"),
            self.local_cache_dir,
        ]
        for eroot in empty_scan_roots:
            if not os.path.isdir(eroot):
                continue
            for root, dirs, files in os.walk(eroot, topdown=False):
                if _norm(root) == _norm(eroot):
                    continue
                if self.is_protected(root):
                    continue
                try:
                    if not os.listdir(root):
                        _add_candidate("empty_folders", root, "Empty directory")
                except Exception:
                    pass

        # ------------------------------------------------------------------
        # GROUP 9: Python cache folders (__pycache__, .pytest_cache)
        # ------------------------------------------------------------------
        for root, dirs, files in os.walk(self.base_dir):
            # Skip virtual environments and git internals
            low_root = root.lower()
            if "\\.git" in low_root or "\\venv" in low_root or "\\.venv" in low_root:
                continue
            for d in list(dirs):
                if d in ("__pycache__", ".pytest_cache"):
                    dp = os.path.join(root, d)
                    if not self.is_protected(dp):
                        _add_candidate("python_cache", dp, f"Python cache folder ({d})")

        # Assemble structured summary
        groups_out = []
        total_files = 0
        total_bytes = 0
        any_google_drive = False

        for gid, label, desc in self.GROUP_DEFINITIONS:
            items = groups_map.get(gid, [])
            g_bytes = sum(x["size_bytes"] for x in items)
            g_count = len(items)
            total_files += g_count
            total_bytes += g_bytes
            if any(x.get("on_google_drive") for x in items):
                any_google_drive = True
            groups_out.append(
                {
                    "group_id": gid,
                    "label": label,
                    "description": desc,
                    "count": g_count,
                    "size_bytes": g_bytes,
                    "size_formatted": format_bytes(g_bytes),
                    "default_checked": g_count > 0,
                    "files": items,
                }
            )

        on_drive = any_google_drive or is_google_drive_path(self.base_dir)
        drive_notice = (
            "Note: This workspace is on Google Drive. Deleted files from Google Drive paths are also held in Google Drive's own Trash (recoverable for 30 days)."
            if on_drive
            else ""
        )

        return {
            "success": True,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_count": total_files,
            "total_size_bytes": total_bytes,
            "total_size_formatted": format_bytes(total_bytes),
            "on_google_drive": on_drive,
            "drive_trash_notice": drive_notice,
            "recycle_bin_default": True,
            "groups": groups_out,
        }

    def execute_cleanup(
        self,
        selected_groups: Optional[List[str]] = None,
        dry_run: bool = False,
        use_recycle_bin: bool = True,
        confirmed: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute (or dry-run) safe clean-up for the selected candidate groups.
        - If dry_run is False and confirmed is False, refuses to delete anything.
        - Writes every removed (or dry-run simulated) path to cleanup_log.json.
        """
        if not dry_run and not confirmed:
            return {
                "success": False,
                "error": "Confirmation required: please confirm the total size and file count before running Clean Up.",
                "removed_count": 0,
                "freed_bytes": 0,
            }

        scan = self.scan_candidates()
        if selected_groups is None:
            selected_set = {g["group_id"] for g in scan["groups"] if g["count"] > 0}
        else:
            selected_set = set(selected_groups)

        removed_entries: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []
        freed_bytes = 0

        for group in scan["groups"]:
            gid = group["group_id"]
            if gid not in selected_set:
                continue
            for item in group["files"]:
                tpath = item["path"]
                # Double-check protection right before action
                if self.is_protected(tpath):
                    errors.append({"path": tpath, "error": "Protected path blocked by safety guard"})
                    continue

                if dry_run:
                    removed_entries.append(
                        {
                            "path": tpath,
                            "rel_path": item["rel_path"],
                            "group_id": gid,
                            "size_bytes": item["size_bytes"],
                            "mode": "dry_run",
                            "status": "simulated",
                        }
                    )
                    freed_bytes += item["size_bytes"]
                else:
                    if not os.path.exists(tpath):
                        continue
                    if use_recycle_bin:
                        ok, msg = send_to_recycle_bin(tpath)
                        mode_str = "recycle_bin"
                    else:
                        ok, msg = self._permanent_delete(tpath)
                        mode_str = "permanent"

                    if ok:
                        removed_entries.append(
                            {
                                "path": tpath,
                                "rel_path": item["rel_path"],
                                "group_id": gid,
                                "size_bytes": item["size_bytes"],
                                "mode": mode_str,
                                "status": "removed",
                                "detail": msg,
                            }
                        )
                        freed_bytes += item["size_bytes"]
                    else:
                        errors.append({"path": tpath, "error": msg})

        log_record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "dry_run": dry_run,
            "use_recycle_bin": use_recycle_bin,
            "confirmed": confirmed,
            "selected_groups": sorted(selected_set),
            "removed_count": len(removed_entries),
            "freed_bytes": freed_bytes,
            "freed_formatted": format_bytes(freed_bytes),
            "on_google_drive": scan["on_google_drive"],
            "drive_trash_notice": scan["drive_trash_notice"],
            "removed_paths": [e["path"] for e in removed_entries],
            "entries": removed_entries,
            "errors": errors,
        }
        self._append_cleanup_log(log_record)

        action_word = "Dry run simulated removing" if dry_run else (
            "Moved to Recycle Bin:" if use_recycle_bin else "Deleted:"
        )
        msg = f"{action_word} {len(removed_entries)} item(s) ({format_bytes(freed_bytes)})."
        if scan["drive_trash_notice"]:
            msg += f" {scan['drive_trash_notice']}"

        return {
            "success": True,
            "dry_run": dry_run,
            "use_recycle_bin": use_recycle_bin,
            "removed_count": len(removed_entries),
            "freed_bytes": freed_bytes,
            "freed_mb": round(freed_bytes / (1024.0 * 1024.0), 2),
            "freed_formatted": format_bytes(freed_bytes),
            "on_google_drive": scan["on_google_drive"],
            "drive_trash_notice": scan["drive_trash_notice"],
            "removed_paths": [e["path"] for e in removed_entries],
            "entries": removed_entries,
            "errors": errors,
            "log_path": self.log_path,
            "message": msg,
        }

    def _permanent_delete(self, path: str) -> Tuple[bool, str]:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return True, "Permanently deleted"
        except Exception as exc:
            return False, str(exc)

    def _append_cleanup_log(self, record: Dict[str, Any]) -> None:
        history: List[Dict[str, Any]] = []
        if os.path.isfile(self.log_path):
            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if isinstance(existing, list):
                    history = existing
                elif isinstance(existing, dict) and isinstance(existing.get("runs"), list):
                    history = existing["runs"]
            except Exception:
                history = []

        history.append(record)
        payload = {
            "updated_at": record["timestamp"],
            "last_run": record,
            "runs": history[-50:],
        }
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    def _dir_size(self, path: str) -> int:
        total = 0
        for root, _, files in os.walk(path):
            for fn in files:
                fp = os.path.join(root, fn)
                try:
                    total += os.path.getsize(fp)
                except Exception:
                    pass
        return total

    def _sha256_file(self, path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _rel_display(self, path: str) -> str:
        norm_p = _norm(path)
        norm_base = _norm(self.base_dir)
        norm_local = _norm(self.local_data_dir)
        if norm_p.startswith(norm_base + os.sep):
            return os.path.relpath(path, self.base_dir).replace("\\", "/")
        if norm_p.startswith(norm_local + os.sep):
            return "C:/LionReel/" + os.path.relpath(path, self.local_data_dir).replace("\\", "/")
        return path.replace("\\", "/")
