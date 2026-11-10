"""Fetch one ESPN fantasy season into the compact raw format the build reads.

Python port of fetch_season.js (which runs in a signed-in browser tab), so the
weekly refresh can run on GitHub Actions. A private league needs two ESPN
cookies, read from the environment: ESPN_S2 and ESPN_SWID.

Usage: python3 pipeline/fetch_season.py LEAGUE_CONFIG YEAR [OUT_PATH]
(the league ID and the year before which ESPN only serves league history come from the config's "espn" block)
"""
import json, os, sys, time
import urllib.request, urllib.error

B = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl'
POS = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'D/ST'}


def make_get(cookie):
    def get(u, hdr=None):
        last = None
        for _ in range(3):
            req = urllib.request.Request(u, headers={'Cookie': cookie, 'Accept': 'application/json',
                                                     'User-Agent': 'Mozilla/5.0 (brown-cow-almanac)', **(hdr or {})})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    j = json.load(r)
                    return j[0] if isinstance(j, list) else j
            except (urllib.error.URLError, json.JSONDecodeError) as e:
                last = e
                time.sleep(0.8)
        raise RuntimeError(f'fetch failed {u}: {last}')
    return get


def fetch(y, lid=125611, cookie='', hist_before=2020):
    get = make_get(cookie)
    hist = y < hist_before

    def url(views, extra=''):
        if hist:
            return f'{B}/leagueHistory/{lid}?seasonId={y}&{views}{extra}'
        return f'{B}/seasons/{y}/segments/0/leagues/{lid}?{views}{extra}'

    base = get(url('view=mTeam&view=mMatchupScore&view=mSettings&view=mDraftDetail&view=mStatus&view=mRoster'))
    if 'settings' not in base:
        raise RuntimeError('ESPN returned no league settings: the cookies are probably missing or expired')
    st = base['settings']; ss = st['scheduleSettings']
    mem = {}
    for m in base.get('members') or []:
        mem[m['id']] = ((m.get('firstName') or '') + ' ' + (m.get('lastName') or '')).strip() or m.get('displayName')
    players = {}

    def addP(p):
        if p['id'] not in players:
            players[p['id']] = [p.get('fullName'), POS.get(p.get('defaultPositionId'), ''), p.get('proTeamId') or 0, None]

    def item(stat_id):
        return next((i for i in st['scoringSettings']['scoringItems'] if i.get('statId') == stat_id), {}).get('points', 0)

    ts = st.get('tradeSettings'); acq = st.get('acquisitionSettings'); ds = st.get('draftSettings')
    out = {
        'y': y, 'name': st['name'], 'done': any(t.get('rankCalculatedFinal') == 1 for t in base['teams']),
        'curPeriod': (base.get('status') or {}).get('currentMatchupPeriod'),
        'settings': {
            'reg': ss['matchupPeriodCount'], 'po': ss['playoffTeamCount'], 'poLen': ss.get('playoffMatchupPeriodLength'),
            'seeding': ss.get('playoffSeedingRule'), 'ppr': item(53), 'passTD': item(4),
            'slots': st['rosterSettings']['lineupSlotCounts'],
            'divisions': [[d['id'], d['name']] for d in ss.get('divisions') or []],
            'tradeDeadline': ts.get('deadlineDate') if ts else None, 'vetoVotes': ts.get('vetoVotesRequired') if ts else None,
            'waivers': acq.get('acquisitionType') if acq else None, 'faab': acq.get('isUsingAcquisitionBudget') if acq else None,
            'keepers': ds.get('keeperCount') if ds else 0, 'draftType': ds.get('type') if ds else None,
        },
        'teams': [], 'games': [], 'draft': [], 'weeks': {}, 'tx': [],
    }
    for t in base['teams']:
        o = t['record']['overall']; tc = t.get('transactionCounter') or {}
        roster = []
        for e in ((t.get('roster') or {}).get('entries') or []):
            addP(e['playerPoolEntry']['player']); roster.append(e['playerId'])
        out['teams'].append({
            'id': t['id'], 'name': (t.get('name') or ((t.get('location') or '') + ' ' + (t.get('nickname') or ''))).strip(),
            'abbrev': t.get('abbrev'), 'owners': [mem.get(x, '?') for x in t.get('owners') or []], 'div': t.get('divisionId'),
            'w': o['wins'], 'l': o['losses'], 't': o['ties'], 'pf': round(o['pointsFor'], 2), 'pa': round(o['pointsAgainst'], 2),
            'rank': t.get('rankCalculatedFinal') or 0, 'seed': t.get('playoffSeed') or 0,
            'tc': [tc.get('acquisitions', 0), tc.get('drops', 0), tc.get('trades', 0), tc.get('moveToActive', 0), tc.get('acquisitionBudgetSpent', 0)],
            'roster': roster,
        })
    out['games'] = [[s['matchupPeriodId'], s['home']['teamId'], round(s['home'].get('totalPoints') or 0, 2), s['away']['teamId'],
                     round(s['away'].get('totalPoints') or 0, 2), s.get('playoffTierType'), s.get('winner')]
                    for s in base.get('schedule') or [] if s.get('away')]
    out['draft'] = [[p['overallPickNumber'], p['roundId'], p['teamId'], p['playerId'], 1 if p.get('keeper') else 0, p.get('bidAmount') or 0]
                    for p in ((base.get('draftDetail') or {}).get('picks') or [])]

    # Weekly lineups
    last_period = max(g[0] for g in out['games'])
    po_len = ss.get('playoffMatchupPeriodLength') or 1
    reg = ss['matchupPeriodCount']
    first_week = lambda mp: mp if mp <= reg else reg + 1 + (mp - reg - 1) * po_len
    max_mp = last_period if out['done'] else min(last_period, (out['curPeriod'] or 1) - 1)
    for mp in range(1, max_mp + 1):
        sp = first_week(mp)
        d = get(url('view=mBoxscore&view=mMatchupScore', f'&scoringPeriodId={sp}'))
        rows = []
        for s in d.get('schedule') or []:
            if s.get('matchupPeriodId') != mp:
                continue
            for side in (s.get('home'), s.get('away')):
                if not side:
                    continue
                if po_len == 1 or mp <= reg:
                    R = side.get('rosterForCurrentScoringPeriod') or side.get('rosterForMatchupPeriod')
                else:
                    R = side.get('rosterForMatchupPeriod') or side.get('rosterForCurrentScoringPeriod')
                if not R:
                    continue
                full = bool(side.get('rosterForCurrentScoringPeriod'))
                ents = []
                for e in R['entries']:
                    p = e['playerPoolEntry']['player']; addP(p)
                    elig = '.'.join(str(x) for x in (p.get('eligibleSlots') or []) if x < 20)
                    ents.append([e['playerId'], e.get('lineupSlotId') if full else -1, round(e['playerPoolEntry'].get('appliedStatTotal') or 0, 2), elig])
                rows.append([side['teamId'], 1 if full else 0, ents])
        if rows:
            out['weeks'][str(mp)] = rows

    # Transactions (season endpoint only)
    if not hist:
        seen = set()
        for sp in range(0, 19):
            d = get(url('view=mTransactions2', f'&scoringPeriodId={sp}'))
            for t in d.get('transactions') or []:
                if t['id'] in seen or t.get('status') != 'EXECUTED':
                    continue
                seen.add(t['id'])
                if t.get('type') not in ('TRADE_ACCEPT', 'TRADE_UPHOLD', 'TRADE_PROPOSAL', 'FREEAGENT', 'WAIVER'):
                    continue
                out['tx'].append([t['type'], t.get('scoringPeriodId'), t.get('proposedDate') or t.get('processDate') or 0, t.get('teamId'),
                                  t.get('bidAmount') or 0, [[i.get('type'), i.get('playerId'), i.get('fromTeamId'), i.get('toTeamId')] for i in t.get('items') or []]])

    # Upcoming week: each roster with ESPN's projected points (for matchup previews)
    if not out['done'] and out['curPeriod']:
        mp = out['curPeriod']; sp = first_week(mp)
        d = get(url('view=mRoster', f'&scoringPeriodId={sp}'))
        up = {}
        for t in d.get('teams') or []:
            lst = []
            for e in ((t.get('roster') or {}).get('entries') or []):
                p = e['playerPoolEntry']['player']; addP(p)
                pr = next((s for s in p.get('stats') or [] if s.get('scoringPeriodId') == sp and s.get('statSourceId') == 1), None)
                lst.append([e['playerId'], e.get('lineupSlotId'), round(pr['appliedTotal'], 1) if pr and pr.get('appliedTotal') is not None else 0,
                            '.'.join(str(x) for x in (p.get('eligibleSlots') or []) if x < 20), p.get('injuryStatus') or ''])
            up[str(t['id'])] = lst
        out['upcoming'] = {'mp': mp, 'sp': sp, 'teams': up}

    # Season totals for every relevant player (draft grades, name lookup)
    need = set([p[3] for p in out['draft']] + list(players.keys()))
    for t in out['tx']:
        for i in t[5]:
            need.add(i[1])

    def season_pts(p):
        s = next((q for q in p.get('stats') or [] if q.get('seasonId') == y and q.get('statSourceId') == 0 and q.get('statSplitTypeId') == 0), None)
        return round(s['appliedTotal'], 1) if s and s.get('appliedTotal') is not None else 0

    flt = {'players': {'limit': 1200, 'sortAppliedStatTotal': {'sortAsc': False, 'sortPriority': 1, 'value': '00' + str(y)}}}
    kp = get(url('view=kona_player_info', '&scoringPeriodId=0'), {'x-fantasy-filter': json.dumps(flt)})
    ranked = []
    for x in kp.get('players') or []:
        p = x['player']; pts = season_pts(p)
        ranked.append([p['id'], POS.get(p.get('defaultPositionId'), ''), pts])
        if p['id'] in need:
            if p['id'] not in players:
                players[p['id']] = [p.get('fullName'), POS.get(p.get('defaultPositionId'), ''), p.get('proTeamId') or 0, pts]
            else:
                players[p['id']][3] = pts
    out['ranked'] = [r for r in ranked if r[2] > 0][:450]
    miss = [i for i in need if i not in players]
    if miss:
        flt2 = {'players': {'filterIds': {'value': miss}, 'limit': len(miss)}}
        kp2 = get(url('view=kona_player_info', '&scoringPeriodId=0'), {'x-fantasy-filter': json.dumps(flt2)})
        for x in kp2.get('players') or []:
            p = x['player']
            if p['id'] in need and p['id'] not in players:
                players[p['id']] = [p.get('fullName'), POS.get(p.get('defaultPositionId'), ''), p.get('proTeamId') or 0, season_pts(p)]
    out['players'] = {str(k): v for k, v in players.items()}
    return out


if __name__ == '__main__':
    cfg = json.load(open(sys.argv[1])); y = int(sys.argv[2])
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), cfg['site']['dir'])
    path = sys.argv[3] if len(sys.argv) > 3 else os.path.join(root, 'raw', f'{y}.json')
    lid = cfg['espn']['leagueId']; hb = cfg['espn'].get('histBefore', 2020)
    s2, swid = os.environ.get('ESPN_S2', '').strip(), os.environ.get('ESPN_SWID', '').strip()
    if not s2 or not swid:
        sys.exit('Set ESPN_S2 and ESPN_SWID (the espn_s2 and SWID cookies from espn.com).')
    if not swid.startswith('{'):
        swid = '{' + swid.strip('{}') + '}'
    data = fetch(y, lid, f'espn_s2={s2}; SWID={swid}', hb)
    json.dump(data, open(path, 'w'), separators=(',', ':'))
    print(f'wrote {path}: {len(data["teams"])} teams, {len(data["games"])} games, {len(data["weeks"])} weeks of lineups, done={data["done"]}')
