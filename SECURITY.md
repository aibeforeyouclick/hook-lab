# Security policy

Hook Lab runs locally and needs no credentials. It starts `yt-dlp`, `whisper` and `ffmpeg` as subprocesses with argument lists (never through a shell), and puts user-supplied URLs after a `--` separator so they cannot be read as options.

## Supported versions
Only the latest release on `main` receives fixes.

## Reporting a vulnerability
Please report privately through **GitHub Security Advisories**: on the repository, open the *Security* tab and choose *Report a vulnerability*. Do not open a public issue for security problems. Include the version, steps to reproduce and the impact. We aim to acknowledge reports within 7 days; this is a volunteer project, so fix times vary.

## Using it safely
- Never commit cookies or tokens. If you pass `--cookies-from-browser` to yt-dlp yourself, treat the result as a secret.
- Only run channel lists and URLs you trust.
- Keep yt-dlp, Whisper and ffmpeg updated; they parse untrusted media.
