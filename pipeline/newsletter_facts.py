"""Fact sheet for the weekly newsletter: everything the writer may say, and nothing it may not.

Usage: python3 pipeline/newsletter_facts.py LEAGUE_CONFIG > facts.json
The newsletter is written from this file only (see pipeline/NEWSLETTER.md). Every number in an issue must appear here.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(sys.argv[1]))
D = json.load(open(os.path.join(ROOT, CFG['site']['dir'], 'data.json')))
MK = {m['key']: m for m in D['managers']}
cur = D['meta'].get('cur')
if not cur:
    print(json.dumps({'league': CFG['name'], 'seasonOver': True, 'champion': next(r for r in D['seasons'][-1]['rows'] if r['rank'] == 1)}, indent=1))
    sys.exit()
y, wk = cur['y'], cur['week']
who = lambda k: MK[k]['short']
rec = D['recaps'].get(f'{y}-{wk}') or {}
S = next(s for s in D['seasons'] if s['y'] == y)
rows = {r['key']: r for r in S['rows']}

games = []
for hk, hs, ak, as_ in rec.get('games', []):
    w, l = (hk, ak) if hs > as_ else (ak, hk)
    games.append(dict(winner=who(w), winnerTeam=rows[w]['team'], winnerScore=max(hs, as_), loser=who(l), loserTeam=rows[l]['team'], loserScore=min(hs, as_),
                      margin=round(abs(hs - as_), 2), allTimeSeries=D['h2h'].get(w, {}).get(l)))
P = D['power'][-1]['rows'] if D['power'] else []
hist = D['live'].get('oddsHist', {}) if D.get('live') else {}
odds = []
for o in sorted(D.get('odds', []), key=lambda o: -o['po']):
    h = hist.get(o['key'], [])
    prev = next((x for x in reversed(h) if x[0] == wk - 1), None)
    odds.append(dict(manager=who(o['key']), team=o['team'], record=f"{o['w']}–{o['l']}", playoffOdds=o['po'], titleOdds=o['title'],
                     playoffOddsLastWeek=prev[1] if prev else None, status={'po': 'clinched a playoff spot', 'div': 'clinched the division', 'out': 'eliminated'}.get(o.get('status'))))
pv = (D.get('live') or {}).get('preview') or {}
nxt = [dict(home=who(g['hk']), homeTeam=g['ht'], homeRecord=g['hrec'], away=who(g['ak']), awayTeam=g['at'], awayRecord=g['arec'],
            homeProjected=g['hp'], awayProjected=g['ap'], homeWinChance=g['hwin'], gameOfTheWeek=bool(g.get('gotw')),
            playoffOddsSwing=g['swing'], allTimeSeriesHomeFirst=g['h2h'],
            homeTopProjected=g.get('htop'), awayTopProjected=g.get('atop')) for g in pv.get('games', [])]
facts = dict(
    league=CFG['name'], season=y, week=wk, weeksInRegularSeason=D['live']['machine']['reg'] if D.get('live') else None,
    playoffSpots=D['live']['machine']['po'] if D.get('live') else None,
    managers={who(k): dict(fullName=MK[k]['name'], team=rows[k]['team'] if k in rows else MK[k]['team'], titles=MK[k]['titles']) for k in rows},
    thisWeek=dict(results=games, recapLines=rec.get('lines', [])),
    standings=[dict(manager=who(r['key']), team=r['team'], w=r['w'], l=r['l'], pointsFor=r['pf']) for r in sorted(S['rows'], key=lambda r: (-r['w'], -r['pf']))],
    powerRankings=[dict(rank=r['rank'], manager=who(r['key']), team=r['team'], record=f"{r['w']}–{r['l']}", movedSinceLastWeek=r.get('move', 0),
                        allPlayPct=r['allplay'], last3Avg=r['form']) for r in P],
    luck=[dict(manager=who(x['key']), wins=x['w'], winsDeserved=x['exp'], luck=x['luck']) for x in (D.get('curLuck') or [])],
    playoffOdds=odds,
    nextWeek=nxt,
    seasonAwardsRace=[dict(award=a['title'], leader=a['mgr'], value=a['value'], detail=a['detail']) for a in (D.get('awards', {}).get(str(y), {}).get('list') or [])],
    allTimeRivalries=[dict(a=who(r['a']), b=who(r['b']), aWins=r['w'], bWins=r['l'], games=r['n'], playoffMeetings=r['po']) for r in D.get('rivalries', [])[:8]],
    allTimeTitles={who(m['key']): m['titles'] for m in D['managers'] if m['titles']},
    siteUrl=CFG['site']['url'],
)
print(json.dumps(facts, indent=1, ensure_ascii=False))
