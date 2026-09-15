"""One MusicBrainz request per second — ACROSS PROCESSES.

Every MusicBrainz caller in this repo was separately throttling
MusicBrainz with a module-level "last call" timestamp. That is exact for one
process and nothing at all for two: the megafan skill now runs its
research, chapter and catalogue stages as separate worker agents, so two
processes can hit MB in the same second, each certain it waited its turn. MB
answers that with a 503, and in a caller with no retry a 503 is an empty list
— a blocked source must never read as an empty one.

`turn()` is a context manager. It takes an exclusive flock on a stamp file,
sleeps out whatever is left of the interval since the stamp's mtime, yields for
the call, and re-stamps on the way out. Holding the lock ACROSS the call also
serializes concurrent callers, which is what MusicBrainz actually asks for
(one request in flight per client). The stamp lives in /run/lock for the
usual lock-file reasons — world-writable, sticky, cleared at boot — and
if it cannot be opened the throttle degrades to in-process only, never to none.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import time
from pathlib import Path

INTERVAL_S = 1.2
STAMP = Path(os.environ.get("MB_RATE_STAMP", "/run/lock/musicbrainz.stamp"))

_last_local = 0.0


@contextlib.contextmanager
def turn(interval: float = INTERVAL_S):
    """Wait for the next MusicBrainz slot, hold it for the call, re-stamp."""
    global _last_local
    fd = None
    try:
        fd = os.open(STAMP, os.O_RDWR | os.O_CREAT, 0o666)
        fcntl.flock(fd, fcntl.LOCK_EX)
        last = max(os.fstat(fd).st_mtime, _last_local)
    except OSError:
        if fd is not None:
            os.close(fd)
            fd = None
        last = _last_local
    try:
        wait = interval - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        yield
    finally:
        _last_local = time.time()
        if fd is not None:
            try:
                os.utime(fd)
            except OSError:
                pass
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
