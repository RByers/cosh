"""Aggregate derived.sqlite into small summaries for the front end.

Review is measured from comments only (metric_version 5+): published comments
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

The author side has one metric, commits (docs/commits.md): human first-parent
commits on main (cosh/commits.py) that touch an in-scope file, in the ISO
week each landed, credited to the git author's org as of that day. authors:
distinct git author emails among them. Reviewer and author rows share
reviewer_weekly.json, keyed by Gerrit account (the git author's email, else
the CL owner).

Path scope: each comment is placed on a file (cosh/paths.py) and counts only
if config/paths.txt includes that file; a CL counts as reviewed only through
in-scope comments. A patchset-level comment is placed on its author's own
most-commented file on that CL; if the author left no inline comment there it
can't be placed and is outside the scope (metric_version 6). Accounts that
never left an inline comment are dropped everywhere, area_weekly included:
they are almost all spam and drive-by comments. org_weekly and reviewer_weekly cover the
scope; area_weekly covers every comment, so the web UI can show what the
scope leaves out.

In org_weekly every org is reported however few reviewers it has; only the
orgs in FOLD_INTO_OTHER (webmail domains, and the affiliations file's
"Undisclosed", which say nothing about an organization) are folded into
'Other'. Self-declared AI comments posted from a
reviewer's own account count (since metric_version 4); the subset is
ai_comments. Post-merge comments (written after the CL closed) count too; that
subset is post_merge_comments. Only fully fetched weeks are reported
(meta.fetched_weeks).

Outputs:
  summaries/org_weekly.json          one row per (week, org), in scope
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
  summaries/area_reviewers.json       comments per (week, tree node, org, reviewer),
                                      so the web UI can link each org's share of a
                                      directory to those reviewers' CLs on Gerrit
  summaries/author_weekly.json        one row per (week, author, org): commits, like
                                      reviewer_weekly (loaded only for the Commits metric)
  summaries/area_commits.json         commits per (week, tree node, org), and
  summaries/area_authors.json         per author too: the Commits metric's
                                      directory data, loaded only when it's chosen
"""

import contextlib
import csv
import hashlib
import json
import os
import sqlite3
from collections import defaultdict

from . import store
from .derive import METRIC_VERSION
from .orgs import OrgResolver
from .paths import DIR_LIMIT, ROOT_FILES, UNPLACED, anchor, dir_tree, directory, load_scope, place

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Orgs always folded into Other, whatever their size: personal webmail
# addresses are not an organization, and "Undisclosed" (affiliations.json5's
# marker for an unnamed employer) is not one either.
FOLD_INTO_OTHER = frozenset({"gmail.com", "Undisclosed"})
OTHER = "Other"
TOTALS_COLS = ["iso_week", "main_cls", "merged_cls", "abandoned_cls", "human_cls",
               "bot_cls", "human_cls_with_comments"]
METRICS = {"comments": "share_comments", "cls": "share_cls", "chars": "share_chars",
           "addressed": "share_addressed", "commits": "share_commits"}
REVIEWERS_FILE = "reviewer_weekly.json"
AUTHORS_FILE = "author_weekly.json"
AREAS_FILE = "area_weekly.json"
AREA_REVIEWERS_FILE = "area_reviewers.json"
AREA_COMMITS_FILE = "area_commits.json"
AREA_AUTHORS_FILE = "area_authors.json"
THREAD_EXAMPLES_FILE = "thread_examples.json"
CLASSIFIER_PROMPT_FILE = "classifier_prompt.json"   # the exact Haiku prompt, shown on the Value page
# How each reviewer-started thread was decided (the UI's thread-classification
# box), in display order.
THREAD_OUTCOMES = ["done_reply", "model_addressed", "model_not", "no_reply", "pending"]
EXAMPLE_OUTCOMES = ["done_reply", "model_addressed", "model_not", "no_reply"]
EXAMPLES_PER_OUTCOME = 3          # per classified week
EXAMPLE_WEEKS = 52                # the most recent classified weeks only
EXAMPLE_MESSAGES, EXAMPLE_CHARS = 8, 700
REVIEWER_COLUMNS = ["account_id", "org", "comments", "cls", "chars", "addressed"]
AUTHOR_COLUMNS = ["account_id", "org", "commits", "files"]

# Non-bot accounts on human-owned CLs on main. CROSS JOIN pins the join order
# (SQLite never reorders it): scan the comments, then look up the CL and the
# account by primary key.
SCOPE_JOINS = """CROSS JOIN changes c ON c.host = x.host AND c.change_number = x.change_number
           CROSS JOIN accounts a ON a.host = x.host AND a.account_id = x.account_id"""
