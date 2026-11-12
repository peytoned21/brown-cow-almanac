"""Fetch ESPN's own weekly projections for every rostered player, for each played week of a season.

Saved to <league dir>/raw/proj/<year>.json as {week: {teamId: [[playerId, lineupSlot, projected, actual], ...]}}.
Used to measure how well ESPN's weekly projections predict matchups, against the season-long power rating.
Needs the ESPN_S2 and ESPN_SWID cookies, like fetch_season.py.

Usage: python3 pipeline/fetch_proj.py LEAGUE_CONFIG YEAR
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_season import B, make_get


def fetch(y, lid, cookie, hist_before):
    get = make_get(cookie)

    def url(views, extra=''):
        if y < hist_before:
            return f'{B}/leagueHistory/{lid}?seasonId={y}&{views}{extra}'
        return f'{B}/seasons/{y}/segments/0/leagues/{lid}?{views}{extra}'

    base = get(url('view=mSettings&view=mStatus'))
    reg = base['settings']['scheduleSettings']['matchupPeriodCount']
    cur = (base.get('status') or {}).get('currentMatchupPeriod') or reg + 1
    done = base.get('status', {}).get('isActive') is False
    last = reg if done or cur > reg else cur - 1
    out = {}
    for mp in range(1, last + 1):
        d = get(url('view=mBoxscore&view=mMatchupScore', f'&scoringPeriodId={mp}'))
        wk = {}
        for s in d.get('schedule') or []:
            if s.get('matchupPeriodId') != mp: continue
            for side in (s.get('home'), s.get('away')):
                R = (side or {}).get('rosterForCurrentScoringPeriod')
                if not R: continue
                rows = []
                for e in R.get('entries') or []:
                    p = e['playerPoolEntry']['player']
                    pr = next((x for x in p.get('stats') or [] if x.get('scoringPeriodId') == mp and x.get('statSourceId') == 1), None)
                    ac = next((x for x in p.get('stats') or [] if x.get('scoringPeriodId') == mp and x.get('statSourceId') == 0), None)
                    rows.append([e['playerId'], e.get('lineupSlotId'), round(pr['appliedTotal'], 2) if pr and pr.get('appliedTotal') is not None else None,
                                 round(ac['appliedTotal'], 2) if ac and ac.get('appliedTotal') is not None else None])
                wk[str(side['teamId'])] = rows
        if wk: out[str(mp)] = wk
        print(f'{y} week {mp}: {len(wk)} teams, {sum(1 for r in wk.values() for x in r if x[2] is not None)} projections')
    return out


if __name__ == '__main__':
    cfg = json.load(open(sys.argv[1])); y = int(sys.argv[2])
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), cfg['site']['dir'])
    s2, swid = os.environ.get('ESPN_S2', '').strip(), os.environ.get('ESPN_SWID', '').strip()
    if not s2 or not swid: sys.exit('Set ESPN_S2 and ESPN_SWID.')
    if not swid.startswith('{'): swid = '{' + swid.strip('{}') + '}'
    data = fetch(y, cfg['espn']['leagueId'], f'espn_s2={s2}; SWID={swid}', cfg['espn'].get('histBefore', 2020))
    os.makedirs(os.path.join(root, 'raw', 'proj'), exist_ok=True)
    path = os.path.join(root, 'raw', 'proj', f'{y}.json')
    json.dump(data, open(path, 'w'), separators=(',', ':'))
    print('wrote', path)
