"""Game-day live layer for one league: live scores, projected finals, win chances and live playoff odds.

Reads the weekly build (<site.dir>/data.json) for the season state, pulls the current week's fantasy box scores
from ESPN (needs ESPN_S2 and ESPN_SWID) plus ESPN's public NFL box scores, and writes one live snapshot. The
snapshot also carries every starter's line, so the site can keep scores moving between snapshots on its own
(see nflbox.py).

Usage:
  python3 pipeline/live.py LEAGUE_CONFIG OUT_JSON                  one snapshot
  python3 pipeline/live.py LEAGUE_CONFIG OUT_JSON --loop 55 --every 180 --after "pipeline/push_live.sh"
        keep taking snapshots for up to 55 minutes while games are on, running the --after command after each change
  python3 pipeline/live.py LEAGUE_CONFIG OUT_JSON --from ESPN_WEEK_JSON [--now UNIX]    offline test
"""
import collections, datetime, json, math, os, random, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_season import make_get, B  # noqa: E402
import nflbox  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = {20, 21}          # bench, IR


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ---------------------------------------------------------------- seeding (same rules as build.py)
def rank_teams(tids, W, PF, H, G, h2h=True):
    import itertools
    out = []; by = collections.defaultdict(list)
    for t in tids: by[W[t]].append(t)
    for w in sorted(by, reverse=True):
        grp = list(by[w])
        while grp:
            if len(grp) == 1: out += grp; break
            cnts = {G.get(frozenset((a, b)), 0) for a, b in itertools.combinations(grp, 2)}
            if h2h and len(cnts) == 1 and 0 not in cnts:
                def key(t):
                    ww = sum(H.get((t, o), 0) for o in grp if o != t); ll = sum(H.get((o, t), 0) for o in grp if o != t)
                    return (-(ww / (ww + ll) if ww + ll else .5), -PF[t])
            else:
                key = lambda t: -PF[t]
            first = min(grp, key=key); out.append(first); grp.remove(first)
    return out


def seed_teams(tids, divof, W, PF, H, G, po, pw=0, h2h=True):
    divs = collections.defaultdict(list)
    for t in tids: divs[divof[t]].append(t)
    if pw:
        order = rank_teams(tids, W, PF, H, G, h2h); top = order[:po - pw]; rest = [t for t in order if t not in top]
        wcs = sorted(rest, key=lambda t: -PF[t])[:pw]
        return (top + wcs)[:po], set()
    if len(divs) > 1:
        dw = [rank_teams(ts, W, PF, H, G, h2h)[0] for ts in divs.values()]
        order = rank_teams(dw, W, PF, H, G, h2h) + rank_teams([t for t in tids if t not in dw], W, PF, H, G, h2h)
        return order[:po], set(dw)
    return rank_teams(tids, W, PF, H, G, h2h)[:po], set()


def simulate(M, wk, fixed, h2h=True, N=6000, seed=1):
    """fixed: {(h, a): (p_home, home_final, away_final)} for the live week."""
    tids = [t['tid'] for t in M['teams']]
    mu = {t['tid']: t['mu'] for t in M['teams']}; sd = M['sd']; divof = {t['tid']: t['div'] for t in M['teams']}
    W0 = collections.Counter({t['tid']: t['w'] for t in M['teams']}); PF0 = collections.Counter({t['tid']: t['pf'] for t in M['teams']})
    H0 = collections.Counter(); G0 = collections.Counter()
    for h, a, hs, as_ in M['done']:
        G0[frozenset((h, a))] += 1
        if hs > as_: H0[(h, a)] += 1
        elif as_ > hs: H0[(a, h)] += 1
    for mp, h, a, ph in M['games']: G0[frozenset((h, a))] += 1
    rng = random.Random(seed); cnt = {t: collections.Counter() for t in tids}; po = M['po']; pw = M.get('pw', 0)
    for _ in range(N):
        W = W0.copy(); PF = PF0.copy(); H = H0.copy()
        for mp, h, a, ph in M['games']:
            if mp == wk and (h, a) in fixed:
                p, fh, fa = fixed[(h, a)]; hw = rng.random() < p; PF[h] += fh; PF[a] += fa
            else:
                sh = rng.gauss(mu[h], sd); sa = rng.gauss(mu[a], sd); PF[h] += sh; PF[a] += sa; hw = sh > sa
            win, lose = (h, a) if hw else (a, h); W[win] += 1; H[(win, lose)] += 1
        seeds, dw = seed_teams(tids, divof, W, PF, H, G0, po, pw, h2h)
        for t in seeds: cnt[t]['po'] += 1
        if po == 6:
            for t in seeds[:2]: cnt[t]['bye'] += 1
        for t in dw: cnt[t]['div'] += 1
        gm = lambda x, y_: x if rng.gauss(mu[x], sd) > rng.gauss(mu[y_], sd) else y_
        if po == 6:
            q1 = gm(seeds[2], seeds[5]); q2 = gm(seeds[3], seeds[4]); s1 = gm(seeds[0], q2); s2 = gm(seeds[1], q1)
        else:
            s1 = gm(seeds[0], seeds[3]); s2 = gm(seeds[1], seeds[2])
        cnt[gm(s1, s2)]['title'] += 1
    return {t: {k: round(cnt[t][k] / N, 3) for k in ('po', 'bye', 'div', 'title')} for t in tids}


