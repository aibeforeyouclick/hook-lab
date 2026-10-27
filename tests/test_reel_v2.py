"""Offline tests for watch v2 (analyze), mention extraction and learn. No network, no
Whisper model, no OCR model needed. The end-to-end test is skipped without ffmpeg."""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from hooklab import analyze as A
from hooklab import extract as X
from hooklab import learn as L
from hooklab import pipeline as P

SHOWINFO = """[Parsed_showinfo_1 @ 0] n:   0 pts:      0 pts_time:0.0333
[Parsed_metadata_1 @ 0] lavfi.scene_score=0.900000
[Parsed_metadata_1 @ 0] frame:1    pts:2   pts_time:1.0
[Parsed_metadata_1 @ 0] lavfi.scene_score=0.010000
[Parsed_metadata_1 @ 0] frame:2    pts:3   pts_time:2.0
[Parsed_metadata_1 @ 0] lavfi.scene_score=0.150000
[Parsed_metadata_1 @ 0] frame:3    pts:4   pts_time:2.2
[Parsed_metadata_1 @ 0] lavfi.scene_score=0.400000
[Parsed_metadata_1 @ 0] frame:4    pts:5   pts_time:5.0
[Parsed_metadata_1 @ 0] lavfi.scene_score=0.130000
"""

AUDIO = """[silencedetect @ 0] silence_start: -0.01
[Parsed_ebur128_1 @ 0] t: 0.1  TARGET:-23 LUFS    M:-120.7 S:-120.7     I: -70.0 LUFS       LRA:   0.0 LU
[silencedetect @ 0] silence_end: 0.8 | silence_duration: 0.81
[Parsed_ebur128_1 @ 0] t: 1.0  TARGET:-23 LUFS    M: -20.0 S:-22.0     I: -21.0 LUFS       LRA:   1.0 LU
[Parsed_ebur128_1 @ 0] t: 3.0  TARGET:-23 LUFS    M: -30.0 S:-25.0     I: -21.0 LUFS       LRA:   1.0 LU
[silencedetect @ 0] silence_start: 9.5
[Parsed_ebur128_1 @ 0] Summary:

  Integrated loudness:
    I:         -18.5 LUFS
    Threshold: -28.5 LUFS

  Loudness range:
    LRA:         4.2 LU
"""

WHISPER = {"language": "en", "segments": [
    {"start": 0.4, "end": 2.0, "text": " This is the number one repo", "no_speech_prob": 0.01,
     "words": [{"word": " This", "start": 0.4, "end": 0.6, "probability": 0.9},
               {"word": " is", "start": 0.6, "end": 0.7, "probability": 0.9},
               {"word": " the", "start": 0.7, "end": 0.8, "probability": 0.9},
               {"word": " number", "start": 0.8, "end": 1.1, "probability": 0.9},
               {"word": " one", "start": 1.1, "end": 1.3, "probability": 0.9},
               {"word": " repo.", "start": 1.3, "end": 2.0, "probability": 0.9}]},
    {"start": 4.0, "end": 6.0, "text": " I made $10k with it. Comment REPO for the link", "no_speech_prob": 0.02},
    {"start": 20.0, "end": 22.0, "text": " Thanks for watching!", "no_speech_prob": 0.95},
]}


def fake_analysis(video_id="abc123def456"):
    return {
        "schema": A.SCHEMA, "source": "C:/x/clip.mp4", "video_file": "clip.mp4", "video_id": video_id,
        "media": {"duration": 30.0, "width": 360, "height": 640, "orientation": "vertical", "fps": 30},
        "language": "en", "settings": {"whisper_model": "small", "ocr": True},
        "pacing": {"shots": 20, "visual_changes": 19, "hard_cuts": 3, "changes_per_second": 0.63,
                   "avg_shot_seconds": 1.5, "median_shot_seconds": 1.4, "longest_shot_seconds": 3.0,
                   "first_visual_change": 0.9, "time_to_first_word": 0.4, "first_on_screen_text_frame": 0.5,
                   "words": 90, "words_per_minute": 200, "max_seconds_without_visual_change": 3.0,
                   "changes_per_10s": 6.3, "words_per_second": 3.3, "cut_times": [0.9]},
        "hook": {"seconds": 3, "said": "This is the number one repo", "said_first_5s": "This is the number one repo",
                 "on_screen_text": ["github.com/acme/tool"], "visual_changes": 2, "first_text_change": 1.5,
                 "hook_type": {"primary": "RANKING_CLAIM", "tags": ["RANKING_CLAIM"]}},
        "audio": {"label": "speech over a music/sound bed (heuristic)"},
        "shots": [{"index": 1, "start": 0.0, "end": 1.5, "length": 1.5, "said": "This is the number one repo",
                   "on_screen_text": ["github.com/acme/tool"], "frames": []}],
        "ctas": [{"kind": "comment-keyword", "match": "comment repo"}],
        "claim_candidates": ["I made $10k with it."],
        "mentions": [{"kind": "github", "value": "github.com/acme/tool", "source": "screen", "t": 1.0},
                     {"kind": "tool", "value": "Claude Code", "source": "speech", "t": 5.0}],
        "notes": [],
    }


