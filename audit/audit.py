"""Independent audit: recompute from raw ESPN season files with fresh code and compare to data.json.

Usage: python3 audit.py RAW_DIR DATA_JSON [LEAGUE_CONFIG]   (config defaults to league.json next to this script)
"""
import json, os, collections, statistics as st, sys

RAW = sys.argv[1] if len(sys.argv) > 1 else 'raw'; D = json.load(open(sys.argv[2] if len(sys.argv) > 2 else 'data.json'))
CFG = json.load(open(sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'league.json')))
CUT = CFG.get('cutoffs', {}); AUD = CFG.get('audit', {})
PPR_FROM = CUT.get('pprFrom', 0); EARLY_WEEKS = CUT.get('earlyWeeks', 6); LADDER = bool(CFG.get('losersLadder'))
raw = {int(f[:4]): json.load(open(os.path.join(RAW, f))) for f in os.listdir(RAW) if f.endswith('.json')}
fails = []; passes = 0
def check(name, ok, detail=''):
    global passes
    if ok: passes += 1
    else: fails.append(f'{name}: {detail}')

# owner name -> franchise (the league config's seat list, matched as substrings of the joined owner names)
def fr(owners):
    s = ' '.join(owners).lower()
    for key, _label, _short, needles in CFG['franchises']:
        if any(n in s for n in needles): return key
    return None

MK = {m['key']: m for m in D['managers']}
SEAS = {s['y']: s for s in D['seasons']}

# ---------- 1. every team maps to a franchise; 12 franchises
for y, r in raw.items():
    for t in r['teams']:
        check(f'{y} franchise map', fr(t['owners']) is not None, t['owners'])
check(f"{len(CFG['franchises'])} managers", len(D['managers']) == len(CFG['franchises']), len(D['managers']))

# ---------- 2. ESPN W/L/PF consistency per season
games = {}
for y, r in sorted(raw.items()):
    reg = r['settings']['reg']; cur = r['curPeriod'] if not r['done'] else 999
    g = [x for x in r['games'] if x[0] <= reg and x[0] < cur and (x[2] or x[4])]
    games[y] = g
    W = collections.Counter(); L = collections.Counter(); PF = collections.Counter()
    for mp, h, hs, a, as_, tier, win in g:
        PF[h] += hs; PF[a] += as_
        if hs > as_: W[h] += 1; L[a] += 1
        elif as_ > hs: W[a] += 1; L[h] += 1
    for t in r['teams']:
        check(f'{y} PF {t["name"]}', abs(PF[t['id']] - t['pf']) < 0.6, f'{PF[t["id"]]:.2f} vs ESPN {t["pf"]}')
        # ESPN may break exact ties; allow W+T match
        check(f'{y} W {t["name"]}', abs(W[t['id']] - t['w']) <= t['t'] + (1 if any(x[2] == x[4] for x in g if t['id'] in (x[1], x[3])) else 0), f'{W[t["id"]]} vs ESPN {t["w"]}')

# ---------- 3. all-time W-L-PF per manager equals sum of ESPN season records
agg = collections.defaultdict(lambda: [0, 0, 0, 0.0])
for y, r in raw.items():
    for t in r['teams']:
        a = agg[fr(t['owners'])]; a[0] += t['w']; a[1] += t['l']; a[2] += t['t']; a[3] += t['pf']
for k, (w, l, t, pf) in agg.items():
    m = MK[k]
    check(f'alltime {k}', (m['w'], m['l'], m['t']) == (w, l, t) and abs(m['pf'] - pf) < 1, f'site {m["w"]}-{m["l"]}-{m["t"]} {m["pf"]} vs {w}-{l}-{t} {pf:.1f}')

# ---------- 4. champions, runner-ups, last place, playoff fields
for y, r in raw.items():
    if not r['done']: continue
    wb = [x for x in r['games'] if x[5] == 'WINNERS_BRACKET']
    fm = max(x[0] for x in wb); f = [x for x in wb if x[0] == fm][0]
    champ_id = f[1] if f[2] > f[4] else f[3]; ru_id = f[3] if champ_id == f[1] else f[1]
    rank1 = [t for t in r['teams'] if t['rank'] == 1][0]
    check(f'{y} champion = final winner', rank1['id'] == champ_id, f'{rank1["name"]}')
    check(f'{y} site champion', y in MK[fr(rank1['owners'])]['titles'])
    ru = [t for t in r['teams'] if t['id'] == ru_id][0]
    check(f'{y} runner-up', y in MK[fr(ru['owners'])]['ru'], ru['name'])
    last = [t for t in r['teams'] if t['rank'] == len(r['teams'])][0]
    check(f'{y} last place', y in MK[fr(last['owners'])]['last'], last['name'])
    field = {x for g in wb for x in (g[1], g[3])}
    check(f'{y} playoff field size', len(field) == r['settings']['po'], f'{len(field)} vs {r["settings"]["po"]}')
    for t in r['teams']:
        check(f'{y} playoff flag {t["name"]}', (y in MK[fr(t['owners'])]['po']) == (t['id'] in field))
