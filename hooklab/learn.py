"""Turn one `watch` analysis into knowledge: a draft reel note in reels/, a row in
reels/00-log.md, playbook proposals with confidence labels, and a vetting queue.

Append-only by design: the note is created with exclusive mode (never overwrites),
the log / proposals / queue files are only appended to, and 99-playbook.md itself is
never touched (proposals go to 99-playbook-proposals.md for a human to promote)."""
import json
import re
from datetime import date
from pathlib import Path

LOG = "00-log.md"
PROPOSALS = "99-playbook-proposals.md"
QUEUE = "98-vetting-queue.md"
VET_KINDS = ("github", "repo?", "url", "domain", "called")
MAX_QUOTE_WORDS = 14  # notes summarise; the full transcript stays in the local analysis folder

PROPOSALS_HEADER = """# Playbook proposals (append-only, written by `hooklab learn`)
Each block comes from one analysed reel. Confidence: C = one reel (default here), B = several
sources agree, A = your own channel data. `learn` never assigns A or B; promote an item into
`99-playbook.md` by hand when the evidence grows.
"""
QUEUE_HEADER = """# Repo / tool vetting queue (append-only, written by `hooklab learn`)
Names and links seen or heard in reels. All are UNVETTED: run the read-only vetting
review before cloning, installing or recommending anything. OCR and speech can misspell names.

| Date | Reel # | Kind | Value | Seen in | At (s) | Status |
|---|---|---|---|---|---|---|
"""


def slug(text, limit=40):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:limit].rstrip("-")) or "untitled"


def short(text, n=MAX_QUOTE_WORDS):
    words = (text or "").split()
    return " ".join(words[:n]) + (" ..." if len(words) > n else "")


def cell(text):
    return (text or "").replace("|", "/").replace("\n", " ").strip()


def fmt(t):
    if t is None:
        return "-"
    t = float(t)
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def next_log_number(log_text):
    nums = [int(m.group(1)) for m in re.finditer(r"^\|\s*(\d+)\s*\|", log_text or "", re.M)]
    return max(nums, default=0) + 1


def next_file_prefix(reels_dir):
    nums = []
    for p in Path(reels_dir).iterdir():
        m = re.match(r"(\d{2})-", p.name)
        if m and m.group(1) not in ("00", "98", "99"):
            nums.append(int(m.group(1)))
    return max(nums, default=0) + 1


def already_learned(reels_dir, video_id):
    tag = f"hooklab-analysis: {video_id}"
    for p in Path(reels_dir).rglob("*.md"):
        try:
            if tag in p.read_text(encoding="utf-8"):
                return p
        except OSError:
            continue
    return None


def default_topic(a):
    h = a.get("hook", {})
    text = h.get("said_first_5s") or " ".join(h.get("on_screen_text", [])[:3])
    return short(text, 7).replace(" ...", "") or Path(a.get("video_file", "video")).stem


def propose(a):
    """Playbook proposals from one analysis. Returns [(label, text)]; label is always C."""
    p, h, au = a.get("pacing", {}), a.get("hook", {}), a.get("audio", {})
    dur = a.get("media", {}).get("duration") or 0
    tags = set(h.get("hook_type", {}).get("tags", [])) | {h.get("hook_type", {}).get("primary")}
    out = []
    fw = p.get("time_to_first_word")
    if fw is not None and fw <= 1.0:
        out.append(("C", f"Supports #1 (speak in the first second): first word at {fw} s."))
    elif fw is None or fw > 2.0:
        ftc = h.get("first_text_change")
        extra = f"; on-screen text changes at {ftc} s" if ftc is not None else ""
        out.append(("C", f"Counter-example or variant of #1: no speech in the first 2 s "
                         f"(first word {fw if fw is not None else 'never'}){extra}. The hook is carried by on-screen text/visuals."))
    if tags & {"RANKING_CLAIM", "BIG_PROMISE"}:
        out.append(("C", f"Supports #2 (promise in the first line): hook type {sorted(t for t in tags if t)}."))
    early = [m for m in a.get("mentions", []) if m["kind"] in ("github", "repo?", "url", "domain") and m["t"] <= 3.0]
    if early:
        out.append(("C", f"Supports #4 (visual proof in 2-3 s): {early[0]['value']} on screen at {early[0]['t']} s."))
    if "NUMBERED_LIST" in tags:
        out.append(("C", "Supports #5 (numbered lists): the hook announces a list."))
    if any(c["kind"] == "comment-keyword" for c in a.get("ctas", [])):
        out.append(("C", "Supports #7 (comment-a-word funnel): call to action asks for a keyword comment."))
    cps = p.get("changes_per_second") or 0
    if cps >= 0.5:
        out.append(("C", f"New: fast visual pacing, {cps} visual changes per second (avg shot {p.get('avg_shot_seconds')} s)."))
    elif dur > 20 and cps <= 0.1:
        out.append(("C", f"New: slow visual pacing still used ({cps} changes/s, longest shot {p.get('longest_shot_seconds')} s)."))
    if "music/sound bed" in (au.get("label") or ""):
        out.append(("C", "New: voice over a music/sound bed (heuristic from loudness between words)."))
    gap = p.get("max_seconds_without_visual_change")
    if gap:
        side = "breaks" if gap > 5 else "fits"
        out.append(("C", f"Rule check '5 s max without a visual change' (Cole, HyperFrames notes): this reel {side} it, "
                         f"longest stretch {gap} s."))
    wpm = p.get("words_per_minute")
    if wpm and wpm >= 180:
        out.append(("C", f"New: fast delivery, about {int(wpm)} words per minute."))
    return out


