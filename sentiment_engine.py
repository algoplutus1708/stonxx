"""News sentiment helper for the stonxx bot.

The analyzer prefers Ollama when available, but it falls back to a deterministic
keyword score so live trading remains operational even when local LLM tooling is
missing.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

try:  # Optional dependency; trading should still work without it.
    import ollama
except ImportError:  # pragma: no cover - exercised in environments without Ollama.
    ollama = None

POSITIVE_TERMS = {
    "beat",
    "bull",
    "bullish",
    "breakout",
    "buy",
    "growth",
    "gain",
    "gains",
    "green",
    "inflow",
    "inflows",
    "jumps",
    "lift",
    "momo",
    "momentum",
    "optimism",
    "optimistic",
    "outperform",
    "positive",
    "profit",
    "profits",
    "recovery",
    "record",
    "rally",
    "risk-on",
    "strong",
    "surge",
    "up",
    "upgrade",
}

NEGATIVE_TERMS = {
    "bear",
    "bearish",
    "crash",
    "cut",
    "cuts",
    "down",
    "downgrade",
    "fear",
    "loss",
    "losses",
    "panic",
    "plunge",
    "risk-off",
    "sell",
    "selloff",
    "slump",
    "slowdown",
    "soft",
    "weak",
    "warning",
    "worst",
}


class SentimentAnalyzer:
    def __init__(self, model_name: str = "llama3.2", *, max_headlines: int = 5, timeout_seconds: int = 8):
        self.model_name = model_name
        self.max_headlines = max_headlines
        self.timeout_seconds = timeout_seconds

    def fetch_text_data(self, asset: str = "NIFTY") -> list[str]:
        query = urllib.parse.quote(f"{asset} stock market news")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

        try:
            request = Request(url, headers={"User-Agent": "stonxx/1.0"})
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
            root = ET.fromstring(payload)
        except (URLError, ET.ParseError, TimeoutError, ValueError, OSError):
            return []

        headlines: list[str] = []
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            if title:
                headlines.append(title)
            if len(headlines) >= self.max_headlines:
                break

        return headlines

    def _lexicon_score(self, text_list: Iterable[str]) -> float:
        headlines = [str(text).strip() for text in text_list if str(text).strip()]
        if not headlines:
            return 0.0

        score = 0.0
        token_count = 0
        for headline in headlines:
            tokens = re.findall(r"[a-z']+", headline.lower())
            token_count += len(tokens)
            for token in tokens:
                if token in POSITIVE_TERMS:
                    score += 1.0
                elif token in NEGATIVE_TERMS:
                    score -= 1.0

        if token_count == 0:
            return 0.0

        normalized = score / max(len(headlines), 1)
        return max(-1.0, min(1.0, normalized / 3.0))

    def analyze_sentiment(self, text_list: Iterable[str] | None = None, asset: str = "NIFTY") -> float:
        if text_list is None:
            text_list = self.fetch_text_data(asset)

        headlines = [str(text).strip() for text in text_list if str(text).strip()]
        if not headlines:
            return 0.0

        if ollama is not None:
            prompt = (
                "You are a quantitative hedge fund AI. Read the following market news. "
                "Output ONLY a single floating-point number between -1.0 (extreme bearish panic) "
                "and 1.0 (extreme bullish euphoria). Output nothing but the number."
            )
            try:
                response = ollama.chat(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": "\n".join(headlines)},
                    ],
                )
                content = response.get("message", {}).get("content", "")
                match = re.search(r"-?\d+(?:\.\d+)?", content)
                if match:
                    return max(-1.0, min(1.0, float(match.group())))
            except Exception:
                pass

        return self._lexicon_score(headlines)
