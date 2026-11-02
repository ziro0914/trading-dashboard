import pandas as pd

from metrics import drawdown, max_drawdown, performance, slice_window


def series(values, start="2024-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype=float)


def test_mdd_recovered():
    close = series([100, 120, 60, 90, 130])
    result = max_drawdown(close)
    assert result["mdd"] == -0.5
    assert result["peak"] == close.index[1]
    assert result["trough"] == close.index[2]
    assert result["recovery"] == close.index[4]
    assert result["current"] == 0


def test_mdd_not_recovered():
    result = max_drawdown(series([100, 200, 100, 150]))
    assert result["mdd"] == -0.5
    assert result["recovery"] is None
    assert result["current"] == -0.25


def test_mdd_uses_largest_of_two_declines():
    result = max_drawdown(series([100, 80, 100, 110, 55, 60]))
    assert result["mdd"] == -0.5


def test_rising_series_has_no_drawdown():
    assert max_drawdown(series([1, 2, 3]))["mdd"] == 0
    assert (drawdown(series([1, 2, 3])) == 0).all()


def test_cagr_doubles_over_two_years():
    close = pd.Series(
        [100.0, 200.0], index=pd.to_datetime(["2020-01-01", "2022-01-01"])
    )
    assert abs(performance(close)["cagr"] - (2 ** (1 / (731 / 365.25)) - 1)) < 1e-9


def test_slice_window():
    close = series(range(1, 800))
    assert slice_window(close, 1).index[0] == close.index[-1] - pd.DateOffset(years=1)
    assert len(slice_window(close, None)) == len(close)
