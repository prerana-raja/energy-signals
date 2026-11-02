"""SQLite storage so each article is processed once and history builds up over time."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable, Set

import pandas as pd

from .schema import Article, Signal

DDL = """
CREATE TABLE IF NOT EXISTS signals (
    article_id TEXT PRIMARY KEY,
    published TEXT, fetched_at TEXT, source TEXT, title TEXT, url TEXT,
    relevant INTEGER, market TEXT, region TEXT, direction TEXT, driver TEXT,
    instruments TEXT, summary TEXT, key_figures TEXT, confidence REAL, extractor TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_pub ON signals(published);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    return conn


def seen_ids(conn: sqlite3.Connection, ids: Iterable[str]) -> Set[str]:
    ids = list(ids)
    if not ids:
        return set()
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT article_id FROM signals WHERE article_id IN ({marks})", ids).fetchall()
    return {r[0] for r in rows}


def save(conn: sqlite3.Connection, art: Article, sig: Signal, extractor: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (art.id, art.published, datetime.now(timezone.utc).isoformat(timespec="seconds"), art.source, art.title,
         art.url, int(sig.relevant), sig.market.value, sig.region, sig.direction.value, sig.driver.value,
         json.dumps(sig.instruments), sig.summary, json.dumps(sig.key_figures), sig.confidence, extractor),
    )
    conn.commit()


def load(conn: sqlite3.Connection, days: int = 7, relevant_only: bool = True) -> pd.DataFrame:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    query = "SELECT * FROM signals WHERE published >= ?" + (" AND relevant = 1" if relevant_only else "")
    df = pd.read_sql_query(query + " ORDER BY published DESC, confidence DESC", conn, params=(since,))
    for col in ("instruments", "key_figures"):
        df[col] = df[col].apply(lambda s: json.loads(s) if s else [])
    return df
