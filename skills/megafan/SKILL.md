---
name: megafan
description: "Fill in metadata for concert and live-music discs in a Plex library that runs no metadata agent, where the filename is the only thing Plex knows and every field must be written by hand and locked. Researches the disc's catalogue number across MusicBrainz, Discogs, CDJapan and Wikipedia, finds and visually checks cover art, then applies release year, release date, summary, setlist and poster. Also names chapters after songs, fills chapter thumbnails, and handles English subtitles for a disc that ships none. Works for live releases from any band and any country, and is built around the awkward cases: catalogue numbers written inconsistently across sources, databases that disagree about a release date, and imported discs that ship no English subtitle track. Handles one disc or a whole queue, and a RESCAN — re-checking a disc already in the library against better scans of the object. Runs as a COORDINATOR that spawns one worker agent per stage, so research, cover hunting, subtitles and chapter work proceed in parallel and no worker ever stops to ask a question mid-run. Triggers: I ripped a concert DVD, I ripped a live Blu-ray, new item in my Concerts library, fix the metadata for this concert, my concert library has no artwork or dates, set up a no-agent Plex music-video library, name the chapters after the songs, add English subtitles to a Japanese concert disc, add English subtitles to a concert disc that has none, I rescanned a disc I already added, check this disc against my new scans, going through my backlog rescanning."
---
## Megafan — concert-disc metadata (research → apply → LOOK)

For the Plex **Concerts** library (section 5, `/mnt/media/Concerts`), which runs
`tv.plex.agents.none`. No agent means **the filename is the only metadata Plex
has** and it fetches no artwork, so everything below is written by hand and
`.locked=1` — an unlocked field gets re-derived on the next scan, and with
nothing to derive it from Plex stamps the scan date. That is how a 2013 release
came up as 2026.

**You do not rip anything.** The rip is a `.bat` you or someone else
double-clicks on Windows. Your job starts once the file is in the library.

Every rule here was learned from a disc that broke it, and the measurement is
kept beside the rule rather than summarised away — which is why so many carry a
date and a catalogue number. **Read the reasoning before working around a
rule**, and don't compress it out: rediscovering it is the expensive part.

### How this skill runs: one coordinator, parallel workers

One session used to do all of this in one context. It ended up carrying 160
booklet tiles it no longer needed while making the run's hardest judgement
calls — does this Discogs entity describe THIS artist, did a page change who it
is — and it took hours, serially, on stages that share nothing. So this file is
the **coordinator**: it does the cheap serial work (§0–§2.5), writes
`job.json`, and spawns one **fresh worker agent per stage**. Each stage's
procedure lives in `stages/<stage>.md` with its section numbers kept; a worker
reads its own stage file and nothing else of the skill.

```
Phase 0  (you, serial, cheap)   §0 mode · §1 rk · §2 catno · §2.5 shape · any scans waiting?
                                 → /tmp/concert/<rk>/job.json
Phase 1  (spawn together)       facts   covers   scans   subs   captions
                                  │       │        │       │       │
Phase 2  (after facts+covers)   apply ──► chapters (after subs too)   translate ×N (after scans)
Phase 3  (you)                  §8 — merge the reports, and carry every NEEDS OWNER line out
```

| Stage file | Does | Needs first | Touches |
|---|---|---|---|
| `stages/facts.md` | §3 facts, §4a tracklist/readings/prose | catno | network only |
| `stages/covers.md` | §3 covers half: harvest, hunt, LOOK, pick | catno (rescan: the front scan) | network only |
| `stages/scans.md` | tiling, page classification, the title as printed | the scans | reads the scans |
| `stages/subs.md` | §6 whole | rk | GPU (locked), sidecars, extras |
| `stages/captions.md` | §7 caption sweep | rk | reads the video |
| `stages/apply.md` | §4 write + §5 LOOK | facts + covers | the Plex item |
| `stages/chapters.md` | §7 gate → rewrite → BIF → thumbs | captions + facts + apply + subs | the main mkv, the Plex item, `analyze` (the only one) |
| `stages/translate.md` | §7.55, ONE booklet page each | scans (its tiles + page list) | scratch only |

**The coordinator's own rules:**

- **You read worker REPORTS** (`/tmp/concert/<rk>/<stage>/report.md`) — never a
  tile, a cover candidate, a contact sheet or a translated page. Looking is the
  workers' job and each stage file says what its worker must LOOK at; your job
  is to keep enough context free to judge what they tell you.
