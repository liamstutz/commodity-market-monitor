"""Pull free public energy-market data and cache it as CSV in data/.

Sources (no API keys needed):
  - EIA spot prices & weekly inventories (historical .xls downloads)
  - CFTC Commitments of Traders, disaggregated futures-only (Socrata API)

Each source is fetched independently. If one fails, the previous cached CSV is
kept so the site still builds -- a single outage never breaks the dashboard.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)
HEADERS = {"User-Agent": "commodity-market-monitor (github.com; educational project)"}

# EIA series -> (cache name, description)
EIA_SERIES = {
    "RWTC": "wti",                              # WTI Cushing spot, $/bbl, daily
    "RBRTE": "brent",                           # Brent spot, $/bbl, daily
    "EER_EPMRU_PF4_Y35NY_DPG": "gasoline_nyh",  # NYH conventional gasoline, $/gal, daily
    "EER_EPD2DXL0_PF4_Y35NY_DPG": "ulsd_nyh",   # NYH ultra-low-sulfur diesel, $/gal, daily
    "WCESTUS1": "crude_stocks",                 # US commercial crude stocks ex-SPR, kbbl, weekly
}

CFTC_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
WTI_CFTC_CODE = "067651"  # NYMEX light sweet crude oil


def fetch_eia(series: str) -> pd.DataFrame:
    freq = "w" if series.startswith("W") else "d"
    url = f"https://www.eia.gov/dnav/pet/hist_xls/{series}{freq}.xls"
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), sheet_name="Data 1", skiprows=2)
    df = df.iloc[:, :2]
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna().sort_values("date")
    if len(df) < 50:
        raise ValueError(f"{series}: only {len(df)} rows parsed, format may have changed")
    return df[df["date"] >= "2015-01-01"]


def _pick(cols, *needles, exclude=()):
    for c in cols:
        if all(n in c for n in needles) and not any(x in c for x in exclude):
            return c
    raise KeyError(f"no column matching {needles}")


def fetch_cftc() -> pd.DataFrame:
    params = {
        "cftc_contract_market_code": WTI_CFTC_CODE,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": 600,
    }
    r = requests.get(CFTC_URL, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    raw = pd.DataFrame(r.json())
    if raw.empty:
        raise ValueError("CFTC returned no rows")
    cols = list(raw.columns)
    # Column names are matched loosely so small schema tweaks don't break us.
    skip = ("pct", "change", "traders", "old", "other", "spread")
    mm_long = _pick(cols, "m_money", "long", exclude=skip)
    mm_short = _pick(cols, "m_money", "short", exclude=skip)
    num = lambda c: pd.to_numeric(raw[c], errors="coerce")
    date = pd.to_datetime(raw["report_date_as_yyyy_mm_dd"])
    if date.dt.tz is not None:
        date = date.dt.tz_localize(None)
    df = pd.DataFrame({"date": date, "mm_net": num(mm_long) - num(mm_short)})
    # Optional extras: keep them if the columns exist, never fail on them.
    for name, needles in {"producer_net": "prod_merc", "open_interest": None}.items():
        try:
            if needles:
                df[name] = num(_pick(cols, needles, "long", exclude=skip)) - num(_pick(cols, needles, "short", exclude=skip))
            else:
                df[name] = num(_pick(cols, "open_interest", exclude=skip))
        except KeyError:
            pass
    return df.dropna(subset=["mm_net"]).sort_values("date")


def save(name: str, df: pd.DataFrame) -> None:
    out = df.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(DATA / f"{name}.csv", index=False)
    print(f"  ok  {name:14s} {len(out):5d} rows, latest {out['date'].iloc[-1]}")


def main() -> int:
    failures = []
    for series, name in EIA_SERIES.items():
        try:
            save(name, fetch_eia(series))
        except Exception as e:  # keep going; old cache stays in place
            failures.append(name)
            print(f"  FAIL {name}: {e}", file=sys.stderr)
    try:
        save("cot_wti", fetch_cftc())
    except Exception as e:
        failures.append("cot_wti")
        print(f"  FAIL cot_wti: {e}", file=sys.stderr)

    total = len(EIA_SERIES) + 1
    print(f"{total - len(failures)}/{total} sources updated")
    # Fail the job only if everything failed (likely a real problem, not a blip).
    return 1 if len(failures) == total else 0


if __name__ == "__main__":
    sys.exit(main())
