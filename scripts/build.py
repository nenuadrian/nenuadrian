#!/usr/bin/env python3
"""Build the images in the profile README.

The header, a card for each video series and the list of recent writing are
SVGs, each in a light and a dark version, built from the channel's long-form
uploads and the Substack feed. Anything a feed can't give this time comes from
the previous build's state.json, so a feed that's down never blanks a card.

    python scripts/build.py --out dist [--previous last-build]

Only the standard library is needed.
"""

from __future__ import annotations

import argparse
import html
import http.client
import json
import random
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from base64 import b64encode
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

CHANNEL_ID = "UCK_b06iYVfaIQeTmpDxbEyw"
# "UULF" and the channel id without its "UC" name the playlist of the channel's
# uploads without its Shorts and streams, newest first.
UPLOADS_FEED = "https://www.youtube.com/feeds/videos.xml?playlist_id=UULF" + CHANNEL_ID[2:]
SUBSTACK_FEED = "https://adriannenu.substack.com/feed"
THUMBNAIL = "https://i.ytimg.com/vi/{}/mqdefault.jpg"
USER_AGENT = "profile-readme-builder/1.0"


@dataclass(frozen=True)
class Series:
    key: str
    name: str
    kicker: str
    blurb: str
    repo: str
    pattern: str  # matches the end of an episode's title; group 1 is its number


SERIES = [
    Series(
        "nanommo", "nanoMMO", "Building an MMO",
        "A whole MMO from scratch in C++: server, client and infrastructure",
        "github.com/nenuadrian/nanoMMO",
        r"\|\s*(?:Building nanoMMO|nanoMMO Devlog)\s*#(\d+)\s*$",
    ),
    Series(
        "mvgpt", "mvGPT", "Minimum Viable GPT",
        "A GPT from scratch in PyTorch: pretraining, SFT, DPO and GRPO",
        "github.com/nenuadrian/mvGPT",
        r"\|\s*Minimum Viable GPT\s*#(\d+)\s*$",
    ),
    Series(
        "smollergraph", "smollerGraph", "Building smollerGraph",
        "A graph database from scratch in C++: pages, a B+ tree, Cypher and GNNs",
        "github.com/nenuadrian/smollerGraph",
        r"\|\s*Building smollerGraph\s*#(\d+)\s*$",
    ),
]

# The palette of nenuadrian.com: ink, fog and the signal blue.
THEMES = {
    "light": {"bg": "#f7f7f9", "border": "#d7d7dd", "ink": "#0b0b0f", "text": "#2a2a35",
              "muted": "#6b6b75", "grid": "#b9b9c2", "accent": "#2c5ccf"},
    "dark": {"bg": "#0b0b0f", "border": "#2a2a35", "ink": "#f7f7f9", "text": "#d7d7dd",
             "muted": "#8e8e99", "grid": "#4a4a53", "accent": "#8ab4ff"},
}
SANS = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
SERIF = "Newsreader, 'Iowan Old Style', Georgia, 'Times New Roman', serif"
MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
WIDTH = 860


# Feeds ------------------------------------------------------------------------

