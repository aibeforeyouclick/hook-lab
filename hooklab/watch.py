"""Watch one video: open a local file (or download a URL), then analyse it.

Default (v2): `analyze.analyze` writes analysis.json + analysis.md with shot detection,
a labelled contact sheet, a word-level transcript, on-screen text (OCR), audio and
pacing stats. `basic=True` keeps the v1 behaviour: fixed-step frame sheets plus a
timestamped transcript in watch.md.

This is the 'eyes and ears' of the project: a chat that cannot play video can read
the report and look at the sheets to understand what the video shows and says."""
import json
import math
import subprocess
import sys
from pathlib import Path

from .pipeline import _run, whisper_cmd

VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov")


def fmt_ts(seconds):
    s = int(max(0, seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def plan_step(duration, every=3.0, max_frames=48):
    """Seconds between sampled frames: `every`, widened so we never exceed max_frames."""
    if duration <= 0:
        return every
    return max(every, duration / max_frames)


def plan_sheets(duration, step, cols=4, rows=3):
    """List of (start_sec, span_sec, n_frames) for each contact sheet."""
    per = cols * rows
    total = max(1, math.ceil(duration / step))
    sheets, i = [], 0
    while i < total:
        n = min(per, total - i)
        sheets.append((i * step, n * step, n))
        i += n
    return sheets


def transcript_md(segments):
    lines = [f"[{fmt_ts(s['start'])}] {s['text'].strip()}" for s in segments if s["text"].strip()]
    return "\n".join(lines)


def probe_duration(video):
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", str(video)])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def fetch(source, out):
    """Return (video_path, error). `source` is a local file or a URL (via yt-dlp)."""
    p = Path(source)
    if p.is_file():
        return p, ""
    found = [f for f in out.glob("video.*") if f.suffix in VIDEO_EXT]
    if found:
        return found[0], ""
    cmd = [sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=720]+ba/b[height<=720]/b",
           "--merge-output-format", "mp4", "--no-playlist", "-o", str(out / "video.%(ext)s"), "--", source]
    r = _run(cmd)
    found = [f for f in out.glob("video.*") if f.suffix in VIDEO_EXT]
    return (found[0], "") if found else (None, (r.stderr or "")[-300:])


def make_sheets(video, out, duration, step, cols=4, rows=3):
    sdir = out / "sheets"
    sdir.mkdir(exist_ok=True)
    made = []
    for n, (start, span, frames) in enumerate(plan_sheets(duration, step, cols, rows), 1):
        f = sdir / f"sheet_{n:02d}_{fmt_ts(start).replace(':', '')}.jpg"
        r = _run(["ffmpeg", "-y", "-ss", str(start), "-t", str(span), "-i", str(video),
                  "-vf", f"fps=1/{step},scale=360:-2,tile={cols}x{rows}", "-frames:v", "1", str(f)])
        if f.exists():
            made.append((f, start, frames))
    return made


def transcribe_full(video, out, model, lang):
    tdir = out / "transcript"
    tdir.mkdir(exist_ok=True)
    jf = tdir / (video.stem + ".json")
    if not jf.exists():
        _run(whisper_cmd(video, model, tdir, lang))
    if not jf.exists():
        return None
    return json.loads(jf.read_text(encoding="utf-8"))


def watch(source, out_dir, model="small", lang="auto", every=3.0, max_frames=48, cols=4, rows=3,
          basic=False, use_ocr=True, threshold=None, transcribe=True):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    video, err = fetch(source, out)
    if video is None:
        note = f"# Watch failed\n\nCould not get the video from `{source}`.\n\n```\n{err}\n```\n"
        (out / "watch.md").write_text(note, encoding="utf-8")
        return out / "watch.md"
    if not basic:
        from .analyze import CHANGE_THRESHOLD, analyze
        analyze(video, out, model, lang, every, min(max_frames, 40),
                threshold if threshold is not None else CHANGE_THRESHOLD, use_ocr, str(source), transcribe)
        return out / "analysis.md"
    duration = probe_duration(video)
    step = plan_step(duration, every, max_frames)
    sheets = make_sheets(video, out, duration, step, cols, rows)
    data = transcribe_full(video, out, model, lang) if transcribe else None

    md = [f"# Watch report", "", f"- Source: {source}", f"- Video file: {video.name}",
          f"- Length: {fmt_ts(duration)} ({duration:.0f} s)", f"- Frame step: one frame every {step:.1f} s",
          f"- Whisper model: {model}, language: {lang}", ""]
    md += ["## Contact sheets (read left to right, top to bottom; each cell is one step)", ""]
    for f, start, n in sheets:
        md.append(f"- `sheets/{f.name}`: {fmt_ts(start)} onwards, {n} frames")
    if not sheets:
        md.append("- No sheets made (is ffmpeg on PATH?)")
    md += ["", "## Transcript with timestamps", ""]
    if data is None:
        md.append("_No transcript: Whisper is missing or failed. Run `python -m hooklab doctor`._")
    else:
        md.append(f"_Detected language: {data.get('language', '?')}_\n")
        md.append(transcript_md(data.get("segments", [])) or "_No speech found._")
    md += ["", "## How to read this", "",
           "1. Read the transcript for what is said, then open each sheet for what is shown.",
           "2. Burned-in captions often repeat the speech; on-screen text and demos are only in the sheets.",
           "3. Write the concept down in your own words and mark what you could not verify."]
    (out / "watch.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out / "watch.md"
