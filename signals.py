"""보유 종목 매매 신호: RSI·이동평균·볼린저밴드·지지/저항·ATR로 분할 매수·익절·손절 가격대를 계산한다.

신호는 하루 종가 기준이며 미래를 보장하지 않는다. 실제 주문은 하지 않는다.
"""
import math

import numpy as np
import pandas as pd

# (티커, 레버리지 배수). 첫 종목이 주력이다.
HOLDINGS = [
    ("SOXL", 3),
    ("SNXX", 2),
    ("PTIR", 2),
    ("RKLX", 2),
    ("JOBY", 1),
    ("RGTX", 2),
    ("PLTR", 1),
    ("SMU", 2),
    ("MVLL", 2),
    ("OKLL", 2),
    ("DNN", 1),
]
CHART_DAYS = 180
FORWARD_DAYS = 10
BACKTEST_YEARS = 3
TRADING_DAYS = 252


def wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def indicators(hist: pd.DataFrame) -> pd.DataFrame:
    """일봉(Open/High/Low/Close)에 지표 열을 붙인다."""
    frame = hist[["High", "Low", "Close"]].astype(float).copy()
    close = frame["Close"]
    change = close.diff()
    gain = wilder(change.clip(lower=0), 14)
    loss = wilder(-change.clip(upper=0), 14)
    frame["rsi"] = np.where(loss == 0, 100.0, 100 - 100 / (1 + gain / loss.replace(0, np.nan)))
    frame.loc[gain.isna(), "rsi"] = np.nan
    for days in (20, 50, 200):
        frame[f"sma{days}"] = close.rolling(days).mean()
    std = close.rolling(20).std()
    frame["bbUpper"] = frame["sma20"] + 2 * std
    frame["bbLower"] = frame["sma20"] - 2 * std
    previous = close.shift()
    true_range = pd.concat(
        [frame["High"] - frame["Low"], (frame["High"] - previous).abs(), (frame["Low"] - previous).abs()], axis=1
    ).max(axis=1)
    frame["atr"] = wilder(true_range, 14)
    frame["low20"] = frame["Low"].rolling(20).min()
    frame["high20"] = frame["High"].rolling(20).max()
    frame["low60"] = frame["Low"].rolling(60).min()
    frame["high60"] = frame["High"].rolling(60).max()
    frame["slope20"] = frame["sma20"] - frame["sma20"].shift(5)
    frame["score"] = score_series(frame)
    return frame


def score_series(frame: pd.DataFrame) -> pd.Series:
    """날마다의 점수. +면 매수 쪽, -면 매도 쪽. 백테스트와 오늘 신호가 같은 규칙을 쓴다."""
    close, rsi = frame["Close"], frame["rsi"]
    score = pd.Series(0, index=frame.index, dtype=float)
    score += np.select([rsi <= 30, rsi <= 40, rsi >= 70, rsi >= 60], [2, 1, -2, -1], 0)
    score += np.select([close <= frame["bbLower"], close >= frame["bbUpper"]], [1, -1], 0)
    score += np.select(
        [(close > frame["sma20"]) & (frame["slope20"] > 0), (close < frame["sma20"]) & (frame["slope20"] < 0)], [1, -1], 0
    )
    return score.where(rsi.notna() & frame["sma20"].notna())


def label(score: float) -> str:
    if score >= 2:
        return "buy"
    if score <= -2:
        return "sell"
    return "hold"


def reasons(row: pd.Series) -> list[str]:
    close, rsi = row["Close"], row["rsi"]
    out = []
    if rsi <= 30:
        out.append(f"RSI {rsi:.0f}: 과매도 구간 (+2)")
    elif rsi <= 40:
        out.append(f"RSI {rsi:.0f}: 약세지만 바닥권에 가까움 (+1)")
    elif rsi >= 70:
        out.append(f"RSI {rsi:.0f}: 과매수 구간 (−2)")
    elif rsi >= 60:
        out.append(f"RSI {rsi:.0f}: 많이 오른 편 (−1)")
    else:
        out.append(f"RSI {rsi:.0f}: 중립 (0)")
    if close <= row["bbLower"]:
        out.append("볼린저밴드 하단 아래: 단기 과하게 빠짐 (+1)")
    elif close >= row["bbUpper"]:
        out.append("볼린저밴드 상단 위: 단기 과하게 오름 (−1)")
    if close > row["sma20"] and row["slope20"] > 0:
        out.append("20일선 위, 20일선 상승 중: 단기 흐름 양호 (+1)")
    elif close < row["sma20"] and row["slope20"] < 0:
        out.append("20일선 아래, 20일선 하락 중: 단기 흐름 약함 (−1)")
    if not math.isnan(row["sma200"]):
        if close < row["sma50"] < row["sma200"]:
            out.append("50일선·200일선 아래 역배열: 중기 하락 추세 (참고)")
        elif close > row["sma50"] > row["sma200"]:
            out.append("50일선·200일선 위 정배열: 중기 상승 추세 (참고)")
    return out


def pick_levels(close: float, atr: float, candidates: dict[str, float], below: bool) -> list[dict]:
    """현재가 아래(지지) 또는 위(저항)의 가까운 가격대 두 개. 서로 0.5 ATR 이상 떨어뜨린다."""
    gap = 0.5 * atr
    side = [
        (value, name)
        for name, value in candidates.items()
        if value is not None and not math.isnan(value) and (value <= close - gap if below else value >= close + gap)
    ]
    side.sort(reverse=below)
    picked = []
    for value, name in side:
        if all(abs(value - p["price"]) >= gap for p in picked):
            picked.append({"price": float(value), "basis": name})
        if len(picked) == 2:
            break
    # 가까운 가격대가 모자라면 현재가에서 ATR 배수만큼 떨어진 곳을 쓴다.
    step, multiple = (-1, 1.0) if below else (1, 1.5)
    while len(picked) < 2:
        while picked and abs(close + step * multiple * atr - picked[-1]["price"]) < gap:
            multiple += 0.5
        if picked and (close + step * multiple * atr - picked[-1]["price"]) * step < 0:
            multiple = abs(picked[-1]["price"] - close) / atr + 1
        picked.append({"price": float(close + step * multiple * atr), "basis": f"현재가 {'−' if below else '+'}{multiple:.1f} ATR"})
    return picked


