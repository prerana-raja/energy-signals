"""Data models. The Signal schema is what the LLM is forced to return."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class Market(str, Enum):
    gas = "gas"
    power = "power"
    emissions = "emissions"
    multi = "multi"
    other = "other"


class Direction(str, Enum):
    bullish = "bullish"  # upward price pressure
    bearish = "bearish"  # downward price pressure
    neutral = "neutral"


class Driver(str, Enum):
    supply = "supply"
    demand = "demand"
    weather = "weather"
    storage = "storage"
    flows = "flows"
    outages = "outages"
    regulation = "regulation"
    geopolitics = "geopolitics"
    fuel_switching = "fuel_switching"
    other = "other"


class Signal(BaseModel):
    """One structured market signal extracted from one article or report chunk."""

    relevant: bool = Field(
        description="False if the text has no information useful to European gas, power or carbon trading."
    )
    market: Market
    region: str = Field(description="Country code or area, e.g. EU, DE, NL, GB, FR, Nordics.")
    direction: Direction = Field(description="Likely price impact on the market named above.")
    driver: Driver
    instruments: List[str] = Field(
        default_factory=list, description="Benchmarks mentioned, e.g. TTF, NBP, EUA, DE Baseload."
    )
    summary: str = Field(description="One sentence, max 30 words, plain facts only.")
    key_figures: List[str] = Field(
        default_factory=list, description="Numbers with units quoted in the text, e.g. '38 EUR/MWh', '62% storage'."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="How clearly the text supports the direction call.")


@dataclass
class Article:
    id: str
    source: str
    title: str
    text: str
    url: str = ""
    published: str = ""  # ISO 8601 date string