# ---------------------------------------------------------------- one snapshot
# How much a player's score swings week to week, by position: sd = a * mean^b, fit on every starter-season in both
# leagues since 2020 (each player's spread around his own average). live.py scales these so a full lineup's total
# spread matches the league's weekly spread (machine.sd), then each player's remaining share of it shrinks as his
# game is played.
POS_SD = {1: (2.518, 0.353), 2: (1.308, 0.619), 3: (1.637, 0.564), 4: (1.268, 0.656), 5: (1.221, 0.556), 16: (2.838, 0.327)}
SKIP_STATUS = {'OUT', 'INJURY_RESERVE', 'SUSPENSION'}
FLEX_SLOTS = {23: {2, 3, 4}, 3: {2, 3}, 5: {3, 4}, 7: {1, 2, 3, 4}}   # FLEX (RB/WR/TE), RB/WR, WR/TE, OP
SLOT_POS = {0: 1, 2: 2, 4: 3, 6: 4, 16: 16, 17: 5}


def player_sd(pos, proj):
    a, b = POS_SD.get(pos, (1.6, 0.56))
    return a * max(proj, 1.0) ** b


def entry_info(e, sp):
    p = e['playerPoolEntry']['player']
    pr = next((s_ for s_ in p.get('stats') or [] if s_.get('scoringPeriodId') == sp and s_.get('statSourceId') == 1), None)
    return p, e['playerPoolEntry'].get('appliedStatTotal') or 0, (pr or {}).get('appliedTotal') or 0


def best_lineup(entries, sp, slot_counts):
    """The lineup a manager would set from ESPN's projections: fixed positions first, then the flex spots."""
    pool = []
    for e in entries:
        p, act, prj = entry_info(e, sp)
        if (p.get('injuryStatus') or '') in SKIP_STATUS or prj <= 0: continue
        pool.append((prj, p.get('defaultPositionId') or 0, e))
    pool.sort(key=lambda x: -x[0]); used = set(); picked = []
    for slot, posn in SLOT_POS.items():
        for _ in range(int(slot_counts.get(str(slot), slot_counts.get(slot, 0)) or 0)):
            c = next((x for x in pool if id(x[2]) not in used and x[1] == posn), None)
            if c: used.add(id(c[2])); picked.append(c[2])
    for slot, allowed in FLEX_SLOTS.items():
        for _ in range(int(slot_counts.get(str(slot), slot_counts.get(slot, 0)) or 0)):
            c = next((x for x in pool if id(x[2]) not in used and x[1] in allowed), None)
            if c: used.add(id(c[2])); picked.append(c[2])
    return picked


def team_side(side, sp, team_frac, box, scoring, players_out, slot_counts, scale):
    R = side.get('rosterForCurrentScoringPeriod') or side.get('rosterForMatchupPeriod') or {}
    entries = R.get('entries') or []
    starters = [e for e in entries if e.get('lineupSlotId') not in BENCH]
    fr = lambda p, act: team_frac.get(p.get('proTeamId') or 0, 1.0 if act == 0 else 0.0)
    started = any(fr(*entry_info(e, sp)[:2]) < 1 or entry_info(e, sp)[1] for e in starters)
    if not started and slot_counts:            # nobody has played yet: assume the best lineup on the roster
        bl = best_lineup(entries, sp, slot_counts)
        if bl and sum(entry_info(e, sp)[2] for e in bl) > sum(entry_info(e, sp)[2] for e in starters): starters = bl
    pts = proj = var = 0.0; left = playing = 0
    for e in starters:
        p, act, prj = entry_info(e, sp)
        frac = fr(p, act)
        if frac >= 1: left += 1
        elif frac > 0: playing += 1
        pace_w = 0.5 * (1 - frac)              # trust the player's own pace more as his game goes on
        rate = prj if frac >= 1 or frac <= 0 else (1 - pace_w) * prj + pace_w * min(act / max(1e-6, 1 - frac), 3 * prj + 6)
        rem = rate * frac
        sd = scale * player_sd(p.get('defaultPositionId') or 0, prj)
        pts += act; proj += act + rem; var += sd * sd * frac
        aid = p['id']
        players_out.append([aid, p.get('defaultPositionId') or 0, p.get('proTeamId') or 0, round(act, 2), round(prj, 1),
                            nflbox.calc(box.get(aid), scoring) if aid > 0 else 0, p.get('fullName') or '', round(sd, 2)])
    return dict(pts=round(pts, 2), proj=round(proj, 1), var=round(var, 2), left=left, playing=playing, started=started)


