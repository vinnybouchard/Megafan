#!/usr/bin/env python3
"""Fill in metadata for the Plex Concerts library, which runs no agent.

    python3 scripts/plex_concert_meta.py                  # what needs work
    python3 scripts/plex_concert_meta.py --item 4842      # do one
    python3 scripts/plex_concert_meta.py --item 4842 --catalog AZBS-1015
    python3 scripts/plex_concert_meta.py --item 4842 --wiki oneokrock
    python3 scripts/plex_concert_meta.py --item 4842 --wiki vocaloid --date 2015-03-11
    python3 scripts/plex_concert_meta.py --item 9296 --wiki wikipedia \
        --cover-file /tmp/jacket.jpg --summary-file /tmp/x.txt

WHY THIS IS ASSISTED AND NOT AUTOMATIC
--------------------------------------
Everything here was measured against the live library on 2026-08-11/12 before
it was written, and each measurement killed an "obvious" design:

* A naive MusicBrainz title search got 1 of 8 items right, and one of the two
  apparent hits was a FALSE POSITIVE scoring 100 - `Palms - Live` matched
  `Live Together, Eat Each Other`, a different release, wrong year, wrong
  format.  MB's `score` is text similarity, NOT confidence, so no threshold on
  it is a safety gate.  (Same trap the request board hit, where "lol" matches
  a real film with high confidence.)

* The titles in this library are the owner's romanisations; the databases hold
  the originals.  `Yononaka Shredder` vs `世の中シュレッダー` share ZERO
  characters - a similarity ratio is 0.0, not 0.6.  This is not a threshold
  that can be tuned, it is not a string problem at all.

* The sources contradict each other on plain facts, and nothing inside a
  pipeline can tell which is lying.  fandom lists the 2008 live DVD as
  AZBS-1009; MusicBrainz assigns AZBS-1009 to the 2012 Yokohama Arena DVD and
  gives the 2008 disc AZBL-1.  fandom's claimed Blu-ray for it, AZXS-1001,
  matches nothing anywhere.  That wrong number reached the live library and sat
  there unnoticed, because a catalogue number is exactly the kind of fact
  nobody re-checks.

So: this tool gathers, ranks and PREVIEWS.  A human picks the release and
confirms the text.  It never resolves a title on its own.

DIVISION OF LABOUR
------------------
MusicBrainz  - date, catalogue number, format, tracklist.  Structured, keyless.
The wiki     - prose only.  MB has no synopsis field, so the "debuted at number
               one on Oricon" sort of line exists only there.  Its FACTS are
               deliberately not trusted; the date and catalogue number always
               come from MB even when a wiki page was read.  `--wiki` takes a
               fandom subdomain OR `wikipedia` - fandom does not cover
               everything, and off the visual-kei scene it covers almost
               nothing.  Prose is not exempt from the distrust: it states
               dates too, and `--summary-file` is how you correct one.
Cover art    - the Cover Art Archive had no front art for any of these, so the
               poster comes from the wiki when one is given, `--cover-file`
               when you have something better (a label's own jacket scan beats
               a fair-use wiki thumbnail), otherwise whatever is already on
               disk is left alone.

Opens no datastore, runs no agent turn, makes no model call.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

PLEX = os.environ.get("PLEX_URL", "http://localhost:32400")
MB = "https://musicbrainz.org/ws/2"
CAA = "https://coverartarchive.org"
# MusicBrainz asks for one request per second and a UA that identifies the app.
MB_UA = os.environ.get(
    "MUSICBRAINZ_UA",
    "megafan/1.0 ( https://github.com/vinnybouchard/Megafan )",
)
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
)
MB_INTERVAL = 1.2

# A concert release is a STANDALONE video disc.  An album that ships with a
# bonus DVD is CD/DVD-Video, and that is the pair which actually collides in
# practice: in 2013 this artist released both `人生×僕=` (album + bonus DVD)
# and the `人生×君=` tour DVD.  Requiring video-without-CD separates them
# structurally rather than by guessing at the title.
VIDEO_FORMATS = {"DVD", "DVD-Video", "Blu-ray", "Blu-ray Disc", "HD-DVD", "VHS"}

_last_mb = 0.0


def _get(url: str, ua: str = MB_UA, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return f.read()


def mb_get(path: str, **params) -> dict:
    """One MusicBrainz call, rate limited to their stated 1 req/sec."""
    global _last_mb
    wait = MB_INTERVAL - (time.time() - _last_mb)
    if wait > 0:
        time.sleep(wait)
    params.setdefault("fmt", "json")
    url = f"{MB}/{path}?{urllib.parse.urlencode(params)}"
    try:
        data = json.loads(_get(url))
    finally:
        _last_mb = time.time()
    return data


# ----------------------------------------------------------------- plex ---
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


def plex_xml(path: str, token: str, **params) -> ET.Element:
    params["X-Plex-Token"] = token
    return ET.fromstring(_get(f"{PLEX}{path}?{urllib.parse.urlencode(params)}", ua=MB_UA))


def find_section(token: str, name: str) -> str:
    root = plex_xml("/library/sections", token)
    for d in root.findall("Directory"):
        if (d.get("title") or "").lower() == name.lower():
            return d.get("key")
    sys.exit(f"No library section called {name!r}")


def list_items(token: str, section: str) -> list[dict]:
    root = plex_xml(f"/library/sections/{section}/all", token)
    out = []
    for v in root.iter("Video"):
        out.append(
            {
                "rk": v.get("ratingKey"),
                "title": v.get("title") or "",
                "year": v.get("year"),
                "oaa": v.get("originallyAvailableAt"),
                "summary": v.get("summary") or "",
            }
        )
    return sorted(out, key=lambda i: i["title"])


def get_item(token: str, rk: str) -> dict:
    v = plex_xml(f"/library/metadata/{rk}", token).find("Video")
    if v is None:
        sys.exit(f"No item with ratingKey {rk}")
    part = v.find("./Media/Part")
    return {
        "rk": rk,
        "title": v.get("title") or "",
        "year": v.get("year"),
        "oaa": v.get("originallyAvailableAt"),
        "summary": v.get("summary") or "",
        "file": part.get("file") if part is not None else None,
    }


def apply_metadata(token: str, section: str, rk: str, summary: str, year: str, date: str) -> None:
    """Write it, then READ IT BACK - a Plex PUT can return 200 and be ignored.

    Everything is `.locked=1` because this library has no agent: an unlocked
    field is re-derived on the next scan, and with nothing to derive it FROM
    Plex stamps the scan date.  That is how a 2013 release came up as 2026.
    """
    params = {
        "type": "1",
        "id": rk,
        "summary.value": summary,
        "summary.locked": "1",
        "year.value": year,
        "year.locked": "1",
        "originallyAvailableAt.value": date,
        "originallyAvailableAt.locked": "1",
        "title.locked": "1",
        "X-Plex-Token": token,
    }
    url = f"{PLEX}/library/sections/{section}/all?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, method="PUT"), timeout=30) as r:
        print(f"  PUT HTTP {r.status}")


# ---------------------------------------------------------- musicbrainz ---
def mb_artist(name: str) -> tuple[str, str] | None:
    d = mb_get("artist/", query=f'artist:"{name}"', limit=5)
    hits = d.get("artists") or []
    if not hits:
        return None
    exact = [a for a in hits if (a.get("name") or "").lower() == name.lower()]
    a = (exact or hits)[0]
    return a["id"], a["name"]


def mb_video_releases(arid: str) -> list[dict]:
    """Every standalone video release for one artist, newest first."""
    rels, offset = [], 0
    while True:
        d = mb_get("release", artist=arid, inc="media+labels", limit=100, offset=offset)
        rels.extend(d.get("releases") or [])
        offset += 100
        if offset >= d.get("release-count", 0) or offset > 500:
            break
    out, seen = [], set()
    for r in rels:
        fmts = {(m.get("format") or "") for m in (r.get("media") or [])}
        if not (fmts & VIDEO_FORMATS):
            continue
        out.append(_shape(r, standalone="CD" not in fmts))
        seen.add(r["id"])
    out.sort(key=lambda r: (not r["standalone"], r["date"] or ""), reverse=False)
    out.sort(key=lambda r: r["date"] or "", reverse=True)
    return out


def mb_by_catalog(catno: str) -> list[dict]:
    d = mb_get("release/", query=f'catno:"{catno}"', limit=5, inc="media+labels")
    return [_shape(r, standalone=True) for r in (d.get("releases") or [])]


def _shape(r: dict, standalone: bool) -> dict:
    media = r.get("media") or []
    fmts = sorted({(m.get("format") or "?") for m in media})
    cats = [li.get("catalog-number") for li in (r.get("label-info") or []) if li.get("catalog-number")]
    return {
        "id": r["id"],
        "title": r.get("title") or "",
        "date": r.get("date") or "",
        "formats": fmts,
        "catalog": cats[0] if cats else "",
        "tracks": sum((m.get("track-count") or 0) for m in media),
        # How many VIDEO discs the release has - not how many media, since a
        # CD+DVD album has two and is not a set. `Deco Vs Deco` is one catalogue
        # number over three DVD-Videos (22 + 2 + 7 tracks), and the rip is ONE
        # of them, so its tracklist describes three times the disc on the shelf.
        "video_discs": sum(1 for m in media
                           if (m.get("format") or "") in VIDEO_FORMATS),
        "standalone": standalone,
    }


def mb_tracklist(release_id: str) -> list[str]:
    d = mb_get(f"release/{release_id}", inc="recordings")
    out = []
    for m in d.get("media") or []:
        # Skip a bonus CD sitting alongside the video disc.
        if (m.get("format") or "") not in VIDEO_FORMATS and len(d.get("media") or []) > 1:
            continue
        for t in m.get("tracks") or []:
            title = (t.get("title") or "").strip()
            if title:
                out.append(title)
    return out


# ------------------------------------------------------------- the wiki ---
_WIKIMEDIA = (".wikipedia.org", ".wikimedia.org", ".wiktionary.org", ".wikiquote.org")


def wiki_endpoint(sub: str) -> tuple[str, str]:
    """(api url, user agent) for a wiki name.

        oneokrock / visualkei              -> that fandom wiki
        wikipedia / en.wikipedia / …org    -> English Wikipedia
        ja.wikipedia                       -> Japanese Wikipedia

    fandom is not the whole world.  The X Japan DVD has no fandom page on any
    subdomain - x-japan.fandom.com exists, has 193 pages, and not one of them is
    this release - while English Wikipedia carries a full article including the
    ROMANISED setlist that MusicBrainz files under 紅 and オルガスム.  Off the
    visual-kei scene this only gets more true: a western artist has no fandom
    wiki at all and always has a Wikipedia article.

    The API path differs between the two families - fandom serves /api.php,
    Wikimedia /w/api.php - and probing both would be a guess, so the host
    decides.  The user agent differs too, in opposite directions: fandom 403s a
    tool-shaped UA, Wikimedia asks for one that names the tool.
    """
    s = sub.strip().lower().rstrip("/")
    s = s.removeprefix("https://").removeprefix("http://")
    if s in ("wikipedia", "wp"):
        s = "en.wikipedia.org"
    elif s.endswith(".wikipedia"):
        s += ".org"
    if "." not in s:
        return f"https://{s}.fandom.com/api.php", BROWSER_UA
    if s.endswith(_WIKIMEDIA):
        return f"https://{s}/w/api.php", MB_UA
    return f"https://{s}/api.php", BROWSER_UA


def wiki_api(sub: str, **params) -> dict:
    """fandom's page URLs 403 for everything; api.php answers normally."""
    params.setdefault("format", "json")
    api, ua = wiki_endpoint(sub)
    return json.loads(_get(f"{api}?" + urllib.parse.urlencode(params), ua=ua))


