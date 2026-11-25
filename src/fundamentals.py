"""Point-in-time fundamentals from Screener.in CSV exports.

Why point-in-time: a decision made on 1-Jun-2020 may only use numbers that were public
on that date. Annual results are assumed public 60 days after FY end (SEBI deadline);
shareholding is assumed public 21 days after quarter end. Using FY-end dates directly
would leak the future into any backtest.

Files expected in <dir>: <TICKER>_{pl,bs,cf,ratios,sh}.csv  (see scripts/screener fetch)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RESULT_LAG_DAYS = 60
SHAREHOLDING_LAG_DAYS = 21


def _num(x):
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).replace(",", "").replace("%", "").replace("+", "").strip()
    try:
        return float(s)
    except ValueError:
        return np.nan


def _table(d: Path, tk: str, tag: str) -> pd.DataFrame:
    """metric x period table; periods parsed to month-end timestamps, TTM dropped."""
    df = pd.read_csv(d / f"{tk}_{tag}.csv")
    df["metric"] = df["metric"].astype(str).str.split("  ").str[0].str.strip()  # drop Screener tooltip text
    df = df.drop_duplicates("metric").set_index("metric")
    cols = {}
    for c in df.columns:
        try:
            cols[c] = pd.to_datetime(c, format="%b %Y") + pd.offsets.MonthEnd(0)
        except ValueError:
            pass  # 'TTM'
    out = df[list(cols)].rename(columns=cols).apply(lambda s: s.map(_num))
    return out


def annual(d: Path, tk: str) -> pd.DataFrame:
    """One row per fiscal year (March year-end) with derived ratios; index = FY end date."""
    pl, bs, cf, ra = (_table(d, tk, t) for t in ("pl", "bs", "cf", "ratios"))
    fy = [c for c in pl.columns if c.month == 3]
    g = lambda t, m: t.loc[m].reindex(fy) if m in t.index else pd.Series(np.nan, index=fy)
    A = pd.DataFrame(index=pd.DatetimeIndex(fy, name="fy_end"))
    A["revenue"] = g(pl, "Sales").values
    A["ebitda"] = g(pl, "Operating Profit").values
    A["pat"] = g(pl, "Net Profit").values
    A["eps"] = g(pl, "EPS in Rs").values
    A["interest"] = g(pl, "Interest").values
    A["opm"] = A.ebitda / A.revenue
    A["equity"] = (g(bs, "Equity Capital") + g(bs, "Reserves")).values
    A["debt"] = g(bs, "Borrowings").values
    A["cfo"] = g(cf, "Cash from Operating Activity").reindex(fy).values
    A["fcf"] = g(cf, "Free Cash Flow").reindex(fy).values
    A["roce"] = g(ra, "ROCE %").reindex(fy).values / 100
    A["roe"] = A.pat / A.equity.rolling(2, min_periods=1).mean()
    A["de"] = A.debt / A.equity
    A["int_cover"] = A.ebitda / A.interest.replace(0, np.nan)
    A["cfo_ebitda"] = A.cfo / A.ebitda
    A["rev_cagr_3y"] = (A.revenue / A.revenue.shift(3)) ** (1 / 3) - 1
    A["eps_cagr_3y"] = np.where((A.eps > 0) & (A.eps.shift(3) > 0), (A.eps / A.eps.shift(3)) ** (1 / 3) - 1, np.nan)
    A["opm_chg_3y"] = A.opm - A.opm.shift(3)
    A["fcf_3y"] = A.fcf.rolling(3).sum()
    A["avail"] = A.index + pd.Timedelta(days=RESULT_LAG_DAYS)
    return A


def promoter(d: Path, tk: str) -> pd.Series:
    sh = _table(d, tk, "sh")
    s = sh.loc["Promoters"].dropna() if "Promoters" in sh.index else pd.Series(dtype=float)
    s.index = s.index + pd.Timedelta(days=SHAREHOLDING_LAG_DAYS)
    return s / 100


def snapshot(A: pd.DataFrame, P: pd.Series, date) -> dict | None:
    """Latest fundamentals knowable on `date`."""
    date = pd.Timestamp(date)
    a = A[A.avail <= date]
    if len(a) < 4:
        return None
    r = a.iloc[-1].to_dict()
    r["fy"] = a.index[-1]
    p = P[P.index <= date]
    r["promoter"] = p.iloc[-1] if len(p) else np.nan
    r["promoter_chg_2y"] = (p.iloc[-1] - p[p.index <= date - pd.Timedelta(days=730)].iloc[-1]) if len(p) and (p.index <= date - pd.Timedelta(days=730)).any() else np.nan
    return r


if __name__ == "__main__":
    import sys

    d = Path(sys.argv[1])
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    for tk in ["AMBER", "DBL", "WELSPUN", "ZEE"]:
        A = annual(d, tk)
        print(f"\n== {tk}")
        print(A[["revenue", "opm", "pat", "roe", "roce", "de", "int_cover", "cfo_ebitda", "fcf", "rev_cagr_3y"]]
              .tail(9).round(2).to_string())
        print("promoter latest:", promoter(d, tk).tail(3).round(3).to_dict())
