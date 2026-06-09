#!/usr/bin/env python3
"""
Hot App Summer × Replay QA — Daily Automation Script
Fetches new showcase submissions, creates Replay QA projects, polls for results,
and regenerates the leaderboard data file.

Run daily via scheduled task or manually:
    python3 scraper.py
"""

import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.error

# ── Config ────────────────────────────────────────────────────────────────────

SHOWCASE_API = "https://hotappsummer.netlify.app/api/submissions"
REPLAY_BASE  = "https://loop-qa.replay.io"
REPLAY_TOKEN = "lqa_f01144a58918e2c5e327e21f5817f79794884c8805baf7e1"

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
STATE_FILE   = os.path.join(SCRIPT_DIR, "state.json")
PUBLIC_DIR   = os.path.join(SCRIPT_DIR, "public")
DATA_FILE    = os.path.join(PUBLIC_DIR, "data.json")

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _headers():
    return {
        "Authorization": f"Bearer {REPLAY_TOKEN}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }

def get(url, params=None):
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def post(url, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        raise RuntimeError(f"POST {url} → {e.code}: {raw.decode()}")

# ── State helpers ─────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"apps": {}, "last_updated": None}

def save_state(state):
    state["last_updated"] = datetime.datetime.utcnow().isoformat() + "Z"
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  ✓ state.json saved ({len(state['apps'])} apps)")

# ── Core logic ────────────────────────────────────────────────────────────────

def fetch_showcase():
    print("Fetching Hot App Summer showcase …")
    req = urllib.request.Request(SHOWCASE_API)
    with urllib.request.urlopen(req, timeout=30) as r:
        apps = json.loads(r.read())
    print(f"  Found {len(apps)} apps")
    return apps

def create_replay_project(app):
    name = f"[HAS] {app['name']} — {app['handle']}"
    payload = {
        "name":       name,
        "target_url": app["link"].rstrip("/") + "/",
        "is_public":  True,
    }
    print(f"  Creating Replay QA project for: {app['name']}")
    result = post(f"{REPLAY_BASE}/api/projects", payload)
    return result

def start_scan(project_id):
    try:
        post(f"{REPLAY_BASE}/api/spawn-containers-background", {"project_id": project_id})
        print(f"    ↳ Scan started for {project_id}")
    except Exception as e:
        print(f"    ↳ Scan trigger note: {e}")

def fetch_bug_counts(project_id):
    try:
        return get(f"{REPLAY_BASE}/api/bugs/counts", {"project_id": project_id})
    except Exception:
        return None

def check_scan_done(project_id):
    """Returns True if no containers are actively running."""
    try:
        summary = get(f"{REPLAY_BASE}/api/tasks/summary", {"project_id": project_id})
        return len(summary.get("running", [])) == 0 and len(summary.get("queued", [])) == 0
    except Exception:
        return False

def process_new_apps(state, showcase_apps):
    """Create Replay QA projects for apps not yet in state."""
    known_ids = set(state["apps"].keys())
    new_apps = [a for a in showcase_apps if str(a["id"]) not in known_ids]

    if not new_apps:
        print("  No new apps since last run.")
        return

    print(f"  {len(new_apps)} new app(s) to process:")
    for app in new_apps:
        sid = str(app["id"])
        try:
            project = create_replay_project(app)
            project_id  = project["id"]
            project_url = f"{REPLAY_BASE}/projects/{project_id}/overview"

            start_scan(project_id)

            state["apps"][sid] = {
                "showcase_id":        app["id"],
                "name":               app["name"],
                "handle":             app["handle"],
                "pitch":              app.get("pitch", ""),
                "emoji":              app.get("emoji", "🚀"),
                "link":               app["link"],
                "primitives":         app.get("primitives"),
                "submitted_at":       app.get("createdAt"),
                "replay_project_id":  project_id,
                "replay_project_url": project_url,
                "scan_status":        "scanning",
                "scan_started_at":    datetime.datetime.utcnow().isoformat() + "Z",
                "scan_completed_at":  None,
                "bug_counts":         None,
            }
            time.sleep(0.5)  # be polite
        except Exception as e:
            print(f"    ✗ Failed for {app['name']}: {e}")
            state["apps"][sid] = {
                "showcase_id":       app["id"],
                "name":              app["name"],
                "handle":            app["handle"],
                "pitch":             app.get("pitch", ""),
                "emoji":             app.get("emoji", "🚀"),
                "link":              app["link"],
                "primitives":        app.get("primitives"),
                "submitted_at":      app.get("createdAt"),
                "replay_project_id": None,
                "replay_project_url":None,
                "scan_status":       "error",
                "scan_started_at":   None,
                "scan_completed_at": None,
                "bug_counts":        None,
                "error":             str(e),
            }

def poll_scanning_apps(state):
    """Poll bug counts for apps that are currently scanning."""
    scanning = [
        (sid, app) for sid, app in state["apps"].items()
        if app.get("scan_status") == "scanning" and app.get("replay_project_id")
    ]
    if not scanning:
        return

    print(f"  Polling {len(scanning)} scanning project(s) …")
    for sid, app in scanning:
        pid = app["replay_project_id"]
        done = check_scan_done(pid)
        counts = fetch_bug_counts(pid)

        if counts:
            app["bug_counts"] = counts

        if done and counts is not None:
            app["scan_status"]      = "complete"
            app["scan_completed_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            print(f"    ✓ {app['name']}: {counts.get('total', 0)} bugs found")
        else:
            print(f"    … {app['name']}: still scanning (bugs so far: {counts.get('total', 0) if counts else '?'})")

def write_data_json(state):
    """Write public/data.json and regenerate index.html with embedded data."""
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    apps_list = list(state["apps"].values())
    # Sort: complete first (by total bugs desc), then scanning, then error
    def sort_key(a):
        status = a.get("scan_status", "")
        bugs   = (a.get("bug_counts") or {}).get("total", 0)
        order  = {"complete": 0, "scanning": 1, "error": 2, "pending": 3}
        return (order.get(status, 9), -bugs)
    apps_list.sort(key=sort_key)

    data = {
        "apps":         apps_list,
        "total_apps":   len(apps_list),
        "last_updated": state.get("last_updated"),
        "showcase_url": "https://hotappsummer.netlify.app/showcase",
    }
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  ✓ data.json written ({len(apps_list)} apps)")

    # Embed data into index.html so it works when opened as a local file
    html_path = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path) as f:
            html = f.read()
        inline = f"<script>window.LEADERBOARD_DATA={json.dumps(data)};</script>"
        # Replace existing embedded block or insert before </head>
        import re
        html = re.sub(r'<script>window\.LEADERBOARD_DATA=.*?;</script>', inline, html)
        if "window.LEADERBOARD_DATA" not in html:
            html = html.replace("</head>", inline + "\n</head>")
        with open(html_path, "w") as f:
            f.write(html)
        print(f"  ✓ index.html updated with embedded data")

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Hot App Summer × Replay QA  —  Daily Run")
    print(f"UTC: {datetime.datetime.utcnow().isoformat()}Z")
    print("=" * 60)

    state = load_state()

    showcase_apps = fetch_showcase()
    print("\n[1/3] Processing new apps")
    process_new_apps(state, showcase_apps)

    print("\n[2/3] Polling in-progress scans")
    poll_scanning_apps(state)

    print("\n[3/3] Writing output files")
    save_state(state)
    write_data_json(state)

    complete = sum(1 for a in state["apps"].values() if a.get("scan_status") == "complete")
    scanning = sum(1 for a in state["apps"].values() if a.get("scan_status") == "scanning")
    errors   = sum(1 for a in state["apps"].values() if a.get("scan_status") == "error")
    total    = len(state["apps"])
    print(f"\nDone. {total} total | {complete} complete | {scanning} scanning | {errors} errors")
    print("=" * 60)

if __name__ == "__main__":
    main()
