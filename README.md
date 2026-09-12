# Megafan

**Metadata for concert discs in a Plex library that has no metadata agent** —
where the filename is the only thing Plex knows, nothing fetches artwork, and
every field you leave unlocked gets overwritten on the next scan.

Works for live releases from any band, anywhere. It was built around the
awkward cases rather than the easy ones: no agent and no artwork, catalogue
numbers written three different ways, sources that disagree about a release
date, and imports that ship no English subtitle track at all.

## Install

**Claude Code (recommended):**

```
/plugin marketplace add vinnybouchard/Megafan
/plugin install megafan
```

Then just say what you did:

> *"I ripped a concert DVD"* · *"fix the metadata for this live Blu-ray"* ·
> *"my Concerts library has no artwork or dates"*

**Or use it without Claude Code.** The four tools are plain Python with no
dependencies beyond the standard library, and the procedure is readable
markdown. See [Running it by hand](#running-it-by-hand).

## What it actually does

A Plex library on `tv.plex.agents.none` fetches nothing, which has two
consequences most people discover the hard way:

* **the filename is the entire metadata**, and
* **any field left unlocked is re-derived on the next scan** — and with nothing
  to derive from, Plex stamps *today's date*. That is how a 2013 concert ends up
  with a release year of 2026.

So Megafan writes each field deliberately and locks it. Given a disc it will:

1. **Find the catalogue number** — the disc's real identity, recovered from your
   ripper's logs or read off the case. Everything downstream keys off it.
2. **Research it** across MusicBrainz, Discogs, CDJapan, Metal Archives and
   Wikipedia, and tell you where each fact came from and which sources agree.
3. **Find cover art**, and make you *look at it* before it goes on.
4. **Apply** release year, release date, summary, setlist and poster — locked.
5. **Name the chapters after the songs** and fill their thumbnails.
6. **Handle English subtitles** on a disc that ships none — either installing a
   file you already have, or transcribing only the *spoken* spans of a concert
   so the songs are never fed to the ASR.

It is **assisted, not automatic**, on purpose. A catalogue number identifies a
*release*, not a disc — and a two-disc set, a reissue, and a video-still cover
all look perfectly normal to an API. The skill applies a disc unattended only
when every independent source agrees; anything else it hands to you with the
research already done.

## What the skill drives

| Tool | Job |
|---|---|
| `scripts/plex_concert_meta.py` | Applies year, date, summary, setlist and poster, and locks them. One disc or a whole `--batch`. |
| `scripts/plex_concert_research.py` | Read-only. Gathers the evidence and drops cover candidates in a folder for you to judge. |
| `scripts/plex_subs.py` | English subtitles: install an existing file as a validated sidecar, or transcribe just the talking. |
| `scripts/plex_bifgen.py` | Plex's video-preview thumbnails, generated in parallel. Plex's own butler uses one core. |

## Setup

Only a Plex token is needed to start.

```bash
cp .env.example .env          # add PLEX_TOKEN
```

* **`PLEX_TOKEN`** — [how to find yours](https://support.plex.tv/articles/204059436)
* **`PLEX_URL`** — defaults to `http://localhost:32400`
* **`MUSICBRAINZ_UA`** — **set this.** MusicBrainz requires a User-Agent naming
  the app and a contact for whoever is running it. The default is a placeholder
  on purpose: shipping one person's details in everybody's requests means a
  rate-limit strike earned by a stranger lands on them.

`ffmpeg` and `ffprobe` must be on `PATH`. Subtitle *transcription* additionally
needs `pip install openai`, an `OPENAI_API_KEY`, and a local
[WhisperX](https://github.com/m-bain/whisperX) install; everything else works
without them.

Full variable list in [`.env.example`](.env.example).

## The rip log — how the catalogue number gets in

The catalogue number is the disc's real identity, and the only moment it is free
to obtain is **while someone is holding the case**. By the time a file is in
Plex, nobody knows which of three pressings it came from.

So the tools will read a small JSON file per rip, if you produce one. Point
`RIP_LOG_DIR` at a directory of them. This is entirely optional — without it you
pass `--catalog` by hand and everything else works the same.

**Only three things are read**, however much else you put in the file:

```json
{
  "catalog":  "LHXD-2004",
  "headline": "Nightmare - Gianizm (2020)",
  "files":    [{ "name": "Nightmare - Gianizm (2020).mkv", "bytes": 13199572245 }]
}
```

* **`catalog`** — the number off the spine or the back panel, exactly as printed.
  Do not tidy it: `KSB5 5734` on the case and `KSB5-5734` in the databases are
  both fine, and the search APIs normalise it themselves.
* **`files[].bytes`** — the exact size of each output file. **This is the match
  key, not the title**, and that is the part worth copying if you write your own
  producer. A byte count survives renaming and moving; a title does not. Matching
  on the title has failed three times here for three unrelated reasons — a comma
  inside a band's name, a bonus disc whose headline named a *different* disc of
  the same set, and a doubled artist prefix. Exact equality on an integer is
  immune to all three.
* **`headline`** — whatever the person typed. Used only as a fallback when no
  byte count matches.

Two optional fields the skill will use if present: **`discNo`** and
**`discsTotal`**, which answer "how many discs am I owed" without a single
lookup. A `discsTotal: 2` with only one log present means a disc has not been
ripped yet — worth knowing before you research a release you only half have.

**Encoding:** the files are read as `utf-8-sig`, so a UTF-8 BOM is fine. Windows
tooling writes one by default (`Set-Content -Encoding UTF8`), and a plain
`json.load` would reject it.

Anything can write these. A five-line shell script at the end of your own ripper
will do, or you can write one by hand for a disc you already have. There is no
dependency on any particular ripping tool.

## Running it by hand

```bash
python3 scripts/plex_concert_meta.py                  # what needs work
python3 scripts/plex_concert_research.py --item 4842  # gather evidence, write nothing
python3 scripts/plex_concert_meta.py --item 4842 --catalog AZBS-1015
```

The full procedure — every step in order, and every trap that cost real time to
find — is [`skills/megafan/SKILL.md`](skills/megafan/SKILL.md).
That file is the skill *and* the manual; it is deliberately the only copy, so
there is no second document to drift out of date. It reads fine as plain
markdown whether or not you ever run an agent.

## Where this came from

These tools were carved out of a larger private project and are published as a
standalone copy. Removed, because they only make sense inside that project: the
steps that fed a personal Obsidian disc-catalogue wiki, and references to that
project's own modules and conventions.

Nothing else was changed. The documentation is the original — including every
measured failure behind a rule, because the reasoning is the part that is
expensive to rediscover.

## Licence

MIT. See [LICENSE](LICENSE).
