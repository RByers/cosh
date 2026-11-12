"""Exploratory analyses for the author/reviewer balance page (docs/balance.md).

Offline; reads data/private/balance*.sqlite (python3 -m cosh.balance) and
commits.sqlite (python3 -m cosh commits) and prints tables. No comment text
is read. Per-person figures are computed only to aggregate them; nothing here
prints a person's identity.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_analysis.py trends|mechanical|growth|pipeline

Also the loaders the other balance and feedback scripts share. Their inputs
come from commits.sqlite; the old hand-made files still work for
exploration, through the scripts' flags:
--first-commit F   lines "email first_commit_unix bot" over all of main's history
--owners-added F   lines "unix email path/OWNERS", an address added to an OWNERS file
--ai-marked F      shas of commits with an AI marker in their message
--mech F           mech.jsonl lines [change_number, files, threads, repetition, lines]
"""

import argparse
import json
import math
import os
import re
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cosh import balance, store  # noqa: E402
from cosh import commits as commit_store  # noqa: E402

BOT = re.compile("|".join(l.split("#")[0].strip() for l in open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "bots.txt"))
    if l.split("#")[0].strip()), re.I)


def git_db():
    return ro(balance.db_path("git"))


def load_first(path=None):
    """{person: unix time of their first commit on main} over all of its
    history: commits.sqlite, or a first_commit.txt."""
    if path:
        rows = (line.split() for line in open(path))
        rows = ((f[0], int(f[1]), 0) for f in rows if len(f) == 3 and f[2] == "0" and not is_bot_email(f[0]))
    else:
        rows = ((e, t, b) for e, (t, b) in commit_store.first_commits(git_db()).items())
    first = {}
    for e, t, bot in rows:
        if not bot and not is_bot_email(e):
            e = person(e)
            first[e] = min(t, first.get(e, t))
    return first


def load_owners_added(path=None):
    """[(unix time, email, OWNERS path)]: each address added to an OWNERS
    file since 2012 (commits.sqlite), or from an owners_added.txt."""
    if not path:
        return commit_store.owners_added(git_db())
    out = []
    for line in open(path):
        t, e, f = line.rstrip("\n").split(" ", 2)
        out.append((int(t), e, f))
    return out


def load_ai_marked(path=None):
    """Shas of the commits since 2023 with an AI marker in their message
    (commits.AI_MARKER; commits.sqlite), or from an ai_marked.txt."""
    return set(open(path).read().split()) if path else commit_store.ai_marked(git_db())


def mech_set(path=None, cls=None):
    """Mechanical CLs: merged CLs whose landed commit has 100 or more files,
    or 10 or more with a repetition ratio of 0.8 or more. From commits.sqlite's
    repetition ratios and balance.sqlite's CLs (or `cls`, dicts with its
    change_number, status, sha and files), or from a mech.jsonl."""
    out = set()
    if path:
        for line in open(path):
            n, files, threads, rep, lines = json.loads(line)
            if files >= 100 or (rep is not None and rep >= 0.8):
                out.add(n)
        return out
    rep = commit_store.repetition(git_db())
    if cls is not None:
        rows = ((c["change_number"], c["sha"], c["files"]) for c in cls
                if c["status"] == "MERGED" and c["files"] is not None and c["files"] >= 10)
    else:
        rows = ro(os.environ.get("BALANCE_CL") or balance.db_path("cl")).execute(
            "SELECT change_number, sha, files FROM cl WHERE status = 'MERGED' AND files >= 10")
    for n, sha, files in rows:
        r = rep.get(sha)
        if files >= 100 or (r is not None and r >= 0.8):
            out.add(n)
    return out


