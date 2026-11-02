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


def performance(close: pd.Series) -> dict:
    """연환산 수익률, 연환산 변동성, 샤프지수(무위험수익률 0% 가정)."""
    returns = close.pct_change().dropna()
    years = (close.index[-1] - close.index[0]).days / 365.25
    cagr = (close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    volatility = returns.std() * np.sqrt(TRADING_DAYS)
    sharpe = cagr / volatility if volatility > 0 else np.nan
    return {"cagr": float(cagr), "volatility": float(volatility), "sharpe": float(sharpe)}