- **Spawn a whole phase in ONE message** so the workers run concurrently. Use
  the `Agent` tool with `subagent_type: "general-purpose"` — **never `fork`**: a
  fork inherits this file and everything you have read, which is the context
  problem restated. Workers run in the background; you are notified as each
  finishes. Do not poll, do not predict a report you have not read.
- **Nobody is asked anything mid-run.** There is nobody on the other end of a
  worker, so a worker that stops to ask has simply stopped. Workers write
  `NEEDS OWNER:` lines and you collect them into §8. Three asks that used to be
  live are decided this way: a login-walled fansub → the link, the password and
  the filename go in the report; the chapter-thumb database write → refused and
  reported, never done; a long booklet (§7.55) → translate up to **6 prose
  pages** this run and list the rest as owed with the measured cost (one page ≈
  6 tile reads at translation grade, plus a render-and-look cycle).
- **A reversible taste call is yours to make, not to escalate** — which of two
  gradings of the same scan to ship, say. Decide it, ship it, and put the
  one-line reversal in §8 (`--artwork-only --cover-file <the other>`). A
  `NEEDS OWNER` line is for what only the owner can know, or only authorise.
- **Only a missing catalogue number stops anything**, and it stops only the
  workers that key on it (facts, covers, apply, chapters' gate). Still run
  `subs`, `captions` and `scans` — they need the rk and the scans, not the
  catno — and put the ask at the top of §8.
- **Workers PROPOSE; one stage owns each thing outside the scratch dir.** Every
  worker writes under `/tmp/concert/<rk>/<stage>/`, and the few resources that
  live outside it are each held by exactly one stage — the Plex item's fields by
  `apply`, the main mkv and `analyze` by `chapters`, sidecars and extras by
  `subs`. Nothing else is written by two workers at once, which is what makes a
  run safe to interleave with whatever else touches the same library.
- **Only `chapters` may `analyze`, and thumbs are its last act** — so it runs
  after `apply` (the poster must be on before anything analyzes) and after
  `subs` (the extras path-change lever re-mints rating keys, and the MC
  transcript pins the chapter offset).
- **Locks a worker holds, so two discs' runs cannot collide:**

  | Lock | Held by | For |
  |---|---|---|
  | `/run/lock/whisper-gpu.lock` | `subs` | the whole `generate` — 11 GB VRAM, one run fits |
  | `/run/lock/plex-chapter-thumbs.lock` | `chapters` | the global `GenerateChapterThumbBehavior` cycle, `asap` → restore |
  | `/run/lock/musicbrainz.stamp` | every MB call, automatically (`scripts/mb_rate.py`) | MusicBrainz's 1 req/s, honoured ACROSS processes |

- **Scratch is per-rk:** `/tmp/concert/<rk>/<stage>/` for everything a worker
  makes (where `/tmp` is tmpfs that is fine for scratch, and §7 says why thumb
  replacements must NOT be staged there), and `$HOME/mkv-chapters-work/<rk>/`
  for the chapters worker's ext4 copy. `--batch` keeps `/tmp/concert-batch/<rk>/`.

**`job.json`** — write it after §2.5, before the first spawn:

```json
{
  "rk": "10804", "catno": "KSBL-5909", "mode": "fresh",
  "title": "<the Plex item title>", "folder": "/mnt/media/Concerts/<folder>",
  "main": ["/mnt/media/Concerts/<folder>/<file>.mkv"],
  "extras": ["/mnt/media/Concerts/<folder>/Featurettes/<x>.mkv"],
  "disc": {"no": 1, "total": 2, "note": "which disc and what settled it"},
  "set": [{"rk": "10805", "catno": "KSBL-5910", "main": ["…"]}],
  "shoot": "~/disc-scans/KSBL-5909",
  "riplogs": ["<RIP_LOG_DIR>/<f>.json"],
  "scratch": "/tmp/concert/10804"
}
```

`set` is empty for a single disc and `shoot` is `null` when nothing was scanned.
`mode` is `rescan` when §0's mechanical test says so. **For a set, write the same
file under EVERY member's rk** (`/tmp/concert/<member rk>/job.json`, its own `rk`
and `main`), because a per-disc worker is spawned with that rk and reads only there.

**The spawn prompt** — the same three lines for every worker, plus any per-stage
extras named below:

