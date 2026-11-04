"""Aggregate derived.sqlite into small summaries for the front end.

Review is measured from comments only (metric_version 5): published comments
by non-owner, non-bot accounts on human-owned CLs on main. Reviews with no
comment (a bare Code-Review vote) don't count: their value can't be judged.
Three metrics, all from those comments:
  - comments: in the ISO week each was written, with the org as of that day
    (cosh/orgs.py). The default headline.
  - review_chars: the length of those comments, quoted '>' lines removed;
    same weeks and orgs.
  - reviewed_cls: CLs an org's reviewers commented on, counted once per org in
    the week the CL closed (merged or abandoned), with the org as of the close.
    Open CLs don't count yet. An org's share uses the sum of every org's CL
    count as the denominator (a CL reviewed by two orgs credits both).
Reviewers in a week: accounts credited with any of these that week.

Path scope: each comment is placed on a file (cosh/paths.py) and counts only
if config/paths.txt includes that file; a CL counts as reviewed only through
in-scope comments. Comments that can't be placed (CLs with no inline
comments) are outside the scope. org_weekly and reviewer_weekly cover the
scope; area_weekly covers every comment, so the web UI can show what the
scope leaves out.

In org_weekly every org is reported however few reviewers it has; only the
domains in FOLD_INTO_OTHER (webmail domains that say nothing about an
organization) are folded into 'Other'. Self-declared AI comments posted from a
reviewer's own account count (since metric_version 4); the subset is
ai_comments. Post-merge comments (written after the CL closed) count too; that
subset is post_merge_comments. Only fully fetched weeks are reported
(meta.fetched_weeks).

Outputs:
  summaries/org_weekly.{csv,json}     one row per (week, org), in scope
  summaries/weekly_totals.csv         one row per close week: human vs bot commits
                                      on main, so bot-only stretches don't look like gaps
  summaries/reviewer_weekly.json      one row per (week, reviewer, org), in scope, for
                                      every reviewer, so the web UI can total any
                                      date range exactly (leaderboard, distinct
                                      reviewers per org); names, emails (public on
                                      Gerrit; the leaderboard's hover card) and orgs
  summaries/area_weekly.json          all three metrics per (week, directory, org),
                                      every comment, as a directory tree (the top
                                      paths.DIR_LIMIT directories) the web UI drills into,
                                      each node marked in or out of scope
"""

import contextlib
import csv
import json
import os
from collections import defaultdict

from . import store
from .derive import METRIC_VERSION
from .orgs import OrgResolver
from .paths import DIR_LIMIT, ROOT_FILES, UNPLACED, dir_tree, directory, load_scope, place

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Domains always folded into Other, whatever their size: personal webmail
# addresses are not an organization.
FOLD_INTO_OTHER = frozenset({"gmail.com"})
OTHER = "Other"
TOTALS_COLS = ["iso_week", "main_cls", "merged_cls", "abandoned_cls", "human_cls",
               "bot_cls", "human_cls_with_comments"]
