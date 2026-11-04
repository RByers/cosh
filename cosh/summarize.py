"""Aggregate derived.sqlite into small summaries for the front end.

The metric is review comments (metric_version 5): published comments by
non-owner, non-bot accounts on human-owned CLs on main, in the ISO week each
was written, with the org as of that day (cosh/orgs.py). Reviews with no
comment (a bare Code-Review vote) don't count: their value can't be judged.

Path scope: each comment is placed on a file (cosh/paths.py) and counts only
if config/paths.txt includes that file. Comments that can't be placed (CLs
with no inline comments) are outside the scope. org_weekly and
reviewer_weekly cover the scope; area_weekly covers every comment, so the web
UI can show what the scope leaves out.

In org_weekly every org is reported however few reviewers it has; only the
domains in FOLD_INTO_OTHER (webmail domains that say nothing about an
organization) are folded into 'Other'. Self-declared AI comments posted from a
reviewer's own account count in `comments` (since metric_version 4); the
subset is ai_comments. Post-merge comments (written after the CL closed) are
in `comments` too; that subset is post_merge_comments.
Only fully fetched weeks are reported (meta.fetched_weeks).

Outputs:
  summaries/org_weekly.{csv,json}     one row per (week, org), in scope
  summaries/weekly_totals.csv         one row per close week: human vs bot commits
                                      on main, so bot-only stretches don't look like gaps
  summaries/reviewer_weekly.json      one row per (week, reviewer, org), in scope, for
                                      every reviewer, so the web UI can total any
                                      date range exactly (leaderboard, distinct
                                      reviewers per org); names, emails (public on
                                      Gerrit; the leaderboard's hover card) and orgs
  summaries/area_weekly.json          comments per (week, directory, org), every
                                      comment, each directory marked in or out of scope
"""

import contextlib
import csv
import json
import os
from collections import defaultdict

from . import store
from .derive import METRIC_VERSION
from .orgs import OrgResolver
from .paths import UNPLACED, load_scope, place

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Domains always folded into Other, whatever their size: personal webmail
# addresses are not an organization.
FOLD_INTO_OTHER = frozenset({"gmail.com"})
OTHER = "Other"
TOTALS_COLS = ["iso_week", "main_cls", "merged_cls", "abandoned_cls", "human_cls",
               "bot_cls", "human_cls_with_comments"]
REVIEWERS_FILE = "reviewer_weekly.json"
AREAS_FILE = "area_weekly.json"
REVIEWER_COLUMNS = ["account_id", "org", "comments"]

# Human reviewers on human-owned CLs on main. CROSS JOIN pins the join order
# (SQLite never reorders it): scan the comments, then look up the CL and the
# account by primary key.
SCOPE = """CROSS JOIN changes c ON c.host = x.host AND c.change_number = x.change_number
           CROSS JOIN accounts a ON a.host = x.host AND a.account_id = x.account_id
           WHERE a.is_bot = 0 AND c.is_bot_owned = 0 AND c.branch = 'main'"""


def fold(org):
    return OTHER if org in FOLD_INTO_OTHER else org


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


def comment_facts(db, resolve, scope, weeks=None):
    """Returns (facts, areas).

    facts: per-(week, reviewer, org) dicts with in-scope comments, and the
    ai and post_merge subsets of them.
    areas: {(week, area, folded org): comments}, every comment.
    `weeks`: the weeks to keep, or None for all."""
    facts = {}
    areas = defaultdict(int)
    keep = (lambda w: True) if weeks is None else weeks.__contains__
    cache = {}

    def where(path):
        if path not in cache:
            cache[path] = (scope.includes(path), scope.area(path))
        return cache[path]

    # Grouped per day, so the org is resolved as of the day written, and per
    # path and anchor, so each group lands on one file.
    for week, aid, email, name, day, path, anchor_path, n, ai, pm in db.execute(f"""
            SELECT x.iso_week, x.account_id, a.email, a.name, substr(x.written_at, 1, 10),
                   x.path, c.anchor_path, count(*), sum(x.is_ai), sum(x.after_close)
            FROM comments x {SCOPE}
            GROUP BY 1, 2, 5, 6, 7"""):
        if not keep(week):
            continue
        org = resolve(email, day)
        included, area = where(place(path, anchor_path))
        areas[(week, area, fold(org))] += n
        if not included:
            continue
        f = facts.get((week, aid, org))
        if f is None:
            f = facts[(week, aid, org)] = dict(week=week, account_id=aid, email=email, name=name,
                                               org=org, comments=0, ai=0, post_merge=0)
        f["comments"] += n
        f["ai"] += ai
        f["post_merge"] += pm
    return list(facts.values()), areas


