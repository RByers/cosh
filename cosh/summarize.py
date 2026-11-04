"""Aggregate cosh.sqlite into small summaries for the front end.
Org attribution: see cosh/orgs.py.
In org_weekly, every org is reported however few reviewers it has; only the
domains in FOLD_INTO_OTHER (webmail domains that say nothing about an
organization) are folded into 'Other'.

Headline metric (column `share`): comment count by default; reviewed CLs or
review characters selectable. All three shares are always present too.
AI comments and post-merge comments (written after the CL closed) are not in
the headline; they are reported per org as ai_comments and post_merge_comments.
A review with a Code-Review vote but no counted comment (e.g. a bare +1) counts
as one comment, so reviews that needed no changes still show in the headline;
how many such reviews each org has is reported as vote_only_reviews.

Outputs:
  summaries/org_weekly.{csv,json}     one row per (week, org)
  summaries/weekly_totals.csv         one row per week: human vs bot commits on
                                      main, so bot-only stretches don't look like gaps
  summaries/reviewer_weekly.json      per reviewer: each week's top 50 by each
                                      metric (the web UI's leaderboard); names and
                                      orgs only, no emails
"""

import csv
import json
import os
from collections import defaultdict

from . import store
from .orgs import OrgResolver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Domains always folded into Other, whatever their size: personal webmail
# addresses are not an organization.
FOLD_INTO_OTHER = frozenset({"gmail.com"})
TOTALS_COLS = ["iso_week", "main_cls", "merged_cls", "abandoned_cls", "human_cls",
               "bot_cls", "human_cls_with_review"]
METRICS = {"comments": "share_comments", "cls": "share_cls", "chars": "share_chars"}
LEADERBOARD_SIZE = 50
REVIEWERS_FILE = "reviewer_weekly.json"


