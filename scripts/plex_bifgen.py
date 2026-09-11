#!/usr/bin/env python3
"""Parallel generator for Plex BIF video-preview thumbnails.

Plex's own butler generates BIFs on ONE core; on a modest host that is ~13 h
for a mid-sized library. This does the same work across N cores (~4.7 h on 3) and then
lets Plex *adopt* the results, which it does without regenerating them —
verified 2026-08-10: an externally written ``index-sd.bif`` survived a
``PUT /library/metadata/{key}/analyze`` byte-for-byte (same size, same mtime)
while Plex set ``mi:indexes`` on the part and began serving thumbnails from it.

Design constraints, each learned the hard way:

* **Plex stays the only writer of its database.** Every read here is
  ``mode=ro``; the ``mi:indexes`` bookkeeping is done BY Plex, via analyze.
  Never write that flag directly -- it would mean writing a live Plex DB.
* **One ffmpeg pass per file.** A separate ffprobe keyframe scan reads every
  file twice, which is punishing on a multi-GB remux.
* **Never de-duplicate repeated keyframes.** A BIF reader derives an image's
  length from the NEXT entry's offset, so offsets must strictly increase and
  repeated slots must repeat the bytes. Plex's own output does this.
* **A blocked source must never read as an empty one.** A file that cannot be
  decoded is recorded as an error with its cause, never silently skipped --
  this library contains truncated downloads that ffmpeg refuses outright.
* Writes are ``.part`` + ``os.replace``, so Plex never sees a partial BIF.

Usage::

    python3 scripts/plex_bifgen.py --workers 3
    python3 scripts/plex_bifgen.py --sections 3 --limit 5     # pilot
    python3 scripts/plex_bifgen.py --dry-run

Progress is published to ``plex_bif_state.json`` for ``plex_jobs.py`` /
``/plex-jobs`` to render; the page's counters come from its own ``.bif`` walk,
so this file only supplies liveness ("is a runner going, and on what").
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

PLEX_DIR = os.getenv(
    "PLEX_DIR",
    "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server",
)
PLEX_URL = os.getenv("PLEX_URL", "http://localhost:32400")
LIB_DB = "Plug-in Support/Databases/com.plexapp.plugins.library.db"
STATE_PATH = os.path.join(REPO, "plex_bif_state.json")
LOCK_PATH = os.path.join(REPO, ".plex_bif.lock")

# Nothing is skipped any more. AV1 used to be, because on the Pi `-skip_frame
# nokey` was SILENTLY IGNORED for it: ffmpeg decoded and JPEG-encoded every
# frame (32,892 of them to fill 685 slots), so a file cost ~45s per video-minute
# and was routed to the PC's GPU by scripts/plex_bif_remote.py.
#
# That premise died with the x86 cutover and the claim was re-measured on the
# tower 2026-09-07: 120 s of a 1920x800 AV1 film decodes in 22.4 s plain and in
# **0.4 s** with `-skip_frame nokey`, i.e. the optimisation is honoured here and
# AV1 is now among the CHEAPEST codecs to index rather than the most expensive.
# So AV1 is built locally like everything else, and the PC offload is retired --
# which also removes the last reason this pipeline ever touched a second machine.
DEFAULT_SKIP_CODECS = ()

MAGIC = b"\x89BIF\r\n\x1a\n"
INTERVAL = 2          # seconds per slot; matches Plex's GenerateBIFFrameInterval
WIDTH = 320           # Plex's own thumbnail width
QSCALE = "3"          # ffmpeg mjpeg qscale ~ the q90 Plex emits
_PTS = re.compile(r"pts_time:([0-9.]+)")

_state_lock = threading.Lock()
_state: dict = {}


# ── BIF construction ─────────────────────────────────────────────────────────
def _duration_s(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, errors="replace",
        check=True).stdout.strip()
    return float(out)


def _extract(path: str, outdir: str) -> tuple[list[str], list[float]]:
    """Single pass: keyframes -> scaled JPEGs, plus each one's pts_time.

    errors="replace" is load-bearing, not defensive tidying. ffmpeg echoes the
    file's own metadata tags into stderr, and a container written with cp1252
    punctuation carries bytes that are not valid UTF-8 -- with the default
    strict decoding that raises *while reading the output of a decode that
    already succeeded*, so a perfectly good video fails for the encoding of its
    title (observed 2026-08-11: `The Amazing Digital Circus - S01E04.mkv`,
    "'utf-8' codec can't decode byte 0xe2 in position 3037"). We only ever
    regex pts_time floats out of this text and truncate it into an error
    message, so a replacement character costs nothing.
    """
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-skip_frame", "nokey", "-i", path,
         "-an", "-sn", "-dn", "-vsync", "0",
         "-vf", f"scale={WIDTH}:-2,showinfo,setpts=N/TB", "-q:v", QSCALE,
         os.path.join(outdir, "%06d.jpg")],
        capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "ffmpeg failed").strip()[-300:])
    files = sorted(os.listdir(outdir))
    times = [float(m) for m in _PTS.findall(proc.stderr)]
    # PAIRED, THEN SORTED BY TIME -- and both halves matter.
    #
    # HEVC re-encodes in this library emit keyframes OUT OF PRESENTATION ORDER
    # (measured on Game of Thrones S01E01: pts_time went 47.4, 57.4, 50.7,
    # 68.1, 60.7). Two things broke on that, and only one of them was loud:
    #
    #   * the mjpeg encoder refuses a pts that moves backwards ("Invalid pts
    #     (1456) <= last (1633)") and the whole run died with EPERM, which is
    #     why 113 files failed every 30 minutes forever; `setpts=N/TB` above
    #     renumbers what the ENCODER sees while `showinfo` -- deliberately
    #     placed before it -- still reports the true timestamps we index on.
    #   * silently, `build_bif` bisects this list, and bisect on an unsorted
    #     list is simply wrong rather than slow: every slot would pick the
    #     wrong frame. That one never raised anything.
    #
    # Sorting a file that was already in order is a no-op, so this costs the
    # ~4000 well-behaved files nothing.
    n = min(len(files), len(times))
    pairs = sorted(zip(times[:n], files[:n]))
    return [f for _, f in pairs], [ts for ts, _ in pairs]


def build_bif(src: str, out_bif: str, interval: int = INTERVAL) -> tuple[int, int]:
    tmp = tempfile.mkdtemp(prefix="bif_")
    try:
        dur = _duration_s(src)
        files, times = _extract(src, tmp)
        n = min(len(files), len(times))
        if n == 0:
            raise RuntimeError("no keyframes extracted")
        files, times = files[:n], times[:n]

        index: list[tuple[int, int]] = []
        payload = bytearray()
        cache: dict[int, bytes] = {}
        for i in range(int(dur // interval)):
            t = i * interval
            j = bisect.bisect_left(times, t)
            k = min((c for c in (j - 1, j) if 0 <= c < n),
                    key=lambda c: abs(times[c] - t))
            data = cache.get(k)
            if data is None:
                with open(os.path.join(tmp, files[k]), "rb") as fh:
                    data = cache[k] = fh.read()
            index.append((t, len(payload)))
            payload += data
        if not index:
            raise RuntimeError(f"duration {dur:.1f}s shorter than one slot")

        header_len = 64 + 8 * (len(index) + 1)
        entries = bytearray()
        for t, off in index:
            entries += struct.pack("<II", t, header_len + off)
        entries += struct.pack("<II", 0xFFFFFFFF, header_len + len(payload))

        head = bytearray(64)
        head[0:8] = MAGIC
        struct.pack_into("<III", head, 8, 0, len(index), 0)

        os.makedirs(os.path.dirname(out_bif), exist_ok=True)
        part = out_bif + ".part"
        with open(part, "wb") as fh:
            fh.write(head)
            fh.write(entries)
            fh.write(payload)
        os.replace(part, out_bif)
        return len(index), os.path.getsize(out_bif)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── targets ──────────────────────────────────────────────────────────────────
def bundle_bif_path(part_hash: str) -> str:
    """Plex lays a media bundle out as Media/localhost/<h[0]>/<h[1:]>.bundle."""
    return os.path.join(PLEX_DIR, "Media", "localhost", part_hash[0],
                        f"{part_hash[1:]}.bundle", "Contents", "Indexes",
                        "index-sd.bif")


def load_targets(sections: list[int] | None,
                 skip_codecs: list[str] | None = None,
                 only_codecs: list[str] | None = None) -> list[dict]:
    """Every BIF target, cheapest first.

    Codec is carried (and filterable) because cost is NOT uniform: measured on
    this Pi, 1080p h264 runs ~0.43 s per video-minute while 10-bit AV1 runs
    ~45 s — roughly 75x — so a 2.7%-of-the-library codec can dominate the run.
    """
    uri = "file:" + os.path.join(PLEX_DIR, LIB_DB) + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        sql = """select m.id, mp.hash, mp.file, mi.duration/60000.0, mi.width,
                        ls.name, lower(ms.codec)
                 from media_parts mp
                 join media_items mi on mi.id = mp.media_item_id
                 join metadata_items m on m.id = mi.metadata_item_id
                 join library_sections ls on ls.id = mi.library_section_id
                 left join media_streams ms
                        on ms.media_item_id = mi.id and ms.stream_type_id = 1
                 where m.metadata_type in (1,4)
                   and mp.file is not null and mp.file != ''
                   and mp.hash is not null"""
        args: list = []
        if sections:
            sql += " and ls.id in (%s)" % ",".join("?" * len(sections))
            args += list(sections)
        if skip_codecs:
            sql += " and coalesce(lower(ms.codec),'') not in (%s)" % \
                   ",".join("?" * len(skip_codecs))
            args += [c.lower() for c in skip_codecs]
        if only_codecs:
            sql += " and lower(ms.codec) in (%s)" % ",".join("?" * len(only_codecs))
            args += [c.lower() for c in only_codecs]
        sql += " group by mp.id order by mi.duration"
        rows = con.execute(sql, tuple(args)).fetchall()
    finally:
        con.close()
    # De-duplicate by HASH, not by part id. 18 of 4222 rows here share a hash
    # (the same underlying file reachable from more than one item), and the
    # output path is derived from the hash alone -- so two workers were handed
    # the same destination and raced, one of them dying on a vanished temp file.
    # One hash is one BIF, by construction.
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        if r[1] in seen:
            continue
        seen.add(r[1])
        out.append({"key": r[0], "hash": r[1], "file": r[2],
                    "minutes": r[3] or 0.0, "width": r[4] or 0,
                    "library": r[5], "codec": r[6] or "?"})
    return out


# ── progress publication (read by plex_jobs.py) ──────────────────────────────
def publish(**fields) -> None:
    """Best-effort. Progress reporting must never break the run."""
    try:
        from storage import atomic_write_json
    except Exception:
        atomic_write_json = None
    with _state_lock:
        _state.update(fields)
        _state["heartbeat"] = int(time.time())
        snapshot = dict(_state)
    try:
        if atomic_write_json:
            atomic_write_json(STATE_PATH, snapshot)
        else:
            tmp = STATE_PATH + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(snapshot, fh)
            os.replace(tmp, STATE_PATH)
        # This runs under sudo (the bundle tree is plex-owned) while the bot
        # serving /plex-jobs runs as an ordinary user. atomic_write_json's
        # secure default is 0600, which made the monitor read every live run as
        # "no runner" — a PermissionError that _cached() correctly swallows and
        # therefore never surfaces. Hand the file back to the repo's owner.
        os.chmod(STATE_PATH, 0o644)
        if os.geteuid() == 0:
            st = os.stat(REPO)
            os.chown(STATE_PATH, st.st_uid, st.st_gid)
    except Exception:
        pass


def adopt(rating_key: int, token: str) -> bool:
    """Ask Plex to notice the file we just wrote.

    Plex sets ``mi:indexes`` on the part and does NOT regenerate an existing
    BIF, so this is bookkeeping, not work. Failure is non-fatal: the file is
    on disk and a later analyze or butler pass will still pick it up.
    """
    if not token:
        return False
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{PLEX_URL}/library/metadata/{rating_key}/analyze"
            f"?X-Plex-Token={token}", method="PUT")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=3,
                    help="parallel workers (default 3, leaving a core for Plex)")
    ap.add_argument("--sections", type=int, nargs="*",
                    help="limit to these library section ids")
    ap.add_argument("--limit", type=int, help="process at most N items")
    ap.add_argument("--interval", type=int, default=INTERVAL,
                    help="seconds between thumbnails (default 2, Plex's own)")
    ap.add_argument("--no-adopt", action="store_true",
                    help="write files but don't ask Plex to register them")
    ap.add_argument("--skip-codecs", nargs="*", default=None,
                    help="skip these video codecs (default: %s)"
                         % " ".join(DEFAULT_SKIP_CODECS))
    ap.add_argument("--only-codecs", nargs="*", default=None,
                    help="restrict to these video codecs")
    ap.add_argument("--allow-av1", action="store_true",
                    help="accepted and ignored; AV1 is built locally now")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # The old AV1 refusal lived here and is gone: see DEFAULT_SKIP_CODECS. A
    # caller (or the deployed unit) may still pass `--skip-codecs av1`, and that
    # is still honoured - it is now a choice rather than a guard.
    skip = args.skip_codecs
    if skip is None and not args.only_codecs:
        skip = list(DEFAULT_SKIP_CODECS)

    token = os.getenv("PLEX_TOKEN", "")
    if not token:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(REPO, ".env"))
            token = os.getenv("PLEX_TOKEN", "")
        except Exception:
            pass
    if not token and not args.no_adopt:
        print("warning: no PLEX_TOKEN; files will be written but not adopted",
              file=sys.stderr)

    lock = None
    if not args.dry_run:
        lock = _acquire_lock()
        if lock is None:
            print("another plex_bifgen run holds the lock; nothing to do")
            return 0
        problem = _preflight()
        if problem:
            print(f"error: {problem}", file=sys.stderr)
            return 2

    targets = load_targets(args.sections, skip, args.only_codecs)
    todo = [t for t in targets if not os.path.exists(bundle_bif_path(t["hash"]))]
    if args.limit:
        todo = todo[:args.limit]

    total_min = sum(t["minutes"] for t in todo)
    print(f"{len(targets)} BIF targets, {len(todo)} missing "
          f"({total_min/60:.0f} h of video), {args.workers} workers")
    if args.dry_run:
        for t in todo[:20]:
            print(f"  {t['library']:<12} {t['minutes']:6.1f}min {t['width']:>5}px "
                  f"{t['codec']:<6} {os.path.basename(t['file'])[:52]}")
        if len(todo) > 20:
            print(f"  ... and {len(todo)-20} more")
        return 0
    if not todo:
        print("nothing to do")
        return 0

    started = time.time()
    done = errors = 0
    err_list: list[dict] = []
    publish(started_at=int(started), pid=os.getpid(), workers=args.workers,
            planned=len(todo), done=0, errors=0, current=None, finished_at=None)

    # The heartbeat must NOT depend on items completing. It used to tick only on
    # completion, so a slow file (a 24-min AV1 episode takes ~18 min here —
    # 10-bit AV1 defeats -skip_frame nokey) left the stamp minutes stale and
    # plex_jobs, which calls a runner stale after 120s, declared a healthy run
    # dead. Liveness is "the process is alive", not "an item just finished".
    stop_beat = threading.Event()

    def beat() -> None:
        while not stop_beat.wait(30):
            publish()

    threading.Thread(target=beat, daemon=True).start()

    def work(t: dict) -> dict:
        out = bundle_bif_path(t["hash"])
        publish(current=os.path.basename(t["file"])[:80])
        frames, size = build_bif(t["file"], out, args.interval)
        try:
            os.chown(out, *_plex_ids())
        except Exception:
            pass
        if not args.no_adopt:
            adopt(t["key"], token)
        return {"frames": frames, "size": size}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, t): t for t in todo}
        try:
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    fut.result()
                    done += 1
                except Exception as exc:
                    errors += 1
                    err_list.append({"file": t["file"], "error": str(exc)[:200]})
                    # the TAIL: ffmpeg puts its real error last, and _extract
                    # already hands us only the closing 300 chars, so printing
                    # the head of that showed stream-info spam and hid the cause
                    print(f"  FAILED {os.path.basename(t['file'])[:60]}: "
                          f"{' '.join(str(exc).split())[-160:]}", file=sys.stderr)
                if (done + errors) % 25 == 0 or (done + errors) == len(todo):
                    el = time.time() - started
                    rate = done / el if el else 0
                    left = len(todo) - done - errors
                    print(f"  {done}/{len(todo)} done, {errors} failed, "
                          f"{rate*3600:.0f}/h, eta {left/rate/3600:.1f}h"
                          if rate else f"  {done}/{len(todo)} done")
                publish(done=done, errors=errors)
        except KeyboardInterrupt:
            print("\ninterrupted -- finished files are kept; re-run to resume",
                  file=sys.stderr)
            pool.shutdown(wait=False, cancel_futures=True)

    stop_beat.set()
    publish(done=done, errors=errors, current=None,
            finished_at=int(time.time()), error_list=err_list[:50])
    el = time.time() - started
    print(f"\n{done} generated, {errors} failed, {el/3600:.2f} h")
    if err_list:
        print("failures (these are usually unplayable/truncated files):")
        for e in err_list[:10]:
            print(f"  {os.path.basename(e['file'])[:60]}: {e['error'][:100]}")
    return 0


def _plex_ids() -> tuple[int, int]:
    import pwd
    ent = pwd.getpwnam("plex")
    return ent.pw_uid, ent.pw_gid


def _acquire_lock():
    """Refuse to run beside another instance.

    Once a systemd timer runs this every 30 minutes, a hand-started sweep can
    overlap a scheduled one. Both would enumerate the same missing targets and
    two workers would write one destination -- the cross-process version of the
    same-hash race that killed an item in the first full run. Returns the held
    file object (kept open for the process's life) or None if someone else owns
    it. flock releases automatically on exit, including SIGKILL.
    """
    import fcntl
    fh = open(LOCK_PATH, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.write(f"{os.getpid()}\n")
    fh.flush()
    return fh


def _preflight() -> str | None:
    """Fail fast on anything that would only surface after real work.

    The first run of this cost 90 s of decode across three files before each
    one hit EACCES on the write — the tree is plex-owned and the script had
    been started as an ordinary user. Anything cheap and knowable up front is
    checked here so a doomed run stops in milliseconds.
    """
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            return f"{tool} not found on PATH"

    root = os.path.join(PLEX_DIR, "Media", "localhost")
    if not os.path.isdir(root):
        return f"Plex media bundle tree not found at {root}"

    probe = os.path.join(root, f".bifgen_write_test_{os.getpid()}")
    try:
        with open(probe, "w") as fh:
            fh.write("")
        os.unlink(probe)
    except OSError as exc:
        return (f"cannot write to {root} ({exc.strerror}). The tree is "
                f"plex-owned — re-run with sudo, e.g.\n"
                f"    sudo python3 {os.path.relpath(__file__, REPO)} "
                f"--workers 3")
    return None


if __name__ == "__main__":
    sys.exit(main())
