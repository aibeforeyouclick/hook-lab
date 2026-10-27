"""Rich local analysis of one short video (v2 of `watch`).

Everything runs on this machine: ffmpeg for shots, frames and audio, Whisper for a
word-level transcript, and (when installed) RapidOCR for on-screen text. The output is
`analysis.json` (machine-readable) and `analysis.md` (a shot-by-shot timeline a chat
can read like it watched the video), plus `frames/`, `sheets/contact_NN.jpg` and
`sheets/hook.jpg`.

The parsing and statistics functions are pure so they can be tested offline."""
import difflib
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

from .classify import classify
from .extract import extract_mentions
from .pipeline import NO_SPEECH_PHRASES, _run, whisper_cmd

SCHEMA = "hooklab.analysis/1"
HOOK_SECONDS = 3.0
SHEET_FRAMES = 20
HOOK_TIMES = [0.05] + [round(0.25 * i, 2) for i in range(1, 12)]  # 4 fps over 0-3 s = 12 cells (4x3); 0.0 is often black
CHANGE_THRESHOLD = 0.12  # visual change (zoom, b-roll, slide) on low-res shorts
HARD_CUT_THRESHOLD = 0.30  # clear hard cut
MIN_SHOT = 0.5  # seconds; bursts closer than this count as one change
SILENCE_DB = -35
SILENCE_MIN = 0.4
OCR_MIN_SCORE = 0.6

CTA_PATTERNS = [
    (r"\bcomment\s+[\"'“]?([a-z0-9]+)", "comment-keyword"),
    (r"\blink in (?:my |the )?bio\b", "link-in-bio"),
    (r"\b(?:follow|subscribe)\b", "follow/subscribe"),
    (r"\bsave this\b", "save-this"),
    (r"\b(?:dm|message) me\b", "dm-me"),
]
CLAIM_RE = re.compile(r"(\$\s?\d|\d+\s?(?:k|m|million|thousand)\b|\bfollowers\b|\bviews\b|\bi made\b|"
                      r"\brevenue\b|\bper (?:month|day)\b|\bviral\b)", re.I)


# ---------- small helpers ----------

def fmt_ts(seconds, decimals=False):
    s = max(0.0, float(seconds))
    if decimals:
        return f"{int(s // 60):02d}:{s % 60:04.1f}"
    s = int(s)
    return f"{s // 60:02d}:{s % 60:02d}"


def file_id(path):
    """Short stable id of a video file (size + first 4 MB), used to spot repeats."""
    p = Path(path)
    h = hashlib.sha1(str(p.stat().st_size).encode())
    with open(p, "rb") as fh:
        h.update(fh.read(4 * 1024 * 1024))
    return h.hexdigest()[:12]


def norm(text):
    return re.sub(r"[^\w]+", " ", (text or "").lower(), flags=re.UNICODE).strip()


def squash(text):
    """Lowercase letters/digits only: OCR often drops the spaces between words."""
    return re.sub(r"[\W_]+", "", (text or "").lower(), flags=re.UNICODE)


def similar(a, b, ratio=0.8):
    a, b = squash(a), squash(b)
    if not a or not b:
        return a == b
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= ratio


def collect_text(frames, limit=10):
    """On-screen text from frames (not captions), near-duplicates merged (OCR reads the
    same line slightly differently in each frame). Keeps the `limit` biggest lines (big
    font = headline) in order of appearance. Returns (texts, n_dropped)."""
    kept = []
    for f in frames:
        for ln in f.get("ocr", []):
            if ln.get("kind") != "text":
                continue
            if any(similar(ln["text"], k["text"]) for k in kept):
                continue
            kept.append({"text": ln["text"], "h": ln.get("h", 0), "order": len(kept)})
    top = sorted(sorted(kept, key=lambda k: -k["h"])[:limit], key=lambda k: k["order"])
    return [k["text"] for k in top], len(kept) - len(top)


# ---------- probing ----------

def probe(video):
    r = _run(["ffprobe", "-v", "error", "-show_entries",
              "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", str(video)])
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        data = {}
    return parse_probe(data)