# Titles count
check('title count total', sum(len(m['titles']) for m in D['managers']) == sum(1 for r in raw.values() if r['done']))

# ---------- 5. H2H symmetric & totals
tot = 0
for a, row in D['h2h'].items():
    for b, (w, l, t) in row.items():
        wb_, lb, tb = D['h2h'][b][a]
        check(f'h2h sym {a}-{b}', (w, l, t) == (lb, wb_, tb))
        tot += w + l + t
allg = sum(1 for y, r in raw.items() for x in r['games'] if x[5] in ('NONE', 'WINNERS_BRACKET') and (x[2] or x[4]) and (r['done'] or x[0] < r['curPeriod']))
check('h2h game total', tot // 2 == allg, f'{tot // 2} vs {allg}')
# spot check one pair from raw
pw = [0, 0]; SA, SB = AUD.get('h2hSpot') or [CFG['franchises'][0][0], CFG['franchises'][1][0]]
for y, r in raw.items():
    for x in r['games']:
        if x[5] not in ('NONE', 'WINNERS_BRACKET') or not (x[2] or x[4]) or (not r['done'] and x[0] >= r['curPeriod']): continue
        tm = {t['id']: fr(t['owners']) for t in r['teams']}
        if {tm[x[1]], tm[x[3]]} == {SA, SB}:
            e = x[2] if tm[x[1]] == SA else x[4]; o = x[4] if tm[x[1]] == SA else x[2]
            pw[0 if e > o else 1] += 1
check(f'h2h {SA} vs {SB}', D['h2h'][SA][SB][:2] == pw, f'{D["h2h"][SA][SB]} vs {pw}')

# ---------- 6. record book: weekly highs/lows, blowouts, streaks
weekly = []
for y, g in games.items():
    for mp, h, hs, a, as_, tier, win in g: weekly += [(hs, y, mp), (as_, y, mp)]
check('highest score', abs(max(weekly)[0] - D['records']['high'][0]['pts']) < 0.01, f'{max(weekly)} vs {D["records"]["high"][0]["pts"]}')
low13 = min(w for w in weekly if w[1] >= PPR_FROM and w[0] > 0)
check('lowest score', abs(low13[0] - D['records']['low'][0]['pts']) < 0.01, f'{low13} vs {D["records"]["low"][0]["pts"]}')
bl = max(abs(x[2] - x[4]) for g in games.values() for x in g)
R0 = D['records']['blowout'][0]
check('blowout', abs(bl - abs(R0['hs'] - R0['as_'])) < 0.01, bl)
cl = min(abs(x[2] - x[4]) for g in games.values() for x in g if x[2] != x[4])
R0 = D['records']['close'][0]
check('closest', abs(cl - abs(R0['hs'] - R0['as_'])) < 0.01, cl)
# streaks (reg + winners bracket)
seq = collections.defaultdict(list)
for y, r in sorted(raw.items()):
    tm = {t['id']: fr(t['owners']) for t in r['teams']}
    for x in sorted(r['games'], key=lambda x: x[0]):
        if x[5] not in ('NONE', 'WINNERS_BRACKET') or not (x[2] or x[4]) or (not r['done'] and x[0] >= r['curPeriod']): continue
        seq[tm[x[1]]].append((y, x[0], 'W' if x[2] > x[4] else 'L' if x[2] < x[4] else 'T'))
        seq[tm[x[3]]].append((y, x[0], 'W' if x[4] > x[2] else 'L' if x[4] < x[2] else 'T'))
def longest(k, c):
    best = cur = 0
    for _, _, r_ in sorted(seq[k]):
        cur = cur + 1 if r_ == c else 0; best = max(best, cur)
    return best
ws = max((longest(k, 'W'), k) for k in seq); ls = max((longest(k, 'L'), k) for k in seq)
check('win streak', ws[0] == D['records']['winStreak'][0]['n'], ws)
check('lose streak', ls[0] == D['records']['loseStreak'][0]['n'], ls)
# best/worst record
br = max(((t['w'] - t['l'], y, t['name']) for y, r in raw.items() if r['done'] for t in r['teams']))
check('best record', (D['records']['bestRec'][0]['w'] - D['records']['bestRec'][0]['l']) == br[0], br)

# ---------- 7. all-play & luck (independent)
ap = collections.defaultdict(lambda: [0.0, 0]); sl = {}
for y, g in games.items():
    tm = {t['id']: fr(t['owners']) for t in raw[y]['teams']}
    seasW = collections.Counter(); seasE = collections.Counter()
    for wk in {x[0] for x in g}:
        sc = {}
        for x in g:
            if x[0] == wk: sc[x[1]] = x[2]; sc[x[3]] = x[4]
        for t, v in sc.items():
            e = sum((ov < v) + 0.5 * (ov == v) for o, ov in sc.items() if o != t) / (len(sc) - 1)
            ap[tm[t]][0] += e; ap[tm[t]][1] += 1; seasE[t] += e
    for x in g:
        if x[2] > x[4]: seasW[x[1]] += 1
        elif x[4] > x[2]: seasW[x[3]] += 1
        else: seasW[x[1]] += .5; seasW[x[3]] += .5
    for t in seasE: sl[(y, tm[t])] = seasW[t] - seasE[t]
for k, (e, n) in ap.items():
    check(f'all-play {k}', abs(MK[k]['allpct'] - e / n) < 0.0015, f'{MK[k]["allpct"]} vs {e / n:.3f}')
best = max((v, y, k) for (y, k), v in sl.items() if raw[y]['done'])
L0 = D['records']['lucky'][0]
check('luckiest season', abs(L0['luck'] - best[0]) < 0.02 and L0['y'] == best[1], f'{L0["y"]} {L0["luck"]} vs {best}')
worst = min((v, y, k) for (y, k), v in sl.items() if raw[y]['done'])
U0 = D['records']['unlucky'][0]
check('unluckiest season', abs(U0['luck'] - worst[0]) < 0.02 and U0['y'] == worst[1], f'{U0["y"]} {U0["luck"]} vs {worst}')
cur = [s for s in D['seasons'] if not s['done']][0]['y']
for x in D['curLuck']:
    check(f'{cur} luck {x["key"]}', abs(x['luck'] - sl[(cur, x['key'])]) < 0.02, f'{x["luck"]} vs {sl[(cur, x["key"])]:.2f}')

# ---------- 8. Elo is zero-sum
avg = st.mean(m['elo'] for m in D['managers'])
check('Elo averages ~1500', abs(avg - 1500) < 2, avg)

# ---------- 9. close games & early/late
close = collections.defaultdict(lambda: [0, 0]); early = collections.defaultdict(lambda: [0, 0]); late = collections.defaultdict(lambda: [0, 0])
for y, r in raw.items():
    tm = {t['id']: fr(t['owners']) for t in r['teams']}
    two = (r['settings']['poLen'] or 1) > 1; reg = r['settings']['reg']
    for x in r['games']:
        if x[5] not in ('NONE', 'WINNERS_BRACKET') or not (x[2] or x[4]) or (not r['done'] and x[0] >= r['curPeriod']): continue
        div = 2 if (two and x[0] > reg) else 1
        if x[2] == x[4]: continue
        w, l = (x[1], x[3]) if x[2] > x[4] else (x[3], x[1])
        if abs(x[2] - x[4]) / div < 10: close[tm[w]][0] += 1; close[tm[l]][1] += 1
        if x[5] == 'NONE':
            b = early if x[0] <= EARLY_WEEKS else late
            b[tm[w]][0] += 1; b[tm[l]][1] += 1
for k in MK:
    check(f'close {k}', MK[k]['close'][:2] == close[k], f'{MK[k]["close"]} vs {close[k]}')
    check(f'early {k}', MK[k]['early'] == early[k], f'{MK[k]["early"]} vs {early[k]}')
    check(f'late {k}', MK[k]['late'] == late[k], f'{MK[k]["late"]} vs {late[k]}')

# ---------- 10. divisions: winners are seeds 1-4 and best in division
for y, r in raw.items():
    if not r['done'] or len(r['settings']['divisions']) < 2: continue
    groups = collections.defaultdict(list)
    for t in r['teams']: groups[t['div']].append(t)
    for d_, ts in groups.items():
        win = min(ts, key=lambda t: t['seed'])
        bestw = max(t['w'] for t in ts)
        check(f'{y} div winner has best record', win['w'] == bestw, f'{win["name"]} {win["w"]} vs {bestw}')
        check(f'{y} div title credited', y in MK[fr(win['owners'])]['divs'], win['name'])

# ---------- 11. legacy points recomputed
LWt = dict(t=10, ru=5, semi=3, po=2, best=2, last=-2)
leg = {}
for k, m in MK.items():
    s = 0
    for y, rk, n in m['finishes']:
        r = raw[y]; t = [t for t in r['teams'] if fr(t['owners']) == k][0]
        best_t = max(r['teams'], key=lambda x: (x['w'] - x['l'], x['pf']))
        inpo = y in m['po']
        s += LWt['t'] * (rk == 1) + LWt['ru'] * (rk == 2) + LWt['semi'] * (rk in (3, 4) and inpo) + LWt['po'] * inpo + LWt['best'] * (best_t['id'] == t['id']) + LWt['last'] * (rk == n)
    leg[k] = s
order = sorted(leg, key=lambda k: -leg[k])
SNAP = AUD.get('legacySnapshot')
if SNAP and max(y for y, r in raw.items() if r['done']) == SNAP['throughYear']:  # hand-verified values from the config
    for k_, v_ in SNAP['values'].items():
        check(f'legacy {k_} {v_}', leg[k_] == v_, leg[k_])

# ---------- 12. lineups: optimal >= actual, actual equals team score
for b in D['records']['benchWeek'][:6]:
    check(f'bench {b["y"]} wk{b["wk"]}', b['opt'] >= b['act'] and b['left'] == round(b['opt'] - b['act'], 2), b)
# recompute one bench week by hand from raw
b = D['records']['benchWeek'][0]; r = raw[b['y']]
tid = [t['id'] for t in r['teams'] if fr(t['owners']) == b['key']][0]
ent = [e for t_, full, e in r['weeks'][str(b['wk'])] if t_ == tid][0]
act = sum(e[2] for e in ent if e[1] not in (20, 21))
check('bench actual matches team score', abs(act - b['act']) < 0.05, f'{act} vs {b["act"]}')
gs = [x for x in r['games'] if x[0] == b['wk'] and tid in (x[1], x[3])][0]
check('bench actual = official score', abs(act - (gs[2] if gs[1] == tid else gs[4])) < 0.05)

# ---------- 13. draft sanity
for y, s in SEAS.items():
    n = len(raw[y]['draft'])
    check(f'{y} draft complete', len(s['draft']) == n, f'{len(s["draft"])} vs {n}')
    for d in s['draft'][:3]:
        p = raw[y]['players'].get(str([q for q in raw[y]['draft'] if q[0] == d['pick']][0][3]))
        check(f'{y} pick {d["pick"]} name', p and p[0] == d['player'], f'{d["player"]} vs {p}')
st_ = D['records']['steals'][0]
check('top steal is real', st_['pts'] > AUD.get('topStealMinPts', 300) and st_['rd'] >= 4, st_)

# ---------- 14. odds sum correctly
O = D['odds']
_cur = [r for r in raw.values() if not r['done']]
PO_N = _cur[-1]['settings']['po'] if _cur else 6
DIV_N = len(_cur[-1]['settings']['divisions']) if _cur and len(_cur[-1]['settings']['divisions']) > 1 else 0
BYE_N = 2 if PO_N == 6 else 0
if O:
    check(f'odds playoffs sum to {PO_N}', abs(sum(o['po'] for o in O) - PO_N) < 0.05, sum(o['po'] for o in O))
    check('odds titles sum to 1', abs(sum(o['title'] for o in O) - 1) < 0.01, sum(o['title'] for o in O))
    check(f'odds divisions sum to {DIV_N}', abs(sum(o['div'] for o in O) - DIV_N) < 0.05, sum(o['div'] for o in O))
    check(f'odds byes sum to {BYE_N}', abs(sum(o['bye'] for o in O) - BYE_N) < 0.05)
    check('odds finals sum to 2', abs(sum(o['final'] for o in O) - 2) < 0.05)
for o in O:
    check(f'odds ordering {o["key"]}', o['title'] <= o['final'] <= o['po'] + 1e-9 and o['bye'] <= o['po'] + 1e-9)

# ---------- 15. recaps: top score line matches the week's max
bad = 0
for key, rc in D['recaps'].items():
    if rc['po']: continue
    mx = max(max(g[1], g[3]) for g in rc['games'])
    if f'{mx:.1f}' not in rc['lines'][0]: bad += 1
check('recap top scores', bad == 0, f'{bad} recaps mismatched')

# ---------- 16. schedule swap: actual equals ESPN wins total
for k, m in MK.items():
    espn = sum(t['w'] + t['t'] / 2 for y, r in raw.items() if r['done'] for t in r['teams'] if fr(t['owners']) == k)
    check(f'swap actual wins {k}', abs(m['swapW'] - espn) <= 2, f'{m["swapW"]} vs ESPN {espn}')
for x in D['records']['gifted'] + D['records']['robbed']:
    check(f'swap pct sane {x["y"]} {x["mgr"]}', 0 < x['pmake'] < 1 or (x['made'] and x['pmake'] > 0), x)

# ---------- 17. favorites: 2 per completed season
check('favorites per season', sum(m['choke']['fav'] for m in D['managers']) == 2 * sum(1 for r in raw.values() if r['done']))

# ---------- 18. standings race final week equals standings order
for y, s in SEAS.items():
    if not s['done']: continue
    last = {int(t): v[-1] for t, v in s['race'].items()}
    check(f'{y} race has all teams', len(last) == s['teams'] and sorted(last.values()) == list(range(1, s['teams'] + 1)))


# ---------- 19. best possible lineup: independent exact assignment (Hungarian algorithm) on every full week
try:
    from scipy.optimize import linear_sum_assignment
    import numpy as np
    def exact(ents, slots):
        slot_list = []
        for sid, c in slots.items():
            if sid in ('20', '21') or not int(c): continue
            slot_list += [sid] * int(c)
        def ok(e, sid):
            el = set(e[3].split('.')) if e[3] else set()
            if el & {'2', '4', '6'}: el.add('23')
            if e[1] not in (20, 21, -1): el.add(str(e[1]))
            return sid in el
        M = np.zeros((len(ents), len(slot_list)))
        for i, e in enumerate(ents):
            for j, sid in enumerate(slot_list):
                M[i, j] = -(e[2] + 1000) if ok(e, sid) else 0
        r_, c_ = linear_sum_assignment(M)
        return sum(ents[i][2] for i, j in zip(r_, c_) if M[i, j] < 0)
    bw = {(b['y'], b['wk'], b['key']): b for b in D['records']['benchWeek']}
    nweeks = 0; mism = 0; below = 0
    for y, r in raw.items():
        if not r['tx']: continue
        tm = {t['id']: fr(t['owners']) for t in r['teams']}
        reg = r['settings']['reg']
        for mp, rows in r['weeks'].items():
            for tid, full, ents in rows:
                if not full: continue
                act = sum(e[2] for e in ents if e[1] not in (20, 21)); opt = exact(ents, r['settings']['slots'])
                nweeks += 1
                if opt + 0.01 < act: below += 1
                b = bw.get((y, int(mp), tm[tid]))
                if b and abs(b['opt'] - opt) > 0.05: mism += 1
    check('best lineup never below actual', below == 0, below)
    check('bench records match exact lineups', mism == 0, mism)
    # efficiency recomputed for every manager
    eff = collections.defaultdict(lambda: [0.0, 0.0])
    for y, r in raw.items():
        if not r['tx']: continue
        tm = {t['id']: fr(t['owners']) for t in r['teams']}
        gm = {}
        for x in r['games']:
            gm[(x[0], x[1])] = x[5]; gm[(x[0], x[3])] = x[5]
        for mp, rows in r['weeks'].items():
            for tid, full, ents in rows:
                if not full or gm.get((int(mp), tid)) not in ('NONE', 'WINNERS_BRACKET'): continue
                act = sum(e[2] for e in ents if e[1] not in (20, 21)); opt = max(exact(ents, r['settings']['slots']), act)
                eff[tm[tid]][0] += act; eff[tm[tid]][1] += opt
    for k, (a, o) in eff.items():
        check(f'lineup efficiency {k}', abs(MK[k]['bench']['eff'] - round(a / o * 100, 1)) <= 0.1, f'{MK[k]["bench"]["eff"]} vs {a / o * 100:.1f}')
except ImportError:
    print('note: scipy not available, skipped exact lineup check')

# ---------- 20. live season: previews, odds history, clinch badges, awards
L = D.get('live')
if L:
    O = {o['key']: o for o in D['odds']}
    if L.get('preview'):
        teams_in = [g['hk'] for g in L['preview']['games']] + [g['ak'] for g in L['preview']['games']]
        check('preview covers every team once', sorted(teams_in) == sorted(O), teams_in)
        check('one game of the week', sum(1 for g in L['preview']['games'] if g.get('gotw')) == 1)
        for g in L['preview']['games']:
            check(f'preview win chance {g["hk"]}', 0 < g['hwin'] < 1 and ((g['hp'] >= g['ap']) == (g['hwin'] >= 0.5)), g['hwin'])
            for side in (g['hs'], g['as_']):
                check(f'winning helps {g["hk"]}/{g["ak"]}', side['poWin'] + 0.03 >= side['poLose'], side)
            # the stake bounds the unconditional odds
            for k_, sd_, pw in ((g['hk'], g['hs'], g['hwin']), (g['ak'], g['as_'], 1 - g['hwin'])):
                check(f'stake brackets odds {k_}', min(sd_['poWin'], sd_['poLose']) - 0.02 <= O[k_]['po'] <= max(sd_['poWin'], sd_['poLose']) + 0.02, (sd_, O[k_]['po']))
    for k, hist in L['oddsHist'].items():
        check(f'odds history ends at current {k}', abs(hist[-1][1] - O[k]['po']) < 0.002 and abs(hist[-1][2] - O[k]['title']) < 0.002)
    wk_ = max(len(v) for v in L['oddsHist'].values())
    for i in range(wk_):
        check(f'odds history week {i + 1} sums', abs(sum(v[i][1] for v in L['oddsHist'].values()) - PO_N) < 0.05 and abs(sum(v[i][2] for v in L['oddsHist'].values()) - 1) < 0.02)
    for o in D['odds']:
        if o['status'] in ('po', 'div'): check(f'clinched {o["key"]} has 100% odds', o['po'] >= 0.999, o['po'])
        if o['status'] == 'out': check(f'eliminated {o["key"]} has 0% odds', o['po'] <= 0.001, o['po'])
        check(f'max wins {o["key"]}', o['maxW'] == o['w'] + o['rem'])
for y, A in (D.get('awards') or {}).items():
    y = int(y); hi = max(x for g in games[y] for x in (g[2], g[4]))
    top = next(a for a in A['list'] if a['code'] == 'high')
    check(f'{y} top-score award', abs(float(top['value']) - hi) < 0.01, f'{top["value"]} vs {hi}')
    pfw = max(raw[y]['teams'], key=lambda t: t['pf'])
    check(f'{y} points champion', next(a for a in A['list'] if a['code'] == 'pf')['key'] == fr(pfw['owners']))

# ---------- 21. seeding rule (independent): wins, then H2H only if all tied teams met equally (H2H_RECORD leagues), else points
def _order(ids, W, PF, rec, h2h=True):
    out, left = [], list(ids)
    while left:
        top = max(W[t] for t in left); grp = [t for t in left if W[t] == top]
        if len(grp) > 1:
            cnts = {rec[a][b][1] for a in grp for b in grp if a != b}
            if h2h and len(cnts) == 1 and 0 not in cnts:
                hp = {a: sum(rec[a][b][0] for b in grp if b != a) / sum(rec[a][b][1] for b in grp if b != a) for a in grp}
                grp.sort(key=lambda t: (-hp[t], -PF[t]))
                best = [t for t in grp if hp[t] == hp[grp[0]]]
                pick = max(best, key=lambda t: PF[t])
            else: pick = max(grp, key=lambda t: PF[t])
        else: pick = grp[0]
        out.append(pick); left.remove(pick)
    return out
def _seeds(r):
    reg = r['settings']['reg']; ids = [t['id'] for t in r['teams']]
    W = {t: 0.0 for t in ids}; PF = {t: 0.0 for t in ids}
    rec = {a: {b: [0.0, 0] for b in ids} for a in ids}
    for g in r['games']:
        if g[0] > reg or (g[2] == 0 and g[4] == 0): continue
        h, hs, a, as_ = g[1], g[2], g[3], g[4]
        PF[h] += hs; PF[a] += as_
        wh = 1.0 if hs > as_ else 0.0 if hs < as_ else (1.0 if g[6] == 'HOME' else 0.0 if g[6] == 'AWAY' else 0.5)  # ESPN awards a tied game to its recorded winner
        W[h] += wh; W[a] += 1 - wh
        rec[h][a][0] += wh; rec[a][h][0] += 1 - wh; rec[h][a][1] += 1; rec[a][h][1] += 1
    divs = collections.defaultdict(list)
    for t in r['teams']: divs[t['div']].append(t['id'])
    h2h = r['settings'].get('seeding') != 'TOTAL_POINTS_SCORED'
    if len(divs) > 1:
        dw = [_order(m, W, PF, rec, h2h)[0] for m in divs.values()]
        first = _order(dw, W, PF, rec, h2h)
    else: first = []
    return first + _order([t for t in ids if t not in first], W, PF, rec, h2h)
for y, r in sorted(raw.items()):
    SY = AUD.get('seedingYears') or [0, 0]
    if r['done'] and SY[0] <= y <= SY[1]:
        mine = _seeds(r); espn = [t['id'] for t in sorted(r['teams'], key=lambda t: t['seed'])]
        check(f'{y} seeding rule reproduces ESPN', mine == espn, f'{mine} vs {espn}')
L = D.get('live') or {}
M = L.get('machine')
if M:
    r = raw[M['y']]; reg = r['settings']['reg']
    check('machine espnSeeds from ESPN', M['espnSeeds'] == [t['id'] for t in sorted(r['teams'], key=lambda t: t['seed'] or 99)])
    if all(t['seed'] for t in r['teams']):
        check(f'{M["y"]} live seeding rule reproduces ESPN', _seeds(r) == M['espnSeeds'], (_seeds(r), M['espnSeeds']))
    left = [g for g in r['games'] if g[0] <= reg and g[0] > M['played']]
    check('machine games = remaining schedule', sorted((g[0], g[1], g[3]) for g in left) == sorted(tuple(g[:3]) for g in M['games']), (len(left), len(M['games'])))
    check('machine win chances in (0,1)', all(0 < g[3] < 1 for g in M['games']))
    played = [g for g in r['games'] if g[0] <= M['played']]
    check('machine finished games', len(played) == len(M['done']))
    for t in M['teams']:
        rt = next(x for x in r['teams'] if x['id'] == t['tid'])
        check(f'machine record {t["key"]}', t['w'] == rt['w'] and t['l'] == rt['l'] and abs(t['pf'] - rt['pf']) < 0.05, (t, rt['w'], rt['l'], rt['pf']))

# ---------- 22. schedule-swap grid and weekly all-play on season pages
for sd in D['seasons']:
    S = sd.get('swap'); r = raw[sd['y']]; reg = r['settings']['reg']
    if not S: check(f'{sd["y"]} has a schedule grid', False); continue
    G = [g for g in r['games'] if g[0] <= reg and (r['done'] or g[0] <= S['wks'][-1])]
    EW = {(g[0], frozenset((g[1], g[3]))): (g[1] if g[6] == 'HOME' else g[3]) for g in G if g[2] == g[4] and g[6] in ('HOME', 'AWAY')}
    def rs(a, b, wk): return (1 if EW[(wk, frozenset((a, b)))] == a else 0) if sc[a][wk] == sc[b][wk] and (wk, frozenset((a, b))) in EW else (1 if sc[a][wk] > sc[b][wk] else 0.5 if sc[a][wk] == sc[b][wk] else 0)
    sc = collections.defaultdict(dict); op = collections.defaultdict(dict)
    for g in G: sc[g[1]][g[0]] = g[2]; sc[g[3]][g[0]] = g[4]; op[g[1]][g[0]] = g[3]; op[g[3]][g[0]] = g[1]
    for i, t in enumerate(S['order']):
        rt = next(x for x in r['teams'] if x['id'] == t)
        if r['done']: check(f'{sd["y"]} grid diagonal = record {t}', abs(S['m'][i][i] - (rt['w'] + rt['t'] / 2)) < 1e-9, (S['m'][i][i], rt['w']))
        for j, b in enumerate(S['order']):
            w = 0.0
            for wk, o in op[b].items():
                o = b if o == t else o
                w += rs(t, o, wk)
            check(f'{sd["y"]} grid {t} on {b}', abs(w - S['m'][i][j]) < 1e-9, (w, S['m'][i][j]))
        apw = sum(sum(rs(t, o, wk) for o in sc if o != t and wk in sc[o]) for wk in sc[t])
        check(f'{sd["y"]} weekly all-play total {t}', abs(apw - sum(x or 0 for x in S['ap'][i])) < 1e-9)
cur = [x for x in D['seasons'] if not x['done']]
if cur and D['power']:
    S = cur[-1]['swap']
    for row in D['power'][-1]['rows']:
        i = S['order'].index(row['tid'])
        check(f'power all-play matches grid {row["key"]}', abs(sum(S['ap'][i]) / (len(S['wks']) * S['opps']) - row['allplay']) < 0.001)

# ---------- 23. finish distribution and Sacko odds
if D['odds'] and 'place' in D['odds'][0]:
    n_ = len(D['odds'][0]['place'])
    for o in D['odds']:
        check(f'finish places sum to 1 {o["key"]}', abs(sum(o['place']) - 1) < 0.002, sum(o['place']))
        check(f'playoff odds = top-{PO_N} finishes {o["key"]}', abs(sum(o['place'][:PO_N]) - o['po']) < 0.002, (sum(o['place'][:PO_N]), o['po']))
        if LADDER and o['po'] >= 0.999: check(f'no Sacko for a playoff lock {o["key"]}', o['sacko'] == 0)
    for i in range(n_):
        check(f'finish place {i + 1} filled once', abs(sum(o['place'][i] for o in D['odds']) - 1) < 0.003)
    if LADDER: check('Sacko odds sum to 1', abs(sum(o['sacko'] for o in D['odds']) - 1) < 0.005)
    else: check('no Sacko odds without a ladder', all(o['sacko'] is None for o in D['odds']))
# the losers' ladder in the sim matches every 6-team-playoff season since 2019: reseeded W1vW2, L1vW3, L2vL3, then loser(L1vW3) vs loser(L2vL3)
for y, r in raw.items():
    if not LADDER or not r['done'] or r['settings']['po'] != 6 or len(r['teams']) != 12: continue
    sd = {t['id']: t['seed'] for t in r['teams']}; reg = r['settings']['reg']
    lad = sorted([g for g in r['games'] if g[5] == 'LOSERS_CONSOLATION_LADDER'], key=lambda g: g[0])
    wks = sorted({g[0] for g in lad})
    if len(wks) < 3: continue
    def won(g): return g[1] if g[6] == 'HOME' else g[3]
    def lost(g): return g[3] if g[6] == 'HOME' else g[1]
    w1 = {frozenset((sd[g[1]], sd[g[3]])): g for g in lad if g[0] == wks[0]}
    W = sorted(sd[won(g)] for g in w1.values()); Lz = sorted(sd[lost(g)] for g in w1.values())
    exp2 = {frozenset((W[0], W[1])), frozenset((Lz[0], W[2])), frozenset((Lz[1], Lz[2]))}
    g2 = {frozenset((sd[g[1]], sd[g[3]])): g for g in lad if g[0] == wks[1]}
    check(f'{y} ladder week 2 pairings', set(g2) == exp2, (set(g2), exp2))
    if set(g2) == exp2:
        bl = sd[lost(g2[frozenset((Lz[0], W[2]))])]; cl = sd[lost(g2[frozenset((Lz[1], Lz[2]))])]
        g3 = [g for g in lad if g[0] == wks[2] and {sd[g[1]], sd[g[3]]} == {bl, cl}]
        last = next(t for t in r['teams'] if t['rank'] == 12)
        check(f'{y} Sacko game is loser vs loser', len(g3) == 1 and sd[lost(g3[0])] == last['seed'], (bl, cl, last['seed']))

# ---------- 25. auction market: prices come straight from raw, fair prices redistribute the same dollars
AU = D.get('auction')
if AU:
    for yr in AU['years']:
        r = raw[yr['y']]; spent = collections.Counter()
        for p in r['draft']: spent[p[2]] += p[5]
        for t in yr['teams']:
            check(f"{yr['y']} auction spend {t['key']}", t['spent'] == spent[t['tid']], (t['spent'], spent[t['tid']]))
        check(f"{yr['y']} fair prices total the money spent", sum(t['fair'] for t in yr['teams']) == sum(spent.values()))
        check(f"{yr['y']} surplus nets to zero", sum(t['surp'] for t in yr['teams']) == 0)
        bids = sorted((p[5] for p in r['draft']), reverse=True)
        check(f"{yr['y']} top price", yr['index']['top'] == bids[0], (yr['index']['top'], bids[0]))
        sd = next(x for x in D['seasons'] if x['y'] == yr['y'])
        check(f"{yr['y']} draft rows carry fair prices", all(d.get('fair') is not None for d in sd['draft']))
    for b in AU['bargains'][:3] + AU['overpays'][:3]:
        r = raw[b['y']]; hit = [p for p in r['draft'] if r['players'].get(str(p[3]), ['?'])[0] == b['player'] and p[5] == b['bid']]
        check(f"auction record {b['player']} {b['y']} bought at ${b['bid']}", len(hit) >= 1)
        check(f"auction record {b['player']} surplus = fair - paid", b['surp'] == b['fair'] - b['bid'])

# ---------- 24. points wildcard: the real bracket = top (po - n) by ESPN's record order + the n top scorers among the rest
PWC = CFG.get('pointsWildcard')
if PWC:
    for y, r in sorted(raw.items()):
        if not r['done'] or y < PWC['from']: continue
        po_, k_ = r['settings']['po'], PWC['spots']
        order = [t['id'] for t in sorted(r['teams'], key=lambda t: t['seed'])]
        pf_ = {t['id']: t['pf'] for t in r['teams']}
        want = set(order[:po_ - k_]) | set(sorted(order[po_ - k_:], key=lambda t: -pf_[t])[:k_])
        field = {x for g in r['games'] if g[5] == 'WINNERS_BRACKET' for x in (g[1], g[3])}
        check(f'{y} bracket follows the points wildcard', field == want, (sorted(field), sorted(want)))
    M_ = (D.get('live') or {}).get('machine')
    if M_ and M_['y'] >= PWC['from']: check('machine carries the points wildcard', M_.get('pw') == PWC['spots'], M_.get('pw'))

print(f'PASSED {passes}, FAILED {len(fails)}')
for f in fails[:80]: print(' -', f)
sys.exit(1 if fails else 0)
