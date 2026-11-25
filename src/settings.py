"""One place for paths and secrets, shared by all notebooks and scripts.

Values come from environment variables, else from `<repo>/.env` (git-ignored; copy `.env.example`).
Defaults are relative to the repo, so notebooks work from VS Code / Jupyter without any shell setup.
"""
import os
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(REPO / ".env")

DATA = Path(os.environ.get("WISDOM_DATA", REPO / "data")).expanduser()
XLSX = Path(os.environ.get("WISDOM_XLSX", REPO.parent / "1 Historical Trade Data.xlsx")).expanduser()
XLSX_PASSWORD = os.environ.get("WISDOM_XLSX_PASSWORD")
PDF_DIR = Path(os.environ.get("WISDOM_PDF_DIR", REPO.parent)).expanduser()
ASOF_STEP1 = pd.Timestamp(os.environ.get("WISDOM_ASOF", "2026-01-14"))   # Step-1 analysis date (pinned)

DATA.mkdir(parents=True, exist_ok=True)
(DATA / "figures").mkdir(exist_ok=True)
