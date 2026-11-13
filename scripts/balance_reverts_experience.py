"""Do authors get reverted less as they gain experience? For the Review
Balance page's "Reverts and the author's experience" section
(docs/balance.md, section 4d).

Every human commit on main with a Gerrit CL, landed 2017-07-01 .. the last whole quarter, not
itself a revert, not a mass edit (100+ files or an LSC), is one trial; it
counts as reverted when a commit on main reverted it within 30 days (as the
page's other revert charts). Experience is the author's commits on main
before it, over main's whole history (from 2008): all of them ("practice"),
and those that touched the commit's main 2-level directory ("practice
here"). Reverts are not counted as practice; relands are.

Three estimates per experience band:

- as found: the share reverted;
- like for like: the same, re-weighted to the overall mix of size (ten
  log-spaced buckets), 2-level directory and year;
- same author: a multiplicative (Poisson) model with a factor per author
  as well, so each band is compared with the same people's commits in other
  bands. That separates learning from selection: authors who are reverted
  often and then leave would make the as-found curve fall with no one
  learning anything.

The directory chart holds overall practice fixed too (its band is another
factor), so it shows what experience in the directory adds beyond
experience on main.

Offline; reads commits.sqlite only (about 3 min, 3 GB). Writes aggregates
only, never anything per person.

  COSH_DATA_DIR=<main>/data/private nice -n 5 python3 scripts/balance_reverts_experience.py [--out F]
"""

import argparse
import math
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cosh import balance_publish  # noqa: E402
from cosh import commits as commit_store  # noqa: E402
from cosh.people import is_bot_email, person  # noqa: E402

DAY = 86400
START = datetime(2017, 7, 1, tzinfo=timezone.utc).timestamp()
END = balance_publish.quarter_end(balance_publish.LAST_QUARTER).timestamp()
WINDOW = 30 * DAY
MASS_FILES = 100

PRACTICE = [(0, 1), (1, 3), (3, 10), (10, 30), (30, 100), (100, 300), (300, 1000), (1000, 3000), (3000, 10 ** 9)]
HERE = [(0, 1), (1, 3), (3, 10), (10, 30), (30, 100), (100, 300), (300, 10 ** 9)]
MIN_COMMITS = 2000          # per published point
REPS = 30                   # bootstrap replicates; 90% intervals
BOOT_ITERS = 40             # per replicate, from the full fit's factors


def label(lo, hi):
    return f"{lo}+" if hi >= 10 ** 9 else str(lo) if hi == lo + 1 else f"{lo}-{hi - 1}"


def band(bins, v):
    for i, (lo, hi) in enumerate(bins):
        if lo <= v < hi:
            return i
    return None


def size10(lines):
    return min(9, max(0, int(math.log2(max(lines, 1))) - 1))


def dir2(path):
    parts = path.split("/")[:-1]
    return "/".join(parts[:2]) + "/" if parts else "(root)/"


def load(db):
    """Per sampled commit: (person, practice band, practice-here band,
    stratum, reverted). Walks main's whole history in landing order."""
    paths = {}
    for pid, p in db.execute("SELECT path_id, path FROM paths"):
        paths[pid] = sys.intern(dir2(p))
    dirs = defaultdict(dict)               # commit_id -> {dir2: weight}
    for cid, pid, ins, dels in db.execute("SELECT commit_id, path_id, ins, dels FROM commit_files"):
        d = dirs[cid]
        k = paths[pid]
        d[k] = d.get(k, 0) + max(ins, 0) + max(dels, 0) + 1
    del paths
    rows = db.execute("SELECT commit_id, sha, author_email, landed_at, is_bot, reverts_sha, is_revert, files, "
                      "ins + dels, is_lsc, change_number FROM commits ORDER BY commit_id").fetchall()
    reverted = {}
    for r in rows:
        if r[5]:
            reverted[r[5]] = min(r[3], reverted.get(r[5], r[3]))
    done = defaultdict(int)                # person -> commits so far
    done_here = defaultdict(int)           # (person, dir2) -> commits so far
    out = []
    for cid, sha, email, at, bot, rv_sha, is_rev, files, lines, lsc, cn in rows:
        if bot or is_bot_email(email):
            continue
        p = person(email)
        ds = dirs.pop(cid, None) or {}
        if is_rev:
            continue
        if START <= at < END and cn and files and files < MASS_FILES and not lsc and ds:
            main = max(ds, key=ds.get)
            rat = reverted.get(sha)
            out.append((p, band(PRACTICE, done[p]), band(HERE, done_here[(p, main)]),
                        (size10(lines), main, datetime.fromtimestamp(at, timezone.utc).year),
                        1 if rat is not None and rat - at < WINDOW else 0))
        done[p] += 1
        for d in ds:
            done_here[(p, d)] += 1
    return out


