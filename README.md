# League Almanacs

History sites for two ESPN fantasy football leagues, built from one shared pipeline:

- **Brown Cow 3.0** (since 2012): https://peytoned21.github.io/brown-cow-almanac/
- **Any Given Sunday** (since 2014): https://peytoned21.github.io/brown-cow-almanac/any-given-sunday/

Each site covers every season, manager, record and rivalry. During the season it adds live game-day scores, playoff odds and a playoff machine. Both can be added to a phone's home screen, and pages you've already viewed open without signal.

## Layout

| Path | What it is |
|---|---|
| `leagues/<league>.json` | Everything specific to one league: ESPN ID, seats and name merges, playoff rules, page text and colors, where it's published |
| `index.html`, `data.json`, `raw/`, `art/` | Brown Cow's site (repo root) and its ESPN data |
| `any-given-sunday/` | The same for Any Given Sunday |
| `pipeline/fetch_season.py` | Pulls one season from ESPN into `<league>/raw/` |
| `pipeline/build.py` | `raw/` → `data.json`: standings, records, Elo, luck, odds and everything else |
| `audit/audit.py` | Independently recomputes thousands of the numbers and fails if any disagree |
| `pipeline/page.py`, `pipeline/template.html` | The page shell, home-screen manifest and offline service worker for each league |
| `pipeline/cards.py`, `cards/card.html` | Link-preview images and the share pages under `s/` and `m/` |
| `pipeline/live.py`, `pipeline/nflbox.py` | Game-day snapshots: live scores, projected finals, win chances, live playoff odds |
| `pipeline/groupme.py`, `pipeline/summary.py` | The weekly recap for GroupMe and the run summary |
| `pipeline/refresh.sh` | The weekly refresh for every league |

## Automation

**Weekly refresh** (`.github/workflows/refresh.yml`, Tuesday mornings, September–January). For every league it:

1. pulls the current season from ESPN,
2. rebuilds the stats,
3. runs the audit,
4. redraws the share cards,
5. commits the leagues that passed,
6. posts each league's recap to its GroupMe.

A league whose audit fails is left as it was, and GitHub emails the repo owner.

**Live scores** (`.github/workflows/live.yml`, hourly during NFL game windows). Each run takes a snapshot for every league every 2 minutes while games are on, using ESPN's official fantasy points and live NFL box scores. Snapshots go to the `live` branch, which is overwritten each time, so game days don't add history to `main` or rebuild the site. While a page is open, it reads the latest snapshot every minute. In between, it updates scores every 45 seconds from ESPN's public NFL box scores, using the same formula as `nflbox.py`. The next snapshot then corrects anything that formula can't see, such as bonuses and kicker distance points.

## Setup

**ESPN cookies.** Both leagues are private, so the jobs sign in with two ESPN cookies, stored as repository secrets. Secrets stay hidden even though the repo is public. To get them, sign in at espn.com in Chrome, open DevTools → Application → Cookies → `https://www.espn.com`, and copy `espn_s2` and `SWID`. Save them as the secrets `ESPN_S2` and `ESPN_SWID`. They expire about once a year, and the refresh fails with a clear message when they do.

**GroupMe bots.** Sign in at dev.groupme.com and go to Bots → Create Bot. Pick the league's group, name the bot, and leave the callback URL blank. Save the Bot ID as `GROUPME_BOT_ID` (Brown Cow) or `AGS_GROUPME_BOT_ID` (Any Given Sunday). A league without a bot ID simply doesn't post. Scheduled refreshes post automatically. Manual runs post only when "Post the recaps to GroupMe" is ticked.

**Run by hand:** Actions → Weekly refresh (or Live scores) → Run workflow.

## Adding another league

Copy a file in `leagues/` and edit it: ESPN ID, franchises, cutoffs, page text, and the `site` block, which needs a new `dir` and `slug`. Fetch every past season with `pipeline/fetch_season.py`. Then run `build.py`, `audit.py` and `page.py`. The weekly and live jobs pick up every file in `leagues/` automatically.

## Running it locally

```
pip install -r requirements.txt
ESPN_S2=... ESPN_SWID=... python3 pipeline/fetch_season.py leagues/brown-cow.json 2026
python3 pipeline/build.py raw data.json leagues/brown-cow.json
python3 audit/audit.py raw data.json leagues/brown-cow.json
python3 pipeline/page.py leagues/brown-cow.json
python3 -m http.server
```

`pipeline/fetch_season.js` is the original browser version of the fetcher. It runs in a signed-in espn.com tab and is kept as a fallback.
