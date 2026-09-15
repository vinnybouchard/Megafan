# Name the chapters, then fill their thumbnails — LAST — worker stage `chapters` of the megafan skill

You are ONE worker in a parallel run of this skill. The coordinator
(`SKILL.md`) has already done §0–§2.5 — mode, rk, catalogue number, disc
shape — and wrote them to `job.json`. `<rk>` below is that rating key.

**Inputs:** `job.json`; `../captions/captions.json`; `../facts/tracklist.json` (published durations, if any); `../subs/report.md` (the MC transcript path — its announcements pin the offset). You run AFTER `apply` and `subs` have finished; nothing else may touch the Plex item after you.

**Outputs** (under `/tmp/concert/<rk>/chapters/`): `report.md`; `chapters_orig.xml` (the UNDO) and `chapters_new.xml` under `$W`; the replacement frames you installed.

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

### 7 (continued). From the caption sweep to the write

The caption sweep (`stages/captions.md`) already ran; start from its
`captions.json`. Names it saw are direct evidence; everything below is the
gate that lets them be WRITTEN, and the route for the chapters it missed.

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
W=$HOME/mkv-chapters-work/<rk>; mkdir -p "$W"
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

**And hold `/run/lock/plex-chapter-thumbs.lock` (`flock -w 3600`) from the `asap`
PUT to the restore.** The pref is global to the SERVER, so another disc's worker
restoring `never` mid-cycle would kill this one's pass, and its `asap` would
queue the whole library behind yours. One holder at a time, always.

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

**★★ And not only that item: a SECTION analyze re-creates the chapter rows of EVERY
item in the section.** Measured 2026-09-14 from Plex's own dated DB backups: those two
Sep-7 calls also zeroed ten other concerts carrying 7–53 thumbs each, and nobody noticed
for a week because nothing re-reads a count you are not working on.

**★★ The ROWS are what dies, not the files — and ANY analyze from ANY source re-creates
them.** Chapter thumbs live in `taggings.thumb_url`; every analyze deletes and re-inserts
that item's chapter rows (fresh ids, fresh `created_at`, empty `thumb_url`) and, with the
pref at `never`, registers nothing — while the JPEGs in `<bundle>/Contents/Chapters/`
sit untouched. So "files on disk, 0 advertised" is the signature of a re-analysis, never
of a deleted picture. Sources seen doing it here: our own cycles (by design), a section
analyze, `plex_bifgen`'s adopt-analyze (a fresh rip, or a BIF regenerated after an mkv
rewrite — the names→BIF→thumbs order above), and **a Plex UPGRADE**: 1.43.3→1.43.4 on
2026-09-11 bumped `media_analysis_version` 7→8 and Plex re-analysed every item on the
server over the following days (the butler's `UpgradeMediaAnalysis` in its 04:00 window,
plus a wave at 03:00 that hit sixteen concert items in the seconds another
program was reading them). That one wiped 9974, 10804, 14540, 16201 and Sigh in a
single four-second burst. **After any Plex upgrade (`grep plexmediaserver
/var/log/dpkg.log`), assume every item's thumbs need re-registering and audit before
believing a menu.** The audit is one read-only query (`Plex SQLite`, `mode=ro` — the
stock `sqlite3` cannot open this file):

```sql
SELECT md.id, md.title, COUNT(t.id) AS chapters,
       SUM(CASE WHEN t.thumb_url<>'' THEN 1 ELSE 0 END) AS advertised,
       datetime(MIN(t.created_at),'unixepoch','localtime') AS rows_created
FROM metadata_items md
JOIN taggings t ON t.metadata_item_id=md.id AND t.time_offset IS NOT NULL
WHERE md.library_section_id=5 AND md.metadata_type=1 GROUP BY md.id;
```

