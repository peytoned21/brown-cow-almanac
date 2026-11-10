"""Game-day live layer: live scores, projected finals, live win chances and live playoff odds.

Reads the weekly build (data.json) for the season state, pulls the current week's box scores
from ESPN, and writes live.json, which the site polls while it is open.

Usage: python3 pipeline/live.py [DATA_JSON] [OUT_JSON]      (needs ESPN_S2 and ESPN_SWID)
       python3 pipeline/live.py DATA_JSON OUT_JSON --from FILE   (offline: use a saved ESPN response)
"""
import collections, datetime, json, math, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_season import make_get, B  # noqa: E402

LID = 125611
BENCH = {20, 21}          # bench, IR
GAME_HOURS = 3.4          # an NFL game, kickoff to final whistle


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ---------------------------------------------------------------- seeding (same rule as build.py)
def rank_teams(tids, W, PF, H, G):
    import itertools
    out = []; by = collections.defaultdict(list)
    for t in tids: by[W[t]].append(t)
    for w in sorted(by, reverse=True):
        grp = list(by[w])
        while grp:
            if len(grp) == 1: out += grp; break
            cnts = {G.get(frozenset((a, b)), 0) for a, b in itertools.combinations(grp, 2)}
            if len(cnts) == 1 and 0 not in cnts:
                def key(t):
                    ww = sum(H.get((t, o), 0) for o in grp if o != t); ll = sum(H.get((o, t), 0) for o in grp if o != t)
                    return (-(ww / (ww + ll) if ww + ll else .5), -PF[t])
            else:
                key = lambda t: -PF[t]
            first = min(grp, key=key); out.append(first); grp.remove(first)
    return out


def seed_teams(tids, divof, W, PF, H, G, po):
    divs = collections.defaultdict(list)
    for t in tids: divs[divof[t]].append(t)
    if len(divs) > 1:
        dw = [rank_teams(ts, W, PF, H, G)[0] for ts in divs.values()]
        order = rank_teams(dw, W, PF, H, G) + rank_teams([t for t in tids if t not in dw], W, PF, H, G)
        return order[:po], set(dw)
    order = rank_teams(tids, W, PF, H, G)
    return order[:po], set()


# ---------------------------------------------------------------- ESPN
def pro_kickoffs(get, y, sp):
    """proTeamId -> kickoff (unix seconds) for this scoring period, from ESPN's pro schedule."""
    try:
        d = get(f'{B}/seasons/{y}?view=proTeamSchedules_wl')
    except Exception:
        return {}
    out = {}
    for pt in ((d.get('settings') or {}).get('proTeams') or []):
        for g in (pt.get('proGamesByScoringPeriod') or {}).get(str(sp), []) or []:
            if g.get('date'):
                out[pt['id']] = g['date'] / 1000
    return out


def fetch_week(get, y, mp, sp):
    return get(f'{B}/seasons/{y}/segments/0/leagues/{LID}?view=mMatchupScore&view=mBoxscore&view=mScoreboard&scoringPeriodId={sp}')


def team_live(side, sp, kick, now):
    """Score so far, projected final and how much of the projection is still to be played."""
    R = side.get('rosterForCurrentScoringPeriod') or side.get('rosterForMatchupPeriod') or {}
    pts = 0.0; proj_total = 0.0; proj_left = 0.0; left = 0; playing = 0
    for e in R.get('entries') or []:
        if e.get('lineupSlotId') in BENCH:
            continue
        p = e['playerPoolEntry']['player']
        act = e['playerPoolEntry'].get('appliedStatTotal') or 0
        pr = next((s_ for s_ in p.get('stats') or [] if s_.get('scoringPeriodId') == sp and s_.get('statSourceId') == 1), None)
        prj = (pr or {}).get('appliedTotal') or 0
        k = kick.get(p.get('proTeamId'))
        if k is None:                      # no schedule: treat a zero as not yet played
            frac = 1.0 if act == 0 else 0.0
        else:
            frac = min(1.0, max(0.0, 1 - (now - k) / (GAME_HOURS * 3600)))
        if frac >= 1: left += 1
        elif frac > 0: playing += 1
        pts += act; proj_total += prj; proj_left += prj * frac
    espn_live = side.get('totalProjectedPointsLive')
    proj_final = pts + proj_left
    if isinstance(espn_live, (int, float)) and espn_live > 0:
        proj_final = max(pts, espn_live)
    live_pts = side.get('totalPointsLive')
    if isinstance(live_pts, (int, float)) and live_pts > pts:
        pts = live_pts; proj_final = max(proj_final, pts)
    share = (proj_left / proj_total) if proj_total else (1.0 if pts == 0 else 0.0)
    return dict(pts=round(pts, 2), proj=round(proj_final, 1), share=round(min(1, max(0, share)), 3), left=left, playing=playing)


