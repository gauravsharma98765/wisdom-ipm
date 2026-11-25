import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []
md = lambda s: C.append(nbf.v4.new_markdown_cell(s.strip("\n")))
code = lambda s: C.append(nbf.v4.new_code_cell(s.strip("\n")))

md("""
# WISDOM Investing — Step 1: Investor Behaviour EDA & Scorecard

**Question:** what does 10 years of trades in Amber, DBL, Welspun Living and Zee tell us about *how* WISDOM actually invests — strengths, biases, and how closely practice matches the written principles?

**How to re-run (≈1 min):**
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` in the repo root and fill in the Excel path and password. Derived data goes to `<repo>/data` (git-ignored).
3. In VS Code/Jupyter pick the **WISDOM IPM (.venv)** kernel and Run All. Prices are downloaded from Yahoo Finance the first time.

**Sections:** 0 Setup · 1 Load & reconcile · 2 Classify executions · 3 Performance · 4 Trades on price · 5 Exposure · 6 Holding period · 7 Timing · 8 Sizing · 9 Scorecard · 10 Findings

> All data is proprietary. Nothing in `WISDOM_DATA` is committed (see `.gitignore`). Delete it after the assessment.
""")

md("## 0. Setup")
code("""
# Kernel check: these notebooks need the project environment (.venv). If this fails,
# click the kernel name (top-right) -> Select Kernel -> Jupyter Kernel -> "WISDOM IPM (.venv)".
import sys, importlib.util
_missing = [m for m in ["msoffcrypto", "openpyxl", "pyarrow", "yfinance", "scipy", "bs4"] if importlib.util.find_spec(m) is None]
if _missing:
    raise RuntimeError(f"Wrong kernel: {sys.executable} is missing {_missing}. "
                       "Select the 'WISDOM IPM (.venv)' kernel (or run: pip install -r requirements.txt in it).")
print("Kernel OK:", sys.executable)
""")
code("""
import os, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib.pyplot as plt, matplotlib.dates as mdates

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path("..", "src").resolve()))   # make src/ importable
import ingest, prices, eda

import settings                                    # reads <repo>/.env -> paths + password
DATA, FIG = settings.DATA, settings.DATA / "figures"

# --- Chart style: validated categorical palette (one colour per stock, fixed order) ---
COL = {"AMBER": "#2a78d6", "DBL": "#eb6834", "WELSPUN": "#1baf7a", "ZEE": "#eda100"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
GOOD, BAD = "#2a78d6", "#e34948"       # blue = good / red = bad (diverging pair)
plt.rcParams.update({
    "figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titleweight": "bold", "axes.titlesize": 11, "axes.titlecolor": INK, "legend.frameon": False,
})
cr = lambda x: x / 1e7   # rupees -> crore
""")

md("""
## 1. Load & reconcile

The workbook has one tab per stock. Each row is a **FIFO-matched lot** (buy → sell). Subtotal rows split the sheet into blocks. We parse the blocks, then **prove the parse is right** by checking that our lot sums equal the sheet's own subtotals.
""")
code("""
# Decrypt + parse (skipped if already done)
xlsx = DATA / "trades.xlsx"
if not xlsx.exists():
    assert settings.XLSX_PASSWORD, "Set WISDOM_XLSX_PASSWORD in <repo>/.env (see .env.example)"
    ingest.decrypt(settings.XLSX, xlsx, settings.XLSX_PASSWORD)
lots, recon = ingest.build(xlsx)
led = ingest.to_ledger(lots)     # one row per execution (date x side), FIFO splits merged back
lots.to_parquet(DATA / "lots.parquet"); led.to_parquet(DATA / "ledger.parquet")   # used by notebooks 02/03

# Market prices (stocks + Nifty 50 + smallcap/midcap substitutes)
if not (DATA / "px_AMBER.csv").exists():
    prices.main(DATA)
px = {t: pd.read_csv(DATA / f"px_{t}.csv", index_col=0, parse_dates=True) for t in eda.TICKERS + eda.BENCH}
# Analysis date is PINNED so the Step-1 numbers don't move when prices are refreshed.
# Override with WISDOM_ASOF=YYYY-MM-DD. Prices after ASOF are cut off (no look-ahead in forward returns).
ASOF = settings.ASOF_STEP1
px = {t: p.loc[:ASOF] for t, p in px.items()}
print(f"{len(lots):,} lots -> {len(led):,} executions | prices as of {ASOF.date()}")
""")
code("""
# Reconciliation: our lot sums vs the sheet's subtotal rows. Every difference should be ~0.
chk = pd.DataFrame({
    "blocks": recon.groupby("ticker").size(),
    "max |Δ buy qty|": (recon.buy_qty_lots - recon.buy_qty_sub).abs().groupby(recon.ticker).max(),
    "max |Δ buy ₹|":   (recon.buy_amt_lots - recon.buy_amt_sub).abs().groupby(recon.ticker).max(),
    "max |Δ sell ₹|":  (recon.sell_amt_lots - recon.sell_amt_sub).abs().groupby(recon.ticker).max(),
})
display(chk.round(2))
assert (chk.iloc[:, 1:].fillna(0) < 1).all().all(), "Reconciliation failed - parse is wrong"

# Row-level sanity checks
print("lots where qty != amt/rate  :", ((lots.buy_amt - lots.buy_qty*lots.buy_rate).abs()/lots.buy_amt > .005).sum())
print("lots with sell date < buy date:", (lots.sell_date < lots.buy_date).sum(), "(FIFO pairing artefact in the source sheet, e.g. DBL Jul-2018; kept)")
""")

