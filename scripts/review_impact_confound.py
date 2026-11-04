"""Owner-habit confound, attribution rounds and same-org review for the thread
records of scripts/review_impact.py (docs/review-impact.md).

  python3 scripts/review_impact_confound.py threads.jsonl
"""

import collections
import json
import random
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from review_impact_stats import reply_class  # noqa: E402


def corr(xs, ys):
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    c = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    v = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** .5
    return c / v if v else float("nan")


def main(path):
    rs = [json.loads(line) for line in open(path)]
    for r in rs:
        r["rc"] = reply_class(r["owner_reply"])
        r["done"] = r["rc"] == "done"
    act = [r for r in rs if r["root_unresolved"]]

    # 1. Owner habit. Owners differ in whether they type "Done" at all.
    by_owner = collections.defaultdict(list)
    for r in act:
        by_owner[r["owner"]].append(r)
    big = {o: v for o, v in by_owner.items() if len(v) >= 20}
    rates = sorted(sum(r["done"] for r in v) / len(v) for v in big.values())
    q = lambda p: rates[int(p * (len(rates) - 1))]
    print(f"owners with >=20 actionable threads: {len(big)}; Done-rate p10 {q(.1):.2f} p25 {q(.25):.2f} "
          f"median {q(.5):.2f} p75 {q(.75):.2f} p90 {q(.9):.2f}")
    never = sum(1 for v in big.values() if sum(r["done"] for r in v) == 0)
    print(f"  owners who never reply Done-type: {never} ({100 * never / len(big):.1f}%)")

    # Leave-reviewer-out owner propensity, then reviewer residuals.
    def owner_prop(r):
        v = [x["done"] for x in by_owner[r["owner"]] if x["reviewer"] != r["reviewer"]]
        return sum(v) / len(v) if len(v) >= 5 else None
    by_rev = collections.defaultdict(list)
    for r in act:
        p = owner_prop(r)
        if p is not None:
            by_rev[r["reviewer"]].append((r["done"], p))
    revs = {k: v for k, v in by_rev.items() if len(v) >= 40}
    raw = [sum(d for d, _ in v) / len(v) for v in revs.values()]
    exp = [sum(p for _, p in v) / len(v) for v in revs.values()]
    print(f"reviewers with >=40 scored threads: {len(revs)}")
    print(f"  corr(reviewer Done-rate, mean owner propensity on their CLs) = {corr(raw, exp):.2f}")
    sd = lambda xs: (sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / len(xs)) ** .5
    res = [a - b for a, b in zip(raw, exp)]
    print(f"  sd raw Done-rate {sd(raw):.3f}; sd expected-from-owners {sd(exp):.3f}; sd residual {sd(res):.3f}")
    random.seed(2)
    xs, ys = [], []
    for v in revs.values():
        v = v[:]
        random.shuffle(v)
        h1, h2 = v[0::2], v[1::2]
        xs.append(sum(d - p for d, p in h1) / len(h1))
        ys.append(sum(d - p for d, p in h2) / len(h2))
    print(f"  split-half corr of owner-adjusted residual = {corr(xs, ys):.2f}")

    # 2. Attribution rounds: Done replies grouped by the rework upload nearest them.
    rounds = collections.defaultdict(set)
    for r in rs:
        if r["done"] and r["reply_upload_ps"] is not None and abs(r["reply_t"] - [u[1] for u in r["uploads"] if u[0] == r["reply_upload_ps"]][0]) <= 3600:
            rounds[(r["cl"], r["reply_upload_ps"])].add(r["reviewer"])
    dist = collections.Counter(min(len(v), 4) for v in rounds.values())
    tot = sum(dist.values())
    print(f"rework uploads with Done replies within 1 h: {tot}; distinct reviewers addressed: " +
          ", ".join(f"{k}{'+' if k == 4 else ''}: {100 * n / tot:.1f}%" for k, n in sorted(dist.items())))
    # rework uploads after the first review with no Done/addressed thread at all
    cl_up = {}
    first_review = {}
    for r in rs:
        cl_up[r["cl"]] = r["uploads"]
        first_review[r["cl"]] = min(first_review.get(r["cl"], 1e18), r["root_t"])
    after = [(cl, u[0]) for cl, ups in cl_up.items() for u in ups if u[2] == "rework" and u[1] > first_review[cl]]
    with_done = set(rounds)
    print(f"rework uploads after a CL's first review: {len(after)}; with a Done reply within 1 h: "
          f"{100 * sum(k in with_done for k in after) / len(after):.1f}%")
    ups = [len([u for u in ups if u[2] == 'rework']) for ups in cl_up.values()]
    print(f"rework uploads per reviewed CL: mean {sum(ups) / len(ups):.2f}")
    kinds = collections.Counter(u[2] for ups in cl_up.values() for u in ups)
    print(f"upload kinds: {dict(kinds)}")

    # 3. Same-org review
    so = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in act:
        b = so[r["org"]]
        same = r["org"] == r["owner_org"]
        b[0 if same else 2] += 1
        b[1 if same else 3] += r["done"]
    print("actionable threads by reviewer org: same-org owner (Done-rate) | other-org owner (Done-rate)")
    for org, b in sorted(so.items(), key=lambda kv: -(kv[1][0] + kv[1][2]))[:8]:
        print(f"  {org:18s} {b[0]:6d} ({b[1] / max(b[0], 1):.2f}) | {b[2]:6d} ({b[3] / max(b[2], 1):.2f})")


if __name__ == "__main__":
    main(sys.argv[1])
