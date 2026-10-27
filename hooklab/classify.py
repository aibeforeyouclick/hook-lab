"""Rule-based hook classifier. No network, no model: transparent and testable.

A hook can carry several tags. `primary` is the first matching tag in PRIORITY.
The rules are deliberately simple English patterns; extend RULES for other languages.
"""
import re

# (tag, regex). Order here is the priority order for `primary`.
RULES = [
    ("RANKING_CLAIM", r"\b(number (one|1)|no\.? ?1|#1|top (\d+|ten|five|three)|the best|biggest|most (popular|viral))\b"),
    ("HOT_TAKE", r"\b(can'?t stand|hate|sucks?|overrated|unpopular opinion|hot take|nobody (wants|talks|tells)|wrong|myth|lie|lying|stop (doing|using|making))\b"),
    ("PERSONAL_PROOF", r"\b(i (tried|tested|built|made|spent|gave|used|ran|quit|lost|found)|we (built|made|tried)|my (whole|entire|first|biggest))\b"),
    ("NUMBERED_LIST", r"\b(\d+|three|four|five|six|seven|ten) (ways|tips|tools|things|reasons|steps|rules|mistakes|hacks|prompts|systems|repos)\b"),
    ("BIG_PROMISE", r"\b(changes everything|game ?changer|in (\d+|one|two|three) (seconds?|minutes?|days?|prompt)|for free|overnight|automatically|on autopilot|passive|10x|20x|100x)\b"),
    ("CURIOSITY_GAP", r"\b(here'?s (why|how|what)|the (secret|reason|truth)|what happens|you won'?t believe|nobody knows|no one knows|turns out)\b"),
    ("QUESTION", r"(\?|^(what|why|how|did you|have you|do you|can you|are you|is it|would you)\b)"),
    ("DIRECT_ADDRESS", r"^(you|if you|listen|watch|look|stop|hey|guys|imagine)\b"),
    ("STORY_OPEN", r"\b(one day|last (week|month|year)|so (i|we)|this (guy|girl|man|woman|kid)|story time)\b"),
]
PRIORITY = [t for t, _ in RULES]
_COMPILED = [(t, re.compile(p, re.IGNORECASE)) for t, p in RULES]


def classify(text):
    """Return {'tags': [...], 'primary': str, 'words': int} for a hook transcript."""
    t = (text or "").strip()
    if not t:
        return {"tags": [], "primary": "NO_SPEECH", "words": 0}
    tags = [tag for tag, rx in _COMPILED if rx.search(t)]
    return {"tags": tags, "primary": tags[0] if tags else "OTHER", "words": len(t.split())}
