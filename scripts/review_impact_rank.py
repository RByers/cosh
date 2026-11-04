"""How a 'led to a change' metric would move org shares and reviewer ranks,
compared with the comment count (docs/review-impact.md).

  python3 scripts/review_impact_rank.py threads.jsonl
"""

import collections
import json
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from review_impact_stats import reply_class  # noqa: E402

AI_FWD = re.compile(r"reported by|autoreview|ai review|ai-assisted|ai assisted|\[🤖\]|bot review|"
                    r"code review agent|gemini", re.I)


def ranks(d):
    order = sorted(d, key=lambda k: -d[k])
    return {k: i for i, k in enumerate(order)}


def spearman(a, b, keys):
    ra, rb = ranks({k: a.get(k, 0) for k in keys}), ranks({k: b.get(k, 0) for k in keys})
    n = len(keys)
    return 1 - 6 * sum((ra[k] - rb[k]) ** 2 for k in keys) / (n * (n * n - 1))


def main(path):
    rs = [json.loads(line) for line in open(path)]
    for r in rs:
        r["rc"] = reply_class(r["owner_reply"])
    sc = [r for r in rs if r["in_scope"]]

    # Org shares in scope under three measures.
    m = collections.defaultdict(lambda: collections.Counter())
    for r in sc:
        m[r["org"]]["comments"] += r["n_reviewer_comments"]
        m[r["org"]]["threads"] += 1
        m[r["org"]]["done"] += r["rc"] == "done"
        m[r["org"]]["actionable"] += r["root_unresolved"]
    tot = collections.Counter()
    for c in m.values():
        tot.update(c)
    print("in-scope shares       comments  threads  actionable  done-threads")
    for org in sorted(m, key=lambda o: -m[o]["comments"])[:7]:
        print(f"  {org:18s} " + "  ".join(f"{100 * m[org][k] / tot[k]:7.2f}%" for k in
                                          ("comments", "threads", "actionable", "done")))
    ng = {k: sum(c[k] for o, c in m.items() if o != "google.com") / tot[k] for k in tot}
    print("  non-Google        " + "  ".join(f"{100 * ng[k]:7.2f}%" for k in ("comments", "threads", "actionable", "done")))

    # Reviewer ranks (all paths).
    com, done = collections.Counter(), collections.Counter()
    for r in rs:
        com[r["reviewer"]] += r["n_reviewer_comments"]
        done[r["reviewer"]] += r["rc"] == "done"
    top = [k for k, _ in com.most_common(200)]
    print(f"\nreviewers: {len(com)}; Spearman(comments, done-threads) over the top 200 by comments: "
          f"{spearman(com, done, top):.2f}")
    t50c = {k for k, _ in com.most_common(50)}
    t50d = {k for k, _ in done.most_common(50)}
    print(f"  top-50 overlap between the two rankings: {len(t50c & t50d)}/50")
    ratio = sorted(done[k] / com[k] for k in top)
    print(f"  done-threads per comment among the top 200: p10 {ratio[20]:.2f} median {ratio[100]:.2f} p90 {ratio[180]:.2f}")

    # Suggested edits.
    sug = [r for r in rs if "```suggestion" in r["root_msg"] or r["root_fix"]]
    fa = sum((r["owner_reply"] or "").strip() == "Fix applied." for r in sug)
    print(f"\nthreads with a suggested edit: {len(sug)} ({100 * len(sug) / len(rs):.1f}%); "
          f"Done-type reply {100 * sum(r['rc'] == 'done' for r in sug) / len(sug):.0f}%, "
          f"'Fix applied.' {fa}")

    # AI findings forwarded by humans.
    fwd = [r for r in rs if AI_FWD.search(r["root_msg"]) or r["root_ai"]]
    print(f"threads whose root is AI-generated or forwards an AI finding: {len(fwd)} ({100 * len(fwd) / len(rs):.1f}%),"
          f" Done-type {100 * sum(r['rc'] == 'done' for r in fwd) / len(fwd):.0f}% vs "
          f"{100 * sum(r['rc'] == 'done' for r in rs) / len(rs):.0f}% overall")

    # Nits.
    nit = [r for r in rs if re.match(r"^\W*(nit|optional|super ?nit)\b", r["root_msg"], re.I)]
    print(f"nit/optional threads: {len(nit)} ({100 * len(nit) / len(rs):.1f}%), "
          f"{100 * sum(r['rc'] == 'done' for r in nit) / max(len(nit), 1):.0f}% Done-type; "
          f"they are {100 * sum(r['rc'] == 'done' for r in nit) / sum(r['rc'] == 'done' for r in rs):.0f}% of all Done threads")

    # Abandonment after review.
    cl = {}
    for r in rs:
        cl.setdefault(r["cl"], r["status"])
    ab = sum(s == "ABANDONED" for s in cl.values())
    print(f"\nreviewed CLs: {len(cl)}; abandoned {ab} ({100 * ab / len(cl):.1f}%)")


if __name__ == "__main__":
    main(sys.argv[1])