def quarter(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def year(t):
    return datetime.fromtimestamp(t, timezone.utc).year


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else float("nan")


def med(xs):
    return st.median(xs) if xs else float("nan")


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def person(e):
    """One identity per person across Chromium's two common domains: many
    people author as user@chromium.org and review as user@google.com."""
    e = (e or "").lower()
    if e.count("@") > 1:            # SVN-era author: user@domain@<repository uuid>
        e = e.rsplit("@", 1)[0]
    local, _, dom = e.partition("@")
    return f"{local}@google.com" if dom in ("chromium.org", "google.com") else e


def is_bot_email(e):
    return not e or bool(BOT.search(e))


def load_cl():
    db = ro(os.environ.get("BALANCE_CL") or balance.db_path("cl"))
    db.row_factory = sqlite3.Row
    out = [dict(r) for r in db.execute("SELECT * FROM cl")]
    for c in out:
        c["owner_email"] = person(c["owner_email"]) if c["owner_email"] else None
    return out


def load_commits():
    """Human commits on main since 2017 with a Gerrit CL."""
    db = git_db()
    rows = db.execute("SELECT commit_id, sha, author_email, landed_at, change_number, is_bot, reviewed_by, "
                      "reverts_sha, is_reland, files, ins + dels FROM gcommits").fetchall()
    reverted = defaultdict(lambda: None)
    for r in rows:
        if r[7]:
            reverted[r[7]] = min(r[3], reverted[r[7]] or r[3])
    out = []
    for cid, sha, email, at, n, bot, rb, rv, rl, files, lines in rows:
        if bot or is_bot_email(email):
            continue
        out.append(dict(cid=cid, sha=sha, email=person(email), at=at, n=n,
                        rb=[person(x) for x in json.loads(rb)] if rb else [],
                        is_revert=rv is not None, reland=rl, files=files, lines=lines,
                        reverted_at=reverted[sha]))
    return out


# ------------------------------------------------------------------ mechanical

def mechanical(cls):
    m = [c for c in cls if c["status"] == "MERGED" and c["files"]]
    big = [c for c in m if c["files"] >= 10]
    rep = commit_store.repetition(git_db())     # python3 -m cosh commits computes them
    for c in m:
        c["rep"] = rep.get(c["sha"]) if c["files"] >= 10 else None
    rb = [0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.01]
    print("\nCLs with >= 10 files by repetition ratio: CLs | share with a reviewer thread | threads/CL | "
          "threads per file | median files")
    for lo, hi in zip(rb, rb[1:]):
        s = [c for c in big if c["rep"] is not None and lo <= c["rep"] < hi]
        if s:
            print(f"{lo:.1f}-{min(hi, 1):.1f} {len(s):>7,} {sum(1 for c in s if c['threads']) / len(s):6.0%} "
                  f"{st.mean(c['threads'] for c in s):6.2f} {st.mean(c['threads'] / c['files'] for c in s):7.3f} "
                  f"{med([c['files'] for c in s]):6.0f}")
    s = [c for c in big if c["rep"] is None]
    if s:
        print(f"too big  {len(s):>7,} {sum(1 for c in s if c['threads']) / len(s):6.0%} "
              f"{st.mean(c['threads'] for c in s):6.2f}")
    print(f"{len(m):,} merged human-owned CLs with a landed commit")
    fb = [1, 2, 5, 10, 20, 50, 100, 200, 500, 10**9]
    lab = ["1", "2-4", "5-9", "10-19", "20-49", "50-99", "100-199", "200-499", "500+"]
    print("\nfiles | CLs | share with any reviewer thread | threads/CL | threads per file | median lines/file "
          "| reverted<30d")
    for lo, hi, name in zip(fb, fb[1:], lab):
        s = [c for c in m if lo <= c["files"] < hi]
        if not s:
            continue
        rev = sum(1 for c in s if c["reverted_at"] and c["reverted_at"] - c["closed_at"] < 30 * 86400)
        print(f"{name:>8} {len(s):>7,} {sum(1 for c in s if c['threads']) / len(s):6.0%} "
              f"{st.mean(c['threads'] for c in s):6.2f} {st.mean(c['threads'] / c['files'] for c in s):7.3f} "
              f"{med([(c['git_lines'] or 0) / c['files'] for c in s]):7.1f} {rev / len(s):6.2%}")
    # 2-D: files bucket x threads-per-file bucket, counts.
    tb = [0, 1e-9, 0.01, 0.05, 0.2, 1, 1e9]
    tl = ["0", "<.01", ".01-.05", ".05-.2", ".2-1", "1+"]
    print("\nCLs by files (rows) and reviewer threads per file (columns)")
    print(f"{'':>8}" + "".join(f"{x:>9}" for x in tl))
    for lo, hi, name in zip(fb, fb[1:], lab):
        s = [c["threads"] / c["files"] for c in m if lo <= c["files"] < hi]
        print(f"{name:>8}" + "".join(f"{sum(1 for x in s if a <= x < b):>9,}" for a, b in zip(tb, tb[1:])))


def as_printed(x, fmt):
    """x rounded as mechanical() and pipeline() print it (f"{x:{fmt}}"), as a
    number: the page's datasets were once copied from those tables."""
    s = f"{x:{fmt}}"
    return float(s[:-1]) / 100 if s.endswith("%") else int(s) if fmt == ".0f" else float(s)


def mechanical_datasets(cls):
    """The page's `mechanical_files` and `mechanical_repetition`: mechanical()'s
    first two tables as rows, rounded as printed."""
    m = [c for c in cls if c["status"] == "MERGED" and c["files"]]
    big = [c for c in m if c["files"] >= 10]
    rep = commit_store.repetition(git_db())
    reps = []
    rb = [0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.01]
    for lo, hi in zip(rb, rb[1:]):
        s = [c for c in big if (r := rep.get(c["sha"])) is not None and lo <= r < hi]
        if s:
            reps.append(dict(repetition=f"{lo:.1f}-{min(hi, 1):.1f}", cls=len(s),
                             with_thread=as_printed(sum(1 for c in s if c["threads"]) / len(s), ".0%"),
                             threads_per_cl=as_printed(st.mean(c["threads"] for c in s), ".2f"),
                             threads_per_file=as_printed(st.mean(c["threads"] / c["files"] for c in s), ".3f"),
                             median_files=as_printed(med([c["files"] for c in s]), ".0f")))
    files = []
    fb = [1, 2, 5, 10, 20, 50, 100, 200, 500, 10**9]
    lab = ["1", "2-4", "5-9", "10-19", "20-49", "50-99", "100-199", "200-499", "500+"]
    for lo, hi, name in zip(fb, fb[1:], lab):
        s = [c for c in m if lo <= c["files"] < hi]
        if not s:
            continue
        rev = sum(1 for c in s if c["reverted_at"] and c["reverted_at"] - c["closed_at"] < 30 * 86400)
        files.append(dict(files=name, cls=len(s),
                          with_thread=as_printed(sum(1 for c in s if c["threads"]) / len(s), ".0%"),
                          threads_per_cl=as_printed(st.mean(c["threads"] for c in s), ".2f"),
                          threads_per_file=as_printed(st.mean(c["threads"] / c["files"] for c in s), ".3f"),
                          lines_per_file=as_printed(med([(c["git_lines"] or 0) / c["files"] for c in s]), ".1f"),
                          reverted=as_printed(rev / len(s), ".2%")))
    return dict(mechanical_files=files, mechanical_repetition=reps)


# ---------------------------------------------------------------------- trends

def trends(cls, commits, ai):
    print("Git (human commits with a CL, main, by quarter)")
    print("quarter | commits | authors | commits/author/month | median lines | p90 lines | >=1000 lines "
          "| reverted<30d | reverts | relands | AI-marked")
    byq = defaultdict(list)
    for c in commits:
        if c["n"]:
            byq[quarter(c["at"])].append(c)
    for k in sorted(byq):
        s = byq[k]
        ok = [c for c in s if not c["is_revert"]]
        authors = len({c["email"] for c in s})
        rv = sum(1 for c in ok if c["reverted_at"] and c["reverted_at"] - c["at"] < 30 * 86400)
        print(f"{k} {len(s):>7,} {authors:>6,} {len(s) / authors / 3:6.2f} {med([c['lines'] for c in ok]):6.0f} "
              f"{q([c['lines'] for c in ok], .9):6.0f} {sum(1 for c in ok if c['lines'] >= 1000) / len(ok):6.1%} "
              f"{rv / len(ok):6.2%} {sum(c['is_revert'] for c in s):5} {sum(c['reland'] for c in s):5} "
              f"{sum(1 for c in s if c['sha'] in ai):5}")
    print("\nGerrit (merged human-owned CLs by close quarter)")
    print("quarter | CLs | reviewed | threads/CL | threads/100 lines | addressed/CL | rework uploads after review "
          "| lines changed after review / final | h to first review (p50, p75) | reviewer wait h (p50) "
          "| owner wait h (p50) | rounds (mean)")
    byq = defaultdict(list)
    for c in cls:
        if c["status"] == "MERGED" and c["closed_at"]:
            byq[quarter(c["closed_at"])].append(c)
    for k in sorted(byq):
        s = byq[k]
        rv = [c for c in s if c["threads"]]
        lines = sum((c["ins"] or 0) + (c["dels"] or 0) for c in s)
        idf = [c for c in rv if c["interdiff_status"] == "ok" and c["lines_final"]]
        ftr = [(c["first_review_at"] - c["sent_at"]) / 3600 for c in rv
               if c["first_review_at"] and c["sent_at"] and c["first_review_at"] >= c["sent_at"]]
        rw = [c["reviewer_wait_h"] for c in rv if c["reviewer_wait_h"] is not None]
        ow = [c["owner_wait_h"] for c in rv if c["owner_wait_h"] is not None]
        print(f"{k} {len(s):>6,} {len(rv) / len(s):5.0%} {st.mean(c['threads'] for c in s):5.2f} "
              f"{100 * sum(c['threads'] for c in s) / max(1, lines):5.2f} {st.mean(c['addressed'] for c in s):5.2f} "
              f"{st.mean(c['rework_after'] or 0 for c in rv):5.2f} "
              f"{sum(c['lines_changed'] for c in idf) / max(1, sum(c['lines_final'] for c in idf)):5.2f} "
              f"{q(ftr, .5):6.1f} {q(ftr, .75):6.1f} {q(rw, .5):6.1f} {q(ow, .5):6.1f} "
              f"{st.mean(c['rounds'] or 0 for c in rv):5.2f}")


# ---------------------------------------------------------------------- growth

def dir_of(path, depth):
    parts = path.split("/")[:-1]
    return "/".join(parts[:depth]) + "/" if parts else "(root)/"


def commit_dirs(depth=3):
    """{commit_id: (top dir by lines, frozenset of dirs)} from gfiles."""
    db = git_db()
    paths = dict(db.execute("SELECT path_id, path FROM paths"))
    cache, out, cur, acc = {}, {}, None, None

    def done():
        if cur is not None and acc:
            out[cur] = (max(acc, key=acc.get), frozenset(acc))
    for cid, pid, ins, dels in db.execute("SELECT commit_id, path_id, ins, dels FROM gfiles"):
        if cid != cur:
            done()
            cur, acc = cid, {}
        d = cache.get(pid)
        if d is None:
            d = cache[pid] = sys.intern(dir_of(paths[pid], depth))
        acc[d] = acc.get(d, 0) + max(ins, 0) + max(dels, 0) + 1
    done()
    return out


def commit_main_dirs(depth=3):
    """{commit_id: main directory at any depth}. Starts from the main
    `depth`-level directory of commit_dirs (same weights, same choice), then
    steps down into the subdirectory with the most lines for as long as it
    outweighs the files directly in the current directory."""
    db = git_db()
    paths = dict(db.execute("SELECT path_id, path FROM paths"))
    cache, out, cur, files = {}, {}, None, []

    def done():
        if cur is None or not files:
            return
        acc = {}
        for parts, w in files:
            d = dir_of_parts(parts, depth)
            acc[d] = acc.get(d, 0) + w
        top = max(acc, key=acc.get)
        here = next(p[:depth] for p, _ in files if dir_of_parts(p, depth) == top)
        if len(here) < depth:          # files directly in a shallower directory
            out[cur] = top
            return
        here = list(here)
        sub = [(p, w) for p, w in files if p[:depth] == tuple(here)]
        while True:
            k, acc = len(here), {}
            for p, w in sub:
                c = p[k] if len(p) > k else None
                acc[c] = acc.get(c, 0) + w
            best = max(acc, key=acc.get)
            if best is None:
                break
            here.append(best)
            sub = [(p, w) for p, w in sub if len(p) > k and p[k] == best]
        out[cur] = sys.intern("/".join(here) + "/")
    for cid, pid, ins, dels in db.execute("SELECT commit_id, path_id, ins, dels FROM gfiles"):
        if cid != cur:
            done()
            cur, files = cid, []
        parts = cache.get(pid)
        if parts is None:
            parts = cache[pid] = tuple(paths[pid].split("/")[:-1])
        files.append((parts, max(ins, 0) + max(dels, 0) + 1))
    done()
    return out


def dir_of_parts(parts, depth):
    """dir_of for a path already split into its directories."""
    return "/".join(parts[:depth]) + "/" if parts else "(root)/"


def size_bucket(lines):
    return 0 if lines < 10 else 1 if lines < 50 else 2 if lines < 250 else 3 if lines < 1000 else 4


MECH_FILES = 50   # provisional; see mechanical()


def expected_threads(cls, top2, ref=(2023, 2024)):
    """Mean reviewer threads per merged CL by (size bucket, top 2-level dir)
    over the reference years, falling back to the size bucket alone."""
    g, b = defaultdict(list), defaultdict(list)
    for c in cls:
        if c["status"] != "MERGED" or not c["closed_at"] or not (ref[0] <= year(c["closed_at"]) <= ref[1]):
            continue
        if (c["files"] or 0) >= MECH_FILES:
            continue
        k = size_bucket((c["ins"] or 0) + (c["dels"] or 0))
        g[(k, top2.get(c["change_number"]))].append(c["threads"])
        b[k].append(c["threads"])
    gm = {k: st.mean(v) for k, v in g.items() if len(v) >= 30}
    bm = {k: st.mean(v) for k, v in b.items()}
    return lambda c: gm.get((size_bucket((c["ins"] or 0) + (c["dels"] or 0)), top2.get(c["change_number"])),
                            bm[size_bucket((c["ins"] or 0) + (c["dels"] or 0))])


def tenure_band(months):
    return "0-1y" if months < 12 else "1-2y" if months < 24 else "2-4y" if months < 48 else "4-8y" \
        if months < 96 else "8y+"


def growth(cls, commits, first_commit):
    first = load_first(first_commit)
    print("loading directories ...", file=sys.stderr, flush=True)
    dirs3 = commit_dirs(3)
    by_cl_commit = {c["n"]: c for c in commits if c["n"]}
    top2 = {}
    for n, c in by_cl_commit.items():
        d = dirs3.get(c["cid"])
        if d:
            top2[n] = "/".join(d[0].split("/")[:2])
    exp = expected_threads(cls, top2)
    month = lambda t: (t - first_t) / (30.44 * 86400)

    # ---- learning curve: feedback index vs tenure and area familiarity, per era
    prior = defaultdict(Counter)          # email -> dir3 -> commits so far
    fam = {}                              # CL -> author's prior commits in its top dir3
    for c in sorted(commits, key=lambda c: c["at"]):
        d = dirs3.get(c["cid"])
        if not d:
            continue
        if c["n"]:
            fam[c["n"]] = prior[c["email"]][d[0]]
        for x in d[1]:
            prior[c["email"]][x] += 1
    era = lambda t: "pre-AI 2023H2-2024" if year(t) <= 2024 else ("2025" if year(t) == 2025 else "2026")
    tab = defaultdict(lambda: [0.0, 0.0, 0])
    tab_f = defaultdict(lambda: [0.0, 0.0, 0])
    for c in cls:
        if c["status"] != "MERGED" or not c["closed_at"] or (c["files"] or 0) >= MECH_FILES:
            continue
        e = c["owner_email"]
        if e not in first:
            continue
        first_t = first[e]
        tb = tenure_band(month(c["closed_at"]))
        x = tab[(era(c["closed_at"]), tb)]
        x[0] += c["threads"]
        x[1] += exp(c)
        x[2] += 1
        f = fam.get(c["change_number"])
        if f is not None:
            fb = "0" if f == 0 else "1-4" if f < 5 else "5-19" if f < 20 else "20-99" if f < 100 else "100+"
            y = tab_f[(era(c["closed_at"]), fb)]
            y[0] += c["threads"]
            y[1] += exp(c)
            y[2] += 1
    eras = ["pre-AI 2023H2-2024", "2025", "2026"]
    print("\nFeedback index (reviewer threads / expected for size and area; 1.00 = 2023-24 norm) by tenure")
    print(f"{'tenure':8}" + "".join(f"{e:>26}" for e in eras))
    for tb in ["0-1y", "1-2y", "2-4y", "4-8y", "8y+"]:
        print(f"{tb:8}" + "".join(f"{tab[(e, tb)][0] / max(1e-9, tab[(e, tb)][1]):>16.2f} ({tab[(e, tb)][2]:>6,})"
                                  for e in eras))
    print("\n... by the author's prior commits in the CL's main directory (3 levels)")
    for fb in ["0", "1-4", "5-19", "20-99", "100+"]:
        print(f"{fb:8}" + "".join(f"{tab_f[(e, fb)][0] / max(1e-9, tab_f[(e, fb)][1]):>16.2f} "
                                  f"({tab_f[(e, fb)][2]:>6,})" for e in eras))

    # ---- per person-year dimensions (git, 2017+)
    py = defaultdict(lambda: dict(commits=0, months=set(), lines=[], dirs=set(), new_dirs=0, reviews=0))
    seen_dirs = defaultdict(set)
    for c in sorted(commits, key=lambda c: c["at"]):
        if c["is_revert"]:
            continue
        y = year(c["at"])
        d = dirs3.get(c["cid"])
        if c["email"] in first:
            r = py[(c["email"], y)]
            r["commits"] += 1
            r["months"].add(datetime.fromtimestamp(c["at"], timezone.utc).month)
            r["lines"].append(c["lines"])
            if d:
                r["dirs"] |= d[1]
                r["new_dirs"] += len(d[1] - seen_dirs[c["email"]])
                seen_dirs[c["email"]] |= d[1]
        for rv in c["rb"]:
            if rv in first and rv != c["email"]:
                py[(rv, y)]["reviews"] += 1
    # feedback index per person-year (Gerrit, 2023H2+)
    rli = defaultdict(lambda: [0.0, 0.0, 0])
    for c in cls:
        if c["status"] == "MERGED" and c["closed_at"] and (c["files"] or 0) < MECH_FILES and c["owner_email"]:
            x = rli[(c["owner_email"], year(c["closed_at"]))]
            x[0] += c["threads"]
            x[1] += exp(c)
            x[2] += 1

    def dims(e, y):
        r = py.get((e, y))
        if not r or r["commits"] < 6:
            return None
        out = dict(velocity=r["commits"] / len(r["months"]), size=med(r["lines"]), breadth=len(r["dirs"]),
                   reviews=r["reviews"] / 12)
        x = rli.get((e, y))
        if x and x[2] >= 10 and x[1] > 0:
            out["independence"] = -math.log((x[0] + 0.5) / (x[1] + 0.5))
        return out

    # ---- reviewing growth by cohort
    print("\nReviews given (Reviewed-by footers) per month, median and share >= 5/month, by start-year cohort "
          "and tenure year")
    cohorts = defaultdict(lambda: defaultdict(list))
    for (e, y), r in py.items():
        fy = year(first[e])
        if fy < 2017 or r["commits"] < 6:
            continue
        cohorts[fy][y - fy].append(r["reviews"] / 12)
    print(f"{'cohort':7}" + "".join(f"{'year ' + str(k):>18}" for k in range(1, 8)))
    for fy in sorted(cohorts):
        print(f"{fy:<7}" + "".join(
            f"{med(cohorts[fy][k]):>6.1f} {sum(1 for v in cohorts[fy][k] if v >= 5) / max(1, len(cohorts[fy][k])):>4.0%}"
            f" ({len(cohorts[fy][k]):>4})" if cohorts[fy][k] else f"{'':>18}" for k in range(0, 7)))

    # ---- growth per person and year pair, against a pre-AI reference
    keys = ["velocity", "size", "breadth", "reviews", "independence"]
    changes = []   # (year pair start, tenure band, {dim: change})
    for (e, y) in list(py):
        a, b = dims(e, y), dims(e, y + 1)
        if not a or not b:
            continue
        ch = {}
        for k in keys:
            if k in a and k in b:
                if k == "independence":
                    ch[k] = b[k] - a[k]
                else:
                    ch[k] = math.log((b[k] + 1) / (a[k] + 1))
        tb = tenure_band((datetime(y, 12, 31, tzinfo=timezone.utc).timestamp() - first[e]) / (30.44 * 86400))
        changes.append((y, tb, ch))
    ref = defaultdict(lambda: defaultdict(list))
    for y, tb, ch in changes:
        if 2018 <= y <= 2022 or (y == 2023 and "independence" in ch):
            for k, v in ch.items():
                ref[tb][k].append(v)
    for tb in ref:
        for k in ref[tb]:
            ref[tb][k].sort()
    import bisect

    def pct(tb, k, v):
        xs = ref[tb].get(k)
        return bisect.bisect_left(xs, v) / len(xs) if xs and len(xs) >= 50 else None

    print("\nGrowth from one year to the next, against the 2018-22 reference at the same tenure "
          "(independence: 2023->24 reference).")
    print("A person-year 'grows' on a dimension if their change is above the reference's 75th percentile;")
    print("'low growth' = at or below the reference median on every dimension measured.")
    print(f"{'years':10} {'people':>7} {'low growth':>11} " + "".join(f"{k:>13}" for k in keys))
    agg = defaultdict(lambda: [0, 0, Counter(), Counter()])
    for y, tb, ch in changes:
        ps = {k: pct(tb, k, v) for k, v in ch.items()}
        ps = {k: v for k, v in ps.items() if v is not None}
        if not ps:
            continue
        a = agg[y]
        a[0] += 1
        a[1] += all(v <= 0.5 for v in ps.values())
        for k, v in ps.items():
            a[2][k] += v > 0.75
            a[3][k] += 1
    for y in sorted(agg):
        n, low, gr, den = agg[y]
        print(f"{y}->{y + 1:<4} {n:>7,} {low / n:>11.1%} " +
              "".join(f"{gr[k] / den[k]:>13.0%}" if den[k] else f"{'':>13}" for k in keys))
    print("\nSame, by tenure band (low-growth share)")
    agg2 = defaultdict(lambda: [0, 0])
    for y, tb, ch in changes:
        ps = [pct(tb, k, v) for k, v in ch.items()]
        ps = [v for v in ps if v is not None]
        if ps:
            agg2[(y, tb)][0] += 1
            agg2[(y, tb)][1] += all(v <= 0.5 for v in ps)
    bands = ["0-1y", "1-2y", "2-4y", "4-8y", "8y+"]
    print(f"{'years':10}" + "".join(f"{b:>16}" for b in bands))
    for y in sorted(agg):
        print(f"{y}->{y + 1:<4}" + "".join(
            f"{agg2[(y, b)][1] / agg2[(y, b)][0]:>8.0%} ({agg2[(y, b)][0]:>5})" if agg2[(y, b)][0] else f"{'':>16}"
            for b in bands))


# -------------------------------------------------------------------- pipeline

def yrs(a, b):
    return (b - a) / (365.25 * 86400)


def pipeline_people(commits, first_commit=None, owners_added=None):
    """pipeline()'s inputs: first commit and first OWNERS addition per person,
    commits authored and reviews given per person and year, and each regular
    reviewer's first year with >= 60 reviews."""
    first = load_first(first_commit)
    owner_at = {}
    for t, e, _ in load_owners_added(owners_added):
        e = person(e)
        if e in first:
            owner_at[e] = min(t, owner_at.get(e, t))
    given = defaultdict(Counter)
    authored = defaultdict(Counter)
    for c in commits:
        y = year(c["at"])
        authored[c["email"]][y] += 1
        for r in c["rb"]:
            if r != c["email"]:
                given[r][y] += 1
    became_reviewer = {e: min(y for y, n in g.items() if n >= 60) for e, g in given.items()
                       if any(n >= 60 for n in g.values()) and e in first}
    return first, owner_at, authored, became_reviewer


def pipeline_new_people(first, owner_at, authored, became_reviewer):
    """The page's `pipeline`: new authors, regular reviewers and OWNERS per
    year (pipeline()'s second table, rounded as printed)."""
    rows = []
    for y in range(2017, 2027):
        no = [e for e, t in owner_at.items() if year(t) == y]
        p50 = med([yrs(first[e], owner_at[e]) for e in no])
        rows.append(dict(year=y, new_authors=sum(1 for e, t in first.items() if year(t) == y and authored[e][y] >= 5),
                         new_regular_reviewers=sum(1 for yy in became_reviewer.values() if yy == y),
                         new_owners=len(no), owner_tenure_p50=None if math.isnan(p50) else as_printed(p50, ".1f")))
    return rows


def pipeline(commits, first_commit, owners_added):
    """Experts training newcomers who become experts: who reviews newcomers,
    and how many people become reviewers and OWNERS, by start-year cohort."""
    first, owner_at, authored, became_reviewer = pipeline_people(commits, first_commit, owners_added)

    print("Who reviews newcomers' CLs (author in their first year), by year: Reviewed-by reviewers'")
    print("tenure and whether they were in an OWNERS file at the time")
    print("year | newcomer CLs | reviewer tenure p50 (y) | reviewer <5y tenure | reviewer an OWNER | "
          "newcomer CLs/newcomer | reviews per newcomer CL")
    for y in range(2017, 2027):
        s = [c for c in commits if year(c["at"]) == y and c["email"] in first
             and yrs(first[c["email"]], c["at"]) < 1 and not c["is_revert"]]
        rv = [(r, c["at"]) for c in s for r in c["rb"] if r in first and r != c["email"]]
        if not s:
            continue
        ten = [yrs(first[r], t) for r, t in rv]
        own = sum(1 for r, t in rv if owner_at.get(r, 1e18) <= t)
        newcomers = {c["email"] for c in s}
        print(f"{y} {len(s):>7,} {med(ten):>6.1f} {sum(1 for x in ten if x < 5) / max(1, len(ten)):>6.0%} "
              f"{own / max(1, len(rv)):>6.0%} {len(s) / len(newcomers):>6.1f} {len(rv) / len(s):>5.2f}")

    print("\nNew authors, reviewers and OWNERS per year (people)")
    print("year | new authors (>=5 CLs that year) | new regular reviewers (first year >=60 reviews) "
          "| first added to an OWNERS file | median tenure of new OWNERS (y)")
    for y in range(2017, 2027):
        na = sum(1 for e, t in first.items() if year(t) == y and authored[e][y] >= 5)
        nr = sum(1 for e, yy in became_reviewer.items() if yy == y)
        no = [e for e, t in owner_at.items() if year(t) == y]
        print(f"{y} {na:>6,} {nr:>6,} {len(no):>6,} {med([yrs(first[e], owner_at[e]) for e in no]):>6.1f}")

    print("\nCohorts: of people who started in year Y and authored >= 20 CLs, share who within N years")
    print("became a regular reviewer (>=60 reviews in a year) / were added to an OWNERS file")
    print(f"{'cohort':7} {'people':>7}" + "".join(f"{'<=' + str(k) + 'y':>14}" for k in (1, 2, 3, 5)))
    for fy in range(2017, 2026):
        ppl = [e for e, t in first.items() if year(t) == fy and sum(authored[e].values()) >= 20]
        if not ppl:
            continue
        cells = []
        for k in (1, 2, 3, 5):
            if fy + k > 2026:
                cells.append(f"{'':>14}")
                continue
            r = sum(1 for e in ppl if e in became_reviewer and became_reviewer[e] - fy < k)
            o = sum(1 for e in ppl if e in owner_at and yrs(first[e], owner_at[e]) <= k)
            cells.append(f"{r / len(ppl):>6.0%} /{o / len(ppl):>5.0%}")
        print(f"{fy:<7} {len(ppl):>7,}" + "".join(cells))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["trends", "mechanical", "growth", "pipeline"])
    ap.add_argument("--owners-added", help="default: commits.sqlite")
    ap.add_argument("--first-commit", help="default: commits.sqlite")
    ap.add_argument("--ai-marked", help="default: commits.sqlite")
    a = ap.parse_args()
    if a.what == "mechanical":
        mechanical(load_cl())
    elif a.what == "trends":
        trends(load_cl(), load_commits(), load_ai_marked(a.ai_marked))
    elif a.what == "pipeline":
        pipeline(load_commits(), a.first_commit, a.owners_added)
    else:
        growth(load_cl(), load_commits(), a.first_commit)


if __name__ == "__main__":
    main()
