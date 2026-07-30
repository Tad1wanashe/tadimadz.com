#!/usr/bin/env python3
"""Regenerate books.html and writing.html for tadimadz.com.

Fetches Goodreads shelves (public RSS) and the Substack archive (public API),
merges in the hand-curated data/medium.json (Medium blocks scrapers), and
renders the two data-driven pages. index.html is hand-edited and untouched.

Usage: python3 scripts/sync.py [--offline]
  --offline  render from the JSON already in data/ without fetching anything
"""

import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

GOODREADS_USER = "127174249"
SHELVES = ["read", "currently-reading", "to-read"]
SUBSTACK = "https://tadiwanashe.substack.com"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tadimadz.com sync"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_goodreads():
    shelves = {}
    for shelf in SHELVES:
        url = f"https://www.goodreads.com/review/list_rss/{GOODREADS_USER}?shelf={shelf}"
        root = ET.fromstring(fetch(url))
        books = []
        for item in root.iter("item"):
            g = lambda tag: (item.findtext(tag) or "").strip()
            books.append({
                "title": html.unescape(g("title")),
                "author": html.unescape(g("author_name")),
                "rating": int(g("user_rating") or 0),
                "date_read": g("user_read_at"),
                "date_added": g("user_date_added"),
                "link": re.sub(r"\?.*$", "", g("link")),
            })
        shelves[shelf] = books
    return shelves


def fetch_substack():
    raw = json.loads(fetch(f"{SUBSTACK}/api/v1/archive?sort=new&limit=50"))
    return [{
        "title": (p.get("title") or "").strip(),
        "subtitle": (p.get("subtitle") or "").strip(),
        "date": (p.get("post_date") or "")[:10],
        "url": p.get("canonical_url"),
        "source": "Substack",
    } for p in raw]


def esc(s):
    return html.escape(s or "", quote=True)


def page(title, body):
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Tadiwanashe Madzivire</title>
<link rel="stylesheet" href="style.css">
</head>
<body>

<nav class="top"><a href="index.html">Tadiwanashe Madzivire</a></nav>

{body}

<footer>Generated {datetime.now(timezone.utc).strftime("%d %B %Y")} ·
<a href="index.html">home</a></footer>

</body>
</html>
"""


def book_li(b, show_stars=True):
    cls = {5: "great", 4: "good"}.get(b["rating"], "")
    stars = f' <span class="stars">{"★" * b["rating"]}</span>' if show_stars and b["rating"] else ""
    inner = f'<a href="{esc(b["link"])}">{esc(b["title"])}</a> — {esc(b["author"])}{stars}'
    return f'  <li class="{cls}">{inner}</li>' if cls else f"  <li>{inner}</li>"


def render_books(shelves):
    read = shelves["read"]
    current = shelves["currently-reading"]
    to_read = shelves["to-read"]

    def sort_key(b):
        for field in ("date_read", "date_added"):
            if b.get(field):
                try:
                    return parsedate_to_datetime(b[field])
                except (TypeError, ValueError):
                    pass
        return datetime.min.replace(tzinfo=timezone.utc)

    read = sorted(read, key=sort_key, reverse=True)

    sections = ["<h1>Books</h1>",
                f"""<p>What I've been reading, pulled from
<a href="https://www.goodreads.com/user/show/{GOODREADS_USER}">my Goodreads</a>.
<span class="great">Green books</span> were particularly great (five stars);
<span class="good">blue books</span> were substantially above average (four).
The rest I'll let sit unjudged.</p>"""]

    if current:
        sections.append(f"<h2>Currently reading</h2>\n<ul>\n" +
                        "\n".join(book_li(b, show_stars=False) for b in current) + "\n</ul>")

    sections.append(f"<h2>Read ({len(read)})</h2>\n<ul>\n" +
                    "\n".join(book_li(b) for b in read) + "\n</ul>")

    if to_read:
        sections.append(
            f"<h2>The antilibrary ({len(to_read)})</h2>\n"
            "<p class=\"small muted\">Unread, in the Umberto Eco sense.</p>\n<ul>\n" +
            "\n".join(book_li(b, show_stars=False) for b in to_read) + "\n</ul>")

    (ROOT / "books.html").write_text(page("Books", "\n\n".join(sections)), encoding="utf-8")


def render_writing(posts):
    posts = sorted([p for p in posts if p.get("title")],
                   key=lambda p: p.get("date") or "", reverse=True)

    body = ["<h1>Writing</h1>",
            f"""<p>Essays and notes, most recent first. Longer pieces live on
<a href="{SUBSTACK}">Substack</a>; older ones on
<a href="https://tad1wanashe.medium.com">Medium</a>.</p>"""]

    year = None
    items = []
    for p in posts:
        y = (p.get("date") or "????")[:4]
        if y != year:
            if items:
                body.append("<ul>\n" + "\n".join(items) + "\n</ul>")
                items = []
            year = y
            body.append(f"<h2>{esc(year)}</h2>")
        try:
            nice_date = datetime.strptime(p["date"], "%Y-%m-%d").strftime("%d %b")
        except (KeyError, ValueError):
            nice_date = ""
        sub = f' <span class="muted">— {esc(p["subtitle"])}</span>' if p.get("subtitle") else ""
        items.append(f'  <li><a href="{esc(p["url"])}">{esc(p["title"])}</a>{sub} '
                     f'<span class="date">{nice_date} · {esc(p["source"])}</span></li>')
    if items:
        body.append("<ul>\n" + "\n".join(items) + "\n</ul>")

    (ROOT / "writing.html").write_text(page("Writing", "\n\n".join(body)), encoding="utf-8")


def main():
    offline = "--offline" in sys.argv

    if offline:
        shelves = json.loads((DATA / "books.json").read_text())
        substack = json.loads((DATA / "substack_posts.json").read_text())
    else:
        shelves = fetch_goodreads()
        substack = fetch_substack()
        (DATA / "books.json").write_text(json.dumps(shelves, indent=1), encoding="utf-8")
        (DATA / "substack_posts.json").write_text(json.dumps(substack, indent=1), encoding="utf-8")

    medium = json.loads((DATA / "medium.json").read_text())
    for p in substack:
        p.setdefault("source", "Substack")
        p["date"] = (p.get("date") or "")[:10]

    render_books(shelves)
    render_writing(substack + medium)
    print(f"books: {sum(len(v) for v in shelves.values())} across {len(shelves)} shelves; "
          f"writing: {len(substack)} substack + {len(medium)} medium")


if __name__ == "__main__":
    main()
