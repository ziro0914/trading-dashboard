"""매일 밤 범위 돌파 모의매매 게시물을 만든다. 실제 주문은 하지 않는다.

python daytrade.py plan     미국장 개장 무렵: 후보 1종목, 뉴스, 진입·청산 계획, 타임머신, 모의 주문서
python daytrade.py result   장 마감 뒤: 아직 결과가 없는 게시물에 그날 실제로 어떻게 됐는지 채운다

방법론은 day-trader-skill(MIT, Jakeschincariol)의 scanner → news → entry → exit →
timemachine → budget 흐름을 따른다. 데이터는 Yahoo Finance(무료, 비공식, 지연 가능).
"""
import json
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
POSTS = ROOT / "history" / "daytrade"
ET = ZoneInfo("America/New_York")

ACCOUNT = 5000.0          # 모의 계좌
MAX_LOSS = 50.0           # 1회 최대 손실(손절가에서)
TARGET_R = 2.0            # 목표가 = 진입가 + 2 × 1주당 위험
STOP_ATR = 0.5            # 1주당 위험 = 14일 ATR의 절반
RANGE_DAYS = 20           # 돌파 기준: 최근 20거래일 범위
MIN_PRICE = 5.0
MIN_VOLUME = 1_000_000
REPLAYS = 10_000
SEED = 19
BAR = 5                   # 5분봉
OPEN = time(9, 30)
NO_ENTRY_BEFORE = time(9, 45)   # 첫 15분(시가 범위)은 진입하지 않는다
NO_ENTRY_AFTER = time(15, 30)
FLAT_BY = time(15, 55)          # 마감 5분 전에는 무조건 청산
NEWS_KEEP = 8
ETFS = {
    "SPY", "VOO", "IVV", "QQQ", "QQQM", "VTI", "DIA", "IWM", "SCHD", "JEPI", "JEPQ", "VYM", "SOXX",
    "SMH", "XLK", "XLF", "XLE", "ARKK", "GLD", "SLV", "TLT", "TQQQ", "SQQQ", "SOXL", "QLD", "UPRO",
}
NYSE_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
    "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
NYSE_EARLY_CLOSE = {"2026-11-27", "2026-12-24", "2027-11-26"}  # 오후 1시 마감


# ------------------------------------------------------------------ 달력

def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day.isoformat() not in NYSE_HOLIDAYS


def session_times(day: date) -> dict:
    """그날의 진입 마감·청산 시각. 조기 마감일은 오후 1시 기준으로 당긴다."""
    if day.isoformat() in NYSE_EARLY_CLOSE:
        return {"close": time(13, 0), "no_entry_after": time(12, 30), "flat_by": time(12, 55)}
    return {"close": time(16, 0), "no_entry_after": NO_ENTRY_AFTER, "flat_by": FLAT_BY}


def slot_of(moment: time) -> int:
    """9:30 봉이 0, 9:35 봉이 1 ..."""
    return ((moment.hour * 60 + moment.minute) - (OPEN.hour * 60 + OPEN.minute)) // BAR


def slot_label(slot: int) -> str:
    minutes = OPEN.hour * 60 + OPEN.minute + slot * BAR
    return f"{minutes // 60}:{minutes % 60:02d}"


# ------------------------------------------------------------------ 순수 계산

