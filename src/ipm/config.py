"""All tunable assumptions in ONE place. Thresholds are set a priori from WISDOM's written
Investment Principles (not fitted to the investor's historical outcomes).

Each field cites the principle it implements so a reviewer can challenge it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Thresholds:
    # --- Principle 1: fundamentals thresholds (growth, ROE/ROCE, FCF, sector) -------------
    rev_cagr_full: float = 0.15      # 3y revenue CAGR scoring full marks
    roce_full: float = 0.18          # 3y-avg ROCE scoring full marks
    roce_zero: float = 0.08          # ~cost of capital: no credit below this
    cfo_ebitda_full: float = 0.70    # cash conversion scoring full marks
    # --- Principle 5: balance-sheet conservatism ---------------------------------------
    de_full: float = 0.30            # debt/equity scoring full marks
    de_zero: float = 1.50            # debt/equity scoring zero
    cover_full: float = 6.0          # interest cover scoring full marks
    cover_zero: float = 1.5
    # --- Principle 2: management with skin in the game ----------------------------------
    promoter_full: float = 0.50
    promoter_zero: float = 0.10
    # --- Principle 1.2: target price CAGR > 25% -----------------------------------------
    buy_cagr: float = 0.25           # minimum expected 3y price CAGR to add
    trim_cagr: float = 0.08          # below this a non-compounder is trimmed
    hurdle_horizon_yrs: int = 3
    growth_cap: float = 0.30         # cap on extrapolated growth (guards against hype)
    growth_floor: float = -0.10
    # --- Principle 4: premium multiples only for durable quality (exit P/E by tier) -----
    exit_pe: tuple = ((70, 28.0), (55, 22.0), (40, 16.0), (0, 10.0))
    # --- "What we avoid" hard gates -----------------------------------------------------
    gate_de: float = 2.0             # leverage gate: D/E above this AND cover below gate_cover
    gate_cover: float = 2.0
    min_quality_hold: float = 40.0   # below this we do not hold
    min_quality_buy: float = 55.0
    # --- Behavioural guardrails (derived from the Step-1 scorecard) ---------------------
    max_weight: float = 0.40         # concentration cap (investor reached 80-100% in one name)
    min_hold_qtrs: int = 4           # anti-churn: no discretionary sell inside 12 months
    trim_exempt_quality: float = 70  # "don't sell the compounder early": no valuation trim above this
    dip_filter: bool = True          # falling-knife filter: buying after a 6m fall needs quality >= buy bar
    max_weight_step: float = 0.15    # max change in target weight per decision (conviction ramp)
    # --- Execution assumptions ----------------------------------------------------------
    cost_per_trade: float = 0.0025   # 25 bps all-in (brokerage, STT, impact) per side
    cash_yield: float = 0.06         # liquid-fund proxy on idle cash
    results_lag_days: int = 60
    decision_months: tuple = (3, 6, 9, 12)   # quarterly, after results season


# Sector tags drive the "sector-specific criteria" of Principle 1(d). Judgement calls, shown openly.
SECTOR = {
    "AMBER":   dict(sector="EMS / consumer-durable components", capital_intensive=True,  cyclical=True,  note="contract manufacturer, thin margins, rising capex"),
    "DBL":     dict(sector="Infrastructure EPC",                  capital_intensive=True,  cyclical=True,  note="order-book driven, working-capital heavy"),
    "WELSPUN": dict(sector="Home textiles (cotton-linked)",       capital_intensive=True,  cyclical=True,  note="commodity input, export/tariff exposed"),
    "ZEE":     dict(sector="Media / broadcasting",                capital_intensive=False, cyclical=True,  note="linear TV ad cycle, structural decline risk"),
}

T = Thresholds()
