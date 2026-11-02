"""미국주식 티커 대시보드. 실행: ./run.sh"""
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import (
    BENCHMARK,
    MARKET_SYMBOLS,
    load_history,
    load_info,
    load_market,
    load_news,
    load_next_earnings,
    search_symbols,
    short_name,
)
from flows import load_flows
from metrics import drawdown, max_drawdown, performance, slice_window

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
WINDOWS = {"1년": 1, "3년": 3, "5년": 5, "10년": 10, "전체": None}
# 핸드폰에서 지표 카드를 두 칸씩 놓는다. 차트가 든 영역은 한 칸을 유지한다.
MOBILE_CSS = """
<style>
@media (max-width: 640px) {
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]):not(:has([data-testid="stPlotlyChart"])) {
    flex-direction: row;
    flex-wrap: wrap;
  }
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]):not(:has([data-testid="stPlotlyChart"]))
    > [data-testid="stColumn"] {
    flex: 1 1 calc(50% - 1rem);
    min-width: calc(50% - 1rem);
  }
  [data-testid="stMetricValue"] { font-size: 1.35rem; }
}
</style>
"""
RATINGS = {
    "strong_buy": "강력 매수",
    "buy": "매수",
    "hold": "보유",
    "underperform": "비중 축소",
    "sell": "매도",
}


def money(value) -> str:
    if value is None:
        return "-"
    for limit, suffix in ((1e12, "조"), (1e9, "십억"), (1e6, "백만")):
        if abs(value) >= limit:
            return f"${value / limit:,.2f}{suffix}"
    return f"${value:,.2f}"


def number(value, digits=2, suffix="") -> str:
    return "-" if value is None else f"{value:,.{digits}f}{suffix}"


def percent(value) -> str:
    return "-" if value is None or pd.isna(value) else f"{value * 100:.1f}%"


def day(value) -> str:
    return "-" if value is None else value.strftime("%Y-%m-%d")


def ago(moment: datetime) -> str:
    hours = (datetime.now(timezone.utc) - moment).total_seconds() / 3600
    if hours < 1:
        return "방금 전"
    return f"{hours:.0f}시간 전" if hours < 24 else f"{hours / 24:.0f}일 전"


def style(fig: go.Figure, height: int, yformat: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", tickformat=yformat)
    return fig


def render_market():
    st.subheader("오늘의 시황")
    try:
        market = load_market()
    except Exception:
        st.warning("시황 데이터를 불러오지 못했습니다.")
        return
    columns = st.columns(4) + st.columns(4)
    for column, (symbol, label) in zip(columns, MARKET_SYMBOLS.items()):
        series = market[symbol].dropna()
        if len(series) < 2:
            column.metric(label, "-")
            continue
        last, previous = series.iloc[-1], series.iloc[-2]
        if symbol == "^TNX":
            column.metric(
                label, f"{last:.2f}%", f"{(last - previous) * 100:+.0f}bp", delta_color="off"
            )
        else:
            column.metric(
                label,
                f"{last:,.2f}",
                f"{last / previous - 1:+.2%}",
                delta_color="inverse" if symbol == "^VIX" else "normal",
            )
    spx = market["^GSPC"].dropna()
    vix = market["^VIX"].dropna()
    if len(spx) >= 200 and len(vix):
        gap = spx.iloc[-1] / spx.tail(200).mean() - 1
        trend = "위" if gap >= 0 else "아래"
        mood = "낮음" if vix.iloc[-1] < 15 else "보통" if vix.iloc[-1] < 25 else "높음"
        st.caption(
            f"S&P 500은 200일 평균선보다 {abs(gap):.1%} {trend}에 있고, "
            f"시장 불안 지표 VIX는 {vix.iloc[-1]:.1f}로 {mood} 수준입니다. "
            f"기준일 {spx.index[-1]:%Y-%m-%d}."
        )


@st.cache_data(ttl=3600, show_spinner=False)
def cached_flows() -> dict:
    return load_flows()


def flow_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "순위": range(1, len(rows) + 1),
            "종목": [row["ticker"] or row["name"] for row in rows],
            "이름": [row["name"] for row in rows],
            "금액": [f"${abs(row['net']) / 1e6:,.1f}백만" for row in rows],
        }
    )