md("""
## 2. Classify executions — which trades were real market decisions?

Not every trade is a timing decision. We compare each execution's price with that day's **Low–High range**:

| Tag | Meaning | Used for timing scores? |
|---|---|---|
| `MARKET` | price inside the day's range | ✅ yes |
| `PRE_LISTING` | traded before the stock listed (pre-IPO/anchor) | ❌ |
| `OFF_MARKET` | price outside the range (placement, buyback, transfer at book cost) | ❌ |
| `NON_TRADING_DAY` | weekend/holiday date (e.g. 31-Mar book entries) | ❌ |

We *infer* the reason for each off-market trade from the price tape (see `KNOWN_EVENTS` in `src/eda.py`). Those labels are hypotheses to verify against exchange filings.
""")
code("""
led = eda.classify(led, px)
summ = led.pivot_table(index="exec_type", columns="side", values="amt", aggfunc=["count", "sum"]).fillna(0)
summ[("sum", "BUY")] = cr(summ[("sum", "BUY")]); summ[("sum", "SELL")] = cr(summ[("sum", "SELL")])
summ.columns = ["# buys", "# sells", "buys ₹cr", "sells ₹cr"]
display(summ.round(1))
share = led[led.side == "BUY"].groupby("exec_type").amt.sum() / led[led.side == "BUY"].amt.sum()
print(f"Share of buy capital that is NOT an open-market decision: {1 - share.get('MARKET', 0):.0%}")
display(led[led.exec_type != "MARKET"][["ticker", "date", "side", "vwap", "amt", "exec_type", "event"]]
        .assign(amt_lakh=lambda d: (d.amt / 1e5).round(1)).drop(columns="amt").reset_index(drop=True))
""")