def wiki_find(sub: str, terms: str) -> list[str]:
    d = wiki_api(sub, action="query", list="search", srsearch=terms, srlimit=8)
    return [s["title"] for s in d.get("query", {}).get("search", [])]


def _strip_file_links(s: str) -> str:
    """Remove [[File:...]] / [[Image:...]] embeds, brackets matched properly.

    A regex cannot do this: the caption is free text and routinely contains its
    own links, e.g. [[File:x.jpg|thumb|[[ONE OK ROCK]] performing...]]. A
    non-greedy [^\\]]* stops at the INNER ]] and leaves the tail behind, which
    is how a setlist entry came out as
    "Be the Light performing in Yokohama Stadium.]]".
    """
    out, i, low = [], 0, s.lower()
    while i < len(s):
        cands = [p for p in (low.find("[[file:", i), low.find("[[image:", i)) if p != -1]
        if not cands:
            out.append(s[i:])
            break
        start = min(cands)
        out.append(s[i:start])
        depth, p = 0, start
        while p < len(s):
            if s.startswith("[[", p):
                depth += 1
                p += 2
            elif s.startswith("]]", p):
                depth -= 1
                p += 2
                if depth == 0:
                    break
            else:
                p += 1
        i = p
    return "".join(out)


# Templates that render as NOTHING in running prose, so deleting them is not a
# loss.  Everything else is deliberately LEFT IN PLACE: `{{nihongo|Kurenai|紅}}`
# IS the track title, and a blanket "remove every {{...}}" would silently delete
# it.  Junk left visible in the preview is something the human signs off on or
# catches; a vanished setlist entry is not.
_INVISIBLE_TEMPLATES = (
    "cite", "citation", "sfn", "refn", "efn", "reflist", "notability",
    "use mdy dates", "use dmy dates", "short description", "authority control",
    "infobox", "about", "for", "main", "see also", "further", "hatnote",
)
_TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}", re.S)


def _strip_invisible_templates(s: str) -> str:
    """Peel `{{cite web|…}}` and friends off, innermost first so nesting works."""
    def one(m: re.Match) -> str:
        name = m.group(1).split("|", 1)[0].strip().lower()
        return "" if name.startswith(_INVISIBLE_TEMPLATES) else m.group(0)

    for _ in range(6):
        out = _TEMPLATE.sub(one, s)
        if out == s:
            break
        s = out
    return s


def _strip_leading_templates(w: str) -> str:
    """Drop the `{{…}}` blocks a page OPENS with - maintenance banners, the
    infobox - by matching braces rather than by regex.

    The regex this replaces (`(?sm)^\\{\\{.*?^\\}\\}`) anchored the closing
    braces at the start of a line, which is only how some wikis write it.
    oneokrock closes its infobox mid-line and nests another template inside it:

        {{Template:Album Infobox
        |Date = November 21, 2007
        |MiX = {{Singles1}}}}

    so nothing matched, the substitution did nothing, and the entire infobox
    came back as the article's lead prose.  Exactly the failure `_dewiki`'s
    `(?s)`-without-`(?m)` bug had, and exactly why `_strip_file_links` counts
    brackets instead of matching them.  Unbalanced braces leave the page
    untouched rather than eating the article.
    """
    i = 0
    while True:
        j = i
        while j < len(w) and w[j].isspace():
            j += 1
        if not w.startswith("{{", j):
            return w[i:].lstrip()
        depth, p = 0, j
        while p < len(w):
            if w.startswith("{{", p):
                depth += 1
                p += 2
            elif w.startswith("}}", p):
                depth -= 1
                p += 2
                if depth == 0:
                    break
            else:
                p += 1
        if depth != 0:
            return w[i:]
        i = p


_NIHONGO_OPEN = re.compile(r"\{\{\s*nihongo\s*\|", re.I)


def _expand_nihongo(s: str) -> str:
    """`{{nihongo|english|kanji|romaji}}` -> the name this library is written in.

    The invisible-template allowlist deliberately LEAVES this one alone, because
    deleting it deletes a track title.  That was safe only while a human read
    every preview - the reasoning was literally "junk left visible in the
    preview is something the human catches".  `--batch` has no such human, and
    Maximum the Hormone's setlist is `{{nihongo}}` on nearly every line, so raw
    template markup was headed into Plex as the setlist.

    Not the blanket delete that was refused: this parses a template whose shape
    is known and takes the display text out of it.  Romaji first, then English,
    then the kanji, because this library is romanised throughout.
    """
    for block in _template_spans(s, _NIHONGO_OPEN):
        parts = _split_template_params(block[2:-2])
        vals = [p.strip() for p in parts[1:]]          # parts[0] is the name
        english = vals[0] if len(vals) > 0 else ""
        kanji = vals[1] if len(vals) > 1 else ""
        romaji = vals[2] if len(vals) > 2 else ""
        s = s.replace(block, romaji or english or kanji, 1)
    return s


def _dewiki(s: str) -> str:
    # Citations first, whole span. `<[^>]+>` below strips only the TAGS, which
    # would leave the citation's guts in the prose - a Wikipedia lead came out
    # as "…released on June 1, 1989.cite web|url=http://…|publisher=Jame World
    # It contains footage…", long and plausible enough to wave through.
    s = re.sub(r"(?is)<ref[^>]*/>", " ", s)
    s = re.sub(r"(?is)<ref[^>]*>.*?</ref>", " ", s)
    s = _strip_file_links(s)                             # images next
    s = _expand_nihongo(s)                               # before the allowlist
    s = _strip_invisible_templates(s)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)   # [[target|shown]] -> shown
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"'''?|<[^>]+>", " ", s)
    # After the tags, never before: unescaping first would turn a written-out
    # `&lt;sup&gt;` into a real tag for the line above to strip. A setlist entry
    # is genuinely titled `→&gt;&gt;8&lt;&lt;←` and reaches Plex as mojibake
    # otherwise.
    s = html.unescape(s)
    s = re.sub(r"[ \t ]+", " ", s)
    # A removed citation leaves the space it stood in, and it stood between
    # the word and its full stop: "...Shibuya Kohkaido ." Never right in prose.
    return re.sub(r" +([,.;:!?)])", r"\1", s).strip()


