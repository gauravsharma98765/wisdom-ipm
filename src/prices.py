"""Download daily prices (Yahoo Finance) for the 4 stocks + benchmark indices.

Usage: python prices.py <out_dir>

Notes
- Raw (unadjusted) Close is what matches the trade file's rates, so we keep both
  Close and Adj Close and use Close for trade comparisons.
- Yahoo has no Midcap-100 / Smallcap-100 tickers, so we substitute Midcap-150 and
  Smallcap-250. Midcap-150 only starts in Jan-2019.
"""
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKERS = {
    "AMBER": "AMBER.NS",
    "DBL": "DBL.NS",
    "ZEE": "ZEEL.NS",
    "WELSPUN": "WELSPUNLIV.NS",
    "NIFTY50": "^NSEI",
    "MIDCAP100": "NIFTYMIDCAP150.NS",   # substitute (Midcap-150)
    "SMALLCAP100": "NIFTYSMLCAP250.NS",  # substitute (Smallcap-250)
}


def main(out: Path, start="2015-01-01", end=None):
    end = end or (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    for name, tkr in TICKERS.items():
        d = yf.download(tkr, start=start, end=end, auto_adjust=False, actions=True, progress=False)
        d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
        d.to_csv(out / f"px_{name}.csv")
        print(f"{name:12}{tkr:20}{len(d):6} rows  {d.index.min().date()} -> {d.index.max().date()}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