md("""
## 3. Performance

* **Realised** = sold lots (sell − buy). **Unrealised** = open lots marked to the last close.
* **XIRR** = money-weighted annual return using the actual dated cash flows.
* **KS-PME** (Kaplan-Schoar) = value created by our cash flows ÷ value if the *same* cash had gone into Nifty 50 on the same dates. **>1 means we beat the index.**
* **Direct alpha** = XIRR of the flows after re-expressing them in Nifty units (annualised excess return).
* Dividends are not in the file, so returns are slightly understated.
""")
code("""
perf = eda.performance(lots, led, px, ASOF)
show = perf.set_index("ticker")[["deployed_cr", "realised_cr", "unrealised_cr", "total_pnl_cr", "xirr", "ks_pme", "direct_alpha", "win_rate_lots"]]
display(show.style.format({"deployed_cr": "{:.1f}", "realised_cr": "{:.1f}", "unrealised_cr": "{:.1f}", "total_pnl_cr": "{:.1f}",
                           "xirr": "{:.1%}", "ks_pme": "{:.2f}", "direct_alpha": "{:+.1%}", "win_rate_lots": "{:.0%}"}))
""")
code("""
# Chart 1: where did the money come from? Stacked realised + unrealised P&L per stock.
p = perf[perf.ticker != "PORTFOLIO"].set_index("ticker")
fig, ax = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [1.1, 1]})
order = p.total_pnl_cr.sort_values(ascending=False).index
x = np.arange(len(order))
ax[0].bar(x, p.loc[order, "realised_cr"], color=[COL[t] for t in order], width=.55, label="Realised")
ax[0].bar(x, p.loc[order, "unrealised_cr"], bottom=p.loc[order, "realised_cr"].clip(lower=0), width=.55,
          color=[COL[t] for t in order], alpha=.45, hatch="///", edgecolor="white", label="Unrealised (paper)")
for i, t in enumerate(order):
    ax[0].text(i, max(p.loc[t, "total_pnl_cr"], 0) + 2, f"{p.loc[t,'total_pnl_cr']:+.1f}", ha="center", color=INK, fontsize=9)
ax[0].set_xticks(x, order); ax[0].set_ylabel("₹ crore"); ax[0].axhline(0, color=MUTED, lw=.8)
ax[0].set_title(f"P&L by stock — Amber is {p.loc['AMBER','total_pnl_cr']/p.total_pnl_cr.sum():.0%} of the total")
ax[0].legend(loc="upper right")

# Chart 2: excess annual return vs Nifty (direct alpha) — blue = beat index, red = lagged
a = p.direct_alpha.loc[order] * 100
ax[1].barh(order[::-1], a[::-1], color=[GOOD if v > 0 else BAD for v in a[::-1]], height=.5)
for i, v in enumerate(a[::-1]): ax[1].text(v + (1 if v > 0 else -1), i, f"{v:+.1f}%", va="center", ha="left" if v > 0 else "right", color=INK, fontsize=9)
ax[1].axvline(0, color=MUTED, lw=.8); ax[1].set_xlabel("Excess return vs Nifty 50 (% p.a.)")
ax[1].set_title("Skill vs index (direct alpha)"); ax[1].set_xlim(-38, 30); ax[1].grid(axis="y", visible=False)
plt.tight_layout(); plt.savefig(FIG / "01_performance.png", bbox_inches="tight"); plt.show()
""")
code("""
# Concentration of outcomes: what would the book look like without the single best stock?
ex = perf[~perf.ticker.isin(["PORTFOLIO", "AMBER"])]
print(f"Total P&L: ₹{perf.set_index('ticker').loc['PORTFOLIO','total_pnl_cr']:.1f} cr | excluding Amber: ₹{ex.total_pnl_cr.sum():.1f} cr "
      f"on ₹{ex.deployed_cr.sum():.1f} cr deployed")
# Realised P&L by calendar year (when did gains get booked?)
display(eda.by_year(lots).fillna(0).assign(TOTAL=lambda d: d.sum(axis=1)).round(2))
""")

md("""
## 4. Trades on price

Every open-market buy (▲) and sell (▼) on the stock's price history, sized by capital. Grey markers are off-market events (pre-IPO, placements, buybacks, transfers).
""")
code("""
fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=False)
for ax, t in zip(axes.ravel(), ["AMBER", "DBL", "WELSPUN", "ZEE"]):
    p_ = px[t]["Close"]; ax.plot(p_.index, p_.values, color=COL[t], lw=1.3)
    for side, mk in (("BUY", "^"), ("SELL", "v")):
        g = led[(led.ticker == t) & (led.side == side)]
        m = g[g.exec_type == "MARKET"]; o = g[g.exec_type != "MARKET"]
        ax.scatter(m.date, m.vwap, s=np.sqrt(m.amt) / 12 + 8, marker=mk, facecolor=("white" if side == "SELL" else INK),
                   edgecolor=INK, lw=.9, zorder=3, label=f"{side.title()} (market)")
        ax.scatter(o.date, o.vwap, s=22, marker=mk, color="#a8a7a1", zorder=2, label=f"{side.title()} (off-market)")
    ax.set_title(t.title() if t != "DBL" else "DBL"); ax.set_yscale("log"); ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.xaxis.set_major_locator(mdates.YearLocator(2)); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
h, l = axes[0, 0].get_legend_handles_labels(); fig.legend(h[:4], l[:4], ncol=4, loc="lower center", bbox_to_anchor=(.5, -.02))
fig.suptitle("Open-market trades vs price (log scale; marker area ∝ ₹ traded)", fontweight="bold", y=1.0)
plt.tight_layout(); plt.savefig(FIG / "02_trades_on_price.png", bbox_inches="tight"); plt.show()
""")

