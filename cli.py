"""Command line entry point.

  python -m energy_signals demo              # offline, bundled sample articles
  python -m energy_signals run               # live RSS feeds -> extract -> reports
  python -m energy_signals pdf report.pdf    # extract signals from a PDF report
  python -m energy_signals report            # rebuild reports from the database
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List

from . import config, fetch, report, store
from .extract import get_extractor
from .schema import Article

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_articles.json"


def process(articles: List[Article], extractor, db_path: str) -> int:
    conn = store.connect(db_path)
    done = store.seen_ids(conn, [a.id for a in articles])
    fresh = [a for a in articles if a.id not in done]
    print(f"{len(articles)} articles, {len(fresh)} new")
    saved = 0
    for i, art in enumerate(fresh, start=1):
        sig = extractor.extract(art)
        if sig is None:
            continue
        store.save(conn, art, sig, extractor.name)
        saved += 1
        print(f"  [{i}/{len(fresh)}] {sig.market.value:9} {sig.direction.value:8} {art.title[:70]}")
    conn.close()
    return saved


def rebuild(db_path: str, out_dir: str, days: int) -> None:
    conn = store.connect(db_path)
    df = store.load(conn, days=days)
    conn.close()
    paths = report.build_all(df, out_dir, days)
    print(f"{len(df)} relevant signals -> " + ", ".join(str(p) for p in paths.values()))


def load_sample() -> List[Article]:
    from datetime import date

    raw = json.loads(SAMPLE.read_text(encoding="utf-8"))
    today = date.today().isoformat()
    return [Article(id=fetch.make_id(r["title"]), source=r["source"], title=r["title"], text=r["text"],
                    url=r.get("url", ""), published=today) for r in raw]


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="energy_signals", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=config.DB_PATH)
    p.add_argument("--out", default=config.OUT_DIR)
    p.add_argument("--days", type=int, default=7, help="report window in days")
    p.add_argument("--provider", choices=["auto", "mock", "claude", "gemini", "ollama", "custom"], default="auto",
                   help="which extractor to use (auto picks one from your environment variables)")
    p.add_argument("--mock", action="store_true", help="same as --provider mock")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="process bundled sample articles (offline)")
    sub.add_parser("run", help="fetch live feeds and process them")
    pdf = sub.add_parser("pdf", help="process a PDF report")
    pdf.add_argument("path")
    sub.add_parser("report", help="rebuild reports from the database")
    args = p.parse_args(argv)

    if args.cmd == "report":
        return rebuild(args.db, args.out, args.days)

    provider = "mock" if args.mock else args.provider
    if provider == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "claude"
        elif os.environ.get("LLM_API_KEY"):
            provider = "gemini"
        else:
            provider = "mock"
            print("No API key found, using the free keyword baseline (see README for free AI options).")
    if provider == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY first.")
    if provider == "gemini" and not os.environ.get("LLM_API_KEY"):
        sys.exit("Set LLM_API_KEY to your Google AI Studio key first.")
    extractor = get_extractor(provider)
    print(f"extractor: {extractor.name}")

    if args.cmd == "demo":
        articles = load_sample()
    elif args.cmd == "pdf":
        articles = fetch.pdf_to_articles(args.path)
    else:
        articles = fetch.fetch_all(config.default_feeds())
    process(articles, extractor, args.db)
    rebuild(args.db, args.out, args.days)
