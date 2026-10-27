# Changelog
All notable changes. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/) (0.x: the interface may still change).

## [0.3.0] - 2026-10-27
First public release.
### Added
- `watch`: single-video analysis (shot detection, word-level transcript, optional OCR, audio and pacing, dense hook sheet, max-gap metric, transcript checks).
- `learn`: turns a `watch` analysis into an append-only draft note, log row, proposals and a vetting queue (local `reels/` folder, git-ignored by default).
- Linux/macOS install script, GitHub Actions CI (Ubuntu + Windows, Python 3.10 and 3.12), issue and PR templates.
- Tests for the `--` option separator.
### Changed
- User-supplied URLs now follow `--` in every yt-dlp call.
- Dependencies declare tested minimum versions; `pyproject.toml` has an `ocr` extra.
- README rewritten for public use (install, limitations, responsible use); example docs use anonymised identifiers.
### Notes
- Version 0.2.0 was internal and never published separately.

## [0.1.0] - 2026-10-17
- Initial CLI: `discover`, `run`, `report`, `classify`, `all`; offline test suite.
