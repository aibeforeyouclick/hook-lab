# Hook Lab

[![tests](https://github.com/aibeforeyouclick/hook-lab/actions/workflows/tests.yml/badge.svg)](https://github.com/aibeforeyouclick/hook-lab/actions/workflows/tests.yml)
![license](https://img.shields.io/badge/license-MIT-blue)

Find a channel's best-performing short videos, transcribe the first five seconds, classify the hook, and get a report of which hook types beat each channel's normal. Runs on your own machine.

Built for studying AI-video channels, but it works on any public YouTube channel. No API keys, no accounts. The only network traffic is what yt-dlp sends to YouTube.

> **Status: v0.3.0, early.** Small samples give hypotheses, not conclusions; the report says so when a run has fewer than 20 videos. The hook classifier uses English patterns.

## What it does

1. **discover**: lists a channel's recent Shorts/videos (metadata only) and ranks them by *outlier score* = views divided by that channel's median. A video that beats its own channel's normal says more about the hook than a big channel's average video.
2. **run**: downloads the winners (2 at a time, so YouTube does not block you), transcribes them with Whisper, and builds a 5-frame strip (0.5 s, 1 s, 2 s, 3 s, 4 s) so you can see the visual hook at a glance.
3. **report**: classifies each hook (ranking claim, hot take, personal proof, numbered list, big promise, curiosity gap, question, direct address, story open) and writes `report.md` with the types ranked by median outlier score.
4. **watch** (single video): shot detection, word-level transcript, on-screen text, audio and pacing analysis for one video file. See below.

## Requirements

- Python 3.10+ for the tool itself. Whisper needs a Python version your PyTorch build supports; **3.12 is what it is tested with** (the offline test suite also runs on 3.10).
- [ffmpeg](https://ffmpeg.org/) on your `PATH`
- `yt-dlp` and `openai-whisper` (installed by the steps below; the first Whisper run downloads a model)
- Optional: `rapidocr-onnxruntime` and `Pillow` for on-screen text and labelled contact sheets

The tools are run through `python -m`, so their script folders do not need to be on `PATH`.

## Install

Windows (PowerShell):
```
git clone https://github.com/aibeforeyouclick/hook-lab.git
cd hook-lab
powershell -ExecutionPolicy Bypass -File .\install.ps1
```
Linux / macOS:
```
git clone https://github.com/aibeforeyouclick/hook-lab.git
cd hook-lab
sh install.sh
```
Both scripts create `.venv`, install `requirements.txt` there and run `hooklab doctor`. Use the virtualenv's Python afterwards (`.venv/bin/python` or `.venv\Scripts\python.exe`), or activate it. Install ffmpeg yourself if `doctor` reports it missing (`winget install ffmpeg`, `apt install ffmpeg`, `brew install ffmpeg`).

## Quick start

```
python -m hooklab doctor

cp channels.example.txt channels.txt      # Windows: copy ...; then edit: one @handle or URL per line
python -m hooklab all channels.txt --top 8
```

Output lands in `runs/<timestamp>/`: `queue.csv`, `hooks.csv`, `report.md`, `strips/`, `transcripts/`, `videos/`.

Step by step:

```
python -m hooklab discover channels.txt --top 10 --out runs/niche-a
python -m hooklab run runs/niche-a --model small.en
python -m hooklab report runs/niche-a
python -m hooklab classify "This is the number one repo of the day"
```

The last command works offline and prints the matched tags and the primary hook type (here `RANKING_CLAIM`). `--model small.en` is slower but more accurate than the default `base.en`.

**Non-English channels:** the `*.en` models only understand English. Use a multilingual model and let Whisper detect the language: `--model small --lang auto`. The classifier uses English patterns, so most hooks in other languages show as `OTHER`. Read the transcripts and the `strips/` images, or add patterns to `RULES` in `hooklab/classify.py`.

## Watch a single video (v2: learn from any reel)

`watch` works on a video file you already have (or a URL). Text from the picture (OCR) is optional:

```
pip install rapidocr-onnxruntime Pillow   # optional: on-screen text and labelled sheets
python -m hooklab doctor
```

Analyse a video file you already have:

```
python -m hooklab watch "path/to/clip.mp4" --out watch/my-clip --model small --lang auto
```

Hebrew speech: `--lang he`. Visuals only (fast): `--no-transcript`. No OCR: `--no-ocr`. The v1 output (fixed-step sheets + `watch.md`): `--basic`.

Output in the `--out` folder (`watch/` is gitignored):

| File | What it holds |
|---|---|
| `analysis.md` | Hook (0-3 s: said, on-screen text, hook type), pacing table, audio, a shot-by-shot timeline (said vs shown), calls to action, claim candidates, tools/repos/links |
| `analysis.json` | The same, machine-readable (schema `hooklab.analysis/1`), plus every word with its time and every OCR line |
| `sheets/hook.jpg` | 12 frames, 4 per second, over the first 3 s |
| `sheets/contact_NN.jpg` | One frame from the middle of each shot (more in long shots), labelled time + shot, 20 per page |
| `frames/`, `transcript/` | Raw frames and the Whisper JSON (word timestamps) |

How it works: ffmpeg's scene filter scores every frame; scores >= 0.12 are visual changes and >= 0.30 hard cuts (`--threshold` to tune). Whisper runs with word timestamps. RapidOCR reads on-screen text (Latin script only) and lines that repeat the speech are marked as captions. ffmpeg `ebur128` + `silencedetect` give loudness and silence; loudness in speech pauses guesses whether a music bed is present. Pacing: cut times, changes per 10 s, max seconds without a visual change, time to first word, words per second.

### Turn an analysis into knowledge

```
python -m hooklab learn watch/my-clip --creator "Name" --topic "short topic" --url "<original link>"
```

Append-only: creates a new draft note `reels/NN-creator-topic.md` (never overwrites; refuses a video already learned), appends a row to `reels/00-log.md`, appends confidence-C proposals to `reels/99-playbook-proposals.md` (the playbook itself is never edited), and appends repos/links to `reels/98-vetting-queue.md` for a later read-only vetting pass (nothing is cloned or installed). `--dry-run` prints everything and writes nothing. Then open the note and write the Impression.

See `skill/reel-watch/SKILL.md`.

## Use it from an AI coding assistant

`skill/hook-lab/` and `skill/reel-watch/` are instruction files (`SKILL.md`) for Claude Code-style skills. Copy them into your skills folder if you want an assistant to run a hook study or analyse a video for you. They are optional; the CLI works on its own.

## Limitations

- Small samples; outlier scores depend on how many recent videos you sample.
- The classifier is a rule list, not a model; the speech-vs-music and "max seconds without visual change" numbers are heuristics.
- Whisper can invent text over music ("thanks for watching"); such rows are flagged `no-speech?`.
- OCR reads Latin script only.
- Platforms change; yt-dlp may need an update when YouTube changes.

## Tests

```
python -m unittest discover -s tests -t . -v
```

The tests are offline (no network, no downloads, no Whisper or OCR model needed). Tests that call ffmpeg are skipped if it is missing. CI runs them on Ubuntu and Windows with Python 3.10 and 3.12.

## Responsible use and legal notes

- Use Hook Lab for private research on **public** videos. Do not repost downloaded videos or transcripts. Respect creators' rights.
- Downloading may be restricted by a platform's terms of service (for example YouTube's). You are responsible for how you use this tool and for complying with the terms and laws that apply to you.
- It does not log in, use cookies, or bypass access controls. Do not commit downloaded media, cookies or channel lists you want to keep private (the `.gitignore` excludes the usual ones).
- Analyses of other people's videos are your own notes; label what you could not verify.
- Not affiliated with or endorsed by YouTube/Google, OpenAI, or any creator or product mentioned. All trademarks belong to their respective owners; product names in `hooklab/extract.py` are only a word list for spotting mentions.

## Contributing, security, conduct

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE). Copyright (c) 2026 AI Before You Click.
