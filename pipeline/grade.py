"""Grade the market calls in calls/*.yml against real data.

Integrity rule: a call counts from the LATER of its `made` date and the date it
was first committed to git. You cannot backdate a call by editing `made` --
the commit history is the timestamp.

Scoring: start = last observation strictly BEFORE the effective date (what was
known when you made the call); end = first observation ON or AFTER resolve_on.
A call is a hit if the metric moved in the stated direction by at least min_move.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pandas as pd
import yaml

from metrics import METRICS

ROOT = Path(__file__).resolve().parent.parent
CALLS = ROOT / "calls"


def first_commit_date(path: Path) -> dt.date | None:
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--follow", "--format=%cI", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip().splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return dt.datetime.fromisoformat(out[-1]).astimezone(dt.timezone.utc).date() if out else None


def _as_date(v) -> dt.date | None:
    if v is None:
        return None
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


def grade_call(path: Path, metrics: dict[str, pd.Series]) -> dict:
    spec = yaml.safe_load(path.read_text()) or {}
    res = {
        "id": path.stem,
        "metric": spec.get("metric"),
        "direction": str(spec.get("direction", "")).lower(),
        "thesis": str(spec.get("thesis", "")).strip(),
        "min_move": float(spec.get("min_move", 0) or 0),
        "status": "pending",
        "note": "",
    }
    committed = first_commit_date(path)
    made = _as_date(spec.get("made"))
    resolve_on = _as_date(spec.get("resolve_on"))

    if res["metric"] not in METRICS:
        return {**res, "status": "invalid", "note": f"unknown metric (use one of {', '.join(METRICS)})"}
    if res["direction"] not in ("up", "down"):
        return {**res, "status": "invalid", "note": "direction must be up or down"}
    if resolve_on is None:
        return {**res, "status": "invalid", "note": "resolve_on is required"}

    effective = max(d for d in (made, committed) if d) if (made or committed) else dt.date.today()
    if made and committed and committed > made:
        res["note"] = f"counted from commit date {committed} (made date {made} is earlier)"
    if resolve_on <= effective:
        return {**res, "made": str(effective), "resolve_on": str(resolve_on),
                "status": "invalid", "note": "resolve_on must be after the date the call was made"}

    res.update(made=str(effective), resolve_on=str(resolve_on))
    s = metrics[res["metric"]]
    before = s[s.index < pd.Timestamp(effective)]
    after = s[s.index >= pd.Timestamp(resolve_on)]
    if before.empty:
        return {**res, "status": "invalid", "note": "no data before call date"}
    res["start"] = round(float(before.iloc[-1]), 3)
    res["start_date"] = before.index[-1].strftime("%Y-%m-%d")
    if after.empty:
        return res  # still pending
    end = float(after.iloc[0])
    move = end - res["start"]
    res.update(end=round(end, 3), end_date=after.index[0].strftime("%Y-%m-%d"), move=round(move, 3))
    signed = move if res["direction"] == "up" else -move
    res["status"] = "hit" if signed > 0 and abs(move) >= res["min_move"] else "miss"
    return res


def grade_all(metrics: dict[str, pd.Series]) -> list[dict]:
    files = sorted(p for p in CALLS.glob("*.y*ml") if not p.name.startswith("_"))
    results = []
    for p in files:
        try:
            results.append(grade_call(p, metrics))
        except Exception as e:  # one malformed file must never break the site
            results.append({"id": p.stem, "metric": None, "direction": "", "thesis": "",
                            "status": "invalid", "note": f"could not read call: {e}"})
    return sorted(results, key=lambda r: r.get("made", ""), reverse=True)


if __name__ == "__main__":
    from metrics import load_metrics
    for r in grade_all(load_metrics()):
        print(f"{r['status']:8s} {r['id']}  {r.get('note', '')}")