```
You are the `<stage>` worker for the megafan skill, run rk <rk>.
Read /tmp/concert/<rk>/job.json, then follow the file
stages/<stage>.md beside this skill, exactly.
Write everything under /tmp/concert/<rk>/<stage>/ and finish with report.md in
the format that file specifies. Never ask the user; never PUT analyze unless
your stage says so.
<extras>
```

Per-stage extras: `apply`, `chapters` — *"Read the reports of the workers your
stage names before starting."* `translate` — *"Your page is `<scan file>`
(`<what it is>`); its tiles are under `/tmp/concert/<rk>/tiles/<stem>/`; write
under `/tmp/concert/<rk>/translate/<stem>/`."* `scans` on a rescan — *"Also read
SKILL.md §0 first."*

**Routing by run shape:**

- **Fresh rip:** all five Phase-1 workers.
- **Rescan** (§0): `scans` (adversarial) + `covers` (from the scan) in Phase 1;
  `apply --artwork-only` + `translate ×N` in Phase 2. Skip `facts`, `subs`,
  `captions` and `chapters` — UNLESS a cheap check says that job was never done
  on this item (`plex_subs.py list` shows nothing for a disc with dialogue;
  `?includeChapters=1` shows empty tags), in which case run just that one.
  **One more `facts` shape a rescan DOES want:** when `scans` reports a claim the
  locked summary asserts as `NOT ON THE OBJECT` (a concert date, a price, a
  companion disc), spawn `facts` **narrowed to those claims** — name them in its
  prompt — to corroborate them OFF the object. That is verification, not
  re-research, and it is what separates "unsupported by a silent panel but true"
  from "invented from a silent panel".
- **A 2-disc set** (§2.5): one `facts`, `covers` and `scans` for the set; `subs`,
  `captions`, `apply` and `chapters` **per disc** (each spawned with that disc's
  rk; `job.json` carries the `set` list). This is the one place per-disc
  parallelism is safe by construction — one release, one set of scans.
- **`--batch` queue:** §0.1's dry run first, then each NEEDS-YOU disc through the
  phases. Overlapping the NEXT disc's Phase 1 with this disc's Phase 2 is
  permitted — the MusicBrainz stamp, the GPU lock and the thumbs lock exist for
  exactly that.
- **Nothing scanned:** no `scans` worker and no `translate` workers; say so in §8
  rather than inventing a reading of the object from cover candidates.

### 0. Which run is this — a fresh rip, or a RESCAN?

**A rescan is the common case right now** (2026-09, the owner is working through the
already-ripped backlog putting every object on a flatbed), and it is a DIFFERENT
JOB from the one the rest of this file describes. Most of what follows assumes an
item with no metadata and holes to fill. A rescan has neither: it has a finished
record, a live public page, and **claims** — some of which are wrong.

**Detect it mechanically; do not wait to be told.** Whatever the ask was phrased
as, a shoot in `disc-scans-inbox/` belongs to a rescan if the disc already has
both a record and metadata:

```bash
ls ~/disc-scans-inbox/                              # a folder here = scans to read
python3 scripts/plex_concert_meta.py | grep -i "<artist>"   # year+summary already? -> rescan
```

**★★ The danger inverts, and this is the whole point of the section.** A fresh
rip's failure mode is a MISSING fact — visible, harmless until filled. A
rescan's failure mode is a CONFIDENT WRONG fact that is already written down,
already rendered, and already published, and that nothing will ever flag. So the
run is **adversarial**: your job is to try to falsify what the record asserts,
not to fill gaps in it.

Measured on GNBL-1002 (2026-09-13), where the previous pass had phone photos:
the record described an **asterisk key on the back panel** marking three footage
sources, and read a concert date out of "the smallest print". The 600 dpi scans
show the back panel has no asterisk anywhere and never carried that date. A
whole `resolved` bullet and the `conflicts` entry built on it were invention
from a downscaled image — stated with the same confidence as the facts that were
right.

So on a rescan:

- **Treat every `sources: [object]` line as UNVERIFIED**, not as done. Those are
  exactly the lines read off the old photos, and `[object]` is precisely the
  provenance that makes a reader stop checking.
- **Re-read the WHOLE object** under the tiling rule in `stages/scans.md` — not just the open
  questions. The Casiopea fabrication was not in a field anybody had flagged.
- **Do not re-research (§3) and do not `--batch`.** The databases were consulted
  last time; the object outranks them now. Research only a hole the object
  genuinely leaves.
- **Do not re-apply year / oaa / summary** — they are locked and were right.
  What you are fixing is the record, the artwork, and anything the object
  contradicts.
