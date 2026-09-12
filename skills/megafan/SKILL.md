---
name: megafan
description: "Fill in metadata for concert and live-music discs in a Plex library that runs no metadata agent, where the filename is the only thing Plex knows and every field must be written by hand and locked. Researches the disc's catalogue number across MusicBrainz, Discogs, CDJapan and Wikipedia, finds and visually checks cover art, then applies release year, release date, summary, setlist and poster. Also names chapters after songs, fills chapter thumbnails, and handles English subtitles for a disc that ships none. Works for live releases from any band and any country, and is built around the awkward cases: catalogue numbers written inconsistently across sources, databases that disagree about a release date, and imported discs that ship no English subtitle track. Handles one disc or a whole queue. Triggers: I ripped a concert DVD, I ripped a live Blu-ray, new item in my Concerts library, fix the metadata for this concert, my concert library has no artwork or dates, set up a no-agent Plex music-video library, name the chapters after the songs, add English subtitles to a Japanese concert disc, add English subtitles to a concert disc that has none."
---

## Concert metadata (research → apply → LOOK)

For the Plex **Concerts** library (section 5, `/mnt/media/Concerts`), which runs
`tv.plex.agents.none`. No agent means **the filename is the only metadata Plex
has** and it fetches no artwork, so everything below is written by hand and
`.locked=1` — an unlocked field gets re-derived on the next scan, and with
nothing to derive it from Plex stamps the scan date. That is how a 2013 release
came up as 2026.

**You do not rip anything.** The rip is a `.bat` you or someone else
double-clicks on Windows. Your job starts once the file is in the library.

Case history, prior discs and the traps behind every rule here live in the
memory `dvd-rip-to-plex.md`. **Read it before anything unusual** — this file is
the procedure, that one is the evidence. Don't restate it here; they will drift.

### 0. More than one disc waiting? Batch it

```bash
python3 scripts/plex_concert_meta.py --batch --dry-run    # say what it would do
python3 scripts/plex_concert_meta.py --batch              # do it
```

Researches every item missing metadata, **applies** the ones nothing is
uncertain about, and leaves the rest with their research already sitting in
`/tmp/concert-batch/<rk>/` (`summary.txt`, `facts.json`, `covers/`). Work the
`NEEDS YOU` pile by hand from step 2, starting from those files rather than from
scratch.

Two rules for batch:
- **`--dry-run` first** whenever anything about the batch is unusual. It writes
  nothing.
- **Then look at every poster it composed** (step 5). Batch picks the
  largest usable candidate as a starting point; nothing in it judged an image.

A disc is applied automatically only when *all* of: the catalogue number came
from the rip log, it resolves to exactly one MusicBrainz release, ≥2
catalogue-keyed sources agree the date, a wiki page title matches the release
exactly once folded, and the setlist plausibly fits the file's runtime. Anything
else is yours.

### 1. Find the item (single disc)

```bash
python3 scripts/plex_concert_meta.py          # no args: what needs work
```