def render_flows():
    st.subheader("한국 투자자 순매수·순매도 TOP 10")
    try:
        flows = cached_flows()
    except Exception:
        st.warning("순위 데이터를 불러오지 못했습니다.")
        return
    for tab, key in zip(st.tabs(["하루", "1주"]), ("daily", "weekly")):
        view = flows[key]
        left, right = tab.columns(2)
        left.markdown("**순매수**")
        left.dataframe(flow_table(view["netBuy"]), hide_index=True, width="stretch")
        right.markdown("**순매도**")
        right.dataframe(flow_table(view["netSell"]), hide_index=True, width="stretch")
        tab.caption(
            f"결제일 {view['start']} ~ {view['end']} 기준이라 실제 매매일과 1~2일 차이가 납니다. "
            "예탁결제원을 거친 내역만 집계되며, 순매도는 매도결제 상위 50개 종목에서 계산했습니다. 출처: SEIBro."
        )


def render_profile(ticker, info, hist):
    last_close = float(hist["Close"].iloc[-1])
    price = info.get("currentPrice") or info.get("regularMarketPrice") or last_close
    previous = info.get("previousClose") or float(hist["Close"].iloc[-2])
    name = info.get("longName") or info.get("shortName") or ticker
    st.header(f"{name} ({ticker})")
    tags = [info.get("sector"), info.get("industry"), info.get("exchange")]
    if info.get("quoteType") == "ETF":
        tags = ["ETF", info.get("category")]
    st.caption(" · ".join(tag for tag in tags if tag))

    target = info.get("targetMeanPrice")
    upside = f"{target / price - 1:+.1%}" if target else None
    high, low = info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow")
    rating = RATINGS.get(info.get("recommendationKey"), "-")
    analysts = info.get("numberOfAnalystOpinions")
    try:
        earnings = load_next_earnings(ticker)
    except Exception:
        earnings = None

    first = st.columns(4)
    first[0].metric("현재가", f"${price:,.2f}", f"{price / previous - 1:+.2%}")
    if info.get("quoteType") == "ETF":
        first[1].metric("운용자산", money(info.get("totalAssets")))
    else:
        first[1].metric("시가총액", money(info.get("marketCap")))
    first[2].metric("PER (최근 / 예상)", f"{number(info.get('trailingPE'), 1)} / {number(info.get('forwardPE'), 1)}")
    first[3].metric("EPS (최근)", number(info.get("trailingEps")))
    second = st.columns(4)
    second[0].metric("52주 고가 / 저가", f"{number(high)} / {number(low)}")
    second[1].metric("배당수익률", number(info.get("dividendYield"), suffix="%"))
    second[2].metric("베타", number(info.get("beta")))
    second[3].metric("다음 실적 발표", day(earnings))
    third = st.columns(4)
    third[0].metric("애널리스트 목표가 평균", number(target), upside, delta_color="off")
    third[1].metric("애널리스트 의견", f"{rating} ({analysts}명)" if analysts else rating)

    summary = info.get("longBusinessSummary")
    if summary:
        with st.expander("회사 소개 (영문)"):
            st.write(summary)


def render_price(ticker, close, years):
    st.subheader("주가")
    # 이동평균이 기간 시작부터 이어지도록 전체 데이터로 계산한 뒤 자른다.
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    window = slice_window(close, years)
    fig = go.Figure()
    fig.add_scatter(x=window.index, y=window, name=ticker, line=dict(color=BLUE, width=2))
    fig.add_scatter(x=window.index, y=ma50.loc[window.index], name="50일 평균", line=dict(color=ORANGE, width=2))
    fig.add_scatter(x=window.index, y=ma200.loc[window.index], name="200일 평균", line=dict(color=AQUA, width=2))
    st.plotly_chart(style(fig, 360, "$,.0f"), width="stretch", config={"displayModeBar": False})


