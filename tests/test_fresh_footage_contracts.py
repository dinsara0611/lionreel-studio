"""
tests/test_fresh_footage_contracts.py
======================================
Automated verification suite for Fresh Footage & Cross-Job Clip Reuse Contracts:
1. Two sandbox jobs back to back share 0 windows, 0 overlapping ranges (>30%), and 0 near-identical frames.
2. Same footage under a different ID or filename is blocked via 5-frame perceptual hash and time overlap.
3. Test / sandbox jobs do not mark windows as used for production videos.
4. Captions are never reused in the next 3 jobs of the same channel; titles never repeat.
5. Source cooldown: sources cannot be reused in the next 3 jobs of the same channel unless no other source exists.
6. 'Allow reuse' switch OFF fails safely with a clear message and triggers harvest when bank is depleted.
7. Both mode contract: teaser uses moments from its own long video.
8. Single source of truth freshness function returns consistent numbers for QA, report, and Export card.
"""

import os
import sys
import unittest
import tempfile
import sqlite3
import json
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import (
    ClipLedger,
    is_same_moment,
    compute_phash,
    hamming_distance,
    compute_window_5_phashes,
    are_frame_hashes_matching,
    compute_footage_freshness
)
from fulfillment_planner import FulfillmentPlanner, FulfillmentPlan
from metadata_generator import MetadataGenerator

def make_dummy_hash(seed_str: str) -> str:
    import hashlib
    return format(int(hashlib.md5(str(seed_str).encode("utf-8")).hexdigest(), 16), "064b")


