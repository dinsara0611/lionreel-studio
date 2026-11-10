"""Deleting a video removes every file that belongs to it; Delete all and leftover clean-up miss nothing."""
import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import web_server as ws

LIVE = "lionreel_cat_20261110_090000_aaaa1111"
GONE = "lionreel_cat_20261026_092742_7caa7b9e"
FAILED = "lionreel_cat_20261106_220242_7fdade37"


def touch(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    fin, out, work = tmp_path / "finished", tmp_path / "output", tmp_path / "work"
    for d in (fin, out, work):
        d.mkdir()
    monkeypatch.setattr(ws, "FINISHED_DIR", str(fin))
    monkeypatch.setattr(ws, "OUTPUT_DIR", str(out))
    monkeypatch.setattr(ws, "WORK_DIR", str(work))
    monkeypatch.setattr(ws, "JOB_RESULT_FILE", str(tmp_path / "job_result.json"))
    monkeypatch.setattr(ws, "RUNNING_PROCESS", None)
    monkeypatch.setattr(ws, "_active_job_id", lambda: None)
    trashed = []

    def fake_trash(p):
        trashed.append(os.path.relpath(p, tmp_path).replace("\\", "/"))
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        return True
    monkeypatch.setattr(ws, "move_to_trash", fake_trash)

    # A video still in the library: its files must survive leftover clean-up
    touch(str(out / LIVE / f"{LIVE}.mp4"))
    touch(str(out / LIVE / "mapping.json"), json.dumps({"job_id": LIVE}))
    for suffix in ("_report.html", "_report.json", "_report.pdf", "_timings.json"):
        touch(str(fin / f"{LIVE}{suffix}"))
    touch(str(fin / f"{LIVE}_thumbnails" / "t1.jpg"))
    # A video that was deleted outside the app, and a failed job: only reports remain
    for stem in (GONE, FAILED):
        for suffix in ("_report.html", "_report.json", "_report.pdf", "_timings.json"):
            touch(str(fin / f"{stem}{suffix}"))
    touch(str(fin / f"{GONE}_thumbnails" / "t1.jpg"))
    touch(str(out / GONE / f"{GONE}_mapping.json"))
    # Loose copies the engine used to write, from a job whose video is gone
    for name in ("mapping.json", "metadata.json", "qa_report.json", "planner_decision.json"):
        touch(str(fin / name), json.dumps({"job_id": GONE}))
    # Not a job file: never touched
    touch(str(fin / "notes.txt"))
    return tmp_path, trashed


def names(items):
    return sorted(f"{i['where']}/{i['name']}" for i in items)


def test_leftovers_are_files_of_videos_that_are_gone(lib):
    got = names(ws.find_leftover_files())
    assert f"output/{GONE}/" in got
    assert f"finished/{GONE}_thumbnails" in got
    assert f"finished/{FAILED}_report.pdf" in got and f"finished/{GONE}_timings.json" in got
    assert {"finished/mapping.json", "finished/qa_report.json", "finished/planner_decision.json"} <= set(got)
    assert not any(LIVE in n for n in got)
    assert "finished/notes.txt" not in got


def test_loose_files_of_a_live_video_are_kept(lib):
    tmp, _ = lib
    touch(str(tmp / "finished" / "mapping.json"), json.dumps({"job_id": LIVE}))
    assert "finished/mapping.json" not in names(ws.find_leftover_files())


def test_running_job_is_never_a_leftover(lib, monkeypatch):
    monkeypatch.setattr(ws, "_active_job_id", lambda: FAILED)
    assert not any(FAILED in n for n in names(ws.find_leftover_files()))


def test_clean_up_moves_leftovers_and_keeps_the_library(lib):
    tmp, trashed = lib
    moved, failed = ws.clean_leftover_files()
    assert not failed and moved
    left = sorted(os.listdir(tmp / "finished"))
    assert left == sorted([f"{LIVE}_report.html", f"{LIVE}_report.json", f"{LIVE}_report.pdf",
                           f"{LIVE}_timings.json", f"{LIVE}_thumbnails", "notes.txt"])
    assert os.listdir(tmp / "output") == [LIVE]
    assert ws.find_leftover_files() == []


def test_deleting_a_video_takes_its_thumbnail_folder_too(lib, monkeypatch):
    tmp, trashed = lib
    monkeypatch.setattr("clip_ledger.ClipLedger", lambda *a, **k: type("L", (), {"delete_output": lambda self, s: True})())
    ok, files, err = ws.delete_compilation_files(f"{LIVE}.mp4")
    assert ok, err
    assert f"finished/{LIVE}_thumbnails/" in files and f"output/{LIVE}/" in files
    assert not any(LIVE in f for f in os.listdir(tmp / "finished"))


def test_delete_all_leaves_nothing_but_unrelated_files(lib, monkeypatch):
    tmp, trashed = lib
    released = []
    monkeypatch.setattr("clip_ledger.ClipLedger", lambda *a, **k: type("L", (), {"delete_output": lambda self, s: released.append(s)})())
    deleted, failed = ws.delete_all_videos()
    assert not failed
    assert os.listdir(tmp / "finished") == ["notes.txt"]
    assert os.listdir(tmp / "output") == []
    assert released == [LIVE]
    assert ws.existing_video_stems() == set()
