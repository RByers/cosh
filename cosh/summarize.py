"""Aggregate derived.sqlite into small summaries for the front end.
Org attribution: see cosh/orgs.py.
In org_weekly, every org is reported however few reviewers it has; only the
domains in FOLD_INTO_OTHER (webmail domains that say nothing about an
organization) are folded into 'Other'.

Weeks (metric_version 3): review activity counts in the week it happened.
  - comments, review_chars, ai_comments, post_merge_comments: the ISO week
    each comment was written; the org is resolved as of that day.
  - vote_only_reviews (and their floor of one comment): the week of the vote.
  - reviewed_cls: the one per-CL metric, by the week the CL closed (merged
    or abandoned); the org is resolved as of the close.
  - reviewers: accounts credited with any of the above in the week.
Only fully fetched weeks are reported (meta.fetched_weeks), so activity before
the oldest week or in the current partial week is left out.

Headline metric (column `share`): comment count by default; reviewed CLs or
review characters selectable. All three shares are always present too.
AI comments are not in the headline; they are reported per org as ai_comments.
Post-merge comments (written after the CL closed) are in the headline; the
subset is also reported per org as post_merge_comments.
A Code-Review vote on a CL where the voter wrote no counted comment (e.g. a
bare +1) counts as one comment, so reviews that needed no changes still show
in the headline; how many such reviews each org has is reported as
vote_only_reviews.

Outputs:
  summaries/org_weekly.{csv,json}     one row per (week, org)
  summaries/weekly_totals.csv         one row per close week: human vs bot commits
                                      on main, so bot-only stretches don't look like gaps
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
REVIEWER_COLUMNS = ["account_id", "org", "comments", "cls", "chars"]

# Human reviewers on human-owned CLs on main. CROSS JOIN pins the join order
# (SQLite never reorders it): scan the fact rows x, then look up the CL and the
# account by primary key. Left to itself the planner put accounts before the
# cl_reviewers view and scanned every account per CL: 15 s per 3,000 rows.
SCOPE = """CROSS JOIN changes c ON c.host = x.host AND c.change_number = x.change_number
           CROSS JOIN accounts a ON a.host = x.host AND a.account_id = x.account_id
           WHERE a.is_bot = 0 AND c.is_bot_owned = 0 AND c.branch = 'main'"""


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


def activity_facts(db, resolve, weeks=None):
    """Per-(week, reviewer, org) facts: dicts with comments (headline, vote
    floor included), chars, ai, post_merge, vote_only and cls (set of CLs, by
    close week). `weeks`: the weeks to keep, or None for all."""
    facts = {}

    def fact(week, aid, email, name, org):
        f = facts.get((week, aid, org))
        if f is None:
            f = facts[(week, aid, org)] = dict(
                week=week, account_id=aid, email=email, name=name, org=org, comments=0,
                chars=0, ai=0, post_merge=0, vote_only=0, cls=set())
        return f

    keep = (lambda w: True) if weeks is None else weeks.__contains__
    # Comments, grouped per day so the org is resolved as of the day written.
    # The headline includes post-merge comments; post_merge is that subset.
    for week, aid, email, name, day, n, chars, ai, pm in db.execute(f"""
            SELECT x.iso_week, x.account_id, a.email, a.name, substr(x.written_at, 1, 10),
                   sum(x.is_ai = 0), sum(CASE WHEN x.is_ai = 0 THEN x.chars ELSE 0 END),
                   sum(x.is_ai), sum(x.is_ai = 0 AND x.after_close = 1)
            FROM comments x {SCOPE}
            GROUP BY 1, 2, 5"""):
        if keep(week):
            f = fact(week, aid, email, name, resolve(email, day))
            f["comments"] += n
            f["chars"] += chars
            f["ai"] += ai
            f["post_merge"] += pm
    # Vote floor: a vote on a CL where the voter wrote no counted (non-AI)
    # comment is a review too, worth one comment, in the week of the vote. A
    # vote never adds to a review that has comments ("LGTM" + +1 is 1, not 2).
    for week, aid, email, name, day, n in db.execute(f"""
            SELECT x.iso_week, x.account_id, a.email, a.name, substr(x.voted_at, 1, 10), count(*)
            FROM votes x {SCOPE}
              AND NOT EXISTS (SELECT 1 FROM comments m WHERE m.host = x.host
                              AND m.change_number = x.change_number
                              AND m.account_id = x.account_id AND m.is_ai = 0)
            GROUP BY 1, 2, 5"""):
        if keep(week):
            f = fact(week, aid, email, name, resolve(email, day))
            f["comments"] += n
            f["vote_only"] += n
    # Reviewed CLs: per CL, by the week it closed.
    for week, closed, cl, aid, email, name in db.execute(f"""
            SELECT x.close_week, x.closed_at, x.change_number, x.account_id, a.email, a.name
            FROM cl_reviewers x {SCOPE}"""):
        if keep(week):
            fact(week, aid, email, name, resolve(email, closed))["cls"].add(cl)
    return list(facts.values())


def summarize(data_dir=store.DATA_DIR, out_dir=os.path.join(ROOT, "summaries"),
              metric="comments", db_path=None):
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {sorted(METRICS)}")
    db = store.open_derived(data_dir, db_path)
    resolve = OrgResolver()
    meta_kv = dict(db.execute("SELECT k, v FROM meta"))
    fetched = json.loads(meta_kv.get("fetched_weeks") or "[]")
    weeks = set(fetched) if fetched else None
    facts = activity_facts(db, resolve, weeks)

    # Fold FOLD_INTO_OTHER domains into Other. Every other org is reported,
    # however few reviewers it has (the user dropped the <5-reviewer fold).
    folded = defaultdict(lambda: dict(cls=set(), reviewers=set(), comments=0, chars=0, ai=0,
                                      post_merge=0, vote_only=0))
    for f in facts:
        g = folded[(f["week"], "Other" if f["org"] in FOLD_INTO_OTHER else f["org"])]
        g["cls"] |= f["cls"]
        g["reviewers"].add(f["account_id"])
        for k in ("comments", "chars", "ai", "post_merge", "vote_only"):
            g[k] += f[k]

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
    for (week, org), f in sorted(folded.items(), key=lambda kv: (kv[0][0], -sort_key(kv[1]), kv[0][1])):
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

    weekly = [r for r in db.execute("""
        SELECT close_week, count(*), sum(status = 'MERGED'), sum(status = 'ABANDONED'),
               sum(is_bot_owned = 0), sum(is_bot_owned),
               -- Same set as cl_reviewers, but against the tables so the
               -- (host, change_number) primary-key prefix is used per CL.
               sum(is_bot_owned = 0 AND (
                   EXISTS (SELECT 1 FROM comments r JOIN accounts a
                           ON a.host = r.host AND a.account_id = r.account_id
                           WHERE r.host = c.host AND r.change_number = c.change_number AND a.is_bot = 0)
                   OR EXISTS (SELECT 1 FROM votes r JOIN accounts a
                           ON a.host = r.host AND a.account_id = r.account_id
                           WHERE r.host = c.host AND r.change_number = c.change_number AND a.is_bot = 0)))
        FROM changes c WHERE branch = 'main' AND close_week IS NOT NULL
        GROUP BY close_week ORDER BY close_week""") if weeks is None or r[0] in weeks]

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
                metric_version=meta_kv.get("metric_version"),
                open_snapshot_at=meta_kv.get("open_snapshot_at"),
                scope="chromium/src branch main: merged, abandoned and open CLs; bot-owned CLs excluded "
                      "from review metrics (counted in weekly_totals.csv)",
                weeks_rule="comments, chars, AI and post-merge comments count in the week the comment "
                           "was written; vote-only reviews in the week of the vote; reviewed_cls in the "
                           "week the CL closed; reviewers = accounts credited with any of these that week; "
                           "weekly_totals is by close week",
                folded_into_other=sorted(FOLD_INTO_OTHER),
                org_rule="affiliations.json5 (dated, as of the day of the activity) > other "
                         "@chromium.org -> google.com > email domain",
                metric_notes="reviews = non-owner, non-bot accounts that voted Code-Review "
                             "or wrote a comment; a vote on a CL with no counted comment by the voter counts as "
                             "one comment (reported as vote_only_reviews); comments exclude self-declared AI (is_ai flag or autogenerated:* tag; reported separately as ai_comments, a lower bound) and "
                             "include post-merge comments (written after the CL closed; that subset is also reported as "
                             "post_merge_comments); chars exclude quoted '>' lines")
    with _atomic_open(os.path.join(out_dir, "org_weekly.json")) as fh:
        json.dump(dict(meta=meta, rows=out,
                       weekly_totals=[dict(zip(TOTALS_COLS, r)) for r in weekly]),
                  fh, indent=1)
    db.close()
    write_reviewers(facts, os.path.join(out_dir, REVIEWERS_FILE))
    return out


def reviewer_weeks(facts):
    """Every reviewer's counts, per (week, account, org): the facts behind
    org_weekly, before the FOLD_INTO_OTHER fold (so the leaderboard can show
    gmail.com). Summed per (week, folded org) they reproduce org_weekly's
    reviewers, comments and review_chars exactly. A reviewer whose activity
    resolves to two orgs in one week gets one row per org.
    Returns (names: account_id -> display name, weeks: week -> [row dict]),
    each week's rows sorted by comments, then CLs, descending."""
    names = {}
    weeks = defaultdict(list)
    for f in facts:
        aid = f["account_id"]
        names[aid] = f["name"] or (f["email"] or "").split("@")[0] or f"Account {aid}"
        weeks[f["week"]].append(dict(account_id=aid, org=f["org"], comments=f["comments"],
                                     cls=len(f["cls"]), chars=f["chars"]))
    for people in weeks.values():
        people.sort(key=lambda r: (-r["comments"], -r["cls"], r["account_id"], r["org"]))
    return names, dict(sorted(weeks.items()))


def write_reviewers(facts, path):
    """Committed and published (derived from public Gerrit data, docs/plan.md
    ground rule 3). Compact: names and emails are listed once per account
    (`accounts`, `emails`: account id -> string) and orgs once,
    and each week is a list of [account_id, org index, comments, cls, chars]
    rows, one per line so weekly regenerations diff well."""
    names, weeks = reviewer_weeks(facts)
    # Gerrit account emails (public); accounts without one are bots and never
    # reach this table, but skip a missing email rather than write null.
    emails = {f["account_id"]: f["email"] for f in facts if f["email"]}
    orgs = sorted({r["org"] for people in weeks.values() for r in people})
    org_index = {o: i for i, o in enumerate(orgs)}
    meta = dict(generated_at=store.now_iso(), columns=REVIEWER_COLUMNS,
                fold_into_other=sorted(FOLD_INTO_OTHER),
                scope="every reviewer, one row per (week, account, org); same scope and weeks as "
                      "org_weekly.json (human reviewers on human-owned CLs on main; comments by week "
                      "written, vote-only reviews by week voted, reviewed CLs by week closed). org is "
                      "an index into orgs, resolved before the fold_into_other fold.")
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
