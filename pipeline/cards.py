"""Link previews: render the share cards and write the pages that carry them.

- og/<id>.png      1200x630 images drawn by cards/card.html from data.json (home, every season, every manager)
- s/<year>/        tiny pages that show a season's card when the link is pasted, then open the site at #s-<year>
- m/<key>/         the same for each manager
- index.html       the home page's preview tags are rewritten between the og markers

Usage: python3 pipeline/cards.py LEAGUE_CONFIG      (after build.py and page.py; needs playwright + chromium)
"""
import functools, html, http.server, json, os, socketserver, sys, threading, urllib.parse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(sys.argv[1]))
SITE = CFG['site']['url']
ROOT = os.path.join(REPO, CFG['site']['dir'])
TITLE = CFG['page']['title']; NOUN = CFG.get('titleNoun', CFG['name'])
ART = (CFG['page'].get('art') or {}).get('painting') or CFG['site']['icon'] + '-512.png'
ACCENT = '#a8700c' if '--brass: #a8700c' in CFG['page'].get('css', '') else '#c4622b'
D = json.load(open(os.path.join(ROOT, 'data.json')))
MK = {m['key']: m for m in D['managers']}
cur = D['meta'].get('cur')
ver = f"{cur['y']}-{cur['week']}" if cur else str(D['seasons'][-1]['y'])


def wl(w, l, t=0):
    return f"{w}–{l}" + (f"–{t}" if t else '')


def tags(title, desc, img, url):
    e = html.escape
    return (f'<meta property="og:type" content="website"><meta property="og:site_name" content="{html.escape(TITLE)}">'
            f'<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">'
            f'<meta property="og:image" content="{SITE}{img}?v={ver}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
            f'<meta property="og:url" content="{SITE}{url}"><meta name="twitter:card" content="summary_large_image">'
            f'<meta name="description" content="{e(desc)}">')


def stub(path, title, desc, card, hash_):
    os.makedirs(os.path.join(ROOT, path), exist_ok=True)
    e = html.escape
    page = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title><meta name="robots" content="noindex,nofollow">{tags(title, desc, f"og/{card}.png", path + "/")}'
            f'<link rel="icon" href="../../{CFG["site"]["icon"]}-192.png"><meta http-equiv="refresh" content="0; url=../../#{hash_}">'
            f'<script>location.replace("../../#{hash_}")</script></head>'
            f'<body style="font-family:sans-serif;padding:24px"><a href="../../#{hash_}">{e(title)}</a></body></html>')
    open(os.path.join(ROOT, path, 'index.html'), 'w').write(page)


# ---------------------------------------------------------------- what each card says
cards = {}
if cur and D.get('power'):
    P = D['power'][-1]['rows']
    home_desc = f"{cur['y']} power rankings after Week {cur['week']}: " + ', '.join(f"{r['rank']}. {r['team']} ({wl(r['w'], r['l'])})" for r in P[:3])
    pv = (D.get('live') or {}).get('preview') or {}
    g = next((x for x in pv.get('games', []) if x.get('gotw')), None)
    if g: home_desc += f". Game of the Week: {MK[g['hk']]['short']} vs {MK[g['ak']]['short']}."
else:
    home_desc = f"{D['meta']['nDone']} champions, {len(D['managers'])} managers and every record since {D['meta']['founded']}."
cards['home'] = (TITLE, home_desc)
for s in D['seasons']:
    y = s['y']
    if s['done']:
        ch = next(r for r in s['rows'] if r['rank'] == 1)
        cards[f's-{y}'] = (f"{y} · {TITLE}", f"{MK[ch['key']]['short']} won it with {ch['team']}. {s.get('headline') or ''}".strip())
    else:
        cards[f's-{y}'] = (f"{y} · {TITLE}", home_desc)
for m in D['managers']:
    t = len(m['titles'])
    desc = f"{t} title{'s' if t != 1 else ''}{' (' + ', '.join(map(str, m['titles'])) + ')' if t else ''} · {wl(m['w'], m['l'], m['t'])} · {len(m['po'])} playoff trips · {m['team']}"
    cards[f"m-{m['key']}"] = (f"{m['name']} · {TITLE}", desc)


# ---------------------------------------------------------------- render
def render(ids):
    from playwright.sync_api import sync_playwright
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=REPO)
    handler.log_message = lambda *a, **k: None
    srv = socketserver.TCPServer(('127.0.0.1', 0), handler); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.makedirs(os.path.join(ROOT, 'og'), exist_ok=True)
    with sync_playwright() as p:
        exe = os.environ.get('CHROMIUM_PATH')
        b = p.chromium.launch(**({'executable_path': exe} if exe else {}))
        pg = b.new_page(viewport={'width': 1200, 'height': 630})
        for cid in ids:
            q = urllib.parse.urlencode(dict(c=cid, dir=CFG['site']['dir'], art=ART, brand=NOUN, room=CFG['site']['theme'], accent=ACCENT, paper=CFG['site']['bg']))
            pg.goto(f'http://127.0.0.1:{port}/cards/card.html?{q}')
            pg.wait_for_function("document.title === 'ready'", timeout=30000)
            pg.screenshot(path=os.path.join(ROOT, 'og', f'{cid}.png'))
        b.close()
    srv.shutdown()


if __name__ == '__main__':
    render(list(cards))
    for cid, (title, desc) in cards.items():
        if cid.startswith('s-'):
            stub(f"s/{cid[2:]}", title, desc, cid, cid)
        elif cid.startswith('m-'):
            stub(f"m/{cid[2:]}", title, desc, cid, cid)
    ip = os.path.join(ROOT, 'index.html'); s = open(ip).read()
    a, b = s.find('<!--og-->'), s.find('<!--/og-->')
    block = '<!--og-->' + tags(*cards['home'], 'og/home.png', '') + '<!--/og-->'
    if a != -1 and b != -1:
        s = s[:a] + block + s[b + len('<!--/og-->'):]
    else:
        s = s.replace('<meta name="robots"', block + '<meta name="robots"', 1)
    open(ip, 'w').write(s)
    print(f'{len(cards)} cards rendered; home: {cards["home"][1]}')