SCOPE_WHERE = "WHERE a.is_bot = 0 AND c.is_bot_owned = 0 AND c.branch = 'main'"
SCOPE = SCOPE_JOINS + "\n" + SCOPE_WHERE

# Addressed points (cosh/classify.py): each comment's point, or NULL while it
# can't be decided yet (its thread needs a model label it doesn't have, or the
# DB predates threads). temp.lab holds the active classifier's labels.
POINT_JOINS = """LEFT JOIN threads t ON t.host = x.host AND t.change_number = x.change_number
                 AND t.root_uuid = x.root_uuid
           LEFT JOIN accounts ra ON ra.host = t.host AND ra.account_id = t.root_account
           LEFT JOIN temp.lab l ON l.change_number = t.change_number AND l.root_uuid = t.root_uuid
                 AND l.input_hash = t.input_hash"""
POINT = """CASE WHEN x.root_uuid IS NULL THEN NULL
                WHEN t.root_uuid IS NULL THEN 0
                WHEN t.last_owner_reply_at IS NULL OR x.written_at > t.last_owner_reply_at THEN 0
                WHEN t.regex_addressed = 1 THEN 1
                WHEN ra.is_bot = 1 THEN 0
                ELSE l.addressed END"""
# A week's addressed metric is shown only once this share of its comments is decided.
COVERAGE_COMPLETE = 0.99


def load_labels(db, data_dir):
    """Fill temp.lab from labels.sqlite's active classifier (empty if there is
    none). Returns the classifier's model id, or None."""
    from . import classify
    db.execute("CREATE TEMP TABLE IF NOT EXISTS lab (change_number INTEGER, root_uuid TEXT, input_hash INTEGER, "
               "addressed INTEGER, PRIMARY KEY (change_number, root_uuid, input_hash)) WITHOUT ROWID")
    db.execute("DELETE FROM temp.lab")
    path = classify.labels_path(data_dir)
    if not os.path.exists(path):
        return None
    ldb = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if not store.has_table(ldb, "classifiers"):
            return None
        active = classify.active_classifier(ldb)
        if not active:
            return None
        db.executemany("INSERT OR REPLACE INTO temp.lab VALUES (?,?,?,?)", ldb.execute(
            "SELECT change_number, root_uuid, input_hash, addressed FROM labels WHERE classifier_id = ?",
            (active[0],)))
        return active[1]
    finally:
        ldb.close()


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


def reviewer_anchors(db):
    """{(host, change_number, account_id): anchor}: the file each reviewer left
    the most inline comments on, per CL (ties: the alphabetically first path).
    Covers every CL and reviewer with at least one inline comment."""
    counts = defaultdict(dict)
    for host, cl, aid, path, n in db.execute("""
            SELECT host, change_number, account_id, path, count(*) FROM comments
            WHERE path != '' AND substr(path, 1, 1) != '/'
            GROUP BY 1, 2, 3, 4"""):
        counts[(host, cl, aid)][path] = n
    return {k: anchor(v) for k, v in counts.items()}


