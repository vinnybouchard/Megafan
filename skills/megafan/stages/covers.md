# Find and LOOK at the cover art — worker stage `covers` of the megafan skill

You are ONE worker in a parallel run of this skill. The coordinator
(`SKILL.md`) has already done §0–§2.5 — mode, rk, catalogue number, disc
shape — and wrote them to `job.json`. `<rk>` below is that rating key.

**Inputs:** `job.json`; the network; in `rescan` mode the flatbed front scan in the shoot folder.

**Outputs** (under `/tmp/concert/<rk>/covers/`): `cover.png` (the chosen art, white padding trimmed, NOT rotated — say the rotation needed), `candidates.md` (every candidate: source, measured WxH, bytes, what it actually shows, verdict), `report.md`.

**Worker rules (the contract every stage shares):**
- Work from the repo root. Read `/tmp/concert/<rk>/job.json` FIRST — it
  names the rk, catalogue number, `mode` (`fresh`|`rescan`), the item's folder
  and files, the shoot folder (or null), and for a multi-disc set every member.
- **Never ask the owner anything.** There is nobody on the other end of a
  worker. Anything that needs a person — a download behind a login, a fact only
  the case in your hands can settle, a sanctioned exception — is a
  `NEEDS OWNER: …` line in your report, and the coordinator carries it out
  after the run.
- **Never write outside your own scratch dir, and never into a git repo.**
  Everything you produce goes under `/tmp/concert/<rk>/<stage>/`; where the text
  below says to file something somewhere, write the same thing in your output
  dir and NAME it in the report. You propose; the coordinator disposes.
- **Never `PUT …/analyze` on Plex** unless your stage file says you may (only
  `chapters` may, and it does so last).
- **Never change the bytes of a video file in `/mnt/media`** unless your stage
  file says you may (`chapters` rewrites the main; `subs` muxes into EXTRAS only).
- LOOK at whatever your stage says to look at — the coordinator will not, by
  design. A worker report that says "applied" about a picture nobody looked at
  is the failure this whole skill is built around.
- Finish with `/tmp/concert/<rk>/<stage>/report.md` in the format at the end of
  this file. The coordinator reads ONLY that file. Keep it under ~80 lines;
  put bulk (transcriptions, candidate lists) in sibling files it names.
- The text below was moved VERBATIM from the single-file skill and keeps its
  section numbers, so `SKILL.md` and the other stages can still cite them.
  Scratch paths were re-pointed under `/tmp/concert/<rk>/`.

---

### 3 (covers half). Harvest, then LOOK

```bash
python3 scripts/plex_concert_research.py --item <rk> --covers-only \
    --out /tmp/concert/<rk>/covers [--sony <slug>] [--wiki <wiki> --wiki-page "<exact page>"]
```

**Rescan mode:** the object is in hand, so the flatbed front scan outranks every
download — copy it as `cover.png` (trim borders, note the rotation) and skip the
hunt; §0 says a phone-photo poster composed *perfectly* into a purple-washed one.

**Covers — you must actually `Read` each candidate image.** Nothing in the
metadata distinguishes them, and every source has produced both good and useless
art across these discs:
- `sonymusic` — the label's own jacket. Sometimes the clean front art, sometimes
  the whole flattened sleeve with the back panel on it.
- `cdjapan` — sometimes a clean jacket, sometimes the **shrink-wrapped retail
  package** with an obi and a price sticker.
- `discogs` — user scans of the actual sleeve. Size varies wildly (240px on one
  disc, 477×599 on the next), so judge by the measured size, not the source.
  **The report shows only the first three; the release may list more** — seven on
  `Dhurha Vs Dhurha`. When none of the three is a clean flat scan, pull the rest
  from `/releases/<id>` and check the `width`×`height` the API reports before
  downloading. There the extras were a photo of the sleeve on a table, the
  shrink-wrapped package, the back panel and a bonus tote bag, and the `primary`
  was still the right pick — but that is the check, not the assumption.
- `wiki` — often a small fair-use crop.

**When every candidate is small (<300px), go to the ARTIST'S and the LABEL'S own
site before settling.** All five candidates for one batch topped out at 267px and
all three were beaten in a couple of minutes:

