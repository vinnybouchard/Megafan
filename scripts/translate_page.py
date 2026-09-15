#!/usr/bin/env python3
"""Render a translated liner page into a JPG that sits beside the scan of it.

    python3 scripts/translate_page.py --text out.txt --like discs/scans/X-1-liner-page-1.jpg \
        --out discs/translations/X-1-liner-page-1.en.jpg --title "NZS-731 — liner, page 1"

WHAT THIS IS AND IS NOT. A lot of these releases carry pages of solid Japanese
prose — the band talking, an essayist setting the record straight — and none of
it reaches anybody who does not read Japanese. This renders a translation of
such a page as its own image, so it can hang beside the scan on the release
page the way a facing-page translation does in a printed book.

It does NOT translate. The translation is the model's, written to a text file by
whoever is running the catalogue pass; this script only sets it. That split is
deliberate and it is the same one the rest of this pipeline uses: the judgement
is model work and cannot be a script, so the script is the part that can be
deterministic, and is.

It also does not doctor the scan. Erasing the Japanese and fitting English into
its place needs OCR, inpainting and per-box font fitting, and on a dense
two-column essay every one of those degrades at once — the result looks like the
page and reads worse than nothing. A clean typeset page is honest about being a
translation, and it is legible, which is the entire point.

THE FOOTER IS NOT DECORATION. A machine translation of a musician's own words is
derived, fallible, and trivially mistaken for the object once it is a JPG in a
folder of scans — so every page it renders says on its face what it is. The
catalogue's whole claim is that its facts come from the object or a named
source; this is neither, and it says so where it cannot be cropped off.

REFUSES RATHER THAN CLIPS. Text that will not fit at the smallest readable size
is an error, not something to silently cut off at the bottom of the page — a
truncated translation is worse than an absent one, because it reads as complete.
Pass --continued to set the overflow as a second page instead.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

# NOT `sys.exit` at import. Pillow may well be absent from the venv you run this
# under (
# it is only needed to RENDER), and a module that dies on import is a module
# whose pure half — the wrapping, the paragraph rules, the glyph check — cannot
# be tested at all. Exit in `main()`, where the command actually needs to draw.
try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except ImportError:                                    # pragma: no cover
    HAVE_PIL = False
    Image = ImageDraw = ImageFont = None

#: Body face. DejaVu ships with most distributions and carries the punctuation a
#: translation actually uses — curly quotes, en dashes, the odd macron in a
#: romanised name. There is NO DejaVu Serif italic in Debian's package, so the
#: italic is Liberation's; asking for one that is not installed is how the
#: subtitle and the disclaimer first came out as 10px bitmap stamps.
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
FONT_ITALIC = "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"

#: Ordered candidates per face. A page set in the wrong serif is a cosmetic
#: problem and no page at all is not — but see `load_font`: falling all the way
#: through is NOT cosmetic and does not happen quietly.
_FALLBACKS = {
    FONT_REGULAR: ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    FONT_BOLD: ("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    FONT_ITALIC: ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
}

#: Printed at the foot of every page. See the module docstring: this is the one
#: line that keeps a rendered translation from reading as the object.
DISCLAIMER = ("Machine translation of the Japanese original. Not a transcription "
              "of the object, and not a source — read the scan beside it.")

#: Page furniture as a fraction of the SHORT edge, so a page rendered to match a
#: 2848px scan and one matching a 6416px spread get the same proportions.
MARGIN = 0.085
#: Body size as a fraction of the short edge, and the floor it may shrink to.
#: Below the floor the page is refused: 1.6% of a 2848px page is a 45px glyph,
#: which is still comfortable, and anything smaller means the text belongs on
#: two pages rather than crushed onto one.
SIZE_START = 0.026
SIZE_FLOOR = 0.016
LINE_SPACING = 1.45
PARA_SPACING = 0.55          # extra blank space between paragraphs, in lines


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """A face at the size asked for, and a LOUD complaint if it could not be.

    `ImageFont.load_default()` ignores the size argument on older Pillow and
    returns a ~10px bitmap stamp, so a silent fall-through here does not degrade
    a layout, it destroys it — measured: the disclaimer this module exists to
    print came out illegible while every step reported success. It is the
    usual rule about inferred values, one layer down: a wrong answer that
    looks like a right one is worse than a refusal.
    """
    for candidate in (path, *_FALLBACKS.get(path, ())):
        if candidate and Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    print(f"  ! no usable font for {Path(path).name} — setting this run in "
          f"Pillow's default face, which will look wrong", file=sys.stderr)
    try:
        return ImageFont.load_default(size=size)      # Pillow >= 10
    except TypeError:
        return ImageFont.load_default()


def unrenderable(text: str, font: ImageFont.FreeTypeFont) -> list[str]:
    """Characters this face has no glyph for, in first-seen order.

    A missing glyph does not fail — it draws `.notdef`, the empty box, which on
    a finished page reads as file corruption rather than as a font problem. The
    check is to render a codepoint no font carries and compare: `getbbox()` is
    NOT enough, because a tofu box has a bounding box like anything else.

    Real, not hypothetical: DejaVu has no CJK and no `※`, and a translation that
    mentions how somebody now writes their name is exactly the kind of sentence
    that reaches for both.
    """
    try:
        notdef = bytes(font.getmask("\uffff"))
    except Exception:                                   # pragma: no cover
        return []
    bad, seen = [], set()
    for ch in text:
        if ch in seen or ch.isspace():
            continue
        seen.add(ch)
        try:
            if bytes(font.getmask(ch)) == notdef:
                bad.append(ch)
        except Exception:                               # pragma: no cover
            continue
    return bad


def paragraphs(text: str) -> list[str]:
    """Blank-line-separated paragraphs, with single newlines treated as flow.

    A translation is written as prose in a text file, and a hard-wrapped source
    file should not become a hard-wrapped page.
    """
    out, buf = [], []
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        if line.strip():
            buf.append(line.strip())
        elif buf:
            out.append(" ".join(buf))
            buf = []
    if buf:
        out.append(" ".join(buf))
    return out


def _wrap(draw: ImageDraw.ImageDraw, para: str, font: ImageFont.FreeTypeFont,
          width: int) -> list[str]:
    """Greedy wrap measured in real glyphs, not characters.

    `textwrap` counts characters, which is wrong for a proportional face by
    enough to overflow a justified-looking margin — measure what will be drawn.
    """
    words = para.split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for word in words[1:]:
        trial = f"{cur} {word}"
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def layout(draw: ImageDraw.ImageDraw, paras: list[str],
           font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Every body line for the page, blank lines included, in order."""
    lines: list[str] = []
    for i, para in enumerate(paras):
        if i:
            lines.append("")
        lines += _wrap(draw, para, font, width)
    return lines


