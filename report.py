"""Reports: CSV table, Markdown brief, self-contained HTML dashboard, plus a simple sentiment index."""
from __future__ import annotations

import html
from datetime import date
from pathlib import Path

import pandas as pd

SIGN = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}


def with_score(df: pd.DataFrame) -> pd.DataFrame:
    """Add a signed, confidence-weighted score: +1 bullish, -1 bearish, scaled by confidence."""
    out = df.copy()
    out["score"] = out["direction"].map(SIGN).fillna(0.0) * out["confidence"]
    return out


def sentiment_index(df: pd.DataFrame) -> pd.DataFrame:
    """Daily mean score per market. Positive = upward price pressure in the news flow."""
    if df.empty:
        return pd.DataFrame(columns=["published", "market", "signals", "net_score"])
    scored = with_score(df)
    grp = scored.groupby(["published", "market"]).agg(signals=("score", "size"), net_score=("score", "mean"))
    return grp.round(2).reset_index().sort_values(["published", "market"], ascending=[False, True])


def write_csv(df: pd.DataFrame, path: Path) -> None:
    flat = df.copy()
    for col in ("instruments", "key_figures"):
        flat[col] = flat[col].apply(lambda xs: "; ".join(xs))
    flat.drop(columns=["article_id"], errors="ignore").to_csv(path, index=False)


def _arrow(direction: str) -> str:
    return {"bullish": "▲", "bearish": "▼"}.get(direction, "–")


def write_markdown(df: pd.DataFrame, path: Path, days: int) -> None:
    lines = [f"# European Energy Signals Brief", f"_Generated {date.today().isoformat()} · last {days} days · "
             f"{len(df)} relevant signals_", ""]
    if df.empty:
        lines.append("No relevant signals found.")
    else:
        idx = sentiment_index(df)
        latest = idx[idx["published"] == idx["published"].max()]
        lines += ["## Net sentiment (latest day)", "", "| Market | Signals | Net score |", "|---|---|---|"]
        lines += [f"| {r.market} | {r.signals} | {r.net_score:+.2f} |" for r in latest.itertuples()]
        lines.append("")
        for market, sub in df.groupby("market"):
            lines += [f"## {market.title()}", "", "| Date | Region | Dir | Driver | Summary | Figures | Conf |",
                      "|---|---|---|---|---|---|---|"]
            for r in sub.sort_values("confidence", ascending=False).head(10).itertuples():
                summary = r.summary.replace("|", "/")
                figures = ", ".join(r.key_figures).replace("|", "/")
                lines.append(f"| {r.published} | {r.region} | {_arrow(r.direction)} {r.direction} | {r.driver} | "
                             f"[{summary}]({r.url}) | {figures} | {r.confidence:.2f} |"
                             if r.url.startswith("http") else
                             f"| {r.published} | {r.region} | {_arrow(r.direction)} {r.direction} | {r.driver} | "
                             f"{summary} | {figures} | {r.confidence:.2f} |")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


CSS = """
body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:1100px;padding:0 1rem;color:#1a1a1a;background:#fff}
h1{margin-bottom:.2rem} .sub{color:#666;margin-top:0}
.cards{display:flex;gap:1rem;flex-wrap:wrap;margin:1.5rem 0}
.card{border:1px solid #ddd;border-radius:8px;padding:.8rem 1.2rem;min-width:140px}
.card b{font-size:1.6rem;display:block}
.up{color:#0a7d33}.down{color:#b3261e}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border-bottom:1px solid #eee;padding:.45rem .5rem;text-align:left;vertical-align:top}
th{background:#f6f6f6}
@media (prefers-color-scheme: dark){
 body{background:#161616;color:#eee}.card{border-color:#444}th{background:#222}td,th{border-color:#333}
 .sub{color:#aaa}.up{color:#5ad17e}.down{color:#ff8a80}a{color:#8ab4f8}}
"""


def write_html(df: pd.DataFrame, path: Path, days: int) -> None:
    e = html.escape
    cards, rows = [], []
    if not df.empty:
        idx = sentiment_index(df)
        latest = idx[idx["published"] == idx["published"].max()]
        for r in latest.itertuples():
            cls = "up" if r.net_score > 0 else "down" if r.net_score < 0 else ""
            cards.append(f'<div class="card"><span>{e(r.market.title())} ({r.signals})</span>'
                         f'<b class="{cls}">{r.net_score:+.2f}</b></div>')
        for r in df.itertuples():
            cls = "up" if r.direction == "bullish" else "down" if r.direction == "bearish" else ""
            link = f'<a href="{e(r.url)}">{e(r.summary)}</a>' if r.url.startswith("http") else e(r.summary)
            rows.append(f"<tr><td>{e(r.published)}</td><td>{e(r.market)}</td><td>{e(r.region)}</td>"
                        f'<td class="{cls}">{_arrow(r.direction)} {e(r.direction)}</td><td>{e(r.driver)}</td>'
                        f"<td>{link}</td><td>{e(', '.join(r.key_figures))}</td><td>{r.confidence:.2f}</td></tr>")
    page = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>European Energy Signals</title><style>{CSS}</style></head><body>"
            f"<h1>European Energy Signals</h1><p class='sub'>Last {days} days · {len(df)} relevant signals · "
            f"net score: +1 = upward price pressure, -1 = downward</p>"
            f"<div class='cards'>{''.join(cards)}</div>"
            f"<table><tr><th>Date</th><th>Market</th><th>Region</th><th>Direction</th><th>Driver</th>"
            f"<th>Summary</th><th>Figures</th><th>Conf</th></tr>{''.join(rows)}</table></body></html>")
    path.write_text(page, encoding="utf-8")


def build_all(df: pd.DataFrame, out_dir: str, days: int) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {"csv": out / "signals.csv", "md": out / "brief.md", "html": out / "dashboard.html"}
    write_csv(df, paths["csv"])
    write_markdown(df, paths["md"], days)
    write_html(df, paths["html"], days)
    return paths
