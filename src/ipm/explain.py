"""Plain-English explanation of each engine decision.

Rule: the CODE decides, the AI only explains.
  1. `decision_record()` turns an engine Decision into a stock-level record of pre-formatted facts:
     scores, gate results, the 25% return test, guardrails, verified research quotes.
     Portfolio weights and position sizes are deliberately left out (WISDOM data stays local).
  2. Claude rewrites the record as a short explanation (fixed schema, no tools).
  3. `number_check()` rejects the explanation if it contains any number that is not in the record.
     A rejected explanation falls back to a deterministic template, so a wrong number can never be shown.
Explanations are cached by a hash of the record, so re-runs are free and reproducible.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import research as R
from .config import T

PROMPT_VERSION = "explain-v1"

SYSTEM = (
    "You explain decisions made by a rules-based portfolio engine to an investment committee. "
    "Use ONLY the facts in the decision record. Do not add facts, opinions or a different recommendation. "
    "Write plainly, for a reader who is not a finance specialist; explain any jargon in a few words. "
    "Copy numbers exactly as they are written in the record; never compute new numbers. "
    "The counterpoint must come from facts in the record (e.g. a principle in tension, or a positive signal)."
)

SCHEMA = {
    "type": "object",
    "required": ["summary", "key_drivers", "what_would_change_it", "counterpoint"],
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentences: what the engine suggests and the main reason"},
        "key_drivers": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
        "what_would_change_it": {"type": "string", "description": "which condition in the record would flip the call"},
        "counterpoint": {"type": "string", "description": "the strongest argument against the call, from the record"},
    },
}

PRINCIPLE_LABEL = {"growth": "Growth (revenue and margins)", "returns": "Return on capital (ROCE)",
                   "durability": "Durability through bad years", "cash": "Cash generation",
                   "balance": "Balance sheet / debt", "alignment": "Founder / promoter stake"}
MAX_PTS = {"growth": 20, "returns": 25, "durability": 10, "cash": 15, "balance": 20, "alignment": 10}


def _pct(x):
    return "n/a" if x != x or x is None else f"{x * 100:+.0f}%"


def _rs(x, unit=""):
    return "n/a" if x != x or x is None else f"Rs {x:,.0f}{unit}"


def decision_record(d, research_item: dict | None) -> dict:
    """Stock-level, pre-formatted facts behind one decision. No weights or quantities."""
    e = d.details or {}
    s = e.get("snap") or {}
    rec = {
        "stock": d.ticker,
        "suggested_action": d.action,
        "engine_reason": d.reason,
        "quality_score": f"{d.quality:.0f} out of 100" if d.quality == d.quality else "n/a",
        "quality_breakdown": {PRINCIPLE_LABEL[k]: f"{e.get('q_' + k, float('nan')):.1f} of {MAX_PTS[k]} points"
                              for k in PRINCIPLE_LABEL if e.get("q_" + k) is not None},
        "quality_bars": f"need {T.min_quality_buy:.0f} to buy, {T.min_quality_hold:.0f} to keep holding",
        "key_financials": {
            "revenue growth, 3-year annual": _pct(s.get("rev_cagr_3y")),
            "return on capital (ROCE), 3-year average": _pct(e.get("roce3")).lstrip("+"),
            "debt to equity": f"{s.get('de', float('nan')):.2f}x",
            "interest cover (operating profit / interest)": f"{s.get('int_cover', float('nan')):.1f}x",
            "free cash flow, last 3 years combined": _rs(s.get("fcf_3y"), " cr"),
            "promoter (founder) holding": _pct(s.get("promoter")).lstrip("+"),
        },
        "avoid_list_checks_failed": d.gates or ["none"],
        "return_test": {
            "hurdle": f"{T.buy_cagr:.0%} a year over {T.hurdle_horizon_yrs} years",
            "price_today": _rs(e.get("price")),
            "fair_value_in_3_years": _rs(e.get("target_price")),
            "expected_return_per_year": _pct(d.exp_cagr),
            "growth_assumed_per_year": _pct(e.get("growth_used")),
            "valuation_multiple_allowed_at_exit": f"{e.get('exit_pe', float('nan')):.0f}x earnings",
            "valuation_today": f"{e.get('pe_now', float('nan')):.0f}x normalised earnings",
        },
        "guardrails": [f"minimum hold {T.min_hold_qtrs} quarters", f"max {T.max_weight:.0%} in one stock",
                       f"no valuation-trim when quality is {T.trim_exempt_quality} or more"],
    }
    if research_item:
        ev, ov = research_item["evidence"], research_item["overlay"]
        rec["research_overlay"] = {
            "buy_blocked": ov.get("veto_buy") or "no",
            "broker_view": ev["analyst_view"].get("rating") or "no rating in report",
            "verified_warnings": [f"{f['category']} ({f['severity']}), p.{f['page']}: \"{f['quote']}\""
                                  for f in ev["red_flags"] if f["severity"] in ("medium", "high")][:4],
            "principle_views": {k: v["assessment"] for k, v in ev["principles"].items()},
        }
    return rec


_NUM = re.compile(r"(?<![A-Za-z])[-+−]?\d[\d,]*(?:\.\d+)?")


def _nums(text: str) -> set[float]:
    out = set()
    for m in _NUM.findall(text):
        try:
            out.add(abs(float(m.replace(",", "").replace("−", "-"))))
        except ValueError:
            pass
    return out


def number_check(explanation: dict, record: dict) -> list[float]:
    """Numbers in the explanation that do not appear in the record. Small integers (counts,
    'Principle 3', '3 years') are allowed. Empty list = pass."""
    allowed = _nums(json.dumps(record, ensure_ascii=False))
    text = " ".join([explanation["summary"], *explanation["key_drivers"],
                     explanation["what_would_change_it"], explanation["counterpoint"]])
    bad = []
    for n in _nums(text):
        if n <= 12 and float(n).is_integer():
            continue
        if not any(abs(n - a) <= max(0.051, 0.005 * a) for a in allowed):
            bad.append(n)
    return sorted(bad)


def template(record: dict) -> dict:
    """Deterministic fallback, used whenever the AI explanation fails the number check."""
    rt = record["return_test"]
    gates = [g for g in record["avoid_list_checks_failed"] if g != "none"]
    return {
        "summary": f"{record['stock']}: suggested action {record['suggested_action']}. {record['engine_reason']}.",
        "key_drivers": [f"Quality {record['quality_score']} ({record['quality_bars']})",
                        f"Expected return {rt['expected_return_per_year']} a year vs hurdle {rt['hurdle']}",
                        *(f"Avoid-list check failed: {g}" for g in gates)][:4],
        "what_would_change_it": "See the return test and avoid-list checks above.",
        "counterpoint": "Template explanation: no counterpoint generated.",
    }


def explain(decision, research_item, cache_dir: Path, model: str = R.MODEL) -> dict:
    record = decision_record(decision, research_item)
    body = json.dumps(record, indent=1, ensure_ascii=False)
    key = hashlib.sha256(f"{PROMPT_VERSION}|{model}|{body}".encode()).hexdigest()[:16]
    cache = cache_dir / f"explain_{decision.ticker}_{key}.json"
    if cache.exists():
        exp = json.loads(cache.read_text())
    else:
        exp = R.call_claude(f"Decision record:\n{body}", model=model, system=SYSTEM, schema=SCHEMA)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(exp, indent=1, ensure_ascii=False))
    bad = number_check(exp, record)
    if bad:
        return {"source": "template (AI explanation rejected)", "unsupported_numbers": bad, "record": record, **template(record)}
    return {"source": "AI, number-checked", "unsupported_numbers": [], "record": record, **exp}