class TestShots(unittest.TestCase):
    def test_parse_scene_scores(self):
        s = A.parse_scene_scores(SHOWINFO)
        self.assertEqual(s[0], (0.0333, 0.9))
        self.assertEqual(len(s), 5)

    def test_pick_cuts_ignores_fade_in_and_merges_bursts(self):
        cuts = A.pick_cuts(A.parse_scene_scores(SHOWINFO), threshold=0.12, min_gap=0.5)
        self.assertEqual(cuts, [(2.2, 0.4), (5.0, 0.13)])

    def test_shots_from_cuts(self):
        shots = A.shots_from_cuts([(2.2, 0.4), (5.0, 0.13)], 8.0)
        self.assertEqual([(s["start"], s["end"]) for s in shots], [(0.0, 2.2), (2.2, 5.0), (5.0, 8.0)])
        self.assertEqual(shots[1]["cut_type"], "hard")
        self.assertEqual(shots[2]["cut_type"], "change")
        self.assertIsNone(shots[0]["cut_type"])

    def test_frame_times_middle_of_shot_and_cap(self):
        shots = A.shots_from_cuts([(2.0, 0.5)], 10.0)
        t = A.frame_times(shots, every=3.0, max_frames=40)
        self.assertEqual(t[0], 1.0)  # middle of the 2 s shot
        self.assertEqual(len(t), 4)  # 8 s shot -> 3 frames
        long = A.shots_from_cuts([], 600.0)
        self.assertLessEqual(len(A.frame_times(long, 3.0, 40)), 40)

    def test_parse_probe(self):
        info = A.parse_probe({"format": {"duration": "12.5"}, "streams": [
            {"codec_type": "video", "width": 360, "height": 640, "r_frame_rate": "30000/1001"},
            {"codec_type": "audio"}]})
        self.assertEqual(info["orientation"], "vertical")
        self.assertTrue(info["has_audio"])
        self.assertAlmostEqual(info["fps"], 29.97)


class TestTranscriptAudio(unittest.TestCase):
    def test_words_from_whisper(self):
        w = A.words_from_whisper(WHISPER)
        self.assertEqual(w[0], {"w": "This", "start": 0.4, "end": 0.6, "p": 0.9})
        self.assertEqual(w[6]["w"], "I made $10k with it. Comment REPO for the link")  # segment fallback
        self.assertFalse(any("Thanks for watching" in x["w"] for x in w))  # hallucination dropped
        self.assertEqual(A.text_between(w, 0, 1.0), "This is the number")

    def test_speech_intervals(self):
        w = A.words_from_whisper(WHISPER)
        self.assertEqual(A.speech_intervals(w), [(0.4, 2.0), (4.0, 6.0)])

    def test_parse_audio(self):
        a = A.parse_audio(AUDIO)
        self.assertEqual(a["integrated_lufs"], -18.5)
        self.assertEqual(a["lra"], 4.2)
        self.assertEqual(a["silences"], [(0.0, 0.8), (9.5, None)])
        self.assertEqual(len(a["momentary"]), 3)

    def test_audio_labels(self):
        scan = {"momentary": [(t / 10, -25.0) for t in range(100)], "silences": [], "integrated_lufs": -20, "lra": 3}
        speech = [(0.0, 4.0)]
        self.assertIn("music/sound bed", A.audio_features(scan, speech, 10.0)["label"])
        quiet = {**scan, "momentary": [(t / 10, -25.0 if t < 40 else -60.0) for t in range(100)]}
        self.assertIn("little or no background", A.audio_features(quiet, speech, 10.0)["label"])
        self.assertIn("music/sound only", A.audio_features(scan, [], 10.0)["label"])
        self.assertIn("speech unknown", A.audio_features(scan, [], 10.0, transcribed=False)["label"])
        nonstop = [(0.0, 4.9), (5.1, 10.0)]  # no pause >= 0.6 s: cannot tell
        self.assertIn("undetermined", A.audio_features(scan, nonstop, 10.0)["label"])

    def test_whisper_cmd_words(self):
        cmd = P.whisper_cmd(Path("v.mp4"), "small", Path("t"), "auto", words=True)
        self.assertIn("--word_timestamps", cmd)
        self.assertNotIn("--language", cmd)
        self.assertNotIn("--word_timestamps", P.whisper_cmd(Path("v.mp4"), "base.en", Path("t")))


