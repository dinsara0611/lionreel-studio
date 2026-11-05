"""Full check, Phase 1: stuck jobs, shortage, counts, legal sourcing. Each test fails on the pre-fix code."""
import ast
import os
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def ledger(tmp_path):
    import clip_ledger
    return clip_ledger.ClipLedger(str(tmp_path / "ledger.db"))


def _source(tmp_path, name="cache_AAAAAAAAAAA.mp4"):
    p = tmp_path / name
    p.write_bytes(b"x" * 2048)
    return str(p)


def _add(ledger, cid, src, start, end=None, verified=1, sharp=300.0, rejection=None):
    return ledger.add_clip(clip_id=cid, source_id=os.path.splitext(os.path.basename(src))[0], source_url_or_path=src,
                           license_name="Creative Commons Attribution license", start_s=start, end_s=end or start + 7.5,
                           frame_phashes=[], is_verified=verified, sharpness=sharp, framing_score=0.9,
                           animal_type="cat", rejection_reason=rejection)


def _blocking_calls_without_timeout(path):
    tree = ast.parse(open(path, encoding="utf8").read())
    uses_wrapper = any(isinstance(n, ast.Import) and any(a.name == "timed_subprocess" for a in n.names) for n in ast.walk(tree))
    missing = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) \
                and n.func.value.id == "subprocess" and n.func.attr in ("run", "call", "check_output", "check_call"):
            if not any(k.arg == "timeout" for k in n.keywords):
                missing.append(n.lineno)
    return uses_wrapper, missing


@pytest.mark.parametrize("module", ["lion_automate_v97.py", "harvest_worker.py"])
def test_engine_blocking_calls_all_have_a_timeout(module):
    uses_wrapper, missing = _blocking_calls_without_timeout(os.path.join(BASE, module))
    assert uses_wrapper or not missing, f"{module}: no timeout on lines {missing}"


def test_timed_subprocess_kills_a_hung_child(monkeypatch):
    import timed_subprocess
    monkeypatch.setattr(timed_subprocess, "FALLBACK_TIMEOUT_SEC", 1.0)
    started = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        timed_subprocess.run([sys.executable, "-c", "import time; time.sleep(30)"])
    assert time.time() - started < 8


def test_timed_subprocess_picks_timeout_by_tool():
    import timed_subprocess
    assert timed_subprocess.default_timeout([r"C:\x\ffprobe.exe", "-v"]) == 60.0
    assert timed_subprocess.default_timeout([r"C:\x\ffmpeg-win.exe", "-i"]) == 3600.0


def test_render_function_does_not_shadow_shutil():
    """A local import made shutil an unbound local, silently disabling clip checkpoints."""
    tree = ast.parse(open(os.path.join(BASE, "lion_automate_v97.py"), encoding="utf8").read())
    render = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "render_one_video")
    inner = [n.lineno for n in ast.walk(render) if isinstance(n, ast.Import) and any(a.name == "shutil" for a in n.names)]
    assert not inner, f"local import of shutil at {inner}"


def test_no_undefined_names_in_project():
    out = subprocess.run([sys.executable, "-m", "ruff", "check", "--select", "F821,F823", "--no-cache", "--output-format", "concise",
                          *[f for f in os.listdir(BASE) if f.endswith(".py") and f != "lion_automate.py"]],
                         cwd=BASE, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-800:]


def test_counts_classes_add_up_and_all_callers_agree(ledger, tmp_path):
    src = _source(tmp_path)
    src2 = _source(tmp_path, "cache_BBBBBBBBBBB.mp4")
    _add(ledger, "fresh1", src, 0)
    _add(ledger, "fresh2", src, 100)
    _add(ledger, "fresh3", src2, 40)
    _add(ledger, "unv", src, 200, verified=0)
    _add(ledger, "bad", src2, 300, verified=0, rejection="LOW_SHARPNESS (40.0 < 150.0)")
    c = ledger.get_ledger_counts("cat")
    classes = ("usable_now", "cooldown", "used", "reserved", "unverified", "needs_recheck", "rejected", "unavailable")
    assert sum(c[k] for k in classes) == c["total_rows"] == 5
    assert c["fresh_total"] == 3
    status = ledger.get_pool_status("cat")
    capacity = ledger.get_pool_ready_and_capacity("cat", target_clips=4)
    assert status["verified_clips"] == capacity["ready"] == c["fresh_total"]
    assert ledger.get_pool_unified_counts("cat")["fresh_total"] == c["fresh_total"]


def test_count_does_not_depend_on_job_size(ledger, tmp_path):
    src = _source(tmp_path)
    for i in range(6):
        _add(ledger, f"c{i}", src, i * 40.0)
    assert ledger.get_pool_ready_and_capacity("cat", target_clips=4)["ready"] == \
        ledger.get_pool_ready_and_capacity("cat", target_clips=24)["ready"]


def test_planner_candidates_equal_ledger_fresh_set(ledger, tmp_path):
    from fulfillment_planner import FulfillmentPlanner
    src = _source(tmp_path)
    _add(ledger, "a", src, 0)
    _add(ledger, "b", src, 50)
    planner = FulfillmentPlanner(ledger=ledger, reframer=None)
    got = {c["clip_id"] for c in planner._fetch_verified_candidates("cat")}
    windows = ledger.get_ledger_counts("cat", include_windows=True)["windows"]
    assert got == {w["clip_id"] for w in windows["usable_now"] + windows["cooldown"]}