`rows_created` later than the thumb files' mtimes = re-analysed since. Run it against
`…/Databases/com.plexapp.plugins.library.db-YYYY-MM-DD` (Plex keeps three dated
backups) to date a loss. Checked against survivors and **cleared**: a Plex restart, a
section `refresh?force=1` + `emptyTrash`, a sidecar `.srt` install, a poster apply —
none of them wipes.

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
- **★★ THERE IS A WAY TO SET IT AND IT IS NOT YOURS TO REACH FOR.** The bullet
  above is exact — no FILE write creates the attribute — and it stops one step
  short. The attribute is a column: `taggings.thumb_url`, keyed by
  `metadata_item_id` with `time_offset IS NOT NULL` picking the chapter rows out
  of the posters and art. On `LABX-8044` the five refused chapters were exactly
  the five rows holding `''` where every other chapter held
  `/library/media/<mediaId>/chapterImages/<idx>`. Setting those five took the
  item from 21/26 to **26/26**, with the images already on disk and already
  serving at that URL.

  **ASK, EVERY TIME.** The standing rule is *nothing but Plex writes its
  DB*, and that rule is load-bearing — it is the whole reason `plex_bifgen.py`
  writes a BIF file and lets Plex do its own bookkeeping. This was granted once,
  for five rows, after the alternative had been measured and rejected. It is a
  per-occasion exception and not a recipe: a run that does it unasked has broken
  a stated invariant to fix a menu tile.

  **Do NOT "fix" it by moving the chapter mark instead.** That is the tempting
  alternative and it is worse. Plex samples the frame AT the chapter start, so a
  chapter opening on a cut to black is refused; shifting the mark forward to a
  lit frame needed **1–7 s** on this disc, and the AUDIO in every window that
  would skip is PRESENT — peak **−1.6 dB** for ch7, −2.0 for ch17, −1.4 for
  ch21. That cuts real music off the front of five songs to fix a thumbnail.
  Measure the audio before believing a shift is free; here it never was.

  If it IS sanctioned: **use `Plex SQLite`, never the stock `sqlite3`.** Plex
  ships its own build with the custom collation and `spellfix1` compiled in, and
  the stock CLI cannot run `PRAGMA integrity_check` on this database
  (`unknown tokenizer: collating`) or even enumerate its tables
  (`no such module: spellfix1`) — so a stock-CLI "check" tells you nothing.

  ```bash
  DB=".../Plug-in Support/Databases/com.plexapp.plugins.library.db"
  PS="/usr/lib/plexmediaserver/Plex SQLite"
  plexsql(){ sudo LD_LIBRARY_PATH=/usr/lib/plexmediaserver/lib "$PS" "$DB" "$1"; }

  sudo systemctl stop plexmediaserver.service        # checkpoints the WAL
  sudo cp -a "$DB" "$DB.bak-$(date +%Y%m%d-%H%M%S)"  # Plex keeps dated ones too
  plexsql 'UPDATE taggings
             SET thumb_url = "/library/media/<mediaId>/chapterImages/" || "index"
           WHERE id IN (<the ids you listed>);'      # by id, never by predicate alone
  sudo systemctl start plexmediaserver.service
  plexsql 'PRAGMA integrity_check;'                  # expect: ok
  ```

  Reversible three ways over — the backup, Plex's own dated copies, and the fact
  that any future `analyze` simply recomputes the previous state. Then **LOOK at
  what the five now serve** (§5's rule): the attribute being set is not evidence
  the picture behind it is any good.
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

---

## Report (`report.md`, required lines)

- `names:` N written / `refused: <why>`; source per chapter (caption / published time / reference recording / MC announcement / elimination); worst gate delta
- `file:` bytes before → after; `cmp` on the far side passed; `nb_streams`/`duration` unchanged; `catalog_from_rip_logs` still returns the catno; rip-log `bytes` updated — and give the new number in the report, since anything else keyed on that byte count is now stale
- `BIF:` waited for / forced the timer; the item was skipped on the next pass
- `thumbs:` advertised K/N at the END of the job (re-read after everything); replaced M (BIF-ranked by contrast); which chapters Plex refused and why that is not yours to fix (`NEEDS OWNER` if the DB write would be the only lever)
- `poster:` md5 unchanged after analyze
- `NEEDS OWNER:` one line per thing only a person can settle (or `NEEDS OWNER: none`).
- `OWED:` anything you started and did not finish, or deliberately left (or `OWED: none`).