def backtest(frame: pd.DataFrame) -> dict:
    """과거에 같은 규칙이 매수·매도 신호를 낸 날, 10거래일 뒤 수익률."""
    recent = frame[frame.index >= frame.index[-1] - pd.DateOffset(years=BACKTEST_YEARS)]
    forward = (frame["Close"].shift(-FORWARD_DAYS) / frame["Close"] - 1).reindex(recent.index)
    signal = recent["score"].map(lambda s: None if pd.isna(s) else label(s))
    valid = forward.notna() & signal.notna()

    def stats(mask):
        values = forward[valid & mask]
        if values.empty:
            return {"days": 0, "upRate": None, "median": None}
        return {"days": int(len(values)), "upRate": float((values > 0).mean()), "median": float(values.median())}

    return {
        "years": BACKTEST_YEARS,
        "forwardDays": FORWARD_DAYS,
        "from": recent.index[0].strftime("%Y-%m-%d"),
        "buy": stats(signal == "buy"),
        "sell": stats(signal == "sell"),
        "all": stats(signal.notna()),
    }


def decay(close: pd.Series, leverage: int) -> dict:
    """변동성 때문에 횡보장에서 깎이는 비율(연간, 추정). 레버리지 L, 연변동성 σ면 (L−1)/(2L)·σ²."""
    returns = close.pct_change().dropna().tail(TRADING_DAYS)
    vol = float(returns.std() * math.sqrt(TRADING_DAYS)) if len(returns) > 20 else None
    drag = (leverage - 1) / (2 * leverage) * vol**2 if vol is not None and leverage > 1 else 0.0
    year = close[close.index >= close.index[-1] - pd.DateOffset(years=1)]
    return {
        "leverage": leverage,
        "volatility": vol,
        "yearlyDecay": 1 - math.exp(-drag) if vol is not None else None,
        "return1y": float(year.iloc[-1] / year.iloc[0] - 1) if len(year) > 1 else None,
        "fromHigh1y": float(close.iloc[-1] / year.max() - 1) if len(year) else None,
    }


def analyze(ticker: str, hist: pd.DataFrame, leverage: int) -> dict:
    frame = indicators(hist)
    if len(frame) < 30 or frame["rsi"].isna().iloc[-1]:
        raise ValueError(f"{ticker}: 자료 부족 ({len(frame)}일)")
    row = frame.iloc[-1]
    close, atr = float(row["Close"]), float(row["atr"])
    supports = pick_levels(
        close,
        atr,
        {
            "20일 최저가": row["low20"],
            "60일 최저가": row["low60"],
            "볼린저밴드 하단": row["bbLower"],
            "20일선": row["sma20"],
            "50일선": row["sma50"],
            "200일선": row["sma200"],
        },
        below=True,
    )
    resistances = pick_levels(
        close,
        atr,
        {
            "20일 최고가": row["high20"],
            "60일 최고가": row["high60"],
            "볼린저밴드 상단": row["bbUpper"],
            "20일선": row["sma20"],
            "50일선": row["sma50"],
            "200일선": row["sma200"],
        },
        below=False,
    )
    stop = supports[0]["price"] - 1.5 * atr
    chart = frame.tail(CHART_DAYS)

    def series(name):
        return [None if pd.isna(v) else round(float(v), 4) for v in chart[name]]

    nan = lambda v: None if pd.isna(v) else float(v)  # noqa: E731
    return {
        "ticker": ticker,
        "leverage": leverage,
        "date": frame.index[-1].strftime("%Y-%m-%d"),
        "close": close,
        "change": float(close / frame["Close"].iloc[-2] - 1),
        "signal": label(row["score"]),
        "score": int(row["score"]),
        "reasons": reasons(row),
        "rsi": float(row["rsi"]),
        "atr": atr,
        "sma20": nan(row["sma20"]),
        "sma50": nan(row["sma50"]),
        "sma200": nan(row["sma200"]),
        "levels": {
            "buy": supports,
            "takeProfit": resistances,
            "stop": {"price": float(stop), "basis": "1차 매수가 − 1.5 ATR"},
        },
        "backtest": backtest(frame),
        "decay": decay(frame["Close"], leverage),
        "chart": {
            "dates": [d.strftime("%Y-%m-%d") for d in chart.index],
            "close": series("Close"),
            "sma20": series("sma20"),
            "sma50": series("sma50"),
            "bbUpper": series("bbUpper"),
            "bbLower": series("bbLower"),
        },
    }


def build(load_history, load_name=lambda ticker: None) -> dict:
    """load_history(ticker) -> High/Low/Close 일봉 DataFrame. 실패한 종목은 errors에 남긴다."""
    items, errors = [], []
    for ticker, leverage in HOLDINGS:
        try:
            item = analyze(ticker, load_history(ticker), leverage)
            item["name"] = load_name(ticker) or ticker
            items.append(item)
        except Exception as error:
            errors.append(ticker)
            print("SIGNAL FAIL", ticker, repr(error)[:160], flush=True)
    return {"items": items, "errors": errors}