class TestScreenHookPacing(unittest.TestCase):
    def test_caption_vs_text(self):
        lines = [{"text": "number one", "score": 0.9, "y": 5}, {"text": "github.com/acme/tool", "score": 0.9, "y": 9}]
        out = A.classify_screen_text(lines, A.norm("this is the number one repo"))
        self.assertEqual([x["kind"] for x in out], ["caption", "text"])

    def test_hook_and_pacing(self):
        words = A.words_from_whisper(WHISPER)
        shots = A.shots_from_cuts([(2.2, 0.4), (5.0, 0.13)], 30.0)
        hook_frames = [{"t": 0.05, "ocr": [{"text": "Number one", "kind": "text"}]},
                       {"t": 1.5, "ocr": [{"text": "Number one", "kind": "text"},
                                          {"text": "GitHub repo", "kind": "text"}]}]
        h = A.hook_window(words, shots, [], hook_frames=hook_frames)
        self.assertEqual(h["said"], "This is the number one repo.")
        self.assertEqual(h["first_text_change"], 1.5)
        self.assertEqual(h["on_screen_text"], ["Number one", "GitHub repo"])
        self.assertEqual(h["visual_changes"], 1)
        self.assertEqual(h["hook_type"]["primary"], "RANKING_CLAIM")
        p = A.pacing(shots, words, 30.0)
        self.assertEqual(p["time_to_first_word"], 0.4)
        self.assertEqual(p["first_visual_change"], 2.2)
        self.assertEqual(p["shots"], 3)
        self.assertAlmostEqual(p["changes_per_second"], 0.067, places=3)

    def test_caption_without_spaces(self):
        out = A.classify_screen_text([{"text": "ANDITFEELS", "score": 0.9, "y": 1}], "and it feels illegal")
        self.assertEqual(out[0]["kind"], "caption")

    def test_collect_text_merges_ocr_variants_and_keeps_big_lines(self):
        frames = [{"ocr": [{"text": "GITHUB TRENDING", "kind": "text", "h": 30},
                           {"text": "tiny footer", "kind": "text", "h": 5},
                           {"text": "said word", "kind": "caption", "h": 40}]},
                  {"ocr": [{"text": "GITHU8 TRENDNG", "kind": "text", "h": 30},
                           {"text": "Second headline", "kind": "text", "h": 25}]}]
        texts, more = A.collect_text(frames, limit=2)
        self.assertEqual(texts, ["GITHUB TRENDING", "Second headline"])
        self.assertEqual(more, 1)

    def test_first_text_change_ignores_ocr_jitter(self):
        hf = [{"t": 0.05, "ocr": [{"text": "Number one GitHub repo"}]},
              {"t": 0.5, "ocr": [{"text": "Number one GitHu8 repo"}]},
              {"t": 1.0, "ocr": [{"text": "It changes everything"}]}]
        self.assertEqual(A.first_text_change(hf), 1.0)

    def test_dense_hook_times(self):
        self.assertEqual(len(A.HOOK_TIMES), 12)  # 4x3 sheet, 4 fps
        self.assertEqual(A.HOOK_TIMES[1], 0.25)
        self.assertEqual(A.HOOK_TIMES[-1], 2.75)

    def test_max_gap_and_rates(self):
        shots = A.shots_from_cuts([(1.0, 0.5), (7.5, 0.5)], 10.0)
        p = A.pacing(shots, [], 10.0)
        self.assertEqual(p["max_seconds_without_visual_change"], 6.5)
        self.assertEqual(p["cut_times"], [1.0, 7.5])
        self.assertEqual(p["changes_per_10s"], 2.0)

    def test_transcript_quality(self):
        good = [{"w": "hi", "p": 0.9}] * 10
        bad = [{"w": "♪", "p": 0.9}] * 3 + [{"w": "x", "p": 0.1}] * 3 + good[:4]
        self.assertFalse(any("UNRELIABLE" in n for n in A.transcript_quality(good, "small", "en")))
        self.assertTrue(any("UNRELIABLE" in n for n in A.transcript_quality(bad, "small", "en")))
        self.assertTrue(any("English-only" in n for n in A.transcript_quality(good, "small.en", "en")))

    def test_ctas_and_claims(self):
        kinds = {c["kind"] for c in A.find_ctas("Comment REPO and follow for more. Link in bio")}
        self.assertEqual(kinds, {"comment-keyword", "follow/subscribe", "link-in-bio"})
        claims = A.claim_sentences(A.words_from_whisper(WHISPER))
        self.assertEqual(len(claims), 1)
        self.assertIn("$10k", claims[0])


