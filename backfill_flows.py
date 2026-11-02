"""지난 날짜의 순위를 채운다. 실행: python backfill_flows.py [일수]"""
import sys
import time
from datetime import date, timedelta

from flows import HISTORY_DIR, attach_tickers, load_ticker_map, period, save_day, save_ticker_map

PAUSE_SECONDS = 0.5


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 92
    known = load_ticker_map()
    for back in range(1, days + 1):
        day = date.today() - timedelta(days=back)
        if day.weekday() >= 5 or (HISTORY_DIR / f"{day}.json").exists():
            continue
        view = period(day, day)
        if view["netBuy"] or view["netSell"]:
            attach_tickers(view, known)
            save_day(view)
            print("OK", day, flush=True)
        time.sleep(PAUSE_SECONDS)
    save_ticker_map(known)


if __name__ == "__main__":
    main()
