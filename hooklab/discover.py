"""Find a channel's top videos with yt-dlp, metadata only (no downloads)."""
import csv
import statistics
import subprocess
import sys
from pathlib import Path

FIELDS = ["channel", "url", "id", "views", "outlier", "duration", "upload_date", "title"]
PRINT_FMT = "%(id)s\t%(view_count)s\t%(duration)s\t%(upload_date)s\t%(title)s"


def channel_url(channel, tab="shorts"):
    """Accept @handle, a channel URL, or a bare name. Return the tab URL."""
    c = channel.strip().rstrip("/")
    if c.startswith("@"):
        c = "https://www.youtube.com/" + c
    elif not c.startswith("http"):
        c = "https://www.youtube.com/@" + c
    for suffix in ("/shorts", "/videos", "/streams"):
        if c.endswith(suffix):
            c = c[: -len(suffix)]
    return f"{c}/{tab}"


def _num(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None  # yt-dlp prints NA when a field is missing


def parse_line(line, channel=""):
    """Parse one tab-separated yt-dlp --print line. Return a dict or None."""
    parts = line.rstrip("\n").split("\t", 4)
    if len(parts) < 5 or len(parts[0]) != 11:
        return None
    vid, views, dur, date, title = parts
    kind = "shorts" if (_num(dur) or 0) <= 60 else "watch?v="
    url = (f"https://www.youtube.com/shorts/{vid}" if kind == "shorts"
           else f"https://www.youtube.com/watch?v={vid}")
    return {"channel": channel, "url": url, "id": vid, "views": _num(views),
            "duration": _num(dur), "upload_date": date if date != "NA" else "",
            "title": title}


def rank(rows, top):
    """Add `outlier` = views / channel median and return the best `top` rows.

    Outlier beats raw views: a video that beats its own channel's normal is
    a better hook signal than a big channel's average video.
    """
    with_views = [r for r in rows if r["views"] is not None]
    if not with_views:
        return []
    med = statistics.median(r["views"] for r in with_views) or 1
    for r in with_views:
        r["outlier"] = round(r["views"] / med, 2)
    with_views.sort(key=lambda r: (r["outlier"], r["views"]), reverse=True)
    return with_views[:top]


def fetch_channel(channel, tab="shorts", sample=60, runner=subprocess.run):
    url = channel_url(channel, tab)
    cmd = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "--playlist-end",
           str(sample), "--print", PRINT_FMT, "--", url]
    r = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    rows = [p for p in (parse_line(l, channel) for l in r.stdout.splitlines()) if p]
    err = "" if rows else (r.stderr or "no rows")[-300:]
    return rows, err


def discover(channels, out_dir, tab="shorts", top=10, sample=60, runner=subprocess.run):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    queue, errors = [], []
    for ch in channels:
        rows, err = fetch_channel(ch, tab, sample, runner)
        if err:
            errors.append((ch, err))
            continue
        queue.extend(rank(rows, top))
    with open(out / "queue.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(queue)
    return queue, errors
