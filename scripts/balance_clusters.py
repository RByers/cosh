"""Cohorts of authors and reviewers by PCA and k-means (docs/balance-clusters.md).

Offline; reads balance*.sqlite, derived.sqlite and the shared Chromium clone
(via balance_analysis / balance_growth). Writes private, per-person output
under data/private/balance_clusters/ and prints aggregate tables that are safe
to publish (cluster sizes, profiles, transition shares).

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_clusters.py \\
      --first-commit F --owners-added F --mech mech.jsonl [--out DIR]

Clusters describe what people did in a half-year relative to everyone active
that half-year. They are descriptions, not judgements, and nobody's cluster is
ever published.
"""

import argparse
import json
import math
import os
import random
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

YEAR = 365.25 * 86400


# ------------------------------------------------------------ linear algebra

def mean_vec(rows):
    n = len(rows)
    return [sum(r[j] for r in rows) / n for j in range(len(rows[0]))]


def covariance(rows):
    mu = mean_vec(rows)
    d, n = len(mu), len(rows)
    c = [[0.0] * d for _ in range(d)]
    for r in rows:
        x = [r[j] - mu[j] for j in range(d)]
        for i in range(d):
            xi = x[i]
            ci = c[i]
            for j in range(i, d):
                ci[j] += xi * x[j]
    for i in range(d):
        for j in range(i, d):
            c[i][j] /= max(1, n - 1)
            c[j][i] = c[i][j]
    return c


def jacobi_eigen(a, tol=1e-12, max_sweeps=100):
    """Eigenvalues and eigenvectors of a symmetric matrix, largest first.
    Returns (values, vectors) with vectors[k] the k-th unit eigenvector."""
    n = len(a)
    a = [row[:] for row in a]
    v = [[float(i == j) for j in range(n)] for i in range(n)]
    for _ in range(max_sweeps):
        off = sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j)
        if off < tol:
            break
        for p in range(n):
            for q in range(p + 1, n):
                if abs(a[p][q]) < 1e-15:
                    continue
                theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
                t = (1 if theta >= 0 else -1) / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    vals = [a[i][i] for i in range(n)]
    order = sorted(range(n), key=lambda i: -vals[i])
    vecs = []
    for i in order:
        e = [v[k][i] for k in range(n)]
        # Sign convention: the largest-magnitude loading is positive.
        if e[max(range(n), key=lambda k: abs(e[k]))] < 0:
            e = [-x for x in e]
        vecs.append(e)
    return [vals[i] for i in order], vecs


def pca(rows, k):
    """(explained variance shares, components, mean) of the top k components."""
    vals, vecs = jacobi_eigen(covariance(rows))
    tot = sum(max(0.0, x) for x in vals) or 1.0
    return [x / tot for x in vals[:k]], vecs[:k], mean_vec(rows)


def project(row, comps, mu):
    return [sum((row[j] - mu[j]) * c[j] for j in range(len(mu))) for c in comps]


def dist2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def kmeans(rows, k, restarts=5, iters=60, seed=1):
    """k-means++ with restarts. Returns (centroids, labels, inertia)."""
    best = None
    rng = random.Random(seed)
    for _ in range(restarts):
        cents = [list(rows[rng.randrange(len(rows))])]
        d2 = [dist2(r, cents[0]) for r in rows]
        while len(cents) < k:
            tot = sum(d2)
            x = rng.random() * tot
            acc = 0.0
            for i, w in enumerate(d2):
                acc += w
                if acc >= x:
                    break
            cents.append(list(rows[i]))
            d2 = [min(a, dist2(r, cents[-1])) for a, r in zip(d2, rows)]
        labels = [0] * len(rows)
        for _ in range(iters):
            changed = False
            for i, r in enumerate(rows):
                j = min(range(k), key=lambda c: dist2(r, cents[c]))
                if j != labels[i]:
                    labels[i], changed = j, True
            sums = [[0.0] * len(rows[0]) for _ in range(k)]
            cnt = [0] * k
            for r, j in zip(rows, labels):
                cnt[j] += 1
                s = sums[j]
                for t, x in enumerate(r):
                    s[t] += x
            for j in range(k):
                if cnt[j]:
                    cents[j] = [x / cnt[j] for x in sums[j]]
            if not changed:
                break
        inertia = sum(dist2(r, cents[j]) for r, j in zip(rows, labels))
        if best is None or inertia < best[2]:
            best = (cents, labels, inertia)
    return best


