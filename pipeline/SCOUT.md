# Daily team scout: playbook

A daily email to Peyton Edwards (peytoned@gmail.com) about his two ESPN teams: **The Loose Stools** in Brown Cow 3.0
and **Uncle Nasty Fingers** in Any Given Sunday. It is his one-stop shop: is the lineup right, what happened
yesterday, what changed in the news, who to pick up and when, and what the almanac says. It runs every morning of
the season around 5:45 ET. Read this whole file before writing.

**Suggestions only.** Never change anything on ESPN, never message the league, never post to GroupMe. The only thing
sent is one email to Peyton.

## Inputs

1. **Scout files** (`scout` branch, `brown-cow.json` and `any-given-sunday.json`), written by `pipeline/scout.py`
   through the `scout.yml` workflow. Start a fresh run and wait for it (see the task prompt). Each file has:
   `rules` (lineup slots, waiver type and timing, trade deadline in ms), `me` (record, seed, waiverRank, roster with
   slot, eligible slots, injury, proj = this week's ESPN projection, actual = this week so far, last3 = actual points
   in each of the previous three weeks, season, restOfSeasonProj, owned/ownedChange/started %, lastNews),
   `opponent` (same), `score` (this week's live totals), `lastWeek`, `standings`, `freeAgents` (status FREEAGENT or
   WAIVERS, with `waiverClears` for waiver players), `transactions` (league adds/drops/trades, newest first), `nfl`
   (this week's games with kickoff in UTC, and teams on bye), `news` (ESPN blurbs keyed by player id).
2. **Almanac** (`main` branch): `data.json` (Brown Cow) and `any-given-sunday/data.json`. Useful parts: `odds`
   (playoff, bye, title, final and Sacko odds, projected wins, finish-place distribution; row with key "edwards"),
   `power` (weekly power ranking; last element is current), `curLuck` (expected wins vs actual), `watch` (record
   chases and streaks), `live.preview` (this week's game previews with win chances and what each result does to the
   playoff odds) and `live.oddsHist` (odds over time), `awards` (current-season awards races), `recaps`.
   The newest newsletter is `newsletter/index.json` → the latest issue file (Brown Cow) and
   `any-given-sunday/newsletter/...`. The site is https://peytoned21.github.io/brown-cow-almanac/ (Any Given Sunday
   at `/any-given-sunday/`).
3. **Live snapshots** (`live` branch, one JSON per league): projected finals and win chances during game windows and a
   few times a day before kickoff. Use it on game days for the win chance; it can be hours old, so say so.
4. **News**: the scout file's ESPN blurbs, plus a handful of web searches (at most 8) for the things that matter
   most today: injury and practice reports for Peyton's questionable starters, depth-chart changes, the top waiver
   targets, and weather for outdoor games on game days. Search for news, not projections.

## Lineup check (every day, both leagues, the most important part)

Work out the best legal lineup from `rules.slots` and each player's `eligible` slots, using this week's projection.
Then flag, in this order:
- an empty starting slot, a starter on bye, or a starter who is OUT / IR / suspended → **DO NOW**
- a starter who is DOUBTFUL → DO NOW; QUESTIONABLE → name a pivot (a bench player whose game is later, ideally)
- a bench player projected clearly higher (≥ 2 points) than a starter he could replace
- players whose games have already kicked off are locked (individual-game lock): don't suggest moving them.
Superflex: the OP slot in Any Given Sunday takes a QB; always start two QBs there when possible.
Show the recommended lineup in the email with flags; mark changes from the current lineup with flag "swap".

## Yesterday

If NFL games were played yesterday (ET), list each of Peyton's players who played: actual vs projection, and the
current score of each matchup. Thursday, Sunday and Monday nights, plus Saturdays late in the season.

## Waivers and free agents

Both leagues use traditional waivers (no FAAB): a dropped player sits on waivers ~24 hours (`waiverClears`), and
waivers process every day except Tuesday. Brown Cow's waiver order is rolling (`waiverOrderReset` false: a claim
sends you to the back); Any Given Sunday's resets each week. Peyton's `waiverRank` tells you whether he'd likely win
a contested claim (1 = first).
- Recommend at most 3 moves per league, each with the drop. Prefer upgrades that help this week AND later; say which.
- Always say whether the player is a free agent (add now) or on waivers (claim; clears at <time ET>), and whether
  he'll clear before his game this week. A waiver claim that clears after the player's kickoff can't help this week.
