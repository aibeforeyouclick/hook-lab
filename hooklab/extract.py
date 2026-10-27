"""Find tools, repos and links mentioned in a video (speech + on-screen text).

The output is a to-do list for a later, read-only `vetting` pass. Nothing here
opens a URL, clones a repo or installs anything."""
import re

# Common AI / creator tools. Matching is case-insensitive on word boundaries.
KNOWN_TOOLS = [
    "Claude Code", "Claude", "ChatGPT", "OpenAI", "Anthropic", "Gemini", "NotebookLM", "Grok", "DeepSeek",
    "Llama", "Mistral", "Perplexity", "Copilot", "Cursor", "Windsurf", "Lovable", "Bolt", "Replit", "v0",
    "Midjourney", "Runway", "Kling", "Veo", "Sora", "Pika", "Luma", "Flux", "Stable Diffusion", "ComfyUI",
    "Higgsfield", "HeyGen", "Synthesia", "ElevenLabs", "Suno", "Udio", "Kokoro", "HyperFrames", "CapCut",
    "Descript", "Opus Clip", "InVideo", "Canva", "Notion", "Zapier", "n8n", "Make.com", "Ollama",
    "Hugging Face", "LM Studio", "GitHub", "Manus", "Remotion", "Whisper", "vidIQ", "TubeBuddy",
]
TLDS = "com|ai|io|dev|app|so|co|org|net|sh|gg|xyz|tech|tools|me|tv|studio|video"
URL_RE = re.compile(r"https?://[^\s\"'<>)]+", re.I)
GITHUB_RE = re.compile(r"github\s*\.\s*com\s*/\s*([A-Za-z0-9_.-]+)\s*/\s*([A-Za-z0-9_.-]+)", re.I)
DOMAIN_RE = re.compile(rf"\b((?:[a-z0-9-]+\.)+(?:{TLDS}))\b(/[^\s\"'<>)]*)?", re.I)
SLASH_RE = re.compile(r"(?<![\w/.-])([A-Za-z][\w.-]{1,38})/([A-Za-z][\w.-]{1,99})(?![\w/])")
CALLED_RE = re.compile(r"\b(?:called|named)\s+([\w.-]+(?:\s+[\w.-]+){0,2})", re.I)
REVERSE_DNS = ("com.", "org.", "net.", "io.")  # app ids like com.calendly.app are not websites
# first parts of file paths seen in terminal/editor screenshots, not GitHub owners
PATH_WORDS = {"apps", "app", "packages", "src", "lib", "docs", "config", "research", "home", "users", "usr",
              "etc", "var", "tmp", "bin", "node_modules", "from", "during", "launch", "run", "in", "read",
              "known", "knowm", "public", "assets", "scripts", "test", "tests", "dist", "build", "and", "or"}
FILE_EXT_RE = re.compile(r"\.(md|json|ts|tsx|js|py|txt|yml|yaml|toml|lock|html|css|png|jpg|mp4)$", re.I)
STOP = {"the", "a", "an", "and", "it", "this", "that", "is", "to", "of", "in", "for", "you", "your", "with"}
SPOKEN_DOT_RE = re.compile(r"\b([a-z0-9-]{2,})\s+dot\s+(" + TLDS + r")\b", re.I)


def _clean_called(phrase):
    words = []
    for w in phrase.split():
        w = w.strip(".,!?;:\"'")
        if not w or w.lower() in STOP:
            break
        words.append(w)
    return " ".join(words)


def mentions_in(text, source, t):
    """All mentions in one piece of text. Returns [{kind, value, source, t}]."""
    found = []
    text = text or ""

    def add(kind, value):
        value = value.strip().rstrip(".,;:!?")
        if value:
            found.append({"kind": kind, "value": value, "source": source, "t": t})

    for m in GITHUB_RE.finditer(text):
        add("github", f"github.com/{m.group(1)}/{m.group(2).removesuffix('.git')}")
    for m in URL_RE.finditer(text):
        if "github.com" not in m.group(0).lower():
            add("url", m.group(0))
    no_urls = URL_RE.sub(" ", GITHUB_RE.sub(" ", text))
    for m in DOMAIN_RE.finditer(no_urls):
        if not re.fullmatch(r"[\d.]+", m.group(1)) and not m.group(1).lower().startswith(REVERSE_DNS):
            add("domain", m.group(1).lower() + (m.group(2) or ""))
    for m in SPOKEN_DOT_RE.finditer(no_urls):
        add("domain", f"{m.group(1).lower()}.{m.group(2).lower()}")
    if source == "screen":
        for m in SLASH_RE.finditer(no_urls):
            owner, repo = m.group(1), m.group(2)
            if (not DOMAIN_RE.fullmatch(owner) and re.search(r"[a-z]", repo, re.I)
                    and owner.lower() not in PATH_WORDS and "." not in owner
                    and not FILE_EXT_RE.search(repo) and not repo.endswith("-")):
                add("repo?", f"{owner}/{repo}")
    for m in CALLED_RE.finditer(text if source == "speech" else ""):  # on screen it is mostly UI noise
        v = _clean_called(m.group(1))
        if v:
            add("called", v)
    low = text.lower()
    for tool in KNOWN_TOOLS:
        if re.search(r"(?<![\w])" + re.escape(tool.lower()) + r"(?![\w])", low):
            add("tool", tool)
    return found


def extract_mentions(speech_words, screen_lines, window=12):
    """speech_words: [(t, word)]; screen_lines: [(t, text)]. Speech is scanned in
    overlapping windows of words so phrases like 'it's called X' are caught."""
    found = []
    words = list(speech_words)
    step = max(1, window // 2)
    for i in range(0, max(1, len(words)), step):
        chunk = words[i:i + window]
        if chunk:
            found += mentions_in(" ".join(w for _, w in chunk), "speech", chunk[0][0])
    for t, text in screen_lines:
        found += mentions_in(text, "screen", t)
    return dedupe(found)


def dedupe(items):
    seen, out = {}, []
    tools = {x["value"].lower() for x in items if x["kind"] == "tool"}
    repos = {x["value"].lower().removeprefix("github.com/") for x in items if x["kind"] == "github"}
    for x in sorted(items, key=lambda x: x["t"]):
        if x["kind"] == "repo?" and x["value"].lower() in repos:
            x = {**x, "kind": "github", "value": "github.com/" + x["value"]}
        key = (x["kind"], x["value"].lower())
        if x["kind"] == "tool" and x["value"] == "Claude" and "claude code" in tools:
            continue  # "Claude Code" already covers it
        if key in seen:
            if x["source"] not in seen[key]["source"]:
                seen[key]["source"] += "+" + x["source"]
            continue
        item = dict(x)
        seen[key] = item
        out.append(item)
    return out
