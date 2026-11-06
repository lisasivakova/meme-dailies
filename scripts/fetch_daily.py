#!/usr/bin/env python3
"""Build today's meme pool for Meme Dailies (run every morning by GitHub Actions).

usage: python scripts/fetch_daily.py [POOL_SIZE]      (default 100; never fewer than 50)

Each phone shows exactly 50 memes a day, picked from this pool by what that phone has learned
it likes, so the pool is bigger than 50 and covers many sources. The script keeps searching,
round after round across all sources, until the pool is full.

Freshness ("has this been around for a while?")
  1. Reddit: only posts from the last 7 days (post ids are sequential, so age comes from the id).
  2. Are.na: only images first uploaded in the last 21 days (not old images re-added to a channel).
  3. Screenshots whose text shows an earlier year or an old date (old tweets etc.) are skipped.
  4. "Seen before" check: every old post the script comes across is fingerprinted (perceptual hash)
     into old_hashes.json. A new post whose picture matches an old fingerprint, or any meme already
     in the app, is a repost and is skipped. This index grows every day, so it gets better over time.

Content filter: NSFW flags, a word list checked against titles and the text read off the image (OCR),
and an English check.

New sources: about once a week the script tries a few untested subreddits from sources.json and
searches Are.na for active meme channels with fresh uploads, and adds the ones that qualify.
"""
import sys, os, re, json, random, io, time, datetime, subprocess, tempfile, urllib.request, urllib.parse

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "memes.json")
SRC = os.path.join(ROOT, "sources.json")
OLD = os.path.join(ROOT, "old_hashes.json")
KEEP_DAYS = 10                   # pool images kept this long (saved memes live on each phone)
MAX_W = 1080                     # image width: sharp on iPhone screens
REDDIT_MAX_AGE_DAYS = 7
ARENA_MAX_AGE_DAYS = 21
REDDIT_IDS_PER_DAY = 1_430_000
MIN_DAILY = 50
TIME_BUDGET = 45 * 60           # seconds; GitHub allows far more, this just stops a stuck run
MAX_OLD_HASHES = 80_000
MATCH = 8                        # fingerprint distance (of 64) that counts as "same picture"

BLOCK = re.compile(r"\b(" + "|".join([
    # current politics & news
    r"trump\w*", r"biden", r"kamala", r"obama", r"putin", r"zelensk\w*", r"netanyahu", r"musk", r"elon",
    r"election\w*", r"voter?s?", r"voting", r"democrats?", r"republicans?", r"maga", r"gop", r"congress\w*", r"senat\w*",
    r"president\w*", r"politic\w*", r"leftist\w*", r"ukrain\w*", r"russia\w*", r"israel\w*", r"palestin\w*", r"gaza",
    r"hamas", r"iran\w*", r"nazi\w*", r"hitler", r"epstein", r"immigra\w*", r"deport\w*", r"tariff\w*", r"midterm\w*",
    r"charlie kirk", r"kirk", r"mamdani", r"vance",
    # hate / groups
    r"n[i1]gg\w*", r"fag\w*", r"retard\w*", r"tranny", r"trans", r"pronoun\w*", r"woke", r"incel\w*",
    r"jews?", r"jewish", r"muslims?", r"islam\w*", r"racis\w*", r"slaves?", r"they/them",
    # games, anime and fan art (not her thing)
    r"games?", r"gaming", r"gamers?", r"nintendo", r"playstation", r"ps[1-5]", r"xbox", r"gamecube", r"steam", r"fortnite", r"minecraft",
    r"pok[eé]mon", r"zelda", r"mario", r"cyberpunk", r"warframe", r"valorant", r"genshin", r"elden ring", r"skyrim", r"overwatch",
    r"roblox", r"twitch", r"speedrun\w*", r"noobs?", r"tf2", r"dnd", r"anime", r"manga", r"waifu", r"fan ?art", r"cosplay", r"oc",
    r"marvel", r"dc comics", r"spider-?man", r"batman", r"superman", r"avengers", r"sonic", r"yu-?gi-?oh", r"sailor moon", r"one piece", r"naruto",
    # sex
    r"sex\w*", r"porn\w*", r"nudes?", r"naked", r"horny", r"dick\w*", r"cock\w*", r"puss(y|ies)", r"boob\w*", r"tits?",
    r"cum\w*", r"orgasm\w*", r"onlyfans", r"nsfw", r"balls", r"breast\w*", r"erect\w*", r"hentai", r"thirst\w*",
    # self-harm / violence
    r"suicid\w*", r"kms", r"kys", r"self.?harm", r"murder\w*", r"shoot\w*", r"shotgun", r"guns?", r"rape\w*",
    r"abus\w*", r"genocid\w*", r"terror\w*", r"bomb\w*", r"gore",
]) + r")\b", re.I)
EN_COMMON = set("the a an and to of in is it you i me my we be that this for on with so not are was what when your just like do how if no can at all have but they he she im i'm its it's dont don't".split())
UA = {"User-Agent": "meme-dailies/3.0 (personal meme feed)"}
T0 = time.time()


