"""Download -> transcribe -> 5-frame strip, with caching. Runs tools via `python -m`
so nothing needs to be on PATH except ffmpeg."""
import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .classify import classify

FRAME_TIMES = [0.5, 1, 2, 3, 4]  # frame 0 is often blank, so start at 0.5
NO_SPEECH_PHRASES = ("thanks for watching", "thank you for watching")
HOOK_SECONDS = 5.0
OUT_FIELDS = ["channel", "url", "views", "outlier", "title", "hook_text", "speech_start",
              "primary", "tags", "words", "strip", "flag"]


def doctor():
    """Return a list of (name, ok, detail) for required tools."""
    res = [("ffmpeg", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg") or "not on PATH")]
    for mod in ("yt_dlp", "whisper"):
        found = importlib.util.find_spec(mod) is not None
        res.append((mod, found, "installed" if found else "pip install " + mod.replace("_", "-")))
    ocr = importlib.util.find_spec("rapidocr_onnxruntime") is not None
    res.append(("optional: rapidocr_onnxruntime (watch OCR)", None,
                "installed" if ocr else "not installed; watch runs without on-screen text "
                "(pip install rapidocr-onnxruntime inside .venv)"))
    return res


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def download(url, vid, vdir):
    existing = [p for p in vdir.glob(vid + ".*") if p.suffix in (".mp4", ".mkv", ".webm")]
    if existing:
        return existing[0], ""
    base = [sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=720]+ba/b[height<=720]",
            "--merge-output-format", "mp4", "--no-playlist", "-o", str(vdir / "%(id)s.%(ext)s")]
    r = _run(base + ["--", url])
    if r.returncode != 0:   # retry with another YouTube player client if the first attempt is blocked
        r = _run(base + ["--extractor-args", "youtube:player_client=mweb", "--", url])
    found = [p for p in vdir.glob(vid + ".*") if p.suffix in (".mp4", ".mkv", ".webm")]
    return (found[0], "") if found else (None, (r.stderr or "")[-200:])


def whisper_cmd(video, model, tdir, lang="en", words=False):
    """Build the Whisper command. lang='auto' lets Whisper detect the language.
    The *.en models are English-only: for other languages use e.g. --model small.
    words=True adds word-level timestamps (used by `watch`)."""
    cmd = [sys.executable, "-m", "whisper", str(video), "--model", model]
    if lang != "auto":
        cmd += ["--language", lang]
    if words:
        cmd += ["--word_timestamps", "True"]
    return cmd + ["--output_format", "json", "--output_dir", str(tdir)]


def transcribe(video, model, tdir, lang="en"):
    jf = tdir / (video.stem + ".json")
    if not jf.exists():
        _run(whisper_cmd(video, model, tdir, lang))
    if not jf.exists():
        return "", None, "transcribe-failed"
    return hook_from_segments(json.loads(jf.read_text(encoding="utf-8")).get("segments", []))


def hook_from_segments(segments):
    """First-5-seconds text, when speech starts, and a no-speech flag."""
    inside = [s for s in segments if s["start"] < HOOK_SECONDS]
    text = " ".join(s["text"].strip() for s in inside).strip()
    start = round(inside[0]["start"], 1) if inside else None
    flag = ""
    if not text or any(p in text.lower() for p in NO_SPEECH_PHRASES):
        flag = "no-speech?"  # Whisper invents 'thanks for watching' over music
    elif inside and all(s.get("no_speech_prob", 0) > 0.6 for s in inside):
        flag = "no-speech?"
    return text, start, flag


def strip(video, sdir):
    frames = []
    for t in FRAME_TIMES:
        f = sdir / f"{video.stem}_{t}.jpg"
        _run(["ffmpeg", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1",
              "-vf", "scale=360:-2", str(f)])
        if f.exists():
            frames.append(f)
    if len(frames) < 2:
        return ""
    out = sdir / f"{video.stem}_strip.jpg"
    cmd = ["ffmpeg", "-y"]
    for f in frames:
        cmd += ["-i", str(f)]
    _run(cmd + ["-filter_complex", f"hstack=inputs={len(frames)}", str(out)])
    for f in frames:
        f.unlink(missing_ok=True)
    return str(out) if out.exists() else ""


def run_queue(run_dir, model="base.en", workers=2, lang="en"):
    """Read queue.csv in run_dir, process every row, write hooks.csv."""
    run = Path(run_dir)
    vdir, tdir, sdir = run / "videos", run / "transcripts", run / "strips"
    for d in (vdir, tdir, sdir):
        d.mkdir(parents=True, exist_ok=True)
    with open(run / "queue.csv", newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    def dl(row):  # 2 parallel downloads at most: more gets YouTube to block
        return download(row["url"], row["id"], vdir)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        downloads = list(ex.map(dl, rows))

    out_rows = []
    for row, (video, err) in zip(rows, downloads):
        rec = {k: row.get(k, "") for k in ("channel", "url", "views", "outlier", "title")}
        if video is None:
            rec.update(hook_text="", speech_start="", primary="DOWNLOAD_FAILED", tags="",
                       words=0, strip="", flag=err.strip())
        else:
            text, start, flag = transcribe(video, model, tdir, lang)
            c = classify("" if flag == "no-speech?" else text)
            rec.update(hook_text=text, speech_start="" if start is None else start,
                       primary=c["primary"], tags="|".join(c["tags"]), words=c["words"],
                       strip=strip(video, sdir), flag=flag)
        out_rows.append(rec)

    with open(run / "hooks.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(out_rows)
    return out_rows