# A tracklist block names its own disc. `映像`/`ビデオ` are "video"/"video disc";
# the audio test is anchored so `DVD（プレミアム盤）` is not read as a CD just
# because the word appears somewhere later in a long label.
_VIDEO_LABEL = re.compile(r"DVD|Blu-?ray|\bBD\b|映像|ビデオ", re.I)
_AUDIO_ONLY_LABEL = re.compile(r"(?:CD|音源|Disc\s*\d)\b(?!.*(?:DVD|Blu-?ray|映像))", re.I)

# `{{tracklist}}` on ja.wikipedia, `{{Track listing}}` on en.wikipedia - the
# standard music template, and a THIRD way a setlist reaches a page after the
# `===Tracklist===`+`#` and `==Set list==`+`*` shapes already handled below.
_TRACKLIST_TEMPLATE = re.compile(r"\{\{\s*track\s*list(?:ing)?\s*(?=[|}])", re.I)


def _template_spans(w: str, opener: re.Pattern) -> list[str]:
    """Every brace-matched `{{…}}` block whose name matches `opener`.

    Braces are counted, not regexed, for `_strip_leading_templates`' reason: a
    track title is legitimately `{{nihongo|Kurenai|紅}}`, so a non-greedy match
    to the first `}}` would end the template in the middle of the setlist.
    """
    out = []
    for m in opener.finditer(w):
        depth, p = 0, m.start()
        while p < len(w):
            if w.startswith("{{", p):
                depth += 1
                p += 2
            elif w.startswith("}}", p):
                depth -= 1
                p += 2
                if depth == 0:
                    break
            else:
                p += 1
        if depth == 0:
            out.append(w[m.start():p])
    return out


def _split_template_params(body: str) -> list[str]:
    """Split `a|b|c` at depth 0 only.

    A pipe inside a link is part of the value, not a separator: track 17 here is
    `[[Take Me Out!!/Twilight|Twilight]]`, which a plain `.split("|")` turns into
    a parameter named `[[Take Me Out!!/Twilight` and a stray `Twilight]]`.
    """
    parts, cur, braces, brackets, i = [], [], 0, 0, 0
    while i < len(body):
        two = body[i:i + 2]
        if two == "{{":
            braces += 1
        elif two == "}}":
            braces -= 1
        elif two == "[[":
            brackets += 1
        elif two == "]]":
            brackets -= 1
        else:
            if body[i] == "|" and braces == 0 and brackets == 0:
                parts.append("".join(cur))
                cur = []
            else:
                cur.append(body[i])
            i += 1
            continue
        cur.append(two)
        i += 2
    parts.append("".join(cur))
    return parts


def _parse_tracklist_template(block: str) -> dict:
    """One `{{tracklist}}` block -> {'label': what disc it is, 'tracks': [...]}."""
    body = block[2:-2] if block.endswith("}}") else block[2:]
    fields = {}
    for p in _split_template_params(body)[1:]:      # [0] is the template name
        if "=" in p:
            k, v = p.split("=", 1)
            fields[k.strip().lower()] = v.strip()
    tracks = []
    # Collected by number rather than counted up from 1: stopping at the first
    # gap would silently truncate a setlist, which is the one failure mode that
    # looks completely fine in a preview.
    nums = sorted(int(m.group(1)) for k in fields
                  for m in [re.fullmatch(r"title(\d+)", k)] if m)
    for n in nums:
        t = re.sub(r"(?is)<sup>.*?</sup>", " ", fields[f"title{n}"])
        t = _dewiki(t).strip().strip('"“”').strip()
        if t:
            tracks.append(t)
    label = " ".join(x for x in (_dewiki(fields.get("headline", "")),
                                 _dewiki(fields.get("extra_column", ""))) if x)
    return {"label": label.strip(), "tracks": tracks}


def _tracklist_from_templates(w: str, interactive: bool = True) -> list[str]:
    """The setlist when the page writes it as a template instead of a list.

    A single with a bonus DVD carries TWO of these - the CD's tracks and the
    DVD's - and only one of them is the disc in the tray.  Picking by size or by
    position would be a guess, and guessing which release a source describes is
    the exact mistake this tool exists to refuse.

    But the blocks LABEL THEMSELVES, and the labels say which disc they are:
    `CD（全タイプ共通）` against
    `DVD（プレミアム盤）「First One Man Show 2014」at 神戸ワールド記念ホール`.
    Reading that is no more a guess than reading the release date off the same
    page - it is the source stating the answer, not size and not position. So
    the label decides when it separates them cleanly, and the human is asked
    only when it does not (a box set of two DVDs, or unlabelled blocks), which
    is the case where a person genuinely knows something the page does not.
    """
    blocks = [b for b in (_parse_tracklist_template(x)
                          for x in _template_spans(w, _TRACKLIST_TEMPLATE))
              if b["tracks"]]
    if not blocks:
        return []
    if len(blocks) == 1:
        print(f"  tracklist template: {blocks[0]['label'] or '(unlabelled)'}"
              f" - {len(blocks[0]['tracks'])} tracks")
        return blocks[0]["tracks"]

    video = [b for b in blocks
             if _VIDEO_LABEL.search(b["label"] or "")
             and not _AUDIO_ONLY_LABEL.match((b["label"] or "").strip())]
    if len(video) == 1:
        b = video[0]
        print(f"  {len(blocks)} tracklists on the page; taking the one labelled as video:")
        print(f"    {b['label']} - {len(b['tracks'])} tracks")
        return b["tracks"]

    print(f"\n  this page carries {len(blocks)} tracklists and their labels do not")
    print("  separate them - pick the disc you ripped:")
    for i, b in enumerate(blocks, 1):
        print(f"    [{i}] {len(b['tracks']):>3} trk  {b['label'] or '(unlabelled)'}")
        print(f"           first: {b['tracks'][0]}")
        print(f"           last : {b['tracks'][-1]}")
    if not interactive:
        print("  !! batch cannot answer this - left for a human")
        return []
    pick = ask("  which one is on this disc? (Enter for none): ")
    if not pick.isdigit() or not (1 <= int(pick) <= len(blocks)):
        print("  no tracklist taken from the wiki")
        return []
    return blocks[int(pick) - 1]["tracks"]


_MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october "
    "november december".split(), 1)}


def wiki_date(text: str) -> str:
    """'October 09, 2013' -> '2013-10-09'. Returns '' if it is not that shape."""
    m = re.match(r"\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\s*$", text or "")
    if m and m.group(1).lower() in _MONTHS:
        return "%s-%02d-%02d" % (m.group(3), _MONTHS[m.group(1).lower()], int(m.group(2)))
    # Japanese-release wikis write `2002.3.30`, unpadded, and a dotted date is
    # never ambiguous the way a slashed one is: the four-digit year leads.
    m = re.match(r"\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*$", text or "")
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    # ja.wikipedia writes the date in kanji, and usually WIKILINKS it in two
    # pieces - `| Released = [[2015年]][[5月13日]]` - which _dewiki hands over as
    # the single run `2015年5月13日`.  Deliberately not anchored to the end: a
    # release line often carries a trailing `発売` or a footnote marker.
    #
    # Returning '' here is the DANGEROUS outcome, not a visible one.  main()
    # falls back to `<folder year>-01-01`, so the Starburst DVD would have been
    # dated 2015-01-01 instead of 2015-05-13 - four months out, no warning, and
    # entirely plausible in the preview because the YEAR is right.
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text or "")
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return ""


_FORMAT_QUAL = re.compile(r"\s*\((?:DVD|Blu-?ray|BD|VHS|LD|CD)\)\s*$", re.I)
_DISC_QUAL = re.compile(r"\((?:DVD|Blu-?ray|BD)\)", re.I)


def _infobox_field(w: str, keys: tuple[str, ...]) -> list[str]:
    """Every `<br>`-separated value of the first infobox key that matches.

    Key names are per-wiki, not per-template: oneokrock writes `Catalog Number`
    and `Date`, visualkei writes `catalog` and `released`. Callers pass every
    spelling they know of and matching is case-insensitive, because looking for
    one exact spelling silently returns nothing on a wiki that chose another -
    which reads identically to a page that simply has no catalogue number.
    """
    for key in keys:
        m = re.search(r"^\|\s*%s\s*=\s*(.+?)\s*$" % re.escape(key), w, re.M | re.I)
        if m:
            parts = re.split(r"<br\s*/?>", m.group(1))
            return [p for p in (_dewiki(p).strip() for p in parts) if p]
    return []


