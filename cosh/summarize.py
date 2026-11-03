"""Aggregate cosh.sqlite into small per-org summaries for the front end.
Org attribution: see cosh/orgs.py.
Output contains no per-person data. Orgs with fewer than MIN_REVIEWERS distinct
reviewers in a period are folded into 'Other'.

Headline metric (column `share`): comment count by default; reviewed CLs or
review characters selectable. All three shares are always present too.

Outputs:
  summaries/org_weekly.{csv,json}     one row per (week, org)
  summaries/weekly_totals.csv         one row per week: human vs bot commits on
                                      main, so bot-only stretches don't look like gaps
"""

import csv
import json
import os
from collections import defaultdict

from . import store
from .orgs import OrgResolver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_REVIEWERS = 5
TOTALS_COLS = ["iso_week", "main_cls", "merged_cls", "abandoned_cls", "human_cls",
               "bot_cls", "human_cls_with_review"]
METRICS = {"comments": "share_comments", "cls": "share_cls", "chars": "share_chars"}


def summarize(data_dir=store.DATA_DIR, out_dir=os.path.join(ROOT, "summaries"),
              min_reviewers=MIN_REVIEWERS, metric="comments"):
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {sorted(METRICS)}")
    db = store.open_cosh(data_dir)
    resolve = OrgResolver()
    rows = db.execute(f"""
        SELECT c.iso_week, c.closed_at, r.change_number, a.email, r.account_id,
               r.review_comments, r.review_chars, r.ai_comments
        FROM reviews r
        JOIN changes c ON c.host = r.host AND c.change_number = r.change_number
        JOIN accounts a ON a.host = r.host AND a.account_id = r.account_id
        WHERE a.is_bot = 0 AND c.is_bot_owned = 0 AND c.branch = 'main'
    """).fetchall()

    agg = defaultdict(lambda: dict(cls=set(), reviewers=set(), comments=0, chars=0, ai=0))
    for week, submitted, cl, email, aid, ncom, nchars, nai in rows:
        g = agg[(week, resolve(email, submitted))]
        g["cls"].add(cl)
        g["reviewers"].add(aid)
        g["comments"] += ncom
        g["chars"] += nchars
        g["ai"] += nai

    # Privacy: fold small orgs into Other (per week).
    folded = defaultdict(lambda: dict(cls=set(), reviewers=set(), comments=0, chars=0, ai=0))
    for (week, org), g in agg.items():
        key = (week, org if len(g["reviewers"]) >= min_reviewers else "Other")
        f = folded[key]
        f["cls"] |= g["cls"]
        f["reviewers"] |= g["reviewers"]
        f["comments"] += g["comments"]
        f["chars"] += g["chars"]
        f["ai"] += g["ai"]

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
                min_reviewers_per_org=min_reviewers,
                org_rule="affiliations.json5 (dated) > other @chromium.org -> google.com > email domain",
                metric_notes="reviews = non-owner, non-bot accounts that voted Code-Review "
                             "or wrote a comment; comments exclude self-declared AI (is_ai flag or autogenerated:* tag; reported separately as ai_comments, a lower bound) and "
                             "post-merge comments; chars exclude quoted '>' lines")
    with open(os.path.join(out_dir, "org_weekly.json"), "w") as fh:
        json.dump(dict(meta=meta, rows=out,
                       weekly_totals=[dict(zip(TOTALS_COLS, r)) for r in weekly]),
                  fh, indent=1)
    db.close()
    return out
