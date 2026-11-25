# WISDOM Intelligent Portfolio Manager (prototype)

This is ENAM's AI engineer assessment. It does three things:
- analyses 10 years of WISDOM's trades in Amber, DBL, Welspun and Zee;
- builds a rules-first portfolio manager based on WISDOM's investment principles;
- adds an LLM research layer whose every claim is checked against the source report.

**Start with [`docs/WRITEUP.md`](docs/WRITEUP.md)**, which covers findings, design, assumptions and architecture.

## Repository layout
```
src/
  ingest.py              decrypt + parse the FIFO trade workbook, reconcile to its subtotals
  prices.py              daily prices (Yahoo Finance) for the stocks and indices
  fetch_fundamentals.py  annual financials and shareholding from Screener.in
  fundamentals.py        point-in-time fundamentals (only what was public on each date)
  eda.py                 performance, timing, sizing, holding and disposition metrics
  ipm/
    config.py            every threshold, each tied to a principle
    scoring.py           quality score, avoid-list gates, expected CAGR vs 25% hurdle (v1/v2)
    engine.py            BUY/ADD/HOLD/TRIM/EXIT with reasons and behavioural guardrails
    backtest.py          quarterly walk-forward backtest; with_thresholds() for sensitivity runs
    research.py          Claude extraction, quote verification, overlay rules
    explain.py           plain-English explanation of each decision, with a number check
    recommend.py         today's recommendation for the current book
notebooks/
  01_trade_eda_and_scorecard.ipynb          Step 1: EDA, charts, investor scorecard (as of 14 Jan 2026)
  02_portfolio_manager_v1_v2.ipynb          Step 2: backtest, v1 vs v2, exit-multiple sweep
  03_research_overlay_and_recommendation.ipynb  Step 2: research evidence and today's call
docs/
  WRITEUP.md, VIDEO_SCRIPT.md
```

## Running it
Requirements:
- Python 3.11+
- `pdftotext` (poppler)
- the [Claude Code](https://claude.com/claude-code) CLI, logged in, for notebook 03 only. Cached results are reused, so re-runs make no LLM calls.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ipykernel install --user --name wisdom-ipm --display-name "WISDOM IPM (.venv)"

cp .env.example .env        # fill in the Excel path, password and PDF folder (.env is git-ignored)
```

Open the notebooks in VS Code or Jupyter and choose the **WISDOM IPM (.venv)** kernel. Run them in order (01, then 02, then 03): 01 writes the trade ledger that 03 needs.

`src/settings.py` reads `.env`, so you don't need to set environment variables in a shell. On the first run the notebooks download prices and fundamentals. Every intermediate file goes to `<repo>/data/`, which is git-ignored. Notebook 02 takes several minutes because it runs about 10 backtests.

## Data handling
- No WISDOM data is in this repo. `.gitignore` blocks `.xlsx`, `.parquet` and price CSVs, and notebooks are committed without outputs.
- The trade ledger is never sent to the LLM; only broker research text is.
- All data downloaded for the assessment is to be deleted after review.
