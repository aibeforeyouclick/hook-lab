"""Offline tests (stdlib unittest). Run:  python -m unittest discover -s tests -v"""
import csv
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hooklab import classify as C
from hooklab import discover as D
from hooklab import pipeline as P
from hooklab import report as R
from hooklab import watch as W

# The three real hooks from the first manual run (see docs/first-run.md).
REAL = {
    "This is the number one GitHub repo of the day, and it changes everything when it comes to content production.":
        ("RANKING_CLAIM", {"BIG_PROMISE"}),
    "I can't stand people that only want to create faceless social media content. I mean, it's not like AI can create animated videos just like this that actually go viral.":
        ("HOT_TAKE", set()),
    "This is the number one trending GitHub repo of the day. It's called super handy tool and":
        ("RANKING_CLAIM", set()),
}


class TestClassify(unittest.TestCase):
    def test_real_hooks(self):
        for text, (primary, extra) in REAL.items():
            r = C.classify(text)
            self.assertEqual(r["primary"], primary, text)
            self.assertTrue(extra <= set(r["tags"]), (text, r["tags"]))

    def test_empty_is_no_speech(self):
        self.assertEqual(C.classify("")["primary"], "NO_SPEECH")
        self.assertEqual(C.classify(None)["primary"], "NO_SPEECH")

    def test_other(self):
        self.assertEqual(C.classify("Welcome back to the channel")["primary"], "OTHER")

    def test_question_and_list(self):
        self.assertIn("QUESTION", C.classify("Why does nobody use this?")["tags"])
        self.assertIn("NUMBERED_LIST", C.classify("Here are 5 tools you need")["tags"])

    def test_personal_proof(self):
        self.assertEqual(C.classify("I tried 100 repos for Claude")["primary"], "PERSONAL_PROOF")


class TestDiscover(unittest.TestCase):
    def test_channel_url(self):
        self.assertEqual(D.channel_url("@abc"), "https://www.youtube.com/@abc/shorts")
        self.assertEqual(D.channel_url("abc", "videos"), "https://www.youtube.com/@abc/videos")
        self.assertEqual(D.channel_url("https://www.youtube.com/@abc/videos/", "shorts"),
                         "https://www.youtube.com/@abc/shorts")

    def test_parse_line(self):
        r = D.parse_line("abcdefghijk\t1700\t45\t20261010\tNumber one repo\n", "@x")
        self.assertEqual(r["url"], "https://www.youtube.com/shorts/abcdefghijk")
        self.assertEqual(r["views"], 1700)
        long = D.parse_line("abcdefghijk\t5\t600\tNA\tLong one")
        self.assertIn("watch?v=", long["url"])
        self.assertEqual(long["upload_date"], "")

    def test_parse_line_rejects_garbage(self):
        self.assertIsNone(D.parse_line("not a row"))
        self.assertIsNone(D.parse_line("short\t1\t1\t1\ttitle"))  # id not 11 chars

    def test_missing_views(self):
        r = D.parse_line("abcdefghijk\tNA\t30\tNA\tT")
        self.assertIsNone(r["views"])
        self.assertEqual(D.rank([r], 5), [])

    def test_rank_by_outlier_not_views(self):
        rows = [{"views": v, "id": str(v)} for v in (100, 100, 100, 100, 900)]
        top = D.rank(rows, 2)
        self.assertEqual(top[0]["views"], 900)
        self.assertEqual(top[0]["outlier"], 9.0)
        self.assertEqual(len(top), 2)

    def test_discover_with_fake_runner(self):
        lines = "\n".join(f"{chr(97 + i) * 11}\t{(i + 1) * 100}\t30\t20261001\tTitle {i}" for i in range(6))

        def fake(cmd, **kw):
            self.assertIn("--flat-playlist", cmd)
            return SimpleNamespace(stdout=lines, stderr="", returncode=0)

        with tempfile.TemporaryDirectory() as d:
            queue, errors = D.discover(["@x"], d, top=3, runner=fake)
            self.assertEqual(len(queue), 3)
            self.assertEqual(errors, [])
            with open(Path(d) / "queue.csv", newline="", encoding="utf-8-sig") as fh:
                self.assertEqual(len(list(csv.DictReader(fh))), 3)

    def test_discover_reports_failure(self):
        def fake(cmd, **kw):
            return SimpleNamespace(stdout="", stderr="ERROR: not found", returncode=1)

        with tempfile.TemporaryDirectory() as d:
            queue, errors = D.discover(["@nope"], d, runner=fake)
            self.assertEqual(queue, [])
            self.assertEqual(errors[0][0], "@nope")


