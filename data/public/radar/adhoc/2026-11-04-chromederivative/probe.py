"""usage: probe.py name endpoint k=v ...  -> saves JSON to $OUT/name.json, prints summary"""
import sys, os, json, hashlib
sys.path.insert(0, '/home/rbagent/projects/cosh')
from cosh.radar import RadarClient, API
out = os.environ['OUT']
c = RadarClient(os.environ['CLOUDFLARE_API_TOKEN'])
args = sys.argv[1:]
# batch mode: lines "name endpoint k=v k=v" on stdin
jobs = [l.split() for l in sys.stdin if l.strip()] if args == ['-'] else [args]
for name, ep, *kv in jobs:
    p = f"{out}/{name}.json"
    if os.path.exists(p):
        continue
    params = dict(x.split('=', 1) for x in kv); params.setdefault('format', 'JSON')
    st, js, body, url = c.get(ep, params)
    json.dump({"url": url.replace(API, ''), "status": st, "response": js if js is not None else body}, open(p, 'w'))
    if st != 200:
        print(name, st, body[:300].replace('\n', ' '))
    else:
        print(name, 'ok')