md("""
## 5. Exposure & concentration

Month-end market value held in each stock. **HHI** = sum of squared weights (1 = one stock, 0.25 = perfectly spread over four). **Effective N = 1/HHI** is “how many equal-sized stocks this book behaves like”.
""")
code("""
expo = eda.exposure(led, px)
fig, ax = plt.subplots(figsize=(10, 3.8))
ax.stackplot(expo.index, [expo[t] for t in ["AMBER", "DBL", "WELSPUN", "ZEE"]],
             colors=[COL[t] for t in ["AMBER", "DBL", "WELSPUN", "ZEE"]], labels=["Amber", "DBL", "Welspun", "Zee"],
             edgecolor="white", linewidth=.6)
ax.set_ylabel("Market value, ₹ crore"); ax.set_title("Portfolio market value by stock"); ax.legend(loc="upper left", ncol=4)
plt.tight_layout(); plt.savefig(FIG / "03_exposure.png", bbox_inches="tight"); plt.show()

w = expo.div(expo.sum(axis=1), axis=0).dropna(); hhi = (w ** 2).sum(axis=1)
print(f"Average HHI {hhi.mean():.2f} -> effective N ≈ {1/hhi.mean():.1f} stocks | peak single-name weight: {w.max().round(2).to_dict()}")
""")

md("""
## 6. Holding period vs the 1–20 year mandate

Each lot is held from its buy date to its sell date (or to `ASOF` if still open). Bars are **capital-weighted** — a ₹10 cr lot counts more than a ₹10 k lot.
""")
code("""
h = eda.holding(lots, ASOF)
bins = [0, 90, 365, 730, 1095, 1825, 4000]; labels = ["<3m", "3m–1y", "1–2y", "2–3y", "3–5y", "5y+"]
h["bucket"] = pd.cut(h.hold_days, bins, labels=labels)
tab = h.groupby(["ticker", "bucket"], observed=False).buy_amt.sum().unstack(0)
tab = tab.div(tab.sum()) * 100
fig, ax = plt.subplots(figsize=(10, 3.6)); wdt = .2
for i, t in enumerate(["AMBER", "DBL", "WELSPUN", "ZEE"]):
    ax.bar(np.arange(len(labels)) + (i - 1.5) * wdt, tab[t], wdt * .9, color=COL[t], label=t.title() if t != "DBL" else t)
ax.set_xticks(range(len(labels)), labels); ax.set_ylabel("% of capital"); ax.legend(ncol=4)
ax.set_title("How long is capital held? (closed + still-open lots)"); plt.tight_layout()
plt.savefig(FIG / "04_holding.png", bbox_inches="tight"); plt.show()

c = h[~h.is_open]
short = c.buy_amt[c.hold_days < 365].sum() / c.buy_amt.sum()
print(f"Closed capital held < 1 year: {short:.0%} | > 3 years: {c.buy_amt[c.hold_days > 1095].sum() / c.buy_amt.sum():.0%}")
print("Median holding days, winners vs losers:"); display(c.assign(win=c.ret > 0).groupby(["ticker", "win"]).hold_days.median().unstack().rename(columns={False: "losers", True: "winners"}))
""")
code("""
# Disposition effect (Odean): on each sell day, were gains realised more readily than losses?
# PGR = realised gains / (realised + paper gains); PLR the same for losses.  Ratio > 1 = sells winners, sits on losers.
d = eda.disposition(lots, led, px)
print({k: round(float(v), 3) for k, v in d.items()})
print("-> ratio < 1 means the investor cut losers faster than winners (the opposite of the classic bias)")
""")

