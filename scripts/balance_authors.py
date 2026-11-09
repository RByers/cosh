"""Per-author breadth and review load over the last year, for the Review
Balance page's "Authors in the last year" section (docs/balance.md): a
histogram of distinct directories touched per author, and a scatter of one
dot per author (directories, review load index, tenure, CLs landed).

Unlike the other balance scripts this writes one row per person, with their
commit email, to summaries/balance_authors.json. That is published: it comes
from public Chromium git and Gerrit data (ground rule 3 of docs/plan.md), and
the review load index is not tone.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_authors.py \
      --first-commit F --owners-added O --mech M [summaries/balance_authors.json]

The year is 2025-11-01 .. 2026-11-01 (the data ends in October 2026).
- CLs landed: commits on main with a CL in the year, reverts and mechanical
  CLs aside.
- Directories: distinct 3-level directories over those commits' files.
- Review load index: reviewer threads on the author's merged, non-mechanical
  CLs closed in the year ÷ the sum of the 2023–24 means for each CL's size and
  directory (the page's load index, pooled per author).
- Tenure: years from the first commit on main (all history) to the year's end.
Authors need MIN_CLS CLs landed to appear; the histogram uses the same people.
"""

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402
from balance_report import mech_set  # noqa: E402
from cosh import balance  # noqa: E402

START = datetime(2025, 11, 1, tzinfo=timezone.utc).timestamp()
END = G.CENSOR                      # 2026-11-01, end of data
MIN_CLS = 10                        # CLs landed in the year to be shown
MIN_EXPECTED = 2.0                  # expected threads needed for a load index


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
            cnt[ids.find(e)][e] += 1
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
            load=round(threads[p] / e, 3) if e >= MIN_EXPECTED else None,
            tenure=round((END - t0) / G.YEAR, 2) if t0 is not None and t0 < END else None))
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
    both = [r for r in rows if r["load"] is not None]
    return dict(authors=len(rows), dirs_p50=q(0.5), dirs_p90=q(0.9), dirs_100=sum(d >= 100 for d in ds),
                rho_dirs_load=round(spearman([r["dirs"] for r in both], [r["load"] for r in both]), 2),
                rho_dirs_cls=round(spearman([r["dirs"] for r in rows], [r["cls"] for r in rows]), 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="summaries/balance_authors.json")
    ap.add_argument("--first-commit", required=True)
    ap.add_argument("--owners-added", required=True)
    ap.add_argument("--ai-marked")
    ap.add_argument("--mech", required=True)
    args = ap.parse_args()
    rows = compute(args)
    summ = summary(rows)
    print(summ, f"load missing {sum(r['load'] is None for r in rows)}, "
          f"tenure missing {sum(r['tenure'] is None for r in rows)}", file=sys.stderr)
    data = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                start="2025-11-01", end="2026-10-31", min_cls=MIN_CLS, summary=summ,
                columns=["email", "cls", "dirs", "load", "tenure"],
                authors=[[r[k] for k in ("email", "cls", "dirs", "load", "tenure")] for r in rows])
    with open(args.path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")


if __name__ == "__main__":
    main()
