"""Research signals on observed commodity spot series; no executable futures returns."""
import pandas as pd

def evaluate(series, window=20):
    s = series.dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    mean = s.rolling(window).mean()
    sd = s.rolling(window).std()
    z = (s-mean)/sd.replace(0,float("nan"))
    signal = z.apply(lambda x: 1 if x < -1 else -1 if x > 1 else 0)
    # Conservative observation lag; publication vintages are not available.
    direction = signal.shift(2)
    change = s.diff()
    valid = z.shift(2).notna() & change.notna() & direction.ne(0)
    scores = (direction*change)[valid]
    return {"date": str(s.index[-1].date()) if len(s) else None,
            "signal": int(signal.iloc[-1]) if len(s)>=window else None,
            "observations": int(len(scores)),
            "directional_accuracy": float((scores>0).mean()) if len(scores) else None,
            "method": "20-observation mean reversion; two-observation lag; revised spot data, not tradable P&L"}

def opening_ema(bars, session="09:30"):
    """Input: timezone-aware five-minute bar START timestamps and open/close.
    Returns next-bar entry candidates only, not realized trades."""
    if not isinstance(bars.index,pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("timezone-aware timestamps required")
    b=bars.sort_index().tz_convert("America/New_York")
    if b.index.has_duplicates:
        raise ValueError("duplicate timestamps")
    ema=b.close.ewm(span=12,adjust=False,min_periods=12).mean()
    out=[]
    for i,t in enumerate(b.index[:-1]):
        if t.strftime("%H:%M")!=session or pd.isna(ema.iloc[i]):
            continue
        if b.index[i+1]-t != pd.Timedelta(minutes=5):
            continue
        d=int(b.close.iloc[i]>ema.iloc[i])-int(b.close.iloc[i]<ema.iloc[i])
        if d:
            out.append({"signal_time":str(t+pd.Timedelta(minutes=5)),
                        "entry_time":str(b.index[i+1]),"direction":d,
                        "entry_open":float(b.open.iloc[i+1])})
    return out

def research(metrics):
    return {"mode":"research only", "signals":{k:evaluate(metrics[k]) for k in ("wti","brent","wti_brent","crack_321")},
            "intraday":{"status":"unavailable","reason":"Licensed historical five-minute contract data not configured"}}
