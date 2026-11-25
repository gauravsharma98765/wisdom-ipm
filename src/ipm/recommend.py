"""Today's recommendation for WISDOM's actual book = quant engine (v2) + verified research overlay.

The trade ledger (proprietary) is used only locally to compute current weights and holding age.
It is never sent to the LLM. The output is a *recommendation for human approval*, not an order.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import fundamentals as F

from . import research as R
from .config import T
from .engine import decide, evaluate

TICKERS = ["AMBER", "DBL", "WELSPUN", "ZEE"]


def current_book(ledger: pd.DataFrame, px: dict, asof) -> tuple[dict, dict]:
    """Weights from net quantity x latest close; age = quarters since the last buy."""
    asof = pd.Timestamp(asof)
    led = ledger[ledger.date <= asof]
    qty = led.groupby("ticker").signed_qty.sum()
    mv = {t: max(qty.get(t, 0.0), 0.0) * float(px[t]["Close"].loc[:asof].iloc[-1]) for t in TICKERS}
    tot = sum(mv.values())
    w = {t: mv[t] / tot if tot else 0.0 for t in TICKERS}
    last_buy = led[led.side == "BUY"].groupby("ticker").date.max()
    age = {t: int((asof - last_buy[t]).days / 91) if t in last_buy else 99 for t in TICKERS}
    return w, age


def recommend(data: Path, ledger: pd.DataFrame, asof=None, valuation="v2", use_research=True):
    px = {t: pd.read_csv(data / f"px_{t}.csv", index_col=0, parse_dates=True) for t in TICKERS}
    asof = pd.Timestamp(asof) if asof else min(p.index.max() for p in px.values())
    ev = {}
    for t in TICKERS:
        A, P = F.annual(data / "fundamentals", t), F.promoter(data / "fundamentals", t)
        c = px[t]["Close"].loc[:asof]
        tr = c.iloc[-1] / c.loc[:asof - pd.Timedelta(days=182)].iloc[-1] - 1
        ev[t] = evaluate(t, A, P, px[t], asof, tr, valuation)
    research = R.run_all(data / "research", data / "research_llm") if use_research else {}
    overlay = {t: research[t]["overlay"] for t in research}
    w, age = current_book(ledger, px, asof)
    decs = decide(asof, ev, w, age, overlay)
    rows = []
    for d in decs:
        e, ov = d.details, overlay.get(d.ticker, {})
        rows.append(dict(
            ticker=d.ticker, current_weight=w[d.ticker], action=d.action, target_weight=d.target_weight,
            quality=d.quality, exp_3y_cagr=d.exp_cagr, price=e.get("price"), target_price=e.get("target_price"),
            gates="; ".join(d.gates) or "-", reason=d.reason,
            research_veto=ov.get("veto_buy") or "-",
            human_review="YES: " + ", ".join(ov.get("review_reasons", [])[:3]) if ov.get("review") else "no",
            analyst=(research.get(d.ticker, {}).get("evidence", {}).get("analyst_view", {}) or {}).get("rating"),
            decision=d,                                    # full record, used by explain.py
        ))
    return asof, pd.DataFrame(rows), research