- Timing by day: Tue–Wed = claims for the coming week and stashes; Thu = last chance for anyone who plays TNF;
  Fri–Sat = Sunday fill-ins and streamers (D/ST, K) and anyone on Saturday games; Sun morning = inactive pivots
  only; Mon = early claims (dropped players clear before Wednesday).
- Byes: look ahead one or two weeks for bye-week holes on Peyton's roster and plan pickups ahead.
- Use `transactions` to note what league-mates just did (big adds, drops worth grabbing, trades), and the
  `ownedChange` trend for players being picked up across ESPN.
- Never recommend dropping someone on IR who is coming back and matters, without saying so.
- Late season: from the trade deadline on, rosters only change through waivers; in the playoffs, think about the
  playoff weeks' schedules.

## Day-of-week focus (ET, on top of the daily lineup check)

- **Monday**: Sunday recap (every starter's score, best and worst calls, bench points left out), matchup status
  going into Monday night, who's left to play, win chance. Early waiver targets from Sunday's breakouts and injuries.
- **Tuesday**: the week's final results and what they did to the standings. The almanac refreshes overnight: playoff
  odds and how they moved, power ranking, luck, record watch, the newsletter headline. Waiver plan for the week.
- **Wednesday**: overnight waiver results (`transactions`: who got whom). Free agents now available. First look at the
  coming week: projected matchup, opponent's roster news, injuries, Wednesday practice reports (DNP/limited).
- **Thursday**: TNF day. Anyone playing tonight (on either side): is the lineup set for them before kickoff? Last
  free-agent adds for TNF players. Thursday practice reports.
- **Friday**: TNF recap. Friday injury reports with game designations (Out / Doubtful / Questionable). Sunday lineup
  plan and weekend pickups.
- **Saturday**: final pre-Sunday checklist. Game-time decisions with kickoff times and pivots (prefer a later-game
  pivot so a Sunday-morning swap is possible). Streamers. Saturday games late in the season.
- **Sunday** (early morning): game-day sheet. Final lineups, the inactive watch list (inactives come 90 minutes before
  each kickoff) with kickoff times, weather for outdoor games, London/early games.

## Almanac and fun

Every day, 1–3 almanac items per league that are actually interesting today: playoff, bye, title and Sacko odds (and
how they changed), clinching or elimination scenarios from `live.preview`, record chases from `watch`, power rank,
luck, awards races, a rivalry or history note about this week's opponent. Keep numbers exactly as the almanac has
them. Don't repeat the same item every day; vary it.

## Writing

- Lead with what Peyton must do and by when. If nothing needs doing, say so plainly ("Lineups are set").
- Short, specific, confident; no filler. Use names and numbers. Times in ET (convert from UTC).
- Use only the data files and what you found in searches; never invent stats, odds or news. If a source failed,
  say what's missing in one line.
- Both leagues every day, Brown Cow first. If one league's season is over for Peyton, drop it with one line.

## Email

Write `/tmp/scout_email.json` in the shape documented at the top of `pipeline/scout_email.py`, render it with
`python3 pipeline/scout_email.py /tmp/scout_email.json /tmp/scout_email.html`, and send ONE email with the Gmail
connector: to peytoned@gmail.com, subject `Team scout · <Dow, Mon D> · <headline>`, htmlBody = the HTML file's
contents, body = a plain-text version (to-do list, then each league's key points).
Before sending, search Sent for `subject:"Team scout · <Dow, Mon D>" newer_than:1d`; if today's email already went
out, send nothing. Call send_message once; never resend because a call was slow or unclear.

## When not to send

- Both seasons are over for Peyton (eliminated from the playoffs and nothing left to play) or ESPN shows no active
  season: send nothing.
- If the scout run fails, still send the email with what you can (almanac, news), and say at the top that ESPN
  roster data couldn't be pulled.

After sending, read the sent message back (get_message) and check its HTML still contains `bgcolor="#5b3a29"` (the
header color). Gmail keeps bgcolor attributes but strips some CSS; if the header color is gone, say so in the summary
(don't resend).
