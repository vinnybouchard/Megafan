# Research the facts — worker stage `facts` of the megafan skill

You are ONE worker in a parallel run of this skill. The coordinator
(`SKILL.md`) has already done §0–§2.5 — mode, rk, catalogue number, disc
shape — and wrote them to `job.json`. `<rk>` below is that rating key.

**Inputs:** `job.json`; the network. Nothing from other workers.

**Outputs** (under `/tmp/concert/<rk>/facts/`): `facts.md` (the fact table with the verdicts, what you corroborated and how, the per-disc published runtimes and chapter counts if any page prints them, which disc the item is if the runtime settles it), `tracklist.json` (ordered romanised titles with the reading evidence and any published per-track durations, per disc), `summary.txt` (the prose, already edited by §4's rules), `discogs.json` (release id, artist id, `credited` count, or `none`), `report.md`.

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

### 3. Research BEFORE writing anything

```bash
python3 scripts/plex_concert_research.py --item <rk> --facts-only \
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

### 4a. Where the tracklist, the readings and the prose come from

(Moved from §4. The `apply` worker drives the tool; you SOURCE what it
will write — the wiki page, the romanised setlist, the summary text — and
hand it over as files. Edit `summary.txt` by §4's rules below before you
hand it over: fix grammar, never add a fact the source doesn't state, delete
any sentence contradicting the date field.)

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

## Report (`report.md`, required lines)

- `catno:`, `mode:`, `disc:` (which disc of how many, and what settled it)
- `date:` YYYY-MM-DD + the verdict word (`AGREED`/`ONE SOURCE`/`DISAGREE`) + which sources; say if the jacket must settle it
- `wiki:` the page used for prose/tracklist (`<wiki> / <exact title>`) or `none — direct locked route`
- `tracklist:` N tracks; readings confirmed how; per-track durations from where (or `none published`)
- `summary:` path + char count
- `discogs:` release id / artist id / `credited` count, or `none`
- `runtime:` published per-disc runtimes + chapter counts, or `none published`
- `NEEDS OWNER:` one line per thing only a person can settle (or `NEEDS OWNER: none`).
- `OWED:` anything you started and did not finish, or deliberately left (or `OWED: none`).
