"""Build data.json for a league almanac from raw/<year>.json season exports.

Usage: python3 build.py RAW_DIR OUT_FILE [LEAGUE_CONFIG]
LEAGUE_CONFIG defaults to league.json next to this script. Everything league-specific (seats, year cutoffs,
one-off cards, branding) lives there; this file is shared by every league.
"""
import json, os, sys, statistics as st, collections, math, datetime, re

RAW = sys.argv[1] if len(sys.argv) > 1 else 'raw'
OUT = sys.argv[2] if len(sys.argv) > 2 else 'data.json'
CFG = json.load(open(sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'league.json')))
CUT = CFG.get('cutoffs', {})
SEEDS_FROM = CUT.get('seedsFrom', 0)        # seeds shown / upsets counted from this season
PPR_FROM = CUT.get('pprFrom', 0)            # low-score records start here
EARLY_WEEKS = CUT.get('earlyWeeks', 6)      # "early" = Weeks 1..EARLY_WEEKS
LADDER = bool(CFG.get('losersLadder'))      # simulate last place through the 12-team losers' ladder
BRIDESMAID = (CFG.get('oneOffs') or {}).get('bridesmaid')
TITLE_NOUN = CFG.get('titleNoun') or CFG.get('name', 'league')
PW = CFG.get('pointsWildcard') or {}        # {"from": year, "spots": n}: the last n playoff spots go to the top scorers outside the top records
def pw_for(y): return PW.get('spots', 0) if PW and y >= PW.get('from', 9999) else 0

# ---------------------------------------------------------------- franchises
FR = [tuple(f) for f in CFG['franchises']]  # key, full label, short label, owner names that identify the seat
LABEL = {k: l for k, l, s, n in FR}
SHORT = {k: s for k, l, s, n in FR}
NICE = dict(CFG.get('niceNames') or {})

def fkey(owners):
    low = [o.lower() for o in owners]
    for k, l, s, names in FR:
        if any(n in low for n in names):
            return k
    k = re.sub('[^a-z]', '', (low[0].split() or ['x'])[-1]) or 'unknown'
    if k not in LABEL:
        LABEL[k] = owners[0]; SHORT[k] = owners[0].split()[0]
    return k

def slabel(owners):
    out = []
    for o in owners:
        n = NICE.get(o.lower(), o)
        if n and n not in out: out.append(n)
    return ' & '.join(out) or '?'

def sshort(owners):
    out = []
    for o in owners:
        n = NICE.get(o.lower(), o).split()[0]
        if n not in out: out.append(n)
    return ' & '.join(out)

def rank_teams(tids, W, PF, H, G):
    """ESPN's order for this league: wins; ties go to head-to-head win % among the tied teams when every pair
    of them has played the same number of times, otherwise to points. Re-applied after each team is placed.
    Reproduces ESPN's full 1-12 order for 2013-2024 and the live 2026 standings."""
    import itertools
    out = []; by = collections.defaultdict(list)
    for t in tids: by[W[t]].append(t)
    for w in sorted(by, reverse=True):
        grp = list(by[w])
        while grp:
            if len(grp) == 1: out += grp; break
            cnts = {G.get(frozenset((a, b)), 0) for a, b in itertools.combinations(grp, 2)}
            if SEED_H2H and len(cnts) == 1 and 0 not in cnts:
                def key(t):
                    ww = sum(H.get((t, o), 0) for o in grp if o != t); ll = sum(H.get((o, t), 0) for o in grp if o != t)
                    return (-(ww / (ww + ll) if ww + ll else .5), -PF[t])
            else:
                key = lambda t: -PF[t]
            first = min(grp, key=key); out.append(first); grp.remove(first)
    return out

def seed_teams(tids, divof, W, PF, H, G, po, pw=0):
    divs = collections.defaultdict(list)
    for t in tids: divs[divof[t]].append(t)
    if pw:  # top (po - pw) records, then the pw highest scorers among everyone else
        assert len(divs) <= 1, 'points wildcard with divisions is not modelled'
        order = rank_teams(tids, W, PF, H, G)
        top = order[:po - pw]; rest = [t for t in order if t not in top]
        wcs = sorted(rest, key=lambda t: -PF[t])[:pw]
        order = top + wcs + [t for t in rest if t not in wcs]
        return order[:po], set(), order
    if len(divs) > 1:
        dw = [rank_teams(ts, W, PF, H, G)[0] for ts in divs.values()]
        order = rank_teams(dw, W, PF, H, G)
        order += rank_teams([t for t in tids if t not in dw], W, PF, H, G)
        return order[:po], set(dw), order
    order = rank_teams(tids, W, PF, H, G)
    return order[:po], set(), order

def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"

# ---------------------------------------------------------------- load
seasons = []
for f in sorted(os.listdir(RAW)):
    if f.endswith('.json'):
        seasons.append(json.load(open(os.path.join(RAW, f))))
seasons.sort(key=lambda s: s['y'])
TIER = {'NONE': 0, 'WINNERS_BRACKET': 1}
CUR = [s for s in seasons if not s['done']]
CUR = CUR[-1] if CUR else None
# ESPN's tiebreak for equal records: head-to-head (H2H_RECORD) or straight to points (TOTAL_POINTS_SCORED)
SEED_H2H = (CUR or seasons[-1])['settings'].get('seeding') != 'TOTAL_POINTS_SCORED'

for s in seasons:
    s['tm'] = {t['id']: t for t in s['teams']}
    s['fk'] = {t['id']: fkey(t['owners']) for t in s['teams']}
    s['sl'] = {t['id']: slabel(t['owners']) for t in s['teams']}
    st_ = s['settings']
    s['two'] = (st_.get('poLen') or 1) > 1
    last_reg = st_['reg']
    played_upto = (s['curPeriod'] - 1) if not s['done'] else 99
    gl = []
    for mp, h, hs, a, as_, tier, win in s['games']:
        if mp > played_upto: continue
        if hs == 0 and as_ == 0: continue
        gl.append(dict(mp=mp, h=h, hs=hs, a=a, as_=as_, tier=TIER.get(tier, 2), tname=tier, div=(2 if (s['two'] and mp > last_reg) else 1)))
    s['g'] = gl
    s['played'] = max([g['mp'] for g in gl if g['tier'] == 0] or [0])
    # playoff field = every team that appears in the winners bracket; seeds re-numbered 1..n in ESPN's seed order
    pt = {x for g in gl if g['tier'] == 1 for x in (g['h'], g['a'])}
    s['poTeams'] = pt
    order = sorted(pt, key=lambda t: (s['tm'][t]['seed'] or 99))
    s['rseed'] = {t: i + 1 for i, t in enumerate(order)}

keys = sorted({k for s in seasons for k in s['fk'].values()}, key=lambda k: [f[0] for f in FR].index(k) if k in LABEL and k in [f[0] for f in FR] else 99)
done = [s for s in seasons if s['done']]

# ---------------------------------------------------------------- per-manager base
M = {k: dict(key=k, name=LABEL[k], short=SHORT[k], seasons=[], teamNames=[], finishes=[], titles=[], ru=[], last=[],
             w=0, l=0, t=0, pf=0.0, pa=0.0, g=0, pw=0, pl=0, po=[], divs=[], wcs=[], berths=[], champAs=[]) for k in keys}
h2h = collections.defaultdict(lambda: [0, 0, 0])
weekly = []   # regular-season single scores
games_flat = []
for s in seasons:
    y = s['y']
    for t in s['teams']:
        k = s['fk'][t['id']]; m = M[k]
        m['seasons'].append(y); m['teamNames'].append([y, t['name']])
        m['w'] += t['w']; m['l'] += t['l']; m['t'] += t['t']; m['pf'] += t['pf']; m['pa'] += t['pa']
        if s['done']:
            m['finishes'].append([y, t['rank'], len(s['teams'])])
            if t['rank'] == 1: m['titles'].append(y)
            if t['rank'] == 2: m['ru'].append(y)
            if t['rank'] == len(s['teams']): m['last'].append(y)
            if t['id'] in s['poTeams']: m['po'].append(y)
    for g in s['g']:
        if g['tier'] == 2: continue
        kh, ka = s['fk'][g['h']], s['fk'][g['a']]
        res = (g['hs'] > g['as_']) - (g['hs'] < g['as_'])
        h2h[(kh, ka)][0 if res > 0 else 1 if res < 0 else 2] += 1
        h2h[(ka, kh)][0 if res < 0 else 1 if res > 0 else 2] += 1
        if g['tier'] == 0:
            M[kh]['g'] += 1; M[ka]['g'] += 1
            for (tid, sc, oid, osc) in ((g['h'], g['hs'], g['a'], g['as_']), (g['a'], g['as_'], g['h'], g['hs'])):
                weekly.append(dict(y=y, wk=g['mp'], key=s['fk'][tid], mgr=s['sl'][tid], team=s['tm'][tid]['name'], pts=sc,
                                   opp=s['sl'][oid], oteam=s['tm'][oid]['name'], opts=osc, won=sc > osc))
            games_flat.append(dict(y=y, wk=g['mp'], hm=s['sl'][g['h']], hs=g['hs'], am=s['sl'][g['a']], as_=g['as_'],
                                   ht=s['tm'][g['h']]['name'], at=s['tm'][g['a']]['name']))
        else:
            if res > 0: M[kh]['pw'] += 1; M[ka]['pl'] += 1
            elif res < 0: M[ka]['pw'] += 1; M[kh]['pl'] += 1

# divisions / wildcards
for s in done:
    po = s['settings']['po']
    divn = len(s['settings']['divisions'])
    if divn > 1:
        groups = collections.defaultdict(list)
        for t in s['teams']: groups[t['div']].append(t)
        winners = {min(ts, key=lambda t: t['seed'])['id'] for ts in groups.values()}
        for t in s['teams']:
            k = s['fk'][t['id']]
            if t['id'] in winners: M[k]['divs'].append(s['y'])
            elif t['id'] in s['poTeams']: M[k]['wcs'].append(s['y'])
            if t['rank'] == 1: M[k]['champAs'].append([s['y'], 'division' if t['id'] in winners else 'wildcard'])
        s['divWinners'] = winners
    else:
        for t in s['teams']:
            if t['id'] in s['poTeams']: M[s['fk'][t['id']]]['berths'].append(s['y'])
        s['divWinners'] = set()

