"""Turn cached raw series into the market metrics the dashboard and grader use."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data"

# name -> (label, unit, decimals)
METRICS = {
    "wti": ("WTI crude (Cushing spot)", "$/bbl", 2),
    "brent": ("Brent crude (spot)", "$/bbl", 2),
    "wti_brent": ("WTI – Brent spread", "$/bbl", 2),
    "crack_321": ("3-2-1 crack spread (NY Harbor)", "$/bbl", 2),
    "crude_stocks": ("US commercial crude stocks", "million bbl", 1),
    "mm_net": ("Managed money net long, WTI", "contracts", 0),
}


def _load(name: str, col: str = "value") -> pd.Series:
    path = DATA / f"{name}.csv"
    if not path.exists():
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    df = pd.read_csv(path, parse_dates=["date"])
    s = pd.to_numeric(df.set_index("date")[col], errors="coerce").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s[np.isfinite(s)]


def load_metrics() -> dict[str, pd.Series]:
    wti, brent = _load("wti"), _load("brent")
    gas, ulsd = _load("gasoline_nyh"), _load("ulsd_nyh")
    out = {
        "wti": wti,
        "brent": brent,
        "wti_brent": (wti - brent).dropna(),
        # 3 bbl crude -> 2 bbl gasoline + 1 bbl diesel, per barrel of crude.
        # Product prices are $/gal; 42 gal per barrel.
        "crack_321": ((2 * gas * 42 + ulsd * 42 - 3 * wti) / 3).dropna(),
        "crude_stocks": _load("crude_stocks") / 1000.0,
        "mm_net": _load("cot_wti", "mm_net"),
    }
    return {k: v.dropna() for k, v in out.items()}
