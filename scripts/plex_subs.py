#!/usr/bin/env python3
"""English subtitles for the Japanese discs in the Plex Concerts library.

Two lanes, because the two sources of a subtitle are completely different jobs:

  install   a subtitle file that already exists (a fansub, a purchased track) is
            validated, normalised to UTF-8, sanity-checked against the video's
            real duration, and placed as a Plex sidecar.

  mc        no subtitle exists anywhere and the disc is a CONCERT: the spoken
            spans are found first and only those are transcribed, so the songs
            are never fed to the ASR. This is the lane to use.

  visual    the text nobody says out loud: title cards, intertitles, signs,
            forum posts filmed off a monitor. Frames are sampled, grouped into
            one span per screen, triaged on the cheap tier and read on the full
            one - into a WORKSHEET the owner corrects, because a filmed screen
            makes the model invent fluent wrong lines (see the block above
            do_visual_scan). `visual apply` folds the corrected file into the
            speech subtitle and installs one merged sidecar.

  generate  the older whole-disc lane: audio is extracted on
            the host, transcribed by WhisperX on the PC's GPU, translated to
            English here, and written through the SAME install path.

**`install` is always the better answer when it is available.** A human fan
translation is worth more than anything this file generates, and the machine
lane exists because for most Japanese live/tour discs nobody has ever made one.

Both lanes end at a sidecar `<video>.en.srt` next to the media. That works on
the Concerts library despite `tv.plex.agents.none`, because a sidecar is found
by local file scan and needs no metadata match. Nothing is re-encoded and
nothing is written inside the .mkv, so every result is undone by deleting one
file.

The GPU half runs on THIS machine, on its own GPU (a GTX 1080 Ti here). It used to be a
host/worker split across ssh to the owner's Windows PC, on the stated premise
that "the Pi 5 has no CUDA device, so that split is forced, not chosen" - a
premise that died with the x86 cutover. The rule now is the opposite and it is
about ownership, not speed: **your workstation stays out of every Plex
process**, which is why that card is in this box. Do not reintroduce a PC lane, even as a fallback.

The driver still decides what to do, owns every write into the library, and
verifies what comes back; the workers are still dumb, handed a file and a
destination. They simply no longer need a network to be handed one.

Usage (from the repo root; `generate` also needs the `openai` package):

    python3 scripts/plex_subs.py install --item 8186 --srt /tmp/x.srt
    python3 scripts/plex_subs.py generate --item 8186
    python3 scripts/plex_subs.py list
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLEX = os.environ.get("PLEX_URL", "http://localhost:32400")
UA = os.environ.get("PLEX_SUBS_UA", "plex-subs/1.0")

# The GPU half runs HERE, on this machine's own GPU.
#
# It used to stage the audio to the owner's Windows PC over ssh/sftp and run it
# on that machine's RTX 3080. That is now FORBIDDEN, and not for performance
# reasons: the 1080 Ti was put in this box precisely so your workstation is never
# pulled into a Plex process. Do not reintroduce a PC lane here, and do not add
# one "as a fallback" - a fallback is just the old behaviour with extra steps.
#
# Running locally also deletes most of the old machinery. There is no far side,
# so nothing is staged, nothing is fetched, no checksum guards a transfer that
# no longer happens, and no remote temp files need sweeping: the worker reads
# the audio in place and writes its JSON straight to the destination.
WHISPER_PY = Path(os.environ.get("WHISPER_PYTHON")
                  or str(Path.home() / "whisper/venv/bin/python"))
# cuBLAS/cuDNN ship inside that venv rather than on the system loader path, so
# ctranslate2 cannot find them without this. Sourcing it is not optional.
WHISPER_CUDA_ENV = Path(os.environ.get("WHISPER_CUDA_ENV")
                        or str(Path.home() / "whisper/cuda-libs.env"))

WORK_ROOT = Path(os.environ.get("SUBS_WORK_ROOT")
                 or "/mnt/media/.subs-work")

# Translation runs on the full tier: a documentary's spoken Japanese is exactly
# the kind of context-dependent text a mini model flattens. Both ids are env
# seams so you can move the whole script to another tier in one place.
MODEL = os.environ.get("PLEX_SUBS_MODEL", "gpt-5.6-terra")
# The visual lane triages frames on the cheap tier before spending the full one
# on a read.
TRIAGE_MODEL = os.environ.get("PLEX_SUBS_TRIAGE_MODEL", "gpt-5.6-luna")
BATCH_SEGMENTS = 40
CONTEXT_LINES = 3

SRT_TIME = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


# ------------------------------------------------------------------ plex ---
def plex_token() -> str:
    tok = os.environ.get("PLEX_TOKEN")
    if tok:
        return tok
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("PLEX_TOKEN="):
                return line.split("=", 1)[1].strip().strip("\"'")
    sys.exit("No PLEX_TOKEN in the environment or .env")


def plex_xml(path: str, token: str, method: str = "GET", **params) -> ET.Element:
    params["X-Plex-Token"] = token
    url = f"{PLEX}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method=method)
    with urllib.request.urlopen(req, timeout=30) as fh:
        body = fh.read()
    return ET.fromstring(body) if body.strip() else ET.Element("empty")


def concerts_section(token: str) -> str:
    for d in plex_xml("/library/sections", token).findall("Directory"):
        if (d.get("title") or "").lower() == "concerts":
            return d.get("key")
    sys.exit("No library section called 'Concerts'")


def item_media(token: str, rk: str) -> dict:
    v = plex_xml(f"/library/metadata/{rk}", token).find("Video")
    if v is None:
        sys.exit(f"No item with ratingKey {rk}")
    part = v.find("./Media/Part")
    if part is None or not part.get("file"):
        sys.exit(f"Item {rk} has no media file")
    streams = [
        {
            "type": s.get("streamType"),
            "codec": s.get("codec"),
            "lang": s.get("language") or s.get("languageCode") or "",
            "title": s.get("title") or "",
            "external": s.get("key") is not None,
        }
        for s in part.iter("Stream")
    ]
    return {
        "rk": rk,
        "title": v.get("title") or "",
        "file": part.get("file"),
        "duration_s": (int(part.get("duration") or 0) or None) and
                      int(part.get("duration")) / 1000.0,
        "streams": streams,
        "subs": [s for s in streams if s["type"] == "3"],
    }


def refresh_item(token: str, rk: str) -> None:
    plex_xml(f"/library/metadata/{rk}/refresh", token, method="PUT", force="1")


# ------------------------------------------------------------------- srt ---
def _ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def decode_subtitle(raw: bytes) -> tuple[str, str]:
    """Return (text, encoding). A fansub is rarely UTF-8 and never says so.

    Order matters: utf-8-sig before utf-8 (a BOM must not survive into cue 1's
    index, which silently breaks the first subtitle), then the two encodings a
    2013-era Japanese fansub is actually written in, then a lossy last resort so
    a stray byte cannot cost the whole file.
    """
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replaced)"


def parse_srt(text: str) -> list[dict]:
    """Parse SRT into cues. Tolerant on purpose - hand-timed files are messy."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[dict] = []
    for block in re.split(r"\n{2,}", text):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        m = None
        body_at = 0
        for idx, ln in enumerate(lines[:2]):
            m = SRT_TIME.search(ln)
            if m:
                body_at = idx + 1
                break
        if not m:
            continue
        h1, m1, s1, f1, h2, m2, s2, f2 = m.groups()
        start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(f1.ljust(3, "0")) / 1000
        end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(f2.ljust(3, "0")) / 1000
        body = "\n".join(lines[body_at:]).strip()
        if body:
            cues.append({"start": start, "end": end, "text": body})
    return cues


def write_srt(cues: list[dict], dest: Path) -> None:
    out = []
    for i, c in enumerate(cues, 1):
        out.append(f"{i}\n{_ts(c['start'])} --> {_ts(c['end'])}\n{c['text']}\n")
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_text("\n".join(out), encoding="utf-8")
    os.replace(tmp, dest)


def wrap_line(text: str, width: int = 42) -> str:
    """Two-line wrap. Long single lines get cropped by some clients."""
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines[:2]) if len(lines) <= 2 else "\n".join(
        [lines[0], " ".join(lines[1:])])


# -------------------------------------------------------------- ffprobe ---
def video_duration(path: str) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=120, check=True).stdout.strip()
        return float(out)
    except Exception:
        return None


# ------------------------------------------------------------- checking ---
def sanity_report(cues: list[dict], duration: float | None) -> list[str]:
    """What is WRONG with this subtitle file, stated plainly.

    A subtitle that is simply offset looks perfect in every automated check
    except this one: its last cue lands nowhere near the end of the video. The
    numbers below are the only cheap evidence that a file belongs to this rip
    rather than to some other release of the same show.
    """
    notes = []
    if not cues:
        return ["NO CUES PARSED - not an SRT, or an encoding this could not read"]
    first, last = cues[0]["start"], max(c["end"] for c in cues)
    notes.append(f"{len(cues)} cues, first at {_ts(first)}, last ends {_ts(last)}")
    if duration:
        notes.append(f"video runs {_ts(duration)}")
        if last > duration + 5:
            notes.append(
                f"** LAST CUE IS {last - duration:.0f}s PAST THE END - this file is "
                "timed to a different cut/release, or needs a negative --shift")
        elif last < duration * 0.5:
            notes.append(
                f"** SUBTITLES STOP AT {100 * last / duration:.0f}% OF THE RUNTIME - "
                "partial subs, or a different cut")
        elif last < duration * 0.85:
            notes.append(
                f"note: subtitles end at {100 * last / duration:.0f}% of the runtime "
                "(normal if the disc ends on a song or credits)")
    bad = [c for c in cues if c["end"] <= c["start"]]
    if bad:
        notes.append(f"note: {len(bad)} cues have a non-positive duration")
    overlaps = sum(1 for a, b in zip(cues, cues[1:]) if b["start"] < a["end"] - 0.05)
    if overlaps:
        notes.append(f"note: {overlaps} overlapping cues")
    return notes


