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
  summaries/reviewer_weekly.json      one row per (week, reviewer, org) for every
                                      reviewer in scope, so the web UI can total
                                      any date range exactly (leaderboard, distinct
                                      reviewers per org); names, emails (public on
                                      Gerrit; the leaderboard's hover card) and orgs
"""

import contextlib
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
REVIEWERS_FILE = "reviewer_weekly.json"


@contextlib.contextmanager
def _atomic_open(path, **kw):
    """Write to a temp file and rename it over `path`, so a reader (e.g. the
    Vite dev server while a backfill re-summarizes) never sees a half-written file."""
    tmp = f"{path}.tmp{os.getpid()}"
    try:
        with open(tmp, "w", **kw) as fh:
            yield fh
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


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
    with _atomic_open(os.path.join(out_dir, "org_weekly.csv"), newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]) if out else ["iso_week", "org"])
        w.writeheader()
        w.writerows(out)
    with _atomic_open(os.path.join(out_dir, "weekly_totals.csv"), newline="") as fh:
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
    with _atomic_open(os.path.join(out_dir, "org_weekly.json")) as fh:
        json.dump(dict(meta=meta, rows=out,
                       weekly_totals=[dict(zip(TOTALS_COLS, r)) for r in weekly]),
                  fh, indent=1)
    db.close()
    write_reviewers(rows, resolve, os.path.join(out_dir, REVIEWERS_FILE))
    return out


REVIEWER_COLUMNS = ["account_id", "org", "comments", "cls", "chars"]


def reviewer_weeks(rows, resolve):
    """Every reviewer's counts, per (week, account, org). Same scope and rules
    as the org summary: human reviewers on human-owned CLs on main; comments
    exclude AI and post-merge comments, and a vote-only review counts as one
    comment. `org` is resolved per review as in org_weekly, but before the
    FOLD_INTO_OTHER fold (so the leaderboard can show gmail.com); a reviewer
    whose reviews resolve to two orgs in one week gets one row per org.
    Returns (names: account_id -> display name, weeks: week -> [row dict]),
    each week's rows sorted by comments, then CLs, descending."""
    names = {}
    per = defaultdict(lambda: dict(cls=set(), comments=0, chars=0))
    for week, submitted, cl, email, aid, ncom, nchars, _, _, name, *_ in rows:
        names[aid] = name or (email or "").split("@")[0] or f"Account {aid}"
        p = per[(week, aid, resolve(email, submitted))]
        p["cls"].add(cl)
        p["comments"] += ncom
        p["chars"] += nchars
    weeks = defaultdict(list)
    for (week, aid, org), p in per.items():
        weeks[week].append(dict(account_id=aid, org=org, comments=p["comments"],
                                cls=len(p["cls"]), chars=p["chars"]))
    for people in weeks.values():
        people.sort(key=lambda r: (-r["comments"], -r["cls"], r["account_id"], r["org"]))
    return names, dict(sorted(weeks.items()))


def write_reviewers(rows, resolve, path):
    """Committed and published (derived from public Gerrit data, docs/plan.md
    ground rule 3). Compact: names and emails are listed once per account
    (`accounts`, `emails`: account id -> string) and orgs once,
    and each week is a list of [account_id, org index, comments, cls, chars]
    rows, one per line so weekly regenerations diff well."""
    names, weeks = reviewer_weeks(rows, resolve)
    # Gerrit account emails (public); accounts without one are bots and never
    # reach this table, but skip a missing email rather than write null.
    emails = {aid: email for _, _, _, email, aid, *_ in rows if email}
    orgs = sorted({r["org"] for people in weeks.values() for r in people})
    org_index = {o: i for i, o in enumerate(orgs)}
    meta = dict(generated_at=store.now_iso(), columns=REVIEWER_COLUMNS,
                fold_into_other=sorted(FOLD_INTO_OTHER),
                scope="every reviewer, one row per (week, account, org); same scope as org_weekly.json "
                      "(human reviewers on human-owned CLs on main). org is an index into orgs, "
                      "resolved before the fold_into_other fold.")
    with _atomic_open(path) as fh:
        fh.write('{"meta": %s,\n "orgs": %s,\n "accounts": {' % (json.dumps(meta), json.dumps(orgs)))
        fh.write(",".join('\n  "%d": %s' % (aid, json.dumps(names[aid], ensure_ascii=False))
                          for aid in sorted(names)))
        fh.write('\n },\n "emails": {')
        fh.write(",".join('\n  "%d": %s' % (aid, json.dumps(emails[aid], ensure_ascii=False))
                          for aid in sorted(names) if aid in emails))
        fh.write('\n },\n "weeks": {')
        for i, (week, people) in enumerate(weeks.items()):
            fh.write('%s\n  %s: [' % ("," if i else "", json.dumps(week)))
            fh.write(",".join("\n   [%d,%d,%d,%d,%d]" % (r["account_id"], org_index[r["org"]], r["comments"],
                                                          r["cls"], r["chars"]) for r in people))
            fh.write("\n  ]")
        fh.write("\n }\n}\n")
