"""Offline tests: no network, no API key."""
import json
from types import SimpleNamespace

import pytest

from energy_signals import fetch, report, store
from energy_signals.cli import load_sample, process
from energy_signals.extract import HeuristicExtractor, LLMExtractor
from energy_signals.schema import Article, Direction, Market, Signal


def art(title, text):
    return Article(id=fetch.make_id(title), source="t", title=title, text=text, published="2099-01-01")


def test_heuristic_bullish_gas():
    sig = HeuristicExtractor().extract(art("TTF jumps on Norwegian outage", "TTF rose 6% to 38.4 EUR/MWh after an outage cut flows."))
    assert sig.relevant and sig.market == Market.gas and sig.direction == Direction.bullish
    assert "TTF" in sig.instruments and any("38.4" in f for f in sig.key_figures)


def test_heuristic_bearish_emissions():
    sig = HeuristicExtractor().extract(art("EUA falls", "EU carbon allowances fell 3% on weak demand."))
    assert sig.market == Market.emissions and sig.direction == Direction.bearish


def test_irrelevant_text_flagged():
    sig = HeuristicExtractor().extract(art("Cycle lanes approved", "The council voted on Tuesday."))
    assert not sig.relevant


def test_llm_extractor_parses_tool_call():
    payload = {"relevant": True, "market": "gas", "region": "NL", "direction": "bullish", "driver": "outages",
               "instruments": ["TTF"], "summary": "TTF rose after an outage.", "key_figures": ["6%"], "confidence": 0.8}

    class FakeMessages:
        def create(self, **kw):
            assert kw["tool_choice"]["name"] == "record_signal"
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=payload)])

    ex = LLMExtractor(client=SimpleNamespace(messages=FakeMessages()), model="test")
    sig = ex.extract(art("x", "y"))
    assert isinstance(sig, Signal) and sig.driver.value == "outages"


def test_llm_extractor_survives_api_errors(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    class Boom:
        def create(self, **kw):
            raise RuntimeError("api down")

    ex = LLMExtractor(client=SimpleNamespace(messages=Boom()), model="test", retries=2)
    assert ex.extract(art("x", "y")) is None


def test_store_dedupes_and_loads(tmp_path):
    db = str(tmp_path / "t.db")
    arts = load_sample()
    for a in arts:
        a.published = "2099-01-01"
    assert process(arts, HeuristicExtractor(), db) == len(arts)
    assert process(arts, HeuristicExtractor(), db) == 0  # second run skips everything
    conn = store.connect(db)
    df = store.load(conn, days=100000)
    assert 0 < len(df) < len(arts)  # irrelevant article filtered out
    assert isinstance(df.iloc[0]["key_figures"], list)


def test_sentiment_index_sign(tmp_path):
    db = str(tmp_path / "t.db")
    arts = [art("TTF jumps on outage", "TTF rose 5% on an outage and tight supply."),
            art("TTF slumps on surplus", "TTF fell 5% as supply was ample and storage full, a surplus.")]
    process(arts, HeuristicExtractor(), db)
    df = store.load(store.connect(db), days=100000)
    scored = report.with_score(df)
    assert scored["score"].max() > 0 > scored["score"].min()


def test_reports_written_and_escaped(tmp_path):
    db = str(tmp_path / "t.db")
    a = art("TTF <script>alert(1)</script> jumps on outage", "TTF rose 6% on an outage.")
    process([a], HeuristicExtractor(), db)
    df = store.load(store.connect(db), days=100000)
    paths = report.build_all(df, str(tmp_path / "out"), 7)
    page = paths["html"].read_text(encoding="utf-8")
    assert "<script>alert" not in page
    assert paths["csv"].exists() and paths["md"].read_text(encoding="utf-8").startswith("# European")


def test_chunk_text_respects_limit():
    text = "\n\n".join(["para " * 50] * 40)
    chunks = fetch.chunk_text(text, max_chars=1000)
    assert all(len(c) <= 1000 for c in chunks) and len(chunks) > 1
    assert fetch.chunk_text("") == []


def test_clean_html():
    assert fetch.clean_html("<a href='x'>TTF&nbsp;up</a>  <b>6%</b>") == "TTF up 6%"


def test_compat_extractor_parses_json(monkeypatch):
    from energy_signals.extract import OpenAICompatExtractor

    content = '```json\n{"relevant": true, "market": "power", "region": "DE", "direction": "bearish", "driver": "weather", "instruments": [], "summary": "Wind output lowered prices.", "key_figures": ["40 GW"], "confidence": 0.7}\n```'

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr("requests.post", lambda *a, **k: R())
    sig = OpenAICompatExtractor("http://x", "k", "m").extract(art("a", "b"))
    assert sig.market == Market.power and sig.direction == Direction.bearish


def test_compat_extractor_bad_json_returns_none(monkeypatch):
    from energy_signals.extract import OpenAICompatExtractor

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "not json"}}]}

    monkeypatch.setattr("requests.post", lambda *a, **k: R())
    assert OpenAICompatExtractor("http://x", "k", "m").extract(art("a", "b")) is None