def wiki_infobox(sub: str, page: str, known_catalog: str = "") -> dict:
    """Date/catalogue straight off the infobox. Used ONLY when MusicBrainz has
    no record of the release at all - these fields are the ones fandom got
    demonstrably wrong (AZBS-1009), so anything sourced here is labelled.

    One infobox routinely describes SEVERAL pressings at once, positionally:

        released = 1999.10.28 (VHS)<br>2002.3.30 (DVD)
        catalog  = COVA-6191 (VHS)<br>COBA-4162 (DVD)

    Taking the text before the first `<br>` would date the DVD in the tray to
    the VHS release five years earlier - a wrong answer that looks entirely
    reasonable in the preview. The catalogue number captured at rip time IS the
    identity of that disc, so it selects the row; failing that prefer a disc
    format over tape, and only then fall back to the first.
    """
    d = wiki_api(sub, action="parse", page=page, prop="wikitext")
    w = d.get("parse", {}).get("wikitext", {}).get("*", "")
    dates = _infobox_field(w, ("Date", "released", "release date", "release"))
    catnos = _infobox_field(w, ("Catalog Number", "catalog", "catalogue", "catalog number"))

    idx = None
    if known_catalog:
        idx = next((i for i, c in enumerate(catnos)
                    if known_catalog.lower() in c.lower()), None)
    if idx is None:
        idx = next((i for i, v in enumerate(catnos or dates)
                    if _DISC_QUAL.search(v)), 0)

    def pick(vals: list[str]) -> str:
        if not vals:
            return ""
        # The two fields are parallel lists, but only when both were written
        # out; a page giving one date and two catalogue numbers must not index
        # off the end of the shorter one.
        return _FORMAT_QUAL.sub("", vals[idx] if idx < len(vals) else vals[0]).strip()

    return {"Date": pick(dates), "Catalog Number": pick(catnos)}


def wiki_intro(sub: str, page: str, want_tracks: bool = True,
               interactive: bool = True) -> tuple[str, str, list]:
    """Return (lead prose, infobox image, tracklist). PROSE ONLY is trusted -
    the date and catalogue number always come from MusicBrainz, because a wiki
    infobox is exactly where the wrong AZBS-1009 came from.

    The tracklist IS taken from here in preference to MusicBrainz: MB stores
    these under their original Japanese titles (`夜にしか咲かない満月`), while
    the wiki lists the romanisations this library is written in.  MB stays the
    fallback for a release with no usable wiki page.
    """
    d = wiki_api(sub, action="parse", page=page, prop="wikitext")
    w = d.get("parse", {}).get("wikitext", {}).get("*", "")
    if not w:
        return "", "", []
    img = ""
    # `image` on fandom, `cover` in Wikipedia's {{Infobox album}} - the same
    # per-wiki key-name problem `_infobox_field` already exists for, and it
    # fails the same silent way: no match reads exactly like a page with no
    # cover on it.
    m = re.search(r"^\|\s*(?:image|cover)\s*=\s*(.+?)\s*$", w, re.M | re.I)
    if m:
        img = m.group(1).strip()
        # Some infoboxes hold a bare filename, others a whole embed:
        # `[[File:Lespace front.jpg|250px]]`. wiki_image_url prepends `File:`
        # itself, so hand it the filename either way.
        fm = re.search(r"\[\[\s*(?:File|Image)\s*:\s*([^|\]]+)", img, re.I)
        if fm:
            img = fm.group(1).strip()
    if not img:
        # A stub page often has no infobox at all, just a bare embed opening the
        # article: `[[File:Artworks-….jpg|thumb]]Studio Jam Session is a…`.
        # Taking the first embed is a GUESS about which picture is the cover -
        # it could as easily be a banner - so it is announced as one. The two
        # gates after it are unchanged: install_artwork names the file and asks
        # before composing, and the result still has to be looked at.
        fm = re.search(r"\[\[\s*(?:File|Image)\s*:\s*([^|\]]+)", w, re.I)
        if fm:
            img = fm.group(1).strip()
            print(f"  (no infobox image; guessing at the page's first embed: {img})")

    body = _strip_leading_templates(w)
    # Anchored at line start, NOT `body.split("\n==")`: plenty of pages have no
    # lead prose at all and open on their first heading, which sits at position
    # 0 with no newline in front of it for that split to find - so the whole
    # article came back as "prose" and Plex got the setlist twice, once as a
    # paragraph of composer credits.
    prose = _dewiki(re.split(r"(?m)^==", body, maxsplit=1)[0])

    # Tracklist. Deliberately loose, because even one wiki is not consistent
    # with itself: the 2013 release uses '===Tracklist===' with '#' items, the
    # 2011 one uses '==Set list==' with '*' items. So accept either heading
    # wording and either bullet, and end the section at the first heading no
    # deeper than the one that opened it (the next disc), or at a Bonus
    # section, which is not part of the setlist. A None marks an Encore.
    tracks: list = []
    sec_level = None
    for line in w.splitlines():
        h = line.strip()
        m = re.match(r"^(=+)\s*(.*?)\s*=+$", h)
        if m:
            lvl, name = len(m.group(1)), m.group(2)
            if sec_level is None:
                if re.search(r"(track|set)\s*list", name, re.I):
                    sec_level = lvl
                continue
            if lvl <= sec_level or re.search(r"bonus", name, re.I):
                break
            if re.search(r"encore", name, re.I):
                tracks.append(None)
            continue
        if sec_level is None:
            continue
        if h.startswith(("#", "*")):
            # A per-track `<sup>composed by Mana, lyrics by Gackt</sup>` credit
            # is not part of the song title, and _dewiki strips only the TAGS -
            # it would keep the sentence, giving Plex a setlist reading
            # "S-CONSCIOUS composed by Mana, lyrics by Gackt".
            h = re.sub(r"(?is)<sup>.*?</sup>", " ", h)
            t = _dewiki(h.lstrip("#*").strip())
            # Wikipedia quotes every song title, fandom quotes none. Left in,
            # this library's sixth setlist would be the only one rendering as
            # `1. "Blue Blood"`. Double quotes only - an apostrophe can be part
            # of a real title.
            t = t.strip('"“”').strip()
            if t:
                tracks.append(t)
    # Some pages render the encore track as its own deep heading rather than a
    # bullet, which leaves an Encore marker with nothing under it. A bare
    # "Encore" and then nothing reads as a truncated setlist, so drop it.
    while tracks and tracks[-1] is None:
        tracks.pop()
    # Nothing bulleted under a heading this recognises. That is not the same as
    # "no setlist": ja.wikipedia files it in a `{{tracklist}}` TEMPLATE under a
    # `== 収録曲 ==` heading, so both halves of the scan above miss - the heading
    # is not English and the entries are `| title1 =` parameters, not bullets.
    # Off the visual-kei fan wikis this is the usual shape, and the failure is
    # silent: zero tracks reads exactly like a release with no setlist on file.
    if want_tracks and not tracks:
        tracks = _tracklist_from_templates(w, interactive)
    return prose, img, tracks


def wiki_image_url(sub: str, filename: str) -> str:
    """`pageimages` can come back empty on a page that plainly has a cover, so
    go straight at the File: title with imageinfo."""
    d = wiki_api(
        sub, action="query", titles=f"File:{filename}", prop="imageinfo", iiprop="url"
    )
    for _pid, p in (d.get("query", {}).get("pages") or {}).items():
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("url"):
            return ii["url"]
    return ""


# ------------------------------------------------------------- artwork ---
# Scans get uploaded on their side and there is no way to tell from the pixels -
# no EXIF orientation tag survives fandom's re-encode, and "which way up is this
# concert photo" is a judgement, not a measurement. So the human who can see it
# says which way, exactly like picking the release.
ROTATE_VF = {"cw": "transpose=1,", "ccw": "transpose=2,", "180": "transpose=1,transpose=1,"}


