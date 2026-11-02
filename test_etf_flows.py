from etf_flows import SCAN_LIMIT, parse_trend, pension_etfs, rank_day, rank_week


def etf(name, amount):
    return {"itemcode": name, "itemname": name, "amonut": amount}


def test_leveraged_and_inverse_are_excluded():
    items = [etf("KODEX 레버리지", 9), etf("TIGER 인버스", 8), etf("KODEX 2X 나스닥", 7), etf("TIGER 미국S&P500", 1)]
    assert [item["itemname"] for item in pension_etfs(items)] == ["TIGER 미국S&P500"]


def test_scan_keeps_largest_trading_value():
    items = [etf(str(i), i) for i in range(SCAN_LIMIT + 5)]
    kept = pension_etfs(items)
    assert len(kept) == SCAN_LIMIT
    assert kept[0]["amonut"] == SCAN_LIMIT + 4


def test_parse_trend_values_net_in_won():
    days = [{"bizdate": "20261102", "individualPureBuyQuant": "-1,000", "closePrice": "25,355"}]
    row = parse_trend("360750", "TIGER", days)[0]
    assert row["date"] == "2026-11-02"
    assert row["net"] == -25355000


def row(date, code, net):
    return {"date": date, "code": code, "name": code, "net": net}


def test_rank_day_uses_only_that_date():
    rows = [row("2026-11-02", "A", 5), row("2026-10-30", "B", 9)]
    assert [item["code"] for item in rank_day(rows, "2026-11-02")["netBuy"]] == ["A"]


def test_rank_week_sums_each_etf():
    rows = [row("2026-11-02", "A", 5), row("2026-10-30", "A", -8), row("2026-10-30", "B", 2)]
    view = rank_week(rows, ["2026-11-02", "2026-10-30"])
    assert [item["code"] for item in view["netBuy"]] == ["B"]
    assert view["netSell"][0]["net"] == -3