class TestPipeline(unittest.TestCase):
    def test_hook_from_segments(self):
        segs = [{"start": 0.4, "text": " Number one repo."}, {"start": 3.0, "text": " It is great."},
                {"start": 7.0, "text": " later"}]
        text, start, flag = P.hook_from_segments(segs)
        self.assertEqual(text, "Number one repo. It is great.")
        self.assertEqual(start, 0.4)
        self.assertEqual(flag, "")

    def test_whisper_cmd_language(self):
        en = P.whisper_cmd(Path("v.mp4"), "base.en", Path("t"))
        self.assertEqual(en[en.index("--language") + 1], "en")
        auto = P.whisper_cmd(Path("v.mp4"), "small", Path("t"), "auto")
        self.assertNotIn("--language", auto)
        self.assertEqual(auto[auto.index("--model") + 1], "small")

    def test_music_hallucination_flagged(self):
        _, _, flag = P.hook_from_segments([{"start": 0, "text": "Thanks for watching!"}])
        self.assertEqual(flag, "no-speech?")

    def test_no_speech_prob_flagged(self):
        _, _, flag = P.hook_from_segments([{"start": 0, "text": "hmm", "no_speech_prob": 0.9}])
        self.assertEqual(flag, "no-speech?")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_strip_makes_five_frame_image(self):
        with tempfile.TemporaryDirectory() as d:
            v = Path(d) / "t.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc=duration=6:size=320x180:rate=10", str(v)], check=True)
            out = P.strip(v, Path(d))
            self.assertTrue(out.endswith("t_strip.jpg"))
            w = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width",
                                "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
            self.assertEqual(w, str(360 * 5))


class TestReport(unittest.TestCase):
    def rows(self):
        base = dict(channel="@x", title="t", hook_text="h", speech_start="0.5", words=5, strip="", flag="")
        return [
            dict(base, url="u1", views="900", outlier="9.0", primary="RANKING_CLAIM", tags="RANKING_CLAIM"),
            dict(base, url="u2", views="100", outlier="1.0", primary="HOT_TAKE", tags="HOT_TAKE"),
            dict(base, url="u3", views="", outlier="", primary="DOWNLOAD_FAILED", tags="", flag="err"),
        ]

    def test_build(self):
        text = R.build(self.rows())
        self.assertIn("Small sample", text)
        self.assertIn("| RANKING_CLAIM | 1 | 9.00 |", text)
        self.assertLess(text.index("RANKING_CLAIM"), text.index("HOT_TAKE"))
        self.assertIn("Needs a look", text)
        self.assertIn("u3", text)

    def test_write_report(self):
        with tempfile.TemporaryDirectory() as d:
            with open(Path(d) / "hooks.csv", "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=P.OUT_FIELDS, extrasaction="ignore")
                w.writeheader()
                w.writerows(self.rows())
            self.assertTrue(R.write_report(d).exists())


class TestWatch(unittest.TestCase):
    def test_fmt_ts(self):
        self.assertEqual(W.fmt_ts(75.9), "01:15")
        self.assertEqual(W.fmt_ts(-3), "00:00")

    def test_plan_step_caps_frames(self):
        self.assertEqual(W.plan_step(60, 3, 48), 3)
        self.assertAlmostEqual(W.plan_step(300, 3, 48), 6.25)

    def test_plan_sheets(self):
        sheets = W.plan_sheets(150, 3, 4, 3)  # 50 frames -> 5 sheets of up to 12
        self.assertEqual(len(sheets), 5)
        self.assertEqual(sum(n for _, _, n in sheets), 50)
        self.assertEqual(sheets[1][0], 36)

    def test_transcript_md(self):
        t = W.transcript_md([{"start": 0, "text": " Hi"}, {"start": 65, "text": " "}, {"start": 70, "text": " Bye"}])
        self.assertEqual(t, "[00:00] Hi\n[01:10] Bye")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_watch_local_file_without_whisper(self):
        with tempfile.TemporaryDirectory() as d:
            v = Path(d) / "t.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc=duration=8:size=320x180:rate=10", str(v)], check=True)
            md = W.watch(str(v), Path(d) / "out", model="tiny", basic=True, transcribe=False)
            text = md.read_text(encoding="utf-8")
            self.assertIn("# Watch report", text)
            self.assertTrue(list((Path(d) / "out" / "sheets").glob("sheet_*.jpg")))


class TestOptionSeparator(unittest.TestCase):
    """User-supplied URLs must come after `--` so yt-dlp never reads them as options."""

    def test_discover_puts_url_after_separator(self):
        seen = []

        def fake(cmd, **kw):
            seen.append(cmd)
            return SimpleNamespace(stdout="", stderr="", returncode=1)

        D.fetch_channel("--exec=evil", runner=fake)
        cmd = seen[0]
        self.assertIn("--", cmd)
        self.assertEqual(cmd.index("--"), len(cmd) - 2)

    def test_download_and_watch_put_url_after_separator(self):
        seen = []
        orig_p, orig_w = P._run, W._run
        try:
            for mod in (P, W):
                mod._run = lambda cmd, seen=seen: seen.append(cmd) or SimpleNamespace(returncode=1, stderr="", stdout="")
            with tempfile.TemporaryDirectory() as d:
                P.download("--exec=evil", "vid", Path(d))
                W.fetch("--exec=evil", Path(d))
        finally:
            P._run, W._run = orig_p, orig_w
        self.assertGreaterEqual(len(seen), 3)  # download tries twice (retry), watch once
        for cmd in seen:
            self.assertEqual(cmd[-2:], ["--", "--exec=evil"])


if __name__ == "__main__":
    unittest.main()