def get(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def getj(url):
    return json.loads(get(url))


def dhash(im):
    g = im.convert("L").resize((9, 8), Image.LANCZOS)
    p = g.tobytes()
    return sum(1 << i for i in range(64) if p[(i // 8) * 9 + i % 8] > p[(i // 8) * 9 + i % 8 + 1])


def near(h, pool):
    return any(bin(h ^ x).count("1") <= MATCH for x in pool)


def ocr(im):
    try:
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            g = im.convert("L"); g = g.resize((g.width * 2, g.height * 2)); g.save(f.name)
            return subprocess.run(["tesseract", f.name, "stdout", "-l", "eng", "--psm", "11"],
                                  capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ""


def text_problem(text, year):
    if BLOCK.search(text): return "blocked word"
    for y in re.findall(r"\b(20[01]\d|202\d)\b", text):
        if int(y) < year: return "old repost"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b", text)
    if m and 2000 + int(m.group(3)) < year: return "old repost"
    if re.search(r"[Ѐ-ӿ؀-ۿ一-鿿぀-ヿ가-힯]", text): return "not English"
    words = re.findall(r"[a-zA-Z']{2,}", text)
    if len(words) >= 8 and not (set(w.lower() for w in words) & EN_COMMON): return "not English"
    return ""


# ---------- kinds of meme (the phone learns which kinds you like, not just which sources) ----------
KIND_WORDS = {
    "therapy": r"therap\w*|trauma\w*|anxi\w*|depress\w*|healing|cop(e|ing)|mental|feelings?|emotion\w*|boundar\w*|inner child",
    "work": r"work\w*|job|boss|office|emails?|meetings?|cowork\w*|manager|monday|salary|deadline|slack|zoom|career|ceo",
    "relatable": r"me when|me:|me irl|nobody:|pov|when you|me trying|me at|my brain|be like",
    "film": r"movies?|films?|scene|actor|actress|director|cinema|netflix|trailer|oscars?|sequel|letterboxd",
    "romance": r"dating|crush|boyfriend|girlfriend|bf|gf|tinder|dates?|relationships?|single|ex|marriage|husband|wife",
    "food": r"food|pizza|eat\w*|hungry|snack\w*|cook\w*|dinner|lunch|breakfast|bread|cheese|nuggets?",
    "art": r"art|artists?|museum|painting|design\w*|draw\w*|gallery|renaissance|aesthetic",
    "school": r"school|class|exam|teacher|homework|universit\w*|college|student|essay|professor|phd",
    "animals": r"cats?|kitten|dogs?|pupp\w*|birds?|frogs?|rats?|raccoons?|goose|geese|ducks?|horses?|bears?|possum|capybara|gecko|lizard",
    "philosophy": r"philosoph\w*|existential|meaning of life|void|nihil\w*|camus|kant|nietzsche|sisyphus|universe",
    "internet": r"twitter|tweet|reddit|tumblr|instagram|tiktok|posts?|followers?|likes|wifi|phone|online",
}
SRC_KINDS = {"surreal": ("surrealmemes", "comedyheaven", "absurdmemes", "antimeme", "hmmm", "blursedimages", "comedynecrophilia", "notinteresting", "bonehurtingjuice", "cursed", "absurd"),
             "art": ("ClassicalArtMemes", "ArtHistoryMemes", "trippinthroughtime", "UnusualArt", "art"),
             "philosophy": ("philosophymemes", "existential", "enlightenment"),
             "film": ("okbuddycinephile", "film", "movie"),
             "animals": ("cat-memes", "funny-little-guys", "AbsoluteUnits"),
             "therapy": ("TherapyMemes", "2meirl4meirl")}


def kinds(src, text, im):
    t = " " + (text or "").lower() + " "
    tags = [k for k, rx in KIND_WORDS.items() if re.search(r"\b(" + rx + r")\b", t)]
    tags += [k for k, keys in SRC_KINDS.items() if any(x.lower() in src.lower() for x in keys)]
    words = len(re.findall(r"[a-zA-Z']{2,}", t))
    # screenshot of a post: lots of text on a mostly flat white or black background
    g = im.convert("L").resize((48, 48)); px = list(g.tobytes())
    flat = sum(1 for v in px if v > 235 or v < 20) / len(px)
    if words >= 12 and flat > .6: tags.append("posts")
    elif words <= 3: tags.append("picture")
    elif words >= 25: tags.append("wordy")
    return sorted(set(tags))[:5]


# ---------- sources ----------
def reddit_batch(sub):
    d = getj(f"https://meme-api.com/gimme/{sub}/50")
    out = []
    for m in d.get("memes", []):
        if not m["url"].lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")): continue
        pid = m["postLink"].rstrip("/").split("/")[-1]
        prev = m.get("preview", [])
        out.append({"id": "r-" + pid, "pid": int(pid, 36), "src": sub, "link": m["postLink"], "title": m.get("title", ""),
                    "nsfw": m.get("nsfw") or m.get("spoiler"),
                    "img": ([p for w in ("width=1080", "width=960", "width=640") for p in prev if w in p] or [m["url"]])[0],
                    "thumb": ([p for p in prev if "width=108" in p] or [m["url"]])[0]})
    return out


def arena_batch(slug, page=1):
    d = getj(f"https://api.are.na/v2/channels/{slug}/contents?per=100&page={page}&sort=position&direction=desc")
    out = []
    for b in d.get("contents", []):
        im = b.get("image") or {}
        if b.get("class") != "Image" or not (im.get("display") or {}).get("url"): continue
        if "gif" in (im.get("content_type") or ""): continue
        out.append({"id": f"a-{b['id']}", "src": "arena:" + slug, "link": f"https://www.are.na/block/{b['id']}",
                    "title": f"{b.get('title') or ''} {b.get('description') or ''}", "created": b.get("created_at") or "",
                    "img": (im.get("large") or im["display"])["url"], "thumb": (im.get("thumb") or im["display"])["url"]})
    return out


def discover(src, log):
    """Weekly: trial a few reserve subreddits and look for fresh Are.na meme channels."""
    today = datetime.date.today()
    if (today - datetime.date.fromisoformat(src.get("last_discovery", "2000-01-01"))).days < 7: return
    newest = 0
    try: newest = max(c["pid"] for c in reddit_batch("me_irl"))
    except Exception: pass
    random.shuffle(src["reserve_reddit"])
    for sub in [x for x in src["reserve_reddit"] if x not in src.get("removed", [])][:4]:
        try:
            got = reddit_batch(sub)
            fresh = [c for c in got if newest and (newest - c["pid"]) / REDDIT_IDS_PER_DAY <= REDDIT_MAX_AGE_DAYS and not c["nsfw"]]
            src["reserve_reddit"].remove(sub)
            if len(fresh) >= 5:
                src["reddit"][sub] = 1; src["discovered"].append({"source": sub, "date": today.isoformat()}); log.append(f"+ r/{sub}")
        except Exception:
            pass
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=ARENA_MAX_AGE_DAYS)).isoformat()
    for q in random.sample(src["arena_queries"], min(4, len(src["arena_queries"]))):
        try:
            chans = getj(f"https://api.are.na/v2/search/channels?q={urllib.parse.quote(q)}&per=24").get("channels", [])
        except Exception:
            continue
        for c in chans:
            slug = c.get("slug")
            if not slug or slug in src["arena"] or "arena:" + slug in src.get("removed", []) or c.get("length", 0) < 60 or (c.get("updated_at") or "") < cutoff: continue
            try:
                fresh = [b for b in arena_batch(slug) if b["created"] >= cutoff]
            except Exception:
                continue
            if len(fresh) >= 5:
                src["arena"][slug] = 1; src["discovered"].append({"source": "arena:" + slug, "date": today.isoformat()}); log.append(f"+ arena:{slug}")
    src["last_discovery"] = today.isoformat()


def main():
    target = max(MIN_DAILY, int(sys.argv[1]) if len(sys.argv) > 1 else 100)
    os.makedirs(os.path.join(ROOT, "memes"), exist_ok=True)
    db = json.load(open(DB)) if os.path.exists(DB) else {"memes": [], "blocked": []}
    src = json.load(open(SRC))
    old = json.load(open(OLD)) if os.path.exists(OLD) else []
    old_set = set(old)
    log = []
    discover(src, log)

    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.astimezone(datetime.timezone(datetime.timedelta(hours=3))).date().isoformat()
    for m in db["memes"]:                                                    # re-running the same day rebuilds today's pool
        if m["batch"] == today:
            try: os.remove(os.path.join(ROOT, m["file"]))
            except FileNotFoundError: pass
    db["memes"] = [m for m in db["memes"] if m["batch"] != today]
    have = {m["id"] for m in db["memes"]} | set(db.get("blocked", []))
    seen_hashes = [int(m["fp"], 16) for m in db["memes"] if m.get("fp")]
    old_hashes = [int(x, 16) for x in old]
    arena_cut = (now - datetime.timedelta(days=ARENA_MAX_AGE_DAYS)).isoformat()
    newest = 0
    for ref in ("me_irl", "memes", "shitposting"):                           # newest Reddit post id = "now"
        try: newest = max([newest] + [c["pid"] for c in reddit_batch(ref)])
        except Exception: pass
    sources = [s for s, w in src["reddit"].items() for _ in range(w)] + ["arena:" + s for s, w in src["arena"].items() for _ in range(w)]
    added, why, tried = [], {}, set()
    per_src_cap = max(4, target // 12)          # keeps the pool varied
    taken = {}
    arena_page = {}
    rounds = 0

    def remember_old(c):
        try:
            h = dhash(Image.open(io.BytesIO(get(c["thumb"], 15))))
        except Exception:
            return
        hx = f"{h:016x}"
        if hx not in old_set:
            old_set.add(hx); old.append(hx); old_hashes.append(h)

    while len(added) < target and time.time() - T0 < TIME_BUDGET:
        rounds += 1
        random.shuffle(sources)
        progress = False
        for s in dict.fromkeys(sources):               # each source once per round, in weighted-random order
            if len(added) >= target or time.time() - T0 > TIME_BUDGET: break
            cap = per_src_cap * (1 + rounds // 3)       # loosen the per-source cap if we're struggling
            if taken.get(s, 0) >= cap: continue
            try:
                if s.startswith("arena:"):
                    pg = arena_page.get(s, 1); arena_page[s] = pg + 1
                    if pg > 3: continue
                    cands = arena_batch(s[6:], pg)
                else:
                    cands = reddit_batch(s)
                    newest = max([newest] + [c["pid"] for c in cands])
            except Exception as e:
                why["source error"] = why.get("source error", 0) + 1; continue
            random.shuffle(cands)
            olds = 0
            for c in cands:
                if len(added) >= target or taken.get(s, 0) >= cap: break
                if c["id"] in have or c["id"] in tried: continue
                tried.add(c["id"])
                if c.get("nsfw"): why["nsfw"] = why.get("nsfw", 0) + 1; continue
                is_old = ("pid" in c and newest and (newest - c["pid"]) / REDDIT_IDS_PER_DAY > REDDIT_MAX_AGE_DAYS) or \
                         ("created" in c and c["created"] < arena_cut)
                if is_old:
                    why["too old"] = why.get("too old", 0) + 1
                    if olds < 25: remember_old(c); olds += 1
                    continue
                if BLOCK.search(c["title"]): why["blocked word"] = why.get("blocked word", 0) + 1; continue
                try:
                    im = Image.open(io.BytesIO(get(c["img"]))).convert("RGB")
                except Exception:
                    continue
                if im.width < 250 or im.height > im.width * 2.4: continue
                h = dhash(im)
                if near(h, seen_hashes): why["already in app"] = why.get("already in app", 0) + 1; continue
                if near(h, old_hashes): why["seen before (old)"] = why.get("seen before (old)", 0) + 1; continue
                text = ocr(im)
                p = text_problem(text, now.year)
                if p: why[p] = why.get(p, 0) + 1; continue
                tags = kinds(c["src"], c.get("title", "") + " " + text, im)
                w = min(MAX_W, im.width)
                im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
                fn = f"memes/{c['id']}.jpg"
                im.save(os.path.join(ROOT, fn), "JPEG", quality=82, optimize=True, progressive=True)
                added.append({"id": c["id"], "src": c["src"], "file": fn, "w": im.width, "h": im.height, "batch": today,
                              "added": (now + datetime.timedelta(seconds=len(added))).isoformat(timespec="seconds"),
                              "link": c["link"], "fp": f"{h:016x}", "tags": tags})
                seen_hashes.append(h); have.add(c["id"]); taken[s] = taken.get(s, 0) + 1; progress = True
        if not progress and rounds > 12: break

    if len(added) < MIN_DAILY:
        print(f"WARNING: only {len(added)} fresh memes found; the app tops up with unseen memes from earlier days")

    # prune: drop memes older than KEEP_DAYS, but keep a fingerprint so they count as "seen before"
    cut = (now - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    keep = []
    for m in db["memes"]:
        if m["added"] < cut:
            try: os.remove(os.path.join(ROOT, m["file"]))
            except FileNotFoundError: pass
            if m.get("fp") and m["fp"] not in old_set: old.append(m["fp"]); old_set.add(m["fp"])
        else:
            keep.append(m)
    db["memes"] = keep + added
    db["updated"] = now.isoformat(timespec="seconds")
    json.dump(db, open(DB, "w"), indent=1)
    json.dump(old[-MAX_OLD_HASHES:], open(OLD, "w"))
    json.dump(src, open(SRC, "w"), indent=1)
    print(f"{today}: pool {len(added)} memes in {rounds} rounds, {int(time.time() - T0)}s; skipped {why}; "
          f"old fingerprints {len(old)}; new sources {log or 'none'}")


if __name__ == "__main__":
    main()
