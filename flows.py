"""한국 투자자의 미국주식 순매수·순매도 순위. 출처는 예탁결제원 SEIBro 종목별내역(주식TOP50)."""
import json
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import requests
import yfinance as yf

from data import yahoo_candidates

SEIBRO_URL = "https://seibro.or.kr/websquare/engine/proworks/callServletService.jsp"
PAGE = "https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921"
SELL, NET_BUY = "2", "4"
TOP = 10
LOOKBACK_DAYS = 10
HISTORY_DIR = Path(__file__).parent / "history" / "flows"
TICKER_MAP = Path(__file__).parent / "history" / "tickers.json"
# 야후 검색이 다른 주식 종류를 먼저 돌려주는 종목
ISIN_TICKERS = {"US02079K3059": "GOOGL"}


def fetch_top50(start: date, end: date, kind: str) -> list[dict]:
    body = (
        '<reqParam action="getImptFrcurStkSetlAmtList" task="ksd.safe.bip.cnts.OvsSec.process.OvsSecIsinPTask">'
        '<MENU_NO value="921"/><W2XPATH value="/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml"/>'
        '<PG_START value="1"/><PG_END value="50"/>'
        f'<START_DT value="{start:%Y%m%d}"/><END_DT value="{end:%Y%m%d}"/>'
        f'<S_TYPE value="2"/><S_COUNTRY value="US"/><D_TYPE value="{kind}"/></reqParam>'
    )
    response = requests.post(
        SEIBRO_URL,
        data=body.encode(),
        timeout=30,
        headers={"Content-Type": "application/xml; charset=UTF-8", "Referer": PAGE, "User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    rows = []
    for node in ET.fromstring(response.content).iter("result"):
        value = lambda tag: node.find(tag).get("value")
        rows.append(
            {
                "isin": value("ISIN"),
                "name": value("KOR_SECN_NM"),
                "buy": float(value("SUM_FRSEC_BUY_AMT")),
                "sell": float(value("SUM_FRSEC_SELL_AMT")),
                "net": float(value("SUM_FRSEC_NET_BUY_AMT")),
            }
        )
    return rows


def latest_date(today: date) -> date:
    """결제 자료가 올라온 가장 최근 날짜를 찾는다."""
    for back in range(LOOKBACK_DAYS):
        day = today - timedelta(days=back)
        if fetch_top50(day, day, NET_BUY):
            return day
    raise RuntimeError("최근 결제 자료가 없습니다")


def rank(buy_rows: list[dict], sell_rows: list[dict]) -> dict:
    """순매도는 순위 조회가 없어 매도결제 상위 50 종목의 순매수 금액으로 계산한다."""
    net_buy = sorted((row for row in buy_rows if row["net"] > 0), key=lambda row: -row["net"])
    net_sell = sorted((row for row in sell_rows if row["net"] < 0), key=lambda row: row["net"])
    return {"netBuy": net_buy[:TOP], "netSell": net_sell[:TOP]}


def period(start: date, end: date) -> dict:
    result = rank(fetch_top50(start, end, NET_BUY), fetch_top50(start, end, SELL))
    return {"start": start.isoformat(), "end": end.isoformat(), **result}


def ticker_for(isin: str, name: str) -> str | None:
    """야후에서 ISIN으로 찾고, 없으면 종목명으로 찾는다."""
    if isin in ISIN_TICKERS:
        return ISIN_TICKERS[isin]
    for query in (isin, name, re.sub(r"\s+(CL|CLASS)\b.*$", "", name)):
        try:
            candidates = yahoo_candidates(yf.Search(query, news_count=0).quotes)
        except Exception:
            continue
        if candidates:
            return candidates[0]["ticker"]
    return None


def attach_tickers(view: dict, tickers: dict) -> None:
    """이미 아는 ISIN은 tickers에서 쓰고, 새로 찾은 티커는 tickers에 더한다."""
    for row in view["netBuy"] + view["netSell"]:
        isin = row["isin"]
        if isin not in tickers:
            tickers[isin] = ticker_for(isin, row["name"])
        row["ticker"] = tickers[isin]


def load_ticker_map() -> dict:
    return json.loads(TICKER_MAP.read_text()) if TICKER_MAP.exists() else {}


def save_ticker_map(tickers: dict) -> None:
    TICKER_MAP.parent.mkdir(parents=True, exist_ok=True)
    TICKER_MAP.write_text(json.dumps(tickers, ensure_ascii=False, indent=0, sort_keys=True) + "\n")


def save_day(view: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"{view['end']}.json"
    path.write_text(json.dumps(view, ensure_ascii=False, indent=1) + "\n")


def load_saved_days() -> list[dict]:
    """저장된 날짜별 순위. 최신 날짜가 먼저 온다."""
    paths = sorted(HISTORY_DIR.glob("*.json"), reverse=True)
    return [json.loads(path.read_text()) for path in paths]


def load_flows(today: date | None = None, tickers: dict | None = None) -> dict:
    end = latest_date(today or date.today())
    flows = {"daily": period(end, end), "weekly": period(end - timedelta(days=6), end)}
    known = load_ticker_map() if tickers is None else tickers
    for view in flows.values():
        attach_tickers(view, known)
    return flows