def render_risk(ticker, adjusted, benchmark, years):
    st.subheader("낙폭과 위험")
    close = slice_window(adjusted, years)
    compare = ticker != BENCHMARK and not benchmark.empty
    bench = slice_window(benchmark, years)
    bench = bench[bench.index >= close.index[0]]
    detail = max_drawdown(close)
    perf = performance(close)

    columns = st.columns(4)
    columns[0].metric("MDD", percent(detail["mdd"]))
    columns[1].metric("현재 고점 대비", percent(detail["current"]))
    columns[2].metric("연환산 수익률", percent(perf["cagr"]))
    columns[3].metric("연환산 변동성", percent(perf["volatility"]))
    recovery = day(detail["recovery"]) if detail["recovery"] is not None else "아직 회복 전"
    st.caption(
        f"MDD 구간: 고점 {day(detail['peak'])} → 저점 {day(detail['trough'])} → 회복 {recovery}. "
        "배당을 재투자했다고 가정한 수익률 기준이며, 선택한 기간 안의 고점으로 계산합니다."
    )

    fig = go.Figure()
    series = drawdown(close)
    fig.add_scatter(x=series.index, y=series, name=ticker, line=dict(color=BLUE, width=2))
    if compare:
        fig.add_scatter(
            x=bench.index, y=drawdown(bench), name=f"{BENCHMARK} (S&P 500)", line=dict(color=ORANGE, width=2)
        )
    fig.add_scatter(
        x=[detail["trough"]],
        y=[detail["mdd"]],
        mode="markers+text",
        marker=dict(color=BLUE, size=9),
        text=[f"MDD {percent(detail['mdd'])}"],
        textposition="middle right",
        showlegend=False,
        hoverinfo="skip",
    )
    st.plotly_chart(style(fig, 280, ".0%"), width="stretch", config={"displayModeBar": False})

    rows = []
    for label, span in WINDOWS.items():
        part = slice_window(adjusted, span)
        if span is not None and (adjusted.index[-1] - adjusted.index[0]).days < span * 365:
            continue
        part_perf = performance(part)
        row = {"기간": label, f"{ticker} MDD": percent(max_drawdown(part)["mdd"])}
        if compare:
            part_bench = slice_window(benchmark, span)
            part_bench = part_bench[part_bench.index >= part.index[0]]
            row[f"{BENCHMARK} MDD"] = percent(max_drawdown(part_bench)["mdd"])
        row["연환산 수익률"] = percent(part_perf["cagr"])
        row["변동성"] = percent(part_perf["volatility"])
        row["샤프지수"] = number(part_perf["sharpe"])
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_news(ticker, info):
    st.subheader("관련 뉴스")
    try:
        name = short_name(info.get("longName")) if info.get("quoteType") != "ETF" else None
        news = load_news(ticker, name)
    except Exception:
        st.warning("뉴스를 불러오지 못했습니다.")
        return
    if not news:
        st.info("최근 뉴스를 찾지 못했습니다.")
    for item in news:
        title = item["title"].replace("[", "\\[").replace("]", "\\]").replace("$", "\\$")
        st.markdown(f"[{title}]({item['link']})  \n{item['source']} · {ago(item['time'])}")


def main():
    st.set_page_config(page_title="미국주식 대시보드", page_icon="📈", layout="wide")
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)
    st.title("미국주식 대시보드")
    if "query" not in st.session_state:
        st.session_state.query = st.query_params.get("ticker", "AAPL")
    left, middle, right = st.columns([1, 1, 1])
    query = left.text_input("티커 또는 회사명", key="query", placeholder="TSLA, tesla, 테슬라").strip()
    period = right.segmented_control("기간", list(WINDOWS), default="5년") or "5년"

    render_market()
    render_flows()
    st.divider()

    candidates = search_symbols(query) if query else []
    if not candidates:
        st.error(f"'{query}'에 해당하는 미국 종목을 찾지 못했습니다. 예: AAPL, tesla, 테슬라")
        return
    ticker = candidates[0]["ticker"]
    if len(candidates) > 1:
        labels = {item["ticker"]: f"{item['ticker']} · {item['name'] or '이름 없음'}" for item in candidates}
        ticker = middle.selectbox("검색 결과", list(labels), format_func=labels.get, key=f"pick_{query}")
    st.query_params["ticker"] = ticker

    with st.spinner(f"{ticker} 데이터를 불러오는 중"):
        try:
            hist = load_history(ticker)
        except Exception:
            st.error("가격 데이터를 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
            return
        if len(hist) < 2:
            st.error(f"{ticker} 종목을 찾지 못했습니다. 티커를 확인해 주세요.")
            return
        try:
            info = load_info(ticker)
        except Exception:
            info = {}
            st.warning("종목 정보를 불러오지 못해 가격 정보만 표시합니다.")
        try:
            benchmark = load_history(BENCHMARK)["Adj Close"]
        except Exception:
            benchmark = pd.Series(dtype=float)

    years = WINDOWS[period]
    render_profile(ticker, info, hist)
    st.divider()
    chart, side = st.columns([2, 1])
    with chart:
        render_price(ticker, hist["Close"], years)
        render_risk(ticker, hist["Adj Close"], benchmark, years)
    with side:
        render_news(ticker, info)
    st.caption("데이터: Yahoo Finance, Google News, 예탁결제원 SEIBro. 시세는 지연될 수 있고 투자 판단의 참고 자료입니다.")


main()
