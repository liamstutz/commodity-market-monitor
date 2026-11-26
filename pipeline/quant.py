"""Deterministic spot-data research, with explicitly separate historical diagnostics."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

MODEL_VERSION = "spot-reversion-20-v2"
SIGNAL_KEYS = ("wti", "brent", "wti_brent", "crack_321")


def clean(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    s = pd.to_numeric(series, errors="coerce").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s[np.isfinite(s)]


def evaluate(series: pd.Series, now: dt.datetime | None = None, window: int = 20) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    s = clean(series)
    s = s[s.index.date <= now.date()]
    mean = s.rolling(window).mean()
    sd = s.rolling(window).std()
    z = (s - mean) / sd.replace(0, np.nan)
    signal = pd.Series(np.select([z < -1, z > 1], [1, -1], default=0), index=s.index)
    # A two-observation lag is only a diagnostic assumption, not a reconstructed release time.
    direction = signal.shift(2)
    change = s.diff()
    valid = z.shift(2).notna() & change.notna() & direction.ne(0)
    scores = (direction * change)[valid]
    last_z = float(z.iloc[-1]) if len(s) and pd.notna(z.iloc[-1]) else None
    age = (now.date() - s.index[-1].date()).days if len(s) else None
    state = "insufficient" if last_z is None else "stale" if age > 7 else "ready"
    current_signal = int(signal.iloc[-1]) if state == "ready" else None
    if state == "insufficient":
        reason = "At least 20 valid observations with non-zero variation are required."
    elif state == "stale":
        reason = f"The latest observation is {age} days old. New forecasts are paused."
    elif current_signal == 0:
        reason = f"The latest value is {abs(last_z):.2f} standard deviations from its 20-observation mean; no directional forecast."
    else:
        side = "below" if current_signal == 1 else "above"
        reason = f"The latest value is {abs(last_z):.2f} standard deviations {side} its 20-observation mean. The rule expects a move toward that mean."
    return {
        "date": s.index[-1].strftime("%Y-%m-%d") if len(s) else None,
        "value": float(s.iloc[-1]) if len(s) else None,
        "mean": float(mean.iloc[-1]) if len(s) and pd.notna(mean.iloc[-1]) else None,
        "z": last_z, "signal": current_signal, "state": state, "reason": reason,
        "version": MODEL_VERSION, "observations": len(scores),
        "directional_accuracy": float((scores > 0).mean()) if len(scores) else None,
        "up_baseline_accuracy": float((change[valid] > 0).mean()) if len(scores) else None,
        "flat_outcomes": int((scores == 0).sum()),
        "method": "20-observation mean reversion; +/-1 standard deviation threshold; two-observation lag.",
        "limitation": "Historical directional diagnostic on revised spot observations, not a trading backtest. Flat moves count as misses. Publication timing, costs, contract rolls and executable prices are not reconstructed. This one-observation test uses a different horizon from the seven-day forward record.",
    }


def opening_ema(bars: pd.DataFrame, session: str = "09:30") -> list[dict]:
    """Experimental 12-EMA rule for a configurable New York session anchor.

    Requires timezone-aware five-minute bar START times and open/close prices.
    An entry candidate uses the next bar's open after the anchor bar completes.
    This function does not simulate fills, exits, fees or realized returns.
    """
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("timezone-aware timestamps required")
    dt.time.fromisoformat(session)
    b = bars.sort_index().tz_convert("America/New_York")
    if b.index.has_duplicates:
        raise ValueError("duplicate timestamps")
    if any(t.minute % 5 or t.second or t.microsecond or t.nanosecond for t in b.index):
        raise ValueError("timestamps must align to five-minute bar starts")
    if not np.isfinite(b[["open", "close"]].to_numpy(dtype=float)).all():
        raise ValueError("finite open and close prices required")
    ema = b.close.ewm(span=12, adjust=False, min_periods=12).mean()
    candidates = []
    for i, timestamp in enumerate(b.index[:-1]):
        if timestamp.strftime("%H:%M") != session or pd.isna(ema.iloc[i]):
            continue
        if b.index[i + 1] - timestamp != pd.Timedelta(minutes=5):
            continue
        # A gap during the warmup makes the five-minute EMA ambiguous.
        warmup = b.index[max(0, i - 11):i + 1]
        if len(warmup) < 12 or any(warmup[1:] - warmup[:-1] != pd.Timedelta(minutes=5)):
            continue
        direction = int(b.close.iloc[i] > ema.iloc[i]) - int(b.close.iloc[i] < ema.iloc[i])
        if direction:
            candidates.append({"signal_time": (timestamp + pd.Timedelta(minutes=5)).isoformat(),
                               "entry_time": b.index[i + 1].isoformat(), "direction": direction,
                               "entry_open": float(b.open.iloc[i + 1])})
    return candidates


def research(metrics: dict, now: dt.datetime | None = None) -> dict:
    return {
        "version": MODEL_VERSION,
        "signals": {key: evaluate(metrics[key], now) for key in SIGNAL_KEYS},
        "intraday": {
            "status": "unavailable",
            "reason": "Five-minute commodity contract data is not connected. No intraday signals or performance are being generated.",
            "rule": "Experimental 12-period EMA on five-minute bars; configurable 09:30 America/New_York anchor, then next-bar open. This anchor is not a universal commodity exchange open.",
        },
    }