md("""
## 7. Timing skill

For each open-market trade we look at the stock's return over the next 3m / 1y / 3y and compare it with the **unconditional average** 1-year return over the same period (the baseline of a random entry date).

* A **buy** is good if the next-year return **beats** the baseline.
* A **sell** is good if the next-year return is **below** the baseline (you avoided what followed).
* `pct_52w`: where in the prior-52-week range the price was (0 = at the low, 1 = at the high).
""")
code("""
tm = eda.timing(led, px)
wm = lambda g, c: np.average(g[c].dropna(), weights=g.loc[g[c].notna(), "amt"])
rows = []
for (t, s), g in tm.groupby(["ticker", "side"]):
    rows.append(dict(ticker=t, side=s, n=len(g), amt_cr=cr(g.amt.sum()), pct_52w=wm(g, "pct_52w"), trail_6m=wm(g, "trail_6m"),
                     fwd_1y=wm(g, "fwd_1y"), baseline_1y=eda.baseline_fwd(px, t, g.date.min(), g.date.max())))
T = pd.DataFrame(rows); T["edge_1y"] = np.where(T.side == "BUY", T.fwd_1y - T.baseline_1y, T.baseline_1y - T.fwd_1y)
display(T.style.format({"amt_cr": "{:.1f}", "pct_52w": "{:.2f}", "trail_6m": "{:+.0%}", "fwd_1y": "{:+.0%}", "baseline_1y": "{:+.0%}", "edge_1y": "{:+.0%}"}))

fig, ax = plt.subplots(figsize=(8, 3.6))
lab = [f"{r.ticker.title() if r.ticker!='DBL' else 'DBL'} {r.side.lower()}s" for r in T.itertuples()]
ax.barh(lab[::-1], (T.edge_1y * 100)[::-1], color=[GOOD if v > 0 else BAD for v in T.edge_1y[::-1]], height=.55)
for i, v in enumerate((T.edge_1y * 100)[::-1]): ax.text(v + (1.5 if v > 0 else -1.5), i, f"{v:+.0f}pp", va="center", ha="left" if v > 0 else "right", color=INK, fontsize=9)
ax.axvline(0, color=MUTED, lw=.8); ax.set_xlabel("Timing edge: next-12-month return vs average entry/exit (percentage points)")
ax.set_title("Timing edge by stock and side  (blue = helped, red = hurt)"); ax.grid(axis="y", visible=False); ax.set_xlim(-55, 55)
plt.tight_layout(); plt.savefig(FIG / "05_timing.png", bbox_inches="tight"); plt.show()
""")
code("""
# Where in the 52-week range, and after what trailing move, did the investor buy? (scatter, one dot per buy)
b = tm[tm.side == "BUY"]
fig, ax = plt.subplots(1, 2, figsize=(11, 3.6))
for t in ["AMBER", "DBL", "WELSPUN", "ZEE"]:
    g = b[b.ticker == t]
    ax[0].scatter(g.pct_52w, g.fwd_1y * 100, s=np.sqrt(g.amt) / 14 + 6, color=COL[t], alpha=.6, edgecolor="white", lw=.4, label=t.title() if t != "DBL" else t)
ax[0].set_xlabel("Buy price position in 52-week range (0 = low, 1 = high)"); ax[0].set_ylabel("Return over next 12 months (%)")
ax[0].set_title("Entry quality"); ax[0].legend(ncol=2, fontsize=8)
ax[1].hist(b.trail_6m.dropna() * 100, bins=30, color=COL["AMBER"], weights=b.loc[b.trail_6m.notna(), "amt"] / 1e7)
ax[1].axvline(0, color=MUTED, lw=.8); ax[1].set_xlabel("Stock's trailing 6-month move before the buy (%)"); ax[1].set_ylabel("₹ crore bought")
ax[1].set_title("Contrarian or momentum buyer?")
plt.tight_layout(); plt.savefig(FIG / "06_entries.png", bbox_inches="tight"); plt.show()
print(f"Capital-weighted: {np.average(b.trail_6m.dropna(), weights=b.loc[b.trail_6m.notna(),'amt']):+.0%} trailing 6m move at purchase; "
      f"{(b.loc[b.trail_6m<0,'amt'].sum()/b.amt.sum()):.0%} of buy capital deployed after the stock had FALLEN over 6 months")
""")