def comment_facts(db, resolve, scope, weeks=None, own=None):
    """Returns (facts, areas).

    facts: per-(week, reviewer, org) dicts with in-scope comments (and their
    ai and post_merge subsets), chars, and cls (the set of CLs closed that
    week that the reviewer commented on in scope).
    areas: {(week, directory, folded org): dict(comments, chars, cls, reviewers)},
    every comment, in scope or not (directory as from paths.directory);
    reviewers maps account id to comments; commits (empty here) is filled by
    commit_facts with commit id -> author account.
    `weeks`: the weeks to keep, or None for all.

    A patchset-level comment is placed on its author's own anchor on that CL
    (reviewer_anchors); one whose author left no inline comment there is
    unplaced. Accounts that never commented inline anywhere are skipped
    entirely (mostly spam and drive-by comments)."""
    own = reviewer_anchors(db) if own is None else own
    inline_authors = {(host, aid) for host, _, aid in own}
    facts = {}
    areas = defaultdict(lambda: dict(comments=0, chars=0, cls=set(), reviewers=defaultdict(int),
                                     addressed=0, pending=0, commits={}))
    keep = (lambda w: True) if weeks is None else weeks.__contains__
    cache = {}

    def where(path, own_anchor):
        key = (path, own_anchor)
        if key not in cache:
            p = place(path, own_anchor)
            cache[key] = (scope.includes(p), directory(p))
        return cache[key]

    def fact(week, aid, email, name, org):
        f = facts.get((week, aid, org))
        if f is None:
            f = facts[(week, aid, org)] = dict(week=week, account_id=aid, email=email, name=name,
                                               org=org, comments=0, chars=0, ai=0, post_merge=0,
                                               cls=set(), addressed=0, pending=0, commits=0, files=0)
        return f

    # Comments and chars: grouped per day, so the org is resolved as of the day
    # written, and per path and anchor, so each group lands on one file.
    for week, host, cl, aid, email, name, day, path, n, chars, ai, pm, addr, pend in db.execute(f"""
            SELECT x.iso_week, x.host, x.change_number, x.account_id, a.email, a.name,
                   substr(x.written_at, 1, 10), x.path,
                   count(*), sum(x.chars), sum(x.is_ai), sum(x.after_close),
                   total({POINT}), sum(({POINT}) IS NULL)
            FROM comments x {SCOPE_JOINS} {POINT_JOINS} {SCOPE_WHERE}
            GROUP BY 1, 2, 3, 4, 7, 8"""):
        if not keep(week) or (host, aid) not in inline_authors:
            continue
        org = resolve(email, day)
        included, area = where(path, own.get((host, cl, aid)))
        g = areas[(week, area, fold(org))]
        g["comments"] += n
        g["chars"] += chars
        g["reviewers"][aid] += n
        g["addressed"] += int(addr)
        g["pending"] += pend
        if included:
            f = fact(week, aid, email, name, org)
            f["comments"] += n
            f["chars"] += chars
            f["ai"] += ai
            f["post_merge"] += pm
            f["addressed"] += int(addr)
            f["pending"] += pend
    # Reviewed CLs: per CL, in the week it closed, with the org as of the close.
    for week, closed, host, cl, aid, email, name, path in db.execute(f"""
            SELECT c.close_week, c.closed_at, x.host, x.change_number, x.account_id, a.email, a.name,
                   x.path
            FROM comments x {SCOPE} AND c.close_week IS NOT NULL
            GROUP BY x.host, x.change_number, x.account_id, x.path"""):
        if not keep(week) or (host, aid) not in inline_authors:
            continue
        org = resolve(email, closed)
        included, area = where(path, own.get((host, cl, aid)))
        areas[(week, area, fold(org))]["cls"].add(cl)
        if included:
            fact(week, aid, email, name, org)["cls"].add(cl)
    return list(facts.values()), areas


def commit_facts(db, resolve, scope, facts, areas, weeks=None):
    """Adds the commits on main (cosh/commits.py) to comment_facts' results.

    Human commits only, each in the ISO week it landed, credited to its git
    author's org as of that day. A commit counts in scope (`facts`) if any
    file it touches is in scope; `areas` gets every commit, in each directory
    it touches (as reviewed CLs do). The author's Gerrit account is the one
    with the git author's email, else the CL owner's; a commit with neither
    still counts for its org but for no person. Facts and areas are updated
    in place; returns per-(week, folded org) {"commits": n, "authors": set}
    over in-scope commits, authors being emails."""
    keep = (lambda w: True) if weeks is None else weeks.__contains__
    by_email = {}
    names = {}
    for aid, email, name, bot in db.execute(
            "SELECT account_id, email, name, is_bot FROM accounts ORDER BY is_bot, account_id"):
        names[aid] = (email, name)
        if email:
            by_email.setdefault(email.lower(), aid)
    owner = dict(db.execute("SELECT change_number, owner_account FROM changes WHERE branch = 'main'"))
    index = {(f["week"], f["account_id"], f["org"]): f for f in facts}
    dirs_of = defaultdict(list)
    for cid, d in db.execute("""SELECT d.commit_id, d.dir FROM commit_dirs d
                                JOIN commits c ON c.commit_id = d.commit_id WHERE c.is_bot = 0"""):
        dirs_of[cid].append(d)
    included = {}
    out = defaultdict(lambda: dict(commits=0, authors=set()))
    for cid, cl, email, week, day, n_files in db.execute(
            "SELECT commit_id, change_number, author_email, iso_week, substr(landed_at, 1, 10), n_files "
            "FROM commits WHERE is_bot = 0"):
        if not keep(week):
            continue
        org = resolve(email, day)
        aid = by_email.get(email) or owner.get(cl)
        in_scope = False
        for d in dirs_of.get(cid, ()):
            if d not in included:
                included[d] = d == ROOT_FILES or scope.includes(d)
            in_scope |= included[d]
            areas[(week, d, fold(org))]["commits"][cid] = aid
        if not in_scope:
            continue
        o = out[(week, fold(org))]
        o["commits"] += 1
        o["authors"].add(email)
        if aid is None:
            continue
        f = index.get((week, aid, org))
        if f is None:
            gerrit_email, name = names.get(aid, (None, None))
            f = index[(week, aid, org)] = dict(week=week, account_id=aid, email=gerrit_email, name=name,
                                               org=org, comments=0, chars=0, ai=0, post_merge=0,
                                               cls=set(), addressed=0, pending=0, commits=0, files=0)
            facts.append(f)
        f["commits"] += 1
        f["files"] += n_files     # every file it changes, in scope or not: its size
    return out


