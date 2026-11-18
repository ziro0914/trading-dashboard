import yfinance as yf, pandas as pd
out = {}
for t in ["QLD", "QQQ", "KRW=X"]:
    d = yf.Ticker(t).history(start="2025-12-20", auto_adjust=False)
    d.index = d.index.tz_localize(None).date
    out[t + "_close"] = d["Close"]; out[t + "_adj"] = d["Adj Close"]
    if t != "KRW=X":
        out[t + "_open"] = d["Open"]; out[t + "_low"] = d["Low"]; out[t + "_div"] = d["Dividends"]
pd.DataFrame(out).to_csv("backtest/qld_data.csv")
print(pd.DataFrame(out).tail())