def test_preflight_line(ledger, tmp_path):
    _add(ledger, "a", _source(tmp_path), 0)
    assert ledger.preflight_line(4).startswith("Need 4, have 1 usable")


def test_rejected_window_blocks_overlap_over_30_percent_under_any_id(ledger, tmp_path):
    src = _source(tmp_path)
    _add(ledger, "rej", src, 10.0, 17.5, verified=0, rejection="LOW_SHARPNESS (40 < 150)")
    _add(ledger, "same_moment_new_id", src, 13.0, 20.5)   # 60% overlap
    _add(ledger, "other_moment", src, 16.5, 24.0)         # 13% overlap
    windows = ledger.get_ledger_counts("cat", include_windows=True)["windows"]
    assert "same_moment_new_id" in {w["clip_id"] for w in windows["rejected"]}
    assert "other_moment" in {w["clip_id"] for w in windows["usable_now"]}


def test_measurement_failure_gets_one_recheck_then_rejected(ledger, tmp_path):
    _add(ledger, "m", _source(tmp_path), 0, verified=0)
    assert ledger.record_candidate_evaluation_failure("m", score=0.0, reason="0.0%")["action"] == "needs_recheck"
    assert ledger.get_ledger_counts("cat")["needs_recheck"] == 1
    assert ledger.record_candidate_evaluation_failure("m", score=0.0, reason="0.0%")["action"] == "rejected"


def test_reserve_wait_does_not_hold_the_write_lock(ledger, tmp_path):
    """Sleeping inside the IMMEDIATE transaction blocked the harvester from saving new clips."""
    src = _source(tmp_path)
    _add(ledger, "only", src, 0)
    errors = []

    def wait_for_clips():
        try:
            ledger.reserve_clips_for_short(count=2, animal_type="cat", short_id="job1", min_required=2, patience_budget_sec=7.0)
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=wait_for_clips, daemon=True)
    t.start()
    time.sleep(1.0)
    conn = sqlite3.connect(ledger.db_path, timeout=0.5, isolation_level=None)
    wrote = 0
    for _ in range(4):
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
            wrote += 1
        except sqlite3.OperationalError:
            pass
        time.sleep(0.8)
    conn.close()
    t.join(12)
    assert wrote >= 3, f"writer got through only {wrote} of 4 times during the wait"


def test_reuse_off_never_falls_back_to_used_moments(ledger, tmp_path):
    src = _source(tmp_path)
    _add(ledger, "fresh", src, 0)
    with ledger._get_conn() as conn:
        conn.execute("INSERT INTO finished_video_windows (job_id, video_index, source_id, source_url_or_path, start_s, end_s, is_production, channel, clip_id) "
                     "VALUES ('oldjob', 1, 'cache_AAAAAAAAAAA', ?, 2.0, 9.5, 1, 'cat', 'older')", (src,))
        conn.commit()
    # 'fresh' overlaps a finished window; with reuse off it must not be offered
    with pytest.raises(RuntimeError):
        ledger.reserve_clips_for_short(count=1, animal_type="cat", short_id="job2", min_required=1, allow_reuse=False)


def test_one_engine_per_job(tmp_path):
    import engine_lock
    ok, _ = engine_lock.acquire_engine_lock("job1", pid=os.getpid(), lock_dir=str(tmp_path), job_dir=str(tmp_path))
    assert ok
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        ok2, msg = engine_lock.acquire_engine_lock("job1", pid=other.pid, lock_dir=str(tmp_path), job_dir=str(tmp_path))
        assert not ok2, msg
    finally:
        other.kill()
        engine_lock.release_engine_lock("job1", pid=os.getpid(), lock_dir=str(tmp_path), job_dir=str(tmp_path))


def test_stop_ends_whole_process_tree_within_5s():
    from watchdog_service import terminate_process_tree
    parent = subprocess.Popen([sys.executable, "-c",
                               "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);time.sleep(60)"])
    time.sleep(1.5)
    started = time.time()
    stopped, msg = terminate_process_tree(parent.pid, timeout_sec=5.0)
    assert stopped, msg
    assert time.time() - started < 5.0
    assert parent.poll() is not None


def test_unknown_licence_text_is_blocked_not_cc():
    from source_utils import normalize_license_name
    assert normalize_license_name("Standard YouTube License")[0] == "Standard YouTube License"
    assert normalize_license_name("all rights reserved")[0] == "BLOCKED"
    assert normalize_license_name("CC BY-SA 4.0 Sharealike")[0] == "CC BY-SA 4.0"
    assert normalize_license_name("Creative Commons")[1] is None


def test_harvest_refuses_video_without_shown_licence(monkeypatch, tmp_path):
    import source_licenses as sl
    assert sl.record_from_info({"id": "x", "license": None, "uploader": "Someone"})["status"] == sl.NOT_SHOWN
    assert sl.record_from_info({"id": "x", "license": "Creative Commons Attribution license (reuse allowed)", "uploader": "Someone"})["status"] == sl.VERIFIED
    src = open(os.path.join(BASE, "harvest_worker.py"), encoding="utf8").read()
    assert 'license_name="Creative Commons CC-BY 4.0"' not in src
    assert "ytsearch" not in src


def test_no_invented_creator_defaults():
    for f in ("lion_automate_v97.py", "metadata_generator.py"):
        assert '"CC Creator"' not in open(os.path.join(BASE, f), encoding="utf8").read(), f