def thread_breakdown(db, scope, own, weeks=None):
    """How the in-scope, reviewer-started threads of each week were decided.

    A thread belongs to the week its root comment was written, and is in
    scope if its root comment is (placed like comment_facts places
    comments). Returns ({week: {outcome: threads}}, {week: {outcome:
    [(sort key, host, cl, root_uuid, path)]}}): the second holds candidates
    for example threads."""
    inline_authors = {(host, aid) for host, _, aid in own}
    counts = defaultdict(lambda: dict.fromkeys(THREAD_OUTCOMES, 0))
    picks = defaultdict(lambda: defaultdict(list))
    keep = (lambda w: True) if weeks is None else weeks.__contains__
    cache = {}
    for week, host, cl, aid, path, root, no_reply, regex, label in db.execute(f"""
            SELECT x.iso_week, x.host, x.change_number, x.account_id, x.path, t.root_uuid,
                   t.last_owner_reply_at IS NULL, t.regex_addressed, l.addressed
            FROM threads t
            CROSS JOIN comments x ON x.host = t.host AND x.change_number = t.change_number
                 AND x.comment_id = t.root_uuid
            {SCOPE_JOINS}
            LEFT JOIN temp.lab l ON l.change_number = t.change_number AND l.root_uuid = t.root_uuid
                 AND l.input_hash = t.input_hash
            {SCOPE_WHERE}"""):
        if not keep(week) or (host, aid) not in inline_authors:
            continue
        key = (path, own.get((host, cl, aid)))
        if key not in cache:
            cache[key] = scope.includes(place(*key))
        if not cache[key]:
            continue
        outcome = ("no_reply" if no_reply else "done_reply" if regex else "pending" if label is None
                   else "model_addressed" if label else "model_not")
        counts[week][outcome] += 1
        if outcome in EXAMPLE_OUTCOMES:
            picks[week][outcome].append((hashlib.sha1(root.encode()).hexdigest(), host, cl, root, path))
    return dict(counts), picks


def write_thread_examples(data_dir, db, picks, weeks, path):
    """thread_examples.json: a few example threads per outcome for each
    classified week (lazily loaded by the UI's thread-classification box).
    Comment text is public Gerrit data (docs/plan.md, ground rule 3)."""
    from . import classify
    from .derive import load_comments, prefetch_notedb
    chosen = []
    for week in sorted(weeks)[-EXAMPLE_WEEKS:]:
        for outcome in EXAMPLE_OUTCOMES:
            for _, host, cl, root, fpath in sorted(picks.get(week, {}).get(outcome, []))[:EXAMPLES_PER_OUTCOME]:
                chosen.append((week, outcome, host, cl, root, fpath))
    out = []
    if chosen and os.path.exists(os.path.join(data_dir, "raw.sqlite")):
        raw = store.open_raw_ro(data_dir)
        repos = {}
        info = {}
        for host, cl in sorted({(c[2], c[3]) for c in chosen}):
            row = db.execute("SELECT owner_account, project FROM changes WHERE host = ? AND change_number = ?",
                             (host, cl)).fetchone()
            if row:
                info[(host, cl)] = row
        cls = sorted({(h, info[(h, n)][1], n) for _, _, h, n, _, _ in chosen if (h, n) in info})
        notes = prefetch_notedb(repos, cls, "auto")
        for week, outcome, host, cl, root, fpath in chosen:
            if (host, cl) not in info:
                continue
            owner, project = info[(host, cl)]
            comments, _ = load_comments(raw, repos, host, project, cl, "auto", notes)
            t = {x["root_id"]: x for x in classify.build_threads(comments, owner)}.get(root)
            if t is None:
                continue
            msgs = []
            for i, (_, aid, _, msg) in enumerate(t["items"][:EXAMPLE_MESSAGES]):
                role = "reviewer" if i == 0 or aid == t["root_account"] else "owner" if aid == owner else "other"
                text = msg.strip()
                msgs.append([role, text[:EXAMPLE_CHARS] + ("…" if len(text) > EXAMPLE_CHARS else "")])
            out.append(dict(week=week, outcome=outcome, cl=cl, root=root, path=fpath,
                            more=max(0, len(t["items"]) - EXAMPLE_MESSAGES), messages=msgs))
        raw.close()
    meta = dict(generated_at=store.now_iso(), outcomes=EXAMPLE_OUTCOMES, per_outcome=EXAMPLES_PER_OUTCOME,
                weeks=sorted(weeks)[-EXAMPLE_WEEKS:],
                note="example reviewer-started threads per classified week and outcome, chosen by a hash of "
                     "the root comment id (stable across runs); messages are [role, text], text cut at "
                     f"{EXAMPLE_CHARS} characters, at most {EXAMPLE_MESSAGES} messages; public Gerrit data")
    with _atomic_open(path) as fh:
        fh.write('{"meta": %s,\n "threads": [' % json.dumps(meta))
        fh.write(",".join("\n  " + json.dumps(t, ensure_ascii=False) for t in out))
        fh.write("\n ]\n}\n")


