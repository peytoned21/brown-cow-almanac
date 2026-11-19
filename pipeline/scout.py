"""Team scout for one manager in one league: everything a daily lineup / waiver check needs, in one JSON file.

Pulls from ESPN (needs ESPN_S2 and ESPN_SWID, like fetch_season.py): league rules (lineup slots, waiver timing,
FAAB), the manager's roster and this week's opponent with projections, actual points, injuries and ownership; the
best free agents and players on waivers; the league's recent adds, drops and trades; the NFL schedule for the week
(kickoff times, byes); and recent ESPN news for every player involved. Read by the daily "team scout" email task.

Usage: python3 pipeline/scout.py LEAGUE_CONFIG OUT_JSON --owner "peyton edwards"
"""
import argparse, datetime, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_season import B, POS, make_get  # noqa: E402

SLOT = {0: 'QB', 2: 'RB', 3: 'RB/WR', 4: 'WR', 5: 'WR/TE', 6: 'TE', 7: 'OP', 16: 'D/ST', 17: 'K', 20: 'BE', 21: 'IR', 23: 'FLEX'}
PRO = {}  # proTeamId -> abbrev, filled from the schedule
WEEKLY = {}  # playerId -> {scoringPeriod: actual points}, filled by weekly_history()


def _utc(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(tzinfo=None)


def weekly_history(get, lg, sp, ids):
    """Actual points for each of the last few weeks (the roster views only carry the current week and season)."""
    ids = list(ids)
    for i in range(0, len(ids), 50):
        filt = {'players': {'filterIds': {'value': ids[i:i + 50]}, 'limit': 50,
                            'filterStatsForTopScoringPeriodIds': {'value': 5, 'additionalValue': []}}}
        try:
            d = get(f'{lg}?view=kona_playercard&scoringPeriodId={sp}', {'x-fantasy-filter': json.dumps(filt)})
        except Exception:
            continue
        for e in d.get('players') or []:
            p = e['player']
            for st in p.get('stats') or []:
                if st.get('statSourceId') == 0 and st.get('statSplitTypeId') == 1 and st.get('scoringPeriodId'):
                    WEEKLY.setdefault(p['id'], {})[st['scoringPeriodId']] = round(st.get('appliedTotal') or 0, 1)


def stat(p, sp, source, split):
    for s in p.get('stats') or []:
        if s.get('scoringPeriodId') == sp and s.get('statSourceId') == source and s.get('statSplitTypeId') == split:
            return round(s.get('appliedTotal') or 0, 1)
    return None


def player_row(p, sp, extra=None):
    own = p.get('ownership') or {}
    row = {
        'id': p['id'], 'name': p.get('fullName'), 'pos': POS.get(p.get('defaultPositionId'), '?'),
        'team': PRO.get(p.get('proTeamId'), p.get('proTeamId')), 'injury': p.get('injuryStatus') or 'ACTIVE',
        'proj': stat(p, sp, 1, 1), 'actual': stat(p, sp, 0, 1),
        'season': stat(p, 0, 0, 0), 'restOfSeasonProj': stat(p, 0, 1, 0),
        'last3': [WEEKLY.get(p['id'], {}).get(w, stat(p, w, 0, 1)) for w in range(max(1, sp - 3), sp)],
        'owned': round(own.get('percentOwned') or 0, 1), 'ownedChange': round(own.get('percentChange') or 0, 1),
        'started': round(own.get('percentStarted') or 0, 1),
    }
    if p.get('lastNewsDate'):
        row['lastNews'] = _utc(p['lastNewsDate'] / 1000).strftime('%Y-%m-%dT%H:%MZ')
    if extra:
        row.update(extra)
    return row


def roster(team, sp):
    out = []
    for e in (team.get('roster') or {}).get('entries') or []:
        p = e['playerPoolEntry']['player']
        out.append(player_row(p, sp, {'slot': SLOT.get(e.get('lineupSlotId'), e.get('lineupSlotId')),
                                      'eligible': [SLOT[s] for s in p.get('eligibleSlots') or [] if s in SLOT and s not in (20, 21)]}))
    return out


def news(get_public, ids):
    """Latest ESPN news blurbs per player (public endpoint; best effort)."""
    out = {}
    for pid in ids:
        try:
            d = get_public(f'https://site.api.espn.com/apis/fantasy/v2/games/ffl/news/players?limit=4&playerId={pid}')
        except Exception:
            continue
        items = []
        for f in (d.get('feed') or [])[:4]:
            items.append({'date': (f.get('published') or f.get('lastModified') or '')[:16],
                          'headline': f.get('headline'), 'story': (f.get('story') or f.get('description') or '')[:600]})
        if items:
            out[str(pid)] = items
        time.sleep(0.15)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('config'); ap.add_argument('out'); ap.add_argument('--owner', required=True)
    ap.add_argument('--year', type=int, default=None)
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    lid = cfg['espn']['leagueId']
    cookie = f"espn_s2={os.environ['ESPN_S2']}; SWID={os.environ['ESPN_SWID']}"
    get = make_get(cookie)
    get_public = make_get('')
    now = datetime.datetime.now(datetime.timezone.utc)
    y = a.year or (now.year if now.month >= 8 else now.year - 1)
    lg = f'{B}/seasons/{y}/segments/0/leagues/{lid}'

    base = get(f'{lg}?view=mSettings&view=mStatus&view=mTeam')
    if 'settings' not in base:
        raise RuntimeError('ESPN returned no league settings: the cookies are probably missing or expired')
    st = base['settings']; ss = st['scheduleSettings']; acq = st.get('acquisitionSettings') or {}
    sp = base.get('scoringPeriodId') or (base.get('status') or {}).get('latestScoringPeriod')
    wk = (base.get('status') or {}).get('currentMatchupPeriod')

    # NFL schedule: abbreviations, byes, this week's kickoffs
    sched = get(f'{B}/seasons/{y}?view=proTeamSchedules_wl')
    games = {}
    for t in (sched.get('settings') or {}).get('proTeams') or []:
        PRO[t['id']] = t.get('abbrev', '').upper()
    for t in (sched.get('settings') or {}).get('proTeams') or []:
        for g in (t.get('proGamesByScoringPeriod') or {}).get(str(sp)) or []:
            key = g.get('id')
            games[key] = {'kickoff': _utc(g['date'] / 1000).strftime('%Y-%m-%dT%H:%MZ'),
                          'away': PRO.get(g.get('awayProTeamId')), 'home': PRO.get(g.get('homeProTeamId'))}
    byes = sorted(PRO[t['id']] for t in (sched.get('settings') or {}).get('proTeams') or [] if t.get('byeWeek') == sp and t['id'])

    full = get(f'{lg}?view=mTeam&view=mRoster&view=mMatchupScore&scoringPeriodId={sp}')
    mem = {m['id']: ((m.get('firstName') or '') + ' ' + (m.get('lastName') or '')).strip() for m in full.get('members') or base.get('members') or []}
    teams = {t['id']: t for t in full['teams']}
    meta = {t['id']: t for t in base['teams']}
    me = next(t for t in full['teams'] if any(a.owner.lower() in mem.get(o, '').lower() for o in t.get('owners') or []))

    def tname(t):
        return (t.get('name') or ((t.get('location') or '') + ' ' + (t.get('nickname') or ''))).strip()

    def tsum(tid):
        t = meta.get(tid) or teams[tid]; o = t['record']['overall']
        tc = t.get('transactionCounter') or {}
        return {'id': tid, 'name': tname(t), 'owners': [mem.get(x, '?') for x in t.get('owners') or []],
                'record': f"{o['wins']}-{o['losses']}" + (f"-{o['ties']}" if o.get('ties') else ''),
                'pointsFor': round(o.get('pointsFor') or 0, 1), 'seed': t.get('playoffSeed'),
                'waiverRank': t.get('waiverRank'),
                'faabLeft': (acq.get('acquisitionBudget') or 0) - (tc.get('acquisitionBudgetSpent') or 0) if acq.get('isUsingAcquisitionBudget') else None}

    game = next((m for m in full.get('schedule') or [] if m.get('matchupPeriodId') == wk
                 and me['id'] in ((m.get('home') or {}).get('teamId'), (m.get('away') or {}).get('teamId'))), None)
    opp_id = None; score = None
    if game:
        h, aw = game.get('home') or {}, game.get('away') or {}
        mine, theirs = (h, aw) if h.get('teamId') == me['id'] else (aw, h)
        opp_id = theirs.get('teamId')
        score = {'me': round(mine.get('totalPoints') or 0, 1), 'opp': round(theirs.get('totalPoints') or 0, 1),
                 'meLive': mine.get('totalPointsLive'), 'oppLive': theirs.get('totalPointsLive')}
    last = next((m for m in full.get('schedule') or [] if m.get('matchupPeriodId') == wk - 1
                 and me['id'] in ((m.get('home') or {}).get('teamId'), (m.get('away') or {}).get('teamId'))), None)
    last_result = None
    if last:
        h, aw = last.get('home') or {}, last.get('away') or {}
        mine, theirs = (h, aw) if h.get('teamId') == me['id'] else (aw, h)
        last_result = {'week': wk - 1, 'opp': tname(teams[theirs['teamId']]), 'me': mine.get('totalPoints'),
                       'opp_pts': theirs.get('totalPoints'), 'winner': last.get('winner')}

    # Free agents and waivers: by ownership, by ownership trend, and by this week's projection
    fa = {}
    for sort in ({'sortPercOwned': {'sortPriority': 1, 'sortAsc': False}},
                 {'sortPercChanged': {'sortPriority': 1, 'sortAsc': False}},
                 {'sortAppliedStatTotalForScoringPeriodId': {'sortPriority': 1, 'sortAsc': False, 'value': sp}}):
        for slot in (0, 2, 4, 6, 16, 17):
            filt = {'players': {'filterStatus': {'value': ['FREEAGENT', 'WAIVERS']}, 'filterSlotIds': {'value': [slot]},
                                'limit': 12 if slot not in (16, 17) else 6, **sort}}
            try:
                d = get(f'{lg}?view=kona_player_info&scoringPeriodId={sp}', {'x-fantasy-filter': json.dumps(filt)})
            except Exception:
                continue
            for e in d.get('players') or []:
                p = e['player']
                if p['id'] not in fa:
                    extra = {'status': e.get('status')}
                    if e.get('waiverProcessDate'):
                        extra['waiverClears'] = _utc(e['waiverProcessDate'] / 1000).strftime('%Y-%m-%dT%H:%MZ')
                    fa[p['id']] = player_row(p, sp, extra)

    # League transactions over the last two scoring periods
    names = {}
    for t in full['teams']:
        for e in (t.get('roster') or {}).get('entries') or []:
            names[e['playerId']] = e['playerPoolEntry']['player'].get('fullName')
    for pid, r in fa.items():
        names[pid] = r['name']
    tx = []
    for s in (sp - 1, sp):
        try:
            d = get(f'{lg}?view=mTransactions2&scoringPeriodId={s}')
        except Exception:
            continue
        for t in d.get('transactions') or []:
            if t.get('status') != 'EXECUTED' or t.get('type') not in ('FREEAGENT', 'WAIVER', 'TRADE_ACCEPT', 'TRADE_PROPOSAL'):
                continue
            if t.get('type') == 'TRADE_PROPOSAL':
                continue
            items = [{'type': i.get('type'), 'player': names.get(i.get('playerId'), i.get('playerId')),
                      'team': tname(teams[i.get('toTeamId') if i.get('type') == 'ADD' else i.get('fromTeamId')])
                      if (i.get('toTeamId') if i.get('type') == 'ADD' else i.get('fromTeamId')) in teams else None}
                     for i in t.get('items') or [] if i.get('type') in ('ADD', 'DROP', 'TRADE')]
            tx.append({'when': _utc((t.get('processDate') or t.get('proposedDate') or 0) / 1000).strftime('%Y-%m-%dT%H:%MZ'),
                       'type': t['type'], 'team': tname(teams[t['teamId']]) if t.get('teamId') in teams else None,
                       'bid': t.get('bidAmount'), 'items': items})
    tx.sort(key=lambda x: x['when'], reverse=True)

    ids = [e['playerId'] for t in (me, teams.get(opp_id)) if t for e in (t.get('roster') or {}).get('entries') or []] + list(fa)
    weekly_history(get, lg, sp, ids)
    for pid, r in fa.items():
        r['last3'] = [WEEKLY.get(pid, {}).get(w, r['last3'][j] if j < len(r['last3']) else None) for j, w in enumerate(range(max(1, sp - 3), sp))]
    my_roster = roster(me, sp)
    opp_roster = roster(teams[opp_id], sp) if opp_id else []
    top_fa = sorted(fa.values(), key=lambda r: (-(r['proj'] or 0)))
    news_ids = [r['id'] for r in my_roster + opp_roster] + [r['id'] for r in sorted(fa.values(), key=lambda r: -r['owned'])[:25]] \
        + [r['id'] for r in top_fa[:15]]
    seen = set(); news_ids = [i for i in news_ids if not (i in seen or seen.add(i))]

    out = {
        'generated': now.strftime('%Y-%m-%dT%H:%MZ'), 'league': st['name'], 'leagueId': lid, 'season': y,
        'week': wk, 'scoringPeriod': sp, 'regularSeasonWeeks': ss.get('matchupPeriodCount'), 'playoffTeams': ss.get('playoffTeamCount'),
        'rules': {'slots': {SLOT.get(int(k), k): v for k, v in st['rosterSettings']['lineupSlotCounts'].items() if v},
                  'waiverType': acq.get('acquisitionType'), 'faab': acq.get('isUsingAcquisitionBudget'),
                  'faabBudget': acq.get('acquisitionBudget'), 'waiverHours': acq.get('waiverHours'),
                  'waiverProcessDays': acq.get('waiverProcessDays'), 'waiverProcessHour': acq.get('waiverProcessHour'),
                  'waiverOrderReset': acq.get('waiverOrderReset'), 'tradeDeadline': (st.get('tradeSettings') or {}).get('deadlineDate'),
                  'lockType': (st.get('rosterSettings') or {}).get('lineupLocktimeType')},
        'me': {**tsum(me['id']), 'roster': my_roster},
        'opponent': ({**tsum(opp_id), 'roster': opp_roster} if opp_id else None),
        'score': score, 'lastWeek': last_result,
        'standings': sorted((tsum(t) for t in meta), key=lambda r: r['seed'] or 99),
        'freeAgents': top_fa,
        'transactions': tx[:40],
        'nfl': {'games': sorted(games.values(), key=lambda g: g['kickoff']), 'byes': byes},
        'news': news(get_public, news_ids),
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, 'w'), indent=1)
    print(f"{st['name']}: week {wk}, {len(my_roster)} rostered, {len(top_fa)} free agents, {len(tx)} transactions, news for {len(out['news'])} players")


if __name__ == '__main__':
    main()
