"""Post the weekly recap to the league GroupMe through a GroupMe bot.

Needs GROUPME_BOT_ID (from dev.groupme.com/bots). With --dry, prints the message instead of posting.
Usage: python3 pipeline/groupme.py [DATA_JSON] [--dry]
"""
import json, os, sys, urllib.request

SITE = 'https://peytoned21.github.io/brown-cow-almanac/'
LIMIT = 1000   # GroupMe's cap on one message


def message(D):
    cur = D['meta'].get('cur')
    MK = {m['key']: m for m in D['managers']}
    if not cur:
        s = D['seasons'][-1]; ch = next(r for r in s['rows'] if r['rank'] == 1)
        return f"🐄 {s['y']} is in the books: {MK[ch['key']]['short']} ({ch['team']}) are champions.\n{SITE}"
    y, wk = cur['y'], cur['week']
    parts = [f"🐄 Brown Cow Almanac · Week {wk} recap"]
    recs = [v for v in D['recaps'].values() if v['y'] == y and v['wk'] == wk]
    if recs:
        parts.append('\n'.join('• ' + line for line in recs[0]['lines']))
    if D.get('power'):
        P = D['power'][-1]['rows']
        parts.append('Power rankings: ' + '  '.join(f"{r['rank']}. {MK[r['key']]['short']} {r['w']}–{r['l']}" for r in P[:5]))
    pv = (D.get('live') or {}).get('preview') or {}
    g = next((x for x in pv.get('games', []) if x.get('gotw')), None)
    if g:
        fav, p = (g['hk'], g['hwin']) if g['hwin'] >= 0.5 else (g['ak'], 1 - g['hwin'])
        parts.append(f"Game of the Week {pv['wk']}: {MK[g['hk']]['short']} vs {MK[g['ak']]['short']} ({MK[fav]['short']} {round(p * 100)}% to win; "
                     f"{round(g['swing'] * 100)} points of playoff odds on the line)")
    lab = {'div': 'clinched the division', 'po': 'clinched a playoff spot', 'out': 'eliminated'}
    cl = [f"{MK[o['key']]['short']} {lab[o['status']]}" for o in D.get('odds', []) if o.get('status') in lab]
    if cl:
        parts.append('Clinches: ' + '; '.join(cl))
    tail = f"Live scores Sunday, playoff machine and more: {SITE}"
    out = '\n\n'.join(parts)
    while len(out) + len(tail) + 2 > LIMIT and len(parts) > 1:   # drop recap lines from the bottom until it fits
        rl = parts[1].split('\n')
        if len(rl) > 2: parts[1] = '\n'.join(rl[:-1])
        else: parts.pop()
        out = '\n\n'.join(parts)
    return out + '\n\n' + tail


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    D = json.load(open(args[0] if args else 'data.json'))
    msg = message(D)
    bot = os.environ.get('GROUPME_BOT_ID', '').strip()
    if '--dry' in sys.argv or not bot:
        print(msg if bot or '--dry' in sys.argv else 'GROUPME_BOT_ID is not set; not posting.\n\n' + msg)
        sys.exit()
    req = urllib.request.Request('https://api.groupme.com/v3/bots/post', data=json.dumps({'bot_id': bot, 'text': msg}).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        print('Posted to GroupMe:', r.status)
