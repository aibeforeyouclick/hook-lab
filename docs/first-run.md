# First manual run

Three YouTube Shorts from one creator, run through an early prototype. They were the first test cases for the hook classifier.

| Video | Primary type | Other tags | Visual hook |
|---|---|---|---|
| A | RANKING_CLAIM | BIG_PROMISE | trending-page screenshot, then repo card with rank badges |
| B | HOT_TAKE | none | title card with a bold opinion and an avatar |
| C | RANKING_CLAIM | none | README screenshot with rank badge, then face camera |

Findings (3 videos, so hypotheses only):

- Two of three opened with a "number one repo of the day" claim.
- The visual proof (rank badge, trending page) appeared within 2-3 seconds.
- Frame 0 was blank in two videos, so the strip now starts at 0.5 s.
- Whisper `base.en` heard "called" as "cold" once. `small.en` is the more accurate option.

The video identifiers are intentionally left out; the sentences used as tests are in `tests/test_hooklab.py`.