METRICS = {"comments": "share_comments", "cls": "share_cls", "chars": "share_chars"}
REVIEWERS_FILE = "reviewer_weekly.json"
AREAS_FILE = "area_weekly.json"
REVIEWER_COLUMNS = ["account_id", "org", "comments", "cls", "chars"]

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

    facts: per-(week, reviewer, org) dicts with in-scope comments (and their
    ai and post_merge subsets), chars, and cls (the set of CLs closed that
    week that the reviewer commented on in scope).
    areas: {(week, directory, folded org): dict(comments, chars, cls)},
    every comment, in scope or not (directory as from paths.directory).
    `weeks`: the weeks to keep, or None for all."""
    facts = {}
    areas = defaultdict(lambda: dict(comments=0, chars=0, cls=set()))
    keep = (lambda w: True) if weeks is None else weeks.__contains__
    cache = {}

    def where(path, anchor_path):
        key = (path, anchor_path)
        if key not in cache:
            p = place(path, anchor_path)
            cache[key] = (scope.includes(p), directory(p))
        return cache[key]

    def fact(week, aid, email, name, org):
        f = facts.get((week, aid, org))
        if f is None:
            f = facts[(week, aid, org)] = dict(week=week, account_id=aid, email=email, name=name,
                                               org=org, comments=0, chars=0, ai=0, post_merge=0,
                                               cls=set())
        return f

    # Comments and chars: grouped per day, so the org is resolved as of the day
    # written, and per path and anchor, so each group lands on one file.
    for week, aid, email, name, day, path, anchor_path, n, chars, ai, pm in db.execute(f"""
            SELECT x.iso_week, x.account_id, a.email, a.name, substr(x.written_at, 1, 10),
                   x.path, c.anchor_path, count(*), sum(x.chars), sum(x.is_ai), sum(x.after_close)
            FROM comments x {SCOPE}
            GROUP BY 1, 2, 5, 6, 7"""):
        if not keep(week):
            continue
        org = resolve(email, day)
        included, area = where(path, anchor_path)
        g = areas[(week, area, fold(org))]
        g["comments"] += n
        g["chars"] += chars
        if included:
            f = fact(week, aid, email, name, org)
            f["comments"] += n
            f["chars"] += chars
            f["ai"] += ai
            f["post_merge"] += pm
    # Reviewed CLs: per CL, in the week it closed, with the org as of the close.
    for week, closed, cl, aid, email, name, path, anchor_path in db.execute(f"""
            SELECT c.close_week, c.closed_at, x.change_number, x.account_id, a.email, a.name,
                   x.path, c.anchor_path
            FROM comments x {SCOPE} AND c.close_week IS NOT NULL
            GROUP BY x.change_number, x.account_id, x.path"""):
        if not keep(week):
            continue
        org = resolve(email, closed)
        included, area = where(path, anchor_path)
        areas[(week, area, fold(org))]["cls"].add(cl)
        if included:
            fact(week, aid, email, name, org)["cls"].add(cl)
    return list(facts.values()), areas


def summarize(data_dir=store.DATA_DIR, out_dir=os.path.join(ROOT, "summaries"), db_path=None,
              scope=None, metric="comments"):
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {sorted(METRICS)}")
    db = store.open_derived(data_dir, db_path)
    scope = scope or load_scope()
    resolve = OrgResolver()
    meta_kv = dict(db.execute("SELECT k, v FROM meta"))
    fetched = json.loads(meta_kv.get("fetched_weeks") or "[]")
    weeks = set(fetched) if fetched else None
    facts, areas = comment_facts(db, resolve, scope, weeks)

    folded = defaultdict(lambda: dict(reviewers=set(), cls=set(), comments=0, chars=0, ai=0,
                                      post_merge=0))
    for f in facts:
        g = folded[(f["week"], fold(f["org"]))]
        g["reviewers"].add(f["account_id"])
        g["cls"] |= f["cls"]
        for k in ("comments", "chars", "ai", "post_merge"):
            g[k] += f[k]
    # Totals per week. The reviewed-CLs share uses the sum of per-org CL counts
    # as its denominator (a CL reviewed by two orgs credits both), so shares sum to 1.
    totals = defaultdict(lambda: dict(cls=0, comments=0, chars=0))
    for (week, _), g in folded.items():
        t = totals[week]
        t["cls"] += len(g["cls"])
        t["comments"] += g["comments"]
        t["chars"] += g["chars"]

    def share(a, b):
        return round(a / b, 4) if b else None

    size = {"comments": lambda g: g["comments"], "cls": lambda g: len(g["cls"]),
            "chars": lambda g: g["chars"]}[metric]
    out = []
    for (week, org), g in sorted(folded.items(), key=lambda kv: (kv[0][0], -size(kv[1]), kv[0][1])):
        t = totals[week]
        row = dict(iso_week=week, org=org, share=None, reviewers=len(g["reviewers"]),
                   reviewed_cls=len(g["cls"]), comments=g["comments"], review_chars=g["chars"],
                   ai_comments=g["ai"], post_merge_comments=g["post_merge"],
                   share_cls=share(len(g["cls"]), t["cls"]),
                   share_comments=share(g["comments"], t["comments"]),
                   share_chars=share(g["chars"], t["chars"]))
        row["share"] = row[METRICS[metric]]
        out.append(row)

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
                headline_metric=metric, headline_column="share",
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
                weeks_rule="comments and review_chars count in the ISO week the comment was written; "
                           "reviewed_cls in the week the CL closed; reviewers = accounts credited with "
                           "any of these that week; weekly_totals is by close week",
                folded_into_other=sorted(FOLD_INTO_OTHER),
                org_rule="affiliations.json5 (dated, as of the day written, or the CL's close for "
                         "reviewed_cls) > other @chromium.org -> google.com > email domain",
                metric_notes="comments include self-declared AI comments from a reviewer's own account "
                             "(is_ai flag or autogenerated:* tag; that subset is ai_comments, a lower bound) "
                             "and post-merge comments (that subset is post_merge_comments); review_chars "
                             "exclude quoted '>' lines; reviewed_cls = closed CLs with an in-scope comment "
                             "from the org; votes don't count")
    with _atomic_open(os.path.join(out_dir, "org_weekly.json")) as fh:
        json.dump(dict(meta=meta, rows=out,
                       weekly_totals=[dict(zip(TOTALS_COLS, r)) for r in weekly]),
                  fh, indent=1)
    db.close()
    write_reviewers(facts, os.path.join(out_dir, REVIEWERS_FILE))
    write_areas(areas, scope, os.path.join(out_dir, AREAS_FILE))
    return out


def reviewer_weeks(facts):
    """Every reviewer's in-scope counts, per (week, account, org): the facts
    behind org_weekly, before the FOLD_INTO_OTHER fold (so the leaderboard can
    show gmail.com). Summed per (week, folded org) they reproduce org_weekly's
    reviewers, comments and review_chars exactly (not reviewed_cls: two
    reviewers can share a CL). A reviewer whose activity resolves to two orgs
    in one week gets one row per org.
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
    (`accounts`, `emails`: account id -> string) and orgs once, and each week
    is a list of [account_id, org index, comments, cls, chars] rows, one per
    line so weekly regenerations diff well."""
    names, weeks = reviewer_weeks(facts)
    # Gerrit account emails (public); accounts without one are bots and never
    # reach this table, but skip a missing email rather than write null.
    emails = {f["account_id"]: f["email"] for f in facts if f["email"]}
    orgs = sorted({r["org"] for people in weeks.values() for r in people})
    org_index = {o: i for i, o in enumerate(orgs)}
    meta = dict(generated_at=store.now_iso(), columns=REVIEWER_COLUMNS,
                fold_into_other=sorted(FOLD_INTO_OTHER),
                scope="every reviewer, one row per (week, account, org); same scope and weeks as "
                      "org_weekly.json (in-scope comments on human-owned CLs on main; comments and "
                      "chars by week written, reviewed CLs by week closed). org is an index into "
                      "orgs, resolved before the fold_into_other fold.")
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


def write_areas(areas, scope, path, limit=DIR_LIMIT):
    """area_weekly.json: comments, reviewed CLs and chars per (week, directory,
    org) over every comment, in scope or not, as a tree the web UI drills into
    (paths.dir_tree: the areas as roots, then the `limit` directories with the
    most comments and their ancestors).

    `nodes` lists [parent index or -1, label, included]: a root's label is its
    path ("chrome/", "third_party/blink/", "(no file)"), a child's is the part
    after its parent's path ("browser/"). Each week's rows are [node, org,
    comments, cls, chars] for the node's own bucket: comments on files directly
    in that directory, or in a directory below it that isn't kept. A node's
    total is the sum of its subtree's buckets, so children add up to their
    parent. cls counts (CL, bucket) pairs: a CL with comments in two directories
    counts in both. Orgs are folded like org_weekly."""
    totals = defaultdict(int)
    for (_, d, _), g in areas.items():
        totals[d] += g["comments"]
    nodes, bucket = dir_tree(totals, scope, limit)
    index = {d: i for i, (d, _) in enumerate(nodes)}
    buckets = defaultdict(lambda: dict(comments=0, chars=0, cls=set()))
    for (week, d, org), g in areas.items():
        b = buckets[(week, index[bucket(d)], org)]
        b["comments"] += g["comments"]
        b["chars"] += g["chars"]
        b["cls"] |= g["cls"]
    orgs = sorted({o for _, _, o in areas})
    org_index = {o: i for i, o in enumerate(orgs)}
    weeks = defaultdict(list)
    for (week, n, org), b in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        weeks[week].append([n, org_index[org], b["comments"], len(b["cls"]), b["chars"]])

    def included(d):
        return d != UNPLACED and (d == ROOT_FILES or scope.includes(d))
    out_nodes = [[-1 if p is None else index[p], d if p is None else d[len(p):], int(included(d))]
                 for d, p in nodes]
    meta = dict(generated_at=store.now_iso(), columns=["node", "org", "comments", "cls", "chars"],
                node_columns=["parent", "label", "included"], dir_limit=limit,
                path_rules=scope.describe(), unplaced=UNPLACED, root_files=ROOT_FILES,
                scope="non-owner, non-bot review comments on human-owned CLs on main, in scope or not: "
                      "comments and chars by week written, reviewed CLs by week closed. Roots are the "
                      "areas: the longest matching path_rules or config/paths.txt area prefix, else the "
                      "top-level directory; unplaced comments (no inline comment anywhere on their CL) "
                      "are their own root. Below a root, the dir_limit directories with the most "
                      "comments are kept; rows are each node's own bucket.")
    with _atomic_open(path) as fh:
        fh.write('{"meta": %s,\n "orgs": %s,\n "nodes": [' % (json.dumps(meta), json.dumps(orgs)))
        fh.write(",".join("\n  " + json.dumps(n, separators=(",", ":")) for n in out_nodes))
        fh.write('\n ],\n "weeks": {')
        fh.write(",".join('\n  %s: %s' % (json.dumps(w), json.dumps(rows, separators=(",", ":")))
                          for w, rows in sorted(weeks.items())))
        fh.write("\n }\n}\n")