def atr(daily: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = daily["Close"].shift()
    tr = pd.concat([daily["High"] - daily["Low"], (daily["High"] - prev).abs(), (daily["Low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def daily_levels(daily: pd.DataFrame) -> pd.DataFrame:
    """각 날짜에 대해 '그 전날까지' 기준의 돌파 기준가(20일 최고가)와 1주당 위험."""
    out = pd.DataFrame(index=daily.index)
    out["level"] = daily["High"].rolling(RANGE_DAYS).max().shift()
    out["risk"] = (atr(daily) * STOP_ATR).shift()
    return out


def find_breakouts(closes: pd.DataFrame, highs: pd.DataFrame, volumes: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """전일 종가가 그 앞 20거래일 종가를 모두 넘은 종목(20일 종가 신고가 돌파). 거래대금 순."""
    rows = []
    for ticker in closes.columns:
        close = closes[ticker].dropna()
        volume = volumes[ticker].reindex(close.index).fillna(0)
        if len(close) < RANGE_DAYS + 15:
            continue
        last, before = float(close.iloc[-1]), close.iloc[-RANGE_DAYS - 1:-1]
        vol = float(volume.iloc[-1])
        if last < MIN_PRICE or vol < MIN_VOLUME:
            continue
        prior_high = float(before.max())
        avg_vol = float(volume.iloc[-RANGE_DAYS - 1:-1].mean()) or 1.0
        rows.append(
            {
                "ticker": ticker,
                "close": last,
                "change": last / float(close.iloc[-2]) - 1,
                "priorHigh": prior_high,
                "breakout": last / prior_high - 1,
                "volumeRatio": vol / avg_vol,
                "dollarVolume": last * vol,
                "high20": float(highs[ticker].reindex(close.index).iloc[-RANGE_DAYS:].max()),
            }
        )
    hits = sorted((r for r in rows if r["breakout"] > 0), key=lambda r: r["dollarVolume"], reverse=True)
    near = sorted((r for r in rows if r["breakout"] <= 0), key=lambda r: r["breakout"], reverse=True)
    return hits, near


def session_bars(bars: pd.DataFrame, day: date) -> pd.DataFrame:
    """그날 정규장 5분봉만, slot 열을 붙여 돌려준다."""
    local = bars[bars.index.date == day]
    close_at = session_times(day)["close"]
    local = local[(local.index.time >= OPEN) & (local.index.time < close_at)].copy()
    local["slot"] = [slot_of(t) for t in local.index.time]
    return local.dropna(subset=["Open", "High", "Low", "Close"])


def run_rule(day_bars: pd.DataFrame, level: float, risk: float, day: date) -> dict:
    """하루에 규칙 한 번: 9:45 이후 처음 5분봉 '종가'가 기준가 위 → 그 종가에 진입.
    다음 봉부터 손절 먼저, 그다음 목표가를 본다(한 봉이 둘 다 건드리면 손절). 청산 시각에 정리."""
    times = session_times(day)
    first, last_entry = slot_of(NO_ENTRY_BEFORE), slot_of(times["no_entry_after"]) - 1
    flat_slot = slot_of(times["flat_by"]) - 1
    entry_row = None
    for stamp, row in day_bars.iterrows():
        if first <= row["slot"] <= last_entry and row["Close"] > level:
            entry_row = (stamp, row)
            break
    if entry_row is None:
        return {"triggered": False}
    stamp, row = entry_row
    entry = float(row["Close"])
    stop, target = entry - risk, entry + TARGET_R * risk
    outcome, exit_price, exit_slot = "close", None, None
    after = day_bars[(day_bars["slot"] > row["slot"]) & (day_bars["slot"] <= flat_slot)]
    for _, bar in after.iterrows():
        if bar["Low"] <= stop:
            outcome, exit_price, exit_slot = "stop", stop, int(bar["slot"])
            break
        if bar["High"] >= target:
            outcome, exit_price, exit_slot = "target", target, int(bar["slot"])
            break
    if exit_price is None:
        if after.empty:
            return {"triggered": False}
        exit_price, exit_slot = float(after["Close"].iloc[-1]), int(after["slot"].iloc[-1])
    return {
        "triggered": True,
        "entrySlot": int(row["slot"]),
        "entryTime": slot_label(int(row["slot"]) + 1),  # 봉이 닫히는 시각
        "entry": entry,
        "stop": stop,
        "target": target,
        "outcome": outcome,
        "exit": float(exit_price),
        "exitTime": slot_label(exit_slot + 1),
        "r": (float(exit_price) - entry) / risk,
    }


def history_test(bars: pd.DataFrame, levels: pd.DataFrame, today: date) -> dict:
    """지난 세션마다 같은 규칙을 그대로 돌린 실제 기록."""
    trades = []
    days = sorted({d for d in bars.index.date if d < today})
    for day in days:
        key = pd.Timestamp(day)
        if key not in levels.index:
            continue
        level, risk = levels.at[key, "level"], levels.at[key, "risk"]
        if not (np.isfinite(level) and np.isfinite(risk)) or risk <= 0:
            continue
        result = run_rule(session_bars(bars, day), float(level), float(risk), day)
        if result["triggered"]:
            trades.append({"date": day.isoformat(), **{k: result[k] for k in ("entryTime", "entrySlot", "outcome", "r")}})
    count = lambda name: sum(t["outcome"] == name for t in trades)
    return {
        "sessions": len(days),
        "fired": len(trades),
        "target": count("target"),
        "stop": count("stop"),
        "neither": count("close"),
        "avgR": float(np.mean([t["r"] for t in trades])) if trades else None,
        "trades": [{k: v for k, v in t.items() if k != "entrySlot"} for t in trades[-15:]],
        "medianSlot": int(np.median([t["entrySlot"] for t in trades])) if trades else None,
    }


def bar_pool(bars: pd.DataFrame, today: date) -> dict[int, np.ndarray]:
    """슬롯별로 '직전 봉 종가 대비' 고가·저가·종가 비율을 모은다. 오늘 봉은 넣지 않는다."""
    pool: dict[int, list] = {}
    for day in sorted({d for d in bars.index.date if d < today}):
        if day.isoformat() in NYSE_EARLY_CLOSE:
            continue
        session = session_bars(bars, day)
        if len(session) < 70:
            continue
        prev = session["Close"].shift()
        for (_, bar), base in zip(session.iterrows(), prev):
            if np.isfinite(base) and base > 0:
                pool.setdefault(int(bar["slot"]), []).append((bar["High"] / base, bar["Low"] / base, bar["Close"] / base))
    return {slot: np.array(rows) for slot, rows in pool.items()}


def time_machine(pool: dict[int, np.ndarray], entry: float, risk: float, start_slot: int, flat_slot: int,
                 replays: int = REPLAYS, seed: int = SEED) -> dict:
    """진입 뒤 남은 하루를 10,000번 다시 그린다. 각 봉은 과거 같은 시간대(±2봉) 봉에서 뽑아 현재가에 맞춘다."""
    rng = np.random.default_rng(seed)
    stop, target = entry - risk, entry + TARGET_R * risk
    price = np.full(replays, entry)
    done = np.zeros(replays, dtype=int)  # 0 진행 중, 1 목표 먼저, -1 손절 먼저
    for slot in range(start_slot, flat_slot + 1):
        near = [pool[s] for s in range(slot - 2, slot + 3) if s in pool and s > 0]
        if not near:
            continue
        rows = np.concatenate(near)
        pick = rows[rng.integers(0, len(rows), replays)]
        high, low, close = price * pick[:, 0], price * pick[:, 1], price * pick[:, 2]
        live = done == 0
        hit_stop = live & (low <= stop)
        hit_target = live & ~hit_stop & (high >= target)
        done[hit_stop], done[hit_target] = -1, 1
        price = np.where(done == 0, close, price)
    r = np.where(done == 1, TARGET_R, np.where(done == -1, -1.0, (price - entry) / risk))
    open_end = price[done == 0]
    return {
        "replays": replays,
        "seed": seed,
        "startTime": slot_label(start_slot),
        "bars": flat_slot - start_slot + 1,
        "target": float(np.mean(done == 1)),
        "stop": float(np.mean(done == -1)),
        "neither": float(np.mean(done == 0)),
        "green": float(np.mean((done == 1) | ((done == 0) & (price > entry)))),
        "avgR": float(np.mean(r)),
        "closeMedian": float(np.median(open_end)) if len(open_end) else None,
        "closeP5": float(np.percentile(open_end, 5)) if len(open_end) else None,
        "closeP95": float(np.percentile(open_end, 95)) if len(open_end) else None,
    }


def verdict(target: float, stop: float, neither: float, avg_r: float) -> list[str]:
    """day-trader-skill 기준: 한쪽에 닿은 경우 중 목표가 먼저인 비율을 손익분기 1/(1+R)과 비교."""
    sided = target + stop
    if sided == 0:
        return ["판정 불가: 어느 쪽에도 닿은 경우가 없습니다."]
    win, even = target / sided, 1 / (1 + TARGET_R)
    gap = (win - even) * 100
    side = "목표가" if gap > 0 else "손절가"
    if abs(gap) < 5:
        line = f"손익분기 근처: 한쪽에 닿은 경우 중 목표가 먼저 {win:.0%} (손익분기 {even:.0%})."
    elif abs(gap) < 15:
        line = f"{side} 쪽으로 기울어짐: 목표가 먼저 {win:.0%} vs 손익분기 {even:.0%}."
    else:
        line = f"{side} 쪽으로 강하게 기울어짐: 목표가 먼저 {win:.0%} vs 손익분기 {even:.0%}."
    lines = [line]
    if neither > 0.4:
        lines.append(f"리플레이의 {neither:.0%}는 청산 시각까지 어느 쪽에도 닿지 않아, 마감 직전 가격이 결과를 정합니다.")
    if (avg_r > 0) != (gap > 0) and abs(gap) >= 5:
        lines.append(f"다만 평균 R은 {avg_r:+.2f}로 반대 방향입니다.")
    return lines


def ticket(level: float, risk: float) -> dict:
    """계좌 5,000달러, 1회 최대 손실 50달러 기준 수량. 현금보다 많이 사지 않는다."""
    by_risk = math.floor(MAX_LOSS / risk) if risk > 0 else 0
    by_cash = math.floor(ACCOUNT / level) if level > 0 else 0
    shares = max(0, min(by_risk, by_cash))
    stop, target = level - risk, level + TARGET_R * risk
    return {
        "account": ACCOUNT,
        "maxLoss": MAX_LOSS,
        "shares": shares,
        "limitedBy": "현금" if by_cash < by_risk else "최대 손실",
        "entry": level,
        "stop": round(stop, 2),
        "target": round(target, 2),
        "cost": shares * level,
        "lossAtStop": shares * risk,
        "gainAtTarget": shares * risk * TARGET_R,
        "paper": True,
    }


# ------------------------------------------------------------------ 데이터

def _yf():
    import logging
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return yf


def load_daily(tickers: list[str]) -> pd.DataFrame:
    frame = _yf().download(tickers, period="6mo", interval="1d", auto_adjust=False, progress=False, threads=True)
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    return frame


def load_bars(ticker: str) -> pd.DataFrame:
    frame = _yf().download(ticker, period="60d", interval="5m", auto_adjust=False, progress=False, multi_level_index=False)
    if frame.empty:
        return frame
    frame.index = pd.to_datetime(frame.index).tz_convert(ET)
    return frame[["Open", "High", "Low", "Close", "Volume"]]


def single_daily(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    return pd.DataFrame({field: frame[field][ticker] for field in ("High", "Low", "Close", "Volume")}).dropna()


def read_stocks() -> list[str]:
    rows = [line.split(",")[0].strip() for line in (ROOT / "universe.txt").read_text().splitlines()]
    return [t for t in rows if t and not t.startswith("#") and t not in ETFS]


def load_context(ticker: str) -> dict:
    from data import load_info, load_news, load_next_earnings, short_name
    context = {"name": ticker, "sector": None, "earnings": None, "news": []}
    try:
        info = load_info(ticker)
        context["name"] = info.get("longName") or info.get("shortName") or ticker
        context["sector"] = info.get("sector")
    except Exception as error:
        print("INFO FAIL", repr(error)[:160])
    try:
        found = load_next_earnings(ticker)
        context["earnings"] = found.isoformat() if found else None
    except Exception:
        pass
    try:
        news = load_news(ticker, short_name(context["name"]))
        context["news"] = [{**item, "time": item["time"].isoformat()} for item in news[:NEWS_KEEP]]
    except Exception as error:
        print("NEWS FAIL", repr(error)[:160])
    return context


def write_post(post: dict):
    POSTS.mkdir(parents=True, exist_ok=True)
    (POSTS / f"{post['date']}.json").write_text(json.dumps(clean(post), ensure_ascii=False, indent=1))


def clean(value):
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return None if math.isnan(value) or math.isinf(value) else round(value, 4)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


# ------------------------------------------------------------------ 명령

def make_plan(today: date, force: bool = False):
    path = POSTS / f"{today.isoformat()}.json"
    if path.exists() and not force:
        print("이미 오늘 게시물이 있습니다:", path.name)
        return
    if not is_trading_day(today):
        print("오늘은 미국장 휴장일입니다:", today)
        return
    stocks = read_stocks()
    daily = load_daily(stocks)
    daily = daily[daily.index < pd.Timestamp(today)]  # 장중이면 오늘의 미완성 일봉은 뺀다
    hits, near = find_breakouts(daily["Close"], daily["High"], daily["Volume"])
    print(f"스캔 {len(stocks)}종목, 돌파 {len(hits)}개")

    # 5분봉이 충분하고 계획이 성립하는 첫 후보를 고른다.
    chosen = None
    for kind, pool in (("breakout", hits), ("near", near[:10])):
        for candidate in pool[:10]:
            ticker = candidate["ticker"]
            frame = single_daily(daily, ticker)
            levels = daily_levels(frame)
            bars = load_bars(ticker)
            if bars.empty or len({d for d in bars.index.date if d < today}) < 20:
                continue
            level = float(frame["High"].iloc[-RANGE_DAYS:].max())
            risk = round(float(atr(frame).iloc[-1]) * STOP_ATR, 2)
            if risk <= 0:
                continue
            chosen = (kind, candidate, frame, levels, bars, level, risk)
            break
        if chosen:
            break
    if not chosen:
        print("후보를 찾지 못했습니다")
        sys.exit(1)

    kind, candidate, frame, levels, bars, level, risk = chosen
    ticker = candidate["ticker"]
    history = history_test(bars, levels, today)
    times = session_times(today)
    start = (history["medianSlot"] if history["medianSlot"] is not None else slot_of(NO_ENTRY_BEFORE)) + 1
    flat_slot = slot_of(times["flat_by"]) - 1
    sim = time_machine(bar_pool(bars, today), level, risk, start, flat_slot)
    sim["verdict"] = verdict(sim["target"], sim["stop"], sim["neither"], sim["avgR"])
    context = load_context(ticker)
    order = ticket(level, risk)
    recent = frame.tail(30)
    post = {
        "date": today.isoformat(),
        "created": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "name": context["name"],
        "sector": context["sector"],
        "kind": kind,
        "scan": {
            "universe": len(stocks),
            "hits": len(hits),
            "pick": candidate,
            "others": [{k: c[k] for k in ("ticker", "close", "breakout", "volumeRatio")} for c in (hits if kind == "breakout" else near)[:6] if c["ticker"] != ticker][:5],
        },
        "earnings": context["earnings"],
        "news": context["news"],
        "plan": {
            "level": level,
            "risk": risk,
            "atr": float(atr(frame).iloc[-1]),
            "stop": round(level - risk, 2),
            "target": round(level + TARGET_R * risk, 2),
            "targetR": TARGET_R,
            "noEntryBefore": NO_ENTRY_BEFORE.strftime("%H:%M"),
            "noEntryAfter": times["no_entry_after"].strftime("%H:%M"),
            "flatBy": times["flat_by"].strftime("%H:%M"),
            "prevClose": float(frame["Close"].iloc[-1]),
        },
        "daily": {
            "dates": [d.strftime("%Y-%m-%d") for d in recent.index],
            "close": recent["Close"].tolist(),
            "high": recent["High"].tolist(),
            "low": recent["Low"].tolist(),
        },
        "timemachine": {"replay": sim, "history": {k: v for k, v in history.items() if k != "medianSlot"}},
        "ticket": order,
        "result": None,
    }
    write_post(post)
    print("게시물 작성:", today, ticker, sim["verdict"][0])


def fill_results(now: datetime):
    if not POSTS.exists():
        return
    today = now.astimezone(ET).date()
    for path in sorted(POSTS.glob("*.json")):
        post = json.loads(path.read_text())
        if post.get("result"):
            continue
        day = date.fromisoformat(post["date"])
        close_at = datetime.combine(day, session_times(day)["close"], ET) + timedelta(minutes=10)
        if now < close_at:
            continue
        bars = load_bars(post["ticker"])
        session = session_bars(bars, day) if not bars.empty else bars
        if session.empty:
            if (today - day).days > 4:
                post["result"] = {"status": "nodata"}
                write_post(post)
            continue
        plan, order = post["plan"], post["ticket"]
        outcome = run_rule(session, plan["level"], plan["risk"], day)
        result = {
            "status": "done",
            "open": float(session["Open"].iloc[0]),
            "high": float(session["High"].max()),
            "low": float(session["Low"].min()),
            "close": float(session["Close"].iloc[-1]),
            "bars": {"times": [slot_label(int(s)) for s in session["slot"]], "close": session["Close"].tolist()},
            **outcome,
        }
        if outcome["triggered"]:
            result["shares"] = order["shares"]
            result["pnl"] = order["shares"] * (outcome["exit"] - outcome["entry"])
        else:
            result["pnl"] = 0.0
        post["result"] = result
        write_post(post)
        print("결과 기록:", post["date"], post["ticker"], outcome.get("outcome", "미진입"))


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    now = datetime.now(timezone.utc)
    if command == "plan":
        make_plan(now.astimezone(ET).date(), force="--force" in sys.argv)
    elif command == "result":
        fill_results(now)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
