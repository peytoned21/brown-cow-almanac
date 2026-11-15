"""Should the live-score job keep going? If an NFL game is on now or kicks off within the next few hours
(this week's ESPN scoreboard), prints how many seconds to wait before starting the next run (0 = now); otherwise 'no'.
That lets the job start its own next run instead of waiting on GitHub's schedule, which can run hours late or skip.
Usage: python3 pipeline/live_next.py [HOURS_AHEAD]
"""
import datetime, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nflbox

ahead = float(sys.argv[1]) if len(sys.argv) > 1 else 4
try:
    d = nflbox.get(f'{nflbox.SITE_API}/scoreboard')
except Exception as e:
    print('no'); sys.exit()
live_now = False; nxt = None
for e in d.get('events') or []:
    state = ((e.get('status') or {}).get('type') or {}).get('state')
    if state == 'in': live_now = True
    elif state == 'pre' and e.get('date'):
        dt = datetime.datetime.fromisoformat(e['date'].replace('Z', '+00:00')).timestamp() - time.time()
        if dt >= -1800 and (nxt is None or dt < nxt): nxt = dt
# prints how many seconds to wait before starting the next run (0 = now), or 'no'
if live_now or (nxt is not None and nxt < 85 * 60): print(0)
elif nxt is not None and nxt < ahead * 3600: print(int(min(nxt - 80 * 60, 4 * 3600)))
else: print('no')
