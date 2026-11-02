"""야후 파이낸스·구글 뉴스에서 데이터를 가져온다. 화면 코드는 app.py에 있다."""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

BENCHMARK = "SPY"
NEWS_LIMIT = 12
# 기사가 아니라 시세 페이지인 검색 결과
NOT_ARTICLE = re.compile(r"stock price|quote & history|latest stock news", re.I)
US_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS", "BATS"}
SEARCH_LIMIT = 6
MARKET_SYMBOLS = {
    "^GSPC": "S&P 500",
    "^IXIC": "나스닥",
    "^DJI": "다우",
    "^VIX": "VIX",
    "^TNX": "미 10년물 금리",
    "DX-Y.NYB": "달러 인덱스",
    "CL=F": "WTI 유가",
    "GC=F": "금",
}


def normalize_ticker(raw: str) -> str | None:
    ticker = raw.strip().upper().replace(".", "-")
    return ticker if re.fullmatch(r"[A-Z0-9\-]{1,10}", ticker) else None


def yahoo_candidates(quotes: list[dict]) -> list[dict]:
    """야후 검색 결과에서 미국 거래소의 주식·ETF만 남긴다."""
    return [
        {"ticker": quote["symbol"], "name": quote.get("shortname") or quote.get("longname")}
        for quote in quotes
        if quote.get("quoteType") in ("EQUITY", "ETF") and quote.get("exchange") in US_EXCHANGES
    ]


def naver_candidates(items: list[dict]) -> list[dict]:
    """네이버 자동완성 결과에서 미국 종목만 남긴다. 티커의 공백은 야후 표기로 바꾼다."""
    return [
        {"ticker": item["code"].replace(" ", "-"), "name": item.get("name")}
        for item in items
        if item.get("nationCode") == "USA"
    ]


def search_yahoo(query: str) -> list[dict]:
    return yahoo_candidates(yf.Search(query, news_count=0, max_results=20).quotes)


def search_naver(query: str) -> list[dict]:
    response = requests.get(
        "https://ac.stock.naver.com/ac",
        params={"q": query, "target": "stock"},
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return naver_candidates(response.json().get("items", []))


def merge_candidates(found: list[dict], exact: str | None) -> list[dict]:
    """중복을 없애고, 입력이 티커와 정확히 같으면 그 종목을 맨 앞에 둔다.

    검색 결과가 없으면 티커 형식의 입력을 그대로 시도한다.
    """
    unique = {}
    for item in found:
        unique.setdefault(item["ticker"], item)
    ranked = sorted(unique.values(), key=lambda item: item["ticker"] != exact)
    if not ranked and exact:
        return [{"ticker": exact, "name": None}]
    return ranked[:SEARCH_LIMIT]


@st.cache_data(ttl=3600, show_spinner=False)
def search_symbols(query: str) -> list[dict]:
    """티커, 영문 회사명, 한글 회사명을 미국 종목 후보로 바꾼다."""
    korean = re.search(r"[가-힣]", query) is not None
    found = []
    for search in (search_naver,) if korean else (search_yahoo, search_naver):
        try:
            found = search(query)
        except Exception:
            continue
        if found:
            break
    return merge_candidates(found, normalize_ticker(query))


def short_name(name: str | None) -> str | None:
    if not name:
        return None
    pattern = r"[,.]?\s+(Inc|Incorporated|Corp|Corporation|Company|Co|Ltd|PLC|Holdings|Group)\b.*$"
    return re.sub(pattern, "", name, flags=re.I).strip() or None


@st.cache_data(ttl=900, show_spinner=False)
def load_history(ticker: str) -> pd.DataFrame:
    """분할 반영 종가(Close)와 배당까지 반영한 종가(Adj Close)."""
    hist = yf.Ticker(ticker).history(period="max", auto_adjust=False)
    if hist.empty:
        return hist
    hist.index = hist.index.tz_localize(None).normalize()
    return hist[["Close", "Adj Close", "Volume"]].dropna(subset=["Close", "Adj Close"])


@st.cache_data(ttl=3600, show_spinner=False)
def load_info(ticker: str) -> dict:
    return yf.Ticker(ticker).info or {}


@st.cache_data(ttl=3600, show_spinner=False)
def load_next_earnings(ticker: str):
    dates = (yf.Ticker(ticker).calendar or {}).get("Earnings Date") or []
    return dates[0] if dates else None


@st.cache_data(ttl=900, show_spinner=False)
def load_market() -> pd.DataFrame:
    frame = yf.download(
        list(MARKET_SYMBOLS), period="1y", progress=False, auto_adjust=True
    )["Close"]
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame


def yahoo_news(ticker: str, name: str | None) -> list[dict]:
    items = []
    for item in yf.Search(ticker, news_count=20).news:
        title = item.get("title", "")
        # 야후 검색은 티커가 잠깐 언급된 글도 돌려주므로 제목에 나온 글만 남긴다.
        mentions = re.search(rf"\b{re.escape(ticker)}\b", title) or (
            name and name.lower() in title.lower()
        )
        if mentions:
            items.append(
                {
                    "title": title,
                    "source": item.get("publisher") or "Yahoo Finance",
                    "link": item.get("link"),
                    "time": datetime.fromtimestamp(
                        item.get("providerPublishTime", 0), tz=timezone.utc
                    ),
                }
            )
    return items


def google_news(ticker: str, name: str | None) -> list[dict]:
    return google_rss(f'"{name}" {ticker} stock when:7d' if name else f"{ticker} stock when:7d")


def market_news() -> list[dict]:
    items = sorted(google_rss("US stock market Wall Street when:1d"), key=lambda item: item["time"], reverse=True)
    unique = {re.sub(r"\W+", "", item["title"].lower()): item for item in reversed(items)}
    return list(reversed(unique.values()))[:NEWS_LIMIT]


def google_rss(query: str) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    items = []
    for node in ET.fromstring(response.content).iter("item"):
        source = node.findtext("source") or "Google News"
        title = node.findtext("title") or ""
        items.append(
            {
                "title": title.removesuffix(f" - {source}"),
                "source": source,
                "link": node.findtext("link"),
                "time": parsedate_to_datetime(node.findtext("pubDate")),
            }
        )
    return items


@st.cache_data(ttl=900, show_spinner=False)
def load_news(ticker: str, name: str | None) -> list[dict]:
    """두 소스를 합쳐 최신순으로 돌려준다. 한쪽이 실패해도 나머지로 보여준다."""
    merged, seen = [], set()
    failures = 0
    for fetch in (yahoo_news, google_news):
        try:
            found = fetch(ticker, name)
        except Exception:
            failures += 1
            continue
        for item in found:
            key = re.sub(r"\W+", "", item["title"].lower())
            if key not in seen and item["link"] and not NOT_ARTICLE.search(item["title"]):
                seen.add(key)
                merged.append(item)
    if failures == 2:
        raise RuntimeError("뉴스 소스에 모두 연결하지 못했습니다")
    return sorted(merged, key=lambda item: item["time"], reverse=True)[:NEWS_LIMIT]
