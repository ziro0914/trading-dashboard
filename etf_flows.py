"""연금계좌에서 살 수 있는 국내 상장 ETF의 개인 순매수·순매도 순위. 출처는 네이버 증권."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests

from flows import rank

ETF_LIST_URL = "https://finance.naver.com/api/sise/etfItemList.nhn"
TREND_URL = "https://m.stock.naver.com/api/stock/{code}/trend"
HISTORY_DIR = Path(__file__).parent / "history" / "etf-flows"
HEADERS = {"User-Agent": "Mozilla/5.0"}
# 연금계좌에서 매수할 수 없는 상품
NOT_FOR_PENSION = re.compile(r"레버리지|인버스|2X|곱버스", re.I)
SCAN_LIMIT = 300
TREND_DAYS = 25
WEEK_DAYS = 5
PAUSE_SECONDS = 0.1


def pension_etfs(items: list[dict]) -> list[dict]:
    """레버리지·인버스를 빼고 거래대금 상위 종목만 남긴다."""
    eligible = [item for item in items if not NOT_FOR_PENSION.search(item["itemname"])]
    eligible.sort(key=lambda item: item.get("amonut") or 0, reverse=True)
    return eligible[:SCAN_LIMIT]


def parse_number(text: str) -> float:
    return float(text.replace(",", "").replace("+", ""))


def parse_trend(code: str, name: str, days: list[dict]) -> list[dict]:
    rows = []
    for day in days:
        shares = parse_number(day["individualPureBuyQuant"])
        close = parse_number(day["closePrice"])
        date = datetime.strptime(day["bizdate"], "%Y%m%d").date().isoformat()
        rows.append({"date": date, "code": code, "name": name, "shares": shares, "close": close, "net": shares * close})
    return rows


def fetch_rows() -> list[dict]:
    response = requests.get(ETF_LIST_URL, timeout=15, headers=HEADERS)
    response.raise_for_status()
    items = response.json()["result"]["etfItemList"]
    rows = []
    for item in pension_etfs(items):
        try:
            trend = requests.get(
                TREND_URL.format(code=item["itemcode"]),
                params={"pageSize": TREND_DAYS},
                timeout=10,
                headers=HEADERS,
            )
            trend.raise_for_status()
            rows += parse_trend(item["itemcode"], item["itemname"], trend.json())
        except (requests.RequestException, KeyError, ValueError):
            continue
        time.sleep(PAUSE_SECONDS)
    if not rows:
        raise RuntimeError("ETF 수급 데이터를 받지 못했습니다")
    return rows


def rank_day(rows: list[dict], date: str) -> dict:
    day = [row for row in rows if row["date"] == date]
    return {"start": date, "end": date, **rank(day, day)}


def rank_week(rows: list[dict], dates: list[str]) -> dict:
    """최근 며칠의 순매수를 종목별로 합쳐 순위를 만든다."""
    totals = {}
    for row in rows:
        if row["date"] in dates:
            total = totals.setdefault(row["code"], {"code": row["code"], "name": row["name"], "net": 0.0})
            total["net"] += row["net"]
    merged = list(totals.values())
    return {"start": min(dates), "end": max(dates), **rank(merged, merged)}


def save_day(view: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / f"{view['end']}.json").write_text(json.dumps(view, ensure_ascii=False, indent=1) + "\n")


def load_saved_days() -> list[dict]:
    """저장된 날짜별 순위. 최신 날짜가 먼저 온다."""
    paths = sorted(HISTORY_DIR.glob("*.json"), reverse=True)
    return [json.loads(path.read_text()) for path in paths]


def load_etf_flows() -> dict:
    """최근 날짜들을 다시 계산해 저장하고, 최신 하루와 1주 합계를 돌려준다."""
    rows = fetch_rows()
    dates = sorted({row["date"] for row in rows}, reverse=True)
    for date in dates:
        save_day(rank_day(rows, date))
    return {"daily": rank_day(rows, dates[0]), "weekly": rank_week(rows, dates[:WEEK_DAYS])}
