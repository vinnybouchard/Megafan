# Read the song titles off the video — worker stage `captions` of the megafan skill

You are ONE worker in a parallel run of this skill. The coordinator
(`SKILL.md`) has already done §0–§2.5 — mode, rk, catalogue number, disc
shape — and wrote them to `job.json`. `<rk>` below is that rating key.

**Inputs:** `job.json`; the main file(s). Nothing from other workers — this is what makes it free to run first.

**Outputs** (under `/tmp/concert/<rk>/captions/`): `captions.json` (`[{chapter, start_s, title_seen|null, offset_used}]` per disc file), the contact sheets, `report.md`.

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
       -vf "crop=iw:ih/2:0:ih/2,scale=430:-1" /tmp/concert/<rk>/cards/ch01.jpg -y
# ...one per chapter, then tile with PIL and Read the sheet.
```

`+20s` caught most of them; sweep `+8`/`+12` for any that come back blank, since
a card can appear and fade before then. A chapter with no card at any offset is
usually the opening or the credits, not a failure.

Do this even when you already have published times, because it is cheap and it
is the only route that proves the mapping rather than inferring it. Then still
run the duration gate below — the captions tell you the NAMES, the 10s test
gates the WRITE, and on that disc the two agreed to within 4.7s.

(That gate is the `chapters` worker's — `stages/chapters.md`. Your job ends at
`captions.json`; do not name a single chapter in Plex.)

---

## Report (`report.md`, required lines)

- `chapters:` N per file (from `ffprobe -show_chapters`)
- `captioned:` K of N identified from the disc itself; which offsets it took; the ones with no card at any offset (opening/credits/MC?)
- `line-up seen:` any per-member captions off the opening sequence
- `sheets:` paths of the contact sheets you READ
- `NEEDS OWNER:` one line per thing only a person can settle (or `NEEDS OWNER: none`).
- `OWED:` anything you started and did not finish, or deliberately left (or `OWED: none`).
