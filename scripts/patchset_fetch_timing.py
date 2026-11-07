"""Timing test (2026-11-07): full (no filter) patch-set fetches of 2026-W44 CLs,
with main from the shared clone as the have. docs/plan.md, 2026-11-07.

Usage: python3 scripts/patchset_fetch_timing.py OUT_DIR 100,300,1000,100
Writes data/private/git/chromium-patchsets.git (borrows main via alternates).
Each fetch takes the extract lock and logs server progress with timestamps.
"""
import json, os, random, re, sqlite3, subprocess, sys, time

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WT)
from cosh import contact, store  # noqa: E402

DATA = "/home/rbagent/projects/cosh/data/private"
R = f"{DATA}/git/chromium-patchsets.git"
SHARED = "/home/rbagent/projects/shared/chromium/objects"
URL = "https://chromium.googlesource.com/chromium/src.git"
OUT = sys.argv[1]
SIZES = [int(x) for x in sys.argv[2].split(",")]
os.environ["GIT_NO_LAZY_FETCH"] = "1"


def git(*a, **kw):
    return subprocess.run(["git", "-C", R, *a], capture_output=True, text=True, check=True, **kw).stdout


def init():
    if os.path.exists(R):
        return
    subprocess.run(["git", "init", "--quiet", "--bare", R], check=True)
    for k, v in [("log.mailmap", "false"), ("gc.auto", "0"), ("maintenance.auto", "false"),
                 ("core.logAllRefUpdates", "false")]:
        git("config", k, v)
    with open(f"{R}/objects/info/alternates", "w") as f:
        f.write(SHARED + "\n")


def pick():
    c = sqlite3.connect(f"file:{DATA}/derived.sqlite?mode=ro", uri=True)
    rows = c.execute("select change_number, patchsets from changes where close_week='2026-W44' "
                     "and project='chromium/src' and branch='main' order by change_number").fetchall()
    have = set(int(r.split("/")[2]) for r in git("for-each-ref", "--format=%(refname)", "refs/patchsets").split())
    rows = [r for r in rows if r[0] not in have]
    random.Random(44).shuffle(rows)
    out, i = [], 0
    for n in SIZES:
        out.append(rows[i:i + n]); i += n
    return out


PHASES = ["remote: Counting objects", "remote: Finding sources", "remote: Getting sizes",
          "remote: Compressing objects", "remote: Writing objects", "remote: Total",
          "Receiving objects", "Resolving deltas"]


def fetch(cls, tag):
    specs = "".join(f"+refs/changes/{n % 100:02d}/{n}/*:refs/patchsets/{n}/*\n"
                    f"^refs/changes/{n % 100:02d}/{n}/meta\n" for n, _ in cls)
    env = dict(os.environ, **contact.git_env(),
               GIT_TRACE2_EVENT=f"{OUT}/{tag}.trace2.json")
    if tag.endswith("_a"):
        env["GIT_TRACE_PACKET"] = f"{OUT}/{tag}.packet.txt"
    packs0 = set(os.listdir(f"{R}/objects/pack"))
    cmd = ["git", "-C", R, *contact.git_config(), "-c", "protocol.version=2", "fetch", "--progress",
           "--no-tags", "--no-write-fetch-head", "--stdin", URL]
    lines = []
    with store.extract_lock(DATA):
        t0 = time.time()
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, env=env)
        p.stdin.write(specs.encode()); p.stdin.close()
        buf = b""
        while True:
            ch = p.stderr.read1(65536)
            if not ch:
                break
            buf += ch
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            now = time.time() - t0
            lines += [(round(now, 2), x.decode(errors="replace").strip()) for x in parts if x.strip()]
        rc = p.wait()
        wall = time.time() - t0
    with open(f"{OUT}/{tag}.stderr.jsonl", "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")
    ph = {}
    for t, l in lines:
        for k in PHASES:
            if l.startswith(k):
                a = ph.setdefault(k, [t, t, l]); a[1] = t; a[2] = l
    new = sorted(set(os.listdir(f"{R}/objects/pack")) - packs0)
    packbytes = sum(os.path.getsize(f"{R}/objects/pack/{x}") for x in new if x.endswith(".pack"))
    # completeness: every object reachable from the new refs, not on main, must be present
    refs = [f"refs/patchsets/{n}/" for n, _ in cls]
    got = git("for-each-ref", "--format=%(refname)", *refs).split()
    miss = subprocess.run(["git", "-C", R, "rev-list", "--objects", "--missing=print", "--stdin",
                           "--not", "--alternate-refs"], input="\n".join(got) + "\n",
                          capture_output=True, text=True)
    nmiss = sum(1 for l in miss.stdout.splitlines() if l.startswith("?"))
    nobj = sum(1 for l in miss.stdout.splitlines() if not l.startswith("?"))
    res = dict(tag=tag, cls=len(cls), expected_ps=sum(p for _, p in cls), refs=len(got), rc=rc,
               wall=round(wall, 1), first_line=lines[0][0] if lines else None,
               phases={k: v for k, v in ph.items()}, new_pack_bytes=packbytes,
               objects_not_on_main=nobj, missing=nmiss, revlist_rc=miss.returncode,
               tail=[l for _, l in lines[-6:]])
    print(json.dumps(res, indent=1), flush=True)
    return res


def main():
    os.makedirs(OUT, exist_ok=True)
    init()
    batches = pick()
    results = []
    for i, cls in enumerate(batches):
        if i:
            time.sleep(15)
        r = fetch(cls, f"run{i}_{len(cls)}_{'abcd'[i]}")
        results.append(r)
        if r["rc"] != 0:
            print("fetch failed; stopping", flush=True)
            break
    json.dump(results, open(f"{OUT}/results.json", "w"), indent=1)


main()