# ---------------------------------------------------------------- odds
def simulate(M, wk, fixed, N=6000, seed=1):
    """fixed: {(h, a): (p_home, home_final, away_final)} for the live week."""
    tids = [t['tid'] for t in M['teams']]
    mu = {t['tid']: t['mu'] for t in M['teams']}; sd = M['sd']; divof = {t['tid']: t['div'] for t in M['teams']}
    W0 = collections.Counter({t['tid']: t['w'] for t in M['teams']}); PF0 = collections.Counter({t['tid']: t['pf'] for t in M['teams']})
    H0 = collections.Counter(); G0 = collections.Counter()
    for h, a, hs, as_ in M['done']:
        G0[frozenset((h, a))] += 1
        if hs > as_: H0[(h, a)] += 1
        elif as_ > hs: H0[(a, h)] += 1
    for mp, h, a, ph in M['games']:
        G0[frozenset((h, a))] += 1
    rng = random.Random(seed)
    cnt = {t: collections.Counter() for t in tids}
    po = M['po']
    for _ in range(N):
        W = W0.copy(); PF = PF0.copy(); H = H0.copy()
        for mp, h, a, ph in M['games']:
            if mp == wk and (h, a) in fixed:
                p, fh, fa = fixed[(h, a)]
                hw = rng.random() < p
                PF[h] += fh; PF[a] += fa
            else:
                sh = rng.gauss(mu[h], sd); sa = rng.gauss(mu[a], sd)
                PF[h] += sh; PF[a] += sa; hw = sh > sa
            win, lose = (h, a) if hw else (a, h)
            W[win] += 1; H[(win, lose)] += 1
        seeds, dw = seed_teams(tids, divof, W, PF, H, G0, po)
        for t in seeds: cnt[t]['po'] += 1
        for t in seeds[:2]: cnt[t]['bye'] += 1
        for t in dw: cnt[t]['div'] += 1
        gm = lambda x, y_: x if rng.gauss(mu[x], sd) > rng.gauss(mu[y_], sd) else y_
        if po == 6:
            q1 = gm(seeds[2], seeds[5]); q2 = gm(seeds[3], seeds[4]); s1 = gm(seeds[0], q2); s2 = gm(seeds[1], q1)
        else:
            s1 = gm(seeds[0], seeds[3]); s2 = gm(seeds[1], seeds[2])
        cnt[gm(s1, s2)]['title'] += 1
    return {t: {k: round(cnt[t][k] / N, 3) for k in ('po', 'bye', 'div', 'title')} for t in tids}


