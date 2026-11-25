"""Deterministic quant layer: turns point-in-time fundamentals into
  (1) a 0-100 quality score broken down by WISDOM principle,
  (2) hard 'avoid list' gates,
  (3) an expected 3-year price CAGR vs the 25% hurdle.

No LLM here on purpose: every number must be reproducible and auditable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import SECTOR, T


def lin(x, zero, full):
    """0..1 linear ramp; works whichever direction (zero may be > full for 'lower is better')."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    return float(np.clip((x - zero) / (full - zero), 0, 1))


def _avg(A, col, d, n=3):
    return A[A.avail <= d][col].tail(n).mean()


def quality(tk: str, A: pd.DataFrame, snap: dict, d) -> dict:
    """Quality score by principle. Weights sum to 100. Missing inputs score neutral (50%) rather than 0."""
    d = pd.Timestamp(d)
    sec = SECTOR[tk]
    # capital-intensive / cyclical businesses are held to a stricter leverage bar (Principle 5)
    k = 0.7 if sec["capital_intensive"] else 1.0
    roce3 = _avg(A, "roce", d)
    roce_min5 = A[A.avail <= d].roce.tail(5).min()
    cfo_conv = _avg(A, "cfo_ebitda", d)
    parts = {
        "growth":       20 * np.nanmean([lin(snap["rev_cagr_3y"], 0, T.rev_cagr_full),
                                         lin(snap["opm_chg_3y"], -0.05, 0.02)]),                # revenue + margin direction
        "returns":      25 * lin(roce3, T.roce_zero, T.roce_full),                              # ROCE/ROE, multi-year
        "durability":   10 * lin(roce_min5, 0.04, 0.14),                                        # worst year in 5 (cycle-proof?)
        "cash":         15 * np.nanmean([lin(cfo_conv, 0.3, T.cfo_ebitda_full),
                                         1.0 if snap["fcf_3y"] > 0 else 0.0]),                  # FCF (Principle 1c)
        "balance":      20 * np.nanmean([lin(snap["de"], T.de_zero * k, T.de_full * k),
                                         lin(snap["int_cover"], T.cover_zero, T.cover_full)]),  # Principle 5
        "alignment":    10 * (lin(snap["promoter"], T.promoter_zero, T.promoter_full)
                              if snap["promoter"] == snap["promoter"] else 0.5),                # Principle 2 (neutral if unknown)
    }
    parts = {kk: (v if v == v else 0.5 * {"growth": 20, "returns": 25, "durability": 10, "cash": 15, "balance": 20, "alignment": 10}[kk])
             for kk, v in parts.items()}
    return {"quality": sum(parts.values()), **{f"q_{kk}": v for kk, v in parts.items()}, "roce3": roce3}


def gates(tk: str, A: pd.DataFrame, snap: dict, d) -> list[str]:
    """'What we avoid' (Principles page 2). Any hit blocks buying and forces an exit once min-hold has elapsed."""
    d = pd.Timestamp(d)
    hit = []
    a = A[A.avail <= d]
    last3 = a.tail(3)
    if (last3.pat <= 0).sum() >= 2 or snap["pat"] <= 0:
        hit.append("TURNAROUND: loss-making in 2 of last 3 years / latest year")
    peak = a.roce.tail(5).max()
    if snap["roce"] < 0.5 * peak and snap["rev_cagr_3y"] < 0.05:
        hit.append("TURNAROUND: ROCE halved vs 5y peak with no growth")
    if snap["de"] > T.gate_de and snap["int_cover"] < T.gate_cover:
        hit.append("LEVERAGE: debt/equity and interest cover both breach limits")
    if snap["fcf_3y"] < 0 and len(a) >= 4 and a.debt.iloc[-1] > a.debt.iloc[-4] * 1.25:
        hit.append("EXTERNAL CAPITAL: negative 3y FCF funded by rising debt")
    if snap["promoter"] == snap["promoter"] and snap["promoter"] < 0.10:
        hit.append("ALIGNMENT: promoter holding <10% (not owner-operated)")
    return hit


def _growth_cap(q: float) -> float:
    """v2: how much growth we are willing to underwrite depends on business quality (Principle 4:
    pay for growth only where it is durable). Low-quality names get no extrapolation."""
    return 0.25 if q >= 70 else 0.18 if q >= 55 else 0.10


def expected_cagr(A: pd.DataFrame, snap: dict, price: float, q: float, d, valuation: str = "v1") -> dict:
    """Principle 1.2: 'target price CAGR > 25% with a value threshold'.

    v1 (original): forward EPS = mean of last 3 FY EPS x (1+g)^4, g = mean(EPS CAGR, revenue CAGR) capped at 30%.
        Flaw found in first backtest: a 3-year-average EPS is a lagging base, so a business that is
        scaling (Amber) always looks expensive on trailing P/E - contradicting Principle 4.
    v2 (this fix): earnings power = forward revenue x through-cycle net margin (5y median), per share.
        Growth g = mean(3y, 5y revenue CAGR), ceiling set by quality tier. Margin is the median over
        5 years so a cyclical peak or trough is not capitalised (Principle 4's 'cyclical mistaken for
        structural' warning). Exit multiple by quality tier is unchanged.
    """
    d = pd.Timestamp(d)
    a = A[A.avail <= d]
    pe = next(p for thr, p in T.exit_pe if q >= thr)
    H = T.hurdle_horizon_yrs
    if valuation == "v1":
        base = max(a.eps.tail(3).mean(), 0.0)
        g_eps = snap["eps_cagr_3y"]
        g = np.nanmean([g_eps if g_eps == g_eps else np.nan, snap["rev_cagr_3y"]])
        g = float(np.clip(0.0 if g != g else g, T.growth_floor, T.growth_cap))
        fwd_eps = base * (1 + g) ** (H + 1)
    else:
        rev = a.revenue
        g5 = (rev.iloc[-1] / rev.iloc[-6]) ** (1 / 5) - 1 if len(rev) >= 6 else np.nan
        g = np.nanmean([snap["rev_cagr_3y"], g5])
        g = float(np.clip(0.0 if g != g else g, T.growth_floor, _growth_cap(q)))
        margin = max((a.pat / a.revenue).tail(5).median(), 0.0)
        shares = a.pat.iloc[-1] / a.eps.iloc[-1] if a.eps.iloc[-1] not in (0, np.nan) and a.pat.iloc[-1] != 0 else np.nan
        if shares != shares or shares <= 0:                      # loss-making latest year: infer shares from older year
            ok = a[(a.eps > 0) & (a.pat > 0)]
            shares = (ok.pat / ok.eps).iloc[-1] if len(ok) else np.nan
        fwd_eps = rev.iloc[-1] * (1 + g) ** (H + 1) * margin / shares if shares == shares else 0.0
        base = rev.iloc[-1] * margin / shares if shares == shares else 0.0     # today's through-cycle EPS
    tgt = fwd_eps * pe
    cagr = (tgt / price) ** (1 / H) - 1 if tgt > 0 else -1.0
    return {"exp_cagr": cagr, "target_price": tgt, "growth_used": g, "exit_pe": pe, "norm_eps": base,
            "pe_now": price / base if base > 0 else np.nan}