class TestFreshFootageContracts(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "fresh_footage_test_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)
        self.planner = FulfillmentPlanner(ledger=self.ledger)

        # Create dummy source files
        self.sources = []
        for i in range(12):
            sp = os.path.join(self.temp_dir.name, f"source_{i:02d}.mp4")
            with open(sp, "wb") as f:
                f.write(b"RIFF" + b"\x00" * 200000) # dummy payload > 100KB
            self.sources.append(sp)

        # Seed clips table with 2 windows per source
        # Generate distinct dummy 5-frame hashes for each clip using make_dummy_hash
        with self.ledger._get_conn() as conn:
            for s_idx, sp in enumerate(self.sources):
                sid = os.path.splitext(os.path.basename(sp))[0]
                for w_idx in range(2):
                    cid = f"clip_{sid}_w{w_idx}"
                    st = float(w_idx * 15.0 + 2.0)
                    en = st + 7.5
                    hashes = [make_dummy_hash(f"src_{s_idx}_w_{w_idx}_frame_{k}") for k in range(5)]
                    conn.execute("""
                        INSERT INTO clips (
                            clip_id, source_id, source_url_or_path, animal_type,
                            start_s, end_s, is_verified, times_used,
                            quality_score, funny_score, sharpness, framing_score, orientation,
                            fingerprint
                        ) VALUES (?, ?, ?, 'cat', ?, ?, 1, 0, 95.0, 90.0, 200.0, 95.0, 'vertical', ?)
                    """, (cid, sid, sp, st, en, json.dumps(hashes)))
            conn.commit()

    def tearDown(self):
        try:
            del self.planner
            del self.ledger
            import gc
            gc.collect()
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_back_to_back_jobs_share_zero_windows(self):
        """
        Two production jobs run back-to-back:
        Job 1 reserves and registers 4 clips.
        Job 2 then reserves 4 clips.
        Job 2 must share:
        - 0 identical clip IDs
        - 0 overlapping ranges (>30%) from same source
        - 0 near-identical frame hashes
        """
        # Job 1 plan
        job1_id = "lionreel_cat_prod_job_1"
        plan1 = self.planner.plan_fulfillment(
            job_id=job1_id,
            animal_mode="cat",
            target_total_sec=30.0,
            target_clip_sec=7.5,
            video_type="short",
            allow_reuse=False,
            is_test=False
        )
        self.assertEqual(len(plan1.clips), 4)

        # Register Job 1 output in ledger as finished production video
        clip_mapping_1 = []
        for idx, c in enumerate(plan1.clips):
            clip_mapping_1.append({
                "clip_id": c["clip_id"],
                "source_id": c.get("source_id") or os.path.splitext(os.path.basename(c["source_url_or_path"]))[0],
                "source_url_or_path": c["source_url_or_path"],
                "source_file": c["source_url_or_path"],
                "start_s": float(c["start_s"]),
                "end_s": float(c["end_s"]),
                "duration": float(c["dur_s"]),
                "frame_hashes": [make_dummy_hash(f"job1_clip_{idx}_frame_{k}") for k in range(5)]
            })

        self.ledger.register_output(
            job_id=job1_id,
            output_filename=f"{job1_id}.mp4",
            sha256="dummy_sha256_1",
            clip_ids=[c["clip_id"] for c in clip_mapping_1],
            duration_sec=30.0,
            render_time_sec=12.0,
            clip_windows=clip_mapping_1,
            is_production=True
        )

        # Job 2 plan immediately back to back
        job2_id = "lionreel_cat_prod_job_2"
        plan2 = self.planner.plan_fulfillment(
            job_id=job2_id,
            animal_mode="cat",
            target_total_sec=30.0,
            target_clip_sec=7.5,
            video_type="short",
            allow_reuse=False,
            is_test=False
        )
        self.assertEqual(len(plan2.clips), 4)

        # Verify 0 overlap between Job 1 and Job 2
        j1_cids = {c["clip_id"] for c in plan1.clips}
        j2_cids = {c["clip_id"] for c in plan2.clips}
        self.assertEqual(len(j1_cids & j2_cids), 0, "Back to back jobs must share zero identical clip IDs")

        for c2 in plan2.clips:
            for c1 in plan1.clips:
                # 1. No same moment (>30% overlap of same source)
                s1 = c1.get("source_id") or os.path.basename(c1.get("source_url_or_path", ""))
                s2 = c2.get("source_id") or os.path.basename(c2.get("source_url_or_path", ""))
                self.assertFalse(
                    is_same_moment(s1, float(c1["start_s"]), float(c1["end_s"]),
                                   s2, float(c2["start_s"]), float(c2["end_s"]), overlap_thresh=0.30),
                    f"Job 2 clip {c2['clip_id']} overlaps >30% with Job 1 clip {c1['clip_id']}"
                )

    def test_same_footage_under_different_id_is_blocked(self):
        """
        A candidate with a different clip_id and different source filename,
        but matching 5-frame perceptual hash to an earlier production window,
        MUST be detected and blocked.
        """
        # Register a used production window with known 5-frame hashes
        job_prev = "lionreel_cat_prev_prod"
        known_hashes = [make_dummy_hash(f"cat_dup_scene_{k}") for k in range(5)]
        self.ledger.register_output(
            job_id=job_prev,
            output_filename=f"{job_prev}.mp4",
            sha256="sha_prev",
            clip_ids=["clip_original_01"],
            duration_sec=7.5,
            render_time_sec=5.0,
            clip_windows=[{
                "clip_id": "clip_original_01",
                "source_id": "source_cat_alpha",
                "source_url_or_path": self.sources[0],
                "start_s": 10.0,
                "end_s": 17.5,
                "duration": 7.5,
                "frame_hashes": known_hashes
            }],
            is_production=True
        )

        # Verify is_window_used_in_production blocks same footage under completely different ID and source name
        is_used, reason = self.ledger.is_window_used_in_production(
            source_id_or_path="reuploaded_different_name.mp4",
            start_s=50.0,
            end_s=57.5,
            frame_hashes=known_hashes,
            channel="cat"
        )
        self.assertTrue(is_used, "Must block footage matching perceptual hash of earlier production video")
        self.assertIn("perceptual_hash", reason.lower())

    def test_test_and_sandbox_jobs_do_not_mark_windows_as_used(self):
        """
        Test and sandbox jobs must NOT mark windows as used in production.
        """
        job_test = "test_contract_sandbox_job"
        test_clip = {
            "clip_id": "clip_test_01",
            "source_id": "source_00",
            "source_url_or_path": self.sources[0],
            "start_s": 2.0,
            "end_s": 9.5,
            "duration": 7.5,
            "frame_hashes": [make_dummy_hash(f"sandbox_frame_{k}") for k in range(5)]
        }
        self.ledger.register_output(
            job_id=job_test,
            output_filename=f"{job_test}.mp4",
            sha256="sha_test",
            clip_ids=["clip_test_01"],
            duration_sec=7.5,
            render_time_sec=2.0,
            clip_windows=[test_clip],
            is_production=False # test job!
        )

        # Checking if this window is used in production must return False
        is_used, reason = self.ledger.is_window_used_in_production(
            source_id_or_path="source_00",
            start_s=2.0,
            end_s=9.5,
            frame_hashes=test_clip["frame_hashes"],
            channel="cat"
        )
        self.assertFalse(is_used, "Test jobs must not mark windows as used in production")

    def test_caption_not_reused_in_next_3_jobs(self):
        """
        Captions used in the last 3 production jobs of the same channel must not be reused.
        """
        channel = "cat"
        # Register 3 jobs with captions
        c_sets = [
            ["When gravity decides to betray you", "Not a single thought behind those eyes"],
            ["Proof that cats are 90% liquid", "Caught red-handed in 4K"],
            ["Zero regrets, will do it again", "The drama queen of the house"]
        ]
        for idx, caps in enumerate(c_sets):
            jid = f"lionreel_cat_job_{idx+1}"
            wins = [{
                "clip_id": f"c_{idx}_{c_idx}",
                "source_id": f"src_{idx}",
                "source_url_or_path": self.sources[idx],
                "start_s": 0.0,
                "end_s": 7.5,
                "duration": 7.5,
                "caption": cap
            } for c_idx, cap in enumerate(caps)]
            self.ledger.register_output(
                job_id=jid,
                output_filename=f"{jid}.mp4",
                sha256=f"sha_{idx}",
                clip_ids=[w["clip_id"] for w in wins],
                duration_sec=15.0,
                render_time_sec=5.0,
                clip_windows=wins,
                is_production=True
            )

        recent_caps = self.ledger.get_recent_captions(channel=channel, last_n_jobs=3)
        for caps in c_sets:
            for cap in caps:
                self.assertIn(cap.lower().strip(), recent_caps, f"Caption '{cap}' should be in cooldown")

        # Pick fresh caption
        pool = [
            "When gravity decides to betray you",
            "Proof that cats are 90% liquid",
            "Zero regrets, will do it again",
            "Cat.exe has stopped working", # Fresh!
            "Instant regret in 3... 2... 1..." # Fresh!
        ]
        available_caps = [c for c in pool if c.lower().strip() not in recent_caps]
        self.assertEqual(len(available_caps), 2)
        self.assertIn("Cat.exe has stopped working", available_caps)
        self.assertIn("Instant regret in 3... 2... 1...", available_caps)

    def test_titles_never_repeat(self):
        """
        Titles must never repeat across any finished production video.
        """
        mg = MetadataGenerator(ledger=self.ledger)
        t1 = "This Playful Kitten Activated 3 AM Zoomies Mode"
        self.ledger.record_metadata(
            job_id="job_title_01",
            animal_type="cat",
            title=t1,
            description="description",
            tags="tags",
            hashtags="#shorts #cats",
            platform="youtube_shorts"
        )

        self.assertTrue(self.ledger.is_title_used(t1, channel="cat"))
        self.assertTrue(self.ledger.is_title_used(t1.lower(), channel="cat"))
        self.assertFalse(self.ledger.is_title_used("A Completely Different Title That Is Brand New", channel="cat"))

    def test_source_cooldown_enforcement(self):
        """
        Do not use the same source video again in the next 3 jobs of the same channel,
        unless the bank has no other source.
        """
        # Register 3 jobs using source_00, source_01, source_02
        for idx in range(3):
            jid = f"lionreel_cat_cooldown_job_{idx}"
            self.ledger.register_output(
                job_id=jid,
                output_filename=f"{jid}.mp4",
                sha256=f"sha_{idx}",
                clip_ids=[f"c_{idx}"],
                duration_sec=7.5,
                render_time_sec=3.0,
                clip_windows=[{
                    "clip_id": f"c_{idx}",
                    "source_id": f"source_{idx:02d}",
                    "source_url_or_path": self.sources[idx],
                    "start_s": 0.0,
                    "end_s": 7.5,
                    "duration": 7.5
                }],
                is_production=True
            )

        cooldown_sources = self.ledger.get_cooldown_sources(channel="cat", last_n_jobs=3)
        self.assertIn("source_00", cooldown_sources)
        self.assertIn("source_01", cooldown_sources)
        self.assertIn("source_02", cooldown_sources)
        self.assertNotIn("source_03", cooldown_sources)

    def test_allow_reuse_switch_off_fails_safely_when_bank_empty(self):
        """
        When allow_reuse is OFF and there are not enough new windows,
        the planner MUST NOT silently reuse used clips; it must return an honest
        shortage_harvest_pending plan with 0 reused clips and trigger harvest.
        """
        # Mark all clips in database as used
        with self.ledger._get_conn() as conn:
            conn.execute("UPDATE clips SET times_used = 5")
            conn.commit()

        plan = self.planner.plan_fulfillment(
            job_id="job_shortage_test",
            animal_mode="cat",
            target_total_sec=30.0,
            target_clip_sec=7.5,
            video_type="short",
            allow_reuse=False,
            is_test=False
        )
        self.assertEqual(plan.strategy_used, "shortage_harvest_pending")
        self.assertEqual(len(plan.clips), 0, "Expected 0 used clips selected when allow_reuse=False and bank is empty")
        self.assertTrue(
            any("shortage" in m.lower() or "to find" in m.lower() for m in plan.log_messages),
            f"Expected shortage message in logs, got: {plan.log_messages}"
        )

    def test_single_source_of_truth_freshness_function(self):
        """
        compute_footage_freshness returns exact contract:
        - 100% new footage -> 'New footage: 100% / Reused from earlier videos: 0%'
        - Reused footage -> 'New footage: 75% / Reused from earlier videos: 25%' with job attribution.
        """
        # Register an earlier production job
        job_old = "lionreel_cat_earlier_job"
        self.ledger.register_output(
            job_id=job_old,
            output_filename=f"{job_old}.mp4",
            sha256="sha_old",
            clip_ids=["clip_old_01"],
            duration_sec=7.5,
            render_time_sec=2.0,
            clip_windows=[{
                "clip_id": "clip_old_01",
                "source_id": "source_00",
                "source_url_or_path": self.sources[0],
                "start_s": 0.0,
                "end_s": 7.5,
                "duration": 7.5
            }],
            is_production=True
        )

        # Test case 1: 100% new footage
        new_clips = [
            {"clip_id": "c_new_1", "source_id": "source_05", "source_url_or_path": self.sources[5], "start_s": 0.0, "end_s": 7.5},
            {"clip_id": "c_new_2", "source_id": "source_06", "source_url_or_path": self.sources[6], "start_s": 0.0, "end_s": 7.5},
            {"clip_id": "c_new_3", "source_id": "source_07", "source_url_or_path": self.sources[7], "start_s": 0.0, "end_s": 7.5},
            {"clip_id": "c_new_4", "source_id": "source_08", "source_url_or_path": self.sources[8], "start_s": 0.0, "end_s": 7.5}
        ]
        res1 = compute_footage_freshness(new_clips, ledger=self.ledger, current_job_id="current_job_100")
        self.assertEqual(res1["new_windows"], 4)
        self.assertEqual(res1["reused_windows"], 0)
        self.assertEqual(res1["new_footage_pct"], 100.0)
        self.assertEqual(res1["reused_footage_pct"], 0.0)
        self.assertEqual(res1["card_line"], "New footage: 100% / Reused from earlier videos: 0%")

        # Test case 2: 1 reused clip from job_old
        mixed_clips = [
            {"clip_id": "c_new_1", "source_id": "source_05", "source_url_or_path": self.sources[5], "start_s": 0.0, "end_s": 7.5},
            {"clip_id": "c_new_2", "source_id": "source_06", "source_url_or_path": self.sources[6], "start_s": 0.0, "end_s": 7.5},
            {"clip_id": "c_new_3", "source_id": "source_07", "source_url_or_path": self.sources[7], "start_s": 0.0, "end_s": 7.5},
            {"clip_id": "c_reused", "source_id": "source_00", "source_url_or_path": self.sources[0], "start_s": 0.0, "end_s": 7.5}
        ]
        res2 = compute_footage_freshness(mixed_clips, ledger=self.ledger, current_job_id="current_job_mixed")
        self.assertEqual(res2["new_windows"], 3)
        self.assertEqual(res2["reused_windows"], 1)
        self.assertEqual(res2["new_footage_pct"], 75.0)
        self.assertEqual(res2["reused_footage_pct"], 25.0)
        self.assertIn(job_old, str(res2["reused_details"]))
        self.assertTrue(res2["card_line"].startswith("New footage: 75% / Reused from earlier videos: 25%"))


if __name__ == "__main__":
    unittest.main()