def fetch(url: str, attempts: int = 3) -> bytes:
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read()
        except (OSError, http.client.HTTPException) as error:
            if attempt == attempts - 1:
                raise
            print(f"retrying {url}: {error}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"


def latest_episodes(feed: bytes) -> dict[str, dict]:
    """The newest episode of each series among the uploads in the feed."""
    found: dict[str, dict] = {}
    for entry in ET.fromstring(feed).iter(ATOM + "entry"):
        title = (entry.findtext(ATOM + "title") or "").strip()
        for series in SERIES:
            match = re.search(series.pattern, title)
            if not match:
                continue
            episode = {
                "number": int(match.group(1)),
                "title": title[: match.start()].strip(),
                "video": entry.findtext(YT + "videoId"),
                "published": (entry.findtext(ATOM + "published") or "")[:10],
            }
            if series.key not in found or episode["number"] > found[series.key]["number"]:
                found[series.key] = episode
    return found


def latest_posts(feed: bytes, count: int = 3) -> list[dict]:
    posts = [
        {
            "title": (item.findtext("title") or "").strip(),
            "url": (item.findtext("link") or "").strip(),
            "published": parsedate_to_datetime(item.findtext("pubDate")).date().isoformat(),
        }
        for item in ET.fromstring(feed).iter("item")
    ]
    return sorted(posts, key=lambda post: post["published"], reverse=True)[:count]


def thumbnail(video: str, previous: Path | None, out: Path) -> bytes | None:
    """The video's thumbnail, kept with the build so a later one can fall back on it."""
    path = Path("thumbs") / f"{video}.jpg"
    try:
        data: bytes | None = fetch(THUMBNAIL.format(video))
    except (OSError, http.client.HTTPException) as error:
        print(f"no thumbnail for {video}: {error}", file=sys.stderr)
        data = (previous / path).read_bytes() if previous and (previous / path).exists() else None
    if data:
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(data)
    return data


# Text ---------------------------------------------------------------------------

NARROW = set("fijlrtI!.,:;'|()[]/ ")
WIDE = set("mwMW@%")


def text_width(text: str, size: float, mono: bool = False) -> float:
    """A rough width, on the wide side, as the viewer's fonts are unknown."""
    if mono:
        return len(text) * size * 0.68  # 0.6em glyphs and 0.08em of letter-spacing
    em = 0.0
    for char in text:
        if char in NARROW:
            em += 0.3
        elif char in WIDE:
            em += 0.86
        elif char.isupper():
            em += 0.66
        elif char.isdigit():
            em += 0.57
        else:
            em += 0.53
    return em * size


def wrap(text: str, size: float, width: float, max_lines: int, weight: float = 1.0) -> list[str]:
    """Lines of at most `width`, the last one ending in an ellipsis if the text doesn't fit."""
    def fits(line: str) -> bool:
        return text_width(line, size) * weight <= width

    lines: list[str] = []
    words = text.split()
    while words and len(lines) < max_lines:
        line = words.pop(0)
        while words and fits(f"{line} {words[0]}"):
            line += " " + words.pop(0)
        lines.append(line)
    if words:
        last = lines[-1]
        while not fits(last + "…") and " " in last:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last.rstrip(",;:.-–— ") + "…"
    return lines


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%b %Y}"


def text(x: float, y: float, content: str, cls: str, fill: str, anchor: str = "start") -> str:
    anchor_attr = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return f'<text x="{x:g}" y="{y:g}" class="{cls}" fill="{fill}"{anchor_attr}>{esc(content)}</text>'


def svg(height: int, title: str, theme: str, body: str, css: str = "") -> str:
    t = THEMES[theme]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-label="{esc(title)}">\n'
        f"<title>{esc(title)}</title>\n"
        "<style>"
        f".sans{{font-family:{SANS}}}"
        f".serif{{font-family:{SERIF};font-style:italic}}"
        f".mono{{font-family:{MONO};letter-spacing:.08em}}"
        f".code{{font-family:{MONO}}}"
        f"{css}</style>\n"
        f'<rect x=".5" y=".5" width="{WIDTH - 1}" height="{height - 1}" rx="12" '
        f'fill="{t["bg"]}" stroke="{t["border"]}"/>\n'
        f"{body}\n</svg>\n"
    )


# The Game of Life ----------------------------------------------------------------

GLIDER = {(1, 0), (2, 1), (0, 2), (1, 2), (2, 2)}  # heads down and to the right


def life_step(cells: set, size: int) -> set:
    counts: dict[tuple[int, int], int] = {}
    for x, y in cells:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    key = ((x + dx) % size, (y + dy) % size)
                    counts[key] = counts.get(key, 0) + 1
    return {cell for cell, n in counts.items() if n == 3 or (n == 2 and cell in cells)}


def glider_loop(size: int, gliders: int) -> list[set]:
    """Generations of gliders on a size×size torus that never meet, so that after
    4·size generations, when each has gone once around, the field is back where it
    started and the animation loops without a seam."""
    period = 4 * size
    for seed in range(100_000):
        rng = random.Random(seed)
        cells: set = set()
        for _ in range(gliders):
            x, y = rng.randrange(size), rng.randrange(size)
            glider = {((gx + x) % size, (gy + y) % size) for gx, gy in GLIDER}
            for _ in range(rng.randrange(4)):
                glider = life_step(glider, size)
            cells |= glider
        frames = [cells]
        for _ in range(period):
            cells = life_step(cells, size)
            if len(cells) != 5 * gliders:
                break
            frames.append(cells)
        if len(frames) == period + 1 and frames[-1] == frames[0]:
            return frames[:-1]
    raise RuntimeError("no seed gives gliders that never meet")


