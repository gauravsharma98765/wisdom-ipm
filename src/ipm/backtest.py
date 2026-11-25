"""Walk-forward backtest of the engine on the 4-stock universe.

Rules of the simulation (all stated assumptions):
  * Decisions quarterly (Mar/Jun/Sep/Dec month-end), using only data public on that date.
  * Orders execute at the NEXT trading day's close (no same-day look-ahead).
  * 25 bps per side cost; idle cash earns 6% p.a.; no taxes; no dividends (conservative, both sides).
  * Start with Rs 100 of cash. Weights are of total portfolio value; cash is allowed.
"""
from __future__ import annotations

import contextlib
import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd

import fundamentals as F

from . import config
from .config import T
from .engine import decide, evaluate

TICKERS = ["AMBER", "DBL", "WELSPUN", "ZEE"]


def decision_dates(start, end):
    d = pd.date_range(start, end, freq="ME")
    return [x for x in d if x.month in T.decision_months]


@contextlib.contextmanager
def with_thresholds(**kw):
    """Temporarily override config thresholds (for sensitivity analysis). Modules bind T at import,
    so we patch each one and restore on exit."""
    from . import engine, scoring
    old = (config.T, engine.T, scoring.T, globals()["T"])
    new = dataclasses.replace(config.T, **kw)
    config.T = engine.T = scoring.T = globals()["T"] = new
    try:
        yield new
    finally:
        config.T, engine.T, scoring.T, globals()["T"] = old


def run(data: Path, start="2018-06-30", end=None, overlay=None, valuation="v1"):
    px = {t: pd.read_csv(data / f"px_{t}.csv", index_col=0, parse_dates=True) for t in TICKERS + ["NIFTY50"]}
    A = {t: F.annual(data / "fundamentals", t) for t in TICKERS}
    P = {t: F.promoter(data / "fundamentals", t) for t in TICKERS}
    end = pd.Timestamp(end) if end else min(p.index.max() for p in px.values())
    cal = px["NIFTY50"].loc[start:end].index
    close = pd.DataFrame({t: px[t]["Close"] for t in TICKERS}).reindex(cal).ffill()
    cash, shares = 100.0, {t: 0.0 for t in TICKERS}
    last_buy_q, qn = {}, 0
    nav, decisions, trades = [], [], []
    ddates = decision_dates(start, end)
    pending = None
    for i, day in enumerate(cal):
        cash *= (1 + T.cash_yield) ** (1 / 365)               # accrue (calendar-day approx.)
        # execute yesterday's decision at today's close
        if pending is not None:
            val = cash + sum(shares[t] * close.at[day, t] for t in TICKERS if close.at[day, t] == close.at[day, t])
            for dec in pending:                                  # sells first, then buys
                tk = dec.ticker
                if dec.action in ("EXIT", "TRIM"):
                    cur_w = shares[tk] * close.at[day, tk] / val
                    if cur_w > dec.target_weight + 1e-6:
                        sell = (cur_w - dec.target_weight) * val
                        shares[tk] -= sell / close.at[day, tk]; cash += sell * (1 - T.cost_per_trade)
                        trades.append((day, tk, "SELL", sell, dec.reason))
            val = cash + sum(shares[t] * close.at[day, t] for t in TICKERS if close.at[day, t] == close.at[day, t])
            for dec in pending:
                tk = dec.ticker
                if dec.action in ("BUY", "ADD"):
                    cur_w = shares[tk] * close.at[day, tk] / val
                    if dec.target_weight > cur_w + 1e-6:
                        buy = min((dec.target_weight - cur_w) * val, cash / (1 + T.cost_per_trade))
                        if buy > 0:
                            shares[tk] += buy / close.at[day, tk]; cash -= buy * (1 + T.cost_per_trade)
                            last_buy_q[tk] = qn; trades.append((day, tk, "BUY", buy, dec.reason))
            pending = None
        nav.append(cash + sum(shares[t] * close.at[day, t] for t in TICKERS if close.at[day, t] == close.at[day, t]))
        # decision at today's close if it's a decision date (last trading day of the month)
        if any((day.year, day.month) == (dd.year, dd.month) for dd in ddates) and \
           (i == len(cal) - 1 or cal[i + 1].month != day.month):
            qn += 1
            val = nav[-1]
            held_w = {t: shares[t] * close.at[day, t] / val if close.at[day, t] == close.at[day, t] else 0 for t in TICKERS}
            ev = {}
            for t in TICKERS:
                c = px[t]["Close"].loc[:day]
                tr = c.iloc[-1] / c.loc[:day - pd.Timedelta(days=182)].iloc[-1] - 1 if len(c.loc[:day - pd.Timedelta(days=182)]) else 0.0
                ev[t] = evaluate(t, A[t], P[t], px[t], day, tr, valuation)
            ages = {t: qn - last_buy_q.get(t, -99) for t in TICKERS}
            decs = decide(day, ev, held_w, ages, overlay)
            decisions += decs
            if i < len(cal) - 1:
                pending = decs
    nav = pd.Series(nav, index=cal, name="IPM")
    return nav, pd.DataFrame(trades, columns=["date", "ticker", "side", "amount", "reason"]), decisions, px


def stats(s: pd.Series, rf=0.06):
    r = s.pct_change().dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    dd = (s / s.cummax() - 1).min()
    return dict(CAGR=cagr, vol=r.std() * np.sqrt(252), maxDD=dd, sharpe=(r.mean() * 252 - rf) / (r.std() * np.sqrt(252)),
                final=s.iloc[-1])
