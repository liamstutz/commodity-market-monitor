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

## Intraday EMA experiment

The existing experimental opening-bar rule is retained and tested in `pipeline/quant.py`: 12-period EMA on five-minute bar-start timestamps, with a configurable 09:30 America/New_York anchor and next-bar-open entry candidate. Timestamps must be timezone aware; gaps, duplicates and invalid prices are rejected or skipped.

**No five-minute commodity contract feed is connected.** The dashboard therefore marks this module inactive. The default anchor is a research parameter, not a universal commodity exchange opening time. No intraday signals or returns are fabricated.

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