A fresh rip shows `year -` or `summary -`, or a `year` equal to the scan date
(a no-agent library stamps today's date when it has nothing to derive from).
Note its `rk`.

### 2. Get the catalogue number — it is the disc's identity

The ripper prompts for it (Concerts only) and stashes it in
`/mnt/media/STAGING/.dvdrip-logs/*.json`; the tools recover it automatically by
matching the item title. If it isn't there, read it off the case yourself.
Everything downstream keys off it, and it is the one fact that has independently
confirmed a disc twice.

It is written inconsistently — `KSB5 5734` on the case, `KSB5-5734` in the
databases. Search APIs normalise that; **URL paths do not**, which is handled,
but never "tidy" the captured string.

**Hyphenation is not the only way it varies: a shop may drop the LEADING ZEROS.**
CDJapan files `ANKM-0038` as `product/ANKM-38` — a different normalisation from
the hyphen case, and not one a search API folds for you — so its row came back
`[none]` for a disc it stocks. Read a `[none]` from any single shop as *"not
found under the spelling I tried"*, and try the zero-stripped form before
concluding the release is not there. Same rule as the ja.wikipedia row below,
and the same rule as the blocked-vs-empty one at the bottom of this file.

### 2.5 Work out what you actually have — a catno names a RELEASE, not a disc

Do this before researching. It is cheap, and every question below is one the
databases will happily answer *about the wrong thing*.

**Count the rip logs against the library.** A multi-disc set ripped over two
nights can produce the **identical folder name** twice, and the second disc then
fails to file and sits in `/mnt/media/STAGING/Concerts/` indefinitely — while the
first disc looks like a perfectly normal, complete item. Nothing anywhere reads
as an error, so nothing will ever tell you.

```bash
# every catno the ripper captured, WHICH DISC it was, and what it produced
cd /mnt/media/STAGING/.dvdrip-logs && for f in *.json; do python3 -c "
import json;d=json.load(open('$f',encoding='utf-8-sig'))
fs=d.get('files') or []
print('$f', repr(d.get('catalog')), 'disc %s/%s'%(d.get('discNo'),d.get('discsTotal')),
      '%d file(s)'%len(fs), [round((x.get('bytes') or 0)/1e9,1) for x in fs])
print('     ', d.get('headline'))"; done
ls /mnt/media/STAGING/Concerts/         # anything parked here is a disc you do not have
```

Measured 2026-08-19, with both shapes visible in four lines:

```
'VIBP-31'    disc 1/2  2 file(s) [3.9, 0.0]                 <- headline shared,
'VIBP-32'    disc 2/2  6 file(s) [0.7, 0.7, 0.6, 0.0, ...]     catnos differ
'PCXE-50110' disc 1/2  4 file(s) [30.7, 29.9, 0.1, 0.0]     <- ONE disc, TWO ~30 GB
'PCXE-50110' disc 2/2  2 file(s) [21.5, 9.9]                   mains: the trap below
```

**Two logs sharing one headline with DIFFERENT catnos is a 2-disc set**
(`KSBL-5909` + `KSBL-5910`). The logs are BOM'd — `encoding='utf-8-sig'`, or
`json.load` raises. Resolving a stuck one is the `/plex-librarian` skill; do not
`approve` it, rename the source (that skill has the procedure).

**★★ The log states `discNo` / `discsTotal` outright — read them before anything
else.** They are the cheapest fact in this whole section and they answer "how
many discs am I owed" without a single lookup. `discsTotal: 2` with only one
log present means a disc has not been ripped; two logs at `discNo` 1 and 2 with
the SAME catno is the normal 2-disc set (a set does not always split its catno
the way `KSBL-5909`/`5910` did). And **count the `files` array**: one disc that
produced two ~equal multi-GB mains is the trap three bullets below.

**Then work out WHICH disc is in the item, and prefer a published runtime to
frames.** The release's wiki article routinely prints a per-disc running time
(`DISC1 1時間29分02秒`), and matching it against `ffprobe` settles it outright —
measured 5347 s against a published 5342 s, and the other disc 6738 s against
6732 s. Frames (the Dam Vs Dam route) still work and are the fallback when
nothing is published, but they cost far more and prove less.

**Say which disc it is in the summary, always** — and give the whole-set
runtime a moment's thought: a set total looks exactly like a wrong disc total.

**★ CHAPTER COUNT against the article's contents table is the other free check,
and it is structural where a runtime is only numeric.** ja.wikipedia lays these
releases out as a `DVD/BDチャプター` table numbered `DISC1-1…DISC1-23`,
`DISC2-1…DISC2-12` — so the count *per disc* is published. On `PCXE-50110` the
filed main had 23 chapters, the staged disc 2 had 12, and its `Featurettes/` had
5 against five listed 映像特典: three independent confirmations of which disc was
which, at the cost of one `ffprobe -show_chapters` each. It also cross-checks the
booklet, which prints the same list without the numbering.

**Sum the disc's unique content against the published runtime.** It is the check
that separates real extras from duplication, and MakeMKV produces both:

- A DVD's **play-all** title and its **individual** titles are both ripped, so a
  `Featurettes/` folder can be a second copy of the main file. The tell is a
  chapter-length sequence that reproduces the featurette durations in order
  (measured: main chapters 3–7 matched titles 02–06 to within 0.1 s).
- **Repeated durations are usually a STRUCTURE, not a fault.** Five titles at
  ~356 s and five at ~546 s were per-member *Personal Edit Versions*, not
  playlist obfuscation. One montage of the same timestamp across all five showed
  five different members; the label's page then said so outright. Extract frames
  before concluding anything about a suspicious title list.
- **★★ TWO near-identical MAIN files from ONE disc is a bonus VIEWING MODE, and
  it files as a COMPLETE 2-DISC ITEM.** This is the worst shape in this section
  because it never fails: the renamer reads the two mains as a set and files them
  `- cd1` / `- cd2` (Plex's *stacking* convention — that suffix pair on a concert
  is itself the tell), the library looks finished, and the real disc 2 sits
  unfiled in STAGING with nothing anywhere reading as an error. Measured on
  `PCXE-50110`: 7627.7 s and 7381.8 s, both ~30 GB.
  **Diff the CHAPTER LENGTHS first — it is one `ffprobe` each and it settles it.**
  Both files had 23 chapters; chapters 2–23 were identical to 0.1 s and only
  chapter 1 differed, by 245.9 s — *exactly* the whole-file delta. One playlist is
  the other plus a head. Confirm with frames at `t + delta` vs `t` (mean |diff|
  was 2.6–3.7 on 0–255), then look at the head itself: here it was four minutes of
  the empty hall, the disc's own
  「開演前の会場の雰囲気を楽しめるモード」, printed in the booklet and listed on
  ja.wikipedia under おまけ映像特典.
  **KEEP THE LONGER PLAYLIST** — the bonus mode is only on that one, so deleting
  it instead silently loses an extra. Say in the summary that the mode is built
  into the file and when the show actually starts, or the runtime looks wrong
  against every published figure.

### 3. Research BEFORE writing anything

```bash
python3 scripts/plex_concert_research.py --item <rk> \
    [--sony <slug>] [--wiki <wiki> --wiki-page "<exact page>"]
```

Read-only. Prints a fact table and drops cover candidates in `/tmp/concert-covers`.

**Facts.** Verdicts mean what they say:
- `AGREED … + corroborated by ja.wikipedia's release table` → trust it.
- `ONE SOURCE ONLY (uncorroborated)` → use it, and *say* it is uncorroborated.
- `CATALOGUE-KEYED SOURCES DISAGREE` → the catalogue-keyed sources outrank
  anything else, and ja.wikipedia's row is the tie-break.
- **`ja.wikipedia [none]` does NOT mean there is no article** — and neither does
  **`[skipped]`**, which is the same false negative wearing a different word.
  That row is queried by CATALOGUE NUMBER, and the article is titled after the
  RELEASE. `KSBL-5909` returned `[none]` while `TOUR 2007-2008 THEATER OF KISS`
  is a full article with the release dates, the tour dates, the filming venue,
  the Oricon placing **and the per-disc runtimes** — i.e. the single most useful
  page for the disc, reported as absent. `ANKM-0038` returned `[skipped]` while
  the **band's** 30 KB article carried a discography table giving that disc's
  date and catalogue number outright, plus furigana for every member name (the
  only place the readings behind the romanised line-up are actually stated).
  **Search the title AND the artist through the wiki API before believing that
  row**, exactly as you would try the hyphenated catno.
- **A shop's PROSE is not its catalogue-keyed data, and it can be wrong.**
  CDJapan's blurb dated a concert 9 October where the band's own site, two other
  shops, the Blu-ray reissue title and *the date printed on the jacket* all said
  the 8th. Its release-date field was right the whole time. Treat a shop's
  descriptive sentence as one uncorroborated source, however authoritative the
  page around it looks.

**The `metal-archives*` row is on probation and does NOT vote.** The star means
observational: it is queried by catalogue number like the real sources, but it is
kept out of the verdict, so it can never turn an `AGREED` into a `DISAGREE` or
block a `--batch` auto-apply. It is metal-only, so `[not a metal release / not
indexed]` is the expected answer for most of this library and is a fact about its
scope, not a fault. It is carried because the disc queue is metal-heavy and its
accuracy is worth measuring: every run appends to
`/mnt/media/STAGING/.dvdrip-logs/ma_tally.jsonl` and the report prints the running
record. **Promote it to a real vote only from that tally**, never from a hunch —
and note it opened 0-for-1, claiming 2008-03-26 for the Galneryus disc against
three sources (including the shop that sold it) saying 2008-03-05.

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

### 4. Apply

```bash
python3 scripts/plex_concert_meta.py --item <rk> --wiki <wiki> \
    --cover-file /tmp/concert-covers/NN-x.png --summary-file /tmp/<name>.txt
```

Interactive, so drive it with `printf '<release>\n<page>\ny\ny\n' | …` — but
**read the printed menus in the output**, don't answer blind.

- **Wiki ladder:** the artist's own fandom subdomain → `visualkei` for anything
  visual-kei/J-rock → `wikipedia` → `ja.wikipedia`. fandom covers almost nothing
  outside that scene; western artists always have a Wikipedia article.
- **Division of labour:** MusicBrainz owns the facts (date, catalogue number,
  format). The wiki owns the **prose** and the **romanised tracklist** — MB files
  Japanese titles, the library is written in romaji.
- **★★ Romanise from the READING, never off the kanji.** A dictionary reading is
  not *the* reading, and a wrong one invents a title that never existed. On
  `Dhurha Vs Dhurha` the live is `面面面～フメツノフェイス～`, where 面 reads
  **ヅラ (zura)** — the band's slang for a face, the same word the release title
  doubles — so it is `Zura Zura Zura`, not the "Menmenmen" the characters suggest
  and which a band this fond of ramen puns makes genuinely *plausible*. Search
  `<title> 読み方` and confirm before a setlist line is written.
- **On a READING specifically, a karaoke database outranks a wiki.**
  ja.wikipedia gave `肺脂西班牙` as はいししせいはんや, a naive literal read;
  uta-net and JOYSOUND both give ハイヤニ・スペイン ("Haiyani Spain") and the
  lyrics repeat it. JOYSOUND indexes on the reading the rights holder supplies for
  karaoke, so for *how a title is pronounced* it beats an editor's guess.
- **Read the artist's existing entries before inventing a romanisation.**
  Internal consistency beats any external standard: this library title-cases what
  the band files lowercase, and keeps the band's own latin where they supply one
  (`恐喝～kyokatsu～` → `Kyokatsu`). A sibling disc by the same artist is the best
  style guide there is — and that rule is load-bearing, because **the library is
  NOT internally consistent on long vowels.** Measured across all 23 items:
  **digraphs are the house default** and macrons appear in only three summaries,
  all of them Maximum the Hormone, which mix both (`Nou` and `Bouriki` sit beside
  `Zetsubō`). Everyone else is `Jumyou` / `Roujin` / `Kanseitou` / `Kagerou` /
  `Kyuuseishu`. So write `Kuuchuu`, not `Kūchū` — and note that a long vowel is
  easy to drop entirely: 空中 is くうちゅう, long in BOTH syllables.
- **★ The artist's own site often prints the tracklist ALREADY ROMANISED**, which
  beats every judgement call above. L'Arc's official discography page supplied
  `Sunadokei` (砂時計), `Umibe` (海辺), `Natsu no yu-utsu`, `Yuki no ashiato`
  outright. Check it before romanising a single kanji title yourself.
- **When neither MB nor a wiki has the tracklist, the label's own NEWS POST
  does.** `sonymusic.co.jp/artist/<slug>/info/<id>` is the 収録内容 announcement,
  and it is a *different page* from the `…/discography/<CATNO>` one used above for
  jackets and facts — that one is jacket-and-facts, the news post is CONTENTS.
  It gave Galileo Galilei's official 20-track list *and* the three bonus songs
  when MusicBrainz had nothing and no wiki page existed, and note Sony's own
  **shop** (`sonymusicshop.jp`) listed no tracks at all — so the shop is not a
  substitute for it. Find it by searching the catalogue number with 収録内容.
  Tower Records (`tower.jp`) is the reliable second opinion and the one source
  that prints **per-track running times** — though only for a CD; on a video
  release it prints `00:00:00` for every track (see §7).
- **Every major Japanese label has that page; only the URL shape differs.**
  Warner Music Japan is `wmg.jp/<artist-slug>/discography/<id>`, and it carried
  the complete DISC1/DISC2 contents for `Dhurha Vs Dhurha` when MusicBrainz had
  nothing whatsoever. **Ask the fetch for it VERBATIM** — a first pass summarised
  a 17-track listing into one sentence and dropped every track number, which
  reads exactly like an answer and is not one. Insisting on line-by-line, no
  paraphrase, no translation, returned all of it.
- **A fan CONCERT REPORT is not a setlist source — use the label's contents
  listing.** A blog write-up of the Budokan show agreed on the encore but its
  opening half was songs that are not on the disc, with one title listed twice.
  A fan review IS a real source for what is *on* a disc (it is how the Dam Vs Dam
  split was confirmed); a **running order** is where it goes wrong, because the
  writer may be recalling a different night of the tour. Let the disc settle it:
  match each published track duration against `ffprobe -show_chapters` in order —
  that pins every song to a chapter and exposes the MCs and any bonus section.
- **Picking the release:** `*` marks one that ships with a CD. That is a
  *label, not a filter* — a bonus DVD from a limited-edition album legitimately
  IS the starred release, and `mb_tracklist` then returns only the DVD's tracks.
- **A folder with no `(year)` needs MusicBrainz**, since there is no `--year`
  flag and the wiki-only path aborts rather than invent one.
- **★ The DIRECT LOCKED ROUTE is the normal path, not an exotic fallback** — it
  is where you end up whenever the tool's happy path cannot run, and that is
  most discs. Three independent triggers, any one of which is enough: MusicBrainz
  holds neither the release NOR the artist (the tool stops at `!! MusicBrainz has
  no artist called '<x>'` and no `--wiki` rescues it); the release is a
  **multi-disc set**, where the whole-set tracklist would be wrong for the disc
  you have; or **no wiki page exists** on the tool's ladder, which is routine for
  a band with no English article. A recent batch of three hit one trigger each.
  **Assert the item's duration before writing** — keying on `rk` alone is what
  let a rename put disc 2's summary on disc 1's file. The route is: `sys.path.insert` the
  `scripts/` dir, `import plex_concert_meta`, and drive its own
  `apply_metadata()` and `compose_poster()` with facts you sourced by hand.
  **Do not hand-roll the PUT.** Reusing those two functions is the whole point:
  it keeps the four locked fields and the 1000×1500 blurred-backdrop poster
  byte-identical to every other item in the library.
- **Two items whose titles differ only in CASE? Lock the title, don't rename the
  folder.** A 2-disc set can rip to two folders that collide on everything but
  capitalisation (`Dhurha vs` / `Dhurha Vs`), leaving the grid showing two
  indistinguishable rows. `title` is just a field: PUT `title.value` +
  `title.locked=1` with a `[Blu-ray]` / `[DVD Bonus Disc]` suffix. In a no-agent
  library a locked title sticks, the folders stay put, the rating keys survive and
  nothing needs re-applying — strictly better than renaming, which makes Plex mint
  new items and discards the summary and poster you just applied.
- **First run writes the summary file and applies nothing.** Edit it, then
  re-run the same command to apply. Editing rules: fix grammar (fan-wiki English
  is often broken), **never add a fact the source doesn't state**, and delete any
  sentence contradicting the date field — the tool warns when the prose claims
  the release year on a different day.
- Plex convention is the **RELEASE year, not the concert year**. The tool warns
  when the folder disagrees; accepting sets Plex to the release year.

### 5. LOOK at the poster — the step nothing else can do

```
Read /mnt/media/Concerts/<folder>/poster.jpg
```

The tool reads year/oaa/summary back from Plex and reports `-> applied`, all
true — while the poster is unreadable. A scan uploaded sideways carries no EXIF
orientation, so it composes *perfectly* into a sideways poster. Fix with
`--artwork-only --rotate {cw,ccw,180}`, which re-does the art alone.

### 6. English subtitles — check EVERY Japanese disc

**Run `list` FIRST. Never assume the disc has none.**

```bash
python3 scripts/plex_subs.py list          # which items have subtitles at all
```

Most of these releases ship **no subtitle track of any kind** — not English, not
even Japanese — and the ripper does pass `--all-subtitles`, so an empty list is
the disc, not the pipeline. the owner does not read Japanese, so on a disc with
dialogue (a tour documentary, backstage footage, MCs between songs) the item is
not really finished until something is there.

**★★ That is a MEASUREMENT, not a property of Japanese discs — and it has been
broken.** The `Dhurha Vs Dhurha` Blu-ray (Warner Music Japan, 2022) ships
official **English, Spanish and Portuguese** PGS: the first disc in this library
to carry any subtitle stream at all. Assuming instead of checking would have
spent a GPU run producing an unproofreadable machine translation to sit beside a
human one. The exception's shape is worth holding — a **2020s major-label release
by a band with a large international following**, where the zero-subtitle discs
are overwhelmingly 2000s Japanese-market pressings. Expect it to get more common,
not less.

Such tracks are **PGS image bitmaps** internal to the mkv, so there is nothing to
install or name, and `list` reports them as internal rather than as an
`external English/srt`.

**Look for a human translation first — always.** A fansub beats anything
generated, and for these discs one occasionally exists:

- Search the **release title + "english subtitles"**, in romaji and in the
  form the fans use (`Jinsei x Kimi Tour Film`, not the library's spelling).
- The scene is **tumblr and wordpress fan blogs**, not OpenSubtitles — that
  site is film/TV oriented and has essentially nothing for Japanese live discs.
  Expect a 2013-era blog post linking a zip on 4shared/MEGA, often with a
  password in the post body.
- **A download that needs an account is the owner's to fetch** — 4shared is
  login-walled now. You need the link, the password and the file name.
- Check WHICH disc it covers. A tour release is usually a live disc plus a
  documentary disc, and the subs are almost always for the documentary.

Then install it — never by copying the file into place by hand:

```bash
python3 scripts/plex_subs.py install --item <rk> --srt /tmp/x.srt --dry-run
python3 scripts/plex_subs.py install --item <rk> --srt /tmp/x.srt
```

It normalises the encoding (a fansub is rarely UTF-8 and never says which it
is), reports cue count and timing, **checks the last cue against the video's
real duration**, writes the `<video>.en.srt` sidecar, refreshes Plex and reads
the stream back. The duration check is the one that matters: a file timed to a
different release looks perfect everywhere else and is fixed with `--shift`.

**If no fan translation exists — the normal case — generate one:**

```bash
venv/bin/python scripts/plex_subs.py generate --item <rk> --stage-only
```

WhisperX transcribes the Japanese, the full model translates it here, and it
lands through the same install path.

**★★ TRANSCRIPTION RUNS ON THE PLEX HOST'S GPU. NEVER YOUR WORKSTATION'S.**
The GPU was put in the Plex host for exactly this reason — **your workstation
is to stay out of every Plex process**, and "it was faster on the other card"
is not a reason, it is the thing being prevented. That machine is your
workstation, not a render farm this pipeline may reach into.

**The command above now honours that** (rewired 2026-09-07). `plex_subs.py` runs
its whisperx workers on this machine under `~/whisper/venv` — no staging, no
sftp, no far side — and there is no PC lane left to fall into.
`tests/test_plex_subs_host.py` scans the GPU lane's *code* for
ssh/sftp/PowerShell and fails if one comes back. The old routing rested on the
premise that *"the Pi 5 has no CUDA device, so that split is forced, not
chosen"*, dead since the x86 cutover — the same stale-premise shape as the
AV1/BIF offload, which is retired for the same reason (AV1 is built locally now
that `-skip_frame nokey` is honoured: 120 s of film decodes in 0.4 s with it
against 22.4 s without).

**Diarization** (the MC lane's speaker labels, and `whisperx-clips/`) needs a
HuggingFace token for the gated `pyannote/speaker-diarization-3.1`. It lives in
the repo `.env` as **`HUGGING_FACE_TOKEN`** — note the spelling: HF's own tooling
says `HF_TOKEN`, so both readers accept `HUGGING_FACE_TOKEN`, `HF_TOKEN` and
`HUGGINGFACE_TOKEN`. A token present under the "wrong" name reads exactly like a
missing one, and the failure lands minutes into a GPU run.

Running the worker by hand is still the quickest way to test the card:

```bash
set -a; source ~/whisper/cuda-libs.env; set +a     # cuBLAS/cuDNN paths - required
~/whisper/venv/bin/python scripts/plex_subs_cuda.py \
    --audio <16k mono flac> --out <json> --language ja
```

**★★ The 1080 Ti is PASCAL (sm_61), and it bit twice on the way home — both
measured 2026-09-07, neither guessable from the card being "available":**

- **`float16` and `int8_float16` are refused outright** by ctranslate2 on this
  card (`Requested float16 compute type, but the target device or backend do not
  support efficient float16 computation`). The workers used to hardcode
  `float16` because they were written for the 3080; they now ASK the device
  (`plex_subs_cuda.pick_compute` reads `ctranslate2.get_supported_compute_types`
  and takes the best supported, landing on `int8_float32` here), so no flag is
  needed. `--compute-type` still forces one by hand. It is genuinely fast:
  90 s of audio in **7.0 s**, and the full 22-min documentary in 48 s.
- **`torch.cuda.is_available()` LIES on this box.** It returns `True` and
  `get_device_name(0)` proudly says *NVIDIA GeForce GTX 1080 Ti* — and then the
  first real kernel launch dies with `CUDA error: no kernel image is available
  for execution on the device`, because the installed **torch 2.8.0+cu128 ships
  no Pascal kernels**. Availability is not usability; prove the card with an
  actual kernel, never with `is_available()`. The practical consequence is that
  **whisperx itself cannot run in `~/whisper/venv` as installed** — its VAD and
  its alignment pass are both torch, so it dies before transcribing and
  `--no-align` does not save it. Plain **faster-whisper / ctranslate2 does
  work**, which is why the hand path above is worth having.

  **FIXED 2026-09-07** by reinstalling torch from the cu126 index at the SAME
  version (`torch==2.8.0+cu126`, plus matching torchaudio/torchvision), which
  keeps every other pin valid. whisperx now runs here end to end, alignment
  included. Note the arch list still prints `sm_60` and never `sm_61` — and the
  kernel runs anyway, so **the arch list is not authoritative either**; the only
  test that settles it is executing a kernel. The pre-change venv is kept at
  `~/whisper/venv.bak-cu128` and `~/whisper/pip-freeze-before-cu126.txt`.

Two more things to hold on to:

- **It works on speech and fails on singing.** A documentary or an MC segment
  is a good candidate; a concert's songs come out as garbage. Don't run it on a
  live disc expecting lyrics. (Transcribing the *concert* anyway is still worth
  it as EVIDENCE — see §7, where the sung titles are what pin the chapter map.)
- **Nobody can proofread it.** Whisper's failure mode is fluent, confident
  wrong text. Use `--stage-only`, skim it, and say in your report that the
  track is machine-generated. Expect two mechanical artifacts worth fixing
  before install, both deterministic: **repetition loops** (one phrase emitted
  32× over 18 s; a rehearsal count degenerating into a cycle) and **cues too
  long to read** (300-420 chars held for 30 s). Collapse a back-to-back repeat
  to one occurrence and split an over-long cue at sentence boundaries inside
  its own span — never re-time a cue outside the window it was spoken in.

**Getting the finished track to actually SHOW is a separate fight when the
target is an EXTRA** (a Featurettes/ file). Measured 2026-09-07: **an external
`.srt` sidecar beside an extra is never indexed** — all 9 extras in this library
that carry subtitles are MUXED and not one is a sidecar — so mux it in with
`mkvmerge` (§7's ext4 round-trip and byte-count rules apply, and the size moves).
Worse, **Plex will not re-read an extra it has already cached**: after the mux
its stored `size` stayed stale through scan, path-scoped scan, `refresh`,
`refresh?force=1`, item `analyze`, section `analyze`, `emptyTrash` and a rename,
while the *main* item in the same folder updated fine. A **Plex restart** is the
known lever — so check `/status/sessions` first and do not restart while the
crew is streaming.

### 7. Name the chapters after the songs, and fill in their thumbnails

A rip lands with generic `Chapter 1`…`Chapter N`. Plex keeps every chapter's
offsets but leaves its `tag` **empty**, so the names are missing, not
unsupported — `/library/metadata/<rk>?includeChapters=1` shows the gap.

**★★ LOOK AT THE VIDEO FIRST — many of these discs caption their own songs, and
that is direct evidence where everything below is inference.** A concert film
routinely burns the song title in at the start of each number, so the disc
already names its own chapters and one `ffmpeg` frame per chapter reads them
off. Measured on Sigh's `GQXS-90477` (2026-09-10): a frame at each
chapter start `+20s`, cropped to the lower half, produced a readable title card
for **11 of 15 chapters**, and a second sweep at `+8s` caught the other four —
**15 of 15 identified from the disc itself**, in about a minute, before a single
database was consulted. It is strictly better than a duration match because it
cannot be fooled by two songs of similar length, and it settles the OFFSET
outright: a shifted-by-one name list is impossible when the caption is in the
frame. The chapter-1 sweep also caught the opening sequence's per-member
captions (`Vocal / Bass`, `Guitar`, `Drums`), which is the line-up confirmed
off the video.

Read the chapter starts out of `ffprobe -show_chapters`, then sweep one frame
each. **Crop to the lower half** (`crop=iw:ih/2:0:ih/2`) — the caption sits
there and a half-frame is far easier to read at a glance — and tile them into
one contact sheet so the whole disc is a single look rather than N:

```bash
ffmpeg -v error -ss <chapter_start+20> -i "$F" -frames:v 1 \
       -vf "crop=iw:ih/2:0:ih/2,scale=430:-1" /tmp/cards/ch01.jpg -y
# ...one per chapter, then tile with PIL and Read the sheet.
```

`+20s` caught most of them; sweep `+8`/`+12` for any that come back blank, since
a card can appear and fade before then. A chapter with no card at any offset is
usually the opening or the credits, not a failure.

Do this even when you already have published times, because it is cheap and it
is the only route that proves the mapping rather than inferring it. Then still
run the duration gate below — the captions tell you the NAMES, the 10s test
gates the WRITE, and on that disc the two agreed to within 4.7s.

Where the disc does not caption itself, what decides the mapping is a **duration
match**, and there are three ways to get one. Best is per-track running times
published for *this disc* — Tower Records
prints them, though only for a CD; a label news post usually does not. **Expect
zeros on a video release**: Tower printed `00:00:00` for every track on both the
Galneryus *Vetelgyus* Blu-ray and Maximum the Hormone's *Dhurha Vs Dhurha*, so
treat per-track times as a CD-only feature and plan for the reference-recording
route on anything video.

**★ But a `Blu-ray+CD` set carries its own CD, and the CD half publishes what the
video half never does.** On a release that pairs the film with an audio disc of
the SAME concert, per-track times for the CD are per-track times for your
chapters — the one case where the CD-only rule above works FOR you instead of
against you. Encyclopaedia Metallum prints them per track (Tower and the label
pages did not for `GQXS-90477`); read them off whichever source has the CD
medium, not the video one. Measured there: all fourteen landed within 4.7s,
most under 1.5s, on a disc where nothing published a single Blu-ray timing.
It also reconciles a chapter count that disagrees with the printed tracklist —
15 chapters against 14 tracks resolved as `Evil Dead ~ ENDING`, one printed
track spanning the last two chapters, because ch14+ch15 summed to 247.0s against
a published 248s.

When nothing publishes them for the disc in hand — the normal case for a
bonus live disc packaged inside an album — match against **other recordings of
the same songs** (the gate below). Every route ends in the same 10s test, so the
absence of published times is never a reason to skip the check, only a reason to
source the numbers differently. mkvtoolnix is assumed installed.

**★★ NEVER run `mkvpropedit` directly on the file in `/mnt/media`.** An in-place
mkv header edit there once silently corrupted files — a 148-file batch zeroed
**28 of them (19%)**, every call exiting 0 with nothing in `dmesg` (see the
`mkvpropedit-ntfs3-corruption` memory for the mechanism and the byte-exact
recovery). This is not theoretical for chaptering: the edit measured there
**grew the file by 679 bytes**, and that appended write is exactly what the
filesystem mangled.

**That mount is now ext4 and the mechanism is gone — keep the round-trip
anyway.** Measured 2026-09-07, the `/mnt/media` here is `/dev/sda1 ext4`,
not the Pi's ntfs3, and the bug was specifically ntfs3 zeroing the head of an
appended write (that investigation's own *control* was an ext4 copy, which came
out byte-perfect). So the danger has genuinely lapsed — but the recovery has
lapsed with it: it needs a **donor file from the same release**, and a one-off
concert disc has none, so a failure here is unrecoverable where a corrupted TV
episode was not. Five minutes of copying buys a retry instead of the only copy
of the disc. Work on an **ext4 copy** and write a whole new file back, and
**verify after writing rather than trusting exit status** — that rule never
depended on the filesystem.

```bash
F="/mnt/media/Concerts/<folder>/<file>.mkv"
W=$HOME/mkv-chapters-work
cp "$F" $W/work.mkv && cmp "$F" $W/work.mkv     # verify the copy before trusting it
mkvextract chapters $W/work.mkv > $W/chapters_orig.xml    # this is the UNDO
```

Build the new file by **regex-replacing only the `<ChapterString>` values, in
order**. Never hand-type timestamps — reusing the extracted XML keeps every
`ChapterTimeStart` and `ChapterUID` byte-for-byte, and hand-copying 34 timecodes
is the obvious way to get this subtly wrong. Then assert that the rewrite changed
nothing else: blank every `<ChapterString>` in both the old and new XML and
require the remainder to compare equal.

**Gate the write on an assertion, not an eyeball:** every song chapter must land
within 10s of its published track duration or refuse to write. Measured worst
case on a real disc was **+3.7s**, most under 2s, so 10s is loose — and a
mis-ordered name list cannot ship past it.

**When NOTHING publishes per-track times, run the same 10s test against
reference recordings instead of skipping the gate.** On the Galneryus
*Vetelgyus* Blu-ray MusicBrainz's video medium was blank and Tower Records
printed `00:00:00` for every Blu-ray track while printing real times for all 12
CD tracks — so there was no published duration to test against at all. Look each
song up as a *recording* (`artist:X AND recording:"Y"`), and note that a live
album's entry is usually the closest reference of all. Eight of eleven came
within 10s that way (best +0.7s, worst +7.8s); the other three were live
extensions, checked only for **not being shorter** than studio, since a live take
runs long and never short. A mis-ordered list still cannot survive it — shifting
the names by one breaks all eight at once.

```bash
mkvpropedit $W/work.mkv --chapters $W/chapters_new.xml    # the EXT4 copy, never $F
```

**0.085 seconds on a 13.8 GB file** — a header edit, not a remux. Confirm
`nb_streams` and `duration` are unchanged and that `mkvmerge -i` still lists both
tracks (losing the `Tracks` element is exactly how the ntfs3 corruption presents,
so it is the check that matters). Then write it back as a **new** file, verify it
*on the far side* before destroying anything, and only then rename over the
original:

```bash
cp $W/work.mkv "$DIR/.new.mkv" && sync
sudo sysctl -q -w vm.drop_caches=3        # or the verify just reads page cache
cmp $W/work.mkv "$DIR/.new.mkv" || { rm -f "$DIR/.new.mkv"; exit 1; }
mv -f "$DIR/.new.mkv" "$F" && sync        # atomic, same filesystem
```

Verifying the temp copy *before* the rename means a bad write costs a retry
instead of the file. Use a dot-prefixed temp name so Plex ignores it while it
exists. Budget about four minutes of I/O each way: 13.8 GB copied at ~119 MB/s
(116s) and `cmp` re-read both sides in 111s. An installed `.srt` sidecar is a
separate file and rides through all of this untouched. Then PUT **`refresh` *and*
`analyze`**, or Plex will not re-read the chapters.

- **★ It changes the file SIZE, which breaks the byte-keyed catalogue recovery.**
  Update that file's `bytes` in `/mnt/media/STAGING/.dvdrip-logs/*.json`
  afterwards — the log is supposed to hold the FINAL size and the final size
  moved. It degrades to the title key, so a disc that was *also* renamed loses
  both paths at once. This is the one known thing that defeats the byte-count
  design: it is immune to renaming, not to remuxing.
  **★★ Anything else keyed on that byte count goes stale at the same moment**
  — a catalogue, a checksum manifest, a backup index — and nothing checks them
  against each other, so a chapter edit leaves them disagreeing with the disk
  while the rip log still reads correct. Fix every copy
  (measured: ANKM-0038 moved 13199572245 → 13199573500, +1255 bytes for 24
  names). Re-run `catalog_from_rip_logs(title, file_path)` afterwards and confirm
  it still returns the catno; that is the one-line proof the recovery survived.
- **Songs bare, talk as `MC`, extras as `Bonus - <x>`.** No numbering — the
  chapter index already orders them. Label the tiny chapters `MC` as well: a
  9-second one turned out to carry a song announcement.
- **Bonus songs rarely have published times.** MusicBrainz *studio* durations
  discriminate the order well enough — a live take runs slightly long, never
  short — and the last one falls out by elimination.
- If you generated an MC track (§6), its "Please listen to X" announcements are a
  free third check: they land within seconds of the chapter they introduce. It
  need not be an announcement — on *Vetelgyus* the ASR caught the sung line
  "Can't live / without you" **9.6s** from the start of the chapter that the
  printed order says is `Can't Live Without You`, which pins the whole mapping's
  OFFSET independently of any duration. Worth running §6 before §7 for that alone.
  Sung lyrics leaking into an MC track are normally noise; here they were evidence.

**Then the thumbnails, or the chapter menu is a wall of blank tiles.** They are a
separate Plex job from the names, and it is switched off here: `GET /:/prefs` →
**`GenerateChapterThumbBehavior`** reads `never`, though Plex's own default is
`scheduled`. (`GenerateBIFBehavior` is *also* `never` — that one is deliberate,
BIF being driven externally by `scripts/plex_bifgen.py`. Do not "fix" it by
analogy.)

It is a **global** pref, so scope it to the one item and put the restore in a
`finally`, or a crash leaves the whole library queued:

```
GenerateChapterThumbBehavior=asap  →  PUT /library/metadata/<rk>/analyze
  →  poll ?includeChapters=1 until the count STOPS RISING (not until it hits N)
  →  restore never
```

**34 thumbs took 70 seconds** — 10–40 frames per item, nothing like BIF's
thousands. Leave the pref on `never` afterwards, or Plex regenerates over any
replacement at the next maintenance window.

**★★ On a disc you just re-chaptered, let the BIF pass run BEFORE you thumb, or
the timer silently undoes it.** `scripts/plex_bifgen.py` finishes by PUTting
`/library/metadata/<rk>/analyze` so Plex adopts the BIF it wrote — and an
analyze re-creates the media part and drops every `thumb=` attribute. §7's
rewrite changes the file, so `plex-bifgen.timer` (every 30 min) sees a missing
BIF, regenerates it, analyzes, and the item lands back at **0/N**. Measured
2026-08-17 on rk 10804: thumbs made at 10:22 read 22/25, the timer ran
10:38→10:46, and at 10:57 the item was **0/25** with every file still perfect on
disk. So the order is **names → BIF → thumbs**, not just names → thumbs. Either
wait for the timer (`systemctl list-timers plex-bifgen.timer`) or force it with
`sudo systemctl start --no-block plex-bifgen.service` and wait for the unit to
go inactive; once the BIF exists and matches, the next pass skips the item and
the thumbs stick (verified across the following run). This is also why the
advertised count must be re-read at the END of the job — an item can be correct
when you install it and wiped twenty minutes later.

**★★ It is not only the timer's analyze — ANY analyze wipes them, including the
ones you fire yourself.** On WPXL-90072 the thumbs read 23/33, then two
`PUT /library/sections/5/analyze` calls (fired while chasing an unrelated
problem — a stale EXTRA, see §6) dropped the item to **0/33** with all 33 JPEGs
still perfect on disk. So treat `analyze` as destructive to this job, do the
thumbnails **LAST**, and if you must analyze afterwards, expect to re-run the
pass *and* re-install the replacement frames — Plex regenerates the black
originals over them. Re-running is cheap and deterministic (the same 10
chapters were refused both times), but only if you notice, so **re-read the
count after anything that touches the item**.

**Do not poll for `all N`, poll for "stopped rising".** Plex **refuses to
register a pure-black thumb at all** — it writes the black JPEG to the bundle but
emits no `thumb=` attribute for that chapter, so an item whose first and last
chapters open on black tops out at **11/13 forever** and a wait-for-all loop just
burns its timeout. The count is the signal; `all N` is not reachable on a disc
that opens dark. A chapter under ~2 s may get no file at all (rk 10804's 1.5 s
trailing stub did not), so the reachable ceiling can sit below the file count
too.

- **★★ Plex grabs the frame EXACTLY at the chapter start, so a chapter opening on
  a cut from black gets a pure black thumb.** Six of 34 did on a real disc — the
  disc open, one song, and every bonus chapter.
- **★★ A brightness THRESHOLD is what fails, not brightness itself.** A
  `mean < 12` test flagged **18 of 34** and was wrong about twelve of them: a
  blue-lit stage reads 11.4 and is perfectly readable, because it is a dark
  concert. Two tells beat it, and the second is better than the first:
  - *Identical file size* — the dead ones are byte-identical, because they are
    the same pure-black JPEG. **The NUMBER is not portable**: 15027 B is the
    1280×720 figure, while a 720×478 DVD writes its dead frames at **7107 B**
    (853×478). Compare sizes to each other, never to a remembered constant.
  - *Luma is exactly zero* — see the BIF method below. Pure black measures
    **0.00** while the darkest legitimate frame measured on a real disc was
    **9.75**, so the gap looked enormous and carried across any resolution.
  **★★ NEITHER TELL SURVIVED WPXL-90072, so stop deriving the list yourself.**
  Measured 2026-09-07 across its 33 chapters: **no two dead thumbs shared a byte
  size** (the first tell simply never fired), and the two populations **OVERLAP
  on luma** — the ten Plex refused ran 0.00–**3.56** while the ones it accepted
  reached down to **3.31**, so any cutoff mislabels in both directions. That is
  the skill's own *a measurement is not a property* rule catching an earlier
  entry in this same file. **Use Plex's own verdict as the list** (the chapters
  with no `thumb=`, next bullet), treat luma as a way to RANK replacements
  rather than to identify victims — and rank on CONTRAST rather than luma once
  a room has haze in it, per the ★★ note below — and widen the job to any *dark* thumb rather
  than only the refused ones — on that disc 5 accepted-but-murky chapters were
  worth replacing too, taking the floor from 0.00 to 8.86 across all 33.
  Either way, LOOK at the finalists — same rule as the poster in §5.
- **★ Read Plex's own `thumb=` attribute first; it usually already names the
  gaps.** On rk 10804 the three chapters lacking `thumb=` were exactly the three
  dead frames, so the size test only corroborated it. A tell is what you need for
  the *dark-but-registered* case — a chapter Plex advertises whose frame is
  black — not for finding what Plex already told you is missing.
- **Replacing one works ONLY for a chapter Plex already advertises.** Where it
  refused to register (no `thumb=`), the attribute lives in Plex's DB and no file
  write creates it — re-verified 2026-08-17 on rk 10804 ch11/ch17: installed the
  right way, `refresh`ed, still `thumb=None`. Install the good frame anyway (it
  serves at `/library/media/<mediaId>/chapterImages/<idx>`, so it beats black)
  but do **not** expect the menu to change, and do **not** re-`analyze` chasing
  it — that regenerates the black file over your replacement (measured twice).
  For an advertised chapter, Plex serves the new bytes with no re-analyze.
  Storage is `<bundle>/Contents/Chapters/chapterN.jpg`, plain JPEGs at the item's
  own thumb size, owned `plex:plex`; locate the bundle with
  `sudo find ".../Media/localhost" -type d -name Chapters -newermt '-2 hours'`
  (**quote it** — the path has spaces, and unquoted it word-splits into four
  bogus paths that all "fail" convincingly).
- **★★ Do NOT stage the `.part` inside the `Chapters/` directory.** This is the
  one place the `plex_bifgen.py` precedent does not carry: writing `chapterN.jpg.part`
  in there made Plex drop the `thumb=` attribute from **every chapter of the
  item** — the images still served at
  `/library/media/<mediaId>/chapterImages/<idx>`, but nothing advertised them, so
  the menu goes blank while every file on disk looks perfect. Stage **outside
  `Chapters/` but on the bundle's own filesystem**, `chown plex:plex` +
  `chmod 644` there, then `mv` straight onto the target. Verified: replacing all
  four that way held the advertised count steady. Recovery if it happens is one
  more `asap` + `analyze` cycle, then re-replace the right way.
  **Do NOT stage in `/tmp` if it is tmpfs** — it is here (measured
  2026-09-07), a different filesystem from the bundle's nvme ext4, so the `mv`
  silently stops being a rename and becomes a copy under the live name. That
  instruction was written on the Pi, where `/tmp` was on the root ext4 and the
  advice held. `stat -c %d` both paths and require the same device number rather
  than trusting either host's layout; a scratch directory under `$HOME` is on
  the right device on most setups and is already the §7 scratch dir.
- **Check the advertised count against another chaptered item before believing a
  number.** `rk 9974` advertises 34/34, which is what proved 0/13 here was a real
  regression and not just how Plex reports it — the same prove-the-instrument rule
  as the decode check.
- **★★ Use Plex's OWN BIF as the frame index — do not hand-probe the video.**
  `scripts/plex_bifgen.py` has already written
  `<bundle>/Contents/Indexes/index-sd.bif`: a JPEG every **2 s** for the whole
  runtime. Parse it (64 B header; `<III` at offset 8 = version, count, reserved;
  then `count+1` `<II` entries of `(timestamp, absolute_offset)`, the last being
  `0xFFFFFFFF`+filesize; each frame's length is the next offset minus its own)
  and you get every candidate for free, with no decode of a multi-GB file.
  Measured on rk 10804 (4383 frames, 35.9 MB): scoring the frame at each chapter
  start reproduced Plex's own verdict **exactly** — flagged `[11,17,25]`, Plex
  refused `[11,17,25]` — in **0.3 s**, and it cleanly separated pure black
  (0.00) from six dark-but-fine chapters (9.7–11.1) that a threshold would have
  condemned.
  Two limits decide how you use it: frames are **320 px wide** (Plex's chapter
  thumbs on that disc were 853×478), so the BIF is an **index, not the image
  source** — find the timestamp with it, then take ONE full-res `ffmpeg` frame
  there; and slots **snap to the nearest keyframe**, so 4383 slots held only
  ~1484 distinct images (effective resolution ~6 s, and the full-res frame at
  that timestamp may differ slightly from the preview — look at what you
  actually extracted, not at the thumbnail that led you to it).
- **The old blind ladder (+3/+6/+10/+15/+20/+30 s) is front-loaded and misses
  long chapters.** All six probes sit in the first 30 s, so on a **431 s** song
  that opens dark and lights up two minutes in, it settled for mean **28.1**
  while the BIF found mean **99** at +168 s — 40 candidate frames against 6
  guesses. Keep the ladder only as the fallback when no BIF exists yet. Extract
  the winner at `scale=<Plex's own chapter-thumb size> -q:v 3` (match what the
  bundle already holds; it is *not* always 1280×720). LOOK at every pick before
  installing it. On a chapter that is dark end to end — an intro in a blacked-out
  hall, a credit roll — the brightest frame within the cap is the answer and it
  will still measure ~8–10; that is not a failure, it is the chapter, and it
  beats pure black.
- **★★ RANK BY CONTRAST, NOT BRIGHTNESS — the brightest frame on a big-stage
  show is usually a washed-out one.** Backlights and haze flood the lens, and
  such a frame has a very high mean and almost no detail. Measured 2026-09-10
  across both discs' BIFs: on `SEXL-79` the **top four frames by mean luma are
  all unusable** — three identical haze-blown shots (luma 180) and a microphone
  lost in a lens flare (luma 164) — while ranking the same 4085 frames by
  standard deviation puts a clean, well-exposed portrait first. Contrast demotes
  the worst offender from **#1 to #592**, and the second from **#4 to #1276**.
  It costs one extra number from the histogram you are already reading:
  ```python
  h = im.convert('L').histogram(); n = sum(h)
  mean = sum(i*c for i,c in enumerate(h))/n
  sd   = (sum((i-mean)**2*c for i,c in enumerate(h))/n) ** 0.5   # rank on this
  ```
  **A clipping penalty is NOT the fix, and gets it backwards.** Tested on the
  same two discs: the most-CLIPPED frames are the GOOD ones — a stage lamp or a
  bright cymbal in shot, 4.7–5.5 % of pixels at 255, and both were sharp usable
  photographs — while the washed-out frame that actually needed rejecting clipped
  **0.10 %**. Penalising clipped pixels would throw away the best candidates and
  keep the one you are trying to avoid. Haze is low variance, not blown highlights.
  **One number catches BOTH failures, which is the real reason to prefer it.** A
  low `sd` is a frame with nothing in it, whether it is blown white or flat black,
  so the same test rejects the haze shot AND the near-featureless dark one that a
  brightness floor waves through. Measured on `SEXL-79`'s installed thumbs: ch26
  reads luma **64** — a perfectly respectable brightness that no floor would
  flag — at `sd` **14**, and it is a blue smear with no subject in it; ch11–ch14
  and ch17–ch23 sit at `sd` 4–10 and are near-black stage washes. Rank on `sd`
  and pick a floor on `sd` (~25 on these discs), not on luma.
- **Whether this bites depends on the ROOM, which is why it can go unnoticed.**
  On `GQXS-90477` — a dark club with no haze — luma ranking picked fine frames
  and its brightest frame (luma 142) was a good warm shot of the guitarist, so
  nothing looked wrong. The same code on an arena show with backlight haze picks
  garbage four times out of four. Rank by contrast on every disc; it costs
  nothing on the ones that did not need it.
- **Re-check the poster after `analyze`.** `thumb` is NOT a locked field on any
  item in this library, so an analyze is in principle free to replace the hand-made
  jacket with a video frame. It did not here — the served bytes stayed md5-identical
  to `poster.jpg` — but confirm rather than assume, since §5's whole point is that
  nothing else can judge the picture.

### 8. Report

rk, `year`, `originallyAvailableAt`, summary length, track count, whether
`thumb`/`art` were picked up, whether the chapters were named and their
thumbnails filled (and how many needed replacing), whether the item
has English subtitles and where they came from (fan translation,
machine-generated, or none exists) — and anything you left owed, including any
fact no source corroborated: "nothing corroborated it" is a finding, not a
silence. Name where the
cover came from — if it is a video still or a reissue's jacket rather than this
pressing's, say so.

### Rules that cost real time to learn

- **MusicBrainz `score` is text similarity, NOT confidence.** A false positive
  scored 100. No threshold on it is a safety gate.
- **A blocked source must never read as an empty one.** A 403 and a genuine
  "not in this database" are the same empty list, and only one is a fact.
- **A measurement is not a property.** "Every disc ships zero subtitles" was true
  of every disc measured, got written down as a fact about Japanese releases, and
  a 2022 disc broke it (§6). Re-run the check; don't cite the conclusion.
- **★★ GPU work stays on the PLEX HOST. A faster card in your workstation is
  off limits.** The GPU was installed here precisely so your workstation is
  never pulled into a Plex process, so "the other card was right there / was
  faster" is the mistake, not a shortcut. The tools no longer make it FOR you — the
  subtitle lane and the AV1/BIF lane both run locally now, and
  `tests/test_plex_subs_host.py` fails if a PC lane reappears — but the way it
  happened the first time was that `plex_subs.py generate` had always been wired
  to the PC and **the wiring read as permission**. So: **check where a job will
  actually run before starting it**, and re-read §6 for the Pascal traps
  (compute type is derived, not `float16`; `torch.cuda.is_available()` returns
  True on a card that cannot execute a kernel).
- **Never accept a date from a single source without saying so.** A catalogue
  number is exactly the kind of fact nobody re-checks.
- **A wiki's prose states facts, and they can be wrong** — no better than its
  infobox, which is where a wrong catalogue number already came from once.
- Nothing here needs a service restart; these are standalone scripts.
