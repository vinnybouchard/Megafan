#!/usr/bin/env python3
"""WhisperX worker: one audio file in, one transcript JSON out.

The dumb half of the pair: the driver decides WHAT to transcribe and owns every
write into the Plex tree; this side is handed a file and a destination and does
nothing else. It never touches the library, never reaches the driver, and keeps
no state.

Runs on the Plex host, under ``~/whisper/venv``, on its own GPU. It used to run
on the owner's Windows PC because the Pi had no CUDA device; that stopped being
true at the x86 cutover, and the rule now is that your workstation stays out of every Plex
process. Because this file was always "handed a file, write a file", moving it
home required no change to it - only to who launches it.

The transcript is emitted as JSON rather than SRT on purpose: translation
happens on the host and wants segment structure, and an SRT round-trip would
force a parse of text we already have structured.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time

# Whisper's own default. large-v3 is the accuracy ceiling and the model already
# cached on this machine (models--Systran--faster-whisper-large-v3).
DEFAULT_MODEL = "large-v3"
# ASK THE DEVICE rather than hardcoding one. This was `float16` because it was
# written for an RTX 3080; on a Pascal card such as a GTX 1080 Ti, ctranslate2
# REFUSES both float16 and int8_float16 outright - `Requested float16 compute
# type, but the target device or backend do not support efficient float16
# computation` - so a fixed default is a crash on the machine that now runs it.
# Preference order is best-quality-first; `pick_compute` takes the first the
# installed ctranslate2 says this card actually supports.
COMPUTE_PREFERENCE = ("float16", "int8_float16", "int8_float32", "int8", "float32")


def pick_compute(device: str, requested: str | None = None) -> str:
    """The best compute type this device really supports.

    An explicit `--compute-type` still wins, so a bad run is always forceable
    by hand; it is only the DEFAULT that is derived.
    """
    if requested:
        return requested
    try:
        import ctranslate2
        supported = ctranslate2.get_supported_compute_types(device)
    except Exception:                                # noqa: BLE001 - never fatal
        return "int8"                                # the universally safe one
    for candidate in COMPUTE_PREFERENCE:
        if candidate in supported:
            return candidate
    return "int8"


def _emit(obj: dict) -> None:
    """One JSON line to stdout, prefixed so the driver can find it in the noise.

    WhisperX and its dependencies print progress, warnings and HF download bars
    to both streams, so a bare JSON dump on stdout is not reliably parseable.
    """
    sys.stdout.write("__SUBS_JSON__ " + json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description="WhisperX transcribe one file to JSON.")
    ap.add_argument("--audio", required=True, help="input audio (16k mono expected)")
    ap.add_argument("--out", required=True, help="destination JSON path")
    ap.add_argument("--language", default="ja", help="spoken language (ISO code)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--compute-type", default=None,
                    help="override; default is derived from what the card supports")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--no-align", action="store_true",
                    help="skip word-level alignment (faster, coarser timings)")
    args = ap.parse_args()

    if not os.path.isfile(args.audio):
        print(f"ERROR: no such audio file: {args.audio}", file=sys.stderr)
        return 2

    import torch
    import whisperx

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute = pick_compute(device, args.compute_type) if device == "cuda" else "int8"
    if device != "cuda":
        # Not fatal — but the entire reason this file exists is the GPU, so a CPU
        # fallback is a 40x slowdown that must be visible, never silent.
        print("WARNING: no CUDA device, falling back to CPU (very slow)", file=sys.stderr)

    started = time.time()
    audio = whisperx.load_audio(args.audio)
    duration_s = len(audio) / 16000.0

    model = whisperx.load_model(args.model, device, compute_type=compute,
                                language=args.language)
    result = model.transcribe(audio, batch_size=args.batch_size,
                              language=args.language)
    segments = result.get("segments") or []
    transcribe_s = time.time() - started

    # Free the ASR model before the alignment model loads; 11 GB of VRAM does not
    # hold both comfortably on the 1080 Ti.
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    aligned = False
    if not args.no_align and segments:
        # Alignment sharpens segment boundaries, which is what makes a subtitle
        # land on the line rather than a second late. It needs a per-language
        # wav2vec2 model, so it is best-effort: a language with none must degrade
        # to whisper's own timings, not fail the run.
        try:
            align_model, meta = whisperx.load_align_model(
                language_code=args.language, device=device)
            result = whisperx.align(segments, align_model, meta, audio, device,
                                    return_char_alignments=False)
            segments = result.get("segments") or segments
            aligned = True
            del align_model
            gc.collect()
            if device == "cuda":
                torch.cuda.empty_cache()
        except Exception as exc:  # noqa: BLE001 - degrade, never fail the run
            print(f"WARNING: alignment unavailable ({exc}); using whisper timings",
                  file=sys.stderr)

    out = {
        "audio": os.path.basename(args.audio),
        "language": args.language,
        "model": args.model,
        "device": device,
        "compute_type": compute,
        "aligned": aligned,
        "duration_s": round(duration_s, 2),
        "transcribe_s": round(transcribe_s, 1),
        "segments": [
            {
                "start": round(float(s.get("start") or 0.0), 3),
                "end": round(float(s.get("end") or 0.0), 3),
                "text": (s.get("text") or "").strip(),
            }
            for s in segments
            if (s.get("text") or "").strip()
        ],
    }

    payload = json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8")
    tmp = args.out + ".part"
    with open(tmp, "wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, args.out)

    _emit({
        "ok": True,
        "out": args.out,
        "md5": hashlib.md5(payload).hexdigest(),
        "bytes": len(payload),
        "segments": len(out["segments"]),
        "duration_s": out["duration_s"],
        "transcribe_s": out["transcribe_s"],
        "aligned": aligned,
        "device": device,
        "compute_type": compute,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
