"""Forward-only forecast journal. First-issued forecasts and first-observed outcomes are frozen."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from quant import MODEL_VERSION, clean
from sources import atomic_json, fetched_today


def update_ledger(research: dict, metrics: dict, path: Path, sources: dict,
                  record: bool = False, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    changed = False
    if record:
        for entry in entries:
            if entry["status"] != "pending" or not fetched_today(entry["metric"], sources, now):
                continue
            series = clean(metrics[entry["metric"]])
            due = dt.date.fromisoformat(entry["due_on"])
            outcomes = series[(series.index.date >= due) & (series.index.date <= now.date())]
            if outcomes.empty:
                continue
            end_date = outcomes.index[0].date()
            # Do not silently score across a long missing-data interval.
            if (end_date - due).days > 7:
                entry.update(status="unscored", observed_at=now.isoformat(),
                             outcome_note="No observation within seven calendar days of the target.")
            else:
                end_value = float(outcomes.iloc[0])
                move = end_value - entry["start_value"]
                entry.update(status="resolved", observed_at=now.isoformat(), end_date=end_date.isoformat(),
                             end_value=end_value, move=move, hit=bool(entry["direction"] * move > 0))
            changed = True
        for key, signal in research["signals"].items():
            if signal["state"] != "ready" or signal["signal"] not in (-1, 1) or not fetched_today(key, sources, now):
                continue
            identity = f"{MODEL_VERSION}:{key}:{signal['date']}"
            if any(entry["id"] == identity for entry in entries):
                continue
            # Target starts from the actual issue date, never from a delayed source observation date.
            entries.append({
                "id": identity, "version": MODEL_VERSION, "metric": key, "issued_at": now.isoformat(),
                "as_of": signal["date"], "due_on": (now.date() + dt.timedelta(days=7)).isoformat(),
                "direction": signal["signal"], "start_value": signal["value"], "mean": signal["mean"],
                "z": signal["z"], "reason": signal["reason"], "status": "pending",
                "sources_fetched_at": {name: value.get("last_success") for name, value in sources.items()},
            })
            changed = True
        if changed:
            atomic_json(path, entries)
    resolved = [entry for entry in entries if entry["status"] == "resolved"]
    hits = sum(entry["hit"] for entry in resolved)
    return {
        "entries": sorted(entries, key=lambda entry: entry["issued_at"], reverse=True),
        "issued": len(entries), "resolved": len(resolved), "hits": hits,
        "pending": sum(entry["status"] == "pending" for entry in entries),
        "unscored": sum(entry["status"] == "unscored" for entry in entries),
        "hit_rate": hits / len(resolved) if resolved else None,
        "method": "Only forecasts issued during successful refreshes enter this record. Each resolves at the first spot observation on or after seven calendar days from issue; a gap over seven additional days is unscored. The baseline is the spot value known at issue. Flat moves count as misses. First-issued values and first-observed outcomes are preserved.",
        "limitation": "Directional research results, not tradable P&L. The baseline can predate issue because sources publish with a delay. Forecasts overlap and are correlated, so hit rate alone does not establish an edge. No historical simulation is included in this record.",
    }
