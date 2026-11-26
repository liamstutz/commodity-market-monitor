"""Source metadata and age checks shared by ingestion and the dashboard."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

SOURCES = {
    "wti": {"label": "WTI Cushing spot", "series": "RWTC", "frequency": "Daily", "max_age": 7},
    "brent": {"label": "Brent spot", "series": "RBRTE", "frequency": "Daily", "max_age": 7},
    "gasoline_nyh": {"label": "NY Harbor gasoline", "series": "EER_EPMRU_PF4_Y35NY_DPG", "frequency": "Daily", "max_age": 7},
    "ulsd_nyh": {"label": "NY Harbor diesel", "series": "EER_EPD2DXL0_PF4_Y35NY_DPG", "frequency": "Daily", "max_age": 7},
    "crude_stocks": {"label": "US commercial crude stocks", "series": "WCESTUS1", "frequency": "Weekly", "max_age": 14},
    "cot_wti": {"label": "WTI managed money", "frequency": "COT report", "max_age": 14},
}
DEPENDENCIES = {
    "wti": ["wti"], "brent": ["brent"], "wti_brent": ["wti", "brent"],
    "crack_321": ["wti", "gasoline_nyh", "ulsd_nyh"],
    "crude_stocks": ["crude_stocks"], "mm_net": ["cot_wti"],
}


def source_url(key: str) -> str:
    if key == "cot_wti":
        return "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
    spec = SOURCES[key]
    frequency = "w" if spec["frequency"] == "Weekly" else "d"
    return f"https://www.eia.gov/dnav/pet/hist_xls/{spec['series']}{frequency}.xls"


def read_status(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def health(key: str, latest: str | None, status: dict, now: dt.datetime) -> dict:
    spec = SOURCES[key]
    age = (now.date() - dt.date.fromisoformat(latest)).days if latest else None
    recorded = status.get(key, {})
    checked = recorded.get("last_attempt")
    state = "current"
    if latest is None:
        state = "missing"
    elif age < 0 or age > spec["max_age"]:
        state = "stale"
    elif recorded.get("status") == "error":
        state = "cached"
    elif not checked or (now - dt.datetime.fromisoformat(checked)).total_seconds() > 36 * 3600:
        state = "unverified"
    return {"key": key, "label": spec["label"], "provider": "CFTC" if key == "cot_wti" else "EIA",
            "frequency": spec["frequency"], "url": source_url(key), "latest": latest,
            "age_days": age, "max_age_days": spec["max_age"], "state": state,
            "last_attempt": checked, "last_success": recorded.get("last_success"),
            "error": recorded.get("error")}


def fetched_today(metric: str, status: dict, now: dt.datetime) -> bool:
    return all(status.get(k, {}).get("status") == "ok" and
               str(status[k].get("last_success", "")).startswith(now.date().isoformat())
               for k in DEPENDENCIES[metric])
