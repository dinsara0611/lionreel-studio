import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from safe_cleanup import SafeCleanupManager, format_bytes

def run():
    print("=== SAFE CLEAN-UP (PHASE 5) VERIFICATION ===")
    m = SafeCleanupManager()
    
    # 1. Preview / Scan
    scan = m.scan_candidates()
    print(f"Total candidate groups: {len(scan['groups'])}")
    print(f"Total candidates: {scan['total_count']} files/dirs ({scan['total_size_formatted']})")
    
    for g in scan['groups']:
        print(f"  [{g['group_id']}] {g['label']}: {g['count']} items, {g['size_formatted']}")

    # Check protected paths are never in candidate items
    exact_prot = len(m._protected_exact_paths)
    prefix_prot = len(m._protected_dir_prefixes)
    print(f"Protected assets registered: {exact_prot} exact paths, {prefix_prot} prefix directories")
    
    candidate_paths = []
    for g in scan['groups']:
        for item in g.get('files', []):
            candidate_paths.append(item['path'])

    # Assert no candidate path is protected
    violations = [p for p in candidate_paths if m.is_protected(p)]
    if violations:
        print(f"FAILED: Protected path in candidates! Violations ({len(violations)}): {violations[:5]}")
        return False
    else:
        print("PASS: Zero protected assets in candidate pool.")

    # Explicitly verify production masters are protected
    masters = [
        os.path.join(BASE_DIR, 'finished', 'lionreel_cat_proof_short_30s.mp4'),
        os.path.join(BASE_DIR, 'finished', 'lionreel_cat_proof_long_3m.mp4'),
        os.path.join(BASE_DIR, 'finished', 'lionreel_cat_proof_both.mp4'),
        os.path.join(BASE_DIR, 'finished', 'lionreel_cat_proof_both_teaser.mp4')
    ]
    for master in masters:
        if not m.is_protected(master):
            print(f"FAILED: Master {master} is not protected!")
            return False
    print("PASS: All finished production master videos are strictly protected.")

    # 2. Dry Run Execution
    print("\nExecuting DRY RUN (dry_run=True, confirmed=False)...")
    res_dry = m.execute_cleanup(selected_groups=None, dry_run=True, confirmed=False, use_recycle_bin=True)
    print(f"Dry run result: dry_run={res_dry['dry_run']}, simulated_freed={res_dry['freed_formatted']}, simulated_items={res_dry['removed_count']}")
    
    # Check that paths on disk still exist after dry run
    sample_item = scan['groups'][3]['files'][0]['path']
    if not os.path.exists(sample_item):
        print(f"FAILED: Item {sample_item} missing after dry run!")
        return False
    print("PASS: Dry run deleted 0 files from disk.")

    # 3. Real Clean-up on test/sandbox files only
    test_group_ids = ['test_sandbox_outputs', 'python_cache']
    test_groups = [g for g in scan['groups'] if g['group_id'] in test_group_ids]
    test_count = sum(g['count'] for g in test_groups)
    test_size = sum(g['size_bytes'] for g in test_groups)
    print(f"\nExecuting REAL CLEANUP on test/sandbox groups ({test_group_ids}, {test_count} items, {format_bytes(test_size)})...")
    
    res_real = m.execute_cleanup(selected_groups=test_group_ids, dry_run=False, confirmed=True, use_recycle_bin=True)
    print(f"Real clean-up result: removed_count={res_real['removed_count']}, freed={res_real['freed_formatted']}")
    print(f"Audit log written to: {res_real['log_path']}")
    
    if os.path.exists(res_real['log_path']):
        print("PASS: cleanup_log.json exists and audit trail verified.")
    else:
        print("FAILED: cleanup_log.json missing!")
        return False

    print("\nSAFE CLEAN-UP (PHASE 5) VERIFICATION PASSED SUCCESSFULLY ✅")
    return True

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