def summarize(data_dir=store.DATA_DIR, out_dir=os.path.join(ROOT, "summaries"), db_path=None,
              scope=None):
    db = store.open_derived(data_dir, db_path)
    scope = scope or load_scope()
    resolve = OrgResolver()
    meta_kv = dict(db.execute("SELECT k, v FROM meta"))
    fetched = json.loads(meta_kv.get("fetched_weeks") or "[]")
    weeks = set(fetched) if fetched else None
    facts, areas = comment_facts(db, resolve, scope, weeks)

    folded = defaultdict(lambda: dict(reviewers=set(), comments=0, ai=0, post_merge=0))
    for f in facts:
        g = folded[(f["week"], fold(f["org"]))]
        g["reviewers"].add(f["account_id"])
        for k in ("comments", "ai", "post_merge"):
            g[k] += f[k]
    totals = defaultdict(int)
    for (week, _), g in folded.items():
        totals[week] += g["comments"]

    out = []
    for (week, org), g in sorted(folded.items(), key=lambda kv: (kv[0][0], -kv[1]["comments"], kv[0][1])):
        t = totals[week]
        out.append(dict(iso_week=week, org=org, share=round(g["comments"] / t, 4) if t else None,
                        reviewers=len(g["reviewers"]), comments=g["comments"],
                        ai_comments=g["ai"], post_merge_comments=g["post_merge"]))

    weekly = [r for r in db.execute("""
        SELECT close_week, count(*), sum(status = 'MERGED'), sum(status = 'ABANDONED'),
               sum(is_bot_owned = 0), sum(is_bot_owned),
               sum(is_bot_owned = 0 AND EXISTS (
                   SELECT 1 FROM comments r JOIN accounts a
                   ON a.host = r.host AND a.account_id = r.account_id
                   WHERE r.host = c.host AND r.change_number = c.change_number
                     AND a.is_bot = 0))
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
    all_weeks = sorted(weeks) if weeks is not None else sorted({k[0] for k in areas} | set(totals))
    meta = dict(generated_at=store.now_iso(), weeks=all_weeks,
                metric_version=METRIC_VERSION,
                derived_metric_version=meta_kv.get("metric_version"),
                open_snapshot_at=meta_kv.get("open_snapshot_at"),
                scope="chromium/src branch main: merged, abandoned and open CLs; review comments by "
                      "non-owner, non-bot accounts on human-owned CLs (bot-owned CLs are counted only in "
                      "weekly_totals.csv)",
                path_rules=scope.describe(),
                path_rule="a comment is placed on its file; a patchset-level comment on its CL's "
                          "anchor (the file with the most inline comments); the longest matching "
                          "path_rules prefix decides, and paths matching none are included; "
                          "comments that can't be placed are excluded (see area_weekly.json)",
                weeks_rule="each comment counts in the ISO week it was written; weekly_totals is by "
                           "close week",
                folded_into_other=sorted(FOLD_INTO_OTHER),
                org_rule="affiliations.json5 (dated, as of the day written) > other "
                         "@chromium.org -> google.com > email domain",
                metric_notes="comments include self-declared AI comments from a reviewer's own account "
                             "(is_ai flag or autogenerated:* tag; that subset is ai_comments, a lower bound) "
                             "and post-merge comments (that subset is post_merge_comments); "
                             "share = org comments / all comments")
    with _atomic_open(os.path.join(out_dir, "org_weekly.json")) as fh:
        json.dump(dict(meta=meta, rows=out,
                       weekly_totals=[dict(zip(TOTALS_COLS, r)) for r in weekly]),
                  fh, indent=1)
    db.close()
    write_reviewers(facts, os.path.join(out_dir, REVIEWERS_FILE))
    write_areas(areas, scope, os.path.join(out_dir, AREAS_FILE))
    return out


def reviewer_weeks(facts):
    """Every reviewer's in-scope comments, per (week, account, org): the facts
    behind org_weekly, before the FOLD_INTO_OTHER fold (so the leaderboard can
    show gmail.com). Summed per (week, folded org) they reproduce org_weekly's
    reviewers and comments exactly. A reviewer whose comments resolve to two
    orgs in one week gets one row per org.
    Returns (names: account_id -> display name, weeks: week -> [row dict]),
    each week's rows sorted by comments, descending."""
    names = {}
    weeks = defaultdict(list)
    for f in facts:
        aid = f["account_id"]
        names[aid] = f["name"] or (f["email"] or "").split("@")[0] or f"Account {aid}"
        weeks[f["week"]].append(dict(account_id=aid, org=f["org"], comments=f["comments"]))
    for people in weeks.values():
        people.sort(key=lambda r: (-r["comments"], r["account_id"], r["org"]))
    return names, dict(sorted(weeks.items()))


def write_reviewers(facts, path):
    """Committed and published (derived from public Gerrit data, docs/plan.md
    ground rule 3). Compact: names and emails are listed once per account
    (`accounts`, `emails`: account id -> string) and orgs once, and each week
    is a list of [account_id, org index, comments] rows, one per line so
    weekly regenerations diff well."""
    names, weeks = reviewer_weeks(facts)
    # Gerrit account emails (public); accounts without one are bots and never
    # reach this table, but skip a missing email rather than write null.
    emails = {f["account_id"]: f["email"] for f in facts if f["email"]}
    orgs = sorted({r["org"] for people in weeks.values() for r in people})
    org_index = {o: i for i, o in enumerate(orgs)}
    meta = dict(generated_at=store.now_iso(), columns=REVIEWER_COLUMNS,
                fold_into_other=sorted(FOLD_INTO_OTHER),
                scope="every reviewer, one row per (week, account, org); same scope and weeks as "
                      "org_weekly.json (human reviewers' in-scope comments on human-owned CLs on main, "
                      "by week written). org is an index into orgs, resolved before the "
                      "fold_into_other fold.")
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
            fh.write(",".join("\n   [%d,%d,%d]" % (r["account_id"], org_index[r["org"]], r["comments"])
                              for r in people))
            fh.write("\n  ]")
        fh.write("\n }\n}\n")


def write_areas(areas, scope, path):
    """area_weekly.json: comments per (week, directory, org) over every
    comment, in scope or not. `areas` lists each directory (largest first) with
    whether the scope includes it; rows are [area index, org index, comments].
    Orgs are folded like org_weekly."""
    by_area = defaultdict(int)
    for (_, area, _), n in areas.items():
        by_area[area] += n
    names = sorted(by_area, key=lambda a: (-by_area[a], a))
    area_index = {a: i for i, a in enumerate(names)}
    orgs = sorted({o for _, _, o in areas})
    org_index = {o: i for i, o in enumerate(orgs)}
    weeks = defaultdict(list)
    for (week, area, org), n in sorted(areas.items()):
        weeks[week].append([area_index[area], org_index[org], n])
    meta = dict(generated_at=store.now_iso(), columns=["area", "org", "comments"],
                path_rules=scope.describe(), unplaced=UNPLACED,
                scope="non-owner, non-bot review comments on human-owned CLs on main, by week written, "
                      "in scope or not. A comment's area is the longest matching path_rules or "
                      "config/paths.txt area prefix, else its top-level directory; unplaced comments "
                      "(no inline comment anywhere on their CL) are their own area.")
    doc = dict(meta=meta,
               areas=[dict(area=a, included=a != UNPLACED and scope.includes(a)) for a in names],
               orgs=orgs, weeks=dict(sorted(weeks.items())))
    with _atomic_open(path) as fh:
        fh.write('{"meta": %s,\n "areas": %s,\n "orgs": %s,\n "weeks": {' % (
            json.dumps(meta), json.dumps(doc["areas"]), json.dumps(orgs)))
        fh.write(",".join('\n  %s: %s' % (json.dumps(w), json.dumps(rows)) for w, rows in doc["weeks"].items()))
        fh.write("\n }\n}\n")