# ---------------------------------------------------------------- all-play, luck, crowns, swing, clutch
allplay = collections.defaultdict(lambda: [0.0, 0])
season_luck = []
crowns = collections.Counter(); duds = collections.Counter()
rel = collections.defaultdict(list)
reg_scores = collections.defaultdict(list)
po_scores = collections.defaultdict(list)
for s in seasons:
    y = s['y']
    reg = [g for g in s['g'] if g['tier'] == 0]
    if not reg: continue
    sl = collections.defaultdict(lambda: [0.0, 0.0])
    for wk in sorted({g['mp'] for g in reg}):
        sc = {}
        for g in reg:
            if g['mp'] == wk: sc[g['h']] = g['hs']; sc[g['a']] = g['as_']
        n = len(sc); avg = st.mean(sc.values())
        crowns[s['fk'][max(sc, key=sc.get)]] += 1; duds[s['fk'][min(sc, key=sc.get)]] += 1
        for t, v in sc.items():
            e = (sum(1 for o, ov in sc.items() if o != t and ov < v) + 0.5 * sum(1 for o, ov in sc.items() if o != t and ov == v)) / (n - 1)
            k = s['fk'][t]
            allplay[k][0] += e; allplay[k][1] += 1; sl[t][0] += e
            reg_scores[(k, y)].append(v)
            if s['settings']['ppr']: rel[k].append(v / avg)
    for g in reg:
        for a_, as_, b_, bs in ((g['h'], g['hs'], g['a'], g['as_']), (g['a'], g['as_'], g['h'], g['hs'])):
            if as_ > bs: sl[a_][1] += 1
            elif as_ == bs: sl[a_][1] += 0.5
    for t, (e, w) in sl.items():
        tt = s['tm'][t]
        season_luck.append(dict(y=y, key=s['fk'][t], mgr=s['sl'][t], team=tt['name'], w=tt['w'], l=tt['l'], exp=round(e, 2), luck=round(w - e, 2), rank=tt['rank'], done=s['done']))
    for g in s['g']:
        if g['tier'] == 1:
            po_scores[(s['fk'][g['h']], y)].append(g['hs'] / g['div'])
            po_scores[(s['fk'][g['a']], y)].append(g['as_'] / g['div'])

# ---------------------------------------------------------------- Elo
elo = {k: 1500.0 for k in keys}
peak = {k: [1500.0, None] for k in keys}
elo_hist = collections.defaultdict(list)
elo_week = {}
for s in seasons:
    for wk in sorted({g['mp'] for g in s['g'] if g['tier'] != 2}):
        for g in [g for g in s['g'] if g['mp'] == wk and g['tier'] != 2]:
            a, b = s['fk'][g['h']], s['fk'][g['a']]
            g['eh'], g['ea'] = elo[a], elo[b]
            ea = 1 / (1 + 10 ** ((elo[b] - elo[a]) / 400))
            res = 1 if g['hs'] > g['as_'] else 0 if g['hs'] < g['as_'] else 0.5
            K = 24 * (1.5 if g['tier'] == 1 else 1)
            elo[a] += K * (res - ea); elo[b] -= K * (res - ea)
            for k in (a, b):
                if elo[k] > peak[k][0]: peak[k] = [elo[k], [s['y'], wk]]
        elo_week[(s['y'], wk)] = dict(elo)
    for k in set(s['fk'].values()): elo_hist[k].append([s['y'], round(elo[k])])
    if s['done']:
        for k in elo: elo[k] = 1500 + 0.75 * (elo[k] - 1500)

# ---------------------------------------------------------------- streaks
seq = collections.defaultdict(list)
for s in seasons:
    for g in s['g']:
        if g['tier'] == 2: continue
        r = (g['hs'] > g['as_']) - (g['hs'] < g['as_'])
        seq[s['fk'][g['h']]].append(((s['y'], g['mp']), 'W' if r > 0 else 'L' if r < 0 else 'T'))
        seq[s['fk'][g['a']]].append(((s['y'], g['mp']), 'W' if r < 0 else 'L' if r > 0 else 'T'))
streaks = []
for k, lst in seq.items():
    lst.sort()
    for want in 'WL':
        best = cur = 0; start = bs = be = None
        for o, r in lst:
            if r == want:
                cur += 1
                if cur == 1: start = o
                if cur > best: best, bs, be = cur, start, o
            else: cur = 0
        streaks.append(dict(key=k, mgr=LABEL[k], kind=want, n=best, start=bs, end=be))

# ---------------------------------------------------------------- schedule swap
swap = collections.defaultdict(lambda: dict(w=0.0, exp=0.0, po=0, poExp=0.0))
swap_seasons = []
for s in done:
    reg = [g for g in s['g'] if g['tier'] == 0]
    score = collections.defaultdict(dict); opp = collections.defaultdict(dict)
    for g in reg:
        score[g['h']][g['mp']] = g['hs']; score[g['a']][g['mp']] = g['as_']; opp[g['h']][g['mp']] = g['a']; opp[g['a']][g['mp']] = g['h']
    weeks = sorted({g['mp'] for g in reg}); teams = list(s['tm'])
    def wins(t, sched_of):
        w = 0.0
        for wk in weeks:
            o = opp[sched_of][wk]
            if o == t: o = sched_of
            w += 1 if score[t][wk] > score[o][wk] else 0.5 if score[t][wk] == score[o][wk] else 0
        return w
    actual = {t: wins(t, t) for t in teams}
    po = s['settings']['po']
    for t in teams:
        recs = [wins(t, b) for b in teams]
        kpw = pw_for(s['y'])
        def makes(w):
            if not kpw:
                return sum(1 for o in teams if o != t and (actual[o], s['tm'][o]['pf']) > (w, s['tm'][t]['pf'])) < po
            if sum(1 for o in teams if o != t and (actual[o], s['tm'][o]['pf']) > (w, s['tm'][t]['pf'])) < po - kpw: return True
            ranked = sorted([o for o in teams if o != t], key=lambda o: (-actual[o], -s['tm'][o]['pf']))
            return sum(1 for o in ranked[po - kpw:] if s['tm'][o]['pf'] > s['tm'][t]['pf']) < kpw  # points don't depend on the schedule
        made = 1 if t in s['poTeams'] else 0
        # own schedule uses what actually happened (ESPN's tiebreakers), the other 11 use wins then points
        pm = st.mean((made if b == t else (1 if makes(w) else 0)) for b, w in zip(teams, recs))
        k = s['fk'][t]; f = swap[k]
        f['w'] += actual[t]; f['exp'] += st.mean(recs); f['po'] += made; f['poExp'] += pm
        tt = s['tm'][t]
        swap_seasons.append(dict(y=s['y'], key=k, mgr=s['sl'][t], w=tt['w'], l=tt['l'], exp=round(st.mean(recs), 2), made=made, pmake=round(pm, 2)))

# ---------------------------------------------------------------- weekly lineups: bench, legends, player-weeks, rosters
ELIG_ORDER = ['0', '2', '4', '6', '16', '17', '23', '7']
def optimal(entries, slots):
    """Best possible lineup. Greedy fill by slot type is exact except for players eligible at two positional
    slots (QB/TE, RB/WR), so those few are tried in every position and the best total is kept."""
    import itertools
    def elig(e):
        el = set(e[3].split('.')) if e[3] else set()
        if el & {'2', '4', '6'}: el.add('23')  # FLEX takes any RB, WR or TE (ESPN slot 23 is dropped from eligibility lists)
        if len(e) > 1 and e[1] not in (20, 21, -1, None): el.add(str(e[1]))  # a slot he actually started in (e.g. Taysom Hill at TE)
        return el
    pool = sorted([(e[2], e[0], elig(e)) for e in entries], key=lambda x: -x[0])
    types = [sid for sid in ELIG_ORDER if int(slots.get(sid, 0)) > 0 and sid not in ('23', '7')]
    multi = [i for i, (_, _, el) in enumerate(pool) if len(el & set(types)) > 1][:6]
    def greedy(pl):
        used = set(); total = 0.0
        for sid in ELIG_ORDER:
            for _ in range(int(slots.get(sid, 0))):
                for k, (pts, pid, el) in enumerate(pl):
                    if k in used or sid not in el: continue
                    used.add(k); total += pts; break
        return total
    best = greedy(pool)
    for combo in itertools.product(*[sorted(pool[i][2] & set(types)) + [None] for i in multi]):
        pl = list(pool)
        for i, ch in zip(multi, combo):
            pts, pid, el = pl[i]
            pl[i] = (pts, pid, (el - set(types)) | ({ch} if ch else set()))
        best = max(best, greedy(pl))
    return best

bench = collections.defaultdict(lambda: [0.0, 0.0, 0])  # k -> actual, optimal, weeks
bench_season = collections.defaultdict(lambda: [0.0, 0.0, 0])
bench_weeks = []; self_losses = collections.Counter(); self_loss_list = []
legend = collections.defaultdict(lambda: [0.0, 0, set()])  # (k,pid) -> pts, starts, years
player_weeks = []
rosters = {}  # (y, mp, tid) -> set(pids)  (full rosters only)
started = collections.defaultdict(float)  # (y, tid, pid, mp) -> pts
names = {}
for s in seasons:
    y = s['y']; P = s['players']
    for pid, v in P.items(): names[int(pid)] = v
    gmap = {}
    for g in s['g']:
        gmap[(g['mp'], g['h'])] = (g, g['a'], g['as_'], g['hs'])
        gmap[(g['mp'], g['a'])] = (g, g['h'], g['hs'], g['as_'])
    for mp, rows in s['weeks'].items():
        mp = int(mp)
        for tid, full, ents in rows:
            if (mp, tid) not in gmap: continue
            g, oid, osc, msc = gmap[(mp, tid)]
            if g['tier'] == 2: continue
            k = s['fk'][tid]
            starters = [e for e in ents if e[1] not in (20, 21)]
            for e in starters:
                L = legend[(k, e[0])]; L[0] += e[2]; L[1] += 1; L[2].add(y)
                if g['tier'] == 0 and not (s['two'] and mp > s['settings']['reg']):
                    nm = P.get(str(e[0]), ['?', '', 0, 0])
                    player_weeks.append(dict(y=y, wk=mp, key=k, mgr=s['sl'][tid], player=nm[0], pos=nm[1], pts=e[2]))
            if full:
                rosters[(y, mp, tid)] = {e[0] for e in ents}
                for e in starters: started[(y, tid, e[0], mp)] = e[2]
                act = sum(e[2] for e in starters)
                opt = optimal(ents, s['settings']['slots'])
                opt = max(opt, act)
                b = bench[k]; b[0] += act; b[1] += opt; b[2] += 1
                bs = bench_season[(k, y)]; bs[0] += act; bs[1] += opt; bs[2] += 1
                bench_weeks.append(dict(y=y, wk=mp, key=k, mgr=s['sl'][tid], team=s['tm'][tid]['name'], act=round(act, 2), opt=round(opt, 2), left=round(opt - act, 2), opp=s['sl'][oid], opts=osc, lost=msc < osc))
                if msc < osc and opt > osc:
                    self_losses[k] += 1
                    self_loss_list.append(dict(y=y, wk=mp, key=k, mgr=s['sl'][tid], act=round(act, 2), opt=round(opt, 2), opp=s['sl'][oid], opts=osc, playoff=g['tier'] == 1))