def parse_probe(data):
    info = {"duration": 0.0, "width": None, "height": None, "fps": None, "has_audio": False}
    try:
        info["duration"] = float(data.get("format", {}).get("duration", 0) or 0)
    except ValueError:
        pass
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and info["width"] is None:
            info["width"], info["height"] = s.get("width"), s.get("height")
            num, _, den = (s.get("r_frame_rate") or "0/1").partition("/")
            try:
                info["fps"] = round(float(num) / float(den or 1), 2)
            except (ValueError, ZeroDivisionError):
                pass
        if s.get("codec_type") == "audio":
            info["has_audio"] = True
    if info["width"] and info["height"]:
        info["orientation"] = "vertical" if info["height"] > info["width"] else (
            "square" if info["height"] == info["width"] else "horizontal")
    return info


# ---------- shots ----------

def scene_scores(video):
    """Every frame's ffmpeg scene score as [(t, score)]. One pass, no files written."""
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an", "-vf",
              "select='gte(scene,0)',metadata=print:key=lavfi.scene_score", "-f", "null", "-"])
    return parse_scene_scores(r.stderr or "")


def parse_scene_scores(text):
    out, t = [], None
    for line in text.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if m and t is not None:
            out.append((t, float(m.group(1))))
            t = None
    return out


def pick_cuts(scores, threshold=CHANGE_THRESHOLD, min_gap=MIN_SHOT):
    """Times of visual changes: scores >= threshold, keeping the strongest in each burst.
    The first ~0.15 s is ignored (fade-in from black is not an edit)."""
    cands = [(t, s) for t, s in scores if s >= threshold and t > 0.15]
    cuts = []
    for t, s in cands:
        if cuts and t - cuts[-1][0] < min_gap:
            if s > cuts[-1][1]:
                cuts[-1] = (t, s)
            continue
        cuts.append((t, s))
    return [(round(t, 2), round(s, 3)) for t, s in cuts]


def shots_from_cuts(cuts, duration):
    bounds = [0.0] + [t for t, _ in cuts if 0 < t < duration] + [duration]
    shots = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a <= 0:
            continue
        score = cuts[i - 1][1] if i > 0 else None
        shots.append({"index": len(shots) + 1, "start": round(a, 2), "end": round(b, 2),
                      "length": round(b - a, 2), "cut_score": score,
                      "cut_type": None if score is None else ("hard" if score >= HARD_CUT_THRESHOLD else "change")})
    return shots


def frame_times(shots, every=3.0, max_frames=40):
    """One frame in the middle of each shot (readable, not mid-transition), plus extra
    frames every `every` s in long shots. Widens `every` until within max_frames."""
    step = every
    while True:
        times = []
        for sh in shots:
            a, b = sh["start"], sh["end"]
            n = max(1, math.ceil((b - a) / step - 0.25))
            for k in range(n):
                times.append(round(a + (b - a) * (k + 0.5) / n, 2))
        if len(times) <= max_frames or step > 600:
            return times[:max_frames] if len(times) > max_frames else times
        step *= 1.5


# ---------- frames and sheets ----------

def grab_frame(video, t, dest, width=None):
    vf = ["-vf", f"scale={width}:-2"] if width else []
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
          "-frames:v", "1", *vf, "-q:v", "3", str(dest)])
    return Path(dest).exists()


