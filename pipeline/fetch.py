"""Refresh public commodity data; preserve validated caches on source failures."""
from __future__ import annotations

import datetime as dt
import io
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from sources import SOURCES, atomic_json, read_status, source_url

DATA = Path(__file__).resolve().parent.parent / "data"
HEADERS = {"User-Agent": "CommodityMarketMonitor/2.0 (github.com/liamstutz/commodity-market-monitor)"}


def download(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=30) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def fetch_eia(key: str) -> pd.DataFrame:
    raw = download(source_url(key))
    frame = pd.read_excel(io.BytesIO(raw), sheet_name="Data 1", skiprows=2).iloc[:, :2]
    frame.columns = ["date", "value"]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna().loc[lambda x: x.date >= "2015-01-01"]


def fetch_cftc() -> pd.DataFrame:
    query = urlencode({"cftc_contract_market_code": "067651", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 1000})
    raw = pd.read_json(io.BytesIO(download(source_url("cot_wti") + "?" + query)), dtype=False)
    # Exact columns prevent selecting spread, percentage or change fields.
    numeric = lambda key: pd.to_numeric(raw[key], errors="coerce")
    dates = pd.to_datetime(raw["report_date_as_yyyy_mm_dd"], utc=True).dt.tz_localize(None)
    frame = pd.DataFrame({"date": dates,
                          "mm_net": numeric("m_money_positions_long_all") - numeric("m_money_positions_short_all")})
    if "prod_merc_positions_long" in raw and "prod_merc_positions_short" in raw:
        frame["producer_net"] = numeric("prod_merc_positions_long") - numeric("prod_merc_positions_short")
    if "open_interest_all" in raw:
        frame["open_interest"] = numeric("open_interest_all")
    return frame


def validate(name: str, frame: pd.DataFrame, previous: pd.DataFrame | None = None,
             now: dt.datetime | None = None) -> pd.DataFrame:
    now = now or dt.datetime.now(dt.timezone.utc)
    required = "mm_net" if name == "cot_wti" else "value"
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    out[required] = pd.to_numeric(out[required], errors="raise")
    if out.date.isna().any() or not np.isfinite(out[required]).all():
        raise ValueError("missing dates or non-finite values")
    if out.date.duplicated().any():
        raise ValueError("duplicate observation dates")
    if len(out) < 50:
        raise ValueError("fewer than 50 observations; refusing incomplete source")
    out = out.sort_values("date").reset_index(drop=True)
    if out.date.iloc[-1].date() > now.date():
        raise ValueError("future-dated observation")
    if name == "crude_stocks" and (out[required] <= 0).any():
        raise ValueError("non-positive inventory")
    if previous is not None and not previous.empty:
        previous_latest = pd.to_datetime(previous.date).max()
        if out.date.iloc[-1] < previous_latest or len(out) < len(previous) * 0.8:
            raise ValueError("source regressed or lost history; retaining cache")
    return out


def refresh(data: Path = DATA, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    data.mkdir(parents=True, exist_ok=True)
    status_path = data / "source_status.json"
    status = read_status(status_path)
    failures = 0
    for key in SOURCES:
        path = data / f"{key}.csv"
        state = {**status.get(key, {}), "last_attempt": now.isoformat()}
        try:
            previous = pd.read_csv(path) if path.exists() else None
            frame = fetch_cftc() if key == "cot_wti" else fetch_eia(key)
            frame = validate(key, frame, previous, now)
            frame["date"] = frame.date.dt.strftime("%Y-%m-%d")
            temporary = path.with_suffix(".csv.tmp")
            frame.to_csv(temporary, index=False)
            temporary.replace(path)
            state.update(status="ok", last_success=now.isoformat(), latest=frame.date.iloc[-1], rows=len(frame), error=None)
            print(f"OK {key}: {len(frame)} rows, latest {frame.date.iloc[-1]}")
        except Exception as exc:
            failures += 1
            state.update(status="error", error=f"{type(exc).__name__}: {exc}"[:240])
            print(f"FAIL {key}: {state['error']}; retained cache", file=sys.stderr)
        status[key] = state
    atomic_json(status_path, status)
    print(f"{len(SOURCES) - failures}/{len(SOURCES)} sources refreshed")
    return 1 if failures == len(SOURCES) else 0


if __name__ == "__main__":
    sys.exit(refresh())
