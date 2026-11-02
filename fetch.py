"""Ingestion: RSS feeds and PDF reports -> Article objects."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List

import feedparser
import requests

from .schema import Article

UA = {"User-Agent": "energy-signals/0.1 (research project)"}
TAG_RE = re.compile(r"<[^>]+>")


def make_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def clean_html(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", raw or ""))).strip()


def _entry_date(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def fetch_feed(name: str, url: str, max_age_days: int = 2, limit: int = 15) -> List[Article]:
    """Download one RSS feed and return recent entries as Articles."""
    resp = requests.get(url, headers=UA, timeout=20)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    articles: List[Article] = []
    for entry in feed.entries[:limit]:
        when = _entry_date(entry)
        if when and when < cutoff:
            continue
        title = clean_html(entry.get("title", ""))
        body = clean_html(entry.get("summary", ""))
        link = entry.get("link", "")
        articles.append(
            Article(
                id=make_id(link or title),
                source=name,
                title=title,
                text=body or title,
                url=link,
                published=(when or datetime.now(timezone.utc)).date().isoformat(),
            )
        )
    return articles


def fetch_all(feeds: Iterable[tuple[str, str]], **kwargs) -> List[Article]:
    """Fetch every feed, skip ones that fail, dedupe by article id and by title."""
    seen_ids, seen_titles, out = set(), set(), []
    for name, url in feeds:
        try:
            batch = fetch_feed(name, url, **kwargs)
        except Exception as exc:  # network errors should not kill the run
            print(f"[warn] feed failed: {name}: {exc}")
            continue
        for art in batch:
            key = art.title.lower()
            if art.id in seen_ids or key in seen_titles:
                continue
            seen_ids.add(art.id)
            seen_titles.add(key)
            out.append(art)
    return out


def chunk_text(text: str, max_chars: int = 6000) -> List[str]:
    """Split long text on paragraph boundaries into chunks of at most max_chars."""
    chunks, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > max_chars:  # a single huge paragraph
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def pdf_to_articles(path: str, max_chars: int = 6000) -> List[Article]:
    """Read a PDF report and return one Article per text chunk."""
    from pypdf import PdfReader

    p = Path(path)
    reader = PdfReader(str(p))
    text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    today = datetime.now(timezone.utc).date().isoformat()
    arts = []
    for i, chunk in enumerate(chunk_text(text, max_chars), start=1):
        arts.append(
            Article(
                id=make_id(p.name, str(i), chunk[:80]),
                source=f"PDF: {p.name}",
                title=f"{p.stem} (part {i})",
                text=chunk,
                url=str(p),
                published=today,
            )
        )
    return arts
