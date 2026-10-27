"""Turn hooks.csv into report.md: which hook types win, with evidence."""
import csv
import statistics
from collections import defaultdict
from pathlib import Path


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def build(rows):
    usable = [r for r in rows if r.get("primary") not in ("DOWNLOAD_FAILED", "NO_SPEECH", "")]
    by = defaultdict(list)
    for r in usable:
        by[r["primary"]].append(r)
    lines = ["# Hook Lab report", "",
             f"Videos analysed: {len(rows)}  |  with usable speech hook: {len(usable)}", ""]
    if len(usable) < 20:
        lines += ["> Small sample (<20). Treat patterns as hypotheses, not findings.", ""]

    lines += ["## Hook types", "", "| Type | Videos | Median outlier | Median views |", "|---|---|---|---|"]
    stats = []
    for tag, rs in by.items():
        out = [x for x in (_f(r["outlier"]) for r in rs) if x is not None]
        views = [x for x in (_f(r["views"]) for r in rs) if x is not None]
        stats.append((statistics.median(out) if out else 0, tag, len(rs),
                      statistics.median(views) if views else 0))
    for med_out, tag, n, med_v in sorted(stats, reverse=True):
        lines.append(f"| {tag} | {n} | {med_out:.2f} | {med_v:,.0f} |")

    lines += ["", "_Outlier = views divided by the channel's median. Above 1 means it beat that channel's normal._", ""]
    starts = [x for x in (_f(r.get("speech_start")) for r in usable) if x is not None]
    if starts:
        lines += [f"Speech starts at a median of {statistics.median(starts):.1f}s.", ""]

    lines += ["## Top hooks by outlier score", ""]
    ranked = sorted(usable, key=lambda r: _f(r["outlier"]) or 0, reverse=True)[:15]
    for r in ranked:
        lines.append(f"- **{r['primary']}** ({r['outlier']}x, {r['views']} views) - "
                     f"\"{r['hook_text']}\"  \n  {r['channel']} - {r['url']}")
    problems = [r for r in rows if r.get("flag") or r.get("primary") == "DOWNLOAD_FAILED"]
    if problems:
        lines += ["", "## Needs a look", ""]
        for r in problems:
            lines.append(f"- {r['url']}: {r.get('flag') or r['primary']}")
    return "\n".join(lines) + "\n"


def write_report(run_dir):
    run = Path(run_dir)
    with open(run / "hooks.csv", newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    text = build(rows)
    (run / "report.md").write_text(text, encoding="utf-8")
    return run / "report.md"