def summarize(data_dir=store.DATA_DIR, out_dir=os.path.join(ROOT, "summaries"),
              metric="comments"):
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {sorted(METRICS)}")
    db = store.open_cosh(data_dir)
    resolve = OrgResolver()
    rows = db.execute(f"""
        SELECT c.iso_week, c.closed_at, r.change_number, a.email, r.account_id,
               -- Floor of 1: a vote with no counted comment (e.g. a bare +1) is a
               -- review, so it counts as one comment here and in the leaderboard.
               max(r.review_comments, coalesce(r.voted_cr, 0) != 0), r.review_chars, r.ai_comments,
               r.post_merge_comments, a.name,
               r.review_comments = 0 AND coalesce(r.voted_cr, 0) != 0 AS vote_only
        FROM reviews r
        JOIN changes c ON c.host = r.host AND c.change_number = r.change_number
        JOIN accounts a ON a.host = r.host AND a.account_id = r.account_id
        WHERE a.is_bot = 0 AND c.is_bot_owned = 0 AND c.branch = 'main'
    """).fetchall()

    agg = defaultdict(lambda: dict(cls=set(), reviewers=set(), comments=0, chars=0, ai=0, post_merge=0,
                                   vote_only=0))
    for week, submitted, cl, email, aid, ncom, nchars, nai, npm, _, vote_only in rows:
        g = agg[(week, resolve(email, submitted))]
        g["vote_only"] += vote_only
        g["cls"].add(cl)
        g["reviewers"].add(aid)
        g["comments"] += ncom
        g["chars"] += nchars
        g["ai"] += nai
        g["post_merge"] += npm

    # Fold FOLD_INTO_OTHER domains into Other. Every other org is reported,
    # however few reviewers it has (the user dropped the <5-reviewer fold).
    folded = defaultdict(lambda: dict(cls=set(), reviewers=set(), comments=0, chars=0, ai=0, post_merge=0,
                                      vote_only=0))
    for (week, org), g in agg.items():
        key = (week, "Other" if org in FOLD_INTO_OTHER else org)
        f = folded[key]
        f["cls"] |= g["cls"]
        f["reviewers"] |= g["reviewers"]
        f["comments"] += g["comments"]
        f["chars"] += g["chars"]
        f["ai"] += g["ai"]
        f["post_merge"] += g["post_merge"]
        f["vote_only"] += g["vote_only"]

    # Totals per week. reviewed_cls share uses sum of per-org CL counts as the
    # denominator (a CL reviewed by two orgs credits both), so shares sum to 1.
    totals = defaultdict(lambda: dict(cls=0, comments=0, chars=0))
    for (week, _), f in folded.items():
        t = totals[week]
        t["cls"] += len(f["cls"])
        t["comments"] += f["comments"]
        t["chars"] += f["chars"]

    def share(a, b):
        return round(a / b, 4) if b else None

    sort_key = {"comments": lambda f: f["comments"], "cls": lambda f: len(f["cls"]),
                "chars": lambda f: f["chars"]}[metric]
    out = []
    for (week, org), f in sorted(folded.items(), key=lambda kv: (kv[0][0], -sort_key(kv[1]))):
        t = totals[week]
        out.append(dict(iso_week=week, org=org, share=None, reviewed_cls=len(f["cls"]),
                        reviewers=len(f["reviewers"]), comments=f["comments"],
                        review_chars=f["chars"], ai_comments=f["ai"],
                        post_merge_comments=f["post_merge"],
                        vote_only_reviews=f["vote_only"],
                        share_cls=share(len(f["cls"]), t["cls"]),
                        share_comments=share(f["comments"], t["comments"]),
                        share_chars=share(f["chars"], t["chars"])))
        out[-1]["share"] = out[-1][METRICS[metric]]

    weekly = db.execute("""
        SELECT iso_week, count(*), sum(status = 'MERGED'), sum(status = 'ABANDONED'),
               sum(is_bot_owned = 0), sum(is_bot_owned),
               sum(is_bot_owned = 0 AND EXISTS (SELECT 1 FROM reviews r JOIN accounts a
                   ON a.host = r.host AND a.account_id = r.account_id
                   WHERE r.host = c.host AND r.change_number = c.change_number AND a.is_bot = 0))
        FROM changes c WHERE branch = 'main' GROUP BY iso_week ORDER BY iso_week""").fetchall()

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "org_weekly.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]) if out else ["iso_week", "org"])
        w.writeheader()
        w.writerows(out)
    with open(os.path.join(out_dir, "weekly_totals.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(TOTALS_COLS)
        w.writerows(weekly)
    meta = dict(generated_at=store.now_iso(), weeks=sorted(totals),
                headline_metric=metric, headline_column="share",
                scope="chromium/src branch main, merged + abandoned CLs; bot-owned CLs excluded from review metrics "
                      "(counted in weekly_totals.csv)",
                folded_into_other=sorted(FOLD_INTO_OTHER),
                org_rule="affiliations.json5 (dated) > other @chromium.org -> google.com > email domain",
                metric_notes="reviews = non-owner, non-bot accounts that voted Code-Review "
                             "or wrote a comment; a review with a vote but no counted comment counts as "
                             "one comment (reported as vote_only_reviews); comments exclude self-declared AI (is_ai flag or autogenerated:* tag; reported separately as ai_comments, a lower bound) and "
                             "post-merge comments (human comments written after the CL closed; reported separately as "
                             "post_merge_comments); chars exclude quoted '>' lines")
    with open(os.path.join(out_dir, "org_weekly.json"), "w") as fh:
        json.dump(dict(meta=meta, rows=out,
                       weekly_totals=[dict(zip(TOTALS_COLS, r)) for r in weekly]),
                  fh, indent=1)
    db.close()
    write_reviewers(rows, resolve, os.path.join(out_dir, REVIEWERS_FILE))
    return out


def reviewer_leaderboard(rows, resolve, n=LEADERBOARD_SIZE):
    """Per week, the top `n` reviewers by each metric (the union, so the UI can
    re-rank by any metric). Same scope as the org summary: human reviewers on
    human-owned CLs on main; comments exclude AI and post-merge comments, and
    a vote-only review counts as one comment.
    `org` is the reviewer's org on most of their reviewed CLs that week."""
    per = defaultdict(lambda: dict(name=None, cls=set(), comments=0, chars=0, orgs=defaultdict(int)))
    for week, submitted, cl, email, aid, ncom, nchars, _, _, name, *_ in rows:
        p = per[(week, aid)]
        p["name"] = name or (email or "").split("@")[0] or f"Account {aid}"
        p["cls"].add(cl)
        p["comments"] += ncom
        p["chars"] += nchars
        p["orgs"][resolve(email, submitted)] += 1
    by_week = defaultdict(list)
    for (week, aid), p in per.items():
        org = max(p["orgs"].items(), key=lambda kv: (kv[1], kv[0]))[0]
        by_week[week].append(dict(account_id=aid, name=p["name"], org=org, comments=p["comments"],
                                  cls=len(p["cls"]), chars=p["chars"]))
    out = {}
    for week, people in sorted(by_week.items()):
        keep = {}
        for m in ("comments", "cls", "chars"):
            ranked = sorted((r for r in people if r[m] > 0), key=lambda r: (-r[m], r["account_id"]))
            for r in ranked[:n]:
                keep[r["account_id"]] = r
        out[week] = sorted(keep.values(), key=lambda r: (-r["comments"], -r["cls"], r["account_id"]))
    return out


def write_reviewers(rows, resolve, path):
    """Committed and published (derived from public Gerrit data, docs/plan.md
    ground rule 3). One reviewer per line, so weekly regenerations diff well."""
    weeks = reviewer_leaderboard(rows, resolve)
    meta = dict(generated_at=store.now_iso(), top_n=LEADERBOARD_SIZE,
                scope="union of each week's top_n reviewers by comments, reviewed CLs and review chars; "
                      "same scope as org_weekly.json (human reviewers on human-owned CLs on main)")
    with open(path, "w") as fh:
        fh.write('{"meta": %s,\n "weeks": {' % json.dumps(meta))
        for i, (week, people) in enumerate(weeks.items()):
            fh.write('%s\n  %s: [' % ("," if i else "", json.dumps(week)))
            fh.write(",".join("\n   " + json.dumps(p, ensure_ascii=False) for p in people))
            fh.write("\n  ]")
        fh.write("\n }\n}\n")
