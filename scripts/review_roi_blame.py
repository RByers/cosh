"""Return on code review, part 2: blame pilot for H2d (SZZ-style fix-inducing
links) and H2e (line survival). docs/review-roi.md; findings in
docs/review-roi-part2.md.

szz: a random sample (fixed seed) of first-parent commits on main since
  2024-01-01 with a `Fixed:` footer naming a bug of type Bug or
  Vulnerability in bugs/bugs.sqlite, not reverts or relands, at most 20
  files. For each changed file (not new, not a test or expectations file,
  at most 20k lines at the parent), the deleted or modified non-blank lines
  are blamed at the parent (`git blame -w -l --porcelain -L ... <parent> --
  <file>`). Blamed commits landed before the bug was filed are the
  "inducing" commits; they map to CLs via gcommits.change_number. Induced
  unit CLs (review_roi_part2's unit) are compared with the non-induced unit
  CLs of the same size bucket, dir2 and half-year. A subsample is also
  blamed whole-file (no -L), to cost the plain full-file variant.
survival: a random sample of unit CLs landed in 2024 with 20–500 added
  lines. Each file the CL added lines to is blamed whole-file at the last
  first-parent commit on main landed before landing + 365 days; lines still
  blamed to the CL's commit survived unmodified.

Only the shared bare clone (main, full blobs), read-only, with
GIT_NO_LAZY_FETCH=1: nothing is fetched or written to it. Commit messages
are parsed only for `Fixed:` footers. Writes per-item numbers (public CL
numbers and shas, no identities) to the scratch directory and aggregates
to --out.

  export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
  S=/home/rbagent/.claude/jobs/9e4a825c/tmp/scratch/part2
  # needs review_roi_part2.py's --cache pickle for the unit-CL table
  nice -n 5 python3 scripts/review_roi_blame.py szz --cache $S/cache.pkl --n 500 --jobs 2 --full-sample 50 \\
      --scratch $S --out $S/blame_szz.json
  nice -n 5 python3 scripts/review_roi_blame.py survival --cache $S/cache.pkl --n 300 --jobs 2 \\
      --scratch $S --out $S/blame_survival.json
  # add --reuse to redo only the analysis from the saved items (e.g. with a new --cache)
"""

import argparse
import bisect
import json
import math
import os
import pickle
import random
import re
import sqlite3
import statistics as st
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import review_roi_part2 as P2  # noqa: E402
import balance_growth as G  # noqa: E402
from cosh import balance, bugs as B, store  # noqa: E402

GIT = os.path.expanduser("~/projects/shared/chromium")
ENV = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
DAY = 86400
SEED = 20261109
MAX_FILES = 20
MAX_LINES = 20000
TEST = re.compile(r"(^|/)(test|tests|testing|unittest|unittests|test_data|testdata|web_tests|wpt)/|"
                  r"(_|-|\.)(unit|browser|api|interactive_ui|perf|integration)?_?tests?\.[a-z]+$|"
                  r"Test\.java$|Tests?\.(java|kt|swift|m|mm)$|test_expectations|TestExpectations|"
                  r"\.(md|txt|grd|grdp|xtb|png|svg|json5?)$", re.I)
HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def git(*args, check=True):
    p = subprocess.run(["git", "--git-dir", GIT, *args], capture_output=True, env=ENV)
    if check and p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace")[:300])
    return p.stdout


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def epoch(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def blob_lines(rev, path):
    p = subprocess.run(["git", "--git-dir", GIT, "cat-file", "blob", f"{rev}:{path}"], capture_output=True, env=ENV)
    return None if p.returncode else p.stdout.count(b"\n")


def porcelain(out):
    """{blamed sha: lines} from `git blame --porcelain` output."""
    cnt = Counter()
    for line in out.split(b"\n"):
        if len(line) > 41 and line[40:41] == b" " and re.fullmatch(rb"[0-9a-f]{40}", line[:40]):
            parts = line.split()
            if len(parts) >= 3:
                cnt[line[:40].decode()] += 1
    return cnt


# ------------------------------------------------------------------ SZZ

def fix_commits(since="2024-01-01"):
    """[(sha, committer time, [bug ids])] of first-parent commits on main with a Fixed: footer."""
    out = subprocess.run(["git", "--git-dir", GIT, "log", "main", "--first-parent", f"--since={since}",
                          "--format=%H%x1f%ct%x1f%(trailers:key=Fixed,valueonly,separator=%x1f)%x1e"],
                         capture_output=True, env=ENV, check=True).stdout.decode(errors="replace")
    res = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, ct, *vals = rec.split("\x1f")
        ids = []
        for v in vals:
            ids += B.footer_ids(v)[0]
        if ids:
            res.append((sha, int(ct), sorted(set(ids))))
    return res


def eligible_fixes():
    bdb = sqlite3.connect(f"file:{os.path.join(store.DATA_DIR, 'bugs', 'bugs.sqlite')}?mode=ro", uri=True)
    remap = {o: n for o, n in bdb.execute("SELECT old_id, new_id FROM monorail_map WHERE new_id IS NOT NULL")}
    bug = {i: (t, c) for i, t, c in bdb.execute("SELECT id, type_name, created FROM bugs")}
    gdb = sqlite3.connect(f"file:{balance.db_path('git')}?mode=ro", uri=True)
    g = {sha: (files, rv is not None or rl, bot) for sha, files, rv, rl, bot in gdb.execute(
        "SELECT sha, files, reverts_sha, is_reland, is_bot FROM gcommits WHERE landed_at >= ?",
        (datetime(2023, 12, 1, tzinfo=timezone.utc).timestamp(),))}
    stats = Counter()
    out = []
    for sha, ct, ids in fix_commits():
        stats["with_fixed_footer"] += 1
        created = [epoch(bug[remap.get(i, i)][1]) for i in ids
                   if remap.get(i, i) in bug and bug[remap.get(i, i)][0] in ("Bug", "Vulnerability")
                   and bug[remap.get(i, i)][1]]
        if not created:
            continue
        stats["bug_or_vuln"] += 1
        gg = g.get(sha)
        if not gg or gg[1]:
            stats["revert_reland_or_unknown"] += 1
            continue
        stats["eligible"] += 1
        if gg[0] > MAX_FILES:
            stats["over_20_files"] += 1
            continue
        stats["eligible_le_20_files"] += 1
        out.append(dict(sha=sha, at=ct, created=min(created), files=gg[0]))
    return out, dict(stats)


def deleted_lines(parent, sha):
    """{old path: [old line numbers]} of deleted/modified non-blank lines, from a -U0 diff."""
    out = git("diff", "-U0", "--no-color", "--no-ext-diff", "-M", parent, sha, "--")
    res, path, ln = defaultdict(list), None, 0
    for line in out.split(b"\n"):
        if line.startswith(b"diff --git "):
            path = None
        elif line.startswith(b"--- "):
            path = None if line == b"--- /dev/null" else line[6:].decode(errors="replace")
        elif line.startswith(b"@@"):
            m = HUNK.match(line)
            ln = int(m.group(1)) if m else 0
        elif line.startswith(b"-") and not line.startswith(b"--- ") and path:
            if line[1:].strip():
                res[path].append(ln)
            ln += 1
    return res


def ranges(nums):
    nums = sorted(set(nums))
    out, s = [], None
    for i, n in enumerate(nums):
        if s is None:
            s = p = n
        elif n == p + 1:
            p = n
        else:
            out.append((s, p))
            s = p = n
    if s is not None:
        out.append((s, p))
    return out


def szz_one(job):
    fx, full = job
    t0 = time.time()
    parent = git("rev-parse", fx["sha"] + "^1").decode().strip()
    dl = deleted_lines(parent, fx["sha"])
    files, blamed, skipped = [], Counter(), Counter()
    for path, lines in dl.items():
        if TEST.search(path):
            skipped["test_or_data"] += 1
            continue
        n = blob_lines(parent, path)
        if n is None:
            skipped["missing"] += 1
            continue
        if n > MAX_LINES:
            skipped["over_20k_lines"] += 1
            continue
        args = ["blame", "-w", "-l", "--porcelain"]
        for a, b in ranges(lines):
            args += ["-L", f"{a},{b}"]
        t1 = time.time()
        try:
            cnt = porcelain(git(*args, parent, "--", path))
        except RuntimeError:
            skipped["blame_error"] += 1
            continue
        dt = time.time() - t1
        dt_full = None
        if full:
            t2 = time.time()
            try:
                git("blame", "-w", "-l", "--porcelain", parent, "--", path)
                dt_full = time.time() - t2
            except RuntimeError:
                pass
        blamed.update(cnt)
        files.append(dict(lines=len(lines), file_lines=n, s=dt, s_full=dt_full))
    return dict(sha=fx["sha"], at=fx["at"], created=fx["created"], files=files, skipped=dict(skipped),
                blamed=dict(blamed), s=time.time() - t0)


def stratified(induced, pool, key, xs):
    """Mean over induced CLs of (x − mean x of non-induced CLs in the same stratum); SD of those differences."""
    by = defaultdict(list)
    for u in pool:
        by[key(u)].append(u)
    out = {}
    for name, f in xs.items():
        means = {k: st.mean(f(u) for u in v) for k, v in by.items() if len(v) >= 5}
        d = [f(u) - means[key(u)] for u in induced if key(u) in means]
        if len(d) < 5:
            continue
        m, sd = st.mean(d), st.pstdev(d)
        se = sd / math.sqrt(len(d))
        need = math.ceil(((1.96 + 0.84) * sd / m) ** 2) if m else None
        out[name] = dict(n=len(d), induced_mean=st.mean(f(u) for u in induced if key(u) in means),
                         matched_mean=st.mean(means[key(u)] for u in induced if key(u) in means),
                         diff=m, lo=m - 1.96 * se, hi=m + 1.96 * se, sd=sd, n_for_80pct_power=need)
    return out


DEPTH = {
    "feedback_index": lambda u: u["fi"],
    "log2_1p_threads": lambda u: math.log2(1 + u["threads"]),
    "rubber_stamped": lambda u: 1.0 if u["threads"] == 0 else 0.0,
    "addressed_any": lambda u: 1.0 if u["addressed"] > 0 else 0.0,
    "reverted_30d": lambda u: float(u["rev"]),      # 0 by construction for induced CLs: a revert removes the lines
    "log2_lines": lambda u: math.log2(max(1, u["lines"])),   # balance check: size within the bucket
}


def load_units(cache):
    L = pickle.load(open(cache, "rb"))
    P2.norms(L["units"])
    return L["units"]


def szz(args):
    t0 = time.time()
    fixes, stats = eligible_fixes()
    print(f"fix commits: {stats} ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
    rnd = random.Random(SEED)
    sample = rnd.sample(fixes, min(args.n, len(fixes)))
    full_ix = set(range(min(args.full_sample, len(sample))))
    jobs = [(fx, i in full_ix) for i, fx in enumerate(sample)]
    res, t1 = [], time.time()
    items = os.path.join(args.scratch, "szz_items.jsonl")
    if args.reuse and os.path.exists(items):
        res = [json.loads(line) for line in open(items)]
        jobs = []
        prev = json.load(open(args.out)) if os.path.exists(args.out) else {}
        wall0, args.jobs = prev.get("wall_s"), prev.get("jobs", args.jobs)
    with Pool(args.jobs) as pool:
        for i, r in enumerate(pool.imap_unordered(szz_one, jobs)):
            res.append(r)
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(jobs)} {time.time() - t1:.0f}s", file=sys.stderr, flush=True)
            if time.time() - t1 > args.budget_s:
                print("  budget reached; stopping", file=sys.stderr)
                pool.terminate()
                break
    wall = time.time() - t1 if jobs else wall0
    if jobs:
        with open(items, "w") as f:
            for r in res:
                f.write(json.dumps(r) + "\n")
    # Map blamed shas to CLs.
    gdb = sqlite3.connect(f"file:{balance.db_path('git')}?mode=ro", uri=True)
    want = {s for r in res for s in r["blamed"]}
    gmap = {}
    for sha, n, at in gdb.execute("SELECT sha, change_number, landed_at FROM gcommits"):
        if sha in want:
            gmap[sha] = (n, at)
    units = load_units(args.cache)
    by_n = {u["n"]: u for u in units}
    induced, lines_before, lines_after, lines_unknown = set(), 0, 0, 0
    per_fix = []
    for r in res:
        ind = set()
        for s, k in r["blamed"].items():
            g = gmap.get(s)
            if not g:
                lines_unknown += k           # before 2017 or not first-parent
                continue
            if g[1] < r["created"]:
                lines_before += k
                if g[0]:
                    ind.add(g[0])
            else:
                lines_after += k
        per_fix.append(len(ind))
        induced |= ind
    ind_units = [by_n[n] for n in induced if n in by_n]
    lo, hi = min(u["at"] for u in ind_units), max(u["at"] for u in ind_units)
    pool = [u for u in units if lo <= u["at"] <= hi and u["n"] not in induced]
    key = lambda u: (u["sb"], u["d2"], P2.period(u["at"], "half"))  # noqa: E731
    cmp_ = stratified(ind_units, pool, key, DEPTH)
    key2 = lambda u: (min(u["sb"] // 2, 4), u["d2"], P2.period(u["at"], "half"))  # noqa: E731
    cmp2 = stratified(ind_units, pool, key2, DEPTH)
    # Rate of becoming "induced" by rubber-stamp status (a different view of the same comparison).
    units_win = [u for u in units if lo <= u["at"] <= hi]
    rate = {}
    for name, f in (("stamped", lambda u: u["threads"] == 0), ("reviewed", lambda u: u["threads"] > 0)):
        g = [u for u in units_win if f(u)]
        rate[name] = dict(cls=len(g), induced=sum(u["n"] in induced for u in g),
                          per_1000=1000 * sum(u["n"] in induced for u in g) / len(g))
    files = [f for r in res for f in r["files"]]
    secs = [r["s"] for r in res]
    full_pairs = [(f["s"], f["s_full"]) for f in files if f["s_full"] is not None]
    skipped = Counter()
    for r in res:
        skipped.update(r["skipped"])
    per_commit = st.mean(secs)
    full_ratio = sum(b for _, b in full_pairs) / sum(a for a, _ in full_pairs) if full_pairs else None
    n_all = stats["eligible_le_20_files"]
    out = dict(
        fix_stats=stats, sample=len(sample), done=len(res), wall_s=wall, jobs=args.jobs,
        sec_per_commit=dict(mean=per_commit, median=st.median(secs), p90=sorted(secs)[int(.9 * len(secs))],
                            max=max(secs)),
        sec_per_file=dict(n=len(files), mean=st.mean(f["s"] for f in files), median=st.median(f["s"] for f in files),
                          p90=sorted(f["s"] for f in files)[int(.9 * len(files))], max=max(f["s"] for f in files)),
        full_file=dict(files=len(full_pairs), sec_L=sum(a for a, _ in full_pairs),
                       sec_full=sum(b for _, b in full_pairs), ratio=full_ratio),
        files_blamed=len(files), files_skipped=dict(skipped),
        fixes_with_any_blamed_file=sum(1 for r in res if r["files"]),
        lines=dict(before_bug=lines_before, after_bug=lines_after, before_2017_or_unknown=lines_unknown),
        inducing_cls_per_fix=dict(mean=st.mean(per_fix), median=st.median(per_fix),
                                  zero=sum(1 for x in per_fix if x == 0)),
        induced_cls=len(induced), induced_unit_cls=len(ind_units),
        induced_window=[iso(lo), iso(hi)],
        compare_size10_dir2_half=cmp_, compare_size5_dir2_half=cmp2, rate_by_stamp=rate,
        estimate=dict(
            eligible_fixes=n_all,
            cpu_h_L=n_all * per_commit / 3600,
            cpu_h_full=n_all * per_commit * full_ratio / 3600 if full_ratio else None,
            note="CPU hours = commits × mean seconds per commit (one process); wall = CPU / jobs. "
                 "No download: all local git."))
    json.dump(out, open(args.out, "w"), indent=1)
    print(json.dumps(out, indent=1))


# ------------------------------------------------------------------ survival

def survival_one(job):
    t0 = time.time()
    sha, target = job["sha"], job["target"]
    out = git("diff-tree", "--no-commit-id", "-r", "--numstat", "-M", sha)
    files, added, alive, gone, big = [], 0, 0, 0, 0
    for line in out.decode(errors="replace").split("\n"):
        f = line.split("\t")
        if len(f) < 3 or f[0] == "-" or int(f[0]) == 0:
            continue
        ins, path = int(f[0]), f[-1]
        if "=>" in path:
            continue
        n = blob_lines(target, path)
        if n is None:
            gone += ins
            added += ins
            files.append(dict(ins=ins, alive=0, gone=True, s=0.0))
            continue
        if n > MAX_LINES:
            big += 1
            continue
        t1 = time.time()
        try:
            # Walk only the year after landing: older lines stop at the boundary (sha^), so
            # a line still blamed to sha survived unmodified (same answer as a full-history blame).
            cnt = porcelain(git("blame", "-w", "-l", "--porcelain", f"{sha}^..{target}", "--", path))
        except RuntimeError:
            continue
        k = min(ins, cnt.get(sha, 0))
        added += ins
        alive += k
        files.append(dict(ins=ins, alive=k, gone=False, s=time.time() - t1, file_lines=n))
    return dict(n=job["n"], sha=sha, added=added, alive=alive, gone_lines=gone, big_files=big, files=files,
                s=time.time() - t0)


def survival(args):
    t0 = time.time()
    units = load_units(args.cache)
    gdb = sqlite3.connect(f"file:{balance.db_path('git')}?mode=ro", uri=True)
    lo = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    hi = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    fp = sorted(gdb.execute("SELECT landed_at, sha FROM gcommits"))
    fp_t = [t for t, _ in fp]
    g = {n: (sha, ins) for n, sha, ins in gdb.execute(
        "SELECT change_number, sha, ins FROM gcommits WHERE landed_at >= ? AND landed_at < ? AND change_number "
        "IS NOT NULL", (lo, hi))}
    elig = [u for u in units if lo <= u["at"] < hi and u["n"] in g and 20 <= g[u["n"]][1] <= 500]
    # Feedback-index terciles over all eligible CLs (the index is already relative to size × dir2).
    fis = sorted(u["fi"] for u in elig)
    cut = (fis[len(fis) // 3], fis[2 * len(fis) // 3])
    rnd = random.Random(SEED)
    sample = rnd.sample(elig, min(args.n, len(elig)))
    jobs = []
    for u in sample:
        i = bisect.bisect_left(fp_t, u["at"] + 365 * DAY) - 1
        jobs.append(dict(n=u["n"], sha=g[u["n"]][0], target=fp[i][1]))
    res, t1 = [], time.time()
    items = os.path.join(args.scratch, "survival_items.jsonl")
    if args.reuse and os.path.exists(items):
        res = [json.loads(line) for line in open(items)]
        jobs = []
        prev = json.load(open(args.out)) if os.path.exists(args.out) else {}
        wall0, args.jobs = prev.get("wall_s"), prev.get("jobs", args.jobs)
    with Pool(args.jobs) as pool:
        for i, r in enumerate(pool.imap_unordered(survival_one, jobs)):
            res.append(r)
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(jobs)} {time.time() - t1:.0f}s", file=sys.stderr, flush=True)
            if time.time() - t1 > args.budget_s:
                print("  budget reached; stopping", file=sys.stderr)
                pool.terminate()
                break
    wall = time.time() - t1 if jobs else wall0
    if jobs:
        with open(items, "w") as f:
            for r in res:
                f.write(json.dumps(r) + "\n")
    by_n = {u["n"]: u for u in units}
    rows = []
    for r in res:
        u = by_n[r["n"]]
        if not r["added"]:
            continue
        t = 0 if u["fi"] <= cut[0] else 1 if u["fi"] <= cut[1] else 2
        rows.append(dict(u=u, t=t, surv=r["alive"] / r["added"], added=r["added"],
                         surv_present=(r["alive"] / (r["added"] - r["gone_lines"]))
                         if r["added"] > r["gone_lines"] else None))
    terc = []
    for t in range(3):
        rr = [x for x in rows if x["t"] == t]
        sp = [x["surv_present"] for x in rr if x["surv_present"] is not None]
        terc.append(dict(tercile=t + 1, cls=len(rr), fi_median=st.median(x["u"]["fi"] for x in rr),
                         survival_mean=st.mean(x["surv"] for x in rr),
                         survival_lines=sum(x["surv"] * x["added"] for x in rr) / sum(x["added"] for x in rr),
                         survival_present_mean=st.mean(sp) if sp else None,
                         added_median=st.median(x["added"] for x in rr)))
    # Adjusted: survival on tercile dummies + log added lines, demeaned by dir2, clustered by dir2.
    X, y, grp = [], [], []
    for x in rows:
        X.append([1.0 if x["t"] == 1 else 0.0, 1.0 if x["t"] == 2 else 0.0, math.log(x["added"]),
                  1.0 if x["u"]["threads"] == 0 else 0.0])
        y.append(x["surv"])
        grp.append(x["u"]["d2"])
    Z = P2.demean([dict(d=gk) for gk in grp], [xx + [yy] for xx, yy in zip(X, y)])
    keep = [i for i, gk in enumerate(grp) if grp.count(gk) >= 2]
    Xd = [Z[i][:3] for i in keep]
    yd = [Z[i][-1] for i in keep]
    adj = None
    try:
        beta, se = P2.FP.ols(Xd, yd, [grp[i] for i in keep])
        adj = dict(n=len(keep), mid_vs_low=dict(b=beta[0], lo=beta[0] - 1.96 * se[0], hi=beta[0] + 1.96 * se[0]),
                   high_vs_low=dict(b=beta[1], lo=beta[1] - 1.96 * se[1], hi=beta[1] + 1.96 * se[1]),
                   log_added=dict(b=beta[2], lo=beta[2] - 1.96 * se[2], hi=beta[2] + 1.96 * se[2]))
    except ValueError:
        pass
    sd = st.pstdev(x["surv"] for x in rows)
    files = [f for r in res for f in r["files"] if not f["gone"]]
    secs = [r["s"] for r in res]
    n_all = len(elig)
    n_units_2024 = sum(1 for u in units if lo <= u["at"] < hi)
    out = dict(
        eligible_2024=n_all, unit_cls_2024=n_units_2024, sample=len(sample), done=len(res), wall_s=wall,
        jobs=args.jobs, fi_tercile_cuts=cut,
        sec_per_cl=dict(mean=st.mean(secs), median=st.median(secs), p90=sorted(secs)[int(.9 * len(secs))],
                        max=max(secs)),
        sec_per_file=dict(n=len(files), mean=st.mean(f["s"] for f in files), median=st.median(f["s"] for f in files),
                          p90=sorted(f["s"] for f in files)[int(.9 * len(files))], max=max(f["s"] for f in files)),
        overall=dict(survival_mean=st.mean(x["surv"] for x in rows), sd=sd,
                     lines_gone_with_file=sum(r["gone_lines"] for r in res) / max(1, sum(r["added"] for r in res))),
        terciles=terc, adjusted=adj,
        n_for_80pct_power_5pt=math.ceil(2 * ((1.96 + 0.84) * sd / 0.05) ** 2 * 1.5),
        estimate=dict(
            cpu_h_2024_eligible=n_all * st.mean(secs) / 3600,
            cpu_h_all_units_2023_2025=sum(1 for u in units if u["at"] < datetime(2025, 10, 1, tzinfo=timezone.utc)
                                          .timestamp()) * st.mean(secs) / 3600,
            note="CPU hours = CLs × mean seconds per CL (one process). Larger CLs cost more; the 20–500 line "
                 "window is the sampled one. No download: all local git."))
    json.dump(out, open(args.out, "w"), indent=1)
    print(json.dumps(out, indent=1))


def main():
    os.nice(5)              # same as `nice -n 5`: blame and the loads yield to interactive work
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("szz", "survival", "count"))
    ap.add_argument("--cache", required=False)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--full-sample", type=int, default=50)
    ap.add_argument("--budget-s", type=float, default=2700)
    ap.add_argument("--scratch", default=".")
    ap.add_argument("--reuse", action="store_true", help="reuse the blamed items in --scratch; only re-analyse")
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.what == "count":
        t0 = time.time()
        fixes, stats = eligible_fixes()
        print(stats, f"{time.time() - t0:.0f}s")
    elif args.what == "szz":
        szz(args)
    else:
        survival(args)


if __name__ == "__main__":
    main()
