"""Per-author breadth and feedback index over the last year, for the Review
Balance page's "Authors in the last year" section (docs/balance.md): a
histogram of distinct directories touched per author, and a scatter of one
dot per author (directories, feedback index, tenure, CLs landed). The
summary also holds abandonment after review against tenure, which the page
quotes in "Wrong turns" (tenure barely predicts it).

Unlike the other balance scripts this gives one row per person, with their
commit email, for summaries/balance_authors.json (written by `python3 -m
cosh.balance_publish`, which calls document()). That is published: it comes
from public Chromium git and Gerrit data (ground rule 3 of docs/plan.md), and
the feedback index is not tone.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_authors.py --out F

The year is the one before balance_publish.DATA_END: 2025-11-01 ..
2026-11-01 (the data ends in October 2026).
- CLs landed: commits on main with a CL in the year, reverts and mechanical
  CLs aside.
- Directories: distinct 3-level directories over those commits' files.
- Feedback index: reviewer threads on the author's merged, non-mechanical
  CLs closed in the year ÷ the sum of the 2023–24 means for each CL's size and
  directory (the page's feedback index, pooled per author).
- Tenure: years from the first commit on main (all history) to the year's end.
- Abandonment (summary only): of the author's non-mechanical CLs closed
  (merged or abandoned) in the year with a first substantive review before
  closing (an inline reviewer comment, or a reviewer thread the owner
  answered), the share abandoned, for authors with MIN_REVIEWED or more.
Authors need MIN_CLS CLs landed to appear; the histogram uses the same people.
"""

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402
from balance_report import mech_set  # noqa: E402
from cosh import balance  # noqa: E402
from cosh.balance_publish import DATA_END  # noqa: E402

END_DAY = DATA_END                  # 2026-11-01, end of data
START_DAY = END_DAY.replace(year=END_DAY.year - 1)
START, END = START_DAY.timestamp(), END_DAY.timestamp()
MIN_CLS = 10                        # CLs landed in the year to be shown
MIN_EXPECTED = 2.0                  # expected threads needed for a feedback index
MIN_REVIEWED = 10                   # reviewed CLs closed in the year for an abandon rate


def raw_emails(ids):
    """{person id: the commit author address they used most in the year}, as written (not merged)."""
    db = A.ro(balance.db_path("git"))
    cnt = defaultdict(Counter)
    for e, bot in db.execute("SELECT author_email, is_bot FROM gcommits WHERE change_number IS NOT NULL "
                             "AND landed_at >= ? AND landed_at < ?", (START, END)):
        if not bot and not A.is_bot_email(e):
            e = e.lower()
            if e.count("@") > 1:
                e = e.rsplit("@", 1)[0]
            cnt[ids.find(A.person(e))][e] += 1
    return {p: c.most_common(1)[0][0] for p, c in cnt.items()}


def compute(args):
    cls, commits, ids, first, owner_at, ai = G.load_all(args)
    mech = mech_set(args.mech)
    dirs3 = A.commit_dirs(3)
    top2 = {}
    for c in commits:
        d = dirs3.get(c["cid"])
        if c["n"] and d:
            top2[c["n"]] = "/".join(d[0].split("/")[:2])

    landed, dirs = Counter(), defaultdict(set)
    for c in commits:
        if not c["n"] or c["is_revert"] or c["n"] in mech or not (START <= c["at"] < END):
            continue
        landed[c["pid"]] += 1
        d = dirs3.get(c["cid"])
        if d:
            dirs[c["pid"]] |= d[1]

    A.MECH_FILES = 10 ** 9          # mechanical CLs come from the --mech list instead
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    reviewed, abandoned = Counter(), Counter()
    for c in cls:
        if (c["pid"] and c["status"] in ("MERGED", "ABANDONED") and c["closed_at"]
                and START <= c["closed_at"] < END and c["first_review_at"]
                and c["first_review_at"] <= c["closed_at"]):
            reviewed[c["pid"]] += 1
            abandoned[c["pid"]] += c["status"] == "ABANDONED"
    threads, expected = Counter(), Counter()
    for c in G.cl_residuals(cls, top2):
        if START <= c["closed_at"] < END:
            threads[c["pid"]] += c["threads"]
            expected[c["pid"]] += c["exp24"]

    email = raw_emails(ids)
    out = []
    for p, n in landed.items():
        if n < MIN_CLS or p not in email:
            continue
        t0 = first.get(p)
        e = expected[p]
        out.append(dict(
            email=email[p], cls=n, dirs=len(dirs[p]),
            feedback=round(threads[p] / e, 3) if e >= MIN_EXPECTED else None,
            tenure=round((END - t0) / G.YEAR, 2) if t0 is not None and t0 < END else None,
            reviewed=reviewed[p], abandoned=abandoned[p]))
    out.sort(key=lambda r: r["email"])
    return out


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(xs, ys):
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return sxy / math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))


