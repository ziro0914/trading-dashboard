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
