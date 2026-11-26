"""Build the automated commodity dashboard; previews never issue forecasts."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd

from ledger import update_ledger
from metrics import METRICS, _load, load_metrics
from quant import research
from sources import DEPENDENCIES, SOURCES, health, read_status

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"
CHART_YEARS = 3


def series_json(series: pd.Series, years: int = CHART_YEARS, dp: int = 3) -> list:
    if series.empty:
        return []
    series = series[series.index >= series.index[-1] - pd.DateOffset(years=years)]
    return [[date.strftime("%Y-%m-%d"), round(float(value), dp)] for date, value in series.items()]


def kpi(name: str, series: pd.Series, now: dt.datetime) -> dict:
    label, unit, dp = METRICS[name]
    result = {"key": name, "label": label, "unit": unit, "dp": dp, "value": None}
    if series.empty:
        return {**result, "state": "missing"}
    last_date = series.index[-1]
    prior = series[series.index <= last_date - pd.Timedelta(days=7)]
    change = float(series.iloc[-1] - prior.iloc[-1]) if not prior.empty else None
    window = series[series.index >= last_date - pd.DateOffset(years=1)]
    percentile = float((window < series.iloc[-1]).mean() * 100) if len(window) > 10 else None
    age = (now.date() - last_date.date()).days
    age_limit = min(SOURCES[source]["max_age"] for source in DEPENDENCIES[name])
    return {**result, "value": round(float(series.iloc[-1]), dp), "date": last_date.strftime("%Y-%m-%d"),
            "chg_1w": round(change, dp) if change is not None else None,
            "pctile_1y": round(percentile) if percentile is not None else None,
            "age_days": age, "state": "stale" if age < 0 or age > age_limit else "current"}


def stocks_seasonal(series: pd.Series) -> dict:
    if series.empty:
        return {}
    frame = series.to_frame("value")
    iso = frame.index.isocalendar()
    frame["year"], frame["week"] = iso.year, iso.week.clip(upper=52)
    year = int(frame.year.iloc[-1])
    history = frame[(frame.year >= year - 5) & (frame.year < year)]
    band = history.groupby("week").value.agg(["min", "max", "mean"]).round(1)
    current = frame[frame.year == year].groupby("week").value.last().round(1)
    return {"year": year, "weeks": [int(week) for week in band.index],
            "min": band["min"].tolist(), "max": band["max"].tolist(), "avg": band["mean"].tolist(),
            "current": [float(current.loc[week]) if week in current else None for week in band.index]}


def market_brief(metrics: dict, signals: dict) -> list[dict]:
    brief = []
    for key in ("wti_brent", "crack_321", "crude_stocks", "mm_net"):
        series = metrics[key]
        if series.empty:
            continue
        label, unit, decimals = METRICS[key]
        latest = series.index[-1]
        previous = series[series.index <= latest - pd.Timedelta(days=7)]
        if previous.empty:
            continue
        change = float(series.iloc[-1] - previous.iloc[-1])
        action = "rose" if change > 0 else "fell" if change < 0 else "was unchanged"
        text = f"{label} {action} {abs(change):,.{decimals}f} {unit} versus the last observation at least seven days earlier."
        if key in signals:
            text += " " + signals[key]["reason"]
        elif key == "crude_stocks":
            text += " This is the reported stock change, not a surprise versus a consensus estimate."
        elif key == "mm_net":
            text += " Net length is managed-money long contracts minus short contracts."
        brief.append({"key": key, "label": label, "date": latest.strftime("%Y-%m-%d"), "text": text})
    return brief


def build(record: bool = False, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    metrics = load_metrics()
    # Avoid consuming future-dated rows even if a manually replaced cache is malformed.
    metrics = {key: value[value.index.date <= now.date()] for key, value in metrics.items()}
    status = read_status(ROOT / "data" / "source_status.json")
    sources = []
    for key in SOURCES:
        series = _load(key, "mm_net" if key == "cot_wti" else "value")
        latest = series.index[-1].strftime("%Y-%m-%d") if len(series) else None
        sources.append(health(key, latest, status, now))
    analysis = research(metrics, now)
    forward = update_ledger(analysis, metrics, ROOT / "data" / "forecast_ledger.json", status, record, now)
    payload = {
        "schema_version": 2, "generated": now.isoformat(),
        "kpis": [kpi(key, metrics[key], now) for key in METRICS],
        "series": {key: series_json(metrics[key], dp=METRICS[key][2] + 1) for key in METRICS},
        "stocks_seasonal": stocks_seasonal(metrics["crude_stocks"]),
        "research": analysis, "forward": forward, "sources": sources,
        "brief": market_brief(metrics, analysis["signals"]),
    }
    serialized = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    # Every asset URL belongs to this exact build, including the stylesheet.
    version = hashlib.sha256(serialized.encode("utf-8") + b"".join(
        path.read_bytes() for path in sorted((ROOT / "site").glob("*")) if path.is_file()
    )).hexdigest()[:16]
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(ROOT / "site", SITE)
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for asset in ("app.js", "app2.js", "style.css"):
        html = html.replace(f'"{asset}"', f'"{asset}?v={version}"')
    (SITE / "index.html").write_text(html, encoding="utf-8")
    script = (SITE / "app.js").read_text(encoding="utf-8").replace('"data.json"', f'"data.json?v={version}"')
    (SITE / "app.js").write_text(script, encoding="utf-8")
    (SITE / "data.json").write_text(serialized, encoding="utf-8")
    print(f"Built dashboard: {len(sources)} sources; {forward['issued']} issued forecasts; record={record}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true", help="Issue/resolve forecasts after successful same-day source fetches")
    build(record=parser.parse_args().record)