- **Recompose the poster (§5) from the scan.** A phone photo composes into a
  perfectly valid poster with a colour cast and a shadow across it, and every
  step reports success. Measured: GNBL-1002's was purple-washed with a diagonal
  shadow, and `-> applied` the whole time.
- **Check the rendered BODY blocks against the frontmatter.** They do not
  re-render themselves. GNBL-1002's `## Tracklist` was still publishing Discogs'
  9-of-31 list with three misspellings months after the booklet list reached
  `tracks:`, because nothing re-runs `tracks_body` when frontmatter changes.
  Re-render with `dc.tracks_body` / `dc.credits_body` and `_set_body_section`;
  never `apply_tracks`, which rewrites the frontmatter and eats its comments.
- **Report corrections and confirmations separately**, and say plainly which
  previously-recorded claims turned out to be false. That list is the deliverable.

**Routing note for the coordinator:** a rescan spawns `scans` + `covers`, then
`apply --artwork-only` + `translate ×N` — see the routing
table above. The `scans` worker is told to read this §0
too, because the adversarial stance and the corrections list are theirs.

### 0.1 More than one disc waiting? Batch it

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

**Batch note for the coordinator:** `--batch` is still a script and still runs
first; the parallel phases are for the `NEEDS YOU` pile, one disc at a time in
Phase 3.

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

### 2.6 Write `job.json`, spawn Phase 1

Everything §2–§2.5 established goes into `/tmp/concert/<rk>/job.json` (schema
above). Then spawn, in ONE message: `facts`, `covers`, `scans` (if a shoot is
waiting), `subs`, `captions` — or the rescan / set variant from the routing
table. Read each `report.md` as it lands; a report you have not read does not
exist yet.

**Between Phase 1 and 2, decide:**
- `facts` + `covers` both reported → spawn `apply`.
- `scans` listed prose pages → spawn one `translate` worker per page, up to 6;
  more than that is OWED in §8 with the cost, not asked about.
- `scans` said a tile was not read → that scan is OWED; do not let the run
  claim the object was read.
- Any worker reported `NEEDS OWNER` for the catalogue number → hold `apply` and
  `chapters`; everything else proceeds.

### 2.7 Phase 2

`apply` first (it needs facts + covers and nothing else). When `apply` AND
`subs` have both reported, spawn `chapters`. `translate` workers run alongside
either.

### 8. Report

rk, `year`, `originallyAvailableAt`, summary length, track count, whether
`thumb`/`art` were picked up, whether the chapters were named and their
thumbnails filled (and how many needed replacing), whether the item
has English subtitles and where they came from (fan translation,
machine-generated, or none exists) — and any fact nothing corroborated, which
is a finding and not a silence — which pages were prose and got a translation
(§7.55), or that none did, naming any lyric pages you skipped, since that is a
deliberate refusal and not an oversight — **and, per scan, how
many tiles it was cut into and that you read all of them**, which is the
one line that makes "I read the object" checkable rather than assumed; a scan
you tiled but did not finish is an outstanding item, not a rounding error — and
anything you left owed. Name where the
cover came from — if it is a video still or a reissue's jacket rather than this
pressing's, say so.

**Merging:** every line above maps to a line some worker's report was required
to carry; assemble §8 from the reports, in this order, and quote a worker's
`FALSE:` / `refused` / `OWED` lines rather than summarising them. Then the
`NEEDS OWNER` list, deduplicated, at the end — that is the part to read first.

### Rules that cost real time to learn

- **MusicBrainz `score` is text similarity, NOT confidence.** A false positive
  scored 100. No threshold on it is a safety gate.
- **A blocked source must never read as an empty one.** A 403 and a genuine
  "not in this database" are the same empty list, and only one is a fact.
- **A measurement is not a property.** "Every disc ships zero subtitles" was true
  of every disc measured, got written down as a fact about Japanese releases, and
  a 2022 disc broke it (§6). Re-run the check; don't cite the conclusion.
- **★★ A scan is READ EXHAUSTIVELY or not at all — tile it, never crop to find
  (see `stages/scans.md`).** Cropping by eye has no denominator, so a half-read page and a fully
  read one feel identical from the inside: measured 51%/57%/38% on `ESBL-2192`
  while reporting the gap as "two crew pages". The object is scanned *precisely*
  so that nothing is skipped, so skipping any of it forfeits the whole point of
  having scanned it. And never rank a block's worth before reading it — that
  judgement is only available afterwards.
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
