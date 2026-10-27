# Contributing to Hook Lab

Thanks for helping. Small, focused pull requests are easiest to review.

## Getting started
```
git clone https://github.com/aibeforeyouclick/hook-lab.git
cd hook-lab
python -m unittest discover -s tests -t . -v
```
The tests are offline and need neither yt-dlp, Whisper nor OCR models. You only need Python 3.10+ (ffmpeg is optional; tests that call it are skipped without it).

## Rules of the road
- **Tests stay offline.** Use the fake `runner` pattern in `tests/test_hooklab.py` instead of calling YouTube.
- New hook types go in `RULES` in `hooklab/classify.py`, with a test using a realistic example sentence.
- Anything built from user input goes to `yt-dlp` and other tools as an argument list (never `shell=True`), with `--` before the URL/path.
- Keep dependencies minimal. The core uses the standard library plus yt-dlp and Whisper; OCR and Pillow stay optional.
- Do not commit downloaded media, cookies, tokens, analyses of real people's videos, or personal channel lists (the `.gitignore` covers the usual ones). Test data must be fictional or short generic sentences.
- Update `README.md` and `CHANGELOG.md` when behaviour changes.

## Pull requests
1. Fork and create a branch.
2. Make the change with tests; run the suite.
3. Open a PR describing what and why. CI runs on Ubuntu and Windows, Python 3.10 and 3.12.

## Reporting bugs and ideas
Open an issue using the templates. For security problems, do **not** open a public issue: see [SECURITY.md](SECURITY.md).

By contributing you agree that your contribution is licensed under the MIT License, and you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
