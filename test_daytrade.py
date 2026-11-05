from datetime import date

import numpy as np
import pandas as pd

import pytest

import daytrade as dt


@pytest.fixture(autouse=True)
def two_r(monkeypatch):
    monkeypatch.setattr(dt, "TARGET_R", 2.0)

DAY = date(2026, 11, 4)


def bars_for(day, closes, highs=None, lows=None):
    index = pd.date_range(f"{day} 09:30", periods=len(closes), freq="5min", tz=dt.ET)
    closes = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": np.array(highs, dtype=float) if highs is not None else closes + 0.1,
            "Low": np.array(lows, dtype=float) if lows is not None else closes - 0.1,
            "Close": closes,
            "Volume": 1000,
        },
        index=index,
    )


def test_no_entry_in_first_15_minutes():
    # 9:30~9:40 봉이 기준가를 넘어도 진입하지 않고, 9:45 봉(slot 3)에서 진입한다.
    closes = [101, 101, 101, 101] + [101] * 74
    result = dt.run_rule(dt.session_bars(bars_for(DAY, closes), DAY), level=100, risk=1, day=DAY)
    assert result["triggered"] and result["entrySlot"] == 3 and result["entryTime"] == "9:50"


def test_target_hit():
    closes = [99] * 5 + [100.5] + [101, 102, 103] + [103] * 69
    result = dt.run_rule(dt.session_bars(bars_for(DAY, closes), DAY), level=100, risk=1, day=DAY)
    assert result["outcome"] == "target"
    assert result["exit"] == 102.5 and result["r"] == 2


def test_stop_checked_before_target_in_same_bar():
    closes = [99] * 5 + [100.5] + [100.5] * 72
    highs = [c + 0.1 for c in closes]
    lows = [c - 0.1 for c in closes]
    highs[6], lows[6] = 110, 90
    result = dt.run_rule(dt.session_bars(bars_for(DAY, closes, highs, lows), DAY), level=100, risk=1, day=DAY)
    assert result["outcome"] == "stop" and result["r"] == -1


def test_flat_by_close_when_neither():
    closes = [99] * 5 + [100.5] + [100.8] * 72
    result = dt.run_rule(dt.session_bars(bars_for(DAY, closes), DAY), level=100, risk=1, day=DAY)
    assert result["outcome"] == "close" and result["exitTime"] == "15:55"
    assert abs(result["r"] - 0.3) < 1e-9


def test_no_trigger():
    result = dt.run_rule(dt.session_bars(bars_for(DAY, [99] * 78), DAY), level=100, risk=1, day=DAY)
    assert result == {"triggered": False}


def test_ticket_sizes_to_max_loss_and_cash():
    order = dt.ticket(level=200, risk=3)
    assert order["shares"] == 16 and order["lossAtStop"] == 48 and order["cost"] <= 5000
    expensive = dt.ticket(level=1000, risk=1)
    assert expensive["shares"] == 5 and expensive["limitedBy"] == "현금"


def test_time_machine_is_repeatable_and_sums_to_one():
    pool = {s: np.array([[1.002, 0.998, 1.0005], [1.001, 0.997, 0.999]]) for s in range(1, 78)}
    first = dt.time_machine(pool, entry=100, risk=0.5, start_slot=5, flat_slot=76, replays=2000)
    again = dt.time_machine(pool, entry=100, risk=0.5, start_slot=5, flat_slot=76, replays=2000)
    assert first == again
    assert abs(first["target"] + first["stop"] + first["neither"] - 1) < 1e-9


def test_verdict_uses_break_even_for_target_r():
    # 2R 목표면 손익분기는 33%. 25% vs 50% → 한쪽에 닿은 것 중 33% → 손익분기 근처.
    assert dt.verdict(0.25, 0.5, 0.25, 0.0)[0].startswith("손익분기 근처")
    assert "손절가 쪽으로 강하게" in dt.verdict(0.05, 0.6, 0.35, -0.8)[0]


def test_breakout_scan():
    index = pd.date_range("2026-08-01", periods=40, freq="B")
    closes = pd.DataFrame({"UP": np.r_[np.full(39, 50.0), 55.0], "FLAT": np.full(40, 50.0)}, index=index)
    volumes = pd.DataFrame({"UP": 2e6, "FLAT": 2e6}, index=index)
    hits, near = dt.find_breakouts(closes, closes + 1, volumes)
    assert [h["ticker"] for h in hits] == ["UP"] and [n["ticker"] for n in near] == ["FLAT"]


def test_calendar():
    assert not dt.is_trading_day(date(2026, 11, 26))
    assert dt.session_times(date(2026, 11, 27))["flat_by"].hour == 12