def assign(row, cents):
    return min(range(len(cents)), key=lambda c: dist2(row, cents[c]))


def silhouette(rows, labels, sample=1500, seed=3):
    """Mean silhouette on a random sample (exact distances within it)."""
    rng = random.Random(seed)
    idx = list(range(len(rows)))
    if len(idx) > sample:
        idx = rng.sample(idx, sample)
    k = max(labels) + 1
    scores = []
    for i in idx:
        by = defaultdict(list)
        for j in idx:
            if j != i:
                by[labels[j]].append(math.sqrt(dist2(rows[i], rows[j])))
        own = by.get(labels[i])
        if not own:
            continue
        a = sum(own) / len(own)
        b = min((sum(v) / len(v) for c, v in by.items() if c != labels[i] and v), default=None)
        if b is None:
            continue
        scores.append((b - a) / max(a, b) if max(a, b) else 0.0)
    return sum(scores) / len(scores) if scores else 0.0 if k else 0.0


# ----------------------------------------------------------------- features

GIT_FEATURES = ["authored", "active_months", "size", "breadth", "approvals", "review_share",
                "newcomer_approvals", "owner", "tenure"]
REVIEW_FEATURES = ["feedback_resid", "interdiff", "rounds_resid", "threads_per_review",
                   "response_h", "gerrit_reviews"]
GERRIT_FROM = 2023 * 2 + 1          # 2023H2


