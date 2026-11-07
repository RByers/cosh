"""Exploration (docs/commits.md): per-commit facts for chromium/src main,
2023-W26 .. 2026-W44, joined to derived.sqlite. Local only, no network.
Usage, from the repo root: python3 scripts/commits_explore.py OUT.json"""
import json, os, re, sqlite3, subprocess, sys
from collections import Counter
sys.path.insert(0, os.getcwd())
from cosh.orgs import OrgResolver
from cosh.paths import load_scope
from cosh.bots import _PATTERNS
from cosh.extract import iso_week_of

REPO = os.path.expanduser("~/projects/shared/chromium")
DB = "/home/rbagent/projects/cosh/data/private/derived.sqlite"
SINCE, UNTIL = "2023-06-26T00:00:00Z", "2026-11-02T00:00:00Z"   # 2023-W26 .. 2026-W44
REV = re.compile(r"^Reviewed-on: https://chromium-review\.googlesource\.com/c/chromium/src/\+/(\d+)", re.M)
COAUTH = re.compile(r"^Co-authored-by:.*<([^>]+)>", re.M | re.I)

resolve, scope = OrgResolver(), load_scope()
db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
owner = {n: (e, b) for n, e, b in db.execute(
    "SELECT c.change_number, a.email, a.is_bot FROM changes c JOIN accounts a "
    "ON a.host=c.host AND a.account_id=c.owner_account WHERE c.status='MERGED'")}

env = dict(os.environ, GIT_NO_LAZY_FETCH="1", TZ="UTC")
p = subprocess.Popen(["git", "-C", REPO, "log", "main", "--first-parent", "--no-renames", "--date=format-local:%Y-%m-%d %H:%M:%S",
                      f"--since={SINCE}", f"--until={UNTIL}",
                      "--format=%x01%H%x00%ae%x00%cd%x00%B%x02", "--name-only"],
                     stdout=subprocess.PIPE, env=env, text=True, errors="replace")
out = []
for chunk in p.stdout.read().split("\x01")[1:]:
    head, _, files = chunk.partition("\x02")
    sha, ae, cdate, body = head.split("\x00", 3)
    files = [f for f in files.split("\n") if f]
    m = REV.search(body)
    cl = int(m.group(1)) if m else None
    oe, ob = owner.get(cl, (None, None))
    bot = bool(ob) if ob is not None else any(r.search(ae) for r in _PATTERNS)
    ins = sum(scope.includes(f) for f in files)
    out.append(dict(sha=sha, ae=ae.lower(), week=iso_week_of(cdate), date=cdate[:10], cl=cl,
                    owner=(oe or "").lower() or None, bot=bot, nfiles=len(files), nin=ins,
                    org=resolve(ae, cdate[:10]), coauth=[c.lower() for c in COAUTH.findall(body)],
                    revert=body.startswith("Revert ")))
json.dump(out, open(sys.argv[1], "w"))
c = Counter((r["bot"], r["cl"] is not None, r["cl"] in owner) for r in out)
print(len(out), c)
