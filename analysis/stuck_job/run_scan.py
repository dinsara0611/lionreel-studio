import os, sys, glob, subprocess, hashlib, sqlite3, json, time

job_id = 'lionreel_cat_20261013_235102_dc973025'
work_dir = r'C:\LionReel\work\lionreel_cat_20261013_235102_dc973025'
import imageio_ffmpeg
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

print('=== 1.a) INTEGRITY SCAN ===')
def check_file(fpath):
    cmd = [ffmpeg_exe, '-v', 'error', '-xerror', '-i', fpath, '-f', 'null', '-']
    res = subprocess.run(cmd, capture_output=True, text=True)
    err = res.stderr.strip()
    return res.returncode == 0, err

files_to_check = []
for ext in ['*.mp4', '*.mkv', '*.webm']:
    files_to_check.extend(glob.glob(os.path.join(r'G:\My Drive\Cat make\raw', ext)))
    files_to_check.extend(glob.glob(os.path.join(r'C:\LionReel\cache', ext)))
if os.path.exists(os.path.join(work_dir, 'clips')):
    files_to_check.extend(glob.glob(os.path.join(work_dir, 'clips', '*.mp4')))

scan_results = []
for fp in sorted(files_to_check):
    if not os.path.exists(fp) or os.path.getsize(fp) == 0:
        continue
    ok, err = check_file(fp)
    sz = os.path.getsize(fp)
    mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fp)))
    h = hashlib.sha256()
    with open(fp, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    file_sha = h.hexdigest()
    if not ok:
        first_line = err.splitlines()[0] if err else 'Decode error'
        print(f"FAIL: {os.path.basename(fp)} | size={sz} | mtime={mtime} | err={first_line}")
        scan_results.append({'file': fp, 'status': 'FAIL', 'error': err, 'size': sz, 'mtime': mtime, 'sha256': file_sha})
    else:
        scan_results.append({'file': fp, 'status': 'PASS', 'size': sz, 'mtime': mtime, 'sha256': file_sha})

fail_count = sum(1 for r in scan_results if r['status'] == 'FAIL')
print(f"Integrity scan finished: {len(scan_results)} files scanned. Failures: {fail_count}")

with open(r'G:\My Drive\Cat make\analysis\stuck_job\integrity_scan.json', 'w', encoding='utf-8') as f:
    json.dump(scan_results, f, indent=2)

# Check ledger match
conn = sqlite3.connect(r'C:\LionReel\data\clip_ledger.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT clip_id, source_url_or_path, fingerprint FROM clips LIMIT 10")
print("Ledger samples:", [dict(r) for r in cur.fetchall()])
conn.close()
