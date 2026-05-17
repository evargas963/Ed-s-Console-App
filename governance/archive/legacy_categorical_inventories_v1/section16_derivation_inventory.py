"""
Section 16 Schwab-leaf derivation audit inventory (external signals).

One row per ``def`` (module, class method, nested helper).
Disposition: REPLACED | KEEP_DERIVED | PASS_THROUGH | NONE
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivationRecord:
    file: str
    line: str
    derivation: str
    schwab_leaf: str
    disposition: str
    justification: str


SECTION16_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("api_pressure.py", "21", "record_schwab_http_response", "HTTP 429 observability", "NONE", "Records Schwab rate-limit events for UI; no quote field derivation."),
    DerivationRecord("api_pressure.py", "41", "throttle_ui_payload", "HTTP 429 observability", "NONE", "UI payload for recent 429 events; no market-field derivation."),
    DerivationRecord("event_risk.py", "38", "session_date_et", "clock ET", "NONE", "ET session date helper."),
    DerivationRecord("event_risk.py", "44", "assess_event_risk", "macro/earnings calendar", "NONE", "Static macro/earnings calendar gating; no Schwab ingest."),
    DerivationRecord("news_sentiment.py", "47", "_load_local_env_once", "—", "NONE", "HTTP/env helper for external APIs."),
    DerivationRecord("news_sentiment.py", "82", "_parse_article_datetime", "Finnhub article datetime", "KEEP_DERIVED", "Parses external article timestamp; not Schwab pricehistory."),
    DerivationRecord("news_sentiment.py", "100", "classify_headline_impact", "Finnhub|AlphaVantage", "KEEP_DERIVED", "External sentiment/headline derivation for snapshots."),
    DerivationRecord("news_sentiment.py", "124", "_http_timeout_sec", "—", "NONE", "HTTP/env helper for external APIs."),
    DerivationRecord("news_sentiment.py", "129", "_http_json_any", "—", "NONE", "HTTP/env helper for external APIs."),
    DerivationRecord("news_sentiment.py", "158", "_finnhub_token", "external API", "PASS_THROUGH", "External sentiment/news API call."),
    DerivationRecord("news_sentiment.py", "165", "_av_token", "external API", "PASS_THROUGH", "External sentiment/news API call."),
    DerivationRecord("news_sentiment.py", "172", "fetch_finnhub_sentiment", "Finnhub API", "PASS_THROUGH", "Finnhub REST sentiment endpoint wrapper."),
    DerivationRecord("news_sentiment.py", "230", "fetch_finnhub_recent_company_news", "Finnhub API", "PASS_THROUGH", "Finnhub company-news REST wrapper."),
    DerivationRecord("news_sentiment.py", "251", "fetch_alpha_vantage_sentiment", "AlphaVantage API", "PASS_THROUGH", "Alpha Vantage sentiment REST wrapper."),
    DerivationRecord("news_sentiment.py", "295", "_update_pre_market_store", "—", "NONE", "Internal helper; no Schwab market-field derivation."),
    DerivationRecord("news_sentiment.py", "307", "get_sentiment_features_for_snapshot", "Finnhub|AlphaVantage", "KEEP_DERIVED", "Merges external sentiment into snapshot feature dict."),
    DerivationRecord("news_sentiment.py", "320", "_merge_finnhub_av", "external API", "PASS_THROUGH", "External sentiment/news API call."),
    DerivationRecord("news_sentiment.py", "335", "refresh_and_context", "Finnhub|AlphaVantage", "KEEP_DERIVED", "Refreshes news/sentiment cache and builds MarketState context."),
    DerivationRecord("news_sentiment.py", "475", "refresh_and_context_for_ui", "Finnhub|AlphaVantage", "KEEP_DERIVED", "UI-bounded refresh path for news/sentiment context."),
)

SECTION16_FILES = frozenset({
    "api_pressure.py",
    "event_risk.py",
    "news_sentiment.py",
})

