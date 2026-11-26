# Commodity Market Monitor

An automated, commodities-only energy research dashboard built by Liam Stutz.

**Dashboard:** https://liamstutz.github.io/commodity-market-monitor/

The scheduled pipeline fetches EIA and CFTC observations, validates them, computes transparent rules, writes a forward forecast journal and publishes the dashboard. No weekly calls or written notes are required.

## Coverage

| Input | Derived view |
| --- | --- |
| EIA WTI and Brent spot prices | Benchmarks and WTI minus Brent spread |
| EIA NY Harbor gasoline and diesel | 3-2-1 crack spread per barrel of crude |
| EIA US commercial crude inventories, ex-SPR | Reported weekly stocks and prior five-year seasonal range |
| CFTC NYMEX WTI disaggregated futures-only positioning | Managed-money long contracts minus short contracts |

This release covers energy commodities. Sources are delayed observations, not streaming exchange quotes. The commentary is generated from explicit calculations, without an LLM or paid API.

## Automatic operation

GitHub Actions runs at **22:30 UTC on weekdays**, and after relevant changes to main:

1. Test the signal rules and journal.
2. Fetch each public source independently with bounded retries.
3. Reject duplicate dates, non-finite values, future observations, regressing end dates and severe history loss.
4. Preserve the last valid cache on failure and record source health separately.
5. Generate four spot-data mean-reversion signals and a factual market brief.
6. Issue qualifying forecasts and resolve earlier forecasts; commit the journal and source observations.
7. Publish GitHub Pages.

A complete data outage still publishes a clearly marked cached dashboard, then marks the workflow failed. Partial failures are visible in source health; affected composite forecasts are not issued. Daily data older than seven calendar days pauses new signals. Weekly source data older than fourteen days is marked stale. These thresholds are safeguards, not assertions about official release schedules.

## Signals and evaluation

The fixed model uses a 20-observation rolling mean and sample standard deviation. A z-score below -1 forecasts a higher value; above +1 forecasts a lower value; otherwise the rule is neutral. Negative crude prices are valid. Spread signals concern the numerical spread: a higher WTI-minus-Brent spread means a less negative value when WTI trades below Brent.

Two evaluations are deliberately separate:

- **Historical diagnostic:** the signal from two observations earlier is checked against a one-observation change, using current revised data. The always-up comparison uses the identical active dates. This is not a point-in-time trading backtest.
- **Forward journal:** only forecasts actually issued during successful same-day refreshes are saved. The target is seven calendar days after issuance. The first observation on or after that date is compared with the baseline known at issue. If that observation is more than another seven days late, the forecast is unscored. Flat moves count as misses.

The baseline may predate issuance because source data arrives with a delay. Results are directional observations, not executable futures P&L. There are no fills, costs, contract rolls or claims of profitability. Forecasts overlap and are correlated. First-issued values and first-observed outcomes are preserved; reruns do not rewrite them. Local previews cannot create a forward record.

## Free intraday companion

**Cost: $0; no account or API key.** The private companion collects five-minute Yahoo Finance futures quotes for **WTI (CL=F), natural gas (NG=F) and gold (GC=F)**. It checks every five minutes while the computer is running. It does not run when the computer sleeps or is off, and does not install a startup task.

On Windows, right-click **Start-Intraday.ps1** and choose Run with PowerShell. It finds Python 3.10+, starts the collector in a hidden process and opens **http://127.0.0.1:8766/**. Re-running it opens the existing collector. Use the dashboard's **Stop local collector** button to stop it.

Cross-platform, run these commands from the project folder:

    python -m pip install tzdata
    python pipeline/intraday_server.py

The standalone companion needs only Python's standard library plus time-zone data on systems without an IANA database. The daily pipeline still uses requirements.txt. For a single refresh without a server, add **--once**. For cached/offline review, add **--offline**.

### Collection and privacy