# Images ------------------------------------------------------------------------

def hero(state: dict, frames: list[set], size: int, theme: str) -> str:
    t = THEMES[theme]
    height, pitch = 280, 14
    episodes = sum(state["episodes"][s.key]["number"] for s in SERIES)
    last = max([e["published"] for e in state["episodes"].values()]
               + [p["published"] for p in state["posts"]])
    first_col = 30  # nothing is drawn under the text, where the fade hides it anyway

    seconds = 0.18
    paths = []
    for i, cells in enumerate(frames):
        d = "".join(
            f"M{c * pitch + pitch / 2:g} {r * pitch + pitch / 2:g}h0"
            for x, y in sorted(cells)
            for c in range(x, WIDTH // pitch + 1, size)
            for r in range(y, height // pitch + 1, size)
            if c >= first_col
        )
        cls = "f f0" if i == 0 else "f"
        paths.append(f'<path class="{cls}" style="animation-delay:{i * seconds:.2f}s" d="{d}"/>')
    duration = len(frames) * seconds
    css = (
        f".f{{opacity:0;animation:life {duration:.2f}s steps(1,end) infinite}}"
        f"@keyframes life{{0%{{opacity:1}}{100 / len(frames):.4f}%{{opacity:0}}100%{{opacity:0}}}}"
        "@media (prefers-reduced-motion:reduce){.f{animation:none}.f0{opacity:1}}"
        ".name{font-size:44px;font-weight:600;letter-spacing:-.01em}"
        ".tag{font-size:23px}.k{font-size:12px}.line{font-size:16.5px}"
    )
    title = ("Adrian Mircea Nenu. computo, ergo sum. PhD researcher at the University of "
             "Manchester, reinforcement learning and reasoning systems. Previously Google Cloud "
             "and Morgan Stanley.")
    body = f"""<defs>
<clipPath id="card"><rect x="1" y="1" width="{WIDTH - 2}" height="{height - 2}" rx="11"/></clipPath>
<pattern id="grid" width="{pitch}" height="{pitch}" patternUnits="userSpaceOnUse"><circle cx="{pitch / 2:g}" cy="{pitch / 2:g}" r="1" fill="{t['grid']}"/></pattern>
<linearGradient id="fade"><stop offset=".48" stop-color="#fff" stop-opacity="0"/><stop offset=".9" stop-color="#fff"/></linearGradient>
<linearGradient id="soft"><stop offset=".15" stop-color="#fff" stop-opacity=".25"/><stop offset=".7" stop-color="#fff"/></linearGradient>
<mask id="cells"><rect width="{WIDTH}" height="{height}" fill="url(#fade)"/></mask>
<mask id="paper"><rect width="{WIDTH}" height="{height}" fill="url(#soft)"/></mask>
</defs>
<g clip-path="url(#card)">
<rect width="{WIDTH}" height="{height}" fill="url(#grid)" mask="url(#paper)" opacity=".7"/>
<g mask="url(#cells)" stroke="{t['accent']}" stroke-width="{pitch - 4}" stroke-linecap="square" opacity=".55">
{chr(10).join(paths)}
</g>
</g>
{text(44, 58, f"LAB NOTEBOOK · {episodes} EPISODES · LAST ENTRY {day(last).upper()}", "mono k", t["accent"])}
{text(42, 114, "Adrian Mircea Nenu", "sans name", t["ink"])}
{text(44, 148, "computo, ergo sum", "serif tag", t["muted"])}
{text(44, 198, "PhD researcher at the University of Manchester", "sans line", t["text"])}
{text(44, 223, "Reinforcement learning and reasoning systems", "sans line", t["muted"])}
{text(44, 248, "Previously Google Cloud and Morgan Stanley", "sans line", t["muted"])}"""
    return svg(height, title, theme, body, css)


def series_card(series: Series, episode: dict, thumb: bytes | None, theme: str) -> str:
    t = THEMES[theme]
    x, width = 300, WIDTH - 300 - 28
    lines = wrap(episode["title"], 21, width, 2, weight=1.06)
    blurb_y = 84 + 27 * (len(lines) - 1) + 29
    image = (
        f'<image x="20" y="20" width="256" height="144" preserveAspectRatio="xMidYMid slice" '
        f'clip-path="url(#thumb)" href="data:image/jpeg;base64,{b64encode(thumb).decode()}"/>'
        if thumb else f'<rect x="20" y="20" width="256" height="144" rx="8" fill="{t["grid"]}" opacity=".35"/>'
    )
    css = ".k{font-size:12px}.t{font-size:21px;font-weight:600}.b{font-size:15px}.s{font-size:12.5px}"
    title = (f"{series.name}, {series.kicker}. Latest episode, number {episode['number']}: "
             f"{episode['title']}. {series.blurb}.")
    body = f"""<defs><clipPath id="thumb"><rect x="20" y="20" width="256" height="144" rx="8"/></clipPath></defs>
{image}
<rect x="20.5" y="20.5" width="255" height="143" rx="7.5" fill="none" stroke="{t['border']}"/>
{text(x, 46, f"{series.name} · {series.kicker}".upper(), "mono k", t["muted"])}
{text(WIDTH - 28, 46, f"EP {episode['number']}", "mono k", t["accent"], anchor="end")}
{chr(10).join(text(x, 84 + 27 * i, line, "sans t", t["ink"]) for i, line in enumerate(lines))}
{text(x, blurb_y, wrap(series.blurb, 15, width, 1)[0], "sans b", t["muted"])}
{text(x, 161, series.repo, "code s", t["muted"])}
{text(WIDTH - 28, 161, day(episode["published"]), "code s", t["muted"], anchor="end")}"""
    return svg(184, title, theme, body, css)


def writing_card(posts: list[dict], theme: str) -> str:
    t = THEMES[theme]
    css = ".k{font-size:12px}.t{font-size:17px;font-weight:600}.s{font-size:12.5px}"
    rows, y = [], 64
    for i, post in enumerate(posts):
        if i:
            rows.append(f'<line x1="28" x2="{WIDTH - 28}" y1="{y - 22}" y2="{y - 22}" stroke="{t["border"]}"/>')
        lines = wrap(post["title"], 17, WIDTH - 56 - 120, 2, weight=1.05)
        rows.append(text(WIDTH - 28, y + 22, day(post["published"]), "code s", t["muted"], anchor="end"))
        rows += [text(28, y + 22 + 24 * j, line, "sans t", t["ink"]) for j, line in enumerate(lines)]
        y += 24 * len(lines) + 40
    title = "Latest writing on Substack: " + "; ".join(p["title"] for p in posts)
    body = (text(28, 42, "LATEST WRITING · ADRIANNENU.SUBSTACK.COM", "mono k", t["muted"]) + "\n"
            + "\n".join(rows))
    return svg(y - 2, title, theme, body, css)


# Build --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--previous", type=Path, help="the last build, to fall back on")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    state: dict = {"episodes": {}, "posts": []}
    if args.previous and (args.previous / "state.json").exists():
        state = json.loads((args.previous / "state.json").read_text())

    try:
        for key, episode in latest_episodes(fetch(UPLOADS_FEED)).items():
            old = state["episodes"].get(key)
            if old is None or episode["number"] >= old["number"]:
                state["episodes"][key] = episode
    except (OSError, http.client.HTTPException, ET.ParseError) as error:
        print(f"keeping the last episodes, as YouTube failed: {error}", file=sys.stderr)
    try:
        state["posts"] = latest_posts(fetch(SUBSTACK_FEED)) or state["posts"]
    except (OSError, http.client.HTTPException, ET.ParseError, TypeError, ValueError) as error:
        print(f"keeping the last posts, as Substack failed: {error}", file=sys.stderr)

    missing = [s.name for s in SERIES if s.key not in state["episodes"]]
    if missing or not state["posts"]:
        print(f"nothing to show for {missing or 'the writing'}; leaving the last build as it is",
              file=sys.stderr)
        return 1

    size = 20
    frames = glider_loop(size, gliders=8)
    files = {}
    for theme in THEMES:
        files[f"hero-{theme}.svg"] = hero(state, frames, size, theme)
        files[f"writing-{theme}.svg"] = writing_card(state["posts"], theme)
    for series in SERIES:
        episode = state["episodes"][series.key]
        thumb = thumbnail(episode["video"], args.previous, args.out)
        for theme in THEMES:
            files[f"{series.key}-{theme}.svg"] = series_card(series, episode, thumb, theme)

    for name, content in files.items():
        (args.out / name).write_text(content, encoding="utf-8")
    (args.out / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    print(f"built {len(files)} images in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
