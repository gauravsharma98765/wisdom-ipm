"""Parse WISDOM's FIFO-matched trade workbook into clean tables.

Layout per sheet: title row, 'Purchase | Sale' row, header row, then blocks of
lot rows (buy date/qty/rate/amt | sell date/qty/rate/amt) each closed by a
subtotal row (no dates, summed qty/amount). Blank rows separate blocks.

Outputs
  lots   : one row per FIFO-matched lot (sell side empty => still held)
  ledger : de-duplicated transaction tape (one row per date/side/rate)
  recon  : per-block check of lot sums vs the sheet's own subtotal rows
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import msoffcrypto
import openpyxl
import pandas as pd

SHEETS = {"Amber": "AMBER", "DBL": "DBL", "Zee": "ZEE", "Welspun": "WELSPUN"}


def decrypt(src: Path, dst: Path, password: str) -> Path:
    with open(src, "rb") as f:
        of = msoffcrypto.OfficeFile(f)
        of.load_key(password=password)
        with open(dst, "wb") as o:
            of.decrypt(o)
    return dst


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def parse_sheet(ws, ticker: str):
    lots, recon = [], []
    block, cur = 0, []
    for i, r in enumerate(ws.iter_rows(min_row=4, max_col=8, values_only=True), start=4):
        bd, bq, br, ba, sd, sq, sr, sa = r
        if isinstance(bd, dt.datetime):
            cur.append(dict(ticker=ticker, block=block, row=i,
                            buy_date=bd, buy_qty=_num(bq), buy_rate=_num(br), buy_amt=_num(ba),
                            sell_date=sd if isinstance(sd, dt.datetime) else None,
                            sell_qty=_num(sq), sell_rate=_num(sr), sell_amt=_num(sa)))
        elif cur and _num(bq) is not None:  # subtotal row closes the block
            b = pd.DataFrame(cur)
            recon.append(dict(ticker=ticker, block=block, subtotal_row=i, n_lots=len(b),
                              buy_qty_lots=b.buy_qty.sum(), buy_qty_sub=_num(bq),
                              buy_amt_lots=b.buy_amt.sum(), buy_amt_sub=_num(ba),
                              sell_qty_lots=b.sell_qty.sum(min_count=1), sell_qty_sub=_num(sq),
                              sell_amt_lots=b.sell_amt.sum(min_count=1), sell_amt_sub=_num(sa)))
            lots += cur
            cur, block = [], block + 1
    if cur:  # trailing block with no subtotal
        recon.append(dict(ticker=ticker, block=block, subtotal_row=None, n_lots=len(cur)))
        lots += cur
    return lots, recon


def build(xlsx: Path):
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    lots, recon = [], []
    for sheet, tk in SHEETS.items():
        l, r = parse_sheet(wb[sheet], tk)
        lots += l
        recon += r
    lots = pd.DataFrame(lots)
    recon = pd.DataFrame(recon)
    for c in ["buy_date", "sell_date"]:
        lots[c] = pd.to_datetime(lots[c])
    lots["is_open"] = lots.sell_date.isna()
    lots["lot_id"] = lots.ticker + "-" + lots.row.astype(str)
    return lots, recon


def to_ledger(lots: pd.DataFrame) -> pd.DataFrame:
    """Collapse lots into executions. FIFO splits one execution across many lots,
    so group by (ticker, side, date, rate) to recover the trade tape."""
    b = lots.rename(columns={"buy_date": "date", "buy_qty": "qty", "buy_rate": "rate", "buy_amt": "amt"})
    b = b.assign(side="BUY")[["ticker", "date", "side", "qty", "rate", "amt"]]
    s = lots[~lots.is_open].rename(columns={"sell_date": "date", "sell_qty": "qty", "sell_rate": "rate", "sell_amt": "amt"})
    s = s.assign(side="SELL")[["ticker", "date", "side", "qty", "rate", "amt"]]
    led = pd.concat([b, s])
    led = (led.groupby(["ticker", "date", "side"], as_index=False)
              .agg(qty=("qty", "sum"), amt=("amt", "sum"), n_fills=("qty", "size")))
    led["vwap"] = led.amt / led.qty
    led["signed_qty"] = led.qty.where(led.side == "BUY", -led.qty)
    led["cash_flow"] = -led.amt.where(led.side == "BUY", -led.amt)  # buy = outflow
    return led.sort_values(["ticker", "date", "side"]).reset_index(drop=True)


if __name__ == "__main__":
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    x = out / "trades.xlsx"
    if not x.exists():
        decrypt(src, x, sys.argv[3])
    lots, recon = build(x)
    lots.to_parquet(out / "lots.parquet")
    recon.to_csv(out / "recon.csv", index=False)
    to_ledger(lots).to_parquet(out / "ledger.parquet")
    print(lots.groupby("ticker").size())
