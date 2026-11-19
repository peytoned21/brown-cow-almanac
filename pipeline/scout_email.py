"""Render the daily team-scout email from a small JSON file written by the scout task.

Usage: python3 pipeline/scout_email.py IN_JSON OUT_HTML

IN_JSON shape (plain-text values; this script escapes them):
{
 "title": "Thursday, Nov 19 · TNF day",
 "headline": "Two lineup fixes before 8:15 tonight",
 "actions": [{"league": "AGS", "text": "Add Jets D/ST, drop Patriots D/ST", "by": "Before Sun 1:00", "level": "now|soon|fyi"}],
 "leagues": [{
   "name": "Any Given Sunday", "team": "Uncle Nasty Fingers", "record": "5-5 · 6th",
   "matchup": {"opp": "Jeni Gee Fellows (5-5)", "me": "135.2", "them": "123.1", "label": "Projected", "note": "Win chance 64%"},
   "lineup": [{"slot": "QB", "name": "Caleb Williams", "team": "CHI", "proj": "18.8", "flag": "", "note": "Sun 1:00"}],
   "yesterday": ["Nico Collins 19.9 (proj 13.4)"],
   "moves": [{"name": "Kyle Pitts Sr.", "pos": "TE", "team": "ATL", "status": "Free agent", "drop": "Dallas Goedert", "why": "..."}],
   "news": [{"player": "Puka Nacua", "text": "Suspended three games; lines up with his IR stint."}],
   "almanac": ["Playoff odds 41% (+12 this week)"]
 }],
 "notes": [{"title": "Fun stuff", "text": "..."}],
 "footer": "Suggestions only; nothing was changed on ESPN."
}
Any section may be omitted or empty.
"""
import html, json, sys

INK, MUTED, LINE, BG, CARD = '#2b2118', '#7a6a5c', '#e7ddd2', '#f6f1ea', '#ffffff'
BROWN, GREEN, RED, AMBER = '#5b3a29', '#2f6b3a', '#a3322a', '#9a6b12'
LEVEL = {'now': (RED, 'DO NOW'), 'soon': (AMBER, 'SOON'), 'fyi': (MUTED, 'FYI')}
FLAG = {'out': RED, 'bye': RED, 'empty': RED, 'doubtful': RED, 'questionable': AMBER, 'swap': AMBER, 'ok': GREEN}


def e(s):
    return html.escape(str(s if s is not None else ''))


def section(title, body):
    return (f'<tr><td style="padding:18px 20px 4px;font:700 12px/1.4 Arial,sans-serif;letter-spacing:.08em;color:{MUTED};'
            f'text-transform:uppercase">{e(title)}</td></tr><tr><td style="padding:0 20px 6px">{body}</td></tr>')


def actions(items):
    rows = ''
    for a in items:
        c, lab = LEVEL.get(a.get('level', 'soon'), LEVEL['soon'])
        rows += (f'<tr><td style="padding:8px 0;border-bottom:1px solid {LINE};vertical-align:top;width:64px">'
                 f'<table cellpadding="0" cellspacing="0"><tr><td bgcolor="{c}" style="background:{c};padding:2px 6px;border-radius:3px;font:700 10px Arial,sans-serif;color:#ffffff">{lab}</td></tr></table></td>'
                 f'<td style="padding:8px 0;border-bottom:1px solid {LINE};font:15px/1.4 Arial,sans-serif;color:{INK}">'
                 f'<b>{e(a.get("league"))}</b> · {e(a.get("text"))}'
                 + (f'<div style="font:12px Arial,sans-serif;color:{MUTED}">{e(a["by"])}</div>' if a.get('by') else '') + '</td></tr>')
    return f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>'