# ------------------------------------------------------------- gpu bridge ---
def gpu_env() -> dict:
    """Environment for the local CUDA venv.

    `cuda-libs.env` is plain `KEY=VALUE` lines holding the LD_LIBRARY_PATH that
    points at the cuBLAS and cuDNN shipped inside the venv. Without it
    ctranslate2 loads and then fails at model-init with a library error that
    reads like a CUDA fault rather than a missing path.
    """
    env = dict(os.environ)
    if WHISPER_CUDA_ENV.exists():
        for line in WHISPER_CUDA_ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def run_gpu(script: str, argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run one CUDA worker on this machine.

    The workers stayed exactly as they were when they lived on the PC - they
    were always "handed a file, write a file" and never reached back at the
    host - so moving them home needed no change to them, only to who launches
    them. They take absolute paths, so there is no working directory to set.
    """
    if not WHISPER_PY.exists():
        sys.exit(f"no CUDA venv at {WHISPER_PY} - see the /megafan skill "
                 "§6 for what belongs there")
    return subprocess.run([str(WHISPER_PY), str(REPO / "scripts" / script), *argv],
                          capture_output=True, text=True, timeout=timeout,
                          env=gpu_env())


def run_gpu_worker(script: str, argv: list[str], timeout: int) -> dict:
    """`run_gpu` for the workers that report a `__SUBS_JSON__` meta line.

    The marker is the contract: pyannote and transformers both print warnings
    at volume, so a noisy run that produced nothing must not read as a success.
    """
    proc = run_gpu(script, argv, timeout)
    marker = [ln for ln in (proc.stdout or "").splitlines()
              if ln.startswith("__SUBS_JSON__")]
    if not marker:
        sys.exit(f"{script} produced no result line.\n"
                 f"stdout tail: {(proc.stdout or '')[-600:]}\n"
                 f"stderr tail: {(proc.stderr or '')[-600:]}")
    return json.loads(marker[-1].split(" ", 1)[1])


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------- translation ---
def _openai():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai package missing - pip install openai, then: "
                 "python3 scripts/plex_subs.py ...")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        env = REPO / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("\"'")
                    break
    if not key:
        sys.exit("No OPENAI_API_KEY in the environment or .env")
    return OpenAI(api_key=key)


INSTRUCTIONS = (
    "You translate Japanese subtitles into natural English for a music "
    "documentary about a rock band on tour. You are given a JSON array of "
    "objects with an integer id and Japanese text, in order.\n"
    "Return ONLY a JSON array of objects {\"id\": <same id>, \"en\": \"<English>\"} "
    "with EXACTLY one entry per input id, in the same order.\n"
    "Rules: translate each line as a subtitle - short, spoken, natural English, "
    "not a literal gloss. Keep each line's meaning inside its own line; do not "
    "merge, split, reorder or summarise. Preserve names, band names, place names "
    "and song titles as they are normally romanised. Casual and profane speech "
    "stays casual and profane. If a line is untranslatable noise, an isolated "
    "filler sound, or clearly a transcription error, return an empty string for "
    "it. Never invent content that is not in the Japanese."
)


def translate_segments(segments: list[dict], verbose: bool = True) -> list[str]:
    """Japanese segments -> English strings, 1:1 and index-safe.

    The count is enforced rather than trusted: a batch that comes back the wrong
    length would silently shift every later subtitle against the video, which is
    the one failure nobody would attribute to the translator.
    """
    client = _openai()
    out: list[str] = [""] * len(segments)
    context: list[str] = []
    done = 0
    for start in range(0, len(segments), BATCH_SEGMENTS):
        batch = segments[start:start + BATCH_SEGMENTS]
        payload = [{"id": start + i, "ja": s["text"]} for i, s in enumerate(batch)]
        prior = ("Previously translated lines, for continuity only - do not "
                 "repeat them:\n" + "\n".join(context[-CONTEXT_LINES:]) + "\n\n"
                 if context else "")
        got: dict[int, str] = {}
        for attempt in (1, 2):
            try:
                resp = client.responses.create(
                    model=MODEL,
                    instructions=INSTRUCTIONS,
                    input=prior + json.dumps(payload, ensure_ascii=False),
                )
                text = resp.output_text if hasattr(resp, "output_text") else ""
                m = re.search(r"\[.*\]", text or "", re.S)
                data = json.loads(m.group(0)) if m else []
                got = {int(d["id"]): (d.get("en") or "").strip()
                       for d in data if isinstance(d, dict) and "id" in d}
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    print(f"  ! batch at {start} failed: {exc}", file=sys.stderr)
                    got = {}
                else:
                    time.sleep(2)
                    continue
            missing = [p["id"] for p in payload if p["id"] not in got]
            if not missing:
                break
            if attempt == 2:
                print(f"  ! batch at {start}: {len(missing)} lines missing, "
                      "left blank", file=sys.stderr)
        for pid, en in got.items():
            if 0 <= pid < len(out):
                out[pid] = en
        context.extend([v for v in (got.get(p["id"], "") for p in payload) if v])
        done += len(batch)
        if verbose:
            print(f"  translated {done}/{len(segments)}", flush=True)
    return out


# ------------------------------------------------------------- cleanup ----
def collapse_hallucinations(segments: list[dict]) -> tuple[list[dict], int]:
    """Fold runs of an identical repeated line into one cue.

    Whisper's classic failure on music and silence is emitting the same phrase
    over and over. Only runs of THREE OR MORE are folded: a genuine repeat
    ("ready? ready?") is real speech and must survive.
    """
    out: list[dict] = []
    dropped = 0
    i = 0
    while i < len(segments):
        j = i
        while (j + 1 < len(segments)
               and segments[j + 1]["text"] == segments[i]["text"]):
            j += 1
        run = j - i + 1
        cue = dict(segments[i])
        if run >= 3:
            cue["end"] = segments[j]["end"]
            dropped += run - 1
        else:
            out.extend(dict(s) for s in segments[i:j])
        out.append(cue)
        i = j + 1
    out.sort(key=lambda c: c["start"])
    return out, dropped


# ------------------------------------------------------------- commands ---
def sidecar_path(video: str, lang: str = "en") -> Path:
    p = Path(video)
    return p.with_suffix("")  .with_name(p.stem + f".{lang}.srt")


def do_install(args) -> int:
    token = plex_token()
    if args.item:
        info = item_media(token, args.item)
        video = info["file"]
    else:
        video = args.video
        info = None
    if not os.path.isfile(video):
        sys.exit(f"Video not readable from this host: {video}")

    raw = Path(args.srt).read_bytes()
    text, enc = decode_subtitle(raw)
    cues = parse_srt(text)
    print(f"source: {args.srt}\n  decoded as {enc}")

    if args.shift:
        for c in cues:
            c["start"] += args.shift
            c["end"] += args.shift
        cues = [c for c in cues if c["end"] > 0]
        for c in cues:
            c["start"] = max(0.0, c["start"])
        print(f"  shifted by {args.shift:+.3f}s")

    duration = video_duration(video)
    for line in sanity_report(cues, duration):
        print(f"  {line}")
    if not cues:
        return 2

    dest = sidecar_path(video, args.lang)
    if dest.exists() and not args.force:
        sys.exit(f"Refusing to overwrite existing {dest.name} (use --force)")
    if args.dry_run:
        print(f"  DRY RUN - would write {dest}")
        return 0

    write_srt(cues, dest)
    try:
        os.chmod(dest, 0o644)
    except OSError:
        pass
    print(f"  wrote {dest} ({dest.stat().st_size} bytes)")

    if args.item:
        refresh_item(token, args.item)
        time.sleep(4)
        after = item_media(token, args.item)
        ext = [s for s in after["subs"] if s["external"]]
        print(f"  plex now reports {len(after['subs'])} subtitle stream(s), "
              f"{len(ext)} external: "
              + ", ".join(f"{s['lang'] or '?'}/{s['codec']}" for s in after["subs"]))
        if not after["subs"]:
            print("  ** Plex has not picked it up yet - it can take a scan; "
                  "check the file sits beside the video with the same base name")
    return 0


def do_generate(args) -> int:
    token = plex_token()
    info = item_media(token, args.item)
    video = info["file"]
    if not os.path.isfile(video):
        sys.exit(f"Video not readable from this host: {video}")
    dest = sidecar_path(video, "en")
    if dest.exists() and not args.force:
        sys.exit(f"{dest.name} already exists (use --force)")

    slug = re.sub(r"[^A-Za-z0-9]+", "-", Path(video).stem).strip("-")[:60]
    work = WORK_ROOT / slug
    work.mkdir(parents=True, exist_ok=True)
    audio = work / "audio.flac"
    tr_json = work / "transcript.json"

    print(f"item {args.item}: {info['title']}")
    print(f"  file  {video}")

    # 1. audio - 16k mono is what whisper consumes; flac keeps it small enough
    #    to push over ssh in seconds without throwing anything away.
    if audio.exists() and not args.force_audio:
        print(f"  audio (cached) {audio} {audio.stat().st_size / 1e6:.1f} MB")
    else:
        print("  extracting audio ...", flush=True)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", video,
             "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "16000",
             "-c:a", "flac", str(audio)],
            check=True, timeout=7200)
        print(f"  audio {audio.stat().st_size / 1e6:.1f} MB")

    if not tr_json.exists() or args.force_transcribe:
        # 2. transcribe on THIS box's GPU, straight onto the destination path.
        #    No staging step: the audio is already here.
        print(f"  transcribing on this host's GPU ({args.language}, whisperx) - "
              "this is the long step ...", flush=True)
        started = time.time()
        meta = run_gpu_worker(
            "plex_subs_cuda.py",
            ["--audio", str(audio), "--out", str(tr_json),
             "--language", args.language] + (["--no-align"] if args.no_align else []),
            timeout=args.timeout)
        print(f"  transcribed {meta['segments']} segments from "
              f"{meta['duration_s'] / 60:.1f} min in {meta['transcribe_s']:.0f}s "
              f"on {meta['device']} ({meta.get('compute_type', '?')})"
              + ("" if meta["aligned"] else " (unaligned timings)"))

        # 3. the worker reports the md5 of what it wrote. Nothing moved between
        #    machines any more, so this is no longer a transfer check - it is a
        #    cheap assertion that the file on disk is the file it just made, and
        #    it costs one read of a few KB.
        if not tr_json.exists():
            sys.exit(f"worker reported success but wrote no {tr_json}")
        local_md5 = md5_file(tr_json)
        if local_md5 != meta["md5"]:
            tr_json.unlink(missing_ok=True)
            sys.exit(f"transcript checksum mismatch "
                     f"(worker {meta['md5']}, disk {local_md5})")
        print(f"  transcript written, md5 verified ({tr_json.stat().st_size} bytes)")
        print(f"  elapsed {time.time() - started:.0f}s")
    else:
        print(f"  transcript (cached) {tr_json}")

    data = json.loads(tr_json.read_text(encoding="utf-8"))
    segments = data.get("segments") or []
    if not segments:
        sys.exit("transcript has no segments - nothing was spoken, or the "
                 "audio track was silent")
    segments, folded = collapse_hallucinations(segments)
    if folded:
        print(f"  folded {folded} repeated lines (whisper loops on music/silence)")

    if args.source_srt:
        ja = work / "source.ja.srt"
        write_srt([{**s, "text": wrap_line(s["text"])} for s in segments], ja)
        print(f"  wrote source transcript {ja}")

    # 5. translate here, where the key and the model seam live
    print(f"  translating {len(segments)} segments with {MODEL} ...", flush=True)
    english = translate_segments(segments)
    cues = [{"start": s["start"], "end": s["end"], "text": wrap_line(en)}
            for s, en in zip(segments, english) if en.strip()]
    blank = len(segments) - len(cues)
    if blank:
        print(f"  {blank} segments left out (untranslatable/noise)")
    if not cues:
        sys.exit("translation produced nothing")

    staged = work / "generated.en.srt"
    write_srt(cues, staged)
    print(f"  staged {staged}")

    duration = video_duration(video)
    for line in sanity_report(cues, duration):
        print(f"  {line}")

    if args.stage_only:
        print("\n  STAGE ONLY - review it, then install with:\n"
              f"    venv/bin/python scripts/plex_subs.py install --item {args.item} "
              f"--srt {staged}")
        return 0

    ns = argparse.Namespace(item=args.item, video=None, srt=str(staged), lang="en",
                            shift=0.0, force=args.force, dry_run=False)
    return do_install(ns)


def do_list(args) -> int:
    token = plex_token()
    section = concerts_section(token)
    root = plex_xml(f"/library/sections/{section}/all", token)
    rows = []
    for v in root.iter("Video"):
        info = item_media(token, v.get("ratingKey"))
        subs = info["subs"]
        rows.append((info["rk"], info["title"], len(subs),
                     ", ".join(sorted({s["lang"] or "?" for s in subs})) or "-",
                     Path(info["file"]).parent))
    print(f"{'rk':>6}  {'subs':>4}  {'langs':<12} title")
    for rk, title, n, langs, _ in sorted(rows, key=lambda r: r[1]):
        flag = " " if n else "*"
        print(f"{rk:>6}  {n:>4}{flag} {langs:<12} {title}")
    print("\n* = no subtitle track of any kind")
    return 0


# --------------------------------------------------------------- mc lane ---
# A live disc is roughly 15-30% talking and the rest singing, and Whisper is
# strong on the first and produces confident garbage on the second. The `mc`
# lane therefore never lets the ASR see the songs: AST finds the spoken spans
# on the PC's GPU, WhisperX transcribes ONLY those, and everything downstream
# is decided here. `generate` above is the older, wrong-shaped lane that fed it
# the whole disc.

MC_WORK = WORK_ROOT

SPEECH_TH = 0.5        # AST speech probability that counts as "someone talking"
SPAN_PAD_S = 1.0
SPAN_MIN_S = 6.0
BRIDGE_WINDOWS = 1     # windows of quiet a single span may jump

HARD_BREAK = "。！？!?"
SOFT_BREAK = "、,♪ "
SOFT_AFTER_S = 7.0
FORCE_S = 11.0
FORCE_CHARS = 52
MIN_CUE_S = 0.7
MAX_SHOW_S = 7.0       # a folded whisper loop must not hold the screen for 21s

MC_NOTICE = ("[Machine-translated from Japanese speech - spoken/MC segments "
             "only, songs are not subtitled]")

# Whisper-ja was trained on TV captions and hallucinates "<name>" speaker
# prefixes: on Yononaka Shredder it invented 深澤 / 佐久間 / 岩﨑, none of whom
# are in that band, and it did the same on Studio Jam Session. The only defence
# is telling the translator who really is in the room, so every disc wants its
# own block; a missing entry still gets the generic warning below.
CASTS: dict[int, str] = {
    7893: "ONE OK ROCK, live at Shibuya Club Quattro, Dec 2007 ('Yononaka "
          "Shredder'). Members: Taka (vocals), Toru (guitar), Ryota (bass), "
          "Tomoya (drums), Alex (guitar, 'アレク').",
    9823: "ONE OK ROCK, 2013 'Jinsei x Kimi =' TOUR FILM - the tour "
          "documentary disc (backstage, travel, interviews). Members: Taka "
          "(vocals), Toru (guitar), Ryota (bass), Tomoya (drums). NOTE the "
          "album is 'Jinsei x Boku =' and the tour is 'Jinsei x Kimi =' - "
          "they are different titles, do not collapse them.",
    4842: "ONE OK ROCK, 'This is My Budokan?!' 2010.11.28, Nippon Budokan. "
          "Members: Taka (vocals), Toru (guitar), Ryota (bass), Tomoya (drums).",
    8186: "ONE OK ROCK, 2013 'Jinsei x Kimi =' tour live disc. Members: Taka "
          "(vocals), Toru (guitar), Ryota (bass), Tomoya (drums). The album is "
          "'Jinsei x Boku =' and the tour is 'Jinsei x Kimi =' - different "
          "titles, do not collapse them.",
    4836: "ONE OK ROCK, 2014 'Mighty Long Fall' at Yokohama Stadium. Members: "
          "Taka (vocals), Toru (guitar), Ryota (bass), Tomoya (drums).",
    4841: "ONE OK ROCK, 'Studio Jam Session' - an acoustic studio session from "
          "the 'Jinsei x Boku =' era. Members: Taka (vocals), Toru (guitar), "
          "Ryota (bass), Tomoya (drums).",
    9297: "Fear, and Loathing in Las Vegas, live at Kobe World Kinen Hall, "
          "March 2014 ('Starburst'). Members: Minami (vocals/keys), So "
          "(vocals/programming), Sxun (guitar), Taiki (guitar), Kei (bass), "
          "Tomonori (drums). The band shortens its own name to 'Vegas'.",
    9313: "JAM Project, 'Hurricane Tour 2009 Gate of the Future', Nippon "
          "Budokan. Members in 2009: Hironobu Kageyama, Masaaki Endoh, Hiroshi "
          "Kitadani, Masami Okui, Yoshiki Fukuyama, Ricardo Cruz. They perform "
          "anime and game theme songs; song titles are usually anime titles.",
    8255: "MALICE MIZER, 'merveilles ~終焉と帰趨~ l'espace' (1998 live, Gackt "
          "era). Members: Gackt (vocals), Mana (guitar), Közi (guitar), Yu~ki "
          "(bass), Kami (drums). Visual kei; the stage patter is theatrical.",
    9298: "MAXIMUM THE HORMONE, 'Deco vs Deco' (2007 tour final at Zepp Tokyo "
          "plus backstage footage). Members: Daisuke-han (vocals/screams), "
          "Nao (drums/vocals), Maximum the Ryo-kun (guitar/vocals), Ue-chan "
          "(bass). Their banter is crude and fast - keep it crude.",
    9910: "MAXIMUM THE HORMONE, 'Dam vs Dam' (2008) - the 'ura final' after "
          "their tour final, at a small live house in their home town of "
          "Hachioji, played to 80 men weighing over 70kg picked by lottery. "
          "Members: Daisuke-han (vocals/screams), Nao (drums/vocals), Maximum "
          "the Ryo-kun (guitar/vocals), Ue-chan (bass). The running joke is "
          "デブ ('fat guy') and the tone is crude - keep it crude.",
    9296: "X JAPAN (then 'X'), 'Blue Blood Tour Bakuhatsu Sunzen GIG', Shibuya "
          "Kohkaido, March 1989. Members: Toshi (vocals), Yoshiki (drums), "
          "hide (guitar), Pata (guitar), Taiji (bass).",
}
GENERIC_CAST = (
    "IMPORTANT: Japanese ASR of this material hallucinates TV-caption speaker "
    "labels - a personal name glued to the front of a line. Any personal name "
    "that is not a member named above is a transcription artifact: drop the "
    "name and translate the rest of the line. The band's own name is often "
    "misrecognised; render it correctly."
)


# Phrases Whisper emits from its training data rather than from the audio. It
# learned them off YouTube captions, so they turn up on material that has never
# been near a YouTube outro - "ご視聴ありがとうございました" landed in the middle
# of a tour documentary. Deterministic and tiny on purpose: this is a list of
# known lies, not a general filter.
HALLUCINATED_JA = ("ご視聴ありがとうございました", "ご清聴ありがとうございました",
                   "最後までご視聴", "チャンネル登録", "字幕視聴者")
HALLUCINATED_EN = ("thank you for watching", "thanks for watching",
                   "please subscribe", "subscribe to the channel")


def _norm_ja(text: str) -> str:
    return re.sub(r"[\s。、！？!?,.\-–—♪・]", "", text or "")


def drop_hallucinations(cues: list[dict]) -> int:
    """Remove known Whisper training-data phrases. Returns how many went."""
    keep = [c for c in cues
            if not any(h in _norm_ja(c["text"]) for h in HALLUCINATED_JA)]
    n = len(cues) - len(keep)
    cues[:] = keep
    return n


# Phrases a performer repeats all night because that is what performers do.
# These must never read as a song hook however often they recur.
COURTESY = ("ありがとう", "おつかれ", "お疲れ", "こんばんは", "こんにちは",
            "よろしく", "thankyou", "thanks", "arigatou", "letsgo")


def _content_len(key: str) -> int:
    """Length weighted by information density, not raw characters.

    A kanji carries roughly a word; a Latin letter carries a fraction of one.
    Counting raw characters compared the two directly and cost real content:
    'Thankyou' (8 Latin chars) cleared a 6-char floor written for Japanese and
    four genuine 'Thank you!'s got dropped off a three-hour JAM Project set,
    while the actual target 人生かけて僕は is only 7 characters.
    """
    cjk = sum(1 for ch in key if ord(ch) > 0x2E80)
    return cjk + (len(key) - cjk) // 3


def drop_song_hooks(cues: list[dict], min_chars: int = 6, min_hits: int = 3,
                    min_spread_s: float = 600.0) -> list[str]:
    """Drop a phrase that recurs across the disc - a sung hook, not speech.

    The acoustic route does NOT work for this and the numbers are worth
    recording so nobody rebuilds it: measured on the tour film, cues the human
    fansub confirms and cues it never subtitled have the same AST profile
    (speech 0.74 vs 0.68, music 0.64 vs 0.65, singing 0.00 vs 0.00), because
    genuine MC on a documentary has a score bed under it. There is nothing to
    threshold.

    What does separate them is repetition at distance. 人生かけて僕は - the
    album title, sung - appears at 00:56, 39:54, 40:05 and 87:44; real
    conversation does not repeat a phrase verbatim across an hour. Narrow by
    construction: long enough not to catch 'ありがとう', frequent enough not to
    catch a callback, and spread far enough not to catch someone repeating
    themselves in one breath.
    """
    seen: dict[str, list[dict]] = {}
    for c in cues:
        key = _norm_ja(c["text"])
        low = key.lower()
        if any(low.startswith(w) for w in COURTESY):
            continue
        if _content_len(key) >= min_chars:
            seen.setdefault(key, []).append(c)
    doomed, dropped = set(), []
    for key, group in seen.items():
        spread = max(c["start"] for c in group) - min(c["start"] for c in group)
        if len(group) >= min_hits and spread >= min_spread_s:
            doomed.update(id(c) for c in group)
            dropped.append(f"{key[:24]} x{len(group)}")
    cues[:] = [c for c in cues if id(c) not in doomed]
    return dropped


def mc_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def mc_run_gpu(script: str, argv: list[str], timeout: int) -> str:
    """One MC-lane worker, on this machine's GPU.

    These two write their JSON directly and print no marker line, so the return
    code is the only signal there is - raise on it rather than letting the
    caller read a file the worker never wrote.
    """
    r = run_gpu(script, argv, timeout)
    if r.returncode:
        raise RuntimeError(f"{script} failed:\n{(r.stderr or '')[-1500:]}")
    return r.stdout


def mc_extract_audio(video: str, work: Path) -> Path:
    out = work / "audio16k.flac"
    if out.exists():
        return out
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1",
                    "-ar", "16000", "-c:a", "flac", str(out)], check=True)
    return out


def spans_from_scores(rows: list[dict], win: float,
                      th: float = SPEECH_TH) -> list[list[float]]:
    """AST windows -> spoken spans. Every threshold here is a host-side decision.

    `th` is NOT portable across discs. AST's absolute confidence tracks how
    clean the master is - measured peaks over a whole disc: Yononaka (2007)
    0.97, Malice Mizer 0.73, X Japan (1989) 0.61 - so a fixed 0.5 found almost
    nothing on the oldest disc even though Toshi plainly addresses the crowd,
    and 0.25 recovered it. But the same drop RUINED Malice Mizer, pulling sung
    lyrics in as speech. A low yield is not automatically a miss: ask whether
    the disc plausibly has talking, then read the recovered cues, because
    contamination reads as perfectly ordinary MC to someone who can't check it.
    """
    def speech(r: dict) -> float:
        return max(r.get("Speech", 0.0),
                   r.get("Male speech, man speaking", 0.0),
                   r.get("Female speech, woman speaking", 0.0),
                   r.get("Conversation", 0.0))

    flags = [speech(r) >= th for r in rows]
    spans: list[list[float]] = []
    i = 0
    while i < len(rows):
        if flags[i]:
            j = i
            while j + 1 < len(rows) and (
                    flags[j + 1]
                    or any(flags[j + 1 + k] for k in range(1, BRIDGE_WINDOWS + 2)
                           if j + 1 + k < len(rows))):
                j += 1
            spans.append([rows[i]["t"], rows[j]["t"] + win])
            i = j + 1
        else:
            i += 1

    out: list[list[float]] = []
    for s, e in spans:
        s, e = max(0.0, s - SPAN_PAD_S), e + SPAN_PAD_S
        if e - s < SPAN_MIN_S:
            continue
        if out and s <= out[-1][1] + 2.0:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([round(s, 1), round(e, 1)])
    return out


def collapse_repeats(chars: list[dict]) -> list[dict]:
    """Fold a phrase repeated 3+ times into one copy, spanning the whole run.

    Whisper loops on crowd noise - 'お疲れ様です' x37 inside ONE segment, which
    collapse_hallucinations cannot see because it folds identical SEGMENTS. Two
    repeats survive untouched: real speech does that.
    """
    out: list[dict] = []
    i, n = 0, len(chars)
    while i < n:
        hit = None
        for L in range(1, 13):
            if i + L * 3 > n:
                break
            unit = "".join(c["w"] for c in chars[i:i + L])
            if not unit.strip():
                continue
            reps = 1
            while (i + L * (reps + 1) <= n and
                   "".join(c["w"] for c in
                           chars[i + L * reps:i + L * (reps + 1)]) == unit):
                reps += 1
            if reps >= 3:
                hit = (L, reps)
                break
        if hit:
            L, reps = hit
            kept = [dict(c) for c in chars[i:i + L]]
            kept[-1]["e"] = chars[i + L * reps - 1]["e"]
            out.extend(kept)
            i += L * reps
        else:
            out.append(chars[i])
            i += 1
    return out


def split_cues(chars: list[dict]) -> list[dict]:
    """Cut on SENTENCES first; length only as a last resort.

    Splitting on a character budget hands the translator half a sentence and
    yields 'Let's huddle' / 'up.' - a long cue is the smaller problem.
    """
    cues: list[dict] = []
    cur: list[dict] = []

    def flush():
        if not cur:
            return
        text = "".join(c["w"] for c in cur).strip()
        if text and re.search(r"[^\s。、！？!?,.\-–—♪]", text):
            cues.append({"start": cur[0]["s"], "end": cur[-1]["e"], "text": text})
        cur.clear()

    for c in chars:
        cur.append(c)
        dur = cur[-1]["e"] - cur[0]["s"]
        if c["w"] in HARD_BREAK and dur >= 1.0:
            flush()
        elif c["w"] in SOFT_BREAK and dur >= SOFT_AFTER_S:
            flush()
        elif dur >= FORCE_S or len("".join(x["w"] for x in cur)) >= FORCE_CHARS:
            flush()
    flush()
    return cues


def build_cues(segments: list[dict]) -> list[dict]:
    cues: list[dict] = []
    for seg in segments:
        spk = seg.get("speaker")
        chars = seg.get("words") or []
        if not chars:
            cues.append({"start": seg["start"], "end": seg["end"],
                         "text": seg["text"], "speaker": spk})
            continue
        part = split_cues(collapse_repeats(chars))
        # A 2-character orphan is a timing artifact, not a line: 'おめ' +
        # 'でとうございます' translated apart becomes 'Congratu-' / 'lations'.
        k = 1
        while k < len(part):
            if len(part[k]["text"]) < 4 or len(part[k - 1]["text"]) < 4:
                part[k - 1]["text"] += part[k]["text"]
                part[k - 1]["end"] = part[k]["end"]
                del part[k]
            else:
                k += 1
        for c in part:
            c["speaker"] = spk
        cues.extend(part)

    cues.sort(key=lambda c: c["start"])
    for c in cues:
        if c["end"] - c["start"] < MIN_CUE_S:
            c["end"] = c["start"] + MIN_CUE_S
        c["end"] = min(c["end"], c["start"] + MAX_SHOW_S)
    for a, b in zip(cues, cues[1:]):
        if a["end"] > b["start"]:
            a["end"] = max(a["start"] + 0.3, b["start"] - 0.05)
    return cues


def parse_speaker_map(spec: str) -> dict[str, str]:
    """'SPEAKER_00=Taka,SPEAKER_01=Toru' -> {...}; also accepts '0=Taka'."""
    out: dict[str, str] = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = (x.strip() for x in part.split("=", 1))
        if k.isdigit():
            k = f"SPEAKER_{int(k):02d}"
        out[k] = v
    return out


def label_cues(cues: list[dict], names: dict[str, str]) -> None:
    """Mark who is talking, in place.

    pyannote hands back anonymous, disc-stable ids. Guessing which member an id
    is would be exactly the confident-wrong-fact failure this lane already
    produces elsewhere, so nothing is named unless the owner names it (the
    whisperx-clips SPEAKER_NN -> real name step). Unnamed, a change of speaker
    still gets the subtitle convention for one: a leading dash.

    Measured on the Jinsei tour film against the human fansub's OWN speaker
    labels: 70% purity, and only with clustering left UNCONSTRAINED (10 ids for
    4 people). Forcing max_speakers=4 collapsed everything into one cluster at
    25%. The documentary is shot in many rooms and the same voice embeds
    differently in each, so over-clustering is correct here - the ids are
    relabeled by hand anyway, and an id that is one person in one setting is
    worth more than a tidy count. 70% is why --diarize is opt-in.
    """
    prev = None
    for c in cues:
        spk = c.get("speaker")
        if spk and spk != prev and len({x.get("speaker") for x in cues
                                        if x.get("speaker")}) > 1:
            who = names.get(spk)
            c["text"] = f"{who}: {c['text']}" if who else f"- {c['text']}"
        prev = spk


def write_speaker_sheet(cues: list[dict], dest: Path) -> None:
    """One file to make relabeling a 30-second job instead of a chore."""
    by: dict[str, list[dict]] = {}
    for c in cues:
        by.setdefault(c.get("speaker") or "SPEAKER_UNK", []).append(c)
    lines = ["# Who is who on this disc.",
             "# Re-run with:  --speakers 'SPEAKER_00=Taka,SPEAKER_01=Toru'",
             "# ids are stable within a disc and meaningless across discs.", ""]
    for spk, cs in sorted(by.items(), key=lambda kv: -sum(
            c["end"] - c["start"] for c in kv[1])):
        talk = sum(c["end"] - c["start"] for c in cs)
        lines.append(f"{spk}  {len(cs)} cues, {talk/60:.1f} min")
        for c in cs[:6]:
            lines.append(f"    {_ts(c['start'])[:8]}  {c['text'][:90]}")
        lines.append("")
    dest.write_text("\n".join(lines), encoding="utf-8")


def do_mc_disc(rk: int, args) -> dict:
    token = plex_token()
    info = item_media(token, str(rk))
    video, title = info["file"], info.get("title", str(rk))
    work = MC_WORK / mc_slug(title)
    work.mkdir(parents=True, exist_ok=True)
    stat = {"item": rk, "title": title}
    print(f"\n=== {rk}  {title}")

    t0 = time.time()
    audio = mc_extract_audio(video, work)
    dur = video_duration(video)
    print(f"  audio {audio.stat().st_size/1e6:.0f} MB, video {dur/60:.1f} min "
          f"({time.time()-t0:.0f}s)")

    stem = work.name
    reuse = getattr(args, "reuse", False) and (work / "seg.json").exists() \
        and (work / "asr.json").exists()
    if reuse:
        print("  reusing cached seg.json + asr.json (no GPU work)")

    t0 = time.time()
    if not reuse:
        mc_run_gpu("plex_subs_segment_cuda.py",
                   ["--audio", str(audio), "--out", str(work / "seg.json")],
                   timeout=7200)
    seg = json.loads((work / "seg.json").read_text())
    spans = spans_from_scores(seg["rows"], seg["win"], args.speech_th)
    talk = sum(e - s for s, e in spans)
    stat.update(minutes=round(dur / 60, 1), spans=len(spans),
                talk_min=round(talk / 60, 1),
                talk_pct=round(talk / dur * 100, 1) if dur else 0.0,
                seg_s=round(time.time() - t0))
    print(f"  segment: {len(spans)} spans, {talk/60:.1f} min talking "
          f"({stat['talk_pct']}%)  [{stat['seg_s']}s]")
    (work / "spans.json").write_text(json.dumps(spans))
    if not spans:
        stat["note"] = "no spoken spans found"
        return stat

    t0 = time.time()
    if not reuse:
        flags = ["--diarize"] if args.diarize else []
        if args.max_speakers:
            flags += ["--max-speakers", str(args.max_speakers)]
        mc_run_gpu("plex_subs_asr_cuda.py",
                   ["--audio", str(audio), "--spans", str(work / "spans.json"),
                    "--out", str(work / "asr.json"), *flags],
                   timeout=14400)
    asr = json.loads((work / "asr.json").read_text())
    stat["asr_s"] = round(time.time() - t0)
    stat["speakers"] = asr.get("speakers", 0)
    print(f"  asr: {len(asr['segments'])} segments, "
          f"{stat['speakers']} speakers  [{stat['asr_s']}s]")

    cues = build_cues(asr["segments"])
    n_hall = drop_hallucinations(cues)
    hooks = drop_song_hooks(cues)
    if n_hall:
        print(f"  dropped {n_hall} known-hallucination cue(s)")
    if hooks:
        print(f"  dropped repeated song hook(s): {', '.join(hooks)}")
    stat["dropped_hallucination"] = n_hall
    stat["dropped_hooks"] = hooks
    (work / "cues_ja.json").write_text(json.dumps(cues, ensure_ascii=False, indent=1))
    stat["cues"] = len(cues)
    if not cues:
        stat["note"] = "nothing transcribed"
        return stat

    cast = CASTS.get(rk, "")
    global INSTRUCTIONS
    saved = INSTRUCTIONS
    INSTRUCTIONS = (saved + "\n\n" +
                    (f"Context for this disc: {cast}\n" if cast else "") +
                    GENERIC_CAST)
    try:
        en = translate_segments(cues, verbose=args.verbose)
    finally:
        INSTRUCTIONS = saved

    out = [{"start": c["start"], "end": c["end"], "text": e.strip(),
            "ja": c["text"], "speaker": c.get("speaker")}
           for c, e in zip(cues, en) if (e or "").strip()]
    stat["english"] = len(out)
    stat["dropped"] = len(cues) - len(out)
    if not out:
        stat["note"] = "nothing translated"
        return stat

    out = [c for c in out if not any(h in c["text"].lower()
                                     for h in HALLUCINATED_EN)]
    stat["english"] = len(out)
    label_cues(out, parse_speaker_map(args.speakers))
    (work / "cues_en.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    write_speaker_sheet(out, work / "speakers.txt")

    srt = work / "mc.en.srt"
    write_srt([{"start": 0.2, "end": 2.6, "text": MC_NOTICE}] +
              [{k: c[k] for k in ("start", "end", "text")} for c in out], srt)
    stat["srt"] = str(srt)
    print(f"  built {len(out)} English cues -> {srt}")

    if args.install:
        inst = argparse.Namespace(item=str(rk), video=None, srt=str(srt),
                                  lang="en", shift=0.0, force=True, dry_run=False)
        do_install(inst)
        stat["installed"] = True
    return stat


# ================================================================ visual ===
# On-screen Japanese: the text a subtitle track never covers because nobody
# ever said it out loud. Title cards, intertitles, signs, and - on Dam vs Dam -
# a long opening of forum posts filmed off a CRT.
#
# The measured reason this lane ends at a WORKSHEET and not at a sidecar:
#
#   A clean digital card reads at 0.99 and is right. A camcorder pointed at a
#   monitor makes the model FABRICATE FLUENTLY. On the 2ch screen at 0:39 the
#   real line is 小さいライブハウスでやるのヤメてほしい ("stop playing tiny
#   live houses") and it came back "小さいライブハウスでやるのもすでに楽しい"
#   ("playing small live houses is already fun") - the complaint inverted into
#   praise, plus a second line invented whole. Cropping to the text region
#   fixed the wording and then dropped two of the three lines.
#
#   Confidence does not separate the two cases: the wrong read and the right
#   read both came back 0.72. So confidence is a SORT KEY for the owner's eye,
#   never a gate that installs anything by itself. Every span is reviewed.
#
# Frames are sampled, hashed, and grouped into spans; a span is one screen and
# gives its own cue timing. Triage runs on the cheap tier so the full tier is
# only spent where there is text - a concert disc is mostly not text.

VIS_FPS = 0.5              # 2s apart: a card held less than that is unreadable
VIS_WIDTH = 720
VIS_HASH_DIST = 8          # dHash hamming distance still counted as one screen
VIS_FLAT_STD = 5.0         # a frame this uniform holds nothing, text included
VIS_MIN_SPAN_S = 0.9
VIS_FRAMES_PER_READ = 3    # a panning camera shows different lines per frame
VIS_WORKERS = 6
VIS_CONF_CHECK = 0.9       # below this the worksheet shouts; it never installs
VIS_NOTICE = ("[Machine-translated: Japanese speech (spoken/MC segments only, "
              "songs are not subtitled) and on-screen text]")

VIS_TRIAGE_INSTR = (
    "You are triaging frames from a Japanese DVD. Answer ONE question: does "
    "this frame contain Japanese text that a viewer is meant to READ - a title "
    "card, an intertitle, a caption, a sign, or a computer/TV screen being "
    "filmed?\n"
    "Return ONLY JSON: {\"text\": true|false}\n"
    "true for readable Japanese text of any size, even if blurry or partly "
    "legible. false for a plain shot of people, a stage, an instrument, black, "
    "or a frame whose only text is a tiny station logo, channel bug or "
    "timecode. When genuinely unsure, answer true - a wrong true costs one "
    "cheap read, a wrong false loses the line for good."
)

VIS_READ_INSTR = (
    "You read ON-SCREEN Japanese text out of frames from a Japanese music "
    "documentary DVD (2008, 480p, interlaced, often a camcorder pointed at a "
    "CRT monitor).\n"
    "You are given one or more frames of THE SAME screen, taken seconds apart. "
    "The camera may pan, drift or refocus, so a line that is mush in one frame "
    "can be sharp in another. Combine them into one reading of that screen.\n"
    "Return ONLY JSON: {\"has_text\": bool, \"ja\": \"<verbatim Japanese, "
    "newline between lines>\", \"en\": \"<natural English subtitle>\", "
    "\"kind\": \"card\"|\"screen\"|\"sign\"|\"none\", \"confidence\": "
    "0.0-1.0}\n"
    "Rules. Transcribe ONLY what you can actually read. Never reconstruct a "
    "plausible sentence from a blurred one - omit the line and lower the "
    "confidence instead. A guess that reads fluently is the worst possible "
    "output here, because nothing downstream can tell it from a real line. "
    "Ignore station logos, channel bugs, timecodes and player chrome. Keep "
    "band names, place names and song titles in their normal romanisation. "
    "Casual and profane text stays casual and profane. Set confidence to your "
    "honest odds that a Japanese reader would agree with every character. "
    "No readable text: has_text false, empty strings, kind \"none\"."
)


def parse_range(spec: str) -> tuple[float, float | None]:
    """'1:30-3:00' -> (90.0, 90.0). Returns (start, duration|None)."""
    def clock(s: str) -> float:
        parts = [float(p) for p in s.strip().split(":")]
        out = 0.0
        for p in parts:
            out = out * 60 + p
        return out
    spec = (spec or "").strip()
    if not spec:
        return 0.0, None
    if "-" not in spec:
        return clock(spec), None
    a, b = spec.split("-", 1)
    start = clock(a) if a.strip() else 0.0
    if not b.strip():
        return start, None
    end = clock(b)
    if end <= start:
        sys.exit(f"--range ends at or before it starts: {spec}")
    return start, end - start


def vis_extract(video: str, out_dir: Path, start: float, dur: float | None,
                fps: float) -> tuple[list[Path], list[bytes]]:
    """One decode pass -> review JPEGs AND 9x8 gray thumbnails for hashing.

    Two outputs off one input so the video is decoded once. The gray stream is
    72 bytes a frame, which is all the hashing and the blank test ever need -
    no image library is involved anywhere in this lane.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.jpg"):
        old.unlink()
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += [
        "-i", video,
        "-vf", f"fps={fps},scale={VIS_WIDTH}:-2", "-q:v", "3",
        str(out_dir / "f_%05d.jpg"),
        "-vf", f"fps={fps},scale=9:8,format=gray", "-f", "rawvideo", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=14400)
    if proc.returncode != 0:
        sys.exit(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[-500:]}")
    raw = proc.stdout
    frames = sorted(out_dir.glob("f_*.jpg"))
    grays = [raw[i * 72:(i + 1) * 72] for i in range(len(raw) // 72)]
    n = min(len(frames), len(grays))
    return frames[:n], grays[:n]


def dhash(gray: bytes) -> int:
    """9x8 gray -> 64-bit difference hash (each pixel vs its right neighbour)."""
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if gray[base + col] > gray[base + col + 1] else 0)
    return bits


def gray_spread(gray: bytes) -> float:
    """Standard deviation of the thumbnail. Near zero = a blank frame."""
    if not gray:
        return 0.0
    mean = sum(gray) / len(gray)
    return (sum((v - mean) ** 2 for v in gray) / len(gray)) ** 0.5


def vis_group(frames: list[Path], grays: list[bytes], start: float,
              fps: float) -> list[dict]:
    """Consecutive near-identical frames -> one span (one screen, one cue).

    The span IS the cue timing, which is why this beats sampling: a card held
    for eight seconds becomes one reviewed line covering those eight seconds,
    not four duplicate reads with invented boundaries.
    """
    step = 1.0 / fps
    spans: list[dict] = []
    for i, (path, gray) in enumerate(zip(frames, grays)):
        h = dhash(gray)
        at = start + i * step
        cur = spans[-1] if spans else None
        if cur is not None and bin(cur["hash"] ^ h).count("1") <= VIS_HASH_DIST:
            cur["frames"].append(path)
            cur["end"] = at + step
            cur["spread"] = max(cur["spread"], gray_spread(gray))
            continue
        spans.append({"start": at, "end": at + step, "hash": h,
                      "frames": [path], "spread": gray_spread(gray)})
    for s in spans:
        s["end"] = max(s["end"], s["start"] + VIS_MIN_SPAN_S)
    return spans


def _vis_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _image_part(path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}",
            "detail": "high"}


def vis_triage(client, span: dict) -> bool:
    """Cheap tier: is there anything to read here at all?"""
    mid = span["frames"][len(span["frames"]) // 2]
    try:
        resp = client.responses.create(
            model=TRIAGE_MODEL, instructions=VIS_TRIAGE_INSTR,
            input=[{"role": "user", "content": [_image_part(mid)]}])
    except Exception as exc:                      # a triage failure must not
        print(f"  ! triage at {_ts(span['start'])} failed: {exc}",   # lose the
              file=sys.stderr)                                       # span
        return True
    span["triage_tokens"] = getattr(resp.usage, "input_tokens", 0)
    return bool(_vis_json(getattr(resp, "output_text", "") or "").get("text"))


def vis_read(client, span: dict, context: str) -> dict:
    """Full tier: every frame of one screen, read together."""
    picks = span["frames"]
    if len(picks) > VIS_FRAMES_PER_READ:
        step = (len(picks) - 1) / (VIS_FRAMES_PER_READ - 1)
        picks = [picks[round(i * step)] for i in range(VIS_FRAMES_PER_READ)]
    content: list[dict] = [_image_part(p) for p in picks]
    content.append({"type": "input_text", "text":
                    f"{len(picks)} frame(s) of the same screen, "
                    f"at {_ts(span['start'])}." + (f"\n{context}" if context else "")})
    for attempt in (1, 2):
        try:
            resp = client.responses.create(
                model=MODEL, instructions=VIS_READ_INSTR,
                input=[{"role": "user", "content": content}])
            span["read_tokens"] = getattr(resp.usage, "input_tokens", 0)
            return _vis_json(getattr(resp, "output_text", "") or "")
        except Exception as exc:                            # noqa: BLE001
            if attempt == 2:
                print(f"  ! read at {_ts(span['start'])} failed: {exc}",
                      file=sys.stderr)
                return {}
            time.sleep(2)
    return {}


def wrap_visual(text: str, width: int = 42) -> list[str]:
    """Wrap into as many lines as it takes, never two.

    `wrap_line` is built for a spoken cue and folds everything past line two
    onto line two, which on a wordy title card produced one short line and one
    90-character run off the side of the screen. A card is already long-form;
    the honest answer is more lines, since the alternative is dropping text a
    viewer can see on screen.
    """
    words, lines, cur = " ".join(text.split()).split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


VIS_MERGE_GAP_S = 3.0
VIS_SAME_SCREEN = 0.55     # normalised-JA ratio at which two reads are one screen


def vis_consolidate(spans: list[dict]) -> list[dict]:
    """Adjacent reads of ONE screen -> one cue, and disagreement made loud.

    Two things happen when a screen is sampled more than once. A card that
    types itself in line by line yields three spans whose text grows, and those
    are the same cue: keep the fullest reading over the union of their time.

    But a filmed monitor yields three spans that DISAGREE, and that is the
    fabrication detector this lane needed. Measured on the 2ch screen at 0:40:
    the real line is ...ヤメてほしい ("stop playing tiny live houses"), and the
    three reads came back ヤメてほしい, がマジでほしい (conf 0.62) and ヤバイ楽しい
    (conf 0.94). The wrong one was the CONFIDENT one, so no confidence gate
    would have caught it - but the three disagreeing with each other is
    conclusive on its own, needs no model, and cannot be talked out of.
    """
    import difflib
    out: list[dict] = []
    for span in spans:
        prev = out[-1] if out else None
        if prev is None or span["start"] - prev["end"] > VIS_MERGE_GAP_S:
            out.append(dict(span, alts=[]))
            continue
        a, b = _norm_ja(prev.get("ja", "")), _norm_ja(span.get("ja", ""))
        if not a or not b:
            out.append(dict(span, alts=[]))
            continue
        grew = a in b or b in a
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        if not grew and ratio < VIS_SAME_SCREEN:
            out.append(dict(span, alts=[]))
            continue
        # One screen. Keep the fuller reading; a card only ever gains text.
        keep, drop = (span, prev) if len(b) >= len(a) else (prev, span)
        merged = dict(keep)
        merged["start"] = min(prev["start"], span["start"])
        merged["end"] = max(prev["end"], span["end"])
        merged["frames"] = prev["frames"] + [f for f in span["frames"]
                                             if f not in prev["frames"]]
        merged["alts"] = prev.get("alts", []) + span.get("alts", [])
        if not grew:
            merged["conflict"] = True
            merged["alts"] = merged["alts"] + [
                {"ja": drop.get("ja", ""), "en": drop.get("en", ""),
                 "confidence": drop.get("confidence", 0)}]
        else:
            merged["conflict"] = prev.get("conflict") or span.get("conflict")
        out[-1] = merged
    return out


def vis_worksheet(spans: list[dict], video: str, title: str, dest: Path) -> None:
    """The owner's review pass. Editing this file is what makes it true."""
    lines = [
        f"# On-screen Japanese - {title}",
        "",
        "Machine reading of the text that appears ON SCREEN. Nothing here is",
        "installed until you run `visual apply`, which reads THIS FILE back.",
        "",
        "How to work it:",
        "  * fix or delete the EN line - EN is what becomes the subtitle",
        "  * an empty EN, or a deleted block, drops that cue entirely",
        "  * `** CHECK: low confidence **` - the model said so itself",
        "  * `** CHECK: frames disagree **` - the SAME screen read two ways in",
        "    two frames. Trust this over confidence: on a filmed monitor the",
        "    wrong reading has come back MORE confident than the right one.",
        "    The rejected readings are kept in a comment under the block.",
        "  * the frame each block was read from is named under it; open it",
        "  * timestamps are the span the screen was actually up for - edit",
        "    them freely, they are just `HH:MM:SS,mmm --> HH:MM:SS,mmm`",
        "",
        f"video: {video}",
        "",
    ]
    for s in spans:
        why = []
        if s.get("conflict"):
            why.append("frames disagree")
        if s.get("confidence", 0) < VIS_CONF_CHECK:
            why.append("low confidence")
        flag = f"  ** CHECK: {', '.join(why)} **" if why else ""
        lines.append(f"## {_ts(s['start'])} --> {_ts(s['end'])}  "
                     f"[{s.get('kind', 'card')}] conf {s.get('confidence', 0):.2f}{flag}")
        lines.append(f"JA: {(s.get('ja') or '').strip()}")
        lines.append(f"EN: {(s.get('en') or '').strip()}")
        for alt in s.get("alts", []):
            # The rejected readings stay visible. Three readings of one screen
            # that disagree is the evidence that none of them can be trusted.
            lines.append(f"<!-- also read as ({alt.get('confidence', 0):.2f}): "
                         f"{' / '.join((alt.get('ja') or '').split(chr(10)))}")
            lines.append(f"     -> {' / '.join((alt.get('en') or '').split(chr(10)))} -->")
        lines.append(f"<!-- frames: {', '.join(p.name for p in s['frames'][:8])} -->")
        lines.append("")
    dest.write_text("\n".join(lines), encoding="utf-8")


WS_HEAD = re.compile(r"^##\s+" + SRT_TIME.pattern)


def parse_visual_worksheet(path: Path) -> list[dict]:
    """Owner-edited worksheet -> cues. EN is the subtitle; JA rides along."""
    cues: list[dict] = []
    cur: dict | None = None
    field: str | None = None
    in_comment = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        head = WS_HEAD.match(raw)
        if head:
            in_comment = False          # a header always ends a stray comment
            if cur:
                cues.append(cur)
            h1, m1, s1, f1, h2, m2, s2, f2 = head.groups()
            cur = {
                "start": int(h1) * 3600 + int(m1) * 60 + int(s1) + int(f1.ljust(3, "0")) / 1000,
                "end": int(h2) * 3600 + int(m2) * 60 + int(s2) + int(f2.ljust(3, "0")) / 1000,
                "ja": "", "en": "",
            }
            field = None
            continue
        # Comments carry the REJECTED readings, which run to a second line
        # ("     -> ..."). Matching only on a leading `<!--` let that second
        # line read as more English and it landed in the subtitle verbatim.
        if in_comment:
            in_comment = "-->" not in raw
            continue
        if raw.lstrip().startswith("<!--"):
            in_comment = "-->" not in raw
            continue
        if cur is None:
            continue
        if raw.startswith("JA:"):
            cur["ja"], field = raw[3:].strip(), "ja"
        elif raw.startswith("EN:"):
            cur["en"], field = raw[3:].strip(), "en"
        elif field and raw.strip():
            cur[field] = f"{cur[field]}\n{raw.strip()}".strip()
        elif not raw.strip():
            field = None
    if cur:
        cues.append(cur)
    return [c for c in cues if c["en"].strip()]


def merge_visual_cues(speech: list[dict], visual: list[dict]) -> list[dict]:
    """Fold on-screen text into the speech cues.

    Overlapping cues are the failure to avoid: two SRT cues live at once and a
    player either stacks them illegibly or drops one. So an on-screen line that
    lands inside a spoken cue joins THAT cue as a second line, and only a line
    with the screen to itself becomes a cue of its own. Italic marks it as
    something read rather than heard.
    """
    out = [dict(c) for c in speech]
    for v in visual:
        # The owner's own line breaks are meaning here - a card is laid out in
        # lines - so each is wrapped on its own rather than reflowed as a blob.
        text = "\n".join(f"<i>{ln}</i>"
                         for src in v["en"].split("\n") if src.strip()
                         for ln in wrap_visual(src) if ln.strip())
        hit = next((c for c in out
                    if c["start"] < v["end"] and v["start"] < c["end"]), None)
        if hit:
            hit["text"] = f"{hit['text']}\n{text}"
        else:
            out.append({"start": v["start"], "end": v["end"], "text": text})
    out.sort(key=lambda c: c["start"])
    return out


def do_visual_scan(args) -> int:
    token = plex_token()
    info = item_media(token, args.item)
    video, title = info["file"], info.get("title", args.item)
    if not os.path.isfile(video):
        sys.exit(f"Video not readable from this host: {video}")
    work = MC_WORK / mc_slug(title)
    work.mkdir(parents=True, exist_ok=True)
    sheet = work / "visual.ja.md"
    if sheet.exists() and not args.force:
        sys.exit(f"Refusing to overwrite {sheet} (use --force). Your edits live "
                 "in that file.")

    start, dur = parse_range(args.range)
    print(f"item {args.item}: {title}\n  file  {video}")
    print(f"  range {_ts(start)} + {'whole disc' if dur is None else _ts(dur)}"
          f" at {args.fps} fps")

    t0 = time.time()
    frames, grays = vis_extract(video, work / "visual_frames", start, dur, args.fps)
    print(f"  {len(frames)} frames  [{time.time()-t0:.0f}s]")
    if not frames:
        sys.exit("no frames extracted - check --range against the video length")

    spans = vis_group(frames, grays, start, args.fps)
    blank = [s for s in spans if s["spread"] < VIS_FLAT_STD]
    spans = [s for s in spans if s["spread"] >= VIS_FLAT_STD]
    print(f"  {len(spans)} distinct screens ({len(blank)} blank dropped)")
    if args.max_spans and len(spans) > args.max_spans:
        print(f"  ! capped at {args.max_spans} of {len(spans)} screens - the "
              f"rest of the range was NOT read (raise --max-spans)")
        spans = spans[:args.max_spans]
    if not spans:
        sys.exit("nothing but blank frames in that range")

    client = _openai()
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=VIS_WORKERS) as pool:
        hits = list(pool.map(lambda s: vis_triage(client, s), spans))
    kept = [s for s, h in zip(spans, hits) if h]
    print(f"  triage: {len(kept)}/{len(spans)} screens carry text "
          f"[{time.time()-t0:.0f}s]")
    if not kept:
        sys.exit("no on-screen text found in that range")

    context = CASTS.get(int(args.item), "")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=VIS_WORKERS) as pool:
        reads = list(pool.map(lambda s: vis_read(client, s, context), kept))
    final = []
    for span, got in zip(kept, reads):
        if not got.get("has_text") or not (got.get("en") or "").strip():
            continue
        span.update(ja=got.get("ja", ""), en=got.get("en", ""),
                    kind=got.get("kind", "card"),
                    confidence=float(got.get("confidence") or 0))
        final.append(span)
    final.sort(key=lambda s: s["start"])
    print(f"  read: {len(final)} screens with text  [{time.time()-t0:.0f}s]")
    final = vis_consolidate(final)
    clash = sum(1 for s in final if s.get("conflict"))
    print(f"  consolidated to {len(final)} cues ({clash} where the frames "
          f"disagreed with each other)")

    tok = sum(s.get("triage_tokens", 0) for s in spans)
    rtok = sum(s.get("read_tokens", 0) for s in kept)
    print(f"  tokens: {tok} triage + {rtok} read  "
          f"(~${tok/1e6*0.20 + rtok/1e6*2.00:.2f})")

    (work / "visual.json").write_text(json.dumps(
        [{**s, "frames": [p.name for p in s["frames"]]} for s in final],
        ensure_ascii=False, indent=1))
    vis_worksheet(final, video, title, sheet)
    flagged = sum(1 for s in final
                  if s.get("conflict") or s.get("confidence", 0) < VIS_CONF_CHECK)
    print(f"\n  worksheet -> {sheet}")
    print(f"  {len(final)} blocks, {flagged} flagged ** CHECK **")
    print(f"  frames    -> {work / 'visual_frames'}")
    print(f"\nRead it, fix the EN lines, then:\n"
          f"  python3 {Path(__file__).name} visual apply --item {args.item} --install")
    return 0


