"""GitHub Pages용 정적 사이트를 dist/ 에 만든다. 실행: python build_site.py [티커 ...]"""
import json
import math
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from data import (
    BENCHMARK,
    MARKET_SYMBOLS,
    load_history,
    load_info,
    load_market,
    load_news,
    load_next_earnings,
    search_naver,
    short_name,
)
from metrics import drawdown, max_drawdown, performance, slice_window

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
WINDOWS = {"1년": 1, "3년": 3, "5년": 5, "10년": 10, "전체": None}
MAX_POINTS = 400
PAUSE_SECONDS = 0.4
MAX_FAILURE_RATE = 0.3
INFO_FIELDS = [
    "longName", "shortName", "quoteType", "sector", "industry", "category", "exchange",
    "currentPrice", "regularMarketPrice", "previousClose", "marketCap", "totalAssets",
    "trailingPE", "forwardPE", "trailingEps", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "dividendYield", "beta", "targetMeanPrice", "recommendationKey",
    "numberOfAnalystOpinions", "longBusinessSummary",
]


def clean(value):
    """JSON에 넣을 수 있게 NaN을 None으로, 소수는 적당히 줄인다."""
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else round(value, 4)
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def day(value) -> str | None:
    return None if value is None else value.strftime("%Y-%m-%d")


def read_universe() -> dict[str, list[str]]:
    universe = {}
    for line in (ROOT / "universe.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            ticker, *aliases = [part.strip() for part in line.split(",")]
            universe[ticker] = aliases
    return universe


def build_window(hist, benchmark, years, compare) -> dict:
    close = hist["Close"]
    ma50, ma200 = close.rolling(50).mean(), close.rolling(200).mean()
    adjusted = slice_window(hist["Adj Close"], years)
    bench = slice_window(benchmark, years)
    bench = bench[bench.index >= adjusted.index[0]]
    dd = drawdown(adjusted)
    bench_dd = drawdown(bench).reindex(adjusted.index) if compare else None
    detail = max_drawdown(adjusted)

    # 점 수를 줄이되 MDD 저점과 마지막 날은 반드시 남긴다.
    step = max(1, len(adjusted) // MAX_POINTS)
    keep = set(adjusted.index[::step]) | {detail["trough"], adjusted.index[-1]}
    points = adjusted.index[adjusted.index.isin(keep)]

    result = {
        "dates": [day(date) for date in points],
        "close": close.reindex(points).tolist(),
        "ma50": ma50.reindex(points).tolist(),
        "ma200": ma200.reindex(points).tolist(),
        "drawdown": dd.reindex(points).tolist(),
        "benchDrawdown": bench_dd.reindex(points).tolist() if compare else None,
        "mdd": detail["mdd"],
        "peak": day(detail["peak"]),
        "trough": day(detail["trough"]),
        "recovery": day(detail["recovery"]),
        "current": detail["current"],
        "benchMdd": max_drawdown(bench)["mdd"] if compare and len(bench) > 1 else None,
    }
    result.update(performance(adjusted))
    return result


def build_ticker(ticker, benchmark) -> dict:
    hist = load_history(ticker)
    if len(hist) < 2:
        raise ValueError("가격 데이터 없음")
    info = load_info(ticker)
    is_etf = info.get("quoteType") == "ETF"
    try:
        earnings = None if is_etf else load_next_earnings(ticker)
    except Exception:
        earnings = None
    try:
        news = load_news(ticker, None if is_etf else short_name(info.get("longName")))
    except Exception:
        news = []
    span_days = (hist.index[-1] - hist.index[0]).days
    compare = ticker != BENCHMARK and not benchmark.empty
    windows = {
        label: build_window(hist, benchmark, years, compare)
        for label, years in WINDOWS.items()
        if years is None or span_days >= years * 365
    }
    return {
        "ticker": ticker,
        "benchmark": BENCHMARK if compare else None,
        "info": {field: info.get(field) for field in INFO_FIELDS},
        "lastClose": float(hist["Close"].iloc[-1]),
        "prevClose": float(hist["Close"].iloc[-2]),
        "priceDate": day(hist.index[-1]),
        "earnings": day(earnings),
        "windows": windows,
        "news": [{**item, "time": item["time"].isoformat()} for item in news],
    }


def build_market() -> dict:
    market = load_market()
    rows = []
    for symbol, label in MARKET_SYMBOLS.items():
        series = market[symbol].dropna()
        if len(series) >= 2:
            rows.append(
                {"symbol": symbol, "label": label, "last": float(series.iloc[-1]), "previous": float(series.iloc[-2])}
            )
    spx, vix = market["^GSPC"].dropna(), market["^VIX"].dropna()
    return {
        "rows": rows,
        "spxGap": float(spx.iloc[-1] / spx.tail(200).mean() - 1) if len(spx) >= 200 else None,
        "vix": float(vix.iloc[-1]) if len(vix) else None,
        "date": day(spx.index[-1]),
    }


def korean_name(ticker) -> str | None:
    try:
        return next((item["name"] for item in search_naver(ticker) if item["ticker"] == ticker), None)
    except Exception:
        return None


def write_json(path: Path, payload):
    path.write_text(json.dumps(clean(payload), ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def main():
    universe = read_universe()
    tickers = sys.argv[1:] or list(universe)
    shutil.rmtree(DIST, ignore_errors=True)
    (DIST / "data").mkdir(parents=True)
    shutil.copy(ROOT / "site" / "index.html", DIST / "index.html")
    (DIST / ".nojekyll").touch()

    benchmark = load_history(BENCHMARK)["Adj Close"]
    write_json(DIST / "data" / "market.json", build_market())

    index, failed = [], []
    for ticker in tickers:
        try:
            payload = build_ticker(ticker, benchmark)
            write_json(DIST / "data" / f"{ticker}.json", payload)
            info = payload["info"]
            index.append(
                {
                    "ticker": ticker,
                    "name": info.get("longName") or info.get("shortName") or ticker,
                    "korean": korean_name(ticker),
                    "aliases": universe.get(ticker, []),
                }
            )
            print("OK", ticker, flush=True)
        except Exception as error:
            failed.append(ticker)
            print("FAIL", ticker, repr(error)[:160], flush=True)
        time.sleep(PAUSE_SECONDS)

    write_json(
        DIST / "data" / "index.json",
        {"updated": datetime.now(timezone.utc).isoformat(), "tickers": index},
    )
    print(f"{len(index)} ok, {len(failed)} failed: {failed}")
    # 실패가 많으면 배포를 멈춰 이전 사이트를 유지한다.
    if len(failed) > len(tickers) * MAX_FAILURE_RATE:
        sys.exit(1)


if __name__ == "__main__":
    main()
