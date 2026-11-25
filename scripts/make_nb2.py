import nbformat as nbf
nb = nbf.v4.new_notebook(); C=[]
md = lambda s: C.append(nbf.v4.new_markdown_cell(s.strip("\n")))
code = lambda s: C.append(nbf.v4.new_code_cell(s.strip("\n")))

md("""
# WISDOM Intelligent Portfolio Manager — v1 vs v2 valuation, and a robustness sweep

**What this notebook does:** runs the rules-based Portfolio Manager (`src/ipm/`) over 2018–2026 on the 4-stock universe, compares two valuation rules, and shows how fragile the result is to one key assumption (the exit P/E multiple).

**How the PM decides (every quarter, using only data public on that date):**
1. **Quality score (0–100)** from fundamentals, split by WISDOM principle: growth, returns (ROCE), durability, cash/FCF, balance sheet, promoter alignment.
2. **Avoid-list gates:** turnaround, leverage, dependence on external capital, no promoter alignment → no buying, and exit after the minimum hold.
3. **25% hurdle (Principle 1.2):** expected 3-year price CAGR must exceed 25%.
4. **Behavioural guardrails** from Step 1: 40% position cap, 12-month minimum hold, no valuation-trim of high-quality compounders, falling-knife filter, gradual position ramp.

**The two valuation rules**
| | v1 | v2 |
|---|---|---|
| Earnings base | mean of last 3 years' EPS | forward revenue × 5-year *median* net margin ÷ shares |
| Growth underwritten | mean(EPS CAGR, revenue CAGR), cap 30% | mean(3y, 5y revenue CAGR), cap by quality tier (25/18/10%) |
| Why | simple | a lagging EPS base makes any scaling business look expensive |

**Assumptions:** quarterly decisions (Mar/Jun/Sep/Dec month-end) · execution at next day's close · 25 bps cost per side · idle cash earns 6% · no dividends or tax · start with 100.

> ⚠️ 4 stocks over 8 years is a **sanity check on logic, not evidence of skill**. Thresholds were set from the written principles *before* any backtest; changes made after seeing results are listed in section 4.
""")
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
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path("..", "src").resolve()))
import prices, fetch_fundamentals
from ipm import backtest as B, config

import settings
DATA = settings.DATA
if not (DATA / "px_AMBER.csv").exists(): prices.main(DATA)                       # Yahoo prices
if not (DATA / "fundamentals" / "AMBER_pl.csv").exists():                         # Screener.in financials
    fetch_fundamentals.main(DATA / "fundamentals")

INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
COL = {"IPM v2": "#2a78d6", "IPM v1": "#6da7ec", "Nifty 50": "#52514e", "Equal-weight buy&hold": "#eb6834"}
plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID,
    "axes.axisbelow": True, "axes.titleweight": "bold", "axes.titlecolor": INK, "legend.frameon": False})
""")
md("## 1. Run both versions and the benchmarks")
code("""
res = {}
for v in ("v1", "v2"):
    nav, trades, decs, px = B.run(DATA, valuation=v)
    res[v] = dict(nav=nav, trades=trades, decs=decs)
nav2 = res["v2"]["nav"]
nifty = px["NIFTY50"]["Close"].reindex(nav2.index).ffill(); nifty = nifty / nifty.iloc[0] * 100
ew = pd.concat([px[t]["Close"].reindex(nav2.index).ffill() for t in B.TICKERS], axis=1)
ew = (ew / ew.bfill().iloc[0]).mean(axis=1) * 100          # equal-weight, bought on day 1, never rebalanced
series = {"IPM v1": res["v1"]["nav"], "IPM v2": nav2, "Nifty 50": nifty, "Equal-weight buy&hold": ew}
S = pd.DataFrame({k: B.stats(s) for k, s in series.items()}).T
S["trades"] = [len(res["v1"]["trades"]), len(res["v2"]["trades"]), np.nan, np.nan]
display(S.style.format({"CAGR": "{:.1%}", "vol": "{:.1%}", "maxDD": "{:.1%}", "sharpe": "{:.2f}", "final": "{:.0f}", "trades": "{:.0f}"}))
""")
code("""
fig, ax = plt.subplots(figsize=(10, 4))
for k, s in series.items(): ax.plot(s.index, s.values, label=k, color=COL[k], lw=1.6 if "v2" in k else 1.2)
ax.set_yscale("log"); ax.set_ylabel("Value of 100 (log scale)"); ax.set_title("Portfolio Manager vs benchmarks"); ax.legend(ncol=2, loc="upper left")
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
plt.tight_layout(); plt.savefig(DATA / "ipm_nav.png", bbox_inches="tight"); plt.show()
""")
md("""
## 2. What was it actually doing? Decisions over time