- **Render the page — an official site is JavaScript and `requests` sees a
  shell.** Measured 2026-09-08: `larc-en-ciel.com/discography/` is **39 KB** to
  plain `requests` and **676 KB rendered**, so the art is not in the bytes a
  normal fetch returns at all. Headless Chromium lives in `scripts/browser/`
  (own `.venv`, gitignored — see its README):
  ```bash
  scripts/browser/.venv/bin/python scripts/browser/art.py \
      "https://www.larc-en-ciel.com/discography/" --min 300
  ```
  It lists every image at the size the browser actually **decoded**, largest
  first, downloading nothing — this section's "judge by the measured size, not
  the source" rule as one command. That page yields 140 candidates.
  **Try `curl --compressed -A "<UA>"` first**: most refusals here are TLS
  fingerprinting rather than JavaScript, and curl already beats metal-archives
  (re-verified 2026-09-08) for a fraction of the cost. Reach for the browser
  when the content is *built* by script, not merely gated.
- **The artist's official discography page.** `larc-en-ciel.com/s/<n>/discography/<CATNO>`
  gave 422x600; `pillows.jp/s/disco/<YYYYMMDD>/` gave the jacket *and* the
  canonical release title. Find it by searching the catno plus the artist.
- **A WordPress site serves a RESIZED thumbnail — strip the suffix.**
  `...-wake_up_stand_up_and_go-300-250x355.jpg` → delete `-250x355` for the
  300x426 original. One-line upgrade, works on any WP-backed official site.
- **Label asset URLs carry a size token.** Warner's is `_LLL_`
  (`prod-v2-assets.wmg.jp/uploads/<catno>_LLL_<hash>.jpg`, 640x640 where Discogs
  and Amazon both had 210x300). It may be **padded to square with white** —
  `convert x.jpg -bordercolor white -border 1 -fuzz 4% -trim +repage y.png`
  before composing, or the poster inherits the padding. An artist site does the
  same with a bare numeric token: on `larc-en-ciel.com/images/...` the page
  serves `800_320_102400.jpg` at 320x320 while `800_800_102400.jpg` is
  **800x800** (measured 2026-09-08) — and `original.jpg` on that same path is a
  **1x1 at HTTP 200**, so decode every guess instead of trusting the pattern.
- Amazon's `images/P/<ASIN>.01.LZZZZZZZ.jpg` **varies wildly by release and is
  worth one try every time** — no better than Discogs on one disc, a 43 B 1x1 at
  HTTP 200 on another, and the outright winner on `PCXE-50110` (397x500, against
  CDJapan's 317x400 and nothing at all on Discogs). The ASIN comes free from a
  plain web search for the catno. The `_SL1500_`/`_SL1200_` size tokens do NOT
  work on the `P/<ASIN>` path — all three returned the same 397x500 bytes — so
  measure what you got and do not assume a suffix upgraded it.

**Check the byte size of every download, not the status code** — CDJapan answers
a guessed path with HTTP 200 and a **1621-byte** 128x128 placeholder, and one
official-site path returned HTTP 200 with **0 bytes**. Both `identify` as images.
`art.py --measure <url> ...` settles it without downloading: it decodes each URL
in the browser and prints the real dimensions, so a placeholder reads as `1x1`
and a dead guess as `DECODE FAILED` rather than as a successful fetch.

If the original's jacket turns out to be the whole flattened sleeve (front *and*
back panel), re-run with a **reissue's** catalogue number — Discogs lists the
other pressings, and a Blu-ray reissue's jacket is often the clean front art.
That is how the X Japan poster was found.

---

## Report (`report.md`, required lines)

- `pick:` `cover.png` ← source + measured WxH; `rotate: none|cw|ccw|180`
- `what it is:` clean front jacket / flattened sleeve / reissue jacket / video still / retail package (say which pressing)
- `rejected:` one line per candidate with the reason (size, shrink-wrap, back panel on it…)
- `hunted:` artist site / label / Amazon tried, with the best size each gave
- `NEEDS OWNER:` one line per thing only a person can settle (or `NEEDS OWNER: none`).
- `OWED:` anything you started and did not finish, or deliberately left (or `OWED: none`).
