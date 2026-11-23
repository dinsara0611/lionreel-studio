"""A job waiting for footage restarts by itself once the bank holds the clips it needs."""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import web_server as ws
from clip_ledger import ClipLedger


def setup(tmp_path, monkeypatch, n_sources, per_source=1, cfg_clips=4):
    monkeypatch.setattr(ws, "WORK_DIR", str(tmp_path / "work"))
    job = "lionreel_cat_20261123_090733_7c1655b1"
    (tmp_path / "work" / job).mkdir(parents=True)
    (tmp_path / "work" / job / "job_config.json").write_text(json.dumps(
        {"job_id": job, "clips": cfg_clips, "animal_mode": "cat", "allow_reuse": False, "layout": "auto"}))
    ledger = ClipLedger(db_path=str(tmp_path / "ledger.db"))
    with sqlite3.connect(ledger.db_path) as conn:
        for s in range(n_sources):
            p = tmp_path / f"cache_s{s}.mp4"
            p.write_bytes(b"x")
            for k in range(per_source):
                conn.execute("INSERT INTO clips (clip_id, source_id, source_url_or_path, start_s, end_s, is_verified, times_used, animal_type, status) "
                             "VALUES (?, ?, ?, ?, ?, 1, 0, 'cat', 'verified')", (f"c{s}_{k}", f"cache_s{s}", str(p), 10 + k * 60, 17.5 + k * 60))
        conn.commit()
    return job, ledger


def test_waits_while_the_bank_is_short(tmp_path, monkeypatch):
    job, ledger = setup(tmp_path, monkeypatch, n_sources=1, per_source=3)
    rd = ws.auto_resume_readiness(job, ledger=ledger)
    assert rd["ready"] is False and rd["need"] == 4


def test_resumes_once_enough_fresh_clips_exist(tmp_path, monkeypatch):
    job, ledger = setup(tmp_path, monkeypatch, n_sources=2, per_source=2)
    rd = ws.auto_resume_readiness(job, ledger=ledger)
    assert rd["ready"] is True and rd["have"] == 4 and rd["sources_needed"] == 2


def test_never_restarts_with_guessed_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "WORK_DIR", str(tmp_path / "work"))
    assert ws.auto_resume_readiness("missing_job", ledger=object())["ready"] is False


def test_watcher_no_longer_calls_the_missing_loader():
    src = open(ws.__file__, encoding="utf-8").read()
    assert "job_options.load_job_config" not in src