# ---------------------------------------------------------------- pickups and trades (full-roster seasons)
pickups = []
trades = []
for s in seasons:
    y = s['y']
    if not s['tx']: continue
    adds = {}; alladds = collections.defaultdict(list)
    for typ, sp, ts, tid, bid, items in s['tx']:
        if typ not in ('WAIVER', 'FREEAGENT'): continue
        for it, pid, frm, to in items:
            if it == 'ADD' and (to, pid) not in adds: adds[(to, pid)] = (sp, typ)
            if it == 'ADD': alladds[(to, pid)].append(sp)
    for (tid, pid), (sp, typ) in adds.items():
        pts = sum(v for (yy, tt, pp, mp), v in started.items() if yy == y and tt == tid and pp == pid and mp >= sp)
        starts = sum(1 for (yy, tt, pp, mp) in started if yy == y and tt == tid and pp == pid and mp >= sp)
        nm = s['players'].get(str(pid), names.get(pid, ['?', '', 0, 0]))
        pickups.append(dict(y=y, wk=sp, key=s['fk'][tid], mgr=s['sl'][tid], player=nm[0], pos=nm[1], pts=round(pts, 1), starts=starts, how='waivers' if typ == 'WAIVER' else 'free agency'))
    mps = sorted({mp for (yy, mp, tid) in rosters if yy == y})
    addset = {(to, pid): sp for (to, pid), (sp, typ) in adds.items()}
    moves = collections.defaultdict(list)
    for i in range(len(mps) - 1):
        a, b = mps[i], mps[i + 1]
        owner_a = {}
        for (yy, mp, tid), pids in rosters.items():
            if yy == y and mp == a:
                for p in pids: owner_a[p] = tid
        for (yy, mp, tid), pids in rosters.items():
            if yy != y or mp != b: continue
            for p in pids:
                if p in owner_a and owner_a[p] != tid:
                    if any(a <= sp_ <= b for sp_ in alladds.get((tid, p), [])): continue
                    moves[(b, tuple(sorted((owner_a[p], tid))))].append((p, owner_a[p], tid))
    for (wk, pair), mv in moves.items():
        sides = {}
        for tid in pair:
            got = [p for p, frm, to in mv if to == tid]
            pts = sum(v for (yy, tt, pp, mp), v in started.items() if yy == y and tt == tid and pp in got and mp >= wk)
            sides[tid] = dict(key=s['fk'][tid], mgr=s['sl'][tid], team=s['tm'][tid]['name'],
                              got=[[s['players'].get(str(p), names.get(p, ['?']))[0], s['players'].get(str(p), names.get(p, ['?', '']))[1]] for p in got], pts=round(pts, 1))
        a, b = pair
        if not sides[a]['got'] or not sides[b]['got']: continue
        trades.append(dict(y=y, wk=wk, a=sides[a], b=sides[b], winner=sides[a]['key'] if sides[a]['pts'] > sides[b]['pts'] else sides[b]['key']))
