"""Turning text into a Signal. Two extractors share one interface:

* LLMExtractor: calls Claude and forces a structured answer through tool use.
* HeuristicExtractor: keyword rules, no API key. A baseline and an offline test double.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional

from .config import MODEL
from .schema import Article, Direction, Driver, Market, Signal

SYSTEM_PROMPT = """You are an analyst on a European energy trading desk (gas, power, carbon).
Read the text and record ONE structured market signal by calling the record_signal tool.

Rules:
- Use only facts stated in the text. Never invent numbers, prices or events.
- direction is the likely PRICE impact on the market you name: bullish = upward, bearish = downward.
- If the text has no information useful for European gas, power or carbon trading, set relevant=false.
- If several markets are affected, pick market="multi" and describe the main driver.
- key_figures must be copied from the text with their units. Leave empty if none.
- Lower confidence when the text is vague, speculative or only repeats old news.
"""


class LLMExtractor:
    name = "llm"

    def __init__(self, client=None, model: str = MODEL, retries: int = 3):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.client = client
        self.model = model
        self.retries = retries
        self.tool = {
            "name": "record_signal",
            "description": "Record the structured market signal for this text.",
            "input_schema": Signal.model_json_schema(),
        }

    def extract(self, article: Article) -> Optional[Signal]:
        prompt = f"Source: {article.source}\nDate: {article.published}\nTitle: {article.title}\n\n{article.text[:6000]}"
        for attempt in range(self.retries):
            try:
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=800,
                    system=SYSTEM_PROMPT,
                    tools=[self.tool],
                    tool_choice={"type": "tool", "name": "record_signal"},
                    messages=[{"role": "user", "content": prompt}],
                )
                for block in resp.content:
                    if getattr(block, "type", "") == "tool_use":
                        return Signal.model_validate(block.input)
                return None
            except Exception as exc:
                if attempt == self.retries - 1:
                    print(f"[warn] extraction failed for '{article.title[:50]}': {exc}")
                    return None
                time.sleep(2**attempt)
        return None



# --- free / OpenAI-compatible backends (Gemini free tier, Ollama, Groq, ...) ----------

PRESETS = {
    # name: (base_url, default_model, seconds to wait between calls)
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", 6.0),
    "ollama": ("http://localhost:11434/v1", "llama3.1:8b", 0.0),
}

JSON_INSTRUCTIONS = """
Reply with ONLY a JSON object, no other text, using exactly these keys:
relevant (true/false), market (one of: gas, power, emissions, multi, other), region (string),
direction (one of: bullish, bearish, neutral), driver (one of: supply, demand, weather, storage, flows,
outages, regulation, geopolitics, fuel_switching, other), instruments (list of strings),
summary (one sentence, max 30 words), key_figures (list of strings), confidence (number 0 to 1).
"""


class OpenAICompatExtractor:
    """Works with any server that speaks the OpenAI chat-completions format."""

    name = "llm-compat"

    def __init__(self, base_url: str, api_key: str, model: str, delay: float = 0.0, retries: int = 4):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key, self.model, self.delay, self.retries = api_key, model, delay, retries

    def _call(self, prompt: str) -> str:
        import requests

        body = {"model": self.model, "temperature": 0,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT + JSON_INSTRUCTIONS},
                             {"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        for attempt in range(self.retries):
            resp = requests.post(self.url, json=body, headers=headers, timeout=90)
            if resp.status_code == 429 and attempt < self.retries - 1:  # rate limited: wait and retry
                time.sleep(10 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        raise RuntimeError("rate limited")

    def extract(self, article: Article) -> Optional[Signal]:
        import json

        prompt = f"Source: {article.source}\nDate: {article.published}\nTitle: {article.title}\n\n{article.text[:6000]}"
        try:
            raw = self._call(prompt).strip()
            raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
            sig = Signal.model_validate(json.loads(raw))
        except Exception as exc:
            print(f"[warn] extraction failed for '{article.title[:50]}': {exc}")
            sig = None
        if self.delay:
            time.sleep(self.delay)
        return sig


# --- keyword baseline -------------------------------------------------------

MARKET_WORDS = {
    Market.gas: ["ttf", "nbp", "lng", "natural gas", " gas ", "storage", "pipeline", "bcm"],
    Market.power: ["power price", "electricity", "baseload", "wind", "solar", "nuclear", "grid", "gw", "heatwave"],
    Market.emissions: ["eua", "carbon", "ets", "emission", "allowance", "co2"],
}
BULLISH = ["surge", "rise", "rose", "jump", "cold snap", "outage", "disruption", "shortfall", "tight",
           "cut supply", "halt", "maintenance", "heatwave", "drought", "higher", "climb", "gain"]
BEARISH = ["fall", "fell", "drop", "slump", "mild", "ample", "oversupply", "record wind", "weak demand",
           "lower", "decline", "slide", "plunge", "full storage", "surplus", "ease"]
DRIVER_WORDS = {
    Driver.storage: ["storage", "inventories"],
    Driver.outages: ["outage", "maintenance", "halt", "unplanned"],
    Driver.weather: ["cold", "mild", "heatwave", "wind", "solar", "temperature", "drought"],
    Driver.regulation: ["regulation", "eu commission", "ets", "reform", "policy", "tax", "cap"],
    Driver.flows: ["flows", "pipeline", "interconnector", "nominations"],
    Driver.supply: ["lng", "supply", "cargo", "production", "output"],
    Driver.geopolitics: ["sanction", "russia", "ukraine", "war", "embargo", "geopolit"],
    Driver.demand: ["demand", "consumption", "industrial"],
}
INSTRUMENTS = {"TTF": "ttf", "NBP": "nbp", "EUA": "eua", "DE Baseload": "baseload", "JKM": "jkm", "Brent": "brent"}
FIGURE_RE = re.compile(
    r"(?:[€$£]\s?\d[\d.,]*(?:/\w+)?)|(?:\d[\d.,]*\s?(?:%|bcm|gw|mw|twh|gwh|mwh|eur/mwh|€/mwh|eur/t|€/t|euros?))",
    re.IGNORECASE,
)


def _count(text: str, words: List[str]) -> int:
    return sum(text.count(w) for w in words)


class HeuristicExtractor:
    name = "heuristic"

    def extract(self, article: Article) -> Optional[Signal]:
        text = f" {article.title} {article.text} ".lower()
        scores = {m: _count(text, w) for m, w in MARKET_WORDS.items()}
        if max(scores.values()) == 0:
            return Signal(relevant=False, market=Market.other, region="n/a", direction=Direction.neutral,
                          driver=Driver.other, summary=article.title[:150], confidence=0.1)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        market = ranked[0][0]
        if ranked[1][1] > 0 and ranked[1][1] >= ranked[0][1] * 0.7:
            market = Market.multi
        up, down = _count(text, BULLISH), _count(text, BEARISH)
        direction = Direction.bullish if up > down else Direction.bearish if down > up else Direction.neutral
        driver_scores = {d: _count(text, w) for d, w in DRIVER_WORDS.items()}
        driver = max(driver_scores, key=driver_scores.get)
        if driver_scores[driver] == 0:
            driver = Driver.other
        region = next((r for r, k in [("DE", "german"), ("NL", "dutch"), ("GB", "uk "), ("FR", "france"),
                                       ("GB", "britain")] if k in text), "EU")
        instruments = [label for label, key in INSTRUMENTS.items() if key in text]
        figures = list(dict.fromkeys(m.strip() for m in FIGURE_RE.findall(f"{article.title}. {article.text}")))[:5]
        first_sentence = re.split(r"(?<=[.!?])\s", article.text.strip())[0] if article.text else article.title
        conf = min(0.3 + 0.1 * abs(up - down) + 0.05 * len(figures), 0.7)
        return Signal(relevant=True, market=market, region=region, direction=direction, driver=driver,
                      instruments=instruments, summary=first_sentence[:200], key_figures=figures,
                      confidence=round(conf, 2))


def get_extractor(provider: str = "mock"):
    """provider: mock | claude | gemini | ollama | custom (uses LLM_BASE_URL)."""
    import os

    if provider == "mock":
        return HeuristicExtractor()
    if provider == "claude":
        return LLMExtractor()
    if provider in PRESETS:
        base, model, delay = PRESETS[provider]
    elif provider == "custom":
        base, model, delay = os.environ["LLM_BASE_URL"], "", 0.0
    else:
        raise ValueError(f"unknown provider: {provider}")
    model = os.environ.get("LLM_MODEL", model)
    key = os.environ.get("LLM_API_KEY", "ollama")  # ollama ignores the key
    return OpenAICompatExtractor(base, key, model, delay=float(os.environ.get("LLM_DELAY", delay)))
