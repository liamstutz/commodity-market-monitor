# Commodity Market Monitor: Energy

A live US oil market dashboard that updates itself every weekday, plus a **public, auto-graded track record of my market calls**.

**Live dashboard:** https://liamstutz.github.io/commodity-market-monitor/

## What it does

| | |
|---|---|
| **Pulls data automatically** | EIA spot prices (WTI, Brent, NY Harbor gasoline & diesel), EIA weekly crude inventories, and CFTC Commitments of Traders positioning, each weekday via GitHub Actions. |
| **Computes the numbers a desk watches** | 3-2-1 crack spread (refining margin), WTI–Brent spread, crude stocks vs. the 5-year seasonal range, managed-money net length. Each shows 1-week change and 1-year percentile. |
| **Grades my calls** | Each week I commit a directional call with a written thesis. The grader scores it against the data once it resolves. |
| **Can't be backdated** | A call counts from the date it was **first committed to git**, not the date written in the file. The commit history is a public, tamper-evident timestamp. |

## Why these metrics

- **3-2-1 crack spread:** 3 barrels of crude → 2 gasoline + 1 diesel. It's a rough gross margin for a refiner and drives crude demand.
- **WTI–Brent:** the US inland vs. waterborne crude price. It reflects US export economics, Cushing storage, and pipeline flows.
- **Inventories vs. 5-year range:** the market reacts to *surprises* against seasonal norms, not absolute levels.
- **Managed money positioning:** crowded speculative length or shortness raises the risk of sharp reversals.

## How calls are scored

```
start = last observation strictly BEFORE the call date   (what I knew)
end   = first observation ON or AFTER resolve_on
hit   = metric moved in the called direction by at least min_move
```

Calls live in `calls/` as small YAML files (see `calls/_TEMPLATE.yml`). Weekly notes live in `notes/`.

## Built with

Python (pandas), GitHub Actions (scheduled pipeline), GitHub Pages (hosting), Chart.js. I used AI to help build the pipeline and dashboard code. The calls, theses, and notes are my own.

---

## Setup (one time, ~10 minutes)

1. **Create the repo.** On github.com, click **New repository** and name it `commodity-market-monitor`. Make it **Public** and don't add a README. Upload this project's files.
   - The web uploader can skip hidden folders. After uploading, check that `.github/workflows/update.yml` exists. If it doesn't, use **Add file → Create new file**, type `.github/workflows/update.yml` as the name, and paste in the file's contents.
2. **Turn on Pages.** Go to **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
3. **Run it.** Go to **Actions → "Update data and publish dashboard" → Run workflow**. After a few minutes the dashboard URL appears in the run summary. Paste it at the top of this README.
4. **Edit the header.** In `site/index.html`, find the `EDIT` comment and put your name and LinkedIn there.

From then on it runs every weekday by itself.

## Weekly routine (~30 minutes)

1. Read the week's news and the EIA Weekly Petroleum Status Report (Wednesdays).
2. Copy `calls/_TEMPLATE.yml` to `calls/2026-09-29-crack-widens.yml` (or similar), fill it in, and commit.
3. Copy `notes/_TEMPLATE.md` to `notes/2026-09-29.md` and write your view. Commit.
4. The site rebuilds automatically after each commit.

Make calls you'd actually defend in an interview. Wrong calls with good reasoning are fine. Explaining what you learned from a miss is a strong interview answer.

## Run locally (optional)

```bash
pip install -r requirements.txt
python pipeline/fetch.py   # download data into data/
python pipeline/build.py   # build the site into _site/
python -m http.server -d _site 8000
```

## Notes

- If one data source is down, the previous cached data is kept and the site still builds.
- GitHub pauses scheduled workflows in repos with no activity for 60 days. The daily data commits normally prevent that. If it does pause, re-enable it in the Actions tab.
- Data: [EIA](https://www.eia.gov/petroleum/) and [CFTC COT](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm). Both are free, public, and need no API key.