class TestExtract(unittest.TestCase):
    def test_screen_mentions(self):
        m = X.extract_mentions([], [(1.0, "github.com/acme-ai/acme"), (1.5, "口acme-ai/acme"),
                                    (2.0, "anthropics/claude-plugins-official"), (3.0, "Try https://example.ai/x now")])
        vals = {(x["kind"], x["value"]) for x in m}
        self.assertIn(("github", "github.com/acme-ai/acme"), vals)
        self.assertIn(("repo?", "anthropics/claude-plugins-official"), vals)
        self.assertIn(("url", "https://example.ai/x"), vals)
        self.assertNotIn(("repo?", "ai/acme"), vals)
        self.assertEqual(sum(1 for k, v in vals if v.endswith("acme-ai/acme")), 1)  # merged into github

    def test_speech_mentions(self):
        words = [(i * 0.3, w) for i, w in enumerate(
            "this repo is called Super Handy Tool, go to acme dot ai and use Claude Code with ElevenLabs".split())]
        m = X.extract_mentions(words, [])
        vals = {(x["kind"], x["value"]) for x in m}
        self.assertIn(("called", "Super Handy Tool"), vals)
        self.assertIn(("domain", "acme.ai"), vals)
        self.assertIn(("tool", "Claude Code"), vals)
        self.assertIn(("tool", "ElevenLabs"), vals)
        self.assertNotIn(("tool", "Claude"), vals)  # covered by Claude Code
        self.assertTrue(all(x["source"] == "speech" for x in m))

    def test_terminal_paths_and_app_ids_are_not_repos(self):
        m = X.extract_mentions([], [(1.0, "packages/core apps/calendly-copy Read.paul/STATE.md known/assetlinks.json"),
                                    (2.0, "com.calendly.app.dev"), (3.0, "a tool called conputer-use 4")])
        self.assertEqual(m, [])

    def test_no_false_repo_from_numbers_or_speech(self):
        self.assertEqual(X.mentions_in("24/7 support and 1/2 price", "screen", 0), [])
        self.assertEqual([x for x in X.mentions_in("either/or", "speech", 0) if x["kind"] == "repo?"], [])


