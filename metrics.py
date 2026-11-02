"""수익률·위험 지표 계산. 입력은 날짜 인덱스의 배당 반영 종가 Series."""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def slice_window(close: pd.Series, years: int | None) -> pd.Series:
    if years is None or close.empty:
        return close
    return close[close.index >= close.index[-1] - pd.DateOffset(years=years)]


def drawdown(close: pd.Series) -> pd.Series:
    return close / close.cummax() - 1


def max_drawdown(close: pd.Series) -> dict:
    """MDD와 고점·저점·회복일. 아직 회복하지 못했으면 recovery는 None."""
    dd = drawdown(close)
    trough = dd.idxmin()
    peak = close.loc[:trough].idxmax()
    after = close.loc[trough:]
    recovered = after[after >= close.loc[peak]]
    return {
        "mdd": float(dd.min()),
        "peak": peak,
        "trough": trough,
        "recovery": recovered.index[0] if not recovered.empty else None,
        "current": float(dd.iloc[-1]),
    }


def rsi(close: pd.Series, period: int = 14) -> float:
    """윌더 방식 RSI의 마지막 값."""
    change = close.diff().dropna()
    gain = change.clip(lower=0).ewm(alpha=1 / period, min_periods=period).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / period, min_periods=period).mean()
    if loss.iloc[-1] == 0:
        return 100.0
    return float(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1]))


def technical_summary(close: pd.Series) -> dict:
    """RSI와 이동평균 배열로 현재 상태를 요약한다. 자료가 짧으면 값이 None이다."""
    last = float(close.iloc[-1])
    ma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    ma200 = float(close.tail(200).mean()) if len(close) >= 200 else None
    strength = rsi(close) if len(close) > 14 else None
    trend = None
    if ma50 is not None and ma200 is not None:
        trend = "상승 추세" if last > ma50 > ma200 else "하락 추세" if last < ma50 < ma200 else "혼조"
    momentum = None
    if strength is not None:
        momentum = "과매수" if strength >= 70 else "과매도" if strength <= 30 else "중립"
    return {
        "rsi": strength,
        "momentum": momentum,
        "trend": trend,
        "gapMa50": last / ma50 - 1 if ma50 else None,
        "gapMa200": last / ma200 - 1 if ma200 else None,
    }


def performance(close: pd.Series) -> dict:
    """연환산 수익률, 연환산 변동성, 샤프지수(무위험수익률 0% 가정)."""
    returns = close.pct_change().dropna()
    years = (close.index[-1] - close.index[0]).days / 365.25
    cagr = (close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    volatility = returns.std() * np.sqrt(TRADING_DAYS)
    sharpe = cagr / volatility if volatility > 0 else np.nan
    return {"cagr": float(cagr), "volatility": float(volatility), "sharpe": float(sharpe)}
