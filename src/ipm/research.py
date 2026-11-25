"""LLM research layer: reads broker reports and returns *cited, verified* evidence per WISDOM principle.

Where the LLM sits (and where it does not):
  * The LLM ONLY extracts and classifies evidence from documents. It never sizes, buys or sells.
  * Every claim must carry a page number and a short verbatim quote.
  * `verify()` checks each quote against the extracted page text in code. Claims whose quote cannot be
    found are DROPPED (and counted), so a hallucinated fact cannot reach the decision engine.
  * `overlay()` turns verified red flags into a BUY veto / human-review flag with fixed rules.

Backend: the local `claude` CLI in headless mode (uses the operator's Claude login; no API key in code).
Only third-party research text is sent. WISDOM's trade data is never sent to the LLM.
Outputs are cached by content hash, so re-runs are reproducible and free.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

PROMPT_VERSION = "v1"
MODEL = "sonnet"

PRINCIPLES = {
    "business_quality": "Enduring competitive advantage; returns on capital through cycles; growth in revenue and margins; free cash flow.",
    "management": "Founder-led / owner-operated, skin in the game, disciplined capital allocation.",
    "reinvestment": "Long runway to reinvest internally at attractive incremental returns.",
    "structural_growth": "Growth from structural (not cyclical) drivers.",
    "balance_sheet": "Strong balance sheet, low leverage, self-funded growth.",
}
FLAG_CATEGORIES = ["governance", "related_party", "promoter_pledge", "turnaround", "leverage",
                   "commodity_exposure", "external_capital", "accounting_change", "execution"]

SCHEMA = {
    "type": "object",
    "required": ["analyst_view", "principles", "red_flags"],
    "properties": {
        "analyst_view": {
            "type": "object", "required": ["rating", "target_price", "page", "quote"],
            "properties": {"rating": {"type": ["string", "null"]}, "target_price": {"type": ["number", "null"]},
                           "page": {"type": ["integer", "null"]}, "quote": {"type": ["string", "null"]}}},
        "principles": {
            "type": "object", "required": list(PRINCIPLES),
            "properties": {k: {
                "type": "object", "required": ["assessment", "claims"],
                "properties": {
                    "assessment": {"enum": ["positive", "neutral", "negative", "not_covered"]},
                    "claims": {"type": "array", "maxItems": 4, "items": {
                        "type": "object", "required": ["statement", "page", "quote"],
                        "properties": {"statement": {"type": "string"}, "page": {"type": "integer"},
                                       "quote": {"type": "string"}}}}}} for k in PRINCIPLES}},
        "red_flags": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "required": ["category", "severity", "statement", "page", "quote"],
            "properties": {"category": {"enum": FLAG_CATEGORIES}, "severity": {"enum": ["low", "medium", "high"]},
                           "statement": {"type": "string"}, "page": {"type": "integer"}, "quote": {"type": "string"}}}},
    },
}

SYSTEM = (
    "You are an equity research analyst extracting evidence for an investment committee. "
    "Use ONLY the document provided. Do not use outside knowledge about the company. "
    "Every claim needs the page number (from the '=== PAGE n ===' markers) and a SHORT verbatim quote "
    "(5-20 consecutive words copied exactly from a single line of that page). "
    "If the document does not cover a principle, set assessment to 'not_covered' with no claims. "
    "Ignore legal disclaimers, analyst certifications and broker disclosures."
)


def load_pages(path: Path) -> list[str]:
    """Pages from a pdftotext -layout dump split on form feeds, or a '=== PAGE n ===' file."""
    txt = path.read_text()
    if "=== PAGE" in txt:
        return re.split(r"=== PAGE \d+ ===\n", txt)[1:]
    return txt.split("\f")


def _norm(s: str) -> list[str]:
    return re.findall(r"[a-z0-9.%]+", s.lower())


def quote_found(quote: str, page_text: str, min_cov: float = 0.8) -> bool:
    """True if the quote is on the page. Layout extraction can interleave columns, so we accept the
    quote if >= min_cov of its 4-word shingles occur on the page (exact match is the common case)."""
    q, p = _norm(quote), _norm(page_text)
    if len(q) < 3:
        return False
    if " ".join(q) in " ".join(p):
        return True
    n = 4 if len(q) >= 6 else 2
    sh = {tuple(q[i:i + n]) for i in range(len(q) - n + 1)}
    ps = {tuple(p[i:i + n]) for i in range(len(p) - n + 1)}
    return len(sh & ps) / len(sh) >= min_cov


def call_claude(prompt: str, model: str = MODEL, system: str = SYSTEM, schema: dict = SCHEMA) -> dict:
    cmd = ["claude", "-p", "--output-format", "json", "--model", model,
           "--system-prompt", system, "--json-schema", json.dumps(schema),
           "--tools", "", "--strict-mcp-config", "--setting-sources", "",
           "--disable-slash-commands", "--no-session-persistence"]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {r.stderr[:500] or r.stdout[:500]}")
    out = json.loads(r.stdout)
    if out.get("structured_output") is not None:
        return out["structured_output"]
    res = out.get("result", "")
    m = re.search(r"\{.*\}", res, re.S)
    return json.loads(m.group(0))


def extract(ticker: str, pages: list[str], cache_dir: Path, model: str = MODEL) -> dict:
    doc = "".join(f"=== PAGE {i} ===\n{p}\n" for i, p in enumerate(pages, 1))
    key = hashlib.sha256(f"{PROMPT_VERSION}|{model}|{doc}".encode()).hexdigest()[:16]
    cache = cache_dir / f"{ticker}_{key}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    principles = "\n".join(f"- {k}: {v}" for k, v in PRINCIPLES.items())
    prompt = (f"Company: {ticker}\n\nWISDOM investment principles to assess:\n{principles}\n\n"
              f"Red-flag categories (WISDOM 'what we avoid'): {', '.join(FLAG_CATEGORIES)}\n\n"
              f"Broker research report follows.\n\n{doc}")
    raw = call_claude(prompt, model)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(raw, indent=1))
    return raw


def verify(raw: dict, pages: list[str]) -> dict:
    """Drop any claim/flag whose quote is not on the cited page. Returns cleaned evidence + audit stats."""
    def ok(item):
        pg = item.get("page")
        return isinstance(pg, int) and 1 <= pg <= len(pages) and quote_found(item.get("quote") or "", pages[pg - 1])
    kept = dropped = 0
    out = {"principles": {}, "red_flags": [], "dropped": []}
    for k, v in raw["principles"].items():
        claims = []
        for c in v["claims"]:
            if ok(c):
                claims.append(c); kept += 1
            else:
                out["dropped"].append({"where": k, **c}); dropped += 1
        # an assessment with no surviving evidence is downgraded to not_covered
        out["principles"][k] = {"assessment": v["assessment"] if claims else "not_covered", "claims": claims}
    for f in raw["red_flags"]:
        if ok(f):
            out["red_flags"].append(f); kept += 1
        else:
            out["dropped"].append({"where": "red_flag", **f}); dropped += 1
    av = raw.get("analyst_view") or {}
    out["analyst_view"] = av if (av.get("quote") and ok(av)) else {"rating": None, "target_price": None, "unverified": av}
    out["audit"] = {"kept": kept, "dropped": dropped}
    return out


VETO_CATEGORIES = {"governance", "related_party", "promoter_pledge", "turnaround", "external_capital"}


def overlay(evidence: dict) -> dict:
    """Fixed rules (no LLM): a verified HIGH-severity flag in an avoid-list category vetoes new buying;
    any verified medium/high flag or a 'negative' principle assessment asks for human review."""
    flags = evidence["red_flags"]
    veto = [f for f in flags if f["severity"] == "high" and f["category"] in VETO_CATEGORIES]
    review = [f for f in flags if f["severity"] in ("medium", "high")]
    negatives = [k for k, v in evidence["principles"].items() if v["assessment"] == "negative"]
    return {
        "veto_buy": (f"{veto[0]['category']}: {veto[0]['statement']} (p.{veto[0]['page']})" if veto else None),
        "review": bool(review or negatives),
        "review_reasons": [f"{f['category']} ({f['severity']}), p.{f['page']}" for f in review]
                          + [f"principle negative: {k}" for k in negatives],
    }


def run_all(research_dir: Path, cache_dir: Path, tickers=("AMBER", "DBL", "WELSPUN", "ZEE"), model: str = MODEL):
    names = {"AMBER": "Amber", "DBL": "DBL", "WELSPUN": "Welspun", "ZEE": "Zee"}
    res = {}
    for tk in tickers:
        pages = load_pages(research_dir / f"{names[tk]}.pages.txt")
        raw = extract(tk, pages, cache_dir, model)
        ev = verify(raw, pages)
        res[tk] = {"evidence": ev, "overlay": overlay(ev)}
    return res


if __name__ == "__main__":
    import sys

    r = run_all(Path(sys.argv[1]), Path(sys.argv[2]))
    for tk, v in r.items():
        e = v["evidence"]
        print(f"\n== {tk} | analyst: {e['analyst_view'].get('rating')} TP {e['analyst_view'].get('target_price')} | audit {e['audit']}")
        for k, p in e["principles"].items():
            print(f"  {k:18} {p['assessment']:12} " + " | ".join(f"{c['statement'][:70]} (p{c['page']})" for c in p["claims"][:2]))
        for f in e["red_flags"]:
            print(f"  FLAG {f['category']}/{f['severity']}: {f['statement'][:90]} (p{f['page']})")
        print("  OVERLAY:", v["overlay"])
