# Apply the metadata, then LOOK at the poster — worker stage `apply` of the megafan skill

You are ONE worker in a parallel run of this skill. The coordinator
(`SKILL.md`) has already done §0–§2.5 — mode, rk, catalogue number, disc
shape — and wrote them to `job.json`. `<rk>` below is that rating key.

**Inputs:** `job.json`; `../facts/{summary.txt,tracklist.json,facts.md,report.md}`; `../covers/{cover.png,report.md}` (the rotation it names). In `rescan` mode: only the artwork (`--artwork-only`), never year/oaa/summary — they are locked and were right.

**Outputs** (under `/tmp/concert/<rk>/apply/`): `report.md`; the poster as applied (you LOOKED at `/mnt/media/Concerts/<folder>/poster.jpg`).

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

### 4. Apply

```bash
python3 scripts/plex_concert_meta.py --item <rk> --wiki <wiki> \
    --cover-file /tmp/concert/<rk>/covers/cover.png --summary-file /tmp/concert/<rk>/facts/summary.txt
```

Interactive, so drive it with `printf '<release>\n<page>\ny\ny\n' | …` — but
**read the printed menus in the output**, don't answer blind.

(The bullets on WHERE the tracklist, readings and prose come from moved to
`stages/facts.md` §4a — that worker already did them and handed you the files.
What is left here is the mechanics of the write.)

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

**Assert the item's duration against `job.json` before writing** (the §4 rule
above) — you are keyed on `<rk>` and the facts worker said which disc it is;
the two must agree or you stop and report.

---

## Report (`report.md`, required lines)

- `rk:`, `year:`, `originallyAvailableAt:`, `summary:` chars, `tracks:` N (per disc)
- `route:` tool happy path (`--wiki <w>` + release/page picked) / direct locked route (why)
- `poster:` `-> applied`, LOOKED at it: upright / rotated `<cw|ccw|180>` and re-applied; `thumb`/`art` picked up
- `title:` locked with a suffix (case-collision) or untouched
- `year warning:` folder year vs release year, and what you accepted
- `NEEDS OWNER:` one line per thing only a person can settle (or `NEEDS OWNER: none`).
- `OWED:` anything you started and did not finish, or deliberately left (or `OWED: none`).