def snapshot(cfg, D, wk_data, events, boxes, scoring, now, slot_counts=None):
    M = D['live']['machine']; y = M['y']; wk = M['played'] + 1
    if wk > M['reg']: return None
    sp = wk; h2h = cfg.get('seedTiebreak', 'h2h') != 'points'
    name = {t['tid']: t for t in M['teams']}
    pre = {(g[1], g[2]): g[3] for g in M['games'] if g[0] == wk}
    team_frac = {}
    for ev in events.values():
        for t in ev['teams']: team_frac[t] = ev['frac']
    box = {}
    for b in boxes.values(): box.update(b)
    sd = M['sd']
    # scale per-player spreads so a typical full lineup's spread equals the league's weekly spread
    full_var = []
    for s_ in wk_data.get('schedule') or []:
        if s_.get('matchupPeriodId') != wk or not s_.get('away'): continue
        for side in (s_['home'], s_['away']):
            R = side.get('rosterForCurrentScoringPeriod') or side.get('rosterForMatchupPeriod') or {}
            v = sum(player_sd(entry_info(e, sp)[0].get('defaultPositionId') or 0, entry_info(e, sp)[2]) ** 2
                    for e in R.get('entries') or [] if e.get('lineupSlotId') not in BENCH)
            if v: full_var.append(v)
    scale = sd / math.sqrt(sum(full_var) / len(full_var)) if full_var else 1.0
    games = []; fixed = {}; base = {}; lineups = {}
    for s_ in wk_data.get('schedule') or []:
        if s_.get('matchupPeriodId') != wk or not s_.get('away'): continue
        h, a = s_['home']['teamId'], s_['away']['teamId']
        lineups[h] = []; lineups[a] = []
        th = team_side(s_['home'], sp, team_frac, box, scoring, lineups[h], slot_counts, scale)
        ta = team_side(s_['away'], sp, team_frac, box, scoring, lineups[a], slot_counts, scale)
        done = th['left'] + th['playing'] + ta['left'] + ta['playing'] == 0 and bool(th['pts'] or ta['pts'])
        if s_.get('winner') in ('HOME', 'AWAY'): done = True
        rem_sd = math.sqrt(th['var'] + ta['var'])
        if done or rem_sd < 0.5:
            ph = 1.0 if th['pts'] > ta['pts'] else 0.0 if ta['pts'] > th['pts'] else 0.5
            if s_.get('winner') == 'HOME': ph = 1.0
            elif s_.get('winner') == 'AWAY': ph = 0.0
        else:
            ph = phi((th['proj'] - ta['proj']) / rem_sd)
        p0 = pre.get((h, a), 0.5)
        fixed[(h, a)] = (ph, th['proj'], ta['proj']); base[(h, a)] = (p0, name[h]['mu'], name[a]['mu'])
        status = 'final' if done else 'live' if th['playing'] + ta['playing'] else 'paused' if th['started'] or ta['started'] else 'pre'
        games.append(dict(h=h, a=a, hs=th['pts'], as_=ta['pts'], hp=th['proj'], ap=ta['proj'], hvar=th['var'], avar=ta['var'],
                          hwin=round(ph, 3), hwin0=round(p0, 3), hleft=th['left'] + th['playing'], aleft=ta['left'] + ta['playing'], status=status))
    if not games: return None
    o_live = simulate(M, wk, fixed, h2h, seed=wk); o_pre = simulate(M, wk, base, h2h, seed=wk)
    odds = [dict(tid=t, po=o_live[t]['po'], po0=o_pre[t]['po'], title=o_live[t]['title'], title0=o_pre[t]['title'],
                 div=o_live[t]['div'], bye=o_live[t]['bye']) for t in o_live]
    return dict(league=cfg['site']['slug'], y=y, wk=wk, updated=datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                started=any(g['status'] != 'pre' for g in games), final=all(g['status'] == 'final' for g in games),
                sd=sd, games=games, odds=odds, scoring=scoring, lineups={str(k): v for k, v in lineups.items()},
                events={k: dict(teams=v['teams'], frac=v['frac'], state=v['state'], date=v.get('date')) for k, v in events.items()})