def note_text(a, n, creator, topic, url, analysis_dir):
    p, h, au, m = a["pacing"], a["hook"], a["audio"], a["media"]
    src = url or a.get("source")
    L = [f"# Reel {n}: {creator} - \"{topic}\" ({src})",
         f"<!-- hooklab-analysis: {a['video_id']} -->",
         "Status: DRAFT written by `hooklab learn` from a local auto-analysis. Fill in \"Impression\", "
         "check the claims, and fix OCR/speech misspellings.", "",
         "## Verified from the video (auto-analysis: transcript, OCR, frames)",
         f"- Length {fmt(m.get('duration'))}, {m.get('width')}x{m.get('height')} {m.get('orientation', '')}; "
         f"speech language: {a.get('language') or 'n/a'}; audio: {au.get('label')}.",
         f"- Hook (0-3 s): said \"{short(h.get('said'))}\"; on screen: {short('; '.join(h.get('on_screen_text', [])))}.",
         f"- Hook type (auto): {h['hook_type']['primary']} {h['hook_type']['tags']}; first word at "
         f"{p.get('time_to_first_word') if p.get('time_to_first_word') is not None else 'never'} s; "
         f"on-screen text first changes at {h.get('first_text_change') if h.get('first_text_change') is not None else '-'} s.",
         f"- Pacing: {p['shots']} shots, {p['changes_per_second']} visual changes/s, avg shot {p['avg_shot_seconds']} s, "
         f"{p.get('words_per_minute') or '-'} words/min.",
         "- Calls to action: " + (", ".join(f"{c['kind']} (\"{c['match']}\")" for c in a.get("ctas", [])) or "none found") + ".",
         "", "## Fields (comparable across reels and with shorts-lab script.json)",
         "- arc: TODO (concept / how-to / listicle / story)",
         f"- hook_type: {h['hook_type']['primary']}",
         f"- time_to_first_word_s: {p.get('time_to_first_word')}",
         f"- first_visual_change_s: {p.get('first_visual_change')}",
         f"- max_gap_s: {p.get('max_seconds_without_visual_change')}",
         f"- changes_per_10s: {p.get('changes_per_10s')}",
         f"- words_per_sec: {p.get('words_per_second')}",
         "- caption_style: TODO (words per caption group; see sheets)",
         "", "## Structure (shot by shot; short excerpts only, full text in the local analysis)"]
    for sh in a["shots"]:
        bits = []
        if sh.get("said"):
            bits.append(f"says \"{short(sh['said'], 10)}\"")
        if sh.get("on_screen_text"):
            bits.append("screen: " + short(" | ".join(sh["on_screen_text"]), 10))
        L.append(f"- {fmt(sh['start'])}-{fmt(sh['end'])}: " + ("; ".join(bits) or "(no speech, no text read)"))
    L += ["", "## Tools, repos and links mentioned (UNVETTED; queued in `98-vetting-queue.md`)"]
    L += [f"- [{x['kind']}] {x['value']} ({x['source']}, {fmt(x['t'])})" for x in a.get("mentions", [])] or ["- none found"]
    L += ["", "## Seller claims (not verified)"]
    L += [f"- \"{short(c)}\"" for c in a.get("claim_candidates", [])] or ["- none detected automatically"]
    L += ["", "## Not captured / limits"]
    L += [f"- {x}" for x in a.get("notes", [])]
    L += ["- Speech vs music and hook type are heuristics. OCR reads Latin script only (no Hebrew) and can join words.",
          "- Anything not in the transcript, OCR or frames is not verified.",
          "", "## Impression", "_TODO: concept in your own words, what you can reuse, verdict, next step._",
          "", "## Analysis files (local, not committed)",
          f"- `{Path(analysis_dir).as_posix()}/analysis.md`, `sheets/contact_NN.jpg`, `sheets/hook.jpg`"]
    return "\n".join(L) + "\n"