Each cell is one quarterly decision for one stock. **NONE** = not held and not buyable that quarter.
""")
code("""
from matplotlib.colors import ListedColormap
acts = ["NONE", "BUY", "ADD", "HOLD", "TRIM", "EXIT"]
shade = ["#f0efec", "#2a78d6", "#6da7ec", "#cde2fb", "#eda100", "#e34948"]
def grid(v):
    d = pd.DataFrame([{"date": x.date, "tk": x.ticker, "a": acts.index(x.action)} for x in res[v]["decs"]])
    return d.pivot(index="tk", columns="date", values="a").loc[B.TICKERS]
fig, axes = plt.subplots(2, 1, figsize=(11, 3.6), sharex=True)
for ax, v in zip(axes, ("v1", "v2")):
    g = grid(v); ax.imshow(g.values, aspect="auto", cmap=ListedColormap(shade), vmin=0, vmax=5, interpolation="nearest")
    ax.set_yticks(range(4), [t.title() if t != "DBL" else "DBL" for t in B.TICKERS]); ax.set_title(f"{v}", loc="left", fontsize=10); ax.grid(False)
    yrs = [i for i, c in enumerate(g.columns) if c.month == 12]; ax.set_xticks(yrs, [g.columns[i].year for i in yrs])
from matplotlib.patches import Patch
fig.legend([Patch(color=c) for c in shade], acts, ncol=6, loc="lower center", bbox_to_anchor=(.5, -.04))
plt.tight_layout(); plt.savefig(DATA / "ipm_decisions.png", bbox_inches="tight"); plt.show()
""")
code("""
# Audit trail: every trade carries its reason, so a PM can challenge it.
display(res["v2"]["trades"].assign(amount=lambda d: d.amount.round(1)).style.hide(axis="index"))
""")
md("""
## 3. The finding: principles + conventional multiples reject the best trade

For Amber at four dates, the v2 arithmetic (checked by hand): through-cycle EPS × (1+g)^4 × exit P/E, versus today's price.
""")
code("""
import fundamentals as F
from ipm.scoring import quality, expected_cagr
A = F.annual(DATA/"fundamentals", "AMBER"); P = F.promoter(DATA/"fundamentals", "AMBER"); pa = px["AMBER"]
rows = []
for d in ["2019-06-28", "2020-03-31", "2021-03-31", "2022-06-30"]:
    s = F.snapshot(A, P, d); price = float(pa.loc[:d, "Close"].iloc[-1]); q = quality("AMBER", A, s, d)["quality"]
    e = expected_cagr(A, s, price, q, d, "v2")
    rows.append(dict(date=d, price=round(price), quality=round(q), trailing_PE=round(price / e["norm_eps"]), exit_PE_allowed=e["exit_pe"],
                     target=round(e["target_price"]), expected_3y_cagr=f"{e['exp_cagr']:+.0%}"))
display(pd.DataFrame(rows))
print("Amber traded at 40-90x earnings; a rule that sells at 22-28x cannot underwrite it. The investor still earned ~Rs74 cr on ~Rs25 cr because earnings grew AND the premium multiple held.")
""")
md("""
## 4. Robustness: sweep the exit multiple

Two sweeps on the exit P/E: (a) change only the top quality tier; (b) scale the whole schedule (28/22/16/10) by a factor. This is **sensitivity analysis, not optimisation**; I know Amber was the winner, so any single multiple I picked would be partly fitted. Showing the whole curve avoids that.
""")
code("""
base = config.T.exit_pe
def run_case(label, **kw):
    with B.with_thresholds(**kw):
        nav, tr, _, _ = B.run(DATA, valuation="v2")
    s = B.stats(nav); first = tr[(tr.ticker == "AMBER") & (tr.side == "BUY")].date.min()
    return dict(case=label, CAGR=s["CAGR"], maxDD=s["maxDD"], sharpe=s["sharpe"], trades=len(tr), first_amber_buy=first.date() if pd.notna(first) else "never")