def half_start(h):
    return datetime(h // 2, 1 if h % 2 == 0 else 7, 1, tzinfo=timezone.utc).timestamp()


def build_panel(cls, commits, ids, first, owner_at, use, dirs3, reviewer_rows):
    """{(pid, half): {feature: raw value}} for person-halves with >= 3 authored
    commits or >= 3 approvals given (git), or >= 3 Gerrit reviews."""
    import balance_growth as G
    rnd = random.Random(7)
    ph = defaultdict(lambda: dict(n=0, months=set(), lines=[], dirs=[], appr=0, newc=0, rmonths=set()))
    for c in commits:
        if c["is_revert"] or not c["n"]:
            continue
        h = G.half(c["at"])
        m = datetime.fromtimestamp(c["at"], timezone.utc).month
        r = ph[(c["pid"], h)]
        r["n"] += 1
        r["months"].add(m)
        r["lines"].append(c["lines"])
        d = dirs3.get(c["cid"])
        if d:
            r["dirs"].append(d[0])
        new_author = c["pid"] in first and c["at"] - first[c["pid"]] < YEAR
        for rv in c["rbp"]:
            if rv != c["pid"]:
                x = ph[(rv, h)]
                x["appr"] += 1
                x["newc"] += new_author
                x["rmonths"].add(m)
    gerrit = defaultdict(lambda: dict(lr=[], ish=[], rr=[]))
    for c in use:
        h = G.half(c["closed_at"])
        g = gerrit[(c["pid"], h)]
        if c["r_threads"] is not None:
            g["lr"].append(c["r_threads"])
        if c["ish"] is not None:
            g["ish"].append(c["ish"])
        if c["r_rounds"] is not None:
            g["rr"].append(c["r_rounds"])
    panel = {}
    keys = set(ph) | set(gerrit) | set(reviewer_rows)
    for key in keys:
        pid, h = key
        if pid not in first:
            continue
        r = ph.get(key)
        rv = reviewer_rows.get(key)
        n = r["n"] if r else 0
        appr = r["appr"] if r else 0
        nrev = len(rv["threads"]) if rv else 0
        if n < 3 and appr < 3 and nrev < 3:
            continue
        f = {}
        f["authored"] = math.log1p(n / 6)
        f["active_months"] = len(r["months"]) / 6 if r else 0.0
        f["size"] = math.log1p(st.median(r["lines"])) if r and n >= 3 else None
        if r and len(r["dirs"]) >= 10:
            f["breadth"] = len(set(rnd.sample(r["dirs"], 10)))
        else:
            f["breadth"] = None
        f["approvals"] = math.log1p(appr / 6)
        f["review_share"] = appr / (appr + n) if appr + n else 0.0
        f["newcomer_approvals"] = r["newc"] / appr if r and appr >= 3 else 0.0
        f["owner"] = 1.0 if owner_at.get(pid, 1e18) <= half_start(h) + YEAR / 2 else 0.0
        f["tenure"] = math.log1p(max(0.0, (half_start(h) - first[pid]) / YEAR))
        if h >= GERRIT_FROM:
            g = gerrit.get(key)
            f["feedback_resid"] = st.mean(g["lr"]) if g and len(g["lr"]) >= 3 else None
            f["interdiff"] = st.median(g["ish"]) if g and len(g["ish"]) >= 3 else None
            f["rounds_resid"] = st.mean(g["rr"]) if g and len(g["rr"]) >= 3 else None
            f["threads_per_review"] = st.mean(rv["threads"]) if nrev >= 3 else None
            f["response_h"] = math.log1p(st.median(rv["resp"])) if rv and len(rv["resp"]) >= 3 else None
            f["gerrit_reviews"] = math.log1p(nrev / 6)
            f["gerrit_newcomer_share"] = (sum(rv["newcomer"]) / nrev) if nrev >= 3 else None
        f["_raw"] = dict(commits=n, approvals=appr, gerrit_reviews=nrev,
                         median_lines=st.median(r["lines"]) if r and n else None,
                         active_months=len(r["months"]) if r else 0)
        panel[key] = f
    return panel


def reviewer_side(cls, ids, first):
    """{(pid, half): {threads: [...], resp: [...], newcomer: [...]}} per
    (CL, reviewer), as in balance_report.py: threads the reviewer started,
    weekday hours from being added to the attention set to their first
    comment, and whether the CL's author was in their first year."""
    import balance_analysis as A
    import balance_growth as G
    from cosh import balance, store
    d = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    emails = dict(d.execute("SELECT account_id, email FROM accounts"))
    bots = {a for a, in d.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    by_n = {c["change_number"]: c for c in cls if c["status"] == "MERGED" and c["closed_at"]}
    first_c = {}
    for n, acct, at in d.execute("SELECT change_number, account_id, min(written_at) FROM comments "
                                 "WHERE after_close = 0 GROUP BY 1, 2"):
        if n in by_n and acct not in bots:
            first_c[(n, acct)] = balance.epoch(at)
    thr = Counter()
    for n, acct in d.execute("SELECT change_number, root_account FROM threads"):
        if n in by_n and acct not in bots:
            thr[(n, acct)] += 1
    tl = A.ro(balance.db_path("timeline"))
    added = {}
    for n, acct, s in tl.execute("SELECT change_number, account_id, min(start_at) FROM attention GROUP BY 1, 2"):
        if n in by_n:
            added[(n, acct)] = s
    out = defaultdict(lambda: dict(threads=[], resp=[], newcomer=[]))
    pid_of = {}
    for (n, acct), t0 in first_c.items():
        c = by_n[n]
        if acct == c["owner"]:
            continue
        e = emails.get(acct)
        if not e or A.is_bot_email(e):
            continue
        p = pid_of.get(acct) or pid_of.setdefault(acct, ids.find(e))
        x = out[(p, G.half(c["closed_at"]))]
        x["threads"].append(thr.get((n, acct), 0))
        a = added.get((n, acct))
        if a and t0 >= a:
            x["resp"].append(balance.weekday_seconds(a, t0) / 3600)
        x["newcomer"].append(c["pid"] in first and c["closed_at"] - first[c["pid"]] < YEAR)
    return out


def standardize(panel, features):
    """z-scores within each half-year (calendar effects drop out); missing
    values become 0 (the half-year's mean) and are flagged."""
    by_h = defaultdict(list)
    for (p, h), f in panel.items():
        by_h[h].append(f)
    stats = {}
    for h, fs in by_h.items():
        for k in features:
            vs = [f[k] for f in fs if f.get(k) is not None]
            if len(vs) >= 20:
                mu = sum(vs) / len(vs)
                sd = math.sqrt(sum((v - mu) ** 2 for v in vs) / len(vs)) or 1.0
                stats[(h, k)] = (mu, sd)
    z = {}
    for (p, h), f in panel.items():
        row = []
        for k in features:
            v, s = f.get(k), stats.get((h, k))
            row.append(0.0 if v is None or s is None else max(-4.0, min(4.0, (v - s[0]) / s[1])))
        z[(p, h)] = row
    return z


# ------------------------------------------------------------------- naming

def name_cluster(prof):
    """A neutral name from a centroid's feature profile (z-scores within the
    half-year): what the group does more or less of than everyone active."""
    g = lambda k: prof.get(k, 0.0)
    if g("tenure") < -0.6 and g("owner") < -0.5:
        return "newcomers ramping up"
    if g("newcomer_approvals") > 1.0:
        return "reviewer-mentors"
    if g("review_share") > 0.8 and g("authored") < -0.4:
        return "mostly reviewing"
    if g("approvals") > 0.6 and g("authored") > 0.4:
        return "authors who also review a lot"
    if g("authored") > 0.6:
        return "high-volume authors"
    if g("authored") < -0.6:
        return "occasional contributors"
    return "steady authors"


# Families for paths: reviewing roles, authoring roles, and light activity.
REVIEW_FAMILY = {"reviewer-mentors", "mostly reviewing", "authors who also review a lot"}
LIGHT_FAMILY = {"occasional contributors", "newcomers ramping up", "early-career, light activity"}


def family(name):
    n = name.split(" (")[0]
    return "review" if n in REVIEW_FAMILY else "light" if n in LIGHT_FAMILY else "author"


def unique_names(names):
    seen = Counter(names)
    out, k = [], Counter()
    for n in names:
        if seen[n] > 1:
            k[n] += 1
            n = f"{n} ({'abcdefg'[k[n] - 1]})"
        out.append(n)
    return out


# --------------------------------------------------------------------- model

def fit_model(z, features, label, ks=range(4, 9), k_fixed=None, sample=6000, seed=5):
    import balance_growth as G
    keys = sorted(z)
    rows = [z[k] for k in keys]
    var, comps, mu = pca(rows, min(5, len(features)))
    pcs = [project(r, comps, mu) for r in rows]
    rng = random.Random(seed)
    idx = rng.sample(range(len(rows)), min(sample, len(rows)))
    srows = [rows[i] for i in idx]
    print(f"\n== {label}: {len(rows):,} person-halves, {len(features)} features")
    print("PCA explained variance: " + ", ".join(f"PC{i + 1} {v:.0%}" for i, v in enumerate(var)))
    for i, c in enumerate(comps[:3]):
        top = sorted(zip(features, c), key=lambda x: -abs(x[1]))[:5]
        print(f"  PC{i + 1}: " + ", ".join(f"{k} {w:+.2f}" for k, w in top))
    best = None
    for k in ks:
        cents, labels, _ = kmeans(srows, k, seed=seed)
        s = silhouette(srows, labels)
        print(f"  k={k}: silhouette {s:.3f}")
        if best is None or s > best[0] + 0.01:
            best = (s, k, cents)
    s, k, cents = best
    if k_fixed and k_fixed != k:
        # Silhouette favours few, broad groups; a fixed k keeps roles apart
        # (interpretability), and the silhouette is reported alongside.
        cents, labels, _ = kmeans(srows, k_fixed, seed=seed)
        s, k = silhouette(srows, labels), k_fixed
    # Refine on all rows from the sample's centroids.
    cents, labels, _ = kmeans_from(rows, cents)
    profs = [dict(zip(features, c)) for c in cents]
    names = [name_cluster(p) for p in profs]
    # Two groups of not-yet-owners: the newer one is "newcomers ramping up",
    # the other "early-career, light activity".
    early = [j for j, n in enumerate(names) if n == "newcomers ramping up"]
    if len(early) > 1:
        early.sort(key=lambda j: profs[j].get("tenure", 0.0))
        for j in early[1:]:
            names[j] = "early-career, light activity"
    names = unique_names(names)
    out = dict(features=features, pca=dict(variance=var, components=comps, mean=mu),
               k=k, silhouette=s, centroids=cents, names=names)
    assignment = {key: (names[j], pc) for key, j, pc in zip(keys, labels, pcs)}
    sizes = Counter(names[j] for j in labels)
    print(f"  chose k={k} (silhouette {s:.3f})")
    print(f"  {'cluster':30} {'share':>6}  profile (z vs everyone active that half-year)")
    for j, nm in enumerate(names):
        top = sorted(profs[j].items(), key=lambda x: -abs(x[1]))[:6]
        print(f"  {nm:30} {sizes[nm] / len(rows):>6.1%}  " + ", ".join(f"{a} {b:+.1f}" for a, b in top))
    return out, assignment


def kmeans_from(rows, cents, iters=60):
    cents = [list(c) for c in cents]
    k = len(cents)
    labels = [assign(r, cents) for r in rows]
    for _ in range(iters):
        sums = [[0.0] * len(rows[0]) for _ in range(k)]
        cnt = [0] * k
        for r, j in zip(rows, labels):
            cnt[j] += 1
            for t, x in enumerate(r):
                sums[j][t] += x
        cents = [[x / cnt[j] for x in sums[j]] if cnt[j] else cents[j] for j in range(k)]
        new = [assign(r, cents) for r in rows]
        if new == labels:
            break
        labels = new
    return cents, labels, sum(dist2(r, cents[j]) for r, j in zip(rows, labels))


# --------------------------------------------------------------- trajectories

def trajectory(seq):
    """A label for a person's path through git-model clusters: (half, name)
    pairs in order, compared between the first and last third of the path."""
    fams = [family(n) for _, n in seq]
    third = max(1, len(fams) // 3)
    start = Counter(fams[:third]).most_common(1)[0][0]
    end = Counter(fams[-third:]).most_common(1)[0][0]
    if start == end:
        changes = sum(1 for a, b in zip(fams, fams[1:]) if a != b)
        if changes > len(fams) // 2:
            return "mixed"
        return {"review": "stable reviewer", "author": "stable author", "light": "stays light"}[start]
    return {("author", "review"): "author → reviewer", ("light", "review"): "light → reviewer",
            ("light", "author"): "ramping up to author", ("review", "author"): "reviewer → author",
            ("author", "light"): "tapering off", ("review", "light"): "tapering off"}[(start, end)]


def transitions(seq_by_person, starts):
    """Year-over-year family transitions (h -> h+2) for the given start halves."""
    t = Counter()
    for seq in seq_by_person.values():
        d = dict(seq)
        for h in starts:
            if h in d and h + 2 in d:
                t[(family(d[h]), family(d[h + 2]))] += 1
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-commit", help="default: commits.sqlite")
    ap.add_argument("--owners-added", help="default: commits.sqlite")
    ap.add_argument("--mech", help="default: commits.sqlite")
    ap.add_argument("--out")
    ap.add_argument("--k", type=int, default=6, help="clusters per model (default 6; 0: best silhouette)")
    args = ap.parse_args()
    args.ai_marked = None
    import balance_analysis as A
    import balance_growth as G
    import balance_report as R
    from cosh import store
    out_dir = args.out or os.path.join(store.DATA_DIR, "balance_clusters")
    os.makedirs(out_dir, exist_ok=True)

    cls, commits, ids, first, owner_at, _ = G.load_all(args)
    mech = R.mech_set(args.mech)
    dirs3 = A.commit_dirs(3)
    top2 = {}
    for c in commits:
        d = dirs3.get(c["cid"])
        if c["n"] and d:
            top2[c["n"]] = "/".join(d[0].split("/")[:2])
    A.MECH_FILES = 10 ** 9
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    use = G.cl_residuals(cls, top2)
    rv = reviewer_side(cls, ids, first)
    panel = build_panel(cls, commits, ids, first, owner_at, use, dirs3, rv)
    print(f"panel: {len(panel):,} person-halves, {len({p for p, _ in panel}):,} people", file=sys.stderr)

    # Git model: every half-year since 2017, so paths can be followed.
    git_panel = {k: v for k, v in panel.items() if k[1] >= 2017 * 2}
    zg = standardize(git_panel, GIT_FEATURES)
    git_model, git_assign = fit_model(zg, GIT_FEATURES, "Git model (2017H1-2026H2)", k_fixed=args.k)

    # Review model: Gerrit era, git + review features.
    rv_panel = {k: v for k, v in panel.items() if k[1] >= GERRIT_FROM}
    feats = GIT_FEATURES + REVIEW_FEATURES
    zr = standardize(rv_panel, feats)
    rv_model, rv_assign = fit_model(zr, feats, "Review model (2023H2-2026H2)", k_fixed=args.k)

    # Shares of each review-model cluster in the pre-AI and recent windows.
    win = {"pre-AI 2023H2-2024H2": range(2023 * 2 + 1, 2024 * 2 + 2),
           "recent 2025H2-2026H1": range(2025 * 2 + 1, 2026 * 2 + 1)}
    agg = dict(review_windows={}, git_windows={})
    print("\n== Cluster shares by window (person-halves)")
    for wn, hs in win.items():
        for model_name, a, key in (("review", rv_assign, "review_windows"), ("git", git_assign, "git_windows")):
            c = Counter(n for (p, h), (n, _) in a.items() if h in hs)
            tot = sum(c.values())
            agg[key][wn] = {n: round(v / tot, 3) for n, v in sorted(c.items(), key=lambda x: -x[1])}
            print(f"  {model_name:6} {wn}: " + ", ".join(f"{n} {v / tot:.0%}" for n, v in c.most_common()))

    # Paths.
    seqs = defaultdict(list)
    for (p, h), (n, _) in sorted(git_assign.items(), key=lambda x: x[0][1]):
        seqs[p].append((h, n))
    traj = {p: trajectory(s) for p, s in seqs.items() if len(s) >= 4}
    print(f"\n== Trajectories (people with >= 4 active half-years since 2017): {len(traj):,}")
    for t, n in Counter(traj.values()).most_common():
        print(f"  {t:24} {n / len(traj):.0%}")

    # Joiners at the same tenure: their first 6 half-years after joining.
    def joined(p):
        return datetime.fromtimestamp(first[p], timezone.utc).year
    early = defaultdict(list)
    for p, s in seqs.items():
        j = G.half(first[p])
        path = [(h, n) for h, n in s if j <= h < j + 6]
        if len(path) >= 4 and j + 6 <= 2026 * 2 + 2:
            early[p] = path
    mix = {}
    print("\n== First three years after joining (>= 4 active half-years of the first 6)")
    for label, ys in (("joined 2017-2019", range(2017, 2020)), ("joined 2021-2023", range(2021, 2024))):
        ps = [p for p in early if joined(p) in ys]
        c = Counter(trajectory(early[p]) for p in ps)
        mix[label] = {"people": len(ps), **{k: round(v / max(1, len(ps)), 3) for k, v in c.most_common()}}
        print(f"  {label} ({len(ps):,} people): " + ", ".join(f"{k} {v / max(1, len(ps)):.0%}" for k, v in c.most_common()))

    # Year-over-year transitions, pre-AI vs AI era.
    tr = {}
    print("\n== Year-over-year transitions between families (author / review / light)")
    for label, hs in (("2019H1-2020H2 -> a year later", range(2019 * 2, 2020 * 2 + 2)),
                      ("2021H1-2023H1 -> a year later", range(2021 * 2, 2023 * 2 + 1)),
                      ("2024H1-2024H2 -> a year later (into 2025)", range(2024 * 2, 2024 * 2 + 2)),
                      ("2025H1 -> a year later (into 2026H1)", range(2025 * 2, 2025 * 2 + 1))):
        t = transitions(seqs, hs)
        rows = {}
        for a in ("light", "author", "review"):
            tot = sum(v for (x, _), v in t.items() if x == a)
            rows[a] = {b: round(t[(a, b)] / tot, 3) if tot else None for b in ("light", "author", "review")}
            rows[a]["n"] = tot
        tr[label] = rows
        print(f"  {label}")
        for a, r in rows.items():
            print(f"    from {a:7} (n={r['n']:>5,}): " + ", ".join(f"→{b} {r[b]:.0%}" for b in ("light", "author", "review") if r[b] is not None))

    # Profiles of clusters (raw medians) for the doc.
    def profile(a, model):
        by = defaultdict(list)
        for key, (n, _) in a.items():
            by[n].append(panel[key])
        res = {}
        for n, fs in by.items():
            raw = lambda k: st.median([f["_raw"][k] for f in fs if f["_raw"][k] is not None] or [0])
            res[n] = dict(person_halves=len(fs),
                          median_tenure_years=round(st.median(math.expm1(f["tenure"]) for f in fs), 1),
                          median_commits_per_half=raw("commits"), median_approvals_per_half=raw("approvals"),
                          median_gerrit_reviews_per_half=raw("gerrit_reviews"),
                          owner_share=round(sum(f["owner"] for f in fs) / len(fs), 2))
        return res
    agg["git_profiles"] = profile(git_assign, git_model)
    agg["review_profiles"] = profile(rv_assign, rv_model)
    agg["trajectories"] = dict(Counter(traj.values()))
    agg["joiner_mix"] = mix
    agg["transitions"] = tr
    for model, nm in ((git_model, "git"), (rv_model, "review")):
        print(f"\n== {nm} cluster profiles (medians)")
        for n, prof in agg[f"{nm}_profiles"].items():
            print(f"  {n:30} " + ", ".join(f"{k} {v}" for k, v in prof.items()))

    # Private per-person output.
    aliases = defaultdict(list)
    for e in list(ids.p):
        aliases[ids.find(e)].append(e)
    people = {}
    for (p, h), f in panel.items():
        x = people.setdefault(p, dict(aliases=sorted(set(aliases.get(p, [p]))),
                                      first_commit=int(first[p]), owner_at=owner_at.get(p),
                                      trajectory=traj.get(p), halves={}))
        g = git_assign.get((p, h))
        r = rv_assign.get((p, h))
        x["halves"][G.half_name(h)] = dict(
            git_cluster=g[0] if g else None, git_pc=[round(v, 3) for v in g[1][:3]] if g else None,
            review_cluster=r[0] if r else None, review_pc=[round(v, 3) for v in r[1][:3]] if r else None,
            features={k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items() if k != "_raw"},
            raw=f["_raw"])
    with open(os.path.join(out_dir, "people.json"), "w") as fh:
        json.dump(people, fh, separators=(",", ":"))
    with open(os.path.join(out_dir, "clusters.json"), "w") as fh:
        json.dump(dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                       git_model=git_model, review_model=rv_model, aggregate=agg), fh, indent=1)
    print(f"\nwrote {out_dir}/people.json ({len(people):,} people) and clusters.json", file=sys.stderr)


if __name__ == "__main__":
    main()
