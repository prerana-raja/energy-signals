# energy-signals

Turns unstructured European energy news and PDF reports into a structured table of market signals for gas, power and carbon. It also builds a daily brief and a small HTML dashboard.

I built it to practise the daily workflow of a commercial analyst on an energy trading desk: a lot of unstructured text comes in, and traders need something they can scan, filter and chart.

## What it does

```
RSS feeds / PDF reports
        │  fetch.py      download, clean HTML, dedupe, chunk long PDFs
        ▼
   Article objects
        │  extract.py    Claude with a forced tool call returns a validated Signal
        ▼
   Signal (pydantic)     market, region, direction, driver, instruments, key figures, confidence
        │  store.py      SQLite, each article processed once, history builds up
        ▼
   report.py             signals.csv · brief.md · dashboard.html · daily sentiment index
```

Each article becomes one row:

| field | example |
|---|---|
| market | gas / power / emissions / multi |
| region | NL, DE, EU |
| direction | bullish (price up) / bearish (price down) / neutral |
| driver | outages, weather, storage, flows, regulation, geopolitics ... |
| instruments | TTF, NBP, EUA |
| key_figures | `38.4 EUR/MWh`, `25 mcm/d` |
| confidence | 0 to 1 |

Design choices worth knowing:

- **Structured output by construction.** The model must answer through a tool whose input schema is generated from the pydantic `Signal` model, then the result is validated. No free-text parsing.
- **Grounding rules in the prompt.** The model may only use facts in the text, must copy figures with units, and must mark off-topic articles `relevant=false`.
- **Idempotent.** Article ids are hashed; re-running only processes new articles, so API cost stays low.
- **Baseline extractor.** `--mock` uses keyword rules with no API key. It is crude on purpose: it lets the pipeline and tests run offline, and gives something to compare the LLM against. For example, on the bundled sample it tags the French nuclear story as region DE because the text also mentions Germany. The LLM handles that case.
- **Sentiment index.** Direction x confidence, averaged per market per day. It is a simple news-flow indicator, not a trading signal.

## Quick start

```bash
git clone <your-repo-url> && cd energy-signals
pip install -r requirements.txt

python -m energy_signals demo            # offline, bundled sample, keyword baseline
export ANTHROPIC_API_KEY=sk-ant-...      # for the LLM extractor
python -m energy_signals demo            # same sample, now through Claude
python -m energy_signals run             # live Google News RSS queries (see config.py)
python -m energy_signals pdf report.pdf  # any PDF: ACER, ENTSOG, a broker note ...
python -m energy_signals report --days 14
```

Outputs land in `output/`. The default model is set in `config.py` and can be overridden with `SIGNALS_MODEL`.

Run the tests (no network or key needed): `pytest -q`

## Free options (no paid API needed)

| Option | Cost | Setup |
|---|---|---|
| Keyword baseline | free, no account | `python -m energy_signals --provider mock demo` |
| Google Gemini (AI Studio free tier) | free tier, no card | create a key at aistudio.google.com, then `--provider gemini` |
| Ollama (runs on your own PC) | free | install Ollama, `ollama pull llama3.1:8b`, then `--provider ollama` |
| Claude API | paid | `ANTHROPIC_API_KEY`, then `--provider claude` |

Free-tier limits and model names change often. Override the model with `LLM_MODEL` and the pause between calls with `LLM_DELAY` (seconds).

## Project layout

```
energy_signals/
  config.py    feed queries, model name
  fetch.py     RSS and PDF ingestion, dedupe, chunking
  extract.py   LLM extractor and keyword baseline
  schema.py    Signal model and enums
  store.py     SQLite persistence
  report.py    CSV, Markdown, HTML, sentiment index
  cli.py       demo / run / pdf / report commands
tests/         10 offline tests, including a fake LLM client
data/          sample articles for the offline demo
examples/      sample output from the keyword baseline
```

## Limitations

- RSS items carry only a title and a short snippet, so the LLM sees less than a full article. Full-text fetching and paywalled sources are not handled.
- No evaluation set yet. A next step is hand-labelling around 50 articles and measuring direction accuracy for the LLM versus the baseline.
- The sentiment index is not backtested against price moves.

## Ideas for next steps

- Join the daily index with TTF or EUA price history and test whether it leads or lags.
- Add storage and LNG data from public sources next to the news signals.
- Schedule `run` daily with cron or GitHub Actions and publish the dashboard.