def compose_poster(src_bytes: bytes, folder: Path, rotate: str = "") -> bool:
    """DVD covers are landscape; Plex posters are 2:3 and it CENTER-CROPS, so
    pre-compose and leave it nothing to crop. Note fandom serves WebP even from
    a .jpg URL, which is why the source goes to ffmpeg as raw bytes."""
    raw = folder / ".cover.raw"
    raw.write_bytes(src_bytes)
    rot = ROTATE_VF.get(rotate, "")
    ok = True
    for out, vf in (
        (
            "poster.jpg",
            # The foreground is BOUNDED by the frame, not pinned to its width.
            # `scale=1000:-2` assumed a landscape cover; a portrait one taller
            # than 2:3 came out 1000x1588 and the centred overlay quietly cut
            # the top and bottom off - including the title. `decrease` is
            # identical for a landscape cover (still width-bound), so this only
            # ever removes a crop.
            f"[0:v]{rot}scale=1000:1500:force_original_aspect_ratio=increase,crop=1000:1500,"
            "gblur=sigma=40,eq=brightness=-0.28:saturation=0.7[bg];"
            f"[0:v]{rot}scale=1000:1500:force_original_aspect_ratio=decrease:"
            "force_divisible_by=2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2",
        ),
        (
            # No trailing [label] here: a -filter_complex whose output is
            # labelled needs a matching -map, and without one ffmpeg exits
            # non-zero and the poster silently never appears.
            "fanart.jpg",
            f"[0:v]{rot}scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
            "gblur=sigma=30,eq=brightness=-0.32:saturation=0.75",
        ),
    ):
        dest = folder / out
        # ffmpeg picks the demuxer off the input PATH, and a `{` anywhere in it
        # defeats that: it falls back to rawvideo and dies on "Invalid pixel
        # format" before the filtergraph is even bound. Plex's own
        # `{edition-...}` folder tag puts braces in the path of every item that
        # carries one, so the first such disc composed no poster at all while
        # every other step reported success. Both files sit directly in
        # `folder`, so running from there and passing bare names sidesteps it
        # and leaves the filters byte-identical. Only the INPUT is affected -
        # a braced output path is fine.
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", raw.name,
               "-filter_complex", vf, "-frames:v", "1", "-q:v", "2", dest.name]
        if (subprocess.run(cmd, capture_output=True, cwd=folder).returncode != 0
                or not dest.exists()):
            ok = False
            continue
        dest.chmod(0o644)
    raw.unlink(missing_ok=True)
    return ok


# ------------------------------------------------------------ catalogue ---
def _title_key(s: str) -> str:
    """Fold a title for comparison: case, punctuation and spacing only.

    The run log and Plex hold the SAME title typed at different moments, and
    one comma apart is enough for `==` to miss: the Starburst disc is filed as
    `Fear, and Loathing in Las Vegas - Starburst (2015)` and its run log says
    `Fear and Loathing in Las Vegas - Starburst (2015)`, so the catalogue
    number - the disc's whole identity - silently came back empty.

    Exact-after-folding, never a similarity ratio. `plex_requests._dup_key`
    makes the same call for the same reason: any ratio loose enough to catch a
    real near-miss also collapses `Deadpool` into `Deadpool 2`, and attaching
    the WRONG disc's catalogue number is far worse than attaching none.
    """
    s = (s or "").replace("&", "and").replace("'", "").replace("’", "")
    # Keep alphanumerics and kana/kanji; drop spacing and punctuation entirely.
    return re.sub(r"[^0-9a-z぀-ヿ一-鿿]+", "", s.lower())


def _rip_logs() -> list[dict]:
    logs = Path(os.environ.get("RIP_LOG_DIR")
                or "/mnt/media/STAGING/.dvdrip-logs")
    if not logs.is_dir():
        return []
    out = []
    for j in sorted(logs.glob("*.json")):
        try:
            out.append(json.loads(j.read_text(encoding="utf-8-sig")))
        except Exception:
            continue
    return out


def catalog_from_rip_logs(title: str, file_path: str | None = None,
                          *, with_reason: bool = False):
    """Recover the catalogue number someone read off the case at rip time.

    **The byte size of the file is the key, and the title is only the fallback.**
    The run log's `headline` is a title a human typed into the ripper, and the
    renamer is free to rewrite it before it reaches Plex, so matching on it has
    missed three times for three unrelated reasons: a comma inside a band's name
    (`Fear, and Loathing`), a bonus-disc headline naming a DIFFERENT disc of the
    same set (JAM Project), and a doubled artist prefix (`One Ok Rock - ONE OK
    ROCK - ...`). `_title_key` folds punctuation and case, which fixes the first
    shape and cannot reach the other two - the words themselves differ.

    A byte count is immune to all three: renaming and moving a file does not
    change it, the ripper verifies it byte-for-byte at copy time, and a match is
    exact equality on an integer rather than any similarity. Two multi-GB
    encodes colliding on an exact size is not a practical concern, and the one
    realistic collision - the same disc ripped twice - carries the same
    catalogue number anyway.

    A sidecar travelling beside the media was the other candidate and does not
    work here: the renamer files only video and subtitle roles, and
    `retire_item` sweeps everything else into `_done/`, so the sidecar would
    never arrive in the library at all without teaching a second, autonomously
    scheduled repo to carry it.

    Returns the catalogue number, or ``(catno, how)`` when `with_reason`.
    """
    logs = _rip_logs()
    size = None
    if file_path:
        try:
            size = os.path.getsize(file_path)
        except OSError:
            size = None

    if size:
        for d in logs:
            if not d.get("catalog"):
                continue
            for f in (d.get("files") or []):
                try:
                    if int(f.get("bytes") or 0) == size:
                        catno = d["catalog"].strip()
                        return (catno, "file size") if with_reason else catno
                except (TypeError, ValueError):
                    continue

    want, best = _title_key(title), ""
    for d in logs:
        if d.get("catalog") and _title_key(d.get("headline") or "") == want:
            best = d["catalog"].strip()
    return (best, "title" if best else "") if with_reason else best


# ----------------------------------------------------------------- flow ---
def parse_title(title: str) -> tuple[str, str, str]:
    artist, _, rest = title.partition(" - ")
    m = re.search(r"\((\d{4})\)\s*$", rest)
    year = m.group(1) if m else ""
    name = re.sub(r"\s*\(\d{4}\)\s*$", "", rest).strip()
    return artist.strip(), name, year


def pick_wiki_page(sub: str, terms: str, purpose: str) -> str:
    titles = wiki_find(sub, terms)
    host = urllib.parse.urlsplit(wiki_endpoint(sub)[0]).netloc
    if not titles:
        print(f"\n{host}: nothing found for {terms!r}")
        return ""
    print(f"\n{host} pages:")
    for i, t in enumerate(titles, 1):
        print(f"  [{i}] {t}")
    p = ask(f"pick a page for {purpose} (Enter to skip): ")
    return titles[int(p) - 1] if p.isdigit() and 1 <= int(p) <= len(titles) else ""


def install_artwork(token: str, item: dict, sub: str, img_name: str,
                    rotate: str, cover_file: str = "") -> bool:
    """Compose poster+fanart into the item's folder and make Plex re-read them.

    `cover_file` is the human handing over a better picture than the wiki has,
    and it is needed more often than not: the X Japan DVD's only wiki cover was
    a 250x250 fair-use crop, while the label's own site publishes the jacket at
    500x580.  Same judgement call as `--rotate` - which of two pictures is the
    cover is something you settle by looking, not by scoring.
    """
    if not item["file"]:
        print("  !! Plex reports no file for this item - nowhere to write artwork")
        return False
    folder = Path(item["file"]).parent
    if not folder.is_dir():
        print(f"  !! {folder} is not a directory")
        return False

    if cover_file:
        src = Path(cover_file).expanduser()
        if not src.is_file():
            print(f"  !! no such cover file: {src}")
            return False
        data, label = src.read_bytes(), str(src)
    else:
        if not img_name:
            print("  no cover image on that page - artwork left alone")
            return False
        url = wiki_image_url(sub, img_name)
        if not url:
            print(f"  !! could not resolve {img_name}")
            return False
        data, label = _get(url, ua=BROWSER_UA), img_name

    turned = f" rotated {rotate}" if rotate else ""
    if ask(f"compose poster from {label}{turned}? [y/N] ").lower() != "y":
        return False
    if not compose_poster(data, folder, rotate):
        print("  !! ffmpeg could not build the poster")
        return False
    print(f"  wrote poster.jpg + fanart.jpg to {folder}")
    if not rotate:
        # No EXIF orientation survives fandom's re-encode, so a sideways scan
        # composes into a sideways poster without anything going wrong. Looking
        # at it is the only check there is.
        print("  -> look at it. If it is sideways, re-run with "
              "--artwork-only --rotate ccw")
    with urllib.request.urlopen(urllib.request.Request(
            f"{PLEX}/library/metadata/{item['rk']}/refresh?X-Plex-Token={token}",
            method="PUT"), timeout=30):
        pass
    time.sleep(10)
    return True