def summarize(data_dir=store.DATA_DIR, out_dir=os.path.join(ROOT, "summaries"), db_path=None,
              scope=None, metric="comments"):
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {sorted(METRICS)}")
    # open_derived creates a missing DB; summarizing one would write empty
    # summaries (and leave a stray empty file at a mistyped or moved path).
    path = db_path or os.path.join(data_dir, store.DERIVED_FILE)
    if not os.path.exists(path):
        raise SystemExit(f"no derived DB at {path}; build it with python3 -m cosh derive")
    db = store.open_derived(data_dir, db_path)
    scope = scope or load_scope()
    resolve = OrgResolver()
    meta_kv = dict(db.execute("SELECT k, v FROM meta"))
    fetched = json.loads(meta_kv.get("fetched_weeks") or "[]")
    weeks = set(fetched) if fetched else None
    classifier = load_labels(db, data_dir)
    own = reviewer_anchors(db)
    facts, areas = comment_facts(db, resolve, scope, weeks, own)
    commits = commit_facts(db, resolve, scope, facts, areas, weeks)
    threads, thread_picks = thread_breakdown(db, scope, own, weeks)

    folded = defaultdict(lambda: dict(reviewers=set(), cls=set(), comments=0, chars=0, ai=0,
                                      post_merge=0, addressed=0, pending=0))
    for f in facts:
        g = folded[(f["week"], fold(f["org"]))]
        if f["comments"] or f["cls"]:
            g["reviewers"].add(f["account_id"])
        g["cls"] |= f["cls"]
        for k in ("comments", "chars", "ai", "post_merge", "addressed", "pending"):
            g[k] += f[k]
    # Totals per week. The reviewed-CLs share uses the sum of per-org CL counts
    # as its denominator (a CL reviewed by two orgs credits both), so shares sum to 1.
    for key in commits:
        folded[key]       # orgs with commits but no review get a row too
    totals = defaultdict(lambda: dict(cls=0, comments=0, chars=0, addressed=0, pending=0, commits=0))
    for (week, org), g in folded.items():
        t = totals[week]
        t["cls"] += len(g["cls"])
        for k in ("comments", "chars", "addressed", "pending"):
            t[k] += g[k]
        t["commits"] += commits[(week, org)]["commits"] if (week, org) in commits else 0

    def share(a, b):
        return round(a / b, 4) if b else None

    size = {"comments": lambda g: g["comments"], "cls": lambda g: len(g["cls"]),
            "chars": lambda g: g["chars"], "addressed": lambda g: g["addressed"],
            "commits": lambda g: g["commits"]}[metric]
    for key, g in folded.items():
        c = commits.get(key)
        g["commits"], g["authors"] = (c["commits"], len(c["authors"])) if c else (0, 0)
    out = []
    for (week, org), g in sorted(folded.items(), key=lambda kv: (kv[0][0], -size(kv[1]), kv[0][1])):
        t = totals[week]
        row = dict(iso_week=week, org=org, share=None, reviewers=len(g["reviewers"]),
                   reviewed_cls=len(g["cls"]), comments=g["comments"], review_chars=g["chars"],
                   ai_comments=g["ai"], post_merge_comments=g["post_merge"],
                   addressed_comments=g["addressed"], pending_comments=g["pending"],
                   commits=g["commits"], authors=g["authors"],
                   share_cls=share(len(g["cls"]), t["cls"]),
                   share_comments=share(g["comments"], t["comments"]),
                   share_chars=share(g["chars"], t["chars"]),
                   share_addressed=share(g["addressed"], t["addressed"]),
                   share_commits=share(g["commits"], t["commits"]))
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
    with _atomic_open(os.path.join(out_dir, "weekly_totals.csv"), newline="") as fh:
        w = csv.writer(fh)
        w.writerow(TOTALS_COLS)
        w.writerows(weekly)
    all_weeks = sorted(weeks) if weeks is not None else sorted({k[0] for k in areas} | set(totals))
    # Share of each week's in-scope comments whose point is decided (regex,
    # label, or scoring nothing by rule). The UI shows the addressed metric
    # only for weeks at COVERAGE_COMPLETE or above.
    coverage = {w: round(1 - totals[w]["pending"] / totals[w]["comments"], 4)
                for w in all_weeks if totals[w]["comments"]}
    meta = dict(generated_at=store.now_iso(), weeks=all_weeks,
                headline_metric=metric, headline_column="share",
                metric_version=METRIC_VERSION,
                derived_metric_version=meta_kv.get("metric_version"),
                open_snapshot_at=meta_kv.get("open_snapshot_at"),
                scope="chromium/src branch main: merged, abandoned and open CLs; review comments by "
                      "non-owner, non-bot accounts on human-owned CLs (bot-owned CLs are counted only in "
                      "weekly_totals.csv)",
                path_rules=scope.describe(),
                path_rule="a comment is placed on its file; a patchset-level comment on the file its "
                          "author left the most inline comments on, on that CL; the longest matching "
                          "path_rules prefix decides, and paths matching none are included; "
                          "comments that can't be placed (the author left no inline comment on the "
                          "CL) are excluded (see area_weekly.json), and accounts that never "
                          "commented inline are left out everywhere",
                weeks_rule="comments and review_chars count in the ISO week the comment was written; "
                           "reviewed_cls in the week the CL closed; reviewers = accounts credited with "
                           "any of these that week; weekly_totals is by close week",
                folded_into_other=sorted(FOLD_INTO_OTHER),
                addressed=dict(
                    classifier=classifier, coverage=coverage, complete_at=COVERAGE_COMPLETE,
                    thread_outcomes=THREAD_OUTCOMES,
                    threads={w: [threads.get(w, {}).get(o, 0) for o in THREAD_OUTCOMES] for w in all_weeks
                             if w in threads},
                    rule="addressed_comments: comments in a reviewer-started thread that led the CL owner to "
                         "change the CL (the owner's first reply is Done-type, or a model label says so), "
                         "written no later than the owner's last reply in it; one point each to the "
                         "comment's author. Threads the owner never answered, or started, score nothing. "
                         "pending_comments: comments whose thread isn't classified yet; coverage = 1 - "
                         "pending / comments per week (docs/comment-classifier.md)"),
                commits=dict(
                    built_at=meta_kv.get("commits_built_at"),
                    rule="commits: human first-parent commits on main (local git clone, cosh/commits.py) "
                         "that touch at least one in-scope file, in the ISO week each landed (committer "
                         "date, UTC), credited to the git author's org as of that day; a commit is a "
                         "bot's if its CL is bot-owned. authors: distinct git author emails among them"),
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
    classified = [w for w in all_weeks if coverage.get(w, 0) >= COVERAGE_COMPLETE]
    write_thread_examples(data_dir, db, thread_picks, classified, os.path.join(out_dir, THREAD_EXAMPLES_FILE))
    from .classify import prompt_doc
    with _atomic_open(os.path.join(out_dir, CLASSIFIER_PROMPT_FILE)) as fh:
        json.dump(prompt_doc(), fh, indent=1)
        fh.write("\n")
    db.close()
    write_reviewers(facts, os.path.join(out_dir, REVIEWERS_FILE))
    write_authors(facts, os.path.join(out_dir, AUTHORS_FILE))
    area_meta = write_areas(areas, scope, os.path.join(out_dir, AREAS_FILE))
    write_area_reviewers(area_meta, os.path.join(out_dir, AREA_REVIEWERS_FILE))
    write_area_commits(area_meta, os.path.join(out_dir, AREA_COMMITS_FILE),
                       os.path.join(out_dir, AREA_AUTHORS_FILE))
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
        if not (f["comments"] or f["cls"]):
            continue                # a commit author only (author_weekly.json)
        aid = f["account_id"]
        names[aid] = f["name"] or (f["email"] or "").split("@")[0] or f"Account {aid}"
        weeks[f["week"]].append(dict(account_id=aid, org=f["org"], comments=f["comments"],
                                     cls=len(f["cls"]), chars=f["chars"], addressed=f["addressed"]))
    for people in weeks.values():
        people.sort(key=lambda r: (-r["comments"], -r["cls"], r["account_id"], r["org"]))
    return names, dict(sorted(weeks.items()))


def write_reviewers(facts, path):
    """Committed and published (derived from public Gerrit data, docs/plan.md
    ground rule 3). Compact: names and emails are listed once per account
    (`accounts`, `emails`: account id -> string) and orgs once, and each week
    is a list of [account_id, org index, comments, cls, chars, addressed] rows, one per
    line so weekly regenerations diff well."""
    names, weeks = reviewer_weeks(facts)
    # Gerrit account emails (public); accounts without one are bots and never
    # reach this table, but skip a missing email rather than write null.
    emails = {aid: e for aid, e in ((f["account_id"], f["email"]) for f in facts if f["comments"] or f["cls"])
              if e}
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
            fh.write(",".join("\n   [%d,%d,%d,%d,%d,%d]" % (r["account_id"], org_index[r["org"]], r["comments"],
                                                             r["cls"], r["chars"], r["addressed"])
                              for r in people))
            fh.write("\n  ]")
        fh.write("\n }\n}\n")


def write_authors(facts, path):
    """author_weekly.json: every commit author's in-scope commits per (week,
    account, org), like reviewer_weekly.json (same compact layout, Gerrit
    accounts and emails), with [account_id, org index, commits, files] rows,
    files being every file those commits change, in scope or not (the
    page's files per commit). Org is
    the git author's, before the fold_into_other fold. Separate from the
    reviewers, as most authors review little; the web UI loads it only for
    the Commits metric."""
    names, emails, weeks = {}, {}, defaultdict(list)
    for f in facts:
        if not f.get("commits"):
            continue
        aid = f["account_id"]
        names[aid] = f["name"] or (f["email"] or "").split("@")[0] or f"Account {aid}"
        if f["email"]:
            emails[aid] = f["email"]
        weeks[f["week"]].append((aid, f["org"], f["commits"], f["files"]))
    orgs = sorted({row[1] for rows in weeks.values() for row in rows})
    org_index = {o: i for i, o in enumerate(orgs)}
    meta = dict(generated_at=store.now_iso(), columns=AUTHOR_COLUMNS,
                fold_into_other=sorted(FOLD_INTO_OTHER),
                scope="every commit author, one row per (week, account, org): human commits on main "
                      "touching an in-scope file, by week landed, with the git author's org (before "
                      "the fold_into_other fold). The account is the Gerrit account with the git "
                      "author's email, else the CL owner's. files: every file those commits change, "
                      "in scope or not.")
    with _atomic_open(path) as fh:
        fh.write('{"meta": %s,\n "orgs": %s,\n "accounts": {' % (json.dumps(meta), json.dumps(orgs)))
        fh.write(",".join('\n  "%d": %s' % (aid, json.dumps(names[aid], ensure_ascii=False))
                          for aid in sorted(names)))
        fh.write('\n },\n "emails": {')
        fh.write(",".join('\n  "%d": %s' % (aid, json.dumps(emails[aid], ensure_ascii=False))
                          for aid in sorted(emails)))
        fh.write('\n },\n "weeks": {')
        for i, (week, rows) in enumerate(sorted(weeks.items())):
            rows.sort(key=lambda r: (-r[2], r[0], r[1]))
            fh.write('%s\n  %s: [' % ("," if i else "", json.dumps(week)))
            fh.write(",".join("\n   [%d,%d,%d,%d]" % (aid, org_index[org], n, k) for aid, org, n, k in rows))
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
    counts in both. Orgs are folded like org_weekly. Commits per bucket go in
    a file of their own (write_area_commits): they touch many more
    directories than comments do, and only the Commits metric needs them."""
    totals = defaultdict(int)
    for (_, d, _), g in areas.items():
        totals[d] += g["comments"]   # directories with only commits are listed too, ranked last
    nodes, bucket = dir_tree(totals, scope, limit)
    index = {d: i for i, (d, _) in enumerate(nodes)}
    buckets = defaultdict(lambda: dict(comments=0, chars=0, cls=set(), reviewers=defaultdict(int), addressed=0,
                                       commits={}))
    for (week, d, org), g in areas.items():
        b = buckets[(week, index[bucket(d)], org)]
        b["comments"] += g["comments"]
        b["chars"] += g["chars"]
        b["addressed"] += g["addressed"]
        b["cls"] |= g["cls"]
        for aid, n in g["reviewers"].items():
            b["reviewers"][aid] += n
        b["commits"].update(g.get("commits", {}))   # commit id -> author account (or None)
    orgs = sorted({o for _, _, o in areas})
    org_index = {o: i for i, o in enumerate(orgs)}
    weeks = defaultdict(list)
    for (week, n, org), b in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        if b["comments"] or b["cls"]:
            weeks[week].append([n, org_index[org], b["comments"], len(b["cls"]), b["chars"], b["addressed"]])

    def included(d):
        return d != UNPLACED and (d == ROOT_FILES or scope.includes(d))
    out_nodes = [[-1 if p is None else index[p], d if p is None else d[len(p):], int(included(d))]
                 for d, p in nodes]
    meta = dict(generated_at=store.now_iso(),
                columns=["node", "org", "comments", "cls", "chars", "addressed"],
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
    return dict(buckets=buckets, org_index=org_index, generated_at=meta["generated_at"])


def write_area_reviewers(area_meta, path):
    """area_reviewers.json: who wrote the comments of each (week, node, org)
    bucket of area_weekly.json (`area_meta`, from write_areas), with that
    file's node and org indexes; `areas_generated_at` names the
    area_weekly.json it goes with. Rows are [node, org, account id, comments,
    account id, comments, ...], most comments first, so the web UI can link an
    org's share of a directory (its subtree's buckets) to those reviewers'
    CLs on Gerrit. A separate file because it's several times the size of
    area_weekly.json and only the links need it."""
    org_index = area_meta["org_index"]
    weeks = defaultdict(list)
    for (week, node, org), b in sorted(area_meta["buckets"].items()):
        if not b["reviewers"]:
            continue
        row = [node, org_index[org]]
        for aid, n in sorted(b["reviewers"].items(), key=lambda kv: (-kv[1], kv[0])):
            row += [aid, n]
        weeks[week].append(row)
    meta = dict(generated_at=store.now_iso(), areas_generated_at=area_meta["generated_at"],
                columns="[node, org, account_id, comments, account_id, comments, ...]",
                scope="area_weekly.json's comment buckets (by week written) split by reviewer; node "
                      "and org are indexes into area_weekly.json's nodes and orgs")
    compact = dict(separators=(",", ":"))
    with _atomic_open(path) as fh:
        fh.write('{"meta": %s,\n "weeks": {' % json.dumps(meta))
        fh.write(",".join('\n  %s: [%s]' % (json.dumps(w), ",".join(json.dumps(r, **compact) for r in rows))
                          for w, rows in sorted(weeks.items())))
        fh.write("\n }\n}\n")


def write_area_commits(area_meta, commits_path, authors_path):
    """The commits of each (week, node, org) bucket of area_weekly.json
    (`area_meta`, from write_areas), in its node and org indexes:
    area_commits.json has [node, org, commits] rows, a commit counting once
    in each bucket it touches; area_authors.json splits them by author like
    area_reviewers.json ([node, org, account id, commits, ...]), for the
    directory charts' Gerrit links. Both name the area_weekly.json they go
    with (`areas_generated_at`); the web UI loads them only for the Commits
    metric."""
    org_index = area_meta["org_index"]
    counts, authors = defaultdict(list), defaultdict(list)
    for (week, node, org), b in sorted(area_meta["buckets"].items()):
        if not b["commits"]:
            continue
        counts[week].append([node, org_index[org], len(b["commits"])])
        people = defaultdict(int)
        for aid in b["commits"].values():
            if aid is not None:
                people[aid] += 1
        if people:
            row = [node, org_index[org]]
            for aid, n in sorted(people.items(), key=lambda kv: (-kv[1], kv[0])):
                row += [aid, n]
            authors[week].append(row)
    compact = dict(separators=(",", ":"))
    for path, weeks, columns, scope in (
            (commits_path, counts, "[node, org, commits]",
             "human commits on main per area_weekly.json bucket, by week landed and the git "
             "author's org; a commit counts once in each bucket it touches, in scope or not"),
            (authors_path, authors, "[node, org, account_id, commits, account_id, commits, ...]",
             "area_commits.json's buckets split by author (Gerrit account: the git author's "
             "email, else the CL owner)")):
        meta = dict(generated_at=store.now_iso(), areas_generated_at=area_meta["generated_at"],
                    columns=columns, scope=scope + "; node and org are indexes into "
                                                   "area_weekly.json's nodes and orgs")
        with _atomic_open(path) as fh:
            fh.write('{"meta": %s,\n "weeks": {' % json.dumps(meta))
            fh.write(",".join('\n  %s: %s' % (json.dumps(w), json.dumps(rows, **compact))
                              for w, rows in sorted(weeks.items())))
            fh.write("\n }\n}\n")