def build_live(D, wk_data, now, kick):
    M = D['live']['machine']; y = M['y']; wk = M['played'] + 1
    if wk > M['reg']:
        return None
    sp = wk
    name = {t['tid']: t for t in M['teams']}
    pre = {(g[1], g[2]): g[3] for g in M['games'] if g[0] == wk}
    # before a team's first player kicks off, assume the best lineup (the weekly preview's projection);
    # managers often fix their lineups right up to kickoff
    pv = (D['live'].get('preview') or {})
    pproj = {}
    if pv.get('wk') == wk:
        for g in pv['games']: pproj[g['h']] = g['hp']; pproj[g['a']] = g['ap']
    sd = M['sd']
    games = []; fixed = {}; base = {}
    for s_ in wk_data.get('schedule') or []:
        if s_.get('matchupPeriodId') != wk or not s_.get('away'):
            continue
        h, a = s_['home']['teamId'], s_['away']['teamId']
        th, ta = team_live(s_['home'], sp, kick, now), team_live(s_['away'], sp, kick, now)
        for t_, tl in ((h, th), (a, ta)):
            if tl['pts'] == 0 and tl['playing'] == 0 and tl['share'] >= 0.999 and t_ in pproj:
                tl['proj'] = max(tl['proj'], pproj[t_])
        done = th['share'] == 0 and ta['share'] == 0 and th['playing'] == 0 and ta['playing'] == 0 and (th['pts'] or ta['pts'])
        if s_.get('winner') in ('HOME', 'AWAY'):
            done = True
        rem_sd = math.sqrt((sd * math.sqrt(th['share'])) ** 2 + (sd * math.sqrt(ta['share'])) ** 2)
        if done or rem_sd < 0.5:
            ph = 1.0 if th['pts'] > ta['pts'] else 0.0 if ta['pts'] > th['pts'] else 0.5
            if s_.get('winner') == 'HOME': ph = 1.0
            elif s_.get('winner') == 'AWAY': ph = 0.0
        else:
            ph = phi((th['proj'] - ta['proj']) / rem_sd)
        p0 = pre.get((h, a), 0.5)
        fixed[(h, a)] = (ph, th['proj'], ta['proj'])
        base[(h, a)] = (p0, name[h]['mu'], name[a]['mu'])
        started = (th['pts'] + ta['pts']) > 0 or th['playing'] + ta['playing'] > 0
        games.append(dict(h=h, a=a, hs=th['pts'], as_=ta['pts'], hp=th['proj'], ap=ta['proj'], hwin=round(ph, 3), hwin0=round(p0, 3),
                          hleft=th['left'] + th['playing'], aleft=ta['left'] + ta['playing'],
                          status='final' if done else ('live' if started else 'pre')))
    if not games:
        return None
    started_any = any(g['status'] != 'pre' for g in games)
    o_live = simulate(M, wk, fixed, seed=wk)
    o_pre = simulate(M, wk, base, seed=wk)
    odds = [dict(tid=t, po=o_live[t]['po'], po0=o_pre[t]['po'], title=o_live[t]['title'], title0=o_pre[t]['title'],
                 div=o_live[t]['div'], bye=o_live[t]['bye']) for t in o_live]
    return dict(y=y, wk=wk, updated=datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                started=started_any, final=all(g['status'] == 'final' for g in games), games=games, odds=odds)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    data_p = args[0] if args else 'data.json'; out_p = args[1] if len(args) > 1 else 'live.json'
    D = json.load(open(data_p))
    if not D.get('live') or not D['live'].get('machine'):
        print('No season in progress; nothing to do.'); sys.exit()
    M = D['live']['machine']; wk = M['played'] + 1
    now = time.time()
    if '--from' in sys.argv:
        src = sys.argv[sys.argv.index('--from') + 1]
        wk_data = json.load(open(src)); kick = {}
        if '--now' in sys.argv: now = float(sys.argv[sys.argv.index('--now') + 1])
    else:
        s2, swid = os.environ.get('ESPN_S2', '').strip(), os.environ.get('ESPN_SWID', '').strip()
        if not s2 or not swid:
            sys.exit('Set ESPN_S2 and ESPN_SWID.')
        if not swid.startswith('{'): swid = '{' + swid.strip('{}') + '}'
        get = make_get(f'espn_s2={s2}; SWID={swid}')
        wk_data = fetch_week(get, M['y'], wk, wk)
        kick = pro_kickoffs(get, M['y'], wk)
    L = build_live(D, wk_data, now, kick)
    if not L:
        print('No live week to report.'); sys.exit()
    # keep the file stable when nothing has moved, so no commit is made
    if os.path.exists(out_p):
        old = json.load(open(out_p))
        strip = lambda x: {k: v for k, v in x.items() if k != 'updated'}
        if strip(old) == strip(L):
            print('No change since the last update.'); sys.exit()
    json.dump(L, open(out_p, 'w'), separators=(',', ':'))
    print(f"Week {L['wk']}: " + '; '.join(f"{g['h']} {g['hs']}-{g['as_']} {g['a']} ({g['status']}, home {round(g['hwin']*100)}%)" for g in L['games']))