def do_visual_apply(args) -> int:
    token = plex_token()
    info = item_media(token, args.item)
    video, title = info["file"], info.get("title", args.item)
    work = MC_WORK / mc_slug(title)
    sheet = Path(args.worksheet) if args.worksheet else work / "visual.ja.md"
    if not sheet.exists():
        sys.exit(f"No worksheet at {sheet} - run `visual scan` first")

    visual = parse_visual_worksheet(sheet)
    print(f"item {args.item}: {title}\n  worksheet {sheet}: {len(visual)} cues")
    if not visual:
        sys.exit("every block has an empty EN - nothing to install")

    speech: list[dict] = []
    source = "none"
    mc_srt = work / "mc.en.srt"
    installed = sidecar_path(video, "en")
    if args.speech:
        speech = parse_srt(decode_subtitle(Path(args.speech).read_bytes())[0])
        source = args.speech
    elif mc_srt.exists():
        speech = parse_srt(decode_subtitle(mc_srt.read_bytes())[0])
        source = str(mc_srt)
    elif installed.exists():
        speech = parse_srt(decode_subtitle(installed.read_bytes())[0])
        source = str(installed)
    print(f"  speech cues: {len(speech)} from {source}")

    speech = [c for c in speech if c["text"].strip() != MC_NOTICE]
    cues = merge_visual_cues(speech, visual)
    if speech:
        cues = [{"start": 0.2, "end": 2.6, "text": VIS_NOTICE}] + cues

    dest = work / "combined.en.srt"
    write_srt(cues, dest)
    print(f"  built {len(cues)} cues -> {dest}")
    for line in sanity_report(cues, video_duration(video)):
        print(f"  {line}")

    if args.install:
        do_install(argparse.Namespace(
            item=str(args.item), video=None, srt=str(dest), lang="en",
            shift=0.0, force=True, dry_run=False))
    else:
        print(f"\n  staged only. Install with:\n"
              f"    python3 {Path(__file__).name} install --item {args.item} "
              f"--srt {dest} --force")
    return 0


