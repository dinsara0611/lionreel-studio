"""Legal sources only: a video whose page showed no Creative Commons licence is never picked."""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import clip_ledger
import lion_automate_v97 as engine
import source_licenses
from bank_enlist import evaluate_candidate_for_enlistment

FREE = "AAAAAAAAAAA"
NO_CC = "BBBBBBBBBBB"
UNCHECKED = "CCCCCCCCCCC"


@pytest.fixture
def records(monkeypatch):
    recs = {}
    monkeypatch.setattr(source_licenses, "load_records", lambda: recs)
    return recs


@pytest.fixture
def bank(tmp_path, records):
    ledger = clip_ledger.ClipLedger(str(tmp_path / "ledger.db"))
    paths = {}
    for vid in (FREE, NO_CC, UNCHECKED):
        p = tmp_path / f"cache_{vid}.mp4"
        p.write_bytes(b"x" * 2048)
        paths[vid] = str(p)
        for i, start in enumerate((10.0, 100.0)):
            ledger.add_clip(clip_id=f"c_{vid}_{i}", source_id=f"cache_{vid}", source_url_or_path=str(p),
                            license_name="Creative Commons Attribution license", start_s=start, end_s=start + 7.5,
                            frame_phashes=[], is_verified=1, sharpness=300.0, framing_score=0.9, animal_type="cat")
    # Licence records arrive after the rows, as they did for the real bank
    records[FREE] = {"status": source_licenses.VERIFIED}
    records[NO_CC] = {"status": source_licenses.NOT_SHOWN}
    return ledger, paths


def test_no_licence_source_is_blocked(bank):
    ledger, paths = bank
    assert ledger.is_blocked_source(paths[NO_CC]) is True
    assert ledger.is_blocked_source(paths[FREE]) is False
    assert ledger.is_blocked_source(paths[UNCHECKED]) is False


def test_count_function_does_not_offer_no_licence_clips(bank):
    ledger, _ = bank
    w = ledger.get_ledger_counts("cat", include_windows=True)["windows"]
    usable = {r["clip_id"] for r in w["usable_now"] + w["cooldown"]}
    assert usable == {f"c_{FREE}_0", f"c_{FREE}_1", f"c_{UNCHECKED}_0", f"c_{UNCHECKED}_1"}
    assert {r["clip_id"] for r in w["unavailable"]} == {f"c_{NO_CC}_0", f"c_{NO_CC}_1"}


def test_reservation_never_picks_no_licence_clips(bank):
    ledger, _ = bank
    got = ledger.reserve_clips_for_short(count=6, animal_type="cat", short_id="job1", min_required=1)
    assert got and not any(NO_CC in c["clip_id"] for c in got)


def test_verified_clip_list_leaves_them_out(bank):
    ledger, _ = bank
    assert not any(NO_CC in r["clip_id"] for r in ledger.get_verified_clips("cat", limit=50))


def test_bank_growth_skips_them_with_a_reason(bank):
    ledger, paths = bank
    cand = {"clip_id": f"c_{NO_CC}_0", "source_id": f"cache_{NO_CC}", "source_url_or_path": paths[NO_CC], "start_s": 10.0, "end_s": 17.5}
    res = evaluate_candidate_for_enlistment(cand, "job1", "cat", ledger, [])
    assert res["usable"] is False and res["reason"].startswith("NO_CC_LICENCE")


def test_render_refuses_without_rejecting_the_bank_row(bank, tmp_path):
    ledger, paths = bank
    host = SimpleNamespace(reframer=None, ledger=ledger)
    cand = {"clip_id": f"c_{NO_CC}_0", "source_url_or_path": paths[NO_CC], "start_s": 10.0, "end_s": 17.5}
    ok, cid, meta, ret = engine.LionReelV97Pipeline._render_and_gate_candidate(
        host, cand, str(tmp_path), str(tmp_path), 7.5, "smart_crop", "job1", 0)
    assert (ok, cid, meta) == (False, f"c_{NO_CC}_0", None)
    assert ret["reason"] == "NO_CC_LICENCE" and ret["keep_window"] is True
    with ledger._get_conn() as conn:
        row = conn.execute("SELECT is_verified, rejection_reason FROM clips WHERE clip_id = ?", (cid,)).fetchone()
    assert row["is_verified"] == 1 and not row["rejection_reason"]
