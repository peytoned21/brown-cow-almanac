"""ESPN's public NFL scoreboard and box scores (no login), and a simple fantasy-points formula.

The site's live view runs the same formula in the browser (template.html, liveCalc) on fresh box scores every
45 seconds. It never stands alone: each live.json snapshot carries ESPN's official fantasy points for every starter
plus this formula's value at that moment, and the browser only adds what the formula says has happened since. So the
formula's blind spots (yardage bonuses, two-point conversions, kicker distance, defense scoring) are corrected every
time a new snapshot lands.
"""
import json, urllib.request

SITE_API = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'

# ESPN fantasy scoring statIds -> the box-score field this formula uses
STAT_IDS = {3: 'passYds', 4: 'passTD', 20: 'int', 24: 'rushYds', 25: 'rushTD', 42: 'recYds', 43: 'recTD', 53: 'rec', 72: 'fumLost'}
BOX_KEYS = {
    'passing': {'passingYards': 'passYds', 'passingTouchdowns': 'passTD', 'interceptions': 'int'},
    'rushing': {'rushingYards': 'rushYds', 'rushingTouchdowns': 'rushTD'},
    'receiving': {'receptions': 'rec', 'receivingYards': 'recYds', 'receivingTouchdowns': 'recTD'},
    'fumbles': {'fumblesLost': 'fumLost'},
    'kicking': {'totalKickingPoints': 'kickPts'},
}


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (brown-cow-almanac)'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def scoring_from_settings(scoring_items):
    """{field: points per unit} from ESPN's scoringItems (league settings)."""
    out = {}
    for it in scoring_items or []:
        f = STAT_IDS.get(it.get('statId'))
        if f: out[f] = it.get('points', 0)
    out['kickPts'] = 1.0   # box score kicking points (3 per FG, 1 per PAT): close enough between snapshots
    return out


def frac_left(ev):
    """Share of a game still to be played: 1 before kickoff, 0 once final."""
    st = ev.get('status') or {}
    state = (st.get('type') or {}).get('state')
    if state == 'pre': return 1.0
    if state == 'post': return 0.0
    period = st.get('period') or 1
    clock = st.get('clock')
    if clock is None:
        try:
            m, s = (st.get('displayClock') or '15:00').split(':'); clock = int(m) * 60 + float(s)
        except Exception:
            clock = 900
    if period > 4: return 0.02
    return max(0.0, min(1.0, ((4 - period) * 900 + clock) / 3600))


def scoreboard(y, wk):
    d = get(f'{SITE_API}/scoreboard?seasontype=2&week={wk}&dates={y}')
    evs = {}
    for e in d.get('events') or []:
        comp = (e.get('competitions') or [{}])[0]
        teams = [int(c['team']['id']) for c in comp.get('competitors') or []]
        state = ((e.get('status') or {}).get('type') or {}).get('state')
        evs[e['id']] = dict(teams=teams, state=state, frac=round(frac_left(e), 4), date=e.get('date'))
    return evs


def box(eid):
    """athleteId -> {field: value} for one game."""
    d = get(f'{SITE_API}/summary?event={eid}')
    out = {}
    for team in ((d.get('boxscore') or {}).get('players') or []):
        for cat in team.get('statistics') or []:
            keys = BOX_KEYS.get(cat.get('name'))
            if not keys: continue
            names = cat.get('keys') or []
            for a in cat.get('athletes') or []:
                aid = int(a['athlete']['id']); row = out.setdefault(aid, {})
                for i, k in enumerate(names):
                    f = keys.get(k)
                    if not f or i >= len(a.get('stats') or []): continue
                    try: row[f] = float(str(a['stats'][i]).replace(',', ''))
                    except ValueError: pass
    return out


def calc(stats, scoring):
    return round(sum(scoring.get(f, 0) * v for f, v in (stats or {}).items()), 2)