def do_mc(args) -> int:
    items = [int(i) for i in (args.item or [])]
    if args.all:
        token = plex_token()
        section = concerts_section(token)
        for v in plex_xml(f"/library/sections/{section}/all", token).iter("Video"):
            info = item_media(token, v.get("ratingKey"))
            if not info["subs"]:
                items.append(int(info["rk"]))
    if not items:
        sys.exit("nothing to do: pass --item or --all")

    # No deploy step any more: the workers run from the repo they live in.
    stats = []
    for rk in items:
        try:
            stats.append(do_mc_disc(rk, args))
        except Exception as exc:                     # one bad disc must not kill
            print(f"  ! {rk} failed: {exc}", file=sys.stderr)          # the run
            stats.append({"item": rk, "error": str(exc)})

    print("\n" + "=" * 78)
    print(f"{'item':>5} {'min':>6} {'talk':>6} {'%':>5} {'spans':>6} {'spk':>4} "
          f"{'cues':>5}  title")
    for s in stats:
        if "error" in s:
            print(f"{s['item']:>5} {'ERROR':>6}  {s['error'][:50]}")
            continue
        print(f"{s['item']:>5} {s.get('minutes',0):>6.1f} {s.get('talk_min',0):>6.1f} "
              f"{s.get('talk_pct',0):>5.1f} {s.get('spans',0):>6} "
              f"{s.get('speakers',0):>4} {s.get('english',0):>5}  "
              f"{s['title'][:40]}")
    MC_WORK.mkdir(parents=True, exist_ok=True)
    (MC_WORK / "mc_run.json").write_text(json.dumps(stats, indent=1,
                                                    ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="what the Concerts library has for subtitles")
    p.set_defaults(func=do_list)

    p = sub.add_parser("install", help="validate + place an existing subtitle file")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--item", help="Plex ratingKey")
    g.add_argument("--video", help="path to the video instead of a ratingKey")
    p.add_argument("--srt", required=True, help="the subtitle file to install")
    p.add_argument("--lang", default="en", help="sidecar language code (default en)")
    p.add_argument("--shift", type=float, default=0.0,
                   help="seconds to add to every timestamp (negative = earlier)")
    p.add_argument("--force", action="store_true", help="overwrite an existing sidecar")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=do_install)

    p = sub.add_parser("generate", help="make one with WhisperX on the PC + translate")
    p.add_argument("--item", required=True, help="Plex ratingKey")
    p.add_argument("--language", default="ja", help="spoken language (default ja)")
    p.add_argument("--stage-only", action="store_true",
                   help="write the srt into the work dir and stop")
    p.add_argument("--source-srt", action="store_true",
                   help="also write the untranslated transcript as an srt")
    p.add_argument("--no-align", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--force-audio", action="store_true")
    p.add_argument("--force-transcribe", action="store_true")
    p.add_argument("--keep-remote", action="store_true",
                   help="leave the staged audio on the PC")
    p.add_argument("--timeout", type=int, default=7200)
    p.set_defaults(func=do_generate)

    p = sub.add_parser("mc", help="MC-only subs: find the talking, skip the songs")
    p.add_argument("--item", action="append", help="Plex ratingKey (repeatable)")
    p.add_argument("--all", action="store_true",
                   help="every Concerts item with no subtitle track")
    p.add_argument("--install", action="store_true",
                   help="place the result as a sidecar (default: stage only)")
    p.add_argument("--speech-th", type=float, default=SPEECH_TH,
                   help="AST speech confidence that counts as talking; older or "
                        "noisier masters need a lower value (X Japan 1989 needs "
                        "0.25). Raising coverage can pull sung lyrics in - read "
                        "the cues before trusting a big jump.")
    p.add_argument("--diarize", action="store_true",
                   help="label who is speaking. OFF by default: measured 70%% "
                        "purity against a human fansub's own labels, and a "
                        "wrong attribution is worse than none. Useful on a "
                        "documentary, pointless on a one-voice concert MC.")
    p.add_argument("--max-speakers", type=int, default=0,
                   help="leave at 0. Constraining this to the band size made "
                        "purity WORSE (25%% vs 70%%) - see label_cues.")
    p.add_argument("--speakers", default="",
                   help="name the diarized ids, e.g. 'SPEAKER_00=Taka,1=Toru'; "
                        "see speakers.txt in the work dir")
    p.add_argument("--reuse", action="store_true",
                   help="reuse cached seg.json/asr.json and redo only the "
                        "host-side build + translation (no GPU work)")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=do_mc)

    p = sub.add_parser("visual", help="translate the text that is ON SCREEN")
    vsub = p.add_subparsers(dest="vcmd", required=True)

    v = vsub.add_parser("scan", help="read on-screen text -> review worksheet")
    v.add_argument("--item", required=True, help="Plex ratingKey")
    v.add_argument("--range", default="",
                   help="'1:30-3:00' to bound the scan; default is the whole "
                        "disc. Cheap either way - a concert body triages out.")
    v.add_argument("--fps", type=float, default=VIS_FPS,
                   help=f"frames sampled per second (default {VIS_FPS}). Raise "
                        "it only for text that flashes past.")
    v.add_argument("--max-spans", type=int, default=0,
                   help="stop after this many distinct screens (0 = no cap). "
                        "A cap is always reported, never silent.")
    v.add_argument("--force", action="store_true",
                   help="overwrite an existing worksheet - THIS DISCARDS YOUR "
                        "EDITS")
    v.set_defaults(func=do_visual_scan)

    v = vsub.add_parser("apply", help="fold the reviewed worksheet into the srt")
    v.add_argument("--item", required=True, help="Plex ratingKey")
    v.add_argument("--worksheet", default="",
                   help="default: visual.ja.md in the item's work dir")
    v.add_argument("--speech", default="",
                   help="speech srt to merge with; default is mc.en.srt in the "
                        "work dir, else the installed sidecar")
    v.add_argument("--install", action="store_true",
                   help="place the merged result as the sidecar")
    v.set_defaults(func=do_visual_apply)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