def _append(path, text, header=""):
    path = Path(path)
    new = not path.exists()
    prefix, nl = "", "\n"
    if not new:
        cur = path.read_bytes().decode("utf-8", errors="replace")
        nl = "\r\n" if "\r\n" in cur else "\n"  # keep the file's own line endings
        if cur and not cur.endswith("\n"):
            prefix = "\n"
    with open(path, "a", encoding="utf-8", newline=nl) as fh:
        fh.write((header if new else prefix) + text)


def learn(analysis_dir, reels_dir="reels", creator="unknown creator", topic=None, url=None,
          dry_run=False, today=None):
    msgs = []
    adir, reels = Path(analysis_dir), Path(reels_dir)
    af = adir / "analysis.json"
    if not af.exists():
        return {"ok": False, "messages": [f"No analysis.json in {adir}. Run `hooklab watch` first."]}
    a = json.loads(af.read_text(encoding="utf-8"))
    reels.mkdir(parents=True, exist_ok=True)
    dup = already_learned(reels, a["video_id"])
    if dup:
        return {"ok": False, "messages": [f"This video was already learned in {dup}. Nothing written."]}

    today = today or date.today()
    log_path = reels / LOG
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    n = next_log_number(log_text)
    topic = topic or default_topic(a)
    name = f"{next_file_prefix(reels):02d}-{slug(creator, 25)}-{slug(topic, 35)}.md"
    note_path = reels / name
    note = note_text(a, n, creator, topic, url, adir)
    log_row = (f"| {n} | {today:%m-%d} | {cell(creator)} | {cell(topic)} | draft: auto-analysis, "
               f"impression pending | reels/{name} |\n")
    props = propose(a)
    prop_block = f"\n## {today:%Y-%m-%d} reel {n}: {cell(creator)} - {cell(topic)} (reels/{name})\n" + \
        "".join(f"- [{lab}] {txt}\n" for lab, txt in props) if props else ""
    vet = [x for x in a.get("mentions", []) if x["kind"] in VET_KINDS]
    vet_rows = "".join(f"| {today:%Y-%m-%d} | {n} | {x['kind']} | {cell(x['value'])} | {x['source']} | "
                       f"{x['t']} | unvetted |\n" for x in vet)

    if dry_run:
        msgs += [f"[dry-run] would create {note_path}", f"[dry-run] would append to {log_path}: {log_row.strip()}",
                 f"[dry-run] would append {len(props)} proposals to {reels / PROPOSALS}",
                 f"[dry-run] would append {len(vet)} rows to {reels / QUEUE}", "", note]
        return {"ok": True, "messages": msgs, "note": None, "number": n}

    with open(note_path, "x", encoding="utf-8", newline="\n") as fh:  # never overwrite
        fh.write(note)
    msgs.append(f"note -> {note_path}")
    _append(log_path, log_row, header="# Reel log\n| # | Date | Creator / page | Topic | Verdict | Note |\n|---|---|---|---|---|---|\n")
    msgs.append(f"log row {n} -> {log_path}")
    if prop_block:
        _append(reels / PROPOSALS, prop_block, header=PROPOSALS_HEADER)
        msgs.append(f"{len(props)} playbook proposals (C) -> {reels / PROPOSALS}")
    if vet_rows:
        _append(reels / QUEUE, vet_rows, header=QUEUE_HEADER)
        msgs.append(f"{len(vet)} mentions queued for read-only vetting -> {reels / QUEUE}")
    msgs.append("Next: open the note, write the Impression, verify claims; promote proposals by hand.")
    return {"ok": True, "messages": msgs, "note": note_path, "number": n}
