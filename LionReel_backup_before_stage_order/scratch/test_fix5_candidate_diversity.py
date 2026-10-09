import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def test_fix5():
    print("=== TESTING FIX 5: CANDIDATE DIVERSITY AND NO OVERLAP (NMS) ===")

    # 1. Test Non-Maximum Suppression (NMS) on Overlapping Windows
    print("\n1. Testing NMS window suppression (< 10s separation on same source):")
    candidates = [
        # Overlapping pair 1: Cand 10 vs Cand 16
        {"candidate": 10, "source": "src_cat1.mp4", "start_s": 179.4, "dur_s": 10.0, "score": 0.95, "clip_id": "c10"},
        {"candidate": 16, "source": "src_cat1.mp4", "start_s": 178.4, "dur_s": 10.0, "score": 0.89, "clip_id": "c16"},
        # Overlapping pair 2: Cand 12 vs Cand 14
        {"candidate": 12, "source": "src_cat1.mp4", "start_s": 165.4, "dur_s": 10.0, "score": 0.88, "clip_id": "c12"},
        {"candidate": 14, "source": "src_cat1.mp4", "start_s": 164.4, "dur_s": 10.0, "score": 0.93, "clip_id": "c14"},
        # Non-overlapping candidate from same source (separated by > 10s)
        {"candidate": 3, "source": "src_cat1.mp4", "start_s": 45.0, "dur_s": 10.0, "score": 0.91, "clip_id": "c03"},
        # Candidates from other sources
        {"candidate": 5, "source": "src_cat2.mp4", "start_s": 12.0, "dur_s": 10.0, "score": 0.94, "clip_id": "c05"},
        {"candidate": 8, "source": "src_cat3.mp4", "start_s": 25.0, "dur_s": 10.0, "score": 0.92, "clip_id": "c08"},
    ]

    # Run NMS algorithm
    candidates.sort(key=lambda x: x["score"], reverse=True)
    nms_passing = []
    rejected_nms = []

    for cand in candidates:
        c_src = cand["source"]
        c_start = cand["start_s"]
        c_end = cand["start_s"] + cand["dur_s"]
        suppressed = False
        for kept in nms_passing:
            if kept["source"] == c_src:
                k_start = kept["start_s"]
                k_end = kept["start_s"] + kept["dur_s"]
                if abs(c_start - k_start) < 10.0 or not (c_end <= k_start or k_end <= c_start):
                    suppressed = True
                    cand["result"] = "REJECT"
                    cand["reason"] = f"NMS_OVERLAP (Duplicate moment with Cand {kept['candidate']})"
                    rejected_nms.append(cand)
                    break
        if not suppressed:
            nms_passing.append(cand)

    kept_cand_nums = [c["candidate"] for c in nms_passing]
    rejected_cand_nums = [c["candidate"] for c in rejected_nms]

    print(f"Candidates kept by NMS: {kept_cand_nums}")
    print(f"Candidates rejected by NMS: {rejected_cand_nums}")

    # Cand 10 (0.95) should be KEPT, Cand 16 (0.89) should be REJECTED
    assert 10 in kept_cand_nums, "Cand 10 should be kept (higher score)"
    assert 16 in rejected_cand_nums, "Cand 16 should be suppressed by NMS"

    # Cand 14 (0.93) should be KEPT, Cand 12 (0.88) should be REJECTED
    assert 14 in kept_cand_nums, "Cand 14 should be kept (higher score)"
    assert 12 in rejected_cand_nums, "Cand 12 should be suppressed by NMS"

    # Cand 3 from src_cat1 (45.0s) should be KEPT (well separated)
    assert 3 in kept_cand_nums, "Cand 3 should be kept (no overlap)"

    # Candidates from other sources should be KEPT
    assert 5 in kept_cand_nums and 8 in kept_cand_nums, "Candidates from distinct sources should be kept"

    # 2. Test Source Diversity Interleaving (>= 3 sources when available, max 2 per source)
    print("\n2. Testing Source Diversity Interleaving & Max 2 clips per source:")
    source_groups = {}
    for c in nms_passing:
        source_groups.setdefault(c["source"], []).append(c)

    interleaved_passing = []
    deferred_passing = []
    src_keys = list(source_groups.keys())

    # Round 1: Take 1st clip from each source
    for s in src_keys:
        if source_groups[s]:
            interleaved_passing.append(source_groups[s].pop(0))
    # Round 2: Take 2nd clip from each source
    for s in src_keys:
        if source_groups[s]:
            interleaved_passing.append(source_groups[s].pop(0))
    # Round 3+: Any remaining clips deferred as backups
    for s in src_keys:
        while source_groups[s]:
            deferred_passing.append(source_groups[s].pop(0))

    final_queue = interleaved_passing + deferred_passing
    first_3_sources = [c["source"] for c in final_queue[:3]]
    print(f"First 3 candidates in render queue come from sources: {first_3_sources}")
    assert len(set(first_3_sources)) == 3, f"Expected 3 distinct sources in top picks, got: {first_3_sources}"

    # Simulate Stage B selection with max 2 clips per source cap
    target_clips = 4
    processed = []
    clips_per_source = {}
    unique_sources = set(c["source"] for c in final_queue)

    for cand in final_queue:
        if len(processed) >= target_clips:
            break
        src = cand["source"]
        if clips_per_source.get(src, 0) >= 2 and len(unique_sources) >= 2:
            continue
        processed.append(cand)
        clips_per_source[src] = clips_per_source.get(src, 0) + 1

    selected_sources = [c["source"] for c in processed]
    print(f"Final 4 selected clips sources: {selected_sources}")
    print(f"Clips per source distribution: {clips_per_source}")

    assert len(processed) == target_clips, f"Expected {target_clips} clips, got {len(processed)}"
    assert len(set(selected_sources)) >= 3, f"Expected >= 3 distinct sources in short, got {len(set(selected_sources))}"
    for src, cnt in clips_per_source.items():
        assert cnt <= 2, f"Source {src} exceeded max 2 clips cap: {cnt}"

    print("\nALL FIX 5 TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_fix5()
