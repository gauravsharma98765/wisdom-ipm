"""EDA on WISDOM trade history: performance, timing, sizing, holding, biases.

Usage: python eda.py <data_dir>   (expects lots/ledger parquet + px_*.csv from ingest/prices)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

TICKERS = ["AMBER", "DBL", "WELSPUN", "ZEE"]
# Off-market executions explained by corporate events / private deals (verified vs price tape)
KNOWN_EVENTS = {
    ("AMBER", "2017-12-12", "BUY"): "pre-IPO placement @800 (IPO priced 859, listed Jan-2018)",
    ("AMBER", "2017-12-13", "BUY"): "pre-IPO placement @800",
    ("AMBER", "2017-12-20", "BUY"): "pre-IPO placement @833",
    ("AMBER", "2018-01-15", "SELL"): "pre-listing secondary sale @805",
    ("AMBER", "2018-01-16", "SELL"): "pre-listing secondary sale @805",
    ("AMBER", "2018-01-18", "SELL"): "pre-listing secondary sale @805",
    ("AMBER", "2018-01-25", "BUY"): "pre-listing purchase @1306 (likely IPO/anchor allotment)",
    ("DBL", "2016-07-29", "BUY"): "pre-listing purchase @209 (IPO priced 219, listed Aug-2016)",
    ("DBL", "2017-03-31", "BUY"): "FY-end book entry @253 (same rate as 2018-03-31: transfer/inherited cost)",
    ("DBL", "2018-03-31", "BUY"): "FY-end book entry @253 (transfer at historical cost)",
    ("DBL", "2021-04-26", "BUY"): "QIP allotment @540 (~9% discount to market)",
    ("WELSPUN", "2023-05-26", "SELL"): "buyback tender @~120 (29% premium to market)",
    ("WELSPUN", "2024-08-22", "SELL"): "buyback tender @~215 (10% premium to market)",
    ("ZEE", "2020-01-30", "BUY"): "transfer at historical cost @149 (mkt 268)",
    ("ZEE", "2025-03-18", "BUY"): "same-day buy/sell of equal qty: inter-account transfer",
    ("ZEE", "2025-03-18", "SELL"): "same-day buy/sell of equal qty: inter-account transfer",
}
BENCH = ["NIFTY50", "SMALLCAP100", "MIDCAP100"]  # files px_<name>.csv (250/150 substitutes)


# ---------- helpers ----------
def load(d: Path):
    lots = pd.read_parquet(d / "lots.parquet")
    led = pd.read_parquet(d / "ledger.parquet")
    px = {t: pd.read_csv(d / f"px_{t}.csv", index_col=0, parse_dates=True) for t in TICKERS + BENCH}
    return lots, led, px


def xirr(dates, flows, guess=0.15):
    d = np.array([(x - dates[0]).days / 365.25 for x in dates])
    f = np.asarray(flows, float)
    lo, hi = -0.99, 10.0
    npv = lambda r: (f / (1 + r) ** d).sum()
    if npv(lo) * npv(hi) > 0:
        return np.nan
    for _ in range(200):
        m = (lo + hi) / 2
        if npv(lo) * npv(m) <= 0:
            hi = m
        else:
            lo = m
    return m


def px_on(p: pd.DataFrame, date, col="Close"):
    s = p.loc[:date, col]
    return s.iloc[-1] if len(s) else np.nan


def fwd_ret(p, date, days):
    s = p["Close"]
    a = s.loc[:date]
    b = s.loc[date + pd.Timedelta(days=days):]
    if not len(a) or not len(b):
        return np.nan
    return b.iloc[0] / a.iloc[-1] - 1


# ---------- 1. execution classification ----------
def classify(led, px, tol=0.01):
    out = []
    for _, r in led.iterrows():
        p = px[r.ticker]
        if r.date < p.index.min():
            tag = "PRE_LISTING"
        elif r.date not in p.index:
            tag = "NON_TRADING_DAY"
        else:
            lo, hi = p.at[r.date, "Low"], p.at[r.date, "High"]
            tag = "MARKET" if lo * (1 - tol) <= r.vwap <= hi * (1 + tol) else "OFF_MARKET"
        out.append(tag)
    led = led.copy()
    led["exec_type"] = out
    for (t, d, side), why in KNOWN_EVENTS.items():
        m = (led.ticker == t) & (led.date == pd.Timestamp(d)) & (led.side == side)
        led.loc[m, "event"] = why
    led["discretionary_mkt"] = led.exec_type.eq("MARKET")
    return led


# ---------- 2. performance ----------
def performance(lots, led, px, asof):
    rows = []
    for t in TICKERS + ["PORTFOLIO"]:
        L = led if t == "PORTFOLIO" else led[led.ticker == t]
        lo = lots if t == "PORTFOLIO" else lots[lots.ticker == t]
        closed, open_ = lo[~lo.is_open], lo[lo.is_open]
        mv = sum(px_on(px[k], asof) * q for k, q in open_.groupby("ticker").buy_qty.sum().items())
        flows = list(L.cash_flow) + [mv]
        dates = list(L.date) + [asof]
        order = np.argsort(dates)
        realised = (closed.sell_amt - closed.buy_amt).sum()
        unreal = mv - open_.buy_amt.sum()
        # Kaplan-Schoar PME + direct alpha vs Nifty 50 (index-compounded flows)
        nT = px_on(px["NIFTY50"], asof)
        fv = [cf * nT / px_on(px["NIFTY50"], d) for d, cf in zip(L.date, L.cash_flow)]
        contrib = -sum(v for v in fv if v < 0)
        dist = sum(v for v in fv if v > 0) + mv
        ks_pme = dist / contrib
        da = xirr(sorted(list(L.date) + [asof]), [v for _, v in sorted(zip(L.date, fv))] + [mv])
        rows.append(dict(
            ticker=t, first_trade=L.date.min().date(), deployed_cr=L[L.side == "BUY"].amt.sum() / 1e7,
            realised_cr=realised / 1e7, unrealised_cr=unreal / 1e7, total_pnl_cr=(realised + unreal) / 1e7,
            open_cost_cr=open_.buy_amt.sum() / 1e7, open_mv_cr=mv / 1e7,
            xirr=xirr([dates[i] for i in order], [flows[i] for i in order]),
            ks_pme=ks_pme, direct_alpha=da,
            win_rate_lots=(closed.sell_amt > closed.buy_amt).mean(),
            win_rate_cap=closed.loc[closed.sell_amt > closed.buy_amt, "buy_amt"].sum() / closed.buy_amt.sum(),
        ))
    return pd.DataFrame(rows)


def by_year(lots):
    c = lots[~lots.is_open].copy()
    c["fy"] = c.sell_date.dt.year
    return c.assign(pnl=c.sell_amt - c.buy_amt).pivot_table(index="fy", columns="ticker", values="pnl", aggfunc="sum").div(1e7).round(2)


# ---------- 3. timing ----------
def timing(led, px):
    rows = []
    for _, r in led[led.exec_type == "MARKET"].iterrows():
        p = px[r.ticker]
        w = p.loc[r.date - pd.Timedelta(days=365):r.date, "Close"]
        rng = (r.vwap - w.min()) / (w.max() - w.min()) if w.max() > w.min() else np.nan
        bench = px["NIFTY50"]
        rows.append(dict(
            ticker=r.ticker, date=r.date, side=r.side, amt=r.amt,
            pct_52w=rng,                                             # 0 = at 52w low, 1 = at 52w high
            trail_6m=p.loc[:r.date, "Close"].iloc[-1] / px_on(p, r.date - pd.Timedelta(days=182)) - 1,
            fwd_3m=fwd_ret(p, r.date, 91), fwd_1y=fwd_ret(p, r.date, 365), fwd_3y=fwd_ret(p, r.date, 365 * 3),
            fwd_1y_rel=fwd_ret(p, r.date, 365) - fwd_ret(bench, r.date, 365),
        ))
    return pd.DataFrame(rows)


def baseline_fwd(px, t, start, end, days=365):
    """Unconditional forward return over every day in the window -> skill baseline."""
    s = px[t]["Close"].loc[start:end]
    vals = [fwd_ret(px[t], d, days) for d in s.index[::5]]
    return np.nanmean(vals)


# ---------- 4. holding / disposition ----------
def holding(lots, asof):
    l = lots.copy()
    end = l.sell_date.fillna(asof)
    l["hold_days"] = (end - l.buy_date).dt.days
    l["ret"] = np.where(l.is_open, np.nan, l.sell_amt / l.buy_amt - 1)
    l["cagr"] = np.where(l.is_open | (l.hold_days < 30), np.nan,
                         (1 + l.ret) ** (365.25 / l.hold_days.clip(lower=1)) - 1)
    return l


def disposition(lots, led, px):
    """Odean PGR/PLR: on each sell day, count realised vs paper gains/losses (capital-weighted)."""
    rg = rl = pg = pl = 0.0
    for (t, d), _ in led[led.side == "SELL"].groupby(["ticker", "date"]):
        L = lots[lots.ticker == t]
        price = px_on(px[t], d)
        sold = L[L.sell_date == d]
        held = L[(L.buy_date <= d) & ((L.sell_date > d) | L.is_open)]
        rg += sold.loc[sold.sell_rate > sold.buy_rate, "buy_amt"].sum()
        rl += sold.loc[sold.sell_rate <= sold.buy_rate, "buy_amt"].sum()
        pg += held.loc[price > held.buy_rate, "buy_amt"].sum()
        pl += held.loc[price <= held.buy_rate, "buy_amt"].sum()
    pgr, plr = rg / (rg + pg), rl / (rl + pl)
    return dict(PGR=pgr, PLR=plr, disposition_ratio=pgr / plr if plr else np.nan)


# ---------- 5. sizing ----------
def sizing(led, px):
    b = led[led.side == "BUY"].copy()
    rows = []
    for t, g in led.groupby("ticker"):
        pos = cost = 0.0
        for _, r in g.iterrows():
            avg = cost / pos if pos > 1e-6 else np.nan
            if r.side == "BUY":
                kind = ("INITIAL" if pos < 1e-6 else "AVG_DOWN" if r.vwap < avg * 0.98
                        else "PYRAMID_UP" if r.vwap > avg * 1.02 else "AT_COST")
                rows.append(dict(ticker=t, date=r.date, amt=r.amt, kind=kind,
                                 vs_avg=r.vwap / avg - 1 if avg == avg else np.nan))
                pos += r.qty
                cost += r.amt
            else:
                cost -= avg * r.qty
                pos -= r.qty
    return pd.DataFrame(rows)


def exposure(led, px, freq="ME"):
    idx = pd.date_range(led.date.min(), led.date.max() + pd.Timedelta(days=60), freq=freq)
    out = {}
    for t, g in led.groupby("ticker"):
        q = g.set_index("date").signed_qty.groupby(level=0).sum().cumsum()
        q = q.reindex(idx.union(q.index)).ffill().fillna(0).reindex(idx)
        c = px[t]["Close"].reindex(idx.union(px[t].index)).ffill().reindex(idx)
        out[t] = (q * c.fillna(g.vwap.iloc[0])) / 1e7
    return pd.DataFrame(out)


if __name__ == "__main__":
    d = Path(sys.argv[1])
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
    lots, led, px = load(d)
    asof = min(p.index.max() for p in px.values())
    led = classify(led, px)
    led.to_parquet(d / "ledger_tagged.parquet")
    print("AS OF", asof.date())
    print("\n== execution types (count / ₹cr)")
    print(led.pivot_table(index="exec_type", columns="side", values="amt", aggfunc=["count", "sum"]).fillna(0)
          .assign(**{}).round(1).to_string())
    print(led[led.exec_type != "MARKET"][["ticker", "date", "side", "qty", "vwap", "amt", "exec_type"]]
          .assign(amt=lambda x: (x.amt / 1e5).round(1)).to_string())

    print("\n== PERFORMANCE (₹ cr)")
    print(performance(lots, led, px, asof).to_string())
    print("\n== realised P&L by calendar year of sale (₹ cr)")
    print(by_year(lots).to_string())

    h = holding(lots, asof)
    h.to_parquet(d / "lots_enriched.parquet")
    print("\n== HOLDING PERIOD (days) — capital-weighted quantiles")
    for t, g in h.groupby("ticker"):
        g = g.sort_values("hold_days")
        cw = g.buy_amt.cumsum() / g.buy_amt.sum()
        q = {k: int(g.hold_days[cw >= k].iloc[0]) for k in (0.25, 0.5, 0.75)}
        cl = g[~g.is_open]
        print(t, q, "| closed lots median days", int(cl.hold_days.median()) if len(cl) else None,
              "| % closed capital held <1y", round((cl.buy_amt[cl.hold_days < 365].sum() / cl.buy_amt.sum()) * 100, 1),
              "| % closed capital held >3y", round((cl.buy_amt[cl.hold_days > 1095].sum() / cl.buy_amt.sum()) * 100, 1))
    print("\n== winners vs losers: median hold days (closed lots)")
    c = h[~h.is_open]
    print(c.assign(win=c.ret > 0).groupby(["ticker", "win"]).hold_days.median().unstack().to_string())

    print("\n== DISPOSITION (capital-weighted PGR/PLR; >1 = sells winners, holds losers)")
    print(disposition(lots, led, px))

    tm = timing(led, px)
    tm.to_parquet(d / "timing.parquet")
    print("\n== TIMING (market executions only), capital-weighted means")
    wm = lambda g, c: np.average(g[c].dropna(), weights=g.loc[g[c].notna(), "amt"]) if g[c].notna().any() else np.nan
    rows = []
    for (t, s), g in tm.groupby(["ticker", "side"]):
        rows.append(dict(ticker=t, side=s, n=len(g), amt_cr=g.amt.sum() / 1e7,
                         pct_52w=wm(g, "pct_52w"), trail_6m=wm(g, "trail_6m"),
                         fwd_3m=wm(g, "fwd_3m"), fwd_1y=wm(g, "fwd_1y"), fwd_3y=wm(g, "fwd_3y"), fwd_1y_rel=wm(g, "fwd_1y_rel"),
                         base_fwd_1y=baseline_fwd(px, t, g.date.min(), g.date.max())))
    print(pd.DataFrame(rows).to_string())

    sz = sizing(led, px)
    sz.to_parquet(d / "sizing.parquet")
    print("\n== SIZING: buy types (count, ₹cr, median vs avg cost)")
    print(sz.groupby(["ticker", "kind"]).agg(n=("amt", "size"), amt_cr=("amt", lambda x: x.sum() / 1e7),
                                              med_vs_avg=("vs_avg", "median")).to_string())
    m = tm[tm.side == "BUY"].dropna(subset=["fwd_1y"])
    print("\n== conviction: Spearman(buy size, fwd 1y ret) by ticker")
    print(m.groupby("ticker").apply(lambda g: g.amt.corr(g.fwd_1y, method="spearman"), include_groups=False).round(2).to_dict())

    ex = exposure(led, px)
    ex.to_csv(d / "exposure.csv")
    print("\n== EXPOSURE (₹ cr MTM, year-end)")
    ye = ex.resample("YE").last()
    print(ye.assign(TOTAL=ye.sum(axis=1)).round(1).to_string())
    w = ex.div(ex.sum(axis=1), axis=0)
    print("\nmean HHI", round((w ** 2).sum(axis=1).mean(), 3), "| max single-name weight", w.max().round(2).to_dict())
