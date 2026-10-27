---
name: reel-watch
description: Watch a short video (reel, Short, TikTok, YouTube) the way a person would, so a chat that cannot play video can still understand the concept. Use when the user shares a video link or file and wants it analysed, summarised, or added to the reels knowledge base.
---

# Reel Watch

You cannot hear or play video. This skill gives you eyes and ears: frames to look at and a timestamped transcript to read. Two paths: for a video FILE use Path B (shots, word transcript, on-screen text, audio, pacing); for a link with no file, Path A.

## Path A: you have a browser pane (any platform link, no download)
1. Open the link in the built-in browser. Expand "See more" with JavaScript (`div[role=button]` whose text is "See more") and read the full caption: creator, claims, call to action, hashtags.
2. Check the player: `document.querySelector('video')` gives `duration`, and you can `pause()` and set `currentTime` to jump. Take a screenshot after each jump.
3. Limits, learned the hard way: burned-in captions show one or two words per frame, so frames alone do NOT carry the spoken content. Use frames for visuals, on-screen text and structure (slides, lists, demos). For what is said, you need Path B.
4. Hidden pane = no video: when the browser pane is in the background the page pauses video to save power, `play()` throws "video-only background media was paused", and seeking shows black frames. Keep the pane visible, and if frames stay black, switch to Path B instead of guessing.
5. Write what you saw. Mark anything you could not see as "not verified".

## Path B: local analysis of a video FILE (preferred; needs the user's PC)
Use it for any video file the user gives you (or one already on disk). Do not download videos from platforms yourself.
```
.venv\Scripts\python.exe -m hooklab watch "<file path>" --out watch\<name> --model small --lang auto
```
(Hebrew speech: `--lang he`. Never use a `*.en` model on non-English speech: it silently translates. Visuals only: `--no-transcript`.)
About 1-3 min for a 1-min reel on CPU. Then read, in this order:
1. `watch\<name>\analysis.md`: notes/warnings at the top first (e.g. "Transcript UNRELIABLE"), then Hook, Pacing, Audio, the shot-by-shot timeline (said vs shown), CTAs, claim candidates, tools/repos/links.
2. `sheets\hook.jpg` (12 frames, 0-3 s at 4 fps): what the viewer sees at the decision moment.
3. `sheets\contact_NN.jpg`: one labelled frame per shot. OCR misses logos, icons, Hebrew and stylised text; look at the frames for those.
4. `analysis.json` only when you need exact word times or every OCR line.
Limits to state, not hide: the scene filter does not see caption-only changes (a talking head with changing captions can show a long "max seconds without visual change"); speech-vs-music is a loudness heuristic; hook type uses English patterns; OCR joins words and misreads letters.

## What to produce
1. Draft the note with `learn` (append-only; never overwrites, refuses a video already learned):
   `.venv\Scripts\python.exe -m hooklab learn watch\<name> --creator "<who>" --topic "<short topic>" --url "<link if any>"`
   Use `--dry-run` first if unsure. It writes `reels/NN-creator-topic.md`, a row in `reels/00-log.md`, C-labelled proposals in `reels/99-playbook-proposals.md` and unvetted repos/links in `reels/98-vetting-queue.md`.
2. Then finish the note by hand (edit only the new note): concept in your own words, arc (concept / how-to / listicle / story), what is shown vs said, seller claims vs verified, Impression, next step. Fix OCR/speech misspellings of tool names. Short excerpts only, no long quotes of the creator's script.
3. Playbook: `99-playbook.md` is changed only by a human decision. Proposals stay C until several reels agree (B) or your own channel data shows it (A).
4. Repos/tools: do not clone, install or open them as part of this skill. They wait in the vetting queue for the read-only vetting review.

## Rules
- Private research only. Do not repost downloaded videos; never commit `watch/`, `runs/`, `.venv/` or cookies.
- Do not log in, comment, DM, follow, or "comment X to get the link" on the user's behalf.
- Never invent what the speaker said. If there is no transcript yet, say so and give the command.
- Income claims, follower counts and "I made $X" are seller claims unless a verifiable source backs them.
