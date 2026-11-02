"""ARK ETF의 매일 매매내역. 출처는 arkfunds.io (ARK 공개 자료를 모은 비공식 API)."""
import json
from pathlib import Path

import requests

TRADES_URL = "https://arkfunds.io/api/v2/etf/trades"
FUNDS = ["ARKK", "ARKQ", "ARKW", "ARKG", "ARKF", "ARKX"]
HISTORY_DIR = Path(__file__).parent / "history" / "ark"
HEADERS = {"User-Agent": "trading-dashboard"}
TOP = 15


def fetch_fund(fund: str) -> list[dict]:
    response = requests.get(TRADES_URL, params={"symbol": fund}, timeout=40, headers=HEADERS)
    response.raise_for_status()
    return response.json().get("trades", [])


def merge_trades(trades: list[dict]) -> dict:
    """가장 최근 날짜의 매매를 펀드 전체로 합쳐 매수와 매도로 나눈다."""
    date = max(trade["date"] for trade in trades)
    totals = {}
    for trade in trades:
        if trade["date"] != date or not trade.get("ticker"):
            continue
        key = (trade["ticker"], trade["direction"])
        total = totals.setdefault(
            key, {"ticker": trade["ticker"], "company": trade.get("company"), "shares": 0, "funds": []}
        )
        total["shares"] += trade.get("shares") or 0
        total["funds"].append(trade["fund"])
    side = lambda name: sorted(
        (total for (_, direction), total in totals.items() if direction == name),
        key=lambda total: -total["shares"],
    )[:TOP]
    return {"date": date, "buy": side("Buy"), "sell": side("Sell")}


def save_day(day: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / f"{day['date']}.json").write_text(json.dumps(day, ensure_ascii=False, indent=1) + "\n")


def load_saved_days() -> list[dict]:
    """저장된 날짜별 매매. 최신 날짜가 먼저 온다."""
    paths = sorted(HISTORY_DIR.glob("*.json"), reverse=True)
    return [json.loads(path.read_text()) for path in paths]


def load_ark_trades() -> dict:
    """펀드 일부가 실패해도 받은 만큼으로 만든다."""
    trades = []
    for fund in FUNDS:
        try:
            trades += fetch_fund(fund)
        except (requests.RequestException, ValueError):
            continue
    if not trades:
        raise RuntimeError("ARK 매매내역을 받지 못했습니다")
    day = merge_trades(trades)
    save_day(day)
    return day
