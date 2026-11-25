"""Decision engine: one call per decision date -> BUY / ADD / HOLD / TRIM / EXIT per stock + target weights.

Every decision carries a human-readable `reason` string and the principle(s) it came from,
so a PM can audit it. The engine never calls an LLM: qualitative research enters only as
an explicit, cited *overlay* (see research.py) that can veto a BUY or flag a review.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import fundamentals as F

from .config import T
from .scoring import expected_cagr, gates, quality


@dataclass
class Decision:
    date: pd.Timestamp
    ticker: str
    action: str
    reason: str
    quality: float = np.nan
    exp_cagr: float = np.nan
    target_weight: float = 0.0
    gates: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


def evaluate(tk, A, P, px, d, trail_6m, valuation="v1"):
    """Score one stock as of date d using only data public on d."""
    snap = F.snapshot(A, P, d)
    if snap is None:
        return None
    price = float(px.loc[:d, "Close"].iloc[-1])
    qd = quality(tk, A, snap, d)
    ec = expected_cagr(A, snap, price, qd["quality"], d, valuation)
    return dict(snap=snap, price=price, gates=gates(tk, A, snap, d), trail_6m=trail_6m, **qd, **ec)


def decide(d, ev: dict, held_w: dict, age_qtrs: dict, overlay: dict | None = None) -> list[Decision]:
    """ev: {ticker: evaluate()}; held_w: current weights; age_qtrs: quarters since last purchase."""
    out, want = [], {}
    for tk, e in ev.items():
        if e is None:
            out.append(Decision(d, tk, "HOLD" if held_w.get(tk, 0) else "NONE", "insufficient history"))
            continue
        q, c, w0 = e["quality"], e["exp_cagr"], held_w.get(tk, 0.0)
        held = w0 > 1e-4
        ov = (overlay or {}).get(tk, {})
        dec = Decision(d, tk, "HOLD", "", q, c, w0, e["gates"], dict(e, overlay=ov))

        if e["gates"]:                                                              # avoid list
            if held and age_qtrs.get(tk, 99) >= T.min_hold_qtrs:
                dec.action, dec.target_weight = "EXIT", 0.0
                dec.reason = f"Avoid-list gate: {e['gates'][0]}"
            elif held:
                dec.action, dec.target_weight = "TRIM", w0 * 0.5
                dec.reason = f"Avoid-list gate ({e['gates'][0]}) but inside {T.min_hold_qtrs}-qtr min hold: halve, review"
            else:
                dec.action, dec.reason = "NONE", f"Blocked by avoid list: {e['gates'][0]}"
        elif q < T.min_quality_hold:
            if held and age_qtrs.get(tk, 99) >= T.min_hold_qtrs:
                dec.action, dec.target_weight, dec.reason = "EXIT", 0.0, f"Quality {q:.0f} < {T.min_quality_hold:.0f} hold bar"
            else:
                dec.action, dec.reason = ("HOLD", "Quality below bar, protected by min-hold") if held else ("NONE", f"Quality {q:.0f} below bar")
        elif q >= T.min_quality_buy and c >= T.buy_cagr:                            # passes quality + 25% hurdle
            falling_knife = T.dip_filter and e["trail_6m"] < -0.20 and q < 70
            veto = ov.get("veto_buy")
            if falling_knife:
                dec.action, dec.target_weight = ("HOLD", w0) if held else ("NONE", 0.0)
                dec.reason = f"Hurdle met ({c:.0%}) but stock -{abs(e['trail_6m']):.0%} in 6m and quality<70: falling-knife filter"
            elif veto:
                dec.action, dec.target_weight = ("HOLD", w0) if held else ("NONE", 0.0)
                dec.reason = f"Research overlay veto: {veto}"
            else:
                want[tk] = (q / 100) * min(c / T.buy_cagr, 2.0)
                dec.action = "ADD" if held else "BUY"
                dec.reason = f"Quality {q:.0f}, expected 3y CAGR {c:.0%} >= {T.buy_cagr:.0%} hurdle"
        elif held and c < T.trim_cagr and q < T.trim_exempt_quality and age_qtrs.get(tk, 99) >= T.min_hold_qtrs:
            dec.action, dec.target_weight = "TRIM", w0 * 0.5
            dec.reason = f"Expected CAGR {c:.0%} < {T.trim_cagr:.0%} and quality {q:.0f} < {T.trim_exempt_quality}: no compounding case"
        else:
            dec.reason = (f"Hold: quality {q:.0f}, expected CAGR {c:.0%} (hurdle {T.buy_cagr:.0%})"
                          + (" - compounder exempt from valuation trim" if held and c < T.trim_cagr and q >= T.trim_exempt_quality else ""))
            dec.action = "HOLD" if held else "NONE"
        out.append(dec)

    # --- sizing: conviction-weighted among BUY/ADD names, capped, ramped (anti-chasing, anti-concentration) ---
    tot = sum(want.values())
    budget = 1.0 - sum(x.target_weight for x in out if x.action in ("HOLD", "TRIM", "EXIT") and x.ticker not in want
                       and x.target_weight == x.target_weight)
    for x in out:
        if x.ticker in want:
            tgt = min(T.max_weight, want[x.ticker] / tot * max(budget, 0)) if tot else 0
            tgt = min(tgt, held_w.get(x.ticker, 0.0) + T.max_weight_step)           # ramp, don't leap
            x.target_weight = max(tgt, held_w.get(x.ticker, 0.0) if x.action == "ADD" else tgt)
    return out
