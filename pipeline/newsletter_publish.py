"""Check a newsletter issue against the league's fact sheet, then save it to <league dir>/newsletter/.

Usage: python3 pipeline/newsletter_publish.py LEAGUE_CONFIG ISSUE_JSON [--check]
Exits non-zero, printing why, if the issue is malformed or uses a number the fact sheet doesn't contain.
With --check it only checks. Prints the GroupMe text when it saves.
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(sys.argv[1])); issue = json.load(open(sys.argv[2]))
facts = json.loads(subprocess.run([sys.executable, os.path.join(ROOT, 'pipeline', 'newsletter_facts.py'), sys.argv[1]],
                                  capture_output=True, text=True, check=True).stdout)
problems = []

# ---- shape
for k, t in (('y', int), ('wk', int), ('title', str), ('dek', str), ('sections', list), ('groupme', str)):
    if not isinstance(issue.get(k), t): problems.append(f'missing or wrong type: {k}')
if not problems:
    if not facts.get('seasonOver') and (issue['y'], issue['wk']) != (facts['season'], facts['week']):
        problems.append(f"issue is for {issue['y']} week {issue['wk']}, but the data is {facts['season']} week {facts['week']}")
    if len(issue['title']) > 80: problems.append('title is over 80 characters')
    if len(issue['groupme']) > 700: problems.append('groupme teaser is over 700 characters')
    if not 1 <= len(issue['sections']) <= 7: problems.append('use 1–7 sections')
    for s in issue['sections']:
        if not isinstance(s.get('head'), str) or not isinstance(s.get('body'), list) or not all(isinstance(p, str) for p in s['body']):
            problems.append('each section needs "head" (text) and "body" (list of paragraphs)')
    words = sum(len(p.split()) for s in issue['sections'] for p in s.get('body', []))
    if words > 900: problems.append(f'{words} words; keep it under 900')

# ---- numbers: every figure of 10+ or with decimals must come from the fact sheet
allowed = set()
def walk(v):
    if isinstance(v, bool): return
    if isinstance(v, (int, float)):
        for x in (v, abs(v)):
            allowed.update({f'{x:.0f}', f'{x:.1f}', f'{x:.2f}'})
            if 0 <= x <= 1: allowed.update({f'{x * 100:.0f}', f'{x * 100:.1f}'})
    elif isinstance(v, str):
        allowed.update(re.findall(r'\d+(?:\.\d+)?', v.replace(',', '')))
    elif isinstance(v, dict): [walk(x) for x in v.values()]
    elif isinstance(v, list): [walk(x) for x in v]
walk(facts)
for o in facts.get('playoffOdds', []):              # week-over-week change in playoff odds, in points
    if o.get('playoffOddsLastWeek') is not None:
        allowed.add(f"{abs(o['playoffOdds'] - o['playoffOddsLastWeek']) * 100:.0f}")
for g in facts.get('nextWeek', []):
    allowed.add(f"{(1 - g['homeWinChance']) * 100:.0f}"); allowed.add(f"{g['playoffOddsSwing'] * 100:.0f}")
text = ' '.join([issue.get('title', ''), issue.get('dek', ''), issue.get('groupme', '')] +
                [p for s in issue.get('sections', []) for p in [s.get('head', '')] + s.get('body', [])])
for n in re.findall(r'(?<![\w.])\d[\d,]*(?:\.\d+)?', text):
    n = n.replace(',', '')
    if ('.' in n or float(n) >= 10) and n not in allowed and n.rstrip('0').rstrip('.') not in allowed and not (1990 <= float(n) <= 2100):
        problems.append(f'number not in the fact sheet: {n}')

if problems:
    print('Issue rejected:\n- ' + '\n- '.join(dict.fromkeys(problems))); sys.exit(1)
if '--check' in sys.argv:
    print('Issue OK.'); sys.exit()

out = os.path.join(ROOT, CFG['site']['dir'], 'newsletter'); os.makedirs(out, exist_ok=True)
name = f"{issue['y']}-w{issue['wk']:02d}.json"
json.dump(issue, open(os.path.join(out, name), 'w'), indent=1, ensure_ascii=False)
ip = os.path.join(out, 'index.json')
idx = json.load(open(ip)) if os.path.exists(ip) else []
idx = [x for x in idx if (x['y'], x['wk']) != (issue['y'], issue['wk'])]
idx.insert(0, dict(y=issue['y'], wk=issue['wk'], title=issue['title'], dek=issue['dek'], file=name))
idx.sort(key=lambda x: (-x['y'], -x['wk']))
json.dump(idx, open(ip, 'w'), indent=1, ensure_ascii=False)
print(f'Saved {os.path.relpath(os.path.join(out, name), ROOT)}\n\nGroupMe:\n{issue["groupme"]}')
