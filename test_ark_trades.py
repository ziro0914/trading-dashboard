from ark_trades import merge_trades


def trade(date, ticker, direction, shares, fund="ARKK"):
    return {"date": date, "ticker": ticker, "direction": direction, "shares": shares, "fund": fund, "company": ticker}


def test_only_latest_date_is_used():
    day = merge_trades([trade("2026-10-29", "OLD", "Buy", 9), trade("2026-10-30", "NEW", "Buy", 1)])
    assert day["date"] == "2026-10-30"
    assert [row["ticker"] for row in day["buy"]] == ["NEW"]


def test_same_ticker_across_funds_is_summed():
    day = merge_trades([trade("2026-10-30", "TSLA", "Sell", 5, "ARKK"), trade("2026-10-30", "TSLA", "Sell", 7, "ARKW")])
    assert day["sell"][0]["shares"] == 12
    assert day["sell"][0]["funds"] == ["ARKK", "ARKW"]


def test_buy_and_sell_are_separated_and_sorted():
    day = merge_trades(
        [trade("2026-10-30", "A", "Buy", 1), trade("2026-10-30", "B", "Buy", 3), trade("2026-10-30", "C", "Sell", 2)]
    )
    assert [row["ticker"] for row in day["buy"]] == ["B", "A"]
    assert [row["ticker"] for row in day["sell"]] == ["C"]
