import nbformat as nbf
nb = nbf.v4.new_notebook(); C=[]
md = lambda s: C.append(nbf.v4.new_markdown_cell(s.strip("\n")))
code = lambda s: C.append(nbf.v4.new_code_cell(s.strip("\n")))
md("""
# WISDOM Intelligent Portfolio Manager — research overlay & today's recommendation

**What this notebook does**
1. Sends each broker report (text only) to Claude and asks for **evidence per WISDOM principle** and **red flags**. Each claim must cite a page and quote the report verbatim.
2. **Verifies every quote in code** against the cited page and drops claims that fail. This is the hallucination guard.
3. Applies **fixed rules** (not the LLM) to turn verified flags into a *buy veto* or a *human-review* flag.
4. Combines this with the quant engine (v2) on WISDOM's **current book** to produce today's recommendation for human approval.

**LLM backend:** the local `claude` CLI in headless mode (your Claude login; tools and MCP disabled). Results are cached by a hash of the input, so re-running is free and reproducible. Delete `WISDOM_DATA/research_llm/` to force fresh calls.

**Privacy:** only third-party research text is sent. WISDOM's trade ledger stays local and is only used to compute current weights.

**Setup:** convert each research PDF with `pdftotext -layout` into `WISDOM_DATA/research/<Name>.pages.txt` (the first cell does this from the PDFs in `WISDOM_PDF_DIR`, set in `.env`). Run notebook 01 first..
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
import os, sys, json, subprocess, warnings
from pathlib import Path
import pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path("..", "src").resolve()))
from ipm import research as R
from ipm.recommend import recommend
pd.set_option("display.max_colwidth", 140)

import settings
DATA = settings.DATA; RES = DATA / "research"; RES.mkdir(parents=True, exist_ok=True)
PDF_DIR = settings.PDF_DIR
assert (DATA / "ledger.parquet").exists(), "Run notebook 01 first (it writes ledger.parquet)"
for name in ["Amber", "DBL", "Welspun", "Zee"]:
    out = RES / f"{name}.pages.txt"
    if out.exists(): continue
    pdf = next(PDF_DIR.glob(f"*Research ({name}).pdf"))
    txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
    out.write_text("".join(f"=== PAGE {i} ===\\n{p}\\n" for i, p in enumerate(txt.split("\\f")[:-1] or [txt], 1)))
print({p.name: len(R.load_pages(p)) for p in sorted(RES.glob("*.pages.txt"))}, "pages")
""")
md("## 1. Extract → verify → overlay")
code("""
research = R.run_all(RES, DATA / "research_llm")
audit = pd.DataFrame({t: {**v["evidence"]["audit"], "analyst_rating": v["evidence"]["analyst_view"].get("rating"),
                          "analyst_target": v["evidence"]["analyst_view"].get("target_price"),
                          "buy_veto": bool(v["overlay"]["veto_buy"]), "human_review": v["overlay"]["review"]}
                      for t, v in research.items()}).T
display(audit)
""")
md("""
### Evidence by principle

Read across a row to see how each business stacks up against one principle. `not_covered` means the report says nothing usable. That is common: these are quarterly result notes, not initiation reports.
""")
code("""
grid = pd.DataFrame({t: {k: p["assessment"] for k, p in v["evidence"]["principles"].items()} for t, v in research.items()})
colour = {"positive": "background-color:#cde2fb", "negative": "background-color:#f6c9c8", "neutral": "", "not_covered": "color:#a8a7a1"}
display(grid.style.map(lambda x: colour.get(x, "")))
""")
code("""
# Every claim with its citation, so a PM can click through to the page.
rows = [dict(ticker=t, principle=k, assessment=p["assessment"], statement=c["statement"], page=c["page"], quote=c["quote"])
        for t, v in research.items() for k, p in v["evidence"]["principles"].items() for c in p["claims"]]
display(pd.DataFrame(rows))
""")
md("### Red flags (verified) and what the overlay did with them")
code("""
flags = pd.DataFrame([dict(ticker=t, **f) for t, v in research.items() for f in v["evidence"]["red_flags"]])
display(flags[["ticker", "category", "severity", "statement", "page", "quote"]])
for t, v in research.items():
    print(f"{t:8} veto_buy = {v['overlay']['veto_buy'] or '-'}")
""")
md("""
### Hallucination guard: what got dropped

Claims whose quote could not be found on the cited page never reach the engine.
""")
code("""
dropped = [dict(ticker=t, **d) for t, v in research.items() for d in v["evidence"]["dropped"]]
display(pd.DataFrame(dropped) if dropped else "nothing dropped")
""")
md("""
## 2. Today's recommendation for WISDOM's current book

The quant engine (v2 valuation, quality, avoid-list gates, guardrails) runs on the latest fundamentals and prices. The verified research overlay can only **block new buying** or **request review**; it cannot force a sale.
""")
code("""
led = pd.read_parquet(DATA / "ledger.parquet")   # produced by notebook 01 / src/ingest.py
asof, rec, _ = recommend(DATA, led)
print("As of", asof.date())
display(rec[["ticker", "current_weight", "action", "target_weight", "quality", "exp_3y_cagr", "price", "target_price", "analyst"]]
        .style.format({"current_weight": "{:.0%}", "target_weight": "{:.0%}", "quality": "{:.0f}", "exp_3y_cagr": "{:+.0%}",
                       "price": "{:,.0f}", "target_price": "{:,.0f}"}).hide(axis="index"))
for r in rec.itertuples():
    print(f"\\n{r.ticker}: {r.action}\\n  why:    {r.reason}\\n  gates:  {r.gates}\\n  veto:   {r.research_veto}\\n  review: {r.human_review}")
""")
md("""
## 3. Plain-English explanation of each decision

**The code decides, the AI only explains.** For each stock the engine's decision record (scores, failed checks, return test, verified research quotes) is turned into a short explanation by Claude.

* The record contains **stock-level facts only**: no portfolio weights or position sizes. That keeps WISDOM's holdings away from the AI.
* **Number check:** every number in the explanation must appear in the record. If one doesn't, the explanation is rejected and a deterministic template is shown instead (`source` column).
""")
code("""
from ipm import explain as X
expl = {}
for r in rec.itertuples():
    e = X.explain(r.decision, research.get(r.ticker), DATA / "research_llm")
    expl[r.ticker] = e
    print(f"\\n=== {r.ticker}: {r.action}   [{e['source']}]")
    print(e["summary"])
    for k in e["key_drivers"]:
        print("  -", k)
    print("What would change it:", e["what_would_change_it"])
    print("Counterpoint:        ", e["counterpoint"])
""")
code("""
# Proof the number check works: plant a made-up number and confirm it is caught.
fake = dict(expl["AMBER"]); fake["counterpoint"] = "Revenue could grow 47% and the stock could reach Rs 13,700."
print("numbers not in the record:", X.number_check(fake, expl["AMBER"]["record"]))
""")
md("""
## 4. How to read this (edit after re-running)

* **Nothing here is an order.** Every line is flagged for human review because each stock has at least one verified medium/high flag.
* **Amber → EXIT is the most contestable call.** The avoid-list rule "dependence on external capital" fires (3-yr FCF −₹326 cr while debt rose ~86% FY23–26). A PM could reasonably argue this is the *reinvestment runway* of Principle 3 (PCB capacity build-out). The engine surfaces the conflict between two principles; a human should resolve it.
* **Welspun: the research overlay disagrees with the broker.** JM rates it BUY, but the verified evidence shows the BUY case depends on EBITDA rebounding +80% after −39%. That is a turnaround, which the principles avoid. The severity label is an LLM judgement; caching makes it reproducible, not infallible.
* **Zee** fails two quant gates (turnaround, 4% promoter holding) independently of the research, and the broker (REDUCE) agrees.
* **DBL** is below the quality bar to keep but inside the 12-month minimum hold (bought Dec-2025), so the engine holds and flags it.
""")
nb["cells"]=C; nb["metadata"]={"kernelspec":{"name":"wisdom-ipm","display_name":"WISDOM IPM (.venv)","language":"python"}}
nbf.write(nb, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "notebooks" / "03_research_overlay_and_recommendation.ipynb")); print("ok",len(C))
