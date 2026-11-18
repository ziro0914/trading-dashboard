import numpy as np
import pandas as pd

import signals


def fake_history(days=900, seed=1, drift=0.0):
    rng = np.random.default_rng(seed)
    close = 50 * np.exp(np.cumsum(rng.normal(drift, 0.05, days)))
    index = pd.bdate_range("2023-01-02", periods=days)
    return pd.DataFrame({"High": close * 1.02, "Low": close * 0.98, "Close": close}, index=index)


def test_levels_are_ordered_around_price():
    item = signals.analyze("SOXL", fake_history(), 3)
    close = item["close"]
    buy1, buy2 = (level["price"] for level in item["levels"]["buy"])
    tp1, tp2 = (level["price"] for level in item["levels"]["takeProfit"])
    assert buy2 < buy1 < close < tp1 < tp2
    assert item["levels"]["stop"]["price"] < buy1
    assert item["signal"] in {"buy", "hold", "sell"}
    assert len(item["chart"]["dates"]) == signals.CHART_DAYS


def test_oversold_after_crash_is_buy_signal():
    hist = fake_history(days=300, seed=2)
    hist.iloc[-8:] = hist.iloc[-9].values * np.linspace(0.95, 0.6, 8)[:, None]
    item = signals.analyze("SOXL", hist, 3)
    assert item["rsi"] < 30
    assert item["reasons"][0].endswith("(+2)")
    assert item["signal"] != "sell"


def test_decay_grows_with_leverage():
    hist = fake_history()
    one = signals.decay(hist["Close"], 1)["yearlyDecay"]
    two = signals.decay(hist["Close"], 2)["yearlyDecay"]
    three = signals.decay(hist["Close"], 3)["yearlyDecay"]
    assert one == 0 and 0 < two < three < 1


def test_backtest_counts_days():
    result = signals.analyze("SOXL", fake_history(), 3)["backtest"]
    assert result["all"]["days"] >= result["buy"]["days"] + result["sell"]["days"]
    assert result["all"]["days"] > 500


def test_build_skips_failures():
    def loader(ticker):
        if ticker == "SOXL":
            return fake_history()
        raise RuntimeError("no data")

    payload = signals.build(loader)
    assert [item["ticker"] for item in payload["items"]] == ["SOXL"]
    assert "PLTR" in payload["errors"]