def summary(rows):
    ds = sorted(r["dirs"] for r in rows)
    q = lambda p: ds[min(len(ds) - 1, int(p * len(ds)))]
    both = [r for r in rows if r["feedback"] is not None]
    ab = [r for r in rows if r["reviewed"] >= MIN_REVIEWED and r["tenure"] is not None]
    rate = lambda r: r["abandoned"] / r["reviewed"]
    rates = sorted(rate(r) for r in ab)
    band = lambda lo, hi: sorted(rate(r) for r in ab if lo <= r["tenure"] < hi)
    medr = lambda xs: round(xs[len(xs) // 2], 4) if xs else None
    abandon = dict(
        abandon_authors=len(ab),
        abandon_pooled=round(sum(r["abandoned"] for r in ab) / sum(r["reviewed"] for r in ab), 4),
        abandon_p50=medr(rates), abandon_p90=round(rates[int(0.9 * len(rates))], 4),
        abandon_zero=sum(r["abandoned"] == 0 for r in ab),
        abandon_p50_under2=medr(band(0, 2)), abandon_p50_10plus=medr(band(10, 1e9)),
        rho_tenure_abandon=round(spearman([r["tenure"] for r in ab], [rate(r) for r in ab]), 2))
    return dict(**abandon, authors=len(rows), dirs_p50=q(0.5), dirs_p90=q(0.9), dirs_100=sum(d >= 100 for d in ds),
                rho_dirs_feedback=round(spearman([r["dirs"] for r in both], [r["feedback"] for r in both]), 2),
                rho_dirs_cls=round(spearman([r["dirs"] for r in rows], [r["cls"] for r in rows]), 2))


COLUMNS = ["email", "cls", "dirs", "feedback", "tenure"]


def document(args):
    """summaries/balance_authors.json's content."""
    rows = compute(args)
    summ = summary(rows)
    print(summ, f"feedback missing {sum(r['feedback'] is None for r in rows)}, "
          f"tenure missing {sum(r['tenure'] is None for r in rows)}", file=sys.stderr)
    return dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                start=START_DAY.strftime("%Y-%m-%d"), end=(END_DAY - timedelta(days=1)).strftime("%Y-%m-%d"),
                min_cls=MIN_CLS, min_reviewed=MIN_REVIEWED, summary=summ,
                columns=COLUMNS, authors=[[r[k] for k in COLUMNS] for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-commit", help="default: commits.sqlite")
    ap.add_argument("--owners-added", help="default: commits.sqlite")
    ap.add_argument("--ai-marked", help="default: commits.sqlite")
    ap.add_argument("--mech", help="default: commits.sqlite")
    ap.add_argument("--out", required=True, help="where to write the file (the page's copy: "
                    "python3 -m cosh.balance_publish)")
    args = ap.parse_args()
    data = document(args)
    with open(args.out, "w") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")


if __name__ == "__main__":
    main()
