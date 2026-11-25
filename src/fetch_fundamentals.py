"""Fetch annual fundamentals from Screener.in public pages (consolidated, fallback standalone).

Usage: python fetch_fundamentals.py <out_dir>
Writes <TICKER>_{pl,bs,cf,ratios,sh,q,top}.csv for each stock.
"""
import io
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

CODES = {"AMBER": "AMBER", "DBL": "DBL", "ZEE": "ZEEL", "WELSPUN": "WELSPUNLIV"}
HEADERS = {"User-Agent": "Mozilla/5.0"}
SECTIONS = {"profit-loss": "pl", "balance-sheet": "bs", "cash-flow": "cf",
            "ratios": "ratios", "shareholding": "sh", "quarters": "q"}


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for k, code in CODES.items():
        for view in ("consolidated", ""):
            url = f"https://www.screener.in/company/{code}/{view + '/' if view else ''}"
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and 'id="profit-loss"' in r.text:
                break
        soup = BeautifulSoup(r.text, "html.parser")
        print(k, url, r.status_code)
        for sec, tag in SECTIONS.items():
            s = soup.find("section", id=sec)
            t = s.find("table", class_="data-table") if s else None
            if t is None:
                print("  missing", sec)
                continue
            df = pd.read_html(io.StringIO(str(t)))[0]
            df = df.rename(columns={df.columns[0]: "metric"})
            df["metric"] = df.metric.astype(str).str.replace(r"\s*\+$", "", regex=True).str.strip()
            df.to_csv(out / f"{k}_{tag}.csv", index=False)
            print(f"  {tag}: {df.shape}")
        top = {li.find("span", class_="name").get_text(strip=True): li.find("span", class_="number").get_text(strip=True)
               for li in soup.select("#top-ratios li")
               if li.find("span", class_="name") and li.find("span", class_="number")}
        pd.Series(top).to_csv(out / f"{k}_top.csv")
        time.sleep(2)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