def fit(codes, n, y, f=None, tol=1e-6, iters=500):
    """Multiplicative Poisson model, rate = product of one factor per coded
    key, by iterative proportional fitting (each factor in turn set to
    observed / expected). codes: per factor, the cells' integer keys; n, y:
    the cells' commits and reverts. f: starting factors (warm start).
    Stops when no factor moves by more than tol (in log). A factor whose
    cells have no reverts is 0 and stays 0."""
    k = [max(c) + 1 for c in codes]
    f = [list(x) for x in f] if f else [[1.0] * m for m in k]
    obs = []
    for c, m in zip(codes, k):
        o = [0.0] * m
        for i, v in zip(c, y):
            o[i] += v
        obs.append(o)
    mu = list(n)                            # fitted reverts per cell
    for c, fc in zip(codes, f):
        mu = [a * fc[i] for a, i in zip(mu, c)]
    for _ in range(iters):
        moved = 0.0
        for j, c in enumerate(codes):
            fj, oj = f[j], obs[j]
            ex = [0.0] * k[j]
            for i, v in zip(c, mu):
                ex[i] += v
            ratio = [1.0] * k[j]
            for i in range(k[j]):
                if oj[i] == 0:
                    ratio[i] = 0.0
                    fj[i] = 0.0
                elif ex[i] > 0:
                    r = oj[i] / ex[i]          # ex already includes the old factor
                    ratio[i] = r
                    fj[i] *= r
                    moved = max(moved, abs(math.log(r)))
            mu = [v * ratio[i] for v, i in zip(mu, c)]
        if moved < tol:
            break
    return f


def curve(rows, bkey, bins, extra=(), reps=REPS):
    """As found, like for like and same author, per band of rows' bkey,
    with author-clustered bootstrap intervals for same author. extra:
    further key positions held fixed in both models (e.g. overall practice
    for the directory chart)."""
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        a = agg[(r[bkey], r[3], r[0]) + tuple(r[k] for k in extra)]
        a[0] += 1
        a[1] += r[4]
    keys = list(agg)
    n = [agg[x][0] for x in keys]
    y = [agg[x][1] for x in keys]
    del agg
    codes = []
    for pos in range(3 + len(extra)):
        if pos == 0:
            codes.append([x[0] for x in keys])          # the band's index is its code
            continue
        m = {}
        codes.append([m.setdefault(x[pos], len(m)) for x in keys])
    nb = len(bins)
    bn, by = [0] * nb, [0] * nb
    for b, a, v in zip(codes[0], n, y):
        bn[b] += a
        by[b] += v
    base = sum(by) / sum(bn)

    def norm(f, bn, base):
        # Scaled so the bands' commit-weighted mean is the overall rate.
        f = f + [0.0] * (nb - len(f))
        m = sum(f[i] * bn[i] for i in range(nb)) / sum(bn)
        return [base * f[i] / m for i in range(nb)]
    ex = list(range(3, 3 + len(extra)))
    like = norm(fit([codes[i] for i in [0, 1] + ex], n, y)[0], bn, base)
    same_codes = [codes[i] for i in [0, 1, 2] + ex]
    fs = fit(same_codes, n, y)
    same = norm(fs[0], bn, base)

    # Author-clustered bootstrap of same author: each author's cells weighted by a
    # Poisson(1) count, warm-started from the fit. Only cells with commits
    # in the resample and an author with reverts can move the bands.
    rnd = random.Random(1)
    who = codes[2]
    hit = [0] * (max(who) + 1)
    for p, v in zip(who, y):
        hit[p] += v
    boot = []
    for _ in range(reps):
        w = [poisson1(rnd) for _ in hit]
        keep = [i for i, p in enumerate(who) if w[p] and hit[p]]
        nn = [n[i] * w[who[i]] for i in keep]
        yy = [y[i] * w[who[i]] for i in keep]
        cc = [[c[i] for i in keep] for c in same_codes]
        wn, wy = [0] * nb, [0] * nb
        for i, p in enumerate(who):
            wn[codes[0][i]] += n[i] * w[p]
            wy[codes[0][i]] += y[i] * w[p]
        f = fit(cc, nn, yy, fs, tol=1e-4, iters=BOOT_ITERS)
        boot.append(norm(f[0], wn, sum(wy) / sum(wn)))

    def ci(i):
        xs = sorted(b[i] for b in boot)
        return round(xs[int(0.05 * (len(xs) - 1))], 4), round(xs[int(0.95 * (len(xs) - 1) + 0.5)], 4)
    out = []
    for i, (lo, hi) in enumerate(bins):
        if bn[i] < MIN_COMMITS:
            continue
        sl, sh = ci(i)
        out.append(dict(band=label(lo, hi), lo=lo, commits=bn[i], reverted=by[i], rate=round(by[i] / bn[i], 4),
                        like=round(like[i], 4), same=round(same[i], 4), same_lo=sl, same_hi=sh))
    return out


