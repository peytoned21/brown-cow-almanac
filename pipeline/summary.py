"""Print a short markdown summary of the latest refresh (for the Actions run page)."""
import json, sys

D = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'data.json'))
cur = D['meta'].get('cur')
if not cur:
    print('## Brown Cow Almanac\n\nThe season is final.')
    sys.exit()
y = cur['y']
print(f"## Brown Cow Almanac · {y} through Week {cur['week']}\n")
recs = [v for v in D['recaps'].values() if v['y'] == y]
if recs:
    r = max(recs, key=lambda v: v['wk'])
    print(f"**{r['label']}**\n")
    for line in r['lines']:
        print(f'- {line}')
    print()
if D.get('power'):
    top = D['power'][-1]['rows'][0]
    print(f"**Power rankings leader:** {top['team']} ({top['mgr']}, {top['w']}–{top['l']})\n")
prev = (D.get('live') or {}).get('preview') or {}
g = next((g for g in prev.get('games', []) if g.get('gotw')), None)
if g:
    print(f"**Game of the Week (Week {prev['wk']}):** {g['ht']} vs {g['at']}, projected {g['hp']}–{g['ap']}\n")
lab = {'div': 'clinched the division', 'po': 'clinched a playoff spot', 'out': 'eliminated'}
st = [f"{o['team']} {lab[o['status']]}" for o in D.get('odds', []) if o.get('status') in lab]
if st:
    print('**Clinches:** ' + '; '.join(st) + '\n')
print('Odds: ' + ', '.join(f"{o['team']} {round(o['po'] * 100)}%" for o in sorted(D.get('odds', []), key=lambda o: -o['po'])))
