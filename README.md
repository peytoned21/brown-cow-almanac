# Brown Cow Almanac

The history site for Brown Cow 3.0, an ESPN fantasy football league founded in 2012. It covers every season, manager, record and rivalry, plus live odds and a playoff machine during the season.

**Site:** https://peytoned21.github.io/brown-cow-almanac/

## How it works

| Folder | What's in it |
|---|---|
| `index.html`, `data.json`, `art/` | The site, served by GitHub Pages from the repo root. `data.json` is built, not edited by hand |
| `raw/` | One file per season, as pulled from ESPN |
| `pipeline/fetch_season.py` | Pulls one season from ESPN into `raw/` |
| `pipeline/build.py` | Turns `raw/` into `data.json`: standings, records, Elo, luck, odds and everything else |
| `audit/audit.py` | Independently recomputes about 3,800 numbers and fails if any disagree |
| `pipeline/summary.py` | Writes the short summary shown on each refresh run |
| `.github/workflows/refresh.yml` | The weekly refresh |

Every Tuesday morning from September through January, GitHub Actions:

1. pulls the current season from ESPN,
2. rebuilds the stats,
3. runs the audit,
4. commits the new data, but only if every check passes.

Pages then republishes the site within a minute or two. If anything fails, nothing changes on the site, and GitHub emails the repo owner.

## Setup

**ESPN cookies.** The league is private, so the refresh signs in with two ESPN cookies. They're stored as repository secrets, which stay hidden even though the repo is public. They expire about once a year, and the refresh fails with a clear message when they do.

1. Sign in at espn.com in Chrome.
2. Open DevTools → Application → Cookies → `https://www.espn.com`.
3. Copy the values of `espn_s2` and `SWID`.
4. In this repo, go to Settings → Secrets and variables → Actions → New repository secret. Add `ESPN_S2` with the first value and `ESPN_SWID` with the second.

**Run a refresh by hand:** Actions → Weekly refresh → Run workflow. Tick "force" to rebuild even when ESPN hasn't changed.

## Running it locally

```
pip install -r requirements.txt
ESPN_S2=... ESPN_SWID=... python3 pipeline/fetch_season.py 2026
python3 pipeline/build.py raw data.json
python3 audit/audit.py raw data.json
python3 -m http.server
```

`pipeline/fetch_season.js` is the original browser version of the fetcher. It runs in a signed-in espn.com tab and is kept as a fallback.