# ------------------------------------------------------------ the disc ---
def disc_shape(path: str | None) -> dict:
    """Runtime and chapter count of the file actually sitting in the library.

    The disc is the one source that cannot be wrong about itself, and it is the
    only one nobody was consulting.  It settles questions the databases argue
    about: a 2-track, 6-minute CD tracklist cannot describe a 90-minute video,
    whatever the page says.
    """
    if not path or not Path(path).is_file():
        return {}
    def probe(args: list[str]) -> str:
        r = subprocess.run(["ffprobe", "-v", "error", *args, str(path)],
                           capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""
    out: dict = {}
    dur = probe(["-show_entries", "format=duration", "-of", "csv=p=0"]).strip()
    try:
        out["minutes"] = float(dur) / 60.0
    except ValueError:
        pass
    # `-show_chapters -of csv` prints nothing greppable for "chapter"; count the
    # JSON array instead. (Counting csv lines reported 0 on a file with 22.)
    try:
        out["chapters"] = len(json.loads(
            probe(["-print_format", "json", "-show_chapters"]) or "{}").get("chapters", []))
    except Exception:
        pass
    return out


def tracklist_sanity(n_tracks: int, shape: dict) -> str:
    """'' when the setlist plausibly describes this file, else why not.

    A warning, never a refusal - chaptering is a mastering choice and plenty of
    discs chapter every five minutes instead of per song. But a setlist whose
    per-track time is absurd means the wrong tracklist was taken, and in a batch
    run nobody is watching the preview.
    """
    mins = shape.get("minutes")
    if not n_tracks or not mins:
        return ""
    per = mins / n_tracks
    if per < 1.0:
        return (f"{n_tracks} tracks over {mins:.0f} min is {per*60:.0f}s each - "
                f"too many for this disc")
    if per > 12.0:
        return (f"{n_tracks} tracks over {mins:.0f} min is {per:.0f} min each - "
                f"too few, this looks like another disc's tracklist")
    ch = shape.get("chapters") or 0
    if ch and abs(ch - n_tracks) > max(6, n_tracks * 0.5):
        return f"{n_tracks} tracks against {ch} chapters on the disc"
    return ""


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit("aborted")


_PROSE_DATE = re.compile(r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})\b")


def prose_date_conflicts(prose: str, release_date: str) -> list[str]:
    """Dates in the wiki's PROSE that claim this release's year but not its day.

    Prose is the one thing here copied verbatim, and prose states facts. English
    Wikipedia's lead for the X Japan DVD says it came out on September 9 2001,
    where MusicBrainz, Discogs, CDJapan and ja.wikipedia all say September 5 -
    so the summary shipped a date contradicting the very field printed two lines
    above it, and nothing said a word.

    Only a SAME-YEAR mismatch counts. A concert film's prose is full of dates
    that are not the release date - the show itself, the original VHS pressing -
    and those are correct and belong there, so flagging them would turn this
    into noise and get it ignored, which is worse than not having it.
    """
    if not re.match(r"\d{4}-\d{2}-\d{2}$", release_date or ""):
        return []
    year, out = release_date[:4], []
    for m in _PROSE_DATE.finditer(prose or ""):
        month = _MONTHS.get(m.group(1).lower())
        if not month or m.group(3) != year:
            continue
        iso = "%s-%02d-%02d" % (m.group(3), month, int(m.group(2)))
        if iso != release_date:
            out.append(m.group(0))
    return out


def build_summary(prose: str, tracks: list[str], rel: dict) -> str:
    bits = []
    if prose:
        bits.append(prose)
    facts = []
    if rel["date"]:
        facts.append(f"Released {rel['date']}")
    if rel["catalog"]:
        facts.append(rel["catalog"])
    if rel["formats"]:
        facts.append("/".join(rel["formats"]))
    if facts and not prose:
        bits.append(". ".join(facts) + ".")
    elif facts:
        bits.append(f"({', '.join(facts)})")
    if tracks:
        n = sum(1 for t in tracks if t is not None)
        width = len(str(n))
        lines, i = ["Setlist"], 0
        for t in tracks:
            if t is None:              # encore boundary
                lines.append("")
                lines.append("Encore")
                continue
            i += 1
            lines.append(f"{i:>{width}}. {t}")
        bits.append("\n".join(lines))
    return "\n\n".join(bits)


# -------------------------------------------------------------- batch ---
# Dozens of discs are coming, so the question stops being "can a human check
# every field" and becomes "which checks does a human actually contribute to".
# These are the ones where the answer is nobody:
#
#   - the catalogue number came off the physical case at rip time
#   - it resolves to EXACTLY ONE MusicBrainz release, by exact key, not search
#   - two or more catalogue-keyed sources independently agree on the date
#   - a wiki page's title matches this release EXACTLY once folded
#   - the setlist plausibly describes the file that is actually on disk
#
# Miss any and it goes on the pile a person looks at, with the research already
# done. The poster is never in this list: nothing can judge an image, so every
# composed poster still gets looked at afterwards.
BATCH_WIKIS = ("wikipedia", "ja.wikipedia")


def _page_matches(page: str, name: str) -> bool:
    """A wiki page title that IS this release, not one that resembles it.

    Exact after folding, with a trailing disambiguator removed - `Starburst (曲)`
    is `Starburst`. Never a ratio: the menu that offered `Blue Blood Tour
    Bakuhatsu Sunzen Gig` also offered `Blue Blood (X Japan album)`, and any
    threshold loose enough to forgive a real title is loose enough to take that.
    """
    return _title_key(re.sub(r"\s*\([^()]*\)\s*$", "", page)) == _title_key(name)


def _batch_one(token: str, section: str, item: dict, wikis: tuple[str, ...],
               out: Path, dry: bool = False) -> dict:
    import plex_concert_research as R      # deferred: R imports this module

    artist, name, folder_year = parse_title(item["title"])
    res: dict = {"rk": item["rk"], "title": item["title"], "blockers": [],
                 "applied": False, "cover": "", "warnings": []}

    catno = catalog_from_rip_logs(item["title"], item.get("file"))
    if not catno:
        res["blockers"].append("no catalogue number in the rip logs")
    res["catalog"] = catno

    cands = mb_by_catalog(catno) if catno else []
    if len(cands) != 1:
        res["blockers"].append(f"MusicBrainz returned {len(cands)} releases for that "
                               f"catalogue number, need exactly 1")
    rel = cands[0] if len(cands) == 1 else None

    # A multi-disc video set is one catalogue number over several discs, and a
    # rip is ONE of them - so every source's tracklist describes more than what
    # is on the shelf, and `tracklist_sanity` cannot see it: 31 tracks over the
    # 93-minute disc 1 of Deco Vs Deco reads as a perfectly normal 3 min/track.
    # Which disc got ripped is a question only a person holding the case can
    # answer, so it never auto-applies.
    if rel and rel.get("video_discs", 1) > 1:
        res["blockers"].append(
            f"the release is a {rel['video_discs']}-disc video set - the rip is one "
            f"of them, so a whole-set tracklist would be wrong")

    facts = R.corroborate(catno, cands, rel["title"] if rel else "")
    res["facts"] = facts
    if not facts["agreed"]:
        res["blockers"].append(
            "sources disagree on the date" if facts["conflict"]
            else "no two sources agree on a date")
    elif rel and facts["agreed"] != rel["date"]:
        res["blockers"].append(f"MusicBrainz says {rel['date']}, the agreed date is "
                               f"{facts['agreed']}")

    prose, tracks, page_used = "", [], ""
    for wiki in wikis:
        try:
            hits = wiki_find(wiki, f"{artist} {name}")
        except Exception:
            continue
        page = next((h for h in hits if _page_matches(h, name)), "")
        if not page:
            continue
        try:
            prose, _img, tracks = wiki_intro(wiki, page, interactive=False)
        except Exception:
            continue
        page_used = f"{wiki}:{page}"
        break
    res["page"] = page_used
    if not page_used:
        res["blockers"].append("no wiki page whose title matches this release exactly")

    if rel and not tracks:
        try:
            tracks = mb_tracklist(rel["id"])
        except Exception:
            tracks = []
    shape = disc_shape(item.get("file"))
    res["shape"] = shape
    n = sum(1 for t in tracks if t is not None)
    if not n:
        res["blockers"].append("no setlist from either source")
    else:
        bad = tracklist_sanity(n, shape)
        if bad:
            res["blockers"].append(bad)
    res["tracks"] = n

    if not rel:
        return res
    summary = build_summary(prose, tracks, rel)
    clash = prose_date_conflicts(summary, rel["date"])
    if clash:
        res["blockers"].append(f"the prose says {', '.join(clash)}, the release is "
                               f"dated {rel['date']}")
    res["summary"] = summary

    item_dir = out / str(item["rk"])
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "summary.txt").write_text(summary, encoding="utf-8")
    (item_dir / "facts.json").write_text(json.dumps(
        {k: v for k, v in res.items() if k != "summary"}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    if res["blockers"]:
        return res

    yr = rel["date"][:4]
    if folder_year and yr != folder_year:
        res["warnings"].append(f"folder says ({folder_year}), release is {yr}")
    res["year"], res["date"] = yr, rel["date"]
    if dry:
        res["applied"] = True          # "would apply" - nothing was written
        return res
    apply_metadata(token, section, item["rk"], summary, yr, rel["date"])
    after = get_item(token, item["rk"])
    res["applied"] = str(after["year"]) == yr and len(after["summary"]) > 0
    if not res["applied"]:
        res["blockers"].append("Plex did not take the write")
    res["year"], res["date"] = yr, rel["date"]

    # Artwork is a STARTING POINT, never a verdict: no rule tells a jacket from
    # a photo of a shrink-wrapped case. Composing the best-ranked candidate
    # means most discs need no artwork pass at all, and a wrong one costs a
    # single `--artwork-only --cover-file` re-run once somebody looks.
    wiki, _, page = page_used.partition(":")
    cands = R.collect_covers(item_dir / "covers", artist, catno, rel["id"],
                             "", wiki, page)
    pick = R.best_cover(cands)
    if not pick:
        res["warnings"].append("no cover candidate over 300px - poster left alone")
        return res
    folder = Path(item["file"]).parent if item.get("file") else None
    if folder and folder.is_dir() and compose_poster(
            Path(pick["path"]).read_bytes(), folder):
        res["cover"] = f"{pick['source']} {pick['w']}x{pick['h']}"
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"{PLEX}/library/metadata/{item['rk']}/refresh"
                    f"?X-Plex-Token={token}", method="PUT"), timeout=30):
                pass
        except Exception:                                 # noqa: BLE001
            res["warnings"].append("poster written but Plex refresh failed")
    else:
        res["warnings"].append("ffmpeg could not build the poster")
    return res


