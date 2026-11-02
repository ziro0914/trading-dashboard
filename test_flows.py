import flows
from flows import TOP, rank


def row(name, net):
    return {"name": name, "net": net}


def test_net_buy_sorted_and_positive_only():
    result = rank([row("a", 5), row("b", 9), row("c", -1)], [])
    assert [item["name"] for item in result["netBuy"]] == ["b", "a"]


def test_net_sell_sorted_by_largest_outflow():
    result = rank([], [row("a", -5), row("b", -9), row("c", 3)])
    assert [item["name"] for item in result["netSell"]] == ["b", "a"]


def test_limited_to_top():
    result = rank([row(str(i), i + 1) for i in range(50)], [])
    assert len(result["netBuy"]) == TOP


def test_saved_days_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(flows, "HISTORY_DIR", tmp_path)
    for end in ("2026-10-01", "2026-10-03", "2026-10-02"):
        flows.save_day({"end": end, "netBuy": [], "netSell": []})
    assert [day["end"] for day in flows.load_saved_days()] == ["2026-10-03", "2026-10-02", "2026-10-01"]


def test_saving_same_day_replaces(tmp_path, monkeypatch):
    monkeypatch.setattr(flows, "HISTORY_DIR", tmp_path)
    flows.save_day({"end": "2026-10-01", "netBuy": [], "netSell": []})
    flows.save_day({"end": "2026-10-01", "netBuy": [{"net": 1}], "netSell": []})
    assert len(flows.load_saved_days()) == 1
    assert flows.load_saved_days()[0]["netBuy"] == [{"net": 1}]


def test_known_ticker_is_not_searched(monkeypatch):
    monkeypatch.setattr(flows, "ticker_for", lambda *_: 1 / 0)
    view = {"netBuy": [{"isin": "X", "name": "x"}], "netSell": []}
    flows.attach_tickers(view, {"X": "XYZ"})
    assert view["netBuy"][0]["ticker"] == "XYZ"
