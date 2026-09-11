#!/usr/bin/env python3
"""Gather the evidence for a concert disc BEFORE its metadata is applied.

    python3 scripts/plex_concert_research.py --item 9296
    python3 scripts/plex_concert_research.py --catalog KSB5-5734
    python3 scripts/plex_concert_research.py --item 9296 --covers-only

Two jobs, both read-only.  Nothing here writes to Plex, opens a datastore, or
makes a model call - it prints a table and drops candidate images in a folder,
and `plex_concert_meta.py` is what applies a decision afterwards.

WHY IT EXISTS
-------------
Both halves were done BY HAND on every disc so far, and each hand pass was
expensive in a different way:

* FACTS.  `AZBS-1009` reached the live library and sat there for a day because
  fandom and MusicBrainz disagreed and nothing compared them.  On the X Japan
  DVD, English Wikipedia asserted September 9 2001 while MusicBrainz, CDJapan
  and ja.wikipedia all said September 5 - and en.wikipedia's OWN cited source
  was the CDJapan page saying September 5.  Both times the fix was the same
  move: ask several independent sources about ONE catalogue number and look at
  them side by side.  A catalogue number is exactly the kind of fact nobody
  re-checks, so re-checking it has to be one command.

* COVERS.  Finding the X Japan cover meant hand-probing Cover Art Archive,
  Wikipedia, CDJapan, Amazon JP, Sony Music, HMV and Discogs, and the decision
  could only be made by LOOKING: CDJapan's image was the shrink-wrapped retail
  package with a price sticker on it, Sony's DVD image was the whole flattened
  sleeve including the back panel, and Wikipedia's was a 250x250 fair-use crop.
  No metadata distinguishes those three.  So this fetches every candidate,
  normalises each to PNG (fandom and others serve WebP from a .jpg URL, which
  most viewers will not open), and prints their sizes - and a human looks.

WHAT IT REFUSES TO DO
---------------------
It does not pick.  Same reason `plex_concert_meta.py` does not: MusicBrainz's
`score` is text similarity rather than confidence, the library's titles are
romanisations that share zero characters with the databases' Japanese ones, and
"which of these two pictures is the cover" is a judgement.  It ranks and shows.

Every source reports its own status, because **a blocked source must never read
as an empty one** - a 403 from Discogs and a genuine "no such catalogue number"
are the same empty list otherwise, and the second one is a fact while the first
is a broken tool.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import plex_concert_meta as M  # noqa: E402  (shares plex/mb/wiki helpers)

DISCOGS = "https://api.discogs.com"
DEFAULT_OUT = Path("/tmp/concert-covers")
# Where the owner files a photo of a booklet page when an online scan is too soft
# to read. That photo has outranked every online source every time one existed -
# it is the only thing that has ever settled an ambiguous date - so it is
# reported BEFORE the online fact table, not after.
SCANS_DIR = Path(os.environ.get("CONCERT_SCANS_DIR",
                                "~/disc-scans")).expanduser()

# A source's answer is one of these. The distinction is the point: `blocked` and
# `none` look identical downstream and mean opposite things.
OK, NONE, BLOCKED, SKIPPED = "ok", "none", "blocked", "skipped"


def _shape_status(err: Exception) -> str:
    """A 404 is an answer ('not in this database'); anything else is a fault."""
    if isinstance(err, urllib.error.HTTPError) and err.code == 404:
        return NONE
    return BLOCKED


# ----------------------------------------------------------------- creds ---
def env_value(key: str) -> str:
    """Same .env-or-environment lookup `plex_concert_meta.plex_token` does."""
    val = os.environ.get(key)
    if val:
        return val.strip()
    env = M.REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return ""


# --------------------------------------------------------------- discogs ---
def discogs_get(path: str, **params) -> dict:
    """Discogs rejects a default user agent outright, and wants the token in a
    header rather than the query string so it stays out of logs and referrers."""
    token = env_value("DISCOGS_TOKEN")
    if not token:
        raise RuntimeError("no DISCOGS_TOKEN in the environment or .env")
    url = f"{DISCOGS}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": M.MB_UA,
        "Authorization": f"Discogs token={token}",
    })
    with urllib.request.urlopen(req, timeout=25) as f:
        return json.loads(f.read())


def discogs_by_catalog(catno: str) -> tuple[str, list[dict]]:
    """Releases carrying this catalogue number, best first.

    Discogs is the strongest source for PHYSICAL media - it files per pressing,
    which is the axis every other database blurs, and its scans are user
    uploads of the actual sleeve rather than a shop's product shot.
    """
    try:
        d = discogs_get("/database/search", catno=catno, per_page=10)
    except Exception as e:                      # noqa: BLE001 - status, not a crash
        return (SKIPPED if isinstance(e, RuntimeError) else _shape_status(e)), []
    out = []
    for r in d.get("results") or []:
        out.append({
            "id": r.get("id"),
            "title": r.get("title") or "",
            "year": str(r.get("year") or ""),
            "country": r.get("country") or "",
            "formats": r.get("format") or [],
            "catalog": r.get("catno") or "",
            "label": (r.get("label") or [""])[0],
            "cover": r.get("cover_image") or "",
        })
    return (OK if out else NONE), out


def discogs_release(rid: int) -> tuple[str, dict]:
    """One release in full - `released` is the exact date, which the search
    endpoint flattens to a bare year."""
    try:
        d = discogs_get(f"/releases/{rid}")
    except Exception as e:                      # noqa: BLE001
        return (SKIPPED if isinstance(e, RuntimeError) else _shape_status(e)), {}
    return OK, {
        "date": (d.get("released") or "").strip(),
        # Keep `type`: Discogs marks exactly one image `primary` and it is the
        # FRONT. That is the source declaring which side of the case this is,
        # and no measurement can recover it - see best_cover.
        "images": [{"uri": i.get("uri"), "type": i.get("type") or ""}
                   for i in (d.get("images") or []) if i.get("uri")],
        "formats": [f.get("name") for f in (d.get("formats") or []) if f.get("name")],
        "title": d.get("title") or "",
    }


# --------------------------------------------------------------- cdjapan ---
def catalog_forms(catno: str) -> list[str]:
    """The spellings one catalogue number is written in.

    The number read off a case is `KSB5 5734`; MusicBrainz files it `KSB5-5734`.
    A search API normalises that away, but CDJapan's product URL is a literal
    path, so the separator decides between the right page and a 404 - which
    reads exactly like 'this shop never sold it'.
    """
    seen, out = set(), []
    for form in (catno, catno.replace(" ", "-"), catno.replace(" ", ""),
                 catno.replace("-", " "), catno.replace("-", "")):
        f = form.strip()
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def cdjapan(catno: str) -> tuple[str, dict]:
    """The retailer's own product page, keyed directly by catalogue number.

    Worth trusting on the date specifically: it is the listing the shop sold,
    and on the X Japan disc it is the page English Wikipedia CITED while
    printing a different date to the one it says.
    """
    last = NONE
    for form in catalog_forms(catno):
        st, got = _cdjapan_one(form)
        if st == OK:
            return st, got
        last = st if st == BLOCKED else last
    return last, {}


def _cdjapan_one(catno: str) -> tuple[str, dict]:
    url = f"https://www.cdjapan.co.jp/product/{urllib.parse.quote(catno)}"
    try:
        page = M._get(url, ua=M.BROWSER_UA, timeout=25).decode("utf-8", "replace")
    except Exception as e:                      # noqa: BLE001
        return _shape_status(e), {}

    def field(label: str) -> str:
        m = re.search(r">%s</th>\s*<td[^>]*>(.*?)</td>" % label, page, re.S | re.I)
        return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())) if m else ""

    title = ""
    m = re.search(r"<title>(.*?)</title>", page, re.S)
    if m:
        title = html.unescape(m.group(1)).replace("CDJapan :", "").strip()
    # The product shot lives under /pictures/l/ - `l` is their large size; the
    # `xl`/`ll` variants answer 200 with a ~1.6 KB placeholder, so asking for a
    # bigger one and trusting the status code gets you a broken image.
    img = ""
    for mm in re.finditer(r'src="(//st\.cdjapan\.co\.jp/pictures/[^"]+)"', page):
        if catno.split("-")[0].upper() in mm.group(1).upper() or "/l/" in mm.group(1):
            img = "https:" + mm.group(1)
            break
    got = {"date": _iso(field("Release Date")), "type": field("Product Type"),
           "title": title, "image": img}
    return (OK if got["date"] or got["title"] else NONE), got


_MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october "
    "november december".split(), 1)}


def _iso(text: str) -> str:
    """'September 05, 2001' / '2001年9月5日' / '2001.9.5' -> '2001-09-05'."""
    t = (text or "").strip()
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", t)
    if m and m.group(1).lower() in _MONTHS:
        return "%s-%02d-%02d" % (m.group(3), _MONTHS[m.group(1).lower()], int(m.group(2)))
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日$", t)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})$", t)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return t


# -------------------------------------------------------- metal archives ---
MA = "https://www.metal-archives.com"
# Where the running track record goes. The point of carrying this source at all
# is to find out whether it EARNS a vote, and that needs evidence across many
# rip sessions rather than the one disc it was first tried on.
MA_TALLY = Path(os.environ.get("CONCERT_MA_TALLY")
                or (os.environ.get("RIP_LOG_DIR")
                    or "/mnt/media/STAGING/.dvdrip-logs") + "/ma_tally.jsonl")
_MA_MEMO: dict[str, tuple[str, dict]] = {}


def metal_archives(catno: str) -> tuple[str, dict]:
    """Encyclopaedia Metallum, keyed by catalogue number.

    OBSERVATIONAL ONLY - deliberately not one of the competing claims, for the
    reason given in the ja.wikipedia note in `fact_report`: a source that can
    turn a clean AGREED into a DISAGREE (and so block `--batch` auto-apply) has
    to have earned that power, and this one has not yet. It is carried because
    the disc queue is metal-heavy and its track record is worth measuring.

    There is no official API and no key exists to apply for, but none is needed:
    the site's own DataTables endpoint answers unauthenticated, and
    `releaseCatalogNumber` is one of its real advanced-search fields - so this is
    a genuine catalogue-keyed lookup, not a title guess.

    NONE is the EXPECTED answer for most of this library. It indexes metal only,
    so 'no such release' is a fact about the database's scope and must never be
    confused with the site being unreachable.
    """
    if not catno:
        return SKIPPED, {}
    if catno in _MA_MEMO:                       # the report and --batch both ask
        return _MA_MEMO[catno]
    last = NONE
    out: tuple[str, dict] = (NONE, {})
    for form in catalog_forms(catno):
        st, got = _ma_one(form)
        if st == OK:
            out = (st, got)
            break
        if st == BLOCKED:                       # a fault, not an answer - stop
            out = (st, {})
            break
        last = st
    else:
        out = (last, {})
    _MA_MEMO[catno] = out
    return out


def _ma_get(url: str, referer: str = "") -> tuple[str, bytes]:
    """Fetch via curl, because urllib CANNOT reach this host.

    Measured 2026-08-15: curl returns 200 while urllib returns 403 for the very
    same URL, user-agent and headers - every combination of Accept,
    Accept-Encoding, Connection, Referer and X-Requested-With still 403s. So it
    is not a header the request is missing; the host fingerprints the TLS client
    hello and python's differs from curl's. Do not "fix" this by going back to
    `M._get` with more headers - that was tried and measured.

    Returns a status from the module's vocabulary plus the body, so a genuine
    'no such release' stays distinguishable from the site refusing us.
    """
    cmd = ["curl", "-s", "--compressed", "--max-time", "25",
           "-A", M.BROWSER_UA, "-o", "-", "-w", "\n%{http_code}"]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=40)
    except Exception:                           # noqa: BLE001 - curl absent/hung
        return BLOCKED, b""
    if r.returncode != 0:
        return BLOCKED, b""
    body, _, code = r.stdout.rpartition(b"\n")
    try:
        status = int(code.strip() or 0)
    except ValueError:
        return BLOCKED, b""
    if status == 200:
        return OK, body
    return (NONE if status == 404 else BLOCKED), b""


def _ma_one(catno: str) -> tuple[str, dict]:
    url = (f"{MA}/search/ajax-advanced/searching/albums/"
           f"?releaseCatalogNumber={urllib.parse.quote(catno)}"
           f"&sEcho=1&iDisplayStart=0&iDisplayLength=25")
    st, raw = _ma_get(url, referer=f"{MA}/search/advanced/searching/albums")
    if st != OK:
        return st, {}
    try:
        hits = json.loads(raw).get("aaData") or []
    except Exception:                           # noqa: BLE001 - a 200 of junk
        return BLOCKED, {}
    if not hits:
        return NONE, {}

    row = hits[0]
    def _text(cell: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", cell or "")).strip()
    link = re.search(r'href="([^"]+)"', row[1] if len(row) > 1 else "")
    got = {
        "band": _text(row[0] if row else ""),
        "title": _text(re.sub(r"<!--.*?-->", "", row[1] if len(row) > 1 else "")),
        "type": _text(row[2] if len(row) > 2 else ""),
        "catalog": _text(row[3] if len(row) > 3 else ""),
        "url": link.group(1) if link else "",
        "date": "",
        "hits": len(hits),
    }
    # The search row carries no date; only the release page does.
    if got["url"]:
        pst, praw = _ma_get(got["url"])
        if pst == OK:
            page = praw.decode("utf-8", "replace")
            page = re.sub(r"<script.*?</script>", "", page, flags=re.S)
            for m in re.finditer(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", page, re.S):
                key = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip().rstrip(":")
                val = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                if key.lower() == "release date":
                    # MA writes ordinals: 'March 26th, 2008'.
                    got["date"] = _iso(re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", val))
                elif key.lower() == "catalog id" and val:
                    got["catalog"] = val
        # A failed page read costs the date, not the hit - the search row still
        # proves the release is indexed under this catalogue number.
    return OK, got


def _ma_record(catno: str, ma_st: str, ma: dict, dates: dict) -> None:
    """Append one line of track record. Best-effort: never break a research run.

    Records what the OTHER sources concluded beside what MA said, because the
    only question worth answering later is 'when it had an opinion, was it
    right' - a bare log of its own answers cannot say that.
    """
    try:
        others = sorted(dates)
        agreed = others[0] if len(others) == 1 else ""
        ma_date = (ma or {}).get("date", "")
        if ma_st != OK:
            verdict = f"no-opinion:{ma_st}"
        elif not ma_date:
            verdict = "hit-but-no-date"
        elif not agreed:
            verdict = "others-disagree" if others else "others-silent"
        else:
            verdict = "match" if ma_date == agreed else "DIFFERS"
        MA_TALLY.parent.mkdir(parents=True, exist_ok=True)
        with MA_TALLY.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "catno": catno,
                "ma_status": ma_st,
                "ma_date": ma_date,
                "ma_title": (ma or {}).get("title", ""),
                "others": {d: sorted(set(w)) for d, w in dates.items()},
                "verdict": verdict,
            }, ensure_ascii=False) + "\n")
    except Exception:                            # noqa: BLE001
        pass


def ma_tally_summary() -> str:
    """One line of accumulated evidence, or '' when there is nothing to say."""
    try:
        rows = [json.loads(l) for l in MA_TALLY.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:                            # noqa: BLE001
        return ""
    seen = {r.get("catno"): r for r in rows}      # a re-run replaces its own row
    judged = [r for r in seen.values() if r.get("verdict") in ("match", "DIFFERS")]
    if not judged:
        return ""
    good = sum(1 for r in judged if r["verdict"] == "match")
    off = [r["catno"] for r in judged if r["verdict"] == "DIFFERS"]
    line = f"  metal-archives track record: agreed on {good}/{len(judged)} discs it had a date for"
    if off:
        line += f"; differed on {', '.join(off)}"
    return line


# ------------------------------------------------------------ sonymusic ---
def sonymusic(slug: str, catno: str) -> tuple[str, str]:
    """(status, jacket image url) from the label's own discography page.

    The page is JS-rendered and its body is a navigation shell, but its
    `og:image` IS the release's jacket, and a label's own scan beats a shop
    photo and a fair-use wiki thumbnail every time.

    Two traps, both hit for real on KSB5-5734:

    * the catalogue number goes into the PATH literally, so `KSB5 5734` off the
      case is not even a legal URL - it raises rather than 404s;
    * a form that resolves to no release still answers **200**, with the band's
      ARTIST PHOTO as its og:image. `KSB55734` returns a perfectly good picture
      of the wrong thing, which is the worst kind of answer. The path is the
      discriminator: a real release image sits under `/jacket_image/`, the
      fallback under `/artist_photo/`.
    """
    blocked = False
    for form in catalog_forms(catno):
        if " " in form:
            continue
        try:
            page = M._get(
                f"https://www.sonymusic.co.jp/artist/{slug}/discography"
                f"/{urllib.parse.quote(form)}", ua=M.BROWSER_UA, timeout=25
            ).decode("utf-8", "replace")
        except Exception as e:                  # noqa: BLE001
            blocked = blocked or _shape_status(e) == BLOCKED
            continue
        m = re.search(r'<meta property="og:image" content="([^"]+)"', page)
        if m and "jacket_image" in m.group(1):
            return OK, m.group(1)
    return (BLOCKED if blocked else NONE), ""


# ---------------------------------------------------------- ja.wikipedia ---
def _fold(s: str) -> str:
    """Compare Japanese titles without tripping on spacing or width.

    MusicBrainz files the X Japan disc as `BLUE BLOOD TOUR 爆発寸前 GIG` and
    ja.wikipedia as `BLUE BLOOD TOUR 爆発寸前GIG` - one space apart, so plain
    equality fails on two names for one thing.
    """
    return re.sub(r"[\s　'\"’”「」『』・･,.\-–—:;!?()（）]+", "", (s or "")).lower()


def ja_release_dates(ja_title: str) -> tuple[str, dict]:
    """Every date on this release's row of a ja.wikipedia discography table.

    Deliberately NOT 'the DVD date'. These tables carry one column per format
    (`!VHS 発売日 !LD 発売日 !DVD 発売日 !Blu-ray 発売日`) and use `rowspan` on
    the label column, so a row after a rowspan has FEWER cells than the header
    has columns and positional mapping silently slides a value under the wrong
    heading - the same class of bug that dated a DVD to its VHS pressing five
    years early off a `<br>`-separated infobox.

    For CORROBORATION the column does not matter: the question is only whether
    the date a source claims appears on this release's row at all. Columns are
    labelled when the counts line up, and the labels are marked uncertain when
    they do not.
    """
    if not ja_title:
        return SKIPPED, {}
    try:
        pages = M.wiki_find("ja.wikipedia", ja_title)[:3]
    except Exception as e:                      # noqa: BLE001
        return _shape_status(e), {}
    want = _fold(ja_title)
    for page in pages:
        try:
            d = M.wiki_api("ja.wikipedia", action="parse", page=page, prop="wikitext")
        except Exception:                       # noqa: BLE001 - try the next page
            continue
        w = d.get("parse", {}).get("wikitext", {}).get("*", "")
        headers, cells, in_row = [], [], False
        for line in w.splitlines():
            s = line.strip()
            if s.startswith("!"):
                headers.append(re.sub(r"^!|style=.*?\|", "", s).strip())
            elif s.startswith("|-"):
                if in_row and cells:
                    break
                headers = headers if headers else []
                cells, in_row = [], False
            elif s.startswith("|"):
                val = M._dewiki(re.sub(r"^\|\s*(?:[a-z\-]+=\"[^\"]*\"\s*)*\|?", "", s))
                if not in_row and want and want in _fold(val):
                    in_row = True
                    cells = [val]
                elif in_row:
                    cells.append(val)
        if in_row and cells:
            dates = [_iso(v) for v in cells if re.match(r"\d{4}年\d{1,2}月\d{1,2}日$", v.strip())]
            labelled = {}
            if len(cells) == len(headers):
                labelled = {h: _iso(c) for h, c in zip(headers, cells)
                            if re.match(r"\d{4}年\d{1,2}月\d{1,2}日$", c.strip())}
            return OK, {"page": page, "dates": dates, "labelled": labelled,
                        "aligned": len(cells) == len(headers)}
    return NONE, {}


# ------------------------------------------------------------ the facts ---
def corroborate(catno: str, mb: list[dict], ja_title: str) -> dict:
    """The fact check as DATA, for a caller that has to decide without a human.

    `fact_report` renders this; `--batch` in plex_concert_meta reads it. Keeping
    one implementation matters more than the small refactor: a batch run that
    judged a date by different rules than the report a human reads would be a
    second opinion nobody asked for.
    """
    dates: dict[str, set[str]] = {}
    st, hits = discogs_by_catalog(catno) if catno else (SKIPPED, [])
    discogs_date = ""
    if st == OK:
        _, full = discogs_release(hits[0]["id"])
        discogs_date = full.get("date", "") or ""
    cd_st, cd = (cdjapan(catno) if catno else (SKIPPED, {}))
    for src, d in (("MusicBrainz", mb[0]["date"] if mb else ""),
                   ("Discogs", discogs_date),
                   ("CDJapan", cd.get("date", ""))):
        if re.match(r"\d{4}-\d{2}-\d{2}$", d or ""):
            dates.setdefault(d, set()).add(src)
    ja_st, ja = ja_release_dates(ja_title)
    ja_dates = set(ja.get("dates") or [])
    agreed = ""
    if len(dates) == 1:
        only = next(iter(dates))
        if len(dates[only]) > 1:
            agreed = only
    # Observational only. It is deliberately absent from `dates`, so it can
    # neither create `conflict` nor block `--batch` auto-apply - it rides along
    # so its track record accrues while a human decides whether it deserves a
    # vote. Promoting it is a one-line change HERE, and should be argued from
    # `ma_tally_summary()`, not from a hunch.
    ma_st, ma = metal_archives(catno) if catno else (SKIPPED, {})
    return {
        "dates": {k: sorted(v) for k, v in dates.items()},
        "agreed": agreed,                  # '' unless >=2 sources say the same day
        "conflict": len(dates) > 1,
        "ma_status": ma_st,
        "ma_date": ma.get("date", ""),
        "ma_agrees": bool(agreed and ma.get("date") == agreed),
        "ja_dates": sorted(ja_dates),
        "ja_corroborates": bool(agreed and agreed in ja_dates),
        "sources_seen": sorted({s for v in dates.values() for s in v}),
    }


def fact_report(catno: str, mb: list[dict], ja_title: str) -> None:
    print(f"\n{'=' * 72}\nFACTS for catalogue number {catno or '(none given)'}\n{'=' * 72}")
    rows: list[tuple[str, str, str, str]] = []
    dates: dict[str, list[str]] = {}

    def note(src: str, date: str, extra: str, title: str) -> None:
        rows.append((src, date or "-", extra or "-", title or "-"))
        if re.match(r"\d{4}-\d{2}-\d{2}$", date or ""):
            dates.setdefault(date, []).append(src)

    for r in mb:
        note("MusicBrainz", r["date"], f"{r['catalog']} {'/'.join(r['formats'])}", r["title"])

    st, hits = discogs_by_catalog(catno) if catno else (SKIPPED, [])
    if st == OK:
        top = hits[0]
        dst, full = discogs_release(top["id"])
        note("Discogs", full.get("date", "") or top["year"],
             f"{top['catalog']} {'/'.join(top['formats'][:2])} {top['country']}", top["title"])
        for extra in hits[1:4]:
            note("  discogs (other pressing)", extra["year"],
                 f"{extra['catalog']} {'/'.join(extra['formats'][:2])} {extra['country']}",
                 extra["title"])
    else:
        note("Discogs", "", f"[{st}]", "")

    st, cd = (cdjapan(catno) if catno else (SKIPPED, {}))
    note("CDJapan", cd.get("date", ""), cd.get("type", "") or f"[{st}]", cd.get("title", ""))

    # ja.wikipedia is deliberately NOT one of the competing claims above. Its
    # row is one release across every pressing it ever had - the X Japan row
    # carries a VHS, an LD, a DVD and a Blu-ray date - so scoring those four as
    # four rival answers to "when did this come out" invents a disagreement out
    # of a complete and correct table. It is a CORROBORATOR: the question it
    # answers is whether the date the catalogue-keyed sources claim appears
    # among this release's pressings at all.
    # metal-archives rides in the same lane as ja.wikipedia below: reported,
    # never counted. It indexes metal only, so `none` here is the database's
    # scope and not a fault - the row says which of the two it was.
    ma_st, ma = metal_archives(catno) if catno else (SKIPPED, {})
    if ma_st == OK:
        rows.append(("metal-archives*", ma.get("date", "") or "-",
                     f"{ma.get('catalog', '')} {ma.get('type', '')}".strip()
                     or "[hit, no date on the page]",
                     ma.get("title", "") or "-"))
    else:
        rows.append(("metal-archives*", "-",
                     "[not a metal release / not indexed]" if ma_st == NONE
                     else f"[{ma_st}]", "-"))

    st, ja = ja_release_dates(ja_title)
    ja_dates = set(ja.get("dates") or [])
    if st == OK:
        if not ja["dates"]:
            lab = "found the page but no dated release row on it"
        elif ja["aligned"]:
            lab = ", ".join(f"{k}={v}" for k, v in ja["labelled"].items())
        else:
            lab = "one date per pressing; columns not aligned (rowspan)"
        rows.append(("ja.wikipedia", " ".join(ja["dates"]) or "-", lab, ja["page"]))
    else:
        rows.append(("ja.wikipedia", "-", f"[{st}]", "-"))

    w = max(len(r[0]) for r in rows) + 1
    print(f"  {'source':<{w}} {'date':<12} {'detail':<38} title")
    for src, date, extra, title in rows:
        print(f"  {src:<{w}} {date:<12} {extra[:37]:<38} {title[:40]}")

    print("-" * 72)
    if not dates:
        print("  no full date from a catalogue-keyed source - nothing to corroborate")
    elif len(dates) == 1:
        d, who = next(iter(dates.items()))
        # One source is not agreement. Saying "AGREED" over a single answer is
        # the false confidence this whole report exists to prevent - it is how
        # a wrong catalogue number goes unquestioned for a day.
        n = len(set(who))
        head = "AGREED" if n > 1 else "ONE SOURCE ONLY (uncorroborated)"
        line = f"  {head}: {d}  ({', '.join(sorted(set(who)))})"
        if ja_dates and d in ja_dates:
            line += "  + corroborated by ja.wikipedia's release table"
        elif ja_dates:
            line += (f"\n  !! but ja.wikipedia lists this release's pressings as "
                     f"{', '.join(sorted(ja_dates))} - {d} is not among them, so "
                     f"check you have the right pressing")
        print(line)
    else:
        print("  !! CATALOGUE-KEYED SOURCES DISAGREE - do not accept one without a third:")
        for d, who in sorted(dates.items()):
            mark = "  <- also on ja.wikipedia's row" if d in ja_dates else ""
            print(f"       {d}  {', '.join(sorted(set(who)))}{mark}")
        if ja_dates & set(dates):
            print("  the tie-break above is the release table, which lists every pressing.")
        print("  the catalogue number read off the case is the disc's identity;")
        print("  prefer the source that keyed off it (Discogs/CDJapan/MusicBrainz).")

    # Printed AFTER the verdict on purpose: this source does not participate in
    # it, and putting it above would read as though it did.
    _ma_record(catno, ma_st, ma, dates)
    if ma_st == OK and ma.get("date"):
        ma_d = ma["date"]
        if ma_d in dates:
            print(f"  * metal-archives agrees ({ma_d}) - observational, not counted above")
        else:
            print(f"  * metal-archives says {ma_d}, which no source counted above says.")
            print("    Not counted: it is user-submitted like MB/Discogs and has not earned a")
            print("    vote. A prompt to go and look, never a veto.")
    summary = ma_tally_summary()
    if summary:
        print(summary)


# --------------------------------------------------------------- covers ---
def normalise(raw: bytes, dest: Path) -> tuple[int, int] | None:
    """Write a viewable PNG and report its real size.

    Everything downstream is a human looking at it, and half these sources
    serve WebP from a `.jpg` URL (fandom does it, and it is why a cover had to
    be converted by hand). ffmpeg both converts and measures, so a file that is
    actually an HTML error page fails here rather than in the viewer.
    """
    tmp = dest.with_suffix(".raw")
    tmp.write_bytes(raw)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), str(dest)],
                       capture_output=True)
    tmp.unlink(missing_ok=True)
    if r.returncode != 0 or not dest.exists():
        return None
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(dest)],
                       capture_output=True, text=True)
    try:
        wd, ht = p.stdout.strip().split(",")[:2]
        return int(wd), int(ht)
    except ValueError:
        return None


# A poster needs roughly 1000x1500; below this there is nothing to enlarge.
# Measured on the SHORT side, not the width: a DVD jacket is portrait, and a
# width floor threw away CDJapan's 255x360 and a wiki's 266x375 while keeping
# a wide, shallow one.
COVER_MIN_SIDE = 250


def best_cover(cands: list[dict]) -> dict | None:
    """The candidate to try first: whichever image its SOURCE calls the front,
    and only then the biggest.

    Ranking by size alone picked the BACK PANEL of Deco Vs Deco - Discogs'
    secondary scan is 477x600 against the front's 420x600, so "largest" and
    "front" are simply unrelated, and a poster of the back of a case is a
    silent, entirely plausible-looking wrong answer.

    Discogs marks exactly one image `primary`, which is the front. That is the
    source stating the answer, the same shape as a `{{tracklist}}` block
    labelling itself `DVD（プレミアム盤）`: a declaration beats any measurement
    inferred from the pixels. Where no source declares anything, size is all
    that is left - which is exactly why every composed poster is still LOOKED
    AT afterwards.

    (Not a source priority list either: "the label's own jacket always wins" is
    false too, since Sony's X Japan image is the whole flattened sleeve while
    its Blu-ray reissue's is the clean front art.)
    """
    usable = [c for c in cands
              if c.get("path") and min(c.get("w") or 0, c.get("h") or 0) >= COVER_MIN_SIDE]
    if not usable:
        return None
    return sorted(usable, key=lambda c: (not c.get("primary"),
                                         -(c["w"] * c["h"]), c["source"]))[0]


def collect_covers(out: Path, artist: str, catno: str, mbid: str,
                   sony_slug: str, wiki: str, wiki_page: str) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    found: list[dict] = []
    n = 0

    def take(source: str, url: str, note: str = "", primary: bool = False) -> None:
        nonlocal n
        if not url:
            return
        n += 1
        dest = out / f"{n:02d}-{source}.png"
        try:
            raw = M._get(url, ua=M.BROWSER_UA, timeout=30)
        except Exception as e:                  # noqa: BLE001
            found.append({"source": source, "status": _shape_status(e), "note": note})
            return
        size = normalise(raw, dest)
        if not size:
            found.append({"source": source, "status": "not an image", "note": note})
            return
        found.append({"source": source, "status": OK, "note": note,
                      "path": str(dest), "w": size[0], "h": size[1],
                      "primary": primary})

    if catno:
        st, hits = discogs_by_catalog(catno)
        if st == OK:
            dst, full = discogs_release(hits[0]["id"])
            imgs = full.get("images") or []
            # Primary first and LABELLED as such: it is the front cover, and
            # ranking the rest by size picked a back panel once already.
            ordered = ([i for i in imgs if i.get("type") == "primary"][:1]
                       + [i for i in imgs if i.get("type") != "primary"][:2])
            for i, im in enumerate(ordered, 1):
                is_front = im.get("type") == "primary"
                take(f"discogs{i}", im["uri"],
                     "FRONT (Discogs calls this the primary image)" if is_front
                     else "a secondary scan - back panel, insert or inner art",
                     primary=is_front)
            if not imgs:
                take("discogs", hits[0]["cover"], "search thumbnail")
        else:
            found.append({"source": "discogs", "status": st, "note": ""})
        st, cd = cdjapan(catno)
        take("cdjapan", cd.get("image", ""),
             "shop photo - often the SHRINK-WRAPPED package, obi and price sticker")

    if mbid:
        take("coverart-archive", f"{M.CAA}/release/{mbid}/front", "")

    if sony_slug and catno:
        st, url = sonymusic(sony_slug, catno)
        if st == OK:
            take("sonymusic", url, "the label's own jacket - usually the best there is")
        else:
            found.append({"source": "sonymusic", "status": st, "note": ""})

    if wiki and wiki_page:
        try:
            _, img, _ = M.wiki_intro(wiki, wiki_page)
            take("wiki", M.wiki_image_url(wiki, img) if img else "", f"{wiki}: {img}")
        except Exception as e:                  # noqa: BLE001
            found.append({"source": "wiki", "status": _shape_status(e), "note": ""})

    return found


def harvest_covers(out: Path, artist: str, catno: str, mbid: str,
                   sony_slug: str, wiki: str, wiki_page: str) -> list[dict]:
    print(f"\n{'=' * 72}\nCOVER CANDIDATES -> {out}\n{'=' * 72}")
    found = collect_covers(out, artist, catno, mbid, sony_slug, wiki, wiki_page)
    if not found:
        print("  nothing tried - give --catalog, --mbid, --sony or --wiki/--wiki-page")
        return found
    w = max(len(f["source"]) for f in found) + 1
    for c in found:
        detail = (f"{c['w']}x{c['h']}  {c['path']}" if c.get("path")
                  else f"[{c['status']}]")
        print(f"  {c['source']:<{w}} {detail}")
        if c.get("note"):
            print(f"  {'':<{w}} {c['note']}")
    print("-" * 72)
    print("  LOOK AT THEM before choosing - a shop photo of a shrink-wrapped case")
    print("  and a clean jacket scan are the same size and the same file type.")
    pick = best_cover(found)
    if pick:
        print(f"  best guess: {pick['source']} ({pick['w']}x{pick['h']}) {pick['path']}")
    print(f"  then: plex_concert_meta.py --item <rk> --artwork-only --cover-file {out}/NN-x.png")
    return found


# ---------------------------------------------------------- local scans ---
def _catno_variants(catno: str) -> list[str]:
    """The case prints `KSB5 5734`, the databases file `KSB5-5734`, and a
    filename could use either. Never "tidy" the captured string - try both."""
    c = catno.strip()
    out = [c]
    for a, b in ((" ", "-"), ("-", " ")):
        if a in c:
            out.append(c.replace(a, b))
    return list(dict.fromkeys(out))


def _set_mates(catno: str) -> list[str]:
    """A multi-disc set has ONE booklet filed under ONE catalogue number: the
    VIBP-31 page carries disc 2's credits too. Most sets in this library are
    2-disc, so matching only the exact catno would miss the booklet on every
    disc 2 - which is exactly the disc whose facts are hardest to find."""
    m = re.match(r"^(.*?)(\d+)$", catno.strip())
    if not m:
        return []
    head, num = m.group(1), m.group(2)
    mates = []
    for delta in (-2, -1, 1, 2):
        n = int(num) + delta
        if n >= 0:
            mates.append(f"{head}{n:0{len(num)}d}")
    return mates


def local_scans(catno: str) -> tuple[str, list[Path], list[Path]]:
    """(status, exact-catno files, set-mate files). A missing directory is
    BLOCKED, never NONE - "the scans directory is not there" and "nobody ever
    scanned this one" are the same empty list and mean opposite things."""
    if not catno:
        return SKIPPED, [], []
    try:
        if not SCANS_DIR.is_dir():
            return BLOCKED, [], []
        files = sorted(p for p in SCANS_DIR.iterdir() if p.is_file())
    except OSError:
        return BLOCKED, [], []

    def hits(keys: list[str]) -> list[Path]:
        low = [k.lower() for k in keys]
        return [p for p in files
                if any(p.name.lower().startswith(k) for k in low)]

    exact = hits(_catno_variants(catno))
    mate_keys: list[str] = []
    for m in _set_mates(catno):
        mate_keys.extend(_catno_variants(m))
    mates = [p for p in hits(mate_keys) if p not in exact]
    return (OK if (exact or mates) else NONE), exact, mates


def _describe_scan(p: Path) -> str:
    """Fixed width, so a trailing set-mate marker lines up down the column."""
    kb = f"{p.stat().st_size / 1024:.0f} KB"
    if p.suffix.lower() in (".txt", ".md"):
        return f"{kb:>9}  {'transcribed notes':<17}"
    try:
        dim = subprocess.run(["identify", "-format", "%wx%h", str(p)],
                             capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:                           # noqa: BLE001
        dim = ""
    return f"{kb:>9}  {dim:<17}"


def scans_report(catno: str) -> None:
    print(f"\n{'=' * 72}\nLOCAL SCANS (owner-supplied) -> {SCANS_DIR}\n{'=' * 72}")
    status, exact, mates = local_scans(catno)
    if status == SKIPPED:
        print("  no catalogue number yet - nothing to look them up by")
        return
    if status == BLOCKED:
        print(f"  [blocked] {SCANS_DIR} is missing or unreadable.")
        print("  That is NOT 'he never scanned this one'. Fix the path, or set")
        print("  CONCERT_SCANS_DIR, before concluding there is no booklet photo.")
        return
    if status == NONE:
        print(f"  none filed for {catno}")
        print("  If a booklet page matters and no online scan is sharp enough,")
        print(f"  PHOTOGRAPH THE DISC. It goes here as {catno}-booklet.jpg, with a")
        print(f"  transcribed {catno}-credits.txt beside it.")
        return
    w = max(len(p.name) for p in exact + mates) + 2
    for p in exact:
        print(f"  {p.name:<{w}}{_describe_scan(p)}")
    for p in mates:
        print(f"  {p.name:<{w}}{_describe_scan(p)}   <- SET-MATE catno, same booklet")
    print("-" * 72)
    print("  READ THESE FIRST, before the online sources below. A booklet photo")
    print("  outranks every online scan: on VIBP-31 the Discogs scan gave the bonus")
    print("  songs as '07.0?.2002' and the photo gave 07.05.2002.")


# ----------------------------------------------------------------- main ---
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--item", help="ratingKey - reads the title and finds the catalogue number")
    ap.add_argument("--catalog", help="catalogue number off the case, if there is no run log")
    ap.add_argument("--sony", help="sonymusic.co.jp artist slug, e.g. xjapan")
    ap.add_argument("--wiki", help="wiki for a cover candidate, e.g. oneokrock / wikipedia")
    ap.add_argument("--wiki-page", help="exact page title on that wiki")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="where to drop cover candidates")
    ap.add_argument("--facts-only", action="store_true")
    ap.add_argument("--covers-only", action="store_true")
    ap.add_argument("--section-name", default="Concerts")
    args = ap.parse_args()

    artist = title = ""
    catno = args.catalog or ""
    if args.item:
        token = M.plex_token()
        M.find_section(token, args.section_name)
        item = M.get_item(token, args.item)
        artist, title, year = M.parse_title(item["title"])
        print(f"item    : {item['title']}")
        print(f"parsed  : artist={artist!r} title={title!r} year={year or '-'}")
        if not catno:
            catno, how = M.catalog_from_rip_logs(item["title"], item.get("file"),
                                                 with_reason=True)
            if catno:
                print(f"catalog : {catno}  (recovered from the ripper's run log "
                      f"by {how})")
    if not catno:
        print("!! no catalogue number - it is the disc's identity and every source "
              "here keys off it.\n   Pass --catalog, or read it off the case.")

    # Local before remote: the one source that outranks every database is a photo
    # of the booklet, and it costs nothing to look.
    scans_report(catno)

    # MusicBrainz first: it supplies both the corroboration row AND the original
    # Japanese title, which is the key ja.wikipedia has to be looked up by - the
    # romanisation in the library shares no characters with it.
    mb: list[dict] = []
    if catno:
        try:
            mb = M.mb_by_catalog(catno)
        except Exception as e:                  # noqa: BLE001
            print(f"  MusicBrainz: [{_shape_status(e)}]")
    ja_title = mb[0]["title"] if mb else ""
    mbid = mb[0]["id"] if mb else ""

    if not args.covers_only:
        fact_report(catno, mb, ja_title)
    if not args.facts_only:
        harvest_covers(Path(args.out).expanduser(), artist, catno, mbid,
                       args.sony or "", args.wiki or "", args.wiki_page or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