def poisson1(rnd):
    """A Poisson(1) draw (Knuth)."""
    k, p, lim = 0, 1.0, math.exp(-1)
    while True:
        p *= rnd.random()
        if p < lim:
            return k
        k += 1


def authors_per_band(rows, bkey, bins):
    s = [set() for _ in bins]
    for r in rows:
        s[r[bkey]].add(r[0])
    return [len(x) for x in s]


def compute(args=None):
    rows = load(commit_store.open_ro())
    print(f"{len(rows):,} commits, {sum(r[4] for r in rows):,} reverted within 30 days", file=sys.stderr)
    practice = curve(rows, 1, PRACTICE)
    here = curve(rows, 2, HERE, extra=(1,))
    na = authors_per_band(rows, 1, PRACTICE)
    for row in practice:
        row["authors"] = na[PRACTICE.index(next(b for b in PRACTICE if b[0] == row["lo"]))]
    na = authors_per_band(rows, 2, HERE)
    for row in here:
        row["authors"] = na[HERE.index(next(b for b in HERE if b[0] == row["lo"]))]
    first, last = practice[0], practice[-1]
    mid = next(r for r in practice if r["lo"] == 100)
    summary = dict(
        commits=len(rows), reverted=sum(r[4] for r in rows), rate=round(sum(r[4] for r in rows) / len(rows), 4),
        first_rate=first["rate"], first_same=first["same"], mid_rate=mid["rate"], mid_same=mid["same"],
        top_rate=last["rate"], top_same=last["same"], top_band=last["band"],
        here_first_same=here[0]["same"], here_top_same=here[-1]["same"], here_top_band=here[-1]["band"],
        since=2017, through=balance_publish.LAST_QUARTER)
    return {"revert_practice": practice, "revert_practice_here": here, "revert_practice_summary": [summary]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()
    new = compute(args)
    for name in ("revert_practice", "revert_practice_here"):
        print(f"\n{name}: band commits authors reverted | as found | like for like | same author")
        for r in new[name]:
            print(f"{r['band']:>10} {r['commits']:>9,} {r['authors']:>7,} {r['reverted']:>7,} | "
                  f"{r['rate']:6.2%} | {r['like']:6.2%} | "
                  f"{r['same']:6.2%} ({r['same_lo']:.2%}-{r['same_hi']:.2%})")
    print(new["revert_practice_summary"][0])
    balance_publish.show(new, args.out)


if __name__ == "__main__":
    main()