md("""
## 8. Sizing behaviour

Each buy is labelled against the running average cost: **INITIAL** (first buy), **AVG_DOWN** (≥2% below avg cost), **PYRAMID_UP** (≥2% above), **AT_COST** (within ±2%). The *conviction test*: does the investor put **more money** into entries that later work (Spearman correlation of buy size vs next-12-month return)?
""")
code("""
sz = eda.sizing(led, px)
S = sz.pivot_table(index="ticker", columns="kind", values="amt", aggfunc="sum").fillna(0).div(1e7)
S = S[[c for c in ["INITIAL", "PYRAMID_UP", "AT_COST", "AVG_DOWN"] if c in S]]
display(S.round(2).assign(TOTAL=S.sum(axis=1).round(2)))
fig, ax = plt.subplots(figsize=(8, 3.4)); left = np.zeros(len(S))
shade = {"INITIAL": "#a8a7a1", "PYRAMID_UP": "#2a78d6", "AT_COST": "#cde2fb", "AVG_DOWN": "#e34948"}
for k in S.columns:
    ax.barh(S.index, S[k], left=left, color=shade[k], label=k.replace("_", " ").title(), height=.5, edgecolor="white", linewidth=1.5); left += S[k].values
ax.set_xlabel("₹ crore bought"); ax.set_title("How is capital added? (vs running average cost)"); ax.legend(ncol=4, loc="lower right", fontsize=8)
ax.grid(axis="y", visible=False); plt.tight_layout(); plt.savefig(FIG / "07_sizing.png", bbox_inches="tight"); plt.show()

bb = tm[tm.side == "BUY"].dropna(subset=["fwd_1y"])
conv = bb.groupby("ticker").apply(lambda g: g.amt.corr(g.fwd_1y, method="spearman"))
print("Conviction test (Spearman, buy size vs next-year return):", conv.round(2).to_dict())
""")

md("""
## 9. Investor scorecard

Each dimension is a **0–10 score from a transparent linear rule** (so you can change the thresholds and re-run). Scores are capital-weighted across the four stocks, using open-market trades for timing/sizing.

| Dimension | Metric | 0 points | 10 points |
|---|---|---|---|
| Returns vs index | Portfolio direct alpha (p.a.) | ≤ −5% | ≥ +15% |
| Entry timing | Buys: next-12m return − baseline | ≤ −20pp | ≥ +20pp |
| Exit timing | Sells: baseline − next-12m return | ≤ −20pp | ≥ +20pp |
| Loss discipline | Disposition ratio (PGR/PLR) | ≥ 1.5 | ≤ 0.5 |
| Holding horizon | Closed capital held ≥ 2 years | 0% | ≥ 60% |
| Sizing conviction | Spearman(buy size, next-12m return) | ≤ −0.3 | ≥ +0.3 |
| Diversification | Effective N stocks | 1 | 4 |

*Diversification is deliberately **not** treated as “more is better”: WISDOM runs a high-conviction style, so a low score here is a risk flag, not an error.*
""")
code("""
lin = lambda x, lo, hi: float(np.clip((x - lo) / (hi - lo), 0, 1) * 10)    # linear 0..10, clipped

port = perf.set_index("ticker").loc["PORTFOLIO"]
buy_edge  = np.average(T[T.side == "BUY"].edge_1y,  weights=T[T.side == "BUY"].amt_cr)
sell_edge = np.average(T[T.side == "SELL"].edge_1y, weights=T[T.side == "SELL"].amt_cr)
held2y = c.buy_amt[c.hold_days >= 730].sum() / c.buy_amt.sum()
conv_w = np.average(conv, weights=bb.groupby("ticker").amt.sum().reindex(conv.index))
eff_n = 1 / hhi.mean()

SC = pd.DataFrame([
    ("Returns vs index",  port.direct_alpha,        f"{port.direct_alpha:+.1%} p.a. alpha",         lin(port.direct_alpha, -.05, .15)),
    ("Entry timing",      buy_edge,                 f"{buy_edge*100:+.0f}pp vs avg entry",          lin(buy_edge, -.20, .20)),
    ("Exit timing",       sell_edge,                f"{sell_edge*100:+.0f}pp vs avg exit",          lin(sell_edge, -.20, .20)),
    ("Loss discipline",   d["disposition_ratio"],   f"PGR/PLR = {d['disposition_ratio']:.2f}",     lin(-d["disposition_ratio"], -1.5, -.5)),
    ("Holding horizon",   held2y,                   f"{held2y:.0%} of closed capital held ≥2y",    lin(held2y, 0, .6)),
    ("Sizing conviction", conv_w,                   f"ρ = {conv_w:+.2f}",                          lin(conv_w, -.3, .3)),
    ("Diversification",   eff_n,                    f"effective N = {eff_n:.1f}",                  lin(eff_n, 1, 4)),
], columns=["dimension", "raw", "evidence", "score"]).set_index("dimension")
display(SC[["evidence", "score"]].style.format({"score": "{:.1f}"}).bar(subset="score", vmin=0, vmax=10, color="#9ec5f4"))

fig, ax = plt.subplots(figsize=(8, 3.8)); s = SC.score[::-1]
ax.barh(s.index, s.values, color=[GOOD if v >= 6 else ("#a8a7a1" if v >= 4 else BAD) for v in s.values], height=.55)
for i, v in enumerate(s.values): ax.text(v + .15, i, f"{v:.1f}", va="center", color=INK, fontsize=9)
ax.set_xlim(0, 10.8); ax.axvline(5, color=MUTED, lw=.8, ls=":"); ax.set_xlabel("Score (0–10)")
ax.set_title("Investor scorecard  (blue ≥6 · grey 4–6 · red <4)"); ax.grid(axis="y", visible=False)
plt.tight_layout(); plt.savefig(FIG / "08_scorecard.png", bbox_inches="tight"); plt.show()
""")
code("""
# Per-stock scorecard: same logic, one stock at a time, so we can see WHERE skill shows up.
rows = []
for t in ["AMBER", "DBL", "WELSPUN", "ZEE"]:
    r = perf.set_index("ticker").loc[t]; tb = T[(T.ticker == t) & (T.side == "BUY")].iloc[0]; ts = T[(T.ticker == t) & (T.side == "SELL")].iloc[0]
    ct = h[(h.ticker == t) & ~h.is_open]
    rows.append(dict(ticker=t, returns=lin(r.direct_alpha, -.05, .15), entry=lin(tb.edge_1y, -.2, .2), exit=lin(ts.edge_1y, -.2, .2),
                     holding=lin(ct.buy_amt[ct.hold_days >= 730].sum() / ct.buy_amt.sum(), 0, .6), conviction=lin(conv[t], -.3, .3)))
PS = pd.DataFrame(rows).set_index("ticker")
display(PS.style.format("{:.1f}").background_gradient(cmap="RdBu", vmin=0, vmax=10))
PS.to_csv(DATA / "scorecard_by_stock.csv"); SC.to_csv(DATA / "scorecard_portfolio.csv")
""")

