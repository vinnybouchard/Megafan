# English subtitles — worker stage `subs` of the megafan skill

You are ONE worker in a parallel run of this skill. The coordinator
(`SKILL.md`) has already done §0–§2.5 — mode, rk, catalogue number, disc
shape — and wrote them to `job.json`. `<rk>` below is that rating key.

**Inputs:** `job.json`; the network; this host's GPU (behind a lock).

**Outputs** (under `/tmp/concert/<rk>/subs/`): `report.md`; the staged transcript(s) it produced (`*.srt`, named in the report — the chapters worker reads a main-disc transcript as evidence for the chapter map).

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
flock -w 7200 /run/lock/whisper-gpu.lock \
    python3 scripts/plex_subs.py generate --item <rk> --stage-only
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
target is an EXTRA** (a Featurettes/ file). Measured 2026-09-07 and **re-tested
directly 2026-09-14**: **an external `.srt` sidecar beside an extra is never
indexed.** The second check is the one to copy, because the first was an
inference from a population — all 9 extras in this library that carry subtitles
are MUXED and not one is a sidecar — and a population always has another
possible explanation. The direct test settles it: `Title 01.en.srt` sits on disk
beside its extra to this day, and Plex reports that extra's subtitle streams as
`NONE`. Somebody installed that sidecar, it never showed, and nothing said so.
Run that check before muxing rather than trusting this paragraph, then mux it in
with `mkvmerge` (§7's ext4 round-trip and byte-count rules apply, and the size
moves).

**★★ AND THE RESTART IS NOT THE LEVER — THE PATH CHANGE IS.** Plex will not
re-read an extra it has already cached: after a mux its stored `size` stays
stale through scan, path-scoped scan, `refresh`, `refresh?force=1`, section
`analyze` and `emptyTrash`, while the *main* item in the same folder updates
fine. (Item `analyze` is not even available — `PUT /library/metadata/<extra
rk>/analyze` is a flat **400**.) This file used to name a **Plex restart** as the
known lever, and that is wrong: on `LABX-8044` a full
`systemctl restart plexmediaserver` did NOT clear it. The three drama extras
still read `NONE` afterwards, and their stored sizes were still the ones from
*before* they had been renamed, so Plex had never re-read those parts at all.
What works is to make the PATH change and then change it back:

```bash
cd "<item>/Featurettes"
for f in *.mkv; do mv "$f" ".hold-$f"; done      # the rows go stale-and-absent
#   refresh?force=1   then   emptyTrash          -> the rows are REAPED
for f in .hold-*.mkv; do mv "$f" "${f#.hold-}"; done
#   refresh?force=1                              -> re-added, bytes actually read
```

Verified on all three at once: fresh rating keys, `size` matching the disk, and
the muxed `English (machine-generated)` track finally visible. The main item's
26 chapters and its 21 chapter thumbnails came through every step untouched,
which is what makes this safe to reach for — unlike `analyze`, which §7 shows is
destructive to thumbnails.

**A path change is the general lever, not a trick for this one case.** Measured
2026-09-12 on Sigh's extras (`Title 03/04/05.mkv` renamed to their printed
titles and `Title 01.mkv` deleted): a path-scoped scan left all four stale names
through 60 s of polling, and then `refresh?force=1` followed by `emptyTrash`
cleared them in one pass. Plex mints **fresh rating keys** for the survivors —
the tell that the rows were reaped rather than updated — so any note holding an
extra's old rating key is stale afterwards, and so is the `install --item <rk>`
line a staging run printed for you earlier in the session.

**The `flock` on `/run/lock/whisper-gpu.lock` is new and is the worker boundary:**
the 1080 Ti has 11 GB and one whisperx run fills it, so two discs' workers
generating at once would OOM each other. Hold it for the whole `generate`.
Also: a sidecar beside the MAIN file is yours to write; the main file's BYTES are
the chapters worker's (it rewrites the mkv after you finish), so mux only into
extras. The path-change lever above uses `refresh?force=1` + `emptyTrash`, which is
allowed; `analyze` is not.

---

## Report (`report.md`, required lines)

- `list:` what `plex_subs.py list` showed for the item and its extras BEFORE you touched anything
- `human translation:` found (link, which disc it covers, installed or `NEEDS OWNER` for a login-walled download) / searched and none
- `generated:` main / extras: cue count, loops collapsed, long cues split, installed as sidecar or muxed; `machine-generated` stated
- `extras:` the path-change lever run or not; the FRESH rating keys of any extras Plex re-minted (old ones are dead)
- `transcript:` path(s) to the staged `.srt` for the chapters worker
- `NEEDS OWNER:` one line per thing only a person can settle (or `NEEDS OWNER: none`).
- `OWED:` anything you started and did not finish, or deliberately left (or `OWED: none`).
