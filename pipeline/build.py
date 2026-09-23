"""Build the static dashboard into _site/ (served by GitHub Pages)."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import markdown
import pandas as pd

from grade import grade_all
from metrics import METRICS, load_metrics

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"
CHART_YEARS = 3


def series_json(s: pd.Series, years: int = CHART_YEARS, dp: int = 2) -> list:
    if s.empty:
        return []
    s = s[s.index >= s.index[-1] - pd.DateOffset(years=years)]
    return [[d.strftime("%Y-%m-%d"), round(float(v), dp)] for d, v in s.items()]


def kpi(name: str, s: pd.Series) -> dict:
    label, unit, dp = METRICS[name]
    if s.empty:
        return {"key": name, "label": label, "unit": unit, "value": None}
    last_date = s.index[-1]
    prior = s[s.index <= last_date - pd.Timedelta(days=7)]
    chg = float(s.iloc[-1] - prior.iloc[-1]) if not prior.empty else None
    window = s[s.index >= last_date - pd.DateOffset(years=1)]
    pct = float((window < s.iloc[-1]).mean() * 100) if len(window) > 10 else None
    return {
        "key": name, "label": label, "unit": unit, "dp": dp,
        "value": round(float(s.iloc[-1]), dp), "date": last_date.strftime("%Y-%m-%d"),
        "chg_1w": None if chg is None else round(chg, dp),
        "pctile_1y": None if pct is None else round(pct),
    }


def stocks_seasonal(s: pd.Series) -> dict:
    """Current year vs prior-5-year min/max/avg by week of year."""
    if s.empty:
        return {}
    df = s.to_frame("v")
    df["year"], df["week"] = df.index.isocalendar().year, df.index.isocalendar().week.clip(upper=52)
    this_year = int(df["year"].iloc[-1])
    hist = df[(df["year"] >= this_year - 5) & (df["year"] < this_year)]
    band = hist.groupby("week")["v"].agg(["min", "max", "mean"]).round(1)
    cur = df[df["year"] == this_year].groupby("week")["v"].last().round(1)
    return {
        "year": this_year,
        "weeks": [int(w) for w in band.index],
        "min": band["min"].tolist(), "max": band["max"].tolist(), "avg": band["mean"].tolist(),
        "current": [cur.get(int(w)) for w in band.index],
    }


def load_notes() -> list[dict]:
    notes = []
    for p in sorted((ROOT / "notes").glob("*.md"), reverse=True):
        if p.name.startswith("_"):
            continue
        notes.append({"id": p.stem, "html": markdown.markdown(p.read_text(), extensions=["tables"])})
    return notes[:12]


def main() -> None:
    m = load_metrics()
    calls = grade_all(m)
    decided = [c for c in calls if c["status"] in ("hit", "miss")]
    hits = sum(c["status"] == "hit" for c in decided)
    payload = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "kpis": [kpi(k, m[k]) for k in METRICS],
        "series": {k: series_json(m[k], dp=METRICS[k][2] + 1) for k in METRICS},
        "stocks_seasonal": stocks_seasonal(m["crude_stocks"]),
        "calls": calls,
        "record": {
            "hits": hits, "decided": len(decided),
            "pending": sum(c["status"] == "pending" for c in calls),
            "hit_rate": round(100 * hits / len(decided)) if decided else None,
        },
        "notes": load_notes(),
    }
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(ROOT / "site", SITE)
    (SITE / "data.json").write_text(json.dumps(payload, separators=(",", ":"), default=str))
    print(f"built _site/  calls={len(calls)} record={hits}/{len(decided)}")


if __name__ == "__main__":
    main()