- Initial fetch: about one month of available five-minute candles; subsequent requests cover five days and merge into a local archive capped at 30,000 bars per commodity.
- Completed bar-start timestamps only, with a ten-second completion buffer. Null rows and live quote placeholders are excluded; wrong symbols, bad OHLC ranges, duplicates, non-finite values and regressing histories are rejected.
- Closed observations are first-write preserved. Last fetch, latest bar end, age, unknown quote delay and failures are displayed separately. Failures retain cached data and retry on the next cycle.
- Yahoo is an unofficial, best-effort source and may rate-limit, change or fail. Rolling symbols do not provide audited historical contract identity. Data gaps, contract changes and quote delays limit the conclusions.
- Personal quotes, forward watches and logs stay in **.private/**, excluded from Git and never read by the public build. The server binds only to 127.0.0.1, serves a fixed file allowlist, rejects foreign hosts/origins and provides no CORS access.
- The public **intraday.html** page explains setup and can reopen an exported report entirely in the browser. It never probes localhost automatically or uploads reports.
- Exports contain personal research observations. Keep them private. No paid service is activated and no raw intraday quotes are redistributed through Pages.

### EMA replay and forward watch

The new **pipeline/intraday.py** engine runs a 12-period EMA on completed five-minute closes. It resets after a gap and each New York calendar day; twelve consecutive bars are required. At the configurable anchor (default **09:30 America/New_York**, not a universal exchange opening), close above/below EMA selects long/short. Ties are neutral.

Replay enters at the **next bar's open**, exits at the open after 15, 30, 60 or 120 minutes (default 60), and excludes incomplete paths. It uses one full-size contract, subtracting editable slippage per side and a round-trip fee. Defaults of one tick per side and $5 total fee are illustrative assumptions, not a broker quote. It shows gross/net hypothetical P&L, costs, net win rate, closed-trade drawdown, an always-buy comparator on identical sessions, a chronological 70/30 split, every simulated trade and report export. The later sample is not independently out of sample if settings are tuned using it.

A separate **forward watch** uses the fixed 09:30 anchor, and only records signals actually received within thirty minutes of completion when the latest bar is also no more than thirty minutes old. Its baseline is the last completed close known at observation; its target is one hour **after actual observation**, not a backdated hypothetical entry. The first subsequent close on/after the target, within thirty minutes, resolves direction. Missing outcomes are unscored and flat moves miss. Resolved entries never change. This watch has no fills or P&L and is separate from replay and the public seven-day spot forecast journal.

Futures units come from CME: [WTI](https://www.cmegroup.com/education/courses/event-contracts-underlying-markets/wti-overview.html) (1,000 barrels, $0.01 tick), [natural gas](https://www.cmegroup.com/education/courses/introduction-to-natural-gas/nat-gas-product-overview) (10,000 MMBtu, $0.001 tick), [gold](https://www.cmegroup.com/markets/metals/precious/gold/specs) (100 oz, $0.10 tick). No leverage, margin, financing, tick-level fills or executable returns are claimed. [Yahoo data usage context](https://github.com/ranaroussi/yfinance#readme).

## Run and validate

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python pipeline/fetch.py
python pipeline/build.py
python -m http.server --directory _site 8000
```

The scheduled workflow alone uses `python pipeline/build.py --record` after fetching. Use the ordinary build for previews.

For real-browser validation:

```bash
npm install --no-save --no-package-lock playwright@1.56.1
npx playwright install chromium
node tests/browser.cjs
```

CI tests desktop and mobile rendering, chart controls, keyboard inspection, journal export, failed-request retry, stale-data warnings and resolved outcomes. It uploads screenshots and a complete static preview as a workflow artifact.

## Project layout

- `pipeline/fetch.py`: validated public-data adapters and atomic cache writes
- `pipeline/sources.py`: source registry, dependencies and health checks
- `pipeline/quant.py`: daily rules and the inactive intraday experiment
- `pipeline/ledger.py`: persistent forward forecast record
- `pipeline/build.py`: strict JSON and static asset build
- `site/`: responsive dashboard with interactive SVG charts; no external chart or font dependency
- `data/`: observations, fetch status and automatically created forecast journal
- `tests/`: deterministic pipeline tests and real Chromium checks

Earlier human-written calls and notes remain in `calls/` and `notes/` for historical context. They are not used by the automated dashboard or included in its forward statistics.