def league(L):
    out = (f'<tr><td style="padding:22px 20px 0"><div style="border-top:3px solid {BROWN};padding-top:12px;'
           f'font:700 19px Georgia,serif;color:{INK}">{e(L.get("name"))}</div>'
           f'<div style="font:13px Arial,sans-serif;color:{MUTED}">{e(L.get("team"))}'
           + (f' · {e(L["record"])}' if L.get('record') else '') + '</div></td></tr>')
    m = L.get('matchup')
    if m:
        out += (f'<tr><td style="padding:10px 20px 0"><table width="100%" cellpadding="0" cellspacing="0" style="border-radius:6px">'
                f'<tr><td bgcolor="{BG}" style="background:{BG};padding:10px 12px;font:12px Arial,sans-serif;color:{MUTED}">{e(m.get("label", "Projected"))} vs {e(m.get("opp"))}'
                f'<div style="font:700 22px Arial,sans-serif;color:{INK}">{e(m.get("me"))} <span style="color:{MUTED};font-weight:400">–</span> {e(m.get("them"))}</div>'
                + (f'<div style="font:13px Arial,sans-serif;color:{INK}">{e(m["note"])}</div>' if m.get('note') else '') + '</td></tr></table></td></tr>')
    if L.get('lineup'):
        rows = ''
        for p in L['lineup']:
            c = FLAG.get((p.get('flag') or '').lower())
            dot = f'<span style="color:{c}">●</span> ' if c else ''
            rows += (f'<tr><td style="padding:5px 6px 5px 0;font:700 11px Arial,sans-serif;color:{MUTED};width:38px;border-bottom:1px solid {LINE}">{e(p.get("slot"))}</td>'
                     f'<td style="padding:5px 0;font:14px Arial,sans-serif;color:{INK};border-bottom:1px solid {LINE}">{dot}{e(p.get("name"))} '
                     f'<span style="color:{MUTED};font-size:12px">{e(p.get("team"))}</span>'
                     + (f'<div style="font:12px Arial,sans-serif;color:{c or MUTED}">{e(p["note"])}</div>' if p.get('note') else '')
                     + f'</td><td align="right" style="padding:5px 0;font:14px Arial,sans-serif;color:{INK};border-bottom:1px solid {LINE};width:44px">{e(p.get("proj"))}</td></tr>')
        out += section('Lineup', f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>')
    if L.get('yesterday'):
        out += section('Yesterday', ''.join(f'<div style="font:14px/1.5 Arial,sans-serif;color:{INK}">{e(x)}</div>' for x in L['yesterday']))
    if L.get('moves'):
        body = ''
        for mv in L['moves']:
            body += (f'<div style="padding:8px 0;border-bottom:1px solid {LINE};font:14px/1.45 Arial,sans-serif;color:{INK}">'
                     f'<b>{e(mv.get("name"))}</b> <span style="color:{MUTED};font-size:12px">{e(mv.get("pos"))} · {e(mv.get("team"))} · {e(mv.get("status"))}</span>'
                     + (f'<div style="font-size:12px;color:{MUTED}">Drop: {e(mv["drop"])}</div>' if mv.get('drop') else '')
                     + (f'<div>{e(mv["why"])}</div>' if mv.get('why') else '') + '</div>')
        out += section('Waivers & free agents', body)
    if L.get('news'):
        out += section('News', ''.join(f'<div style="padding:5px 0;font:14px/1.45 Arial,sans-serif;color:{INK}"><b>{e(n.get("player"))}:</b> {e(n.get("text"))}</div>' for n in L['news']))
    if L.get('almanac'):
        out += section('From the almanac', ''.join(f'<div style="padding:3px 0;font:14px/1.45 Arial,sans-serif;color:{INK}">· {e(x)}</div>' for x in L['almanac']))
    return out


def render(d):
    body = (f'<tr><td bgcolor="{BROWN}" style="background:{BROWN};padding:20px;color:#ffffff">'
            f'<div style="font:12px Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#e9dccf">Team scout · {e(d.get("title"))}</div>'
            f'<div style="font:700 22px/1.3 Georgia,serif;margin-top:6px">{e(d.get("headline"))}</div></td></tr>')
    if d.get('actions'):
        body += section('Today’s to-do', actions(d['actions']))
    for L in d.get('leagues') or []:
        body += league(L)
    for n in d.get('notes') or []:
        body += section(n.get('title', ''), f'<div style="font:14px/1.5 Arial,sans-serif;color:{INK}">{e(n.get("text"))}</div>')
    body += (f'<tr><td style="padding:20px;font:12px Arial,sans-serif;color:{MUTED}">'
             f'{e(d.get("footer", "Suggestions only; nothing was changed on ESPN."))}</td></tr>')
    return (f'<!DOCTYPE html><html><body style="margin:0;background:{BG}">'
            f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{BG}" style="background:{BG}"><tr><td align="center" style="padding:12px">'
            f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="{CARD}" style="max-width:620px;background:{CARD};border-radius:8px;overflow:hidden">'
            f'{body}</table></td></tr></table></body></html>')


if __name__ == '__main__':
    open(sys.argv[2], 'w').write(render(json.load(open(sys.argv[1]))))
