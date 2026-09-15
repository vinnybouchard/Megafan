#!/usr/bin/env python3
"""Cut a scan into a COMPLETE, overlapping grid of readable tiles.

Why this exists, in one sentence: reading a booklet by cropping to where you
think a block is gives you no denominator, so nothing ever tells you there was
a bottom half.

Measured 2026-09-12 on ESBL-2192, which is the whole argument. Three credits
pages were transcribed by hand-cropping "the band block", "the crew block",
"the legal block" - fractions guessed by eye, each sized to the thing being
hunted for. Coverage came out 51%, 57% and 38%. What sat in the unread
remainder was not the tail of a crew list: it was the PROMOTERS block spanning
two pages, the whole VTR CREW, and - only there - the fact that the disc was
PRODUCED BY Epic Records Japan AND BS FUJI. A co-producer was absent from the
record entirely, and the report called the gap "two crew pages", a description
of content nobody had looked at.

So the rule this tool exists to make cheap: you do not crop a scan to find
something. You tile it and you read every tile. The manifest is the denominator
and the tile count is the thing you state in the report.

TWO THINGS IT GUARANTEES, both asserted rather than hoped for:

  * Every pixel is in at least one tile. `verify_cover` walks the emitted boxes
    and refuses to write a manifest that leaves a gap, so "I read all the tiles"
    and "I read the page" are the same sentence.

  * Tiles OVERLAP. A seam is exactly where a line of text goes missing while
    both neighbours look complete - a heading sitting on the boundary is read as
    belonging to neither. The default 15% is far more than one line of body text
    at any sane tile size.

It does not upscale for you. Pass --scale to render bigger tiles if the text is
small; the default 2x is what made 9pt credits legible on a 1360x2128 phone
scan, and the point of `--probe` is to settle that in one look before you spend
N reads on tiles you cannot actually read.

DELIBERATELY NOT OFFERED: a "skip the blank tiles" flag. It is the obvious next
optimisation and it hands the judgement back to exactly the place that failed -
the whole bug was deciding, without looking, that a region held nothing worth
reading. A variance threshold cannot tell faint ink on a black booklet page from
an empty one, and the saving is a handful of reads against the cost of another
silently half-read object. Eight scans of a jacket come to 64 tiles; that is the
price of the guarantee, and it is cheap next to what it buys.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("needs Pillow: use system python3, or a venv that has PIL")

# A tile has to survive the display downscale. Measured across this session's
# own reads, the viewer caps the LONG EDGE at 2000px (2121x3192 came back
# 1329x2000; 3060x475 came back 2000x310), so a tile rendered longer than that
# is silently shrunk and the upscale you asked for buys nothing.
#
# Getting this wrong is not harmless: an under-estimate pushes you into more
# columns than the page has, which splits a line of text mid-word across tiles
# and makes you reassemble prose that was never broken.
DISPLAY_LONG_EDGE = 2000


def plan(w: int, h: int, cols: int, rows: int, overlap: float) -> list[dict]:
    """Boxes for a cols x rows grid, each grown by `overlap` on every side."""
    out = []
    tw, th = w / cols, h / rows
    ox, oy = tw * overlap, th * overlap
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(c * tw - ox))
            y0 = max(0, int(r * th - oy))
            x1 = min(w, int((c + 1) * tw + ox))
            y1 = min(h, int((r + 1) * th + oy))
            out.append({"row": r + 1, "col": c + 1, "box": [x0, y0, x1, y1]})
    return out


def verify_cover(tiles: list[dict], w: int, h: int, step: int = 4) -> list[tuple[int, int]]:
    """Sample the page and return any point no tile contains. Empty == covered."""
    holes = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            if not any(t["box"][0] <= x < t["box"][2] and t["box"][1] <= y < t["box"][3]
                       for t in tiles):
                holes.append((x, y))
                if len(holes) > 20:
                    return holes
    return holes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--out", type=Path, help="tile directory (default: <image stem>-tiles)")
    ap.add_argument("--cols", type=int, default=2)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--overlap", type=float, default=0.15, help="fraction of a tile, per side")
    ap.add_argument("--scale", type=float, default=2.0, help="upscale each tile by this")
    ap.add_argument("--probe", action="store_true",
                    help="write ONE middle tile and stop, to check the text is legible")
    a = ap.parse_args()

    if not a.image.is_file():
        return f"no such image: {a.image}"
    im = Image.open(a.image)
    w, h = im.size
    out = a.out or a.image.with_name(a.image.stem + "-tiles")

    tiles = plan(w, h, a.cols, a.rows, a.overlap)
    holes = verify_cover(tiles, w, h)
    if holes:
        return f"REFUSING: {len(holes)}+ uncovered points, first at {holes[0]} - geometry bug"

    long_edge = max(max(t["box"][2] - t["box"][0], t["box"][3] - t["box"][1])
                    for t in tiles) * a.scale
    warn = ""
    if long_edge > DISPLAY_LONG_EDGE:
        warn = (f"\n  ! a tile renders {long_edge:.0f}px on its long edge and the viewer caps "
                f"at {DISPLAY_LONG_EDGE}px,\n    so it will be shrunk back. Raise --rows (prefer "
                f"rows over cols: splitting a\n    text column across tiles breaks lines "
                f"mid-word) or lower --scale.")

    if a.probe:
        t = tiles[len(tiles) // 2]
        out.mkdir(parents=True, exist_ok=True)
        p = out / "probe.png"
        c = im.crop(tuple(t["box"]))
        c.resize((int(c.width * a.scale), int(c.height * a.scale)), Image.LANCZOS).save(p)
        print(f"  probe tile (r{t['row']}c{t['col']}) -> {p}\n"
              f"  LOOK AT IT. If the text is not comfortably readable, raise --scale "
              f"(and --cols/--rows to match).{warn}")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("tile_*.png"):
        old.unlink()
    for t in tiles:
        c = im.crop(tuple(t["box"]))
        c = c.resize((int(c.width * a.scale), int(c.height * a.scale)), Image.LANCZOS)
        name = f"tile_r{t['row']}c{t['col']}.png"
        c.save(out / name)
        t["file"] = name

    manifest = {
        "image": str(a.image),
        "image_size": [w, h],
        "grid": {"cols": a.cols, "rows": a.rows, "overlap": a.overlap, "scale": a.scale},
        "covers_full_page": True,
        "tile_count": len(tiles),
        "tiles": tiles,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"  {a.image.name}  {w}x{h}")
    print(f"  {len(tiles)} tiles -> {out}/   (every pixel covered, {a.overlap:.0%} overlap){warn}")
    print(f"\n  READ ALL {len(tiles)}. Not the ones that look like they have something on them:")
    for t in tiles:
        print(f"    [ ] {t['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
