"""Settings. Edit FEED_QUERIES to change what the pipeline watches."""
import os
from urllib.parse import quote_plus

MODEL = os.environ.get("SIGNALS_MODEL", "claude-sonnet-5-5")
DB_PATH = os.environ.get("SIGNALS_DB", "signals.db")
OUT_DIR = os.environ.get("SIGNALS_OUT", "output")

# Google News RSS search queries. "when:2d" limits results to the last two days.
FEED_QUERIES = [
    "TTF gas price Europe when:2d",
    "NBP UK gas price when:2d",
    "European gas storage LNG when:2d",
    "EU carbon price EUA ETS when:2d",
    "German power prices baseload when:2d",
    "European wind solar power generation when:2d",
]


def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-GB&gl=GB&ceid=GB:en"


def default_feeds():
    """Returns a list of (name, url) tuples."""
    return [(f"GoogleNews: {q.replace(' when:2d', '')}", google_news_url(q)) for q in FEED_QUERIES]
