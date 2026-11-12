"""Per-CL analysis table for the review-ROI study, Part 1 (docs/review-roi.md,
docs/review-roi-part1.md).

One row per CL in the unit: merged, human-owned, non-mechanical, not a
revert, not a reland, not a Bot-Commit (Rubber Stamper) approval, landed on
main 2023-07-01 .. 2026-09-30 and at least 30 days before the newest commit
in balance-git.sqlite. Each row has the revert outcomes (7, 30, 90 days),
the review-depth exposures, the approvers' expertise and habit, and the
controls. Offline: reads data/private/balance*.sqlite and derived.sqlite
read-only (no comment text), plus the shared inputs below, and writes one
scratch SQLite file. Identities appear only as integer ids.

  export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
  I=data/private/review_feedback_inputs
  nice -n 5 python3 scripts/review_roi_table.py \
      --out data/private/scratch/review_roi/part1/cl_table.sqlite \
      [--first-commit $I/first_commit.txt] [--owners-added $I/owners_added.txt] [--mech $I/mech.jsonl]

Without --first-commit, tenure is from the first authored commit in
gcommits (since 2017-01), and authors whose first commit there is before
2017-07 are flagged `tenure_censored` ("9+ years"). Without --mech the
provisional mechanical rule applies (>= 50 files). Without --owners-added
the OWNERS columns are NULL. The `meta` table records which inputs were
used and the exclusion counts. About 2 minutes and 3.5 GB.
"""

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402
from balance_report import mech_set  # noqa: E402
from cosh import balance, store  # noqa: E402

DAY = 86400
MONTH = 365.25 * DAY / 12
START = int(datetime(2023, 7, 1, tzinfo=timezone.utc).timestamp())
STOP = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())       # landed before this
EARLY = int(datetime(2017, 7, 1, tzinfo=timezone.utc).timestamp())      # tenure censoring
PROVISIONAL_MECH_FILES = 50
MIN_HABIT = 5                    # other CLs the approver approved in the half-year

TEST_DIR = {"test", "tests", "testing", "test_data", "testdata", "web_tests", "unittests", "browsertests",
            "test_support", "javatests", "androidTest", "fixtures", "mock", "mocks", "fakes"}
TEST_BASE = re.compile(
    r"([_.-](unit|browser|interactive_ui|api|ui|perf|integration|fuzz)?tests?(_[a-z0-9]+)?\.[A-Za-z0-9]+$)"
    r"|(^tests?_[^/]*\.py$)|(Tests?\.(java|kt|swift|mm|m)$)|(\.test\.[jt]sx?$)|(_(fake|mock)[a-z_]*\.(cc|h)$)"
    r"|(^(fake|mock)_[^/]*\.(cc|h)$)|(_browsertest|_unittest|_apitest|_uitest)")


def is_test(path):
    parts = path.split("/")
    return any(p in TEST_DIR for p in parts[:-1]) or bool(TEST_BASE.search(parts[-1]))