def add_history(L, old, now):
    """Each game keeps its win-chance path for the week: [[minutes since epoch, home win chance, 'p' if before kickoff], ...]."""
    prev = {}
    if old and old.get('y') == L['y'] and old.get('wk') == L['wk']:
        prev = {f"{g['h']}-{g['a']}": g.get('hist') or [] for g in old.get('games', [])}
    t = int(now // 60)
    for g in L['games']:
        h = list(prev.get(f"{g['h']}-{g['a']}", []))
        tag = ['p'] if g['status'] == 'pre' else []
        if not h: h.append([t, g['hwin0'], 'p'])
        if h[-1][1] != g['hwin'] or t - h[-1][0] >= 30 or (len(h[-1]) > 2) != bool(tag):
            if g['status'] != 'final' or h[-1][1] != g['hwin']: h.append([t, g['hwin']] + tag)
        g['hist'] = h[-500:]


def same(a, b):
    strip = lambda x: {k: v for k, v in x.items() if k != 'updated'}
    return strip(a) == strip(b)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = lambda k, d=None: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
    cfg = json.load(open(args[0])); out_p = args[1]
    D = json.load(open(os.path.join(ROOT, cfg['site']['dir'], 'data.json')))
    if not D.get('live') or not D['live'].get('machine'):
        print(f"{cfg['name']}: no season in progress."); return
    M = D['live']['machine']; wk = M['played'] + 1; y = M['y']; lid = cfg['espn']['leagueId']
    if opt('--from'):
        wk_data = json.load(open(opt('--from'))); events = {}; boxes = {}
        scoring = nflbox.scoring_from_settings([{'statId': 3, 'points': .04}, {'statId': 4, 'points': 4}, {'statId': 53, 'points': 1}])
        L = snapshot(cfg, D, wk_data, events, boxes, scoring, float(opt('--now', time.time())))
        if L: json.dump(L, open(out_p, 'w'), separators=(',', ':')); print('wrote', out_p)
        return
    s2, swid = os.environ.get('ESPN_S2', '').strip(), os.environ.get('ESPN_SWID', '').strip()
    if not s2 or not swid: sys.exit('Set ESPN_S2 and ESPN_SWID.')
    if not swid.startswith('{'): swid = '{' + swid.strip('{}') + '}'
    get = make_get(f'espn_s2={s2}; SWID={swid}')
    league = f'{B}/seasons/{y}/segments/0/leagues/{lid}'
    st = get(f'{league}?view=mSettings')
    scoring = nflbox.scoring_from_settings((st.get('settings') or {}).get('scoringSettings', {}).get('scoringItems'))
    slot_counts = ((st.get('settings') or {}).get('rosterSettings') or {}).get('lineupSlotCounts') or {}
    loop_until = time.time() + 60 * float(opt('--loop', 0)); every = float(opt('--every', 180)); after = opt('--after')
    final_boxes = {}
    while True:
        now = time.time()
        try:
            events = nflbox.scoreboard(y, wk)
        except Exception as e:
            print('scoreboard unavailable:', e); events = {}
        boxes = {}
        for eid, ev in events.items():
            if ev['state'] == 'pre': continue
            if eid in final_boxes: boxes[eid] = final_boxes[eid]; continue
            try:
                boxes[eid] = nflbox.box(eid)
                if ev['state'] == 'post': final_boxes[eid] = boxes[eid]
            except Exception as e:
                print('box score unavailable for', eid, e)
        wk_data = get(f'{league}?view=mMatchupScore&view=mBoxscore&view=mScoreboard&scoringPeriodId={wk}')
        L = snapshot(cfg, D, wk_data, events, boxes, scoring, now, slot_counts)
        if L:
            old = json.load(open(out_p)) if os.path.exists(out_p) else None
            add_history(L, old, now)
            if old and same(old, L):
                print(time.strftime('%H:%M:%S'), 'no change')
            else:
                json.dump(L, open(out_p, 'w'), separators=(',', ':'))
                print(time.strftime('%H:%M:%S'), f"{cfg['name']} week {L['wk']}: " + '; '.join(f"{g['hs']}-{g['as_']} ({g['status']})" for g in L['games']))
                if after: subprocess.run(after, shell=True, check=False)
        on_now = any(ev['state'] == 'in' for ev in events.values())
        soon = any(ev['state'] == 'pre' and ev.get('date') and
                   0 <= (datetime.datetime.fromisoformat(ev['date'].replace('Z', '+00:00')).timestamp() - time.time()) < 3600
                   for ev in events.values())
        if time.time() + every > loop_until or not (on_now or soon):
            break
        time.sleep(every)


if __name__ == '__main__':
    main()