trade_counts = {s['y']: sum(t['tc'][2] for t in s['teams']) // 2 for s in seasons}

# ---------------------------------------------------------------- draft grades
draft_rows = []; draft_team = []
for s in seasons:
    y = s['y']; P = s['players']
    picks = sorted(s['draft'], key=lambda p: p[0])
    if not picks: continue
    # In an auction the pick number is only nomination order: rank by price instead, and call each block of
    # league-size price ranks a "round" (round 1 = the N most expensive buys), so steals and busts mean the same thing.
    auc = s['settings'].get('draftType') == 'AUCTION'
    if auc: picks = sorted(picks, key=lambda p: (-p[5], p[0]))
    nT = len(s['teams'])
    vals = [(P.get(str(p[3])) or names.get(p[3]) or ['?', '', 0, 0]) for p in picks]
    pts = [v[3] or 0 for v in vals]
    n = len(picks)
    rows = []
    for i, (p, v) in enumerate(zip(picks, vals)):
        lo, hi = max(0, i - 8), min(n, i + 9)
        exp = st.mean(pts[lo:hi])
        rows.append(dict(y=y, pick=p[0], rd=(i // nT + 1) if auc else p[1], tid=p[2], key=s['fk'].get(p[2]), mgr=s['sl'].get(p[2], '?'), player=v[0], pos=v[1], pts=pts[i], exp=round(exp, 1), val=round(pts[i] - exp, 1), keeper=p[4],
                         **({'bid': p[5], 'prank': i + 1} if auc else {})))
    # position finish rank
    by_pos = collections.defaultdict(list)
    for pid, pos, pp in s.get('ranked', []): by_pos[pos].append(pid)
    for r_, p in zip(rows, picks):
        lst = by_pos.get(r_['pos'], [])
        r_['posRank'] = (lst.index(p[3]) + 1) if p[3] in lst else None
    draft_rows += rows
    if s['done']:
        tot = collections.defaultdict(float)
        for r_ in rows: tot[r_['tid']] += r_['val']
        vals_ = list(tot.values()); mu = st.mean(vals_); sd = st.pstdev(vals_) or 1
        for tid, v in tot.items():
            z = (v - mu) / sd
            grade = 'A' if z >= 1 else 'B' if z >= 0.3 else 'C' if z > -0.3 else 'D' if z > -1 else 'F'
            draft_team.append(dict(y=y, key=s['fk'][tid], mgr=s['sl'][tid], val=round(v, 1), z=round(z, 2), grade=grade, rank=s['tm'][tid]['rank']))

# ---------------------------------------------------------------- auction market (auction-draft seasons only)
# Fair price in hindsight: rate every drafted player by points above replacement at his position (filling every
# starting slot league-wide, flex slots included), then hand out that year's actual prices in that order -- the most
# valuable player "should" have cost the highest price paid, and so on. Surplus = fair price - price paid.
FLEX_ELIG = {'7': {'QB', 'RB', 'WR', 'TE'}, '23': {'RB', 'WR', 'TE'}, '3': {'RB', 'WR'}, '5': {'WR', 'TE'}}
SLOT_POS = {'0': 'QB', '2': 'RB', '4': 'WR', '6': 'TE', '16': 'D/ST', '17': 'K'}
AUC_POS = ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST']
auction = None
auc_seasons = [s for s in seasons if s['settings'].get('draftType') == 'AUCTION' and s['draft']]
if auc_seasons:
    auction = dict(years=[], managers={}, bargains=[], overpays=[])
    a_rows = []          # every auction purchase, with fair price
    for s in auc_seasons:
        y = s['y']; nT = len(s['teams']); slots = s['settings']['slots']
        pool = sorted([r for r in s.get('ranked', []) if r[1] in AUC_POS], key=lambda r: -r[2])
        taken = set(); by_pos = collections.defaultdict(list)
        for pid, pos, pts in pool: by_pos[pos].append((pts, pid))
        for sid, pos in SLOT_POS.items():
            for pts, pid in by_pos[pos][:int(slots.get(sid, 0)) * nT]: taken.add(pid)
        for sid, elig in FLEX_ELIG.items():
            need = int(slots.get(sid, 0)) * nT
            for pid, pos, pts in pool:
                if need <= 0: break
                if pos in elig and pid not in taken: taken.add(pid); need -= 1
        repl = {pos: next((pts for pts, pid in by_pos[pos] if pid not in taken), 0) for pos in AUC_POS}
        rows = [r_ for r_ in draft_rows if r_['y'] == y]
        for r_ in rows: r_['vor'] = round(r_['pts'] - repl.get(r_['pos'], 0), 1)
        prices = sorted((r_['bid'] for r_ in rows), reverse=True)
        for r_, fair in zip(sorted(rows, key=lambda r_: (-r_['vor'], -r_['pts'], r_['prank'])), prices):
            r_['fair'] = fair; r_['surp'] = fair - r_['bid']
        a_rows += rows
        # price index: the n-th highest price paid at a position
        nth = lambda pos, n: (sorted((r_['bid'] for r_ in rows if r_['pos'] == pos), reverse=True) + [0] * n)[n - 1]
        index = dict(top=prices[0], QB1=nth('QB', 1), QB5=nth('QB', 5), RB1=nth('RB', 1), RB5=nth('RB', 5), RB10=nth('RB', 10),
                     WR1=nth('WR', 1), WR5=nth('WR', 5), WR10=nth('WR', 10), TE1=nth('TE', 1), ones=sum(1 for p in prices if p == 1))
        spent_all = sum(prices) or 1
        pos_eff = []
        for pos in AUC_POS:
            pr = [r_ for r_ in rows if r_['pos'] == pos]
            if not pr: continue
            sp_ = sum(r_['bid'] for r_ in pr); pt_ = sum(r_['pts'] for r_ in pr); vo_ = sum(max(0, r_['vor']) for r_ in pr)
            pos_eff.append(dict(pos=pos, n=len(pr), spent=sp_, share=round(sp_ / spent_all, 3), pts=round(pt_, 1), ppd=round(pt_ / max(1, sp_), 2),
                                vpd=round(vo_ / max(1, sp_), 2), surp=sum(r_['surp'] for r_ in pr)))
        teams_ = []
        for t in s['teams']:
            mine = [r_ for r_ in rows if r_['tid'] == t['id']]
            if not mine: continue
            sp_ = sum(r_['bid'] for r_ in mine); bids = sorted((r_['bid'] for r_ in mine), reverse=True)
            teams_.append(dict(tid=t['id'], key=s['fk'][t['id']], mgr=s['sl'][t['id']], team=t['name'], spent=sp_, fair=sum(r_['fair'] for r_ in mine),
                               surp=sum(r_['surp'] for r_ in mine), pts=round(sum(r_['pts'] for r_ in mine), 1),
                               ppd=round(sum(r_['pts'] for r_ in mine) / max(1, sp_), 2), top2=round(sum(bids[:2]) / max(1, sp_), 3),
                               rank=t['rank'] if s['done'] else None, w=t['w'], l=t['l']))
        teams_.sort(key=lambda x: -x['surp'])
        auction['years'].append(dict(y=y, done=s['done'], index=index, pos=pos_eff, teams=teams_, repl={k: round(v, 1) for k, v in repl.items()}))
    # careers
    done_rows = [r_ for r_ in a_rows if any(x['y'] == r_['y'] and x['done'] for x in auc_seasons)]
    slim = lambda r_: dict(y=r_['y'], key=r_['key'], mgr=r_['mgr'], player=r_['player'], pos=r_['pos'], bid=r_['bid'], fair=r_['fair'], surp=r_['surp'], pts=r_['pts'], keeper=r_['keeper'])
    for k in keys:
        mine = [r_ for r_ in a_rows if r_['key'] == k]
        if not mine: continue
        mdone = [r_ for r_ in mine if r_ in done_rows]
        yrs = sorted({r_['y'] for r_ in mine})
        tops = [ty['top2'] for yy in auction['years'] for ty in yy['teams'] if ty['key'] == k]
        sp_ = sum(r_['bid'] for r_ in mdone) or 1
        pos_sh = {pos: round(sum(r_['bid'] for r_ in mine if r_['pos'] == pos) / max(1, sum(r_['bid'] for r_ in mine)), 3) for pos in AUC_POS}
        guys = collections.defaultdict(list)
        for r_ in mine: guys[(r_['player'], r_['pos'])].append([r_['y'], r_['bid']])
        guys = sorted([dict(player=p, pos=q, buys=sorted(b)) for (p, q), b in guys.items() if len(b) >= 3], key=lambda g: (-len(g['buys']), -sum(x[1] for x in g['buys'])))[:6]
        auction['managers'][k] = dict(
            years=len(yrs), spent=sum(r_['bid'] for r_ in mdone), pts=round(sum(r_['pts'] for r_ in mdone), 1),
            ppd=round(sum(r_['pts'] for r_ in mdone) / sp_, 2), surp=sum(r_['surp'] for r_ in mdone),
            top2=round(st.mean(tops), 3) if tops else None, pos=pos_sh,
            biggest=slim(max(mine, key=lambda r_: (r_['bid'], -r_['y']))),
            best=slim(max(mdone, key=lambda r_: r_['surp'])) if mdone else None,
            worst=slim(min(mdone, key=lambda r_: r_['surp'])) if mdone else None, guys=guys)
    # style label from the league's own spread of top-two shares (thirds)
    shares = sorted(m['top2'] for m in auction['managers'].values() if m['top2'] is not None)
    if shares:
        lo, hi = shares[len(shares) // 3], shares[(2 * len(shares)) // 3]
        for m in auction['managers'].values():
            if m['top2'] is None: continue
            m['style'] = 'More top-heavy than most' if m['top2'] >= hi else 'More spread out than most' if m['top2'] < lo else 'Typical for the league'
    auction['bargains'] = [slim(r_) for r_ in sorted(done_rows, key=lambda r_: -r_['surp'])[:10]]
    auction['overpays'] = [slim(r_) for r_ in sorted(done_rows, key=lambda r_: r_['surp'])[:10]]
    auction['budget'] = max(sum(r_['bid'] for r_ in a_rows if r_['y'] == yy and r_['tid'] == tt) for yy, tt in {(r_['y'], r_['tid']) for r_ in a_rows})

# ---------------------------------------------------------------- per-season extras: bracket, race, champ roster, sacko, headline
upsets = []; sacko = []; season_out = []
title_count = collections.Counter()
for s in seasons:
    y = s['y']; tm = s['tm']; po = s['settings']['po']; reg = s['settings']['reg']
    seed = {t['id']: s['rseed'].get(t['id'], 0) for t in s['teams']}
    rows = []
    for t in s['teams']:
        status = ''
        if s['done']:
            if t['rank'] == 1: status = 'champ'
            elif t['rank'] == len(s['teams']): status = 'last'
            if t['id'] in s['poTeams']:
                status += (' div' if t['id'] in s['divWinners'] else ' wc' if s['divWinners'] else ' po')
        rows.append(dict(tid=t['id'], team=t['name'], key=s['fk'][t['id']], mgr=s['sl'][t['id']], w=t['w'], l=t['l'], t=t['t'], pf=t['pf'], pa=t['pa'], rank=t['rank'], seed=s['rseed'].get(t['id'], 0), div=t['div'], status=status.strip(), tc=t['tc']))
    rows.sort(key=(lambda r: (r['rank'] or 99)) if s['done'] else (lambda r: (-(r['w'] + r['t'] / 2), -r['pf'])))
    # bracket
    wb = [g for g in s['g'] if g['tier'] == 1]
    rounds = []
    for mp in sorted({g['mp'] for g in wb}):
        rg = []
        for g in [g for g in wb if g['mp'] == mp]:
            hw = g['hs'] > g['as_']
            rg.append(dict(h=g['h'], a=g['a'], hs=g['hs'], as_=g['as_'], hseed=seed[g['h']], aseed=seed[g['a']], win=g['h'] if hw else g['a']))
            ws, ls = (seed[g['h']], seed[g['a']]) if hw else (seed[g['a']], seed[g['h']])
            if ws > ls:
                wt, lt = (g['h'], g['a']) if hw else (g['a'], g['h'])
                if s['y'] >= SEEDS_FROM: upsets.append(dict(y=y, mp=mp, final=(mp == max(x['mp'] for x in wb)), wseed=ws, lseed=ls, w=s['sl'][wt], l=s['sl'][lt], wkey=s['fk'][wt], lkey=s['fk'][lt], ws=max(g['hs'], g['as_']) / g['div'], ls=min(g['hs'], g['as_']) / g['div']))
        rg.sort(key=lambda m: min(m['hseed'], m['aseed']))
        rounds.append(rg)
    byes = []
    if rounds:
        r1 = {m['h'] for m in rounds[0]} | {m['a'] for m in rounds[0]}
        byes = sorted([t for t in s['poTeams'] if t not in r1], key=lambda t: seed[t])
    # race
    race = {t['id']: [] for t in s['teams']}
    W = collections.Counter(); PF = collections.Counter()
    for wk in range(1, (s['played'] if not s['done'] else reg) + 1):
        for g in [g for g in s['g'] if g['tier'] == 0 and g['mp'] == wk]:
            PF[g['h']] += g['hs']; PF[g['a']] += g['as_']
            if g['hs'] > g['as_']: W[g['h']] += 1
            elif g['as_'] > g['hs']: W[g['a']] += 1
            else: W[g['h']] += 0.5; W[g['a']] += 0.5
        order = sorted(race, key=lambda t: (-W[t], -PF[t]))
        for i, t in enumerate(order): race[t].append(i + 1)
    # final / champion roster
    final = None; champ_roster = []; champ_mvp = None
    champ = next((t for t in s['teams'] if t['rank'] == 1), None)
    if s['done'] and wb:
        fm = max(g['mp'] for g in wb)
        fg = [g for g in wb if g['mp'] == fm][0]
        wt, lt = (fg['h'], fg['a']) if fg['hs'] > fg['as_'] else (fg['a'], fg['h'])
        final = dict(w=tm[wt]['name'], l=tm[lt]['name'], wm=s['sl'][wt], lm=s['sl'][lt], ws=max(fg['hs'], fg['as_']), ls=min(fg['hs'], fg['as_']), two=fg['div'] == 2, wseed=seed[wt], lseed=seed[lt])
        rows_f = s['weeks'].get(str(fm)) or []
        ent = next((e for tid, full, e in rows_f if tid == champ['id']), None)
        P = s['players']
        if ent:
            champ_roster = [[P.get(str(e[0]), ['?', ''])[0], P.get(str(e[0]), ['?', ''])[1], e[2]] for e in ent if e[1] not in (20, 21)]
            champ_roster.sort(key=lambda x: -x[2]); s['champPts'] = True
        else:
            champ_roster = [[P.get(str(p), ['?', ''])[0], P.get(str(p), ['?', ''])[1], None] for p in champ['roster']]
        # season MVP for the champ: most started points
        cand = collections.Counter()
        for (yy, tid, pid, mp), v in started.items():
            if yy == y and tid == champ['id']: cand[pid] += v
        if not cand:
            for mp, rws in s['weeks'].items():
                for tid, full, e in rws:
                    if tid == champ['id']:
                        for x in e:
                            if x[1] not in (20, 21): cand[x[0]] += x[2]
        if cand:
            pid, v = cand.most_common(1)[0]; champ_mvp = [P.get(str(pid), ['?', ''])[0], P.get(str(pid), ['?', ''])[1], round(v, 1)]
    # sacko
    if s['done']:
        lastt = next(t for t in s['teams'] if t['rank'] == len(s['teams']))
        lg = [g for g in s['g'] if g['tier'] == 2 and lastt['id'] in (g['h'], g['a']) and g['tname'] == 'LOSERS_CONSOLATION_LADDER']
        sg = None
        if lg:
            g = max(lg, key=lambda g: g['mp']); o = g['a'] if g['h'] == lastt['id'] else g['h']
            sg = dict(opp=s['sl'][o], ms=(g['hs'] if g['h'] == lastt['id'] else g['as_']) / g['div'], os=(g['as_'] if g['h'] == lastt['id'] else g['hs']) / g['div'])
        sacko.append(dict(y=y, key=s['fk'][lastt['id']], mgr=s['sl'][lastt['id']], team=lastt['name'], w=lastt['w'], l=lastt['l'], pf=lastt['pf'], game=sg))
    # headline
    headline = ''
    if s['done'] and champ:
        ck = s['fk'][champ['id']]; title_count[ck] += 1
        n = title_count[ck]
        nth = {1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth'}.get(n, ordinal(n))
        cs = sshort(s['tm'][champ['id']]['owners'])
        bits = [f"{cs} {'win' if '&' in cs else 'wins'} {'the first ' + TITLE_NOUN + ' title' if y == seasons[0]['y'] else nth + ' title'}"]
        if seed.get(champ['id'], 0) >= 4 and s['y'] >= SEEDS_FROM: bits[0] += f" from the No. {seed[champ['id']]} seed"
        best = max(s['teams'], key=lambda t: (t['w'] - t['l'], t['pf']))
        if best['id'] != champ['id'] and best['w'] - best['l'] >= 8:
            bs_ = sshort(best['owners'])
            bits.append(f"{bs_} {'go' if '&' in bs_ else 'goes'} {best['w']}–{best['l']} and {'finish' if '&' in bs_ else 'finishes'} {ordinal(best['rank'])}")
        elif final and final['lm']:
            lk = next(s['fk'][t['id']] for t in s['teams'] if t['name'] == final['l'])
            if BRIDESMAID and lk == BRIDESMAID and y in M[BRIDESMAID]['ru']:
                c = sum(1 for yy in M[BRIDESMAID]['ru'] if yy <= y)
                if c >= 3: bits.append(f"{SHORT[BRIDESMAID]}'s {ordinal(c)} runner-up finish")
        headline = '; '.join(bits)
    elif not s['done']:
        headline = f"In progress through Week {s['played']}"
    # division standings
    divs = []
    if len(s['settings']['divisions']) > 1:
        dn = dict((d[0], d[1]) for d in s['settings']['divisions'])
        for did in sorted({t['div'] for t in s['teams']}):
            ts = sorted([r for r in rows if r['div'] == did], key=lambda r: (-(r['w'] - r['l']), -r['pf']))
            lead = (next((r['tid'] for r in ts if r['tid'] in s['divWinners']), None) if s['done'] else ts[0]['tid'])
            divs.append(dict(name=dn.get(did, f'Division {did}'), teams=[dict(r, lead=(r['tid'] == lead)) for r in ts]))
    # top weekly score per week
    weeks_best = []
    for wk in sorted({g['mp'] for g in s['g'] if g['tier'] == 0}):
        sc = [(g['hs'], g['h']) for g in s['g'] if g['mp'] == wk and g['tier'] == 0] + [(g['as_'], g['a']) for g in s['g'] if g['mp'] == wk and g['tier'] == 0]
        hi = max(sc); lo = min(sc)
        weeks_best.append([wk, s['sl'][hi[1]], hi[0], s['sl'][lo[1]], lo[0]])
    # schedule-swap grid (every team on every schedule) and week-by-week all-play, for completed regular-season weeks
    pl_ = [g for g in s['g'] if g['tier'] == 0 and (s['done'] or g['mp'] <= s['played'])]
    swap_grid = None
    if pl_:
        scr = collections.defaultdict(dict); opp_ = collections.defaultdict(dict)
        for g in pl_:
            scr[g['h']][g['mp']] = g['hs']; scr[g['a']][g['mp']] = g['as_']; opp_[g['h']][g['mp']] = g['a']; opp_[g['a']][g['mp']] = g['h']
        wks_ = sorted({g['mp'] for g in pl_}); order_ = [r['tid'] for r in rows]
        espn_w = {(g[0], frozenset((g[1], g[3]))): (g[1] if g[6] == 'HOME' else g[3] if g[6] == 'AWAY' else None) for g in s['games'] if g[2] == g[4]}
        def res_(a, b, wk):  # a tie that actually happened uses ESPN's tiebreak winner
            if scr[a][wk] != scr[b][wk]: return 1 if scr[a][wk] > scr[b][wk] else 0
            ew = espn_w.get((wk, frozenset((a, b))))
            return 0.5 if ew is None else (1 if ew == a else 0)
        def on_sched(t, b):
            w = 0.0; n = 0
            for wk in wks_:
                o = opp_[b].get(wk)
                if o is None or wk not in scr[t]: continue
                if o == t: o = b
                w += res_(t, o, wk); n += 1
            return w, n
        grid = []; ngrid = 0
        for t in order_:
            row_ = []
            for b in order_:
                w, n = on_sched(t, b); row_.append(w); ngrid = max(ngrid, n)
            grid.append(row_)
        apw = [[sum(res_(t, o, wk) for o in scr if o != t and wk in scr[o]) if wk in scr[t] else None for wk in wks_] for t in order_]
        swap_grid = dict(order=order_, wks=wks_, n=ngrid, opps=len(order_) - 1, m=grid, ap=apw)
    season_out.append(dict(
        y=y, done=s['done'], swap=swap_grid, teams=len(s['teams']), ppr=s['settings']['ppr'], po=po, reg=reg, two=s['two'], played=s['played'],
        headline=headline, rows=rows, rounds=rounds, byes=byes, race={str(k): v for k, v in race.items()}, final=final,
        champRoster=champ_roster, champMvp=champ_mvp, divs=divs, weeks=weeks_best,
        games=[[g['mp'], g['h'], g['hs'], g['a'], g['as_'], g['tier']] for g in s['g'] if g['tier'] != 2],
        draft=[dict(**({'bid': r_['bid'], 'prank': r_['prank'], 'fair': r_.get('fair'), 'surp': r_.get('surp')} if 'bid' in r_ else {}), pick=r_['pick'], rd=r_['rd'], tid=r_['tid'], key=r_['key'], mgr=r_['mgr'], player=r_['player'], pos=r_['pos'], pts=r_['pts'], posRank=r_['posRank'], val=r_['val'], keeper=r_['keeper']) for r_ in draft_rows if r_['y'] == y],
        draftGrades=[d for d in draft_team if d['y'] == y],
        trades=trade_counts.get(y, 0), hasLineups=bool(s['weeks']), hasBench=bool(s['tx']),
    ))

# ---------------------------------------------------------------- rivalries & eras
pairs = collections.defaultdict(lambda: dict(n=0, w=0, l=0, t=0, m=[], po=0, last=None))
for s in seasons:
    for g in s['g']:
        if g['tier'] == 2: continue
        a, b = sorted((s['fk'][g['h']], s['fk'][g['a']]))
        sa, sb = (g['hs'], g['as_']) if s['fk'][g['h']] == a else (g['as_'], g['hs'])
        p = pairs[(a, b)]; p['n'] += 1; p['m'].append(abs(sa - sb) / g['div'])
        if sa > sb: p['w'] += 1
        elif sb > sa: p['l'] += 1
        else: p['t'] += 1
        if g['tier'] == 1: p['po'] += 1
        p['last'] = [s['y'], g['mp']]
riv = []
for (a, b), p in pairs.items():
    close = sum(1 for x in p['m'] if x < 10)
    idx = p['n'] * (1 - abs(p['w'] - p['l']) / p['n']) + 3 * p['po'] + close
    riv.append(dict(a=a, b=b, n=p['n'], w=p['w'], l=p['l'], t=p['t'], po=p['po'], margin=round(st.mean(p['m']), 1), close=close, idx=round(idx, 1), last=p['last']))
riv.sort(key=lambda r: -r['idx'])

per = collections.defaultdict(dict)
for x in season_luck:
    if x['done']: per[x['key']][x['y']] = x
ap_season = collections.defaultdict(dict)
for s in done:
    reg = [g for g in s['g'] if g['tier'] == 0]
    for t in s['tm']:
        ap_season[s['fk'][t]][s['y']] = dict(g=len([1 for g in reg if t in (g['h'], g['a'])]), lbl=s['sl'][t])
eras = []
for k, ys in per.items():
    yrs = sorted(ys)
    for i in range(len(yrs) - 2):
        span = yrs[i:i + 3]
        if span[2] - span[0] != 2: continue
        g = sum(ap_season[k][y]['g'] for y in span)
        lbls = []
        for y in span:
            if ap_season[k][y]['lbl'] not in lbls: lbls.append(ap_season[k][y]['lbl'])
        eras.append(dict(key=k, mgr=' / '.join(lbls), start=span[0], end=span[2], allpct=round(sum(ys[y]['exp'] for y in span) / g, 3),
                         w=sum(ys[y]['w'] for y in span), l=sum(ys[y]['l'] for y in span), finishes=[ys[y]['rank'] for y in span]))
def best_per(lst):
    out, seen = [], set()
    for e in lst:
        if e['key'] in seen: continue
        seen.add(e['key']); out.append(e)
    return out
eras_best = best_per(sorted(eras, key=lambda e: -e['allpct']))[:8]
eras_dark = best_per(sorted(eras, key=lambda e: e['allpct']))[:5]

# ---------------------------------------------------------------- timeline of rule changes
timeline = []
prev = None
NUMW = {2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six'}
for s in seasons:
    stt = s['settings']; y = s['y']; ev = []
    if prev is None:
        ev.append(f"League founded on ESPN with {len(s['teams'])} teams, {'half-point PPR' if stt['ppr'] == 0.5 else 'PPR' if stt['ppr'] else 'standard'} scoring and a {stt['po']}-team playoff.")
    else:
        p, pt = prev['settings'], len(prev['teams'])
        if len(s['teams']) != pt: ev.append(f"{'Expands' if len(s['teams']) > pt else 'Contracts'} from {pt} to {len(s['teams'])} teams.")
        if stt['ppr'] != p['ppr']: ev.append('Switches to full PPR.' if stt['ppr'] == 1 else f"Scoring changes to {stt['ppr']} per reception.")
        if stt['po'] != p['po']: ev.append(f"Playoff field goes from {p['po']} to {stt['po']} teams.")
        if (stt.get('poLen') or 1) != (p.get('poLen') or 1): ev.append('Playoff rounds become two-week matchups.' if (stt.get('poLen') or 1) > 1 else 'Playoff rounds go back to one week each.')
        if len(stt['divisions']) > 1 and len(p['divisions']) <= 1: ev.append(f"{NUMW.get(len(stt['divisions']), str(len(stt['divisions'])))} divisions introduced: {', '.join(d[1] for d in stt['divisions'])}. Division winners take the top seeds.")
        if stt['reg'] != p['reg']: ev.append(f"Regular season goes from {p['reg']} to {stt['reg']} weeks.")
        if (stt.get('keepers') or 0) != (p.get('keepers') or 0): ev.append(f"Keepers introduced: {stt['keepers']} per team." if stt.get('keepers') else 'Keepers dropped.')
        if stt.get('vetoVotes') != p.get('vetoVotes') and stt.get('vetoVotes') is not None and p.get('vetoVotes') is not None: ev.append(f"Trade veto threshold changes from {p['vetoVotes']} to {stt['vetoVotes']} votes.")
        if stt.get('passTD') != p.get('passTD'): ev.append(f"Passing TDs change from {p.get('passTD')} to {stt.get('passTD')} points.")
    if ev: timeline.append(dict(y=y, events=ev))
    prev = s

# ---------------------------------------------------------------- close games, early/late splits, choke index
import random
CLOSE = 10.0
close = collections.defaultdict(lambda: [0, 0, 0])      # k -> w, l, t in games decided by < 10 (per week)
split = collections.defaultdict(lambda: [[0, 0], [0, 0]])  # k -> [[early w,l],[late w,l]]
close_season = []
for s in seasons:
    reg = s['settings']['reg']
    cs = collections.defaultdict(lambda: [0, 0])
    for g in s['g']:
        if g['tier'] == 2: continue
        m = abs(g['hs'] - g['as_']) / g['div']
        kh, ka = s['fk'][g['h']], s['fk'][g['a']]
        res = (g['hs'] > g['as_']) - (g['hs'] < g['as_'])
        if m < CLOSE:
            if res > 0: close[kh][0] += 1; close[ka][1] += 1; cs[g['h']][0] += 1; cs[g['a']][1] += 1
            elif res < 0: close[ka][0] += 1; close[kh][1] += 1; cs[g['a']][0] += 1; cs[g['h']][1] += 1
            else: close[kh][2] += 1; close[ka][2] += 1
        if g['tier'] == 0 and res != 0:
            half = 0 if g['mp'] <= EARLY_WEEKS else 1
            split[kh][half][0 if res > 0 else 1] += 1
            split[ka][half][0 if res < 0 else 1] += 1
    for tid, (w, l) in cs.items():
        if w + l >= 4:
            close_season.append(dict(y=s['y'], key=s['fk'][tid], mgr=s['sl'][tid], w=w, l=l, done=s['done']))

choke = collections.defaultdict(lambda: dict(fav=0, early=0, titles=0, years=[], exits=[]))
fav_titles = 0; fav_seasons = 0
for s in done:
    pt = s['poTeams']
    if not pt: continue
    fav = sorted(pt, key=lambda t: (-(s['tm'][t]['w'] + s['tm'][t]['t'] / 2), -s['tm'][t]['pf']))[:2]
    fav_seasons += 1
    for t in fav:
        k = s['fk'][t]; c = choke[k]
        c['fav'] += 1; c['years'].append(s['y'])
        first = min((g for g in s['g'] if g['tier'] == 1 and t in (g['h'], g['a'])), key=lambda g: g['mp'])
        won = (first['hs'] > first['as_']) == (first['h'] == t)
        if not won:
            c['early'] += 1
            o = first['a'] if first['h'] == t else first['h']
            c['exits'].append(dict(y=s['y'], opp=s['sl'][o], w=s['tm'][t]['w'], l=s['tm'][t]['l']))
        if s['tm'][t]['rank'] == 1: c['titles'] += 1; fav_titles += 1

# ---------------------------------------------------------------- weekly recaps (every week of every season)
recaps = {}
def nm(s, tid): return sshort(s['tm'][tid]['owners'])
def vb(name, one, many): return many if '&' in name else one
for s in seasons:
    y = s['y']; reg = s['settings']['reg']
    bw = {}
    for b in bench_weeks:
        if b['y'] == y: bw[(b['wk'], b['key'])] = b
    for wk in sorted({g['mp'] for g in s['g'] if g['tier'] != 2}):
        gs = [g for g in s['g'] if g['mp'] == wk and g['tier'] != 2]
        if not gs: continue
        po = gs[0]['tier'] == 1
        div = gs[0]['div']
        sides = []
        for g in gs:
            sides.append((g['hs'] / div, g['h'], g['as_'] / div, g['a'], g))
            sides.append((g['as_'] / div, g['a'], g['hs'] / div, g['h'], g))
        hi = max(sides, key=lambda x: x[0]); lo = min(sides, key=lambda x: x[0])
        lines = []
        label = ('Week %d' % wk) if wk <= reg else ({1: 'Final'}.get(max(x['mp'] for x in s['g'] if x['tier'] == 1) - wk + 1, 'Playoffs'))
        if po:
            rnd = max(x['mp'] for x in s['g'] if x['tier'] == 1) - wk
            label = 'Final' if rnd == 0 else 'Semifinals' if rnd == 1 else 'Quarterfinals'
        pw = ' a week' if div == 2 else ''
        lines.append(f"{nm(s, hi[1])} {'averaged' if div == 2 else 'put up'} the {'round' if div == 2 else 'week'}'s top score, {hi[0]:.1f}{pw}, {'beating' if hi[0] > hi[2] else 'and still losing to'} {nm(s, hi[3])}.")
        if not po:
            lines.append(f"{nm(s, lo[1])} brought up the rear with {lo[0]:.1f}{pw}.")
        blow = max(gs, key=lambda g: abs(g['hs'] - g['as_']))
        clos = min(gs, key=lambda g: abs(g['hs'] - g['as_']))
        def winlose(g):
            return (g['h'], g['hs'] / g['div'], g['a'], g['as_'] / g['div']) if g['hs'] > g['as_'] else (g['a'], g['as_'] / g['div'], g['h'], g['hs'] / g['div'])
        w_, ws_, l_, ls_ = winlose(clos)
        if abs(ws_ - ls_) < 5 and clos is not blow:
            lines.append(f"Nail-biter: {nm(s, w_)} edged {nm(s, l_)} {ws_:.1f}–{ls_:.1f}.")
        w_, ws_, l_, ls_ = winlose(blow)
        if abs(ws_ - ls_) >= 40:
            lines.append(f"Blowout of the week: {nm(s, w_)} over {nm(s, l_)} by {ws_ - ls_:.1f}.")
        # upset: winner with lower pre-game Elo, biggest gap
        ups = []
        for g in gs:
            if g['hs'] == g['as_']: continue
            hw = g['hs'] > g['as_']
            we, le = (g['eh'], g['ea']) if hw else (g['ea'], g['eh'])
            if le - we >= 40: ups.append((le - we, g))
        if ups:
            gap, g = max(ups, key=lambda x: x[0]); w_, ws_, l_, ls_ = winlose(g)
            lines.append(f"Upset alert: {nm(s, w_)} knocked off {nm(s, l_)}, rated {gap:.0f} Elo points higher.")
        # bench blunder
        blunders = [b for (wk_, k), b in bw.items() if wk_ == wk]
        if blunders:
            b = max(blunders, key=lambda b: b['left'])
            if b['left'] >= 25:
                cost = ' It cost them the game.' if b['lost'] and b['opt'] > b['opts'] else ''
                lines.append(f"Bench blunder: {sshort(b['mgr'].split(' & '))} left {b['left']:.1f} points on the bench.{cost}")
        # standings leader after regular-season weeks
        if not po:
            W = collections.Counter(); PF = collections.Counter()
            for g in s['g']:
                if g['tier'] == 0 and g['mp'] <= wk:
                    PF[g['h']] += g['hs']; PF[g['a']] += g['as_']
                    if g['hs'] > g['as_']: W[g['h']] += 1
                    elif g['as_'] > g['hs']: W[g['a']] += 1
            lead = max(s['tm'], key=lambda t: (W[t], PF[t]))
            unbeaten = [t for t in s['tm'] if W[t] == wk]
            winless = [t for t in s['tm'] if W[t] == 0]
            if len(unbeaten) and wk >= 3:
                lines.append(f"Still unbeaten: {', '.join(nm(s, t) for t in unbeaten)}.")
            else:
                lines.append(f"{nm(s, lead)} {vb(nm(s, lead), 'leads', 'lead')} the league at {W[lead]}–{wk - W[lead]}.")
            if winless and wk >= 3:
                lines.append(f"Still looking for a win: {', '.join(nm(s, t) for t in winless)}.")
        recaps[f"{y}-{wk}"] = dict(y=y, wk=wk, label=label, po=po, lines=lines,
                                   games=[[s['fk'][g['h']], round(g['hs'] / div, 2), s['fk'][g['a']], round(g['as_'] / div, 2)] for g in gs])

# ---------------------------------------------------------------- season awards (every season; the current one is a race)
awards = {}
for s_ in seasons:
    y = s_['y']; A = []
    wk_ = [w for w in weekly if w['y'] == y]
    if not wk_: continue
    def add(code, title, row, value, detail):
        A.append(dict(code=code, title=title, key=row['key'], mgr=row['mgr'], value=value, detail=detail))
    hi = max(wk_, key=lambda w: w['pts']); add('high', 'Top score', hi, f"{hi['pts']:.2f}", f"Week {hi['wk']} vs {hi['opp']}")
    lo = min([w for w in wk_ if w['pts'] > 0], key=lambda w: w['pts']); add('low', 'Dud of the year', lo, f"{lo['pts']:.2f}", f"Week {lo['wk']} vs {lo['opp']}")
    bw = max([w for w in wk_ if w['won']], key=lambda w: w['pts'] - w['opts']); add('blowout', 'Biggest beatdown', bw, f"+{bw['pts'] - bw['opts']:.1f}", f"Week {bw['wk']} over {bw['opp']}, {bw['pts']:.1f}–{bw['opts']:.1f}")
    hl = [w for w in wk_ if not w['won'] and w['pts'] < w['opts']]
    if hl:
        x = max(hl, key=lambda w: w['pts']); add('heartbreak', 'Highest-scoring loser', x, f"{x['pts']:.2f}", f"Week {x['wk']}, lost to {x['opp']} ({x['opts']:.1f})")
    rows = [dict(key=s_['fk'][t['id']], mgr=s_['sl'][t['id']], pf=t['pf'], pa=t['pa']) for t in s_['teams']]
    x = max(rows, key=lambda r: r['pf']); add('pf', 'Points champion', x, f"{x['pf']:.1f}", 'Most points scored')
    x = max(rows, key=lambda r: r['pa']); add('pa', 'Snakebitten', x, f"{x['pa']:.1f}", 'Most points scored against')
    sl_ = [z for z in season_luck if z['y'] == y]
    if sl_:
        x = max(sl_, key=lambda z: z['luck']); add('lucky', 'Luckiest', x, f"+{x['luck']:.1f}", f"{x['w']}–{x['l']}, scored like a {x['exp']:.1f}-win team")
        x = min(sl_, key=lambda z: z['luck']); add('unlucky', 'Unluckiest', x, f"{x['luck']:.1f}".replace('-', '−'), f"{x['w']}–{x['l']}, scored like a {x['exp']:.1f}-win team")
    pk = [p for p in pickups if p['y'] == y]
    if pk:
        x = max(pk, key=lambda p: p['pts']); add('pickup', 'Waiver wire king', x, f"{x['pts']:.1f}", f"{x['player']} ({x['pos']}), added Week {x['wk']}, points as a starter")
    bb = [b for b in bench_weeks if b['y'] == y]
    if bb:
        x = max(bb, key=lambda b: b['left']); add('bench', 'Bench blunder', x, f"{x['left']:.1f}", f"Week {x['wk']}: scored {x['act']:.1f}, best lineup was {x['opt']:.1f}" + (" — and lost" if x['lost'] and x['opt'] > x['opts'] else ''))
    dg = [d for d in draft_team if d['y'] == y]
    if dg:
        x = max(dg, key=lambda d: d['z']); add('draft', 'Best draft', x, x['grade'], f"{x['val']:+.0f} points above where they picked")
    awards[str(y)] = dict(final=s_['done'], list=A)

# ---------------------------------------------------------------- power rankings and odds (current season)
power = []; odds = []; clinch = None
if CUR:
    s = CUR; y = s['y']; reg = s['settings']['reg']; played = s['played']
    tids = list(s['tm'])
    # Season-only view. The one thing carried in is last season, and it fades as 2026 games pile up.
    # Checked on 154 team-seasons: last season predicts the rest of a season about as well as four weeks of games,
    # and a team's scoring edge carries over at roughly 20% (career history adds nothing beyond last season).
    PREV = next((x for x in reversed(seasons) if x['done'] and x['y'] < y), None)
    prior_ap = {}; prior_rel = {}
    if PREV:
        pk = {v: t for t, v in PREV['fk'].items()}; preg = PREV['settings']['reg']
        pw = collections.defaultdict(dict)
        for g in PREV['g']:
            if g['tier'] == 0 and g['mp'] <= preg: pw[g['mp']][g['h']] = g['hs']; pw[g['mp']][g['a']] = g['as_']
        allp = [v for ss in pw.values() for v in ss.values()]; pl = st.mean(allp)
        for t in tids:
            pt = pk.get(s['fk'][t])
            if pt is None: continue
            v = [(sum(1 for o, ov in ss.items() if o != pt and ov < ss[pt]) + 0.5 * sum(1 for o, ov in ss.items() if o != pt and ov == ss[pt])) / (len(ss) - 1) for ss in pw.values() if pt in ss]
            prior_ap[t] = st.mean(v); prior_rel[t] = st.mean([ss[pt] for ss in pw.values() if pt in ss]) / pl - 1
    PRIOR_WEEKS = 4; CARRY = 0.2; AP_K = 13.4; AP_C = 0.29
    for wk in range(1, played + 1):
        reg_g = [g for g in s['g'] if g['tier'] == 0 and g['mp'] <= wk]
        ap = collections.defaultdict(float); n = collections.Counter(); W = collections.Counter(); sc = collections.defaultdict(list)
        for w_ in range(1, wk + 1):
            ss = {}
            for g in reg_g:
                if g['mp'] == w_: ss[g['h']] = g['hs']; ss[g['a']] = g['as_']
            for t, v in ss.items():
                ap[t] += (sum(1 for o, ov in ss.items() if o != t and ov < v) + 0.5 * sum(1 for o, ov in ss.items() if o != t and ov == v)) / (len(ss) - 1); n[t] += 1; sc[t].append(v)
        for g in reg_g:
            if g['hs'] > g['as_']: W[g['h']] += 1
            elif g['as_'] > g['hs']: W[g['a']] += 1
        E = elo_week.get((y, wk), elo)
        def z(vals):
            mu = st.mean(vals.values()); sd = st.pstdev(vals.values()) or 1
            return {k: (v - mu) / sd for k, v in vals.items()}
        # all-play blended with last season, in all-play units (fit on league history: K=13 weeks of shrinkage, 29% carryover)
        est = {t: (ap[t] + AP_K * (0.5 + AP_C * (prior_ap.get(t, 0.5) - 0.5))) / (n[t] + AP_K) for t in tids}
        a_ = (AP_K * AP_C / (n[tids[0]] + AP_K)) / (AP_K * AP_C / (n[tids[0]] + AP_K) + n[tids[0]] / (n[tids[0]] + AP_K)) if prior_ap else 0
        za = z(est); zf = z({t: st.mean(sc[t][-3:]) for t in tids}); zw = z({t: W[t] for t in tids})
        score = {t: 0.5 * za[t] + 0.3 * zf[t] + 0.2 * zw[t] for t in tids}
        order = sorted(tids, key=lambda t: -score[t])
        power.append(dict(wk=wk, rows=[dict(tid=t, key=s['fk'][t], mgr=s['sl'][t], team=s['tm'][t]['name'], rank=i + 1, score=round(score[t], 2),
                                            allplay=round(ap[t] / n[t], 3), elo=round(E[s['fk'][t]]), prior=round(prior_ap[t], 3) if t in prior_ap else None, priorWt=round(a_, 2), form=round(st.mean(sc[t][-3:]), 1), w=W[t], l=wk - W[t]) for i, t in enumerate(order)]))
    for i, r in enumerate(power[-1]['rows'] if power else []):
        prev = next((p['rank'] for p in power[-2]['rows'] if p['tid'] == r['tid']), None) if len(power) > 1 else None
        r['move'] = (prev - r['rank']) if prev else 0

    # odds: simulate the rest of the regular season and the bracket
    divs_ = collections.defaultdict(list)
    for t in tids: divs_[s['tm'][t]['div']].append(t)
    po = s['settings']['po']
    ndiv = len(divs_) if len(divs_) > 1 else 0

    def state_at(asof):
        W0 = collections.Counter(); PF0 = collections.Counter(); tsc = collections.defaultdict(list)
        for g in s['g']:
            if g['tier'] == 0 and g['mp'] <= asof:
                PF0[g['h']] += g['hs']; PF0[g['a']] += g['as_']; tsc[g['h']].append(g['hs']); tsc[g['a']].append(g['as_'])
                if g['hs'] > g['as_']: W0[g['h']] += 1
                elif g['as_'] > g['hs']: W0[g['a']] += 1
                else: W0[g['h']] += .5; W0[g['a']] += .5
        allsc = [x for v in tsc.values() for x in v]
        lmu = st.mean(allsc); lsd = st.pstdev(allsc) or 25
        mu = {t: (sum(tsc[t]) + PRIOR_WEEKS * lmu * (1 + CARRY * prior_rel.get(t, 0))) / (len(tsc[t]) + PRIOR_WEEKS) for t in tids}
        future = [(mp, h, a) for mp, h, hs, a, as_, tier, win in s['games'] if tier == 'NONE' and asof < mp <= reg]
        H0 = collections.Counter(); G0 = collections.Counter()
        for g in s['g']:
            if g['tier'] == 0 and g['mp'] <= asof:
                G0[frozenset((g['h'], g['a']))] += 1
                if g['hs'] > g['as_']: H0[(g['h'], g['a'])] += 1
                elif g['as_'] > g['hs']: H0[(g['a'], g['h'])] += 1
        for mp, h, a in future: G0[frozenset((h, a))] += 1  # the schedule is fixed; only winners are unknown
        return W0, PF0, mu, lsd * 0.92, future, H0, G0

    def simulate(asof, N, proj=None):
        W0, PF0, mu, sd, future, H0, G0 = state_at(asof)
        divof = {t: s['tm'][t]['div'] for t in tids}
        rng = random.Random(y * 1000 + asof)
        cnt = {t: collections.Counter() for t in tids}; wins_sum = collections.Counter()
        cond = {t: collections.Counter() for t in tids}  # next-week win/loss -> playoff/title tallies
        nxt = asof + 1
        for _ in range(N):
            W = W0.copy(); PF = PF0.copy(); H = H0.copy(); res = {}
            for mp, h, a in future:
                mh, ma = (proj[h], proj[a]) if (proj and mp == nxt) else (mu[h], mu[a])
                sh = rng.gauss(mh, sd); sa = rng.gauss(ma, sd)
                PF[h] += sh; PF[a] += sa
                if sh > sa: W[h] += 1; win, lose = h, a
                else: W[a] += 1; win, lose = a, h
                H[(win, lose)] += 1
                if mp == nxt: res[win] = 'w'; res[lose] = 'l'
            seeds, dw, full_ = seed_teams(tids, divof, W, PF, H, G0, po, pw_for(y))
            for i_, t in enumerate(full_): cnt[t]['p%d' % (i_ + 1)] += 1
            for t in dw: cnt[t]['div'] += 1
            for t in tids: wins_sum[t] += W[t]
            for t in seeds: cnt[t]['po'] += 1
            for t in seeds[:(2 if po == 6 else 0)]: cnt[t]['bye'] += 1
            gm = lambda a, b: a if rng.gauss(mu[a], sd) > rng.gauss(mu[b], sd) else b
            if po == 6:
                q1 = gm(seeds[2], seeds[5]); q2 = gm(seeds[3], seeds[4]); s1 = gm(seeds[0], q2); s2 = gm(seeds[1], q1)
            else:
                s1 = gm(seeds[0], seeds[3]); s2 = gm(seeds[1], seeds[2])
            cnt[s1]['final'] += 1; cnt[s2]['final'] += 1
            champ = gm(s1, s2); cnt[champ]['title'] += 1
            if LADDER and len(full_) == 12 and po == 6:
                # losers' ladder (same every year since at least 2020): wk1 7v8, 9v10, 11v12; wk2 W1vW2, L1vW3, L2vL3;
                # the Sacko game is the loser of L1vW3 against the loser of L2vL3
                L_ = full_[6:]
                w1 = gm(L_[0], L_[1]); l1 = L_[1] if w1 == L_[0] else L_[0]
                w2 = gm(L_[2], L_[3]); l2 = L_[3] if w2 == L_[2] else L_[2]
                w3 = gm(L_[4], L_[5]); l3 = L_[5] if w3 == L_[4] else L_[4]
                bw = gm(l1, w3); bl = w3 if bw == l1 else l1
                cw = gm(l2, l3); cl = l3 if cw == l2 else l2
                sk_w = gm(bl, cl); cnt[cl if sk_w == bl else bl]['sacko'] += 1
            for t, r_ in res.items():
                cond[t][r_ + 'n'] += 1
                if t in seeds: cond[t][r_ + 'po'] += 1
                if t == champ: cond[t][r_ + 'ti'] += 1
        return cnt, wins_sum, mu, sd, cond, W0, PF0, future, H0, G0

    # projections for the upcoming week: best possible lineup from ESPN's projections
    proj = None; preview = None
    up = s.get('upcoming')
    if up and up.get('mp') == played + 1 and played + 1 <= reg:
        proj = {}; projTop = {}
        for tid_s, ents in up['teams'].items():
            tid = int(tid_s)
            pe = [[e[0], e[1], e[2], e[3]] for e in ents if e[4] not in ('OUT', 'INJURY_RESERVE', 'SUSPENSION')]
            proj[tid] = round(optimal(pe, s['settings']['slots']), 1)
            best = max(ents, key=lambda e: e[2]) if ents else None
            projTop[tid] = [s['players'].get(str(best[0]), ['?', ''])[0], s['players'].get(str(best[0]), ['?', ''])[1], best[2]] if best else None
    N = 10000
    cnt, wins_sum, mu, sd, cond, W0, PF0, future, H0, G0 = simulate(played, N, proj)
    for t in tids:
        odds.append(dict(tid=t, key=s['fk'][t], mgr=s['sl'][t], team=s['tm'][t]['name'], w=W0[t], l=played - W0[t],
                         projW=round(wins_sum[t] / N, 1), po=round(cnt[t]['po'] / N, 3), div=round(cnt[t]['div'] / N, 3),
                         bye=round(cnt[t]['bye'] / N, 3), final=round(cnt[t]['final'] / N, 3), title=round(cnt[t]['title'] / N, 3), ppg=round(mu[t], 1),
                         place=[round(cnt[t]['p%d' % i_] / N, 4) for i_ in range(1, len(tids) + 1)], sacko=round(cnt[t]['sacko'] / N, 3) if LADDER else None))
    odds.sort(key=lambda x: (-x['title'], -x['po']))

    # matchup previews with playoff stakes
    if proj:
        from math import erf, sqrt
        games_next = [(h, a) for mp, h, a in future if mp == played + 1]
        pv = []
        for h, a in games_next:
            ph = 0.5 * (1 + erf((proj[h] - proj[a]) / (sd * sqrt(2) * sqrt(2))))
            def stake(t):
                c = cond[t]
                pw = c['wpo'] / c['wn'] if c['wn'] else 0; pl = c['lpo'] / c['ln'] if c['ln'] else 0
                tw = c['wti'] / c['wn'] if c['wn'] else 0; tl = c['lti'] / c['ln'] if c['ln'] else 0
                return dict(poWin=round(pw, 3), poLose=round(pl, 3), swing=round(pw - pl, 3), tiWin=round(tw, 3), tiLose=round(tl, 3))
            sh, sa = stake(h), stake(a)
            pv.append(dict(h=h, a=a, hk=s['fk'][h], ak=s['fk'][a], hm=s['sl'][h], am=s['sl'][a], ht=s['tm'][h]['name'], at=s['tm'][a]['name'],
                           hrec=f"{W0[h]:g}–{played - W0[h]:g}", arec=f"{W0[a]:g}–{played - W0[a]:g}",
                           hp=proj[h], ap=proj[a], hwin=round(ph, 3), hs=sh, as_=sa, swing=round(sh['swing'] + sa['swing'], 3),
                           htop=projTop.get(h), atop=projTop.get(a),
                           h2h=h2h.get((s['fk'][h], s['fk'][a]), [0, 0, 0])))
        pv.sort(key=lambda x: -x['swing'])
        if pv: pv[0]['gotw'] = True
        preview = dict(wk=played + 1, games=pv)

    # odds history: re-run the simulation as of the end of every week so far
    oddsHist = collections.defaultdict(list)
    for w in range(1, played + 1):
        c_ = cnt if w == played else simulate(w, 3000)[0]
        n_ = N if w == played else 3000
        for t in tids:
            oddsHist[s['fk'][t]].append([w, round(c_[t]['po'] / n_, 3), round(c_[t]['title'] / n_, 3)])

    # clinch / elimination (worst case for clinching, best case for elimination; points tiebreaks ignored)
    rem = collections.Counter()
    for mp, h, a in future: rem[h] += 1; rem[a] += 1
    mx = {t: W0[t] + rem[t] for t in tids}
    wc = po - ndiv if ndiv else po
    status = {}
    for t in tids:
        Wt, Mt = W0[t], mx[t]
        if ndiv:
            mydiv = s['tm'][t]['div']
            rivals = [r_ for r_ in divs_[mydiv] if r_ != t]
            can_ahead_r = [r_ for r_ in rivals if mx[r_] >= Wt]
            if not can_ahead_r:
                status[t] = 'div'
            else:
                ahead = len(can_ahead_r) - 1
                for d_, ts in divs_.items():
                    if d_ == mydiv: continue
                    c_ = sum(1 for x in ts if mx[x] >= Wt); ahead += max(0, c_ - 1)
                if ahead < wc: status[t] = 'po'
            sure_r = [r_ for r_ in rivals if W0[r_] > Mt]
            if sure_r and t not in status:
                ahead = len(sure_r) - 1
                for d_, ts in divs_.items():
                    if d_ == mydiv: continue
                    c_ = sum(1 for x in ts if W0[x] > Mt); ahead += max(0, c_ - 1)
                status[t] = 'out' if ahead >= wc else 'nodiv'
        elif pw_for(y):
            # in by record alone; nobody is ruled out, since the points spot stays open until the last week
            if sum(1 for o in tids if o != t and mx[o] >= Wt) < po - pw_for(y): status[t] = 'po'
        else:
            if sum(1 for o in tids if o != t and mx[o] >= Wt) < po: status[t] = 'po'
            elif sum(1 for o in tids if o != t and W0[o] > Mt) >= po: status[t] = 'out'
    sos = {t: (st.mean([mu[a if h == t else h] for mp, h, a in future if t in (h, a)]) if rem[t] else None) for t in tids}
    sos_rank = {t: i + 1 for i, t in enumerate(sorted([t for t in tids if sos[t] is not None], key=lambda t: -sos[t]))}
    for o in odds:
        t = o['tid']; o['status'] = status.get(t, ''); o['rem'] = rem[t]; o['maxW'] = mx[t]
        o['sos'] = round(sos[t], 1) if sos[t] is not None else None; o['sosRank'] = sos_rank.get(t)
    from math import erf as _erf, sqrt as _sqrt
    def p_home(mp, h, a):
        if preview and mp == played + 1:
            g_ = next((x for x in preview['games'] if {x['h'], x['a']} == {h, a}), None)
            if g_: return g_['hwin'] if g_['h'] == h else 1 - g_['hwin']
        return 0.5 * (1 + _erf((mu[h] - mu[a]) / (sd * 2)))
    machine = dict(
        y=y, reg=reg, po=po, played=played, sd=round(sd, 2),
        divs={str(d_[0]): d_[1] for d_ in s['settings']['divisions']} if ndiv else {},
        teams=[dict(tid=t, key=s['fk'][t], mgr=s['sl'][t], team=s['tm'][t]['name'], div=s['tm'][t]['div'], w=W0[t], l=played - W0[t],
                    pf=round(PF0[t], 2), mu=round(mu[t], 2)) for t in tids],
        done=[[g['h'], g['a'], g['hs'], g['as_']] for g in s['g'] if g['tier'] == 0],
        games=[[mp, h, a, round(p_home(mp, h, a), 3)] for mp, h, a in future],
        espnSeeds=[t['id'] for t in sorted(s['teams'], key=lambda t: t['seed'] or 99)],
        **({'pw': pw_for(y)} if pw_for(y) else {}),
    )
    clinch = dict(preview=preview, oddsHist=dict(oddsHist), remWeeks=reg - played, sd=round(sd, 1), machine=machine)

# ---------------------------------------------------------------- manager profiles
H = {a: {b: h2h.get((a, b), [0, 0, 0]) for b in keys if b != a} for a in keys}
bench_m = {k: v for k, v in bench.items()}
draft_by = collections.defaultdict(list)
for d in draft_team: draft_by[d['key']].append(d)
tx_by = collections.defaultdict(lambda: [0, 0, 0])
for s in seasons:
    for t in s['teams']:
        k = s['fk'][t['id']]; tx_by[k][0] += t['tc'][0]; tx_by[k][1] += t['tc'][1]; tx_by[k][2] += t['tc'][2]
legend_by = collections.defaultdict(list)
for (k, pid), (pts, n, yrs) in legend.items():
    nm = names.get(pid, ['?', '', 0, 0])
    legend_by[k].append(dict(player=nm[0], pos=nm[1], pts=round(pts, 1), starts=n, years=sorted(yrs)))
managers = []
for k in keys:
    m = M[k]
    ap = allplay[k]
    ratios = []
    for (kk, y), lst in po_scores.items():
        if kk == k and reg_scores.get((k, y)):
            base = st.mean(reg_scores[(k, y)]); ratios += [x / base for x in lst]
    opp = [(o, *H[k][o]) for o in H[k]]
    rival = max(riv, key=lambda r: (k in (r['a'], r['b'])) * r['idx'])
    rival_k = rival['b'] if rival['a'] == k else rival['a']
    q = [x for x in opp if x[1] + x[2] >= 8]
    victim = max(q, key=lambda x: (x[1] - x[2], x[1])) if q else None
    nemesis = min(q, key=lambda x: (x[1] - x[2], -x[2])) if q else None
    b = bench_m.get(k)
    dd = draft_by.get(k, [])
    sw = swap.get(k, dict(w=0, exp=0, po=0, poExp=0))
    leg = sorted(legend_by.get(k, []), key=lambda x: -x['pts'])[:8]
    cur_team = next((t['name'] for t in (CUR or seasons[-1])['teams'] if (CUR or seasons[-1])['fk'][t['id']] == k), m['teamNames'][-1][1])
    best_season = max((x for x in season_luck if x['key'] == k and x['done']), key=lambda x: (x['w'] - x['l'], -x['rank']), default=None)
    worst_season = min((x for x in season_luck if x['key'] == k and x['done']), key=lambda x: (x['w'] - x['l'], -x['rank']), default=None)
    managers.append(dict(
        key=k, name=m['name'], short=m['short'], team=cur_team, seasons=m['seasons'], teamNames=m['teamNames'], finishes=m['finishes'],
        titles=m['titles'], ru=m['ru'], last=m['last'], po=m['po'], divs=m['divs'], wcs=m['wcs'], berths=m['berths'], champAs=m['champAs'],
        w=m['w'], l=m['l'], t=m['t'], pct=round(m['w'] / max(1, m['w'] + m['l'] + m['t']), 3), pf=round(m['pf'], 1), pa=round(m['pa'], 1),
        ppg=round(m['pf'] / max(1, m['g']), 1), pw=m['pw'], pl=m['pl'],
        avgFin=round(st.mean(f[1] for f in m['finishes']), 1) if m['finishes'] else None,
        elo=round(elo[k]), peak=round(peak[k][0]), peakAt=peak[k][1], eloHist=elo_hist[k],
        allpct=round(ap[0] / max(1, ap[1]), 3), apW=round(ap[0], 1), luck=round(sum(x['w'] for x in season_luck if x['key'] == k) - ap[0], 1),
        swing=round(st.pstdev(rel[k]) * 100, 1) if rel[k] else None, crowns=crowns[k], duds=duds[k],
        clutch=round((st.mean(ratios) - 1) * 100, 1) if ratios else None, pog=len(ratios),
        swapW=round(sw['w'], 1), swapExp=round(sw['exp'], 1), swapPo=sw['po'], swapPoExp=round(sw['poExp'], 1),
        bench=dict(eff=round(b[0] / b[1] * 100, 1), left=round((b[1] - b[0]) / b[2], 1), weeks=b[2]) if b else None,
        selfLosses=self_losses[k],
        draft=dict(avgZ=round(st.mean(d['z'] for d in dd), 2) if dd else None, grades=[[d['y'], d['grade']] for d in sorted(dd, key=lambda d: d['y'])],
                   best=max(dd, key=lambda d: d['z'])['y'] if dd else None, worst=min(dd, key=lambda d: d['z'])['y'] if dd else None),
        tx=dict(acq=tx_by[k][0], drops=tx_by[k][1], trades=tx_by[k][2] // 1),
        legends=leg, pickups=sorted([p for p in pickups if p['key'] == k], key=lambda p: -p['pts'])[:5], rival=rival_k, victim=victim[0] if victim else None, nemesis=nemesis[0] if nemesis else None,
        bestSeason=best_season, worstSeason=worst_season,
        close=close[k], early=split[k][0], late=split[k][1],
        choke=dict(fav=choke[k]['fav'], early=choke[k]['early'], titles=choke[k]['titles'], years=choke[k]['years'], exits=choke[k]['exits']),
    ))

# ---------------------------------------------------------------- records
def top(lst, f, n=6, rev=True): return sorted(lst, key=f, reverse=rev)[:n]
done_rows = [dict(r, y=s['y']) for s in season_out if s['done'] for r in s['rows']]
records = dict(
    high=top(weekly, lambda x: x['pts']),
    low=top([w for w in weekly if w['pts'] > 0 and w['y'] >= PPR_FROM], lambda x: x['pts'], rev=False),
    blowout=top(games_flat, lambda g: abs(g['hs'] - g['as_'])),
    close=top([g for g in games_flat if g['hs'] != g['as_']], lambda g: abs(g['hs'] - g['as_']), rev=False),
    combined=top(games_flat, lambda g: g['hs'] + g['as_']),
    lossHi=top([w for w in weekly if not w['won'] and w['pts'] < w['opts']], lambda x: x['pts']),
    winLo=top([w for w in weekly if w['won'] and w['y'] >= PPR_FROM], lambda x: x['pts'], rev=False),
    ppg=top([r for r in done_rows if r['y'] >= PPR_FROM], lambda r: r['pf'] / max(1, r['w'] + r['l'] + r['t'])),
    bestRec=top(done_rows, lambda r: (r['w'] / max(1, r['w'] + r['l']), r['pf'])),
    worstRec=top(done_rows, lambda r: (r['w'] / max(1, r['w'] + r['l']), r['pf']), rev=False),
    winStreak=top([x for x in streaks if x['kind'] == 'W'], lambda x: x['n']),
    loseStreak=top([x for x in streaks if x['kind'] == 'L'], lambda x: x['n']),
    playerWeek=top(player_weeks, lambda x: x['pts'], n=8),
    benchWeek=top(bench_weeks, lambda x: x['left']),
    selfLoss=top(self_loss_list, lambda x: x['opt'] - x['opts']),
    perfect=sorted([b for b in bench_weeks if b['left'] < 0.01], key=lambda b: -b['act'])[:6],
    pickups=top(pickups, lambda x: x['pts'], n=10),
    steals=top([d for d in draft_rows if d['rd'] >= 4 and not d['keeper'] and any(s['y'] == d['y'] and s['done'] for s in season_out)], lambda d: d['val'], n=10),
    busts=top([d for d in draft_rows if d['rd'] <= 2 and not d['keeper'] and any(s['y'] == d['y'] and s['done'] for s in season_out)], lambda d: d['val'], n=10, rev=False),
    draftBest=top(draft_team, lambda d: d['z']), draftWorst=top(draft_team, lambda d: d['z'], rev=False),
    lucky=top([x for x in season_luck if x['done']], lambda x: x['luck']),
    unlucky=top([x for x in season_luck if x['done']], lambda x: x['luck'], rev=False),
    robbed=top([x for x in swap_seasons if not x['made']], lambda x: x['pmake']),
    gifted=top([x for x in swap_seasons if x['made']], lambda x: x['pmake'], rev=False),
    divOdd=sorted([dict(y=s['y'], mgr=r['mgr'], key=r['key'], team=r['team'], w=r['w'], l=r['l']) for s in season_out if s['done'] for r in s['rows'] if 'div' in r['status'].split() and r['w'] <= r['l']], key=lambda x: x['w'] - x['l'])[:6],
    missed=sorted([dict(y=s['y'], mgr=r['mgr'], key=r['key'], w=r['w'], l=r['l'], pf=r['pf']) for s in season_out if s['done'] and s['divs'] for r in s['rows'] if r['seed'] == 0], key=lambda x: (-(x['w'] - x['l']), -x['pf']))[:6],
    eras=eras_best, dark=eras_dark,
)
lopsided = sorted([r for r in riv if r['n'] >= 12], key=lambda r: -(abs(r['w'] - r['l']) / r['n']))[:6]

# ---------------------------------------------------------------- names
div_names = [[s['y'], [d[1] for d in s['settings']['divisions']]] for s in seasons if len(s['settings']['divisions']) > 1]

top_seed_titles = sum(1 for s in season_out if s['done'] and s['final'] and s['final']['wseed'] == 1)
out = dict(
    meta=dict(league=seasons[-1]['name'], founded=seasons[0]['y'], updated=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
              cur=dict(y=CUR['y'], week=CUR['played']) if CUR else None, nSeasons=len(seasons), nDone=len(done),
              lineupYears=[s['y'] for s in seasons if s['weeks']], benchYears=[s['y'] for s in seasons if s['tx']],
              topSeedTitles=top_seed_titles),
    managers=managers, h2h=H, seasons=season_out, records=records, rivalries=riv[:12], lopsided=lopsided,
    upsets=sorted(upsets, key=lambda u: -(u['wseed'] - u['lseed'])), sacko=sacko, trades=trades, tradeCounts=trade_counts,
    timeline=timeline, divNames=div_names, **({'auction': auction} if auction else {}),
    curLuck=sorted([x for x in season_luck if not x['done']], key=lambda x: -x['luck']),
    recaps=recaps, power=power, odds=odds, live=clinch, awards=awards, favTitles=[fav_titles, fav_seasons],
    closeSeasons=dict(best=sorted([x for x in close_season if x['done']], key=lambda x: (-(x['w'] - x['l']), -x['w']))[:6],
                      worst=sorted([x for x in close_season if x['done']], key=lambda x: ((x['w'] - x['l']), -x['l']))[:6]),
)
json.dump(out, open(OUT, 'w'), separators=(',', ':'))
print('wrote', OUT, os.path.getsize(OUT) // 1024, 'KB')