def run_batch(token: str, section: str, wikis: tuple[str, ...], out: Path,
              dry: bool = False) -> int:
    items = [i for i in list_items(token, section) if not i["summary"] or not i["year"]]
    print(f"{len(items)} item(s) missing metadata"
          f"{'  [DRY RUN - nothing will be written]' if dry else ''}\n")
    if not items:
        return 0
    done, todo = [], []
    for it in items:
        print(f"--- {it['rk']}  {it['title']}")
        full = get_item(token, it["rk"])
        it["file"] = full.get("file")
        try:
            r = _batch_one(token, section, it, wikis, out, dry)
        except Exception as e:                            # noqa: BLE001
            r = {"rk": it["rk"], "title": it["title"], "applied": False,
                 "blockers": [f"{type(e).__name__}: {e}"], "warnings": []}
        (done if r.get("applied") else todo).append(r)
        verb = ("WOULD APPLY " if dry else "APPLIED ") + r.get("date", "")
        print(f"    {verb if r.get('applied') else 'NEEDS YOU'}")
        for b in r["blockers"]:
            print(f"      - {b}")

    head = "WOULD APPLY" if dry else "APPLIED"
    print(f"\n{'=' * 72}\n{head} {len(done)}   NEEDS YOU {len(todo)}\n{'=' * 72}")
    for r in done:
        print(f"  {r['rk']:<6} {r.get('date', ''):<11} {r.get('tracks', 0):>2} trk  {r['title'][:44]}")
        for w in r["warnings"]:
            print(f"         !! {w}")
    if done and not dry:
        print("\n  LOOK AT EVERY POSTER these produced - nothing here judged an image.")
    for r in todo:
        print(f"  {r['rk']:<6} {r['title'][:52]}")
        for b in r["blockers"]:
            print(f"         - {b}")
    if todo:
        print(f"\n  research for these is already in {out}/<rk>/ - correct and apply with")
        print("  plex_concert_meta.py --item <rk> --wiki <w> --summary-file <that file>")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--item", help="ratingKey to work on")
    ap.add_argument("--catalog", help="catalogue number off the case - the exact key")
    ap.add_argument("--date", help="release date as YYYY-MM-DD, for when neither "
                                   "MusicBrainz nor the infobox carries one - it "
                                   "WINS over both, and without it the fallback is "
                                   "a guess off the folder year")
    ap.add_argument("--wiki", help="where the prose comes from: a fandom "
                                   "subdomain (oneokrock, visualkei) or "
                                   "wikipedia / ja.wikipedia")
    ap.add_argument("--rotate", choices=("cw", "ccw", "180"),
                    help="turn the cover before composing - scans get uploaded "
                         "sideways and nothing in the file says so")
    ap.add_argument("--artwork-only", action="store_true",
                    help="redo poster/fanart from the wiki page and leave the "
                         "metadata alone (for fixing a rotation)")
    ap.add_argument("--cover-file",
                    help="use this local image as the cover instead of the "
                         "wiki's - the label's own jacket art usually beats it")
    ap.add_argument("--summary-file",
                    help="path to hold the summary text. Missing: the composed "
                         "summary is written there and nothing is applied, so "
                         "you can correct it and re-run. Present: its contents "
                         "are used verbatim")
    ap.add_argument("--batch", action="store_true",
                    help="research every item missing metadata, apply the ones "
                         "nothing is uncertain about, and leave the rest with "
                         "their research already done")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --batch: do all the research and say what it "
                         "WOULD apply, without writing anything")
    ap.add_argument("--batch-out", default="/tmp/concert-batch",
                    help="where --batch leaves per-item research")
    ap.add_argument("--section-name", default="Concerts")
    args = ap.parse_args()

    # A date is a fact about ONE release, so it cannot ride along with a run
    # over every item; and a half-typed one is worse than none, because it
    # would be written with the same locks as a checked one. Refuse both.
    if args.date:
        if args.batch:
            sys.exit("--date describes one release - it cannot be used with --batch")
        if not re.match(r"\d{4}-\d{2}-\d{2}$", args.date):
            sys.exit(f"--date must be YYYY-MM-DD, got {args.date!r}")

    token = plex_token()
    section = find_section(token, args.section_name)

    if args.batch:
        wikis = (args.wiki,) if args.wiki else BATCH_WIKIS
        return run_batch(token, section, wikis, Path(args.batch_out).expanduser(),
                         args.dry_run)

    if not args.item:
        print(f"{args.section_name} (section {section}) - pass --item <rk> to work on one\n")
        print(f"  {'rk':<6} {'year':<6} {'summary':<8} title")
        for it in list_items(token, section):
            print(f"  {it['rk']:<6} {str(it['year'] or '-'):<6} "
                  f"{(str(len(it['summary'])) + 'ch') if it['summary'] else '-':<8} {it['title']}")
        return 0

    item = get_item(token, args.item)
    artist, name, year = parse_title(item["title"])
    print(f"\nitem    : {item['title']}")
    print(f"parsed  : artist={artist!r} title={name!r} year={year or '-'}")
    print(f"current : year={item['year']} oaa={item['oaa']} summary={len(item['summary'])}ch")

    catalog, how = args.catalog, "given"
    if not catalog:
        catalog, how = catalog_from_rip_logs(item["title"], item.get("file"),
                                             with_reason=True)
    if catalog and not args.catalog:
        print(f"catalog : {catalog}  (recovered from the ripper's run log "
              f"by {how})")

    # Artwork is the one step whose result you can only judge by looking at it,
    # so it has to be redoable on its own - re-running the whole flow to turn a
    # picture means re-confirming metadata that was already right.
    if args.artwork_only:
        if args.cover_file:
            return 0 if install_artwork(token, item, "", "", args.rotate or "",
                                        args.cover_file) else 1
        if not args.wiki:
            print("!! --artwork-only needs --wiki <subdomain> or --cover-file <path>")
            return 1
        page = pick_wiki_page(args.wiki, f"{artist} {name}", "the COVER IMAGE")
        if not page:
            print("nothing picked, artwork left alone")
            return 1
        # want_tracks=False: this path throws the setlist away, and parsing it
        # can now ask the human which disc it belongs to - a pointless question
        # when all that is being redone is a rotated picture.
        _, img_name, _ = wiki_intro(args.wiki, page, want_tracks=False)
        return 0 if install_artwork(token, item, args.wiki, img_name,
                                    args.rotate or "") else 1

    # ---- candidates -------------------------------------------------------
    cands: list[dict] = []
    if catalog:
        cands = mb_by_catalog(catalog)
        print(f"\nMusicBrainz by catalogue number {catalog}: {len(cands)} hit(s)")
    if not cands:
        got = mb_artist(artist)
        if not got:
            print(f"!! MusicBrainz has no artist called {artist!r}")
            return 1
        arid, aname = got
        print(f"\nartist  : {aname}  ({arid})")
        cands = mb_video_releases(arid)
        print(f"video releases on file: {len(cands)}"
              f"{'  (filtered to year ' + year + ')' if year else ''}")
        if year:
            near = [c for c in cands if c["date"][:4] == year]
            if near:
                cands = near

    if not cands:
        # The [0] wiki-only escape used to be reachable only as an entry in a
        # menu that needed at least one candidate to be printed at all - so an
        # artist with NO video releases on MusicBrainz aborted here, and that is
        # precisely the release that needs the escape most.  A concert DVD that
        # ships inside a CD single is not filed as a video release by anyone:
        # MB has Fear, and Loathing in Las Vegas as an artist and zero videos,
        # and no record whatsoever of catalogue number VPCC-82656.
        if not args.wiki:
            print("!! nothing to choose from - re-run with --wiki <subdomain> "
                  "to work from the wiki alone, or leave it untouched")
            return 1
        print("\n!! MusicBrainz has no video release on file for this artist.")
        print("   Normal for a DVD packaged inside a CD single - nobody files")
        print("   that as a video release.")
        if ask("work from the wiki alone? [y/N]: ").strip().lower() not in ("y", "yes"):
            print("aborted, nothing written")
            return 1
        pick = "0"
    else:
        print()
        for i, c in enumerate(cands, 1):
            flag = " " if c["standalone"] else "*"
            print(f"  [{i}]{flag} {c['date']:<11} {'/'.join(c['formats']):<14} "
                  f"{c['catalog'] or '-':<12} {c['tracks']:>3} trk  {c['title']}")
        print("   * = ships with a CD, so it is an album with a bonus disc, not a concert release")
        print("  [0]  none of these - MusicBrainz has no record of it, use the wiki alone")
        pick = ask("\npick a release number (Enter to abort): ")
        if not pick.isdigit() or not (0 <= int(pick) <= len(cands)):
            print("aborted, nothing written")
            return 1

    wiki_only = int(pick) == 0
    if wiki_only:
        # MusicBrainz genuinely lacks plenty of these - it has no record at all
        # of the 2014 Yokohama Stadium release. Refusing to touch the item is
        # worse than working from the wiki, but the wiki is the source that got
        # a catalogue number demonstrably wrong, so anything taken from it is
        # LABELLED as such in the preview the human signs off on.
        if not args.wiki:
            print("!! nothing left to work from - re-run with --wiki <subdomain>")
            return 1
        rel = {"id": "", "title": name, "date": "", "formats": [], "catalog": "",
               "tracks": 0, "standalone": True}
        mb_tracks: list = []
        print("\n-> wiki-only: date and catalogue number will come from the infobox")
    else:
        rel = cands[int(pick) - 1]
        mb_tracks = mb_tracklist(rel["id"])
        print(f"\ntracklist from MusicBrainz: {len(mb_tracks)} tracks")

    # ---- the wiki: prose + a ROMANISED tracklist, never facts -------------
    prose, img_name, wiki_tracks = "", "", []
    if args.wiki:
        page = pick_wiki_page(args.wiki, f"{artist} {name}", "the SUMMARY PROSE")
        if page:
            prose, img_name, wiki_tracks = wiki_intro(args.wiki, page)
            print(f"  prose {len(prose)} chars | tracklist {len(wiki_tracks)} "
                  f"| image {img_name or '(none)'}")
            if wiki_only:
                box = wiki_infobox(args.wiki, page, known_catalog=catalog)
                rel["date"] = wiki_date(box.get("Date", ""))
                rel["catalog"] = box.get("Catalog Number", "") or catalog
                print(f"  infobox (UNVERIFIED): date={rel['date'] or '?'} "
                      f"catalog={rel['catalog'] or '?'}")
                # Two sources naming two different numbers is the exact shape
                # of the AZBS-1009 mistake, which sat live in Plex for a day.
                # The one off the case wins - it was read off the disc being
                # ripped - but say so rather than picking quietly.
                if catalog and rel["catalog"].lower() != catalog.lower():
                    print(f"  !! the case says {catalog}, this page says "
                          f"{rel['catalog']} - the date may describe a "
                          f"different pressing")

    # The wiki wins on the tracklist because it is romanised; MB wins on facts.
    tracks = wiki_tracks or mb_tracks
    src = "wiki (romanised)" if wiki_tracks else "MusicBrainz (original titles)"
    print(f"using tracklist from: {src}")
    # Two independent sources counted the same discs, so a disagreement means
    # one of them was parsed wrong. Say so - a short setlist looks perfectly
    # plausible in the preview, which is exactly how it would get waved through.
    n_wiki = sum(1 for t in wiki_tracks if t is not None)
    if wiki_tracks and mb_tracks and abs(n_wiki - len(mb_tracks)) > 2:
        print(f"  !! wiki says {n_wiki} tracks, MusicBrainz says {len(mb_tracks)} - "
              f"check the preview before accepting")

    summary = build_summary(prose, tracks, rel)

    # A wiki's PROSE carries facts too, and they are worth no more than the
    # infobox facts this tool already refuses to trust.  The English Wikipedia
    # article for the X Japan DVD dates it to September 9 2001 in the lead,
    # while MusicBrainz, the label's own shop listing and the article's OWN
    # cited source all say September 5 - so accepting the text as written ships
    # a date the tool has already contradicted two fields higher up.  Accept or
    # abort is not enough; there has to be a way to fix the words.
    if args.summary_file:
        sf = Path(args.summary_file).expanduser()
        if sf.exists():
            summary = sf.read_text(encoding="utf-8").strip()
            print(f"\nsummary read from {sf}  ({len(summary)} chars)")
        else:
            sf.write_text(summary, encoding="utf-8")
            print(f"\nwrote the composed summary to {sf}")
            print("NOTHING APPLIED - correct the text, then re-run the same "
                  "command to use it")
            return 0

    # `--date` exists because neither source is guaranteed to carry one, and
    # the fallback below is a GUESS that reads like a fact.  MusicBrainz can
    # have no record of the release at all, and a fandom EVENT page - the only
    # page some series have - carries the SHOW date with trailing qualifiers,
    # which `wiki_date` refuses correctly and indistinguishably from `nothing
    # on file`.  ANSX-11091 came out 2015-03-11 and was filed 2015-01-01 that
    # way: ten weeks wrong, no warning, and entirely plausible in the preview
    # because the YEAR is right.  A date given here is the human's and WINS
    # over both sources - but a disagreement is printed rather than settled
    # quietly, the same rule the catalogue-number clash follows.
    if args.date and rel["date"] and args.date != rel["date"]:
        print(f"\n!! --date says {args.date}, this release is dated "
              f"{rel['date']} - using {args.date}")
    date = args.date or rel["date"] or (f"{year}-01-01" if year else "")
    yr = (args.date or rel["date"] or year or "")[:4]
    if not yr:
        print("!! no year from either source - aborting rather than inventing one")
        return 1
    if not args.date and not rel["date"]:
        print(f"\n!! neither source has a release date - {date} is a GUESS off "
              f"the folder year. Re-run with --date YYYY-MM-DD to state the "
              f"real one.")

    print("\n" + "=" * 70)
    print(f"year {yr}   originallyAvailableAt {date}")
    # A concert filmed one year and released the next is normal, and the folder
    # is usually named for the SHOW while the databases record the RELEASE.
    # Neither is wrong, but silently disagreeing with the title on screen is,
    # so make the human decide rather than discovering it in Plex later.
    if year and yr != year:
        print(f"  !! the title says ({year}) but this release is dated {yr} - "
              f"filmed one year, released the next. Accepting sets Plex to {yr}.")
    clashes = prose_date_conflicts(summary, rel["date"])
    if clashes:
        print(f"  !! the prose says {', '.join(clashes)} but this release is dated "
              f"{rel['date']}.")
        print(f"     The wiki's PROSE is no more trustworthy than its infobox. Check it "
              f"against plex_concert_research.py and fix the words with --summary-file.")
    print("-" * 70)
    print(summary)
    print("=" * 70)
    if ask("\napply this to Plex? [y/N] ").lower() != "y":
        print("nothing written")
        return 1

    apply_metadata(token, section, item["rk"], summary, yr, date)

    # ---- artwork ----------------------------------------------------------
    if img_name or args.cover_file:
        install_artwork(token, item, args.wiki or "", img_name,
                        args.rotate or "", args.cover_file or "")

    after = get_item(token, item["rk"])
    print("\nread back from Plex:")
    print(f"  year    : {after['year']}")
    print(f"  oaa     : {after['oaa']}")
    print(f"  summary : {len(after['summary'])} chars")
    ok = str(after["year"]) == yr and len(after["summary"]) > 0
    print("  ->", "applied" if ok else "!! Plex did not take it")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
