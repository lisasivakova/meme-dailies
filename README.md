# Meme Dailies

A full-screen meme swiper for iPhone. Exactly 50 fresh memes a day, picked for each phone by what that phone likes.

- ✕ or swipe left: dislike · ✓ or swipe right: like · ♥, swipe up or double-tap: save to library
- Library (top right): tap a meme → **Save to Photos** → **Save Image**. Or tap **Select** to save several at once.
- Every phone (or browser) that opens the site has its own taste, its own 50 a day and its own library. Nothing is shared between devices.

## Morning hello

The first time you open the app each day, the dog says good morning with one of 50 lines (and its own button label).
Tap the button to start swiping, or the grid button to go straight to your saved memes.
Lines live in `hello/lines.js`, the photo is `hello/dog.jpg`.

## How a day works

1. Every morning at 06:11 Moscow time, GitHub runs `scripts/fetch_daily.py`. It searches Reddit and Are.na round after round
   until it has a pool of 100 fresh memes (never fewer than 50; if a day is ever short, phones top up with unseen memes from earlier days).
2. When a phone opens the app that day, it picks its own 50 from the pool, ranked by the sources it has liked. About 1 in 6 is a wildcard.
3. Your likes and dislikes keep re-ordering the rest of the day's 50 as you swipe.

## Freshness

- Reddit: only posts from the last 7 days (age is worked out from the post id).
- Are.na: only images first uploaded in the last 21 days, not old images re-added to a channel.
- Screenshots whose text shows an earlier year or an old date (old tweets etc.) are skipped.
- **Seen-before check**: `old_hashes.json` holds visual fingerprints of about 5,700 older memes (and grows every day with each old post
  the script comes across). A new post that looks like any of them, or like a meme already in the app, counts as a repost and is skipped.

This is a home-made reverse image check. Google Lens and TinEye have no free way to be called automatically.
TinEye's paid API could be plugged in later if this ever isn't good enough.

## New sources

`sources.json` lists every source and how often it's sampled. About once a week the script trials a few untested subreddits from
the reserve list and searches Are.na for active meme channels with fresh uploads, and adds the ones that qualify. Phones that don't
like a new source will simply see less of it. Sources moved to `"removed"` are never used or re-added.

## Content filter

The daily run has no human looking at it, so it errs on the side of skipping: NSFW flags, plus a word list checked against the title and
the text read off the image (current politics, slurs, sex, self-harm, violence), and an English check.
If something slips through, add its id (from `memes.json`) to the `"blocked"` list and delete its file.

## Put it online (GitHub Pages)

1. Create a new **public** repository on GitHub, e.g. `meme-dailies`.
2. **Settings → Pages**: under *Build and deployment*, set **Source = GitHub Actions**.
3. Upload everything in this folder, including the hidden `.github` folder, keeping the folder structure.
   If `.github` doesn't upload by drag-and-drop, create `.github/workflows/daily-memes.yml` with **Add file → Create new file** and paste its contents.
4. Uploading starts the workflow, which publishes the site (Actions tab, green tick). The site is at `https://<your-username>.github.io/meme-dailies/`.
5. From then on it runs by itself every morning. **Actions → Daily memes → Run workflow** fetches a new batch right away.
6. On iPhone, open the site in Safari → Share → **Add to Home Screen**.

About once a month the workflow commits a tiny `.github/heartbeat.txt`, because GitHub pauses scheduled workflows after 60 days without commits. This needs **Settings → Actions → General → Workflow permissions → Read and write**.

Images are never committed to git. Each run downloads the current memes from the live site, adds today's, removes ones
older than 10 days and republishes, so the repo stays small. Saved memes are kept on each phone, so they never disappear.

## Using it

- ✕ / ✓ / ♥ or swipe left, right, up. Double-tap also saves.
- **Share** (arrow, top bar): sends the meme as a JPEG picture. Pick an app, or Save Image to put it in Photos.
- Learning happens quietly in the background: from your ✕ ✓ ♥ it learns which sources and which kinds of memes (therapy jokes, screenshots of posts, surreal, animals…) you like.
- Tap the counter (e.g. 12 / 50) or finish your 50 to look back through today's memes and change any decision.

## Files

- `index.html`: the app
- `memes.json`: the current pool (the newest batch is "today"), plus `"blocked"` ids
- `memes/`: today's starter images (after that, images live only in the published site)
- `sources.json`: Reddit subs and Are.na channels with weights, reserve list, removed list
- `old_hashes.json`: fingerprints of old memes for the seen-before check
- `scripts/fetch_daily.py`: finds, checks, tags and adds memes. Locally: `python scripts/fetch_daily.py 100` (needs Pillow and tesseract)
- `scripts/restore_state.py`: pulls the current memes from the live site before each run
- `.github/workflows/daily-memes.yml`: runs the script every morning
- `hello/`: the morning hello (photo and the 50 lines)
- `icon.png`, `icon-512.png`, `favicon.png`, `manifest.json`: app icon