class TestLearn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.reels = root / "reels"
        self.reels.mkdir()
        self.log0 = "# Reel log\n| # | Date | Creator / page | Topic | Verdict | Note |\n|---|---|---|---|---|---|\n" \
                    "| 14 | 10-19 | Example | avatar | low | reels/02-ai-influencer-process/ |"  # no trailing newline
        (self.reels / "00-log.md").write_text(self.log0, encoding="utf-8")
        (self.reels / "01-old.md").write_text("old note", encoding="utf-8")
        (self.reels / "02-folder").mkdir()
        (self.reels / "99-playbook.md").write_text("playbook", encoding="utf-8")
        self.adir = root / "analysis"
        self.adir.mkdir()
        (self.adir / "analysis.json").write_text(json.dumps(fake_analysis()), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_helpers(self):
        self.assertEqual(L.next_log_number(self.log0), 15)
        self.assertEqual(L.next_file_prefix(self.reels), 3)
        self.assertEqual(L.slug("Hello, World! 2"), "hello-world-2")
        self.assertEqual(L.short("a b c d", 2), "a b ...")

    def test_proposals_are_c_and_reference_playbook(self):
        props = L.propose(fake_analysis())
        self.assertTrue(props)
        self.assertTrue(all(lab == "C" for lab, _ in props))
        text = " ".join(t for _, t in props)
        for ref in ("#1", "#2", "#4", "#7", "fast visual pacing", "music/sound bed", "words per minute", "5 s max"):
            self.assertIn(ref, text)

    def test_learn_appends_and_never_overwrites(self):
        res = L.learn(self.adir, self.reels, creator="Acme Creator", topic="Number one repo",
                      today=date(2026, 10, 21))
        self.assertTrue(res["ok"], res["messages"])
        note = self.reels / "03-acme-creator-number-one-repo.md"
        self.assertEqual(res["note"], note)
        text = note.read_text(encoding="utf-8")
        self.assertIn("# Reel 15: Acme Creator", text)
        self.assertIn("hooklab-analysis: abc123def456", text)
        self.assertIn("## Impression", text)
        self.assertIn("- max_gap_s: 3.0", text)
        log = (self.reels / "00-log.md").read_text(encoding="utf-8")
        self.assertTrue(log.startswith(self.log0 + "\n"))  # old content kept byte for byte
        self.assertIn("| 15 | 10-21 | Acme Creator | Number one repo |", log)
        self.assertEqual((self.reels / "99-playbook.md").read_text(encoding="utf-8"), "playbook")
        self.assertEqual((self.reels / "01-old.md").read_text(encoding="utf-8"), "old note")
        props = (self.reels / L.PROPOSALS).read_text(encoding="utf-8")
        self.assertIn("- [C] Supports #1", props)
        queue = (self.reels / L.QUEUE).read_text(encoding="utf-8")
        self.assertIn("| github | github.com/acme/tool | screen |", queue)
        self.assertNotIn("Claude Code", queue)  # known tools stay in the note, not the vetting queue
        # same video again: refused, nothing changes
        before = log
        res2 = L.learn(self.adir, self.reels, creator="Acme Creator")
        self.assertFalse(res2["ok"])
        self.assertEqual((self.reels / "00-log.md").read_text(encoding="utf-8"), before)

    def test_second_video_appends_to_proposals(self):
        L.learn(self.adir, self.reels, creator="A", topic="one", today=date(2026, 10, 21))
        (self.adir / "analysis.json").write_text(json.dumps(fake_analysis("ffff00001111")), encoding="utf-8")
        res = L.learn(self.adir, self.reels, creator="B", topic="two", today=date(2026, 10, 21))
        self.assertEqual(res["number"], 16)
        self.assertTrue((self.reels / "04-b-two.md").exists())
        props = (self.reels / L.PROPOSALS).read_text(encoding="utf-8")
        self.assertEqual(props.count("# Playbook proposals"), 1)
        self.assertIn("reel 15", props)
        self.assertIn("reel 16", props)

    def test_append_keeps_crlf(self):
        f = self.reels / "crlf.md"
        f.write_bytes(b"a\r\nb\r\n")
        L._append(f, "c\nd\n")
        self.assertEqual(f.read_bytes(), b"a\r\nb\r\nc\r\nd\r\n")

    def test_dry_run_writes_nothing(self):
        res = L.learn(self.adir, self.reels, creator="X", dry_run=True)
        self.assertTrue(res["ok"])
        self.assertEqual((self.reels / "00-log.md").read_text(encoding="utf-8"), self.log0)
        self.assertFalse((self.reels / L.PROPOSALS).exists())
        self.assertEqual(len(list(self.reels.glob("03-*"))), 0)

    def test_missing_analysis(self):
        res = L.learn(Path(self.tmp.name) / "nope", self.reels)
        self.assertFalse(res["ok"])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class TestAnalyzeEndToEnd(unittest.TestCase):
    def test_synthetic_video(self):
        with tempfile.TemporaryDirectory() as d:
            v = Path(d) / "cuts.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x180:rate=10",
                            "-f", "lavfi", "-i", "color=c=blue:duration=3:size=320x180:rate=10",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                            "-map", "[v]", "-map", "2:a", "-shortest", str(v)], check=True)
            out = Path(d) / "out"
            a = A.analyze(v, out, transcribe=False, use_ocr=False)
            self.assertGreaterEqual(a["pacing"]["shots"], 2)
            self.assertTrue(any(abs(s["start"] - 3.0) < 0.3 for s in a["shots"][1:]))
            self.assertTrue((out / "analysis.json").exists())
            self.assertTrue((out / "sheets" / "contact_01.jpg").exists())
            self.assertEqual(a["sheets"]["contact"], ["sheets/contact_01.jpg"])
            self.assertTrue((out / "sheets" / "hook.jpg").exists())
            self.assertIn("speech unknown", a["audio"]["label"])
            md = (out / "analysis.md").read_text(encoding="utf-8")
            self.assertIn("## Timeline, shot by shot", md)
            json.loads((out / "analysis.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