def half_name(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return f"{d.year}H{1 + (d.month > 6)}"


def era_of(t):
    y = datetime.fromtimestamp(t, timezone.utc).year
    return "2023-24" if y <= 2024 else str(y)


def practice_band(n):
    return "0" if n == 0 else "1-4" if n < 5 else "5-19" if n < 20 else "20-99" if n < 100 else "100+"


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:6.0f}s] {msg}", file=sys.stderr, flush=True)


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--first-commit")
    ap.add_argument("--owners-added")
    ap.add_argument("--mech")
    args = ap.parse_args()
    meta = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mech_rule": "mech.jsonl: >= 100 files or >= 10 files with repetition >= 0.8" if args.mech
            else f"provisional: >= {PROVISIONAL_MECH_FILES} files",
            "tenure_source": "first_commit.txt (all history)" if args.first_commit
            else "first authored commit in gcommits since 2017-01; first commit before 2017-07 = censored",
            "owners_source": "owners_added.txt" if args.owners_added else "none"}

    # ---------------------------------------------------------------- git
    g = ro(balance.db_path("git"))
    newest = g.execute("SELECT max(landed_at) FROM gcommits").fetchone()[0]
    meta["newest_commit"] = newest
    commits = g.execute("SELECT commit_id, sha, author_email, landed_at, change_number, is_bot, reviewed_by, "
                        "reverts_sha, is_reland FROM gcommits ORDER BY landed_at, commit_id").fetchall()
    log(f"{len(commits):,} commits")
    reverted = {}                       # sha -> (first revert landed_at, revert sha)
    for cid, sha, e, at, n, bot, rb, rv, rl in commits:
        if rv and (rv not in reverted or at < reverted[rv][0]):
            reverted[rv] = (at, sha)
    by_n = {}
    for i, c in enumerate(commits):
        if c[4]:
            by_n[c[4]] = i

    # ---------------------------------------------------------------- CLs
    b = ro(balance.db_path("cl"))
    cols = ["change_number", "owner", "owner_email", "status", "closed_at", "ins", "dels", "sha", "files",
            "git_lines", "is_revert", "is_reland", "comments", "chars", "threads", "addressed", "pending",
            "first_review_at", "sent_at", "rework_after", "rounds", "reviewer_wait_h", "reviewer_wait_wd_h",
            "lines_changed", "lines_final", "created_at"]
    light_cls = [{"change_number": n, "owner_email": e} for n, e in b.execute("SELECT change_number, owner_email FROM cl")]
    meta["cl_rows"] = len(light_cls)
    cls = [dict(zip(cols, r)) for r in b.execute(f"SELECT {', '.join(cols)} FROM cl WHERE status = 'MERGED'")]
    log(f"{len(light_cls):,} CLs in balance.sqlite, {len(cls):,} merged")

    ids = G.Ids()
    light_commits = [{"n": c[4], "email": c[2]} for c in commits if c[4]]
    for a_, b_ in G.alias_pairs(light_cls, light_commits):
        ids.union(a_, b_)
    del light_cls, light_commits
    pid_int = {}

    def pint(e):
        p = ids.find(e)
        i = pid_int.get(p)
        if i is None:
            i = pid_int[p] = len(pid_int) + 1
        return i

    # ------------------------------------------------- directories per commit
    paths = dict(g.execute("SELECT path_id, path FROM paths"))
    cand_cids = set()
    for c in cls:
        if c["status"] == "MERGED" and c["change_number"] in by_n:
            cand_cids.add(commits[by_n[c["change_number"]]][0])
    d3_of_path, intern = {}, {}

    def d3p(pid_):
        d = d3_of_path.get(pid_)
        if d is None:
            d = d3_of_path[pid_] = sys.intern(A.dir_of(paths[pid_], 3))
        return d
    cdirs = {}            # cid -> (main dir3, tuple of dir3s)
    cinfo = {}            # cid of candidate CL -> (heavy file dir, test files, files)
    cur, acc, heavy, tests, nfiles = None, None, None, 0, 0

    def flush():
        if cur is None or not acc:
            return
        main3 = max(acc, key=acc.get)
        cdirs[cur] = (main3, tuple(acc))
        if cur in cand_cids:
            # heaviest file within the main dir3: its full directory (for OWNERS coverage)
            cinfo[cur] = (heavy[main3][1], tests, nfiles)
    for cid, pid_, ins, dels in g.execute("SELECT commit_id, path_id, ins, dels FROM gfiles"):
        if cid != cur:
            flush()
            cur, acc, heavy, tests, nfiles = cid, {}, {}, 0, 0
        d = d3p(pid_)
        w = max(ins, 0) + max(dels, 0) + 1
        acc[d] = acc.get(d, 0) + w
        if cid in cand_cids:
            p = paths[pid_]
            if d not in heavy or w > heavy[d][0]:
                heavy[d] = (w, p.rsplit("/", 1)[0] + "/" if "/" in p else "")
            tests += is_test(p)
            nfiles += 1
    flush()
    del d3_of_path
    log(f"directories for {len(cdirs):,} commits")

    def d2(d3):
        return "/".join(d3.split("/")[:2])

    # ------------------------------------------------------------ accounts
    d = ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    emails = dict(d.execute("SELECT account_id, email FROM accounts"))
    bots = {a for a, in d.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    acct_pint = {a: pint(e) for a, e in emails.items() if e and a not in bots and not A.is_bot_email(e)}

    # --------------------------------------------------------- mechanical
    mech = mech_set(args.mech) if args.mech else None

    def is_mech(c):
        if mech is not None:
            return c["change_number"] in mech
        return (c["files"] or 0) >= PROVISIONAL_MECH_FILES

    # Base set (for norms and approver habits): merged, human-owned, landed, non-mechanical, not Bot-Commit.
    base = []
    for c in cls:
        if c["status"] != "MERGED" or c["change_number"] not in by_n or not c["owner_email"] \
                or A.is_bot_email(c["owner_email"]):
            continue
        gc = commits[by_n[c["change_number"]]]
        if gc[1] != c["sha"] or gc[5] or is_mech(c) or gc[3] < START:
            continue
        c["cid"], c["landed"], c["author"] = gc[0], gc[3], pint(c["owner_email"])
        c["git_author"] = pint(gc[2])
        c["rb"] = [pint(x) for x in json.loads(gc[6])] if gc[6] else []
        dd = cdirs.get(gc[0])
        c["dir3"] = dd[0] if dd else "(none)/"
        c["dir2"] = d2(c["dir3"])
        c["lines"] = (c["ins"] or 0) + (c["dels"] or 0)
        c["sb"] = G.size10(c["lines"])
        r = reverted.get(c["sha"])
        c["revert_days"] = (r[0] - c["landed"]) / DAY if r else None
        c["revert_sha"] = r[1] if r else None
        c["rev30"] = int(r is not None and c["revert_days"] <= 30)
        c["half"] = half_name(c["landed"])
        base.append(c)
    log(f"{len(base):,} CLs in the base set")

    # Norm: mean threads by size10 x dir2 over 2023-24 (>= 30 CLs), else size10.
    # The same norm for log1p(threads), for the log-scale habit.
    gsum, bsum = defaultdict(lambda: [0, 0, 0.0]), defaultdict(lambda: [0, 0, 0.0])
    for c in base:
        if datetime.fromtimestamp(c["landed"], timezone.utc).year <= 2024:
            for k, m in (((c["sb"], c["dir2"]), gsum), (c["sb"], bsum)):
                m[k][0] += 1
                m[k][1] += c["threads"]
                m[k][2] += math.log1p(c["threads"])
    for c in base:
        x = gsum.get((c["sb"], c["dir2"]))
        if not x or x[0] < 30:
            x = bsum[c["sb"]]
        c["exp24"] = x[1] / x[0] if x[0] else 1.0
        c["fi"] = c["threads"] / c["exp24"] if c["exp24"] > 0 else None
        c["resid"] = c["threads"] - c["exp24"]
        c["lresid"] = math.log1p(c["threads"]) - (x[2] / x[0] if x[0] else 0.0)

    # -------------------------------------------------------------- votes
    base_by_n = {c["change_number"]: c for c in base}
    v = ro(os.path.join(store.DATA_DIR, "balance-votes.sqlite"))
    votes = defaultdict(list)
    for n, voter, value, at in v.execute("SELECT change_number, voter, value, at FROM votes"):
        if n in base_by_n:
            votes[n].append((at, voter, value))
    agree = Counter()
    for c in base:
        last = {}
        bound = (c["closed_at"] or c["landed"]) + 120
        for at, voter, value in sorted(votes.get(c["change_number"], [])):
            if at <= bound and voter != c["owner"] and voter in acct_pint:
                last[voter] = (value, at)
        appr = {}
        for voter, (value, at) in last.items():
            p = acct_pint[voter]
            if value > 0 and p not in (c["author"],):
                appr[p] = min(at, appr.get(p, at))
        rb = set(c["rb"]) - {c["author"], c["git_author"]}
        if appr:
            c["appr"] = sorted(appr, key=appr.get)
            c["appr_src"] = "votes"
            c["appr_at"] = appr[c["appr"][0]]
        elif rb:
            c["appr"] = sorted(rb)
            c["appr_src"] = "reviewed_by"
        else:
            c["appr"] = []
            c["appr_src"] = "none"
        if c["landed"] >= START:
            va = set(appr)
            agree["same" if va == rb else "votes_only" if not rb else "rb_only" if not va
                  else "votes_subset" if va < rb else "rb_subset" if rb < va else "differ"] += 1
    meta["approver_agreement_votes_vs_reviewed_by"] = dict(agree)
    del votes
    log(f"approvers: {dict(agree)}")

    # ---------------------------------------------------- comments, attention
    commenters = defaultdict(set)
    for n, acct in d.execute("SELECT change_number, account_id FROM comments WHERE after_close = 0"):
        c = base_by_n.get(n)
        if c is not None and acct != c["owner"] and acct in acct_pint and acct_pint[acct] != c["author"]:
            commenters[n].add(acct)
    attn = defaultdict(lambda: [0.0, 0.0])
    for n, h, wh in b.execute("SELECT change_number, hours, weekday_hours FROM cl_attention"):
        if n in base_by_n:
            attn[n][0] += h
            attn[n][1] += wh
    log("comments and attention")

    # ----------------------------------------------------- first commits, OWNERS
    first = {}
    if args.first_commit:
        for e, t in A.load_first(args.first_commit).items():
            k = pint(e)
            first[k] = min(t, first.get(k, t))
    first_git = {}
    for cid, sha, e, at, n, bot, rb, rv, rl in commits:
        if not bot and not A.is_bot_email(e):
            k = pint(e)
            if k not in first_git:
                first_git[k] = at
    owners = defaultdict(list)
    if args.owners_added:
        for line in open(args.owners_added):
            f = line.rstrip("\n").split(" ", 2)
            if len(f) != 3:
                continue
            t, e, path = f
            dirp = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
            owners[pint(e)].append((int(t), dirp))
        for k in owners:
            owners[k].sort()

    def tenure(p, at):
        """(months, censored) at time `at`."""
        t0 = first.get(p)
        if t0 is not None:
            return max(0.0, (at - t0) / MONTH), 0
        t0 = first_git.get(p)
        if t0 is None:
            return None, 0
        return max(0.0, (at - t0) / MONTH), int(not args.first_commit and t0 < EARLY)

    def owner_status(p, at, heavy_dir, dir3):
        """(covers: an OWNERS file at the CL's heaviest file's directory or a parent,
            near: covers, or an OWNERS file inside the CL's main dir3) added before `at`."""
        cov = near = 0
        for t, od in owners.get(p, ()):
            if t >= at:
                break
            if heavy_dir.startswith(od):
                cov = near = 1
                break
            if od.startswith(dir3):
                near = 1
        return cov, near

    # ------------------------------------------ chronological expertise stream
    dir_int = {}

    def dint(s):
        i = dir_int.get(s)
        if i is None:
            i = dir_int[s] = len(dir_int) + 1
        return i
    K = 10 ** 7
    auth, appr_given, total = Counter(), Counter(), Counter()
    feats = {}
    for cid, sha, e, at, n, bot, rb, rv, rl in commits:
        dd = cdirs.get(cid)
        c = base_by_n.get(n) if n else None
        if c is not None and c["cid"] == cid and dd:
            i3, i2 = dint(c["dir3"]), dint("2:" + c["dir2"])
            ap_ = []
            for p in c["appr"]:
                ap_.append((auth[p * K + i3], auth[p * K + i2], appr_given[p * K + i3], appr_given[p * K + i2]))
            feats[n] = (ap_, auth[c["author"] * K + i3], total[c["author"]])
        if bot or A.is_bot_email(e) or rv or not dd:
            continue
        a = pint(e)
        total[a] += 1
        ds3 = dd[1]
        ds2 = {"2:" + d2(x) for x in ds3}
        for x in ds3:
            auth[a * K + dint(x)] += 1
        for x in ds2:
            auth[a * K + dint(x)] += 1
        if rb:
            for r in {pint(x) for x in json.loads(rb)} - {a}:
                for x in ds3:
                    appr_given[r * K + dint(x)] += 1
                for x in ds2:
                    appr_given[r * K + dint(x)] += 1
    del auth, appr_given
    log(f"expertise for {len(feats):,} CLs")

    # ------------------------------------------------ approver habits (LOO)
    hab = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0, 0.0])   # (p, half) -> n, sum resid, threads, exp, reverts, lresid
    for c in base:
        for p in c["appr"]:
            h = hab[(p, c["half"])]
            h[0] += 1
            h[1] += c["resid"]
            h[2] += c["threads"]
            h[3] += c["exp24"]
            h[4] += c["rev30"]
            h[5] += c["lresid"]
    # Split-half reliability input: odd/even CLs in time order per (approver, half).
    seq = defaultdict(list)
    for c in sorted(base, key=lambda c: c["landed"]):
        for p in c["appr"][:1]:
            seq[(p, c["half"])].append(c)

    def corr(pairs):
        mx, my = sum(x for x, _ in pairs) / len(pairs), sum(y for _, y in pairs) / len(pairs)
        sxy = sum((x - mx) * (y - my) for x, y in pairs)
        sxx = sum((x - mx) ** 2 for x, _ in pairs)
        syy = sum((y - my) ** 2 for _, y in pairs)
        r = sxy / math.sqrt(sxx * syy)
        return {"pairs": len(pairs), "r": round(r, 3), "spearman_brown": round(2 * r / (1 + r), 3)}
    halves = [(xs[0::2], xs[1::2]) for xs in seq.values() if len(xs) >= 2 * MIN_HABIT]
    mean = lambda cs, k: sum(c[k] for c in cs) / len(cs)
    ratio = lambda cs: sum(c["threads"] for c in cs) / max(1e-9, sum(c["exp24"] for c in cs))
    meta["habit_split_half"] = {
        "note": f"first approver per CL; (approver, half-year) cells with >= {2 * MIN_HABIT} CLs; odd vs even CLs in time order",
        "mean residual threads": corr([(mean(a, "resid"), mean(b, "resid")) for a, b in halves]),
        "mean residual log1p threads": corr([(mean(a, "lresid"), mean(b, "lresid")) for a, b in halves]),
        "feedback index (sum threads / sum norm)": corr([(ratio(a), ratio(b)) for a, b in halves]),
        "revert rate (30 d)": corr([(mean(a, "rev30"), mean(b, "rev30")) for a, b in halves]),
    }
    log(f"habit split-half: {meta['habit_split_half']}")
    del seq, halves

    def loo(p, c):
        h = hab.get((p, c["half"]))
        if not h or h[0] - 1 < MIN_HABIT:
            return None
        m = h[0] - 1
        sexp = h[3] - c["exp24"]
        return ((h[1] - c["resid"]) / m, (h[2] - c["threads"]) / sexp if sexp > 0 else None,
                (h[4] - c["rev30"]) / m, m, (h[5] - c["lresid"]) / m)

    # ------------------------------------- approver weekly load (follow-up item 2)
    # Weeks start Monday 00:00 UTC (ISO weeks). A CL's approval week is its
    # first approver's approving vote, or its landing when approvers come from
    # Reviewed-by. Threads are reviewer-started threads dated by their root
    # comment, on any CL in derived.sqlite.
    wk = lambda t: (t - 345600) // 604800
    cls_week, thr_week, thr_on = Counter(), Counter(), Counter()
    for c in base:
        for p in c["appr"]:
            cls_week[(p, wk(c.get("appr_at") or c["landed"]) if p == c["appr"][0] else wk(c["landed"]))] += 1
    for n, acct, at in d.execute(
            "SELECT t.change_number, t.root_account, c.written_at FROM threads t JOIN comments c ON c.host = t.host "
            "AND c.change_number = t.change_number AND c.comment_id = t.root_uuid"):
        p = acct_pint.get(acct)
        if p is None:
            continue
        t = int(datetime.strptime(at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        thr_week[(p, wk(t))] += 1
        if n in base_by_n:
            thr_on[(n, p)] += 1
    act = defaultdict(set)              # (p, half) -> active weeks
    for (p, w) in list(cls_week) + list(thr_week):
        act[(p, half_name(w * 604800 + 345600 + 3 * 86400))].add(w)
    med = {}
    for k, ws in act.items():
        ws = sorted(ws)
        a = sorted(cls_week.get((k[0], w), 0) for w in ws)
        b = sorted(thr_week.get((k[0], w), 0) for w in ws)
        med[k] = (a[len(a) // 2], b[len(b) // 2], len(ws))
    log("approver weekly load")

    def load(c):
        if not c["appr"]:
            return None, None, None, None
        p = c["appr"][0]
        w = wk(c.get("appr_at") or c["landed"])
        m = med.get((p, half_name(w * 604800 + 345600 + 3 * 86400)))
        if not m:
            return None, None, None, None
        own = thr_on.get((c["change_number"], p), 0)
        lc = math.log2(max(1, cls_week.get((p, w), 0)) / max(1, m[0]))
        lt = math.log2((1 + max(0, thr_week.get((p, w), 0) - own)) / (1 + m[1]))
        return lc, lt, m[2], own

    # ---------------------------------------------------------- the unit
    counts = Counter()
    rows = []
    counts["0 cl rows"] = meta["cl_rows"]
    for c in cls:
        counts["1 merged"] += 1
        gi = by_n.get(c["change_number"])
        gc = commits[gi] if gi is not None else None
        if gc is None or gc[1] != c["sha"]:
            counts["x no landed first-parent commit"] += 1
            continue
        if not START <= gc[3] < STOP:
            continue
        counts["2 merged, landed 2023-07-01 .. 2026-09-30"] += 1
        if not c["owner_email"] or A.is_bot_email(c["owner_email"]):
            counts["x bot owner"] += 1
            continue
        if gc[5]:
            counts["x Bot-Commit"] += 1
            continue
        if is_mech(c):
            counts["x mechanical"] += 1
            continue
        if c["is_revert"]:
            counts["x revert"] += 1
            continue
        if c["is_reland"]:
            counts["x reland"] += 1
            continue
        if gc[3] > newest - 30 * DAY:
            counts["x landed < 30 d before data end"] += 1
            continue
        if c["change_number"] not in feats:
            counts["x no directory"] += 1
            continue
        counts["3 unit"] += 1
        n = c["change_number"]
        ap_, prac, prior_total = feats[n]
        landed = c["landed"]
        ci = cinfo.get(c["cid"], ("", 0, 0))
        heavy_dir = ci[0]
        tm, cens = tenure(c["author"], landed)
        own, ten, hb = [], [], []
        for p in c["appr"]:
            own.append(owner_status(p, landed, heavy_dir, c["dir3"]) if args.owners_added else (None, None))
            ten.append(tenure(p, landed)[0])
            hb.append(loo(p, c))
        dt = datetime.fromtimestamp(landed, timezone.utc)

        def mx(xs):
            xs = [x for x in xs if x is not None]
            return max(xs) if xs else None
        rd = c["revert_days"]
        ld = load(c)
        first_rev = c["first_review_at"]
        sent = c["sent_at"]
        rows.append(dict(
            change_number=n, author_id=c["author"], landed_at=landed, half=c["half"], era=era_of(landed),
            weekday=dt.weekday(), hour=dt.hour,
            lines=c["lines"], git_lines=c["git_lines"], files=c["files"], size10=c["sb"],
            dir2=c["dir2"], dir3=c["dir3"], test_files=ci[1], test_share=ci[1] / ci[2] if ci[2] else None,
            author_tenure_m=tm, tenure_censored=cens,
            tenure_band=A.tenure_band(tm) if tm is not None else None,
            author_prior_commits=prior_total, author_practice3=prac, practice_band=practice_band(prac),
            threads=c["threads"], addressed=c["addressed"], comments=c["comments"], chars=c["chars"],
            commenters=len(commenters.get(n, ())), rounds=c["rounds"], rework_after=c["rework_after"],
            interdiff_share=min(2.0, c["lines_changed"] / c["lines_final"])
            if c["lines_changed"] is not None and c["lines_final"] else None,
            attn_h=attn[n][0] if n in attn else None, attn_wd_h=attn[n][1] if n in attn else None,
            reviewer_wait_h=c["reviewer_wait_h"],
            first_review_h=(first_rev - sent) / 3600 if first_rev and sent and first_rev >= sent else None,
            review_total_h=(c["closed_at"] - sent) / 3600 if sent and c["closed_at"] else None,
            exp24=c["exp24"], feedback_index=c["fi"], resid_threads=c["resid"], lresid_threads=c["lresid"],
            sent_at=sent, first_appr_at=c.get("appr_at"),
            load_cls_log2=ld[0], load_thr_log2=ld[1], load_active_weeks=ld[2], first_appr_threads=ld[3],
            n_approvers=len(c["appr"]), approver_source=c["appr_src"],
            rubber_stamp=int(bool(c["appr"]) and c["threads"] == 0),
            appr_auth3_max=mx([x[0] for x in ap_]), appr_auth2_max=mx([x[1] for x in ap_]),
            appr_appr3_max=mx([x[2] for x in ap_]), appr_appr2_max=mx([x[3] for x in ap_]),
            appr_owner_cover_any=mx([o[0] for o in own]), appr_owner_near_any=mx([o[1] for o in own]),
            appr_tenure_y_max=mx([t / 12 if t is not None else None for t in ten]),
            first_approver_id=c["appr"][0] if c["appr"] else None,
            first_auth3=ap_[0][0] if ap_ else None, first_auth2=ap_[0][1] if ap_ else None,
            first_appr3=ap_[0][2] if ap_ else None, first_appr2=ap_[0][3] if ap_ else None,
            first_owner_cover=own[0][0] if own else None,
            first_tenure_y=ten[0] / 12 if ten and ten[0] is not None else None,
            habit_first=hb[0][0] if hb and hb[0] else None, habit_first_n=hb[0][3] if hb and hb[0] else None,
            habit_idx_first=hb[0][1] if hb and hb[0] else None,
            habit_max=mx([h[0] if h else None for h in hb]),
            habit_log_first=hb[0][4] if hb and hb[0] else None,
            habit_log_max=mx([h[4] if h else None for h in hb]),
            habit_idx_max=mx([h[1] if h else None for h in hb]),
            habrev_first=hb[0][2] if hb and hb[0] else None,
            habrev_max=mx([h[2] if h else None for h in hb]),
            rev7=int(rd is not None and rd <= 7), rev30=int(rd is not None and rd <= 30),
            rev90=int(rd is not None and rd <= 90) if landed <= newest - 90 * DAY else None,
            revert_days=rd, sha=c["sha"], revert_sha=c["revert_sha"],
        ))
    meta["counts"] = dict(sorted(counts.items()))
    log(f"{len(rows):,} unit CLs; {dict(sorted(counts.items()))}")

    # -------------------------------------------------------------- write
    if os.path.exists(args.out):
        os.remove(args.out)
    out = sqlite3.connect(args.out)
    keys = list(rows[0])
    out.execute(f"CREATE TABLE cl ({', '.join(keys)})")
    out.executemany(f"INSERT INTO cl VALUES ({','.join('?' * len(keys))})", [tuple(r[k] for k in keys) for r in rows])
    # Every unit CL's approvers (integer ids), for approver-clustered checks.
    out.execute("CREATE TABLE cl_approver (change_number, approver_id, rank)")
    out.executemany("INSERT INTO cl_approver VALUES (?,?,?)",
                    [(r["change_number"], p, i) for r in rows for i, p in enumerate(base_by_n[r["change_number"]]["appr"])])
    out.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    out.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    out.commit()
    import resource
    log(f"wrote {args.out}; peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6:.2f} GB")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
