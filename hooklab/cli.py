"""Command line: python -m hooklab <command>."""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .classify import classify
from .discover import discover
from .pipeline import doctor, run_queue
from .report import write_report
from .watch import watch


def read_channels(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hooklab", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check ffmpeg, yt-dlp and whisper are available")

    c = sub.add_parser("classify", help="classify a hook sentence (offline)")
    c.add_argument("text")

    d = sub.add_parser("discover", help="list each channel's top videos (metadata only)")
    d.add_argument("channels", help="text file: one @handle or channel URL per line")
    d.add_argument("--tab", choices=["shorts", "videos"], default="shorts")
    d.add_argument("--top", type=int, default=10)
    d.add_argument("--sample", type=int, default=60, help="recent videos to rank per channel")
    d.add_argument("--out", default=None)

    r = sub.add_parser("run", help="download, transcribe and strip the videos in a run folder")
    r.add_argument("run_dir")
    r.add_argument("--model", default="base.en", help="whisper model, e.g. small.en for accuracy")
    r.add_argument("--lang", default="en", help="speech language code, or 'auto'. Non-English needs a "
                   "multilingual model, e.g. --model small --lang auto")

    p = sub.add_parser("report", help="write report.md for a run folder")
    p.add_argument("run_dir")

    w = sub.add_parser("watch", help="analyse one video (file or URL): shots, contact sheet, word transcript, "
                       "OCR, audio, pacing -> analysis.md/json")
    w.add_argument("source", help="video URL or path to a local video file")
    w.add_argument("--out", default=None, help="output folder (default watch/<timestamp>)")
    w.add_argument("--model", default="small", help="whisper model; small is multilingual")
    w.add_argument("--lang", default="auto", help="speech language code or 'auto'")
    w.add_argument("--every", type=float, default=3.0, help="seconds between frames")
    w.add_argument("--max-frames", type=int, default=48, help="frame cap (v2 caps at 40)")
    w.add_argument("--threshold", type=float, default=None,
                   help="scene-change threshold 0-1 (default 0.12; hard cuts are >= 0.30)")
    w.add_argument("--no-ocr", action="store_true", help="skip on-screen text extraction")
    w.add_argument("--no-transcript", action="store_true", help="skip Whisper (fast, visuals only)")
    w.add_argument("--basic", action="store_true", help="v1 output: fixed-step sheets + watch.md only")

    l = sub.add_parser("learn", help="turn a watch analysis into a draft reel note + log row "
                       "(append only)")
    l.add_argument("analysis_dir", help="folder with analysis.json (the watch --out folder)")
    l.add_argument("--creator", default="unknown creator")
    l.add_argument("--topic", default=None, help="short topic; default = first words of the hook")
    l.add_argument("--url", default=None, help="original link, if any")
    l.add_argument("--reels", default="reels", help="reels knowledge-base folder")
    l.add_argument("--dry-run", action="store_true", help="print what would be written, write nothing")

    a = sub.add_parser("all", help="discover + run + report in one go")
    a.add_argument("channels")
    a.add_argument("--tab", choices=["shorts", "videos"], default="shorts")
    a.add_argument("--top", type=int, default=8)
    a.add_argument("--sample", type=int, default=60)
    a.add_argument("--model", default="base.en")
    a.add_argument("--lang", default="en")
    a.add_argument("--out", default=None)

    args = ap.parse_args(argv)

    if args.cmd == "doctor":
        bad = 0
        for name, ok, detail in doctor():
            print(("INFO " if ok is None else "OK   " if ok else "FAIL ") + f"{name}: {detail}")
            bad += ok is False
        return 1 if bad else 0

    if args.cmd == "watch":
        out = args.out or str(Path("watch") / datetime.now().strftime("%Y%m%d-%H%M%S"))
        print("watch ->", watch(args.source, out, args.model, args.lang, args.every, args.max_frames,
                                basic=args.basic, use_ocr=not args.no_ocr, threshold=args.threshold,
                                transcribe=not args.no_transcript))
        return 0

    if args.cmd == "learn":
        from .learn import learn
        res = learn(args.analysis_dir, args.reels, creator=args.creator, topic=args.topic,
                    url=args.url, dry_run=args.dry_run)
        for line in res["messages"]:
            print(line)
        return 0 if res["ok"] else 1

    if args.cmd == "classify":
        print(classify(args.text))
        return 0

    def run_dir_for(out):
        return Path(out or Path("runs") / datetime.now().strftime("%Y%m%d-%H%M%S"))

    if args.cmd in ("discover", "all"):
        out = run_dir_for(args.out)
        queue, errors = discover(read_channels(args.channels), out, args.tab, args.top, args.sample)
        print(f"{len(queue)} videos queued -> {out / 'queue.csv'}")
        for ch, err in errors:
            print(f"WARN {ch}: {err}", file=sys.stderr)
        if args.cmd == "discover" or not queue:
            return 0 if queue else 1
        run_queue(out, args.model, lang=args.lang)
        print("report ->", write_report(out))
        return 0

    if args.cmd == "run":
        run_queue(args.run_dir, args.model, lang=args.lang)
        print("hooks ->", Path(args.run_dir) / "hooks.csv")
        return 0

    if args.cmd == "report":
        print("report ->", write_report(args.run_dir))
        return 0


if __name__ == "__main__":
    sys.exit(main())
