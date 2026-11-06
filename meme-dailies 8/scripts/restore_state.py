#!/usr/bin/env python3
"""Pull the current memes, images and state files from the live site before a run.

Images are never committed to git (the repo would grow by megabytes every day); they only live
in the published site. Each run downloads what's live, adds today's memes, prunes old ones and
publishes the result. If the site can't be reached (first run), the copies in the repo are used.

usage: python scripts/restore_state.py https://<user>.github.io/<repo>/
"""
import sys, os, json, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
site = sys.argv[1].rstrip("/") + "/"


def get(path, timeout=40):
    with urllib.request.urlopen(urllib.request.Request(site + path, headers={"User-Agent": "meme-dailies"}), timeout=timeout) as r:
        return r.read()


try:
    live = json.loads(get("memes.json"))
except Exception as e:
    print("live site not reachable, using repo copies:", e); sys.exit(0)

for name in ("sources.json", "old_hashes.json"):
    try:
        data = get(name); json.loads(data)
        open(os.path.join(ROOT, name), "wb").write(data)
    except Exception as e:
        print("kept repo copy of", name, e)

# keep whichever list of memes is newer (the repo's copy wins right after you upload an edited memes.json)
repo = json.load(open(os.path.join(ROOT, "memes.json"))) if os.path.exists(os.path.join(ROOT, "memes.json")) else {"memes": [], "blocked": []}
blocked = set(repo.get("blocked", [])) | set(live.get("blocked", []))
if (repo.get("updated") or "") > (live.get("updated") or ""):
    print("repo memes.json is newer than the live one; keeping it")
    live = repo
live["blocked"] = sorted(blocked)
live["memes"] = [m for m in live["memes"] if m["id"] not in blocked]

os.makedirs(os.path.join(ROOT, "memes"), exist_ok=True)
def fetch(m):
    dest = os.path.join(ROOT, m["file"])
    if os.path.exists(dest): return True
    try:
        open(dest, "wb").write(get(m["file"])); return True
    except Exception:
        return False
with ThreadPoolExecutor(16) as ex:
    ok = list(ex.map(fetch, live["memes"]))
live["memes"] = [m for m, k in zip(live["memes"], ok) if k]
json.dump(live, open(os.path.join(ROOT, "memes.json"), "w"), indent=1)
print(f"restored {sum(ok)} of {len(ok)} images from the live site")
