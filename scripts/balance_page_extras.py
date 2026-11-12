"""The growth-signal, activity-pattern and security-fix datasets of
summaries/balance.json (the Review Balance page). `python3 -m
cosh.balance_publish` calls these functions.

Inputs are aggregate outputs of other scripts, all in $COSH_DATA_DIR:
  (signals)                        scripts/balance_signals.py (compute, or report --out)
  balance_clusters/clusters.json   scripts/balance_clusters.py
  balance_clusters/map.json        scripts/balance_cluster_map.py
  chrome_releases/summary.json     scripts/chrome_releases.py join

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_page_extras.py \
      [--signals signals.json] [--out datasets.json]

Nothing here names a person: clusters.json's "aggregate" block holds shares
only, map.json holds binned counts (cells of 5+ person-halves), ellipses and
rule agreement, and people.json (per person) is never read.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cosh import store  # noqa: E402
from cosh.balance_publish import show  # noqa: E402

WINDOWS = {"2019H1-2020H2": "2019–20 → a year later", "2021H1-2023H1": "2021–23 → a year later",
           "2024H1-2024H2": "2024 → 2025", "2025H1": "2025 H1 → 2026 H1"}

PANEL = [
    # key in signals.json panels, side, label, raw format
    ("reviewer_log1p_threads", "reviewer", "Threads started per review"),
    ("reviewer_neg_vote", "reviewer", "−1/−2 vote rate"),
    ("author_log1p_threads_received", "author", "Threads received per CL"),
    ("author_rounds", "author", "Review rounds"),
    ("author_interdiff_share", "author", "Share of lines changed after review"),
    ("author_reverted_30d", "author", "Reverted within 30 days"),
    ("author_abandoned", "author", "Abandoned"),
    ("author_pre_send_uploads", "author", "Uploads before sending for review"),
    ("author_neg_received", "author", "Any −1 received"),
]


def signals(sig):
    out = {}
    out["signals_era"] = sig["by_era"]
    out["signals_tenure"] = [
        {k: r[k] for k in ("era", "tenure_months", "cls", "neg_index", "abandon_index", "neg_share", "abandon_rate",
                           "after_neg_abandoned")}
        for r in sig["by_tenure"]]
    out["signals_familiarity"] = sig["by_familiarity_merged"]
    p = sig["panels"]
    rows = []
    for key, side, label in PANEL:
        v = p[key]
        rows.append(dict(key=key, side=side, measure=label, change=v["mean"], lo=v["lo"], hi=v["hi"], n=v["n"],
                         raw_2024=v.get("raw_2024"), raw_2026=v.get("raw_2026")))
    r24, r26 = p["reviewer_panel_2024"], p["reviewer_panel_2026"]
    rows[0].update(raw_2024=r24["threads_per_review"], raw_2026=r26["threads_per_review"])
    rows[1].update(raw_2024=r24["neg_vote_rate"], raw_2026=r26["neg_vote_rate"])
    out["panels"] = rows
    m = sig["matched"]
    out["matched"] = m["months"]
    out["signals_summary"] = [dict(
        cls=sig["cls"], votes_cls=sig["votes_cls"], reviewers=r24["reviewers"], reviews_2024=r24["reviews"],
        reviews_2026=r26["reviews"], authors=p["author_panel_size"], joiners_2025=m["joiners_2025"],
        joiners_2024=m["joiners_2024"], matched_pairs=m["matched_pairs"])]
    return out


def clusters(c):
    a = c["aggregate"]
    out = {}
    (pre_k, pre), (rec_k, rec) = list(a["git_windows"].items())
    out["patterns"] = [
        dict(pattern=name, tenure=prof["median_tenure_years"], commits=prof["median_commits_per_half"],
             approvals=prof["median_approvals_per_half"], owner=prof["owner_share"],
             share_pre=pre.get(name), share_recent=rec.get(name))
        for name, prof in sorted(a["git_profiles"].items(), key=lambda kv: -(rec.get(kv[0]) or 0))]
    total = sum(v for k, v in a["trajectories"].items())
    out["trajectories"] = [dict(trajectory=k, people=v, share=round(v / total, 3))
                           for k, v in sorted(a["trajectories"].items(), key=lambda kv: -kv[1])
                           if k not in ("mixed", "tapering off")]
    jm = a["joiner_mix"]
    keys = ["light → reviewer", "ramping up to author", "stays light"]
    out["joiner_paths"] = [dict(cohort=k.replace("joined ", ""), people=v["people"], **{t: v.get(t) for t in keys})
                           for k, v in jm.items()]
    out["transitions"] = [
        dict(window=WINDOWS.get(w.split(" ->")[0], w.split(" ->")[0]), light_review=t["light"]["review"], light_author=t["light"]["author"],
             author_review=t["author"]["review"], review_review=t["review"]["review"])
        for w, t in a["transitions"].items()]
    return out


def pattern_map(m):
    return {"pattern_cells": m["cells"], "pattern_ellipses": m["ellipses"], "pattern_loadings": m["loadings"],
            "pattern_rules": m["rules"], "pattern_map_summary": [m["summary"]]}


def security(s):
    sev = ["Critical", "High", "Medium", "Low"]
    rows = []
    for y, v in sorted(s["cves_by_year"].items()):
        rows.append(dict(year=int(y), **{k.lower(): v.get(k, 0) for k in sev}, total=sum(v.values()),
                         matched=s["matched_share_by_year"].get(y)))
    return {"security_years": rows,
            "security_summary": [dict(cves=s["cves"], bugs_with_commit=s["bugs_with_commit"],
                                      fixing_commits=s["fixing_commits"])]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", help="a balance_signals.py report (default: none)")
    ap.add_argument("--out", help="write the datasets here as JSON")
    args = ap.parse_args()
    d = store.DATA_DIR
    new = {}
    if args.signals:
        new.update(signals(json.load(open(args.signals))))
    new.update(clusters(json.load(open(os.path.join(d, "balance_clusters", "clusters.json")))))
    new.update(pattern_map(json.load(open(os.path.join(d, "balance_clusters", "map.json")))))
    new.update(security(json.load(open(os.path.join(d, "chrome_releases", "summary.json")))))
    show(new, args.out)


if __name__ == "__main__":
    main()
