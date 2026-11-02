from data import merge_candidates, naver_candidates, yahoo_candidates


def test_yahoo_keeps_only_us_stocks_and_etfs():
    quotes = [
        {"symbol": "TSLA", "quoteType": "EQUITY", "exchange": "NMS", "shortname": "Tesla, Inc."},
        {"symbol": "STSLA=F", "quoteType": "FUTURE", "exchange": "CME"},
        {"symbol": "TSLZ", "quoteType": "ETF", "exchange": "BTS", "shortname": "Inverse"},
        {"symbol": "TL0.DE", "quoteType": "EQUITY", "exchange": "GER"},
    ]
    assert [item["ticker"] for item in yahoo_candidates(quotes)] == ["TSLA", "TSLZ"]


def test_naver_keeps_us_and_converts_class_shares():
    items = [
        {"code": "BRK B", "name": "버크셔 해서웨이 Class B", "nationCode": "USA"},
        {"code": "005930", "name": "삼성전자", "nationCode": "KOR"},
    ]
    assert naver_candidates(items) == [{"ticker": "BRK-B", "name": "버크셔 해서웨이 Class B"}]


def test_exact_ticker_moves_first():
    found = [{"ticker": "SPYM", "name": "a"}, {"ticker": "SPY", "name": "b"}]
    assert merge_candidates(found, "SPY")[0]["ticker"] == "SPY"


def test_duplicates_removed_keeping_order():
    found = [{"ticker": "A", "name": "1"}, {"ticker": "B", "name": "2"}, {"ticker": "A", "name": "3"}]
    assert [item["ticker"] for item in merge_candidates(found, None)] == ["A", "B"]


def test_unknown_ticker_format_still_tried():
    assert merge_candidates([], "ZZZZQ") == [{"ticker": "ZZZZQ", "name": None}]


def test_name_like_input_does_not_become_a_ticker():
    found = [{"ticker": "TSLA", "name": "Tesla, Inc."}]
    assert merge_candidates(found, "TESLA")[0]["ticker"] == "TSLA"
    assert len(merge_candidates(found, "TESLA")) == 1


def test_nothing_found():
    assert merge_candidates([], None) == []
