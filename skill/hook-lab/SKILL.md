---
name: hook-lab
description: Run a hook study on YouTube channels: find each channel's top Shorts by outlier score, transcribe and classify the first-5-second hooks, and summarise which hook types win. Use when the user wants to research competitors' hooks or find what makes short videos take off.
---

# Hook Lab

Runs the `hooklab` CLI in the repository folder and turns the output into a plain-language finding.

## Before you run
1. Confirm you are in the Hook Lab repo folder and run `python -m hooklab doctor`. If anything fails, tell the user which tool is missing and stop; do not install system software without asking.
2. You need a channel list: one `@handle` or URL per line in `channels.txt`. If the user has no list, ask for channels or offer to research candidates first. Never invent channel handles.

## Run
```
python -m hooklab all channels.txt --top 8
```
Add `--model small.en` when accuracy matters more than speed. For a single step use `discover`, `run` or `report` with the run folder.

## Read the results
- Open `runs/<latest>/report.md` first, then `hooks.csv`.
- Look at a few `strips/*.jpg` images to describe the visual hook; the transcript only covers speech.
- Report: which hook types had the highest median outlier score, the three best hooks with their URLs, and any rows flagged `no-speech?` or `DOWNLOAD_FAILED`.

## Rules
- Fewer than 20 videos is a small sample. Say so and call the patterns hypotheses.
- This is for private research on public videos. Do not repost downloaded media, and never commit `runs/`, cookies or channel lists.
- Do not enter credentials or log in anywhere. If YouTube blocks downloads, report it instead of working around it.