def make_sheet(frames, dest, cols=6, cell_w=240):
    """frames: [(path, label)]. Pillow when available (labels each cell), else ffmpeg tile."""
    frames = [(Path(p), lab) for p, lab in frames if Path(p).exists()]
    if not frames:
        return None
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        Image = None
    if Image is None:
        rows = -(-len(frames) // cols)
        lst = Path(dest).with_suffix(".txt")
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p, _ in frames), encoding="utf-8")
        _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
              "-vf", f"scale={cell_w}:-2,tile={cols}x{rows}", "-frames:v", "1", str(dest)])
        lst.unlink(missing_ok=True)
        return Path(dest) if Path(dest).exists() else None
    imgs = []
    for p, lab in frames:
        im = Image.open(p).convert("RGB")
        im = im.resize((cell_w, max(1, int(im.height * cell_w / im.width))))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 8 * len(lab) + 8, 18], fill=(0, 0, 0))
        d.text((4, 3), lab, fill=(255, 255, 0))
        imgs.append(im)
    cell_h = max(i.height for i in imgs)
    cols = min(cols, len(imgs))
    rows = -(-len(imgs) // cols)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), (20, 20, 20))
    for i, im in enumerate(imgs):
        sheet.paste(im, ((i % cols) * cell_w, (i // cols) * cell_h))
    sheet.save(dest, quality=85)
    return Path(dest)


# ---------- transcript ----------

def transcribe_words(video, out, model, lang):
    tdir = out / "transcript"
    tdir.mkdir(exist_ok=True)
    jf = tdir / (video.stem + ".json")
    if not jf.exists():
        _run(whisper_cmd(video, model, tdir, lang, words=True))
    if not jf.exists():
        return None
    return json.loads(jf.read_text(encoding="utf-8"))


def words_from_whisper(data):
    """Flatten Whisper JSON into [{'w','start','end','p'}]. Falls back to one pseudo-word
    per segment when word timestamps are missing. Drops likely hallucinated segments."""
    words = []
    for seg in (data or {}).get("segments", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        if seg.get("no_speech_prob", 0) > 0.8 and any(p in text.lower() for p in NO_SPEECH_PHRASES):
            continue
        if seg.get("words"):
            for w in seg["words"]:
                if w.get("word", "").strip():
                    words.append({"w": w["word"].strip(), "start": round(w["start"], 2),
                                  "end": round(w["end"], 2), "p": round(w.get("probability", 1.0), 2)})
        else:
            words.append({"w": text, "start": round(seg["start"], 2), "end": round(seg["end"], 2), "p": None})
    return words


MUSIC_RE = re.compile("[\\u266a\\u266b\\ufffd]")  # music notes / replacement char in Whisper output


def transcript_quality(words, model, language):
    """Warnings for the reader: unreliable transcript, English-only model, timing accuracy."""
    out = []
    if model.endswith(".en"):
        out.append(f"Model {model} is English-only: non-English speech gets silently translated or garbled. "
                   "Use --model small --lang auto (or --lang he).")
    scored = [w for w in words if w.get("p") is not None]
    if scored:
        bad = sum(1 for w in scored if w["p"] < 0.4 or MUSIC_RE.search(w["w"]))
        if bad / len(scored) > 0.2:
            out.append(f"Transcript UNRELIABLE: {bad} of {len(scored)} words have low confidence or are "
                       "music symbols. Try --model medium, or check the language.")
        out.append("Word timings are Whisper estimates (about +/-0.2 s); names of tools/repos may be misspelled.")
    return out


def text_between(words, a, b):
    return " ".join(w["w"] for w in words if a <= w["start"] < b).strip()


def speech_intervals(words, join_gap=0.3):
    iv = []
    for w in words:
        if iv and w["start"] - iv[-1][1] <= join_gap:
            iv[-1][1] = max(iv[-1][1], w["end"])
        else:
            iv.append([w["start"], w["end"]])
    return [(round(a, 2), round(b, 2)) for a, b in iv]


# ---------- audio ----------

def audio_scan(video):
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af",
              f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN},ebur128", "-f", "null", "-"])
    return parse_audio(r.stderr or "")


def parse_audio(text):
    momentary, silences, start = [], [], None
    integrated = lra = None
    in_summary = False
    for line in text.splitlines():
        m = re.search(r"\bt:\s*([0-9.]+)\s+TARGET:.*?M:\s*(-?[0-9.]+)", line)
        if m:
            momentary.append((float(m.group(1)), float(m.group(2))))
            continue
        m = re.search(r"silence_start:\s*(-?[0-9.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m:
            silences.append((round(start or 0.0, 2), round(float(m.group(1)), 2)))
            start = None
            continue
        if "Summary:" in line:
            in_summary = True
        if in_summary:
            m = re.match(r"\s*I:\s*(-?[0-9.]+) LUFS", line)
            if m:
                integrated = float(m.group(1))
            m = re.match(r"\s*LRA:\s*(-?[0-9.]+) LU", line)
            if m:
                lra = float(m.group(1))
    if start is not None:  # silence that runs to the end of the file
        silences.append((round(start, 2), None))
    return {"momentary": momentary, "silences": silences, "integrated_lufs": integrated, "lra": lra}


def audio_features(scan, speech_iv, duration, transcribed=True):
    """Speech vs music/sfx (heuristic): loudness while nobody speaks tells whether a
    music/sound bed is present. Labels are guesses and say so."""
    if duration <= 0:
        return {}
    silences = [(a, b if b is not None else duration) for a, b in scan.get("silences", [])]
    silent = sum(max(0, b - a) for a, b in silences)
    spoken = sum(b - a for a, b in speech_iv)

    def in_speech(t):
        return any(a - 0.15 <= t <= b + 0.15 for a, b in speech_iv)

    # Pauses of 0.6 s or more. Momentary loudness uses a 0.4 s window that ends at t,
    # so only samples >= 0.45 s into a pause measure the pause and not the last word.
    edges = [0.0] + [x for iv in speech_iv for x in iv] + [duration]
    pauses = [(edges[i], edges[i + 1]) for i in range(0, len(edges) - 1, 2) if edges[i + 1] - edges[i] >= 0.6]
    gap_levels = [m for t, m in scan.get("momentary", [])
                  if any(a + 0.45 <= t <= b for a, b in pauses) and m > -100]
    speech_levels = [m for t, m in scan.get("momentary", []) if in_speech(t) and m > -100]
    gap_med = round(statistics.median(gap_levels), 1) if len(gap_levels) >= 5 else None
    speech_cov = spoken / duration
    if not scan.get("momentary") and scan.get("integrated_lufs") is None:
        label = "no audio track"
    elif not transcribed:
        label = "audio present; speech unknown (no transcript)"
    elif speech_cov < 0.1:
        label = "no speech: music/sound only" if (gap_med or -120) > -45 else "mostly silent"
    elif gap_med is None:
        label = "speech almost throughout; background audio undetermined (no long pauses)"
    elif gap_med > -40:
        label = "speech over a music/sound bed (heuristic)"
    else:
        label = "speech, little or no background audio (heuristic)"
    return {
        "label": label,
        "integrated_lufs": scan.get("integrated_lufs"),
        "loudness_range_lu": scan.get("lra"),
        "speech_coverage": round(speech_cov, 2),
        "silence_seconds": round(silent, 1),
        "silences": silences,
        "median_lufs_in_speech": round(statistics.median(speech_levels), 1) if speech_levels else None,
        "median_lufs_between_words": gap_med,
    }


# ---------- OCR ----------

def load_ocr():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:  # not installed or broken onnxruntime
        return None
    return RapidOCR()


def ocr_frame(engine, path):
    try:
        result, _ = engine(str(path))
    except Exception:
        return []
    lines = []
    for box, text, score in result or []:
        if float(score) >= OCR_MIN_SCORE and len(re.findall(r"\w", text)) >= 2:
            ys = [pt[1] for pt in box]
            lines.append({"text": text.strip(), "score": round(float(score), 2), "y": round(min(ys)),
                          "h": round(max(ys) - min(ys))})
    return sorted(lines, key=lambda x: x["y"])


def classify_screen_text(lines, transcript_norm):
    """Mark OCR lines that just repeat the speech (burned-in captions) vs other text.
    Compared without spaces, because OCR often reads 'AND IT FEELS' as 'ANDITFEELS'."""
    out, flat = [], squash(transcript_norm)
    for ln in lines:
        n = squash(ln["text"])
        kind = "caption" if n and len(n) >= 2 and n in flat else "text"
        out.append({**ln, "kind": kind})
    return out


# ---------- pacing and hook ----------

def pacing(shots, words, duration, frames_ocr=None):
    cuts = [s["start"] for s in shots[1:]]
    lengths = [s["length"] for s in shots]
    n_words = len(words)
    first_word = words[0]["start"] if words else None
    span = (words[-1]["end"] - words[0]["start"]) if words else 0
    first_text = None
    for f in frames_ocr or []:
        if any(l["kind"] == "text" for l in f["ocr"]):
            first_text = f["t"]
            break
    return {
        "shots": len(shots),
        "visual_changes": len(cuts),
        "hard_cuts": sum(1 for s in shots[1:] if s["cut_type"] == "hard"),
        "changes_per_second": round(len(cuts) / duration, 3) if duration else 0,
        "avg_shot_seconds": round(statistics.mean(lengths), 2) if lengths else 0,
        "median_shot_seconds": round(statistics.median(lengths), 2) if lengths else 0,
        "longest_shot_seconds": round(max(lengths), 2) if lengths else 0,
        "max_seconds_without_visual_change": round(max(lengths), 2) if lengths else 0,
        "changes_per_10s": round(10 * len(cuts) / duration, 2) if duration else 0,
        "words_per_second": round(n_words / span, 2) if span > 1 else None,
        "first_visual_change": cuts[0] if cuts else None,
        "time_to_first_word": first_word,
        "first_on_screen_text_frame": first_text,
        "words": n_words,
        "cut_times": cuts,
        "words_per_minute": round(n_words / (span / 60), 0) if span > 1 else None,
    }


def first_text_change(hook_frames):
    """Time of the first hook frame whose on-screen text differs from the first frame."""
    if not hook_frames:
        return None
    def joined(f):
        return " ".join(l["text"] for l in f["ocr"])

    base = joined(hook_frames[0])
    for f in hook_frames[1:]:
        if not similar(joined(f), base, 0.85):
            return f["t"]
    return None


def hook_window(words, shots, frames, seconds=HOOK_SECONDS, hook_frames=()):
    said = text_between(words, 0, seconds)
    said5 = text_between(words, 0, 5.0)
    shown, more = collect_text([f for f in list(hook_frames) + list(frames) if f["t"] <= seconds], 12)
    return {
        "seconds": seconds,
        "said": said,
        "said_first_5s": said5,
        "on_screen_text": shown,
        "on_screen_text_more": more,
        "visual_changes": sum(1 for s in shots[1:] if s["start"] < seconds),
        "first_text_change": first_text_change(list(hook_frames)),
        "hook_type": classify(said5) if said5 else classify(" ".join(shown)) if shown else classify(""),
    }


def find_ctas(text):
    found, low = [], (text or "").lower()
    for pat, kind in CTA_PATTERNS:
        for m in re.finditer(pat, low):
            item = {"kind": kind, "match": m.group(0)}
            if item not in found:
                found.append(item)
    return found


def claim_sentences(words):
    text = " ".join(w["w"] for w in words)
    sents = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sents if CLAIM_RE.search(s)][:10]


# ---------- the whole thing ----------

def analyze(video, out, model="small", lang="auto", every=3.0, max_frames=40,
            threshold=CHANGE_THRESHOLD, use_ocr=True, source=None, transcribe=True):
    video, out = Path(video), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    fdir, sdir = out / "frames", out / "sheets"
    fdir.mkdir(exist_ok=True)
    sdir.mkdir(exist_ok=True)
    notes = []

    info = probe(video)
    duration = info["duration"]
    scores = scene_scores(video)
    cuts = pick_cuts(scores, threshold)
    shots = shots_from_cuts(cuts, duration) or [{"index": 1, "start": 0.0, "end": duration,
                                                  "length": duration, "cut_score": None, "cut_type": None}]

    data = transcribe_words(video, out, model, lang) if transcribe else None
    if transcribe and data is None:
        notes.append("Whisper missing or failed: no transcript. Run `python -m hooklab doctor`.")
    words = words_from_whisper(data)
    notes += transcript_quality(words, model, (data or {}).get("language"))
    transcript_norm = norm(" ".join(w["w"] for w in words))

    engine = load_ocr() if use_ocr else None
    if use_ocr and engine is None:
        notes.append("OCR not available (pip install rapidocr-onnxruntime in the project venv).")

    frames = []
    for t in frame_times(shots, every, max_frames):
        dest = fdir / f"f_{t:07.2f}.jpg"
        if not grab_frame(video, t, dest):
            continue
        shot = next((s["index"] for s in shots if s["start"] <= t < s["end"]), shots[-1]["index"])
        ocr = classify_screen_text(ocr_frame(engine, dest), transcript_norm) if engine else []
        frames.append({"t": t, "shot": shot, "file": f"frames/{dest.name}", "ocr": ocr})

    hook_frames = []
    for t in [x for x in HOOK_TIMES if x < max(duration, 0.1)]:
        dest = fdir / f"hook_{t:04.2f}.jpg"
        if grab_frame(video, t, dest):
            ocr = classify_screen_text(ocr_frame(engine, dest), transcript_norm) if engine else []
            hook_frames.append({"t": t, "file": f"frames/{dest.name}", "ocr": ocr})
    contacts = []  # 20 frames (5x4) per sheet keeps each image readable when viewed whole
    for i in range(0, len(frames), SHEET_FRAMES):
        part = frames[i:i + SHEET_FRAMES]
        c = make_sheet([(out / f["file"], f"{fmt_ts(f['t'], True)} s{f['shot']}") for f in part],
                       sdir / f"contact_{i // SHEET_FRAMES + 1:02d}.jpg", cols=5)
        if c:
            contacts.append(f"sheets/{c.name}")
    hook_sheet = make_sheet([(out / f["file"], fmt_ts(f["t"], True)) for f in hook_frames],
                            sdir / "hook.jpg", cols=min(4, len(hook_frames) or 1))

    speech_iv = speech_intervals(words)
    audio = audio_features(audio_scan(video), speech_iv, duration, data is not None) if info["has_audio"] else {"label": "no audio track"}

    for sh in shots:
        sh["said"] = text_between(words, sh["start"], sh["end"])
        sh["on_screen_text"], sh["on_screen_text_more"] = collect_text(
            [f for f in frames if f["shot"] == sh["index"]], 8)
        sh["frames"] = [f["file"] for f in frames if f["shot"] == sh["index"]]

    full_text = " ".join(w["w"] for w in words)
    screen_lines = [(f["t"], ln["text"]) for f in hook_frames + frames for ln in f["ocr"] if ln["kind"] == "text"]
    result = {
        "schema": SCHEMA,
        "source": source or str(video),
        "video_file": video.name,
        "video_id": file_id(video),
        "media": info,
        "settings": {"whisper_model": model, "lang": lang, "change_threshold": threshold,
                     "hard_cut_threshold": HARD_CUT_THRESHOLD, "ocr": bool(engine)},
        "language": (data or {}).get("language"),
        "pacing": pacing(shots, words, duration, frames),
        "hook": hook_window(words, shots, frames, hook_frames=hook_frames),
        "hook_frames": hook_frames,
        "audio": audio,
        "shots": shots,
        "frames": frames,
        "transcript": {"text": full_text, "segments": [
            {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
            for s in (data or {}).get("segments", []) if s.get("text", "").strip()], "words": words},
        "ctas": find_ctas(full_text + " " + " ".join(t for _, t in screen_lines)),
        "claim_candidates": claim_sentences(words),
        "mentions": extract_mentions([(w["start"], w["w"]) for w in words], screen_lines),
        "sheets": {"contact": contacts,
                   "hook": f"sheets/{hook_sheet.name}" if hook_sheet else None},
        "notes": notes,
    }
    (out / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "analysis.md").write_text(render_md(result), encoding="utf-8")
    return result


def render_md(a):
    p, h, au, m = a["pacing"], a["hook"], a["audio"], a["media"]
    L = ["# Video analysis", "",
         f"- Source: {a['source']}", f"- File: {a['video_file']} (id {a['video_id']})",
         f"- Length {fmt_ts(m['duration'], True)}, {m.get('width')}x{m.get('height')} "
         f"{m.get('orientation', '')}, {m.get('fps')} fps",
         f"- Speech language: {a.get('language') or 'n/a'} (Whisper {a['settings']['whisper_model']}); "
         f"OCR: {'on' if a['settings']['ocr'] else 'off'}", ""]
    for n in a.get("notes", []):
        L.append(f"> NOTE: {n}")
    L += ["", "## Hook (first 3 s)", "",
          f"- Said (0-3 s): {h['said'] or '_nothing_'}",
          f"- Said (0-5 s): {h['said_first_5s'] or '_nothing_'}",
          f"- On-screen text (0-3 s, biggest first-seen lines): {'; '.join(h['on_screen_text']) or '_none read_'}"
          + (f" (+{h['on_screen_text_more']} smaller)" if h.get("on_screen_text_more") else ""),
          f"- Visual changes in 0-3 s (scene filter): {h['visual_changes']}; on-screen text first changes at "
          f"{h['first_text_change'] if h.get('first_text_change') is not None else '-'} s",
          f"- Hook type (auto, English patterns): {h['hook_type']['primary']} {h['hook_type']['tags']}",
          f"- Look at `{a['sheets']['hook']}` (12 frames, 4 per second, 0-2.75 s).", "",
          "## Pacing", "",
          "| metric | value |", "|---|---|"]
    for k, v in p.items():
        L.append(f"| {k.replace('_', ' ')} | {v if v is not None else '-'} |")
    L += ["", "## Audio", "", f"- {au.get('label')}"]
    if "integrated_lufs" in au:
        L += [f"- Loudness {au['integrated_lufs']} LUFS integrated, range {au['loudness_range_lu']} LU; "
              f"speech covers {int(au['speech_coverage'] * 100)}% of the video; silence {au['silence_seconds']} s.",
              f"- Median loudness while speaking {au['median_lufs_in_speech']} LUFS, between words "
              f"{au['median_lufs_between_words']} LUFS (above about -40 suggests a music/sound bed)."]
    L += ["", "## Timeline, shot by shot", "",
          "Each shot = the span between two visual changes. 'Said' is the word-level transcript, "
          "'Screen' is OCR text that is NOT just the burned-in captions.", ""]
    for sh in a["shots"]:
        cut = f" ({sh['cut_type']} cut {sh['cut_score']})" if sh["cut_type"] else ""
        L.append(f"### Shot {sh['index']}: {fmt_ts(sh['start'], True)}-{fmt_ts(sh['end'], True)} "
                 f"({sh['length']} s){cut}")
        L.append(f"- Said: {sh['said'] or '_-_'}")
        if sh["on_screen_text"]:
            more = f" (+{sh['on_screen_text_more']} smaller lines in analysis.json)" if sh.get("on_screen_text_more") else ""
            L.append(f"- Screen: {' | '.join(sh['on_screen_text'])}{more}")
        if sh["frames"]:
            L.append(f"- Frames: {', '.join('`' + f + '`' for f in sh['frames'])}")
        L.append("")
    L += ["## Calls to action", ""]
    L += [f"- {c['kind']}: \"{c['match']}\"" for c in a["ctas"]] or ["- none found"]
    L += ["", "## Claim candidates (seller claims until verified)", ""]
    L += [f"- {c}" for c in a["claim_candidates"]] or ["- none found"]
    L += ["", "## Tools, repos and links mentioned (for read-only vetting; do NOT clone or install)", ""]
    L += [f"- [{x['kind']}] {x['value']} ({x['source']} at {fmt_ts(x['t'], True)})" for x in a["mentions"]] \
        or ["- none found"]
    L += ["", "## Transcript (segments)", ""]
    L += [f"[{fmt_ts(s['start'], True)}] {s['text']}" for s in a["transcript"]["segments"]] or ["_No speech found._"]
    L += ["", "## How to use this", "",
          f"1. Open {', '.join('`' + c + '`' for c in a['sheets']['contact'])} (each frame is labelled "
          f"time + shot) and `{a['sheets']['hook']}`.",
          "2. Read the timeline: what is said vs what is shown in each shot.",
          "3. Run `python -m hooklab learn <this folder> --creator ... --topic ...` to draft a reel note, "
          "then fill in the impression and verify the claims.",
          "4. Anything not in the transcript, OCR or frames is NOT verified. Say so."]
    return "\n".join(L) + "\n"