cases = [run_case("baseline 28/22/16/10")]
cases += [run_case(f"top tier -> {t}x", exit_pe=((70, float(t)),) + base[1:]) for t in (35, 40, 50, 60)]
cases += [run_case(f"all tiers x{m}", exit_pe=tuple((t, p * m) for t, p in base)) for m in (1.25, 1.5, 2.0)]
sweep = pd.DataFrame(cases)
display(sweep.style.format({"CAGR": "{:.1%}", "maxDD": "{:.1%}", "sharpe": "{:.2f}"}).hide(axis="index"))
print("config restored:", config.T.exit_pe == base)
""")
code("""
fig, ax = plt.subplots(figsize=(9, 3.6))
lab = sweep.case.str.replace("baseline 28/22/16/10", "baseline")
ax.bar(range(len(sweep)), sweep.CAGR * 100, color=["#a8a7a1"] + ["#2a78d6"] * 4 + ["#6da7ec"] * 3, width=.6)
ax.axhline(B.stats(nifty)["CAGR"] * 100, color=COL["Nifty 50"], ls="--", lw=1); ax.text(len(sweep) - .5, B.stats(nifty)["CAGR"] * 100 + .3, "Nifty 50", ha="right", color=MUTED, fontsize=8)
for i, v in enumerate(sweep.CAGR * 100): ax.text(i, v + .25, f"{v:.1f}", ha="center", fontsize=8, color=INK)
ax.set_xticks(range(len(sweep)), lab, rotation=25, ha="right", fontsize=8); ax.set_ylabel("Annual return (%)"); ax.set_title("Result vs exit multiple: not monotonic")
plt.tight_layout(); plt.savefig(DATA / "ipm_sweep.png", bbox_inches="tight"); plt.show()
""")
md("""
## 5. What this tells us (edit after re-running)

1. **v2 is only marginally better than v1** (≈+0.6 pp/yr, fewer trades) and both trail Nifty 50. The improvement is within noise.
2. **The PM spends most of its time in cash.** Few stock-quarters pass quality + the 25% hurdle + the avoid list together. That is a property of the principles *as quantified*, not a bug.
3. **With conventional exit multiples (≤28×) the PM never buys Amber**, the portfolio's best trade. With top-tier multiples ≥35× it buys Amber (first buy 2018–2020 depending on the multiple).
4. **The return is not monotonic in the multiple** (e.g. 9.5% at 35×, 7.5% at 40×, 10.3% at 50×): small rule changes flip individual entries and exits. Several settings beat Nifty 50 (1.25x schedule 11.8%, top tier 60x 12.9%, 2x schedule 15.9%, close to equal-weight buy&hold at 15.6%), but they sit beside settings that do not (1.5x schedule 9.1%). With 4 stocks there is no stable optimum, so I would not publish any single multiple as "right" or claim the PM beats the index.
5. **Zee is still bought in 2019** (quality 85, debt-free, 27% ROCE). The governance collapse was not in any number. This is the case for a research/governance overlay that can *veto* a buy (built next, but it cannot be backtested because the reports are all dated May 2026).
6. **Recommendation to WISDOM:** the principles page needs an explicit premium-multiple rule for structural growth (Principle 4 says “willing to pay” but gives no number). Until that is decided, the quant layer should *flag* high-quality-but-expensive names for human judgement instead of auto-rejecting them.

**Changes made after seeing backtest results (disclosed):** (a) replaced the v1 valuation with v2 because v1's lagging EPS base contradicted Principle 4; (b) nothing else was tuned. The multiple sweep is reported in full, not selected from.
""")
nb["cells"]=C; nb["metadata"]={"kernelspec":{"name":"wisdom-ipm","display_name":"WISDOM IPM (.venv)","language":"python"}}
nbf.write(nb, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "notebooks" / "02_portfolio_manager_v1_v2.ipynb")); print("ok",len(C))
