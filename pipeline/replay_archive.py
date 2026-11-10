"""Keep each finished week's game-day story for the matchup replay.

The live snapshot (pipeline/live.py) carries every matchup's win-chance and score path for the week plus its big
moments, but it is overwritten when the next week starts. Run after the Tuesday build: if the live snapshot is for a
week that is now final, this saves it to <league dir>/replays/<year>-w<week>.json and lists it in replays/index.json,
with the official final scores and each week's comeback (the lowest win chance a winner climbed back from).

Usage: python3 pipeline/replay_archive.py LEAGUE_CONFIG [--from LIVE_JSON]
"""
import datetime, json, os, sys, urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ET = ZoneInfo('America/New_York')


def when(minute):
    d = datetime.datetime.fromtimestamp(minute * 60, ET)
    return d.strftime('%a ') + d.strftime('%I:%M%p').lstrip('0').lower()


def main():
    cfg = json.load(open(sys.argv[1])); sd = os.path.join(ROOT, cfg['site']['dir'])
    D = json.load(open(os.path.join(sd, 'data.json')))
    if '--from' in sys.argv:
        L = json.load(open(sys.argv[sys.argv.index('--from') + 1]))
    else:
        req = urllib.request.Request(cfg['site']['liveUrl'] + '?t=' + str(int(datetime.datetime.now().timestamp())), headers={'User-Agent': 'brown-cow-almanac'})
        try:
            with urllib.request.urlopen(req, timeout=30) as r: L = json.load(r)
        except Exception as e:
            print('No live snapshot to keep:', e); return
    cur = D['meta'].get('cur'); M = (D.get('live') or {}).get('machine')
    if L.get('league') not in (None, cfg['site']['slug']) or not M or L.get('y') != M['y'] or L.get('wk', 99) > M['played']:
        print(f"Live snapshot is week {L.get('wk')} of {L.get('y')}; nothing final to keep."); return
    y, wk = L['y'], L['wk']
    key = {t['tid']: t['key'] for t in M['teams']}
    rec = D['recaps'].get(f'{y}-{wk}') or {}
    final = {}
    for a, as_, b, bs in rec.get('games', []):
        final[(a, b)] = (as_, bs); final[(b, a)] = (bs, as_)
    games = []
    for g in L['games']:
        hk, ak = key.get(g['h']), key.get(g['a'])
        if not hk or not ak: continue
        hs, as_ = final.get((hk, ak), (g['hs'], g['as_']))
        allh = g.get('hist') or []
        pre = [x for x in allh if len(x) > 2 and x[2] == 'p']
        game_pts = [x for x in allh if not (len(x) > 2 and x[2] == 'p')]
        hist = pre[-1:] + game_pts                          # the kickoff baseline, then the games
        win = hk if hs > as_ else ak if as_ > hs else None
        comeback = None
        if win and game_pts:
            path = [(x[0], x[1] if win == hk else 1 - x[1]) for x in game_pts]
            lo = min(path, key=lambda p: p[1])
            comeback = dict(low=round(lo[1], 3), at=lo[0], when=when(lo[0]))
        games.append(dict(hk=hk, ak=ak, h=g['h'], a=g['a'], hs=hs, as_=as_, win=win, hwin0=g.get('hwin0'),
                          hist=hist, moments=g.get('moments') or [], comeback=comeback))
    if not games:
        print('No matchups in the live snapshot.'); return
    out = os.path.join(sd, 'replays'); os.makedirs(out, exist_ok=True)
    name = f'{y}-w{wk:02d}.json'; path = os.path.join(out, name)
    if os.path.exists(path):
        old = json.load(open(path))
        if sum(len(g['hist']) for g in old['games']) > sum(len(g['hist']) for g in games):
            print(f'{name} already has a fuller replay; kept it.'); return
    json.dump(dict(y=y, wk=wk, games=games), open(path, 'w'), separators=(',', ':'))
    ip = os.path.join(out, 'index.json')
    idx = json.load(open(ip)) if os.path.exists(ip) else []
    idx = [x for x in idx if (x['y'], x['wk']) != (y, wk)]
    cb = [g for g in games if g['comeback'] and len(g['hist']) > 10]
    best = min(cb, key=lambda g: g['comeback']['low']) if cb else None
    idx.append(dict(y=y, wk=wk, file=name, games=[[g['hk'], g['ak']] for g in games],
                    comeback=dict(winner=best['win'], loser=best['ak'] if best['win'] == best['hk'] else best['hk'], **best['comeback']) if best else None))
    idx.sort(key=lambda x: (-x['y'], -x['wk']))
    json.dump(idx, open(ip, 'w'), indent=1)
    print(f'Saved {os.path.relpath(path, ROOT)}' + (f" · comeback: {best['win']} from {round(best['comeback']['low'] * 100)}% ({best['comeback']['when']})" if best else ''))


if __name__ == '__main__':
    main()