md("""
## 10. What the data says — hypotheses to carry into Step 2

> These are written after looking at the numbers; edit them after re-running if the data changes.

1. **The edge is selection, not trading.** Amber alone produced ~84% of total P&L at ~34% XIRR (alpha +21% p.a. vs Nifty). Outside Amber, DBL and Welspun added only +2–3% p.a. over the index and Zee lagged it by −29% p.a. Stock choice dominates timing.
2. **Great entries, early exits in the best business.** Amber buys were near 52-week lows and the stock rose a further ~75% in the year after the investor *sold* — a sign of trimming winners too early versus the stated 1–20 year horizon.
3. **Good exits in the weaker businesses (DBL, Welspun, Zee), but poor entries.** The investor is a *dip buyer*: ~70% of buy capital went in after the stock had fallen over the prior 6 months. That worked in Amber (bought near 52-week lows) but in DBL, Welspun and Zee the falls continued and entries lagged the average 12-month return. Zee is the clearest falling-knife case (−25% trailing 6-month move, 86% of capital bought after a fall).
4. **No classic disposition bias**; losers are cut faster than winners — a genuine strength — **except Zee**, where losers were held longer than winners.
5. **Holding discipline is real only in Amber.** The portfolio holding score (8.7) is Amber-weighted: 65% of Amber's closed capital was held ≥2 years versus 37% (DBL), 24% (Zee) and 19% (Welspun), and 33% of all closed capital was held under a year, short of a 1–20 year mandate. Conviction is also weakly expressed in size (buy size does not predict the next-year return).
6. **Extreme concentration**: the book behaves like ~1.7 stocks. This is consistent with “high-conviction” but is also the single biggest risk.
7. **Principle fit:** the winner (Amber) is the stock that best matches *quality / founder-led / structural growth*; the loser (Zee) is the stock that the *avoid list* (governance, turnaround) would have screened out. This is the case for a principles-first rules engine.

**Next (Step 2):** turn the scorecard's weak spots (early exits, momentum chasing, no size-conviction link, over-concentration) into explicit guardrails in the Intelligent Portfolio Manager, and encode the principles as thresholds scored from fundamentals.
""")

nb["cells"] = C
nb["metadata"] = {"kernelspec": {"name": "wisdom-ipm", "display_name": "WISDOM IPM (.venv)", "language": "python"}}
nbf.write(nb, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "notebooks" / "01_trade_eda_and_scorecard.ipynb"))
print("written", len(C), "cells")
