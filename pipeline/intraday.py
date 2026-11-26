"""Private five-minute commodity research. No orders, keys or paid APIs."""
from __future__ import annotations
import datetime as dt
import json
import math
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
NY = ZoneInfo("America/New_York")
VERSION = "opening-ema12-v1"
INSTRUMENTS = {
    "CL=F": {"name": "WTI crude", "tick": .01, "multiplier": 1000, "unit": "$/bbl", "dp": 2},
    "NG=F": {"name": "Natural gas", "tick": .001, "multiplier": 10000, "unit": "$/MMBtu", "dp": 3},
    "GC=F": {"name": "Gold", "tick": .1, "multiplier": 100, "unit": "$/oz", "dp": 1},
}
LIMITATION = ("Yahoo rolling futures quotes; historical contract mapping and quote delay are unverified. "
              "Indicative research, not exchange-quality execution data. Simulated entries use historical "
              "opens that may have been unavailable when the delayed feed arrived. No orders, leverage, "
              "margin or live trading returns are represented.")

def iso(timestamp):
    return dt.datetime.fromtimestamp(timestamp, UTC).isoformat()

def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)

def normalize(rows, now=None):
    """Reject malformed rows; discard incomplete candles and provider null placeholders."""
    now = now or dt.datetime.now(UTC)
    seen, valid, skipped = set(), [], 0
    for row in rows:
        if len(row) != 6:
            raise ValueError("Expected timestamp, open, high, low, close, volume")
        stamp, opening, high, low, close, volume = row
        if not finite(stamp) or stamp != int(stamp) or stamp % 300:
            raise ValueError("Bar starts must align to five UTC minutes")
        if stamp in seen:
            raise ValueError("Duplicate bar timestamp")
        seen.add(stamp)
        if stamp + 300 > now.timestamp() - 10:
            skipped += 1
            continue
        if any(v is None for v in row[1:]):
            skipped += 1
            continue
        if not all(finite(v) for v in row[1:]):
            raise ValueError("Non-finite OHLCV")
        if high < max(opening, close, low) or low > min(opening, close, high) or volume < 0:
            raise ValueError("Invalid OHLC range or volume")
        valid.append([int(stamp), *[float(v) for v in row[1:]]])
    return sorted(valid), skipped

def parse_yahoo(payload, symbol, now=None):
    if symbol not in INSTRUMENTS:
        raise ValueError("Unsupported commodity")
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result"):
        raise ValueError("Provider returned no chart")
    result = chart["result"][0]
    meta = result.get("meta", {})
    if (meta.get("symbol") != symbol or meta.get("instrumentType") != "FUTURE"
            or meta.get("dataGranularity") != "5m" or meta.get("currency") != "USD"):
        raise ValueError("Unexpected provider symbol, asset, interval or currency")
    stamps = result.get("timestamp", [])
    quotes = result.get("indicators", {}).get("quote", [{}])[0]
    fields = [quotes.get(key, []) for key in ("open", "high", "low", "close", "volume")]
    if not stamps or any(len(field) != len(stamps) for field in fields):
        raise ValueError("Empty or inconsistent provider arrays")
    if not all(finite(t) and t == int(t) for t in stamps):
        raise ValueError("Invalid provider timestamps")
    # A current, non-aligned quote sometimes follows the candles. It is not a closed candle.
    raw = [list(row) for row in zip(stamps, *fields) if row[0] % 300 == 0]
    bars, skipped = normalize(raw, now)
    if len(bars) < 12:
        raise ValueError("Fewer than twelve completed bars")
    return {"bars": bars, "provider_name": str(meta.get("shortName", symbol))[:100],
            "skipped": skipped + len(stamps) - len(raw), "delay_minutes": None}

def fetch_yahoo(symbol, initial=False, now=None):
    if symbol not in INSTRUMENTS:
        raise ValueError("Unsupported commodity")
    query = urllib.parse.urlencode({"interval": "5m", "range": "1mo" if initial else "5d"})
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol, safe="") + "?" + query
    request = urllib.request.Request(url, headers={"User-Agent": "commodity-market-monitor/1.0 (personal research)"})
    # One request per symbol per five minutes; errors wait until the next cycle.
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(8_000_001)
    if len(body) > 8_000_000:
        raise ValueError("Provider response too large")
    return parse_yahoo(json.loads(body), symbol, now)

def merge_bars(old, new):
    """Retain first-observed closed candles, bounded to approximately 100 sessions."""
    if old and new and new[-1][0] < old[-1][0]:
        raise ValueError("Provider end time regressed; retaining cache")
    merged = {row[0]: row for row in new}
    merged.update({row[0]: row for row in old})
    return [merged[key] for key in sorted(merged)[-30000:]]

def ema_points(bars):
    points, ema, count, previous, day = [], None, 0, None, None
    for row in bars:
        stamp, close = row[0], row[4]
        current_day = dt.datetime.fromtimestamp(stamp, NY).date()
        if previous is None or stamp - previous != 300 or current_day != day:
            ema, count = close, 1
        else:
            ema, count = 2 / 13 * close + 11 / 13 * ema, count + 1
        points.append([stamp, ema if count >= 12 else None])
        previous, day = stamp, current_day
    return points

