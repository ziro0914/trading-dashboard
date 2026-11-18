import yfinance as yf, pandas as pd
out = {}
for t in ["QLD", "QQQ", "KRW=X"]:
    d = yf.Ticker(t).history(start="2006-06-01", auto_adjust=False)
    d.index = d.index.tz_localize(None).date
    out[t + "_close"] = d["Close"]; out[t + "_adj"] = d["Adj Close"]
    if t != "KRW=X":
        out[t + "_open"] = d["Open"]; out[t + "_low"] = d["Low"]; out[t + "_div"] = d["Dividends"]
pd.DataFrame(out).to_csv("backtest/qld_data.csv")
print(pd.DataFrame(out).tail())

# 나스닥100 지수와 단기금리 (QLD 상장 전 2배 합성용)
o = {}
for t in ["^NDX", "^IRX", "KRW=X", "^GSPC", "^SP500TR", "BTC-USD", "IBIT"]:
    d = yf.Ticker(t).history(start="1985-01-01", auto_adjust=False)
    d.index = d.index.tz_localize(None).date
    o[t] = d["Close"]
pd.DataFrame(o).to_csv("backtest/ndx_long.csv")
print(pd.DataFrame(o).dropna().head())
