import re
import urllib.parse
import feedparser
import ollama


class SentimentAnalyzer:
    def __init__(self, model_name="llama3.2"):
        self.model_name = model_name

    def fetch_text_data(self, asset="NIFTY"):
        query = urllib.parse.quote(f"{asset} stock market news")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        feed = feedparser.parse(url)

        headlines = []
        for entry in feed.entries[:5]:  # Get top 5 recent headlines
            headlines.append(entry.title)

        if not headlines:
            return [
                f"{asset} trades flat today.",
                "Global tech selloff triggers mild panic in Indian markets.",
            ]
        return headlines

    def analyze_sentiment(self, text_list):
        text_block = "\n".join(text_list)
        prompt = (
            "You are a quantitative hedge fund AI. Read the following market news. "
            "Output ONLY a single floating-point number between -1.0 (extreme bearish panic) "
            "and 1.0 (extreme bullish euphoria). Output nothing but the number."
        )
        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text_block}],
            )
            content = response.get("message", {}).get("content", "")
            match = re.search(r"-?\d+(?:\.\d+)?", content)
            if match:
                return float(match.group())
            return 0.0
        except Exception:
            return 0.0