def candidates(bars, anchor="09:30"):
    try:
        hour, minute = map(int, anchor.split(":"))
        dt.time(hour, minute)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Anchor must be HH:MM") from None
    if minute % 5:
        raise ValueError("Anchor must align to five minutes")
    signals = []
    for row, (_, ema) in zip(bars, ema_points(bars)):
        clock = dt.datetime.fromtimestamp(row[0], NY)
        if clock.hour != hour or clock.minute != minute or ema is None or clock.weekday() >= 5:
            continue
        direction = (row[4] > ema) - (row[4] < ema)
        if direction:
            signals.append({"date": clock.date().isoformat(), "signal_time": row[0] + 300,
                            "direction": direction, "ema": ema, "anchor_close": row[4]})
    return signals

def summary(trades):
    if not trades:
        return {"count": 0, "net": 0, "gross": 0, "costs": 0, "win_rate": None,
                "max_drawdown": 0, "long_baseline": 0}
    equity, peak, drawdown = 0, 0, 0
    for trade in trades:
        equity += trade["net"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {"count": len(trades), "net": round(equity, 2),
            "gross": round(sum(t["gross"] for t in trades), 2),
            "costs": round(sum(t["cost"] for t in trades), 2),
            "win_rate": sum(t["net"] > 0 for t in trades) / len(trades),
            "max_drawdown": round(drawdown, 2),
            "long_baseline": round(sum(t["long_net"] for t in trades), 2)}

def replay(bars, symbol, anchor="09:30", holding=60, slippage=1.0, fee=5.0):
    if symbol not in INSTRUMENTS:
        raise ValueError("Unsupported commodity")
    if holding not in (15, 30, 60, 120):
        raise ValueError("Holding period must be 15, 30, 60 or 120 minutes")
    if not finite(slippage) or not 0 <= slippage <= 20 or not finite(fee) or not 0 <= fee <= 100:
        raise ValueError("Invalid costs")
    spec = INSTRUMENTS[symbol]
    by_time = {row[0]: row for row in bars}
    trades, excluded = [], 0
    cost = fee + 2 * slippage * spec["tick"] * spec["multiplier"]
    for signal in candidates(bars, anchor):
        entry, end = signal["signal_time"], signal["signal_time"] + holding * 60
        if (dt.datetime.fromtimestamp(entry, NY).date() != dt.datetime.fromtimestamp(end, NY).date()
                or any(stamp not in by_time for stamp in range(entry, end + 1, 300))):
            excluded += 1
            continue
        opening, exit_price = by_time[entry][1], by_time[end][1]
        change = (exit_price - opening) * spec["multiplier"]
        gross = signal["direction"] * change
        trades.append({**signal, "entry_time": iso(entry), "exit_time": iso(end),
                       "entry": opening, "exit": exit_price, "gross": round(gross, 2),
                       "cost": round(cost, 2), "net": round(gross - cost, 2),
                       "long_net": round(change - cost, 2)})
    split = int(len(trades) * .7)
    return {"version": VERSION, "params": {"anchor": anchor, "holding": holding,
            "slippage": slippage, "fee": fee}, "summary": summary(trades),
            "earlier": summary(trades[:split]), "later": summary(trades[split:]),
            "split_date": trades[split]["date"] if trades else None,
            "excluded": excluded, "trades": trades, "limitation": LIMITATION}

def update_watch(entries, bars, symbol, now, fresh):
    """Only signals actually seen now enter this record. Delayed observations are never backdated."""
    records = [dict(entry) for entry in entries]
    clock = now.timestamp()
    for record in records:
        if record["status"] != "pending":
            continue
        outcome = next((b for b in bars if b[0] + 300 >= record["due_at"]), None)
        if outcome and outcome[0] + 300 <= record["due_at"] + 1800:
            record.update(status="resolved", outcome=outcome[4], outcome_time=iso(outcome[0] + 300),
                          scored_at=now.isoformat(), hit=(outcome[4] - record["baseline"]) * record["direction"] > 0)
        elif clock > record["due_at"] + 3600:
            record.update(status="unscored", scored_at=now.isoformat())
    if not bars or not fresh or clock - (bars[-1][0] + 300) > 1800:
        return records
    for signal in candidates(bars):
        identifier = VERSION + ":" + symbol + ":" + signal["date"]
        if not 0 <= clock - signal["signal_time"] <= 1800 or any(r["id"] == identifier for r in records):
            continue
        records.append({"id": identifier, "symbol": symbol, "direction": signal["direction"],
                        "signal_time": iso(signal["signal_time"]), "observed_at": now.isoformat(),
                        "baseline": bars[-1][4], "baseline_time": iso(bars[-1][0] + 300),
                        "due_at": clock + 3600, "status": "pending"})
    return records