def render(text: str, size: tuple[int, int], title: str,
           subtitle: str = "", continued: bool = False) -> tuple[Image.Image, list[str]]:
    """The page, plus any body lines that did not fit on it.

    Returns leftovers rather than raising so a caller can choose to spill them
    onto a second page; the CLI refuses unless asked to.
    """
    w, h = size
    short = min(w, h)
    margin = int(short * MARGIN)
    box = w - 2 * margin

    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)

    head_f = load_font(FONT_BOLD, int(short * 0.030))
    sub_f = load_font(FONT_ITALIC, int(short * 0.020))
    foot_f = load_font(FONT_ITALIC, int(short * 0.017))

    y = margin
    draw.text((margin, y), title, font=head_f, fill="black")
    y += int(head_f.size * 1.5)
    if subtitle:
        draw.text((margin, y), subtitle, font=sub_f, fill="#444444")
        y += int(sub_f.size * 1.7)
    draw.line([(margin, y), (w - margin, y)], fill="#999999", width=max(2, short // 900))
    y += int(short * 0.022)
    body_top = y

    # the footer sits on the page, so the body may not run into it
    foot_lines = _wrap(draw, DISCLAIMER, foot_f, box)
    foot_h = int(foot_f.size * 1.35) * len(foot_lines)
    body_bottom = h - margin - foot_h - int(short * 0.02)

    paras = paragraphs(text)
    body_f = None
    lines: list[str] = []
    size_px = int(short * SIZE_START)
    floor_px = max(8, int(short * SIZE_FLOOR))
    while size_px >= floor_px:
        body_f = load_font(FONT_REGULAR, size_px)
        lines = layout(draw, paras, body_f, box)
        step = int(body_f.size * LINE_SPACING)
        need = 0
        for ln in lines:
            need += int(step * PARA_SPACING) if ln == "" else step
        if body_top + need <= body_bottom:
            break
        size_px = int(size_px * 0.94)
    if body_f is None:                                  # pragma: no cover - guarded above
        body_f = load_font(FONT_REGULAR, floor_px)
        lines = layout(draw, paras, body_f, box)

    step = int(body_f.size * LINE_SPACING)
    leftover: list[str] = []
    y = body_top
    for i, ln in enumerate(lines):
        advance = int(step * PARA_SPACING) if ln == "" else step
        if y + advance > body_bottom:
            # Drop only the LEADING blanks — a page should not open on white —
            # and keep the interior ones, which are the paragraph breaks. The
            # first cut of this dropped every blank line, so the continuation
            # page came out as one unbroken slab with the sign-off run into the
            # last quote.
            tail = lines[i:]
            while tail and tail[0] == "":
                tail.pop(0)
            leftover = tail
            break
        if ln:
            draw.text((margin, y), ln, font=body_f, fill="#111111")
        y += advance

    y = h - margin - foot_h
    draw.line([(margin, y - int(short * 0.016)), (w - margin, y - int(short * 0.016))],
              fill="#cccccc", width=max(1, short // 1400))
    for ln in foot_lines:
        draw.text((margin, y), ln, font=foot_f, fill="#666666")
        y += int(foot_f.size * 1.35)

    if continued and leftover:
        draw.text((w - margin - draw.textlength("(continued)", font=foot_f),
                   body_bottom + int(short * 0.004)),
                  "(continued)", font=foot_f, fill="#666666")
    return img, leftover


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", type=Path, required=True, help="the translation")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--like", type=Path,
                    help="match this image's pixel dimensions (the scan it translates)")
    ap.add_argument("--size", help="WxH, when there is no scan to match")
    ap.add_argument("--title", required=True, help='e.g. "NZS-731 — liner, page 1"')
    ap.add_argument("--subtitle", default="", help="what the page is, in one line")
    ap.add_argument("--continued", action="store_true",
                    help="spill overflow onto -2.jpg, -3.jpg rather than refusing")
    ap.add_argument("--quality", type=int, default=88)
    a = ap.parse_args()

    if not HAVE_PIL:
        return "needs Pillow: use system python3, or a venv that has PIL"
    if not a.text.is_file():
        return f"no such text file: {a.text}"
    if a.like:
        if not a.like.is_file():
            return f"no such image: {a.like}"
        with Image.open(a.like) as src:
            size = src.size
    elif a.size:
        try:
            w, h = (int(x) for x in a.size.lower().split("x"))
        except ValueError:
            return "--size wants WxH, e.g. 2848x4032"
        size = (w, h)
    else:
        return "give --like <the scan> or --size WxH"

    text = a.text.read_text(encoding="utf-8")
    if not text.strip():
        return f"{a.text} is empty — nothing to set"

    probe = load_font(FONT_REGULAR, 40)
    bad = unrenderable(text + " " + a.title + " " + a.subtitle, probe)
    if bad:
        return ("REFUSING: the body face has no glyph for "
                + " ".join(f"{c!r} (U+{ord(c):04X})" for c in bad[:12])
                + (" …" if len(bad) > 12 else "")
                + ". They would set as empty boxes, which reads as a corrupt file "
                  "rather than a missing font. Romanise them, or swap FONT_REGULAR "
                  "for a face that carries them.")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    written = []
    page, leftover = render(text, size, a.title, a.subtitle, continued=a.continued)
    page.save(a.out, "JPEG", quality=a.quality, optimize=True, progressive=True)
    written.append(a.out)

    n = 1
    while leftover:
        if not a.continued:
            for p in written:
                p.unlink(missing_ok=True)
            return (f"REFUSING: {len(leftover)} line(s) do not fit at the smallest "
                    f"readable size. A clipped translation reads as a complete one. "
                    f"Split the text, or pass --continued to set the rest as "
                    f"{a.out.stem}-2{a.out.suffix}.")
        n += 1
        nxt = a.out.with_name(f"{a.out.stem}-{n}{a.out.suffix}")
        # `leftover` is already wrapped LINES, with "" where a paragraph ended,
        # and `paragraphs()` reads a single newline as flow and a blank line as a
        # break. Joining with "\n\n" therefore made every line its own paragraph
        # and the continuation page came out as a column of one-line stanzas.
        page, leftover = render("\n".join(leftover), size,
                                f"{a.title} (cont.)", a.subtitle, continued=True)
        page.save(nxt, "JPEG", quality=a.quality, optimize=True, progressive=True)
        written.append(nxt)

    for p in written:
        with Image.open(p) as im:
            print(f"  {p}  {im.width}x{im.height}  {p.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
