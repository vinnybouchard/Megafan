# Read the object — every tile of every scan — worker stage `scans` of the megafan skill

You are ONE worker in a parallel run of this skill. The coordinator
(`SKILL.md`) has already done §0–§2.5 — mode, rk, catalogue number, disc
shape — and wrote them to `job.json`. `<rk>` below is that rating key.

**Inputs:** `job.json` (`shoot` = the folder of scans, which on a rescan is the set already on disk); in `rescan` mode ALSO read `SKILL.md` §0 — the run is adversarial and the record's claims are what you test.

**Outputs** (under `/tmp/concert/<rk>/scans/`): `object.md` (everything printed on the object that is not a lyric, transcribed: title exactly as printed with its English line if any, spec bar, catno, dates, tracklist as printed, the credits panels, notes), `pages.md` (one line per scan: what it is, `list|prose|lyrics|art`, legible at `--probe`?, rotation needed, tile count), `report.md`.

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

**★★ TILE EVERY SCAN AND READ EVERY TILE. Never crop a scan to find something.**

```bash
python3 scripts/scan_tiles.py <scan.jpg> --out /tmp/concert/<rk>/tiles/<scan-stem> --probe   # is the text legible?
python3 scripts/scan_tiles.py <scan.jpg> --out /tmp/concert/<rk>/tiles/<scan-stem>           # then the full grid
```

It emits an overlapping grid that provably covers every pixel (it refuses to
write a manifest that leaves a gap) and prints a checklist. Read the whole
checklist. **State the tile count in the §8 report** — that is the number that
makes the claim checkable.

Two reasons this is mechanical rather than a reminder:

- **Cropping by eye gives you no denominator, so nothing ever tells you there
  was more.** Measured on `ESBL-2192` 2026-09-12: three credits pages were read
  by hand-cropping "the band block", "the crew block", "the legal block", each
  a fraction guessed to fit the thing being hunted for. Coverage came out
  **51%, 57% and 38%** — and none of that was visible from inside the job. The
  unread remainder was not a tail of crew names: it held the PROMOTERS block
  spanning two pages, the entire VTR CREW, and the fact that the disc was
  **PRODUCED BY Epic Records Japan AND BS FUJI**, so a co-producer was missing
  from the record altogether. The report then called the gap "two crew pages",
  which is a description of content nobody had looked at.
- **You cannot judge what is worth reading before you read it.** "It's just
  crew" was the reasoning, and it was wrong on this disc in two places at once
  (the co-producer above, and the choreographer who staged the six dancers
  already credited). Whether a block earns its transcription is knowable only
  afterwards, so the decision does not belong in the loop.

Tiles **overlap** (15% by default) because a seam is exactly where a line goes
missing while both neighbours look complete. Prefer `--rows` over `--cols` when
a tile exceeds the viewer's 2000px long edge: splitting a text column breaks
lines mid-word and makes you reassemble prose that was never broken.

Resolution still matters for its own reason. The image tool downscales (a
3000×4000 phone photo displays at 1500×2000), and a downscaled booklet reads
*cleanly* while being wrong — `SEXL-79` produced ~30 silent misreads that way
and `Chima` filed as `Clim` on the live public site; on `ESBL-2192` a tour
manager read as "PIROKI" until zoomed, where the jacket says **HIROKI**. That is
what `--probe` settles before you spend N reads on tiles you cannot read.

**The object outranks the fact table.** On `ANKM-0038` the research report said
`ONE SOURCE ONLY (uncorroborated)` for the release date while the jacket in hand
printed `2022.3.9` on its spec bar and the catalogue number on its back panel —
verifying, for free, what one person typed into the ripper at rip time. A printed
jacket is a primary source and beats any database row; when you have one, say so
in the report instead of repeating the script's verdict.

**Classify every page while you are there.** `pages.md` is what decides the
next phase: a `prose` page gets its own translation worker (§7.55), a `lyrics`
page is NEVER translated (that rule is in `stages/translate.md` and it is a
refusal, not an oversight), a `list` page is already transcribed into `object.md`.
Say which scan carries the title block and transcribe the title EXACTLY as printed —
the title as printed is what the catalogue takes, never the filename.

## Report (`report.md`, required lines)

- `scans:` N files; per scan: `<file>: <what it shows> | <list|prose|lyrics|art> | tiles read M/M | rotate <none|cw|ccw|180>` — every tile, or it is OWED
- `title:` as printed (ja + any English line) and which scan
- `object facts:` date on the spec bar, catno on the back panel, anything else the object states
- `prose pages:` the list the translate workers will take (scan + what it is), `lyrics pages:` skipped by rule
- `rescan:` (rescan only) each previously-recorded claim → `confirmed` / `FALSE: <what the scan shows>`
- `NEEDS OWNER:` one line per thing only a person can settle (or `NEEDS OWNER: none`).
- `OWED:` anything you started and did not finish, or deliberately left (or `OWED: none`).
