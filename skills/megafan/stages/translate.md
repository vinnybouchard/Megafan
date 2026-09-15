# Translate ONE page of Japanese prose — worker stage `translate` of the megafan skill

You are ONE worker in a parallel run of this skill. The coordinator
(`SKILL.md`) has already done §0–§2.5 — mode, rk, catalogue number, disc
shape — and wrote them to `job.json`. `<rk>` below is that rating key.

**Inputs:** `job.json` plus the page the coordinator named in your prompt (`page`: the scan file, what it is, and its tiles under `/tmp/concert/<rk>/tiles/<scan-stem>/`). One worker per page — you translate exactly one.

**Outputs** (under `/tmp/concert/<rk>/translate/<scan-stem>/` — YOUR page's own folder, since one worker runs per page and their reports must not overwrite each other): `<CATNO>-<page>.txt` (the English), `<CATNO>-<page>.en.jpg` (and `-2.jpg` if continued), `report.md`. Filing them alongside the scans is the coordinator's to do.

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

### 7.55 Translate the pages that are solid Japanese prose

Most of what you tile is lists — a tracklist, a spec strip, a credits panel — and
the catalogue transcribes those into `tracks:` and `credits:` already. But a lot
of these releases also carry PROSE: a liner essay, the band talking about the
recording, an interview. None of it reaches the owner, and it is routinely the only
place a fact is stated at all — `NZS-731`'s concert date is in its liner essay
and nowhere else on the object, and the pass before this one called that date
"very likely unobtainable".

**WHAT IT COSTS, because the instruction is worthless without it.** Measured on
NZS-731's three-page liner (2026-09-13): 18 tile reads at translation grade,
about 2,500 words of English, and three render-and-look cycles. That is a
sizeable fraction of a whole rescan pass. So:

- **A liner essay — a few pages — just do it.** It is where the facts hide.
- **A long booklet: say what it will cost and ASK.** Twenty pages of prose is
  its own job, not a step inside this one.
- **NEVER in `--batch`.** Nobody on this end can proofread a Japanese-to-English
  translation, which is the §6 machine-subtitle problem exactly; unattended is
  the one mode where a confident wrong paragraph goes out unseen. `--batch` does
  not do judgement work and this is judgement work.
- **A page of LISTS is not prose.** A back panel or a credits panel is already
  transcribed into `tracks:` and `credits:`; translating it again buys nothing.
- **★★ NEVER TRANSLATE THE LYRIC PAGES.** Most of these booklets print the words
  to every song, and they are the one kind of page that is emphatically out of
  scope — not because of cost, but because a translation of a song lyric is a
  DERIVATIVE WORK of the whole song, and this renders it onto a page that gets
  published to a public website. That is a different act from reproducing a
  jacket at thumbnail size to identify a release, and none of that reasoning
  carries over.
  The catalogue has no use for them either: a lyric settles no catalogue
  question, and what the lyric pages ARE good for is already taken — on NZS-731
  the fact that they skip track 3 is what proved `侍's` an instrumental, and
  that is a structural observation about the page, not its content.
  Skip them, and say in the §8 report that you did.

Then, for each page that qualifies:

```bash
# you have already read the tiles; write the English to a file, then:
python3 scripts/translate_page.py --text /tmp/concert/<rk>/translate/<scan-stem>/<CATNO>-liner-page-1.txt \
    --like ~/disc-scans/<CATNO>/<CATNO>-liner-page-1.jpg \
    --out  /tmp/concert/<rk>/translate/<scan-stem>/<CATNO>-liner-page-1.en.jpg \
    --title "<CATNO> — liner, page 1" --subtitle "<what the page is>"
```

- **Read the tiles for TRANSLATION, not for facts.** They are different jobs and
  the first does not give you the second: this session's own fact pass through
  `NZS-731`'s liner captured the gist of every tile and still had to re-read all
  six to write the page, because a gist is not a translation and will quietly
  invent connective tissue if you let it.
- **Mind the column order.** These pages are two-column, left column full height
  and then the right — so the reading order is `r1c1 → r2c1 → r3c1 → r1c2 → …`,
  not tile order. Look at the whole page downscaled once before assembling, or
  you will splice the halves together in the wrong sequence and it will read
  almost plausibly.
- A page that breaks mid-sentence should SAY so and name where it continues.
  Do not finish the sentence for it.
- The script **refuses** text that will not fit rather than clipping it; pass
  `--continued` to spill onto `-2.jpg`.
- **It also refuses a character the face cannot draw**, and that one WILL fire:
  DejaVu has no CJK and no `※`, so a sentence explaining that somebody now
  writes their name differently is refused rather than set as empty boxes.
  Romanise it, or say it in English — `(who now writes their name with different
  characters)` is what NZS-731 uses — write it in the third person plural if you do not know the person's pronouns.
- **LOOK at every page it produces, including the `-2`.** Three bugs on the
  first disc through this each produced a page that was *rendered perfectly* and
  wrong — nine tofu boxes, a continuation page of one-line stanzas, and then one
  unbroken slab with the sign-off run into the last quote. None of them raised
  anything. This is §5's rule about the poster, for the same reason.
- Keep the `.txt` you set each page from beside the rendered image. Whatever
  reads these later wants both, and the text is the only reviewable half.

**It is NOT a source, and the record must not treat it as one.** Cite the scan.
Every rendered page says as much on its own face, because an image gets saved
and shared away from the page that framed it — same reasoning as the
machine-subtitle note in §6.

(Filing the finished pages is the coordinator's — you name them in your report.
The long-booklet "say what it will cost and ASK" rule is now the COORDINATOR's
call, made before you were spawned; if you were spawned, translate the page.)

---

## Report (`report.md`, required lines)

- `page:` scan file, what it is, tiles re-read for translation M/M, column order used
- `out:` `.txt` + `.en.jpg` (+ `-2.jpg`), LOOKED at every rendered page: no tofu, no one-line stanzas, no run-on slab
- `refused:` any character the face could not draw and how you rendered it
- `facts found:` anything the prose states that the catalogue lacks (a date, a venue, a member change) — quoted, for the coordinator
- `NEEDS OWNER:` one line per thing only a person can settle (or `NEEDS OWNER: none`).
- `OWED:` anything you started and did not finish, or deliberately left (or `OWED: none`).
