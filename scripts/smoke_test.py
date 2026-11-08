#!/usr/bin/env python3
"""End-to-end smoke test against a running instance (local or production).

Signs in, analyzes a URL, downloads the smallest offered resolution, checks the MP4,
and prints a summary. Uses only the Python standard library.

    python3 scripts/smoke_test.py https://videos.example.com               (open mode)
    VD_PASSWORD='...' python3 scripts/smoke_test.py https://videos.example.com admin \
        'https://www.youtube.com/watch?v=YE7VzlLtp-4'                        (login mode)

Only use URLs you are authorized to download. The default sample is Blender
Foundation's "Big Buck Bunny" (Creative Commons Attribution 3.0).
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request

SAMPLE = "https://www.youtube.com/watch?v=YE7VzlLtp-4"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    username = sys.argv[2] if len(sys.argv) > 2 else None
    target = sys.argv[3] if len(sys.argv) > 3 else SAMPLE
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {"Origin": base, "Content-Type": "application/json"}

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with opener.open(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def wait(job_id, label):
        last = None
        while True:
            _, job = call("GET", f"/api/jobs/{job_id}")
            line = f"  {label}: {job['status']:<11} {int(job['progress'] * 100):>3}%  {job.get('stage') or ''}"
            if line != last:
                print(line)
                last = line
            if job["status"] in ("completed", "failed"):
                return job
            time.sleep(2)

    status, health = call("GET", "/api/health")
    print(f"health: {status} {health}")
    status, me = call("GET", "/api/auth/me")
    if status == 200 and me.get("mode") == "open" and not username:
        print(f"open mode: browsing as {me['user']['username']}")
    else:
        if not username:
            print("This server requires sign-in: pass a username (and VD_PASSWORD).")
            return 1
        password = os.environ.get("VD_PASSWORD") or __import__("getpass").getpass("Password: ")
        status, me = call("POST", "/api/auth/login", {"username": username, "password": password})
        if status != 200:
            print("login failed:", me)
            return 1
        print(f"signed in as {me['user']['username']}")
    headers["X-CSRF-Token"] = me["csrf_token"]

    status, job = call("POST", "/api/media/analyze", {"url": target})
    if status != 202:
        print("analyze rejected:", job)
        return 1
    job = wait(job["id"], "analyze")
    if job["status"] != "completed":
        print("analyze failed:", job["error"])
        return 1
    res = job["result"]
    print(f"  title: {res['title']!r}  duration: {res['duration']}s  platform: {res['platform']}")
    print(f"  caption: {(res['caption'] or 'Caption unavailable')[:120]!r}")
    print(f"  formats: {[f['label'] for f in res['formats']]}")
    smallest = [f for f in res["formats"] if f["format_id"] != "best"][-1]

    status, dl = call("POST", "/api/media/download", {"analysis_job_id": job["id"], "format_id": smallest["format_id"]})
    if status != 202:
        print("download rejected:", dl)
        return 1
    dl = wait(dl["id"], f"download {smallest['label']}")
    if dl["status"] != "completed":
        print("download failed:", dl["error"])
        return 1
    r = dl["result"]
    status, data = call("GET", f"/api/media/{r['media_file_id']}/file")
    ok = status == 200 and data[4:8] == b"ftyp"
    print(f"  file: {r['filename']} {r['size_bytes'] / 1e6:.1f} MB {r['width']}x{r['height']} "
          f"video={r['vcodec']} audio={r['acodec']} expires={r['expires_at']}")
    print("RESULT:", "PASS" if ok and r["has_audio"] else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
