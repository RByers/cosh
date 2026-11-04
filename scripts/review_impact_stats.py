"""Aggregate the thread records from scripts/review_impact.py (docs/review-impact.md).

  python3 scripts/review_impact_stats.py threads.jsonl
"""

import collections
import json
import re
import sys

DONE = re.compile(r"^\W*(done|fixed|fix(ed)? (it|this)|updated|removed|changed|added|renamed|moved|deleted|"
                  r"reverted|replaced|switched|applied|refactored|good (catch|call|point|idea)|nice catch|"
                  r"great (catch|point|idea)|thanks?( you)?[,.!]* *(done|fixed|updated)|"
                  r"ok[,.!]* *(done|fixed|updated))\b", re.I)
ACK = re.compile(r"^\W*(ack|acknowledged|noted|ok|okay|sure|thanks?( you)?|ty)\W*$", re.I)
LATER = re.compile(r"follow[- ]?up|separate cl|future cl|later cl|another cl|next cl|\btodo\b|crbug|\bb/\d+", re.I)
NIT = re.compile(r"^\W*(nit|optional|opt|super ?nit)\b", re.I)
APPROVAL = re.compile(r"^\W*(lgtm|lgmt|looks good|thanks|thank you|ty|\+1|l?gtm)\b", re.I)


def reply_class(msg):
    if msg is None:
        return "none"
    m = msg.strip()
    if DONE.match(m):
        return "done"
    if ACK.match(m):
        return "ack"
    if LATER.search(m):
        return "later"
    return "discussion"


def pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "  -  "


def main(path):
    rs = [json.loads(line) for line in open(path)]
    print(f"{len(rs)} reviewer-started threads on {len({r['cl'] for r in rs})} CLs")
    for r in rs:
        r["rc"] = reply_class(r["owner_reply"])
        r["rework"] = r["rework_after"] > 0
        r["near"] = r["reply_upload_gap"] is not None and r["reply_upload_gap"] <= 3600
        r["nit"] = bool(NIT.match(r["root_msg"]))
        r["approval"] = bool(APPROVAL.match(r["root_msg"])) and r["file"] == "/PATCHSET_LEVEL"
    total = len(rs)

    print("\n## Root comment kinds")
    for k, f in [("posted unresolved", lambda r: r["root_unresolved"]),
                 ("patchset-level", lambda r: r["file"] == "/PATCHSET_LEVEL"),
                 ("patchset-level approval/thanks", lambda r: r["approval"]),
                 ("nit/optional prefix", lambda r: r["nit"]),
                 ("has suggested fix (fixSuggestions)", lambda r: r["root_fix"]),
                 ("```suggestion block", lambda r: "```suggestion" in r["root_msg"]),
                 ("self-declared AI", lambda r: r["root_ai"]),
                 ("in path scope", lambda r: r["in_scope"])]:
        n = sum(map(f, rs))
        print(f"  {k:38s} {n:7d} {pct(n, total)}")

    print("\n## Owner's first reply x code-changing upload after the root comment")
    print(f"  {'reply':12s} {'threads':>8s} {'share':>7s} {'rework after':>13s} {'rework <=1h of reply':>21s}")
    for rc in ["done", "ack", "later", "discussion", "none"]:
        g = [r for r in rs if r["rc"] == rc]
        print(f"  {rc:12s} {len(g):8d} {pct(len(g), total)} {pct(sum(r['rework'] for r in g), len(g)):>13s}"
              f" {pct(sum(r['near'] for r in g), len(g)):>21s}")

    print("\n## Same, unresolved non-approval roots only (actionable requests)")
    act = [r for r in rs if r["root_unresolved"] and not r["approval"]]
    for rc in ["done", "ack", "later", "discussion", "none"]:
        g = [r for r in act if r["rc"] == rc]
        print(f"  {rc:12s} {len(g):8d} {pct(len(g), len(act))} {pct(sum(r['rework'] for r in g), len(g)):>13s}"
              f" {pct(sum(r['near'] for r in g), len(g)):>21s}")
    print(f"  no rework upload ever followed: {pct(sum(not r['rework'] for r in act), len(act))} of actionable threads")

    print("\n## Exact quick-reply texts among owner first replies (top 15)")
    c = collections.Counter((r["owner_reply"] or "").strip() for r in rs if r["owner_reply"])
    for t, n in c.most_common(15):
        print(f"  {n:6d} {t[:50]!r}")

    # Per org: share of comments vs share of 'probably led to change' threads.
    print("\n## Per org, in-scope threads: share of threads vs share of changed-code threads")

    def led(r):  # a cheap proxy: Done-type reply, or a rework upload within 1 h of the reply
        return r["rc"] == "done" or (r["near"] and r["rc"] not in ("ack",))
    sc = [r for r in rs if r["in_scope"]]
    tot_t, tot_l = len(sc), sum(map(led, sc))
    by = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in sc:
        b = by[r["org"]]
        b[0] += 1
        b[1] += led(r)
        b[2] += r["n_reviewer_comments"]
        b[3] += r["rc"] == "done"
    tot_c = sum(b[2] for b in by.values())
    print(f"  {'org':22s} {'comments':>9s} {'c-share':>8s} {'threads':>8s} {'led':>6s} {'led-rate':>8s} {'led-share':>9s}")
    for org, b in sorted(by.items(), key=lambda kv: -kv[1][2])[:14]:
        print(f"  {org:22s} {b[2]:9d} {pct(b[2], tot_c):>8s} {b[0]:8d} {b[1]:6d} {pct(b[1], b[0]):>8s} {pct(b[1], tot_l):>9s}")
    ng_c = sum(b[2] for o, b in by.items() if o != "google.com")
    ng_l = sum(b[1] for o, b in by.items() if o != "google.com")
    print(f"  non-Google share: comments {pct(ng_c, tot_c)}, led-to-change threads {pct(ng_l, tot_l)}")

    # Per reviewer stability: led-rate in two random halves of their threads.
    print("\n## Per reviewer led-rate (reviewers with >= 40 threads)")
    per = collections.defaultdict(list)
    for r in rs:
        per[r["reviewer"]].append(led(r))
    big = {k: v for k, v in per.items() if len(v) >= 40}
    rates = sorted(sum(v) / len(v) for v in big.values())
    if rates:
        q = lambda p: rates[int(p * (len(rates) - 1))]
        print(f"  {len(big)} reviewers; led-rate p10 {q(.1):.2f}, p25 {q(.25):.2f}, median {q(.5):.2f},"
              f" p75 {q(.75):.2f}, p90 {q(.9):.2f}")
        # split-half reliability
        xs, ys = [], []
        for v in big.values():
            xs.append(sum(v[0::2]) / len(v[0::2]))
            ys.append(sum(v[1::2]) / len(v[1::2]))
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs) ** .5
        vy = sum((y - my) ** 2 for y in ys) ** .5
        if vx and vy:
            print(f"  split-half correlation of led-rate: {cov / (vx * vy):.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
